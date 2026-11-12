"""Sind Nullwuerfe an der Tafel ueberhaupt erkennbar? -- MESSUNG, kein Umbau.

Befund vom 2026-08-28: Faellt bei einem Wurf KEIN Kegel, schaltet die Anlage die
gruene Lampe nicht aus. Es gibt nichts zu zaehlen und nichts aufzustellen -- die
Bahn bleibt freigegeben, der Spieler wirft weiter. Belegt an der Gruenspur:

    Bahn 4   F16366 gruen AN ... F17477 gruen AUS   (1111 Frames, EINE Phase)
             darin Wurf 28 (0 Kegel) und Wurf 29 (1 Kegel)
    Bahn 2   F50986 gruen AN ... F51566 gruen AUS   (580 Frames)
             darin Wurf 18 (0 Kegel) und Wurf 19 (2 Kegel)

Damit ist ein Nullwurf fuer den Gruenlampen-Trigger strukturell unsichtbar. Die
Frage ist, ob die ANZEIGE ihn verraet. Zwei Kandidaten:

    1. Die Wurfnummer springt um zwei statt um eins
    2. Der Fehlwurfzaehler links zaehlt hoch (Q2: er zaehlt die Nullwuerfe)

Die Summe scheidet aus -- ein Nullwurf addiert null, sie bleibt stehen.

Diese Datei liest beide Felder ueber die betroffenen Gruenphasen hinweg Frame
fuer Frame. Sie aendert nichts.

Aufruf:
    .venv/Scripts/python.exe tools/measure_zero_throws.py [VIDEO] [KALIBRIERUNG]
"""

from __future__ import annotations

import csv
import logging
import sys
from collections import Counter
from pathlib import Path

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.video import FileVideoSource

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/nullwuerfe.csv")

# Die beiden im Protokoll belegten Nullwuerfe, grosszuegig eingerahmt:
# vom Wurf davor bis zum Wurf danach.
FAELLE = [
    {"bahn": 4, "von": 16100, "bis": 18050, "satz": 1, "wurf": 28,
     "davor": "W27 = 8 Kegel (F16168)", "danach": "W29 = 1 Kegel (F17502)"},
    {"bahn": 2, "von": 50700, "bis": 51650, "satz": 3, "wurf": 18,
     "davor": "W17 = 1 Kegel (F50794)", "danach": "W19 = 2 Kegel (F51568)"},
]
ABSTAND = 5
FELDER = ["throw_number", "pin_count", "total_b", "left_display"]


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
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

    zeilen: list[dict] = []

    for fall in FAELLE:
        p = prozessoren.get(fall["bahn"])
        if p is None:
            continue
        print("=" * 74)
        print(f"Bahn {fall['bahn']}, Satz {fall['satz']}, Wurf {fall['wurf']} "
              f"= 0 Kegel (im Protokoll)")
        print(f"   davor : {fall['davor']}")
        print(f"   danach: {fall['danach']}")
        print("=" * 74)

        src.seek(fall["von"])
        verlauf: dict[str, list[tuple[int, int]]] = {f: [] for f in FELDER}

        frame = src.read()
        while frame is not None and frame.index <= fall["bis"]:
            if frame.index % ABSTAND == 0:
                lesungen = p.read_digits(frame)
                zeile = {"Bahn": fall["bahn"], "Frame": frame.index,
                         "Zeit": f"{int(frame.timestamp // 60)}:"
                                 f"{frame.timestamp % 60:05.2f}"}
                for feld in FELDER:
                    lesung = lesungen.get(feld)
                    wert = (lesung.value
                            if lesung is not None and lesung.is_readable else None)
                    zeile[feld] = "" if wert is None else wert
                    if wert is not None:
                        verlauf[feld].append((frame.index, wert))
                zeilen.append(zeile)
            frame = src.read()

        # Je Feld: die Wertwechsel, das ist die eigentliche Information
        for feld in FELDER:
            werte = verlauf[feld]
            if not werte:
                print(f"   {feld:<14} nie lesbar")
                continue
            wechsel = []
            letzter = None
            for f, w in werte:
                if w != letzter:
                    wechsel.append((f, w))
                    letzter = w
            lesbar = 100 * len(werte) / max(1, len(zeilen))
            folge = " -> ".join(f"{w}@F{f}" for f, w in wechsel[:10])
            print(f"   {feld:<14} {folge}")
            haeufig = Counter(w for _, w in werte).most_common(3)
            print(f"   {'':<14} haeufigste Werte: {haeufig}")
        print()

    src.close()

    if zeilen:
        AUSGABE.parent.mkdir(parents=True, exist_ok=True)
        with AUSGABE.open("w", encoding="utf-8-sig", newline="") as datei:
            schreiber = csv.DictWriter(datei, fieldnames=list(zeilen[0]),
                                       delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(zeilen)
        print(f"Messreihe: {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
