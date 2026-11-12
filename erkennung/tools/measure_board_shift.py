"""Misst, ob die Anzeigetafel im Bild wandert.

WOZU -- gefunden am 2026-08-30: Bei den Scheinzyklen auf Bahn 5 leuchtete die
gruene Lampe in JEDEM Frame. Der Score fiel trotzdem, weil die Tafel im Bild
verrutscht war und die feste ROI daneben lag.

Das widerspricht einer Annahme, auf der die ganze Kalibrierung steht (geklaert
2026-08-25): "die Position ist innerhalb einer Uebertragung stabil". Ist sie
das nicht, genuegt EINE Kalibrierung zu Beginn nicht mehr.

VERFAHREN: Phasenkorrelation der Tafelregion gegen ein Referenzbild. Sie liefert
den Versatz in Pixeln, ohne dass irgendetwas erkannt werden muss -- gemessen
wird die Verschiebung des gesamten Bildinhalts in diesem Ausschnitt.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.calibration import Calibration


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True)
    p.add_argument("--frames", required=True,
                   help="Kommaliste der zu pruefenden Frames")
    p.add_argument("--reference", type=int, required=True,
                   help="Frame, gegen den gemessen wird")
    p.add_argument("--csv", type=Path, default=None)
    a = p.parse_args()

    nummern = [int(x) for x in a.frames.split(",")]
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

    def hole(n):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(n))
        ok, b = cap.read()
        return b if ok else None

    ref = hole(a.reference)
    if ref is None:
        raise SystemExit("Referenzframe nicht lesbar")

    quad = np.array(lane.quad, dtype=np.float32)
    x0, y0 = int(quad[:, 0].min()), int(quad[:, 1].min())
    x1, y1 = int(quad[:, 0].max()), int(quad[:, 1].max())
    # Etwas Luft, damit eine Verschiebung noch Inhalt zum Vergleichen hat
    rand = 12
    H, B = ref.shape[:2]
    sx0, sy0 = max(0, x0 - rand), max(0, y0 - rand)
    sx1, sy1 = min(B, x1 + rand), min(H, y1 + rand)

    def ausschnitt(bild):
        g = cv2.cvtColor(bild[sy0:sy1, sx0:sx1], cv2.COLOR_BGR2GRAY)
        return np.float32(g)

    basis = ausschnitt(ref)
    fenster = cv2.createHanningWindow(
        (basis.shape[1], basis.shape[0]), cv2.CV_32F)

    print(f"Bahn {a.lane}, Tafel bei ({x0},{y0})-({x1},{y1}), "
          f"Referenz Frame {a.reference}\n")
    print(f"  {'Frame':>8} {'dx':>7} {'dy':>7} {'Versatz':>8}  Guete")
    zeilen = []
    for n in nummern:
        bild = hole(n)
        if bild is None:
            print(f"  {n:>8}   nicht lesbar")
            continue
        (dx, dy), guete = cv2.phaseCorrelate(basis, ausschnitt(bild), fenster)
        betrag = float(np.hypot(dx, dy))
        marke = "   << verschoben" if betrag >= 1.5 else ""
        print(f"  {n:>8} {dx:+7.2f} {dy:+7.2f} {betrag:8.2f}  {guete:.3f}{marke}")
        zeilen.append({"Frame": n, "dx": round(dx, 3), "dy": round(dy, 3),
                       "Versatz_px": round(betrag, 3), "Guete": round(guete, 4)})
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
