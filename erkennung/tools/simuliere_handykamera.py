"""Stellt aus dem Hallenmitschnitt nach, was ein Handy vor der Tafel saehe.

WOFUER. Die Handy-App fand auf einer FUNK-Tafel nichts. Ob das am Massstab
liegt, am Winkel oder daran, dass eine Handykamera schlicht andere Merkmale
liefert, laesst sich vor Ort in fuenf Minuten klaeren -- nur kommt man nicht in
fuenf Minuten an eine Kegelbahn. Also wird der Blick nachgestellt.

WIE. Aus einem Hallenframe wird ein Ausschnitt um eine Tafel geschnitten,
gerade so gross, dass die Tafel denselben Anteil der Bildbreite einnimmt wie
auf einem Telefon aus der gewuenschten Entfernung. Dieser Ausschnitt wird auf
Handyaufloesung hochskaliert -- genau das tut die Optik eines Telefons, das
naeher drangeht.

WAS DAMIT NICHT GEPRUEFT IST, und das ist wichtig:

* **Andere Optik.** Ein Handyobjektiv zeichnet anders als eine RTSP-Kamera:
  andere Verzeichnung, andere Schaerfeverteilung, andere Farbabstimmung.
* **Andere Beleuchtung.** Der Mitschnitt ist abends im Training entstanden.
* **Echte Aufloesung.** Hochskalieren erfindet keine Bildpunkte. Ein Telefon
  aus einem Meter Entfernung sieht MEHR Einzelheiten als dieser Ausschnitt,
  nicht weniger.

Der letzte Punkt macht die Simulation zur **unteren Schranke**: Was hier
gefunden wird, wird vor Ort erst recht gefunden. Was hier durchfaellt, kann
vor Ort trotzdem klappen.

    .venv/Scripts/python.exe tools/simuliere_handykamera.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL / "src"))

from kegel_cv.calibration.board_finder import BoardFinder  # noqa: E402
from kegel_cv.calibration.board_library import (erkenne,  # noqa: E402
                                                lade_bibliothek)
from kegel_cv.calibration.model import Calibration  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402

# Hochformat, wie das Stativ es haelt.
HANDY = (1440, 1920)


def handyblick(bild: np.ndarray, quad, anteil: float, neigung: float = 0.0,
               unschaerfe: int = 0, jpeg: int = 0) -> np.ndarray:
    """Ein Ausschnitt um `quad`, so gross, dass die Tafel `anteil` der Breite fuellt."""
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    mx, my = sum(xs) / 4, sum(ys) / 4
    tafelbreite = max(xs) - min(xs)

    breit = tafelbreite / max(0.05, anteil)
    hoch = breit * HANDY[1] / HANDY[0]
    x0, y0 = int(mx - breit / 2), int(my - hoch / 2)
    x1, y1 = int(mx + breit / 2), int(my + hoch / 2)

    # Ueber den Bildrand hinaus wird schwarz aufgefuellt statt verschoben:
    # Verschieben wuerde die Tafel aus der Mitte ruecken und damit etwas
    # anderes messen, als gefragt war.
    rand_l, rand_o = max(0, -x0), max(0, -y0)
    rand_r, rand_u = max(0, x1 - bild.shape[1]), max(0, y1 - bild.shape[0])
    ausschnitt = bild[max(0, y0):min(bild.shape[0], y1),
                      max(0, x0):min(bild.shape[1], x1)]
    if rand_l or rand_o or rand_r or rand_u:
        ausschnitt = cv2.copyMakeBorder(ausschnitt, rand_o, rand_u, rand_l,
                                        rand_r, cv2.BORDER_CONSTANT, value=(0, 0, 0))

    handy = cv2.resize(ausschnitt, HANDY, interpolation=cv2.INTER_CUBIC)

    if neigung > 0:
        h, b = handy.shape[:2]
        d = neigung * b
        quelle = np.float32([[0, 0], [b, 0], [b, h], [0, h]])
        ziel = np.float32([[d, 0], [b - d, 0], [b, h], [0, h]])
        handy = cv2.warpPerspective(
            handy, cv2.getPerspectiveTransform(quelle, ziel), (b, h))
    if unschaerfe > 1:
        handy = cv2.GaussianBlur(handy, (unschaerfe, unschaerfe), 0)
    if jpeg:
        ok, kodiert = cv2.imencode(".jpg", handy, [cv2.IMWRITE_JPEG_QUALITY, jpeg])
        if ok:
            handy = cv2.imdecode(kodiert, cv2.IMREAD_COLOR)
    return handy


def stuetzen(ziel, vorlagen) -> int:
    finder = BoardFinder()
    finder.finde(ziel, vorlagen)
    return finder.beste_inlier


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--video", default="kegelVideos/mitschnitt_2026-09-08_20-12-22.mp4")
    p.add_argument("--kalibrierung", default="debug/aktuell_mitschnitt.json")
    p.add_argument("--frame", type=int, default=3000)
    p.add_argument("--bahn", type=int, default=1, help="lane_id des Vorbilds")
    p.add_argument("--montage", default="debug/handyblick.png")
    a = p.parse_args()

    cfg = load_config()
    leiter = cfg.detection.board_search.scale_ladder
    typen = lade_bibliothek(WURZEL / "data" / "boardtypes")
    if not typen:
        raise SystemExit("keine Tafeltypen")
    muster = typen[0].muster
    ohne = [muster]
    mit = [muster if f == 1.0 else cv2.resize(
        muster, None, fx=f, fy=f,
        interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
        for f in leiter]

    kamera = cv2.VideoCapture(str(WURZEL / a.video))
    kamera.set(cv2.CAP_PROP_POS_FRAMES, a.frame)
    ok, bild = kamera.read()
    kamera.release()
    if not ok:
        raise SystemExit(f"Frame {a.frame} nicht lesbar")

    kal = Calibration.load(WURZEL / a.kalibrierung)
    bahn = kal.get_lane(a.bahn) or kal.lanes[0]
    quad = bahn.quad
    tafelbreite = max(p[0] for p in quad) - min(p[0] for p in quad)
    print(f"Hallenframe {bild.shape[1]}x{bild.shape[0]}, "
          f"Tafel {tafelbreite:.0f} px breit")
    print(f"Muster {muster.shape[1]}x{muster.shape[0]}, "
          f"Leiter {leiter}\n")

    print("SO SAEHE ES EIN HANDY (1440x1920 hochkant)")
    print(f"{'Tafel fuellt':>13s} {'Tafel dann':>11s} {'ohne Leiter':>12s} "
          f"{'mit Leiter':>11s} {'Tafeln':>7s}")
    kacheln = []
    for anteil in (0.15, 0.25, 0.40, 0.60, 0.80):
        handy = handyblick(bild, quad, anteil, jpeg=90)
        breit_px = anteil * HANDY[0]
        a_ohne = stuetzen(handy, ohne)
        a_mit = stuetzen(handy, mit)
        erg = erkenne(handy, typen, leiter=leiter)
        n = len(erg.treffer) if erg else 0
        print(f"{100*anteil:11.0f} % {breit_px:8.0f} px {a_ohne:12d} "
              f"{a_mit:11d} {n:7d}")
        k = cv2.resize(handy, (270, 360))
        cv2.putText(k, f"{100*anteil:.0f}%", (6, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(k, f"{a_mit} Stuetzen", (6, 350),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        kacheln.append(k)

    print("\nDAZU SCHRAEG UND UNSCHARF (Tafel fuellt 40 %)")
    print(f"{'Neigung':>8s} {'Unschaerfe':>11s} {'mit Leiter':>11s} {'Tafeln':>7s}")
    for neigung, unschaerfe in ((0.0, 0), (0.10, 0), (0.20, 0), (0.0, 5),
                                (0.0, 9), (0.10, 5)):
        handy = handyblick(bild, quad, 0.40, neigung=neigung,
                           unschaerfe=unschaerfe, jpeg=90)
        erg = erkenne(handy, typen, leiter=leiter)
        print(f"{100*neigung:7.0f} % {unschaerfe:9d} px {stuetzen(handy, mit):11d} "
              f"{len(erg.treffer) if erg else 0:7d}")

    if kacheln:
        ziel = WURZEL / a.montage
        cv2.imwrite(str(ziel), np.hstack(kacheln))
        print(f"\n{ziel} geschrieben")
    return 0


if __name__ == "__main__":
    sys.exit(main())
