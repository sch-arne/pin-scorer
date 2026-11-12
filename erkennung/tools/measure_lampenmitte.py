"""Sitzt die Kegellampen-ROI auf der Lampe? Gemessen an LEUCHTENDEN Lampen.

DIE FRAGE (Nutzer, 2026-09-11, vor dem Nachkalibrieren-Fenster):

    "das sieht aber nicht gut kalibriert aus... die Lampen sitzen eher nicht so
     sauber"

WARUM AN LEUCHTENDEN: Bei ausgeschalteter Lampe ist im Rahmen nichts, woran
sich eine Mitte festmachen liesse -- das Gehaeuse ist ringsum gleich hell.
Leuchtet sie, ist der Schwerpunkt der Waerme (R-B) genau ihr Mittelpunkt.
Dieselbe Ueberlegung wie in `fit_lamp_rois.py`.

WARUM DAS NICHT ZIRKULAER IST: Gemessen wird in einem FENSTER, das deutlich
groesser ist als die ROI. Die ROI bestimmt also nur, wo gesucht wird, nicht was
gefunden wird -- ihr eigener Rand kann das Ergebnis nicht festhalten. Liegt der
Schwerpunkt am Fensterrand, wird die Messung verworfen.

Aufruf:

    .venv/Scripts/python.exe tools/measure_lampenmitte.py QUELLE \
        --kalibrierung data/calibrations/1Spieltag.json=Hand \
        --kalibrierung debug/endstand.json=automatisch
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.calibration.model import Calibration                 # noqa: E402
from kegel_cv.config import load_config                            # noqa: E402

# Das Suchfenster misst ein Vielfaches der ROI-Kante. Gross genug, dass eine
# um zwei Pixel danebenliegende ROI die Lampe noch ganz enthaelt.
FENSTER = 2.6
# Ab dieser Waerme (R-B im Fenstermaximum) gilt die Lampe als leuchtend.
# GEMESSEN in diesem Projekt: AUS liegt bei 10-30, AN bei ueber 60.
LEUCHTET_AB = 60.0
# Nur der helle Kern zaehlt fuer den Schwerpunkt -- der Schein reicht weit
# ueber die Lampe hinaus und zoege die Mitte zum Fenstermittelpunkt.
KERN_ANTEIL = 0.6


def fenster_um(box: tuple[int, int, int, int], form) -> tuple[int, int, int, int]:
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    nw, nh = max(6, int(round(w * FENSTER))), max(6, int(round(h * FENSTER)))
    nx = int(round(cx - nw / 2))
    ny = int(round(cy - nh / 2))
    nx = min(max(0, nx), form[1] - nw)
    ny = min(max(0, ny), form[0] - nh)
    return nx, ny, nw, nh


def schwerpunkt(ausschnitt: np.ndarray) -> tuple[float, float] | None:
    """Mitte der Waerme im Ausschnitt, in Pixeln ab dessen Ecke."""
    waerme = (ausschnitt[:, :, 2].astype(np.float32)
              - ausschnitt[:, :, 0].astype(np.float32))
    hoechste = float(waerme.max())
    if hoechste < LEUCHTET_AB:
        return None
    kern = waerme >= hoechste * KERN_ANTEIL
    if kern.sum() < 3:
        return None
    ys, xs = np.nonzero(kern)
    gewicht = waerme[kern]
    return (float((xs * gewicht).sum() / gewicht.sum()),
            float((ys * gewicht).sum() / gewicht.sum()))


def main() -> int:
    zerleger = argparse.ArgumentParser()
    zerleger.add_argument("quelle")
    zerleger.add_argument("--kalibrierung", action="append", required=True)
    zerleger.add_argument("--von", type=int, default=20000)
    zerleger.add_argument("--bis", type=int, default=26000)
    zerleger.add_argument("--schritt", type=int, default=25)
    argumente = zerleger.parse_args()

    cfg = load_config()
    saetze = []
    for eintrag in argumente.kalibrierung:
        pfad, _, name = eintrag.partition("=")
        saetze.append((name or Path(pfad).stem, Calibration.load(pfad)))

    kamera = cv2.VideoCapture(argumente.quelle)
    if not kamera.isOpened():
        print("Quelle laesst sich nicht oeffnen")
        return 1
    kamera.set(cv2.CAP_PROP_POS_FRAMES, argumente.von)

    # (Name, Bahn, Lampe) -> Liste der Versaetze in Pixeln
    versatz: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    kaesten: dict | None = None
    gelesen = verworfen = 0

    for nummer in range(argumente.von, argumente.bis):
        ok, bild = kamera.read()
        if not ok or bild is None:
            break
        if (nummer - argumente.von) % argumente.schritt:
            continue
        gelesen += 1
        if kaesten is None:
            kaesten = {}
            for name, kal in saetze:
                for bahn in sorted(kal.lanes, key=lambda l: l.quad[0][0]):
                    t = bahn.transform(cfg.calibration.warped_width,
                                       cfg.calibration.warped_height)
                    for roi in bahn.pin_lamps():
                        box = norm_rect_to_frame_bbox(t, roi.rect, bild.shape)
                        kaesten[(name, bahn.display_number, roi.name)] = box

        for schluessel, box in kaesten.items():
            fx, fy, fw, fh = fenster_um(box, bild.shape)
            mitte = schwerpunkt(bild[fy:fy + fh, fx:fx + fw])
            if mitte is None:
                continue
            # Am Fensterrand ist der Schwerpunkt abgeschnitten -- so eine
            # Messung sagt nur, dass das Fenster zu klein war.
            if not (1 < mitte[0] < fw - 2 and 1 < mitte[1] < fh - 2):
                verworfen += 1
                continue
            versatz[schluessel].append((fx + mitte[0] - (box[0] + box[2] / 2),
                                        fy + mitte[1] - (box[1] + box[3] / 2)))
    kamera.release()
    print(f"{gelesen} Bilder, {verworfen} Messungen am Fensterrand verworfen\n")

    for name, _ in saetze:
        print(f"=== {name} ===")
        print(f"{'Bahn':6s} {'Messungen':>10s} {'dx':>7s} {'dy':>7s} "
              f"{'Abstand':>8s} {'schlechteste Lampe':>22s}")
        for bahn in sorted({k[1] for k in versatz if k[0] == name}):
            teile = [(lampe, np.median([v[0] for v in werte]),
                      np.median([v[1] for v in werte]), len(werte))
                     for (n, b, lampe), werte in versatz.items()
                     if n == name and b == bahn and werte]
            if not teile:
                continue
            dx = float(np.median([t[1] for t in teile]))
            dy = float(np.median([t[2] for t in teile]))
            schlimmste = max(teile, key=lambda t: np.hypot(t[1], t[2]))
            print(f"{bahn:<6d} {sum(t[3] for t in teile):10d} {dx:+7.2f} "
                  f"{dy:+7.2f} {np.hypot(dx, dy):8.2f} "
                  f"{schlimmste[0]:>13s} {np.hypot(schlimmste[1], schlimmste[2]):5.2f}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
