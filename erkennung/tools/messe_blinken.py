"""Zaehlt je Lampe die AN/AUS-WECHSEL -- trennt Blinken von Dauerleuchten.

WOZU (Nutzer, 2026-09-25): *"wie willst du echtes blinken erkennen? Wir
checken ja immer nur 'eine Lampe hat mal geleuchtet' aber ja nie 'Lampe
blinkt'? Dazu muessten wir doch viel mehr Frames abfragen, oder?"*

Die Vermutung dahinter: Wir muessten dichter abtasten. Dieses Werkzeug prueft
das nach, ohne einen einzigen zusaetzlichen Frame -- allein auf der
Lampenspur, die der Lauf ohnehin geschrieben hat.

WAS DAHINTER STEHT (vom Nutzer erklaert, 2026-09-25): Blinken hat genau drei
Bedeutungen. Alle Neune mit einem Wurf, ein 8er Kranz mit einem Wurf (alle
ausser der 5, die 5 ist AUS), oder ein FEHLERCODE. Braucht das Raeumen
mehrere Wuerfe, blinkt nichts. Bei den beiden Jubel-Effekten blinkt alles,
was leuchtet -- die dauerleuchtende Menge ist leer. Nur ein Fehlercode hat
eine dauerleuchtende UND eine blinkende Menge zugleich. Fehlercodes beginnen
immer erst NACH Gruen-AUS.

GEZAEHLT WIRD GETRENNT nach "bis Gruen-AUS" und "nach Gruen-AUS": Wenn die
Behauptung stimmt, darf vor Gruen-AUS nie ein Fehlercode-Muster stehen.

Ein einzelnes AUS zaehlt bewusst NICHT als Blinken. Bahn 5 Kegel 8 liest sich
regelmaessig als AUS, obwohl sie leuchtet (die ROI sitzt zwei Pixel zu tief);
sie wuerde sonst zum Dauerblinker. Gewertet werden WECHSEL.

Aufruf:

    .venv/Scripts/python.exe tools/messe_blinken.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
from pathlib import Path

# So viele Frames nach Gruen-AUS gehoeren noch zum Wurf. Das Abtastfenster der
# Ziffern reicht so weit; laenger zu schauen hiesse, in den naechsten Wurf zu
# greifen.
NACHLAUF = 120


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--mindestwechsel", type=int, default=2,
                   help="Ab so vielen Wechseln gilt eine Lampe als blinkend. "
                        "2 statt 1, weil eine einzelne Fehllesung sonst "
                        "genuegte.")
    a = p.parse_args()

    # DIE FENSTER KOMMEN AUS DER GRUENSPUR, nicht aus den Wurfframes.
    #
    # Erster Versuch am 2026-09-25 war mit den Wurfframes geschnitten: "bis"
    # reichte damit vom VORIGEN Wurf bis zu diesem und umfasste das Loeschen
    # der Anzeige und das Stellen des neuen Satzes. Dabei geht jede leuchtende
    # Lampe aus und wieder an -- die Messung meldete 1455 "Jubel"-Muster, wo
    # es hoechstens ein paar Dutzend geben kann. Ausserdem landeten die
    # Abtastungen NACH Gruen-AUS im Eimer des naechsten Wurfs.
    #
    # Richtig ist: "bis" ist die Gruenphase selbst (Gruen-AN bis Gruen-AUS),
    # "nach" die Frames unmittelbar danach.
    zyklen: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    folge: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
    with (a.lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            folge[r["Bahn"]].append((int(r["Frame"]), r["Zustand"]))
    for bahn, reihe in folge.items():
        reihe.sort()
        an = vor = None
        for frame, zustand in reihe:
            if zustand == "ON" and vor != "ON":
                an = frame
            elif zustand == "OFF" and vor == "ON" and an is not None:
                zyklen[bahn].append((an, frame))
                an = None
            if zustand in ("ON", "OFF"):
                vor = zustand
    starts = {b: [x for x, _ in v] for b, v in zyklen.items()}

    with (a.lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as f:
        wuerfe = [r for r in csv.DictReader(f, delimiter=";")
                  if r["Herkunft"] == "gruenzyklus"]
    info = {}
    for r in wuerfe:
        b, fr = r["Bahn"], int(r["Frame"])
        p_ = next(((x, y) for x, y in zyklen.get(b, []) if x <= fr <= y + 60), None)
        if p_ is not None:
            info[(b, p_[1])] = r

    def eimer(bahn: str, frame: int):
        """(Gruen-AUS des Zyklus, Phase) -- oder None ausserhalb."""
        reihe = zyklen.get(bahn)
        if not reihe:
            return None
        i = bisect.bisect_right(starts[bahn], frame) - 1
        if i < 0:
            return None
        an, aus = reihe[i]
        if frame <= aus:
            return aus, "bis"
        if frame <= aus + NACHLAUF:
            return aus, "nach"
        return None

    # (bahn, wurf, phase, pin) -> [an, aus, wechsel]
    zaehler: dict[tuple, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
    letzter: dict[tuple, str] = {}

    with (a.lauf / "lampenspur.csv").open(encoding="utf-8-sig") as f:
        f.readline()
        for zeile in f:
            t = zeile.split(";")
            anlass = t[9].strip()
            if anlass == "live":
                continue
            bahn, frame, zustand = t[2], int(t[0]), t[5]
            if zustand == "UNKNOWN":
                continue                    # keine Aussage, kein Wechsel
            treffer = eimer(bahn, frame)
            if treffer is None:
                continue
            wurf, phase = treffer
            pin = int(t[3].rsplit("_", 1)[1])
            s = (bahn, wurf, phase, pin)
            z = zaehler[s]
            z[0 if zustand == "ON" else 1] += 1
            if s in letzter and letzter[s] != zustand:
                z[2] += 1
            letzter[s] = zustand

    # Auswerten
    proWurf: dict[tuple, dict] = collections.defaultdict(
        lambda: {"bis": {}, "nach": {}})
    for (bahn, wurf, phase, pin), (an, aus, wechsel) in zaehler.items():
        proWurf[(bahn, wurf)][phase][pin] = (an, aus, wechsel)

    verteilung = collections.Counter()
    muster = collections.Counter()
    fehlercodes = []
    for (bahn, wurf), phasen in sorted(proWurf.items()):
        for phase in ("bis", "nach"):
            d = phasen[phase]
            if not d:
                continue
            blinkt = {p for p, v in d.items() if v[2] >= a.mindestwechsel}
            fest = {p for p, v in d.items() if v[2] == 0 and v[0] and not v[1]}
            for v in d.values():
                verteilung[v[2]] += 1
            if not blinkt:
                muster[(phase, "nichts blinkt")] += 1
            elif not fest:
                muster[(phase, "alles Leuchtende blinkt (Jubel)")] += 1
            else:
                muster[(phase, "FEST UND BLINKEND (Fehlercode)")] += 1
                fehlercodes.append((bahn, wurf, phase, sorted(fest), sorted(blinkt)))

    print("Wechsel je Lampe und Wurf -- wie oft kommt welche Zahl vor?")
    for w in sorted(verteilung):
        print(f"  {w:>2} Wechsel: {verteilung[w]:>7}")
    print(f"\n{'Phase':<6} {'Muster':<36} {'Anzahl':>7}")
    for (phase, name), n in sorted(muster.items()):
        print(f"{phase:<6} {name:<36} {n:>7}")

    print(f"\nFehlercode-Muster (fest UND blinkend zugleich): {len(fehlercodes)}")
    print(f"{'Bahn':>4} {'Frame':>7} {'Phase':>6} {'Ziffer':>6} {'gebucht':>7}  "
          f"{'dauerleuchtend':<22} blinkend")
    for bahn, wurf, phase, fest, blinkt in fehlercodes[:40]:
        r = info.get((bahn, wurf), {})
        print(f"{bahn:>4} {wurf:>7} {phase:>6} {r.get('Ziffer', '') or '-':>6} "
              f"{r.get('Kegel', '?'):>7}  {str(fest):<22} {blinkt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
