"""Vollstaendiger Analyselauf ueber ein ganzes Video.

Zweck: Phase 11 (Robustheit). Der Lauf ueber acht Minuten sagt wenig darueber,
wie sich die Erkennung ueber ein ganzes Training verhaelt -- Bahnen wechseln,
Spiele enden, die Anzeige wird zurueckgesetzt.

Aufruf:
    .venv/Scripts/python.exe tools/run_full_analysis.py [VIDEO] [KALIBRIERUNG]
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from pathlib import Path

from kegel_cv.analysis.pipeline import AnalysisPipeline
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.sinks.factory import build_sink
from kegel_cv.detection.state_machine import EventType
from kegel_cv.video import FileVideoSource

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits.json"
AUSGABE = Path("debug/vollauswertung.json")


def main() -> int:
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    video = argumente[0] if argumente else VIDEO
    kalibrierung = argumente[1] if len(argumente) > 1 else KALIBRIERUNG

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    cfg = load_config()
    # Debug-Frames abschalten: Bei rund 450 Wuerfen zu je 44 Bildern waeren das
    # ueber 20 000 Dateien. Fuer die Auswertung genuegt die JSON-Ausgabe.
    cfg.debug.save_frames = False

    # Der Versand ist hier bewusst AUS, auch wenn er konfiguriert ist: Dieses
    # Werkzeug dient dem Messen und wird beim Vergleichen mehrfach laufen
    # gelassen. Es wuerde die Tabelle sonst bei jedem Durchlauf mit denselben
    # Wuerfen fuellen. Mit --send laesst es sich einschalten.
    versenden = "--send" in sys.argv
    if not versenden:
        cfg.output.supabase.enabled = False

    cal = Calibration.load(kalibrierung)
    pipe = AnalysisPipeline(cal, cfg, video_id=Path(video).name)
    sink = build_sink(cfg, video_id=Path(video).name)

    src = FileVideoSource(video)
    src.open()
    info = src.info
    print(f"Video      : {info.source_id}")
    print(f"             {info.frame_count} Frames, {info.fps:.1f} fps "
          f"-> {info.frame_count / info.fps / 60:.1f} Minuten")
    print(f"Kalibrierung: {Path(kalibrierung).name}\n")

    first = src.read()
    if first is None:
        print("FEHLER: Video liefert keine Frames")
        return 1
    pipe.prepare(first.image.shape)

    # Gruenzyklen unabhaengig mitzaehlen -- die einzige Groesse, die sagt, ob
    # ein Wurf UEBERSEHEN wurde (siehe BUG-008).
    zyklen: Counter[int] = Counter()
    for processor in pipe.processors:
        def wrap(proc, original):
            def inner(*args, **kwargs):
                event = original(*args, **kwargs)
                if event is not None and event.event is EventType.GREEN_OFF:
                    zyklen[proc.display_number] += 1
                return event
            return inner
        processor.state_machine.update = wrap(processor,
                                              processor.state_machine.update)

    throws = []
    frame = first
    begonnen = time.perf_counter()
    n_frames = 0
    letzte_meldung = begonnen

    while frame is not None:
        neue = pipe.process(frame).throws
        throws.extend(neue)
        for wurf in neue:
            sink.send(wurf)
        frame = src.read()
        n_frames += 1
        jetzt = time.perf_counter()
        if jetzt - letzte_meldung >= 30.0:
            anteil = n_frames / max(1, info.frame_count)
            verbleibend = (jetzt - begonnen) / max(anteil, 1e-9) * (1 - anteil)
            print(f"   {anteil * 100:5.1f} %  ({n_frames} Frames, "
                  f"{len(throws)} Wuerfe, noch ca. {verbleibend / 60:.1f} min)",
                  flush=True)
            letzte_meldung = jetzt
    src.close()
    pipe.close()
    sink.flush()
    sink.close()

    dauer = time.perf_counter() - begonnen
    daten = {
        "video": info.source_id,
        "frames": n_frames,
        "dauer_s": round(dauer, 1),
        "ms_pro_frame": round(dauer / max(1, n_frames) * 1000, 2),
        "gruenzyklen": dict(zyklen),
        "wuerfe": [t.to_dict() for t in throws],
    }
    AUSGABE.parent.mkdir(parents=True, exist_ok=True)
    AUSGABE.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")

    print(f"\nFertig in {dauer / 60:.1f} min ({daten['ms_pro_frame']} ms/Frame)")
    print(f"Gruenzyklen {sum(zyklen.values())} | Wuerfe {len(throws)}")
    print(f"Status: {dict(Counter(t.status.value for t in throws))}")
    print(f"Ergebnis geschrieben: {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
