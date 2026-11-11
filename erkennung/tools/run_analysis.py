"""Analyselauf OHNE Oberflaeche -- Datei oder Stream, von der Kommandozeile.

WARUM ES DAS GIBT: Bis hierher liess sich ein Lauf nur ueber das Fenster
starten. Wer nicht davor sitzt -- ein Skript, ein Dienst, eine Fernwartung --
kam nicht heran, obwohl an der Analyse selbst nichts Grafisches ist. Der Weg
ueber `run_full_analysis.py` half nicht: Der arbeitet fest mit
`FileVideoSource` und kann keinen Stream oeffnen.

Unterschied zu `run_full_analysis.py`: Dieses Werkzeug ist fuer den ECHTEN
Lauf gedacht (Stream, Versand, Echtzeit), jenes fuer das Vermessen einer
Videodatei.

Aufruf:

    .venv/Scripts/python.exe tools/run_analysis.py \
        --source "https://.../rendition.m3u8?..." \
        --calibration data/calibrations/1Spieltag.json \
        --start-frame 1039 --fps 25 --send

Ohne `--send` geht nichts an Supabase -- bewusst, damit ein Probelauf die
Tabelle nicht fuellt.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from collections import Counter
from pathlib import Path

from kegel_cv.analysis.pipeline import AnalysisPipeline
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.detection.state_machine import EventType
from kegel_cv.sinks.factory import build_sink
from kegel_cv.video.factory import open_source, source_label

log = logging.getLogger("run_analysis")

_abbruch = False


def _auf_signal(signum, rahmen) -> None:
    """Strg-C beendet den Lauf GEORDNET.

    Ein harter Abbruch liesse die Senke ungeleert -- die zuletzt erkannten
    Wuerfe waeren dann weg, obwohl sie erkannt waren.
    """
    global _abbruch
    _abbruch = True
    print("\n   Abbruch angefordert -- der Lauf wird geordnet beendet ...",
          flush=True)


def argumente() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True,
                   help="Videodatei oder Stream-Adresse (m3u8, rtsp, ...)")
    p.add_argument("--calibration", required=True, type=Path,
                   help="Kalibrierungsdatei (JSON)")
    p.add_argument("--start-frame", type=int, default=0,
                   help="An dieser Stelle beginnen (Standard: 0)")
    p.add_argument("--until-frame", type=int, default=0,
                   help="Nach diesem Frame aufhoeren (0 = bis zum Ende)")
    p.add_argument("--fps", type=float, default=0.0,
                   help="Tempo drosseln: 25 = Echtzeit, 0 = so schnell wie "
                        "moeglich (Standard)")
    p.add_argument("--send", action="store_true",
                   help="Wurfergebnisse an Supabase senden")
    p.add_argument("--spielname", default="",
                   help="Name der Partie. Geht als `game_name` mit in die "
                        "Datenbank und benennt den Debug-Ordner. Bei mehreren "
                        "Geraeten auf ALLEN denselben Namen setzen -- daran "
                        "finden die Wuerfe wieder zusammen.")
    p.add_argument("--bahnen", default="",
                   help="Nur diese Bahnen erfassen, z. B. '2,3'. Leer = alle "
                        "aus der Kalibrierung. Nicht erfasste Bahnen kosten "
                        "keine Rechenzeit.")
    p.add_argument("--sende-bahnen", dest="sende_bahnen", default="",
                   help="Nur diese Bahnen senden, z. B. '2,3'. Leer = alle "
                        "erfassten. Getrennt von --bahnen, damit sich eine "
                        "Bahn mitrechnen, aber nicht senden laesst.")
    p.add_argument("--config", type=Path, default=None,
                   help="Konfigurationsdatei (Vorgabe: config/default.yaml). "
                        "Fuer die direkte Hallenkamera: "
                        "config/hallenkamera.yaml. ACHTUNG: ERSETZT die "
                        "Vorgabedatei, mischt NICHT -- fuer einen Messlauf "
                        "mit einem geaenderten Wert also eine VOLLKOPIE von "
                        "default.yaml anlegen, sonst fallen alle uebrigen "
                        "Werte auf die Schema-Vorgaben zurueck.")
    p.add_argument("--quiet", action="store_true",
                   help="Nur Fortschritt, keine Ereignismeldungen")
    return p.parse_args()


def main() -> int:
    a = argumente()
    logging.basicConfig(
        level=logging.WARNING if a.quiet else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)-28s %(message)s")
    signal.signal(signal.SIGINT, _auf_signal)

    cfg = load_config(a.config)

    def bahnliste(text: str, wofuer: str) -> list[int]:
        """'2,3' zu [2, 3]. Ein Tippfehler soll sofort auffallen, nicht erst
        daran, dass eine Bahn stumm bleibt."""
        werte = []
        for teil in text.replace(";", ",").split(","):
            teil = teil.strip()
            if not teil:
                continue
            if not teil.isdigit():
                raise SystemExit(f"--{wofuer}: '{teil}' ist keine Bahnnummer")
            werte.append(int(teil))
        return werte

    if a.bahnen:
        cfg.processing.lanes = bahnliste(a.bahnen, "bahnen")
    if a.sende_bahnen:
        cfg.output.lanes = bahnliste(a.sende_bahnen, "sende-bahnen")

    if not a.send:
        cfg.output.supabase.enabled = False
        print("   Versand AUS (mit --send einschalten)")

    kennung = source_label(a.source)
    cal = Calibration.load(a.calibration)
    pipe = AnalysisPipeline(cal, cfg, video_id=kennung,
                            game_name=a.spielname)
    sink = build_sink(cfg, video_id=kennung, game_name=a.spielname)

    src = open_source(a.source, cfg)
    src.open()
    info = src.info
    print(f"Quelle       : {kennung}")
    print(f"               {info.width}x{info.height}, {info.fps:.1f} fps")
    print(f"Kalibrierung : {a.calibration.name}")
    if a.spielname:
        print(f"Spiel        : {a.spielname}")
    if cfg.processing.lanes:
        print(f"Erfasst      : Bahnen {sorted(cfg.processing.lanes)}")
    if cfg.output.lanes:
        print(f"Gesendet     : Bahnen {sorted(cfg.output.lanes)}")
    print(f"Tempo        : "
          + (f"{a.fps:g} fps" if a.fps > 0 else "so schnell wie moeglich"))

    if a.start_frame > 0 and not src.seek(a.start_frame):
        print(f"   Sprung auf Frame {a.start_frame} nicht moeglich -- es wird "
              f"von vorn gelesen.")

    erster = src.read()
    if erster is None:
        print("FEHLER: Quelle liefert keine Frames")
        return 1
    pipe.prepare(erster.image.shape)
    print(f"Beginnt bei  : Frame {erster.index}\n")

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

    wuerfe = []
    frame = erster
    begonnen = time.perf_counter()
    letzte_meldung = begonnen
    # Fester Zeitplan statt gemessener Abstaende -- sonst summiert sich die
    # Ungenauigkeit jedes Schlafens auf (2026-08-30 gemessen: 1,12faches Tempo
    # bei eingestellten 25 fps).
    naechster_takt = begonnen
    gelesen = 0

    while frame is not None and not _abbruch:
        neue = pipe.process(frame).throws
        wuerfe.extend(neue)
        for wurf in neue:
            sink.send(wurf)
        gelesen += 1

        if a.until_frame and frame.index >= a.until_frame:
            print(f"\n   Endmarke Frame {a.until_frame} erreicht.")
            break

        jetzt = time.perf_counter()
        if jetzt - letzte_meldung >= 30.0:
            video_s = (frame.index - erster.index) / info.fps
            wand_s = jetzt - begonnen
            print(f"   Frame {frame.index} ({frame.index / info.fps / 60:5.1f} min "
                  f"Video) | {len(wuerfe)} Wuerfe | "
                  f"{sum(zyklen.values())} Gruenzyklen | "
                  f"Tempo {video_s / max(wand_s, 1e-9):.2f}x", flush=True)
            letzte_meldung = jetzt

        if a.fps > 0:
            naechster_takt += 1.0 / a.fps
            rest = naechster_takt - time.perf_counter()
            if rest > 0:
                time.sleep(rest)
            else:
                # Nicht aufholen wollen -- sonst laeuft die Analyse
                # anschliessend ungebremst, bis der Rueckstand weg ist.
                naechster_takt = time.perf_counter()

        frame = src.read()

    src.close()
    pipe.close()
    sink.flush()
    sink.close()

    dauer = time.perf_counter() - begonnen
    print(f"\nFertig nach {dauer / 60:.1f} min, {gelesen} Frames gelesen")
    print(f"Gruenzyklen {sum(zyklen.values())} | Wuerfe {len(wuerfe)}")
    if wuerfe:
        print(f"Status: {dict(Counter(t.status.value for t in wuerfe))}")
    if sum(zyklen.values()) > len(wuerfe):
        print(f"ACHTUNG: {sum(zyklen.values()) - len(wuerfe)} Gruenzyklen ohne "
              f"Wurfergebnis -- fehlendes faellt sonst nicht auf (BUG-008).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
