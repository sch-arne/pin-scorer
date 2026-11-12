"""Findet die Ziffernstellen direkt im Bild -- unabhaengig von den Rahmen.

Am Spieltag zeigte sich: Die von Hand gesetzten GESAMTFELD-Rahmen sitzen selbst
daneben (zu hoch, seitlich versetzt). Eine Suche, die von ihnen ausgeht, sucht
vom falschen Startpunkt -- gemessen 0 bis 2 % Treffer.

Deshalb hier der umgekehrte Weg: Die Anzeigen sind helle rote Ziffern auf
schwarzem Grund. Ueber ein Spaltenprofil der roten Pixel lassen sich die
Ziffergruppen finden, ohne irgendeine Vorannahme ueber ihre Lage.

Die untere Reihe traegt drei Gruppen: Wurfnummer (3), Kegelzahl (1), Summe (4).
Sie werden ueber ihre Reihenfolge und die Luecken dazwischen zugeordnet.

Geprueft wird anschliessend gegen unabhaengige Groessen: die Kegelzahl gegen
die LAMPEN, die Summe gegen den laufenden Punktestand.

Aufruf:
    .venv/Scripts/python.exe tools/find_digits_live.py [LAUFORDNER]
"""

from __future__ import annotations

import csv
import glob
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

# Suchbereich fuer die untere Reihe, in normierten Tafelkoordinaten.
# Grosszuegig -- die genaue Lage wird ja gerade gesucht.
UNTEN = (0.05, 0.83, 0.90, 0.14)
RAND = 0.004        # Zugabe je Seite, wie beim Einrahmen von Hand


def rote_maske(bild: np.ndarray) -> np.ndarray:
    """Leuchtende Ziffern: deutlich rot und deutlich hell."""
    b = bild[:, :, 0].astype(int)
    r = bild[:, :, 2].astype(int)
    return (r > 110) & (r - b > 45)


def gruppen(profil: np.ndarray, mindestens: int = 1) -> list[tuple[int, int]]:
    """Zusammenhaengende Bereiche mit Signal."""
    aktiv = profil >= mindestens
    bereiche, start = [], None
    for i, an in enumerate(aktiv):
        if an and start is None:
            start = i
        elif not an and start is not None:
            bereiche.append((start, i - 1))
            start = None
    if start is not None:
        bereiche.append((start, len(aktiv) - 1))
    return bereiche


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    ordner = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(LAUF)

    from kegel_cv.calibration import Calibration
    from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox

    cal = Calibration.load(QUELLE)
    daten = json.loads(QUELLE.read_text(encoding="utf-8"))
    ergebnis: dict[int, dict[str, list[list[float]]]] = {}

    for lane in cal.lanes:
        bahn = lane.lane_id
        transform = lane.transform(440, 530)
        xs = [p[0] for p in lane.quad]
        ys = [p[1] for p in lane.quad]
        x0, y0 = int(min(xs)), int(min(ys))

        bilder = sorted(glob.glob(str(ordner / f"lane_{bahn}"
                                      / "event_*" / "*_tafel.png")))
        if not bilder:
            print(f"Bahn {bahn}: keine Bilder")
            continue

        # Ueber viele Bilder summieren: Eine einzelne Anzeige zeigt nicht alle
        # Stellen (fuehrende Nullen leuchten, aber eine "1" ist schmal). Das
        # Maximum ueber viele Frames zeigt die volle Ausdehnung jeder Stelle.
        sammel = None
        for pfad in bilder[-60:]:
            tafel = cv2.imread(pfad)
            if tafel is None:
                continue
            h, w = tafel.shape[:2]
            if y0 + h > 1080 or x0 + w > 1920:
                continue
            leinwand = np.zeros((1080, 1920, 3), dtype=np.uint8)
            leinwand[y0:y0 + h, x0:x0 + w] = tafel
            bx, by, bw, bh = norm_rect_to_frame_bbox(transform, UNTEN,
                                                     (1080, 1920, 3))
            aus = leinwand[by:by + bh, bx:bx + bw]
            if aus.size == 0:
                continue
            maske = rote_maske(aus).astype(np.uint16)
            sammel = maske if sammel is None else sammel + maske

        if sammel is None:
            print(f"Bahn {bahn}: kein auswertbarer Ausschnitt")
            continue

        hoehe, breite = sammel.shape
        schwelle = max(1, int(sammel.max() * 0.15))
        spalten = (sammel >= schwelle).sum(axis=0)
        zeilen_profil = (sammel >= schwelle).sum(axis=1)

        senkrecht = gruppen(zeilen_profil, mindestens=max(1, breite // 20))
        if not senkrecht:
            print(f"Bahn {bahn}: keine Ziffernzeile gefunden")
            continue
        oben, unten = max(senkrecht, key=lambda g: g[1] - g[0])

        # Einzelne Ziffern verschmelzen: Bei rund 11 px Ziffernbreite liegen
        # die Luecken INNERHALB einer Gruppe unter einem Pixel. Getrennt wird
        # deshalb an den beiden GROESSTEN Luecken -- das sind die Abstaende
        # zwischen Wurfnummer, Kegelzahl und Summe. Innerhalb einer Gruppe
        # wird nach Stellenzahl gleichmaessig geteilt; anders als bei einem von
        # Hand gezogenen Rahmen ist hier die Tintenausdehnung exakt bekannt.
        tinte = spalten >= max(1, hoehe // 8)
        if not tinte.any():
            print(f"Bahn {bahn}: keine Ziffern gefunden")
            continue

        # Winzige Flecken am Rand ausblenden. GEMESSEN: Auf drei von vier
        # Bahnen lag links ein Fragment von 2 bis 4 px -- schmaler als jede
        # Ziffer (rund 10 px). Als Gruppe gezaehlt verschob es die Suche nach
        # den groessten Luecken und machte die Zuordnung unbrauchbar.
        mindestbreite = max(4, breite // 40)
        for a, b in gruppen(tinte.astype(int)):
            if b - a + 1 < mindestbreite:
                tinte[a:b + 1] = False
        if not tinte.any():
            print(f"Bahn {bahn}: nach dem Filtern nichts uebrig")
            continue

        erste = int(np.argmax(tinte))
        letzte = len(tinte) - 1 - int(np.argmax(tinte[::-1]))

        luecken = [(a, b) for a, b in gruppen((~tinte).astype(int))
                   if erste < a and b < letzte]
        luecken.sort(key=lambda g: g[1] - g[0], reverse=True)
        if len(luecken) < 2:
            print(f"Bahn {bahn}: nur {len(luecken)} Luecke(n) -- "
                  f"Gruppen nicht trennbar")
            continue
        trenner = sorted(luecken[:2], key=lambda g: g[0])
        waagerecht = [
            (erste, trenner[0][0] - 1),
            (trenner[0][1] + 1, trenner[1][0] - 1),
            (trenner[1][1] + 1, letzte),
        ]
        print(f"Bahn {bahn}: Zeile {oben}..{unten} px, Gruppen "
              f"{[(a, b, b - a + 1) for a, b in waagerecht]}")

        # px -> normiert. Der Ausschnitt beginnt bei UNTEN.
        def nx(px: float) -> float:
            return UNTEN[0] + px / breite * UNTEN[2]

        def ny(py: float) -> float:
            return UNTEN[1] + py / hoehe * UNTEN[3]

        y_oben, y_unten = ny(oben), ny(unten + 1)

        def teilen(bereich: tuple[int, int], stellen: int) -> list[list[float]]:
            a, b = bereich
            schritt = (b + 1 - a) / stellen
            return [[nx(a + i * schritt) - RAND, y_oben - RAND,
                     nx(a + (i + 1) * schritt) - nx(a + i * schritt) + 2 * RAND,
                     y_unten - y_oben + 2 * RAND]
                    for i in range(stellen)]

        ergebnis[bahn] = {
            "throw_number": teilen(waagerecht[0], 3),
            "pin_count": teilen(waagerecht[1], 1),
            "total_b": teilen(waagerecht[2], 4),
        }
        for feld, rects in ergebnis[bahn].items():
            breiten = [round(r[2], 4) for r in rects]
            print(f"   {feld}: {len(rects)} Stellen, Breite {breiten[0]}")

    for lane_daten in daten["lanes"]:
        felder = ergebnis.get(lane_daten["lane_id"])
        if not felder:
            continue
        for feld, rects in felder.items():
            lane_daten["rois"] = [r for r in lane_daten["rois"]
                                  if not r["name"].startswith(f"digit_{feld}_")]
            for i, rect in enumerate(rects, 1):
                lane_daten["rois"].append({
                    "name": f"digit_{feld}_{i}",
                    "rect": [round(v, 4) for v in rect],
                    "enabled": True, "pin_number": None})

    ZIEL.write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"\nGeschrieben: {ZIEL}  ({len(ergebnis)} Bahnen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
