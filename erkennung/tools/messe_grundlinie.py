"""Vier Wege zur Grundlinie aus der laufenden Lampenspur, gegen die Ziffer.

WOZU (BUG-031): Die Grundlinie -- wie viele Kegel vor dem Wurf schon lagen --
wird heute in einem einzigen Fenster von 25 Frames nach dem erkannten Gruen-AN
gemessen. Trifft dieses Fenster den falschen Augenblick, ist die gebuchte
Kegelzahl falsch, und zwar dauerhaft: Sie verschwindet in einer Subtraktion.

Nebenher laufen ohnehin Lampenmessungen fuer die Anzeige, jede davon steht in
der `lampenspur.csv`. Dieses Werkzeug fragt: Haetten die genuegt?

Als Grundlinie wird der KLEINSTE Lampenstand seit dem vorigen Wurf genommen.
Beim Raeumen bleiben die alten Lampen an, das Minimum ist die Grundlinie; nach
dem Neuaufstellen faellt der Stand auf null, das Minimum ist null. Gemessen
wird gegen die Kegelziffer der Tafel.

"Nx bestaetigt" verlangt, dass ein Stand N-mal hintereinander so gemessen
wurde. Ohne diese Bedingung bestimmt eine einzelne Lampe in der Dunkelphase des
Blinkens die Grundlinie -- gemessen kippen dadurch zwei sonst richtige Wuerfe.

GEMESSEN am Lauf 2026-09-17 12:53, 874 Wuerfe mit lesbarer Ziffer:

    heute (Fenster nach Gruen-AN)   870   99,54 %
    Probe, kleinster Stand          871   99,66 %
    Probe, 2x bestaetigt            871   99,66 %
    Probe, 3x bestaetigt            872   99,77 %

Die beiden dann noch falschen sind keine Grundlinienfehler: ein verlorener
Wurf (BUG-030) und eine falsch gelesene Ziffer.

Aufruf:

    .venv/Scripts/python.exe tools/messe_grundlinie.py <laufordner>
"""
import csv
import sys
from collections import defaultdict
from pathlib import Path

LAUF = Path(sys.argv[1])

spur = defaultdict(dict)
with (LAUF / "lampenspur.csv").open(encoding="utf-8-sig", newline="") as d:
    for z in csv.DictReader(d, delimiter=";"):
        b, f = int(z["Bahn"]), int(z["Frame"])
        spur[b].setdefault(f, set())
        if z["Zustand"] == "ON":
            spur[b][f].add(int(z["Lampe"].rsplit("_", 1)[1]))

wuerfe = list(csv.DictReader(
    (LAUF / "wuerfe.csv").open(encoding="utf-8-sig", newline=""), delimiter=";"))
je_bahn = defaultdict(list)
for w in wuerfe:
    je_bahn[int(w["Bahn"])].append(w)


def zahl(t):
    t = (t or "").strip()
    return int(t) if t.isdigit() else None


def bestaetigt(staende, wie_oft):
    """Kleinster Stand, der WIE_OFT mal hintereinander gemessen wurde.

    Ein einzelner Ausreisser nach unten -- eine Lampe in der Dunkelphase des
    Blinkens -- darf die Grundlinie nicht bestimmen.
    """
    beste = None
    lauf = 0
    vorher = None
    for wert in staende:
        lauf = lauf + 1 if wert == vorher else 1
        vorher = wert
        if lauf >= wie_oft and (beste is None or wert < beste):
            beste = wert
    return beste if beste is not None else (min(staende) if staende else 0)


ergebnis = defaultdict(int)
gesamt = 0
details = defaultdict(list)
for bahn, reihe in sorted(je_bahn.items()):
    reihe.sort(key=lambda w: int(w["Frame"]))
    rahmen = sorted(spur[bahn])
    vorher_frame = 0
    for w in reihe:
        frame = int(w["Frame"])
        ziffer, lampen = zahl(w["Ziffer"]), zahl(w["Kegel"])
        grundlinie = zahl(w["Grundlinie"]) or 0
        ende = (lampen or 0) + grundlinie
        fenster = [f for f in rahmen if vorher_frame < f <= frame]
        vorher_frame = frame
        if ziffer is None or lampen is None or not fenster:
            continue
        staende = [len(spur[bahn][f]) for f in fenster]
        gesamt += 1

        kandidaten = {
            "heute": lampen,
            "min": ende - min(staende),
            "min, 2x bestaetigt": ende - bestaetigt(staende, 2),
            "min, 3x bestaetigt": ende - bestaetigt(staende, 3),
        }
        # Eine Kegelzahl unter 0 oder ueber dem Endstand ist keine Aussage,
        # sondern ein Rechenfehler -- dann bleibt es bei der alten Zahl.
        for name, wert in list(kandidaten.items()):
            if name != "heute" and not (0 <= wert <= 9):
                kandidaten[name] = lampen
        for name, wert in kandidaten.items():
            if wert == ziffer:
                ergebnis[name] += 1
            elif name != "heute":
                details[name].append((bahn, frame, w["Wurfnummer"], ziffer,
                                      lampen, wert))

print(f"{gesamt} Wuerfe mit lesbarer Ziffer\n")
for name in ("heute", "min", "min, 2x bestaetigt", "min, 3x bestaetigt"):
    t = ergebnis[name]
    print(f"  {name:<22s} {t:4d} richtig  ({100*t/gesamt:6.2f} %)  "
          f"{gesamt - t} falsch")

for name in ("min, 2x bestaetigt", "min, 3x bestaetigt"):
    print(f"\n  Fehler von '{name}':")
    for d in details[name][:12]:
        print(f"    Bahn {d[0]} F{d[1]} Wurf {d[2]}: Ziffer {d[3]}, "
              f"heute {d[4]}, Probe {d[5]}")
