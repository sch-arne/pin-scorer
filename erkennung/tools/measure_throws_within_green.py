"""Verraet die Wurfnummer einen Nullwurf? -- MESSUNG, kein Umbau.

Befund vom 2026-08-28: Faellt bei einem Wurf KEIN Kegel, schaltet die Anlage die
gruene Lampe nicht aus -- es gibt nichts zu zaehlen und nichts aufzustellen. Der
Wurf ist damit fuer den Gruenlampen-Trigger unsichtbar. Im Wurfprotokoll stehen
zwei solche Wuerfe (Bahn 2 Satz 3 Wurf 18, Bahn 4 Satz 1 Wurf 28), beide fehlen
in der Auswertung.

Die untere Reihe zeigt sie aber sehr wohl. Gemessen an Bahn 2:

    F50700   Wurfnummer 17   Kegelzahl 1
    F51085   Wurfnummer 18   Kegelzahl 0     <- der Nullwurf, 16 Sekunden lang
    F51480   Wurfnummer 19   Kegelzahl 2

Daraus liesse sich eine Regel bauen: Aendert sich die Wurfnummer, WAEHREND die
gruene Lampe an ist, war es ein Wurf ohne Kegel. Physikalisch sauber -- fiele
auch nur ein Kegel, muesste die Anlage zaehlen und aufstellen.

DIESE DATEI PRUEFT, OB DIE REGEL TRAEGT. Gezaehlt wird ueber das ganze Video,
wie oft sich die Wurfnummer waehrend einer Gruenphase STABIL aendert. Sind es
genau die zwei bekannten Faelle, ist die Regel sicher. Sind es fuenfzig, ist es
Rauschen -- und eine darauf gebaute Regel erfaende Wuerfe. Genau der Fehler aus
BUG-013, diesmal vorher gemessen.

Nicht der WERT der Wurfnummer wird gebraucht, nur dass sie sich geaendert hat.
Das ist wichtig, weil sie auf Bahn 4 stabil falsch gelesen wird (28 als 23) --
der Wechsel ist trotzdem eindeutig.

Nebenbei geklaert wird: Ist der Fehlwurfzaehler links ueberhaupt jemals lesbar?
Er ist als Gegenprobe konfiguriert (`scoring.check_foul_count`), lieferte in
zwei Stichproben aber ueber 580 Messungen hinweg nichts.

Aufruf:
    .venv/Scripts/python.exe tools/measure_throws_within_green.py [VIDEO] [KAL]

Ergebnis:
    debug/wuerfe_in_gruenphase.csv
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
from kegel_cv.detection.state_machine import EventType
from kegel_cv.video import FileVideoSource, FrameBuffer

sys.path.insert(0, str(Path(__file__).parent))
from compare_protocol import wahrheit_lesen  # noqa: E402

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/wuerfe_in_gruenphase.csv")

ABSTAND = 5        # jeden n-ten Frame lesen (wie die spaeten Felder)
STABIL = 5         # so viele Messungen in Folge gelten als stabiler Wert
                   # -> 25 Frames = 1 Sekunde


class Feldverlauf:
    """Verfolgt ein Ziffernfeld und meldet nur STABILE Wertwechsel.

    Ein einzelner Ausreisser darf keinen Wurf erfinden. Die Anzeige flackert
    gemessen erheblich (auf Bahn 2 sprang die Wurfnummer zwischen 17 und 317).
    """

    def __init__(self) -> None:
        self.stabiler_wert: int | None = None
        self.kandidat: int | None = None
        self.zaehler = 0
        self.wechsel: list[tuple[int, int, int | None]] = []   # Frame, neu, alt

    def messen(self, frame: int, wert: int | None) -> bool:
        """Liefert True, wenn hier ein stabiler Wechsel festgestellt wurde."""
        if wert is None:
            return False
        if wert == self.kandidat:
            self.zaehler += 1
        else:
            self.kandidat = wert
            self.zaehler = 1
        if self.zaehler < STABIL or wert == self.stabiler_wert:
            return False
        alt = self.stabiler_wert
        self.stabiler_wert = wert
        if alt is not None:
            self.wechsel.append((frame, wert, alt))
            return True
        return False


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
    print(f"Video: {info.source_id} | Bahnen {sorted(prozessoren)}")
    print(f"{info.frame_count} Frames | Raster {ABSTAND} | stabil ab {STABIL} "
          f"Messungen ({STABIL * ABSTAND} Frames)\n")

    gruen_an: dict[int, int | None] = {dn: None for dn in prozessoren}
    verlauf: dict[int, Feldverlauf] = {dn: Feldverlauf() for dn in prozessoren}
    treffer: dict[int, list[dict]] = {dn: [] for dn in prozessoren}
    gruenphasen: dict[int, int] = {dn: 0 for dn in prozessoren}
    fehlwurf_lesbar = Counter()
    fehlwurf_gesamt = Counter()
    buffer = FrameBuffer(cfg.processing.frame_buffer_size)

    frame = erster
    n = 0
    while frame is not None:
        buffer.append(frame)
        for dn, p in prozessoren.items():
            _, ereignis, _ = p.process(frame, buffer)

            if ereignis is not None and ereignis.event is EventType.GREEN_ON:
                gruen_an[dn] = frame.index
                gruenphasen[dn] += 1
            elif ereignis is not None and ereignis.event is EventType.GREEN_OFF:
                gruen_an[dn] = None

            # Nur WAEHREND der Gruenphase lesen -- ein Wechsel danach ist der
            # ganz normale Uebergang zum naechsten Wurf.
            if gruen_an[dn] is None or frame.index % ABSTAND != 0:
                continue

            lesungen = p.read_digits(frame)

            fehlwurf = lesungen.get("left_display")
            fehlwurf_gesamt[dn] += 1
            if fehlwurf is not None and fehlwurf.is_readable:
                fehlwurf_lesbar[dn] += 1

            nummer = lesungen.get("throw_number")
            wert = (nummer.value
                    if nummer is not None and nummer.is_readable else None)
            if verlauf[dn].messen(frame.index, wert):
                neu_frame, neu, alt = verlauf[dn].wechsel[-1]
                kegel = lesungen.get("pin_count")
                treffer[dn].append({
                    "Bahn": dn, "Frame": neu_frame,
                    "Zeit": f"{int(frame.timestamp // 60)}:"
                            f"{int(frame.timestamp % 60):02d}",
                    "Wurfnummer_alt": alt, "Wurfnummer_neu": neu,
                    "Sprung": neu - alt,
                    "Kegelzahl": (kegel.value if kegel is not None
                                  and kegel.is_readable else ""),
                    "GruenAn_seit": neu_frame - gruen_an[dn],
                })

        frame = src.read()
        n += 1
        if n % 5000 == 0:
            gefunden = sum(len(v) for v in treffer.values())
            print(f"   {100 * n / max(1, info.frame_count):5.1f} %  "
                  f"({gefunden} Wechsel bisher)", flush=True)
    src.close()

    # -------------------------------------------------------------- Ergebnis
    alle = [t for v in treffer.values() for t in v]
    print("\n" + "=" * 74)
    print("WURFNUMMER-WECHSEL WAEHREND EINER GRUENPHASE")
    print("=" * 74)
    print(f"{'Bahn':<6}{'Gruenphasen':>13}{'Wechsel':>10}{'davon +1':>10}")
    for dn in sorted(prozessoren):
        eins = sum(1 for t in treffer[dn] if t["Sprung"] == 1)
        print(f"{dn:<6}{gruenphasen[dn]:>13}{len(treffer[dn]):>10}{eins:>10}")
    eins_gesamt = sum(1 for t in alle if t["Sprung"] == 1)
    print("-" * 39)
    print(f"{'alle':<6}{sum(gruenphasen.values()):>13}{len(alle):>10}"
          f"{eins_gesamt:>10}")

    print("\nIm Wurfprotokoll stehen 2 Nullwuerfe:")
    print("   Bahn 2, Satz 3, Wurf 18   (erwartet um Frame 51085)")
    print("   Bahn 4, Satz 1, Wurf 28   (erwartet um Frame 16965)")

    if alle:
        print(f"\nAlle {len(alle)} Wechsel:")
        for t in sorted(alle, key=lambda x: (x["Bahn"], x["Frame"])):
            passt = ""
            if t["Bahn"] == 2 and 50900 <= t["Frame"] <= 51300:
                passt = "   <== der bekannte Nullwurf"
            if t["Bahn"] == 4 and 16800 <= t["Frame"] <= 17200:
                passt = "   <== der bekannte Nullwurf"
            print(f"   Bahn {t['Bahn']} F{t['Frame']:>6} {t['Zeit']:>6}  "
                  f"{t['Wurfnummer_alt']} -> {t['Wurfnummer_neu']} "
                  f"(Sprung {t['Sprung']:+d}), Kegelzahl {t['Kegelzahl'] or '?'}, "
                  f"gruen seit {t['GruenAn_seit']} Frames{passt}")

    print("\n" + "=" * 74)
    print("FEHLWURFZAEHLER (linkes Display) -- ist er ueberhaupt lesbar?")
    print("=" * 74)
    for dn in sorted(prozessoren):
        gesamt = fehlwurf_gesamt[dn]
        lesbar = fehlwurf_lesbar[dn]
        print(f"   Bahn {dn}: {lesbar} von {gesamt} Messungen lesbar "
              f"({100 * lesbar / max(1, gesamt):.1f} %)")

    if alle:
        AUSGABE.parent.mkdir(parents=True, exist_ok=True)
        with AUSGABE.open("w", encoding="utf-8-sig", newline="") as datei:
            schreiber = csv.DictWriter(datei, fieldnames=list(alle[0]),
                                       delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(sorted(alle, key=lambda x: (x["Bahn"], x["Frame"])))
        print(f"\nZeile fuer Zeile: {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
