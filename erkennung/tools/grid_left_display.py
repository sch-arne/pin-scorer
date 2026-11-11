"""Rendert das linke Display mit feinem Koordinatengitter -- zum Ablesen.

Die Rahmen der beiden Ziffernstellen muessen in NORMIERTEN Tafelkoordinaten
gesetzt werden, nicht in Pixeln: Die Tafeln stehen je Bahn unterschiedlich
schraeg im Overlay, und die Position verschiebt sich zwischen Sessions.

Raster 0,005. Ein groeberes Raster (0,01) genuegt nicht -- bei rund 11 px
Ziffernbreite sind 0,015 normiert schon drei Pixel, und damit verfehlt der
Leser die Segmente. Genau daran ist der erste Versuch auf Bahn 2 gescheitert
(17 % lesbar, Werte 36 und 56 bei einer Anzeige, die "00" zeigt).

Aufruf:
    .venv/Scripts/python.exe tools/grid_left_display.py [FRAME] [BAHN ...]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox
from kegel_cv.config import load_config
from kegel_cv.video import FileVideoSource

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/left_display")

BEREICH = (0.06, 0.61, 0.26, 0.18)     # x, y, Breite, Hoehe (normiert)
ZOOM = 30
RASTER = 0.005
BESCHRIFTET = 0.01


def gitter(bild, bereich, breite_px, hoehe_px):
    """Zeichnet das Koordinatengitter und beschriftet die groben Linien."""
    x0, y0, bw, bh = bereich
    schritte = int(round(bw / RASTER))
    for i in range(schritte + 1):
        nx = x0 + i * RASTER
        px = 52 + int((nx - x0) / bw * breite_px)
        stark = abs(round(nx / BESCHRIFTET) * BESCHRIFTET - nx) < 1e-9
        cv2.line(bild, (px, 26), (px, bild.shape[0]),
                 (115, 115, 115) if stark else (58, 58, 58), 1)
        if stark:
            cv2.putText(bild, f"{nx:.2f}", (px - 16, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.34, (215, 215, 215), 1)
    schritte = int(round(bh / RASTER))
    for j in range(schritte + 1):
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
    zahlen = [int(a) for a in sys.argv[1:] if a.isdigit()]
    index = zahlen[0] if zahlen else 51000
    bahnen = zahlen[1:] or [3, 4, 5]

    cfg = load_config()
    cal = Calibration.load(KALIBRIERUNG)
    src = FileVideoSource(VIDEO)
    src.open()
    erster = src.read()

    prozessoren = {}
    for lane in cal.lanes:
        p = LaneProcessor(lane, cfg)
        if p.prepare(erster.image.shape):
            prozessoren[lane.display_number] = p

    src.seek(index)
    frame = src.read()
    src.close()
    if frame is None:
        print(f"Frame {index} nicht lesbar")
        return 1

    AUSGABE.mkdir(parents=True, exist_ok=True)
    for bahn in bahnen:
        p = prozessoren.get(bahn)
        if p is None:
            print(f"Bahn {bahn} nicht kalibriert")
            continue
        x, y, w, h = norm_rect_to_frame_bbox(p._transform, BEREICH,
                                             frame.image.shape)
        aus = frame.image[y:y + h, x:x + w]
        gross = cv2.resize(aus, (w * ZOOM, h * ZOOM),
                           interpolation=cv2.INTER_NEAREST)
        gross = cv2.copyMakeBorder(gross, 26, 4, 52, 4, cv2.BORDER_CONSTANT,
                                   value=(25, 25, 25))
        gross = gitter(gross, BEREICH, w * ZOOM, h * ZOOM)
        ziel = AUSGABE / f"gitter_bahn{bahn}_{index}.png"
        cv2.imwrite(str(ziel), gross)
        print(f"Bahn {bahn}: {ziel}  ({w}x{h} px im Bild)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
