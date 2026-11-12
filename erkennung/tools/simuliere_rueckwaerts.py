"""Rechnet das rueckwaerts gemessene Fenster gegen den ganzen Lauf.

DER VORSCHLAG (Nutzer, 2026-09-28): *„Sobald GRUEN AUS (im Sinne von Wurf
erfolgt!) nehmen wir die vergangenen 5 Sekunden... 1. Sekunde: Grundlinie
(was nicht leuchtet ist das Wurfbild). 2.-5. Sekunde: Wurf (was mindestens 1x
leuchtet ist gefallen)."* Nach der ersten Messung dann: *„6 Sekunden? Dann
muss es 2 und 4 sein."*

ALLES IN SEKUNDEN, nicht in Frames -- *„Wichtig waere es jedoch, dass das
ganze FRAMEUNABHAENGIG laeuft... denn die Frames koennen ja variieren die
Sekunden nicht."* Die Umrechnung passiert an genau einer Stelle, unten in
`fenster_frames`.

Der Anker ist Gruen-AUS statt Gruen-AN. Das loest drei Dinge auf einmal:
der Fehlercode beginnt erst nach Gruen-AUS und liegt ausserhalb; die
Grundlinie sitzt so spaet wie moeglich; und die Laenge der Gruenphase ist
egal -- ein Fehlwurf mit 34 Sekunden Gruen genauso wie ein Raeumwurf mit 4,5.

Reicht das Fenster vor das Gruen-AN zurueck, wird dort abgeschnitten.

Gemessen gegen die KEGELZIFFER. Der heutige Stand liegt bei 93,3 %.

Aufruf:

    .venv/Scripts/python.exe tools/simuliere_rueckwaerts.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
from pathlib import Path


def fenster_frames(sekunden: float, fps: float) -> int:
    """Die einzige Stelle, an der aus Sekunden Frames werden."""
    return max(1, round(sekunden * fps))


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


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--fps", type=float, default=20.0)
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

    # Alle Messungen der Gruenphase je Zyklus, auch "alle Lampen aus".
    stand = collections.defaultdict(dict)
    heute_grund = collections.defaultdict(dict)
    nach = collections.defaultdict(dict)
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
            ziele = [nach[(b, aus)]] if fr > aus else [stand[(b, aus)]]
            if anlass == "grundlinie":
                ziele.append(heute_grund[(b, aus)])
            for ziel in ziele:
                eintrag = ziel.setdefault(fr, set())
                if t[5] == "ON":
                    eintrag.add(int(t[3].rsplit("_", 1)[1]))

    def vereinigung(d, von=None, bis=None):
        teile = [frozenset(s) for fr, s in d.items()
                 if (von is None or fr >= von) and (bis is None or fr < bis)]
        return frozenset().union(*teile) if teile else None

    varianten = [(6.0, 2.0), (7.0, 2.0), (8.0, 2.0), (10.0, 2.0),
                 (14.0, 2.0), (99.0, 2.0)]
    bilanz = collections.Counter()
    fehlend = collections.Counter()
    for schluessel, r in zu_zyklus.items():
        try:
            ziffer = int(r["Ziffer"])
        except (TypeError, ValueError):
            continue
        b, aus = schluessel
        an = next(x for x, y in zyklen[b] if y == aus)
        messungen = stand.get(schluessel)
        if not messungen:
            continue
        bilanz["geprueft"] += 1

        # Heutiger Stand: Grundlinie aus dem festen Fenster nach Gruen-AN,
        # Ergebnis als Vereinigung ueber alles.
        g_heute = vereinigung(heute_grund.get(schluessel, {})) or frozenset()
        e_heute = (vereinigung(messungen) or frozenset()) | (
            vereinigung(nach.get(schluessel, {})) or frozenset())
        bilanz["heute"] += (len(e_heute - g_heute) == ziffer)

        for rueckblick, grundsek in varianten:
            start = max(an, aus - fenster_frames(rueckblick, a.fps))
            grenze = start + fenster_frames(grundsek, a.fps)
            g = vereinigung(messungen, start, grenze)
            e = vereinigung(messungen, grenze, None)
            if g is None or e is None:
                fehlend[(rueckblick, grundsek)] += 1
                # Kein verwertbares Fenster -> wie heute
                g, e = g_heute, e_heute
            bilanz[(rueckblick, grundsek)] += (len(e - g) == ziffer)

    n = bilanz["geprueft"]
    print(f"Geprueft: {n} Wuerfe mit lesbarer Kegelziffer, {a.fps} fps\n")
    print(f"{'Verfahren':<34} {'richtig':>9} {'Anteil':>8} {'Fenster leer':>13}")
    print(f"{'heute (Anker Gruen-AN)':<34} {bilanz['heute']:>9} "
          f"{100*bilanz['heute']/n:>7.1f}%")
    for v in varianten:
        name = f"rueckwaerts {v[0]} s, davon {v[1]} s Grundlinie"
        print(f"{name:<34} {bilanz[v]:>9} {100*bilanz[v]/n:>7.1f}% "
              f"{fehlend[v]:>13}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
