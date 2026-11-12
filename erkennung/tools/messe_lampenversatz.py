"""Misst, ob eine Kegellampen-ROI wirklich auf ihrer Lampe sitzt.

WOZU (Nutzer, 2026-09-24): *"Ebenfalls auf Bahn 5 wird die Lampe 8 manchmal
irrtuemlich 'AUS' gelesen, obwohl sie an ist. ... Ich glaube hier sass aber
zusaetzlich die Kalibrierung leicht ungut."*

Die Lampenspur sagt, DASS eine Lampe zu dunkel gemessen wird. Sie sagt nicht,
warum. Eine ROI ist hier rund 6x6 Pixel gross -- ein einziges Pixel Versatz
nimmt ihr ein Sechstel ihrer Flaeche und zieht den Mittelwert der hellsten
Pixel nach unten. Genau das laesst sich nachmessen, ohne zu raten: Man
verschiebt die ROI probeweise um ein paar Pixel und schaut, wo die Lampe am
hellsten wird. Sitzt die Kalibrierung richtig, ist das Maximum bei (0,0).

Gemessen wird auf den Tafelbildern, die der Lauf ohnehin gespeichert hat
(`lane_N/event_*/…_tafel.png`) -- kein Sprung in die Quelle noetig. Je Lampe
und Verschiebung wird das Perzentil `--perzentil` der Helligkeit ueber alle
Bilder gebildet: Es beschreibt, wie hell die Lampe wird, WENN sie leuchtet.
Der Mittelwert taugt dafuer nicht, weil jede Lampe die meiste Zeit aus ist.

Aufruf:

    .venv/Scripts/python.exe tools/messe_lampenversatz.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45 \
        --kalibrierung data/calibrations/2Spieltag.json
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

# Der Rand, den `LaneProcessor.lane_box` um das Tafelviereck legt. Er steht
# dort fest verdrahtet; hier muss derselbe Wert stehen, sonst liegt das
# gesamte Raster um acht Pixel daneben.
TAFEL_RAND = 8


def helligkeit(patch: np.ndarray, kern_perzentil: float) -> float:
    """Dieselbe Groesse, die auch der Lampendetektor bildet.

    Mittelwert ueber die hellsten Pixel des Ausschnitts (Kanalmaximum). Nicht
    ueber alle: Eine Lampe fuellt ihre ROI nie ganz aus, der dunkle Rand
    wuerde den Wert verwaessern.
    """
    if patch.size == 0:
        return 0.0
    value = patch.max(axis=2).astype(np.float32)
    kern = value >= np.percentile(value, kern_perzentil)
    if not kern.any():
        kern = np.ones_like(value, dtype=bool)
    return float(value[kern].mean())


def tafel_ausschnitt(lane) -> tuple[int, int]:
    """Linke obere Ecke des gespeicherten Tafelbildes im Vollframe."""
    xs = [p[0] for p in lane.quad]
    ys = [p[1] for p in lane.quad]
    return (max(0, int(min(xs)) - TAFEL_RAND),
            max(0, int(min(ys)) - TAFEL_RAND))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--radius", type=int, default=3,
                   help="Wie weit die ROI probeweise verschoben wird (Pixel). "
                        "3 reicht: Die Lampen stehen 9 bis 11 Pixel "
                        "auseinander, groessere Suchfenster fielen auf den "
                        "Nachbarn.")
    p.add_argument("--perzentil", type=float, default=99.0,
                   help="Welches Helligkeitsperzentil ueber alle Bilder als "
                        "'so hell wird sie, wenn sie leuchtet' gilt.")
    p.add_argument("--bilder", type=int, default=400,
                   help="Hoechstzahl ausgewerteter Tafelbilder je Bahn.")
    a = p.parse_args()

    cfg = load_config()
    kal = Calibration.load(str(a.kalibrierung))
    versatz = range(-a.radius, a.radius + 1)

    for lane in sorted(kal.lanes, key=lambda x: x.real_lane_number or x.lane_id):
        bahn = lane.real_lane_number or lane.lane_id
        bilder = sorted((a.lauf / f"lane_{lane.lane_id}").glob("event_*/*_tafel.png"))
        if not bilder:
            print(f"Bahn {bahn}: keine Tafelbilder unter "
                  f"{a.lauf / f'lane_{lane.lane_id}'}")
            continue
        # Gleichmaessig ueber den Lauf greifen, nicht die ersten N: Sonst
        # misst man nur die erste Viertelstunde.
        schritt = max(1, len(bilder) // a.bilder)
        bilder = bilder[::schritt]
        stapel = [cv2.imread(str(b)) for b in bilder]
        stapel = [b for b in stapel if b is not None]

        x0, y0 = tafel_ausschnitt(lane)
        transform = lane.transform(cfg.calibration.warped_width,
                                   cfg.calibration.warped_height)

        print(f"\n=== Bahn {bahn} ({len(stapel)} Tafelbilder) ===")
        print(f"{'Kegel':>5} {'p'+str(int(a.perzentil)):>6} "
              f"{'bester Versatz':>15} {'dort':>6} {'Gewinn':>7}")
        for roi in lane.pin_lamps():
            if not roi.enabled:
                continue
            bx, by, bw, bh = norm_rect_to_frame_bbox(transform, roi.rect,
                                                     (1080, 1920, 3))
            bx, by = bx - x0, by - y0
            ergebnis: dict[tuple[int, int], float] = {}
            for dy in versatz:
                for dx in versatz:
                    werte = []
                    for bild in stapel:
                        h, w = bild.shape[:2]
                        yy, xx = by + dy, bx + dx
                        if yy < 0 or xx < 0 or yy + bh > h or xx + bw > w:
                            continue
                        werte.append(helligkeit(
                            bild[yy:yy + bh, xx:xx + bw],
                            cfg.detection.lamps.core_percentile))
                    if werte:
                        ergebnis[(dx, dy)] = float(np.percentile(werte,
                                                                 a.perzentil))
            if not ergebnis:
                continue
            hier = ergebnis.get((0, 0), 0.0)
            best, wert = max(ergebnis.items(), key=lambda kv: kv[1])
            marke = "   <-- deutlich daneben" if wert - hier >= 10 else ""
            print(f"{roi.pin_number:>5} {hier:>6.1f} "
                  f"{str(best):>15} {wert:>6.1f} {wert - hier:>+7.1f}{marke}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
