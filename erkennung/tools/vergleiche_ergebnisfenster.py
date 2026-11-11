"""Vergleicht Varianten, wie aus den Lampenmessungen ein Wurfergebnis wird.

WOZU (Nutzer, 2026-09-25): *"miss das noch... und miss bitte weitere
Moeglichkeiten das zu loesen"*

Gegen die KEGELZIFFER gemessen, ueber alle Wuerfe des Laufs. Die Ziffer weiss
nichts von den Lampen.

Varianten fuer die GRUNDLINIE:
    G1  Vereinigung ueber das heutige Fenster (`baseline_offsets`)
    G2  erstes Plateau, nach dem nichts mehr wegfaellt (ganze Gruenphase)

Varianten fuer das ERGEBNIS:
    E1  Vereinigung ueber alles, auch nach Gruen-AUS   (heutiger Stand)
    E2  Vereinigung nur bis Gruen-AUS
    E3  der letzte Stand vor Gruen-AUS
    E4  Mehrheit: eine Lampe zaehlt, wenn sie in mindestens der Haelfte der
        Messungen der Gruenphase brennt
    E5  das letzte Plateau (drei gleiche Messungen) vor Gruen-AUS

E1 ist der Stand von heute und der Massstab. E2 ist der billige Hebel gegen
den Fehlercode, der erst nach Gruen-AUS beginnt. E4 bricht die Praemisse
("eine Lampe kann nicht falsch leuchten") und ist nur als Vergleich dabei --
beim Blinken ist jede Lampe die halbe Zeit aus.
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
from pathlib import Path

RUHE = 3


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


def plateau(staende: list[frozenset], ruhe: int = RUHE):
    """Erstes Plateau, nach dem keine Lampe mehr ausgeht."""
    for i in range(len(staende) - ruhe + 1):
        if len(set(staende[i:i + ruhe])) != 1:
            continue
        if all(staende[i] <= spaeter for spaeter in staende[i:]):
            return staende[i]
    return staende[-1] if staende else frozenset()


def fehlercode(staende: list[frozenset]) -> bool:
    """Blinkt ein TEIL der Lampen, waehrend ein anderer fest leuchtet?"""
    if len(staende) < 3:
        return False
    blinkt = fest = 0
    for pin in range(1, 10):
        v = [pin in s for s in staende]
        wechsel = sum(1 for x, y in zip(v, v[1:]) if x != y)
        if wechsel >= 2:
            blinkt += 1
        elif all(v):
            fest += 1
    return bool(blinkt and fest)


def letztes_plateau(staende: list[frozenset], ruhe: int = RUHE):
    for i in range(len(staende) - ruhe, -1, -1):
        if len(set(staende[i:i + ruhe])) == 1:
            return staende[i]
    return staende[-1] if staende else frozenset()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
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

    # Je Zyklus: Messungen getrennt nach Rolle
    fenster = collections.defaultdict(
        lambda: {"grund": {}, "bis": {}, "nach": {}})
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
            if fr > aus + 120:
                continue
            rolle = "nach" if fr > aus else ("grund" if anlass == "grundlinie"
                                             else "bis")
            eintrag = fenster[(b, aus)][rolle].setdefault(fr, set())
            if t[5] == "ON":
                eintrag.add(int(t[3].rsplit("_", 1)[1]))
            # Die Grundlinienmessungen liegen zeitlich VOR der Gruenphase und
            # gehoeren fuer die Plateau-Suche mit dazu.
            if rolle == "grund":
                e2 = fenster[(b, aus)]["bis"].setdefault(fr, set())
                if t[5] == "ON":
                    e2.add(int(t[3].rsplit("_", 1)[1]))

    def folge(d):
        return [frozenset(s) for _, s in sorted(d.items())]

    bilanz = collections.Counter()
    for schluessel, r in zu_zyklus.items():
        try:
            ziffer = int(r["Ziffer"])
        except (TypeError, ValueError):
            continue
        f = fenster.get(schluessel)
        if not f or not f["bis"]:
            continue
        bis = folge(f["bis"])
        nach = folge(f["nach"])
        alle = bis + nach

        g1 = frozenset().union(*folge(f["grund"])) if f["grund"] else frozenset()
        g2 = plateau(bis)

        e = {
            "E1 Vereinigung alles": frozenset().union(*alle),
            "E2 nur bis Gruen-AUS": frozenset().union(*bis),
            "E3 letzter Stand": bis[-1],
            "E4 Mehrheit": frozenset(
                p_ for p_ in range(1, 10)
                if sum(1 for s in bis if p_ in s) * 2 >= len(bis)),
            "E5 letztes Plateau": letztes_plateau(bis),
            # E6: wie heute -- ausser wenn NACH Gruen-AUS ein Fehlercode
            # laeuft. Erkennbar daran, dass ein Teil der Lampen blinkt,
            # waehrend ein anderer fest leuchtet (BUG-036). Beim Jubel-Blinken
            # blinkt alles, was leuchtet; dort bleibt die Vereinigung.
            "E6 alles, ausser Fehlercode": (
                frozenset().union(*bis) if fehlercode(nach)
                else frozenset().union(*alle)),
        }
        bilanz["geprueft"] += 1
        for name, stand in e.items():
            bilanz[(name, "G1")] += (len(stand - g1) == ziffer)
            bilanz[(name, "G2")] += (len(stand - g2) == ziffer)

    n = bilanz["geprueft"]
    print(f"Geprueft: {n} Wuerfe mit lesbarer Kegelziffer\n")
    print(f"{'Ergebnisfenster':<24} {'G1 Vereinigung':>16} {'G2 Plateau':>14}")
    for name in ("E1 Vereinigung alles", "E2 nur bis Gruen-AUS",
                 "E3 letzter Stand", "E4 Mehrheit", "E5 letztes Plateau",
                 "E6 alles, ausser Fehlercode"):
        a1, a2 = bilanz[(name, "G1")], bilanz[(name, "G2")]
        print(f"{name:<24} {a1:>7} {100*a1/n:>6.1f}% {a2:>6} {100*a2/n:>6.1f}%")
    print("\nG1 = Grundlinie wie heute, G2 = erstes Plateau. "
          "E1/G1 ist der heutige Stand.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
