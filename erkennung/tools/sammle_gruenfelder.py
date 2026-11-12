"""Schneidet die Umgebung der Gruenlampen einmal aus und legt sie ab.

WOZU (Nutzer, 2026-10-02): *„aber koennte man daraus nicht bei einem
Livestream theoretisch ein fitting bauen? ... das sollte halt irgendwie nicht
unsupervised laufen, bevor dann die Lampe die ganze Zeit aus oder an ist."*

Bevor so ein Wachhund gebaut wird, muss eine Frage beantwortet sein: **Wie
viele Bilder braucht eine Lagebestimmung, bis sie stabil ist?** Die heutige
Korrektur auf Bahn 5 stammt aus 36 Referenzframes. Die Gegenprobe ueber 2000
Bilder hat sie bestaetigt -- das heisst aber nicht, dass 36 Frames
ZUVERLAESSIG dieselbe Lage finden. Vielleicht war es Glueck.

Diese Frage laesst sich nur beantworten, indem man dieselbe Schaetzung ueber
viele unabhaengige Fenster wiederholt und die Streuung ansieht. Dafuer das
Video jedes Mal neu zu lesen, waere Unsinn: Ein Durchlauf kostet ueber eine
Stunde, die Lampenumgebung ist 20x19 Pixel gross.

Also EINMAL lesen, die Ausschnitte ablegen, und danach beliebig oft rechnen.
`tools/messe_gruenfit_stabilitaet.py` wertet die Ablage aus.

Gespeichert wird je Bahn ein Stapel von Ausschnitten samt Framenummern. Der
Rand (`--rand`) muss den Suchbereich des Fits abdecken.

Aufruf:

    .venv/Scripts/python.exe tools/sammle_gruenfelder.py QUELLE \
        --kalibrierung data/calibrations/2Spieltag_neu.json \
        --von 64000 --bis 104000 --schritt 5 \
        --ziel scratchpad/gruenfelder.npz
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.calibration.model import Calibration                 # noqa: E402
from kegel_cv.config import load_config                            # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("quelle")
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--von", type=int, default=0)
    p.add_argument("--bis", type=int, default=0, help="0 = bis zum Ende")
    p.add_argument("--schritt", type=int, default=5)
    p.add_argument("--rand", type=int, default=6,
                   help="Pixel Rand um die ROI -- muss den Suchbereich decken")
    p.add_argument("--ziel", type=Path, required=True)
    a = p.parse_args()

    cfg = load_config()
    kal = Calibration.load(a.kalibrierung)
    cap = cv2.VideoCapture(a.quelle)
    if not cap.isOpened():
        raise SystemExit(f"Quelle nicht lesbar: {a.quelle}")

    kaesten: dict[int, tuple[int, int, int, int]] = {}
    stapel: dict[int, list] = {}
    frames: list[int] = []
    nummer = -1
    gelesen = 0
    while True:
        ok = cap.grab()
        if not ok:
            break
        nummer += 1
        if nummer < a.von:
            continue
        if a.bis and nummer > a.bis:
            break
        if (nummer - a.von) % a.schritt:
            continue
        ok, bild = cap.retrieve()
        if not ok or bild is None:
            continue
        if not kaesten:
            for bahn in kal.lanes:
                roi = bahn.get_roi("green_lamp")
                if roi is None:
                    continue
                t = bahn.transform(cfg.calibration.warped_width,
                                   cfg.calibration.warped_height)
                x, y, w, h = norm_rect_to_frame_bbox(t, roi.rect, bild.shape)
                kaesten[bahn.display_number] = (x, y, w, h)
                stapel[bahn.display_number] = []
            print("Kaesten:", {b: k for b, k in sorted(kaesten.items())})
        for bahn, (x, y, w, h) in kaesten.items():
            x0, y0 = x - a.rand, y - a.rand
            x1, y1 = x + w + a.rand, y + h + a.rand
            if x0 < 0 or y0 < 0 or y1 > bild.shape[0] or x1 > bild.shape[1]:
                stapel[bahn].append(None)
                continue
            stapel[bahn].append(bild[y0:y1, x0:x1].copy())
        frames.append(nummer)
        gelesen += 1
        if gelesen % 500 == 0:
            print(f"   {gelesen} Ausschnitte (Frame {nummer})", flush=True)
    cap.release()

    daten = {"frames": np.asarray(frames, dtype=np.int64),
             "rand": np.asarray([a.rand])}
    for bahn, bilder in stapel.items():
        gut = [b for b in bilder if b is not None]
        if not gut:
            continue
        # Alle Ausschnitte einer Bahn haben dieselbe Groesse.
        daten[f"bahn{bahn}"] = np.stack(gut)
        daten[f"kasten{bahn}"] = np.asarray(kaesten[bahn])
    a.ziel.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.ziel, **daten)
    groesse = a.ziel.stat().st_size / 2**20
    print(f"\n{gelesen} Bilder je Bahn -> {a.ziel} ({groesse:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
