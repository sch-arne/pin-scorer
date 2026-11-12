"""Rendert ein Tafelbild aus einem laufenden Mitschnitt mit Koordinatengitter.

Zweck: Die Ziffernrahmen des Fehlwurfzaehlers nachtragen, OHNE die laufende
Analyse zu unterbrechen. Der Frame-Mitschnitt legt je Ereignis ein
`*_tafel.png` ab -- den Ausschnitt der Anzeigetafel im Originalframe. Zusammen
mit der Kalibrierung laesst sich daraus die normierte Tafelkoordinate jedes
Bildpunktes bestimmen.

Raster 0,005. Ein groeberes genuegt nicht: Bei rund 11 px Ziffernbreite sind
0,015 normiert schon drei Pixel, und damit verfehlt der Leser die Segmente.

Aufruf:
    .venv/Scripts/python.exe tools/grid_from_run.py LAUFORDNER [BAHN ...]
"""

from __future__ import annotations

import glob
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.calibration import Calibration
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox

KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-29_1227.json"
AUSGABE = Path("debug/left_display_live")

BEREICH = (0.04, 0.66, 0.30, 0.20)     # x, y, Breite, Hoehe (normiert)
ZOOM = 26
RASTER = 0.005
BESCHRIFTET = 0.01


def gitter(bild, bereich, breite_px, hoehe_px):
    x0, y0, bw, bh = bereich
    for i in range(int(round(bw / RASTER)) + 1):
        nx = x0 + i * RASTER
        px = 52 + int((nx - x0) / bw * breite_px)
        stark = abs(round(nx / BESCHRIFTET) * BESCHRIFTET - nx) < 1e-9
        cv2.line(bild, (px, 26), (px, bild.shape[0]),
                 (115, 115, 115) if stark else (58, 58, 58), 1)
        if stark:
            cv2.putText(bild, f"{nx:.2f}", (px - 16, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.34, (215, 215, 215), 1)
    for j in range(int(round(bh / RASTER)) + 1):
        ny = y0 + j * RASTER
        py = 26 + int((ny - y0) / bh * hoehe_px)
        stark = abs(round(ny / BESCHRIFTET) * BESCHRIFTET - ny) < 1e-9
        cv2.line(bild, (52, py), (bild.shape[1], py),
                 (115, 115, 115) if stark else (58, 58, 58), 1)
        if stark:
            cv2.putText(bild, f"{ny:.2f}", (2, py + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.34, (215, 215, 215), 1)
    return bild


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    ordner = Path(sys.argv[1])
    bahnen = [int(a) for a in sys.argv[2:]] or [1, 2, 3, 4]

    cal = Calibration.load(KALIBRIERUNG)
    AUSGABE.mkdir(parents=True, exist_ok=True)

    for bahn in bahnen:
        lane = cal.get_lane(bahn)
        if lane is None:
            print(f"Bahn {bahn} nicht in der Kalibrierung")
            continue

        bilder = sorted(glob.glob(str(ordner / f"lane_{bahn}" / "event_*" / "*_tafel.png")))
        if not bilder:
            print(f"Bahn {bahn}: keine Tafelbilder")
            continue
        tafel = cv2.imread(bilder[-1])

        # Der Ausschnitt ist die Bounding Box des Vierecks im Originalframe.
        xs = [p[0] for p in lane.quad]
        ys = [p[1] for p in lane.quad]
        x0, y0 = int(min(xs)), int(min(ys))

        # Fuer die Umrechnung wird die Frame-Groesse gebraucht. Sie steckt nicht
        # im Ausschnitt -- 1920x1080 ist die gemessene Groesse des Materials.
        transform = lane.transform(440, 530)
        bx, by, bw, bh = norm_rect_to_frame_bbox(transform, BEREICH,
                                                 (1080, 1920, 3))
        # in Ausschnittskoordinaten
        cx, cy = bx - x0, by - y0
        if cx < 0 or cy < 0 or cx + bw > tafel.shape[1] or cy + bh > tafel.shape[0]:
            print(f"Bahn {bahn}: Bereich liegt ausserhalb des Ausschnitts "
                  f"({cx},{cy} {bw}x{bh} in {tafel.shape[1]}x{tafel.shape[0]}) "
                  f"-- wird zugeschnitten")
            cx, cy = max(0, cx), max(0, cy)
            bw = min(bw, tafel.shape[1] - cx)
            bh = min(bh, tafel.shape[0] - cy)
        aus = tafel[cy:cy + bh, cx:cx + bw]
        if aus.size == 0:
            print(f"Bahn {bahn}: leerer Ausschnitt")
            continue

        gross = cv2.resize(aus, (aus.shape[1] * ZOOM, aus.shape[0] * ZOOM),
                           interpolation=cv2.INTER_NEAREST)
        gross = cv2.copyMakeBorder(gross, 26, 4, 52, 4, cv2.BORDER_CONSTANT,
                                   value=(25, 25, 25))
        gross = gitter(gross, BEREICH, aus.shape[1] * ZOOM, aus.shape[0] * ZOOM)
        ziel = AUSGABE / f"gitter_bahn{bahn}.png"
        cv2.imwrite(str(ziel), gross)
        print(f"Bahn {bahn}: {ziel}  (Quelle {Path(bilder[-1]).name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
