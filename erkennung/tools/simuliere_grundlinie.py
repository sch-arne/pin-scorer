"""Rechnet die vorgeschlagene Grundlinien-Regel gegen den ganzen Lauf.

WOZU (Nutzer, 2026-09-25): *"Bei der Grundlinie muessen so spaete Frames wie
moeglich genommen werden, was aber spaet heisst ist davon abhaengig, wann der
naechste Wurf stattfindet."*

HEUTE: Die Grundlinie ist die Vereinigung der Messungen an festen Versaetzen
nach Gruen-AN (`baseline_offsets`). Leuchtet dort ein Fehlercode nach, gehen
dessen Lampen mit ein.

VORSCHLAG: Nicht zaehlen, sondern warten -- den Stand nehmen, sobald er
`ruhe` Messungen lang unveraendert ist. Gemessen dauert das im Median zwei
Frames; nur beim Fehlercode rund achtunddreissig.

DIE AUSNAHME, DIE ES BRAUCHT: Laeuft beim Gruen-AN noch ein Jubel-Blinken des
VORIGEN Wurfs (alle Neune, 8er Kranz), wird der Stand nie ruhig -- und die
Dunkelphase saehe aus wie ein leerer Kranz. Blinkt ALLES, was leuchtet, gilt
darum weiter die Vereinigung. Blinkt nur ein Teil, ist es ein Fehlercode und
es wird gewartet.

Gemessen wird gegen die KEGELZIFFER: Sie sagt, wieviele Kegel der Wurf hatte,
und die Grundlinie geht direkt in diese Zahl ein.

Aufruf:

    .venv/Scripts/python.exe tools/simuliere_grundlinie.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
from pathlib import Path

RUHE = 3            # so viele gleiche Messungen hintereinander heissen "steht"


def gruenzyklen(lauf: Path):
    folge = collections.defaultdict(list)
    with (lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            folge[r["Bahn"]].append((int(r["Frame"]), r["Zustand"]))
    zyklen = collections.defaultdict(list)
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
    return zyklen


def neue_grundlinie(messungen: list[tuple[int, frozenset]], ruhe: int):
    """(Grundlinie, Begruendung) aus der Folge (Frame, leuchtende Lampen)."""
    if not messungen:
        return frozenset(), "keine Messung"

    staende = [s for _, s in messungen]

    # KEINE Sonderbehandlung fuer Blinken noetig. Das Plateau-Kriterium
    # schliesst es schon aus: Waehrend eines Blinkens faellt regelmaessig
    # etwas weg, und ein Plateau, nach dem eine Lampe wieder ausgeht, wird
    # verworfen. Eine eigene "Jubel"-Ausnahme machte es sogar schlechter --
    # sie griff beim Wurf selbst statt beim vorigen und lieferte bei jedem
    # Neuner eine Grundlinie von neun (gemessen: 560 Wuerfe schlechter).

    # Das erste Plateau, nach dem nichts mehr WEGFAELLT.
    #
    # WARUM NICHT EINFACH "das erste Plateau" (gemessen 2026-09-25): Waehrend
    # eines Fehlercodes wiederholt sich der dauerleuchtende Teil -- die Regel
    # rastete auf [6,7,9] ein und machte aus einem Wurf mit 1 Kegel einen mit
    # 6. Kegel fallen aber nur; sie stehen nicht wieder auf. Ein Plateau, nach
    # dem eine Lampe wieder ausgeht, war deshalb kein Ergebnisstand, sondern
    # eine Blinkphase.
    for i in range(len(staende) - ruhe + 1):
        if len(set(staende[i:i + ruhe])) != 1:
            continue
        stand = staende[i]
        if all(stand <= spaeter for spaeter in staende[i:]):
            return stand, f"Plateau ab Messung {i}"
    return staende[-1], "kein Plateau -- letzte Messung"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--ruhe", type=int, default=RUHE)
    a = p.parse_args()

    zyklen = gruenzyklen(a.lauf)
    starts = {b: [x for x, _ in v] for b, v in zyklen.items()}

    with (a.lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as f:
        wuerfe = [r for r in csv.DictReader(f, delimiter=";")
                  if r["Herkunft"] == "gruenzyklus"]
    zu_zyklus = {}
    for r in wuerfe:
        b, fr = r["Bahn"], int(r["Frame"])
        z = next(((x, y) for x, y in zyklen.get(b, []) if x <= fr <= y + 60), None)
        if z:
            zu_zyklus[(b, z[1])] = r

    # Messungen je Zyklus einsammeln: Grundlinienfenster und Ergebnis
    grund = collections.defaultdict(lambda: collections.defaultdict(set))
    ergeb = collections.defaultdict(lambda: collections.defaultdict(set))
    alles = collections.defaultdict(lambda: collections.defaultdict(set))
    with (a.lauf / "lampenspur.csv").open(encoding="utf-8-sig") as f:
        f.readline()
        for zeile in f:
            t = zeile.split(";")
            anlass = t[9].strip()
            if anlass == "live":
                continue
            b, fr = t[2], int(t[0])
            if b not in starts:
                continue
            i = bisect.bisect_right(starts[b], fr) - 1
            if i < 0:
                continue
            an, aus = zyklen[b][i]
            if fr > aus:
                continue
            # `grund` ist das HEUTIGE Fenster, `ergeb` der Rest der
            # Gruenphase. `alles` ist beides zusammen -- nur damit kann die
            # neue Regel ueber das heutige Fenster hinaus warten.
            for ziel in ((grund if anlass == "grundlinie" else ergeb), alles):
                eintrag = ziel[(b, aus)][fr]
                if t[5] == "ON":
                    eintrag.add(int(t[3].rsplit("_", 1)[1]))

    bilanz = collections.Counter()
    gruende = collections.Counter()
    geaendert = []
    for schluessel, r in sorted(zu_zyklus.items()):
        fenster = grund.get(schluessel, {})
        if not fenster:
            continue
        alt = frozenset().union(
            *[frozenset(s) for s in fenster.values()])
        messungen = [(fr, frozenset(s))
                     for fr, s in sorted(alles[schluessel].items())]
        neu, warum = neue_grundlinie(messungen, a.ruhe)
        gruende[warum.split(" ab ")[0]] += 1

        # Ergebnis = Vereinigung ueber die Gruenphase minus Grundlinie
        endstand = frozenset().union(
            *[frozenset(s) for s in ergeb.get(schluessel, {}).values()]
        ) if ergeb.get(schluessel) else frozenset()
        try:
            ziffer = int(r["Ziffer"])
        except (TypeError, ValueError):
            continue
        n_alt, n_neu = len(endstand - alt), len(endstand - neu)
        bilanz["geprueft"] += 1
        bilanz["alt richtig"] += (n_alt == ziffer)
        bilanz["neu richtig"] += (n_neu == ziffer)
        if alt != neu:
            bilanz["Grundlinie anders"] += 1
            if (n_alt == ziffer) != (n_neu == ziffer):
                geaendert.append((schluessel, r, sorted(alt), sorted(neu),
                                  n_alt, n_neu, ziffer))

    print(f"Wie oft welcher Weg: {dict(gruende)}\n")
    print(f"Geprueft (Kegelziffer lesbar): {bilanz['geprueft']}")
    print(f"  Grundlinie weicht ab:        {bilanz['Grundlinie anders']}")
    print(f"  heute  richtig:              {bilanz['alt richtig']}")
    print(f"  Regel  richtig:              {bilanz['neu richtig']}")
    besser = [g for g in geaendert if g[5] == g[6]]
    schlechter = [g for g in geaendert if g[4] == g[6]]
    print(f"\nBESSER {len(besser)} | SCHLECHTER {len(schlechter)}")
    for name, menge in (("BESSER", besser), ("SCHLECHTER", schlechter)):
        for (b, aus), r, alt, neu, na, nn, z in menge[:15]:
            print(f"  {name:<10} Bahn {b} Spiel {r['Spiel']:>2} Wurf "
                  f"{r['Wurfnummer']:>2} F{aus:>7}: Ziffer {z}, "
                  f"heute {na} (Grundlinie {alt}), Regel {nn} (Grundlinie {neu})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
