"""Vergleicht zwei Regeln fuer das Wurfergebnis -- MESSUNG, kein Umbau.

Die Frage stammt vom Nutzer: Muss der Messzeitpunkt ueberhaupt getroffen werden?

Ueberlegung dahinter: Waehrend eines Wurfs koennen Lampen nur DAZUKOMMEN --
Kegel stehen nicht wieder auf. Blinken zieht die Zahl kurz nach unten, nie nach
oben. Das Aufstellen zieht sie auf null, nie nach oben. Und die Kegel des
naechsten Wurfs koennen nicht fallen, bevor Gruen wieder angeht.

Wenn das stimmt, ist das MAXIMUM ueber das ganze Fenster von Gruen-AN bis zum
naechsten Gruen-AN das Ergebnis -- unabhaengig davon, wann genau GREEN_OFF
erkannt wurde. Damit verschwaende der Messzeitpunkt als Fehlerquelle.

Verglichen werden:
    A  ab GREEN_OFF   (heutiges Verhalten)
    B  ab GREEN_ON    (Vorschlag: das ganze Fenster)

Als Bezug dient die angezeigte Kegelzahl, wo sie eindeutig lesbar ist. Sie ist
nicht unfehlbar -- deshalb wird zusaetzlich ausgewiesen, wo A und B sich
UNTERSCHEIDEN, denn dort lohnt der Blick ins Bild.

Aufruf:
    .venv/Scripts/python.exe tools/measure_max_window.py [VIDEO] [KALIBRIERUNG]
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.detection.state_machine import EventType
from kegel_cv.models.readings import aggregate_pin_readings
from kegel_cv.video import FileVideoSource, FrameBuffer

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/maxfenster.csv")

ABSTAND = 3          # jeden n-ten Frame messen -- fuer ein Maximum reicht das
GRUNDLINIE_BIS = 25  # Frames nach GREEN_ON: aufgestellt, Ball noch unterwegs


class Fenster:
    """Sammelt die Lampenmessungen eines Wurfs."""

    def __init__(self, gruen_an: int) -> None:
        self.gruen_an = gruen_an
        self.gruen_aus: int | None = None
        self.grundlinie: list = []       # kurz nach GREEN_ON
        self.ab_gruen_an: list = []      # ganzes Fenster
        self.ab_gruen_aus: list = []     # heutiges Verhalten
        self.ziffer: int | None = None

    def messen(self, index: int, messung) -> None:
        if messung is None:
            return
        if index - self.gruen_an <= GRUNDLINIE_BIS:
            self.grundlinie.append(messung)
        self.ab_gruen_an.append(messung)
        if self.gruen_aus is not None and index >= self.gruen_aus:
            self.ab_gruen_aus.append(messung)

    def auswerten(self) -> tuple[int | None, int | None, int]:
        """(Ergebnis A, Ergebnis B, Grundlinie)."""
        grund = aggregate_pin_readings(self.grundlinie)
        basis = set(grund.pins) if grund else set()

        a = aggregate_pin_readings(self.ab_gruen_aus)
        b = aggregate_pin_readings(self.ab_gruen_an)
        return (len(set(a.pins) - basis) if a else None,
                len(set(b.pins) - basis) if b else None,
                len(basis))


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
    print(f"Video: {info.source_id} | Bahnen {sorted(prozessoren)}\n")

    offen: dict[int, Fenster | None] = {dn: None for dn in prozessoren}
    fertig: dict[int, list[Fenster]] = {dn: [] for dn in prozessoren}
    buffer = FrameBuffer(cfg.processing.frame_buffer_size)

    frame = erster
    n = 0
    while frame is not None:
        buffer.append(frame)
        for dn, p in prozessoren.items():
            _, ereignis, _ = p.process(frame, buffer)

            if ereignis is not None and ereignis.event is EventType.GREEN_ON:
                if offen[dn] is not None:
                    fertig[dn].append(offen[dn])
                offen[dn] = Fenster(frame.index)
            elif (ereignis is not None and ereignis.event is EventType.GREEN_OFF
                  and offen[dn] is not None):
                offen[dn].gruen_aus = frame.index
                # Die Ziffer EINMAL lesen, als Bezugsgroesse
                try:
                    lesungen = p.read_digits(frame)
                    kegel = lesungen.get("pin_count")
                    if kegel is not None and kegel.is_readable:
                        offen[dn].ziffer = kegel.value
                except Exception:  # noqa: BLE001
                    pass

            if offen[dn] is not None and frame.index % ABSTAND == 0:
                offen[dn].messen(frame.index, p.read_pin_lamps_at(frame))

        frame = src.read()
        n += 1
        if n % 10000 == 0:
            print(f"   {100 * n / max(1, info.frame_count):5.1f} %", flush=True)
    for dn, f in offen.items():
        if f is not None:
            fertig[dn].append(f)
    src.close()

    # --- Auswerten ---
    zeilen = []
    for dn, fenster in sorted(fertig.items()):
        for f in fenster:
            if f.gruen_aus is None:
                continue          # Fenster ohne Wurfende -- unbrauchbar
            a, b, grund = f.auswerten()
            zeilen.append({"Bahn": dn, "GruenAn": f.gruen_an, "GruenAus": f.gruen_aus,
                           "Grundlinie": grund, "A_ab_GruenAus": a,
                           "B_ab_GruenAn": b, "Ziffer": f.ziffer})

    AUSGABE.parent.mkdir(parents=True, exist_ok=True)
    with AUSGABE.open("w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.DictWriter(datei, fieldnames=list(zeilen[0]), delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)

    mit_ziffer = [z for z in zeilen if z["Ziffer"] is not None]
    a_ok = sum(1 for z in mit_ziffer if z["A_ab_GruenAus"] == z["Ziffer"])
    b_ok = sum(1 for z in mit_ziffer if z["B_ab_GruenAn"] == z["Ziffer"])
    anders = [z for z in zeilen if z["A_ab_GruenAus"] != z["B_ab_GruenAn"]]

    print(f"\n{len(zeilen)} Wurffenster, davon {len(mit_ziffer)} mit lesbarer Ziffer\n")
    print(f"{'Regel':<34}{'stimmig':>9}{'Anteil':>9}")
    print(f"{'A  ab GREEN_OFF (heute)':<34}{a_ok:>9}"
          f"{100 * a_ok / max(1, len(mit_ziffer)):>8.1f} %")
    print(f"{'B  ab GREEN_ON (Vorschlag)':<34}{b_ok:>9}"
          f"{100 * b_ok / max(1, len(mit_ziffer)):>8.1f} %")

    nur_a = [z for z in mit_ziffer
             if z["A_ab_GruenAus"] == z["Ziffer"] != z["B_ab_GruenAn"]]
    nur_b = [z for z in mit_ziffer
             if z["B_ab_GruenAn"] == z["Ziffer"] != z["A_ab_GruenAus"]]
    print(f"\nA und B unterscheiden sich bei {len(anders)} von {len(zeilen)} Fenstern")
    print(f"   nur A trifft die Ziffer: {len(nur_a)}")
    print(f"   nur B trifft die Ziffer: {len(nur_b)}")

    if nur_a:
        print("\nWo nur A trifft (erste 8) -- diese Bilder lohnen den Blick:")
        for z in nur_a[:8]:
            print(f"   Bahn {z['Bahn']} F{z['GruenAus']}: A={z['A_ab_GruenAus']} "
                  f"B={z['B_ab_GruenAn']} Ziffer={z['Ziffer']} "
                  f"(Grundlinie {z['Grundlinie']})")
    if nur_b:
        print("\nWo nur B trifft (erste 8):")
        for z in nur_b[:8]:
            print(f"   Bahn {z['Bahn']} F{z['GruenAus']}: A={z['A_ab_GruenAus']} "
                  f"B={z['B_ab_GruenAn']} Ziffer={z['Ziffer']} "
                  f"(Grundlinie {z['Grundlinie']})")

    print(f"\nTabelle: {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
