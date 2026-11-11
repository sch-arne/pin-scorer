"""Legt die Bildbelege zu verdaechtigen Gruenzyklen nebeneinander.

WOZU: Ein Scheinzyklus von unter einer Sekunde laesst sich aus Zahlen nicht
erklaeren -- die Gruenspur sagt nur, DASS der Score die Schwelle gekreuzt hat,
nicht warum. Die Vermutung des Nutzers (2026-08-30): das Oeffnen des hinteren
Bereichs aendert die Beleuchtung. Das steht in keiner Kennzahl, aber im Bild.

Ausgegeben wird je Verdachtsfall eine Zeile aus drei Bildern -- vorher,
mittendrin, nachher -- mit der Tafel und genug Umgebung, dass eine Aenderung
der Beleuchtung sichtbar wird. Die ROI der Gruenlampe ist eingezeichnet.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.calibration import Calibration
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox

# So viel Umgebung um die Tafel herum, als Vielfaches ihrer Kantenlaenge.
# Die Tafel allein wuerde die Frage nicht beantworten -- gesucht ist, was
# DANEBEN passiert.
RAND = 1.1
# Vergroesserung: bei 133 px Tafelbreite ist ungestreckt nichts zu erkennen.
ZOOM = 2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True)
    p.add_argument("--frames", required=True,
                   help="Gruppen zu je drei Frames, Gruppen mit ';' getrennt: "
                        "'40728,40889,41051;47048,47221,47394'")
    p.add_argument("--out", type=Path, default=Path("debug/phantom"))
    a = p.parse_args()

    gruppen = [[int(x) for x in g.split(",")] for g in a.frames.split(";")]
    alle = sorted({f for g in gruppen for f in g})

    cal = Calibration.load(a.calibration)
    lane = next((l for l in cal.lanes if l.display_number == a.lane), None)
    if lane is None:
        raise SystemExit(f"Bahn {a.lane} nicht in der Kalibrierung")

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 15000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 10000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")

    bilder = {}
    for n in alle:
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(n))
        ok, bild = cap.read()
        if ok and bild is not None:
            bilder[n] = bild
    cap.release()
    print(f"{len(bilder)} von {len(alle)} Frames geladen")
    if not bilder:
        return 1

    erstes = next(iter(bilder.values()))
    H, B = erstes.shape[:2]
    quad = np.array(lane.quad, dtype=np.float32)
    x0, y0 = quad[:, 0].min(), quad[:, 1].min()
    x1, y1 = quad[:, 0].max(), quad[:, 1].max()
    br, ho = x1 - x0, y1 - y0
    ax0 = max(0, int(x0 - br * RAND))
    ay0 = max(0, int(y0 - ho * RAND))
    ax1 = min(B, int(x1 + br * RAND))
    ay1 = min(H, int(y1 + ho * RAND))

    tf = lane.transform(B, H)
    roi = lane.get_roi("green_lamp")
    gx, gy, gw, gh = norm_rect_to_frame_bbox(tf, roi.rect, erstes.shape)

    a.out.mkdir(parents=True, exist_ok=True)
    zeilen = []
    for gruppe in gruppen:
        kacheln = []
        for n in gruppe:
            if n not in bilder:
                continue
            aus = bilder[n][ay0:ay1, ax0:ax1].copy()
            # Tafel und Gruenlampe markieren, relativ zum Ausschnitt
            cv2.rectangle(aus, (int(x0) - ax0, int(y0) - ay0),
                          (int(x1) - ax0, int(y1) - ay0), (255, 200, 0), 1)
            cv2.rectangle(aus, (gx - ax0 - 1, gy - ay0 - 1),
                          (gx - ax0 + gw, gy - ay0 + gh), (0, 0, 255), 1)
            aus = cv2.resize(aus, None, fx=ZOOM, fy=ZOOM,
                             interpolation=cv2.INTER_NEAREST)
            cv2.putText(aus, f"F{n}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (255, 255, 255), 1, cv2.LINE_AA)
            kacheln.append(aus)
        if kacheln:
            zeilen.append(np.hstack(kacheln))

    if zeilen:
        breite = max(z.shape[1] for z in zeilen)
        zeilen = [np.pad(z, ((0, 0), (0, breite - z.shape[1]), (0, 0)))
                  for z in zeilen]
        ziel = a.out / f"bahn{a.lane}_verdacht.png"
        cv2.imwrite(str(ziel), np.vstack(zeilen))
        print(f"Geschrieben: {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
