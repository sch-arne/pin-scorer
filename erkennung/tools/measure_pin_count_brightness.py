"""Misst die Helligkeit des `pin_count`-Felds an bestimmten Frames.

WOZU: Nutzeridee (2026-09-03) -- ein echter Nullwurf zeigt eine LEUCHTENDE 0,
ein Artefakt (Anlage raeumt/setzt zurueck) zeigt ein DUNKLES Feld. Beide
erscheinen in `wuerfe.csv` gleich (keine lesbare Ziffer oder Ziffer 0), aber
die Helligkeit des Feldes sollte sie trennen.

Misst denselben Wert wie `CalibratedDigitReader.read_digit_full`: das
95. Perzentil des Rotkanals (`brightness_percentile`), gegen das
`min_display_brightness` bereits prueft. Die Frage ist, ob die Schwelle nur
falsch gesetzt ist oder ob das Merkmal selbst nicht traegt.

AUFRUF:

    .venv/Scripts/python.exe tools/measure_pin_count_brightness.py \
        --source <Datei oder Stream-URL> \
        --calibration data/calibrations/1Spieltag_enge_lampen.json \
        --fall 3:218448:Artefakt --fall 2:85730:echt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration, norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402


def stellen_von(lane, feld: str) -> list:
    praefix = f"digit_{feld}_"
    stellen = [r for r in lane.rois if r.name.startswith(praefix) and r.enabled]
    return sorted(stellen, key=lambda r: r.rect[0])


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--fall", action="append", required=True,
                   metavar="BAHN:FRAME[:LABEL]")
    p.add_argument("--feld", default="pin_count")
    a = p.parse_args()

    faelle = []
    for eintrag in a.fall:
        teile = eintrag.split(":", 2)
        faelle.append((int(teile[0]), int(teile[1]),
                       teile[2] if len(teile) > 2 else ""))
    faelle.sort(key=lambda f: f[1])   # nur vorwaerts springen

    cfg = load_config()
    cal = Calibration.load(a.calibration)
    transforms = {l.lane_id: l.transform(cfg.calibration.warped_width,
                                         cfg.calibration.warped_height)
                  for l in cal.lanes}
    lane_von_bahn = {l.display_number: l for l in cal.lanes}

    cap = cv2.VideoCapture(a.source)
    if not cap.isOpened():
        print("Quelle nicht lesbar"); return 1

    print(f"{'Bahn':>4} {'Frame':>8} {'Label':>10} | Stelle: p95(Rot) je Ziffer")
    for bahn, frame, label in faelle:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        erreicht = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if abs(erreicht - frame) > 2000:
            print(f"{bahn:>4} {frame:>8} {label:>10} | Sprung misslungen "
                  f"(landete bei {erreicht})")
            continue
        ok, bild = cap.read()
        if not ok:
            print(f"{bahn:>4} {frame:>8} {label:>10} | Frame nicht lesbar")
            continue
        lane = lane_von_bahn.get(bahn)
        if lane is None:
            print(f"{bahn:>4} {frame:>8} {label:>10} | Bahn nicht kalibriert")
            continue
        werte = []
        for roi in stellen_von(lane, a.feld):
            x, y, w, h = norm_rect_to_frame_bbox(
                transforms[lane.lane_id], roi.rect, bild.shape)
            if w <= 0 or h <= 0:
                werte.append(float("nan")); continue
            patch = bild[y:y+h, x:x+w]
            werte.append(float(np.percentile(patch[:, :, 2],
                                             cfg.detection.digits.brightness_percentile)))
        text = "  ".join(f"{v:.0f}" for v in werte)
        schwelle = cfg.detection.digits.min_display_brightness
        urteil = "HELL" if any(v >= schwelle for v in werte) else "dunkel"
        print(f"{bahn:>4} {frame:>8} {label:>10} | {text}   -> {urteil} "
              f"(Schwelle {schwelle})")
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
