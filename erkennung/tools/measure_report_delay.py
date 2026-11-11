"""Wie frueh darf ein Wurf gemeldet werden? -- MESSUNG, kein Umbau.

Heute wird ein Wurf erst beim NAECHSTEN Gruen-AN gemeldet. Das sind typisch
zehn Sekunden, beim Spielwechsel bis zu einer Minute. Fuer einen Spielleiter,
der live mitliest, ist das der Unterschied zwischen "jetzt" und "spaeter".

Zwei Vorschlaege des Nutzers stehen zur Pruefung.

VORSCHLAG A (2026-08-28, erste Fassung): den Frame nehmen, in dem die gruene
Lampe ausgeht. Bereits gemessen und WIDERLEGT: 83,4 % gegen das Wurfprotokoll,
bei den blinkenden Wuerfen nur 61,8 %. Der Fehler ist immer derselbe -- der
Frame liegt in einer Dunkelphase, gelesen wird null. Das Blinken laeuft bei
Gruen-AUS also schon.

VORSCHLAG C (2026-08-28, zweite Fassung): "Ich messe in einer Gruenphase immer,
wie viele Lampen leuchten -- jetzt? und jetzt? -- und dann steigt die Zahl ja
optimalerweise. In dem Moment, wo die Gruenphase ausgeht, kenne ich ja noch den
Wert von davor."

Das ist etwas anderes als A: nicht EIN Frame, sondern das Maximum ueber die
GANZE Gruenphase, in der die Kegel fallen. Solange das Ergebnis noch nicht
vollstaendig ist, blinkt auch noch nichts -- und ein Maximum ist gegen Blinken
ohnehin unempfindlich, weil eine Lampe faelschlich dunkel erscheinen kann, aber
nicht faelschlich leuchten.

Zum Blinken, vom Nutzer praezisiert: Es zeigt "fertig abgeraeumt" an, nicht nur
"alle Neune". Der Koenig muss nicht geraeumt werden -- faellt alles ausser ihm,
blinkt es ebenfalls.

Geprueft werden in EINEM Durchlauf:

    A        ein Frame bei Gruen-AUS
    C        Maximum ueber die Gruenphase          <- Vorschlag, Meldung sofort
    C+N      Gruenphase plus N Frames Wartezeit
    B        das ganze Fenster bis zum naechsten Gruen-AN (heutiges Verhalten)

Aufruf:
    .venv/Scripts/python.exe tools/measure_report_delay.py [VIDEO] [KALIBRIERUNG]

Ergebnis:
    debug/meldeverzoegerung.csv
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

sys.path.insert(0, str(Path(__file__).parent))
from compare_protocol import ausrichten, wahrheit_lesen  # noqa: E402

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/meldeverzoegerung.csv")

# Wartezeiten nach Gruen-AUS, in Frames (25 fps).
WARTEZEITEN = [0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 150]
MAXIMAL = max(WARTEZEITEN)
GRUEN_RASTER = 2      # in der Gruenphase jeden 2. Frame -- ein Maximum ueber
                      # Hunderte Frames braucht kein feineres Raster

# Der Koenig steht in der Mitte der Raute. Er muss NIE geraeumt werden
# (Nutzerhinweis 2026-08-28), zaehlt also nicht zur Vollstaendigkeit.
KOENIG = 5


def werten(ende: set[int], grundlinie: set[int]) -> int:
    """Wurfergebnis aus Endstand und Grundlinie -- wie im ThrowAnalyzer."""
    neu = ende - grundlinie
    if grundlinie - ende:
        neu = ende          # Anlage hat neu aufgestellt, Grundlinie hinfaellig
    return len(neu)


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    video = argumente[0] if argumente else VIDEO
    kalibrierung = argumente[1] if len(argumente) > 1 else KALIBRIERUNG

    cfg = load_config()
    cal = Calibration.load(kalibrierung)
    # Erst NACH dem Grundlinienfenster mitschreiben: Davor steht dort, was
    # bereits lag (Raeumen) -- das gehoert nicht zu diesem Wurf.
    ab_gruen_an = max(cfg.sampling.baseline_offsets)

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
    print(f"{info.frame_count} Frames | Gruenphase ab +{ab_gruen_an} | "
          f"Wartezeiten {WARTEZEITEN}\n")

    gruen_an: dict[int, int | None] = {dn: None for dn in prozessoren}
    gruen_messungen: dict[int, list] = {dn: [] for dn in prozessoren}
    laufend: dict[int, dict | None] = {dn: None for dn in prozessoren}
    fertig: dict[int, list[dict]] = {dn: [] for dn in prozessoren}
    buffer = FrameBuffer(cfg.processing.frame_buffer_size)

    frame = erster
    n = 0
    while frame is not None:
        buffer.append(frame)
        for dn, p in prozessoren.items():
            _, ereignis, sample = p.process(frame, buffer)

            if ereignis is not None and ereignis.event is EventType.GREEN_ON:
                gruen_an[dn] = frame.index
                gruen_messungen[dn] = []

            elif ereignis is not None and ereignis.event is EventType.GREEN_OFF:
                laufend[dn] = {
                    "frame": frame.index, "zeit": frame.timestamp, "bahn": dn,
                    # Vorschlag C: alles, was WAEHREND der Gruenphase gesehen wurde
                    "gruenphase": list(gruen_messungen[dn]),
                    "gruen_frames": (frame.index - gruen_an[dn]
                                     if gruen_an[dn] is not None else 0),
                    "nachher": [],
                }
                gruen_an[dn] = None

            # --- waehrend der Gruenphase mitschreiben (Vorschlag C) ---
            if (gruen_an[dn] is not None
                    and frame.index - gruen_an[dn] >= ab_gruen_an
                    and frame.index % GRUEN_RASTER == 0):
                messung = p.read_pin_lamps_at(frame)
                if messung is not None:
                    gruen_messungen[dn].append(messung)

            # --- nach Gruen-AUS mitschreiben (Wartezeiten) ---
            eintrag = laufend[dn]
            if eintrag is not None:
                versatz = frame.index - eintrag["frame"]
                if 0 < versatz <= MAXIMAL:
                    messung = p.read_pin_lamps_at(frame)
                    if messung is not None:
                        eintrag["nachher"].append((versatz, messung))
                if versatz == 0:
                    bei_aus = p.result_pins
                    eintrag["bei_aus"] = set(bei_aus.pins) if bei_aus else set()

            if sample is not None and laufend[dn] is not None:
                eintrag = laufend[dn]
                laufend[dn] = None
                grundlinie = p.baseline_pins
                eintrag["basis"] = set(grundlinie.pins) if grundlinie else set()
                fenster = aggregate_pin_readings(list(p.result_samples))
                ende = set(fenster.pins) if fenster else set()
                eintrag["B_ganzes_fenster"] = werten(ende, eintrag["basis"])
                # BLINKT DIESER WURF? Nur, wenn in diesem einen Wurf alles
                # faellt, was noch stand -- der Koenig ausgenommen, den muss
                # man nie raeumen. Aus der Kegelzahl allein ist das nicht
                # ablesbar: Acht Kegel blinken nur, wenn es dieselben acht
                # eines Wurfes sind, nicht wenn schon welche lagen.
                steht_noch = ({1, 2, 3, 4, 6, 7, 8, 9}
                              - eintrag["basis"] - ende)
                eintrag["vollstaendig"] = not steht_noch
                fertig[dn].append(eintrag)

        frame = src.read()
        n += 1
        if n % 5000 == 0:
            print(f"   {100 * n / max(1, info.frame_count):5.1f} %", flush=True)
    src.close()

    # ------------------------------------------------------------- Auswerten
    for wuerfe in fertig.values():
        for w in wuerfe:
            basis = w["basis"]
            w["A_bei_aus"] = werten(w.get("bei_aus", set()), basis)
            nur_gruen = aggregate_pin_readings(w["gruenphase"])
            w["C_gruenphase"] = werten(
                set(nur_gruen.pins) if nur_gruen else set(), basis)
            for wartezeit in WARTEZEITEN:
                bis = w["gruenphase"] + [m for versatz, m in w["nachher"]
                                         if versatz <= wartezeit]
                zusammen = aggregate_pin_readings(bis)
                w[f"C{wartezeit}"] = werten(
                    set(zusammen.pins) if zusammen else set(), basis)

    wahrheit = wahrheit_lesen()
    zeilen: list[dict] = []
    treffer = {wartezeit: 0 for wartezeit in WARTEZEITEN}
    treffer_blink = {wartezeit: 0 for wartezeit in WARTEZEITEN}
    a_ok = c_ok = b_ok = blink_a = blink_b = 0
    gesamt = blink_gesamt = 0

    for bahn in sorted(wahrheit):
        wuerfe = fertig.get(bahn, [])
        soll = wahrheit[bahn]
        paare = ausrichten([w["B_ganzes_fenster"] for w in wuerfe],
                           [s["kegel"] for s in soll])
        for i, j in paare:
            if i is None or j is None:
                continue
            w, s = wuerfe[i], soll[j]
            gesamt += 1
            # "Blinkend" heisst: in DIESEM Wurf ist alles gefallen, was noch
            # stand -- der Koenig ausgenommen (Nutzerhinweis 2026-08-28).
            blinkt = w["vollstaendig"]
            blink_gesamt += blinkt
            a_ok += w["A_bei_aus"] == s["kegel"]
            c_ok += w["C_gruenphase"] == s["kegel"]
            b_ok += w["B_ganzes_fenster"] == s["kegel"]
            blink_a += blinkt and w["C_gruenphase"] == s["kegel"]
            blink_b += blinkt and w["B_ganzes_fenster"] == s["kegel"]

            zeile = {"Bahn": bahn, "Frame": w["frame"],
                     "Zeit": f"{int(w['zeit'] // 60)}:{int(w['zeit'] % 60):02d}",
                     "Satz": s["satz"], "Wurf": s["wurf"], "Protokoll": s["kegel"],
                     "GruenFrames": w["gruen_frames"],
                     "Vollstaendig": "ja" if blinkt else "",
                     "Grundlinie": len(w["basis"]),
                     "A_bei_GruenAus": w["A_bei_aus"],
                     "C_Gruenphase": w["C_gruenphase"],
                     "B_GanzesFenster": w["B_ganzes_fenster"]}
            for wartezeit in WARTEZEITEN:
                richtig = w[f"C{wartezeit}"] == s["kegel"]
                treffer[wartezeit] += richtig
                treffer_blink[wartezeit] += richtig and blinkt
                zeile[f"C_plus_{wartezeit}"] = w[f"C{wartezeit}"]
            zeilen.append(zeile)

    def zeile_aus(name: str, richtig: int, blink: int | None = None) -> str:
        text = (f"{name:<34}{richtig:>6}"
                f"{100 * richtig / max(1, gesamt):>8.1f} %")
        if blink is not None:
            text += (f"{blink:>10}{100 * blink / max(1, blink_gesamt):>8.1f} %")
        return text

    print("\n" + "=" * 74)
    print(f"WIE FRUEH DARF GEMELDET WERDEN?   ({gesamt} Wuerfe gegen das Protokoll)")
    print("=" * 74)
    print(f"{'':<34}{'richtig':>14}{'davon blinkend':>18}")
    print(zeile_aus("A  ein Frame bei Gruen-AUS", a_ok))
    print(zeile_aus("C  Maximum ueber die Gruenphase", c_ok, blink_a))
    print(zeile_aus("B  ganzes Fenster (heute)", b_ok, blink_b))

    print(f"\n{'Gruenphase + Wartezeit':<26}{'richtig':>10}{'Anteil':>10}"
          f"{'blinkend':>12}")
    for wartezeit in WARTEZEITEN:
        marke = "  <- reicht" if treffer[wartezeit] >= b_ok else ""
        print(f"{'   + ' + str(wartezeit) + ' Frames':<18}{wartezeit / 25:>5.1f}s"
              f"{treffer[wartezeit]:>10}"
              f"{100 * treffer[wartezeit] / max(1, gesamt):>9.1f}%"
              f"{100 * treffer_blink[wartezeit] / max(1, blink_gesamt):>11.1f}%"
              f"{marke}")

    genug = [w for w in WARTEZEITEN if treffer[w] >= b_ok]
    if genug:
        print(f"\n=> Ab {genug[0]} Frames ({genug[0] / 25:.1f} s) nach Gruen-AUS ist das "
              f"Ergebnis so gut wie heute.")
        heute_s = None
        print(f"   Heute wird bis zum naechsten Gruen-AN gewartet -- im Mittel "
              f"{sum(z['GruenFrames'] for z in zeilen) / max(1, len(zeilen)) / 25:.0f} s "
              f"allein fuer die Gruenphase des naechsten Wurfs.")
    else:
        print("\n=> Keine der geprueften Wartezeiten erreicht das heutige Ergebnis.")

    strittig = [z for z in zeilen
                if z["C_Gruenphase"] != z["B_GanzesFenster"]]
    print(f"\nC und B unterscheiden sich bei {len(strittig)} Wuerfen.")
    for z in strittig[:12]:
        print(f"   Bahn {z['Bahn']} {z['Zeit']} Satz {z['Satz']} Wurf {z['Wurf']}: "
              f"C={z['C_Gruenphase']} B={z['B_GanzesFenster']} "
              f"Protokoll={z['Protokoll']}  (Gruenphase {z['GruenFrames']} Frames)")

    AUSGABE.parent.mkdir(parents=True, exist_ok=True)
    with AUSGABE.open("w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.DictWriter(datei, fieldnames=list(zeilen[0]), delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)
    print(f"\nZeile fuer Zeile: {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
