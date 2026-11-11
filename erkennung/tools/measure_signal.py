"""Signalwerte an ROIs messen -- Grundlage jeder Schwellwertfestlegung.

Prinzip P7: Schwellwerte werden gemessen, nicht geschaetzt. Dieses Werkzeug
liefert die Verteilung der Messwerte, aus der sich die Schwelle ableiten laesst.

    # Gruenlampe ueber ein ganzes Video verfolgen
    python tools/measure_signal.py --calibration data/calibrations/x.json --roi green_lamp

    # Kegellampen in einem einzelnen Frame vergleichen
    python tools/measure_signal.py --calibration data/calibrations/x.json \
        --roi pin_lamps --frame 90 --lane 3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration, norm_rect_to_frame_bbox  # noqa: E402


def roi_pixels(image: np.ndarray, transform, rect) -> np.ndarray:
    """Schneidet den ROI-Bereich aus dem Frame."""
    x, y, w, h = norm_rect_to_frame_bbox(transform, rect, image.shape)
    if w <= 0 or h <= 0:
        return np.empty((0, 0, 3), dtype=np.uint8)
    return image[y:y + h, x:x + w]


def green_score(patch: np.ndarray) -> float:
    """Anteil gruener Pixel in Prozent (HSV-Maske)."""
    if patch.size == 0:
        return 0.0
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (40, 80, 80), (90, 255, 255))
    return float(mask.mean() / 255.0 * 100.0)


def lamp_stats(patch: np.ndarray) -> dict[str, float]:
    """Kennwerte einer Kegellampe: Helligkeit, Saettigung, Rot-Blau-Differenz."""
    if patch.size == 0:
        return {"value": 0.0, "saturation": 0.0, "warmth": 0.0}
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    # Auf die hellsten Pixel beschraenken: Die Lampe fuellt den ROI nie ganz aus,
    # der Rand ist Gehaeuse. Ein Mittelwert ueber alles verwaessert das Signal.
    v = hsv[:, :, 2].astype(np.float32)
    threshold = np.percentile(v, 70)
    core = v >= threshold
    b, g, r = (patch[:, :, i].astype(np.float32) for i in range(3))
    return {
        "value": float(v[core].mean()),
        "saturation": float(hsv[:, :, 1].astype(np.float32)[core].mean()),
        "warmth": float((r[core] - b[core]).mean()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Signalwerte an ROIs messen")
    parser.add_argument("--video", type=Path,
                        default=Path("kegelVideos/2026-08-22 09-15-50.mp4"))
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--roi", default="green_lamp",
                        help="ROI-Name oder 'pin_lamps' fuer alle neun Kegellampen")
    parser.add_argument("--lane", type=int, default=None, help="nur diese Bahn")
    parser.add_argument("--frame", type=int, default=None,
                        help="nur dieser Frame (sonst das ganze Video)")
    parser.add_argument("--step", type=int, default=1, help="jeden n-ten Frame")
    parser.add_argument("--width", type=int, default=440)
    parser.add_argument("--height", type=int, default=530)
    args = parser.parse_args()

    calibration = Calibration.load(args.calibration)
    lanes = [l for l in calibration.lanes
             if args.lane is None or l.lane_id == args.lane]
    if not lanes:
        print(f"Bahn {args.lane} nicht in der Kalibrierung", file=sys.stderr)
        return 1

    transforms = {l.lane_id: l.transform(args.width, args.height) for l in lanes}

    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        print(f"Video nicht lesbar: {args.video}", file=sys.stderr)
        return 1

    # --- Einzelframe: Kegellampen nebeneinander vergleichen ---
    if args.frame is not None:
        cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
        ok, image = cap.read()
        cap.release()
        if not ok:
            print(f"Frame {args.frame} nicht lesbar", file=sys.stderr)
            return 1

        for lane in lanes:
            print(f"\n=== Bahn {lane.lane_id}, Frame {args.frame} ===")
            if args.roi == "pin_lamps":
                print(f"{'Lampe':>8} | {'Helligkeit':>10} | {'Saettigung':>10} | {'Waerme':>7}")
                print("-" * 46)
                for roi in lane.pin_lamps():
                    stats = lamp_stats(roi_pixels(image, transforms[lane.lane_id], roi.rect))
                    print(f"{roi.name.removeprefix('pin_lamp_'):>8} | "
                          f"{stats['value']:10.1f} | {stats['saturation']:10.1f} | "
                          f"{stats['warmth']:7.1f}")
            else:
                roi = lane.get_roi(args.roi)
                if roi is None:
                    print(f"  ROI {args.roi} nicht vorhanden")
                    continue
                patch = roi_pixels(image, transforms[lane.lane_id], roi.rect)
                print(f"  Gruen-Score: {green_score(patch):.1f}")
                print(f"  {lamp_stats(patch)}")
        return 0

    # --- ganzes Video: Zeitreihe der Gruenlampe ---
    series: dict[int, list[tuple[int, float]]] = {l.lane_id: [] for l in lanes}
    index = 0
    while True:
        ok, image = cap.read()
        if not ok:
            break
        if index % args.step == 0:
            for lane in lanes:
                roi = lane.get_roi(args.roi)
                if roi is None:
                    continue
                patch = roi_pixels(image, transforms[lane.lane_id], roi.rect)
                series[lane.lane_id].append((index, green_score(patch)))
        index += 1
    cap.release()

    print(f"Video: {args.video.name}, {index} Frames, ROI '{args.roi}'\n")
    for lane_id, values in series.items():
        if not values:
            continue
        scores = np.array([v for _, v in values])
        print(f"Bahn {lane_id}: min={scores.min():6.1f} max={scores.max():6.1f} "
              f"median={np.median(scores):6.1f}")

        # Wechsel anzeigen -- die interessanten Stellen im Video
        mid = (scores.min() + scores.max()) / 2
        above = scores > mid
        changes = np.where(np.diff(above.astype(int)) != 0)[0]
        if len(changes):
            print("   Wechsel bei Frames: " + ", ".join(
                f"{values[i + 1][0]} ({'AN' if above[i + 1] else 'AUS'})"
                for i in changes[:20]
            ))
        else:
            print(f"   kein Wechsel -- durchgehend {'AN' if above[0] else 'AUS'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
