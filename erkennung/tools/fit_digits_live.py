"""Passt alle Ziffernrahmen einer laufenden Aufnahme ein -- MESSUNG.

Am Spieltag stellte sich heraus, dass KEIN Ziffernfeld stellenweise eingerahmt
war ("4 Ziffernfelder, 0 davon stellenweise"). Alle liefen ueber den
Gesamtfeld-Leser, der am Material 0/12 bis 7/12 erreicht -- die kalibrierten
Stellen erreichen 59/70. Folgen: Die Summenanzeige war nie lesbar, und die
Neun wurde 35-mal als Vier gelesen (die Anlage zeichnet sie ohne unteren
Balken, siehe BUG-009 -- das Alternativmuster kennt nur der kalibrierte Leser).

Eingepasst wird gegen eine Wahrheit, die NICHT aus dem jeweiligen Feld stammt:

    pin_count      die Kegelzahl der LAMPEN (unabhaengige Quelle)
    total_b        die laufende Summe vor diesem Wurf (die Anzeige hinkt
                   einen Wurf hinterher, BUG-010)
    throw_number   die Wurfnummer aus dem Lauf

ABGRENZUNG zu einem frueheren Fehlschlag: Es wird NICHT auf hoechste Confidence
optimiert. Die misst die Schaerfe des Mustertreffers, nicht die Richtigkeit --
auf sie ausgerichtet wurde aus einer "001" eine "081".

Aufruf:
    .venv/Scripts/python.exe tools/fit_digits_live.py [LAUFORDNER]
"""

from __future__ import annotations

import csv
import glob
import itertools
import json
import logging
import re
import sys
from pathlib import Path

import cv2
import numpy as np

QUELLE = Path("data/calibrations/kalibrierung_2026-08-29_fehlwurf.json")
ZIEL = Path("data/calibrations/kalibrierung_2026-08-29_komplett.json")
LAUF = ("debug/manifest-oci-us-ashburn-1-vop1.edgemv.mux.com_rendition.m3u8/"
        "lauf_2026-08-29_12-31-46")

# Feld -> (Stellenzahl, wie die Sollziffern aus einer Wurfzeile entstehen)
FELDER = {
    "pin_count": 1,
    "throw_number": 3,
    "total_b": 4,
}

DX = (-0.010, -0.006, -0.003, 0.0, 0.003, 0.006, 0.010)
DY = (-0.010, -0.006, -0.003, 0.0, 0.003, 0.006, 0.010)
DW = (-0.005, 0.0, 0.005)
DH = (-0.008, 0.0, 0.008)

HOECHSTENS = 40          # Ereignisse je Bahn


def soll_ziffern(zeile: dict, feld: str) -> str | None:
    """Sollwert eines Feldes fuer diesen Wurf, als Ziffernkette."""
    try:
        kegel = int(zeile["Kegel"])
        summe = int(zeile["LaufendeSumme"])
        nummer = int(zeile["Wurfnummer"])
    except (ValueError, KeyError):
        return None
    if feld == "pin_count":
        return str(kegel)
    if feld == "throw_number":
        return f"{nummer:03d}"
    if feld == "total_b":
        # Die Anlage traegt das Ergebnis erst spaeter ein -- zum Zeitpunkt
        # GREEN_OFF steht dort der Stand VOR diesem Wurf.
        return f"{summe - kegel:04d}"
    return None


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    ordner = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(LAUF)

    from kegel_cv.calibration import Calibration
    from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox
    from kegel_cv.config import load_config
    from kegel_cv.detection.digit_reader import CalibratedDigitReader

    cfg = load_config()
    leser = CalibratedDigitReader(cfg.detection.digits)
    cal = Calibration.load(QUELLE)
    daten = json.loads(QUELLE.read_text(encoding="utf-8"))

    # Wurfzeilen je Bahn
    zeilen = list(csv.DictReader((ordner / "wuerfe.csv").open(encoding="utf-8-sig"),
                                 delimiter=";"))
    je_bahn: dict[int, list[dict]] = {}
    for z in zeilen:
        je_bahn.setdefault(int(z["Bahn"]), []).append(z)

    gefunden: dict[int, dict[str, list[list[float]]]] = {}

    for lane in cal.lanes:
        bahn = lane.lane_id
        transform = lane.transform(440, 530)
        xs = [p[0] for p in lane.quad]
        ys = [p[1] for p in lane.quad]
        x0, y0 = int(min(xs)), int(min(ys))

        # Ereignisbilder nach Frame-Nummer, damit sie sich den Wuerfen zuordnen
        bilder: dict[int, np.ndarray] = {}
        for pfad in glob.glob(str(ordner / f"lane_{bahn}" / "event_*" / "*_tafel.png")):
            treffer = re.search(r"frame_(\d+)", pfad)
            if treffer:
                bilder[int(treffer.group(1))] = None       # erst spaeter laden
        proben: list[tuple[np.ndarray, dict]] = []
        for z in je_bahn.get(bahn, [])[-HOECHSTENS:]:
            frame_nr = int(z["Frame"])
            kandidaten = [p for p in glob.glob(
                str(ordner / f"lane_{bahn}" / "event_*" / f"*frame_{frame_nr:06d}*_tafel.png"))]
            if not kandidaten:
                continue
            tafel = cv2.imread(kandidaten[0])
            if tafel is None:
                continue
            h, w = tafel.shape[:2]
            if y0 + h > 1080 or x0 + w > 1920:
                continue
            leinwand = np.zeros((1080, 1920, 3), dtype=np.uint8)
            leinwand[y0:y0 + h, x0:x0 + w] = tafel
            proben.append((leinwand, z))

        if not proben:
            print(f"Bahn {bahn}: keine zuordenbaren Ereignisbilder")
            continue
        print(f"\nBahn {bahn}: {len(proben)} Ereignisse")
        gefunden[bahn] = {}

        for feld, stellen in FELDER.items():
            roi = lane.get_roi(feld)
            if roi is None:
                print(f"   {feld}: kein Gesamtfeld in der Kalibrierung")
                continue
            fx, fy, fw, fh = roi.rect
            # Ausgangslage: gleichmaessig geteiltes Gesamtfeld. Das trifft die
            # Ziffergrenzen NICHT genau (gemessen) -- es ist nur der Startpunkt
            # der Suche, nicht das Ergebnis.
            breite = fw / stellen
            ergebnis_stellen = []

            for i in range(stellen):
                basis = (fx + i * breite, fy, breite, fh)
                sollwerte = []
                for leinwand, z in proben:
                    soll = soll_ziffern(z, feld)
                    if soll is not None and len(soll) == stellen:
                        sollwerte.append((leinwand, soll[i]))
                if not sollwerte:
                    ergebnis_stellen.append(list(basis))
                    continue

                bestes = (-1, 0, basis)
                for dx, dy, dw, dh in itertools.product(DX, DY, DW, DH):
                    rect = (basis[0] + dx, basis[1] + dy,
                            basis[2] + dw, basis[3] + dh)
                    if rect[2] <= 0 or rect[3] <= 0:
                        continue
                    box = norm_rect_to_frame_bbox(transform, rect, (1080, 1920, 3))
                    bx, by, bw_, bh_ = box
                    treffer = lesbar = 0
                    for leinwand, ziffer in sollwerte:
                        patch = leinwand[by:by + bh_, bx:bx + bw_]
                        if patch.size == 0:
                            continue
                        gelesen, _ = leser.read_digit(patch)
                        if gelesen and gelesen != "?":
                            lesbar += 1
                            if gelesen == ziffer:
                                treffer += 1
                    if (treffer, lesbar) > (bestes[0], bestes[1]):
                        bestes = (treffer, lesbar, rect)

                treffer, lesbar, rect = bestes
                anteil = 100 * treffer / max(1, len(sollwerte))
                print(f"   {feld} Stelle {i+1}: {treffer}/{len(sollwerte)} "
                      f"({anteil:.0f} %)  {[round(v, 4) for v in rect]}")
                ergebnis_stellen.append([round(v, 4) for v in rect])

            gefunden[bahn][feld] = ergebnis_stellen

    # --- Schreiben ---
    for lane_daten in daten["lanes"]:
        felder = gefunden.get(lane_daten["lane_id"])
        if not felder:
            continue
        for feld, stellen in felder.items():
            lane_daten["rois"] = [r for r in lane_daten["rois"]
                                  if not r["name"].startswith(f"digit_{feld}_")]
            for i, rect in enumerate(stellen, 1):
                lane_daten["rois"].append({
                    "name": f"digit_{feld}_{i}", "rect": rect,
                    "enabled": True, "pin_number": None})

    ZIEL.write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"\nGeschrieben: {ZIEL}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
