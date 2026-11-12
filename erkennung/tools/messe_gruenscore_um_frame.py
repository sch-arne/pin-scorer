"""Misst den rohen Gruen-Score frameweise um eine Liste von Frames.

WOZU: Trennt "Spielsperre-Lockzyklus" (Bug #2, vier Faelle) von
"Personenverdeckung" (Bug #1, drei Faelle) -- Nutzerhypothese: Ein echter
Gruen-Aus-Zyklus faellt in EINEM Frame wirklich auf 0, eine blosse Verdeckung
nicht (oder umgekehrt). Muss gemessen werden, nicht geraten.

Liest den Gruen-Score direkt ueber `green_detector.detect()` -- wie
`export_problem_clips.py` es tut -- statt `LaneProcessor.process()`
aufzurufen: So bleibt der Zustandsautomat (Occlusion-Zaehler, Reset-Latch)
unberuehrt und jeder Frame liefert einen unverfaelschten Rohwert.

AUFRUF:

    .venv/Scripts/python.exe tools/messe_gruenscore_um_frame.py \
        --source <Stream-URL> --calibration <Pfad> \
        --fall BAHN:FRAME[:LABEL] [--fall ...] --fenster 150
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kegel_cv.analysis.lane_processor import LaneProcessor  # noqa: E402
from kegel_cv.calibration import Calibration  # noqa: E402
from kegel_cv.config.loader import load_config  # noqa: E402
from kegel_cv.video.factory import open_source  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--fall", action="append", required=True,
                   help="BAHN:FRAME[:LABEL], mehrfach angebbar")
    p.add_argument("--fenster", type=int, default=150,
                   help="Frames vor UND nach dem Zielframe (Standard 150)")
    a = p.parse_args()

    cfg = load_config()
    cal = Calibration.load(a.calibration)

    faelle = []
    for f in a.fall:
        teile = f.split(":")
        bahn, frame = int(teile[0]), int(teile[1])
        label = teile[2] if len(teile) > 2 else ""
        faelle.append((bahn, frame, label))
    faelle.sort(key=lambda t: t[1])

    ergebnisse = {}

    for bahn, ziel, label in faelle:
        von, bis = max(0, ziel - a.fenster), ziel + a.fenster
        print(f"\n=== Bahn {bahn} Frame {ziel} {label} "
              f"(Fenster {von}-{bis}) ===")

        quelle = open_source(a.source, cfg)
        quelle.open()
        erster = quelle.read()
        lane_cal = next(l for l in cal.lanes if l.display_number == bahn)
        proz = LaneProcessor(lane_cal, cfg)
        if not proz.prepare(erster.image.shape):
            print(f"  Bahn {bahn} nicht kalibrierbar -- uebersprungen")
            quelle.close()
            continue

        quelle.seek(von)
        frame = quelle.read()
        werte = []
        while frame is not None and frame.index <= bis:
            gruen = proz.green_detector.detect(
                proz._crop(frame.image, proz._green_box))  # noqa: SLF001
            score = gruen.score
            werte.append((frame.index, score))
            unter = score < cfg.detection.green.occlusion_score
            markiert = abs(frame.index - ziel) <= 2
            if markiert or unter or frame.index % 5 == 0:
                flagge = " VERDECKT" if unter else ""
                stern = " <== ZIEL" if markiert else ""
                print(f"  F{frame.index:>7}  Score {score:6.2f}{flagge}{stern}")
            frame = quelle.read()
        quelle.close()

        if werte:
            minimum = min(werte, key=lambda t: t[1])
            print(f"  --> Minimum im Fenster: Score {minimum[1]:.2f} "
                  f"bei F{minimum[0]}")
            ergebnisse[(bahn, ziel, label)] = minimum[1]

    if ergebnisse:
        print("\n=== Zusammenfassung ===")
        for (bahn, ziel, label), minimum in ergebnisse.items():
            print(f"  Bahn {bahn} F{ziel:<8} {label:<20} Minimum {minimum:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
