"""Vergleicht Messzeitpunkte fuer die Kegellampen -- MESSUNG, kein Umbau.

Frage: Ist der exakte GREEN_OFF-Frame besser als die Aggregation ueber das
ganze Fenster? Der Nutzer beschreibt die Anlage so, dass ab GREEN_OFF kein Kegel
mehr fallen kann -- dann waere der einzelne Frame die reinere Quelle.

Dagegen steht: Fallen alle neun, blinken die Lampen (Spezialeffekt). Ein
einzelner Frame kann dann in eine Dunkelphase fallen.

Gemessen wird gegen die angezeigte Kegelzahl als Wahrheit -- nur dort, wo sie
eindeutig lesbar ist.

Aufruf:
    .venv/Scripts/python.exe tools/measure_measurement_point.py
"""

from __future__ import annotations

import json
import logging
import sys
from collections import Counter
from pathlib import Path

from kegel_cv.analysis.pipeline import AnalysisPipeline
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.models.readings import aggregate_pin_readings
from kegel_cv.video import FileVideoSource

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/messzeitpunkt.json")


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    cfg = load_config()
    cfg.debug.save_frames = False
    cal = Calibration.load(sys.argv[2] if len(sys.argv) > 2 else KALIBRIERUNG)
    pipe = AnalysisPipeline(cal, cfg, video_id="messung")

    src = FileVideoSource(sys.argv[1] if len(sys.argv) > 1 else VIDEO)
    src.open()
    info = src.info
    first = src.read()
    pipe.prepare(first.image.shape)

    daten: list[dict] = []

    # Beim Auswerten eines Ereignisses BEIDE Varianten festhalten.
    original = pipe._evaluate_sample

    def beobachtet(processor, sample):
        # Variante A: der Lampenstand im exakten GREEN_OFF-Frame
        exakt = processor.result_pins
        # Variante B: die Aggregation ueber das ganze Fenster (wie im Betrieb)
        fenster = aggregate_pin_readings(list(processor.result_samples)) or exakt
        grundlinie = processor.baseline_pins
        basis = set(grundlinie.pins) if grundlinie is not None else set()

        throw = original(processor, sample)
        if throw is not None:
            daten.append({
                "lane": processor.display_number,
                "throw": throw.throw_number,
                "frame": throw.source_frame,
                "digit": throw.displayed_pin_count,
                "exakt": len(set(exakt.pins) - basis) if exakt else None,
                "fenster": len(set(fenster.pins) - basis) if fenster else None,
                "gebucht": throw.pins_count,
            })
        return throw

    pipe._evaluate_sample = beobachtet

    frame = first
    while frame is not None:
        pipe.process(frame)
        frame = src.read()
    src.close()

    AUSGABE.parent.mkdir(parents=True, exist_ok=True)
    AUSGABE.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")

    pruefbar = [d for d in daten if d["digit"] is not None]
    print(f"{len(daten)} Wuerfe, davon {len(pruefbar)} mit eindeutiger Ziffer\n")
    print(f"{'Variante':<34}{'stimmig':>9}{'Anteil':>9}")
    for name, feld in (("nur GREEN_OFF-Frame", "exakt"),
                       ("Aggregation ueber das Fenster", "fenster")):
        ok = sum(1 for d in pruefbar if d[feld] == d["digit"])
        print(f"{name:<34}{ok:>9}{100 * ok / max(1, len(pruefbar)):>8.1f} %")

    nur_a = [d for d in pruefbar if d["exakt"] == d["digit"] != d["fenster"]]
    nur_b = [d for d in pruefbar if d["fenster"] == d["digit"] != d["exakt"]]
    print(f"\nnur der GREEN_OFF-Frame richtig : {len(nur_a)}")
    print(f"nur die Aggregation richtig     : {len(nur_b)}")
    print(f"\nWo nur der einzelne Frame trifft (erste 10):")
    for d in nur_a[:10]:
        print(f"   Bahn {d['lane']} W{d['throw']:>3} F{d['frame']}: "
              f"exakt={d['exakt']} Fenster={d['fenster']} Ziffer={d['digit']}")
    print(f"\nWo nur die Aggregation trifft (erste 10):")
    for d in nur_b[:10]:
        print(f"   Bahn {d['lane']} W{d['throw']:>3} F{d['frame']}: "
              f"exakt={d['exakt']} Fenster={d['fenster']} Ziffer={d['digit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
