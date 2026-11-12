"""Sucht die Ziffernrahmen des Fehlwurfzaehlers am Bild -- MESSUNG.

Das Ablesen am Gitter hat auf drei von vier Bahnen danebengelegen (gelesen
wurden 3, 6, 3 statt 0). Bei rund 12 px Ziffernbreite entscheiden ein bis zwei
Pixel darueber, ob ein Segment in seiner Messflaeche liegt.

Deshalb hier eine Suche ueber kleine Verschiebungen und Groessen. Der Massstab
ist der IM BILD ABLESBARE Wert: Die Anzeige steht in allen geprueften Frames
auf `00`, der Leser muss also 0 liefern.

ABGRENZUNG zu einem frueheren Fehlschlag: Es wird NICHT auf hoechste Confidence
optimiert. Die misst die Schaerfe des Mustertreffers, nicht die Richtigkeit --
auf sie ausgerichtet wurde aus einer "001" eine "081". Hier ist der Sollwert
bekannt und von aussen gegeben.

Aufruf:
    .venv/Scripts/python.exe tools/fit_left_display.py [LAUFORDNER]
"""

from __future__ import annotations

import glob
import itertools
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

QUELLE = Path("data/calibrations/kalibrierung_2026-08-29_1227.json")
ZIEL = Path("data/calibrations/kalibrierung_2026-08-29_fehlwurf.json")
LAUF = ("debug/manifest-oci-us-ashburn-1-vop1.edgemv.mux.com_rendition.m3u8/"
        "lauf_2026-08-29_12-31-46")

SOLL = 0            # die Anzeige steht in allen Bildern auf 00
FRAMES = 40         # je Bahn geprueft

# Ausgangswerte aus dem Gitter -- die Suche geht davon aus.
BASIS: dict[int, dict[int, list[float]]] = {
    1: {1: [0.181, 0.720, 0.059, 0.104], 2: [0.251, 0.720, 0.056, 0.104]},
    2: {1: [0.184, 0.722, 0.053, 0.096], 2: [0.251, 0.722, 0.053, 0.096]},
    3: {1: [0.178, 0.724, 0.054, 0.099], 2: [0.246, 0.724, 0.054, 0.099]},
    4: {1: [0.188, 0.712, 0.056, 0.105], 2: [0.256, 0.712, 0.056, 0.105]},
}

DX = (-0.010, -0.006, -0.003, 0.0, 0.003, 0.006, 0.010)
DY = (-0.010, -0.006, -0.003, 0.0, 0.003, 0.006, 0.010)
DW = (-0.006, -0.003, 0.0, 0.003, 0.006)
DH = (-0.008, 0.0, 0.008)


def leinwaende(ordner: Path, lane, anzahl: int) -> list[np.ndarray]:
    """Tafelausschnitte an ihrer Originalstelle in einem Vollframe."""
    xs = [p[0] for p in lane.quad]
    ys = [p[1] for p in lane.quad]
    x0, y0 = int(min(xs)), int(min(ys))
    bilder = sorted(glob.glob(str(ordner / f"lane_{lane.lane_id}"
                                  / "event_*" / "*_tafel.png")))[-anzahl:]
    ergebnis = []
    for pfad in bilder:
        tafel = cv2.imread(pfad)
        if tafel is None:
            continue
        h, w = tafel.shape[:2]
        if y0 + h > 1080 or x0 + w > 1920:
            continue
        leinwand = np.zeros((1080, 1920, 3), dtype=np.uint8)
        leinwand[y0:y0 + h, x0:x0 + w] = tafel
        ergebnis.append(leinwand)
    return ergebnis


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    ordner = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(LAUF)

    from kegel_cv.analysis.lane_processor import LaneProcessor
    from kegel_cv.calibration import Calibration
    from kegel_cv.config import load_config
    from kegel_cv.video.source import Frame

    cfg = load_config()
    daten = json.loads(QUELLE.read_text(encoding="utf-8"))
    beste: dict[int, dict[int, list[float]]] = {}

    for lane_daten in daten["lanes"]:
        bahn = lane_daten["lane_id"]
        basis = BASIS.get(bahn)
        if basis is None:
            continue

        cal = Calibration.load(QUELLE)
        lane = cal.get_lane(bahn)
        frames = [Frame(i, 0.0, bild)
                  for i, bild in enumerate(leinwaende(ordner, lane, FRAMES))]
        if not frames:
            print(f"Bahn {bahn}: keine Bilder")
            continue

        ergebnisse = []
        for dx, dy, dw, dh in itertools.product(DX, DY, DW, DH):
            probe = json.loads(json.dumps(lane_daten))
            probe["rois"] = [r for r in probe["rois"]
                             if not r["name"].startswith("digit_left_display_")]
            for nummer, rect in basis.items():
                probe["rois"].append({
                    "name": f"digit_left_display_{nummer}",
                    "rect": [rect[0] + dx, rect[1] + dy,
                             rect[2] + dw, rect[3] + dh],
                    "enabled": True, "pin_number": None})

            from kegel_cv.calibration.model import LaneCalibration
            p = LaneProcessor(LaneCalibration(**probe), cfg)
            if not p.prepare((1080, 1920, 3)):
                continue
            werte = []
            for frame in frames:
                lesung = p.read_digits(frame).get("left_display")
                if lesung is not None and lesung.is_readable:
                    werte.append(lesung.value)
            treffer = sum(1 for w in werte if w == SOLL)
            ergebnisse.append((treffer, len(werte), dx, dy, dw, dh,
                               dict(Counter(werte).most_common(3))))

        ergebnisse.sort(key=lambda e: (-e[0], -e[1]))
        treffer, lesbar, dx, dy, dw, dh, verteilung = ergebnisse[0]
        print(f"Bahn {bahn}: bester Treffer {treffer}/{len(frames)} "
              f"(lesbar {lesbar})  dx={dx:+.3f} dy={dy:+.3f} "
              f"dw={dw:+.3f} dh={dh:+.3f}   {verteilung}")
        beste[bahn] = {n: [r[0] + dx, r[1] + dy, r[2] + dw, r[3] + dh]
                       for n, r in basis.items()}

    # --- Ergebnis schreiben ---
    for lane_daten in daten["lanes"]:
        stellen = beste.get(lane_daten["lane_id"])
        if stellen is None:
            continue
        lane_daten["rois"] = [r for r in lane_daten["rois"]
                              if not r["name"].startswith("digit_left_display_")]
        for roi in lane_daten["rois"]:
            if roi["name"] == "left_display":
                roi["enabled"] = True
        for nummer, rect in stellen.items():
            lane_daten["rois"].append({
                "name": f"digit_left_display_{nummer}",
                "rect": [round(v, 4) for v in rect],
                "enabled": True, "pin_number": None})

    ZIEL.write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"\nGeschrieben: {ZIEL}")
    print("\nGefundene Rahmen:")
    for bahn, stellen in sorted(beste.items()):
        for nummer, rect in sorted(stellen.items()):
            print(f"   Bahn {bahn} Stelle {nummer}: "
                  f"{[round(v, 4) for v in rect]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
