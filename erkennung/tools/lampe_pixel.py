"""Zeigt die ROHEN PIXEL einer Kegellampe -- ohne jede Auswertung.

WOZU (Nutzer, 2026-09-24): *"Die GIFs zeigen doch immer nur an, dass Lampe 8
fehlt?"* -- Richtig. Die Lampenbeschriftung im Streitfall-GIF stammt aus
demselben Detektor, dessen Messung in Frage steht. Sie kann den Fehler nicht
belegen, sie ist der Fehler.

Dieses Werkzeug beschriftet nichts, was es misst. Es schneidet zwei Frames
derselben Bahn aus und stellt sie nebeneinander: einen, auf dem die fragliche
Lampe nachweislich AUS sein muss, und einen, auf dem sie nachweislich AN sein
muss -- nachgewiesen durch die ZIFFERNFELDER, nicht durch die Lampen. Wer die
beiden Bilder vergleicht, sieht mit eigenen Augen, ob die Lampe leuchtet.

Zusaetzlich wird je Lampe ihr ROI einzeln und stark vergroessert gezeigt, in
derselben Reihenfolge wie auf der Tafel.

Aufruf:

    .venv/Scripts/python.exe tools/lampe_pixel.py \
        --kalibrierung data/calibrations/2Spieltag.json \
        --quelle "<stream oder datei>" --bahn 5 \
        --aus 228743 --an 228922 --ziel scratchpad/lampe8.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, "src")

from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox   # noqa: E402
from kegel_cv.calibration.model import Calibration                  # noqa: E402
from kegel_cv.config import load_config                             # noqa: E402

ZOOM_TAFEL = 5
ZOOM_LAMPE = 14
GRAU = (40, 40, 40)


def hole(quelle: str, frames: list[int]) -> dict[int, np.ndarray]:
    kamera = cv2.VideoCapture(quelle)
    if not kamera.isOpened():
        raise SystemExit("Quelle nicht zu oeffnen")
    bilder = {}
    for f in sorted(frames):
        kamera.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, bild = kamera.read()
        if not ok:
            raise SystemExit(f"Frame {f} nicht lesbar")
        bilder[f] = bild
    kamera.release()
    return bilder


def beschrifte(bild: np.ndarray, text: str) -> np.ndarray:
    """Eine Zeile UNTER dem Bild -- nie darauf."""
    leiste = np.zeros((34, bild.shape[1], 3), np.uint8)
    cv2.putText(leiste, text, (6, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                (230, 230, 230), 1, cv2.LINE_AA)
    return np.vstack([bild, leiste])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--quelle", required=True)
    p.add_argument("--bahn", required=True, type=int)
    p.add_argument("--aus", required=True, type=int,
                   help="Frame, auf dem die Lampe nachweislich AUS ist")
    p.add_argument("--an", required=True, type=int,
                   help="Frame, auf dem sie nachweislich AN sein muss")
    p.add_argument("--ziel", required=True, type=Path)
    a = p.parse_args()

    cfg = load_config()
    kal = Calibration.load(str(a.kalibrierung))
    lane = next(l for l in kal.lanes if l.real_lane_number == a.bahn)
    bilder = hole(a.quelle, [a.aus, a.an])

    form = next(iter(bilder.values())).shape
    transform = lane.transform(cfg.calibration.warped_width,
                               cfg.calibration.warped_height)
    kaesten = {roi.pin_number: norm_rect_to_frame_bbox(transform, roi.rect, form)
               for roi in lane.pin_lamps() if roi.enabled}

    # Der Lampenkranz, grosszuegig umschlossen -- ganz ohne Markierungen.
    xs = [b[0] for b in kaesten.values()] + [b[0] + b[2] for b in kaesten.values()]
    ys = [b[1] for b in kaesten.values()] + [b[1] + b[3] for b in kaesten.values()]
    rand = 6
    x0, x1 = min(xs) - rand, max(xs) + rand
    y0, y1 = min(ys) - rand, max(ys) + rand

    reihen = []
    for frame, marke in ((a.aus, "AUS"), (a.an, "AN")):
        kranz = bilder[frame][y0:y1, x0:x1]
        gross = cv2.resize(kranz, None, fx=ZOOM_TAFEL, fy=ZOOM_TAFEL,
                           interpolation=cv2.INTER_NEAREST)
        reihen.append(beschrifte(gross, f"Frame {frame}  --  Lampe soll {marke} sein"))
    hoehe = max(r.shape[0] for r in reihen)
    reihen = [cv2.copyMakeBorder(r, 0, hoehe - r.shape[0], 8, 8,
                                 cv2.BORDER_CONSTANT, value=GRAU) for r in reihen]
    oben = np.hstack(reihen)

    # Und jede Lampe einzeln, beide Frames untereinander.
    spalten = []
    for pin in sorted(kaesten):
        bx, by, bw, bh = kaesten[pin]
        paare = []
        for frame in (a.aus, a.an):
            stueck = bilder[frame][by:by + bh, bx:bx + bw]
            paare.append(cv2.resize(stueck, None, fx=ZOOM_LAMPE, fy=ZOOM_LAMPE,
                                    interpolation=cv2.INTER_NEAREST))
        breite = max(x.shape[1] for x in paare)
        paare = [cv2.copyMakeBorder(x, 0, 0, 0, breite - x.shape[1],
                                    cv2.BORDER_CONSTANT, value=GRAU) for x in paare]
        saeule = np.vstack([paare[0],
                            np.full((6, breite, 3), 90, np.uint8),
                            paare[1]])
        spalten.append(cv2.copyMakeBorder(beschrifte(saeule, f" Kegel {pin}"),
                                          8, 8, 6, 6, cv2.BORDER_CONSTANT,
                                          value=GRAU))
    hoehe = max(s.shape[0] for s in spalten)
    spalten = [cv2.copyMakeBorder(s, 0, hoehe - s.shape[0], 0, 0,
                                  cv2.BORDER_CONSTANT, value=GRAU) for s in spalten]
    unten = np.hstack(spalten)

    breite = max(oben.shape[1], unten.shape[1])
    tafel = np.vstack([
        cv2.copyMakeBorder(oben, 10, 10, 0, breite - oben.shape[1],
                           cv2.BORDER_CONSTANT, value=GRAU),
        cv2.copyMakeBorder(unten, 0, 10, 0, breite - unten.shape[1],
                           cv2.BORDER_CONSTANT, value=GRAU)])
    a.ziel.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(a.ziel), tafel)
    print(f"{a.ziel}  ({tafel.shape[1]}x{tafel.shape[0]})")
    print("Oben je Frame der ganze Lampenkranz, unten jede Lampe einzeln "
          "(oben = AUS-Frame, unten = AN-Frame).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
