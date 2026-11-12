"""Prueft den Fehlwurfzaehler ueber das ganze Video -- MESSUNG.

Vorgeschichte: Bei einem Wurf ohne Kegel schaltet die Anlage die gruene Lampe
nicht aus (Q10) -- der Wurf ist fuer den Trigger unsichtbar. Der Fehlwurfzaehler
im linken Display (Q2) ist die einzige unabhaengige Quelle dafuer.

Er galt als unlesbar (0 von 36 789 Messungen). Tatsaechlich war er nie
AKTIVIERT: `enabled: false`, und der Rahmen deckte nur den oberen Teil der
Ziffern ab. Mit stellenweise gesetzten Rahmen (tools/pin_left_display.py)
liefert er auf Bahn 2:

    Fenster um den bekannten Nullwurf   0 -> 1 bei F51190
    Kontrollfenster ohne Nullwurf       durchgehend 0 (4 Einzelframe-Ausreisser)

DIESE DATEI PRUEFT DIE VORHERSAGE. Das Wurfprotokoll sagt: Bahn 2 hat GENAU
EINEN Nullwurf in 120 Wuerfen (Satz 3, Wurf 18). Der Zaehler darf also ueber das
ganze Video genau einmal hochzaehlen -- abgesehen von den Ruecksetzungen beim
Spielwechsel.

Findet die Messung mehr Anstiege, taugt der Zaehler nicht. Findet sie genau
einen an der richtigen Stelle, ist die Nullwurf-Erkennung geloest.

Aufruf:
    .venv/Scripts/python.exe tools/verify_foul_counter.py
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
from kegel_cv.video import FileVideoSource, FrameBuffer

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = ("data/calibrations/"
                "kalibrierung_2026-08-25_0950_allDigits_neu_2_leftdisplay.json")
AUSGABE = Path("debug/fehlwurfzaehler.csv")

BAHN = 2           # nur diese Bahn ist stellenweise kalibriert
ABSTAND = 5
STABIL = 5         # Messungen in Folge -> 25 Frames = 1 Sekunde

# Erwartung aus dem Wurfprotokoll
ERWARTET_FRAME = 51190
ERWARTET_TOLERANZ = 400


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    cfg = load_config()
    cal = Calibration.load(KALIBRIERUNG)
    src = FileVideoSource(VIDEO)
    src.open()
    info = src.info
    erster = src.read()

    p = None
    for lane in cal.lanes:
        kandidat = LaneProcessor(lane, cfg)
        if kandidat.prepare(erster.image.shape) and lane.display_number == BAHN:
            p = kandidat
    if p is None:
        print(f"Bahn {BAHN} nicht gefunden")
        return 1
    if "left_display" not in p._digit_cell_boxes:
        print("left_display ist nicht stellenweise kalibriert -- zuerst "
              "tools/pin_left_display.py")
        return 1
    print(f"Video: {info.source_id} | Bahn {BAHN} | {info.frame_count} Frames")
    print(f"Stabil ab {STABIL} Messungen ({STABIL * ABSTAND} Frames)\n")

    buffer = FrameBuffer(cfg.processing.frame_buffer_size)
    werte: list[tuple[int, int]] = []
    lesbar = gesamt = 0

    frame = erster
    n = 0
    while frame is not None:
        buffer.append(frame)
        p.process(frame, buffer)          # damit die Zustandsmaschine mitlaeuft
        if frame.index % ABSTAND == 0:
            lesung = p.read_digits(frame).get("left_display")
            gesamt += 1
            if lesung is not None and lesung.is_readable:
                lesbar += 1
                werte.append((frame.index, lesung.value))
        frame = src.read()
        n += 1
        if n % 10000 == 0:
            print(f"   {100 * n / max(1, info.frame_count):5.1f} %", flush=True)
    src.close()

    # Stabile Werte bilden: ein Wert gilt erst nach STABIL Messungen in Folge
    stabil: list[tuple[int, int]] = []
    kandidat = None
    zaehler = 0
    aktuell = None
    for index, wert in werte:
        if wert == kandidat:
            zaehler += 1
        else:
            kandidat, zaehler = wert, 1
        if zaehler >= STABIL and wert != aktuell:
            aktuell = wert
            stabil.append((index, wert))

    print(f"\n{lesbar} von {gesamt} Messungen lesbar "
          f"({100 * lesbar / max(1, gesamt):.1f} %)")
    print(f"Verteilung der Rohwerte: "
          f"{dict(sorted(Counter(w for _, w in werte).items()))}")

    anstiege = [(f, w) for (f, w), (_, vor) in
                zip(stabil[1:], stabil[:-1]) if w > vor]
    rueckfaelle = [(f, w) for (f, w), (_, vor) in
                   zip(stabil[1:], stabil[:-1]) if w < vor]

    print(f"\n{len(stabil)} stabile Werte insgesamt")
    print(f"   {len(anstiege)} Anstiege (ein Nullwurf zaehlt hoch)")
    print(f"   {len(rueckfaelle)} Rueckfaelle (Spielwechsel setzt zurueck)")

    print("\nAlle stabilen Wertwechsel:")
    for index, wert in stabil:
        s = index / info.fps
        marke = ""
        if abs(index - ERWARTET_FRAME) <= ERWARTET_TOLERANZ:
            marke = "   <== hier steht der Nullwurf im Protokoll"
        print(f"   F{index:>6}  {int(s // 60):>2}:{int(s % 60):02d}   "
              f"Zaehler = {wert}{marke}")

    getroffen = [f for f, _ in anstiege
                 if abs(f - ERWARTET_FRAME) <= ERWARTET_TOLERANZ]
    print("\n" + "=" * 66)
    print("URTEIL")
    print("=" * 66)
    print(f"Das Protokoll nennt fuer Bahn {BAHN} genau EINEN Nullwurf "
          f"(Satz 3, Wurf 18).")
    if len(anstiege) == 1 and getroffen:
        print("Gemessen: genau ein Anstieg, an der richtigen Stelle.")
        print("-> Der Zaehler traegt. Nullwuerfe sind darueber erkennbar.")
    elif getroffen:
        print(f"Gemessen: {len(anstiege)} Anstiege, darunter der richtige.")
        print(f"-> {len(anstiege) - 1} zusaetzliche waeren erfundene Nullwuerfe. "
              f"Die uebrigen Stellen gehoeren angesehen, bevor daraus etwas "
              f"gebaut wird.")
    else:
        print(f"Gemessen: {len(anstiege)} Anstiege, der erwartete NICHT darunter.")
        print("-> Der Zaehler traegt so nicht.")

    if werte:
        AUSGABE.parent.mkdir(parents=True, exist_ok=True)
        with AUSGABE.open("w", encoding="utf-8-sig", newline="") as datei:
            schreiber = csv.writer(datei, delimiter=";")
            schreiber.writerow(["Frame", "Zeit_s", "Fehlwurfzaehler"])
            for index, wert in werte:
                schreiber.writerow([index, round(index / info.fps, 2), wert])
        print(f"\nMessreihe: {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
