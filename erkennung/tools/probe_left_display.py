"""Vermisst das linke Display in normierten Tafelkoordinaten -- HINSEHEN.

Der vorhandene ROI sitzt waagerecht richtig, ist aber zu flach: Die Ziffern sind
unten abgeschnitten. Diese Datei rendert die Umgebung mit einem Koordinatengitter
in NORMIERTEN Tafelkoordinaten, damit sich die Raender ablesen lassen -- feste
Pixelwerte waeren nach dem naechsten Kameraschwenk falsch.

Aufruf:
    .venv/Scripts/python.exe tools/probe_left_display.py [FRAME]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox
from kegel_cv.config import load_config
from kegel_cv.video import FileVideoSource

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/left_display")

# Grosszuegiger Bereich um das Display herum
BEREICH = (0.00, 0.60, 0.40, 0.22)      # x, y, Breite, Hoehe (normiert)
ZOOM = 14


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    index = int(sys.argv[1]) if len(sys.argv) > 1 else 51000
    bahn = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    cfg = load_config()
    cal = Calibration.load(KALIBRIERUNG)
    src = FileVideoSource(VIDEO)
    src.open()
    erster = src.read()

    p = None
    for lane in cal.lanes:
        kandidat = LaneProcessor(lane, cfg)
        if kandidat.prepare(erster.image.shape) and lane.display_number == bahn:
            p = kandidat
    if p is None:
        print(f"Bahn {bahn} nicht gefunden")
        return 1

    src.seek(index)
    frame = src.read()
    src.close()
    if frame is None:
        print(f"Frame {index} nicht lesbar")
        return 1

    x, y, w, h = norm_rect_to_frame_bbox(p._transform, BEREICH, frame.image.shape)
    ausschnitt = frame.image[y:y + h, x:x + w]
    gross = cv2.resize(ausschnitt, None, fx=ZOOM, fy=ZOOM,
                       interpolation=cv2.INTER_NEAREST)
    gross = cv2.copyMakeBorder(gross, 26, 4, 46, 4, cv2.BORDER_CONSTANT,
                               value=(30, 30, 30))

    # Gitter in NORMIERTEN Koordinaten -- daran laesst sich der ROI ablesen
    for i in range(0, 41):
        nx = BEREICH[0] + i * 0.01
        px = 46 + int((nx - BEREICH[0]) / BEREICH[2] * gross.shape[1] - 50)
        if not (46 <= px < gross.shape[1]):
            continue
        stark = i % 5 == 0
        cv2.line(gross, (px, 26), (px, gross.shape[0]),
                 (90, 90, 90) if stark else (55, 55, 55), 1)
        if stark:
            cv2.putText(gross, f"{nx:.2f}", (px - 16, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.36, (200, 200, 200), 1)
    for j in range(0, 23):
        ny = BEREICH[1] + j * 0.01
        py = 26 + int((ny - BEREICH[1]) / BEREICH[3] * (gross.shape[0] - 30))
        if not (26 <= py < gross.shape[0]):
            continue
        stark = j % 5 == 0
        cv2.line(gross, (46, py), (gross.shape[1], py),
                 (90, 90, 90) if stark else (55, 55, 55), 1)
        if stark:
            cv2.putText(gross, f"{ny:.2f}", (2, py + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.36, (200, 200, 200), 1)

    ziel = AUSGABE / f"gitter_bahn{bahn}_{index}.png"
    AUSGABE.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(ziel), gross)
    print(f"Bahn {bahn}, Frame {index}: {ziel}")
    print(f"Bereich {BEREICH} entspricht {w}x{h} px im Bild")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
