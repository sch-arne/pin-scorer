"""Reicht der Lampenstand IM MOMENT von Gruen-AUS? -- MESSUNG, kein Umbau.

Die Frage stammt vom Nutzer (2026-08-28): "Ich glaube wir koennen hier auch
sagen, sobald GRUEN AUS gib mir den Wert, der ist ja zuvor die ganze Zeit
angestiegen bei den fallenden Kegeln. Wir wissen ja eigentlich schon wie viele
es sind, nur wenn es 9e sind (oder 8 beim Raeumen, da darf der Koenig fehlen),
dann blinkt es. Aber das sollte in exakt dem Frame, wo das gruene Licht ausgeht,
noch nicht der Fall sein."

Es geht um mehr als eine Kennzahl: Heute wird ein Wurf erst beim NAECHSTEN
Gruen-AN gemeldet, also erst, wenn der uebernaechste Spieler antritt. Traegt der
Wert bei Gruen-AUS, kann der Wurf sofort gemeldet werden -- fuer den Spielleiter
vor Ort ist das der Unterschied zwischen "live" und "eine Minute spaeter". Und
der letzte Wurf eines Videos ginge nicht mehr verloren.

Verglichen werden gegen das handgefuehrte Wurfprotokoll:

    A  ein Frame bei GREEN_OFF   (Vorschlag: sofort melden)
    B  Maximum ueber das Fenster (heutiges Verhalten)

Das ist der erste Vergleich dieser Art mit einer Bodenwahrheit, die NICHT aus
dem Bild stammt. Frueher stand als Bezug die Ziffernanzeige zur Verfuegung --
die ist selbst fehlbar, und wer sie als Wahrheit nimmt, misst am Ende sie.

Aufruf:
    .venv/Scripts/python.exe tools/measure_green_off_value.py [VIDEO] [KALIBRIERUNG]

Ergebnis:
    debug/gruenaus_vergleich.csv
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
from kegel_cv.models.readings import aggregate_pin_readings
from kegel_cv.video import FileVideoSource, FrameBuffer

sys.path.insert(0, str(Path(__file__).parent))
from compare_protocol import ausrichten, wahrheit_lesen  # noqa: E402

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/gruenaus_vergleich.csv")


def werten(ende: set[int], grundlinie: set[int]) -> tuple[int, tuple[int, ...]]:
    """Wurfergebnis aus Endstand und Grundlinie -- wie im ThrowAnalyzer.

    Bewusst nachgebildet statt importiert: Der Analyzer bucht dabei zugleich
    Summen und Wurfnummern, und das soll eine Messung nicht anfassen.
    """
    neu = ende - grundlinie
    if grundlinie - ende:
        # Kegel lagen vorher und stehen wieder -- die Anlage hat neu aufgestellt,
        # die Grundlinie ist hinfaellig.
        neu = ende
    return len(neu), tuple(sorted(neu))


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
    print(f"{info.frame_count} Frames -- das dauert.\n")

    # Je Bahn: offener Wurf und fertige Wuerfe
    offen: dict[int, dict | None] = {dn: None for dn in prozessoren}
    fertig: dict[int, list[dict]] = {dn: [] for dn in prozessoren}
    buffer = FrameBuffer(cfg.processing.frame_buffer_size)

    frame = erster
    n = 0
    while frame is not None:
        buffer.append(frame)
        for dn, p in prozessoren.items():
            _, ereignis, sample = p.process(frame, buffer)

            if ereignis is not None and ereignis.event is EventType.GREEN_OFF:
                # Der Wert GENAU JETZT -- das ist Vorschlag A.
                bei_aus = p.result_pins
                offen[dn] = {
                    "frame": frame.index,
                    "zeit": frame.timestamp,
                    "bei_aus": set(bei_aus.pins) if bei_aus else set(),
                    "bei_aus_lesbar": bei_aus.is_complete if bei_aus else False,
                }
            elif sample is not None and offen[dn] is not None:
                eintrag = offen[dn]
                offen[dn] = None
                # Vorschlag B: alles, was ueber das Fenster gesammelt wurde.
                fenster = aggregate_pin_readings(list(p.result_samples))
                grundlinie = p.baseline_pins
                basis = set(grundlinie.pins) if grundlinie else set()

                a_zahl, a_pins = werten(eintrag["bei_aus"], basis)
                b_zahl, b_pins = werten(set(fenster.pins) if fenster else set(),
                                        basis)
                eintrag.update({
                    "bahn": dn, "grundlinie": len(basis),
                    "a_zahl": a_zahl, "a_pins": a_pins,
                    "b_zahl": b_zahl, "b_pins": b_pins,
                    "raeumen": bool(basis),
                })
                fertig[dn].append(eintrag)

        frame = src.read()
        n += 1
        if n % 10000 == 0:
            print(f"   {100 * n / max(1, info.frame_count):5.1f} %", flush=True)
    src.close()

    # -------------------------------------------------------------- Vergleich
    wahrheit = wahrheit_lesen()
    zeilen: list[dict] = []
    gesamt_a = Counter()
    gesamt_b = Counter()

    print("\n" + "=" * 78)
    print("A = ein Frame bei GREEN_OFF      B = Maximum ueber das Fenster")
    print("=" * 78)
    print(f"{'Bahn':<6}{'Wuerfe':>8}{'A richtig':>12}{'B richtig':>12}"
          f"{'A != B':>10}")

    for bahn in sorted(wahrheit):
        wuerfe = fertig.get(bahn, [])
        soll = wahrheit[bahn]

        # Ausgerichtet wird EINMAL, ueber B (das heutige Verhalten). Sonst
        # verglichen die beiden Vorschlaege gegen verschieden ausgerichtete
        # Protokolle und die Zahlen waeren nicht gegeneinander lesbar.
        paare = ausrichten([w["b_zahl"] for w in wuerfe],
                           [s["kegel"] for s in soll])

        a_ok = b_ok = verschieden = 0
        for i, j in paare:
            w = wuerfe[i] if i is not None else None
            s = soll[j] if j is not None else None
            if w is None or s is None:
                continue
            if w["a_zahl"] == s["kegel"]:
                a_ok += 1
            if w["b_zahl"] == s["kegel"]:
                b_ok += 1
            if w["a_zahl"] != w["b_zahl"]:
                verschieden += 1
            zeilen.append({
                "Bahn": bahn, "Frame": w["frame"],
                "Zeit": f"{int(w['zeit'] // 60)}:{int(w['zeit'] % 60):02d}",
                "Satz": s["satz"], "Wurf": s["wurf"],
                "Protokoll": s["kegel"],
                "A_bei_GruenAus": w["a_zahl"],
                "B_Fenstermax": w["b_zahl"],
                "A_richtig": "ja" if w["a_zahl"] == s["kegel"] else "",
                "B_richtig": "ja" if w["b_zahl"] == s["kegel"] else "",
                "Grundlinie": w["grundlinie"],
                "Raeumen": "ja" if w["raeumen"] else "",
                "A_Kegel": " ".join(map(str, w["a_pins"])),
                "B_Kegel": " ".join(map(str, w["b_pins"])),
            })
            gesamt_a[w["a_zahl"] == s["kegel"]] += 1
            gesamt_b[w["b_zahl"] == s["kegel"]] += 1

        vergleichbar = a_ok + b_ok and len([1 for i, j in paare
                                            if i is not None and j is not None])
        print(f"{bahn:<6}{vergleichbar:>8}"
              f"{a_ok:>7} {100 * a_ok / max(1, vergleichbar):>4.0f}%"
              f"{b_ok:>7} {100 * b_ok / max(1, vergleichbar):>4.0f}%"
              f"{verschieden:>10}")

    a_richtig, a_falsch = gesamt_a[True], gesamt_a[False]
    b_richtig, b_falsch = gesamt_b[True], gesamt_b[False]
    summe = a_richtig + a_falsch
    print("-" * 58)
    print(f"{'alle':<6}{summe:>8}"
          f"{a_richtig:>7} {100 * a_richtig / max(1, summe):>4.1f}%"
          f"{b_richtig:>7} {100 * b_richtig / max(1, summe):>4.1f}%")

    # Wo unterscheiden sie sich -- und wer hat dann recht?
    strittig = [z for z in zeilen if z["A_bei_GruenAus"] != z["B_Fenstermax"]]
    nur_a = [z for z in strittig if z["A_richtig"] and not z["B_richtig"]]
    nur_b = [z for z in strittig if z["B_richtig"] and not z["A_richtig"]]
    keiner = [z for z in strittig if not z["A_richtig"] and not z["B_richtig"]]

    print(f"\nA und B unterscheiden sich bei {len(strittig)} von {summe} Wuerfen")
    print(f"   nur A hat recht : {len(nur_a)}")
    print(f"   nur B hat recht : {len(nur_b)}")
    print(f"   beide daneben   : {len(keiner)}")

    # Die vom Nutzer benannte Sorge: Neuner blinken.
    neuner = [z for z in zeilen if z["Protokoll"] == 9]
    neuner_a = sum(1 for z in neuner if z["A_richtig"])
    neuner_b = sum(1 for z in neuner if z["B_richtig"])
    print(f"\nWuerfe mit 9 Kegeln (die blinken): {len(neuner)}")
    print(f"   A trifft {neuner_a} ({100 * neuner_a / max(1, len(neuner)):.1f} %)")
    print(f"   B trifft {neuner_b} ({100 * neuner_b / max(1, len(neuner)):.1f} %)")

    raeum = [z for z in zeilen if z["Raeumen"]]
    raeum_a = sum(1 for z in raeum if z["A_richtig"])
    raeum_b = sum(1 for z in raeum if z["B_richtig"])
    print(f"\nRaeumwuerfe: {len(raeum)}")
    print(f"   A trifft {raeum_a} ({100 * raeum_a / max(1, len(raeum)):.1f} %)")
    print(f"   B trifft {raeum_b} ({100 * raeum_b / max(1, len(raeum)):.1f} %)")

    if nur_b:
        print("\nWo nur das Fenster recht hat (erste 10) -- dort waere ein "
              "sofortiges Melden falsch:")
        for z in nur_b[:10]:
            print(f"   Bahn {z['Bahn']} {z['Zeit']} Satz {z['Satz']} Wurf {z['Wurf']}: "
                  f"A={z['A_bei_GruenAus']} B={z['B_Fenstermax']} "
                  f"Protokoll={z['Protokoll']}"
                  f"{'  RAEUMEN' if z['Raeumen'] else ''}")
    if nur_a:
        print("\nWo nur der Moment recht hat (erste 10):")
        for z in nur_a[:10]:
            print(f"   Bahn {z['Bahn']} {z['Zeit']} Satz {z['Satz']} Wurf {z['Wurf']}: "
                  f"A={z['A_bei_GruenAus']} B={z['B_Fenstermax']} "
                  f"Protokoll={z['Protokoll']}"
                  f"{'  RAEUMEN' if z['Raeumen'] else ''}")

    AUSGABE.parent.mkdir(parents=True, exist_ok=True)
    with AUSGABE.open("w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.DictWriter(datei, fieldnames=list(zeilen[0]), delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)
    print(f"\nZeile fuer Zeile: {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
