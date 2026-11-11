"""Prueft, ob ein Anstieg des Gruen-Scores von der Lampe kommt oder vom Licht.

WOZU -- gefunden am 2026-08-30: Auf Bahn 5 gab es acht Gruenzyklen von unter
zwei Sekunden. Im Bild leuchtete die gruene Lampe dabei NICHT. Was sich aenderte,
war die Beleuchtung: Der Raum hinter den Kegeln stand offen, ein helles Feld
leuchtete herein, und der HSV-Score der Lampenregion stieg mit.

DIE UNTERSCHEIDUNG: Eine leuchtende Lampe hebt NUR ihre eigene Region. Mehr
Umgebungslicht hebt die ganze Tafel. Gemessen wird deshalb der Score der
Lampe UND der eines Referenzfeldes daneben, das nie gruen leuchtet -- hier das
Gehaeuse links der Lampe. Steigen beide, war es das Licht.

Das ist dieselbe Logik, die im Projekt schon fuer die Kegellampen gilt: nicht
der absolute Wert entscheidet, sondern der Abstand zu einer mitlaufenden
Grundlinie.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.calibration import Calibration
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox
from kegel_cv.config import load_config
from kegel_cv.detection.lamp_detectors import HsvGreenDetector

# Referenzfeld: gleiche Hoehe wie die Lampe, um diesen Betrag nach LINKS
# versetzt. Dort sitzt Gehaeuse, keine Anzeige und keine Lampe.
REFERENZ_VERSATZ_X = -0.085
# Das ganze Tafelinnere als zweiter Zeuge fuer die Helligkeit.
TAFEL_FELD = (0.15, 0.30, 0.70, 0.30)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True)
    p.add_argument("--frames", required=True)
    p.add_argument("--csv", type=Path, default=None)
    a = p.parse_args()

    nummern = [int(x) for x in a.frames.split(",")]
    cal = Calibration.load(a.calibration)
    lane = next((l for l in cal.lanes if l.display_number == a.lane), None)
    if lane is None:
        raise SystemExit(f"Bahn {a.lane} nicht in der Kalibrierung")
    roi = lane.get_roi("green_lamp")
    x0, y0, w0, h0 = roi.rect
    ref_rect = (x0 + REFERENZ_VERSATZ_X, y0, w0, h0)

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 15000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 10000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")

    cfg = load_config()
    det = HsvGreenDetector(cfg.detection.green)
    zeilen = []
    tf = None

    print(f"  {'Frame':>8} {'Lampe':>7} {'Referenz':>9} {'Abstand':>8} "
          f"{'Tafel-Hell':>11}")
    for n in nummern:
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(n))
        ok, bild = cap.read()
        if not ok or bild is None:
            print(f"  {n:>8}   nicht lesbar")
            continue
        if tf is None:
            tf = lane.transform(bild.shape[1], bild.shape[0])

        def score(rect):
            bx, by, bw, bh = norm_rect_to_frame_bbox(tf, rect, bild.shape)
            if bw <= 0 or bh <= 0:
                return 0.0
            return det.score(bild[by:by + bh, bx:bx + bw])

        lampe = score(roi.rect)
        referenz = score(ref_rect)
        bx, by, bw, bh = norm_rect_to_frame_bbox(tf, TAFEL_FELD, bild.shape)
        hell = float(cv2.cvtColor(bild[by:by + bh, bx:bx + bw],
                                  cv2.COLOR_BGR2GRAY).mean())
        print(f"  {n:>8} {lampe:7.1f} {referenz:9.1f} {lampe - referenz:8.1f} "
              f"{hell:11.1f}")
        zeilen.append({"Frame": n, "Lampe": round(lampe, 1),
                       "Referenz": round(referenz, 1),
                       "Abstand": round(lampe - referenz, 1),
                       "Tafelhelligkeit": round(hell, 1)})
    cap.release()

    if a.csv and zeilen:
        a.csv.parent.mkdir(parents=True, exist_ok=True)
        with a.csv.open("w", encoding="utf-8-sig", newline="") as d:
            s = csv.DictWriter(d, fieldnames=list(zeilen[0]), delimiter=";")
            s.writeheader()
            s.writerows(zeilen)
        print(f"\nGeschrieben: {a.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
