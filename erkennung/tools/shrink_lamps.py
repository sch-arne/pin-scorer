"""Verkleinert die Lampen-ROIs einer Bahn um den gemeinsamen Mittelpunkt.

WOZU: Die Messung vom 2026-08-30 ergab, dass die Lampen-ROIs zu gross sind --
sie ziehen Gehaeusefarbe mit hinein und heben damit den Wert im DUNKLEN
Zustand. Der kritische Abstand zwischen "schwach an" und "aus" stieg auf Bahn 5
von +18,9 auf +35,4, wenn die Kantenlaenge auf 80 % ging.

Dieses Werkzeug erzeugt die verkleinerte Fassung als eigene Datei, damit sich
beide gegeneinander messen lassen. Es entscheidet nichts -- es stellt nur die
Gegenprobe her.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

LAMPEN = tuple(f"pin_lamp_{i}" for i in range(1, 10)) + ("green_lamp",)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True,
                   help="reale Bahnnummer (real_lane_number)")
    p.add_argument("--factor", type=float, default=0.8)
    a = p.parse_args()

    d = json.loads(a.calibration.read_text(encoding="utf-8"))
    geaendert = 0
    for lane in d["lanes"]:
        if lane.get("real_lane_number") != a.lane:
            continue
        for roi in lane["rois"]:
            if roi["name"] not in LAMPEN:
                continue
            x, y, w, h = roi["rect"]
            cx, cy = x + w / 2, y + h / 2
            nw, nh = w * a.factor, h * a.factor
            roi["rect"] = [cx - nw / 2, cy - nh / 2, nw, nh]
            geaendert += 1
            print(f"   {roi['name']:<14} {w:.4f}x{h:.4f} -> {nw:.4f}x{nh:.4f}")

    if not geaendert:
        raise SystemExit(f"Bahn {a.lane} nicht gefunden oder keine Lampen")
    d["name"] = f"{d.get('name', '')} (Lampen Bahn {a.lane} x{a.factor})".strip()
    a.out.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"\n{geaendert} Lampen verkleinert -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
