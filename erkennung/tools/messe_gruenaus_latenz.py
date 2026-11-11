"""Was der Erkennungsverzug von Gruen-AUS bei engerer Hysterese waere.

WOZU (Nutzer, 2026-09-28): *„wie viele Sekunden nach tatsaechlichem Gruen Aus
koennen wir spaetestens gruen aus abtasten und feststellen?"* -- gemessen:
Median 0,10 s, p99 2,45 s, schlechtester Fall 3,85 s. Der Verzug ist reine
Hysterese; die gruene Lampe wird jeden Frame gelesen.

Das ist wichtig fuer das rueckwaerts gemessene Fenster: Alles, was wir zu
spaet als Gruen-AUS erklaeren, verschiebt das ganze Fenster nach hinten und
frisst die Grundlinie an.

HIER WIRD DURCHGESPIELT, was passierte, wenn die AUS-Schwelle hoeher laege
oder weniger stabile Frames verlangt wuerden. Zwei Groessen stehen sich
gegenueber:

    Verzug          wie spaet wir AUS erklaeren
    Falschabbruch   wie oft wir MITTEN in der Gruenphase AUS erklaeren, weil
                    der Score kurz einbricht -- das zerhackt einen Wurf in zwei

Ein Verfahren ist nur dann besser, wenn es den Verzug senkt, OHNE
Falschabbrueche einzuhandeln.

Aufruf:

    .venv/Scripts/python.exe tools/messe_gruenaus_latenz.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45
"""

from __future__ import annotations

import argparse
import collections
import csv
import statistics
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--fps", type=float, default=20.0)
    a = p.parse_args()

    reihen = collections.defaultdict(list)
    with (a.lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            reihen[r["Bahn"]].append(
                (int(r["Frame"]), r["Zustand"], float(r["Score"])))
    for b in reihen:
        reihen[b].sort()

    # Die Gruenphasen, wie sie heute erkannt werden, samt Niveaus.
    phasen = []          # (bahn, von_idx, bis_idx, an_niveau, aus_niveau)
    for b, reihe in reihen.items():
        vor = anIdx = None
        for i, (fr, zu, sc) in enumerate(reihe):
            if zu == "ON" and vor != "ON":
                anIdx = i
            elif zu == "OFF" and vor == "ON" and anIdx is not None:
                an_niveau = statistics.median(
                    [x[2] for x in reihe[anIdx:i]] or [sc])
                nach = [x[2] for x in reihe[i:i + 30]]
                phasen.append((b, anIdx, i, an_niveau,
                               statistics.median(nach) if nach else sc))
                anIdx = None
            if zu in ("ON", "OFF"):
                vor = zu

    def uebergang(b, anIdx, ausIdx, an_niveau, aus_niveau):
        """Der physische Abfall: letzter Frame oberhalb der Mitte."""
        mitte = (an_niveau + aus_niveau) / 2
        reihe = reihen[b]
        for j in range(ausIdx - 1, anIdx - 1, -1):
            if reihe[j][2] > mitte:
                return reihe[j][0]
        return None

    varianten = [("heute (35,0 / 3 Frames)", None, None)]
    for schwelle in (37.0, 40.0, 42.0):
        for stabil in (1, 2, 3):
            varianten.append((f"AUS ab {schwelle:.0f}, {stabil} Frame(n)",
                              schwelle, stabil))

    print(f"{len(phasen)} Gruenphasen, {a.fps} fps\n")
    print(f"{'Verfahren':<26} {'Median':>8} {'p95':>7} {'p99':>7} {'max':>7} "
          f"{'Falschabbruch':>14}")
    for name, schwelle, stabil in varianten:
        verzug = []
        falsch = 0
        for b, anIdx, ausIdx, an_n, aus_n in phasen:
            echt = uebergang(b, anIdx, ausIdx, an_n, aus_n)
            if echt is None:
                continue
            reihe = reihen[b]
            if schwelle is None:
                erklaert = reihe[ausIdx][0]
            else:
                # Von Gruen-AN an vorwaerts: der erste Frame, ab dem der Score
                # `stabil` Messungen lang unter der Schwelle bleibt.
                erklaert = None
                zaehler = 0
                for j in range(anIdx, ausIdx + 1):
                    if reihe[j][2] < schwelle:
                        zaehler += 1
                        if zaehler >= stabil:
                            erklaert = reihe[j][0]
                            break
                    else:
                        zaehler = 0
                if erklaert is None:
                    erklaert = reihe[ausIdx][0]
                elif erklaert < echt:
                    falsch += 1        # mitten in der Phase abgebrochen
                    continue
            verzug.append(erklaert - echt)
        if not verzug:
            continue
        v = sorted(verzug)
        pq = lambda q: v[min(len(v) - 1, int(len(v) * q))]
        print(f"{name:<26} {statistics.median(v)/a.fps:>7.2f}s "
              f"{pq(0.95)/a.fps:>6.2f}s {pq(0.99)/a.fps:>6.2f}s "
              f"{v[-1]/a.fps:>6.2f}s {falsch:>8} "
              f"{100*falsch/len(phasen):>5.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
