"""Misst, was die untere Reihe beim Spielwechsel anzeigt -- MESSUNG, kein Umbau.

Der Nutzer beschreibt (2026-08-28): "irgendwann erscheint ploetzlich in der
unteren Reihe (meistens nach 30 Wurf, aber nicht immer) `000  0000`, das
passiert dann eigentlich ueber alle Bahnen. Dann muss wieder neu gezaehlt
werden."

Heute erkennt das Werkzeug den Spielwechsel indirekt: Die Wurfnummer faellt von
einem hohen Wert auf einen kleinen. Das setzt voraus, dass die Wurfnummer im
richtigen Moment LESBAR ist. Der beschriebene Nullzustand waere ein direkteres
Zeichen -- aber ob er im Bild ueberhaupt messbar ist, und wie lange er steht,
ist bisher nicht nachgesehen worden.

Diese Datei sieht nach. Sie aendert nichts. Gefragt wird:

    1. Steht `000` und `0000` tatsaechlich in der Anzeige, lesbar?
    2. Ueber wie viele Frames?
    3. Wirklich auf allen Bahnen gleichzeitig?

Aufruf:
    .venv/Scripts/python.exe tools/measure_display_reset.py [VIDEO] [KALIBRIERUNG]
    .venv/Scripts/python.exe tools/measure_display_reset.py --fenster 13:00-14:00
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.video import FileVideoSource

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/anzeige_reset.csv")

# Die drei Satzgrenzen aus dem Wurfprotokoll, grosszuegig eingerahmt.
# Gemessen ueber den Ruecksprung der Wurfnummer: 13:25-13:38, 26:06-26:27,
# 39:45-40:14 -- die Bahnen wechseln nicht gleichzeitig.
FENSTER = ["12:50-14:10", "25:40-26:50", "39:20-40:40"]
ABSTAND = 5          # jeden n-ten Frame lesen
FELDER = ["throw_number", "pin_count", "total_b"]


def zeit_zu_frame(text: str, fps: float) -> int:
    minuten, sekunden = text.split(":")
    return int((int(minuten) * 60 + int(sekunden)) * fps)


def zeit(frame: int, fps: float) -> str:
    s = frame / fps
    return f"{int(s // 60)}:{s % 60:05.2f}"


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    # `--fenster` traegt einen Wert -- der darf nicht als Videopfad durchgehen.
    roh = sys.argv[1:]
    fenster = FENSTER
    argumente = []
    i = 0
    while i < len(roh):
        if roh[i] == "--fenster":
            fenster = roh[i + 1].split(",")
            i += 2
            continue
        if not roh[i].startswith("--"):
            argumente.append(roh[i])
        i += 1

    video = argumente[0] if argumente else VIDEO
    kalibrierung = argumente[1] if len(argumente) > 1 else KALIBRIERUNG

    cfg = load_config()
    cal = Calibration.load(kalibrierung)
    src = FileVideoSource(video)
    src.open()
    info = src.info
    erster = src.read()

    prozessoren = {}
    for lane in cal.lanes:
        p = LaneProcessor(lane, cfg)
        if p.prepare(erster.image.shape):
            prozessoren[lane.display_number] = p
    bahnen = sorted(prozessoren)
    print(f"Video: {info.source_id} | Bahnen {bahnen}\n")

    zeilen: list[dict] = []

    for spanne in fenster:
        von_text, bis_text = spanne.split("-")
        von = zeit_zu_frame(von_text, info.fps)
        bis = zeit_zu_frame(bis_text, info.fps)
        print("=" * 78)
        print(f"FENSTER {spanne}   (Frame {von} bis {bis})")
        print("=" * 78)

        src.seek(von)
        nullzustaende: dict[int, list[int]] = {dn: [] for dn in bahnen}

        frame = src.read()
        while frame is not None and frame.index <= bis:
            if frame.index % ABSTAND == 0:
                zeile = {"Frame": frame.index, "Zeit": zeit(frame.index, info.fps)}
                for dn, p in prozessoren.items():
                    lesungen = p.read_digits(frame)
                    werte = {}
                    for feld in FELDER:
                        lesung = lesungen.get(feld)
                        werte[feld] = (lesung.value
                                       if lesung is not None and lesung.is_readable
                                       else None)
                        zeile[f"B{dn}_{feld}"] = (
                            "" if werte[feld] is None else werte[feld])
                    # Der beschriebene Zustand: Wurfnummer UND Summe auf null.
                    # Die Kegelzahl bleibt aussen vor -- eine Null dort ist ein
                    # ganz normaler Fehlwurf.
                    if werte["throw_number"] == 0 and werte["total_b"] == 0:
                        nullzustaende[dn].append(frame.index)
                zeilen.append(zeile)
            frame = src.read()

        for dn in bahnen:
            treffer = nullzustaende[dn]
            if not treffer:
                print(f"  Bahn {dn}: KEIN Nullzustand gefunden")
                continue
            print(f"  Bahn {dn}: {len(treffer)} Messungen mit 000/0000, "
                  f"Frame {treffer[0]}-{treffer[-1]} "
                  f"({zeit(treffer[0], info.fps)} bis {zeit(treffer[-1], info.fps)}, "
                  f"{(treffer[-1] - treffer[0]) / info.fps:.1f} s)")

        beginn = {dn: v[0] for dn, v in nullzustaende.items() if v}
        if len(beginn) > 1:
            spanne_s = (max(beginn.values()) - min(beginn.values())) / info.fps
            print(f"\n  Zwischen der ersten und der letzten Bahn liegen "
                  f"{spanne_s:.1f} s.")
            print("  -> " + ("gleichzeitig genug fuer ein gemeinsames Zeichen"
                             if spanne_s < 2 else
                             "NICHT gleichzeitig -- je Bahn eigenstaendig zu werten"))
        print()

    src.close()

    if zeilen:
        AUSGABE.parent.mkdir(parents=True, exist_ok=True)
        felder = ["Frame", "Zeit"] + [f"B{dn}_{f}" for dn in bahnen for f in FELDER]
        with AUSGABE.open("w", encoding="utf-8-sig", newline="") as datei:
            schreiber = csv.DictWriter(datei, fieldnames=felder, delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(zeilen)
        print(f"Messreihe: {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
