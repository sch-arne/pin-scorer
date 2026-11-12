"""Warum wird eine Ziffer verworfen? Zaehlt die Gruende einzeln.

ANLASS (2026-09-03): Ein Wurfbeleg zeigte auf Bahn 4 eine unuebersehbare "9"
im Kegelzahl-Feld -- die Wurfzeile trug trotzdem "Tafel unlesbar". Aus
`wuerfe.csv` allein ist nur zu sehen, DASS die Spalte leer blieb, nicht warum.

DIE DREI AUSSTIEGE in `CalibratedDigitReader.read_digit_full`:

    1. zu dunkel     -- Helligkeit unter `min_display_brightness`
    2. keine Maske   -- die Rotmaske ist leer, es leuchtet nichts Rotes
    3. kein Muster   -- Maske vorhanden, aber die sieben Segmente ergeben
                        keine gueltige Ziffer

Nur der DRITTE Fall ist ein Erkennungsproblem. Die ersten beiden heissen, dass
im Bild tatsaechlich nichts steht -- waehrend der Wurf laeuft, ist das Feld
geloescht, und das ist der Normalfall.

Diese Unterscheidung entscheidet, ob sich an der Ziffernerkennung ueberhaupt
etwas holen laesst: Sind die Ausfaelle ueberwiegend Fall 1 und 2, waere ein
besseres Verfahren wirkungslos -- es gaebe nichts zu lesen.

AUFRUF:

    .venv/Scripts/python.exe tools/measure_digit_rejects.py \
        --source <Datei oder Stream-URL> \
        --calibration data/calibrations/1Spieltag_enge_lampen.json \
        --von 14000 --bis 24000 --feld pin_count
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration, norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.detection.digit_reader import CalibratedDigitReader  # noqa: E402


def stellen_von(lane, feld: str) -> list:
    """Die einzeln eingerahmten Stellen eines Feldes, in Lesereihenfolge."""
    praefix = f"digit_{feld}_"
    stellen = [r for r in lane.rois if r.name.startswith(praefix) and r.enabled]
    return sorted(stellen, key=lambda r: r.rect[0])


def grund(reader: CalibratedDigitReader, patch: np.ndarray,
          cfg) -> tuple[str, str]:
    """(gelesenes Zeichen, Grund) -- die Gruende wie im Reader selbst."""
    if patch is None or patch.size == 0:
        return "?", "kein Ausschnitt"

    if cfg.brightness_percentile >= 100.0:
        helligkeit = float(patch[:, :, 2].max())
    else:
        helligkeit = float(np.percentile(patch[:, :, 2],
                                         cfg.brightness_percentile))
    if helligkeit < cfg.min_display_brightness:
        return "?", "zu dunkel"

    maske = reader._preprocessor._red_mask(patch)
    if maske.max() == 0:
        return "?", "keine Maske"

    zeichen, _, _ = reader.read_digit_full(patch)
    if zeichen == "?":
        return "?", "kein Muster"
    return zeichen, "gelesen"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--von", type=int, default=14000)
    p.add_argument("--bis", type=int, default=24000)
    p.add_argument("--schritt", type=int, default=25)
    p.add_argument("--feld", default="pin_count")
    a = p.parse_args()

    cfg = load_config()
    cal = Calibration.load(a.calibration)
    reader = CalibratedDigitReader(cfg.detection.digits)
    transforms = {l.lane_id: l.transform(cfg.calibration.warped_width,
                                         cfg.calibration.warped_height)
                  for l in cal.lanes}

    cap = cv2.VideoCapture(a.source)
    if not cap.isOpened():
        print(f"Quelle nicht lesbar: {a.source}")
        return 1
    if a.von > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, a.von)
        erreicht = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if abs(erreicht - a.von) > 5000:
            print(f"Sprung nach {a.von} landete bei {erreicht} -- Abbruch.")
            cap.release()
            return 1

    zaehler: dict[int, collections.Counter] = collections.defaultdict(
        collections.Counter)
    # Fuer den interessanten Fall: Was stand da, als kein Muster erkannt wurde?
    proben: list[tuple[int, int, float]] = []

    frame = a.von
    try:
        while frame < a.bis:
            if not cap.grab():
                print(f"Quelle endet bei Frame {frame}")
                break
            if (frame - a.von) % a.schritt == 0:
                ok, bild = cap.retrieve()
                if ok:
                    for lane in cal.lanes:
                        bahn = lane.display_number
                        for roi in stellen_von(lane, a.feld):
                            x, y, w, h = norm_rect_to_frame_bbox(
                                transforms[lane.lane_id], roi.rect, bild.shape)
                            if w <= 0 or h <= 0:
                                continue
                            patch = bild[y:y + h, x:x + w]
                            zeichen, warum = grund(reader, patch,
                                                   cfg.detection.digits)
                            zaehler[bahn][warum] += 1
                            if warum == "kein Muster" and len(proben) < 40:
                                hell = float(np.percentile(
                                    patch[:, :, 2],
                                    cfg.detection.digits.brightness_percentile)
                                    if cfg.detection.digits.brightness_percentile < 100
                                    else patch[:, :, 2].max())
                                proben.append((frame, bahn, hell))
                if (frame - a.von) % (a.schritt * 100) == 0:
                    print(f"  Frame {frame} ...", flush=True)
            frame += 1
    finally:
        cap.release()

    print(f"\n=== Feld '{a.feld}', Frames {a.von}-{a.bis} alle {a.schritt} ===")
    print(f"{'Bahn':>4} {'Messungen':>10} {'gelesen':>10} {'zu dunkel':>11} "
          f"{'keine Maske':>12} {'KEIN MUSTER':>12}")
    gesamt = collections.Counter()
    for bahn in sorted(zaehler):
        z = zaehler[bahn]
        n = sum(z.values())
        gesamt.update(z)
        print(f"{bahn:>4} {n:>10} "
              f"{100*z['gelesen']/n:>9.1f}% {100*z['zu dunkel']/n:>10.1f}% "
              f"{100*z['keine Maske']/n:>11.1f}% {100*z['kein Muster']/n:>11.1f}%")
    n = sum(gesamt.values())
    print(f"{'alle':>4} {n:>10} {100*gesamt['gelesen']/n:>9.1f}% "
          f"{100*gesamt['zu dunkel']/n:>10.1f}% "
          f"{100*gesamt['keine Maske']/n:>11.1f}% "
          f"{100*gesamt['kein Muster']/n:>11.1f}%")

    print("\nNur 'KEIN MUSTER' ist ein Erkennungsproblem -- dort steht etwas,")
    print("das nicht gelesen wird. 'zu dunkel' und 'keine Maske' heissen, dass")
    print("das Feld geloescht war; waehrend eines Wurfs ist das der Normalfall.")
    if proben:
        print(f"\nErste Faelle mit Muster-Fehlschlag (Frame, Bahn, Helligkeit):")
        for f, b, hell in proben[:12]:
            print(f"  Frame {f:>7}  Bahn {b}  Helligkeit {hell:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
