"""Zeigt, was an der Stelle des linken Displays wirklich steht -- HINSEHEN.

Der Fehlwurfzaehler ist in 36 789 Messungen kein einziges Mal lesbar gewesen
(siehe Q10). Bevor daran etwas geschraubt wird, gehoert das Bild angesehen:
Der ROI `left_display` traegt auf allen vier Bahnen dieselben Koordinaten,
waehrend jedes andere Feld je Bahn abweicht -- das riecht nach einem nie
kalibrierten Vorgabewert.

Ausgegeben wird die entzerrte Tafel mit eingezeichnetem ROI und daneben der
Ausschnitt stark vergroessert.

Aufruf:
    .venv/Scripts/python.exe tools/inspect_left_display.py [FRAME] [BAHN]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.video import FileVideoSource

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/left_display")


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    frames = [int(a) for a in sys.argv[1:] if a.isdigit()] or [51000]
    bahn = 2

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
    p = prozessoren[bahn]

    AUSGABE.mkdir(parents=True, exist_ok=True)
    from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox

    # roi_boxes() liefert nur Lampen. Die Ziffernfelder muessen aus der
    # Kalibrierung selbst geholt werden -- und zwar AUCH die abgeschalteten,
    # denn genau die will man ja ansehen.
    lane = p.lane
    boxes = {}
    for roi in lane.rois:
        if roi.name == "left_display" or roi.name.startswith("digit_"):
            boxes[roi.name] = norm_rect_to_frame_bbox(
                p._transform, roi.rect, erster.image.shape)
    x, y, w, h = p.lane_box()

    blaetter = []
    for index in frames:
        src.seek(index)
        frame = src.read()
        if frame is None:
            continue

        tafel = frame.image[y:y + h, x:x + w].copy()
        tafel = cv2.resize(tafel, None, fx=3.0, fy=3.0,
                           interpolation=cv2.INTER_LANCZOS4)

        # Alle Ziffernfelder einzeichnen -- so ist sofort sichtbar, welches
        # sitzt und welches nicht.
        farben = {"left_display": (0, 80, 255)}
        for name, box in boxes.items():
            if not (name == "left_display" or name.startswith("digit_")):
                continue
            bx, by, bw, bh = box
            pt1 = (int((bx - x) * 3), int((by - y) * 3))
            pt2 = (int((bx - x + bw) * 3), int((by - y + bh) * 3))
            cv2.rectangle(tafel, pt1, pt2, farben.get(name, (0, 220, 0)),
                          2 if name == "left_display" else 1)
        cv2.putText(tafel, f"Bahn {bahn}  Frame {index}   ROT = left_display",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        cv2.imwrite(str(AUSGABE / f"tafel_{index}.png"), tafel)
        blaetter.append(tafel)

        # Der Ausschnitt selbst, stark vergroessert
        bx, by, bw, bh = boxes["left_display"]
        aus = frame.image[by:by + bh, bx:bx + bw]
        if aus.size:
            aus = cv2.resize(aus, None, fx=10.0, fy=10.0,
                             interpolation=cv2.INTER_NEAREST)
            cv2.imwrite(str(AUSGABE / f"ausschnitt_{index}.png"), aus)
        print(f"Frame {index}: ROI left_display = {bx},{by} {bw}x{bh} px")

    src.close()
    if blaetter:
        breite = max(b.shape[1] for b in blaetter)
        blaetter = [cv2.copyMakeBorder(b, 0, 8, 0, breite - b.shape[1],
                                       cv2.BORDER_CONSTANT, value=(40, 40, 40))
                    for b in blaetter]
        cv2.imwrite(str(AUSGABE / "uebersicht.png"), np.vstack(blaetter))
        print(f"\n{AUSGABE / 'uebersicht.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
