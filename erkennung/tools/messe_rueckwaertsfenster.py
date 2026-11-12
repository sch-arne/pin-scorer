"""Prueft die Annahmen des rueckwaerts gemessenen Fensters.

DER VORSCHLAG (Nutzer, 2026-09-28): *„Wir drehen den Spiess jetzt um. Sobald
GRUEN AUS (im Sinne von Wurf erfolgt!) nehmen wir die vergangenen 5 Sekunden
und werten diese wie folgt aus. 1. Sekunde: Grundlinie (was nicht leuchtet ist
das Wurfbild). 2.-5. Sekunde: Wurf (was mindestens 1x leuchtet ist gefallen
[oder stand schon vorher nicht mehr])."*

Der Anker wandert damit von Gruen-AN auf Gruen-AUS. Das loest drei Probleme
auf einmal: Der Fehlercode beginnt erst NACH Gruen-AUS und liegt damit
ausserhalb; die Grundlinie sitzt so spaet wie moeglich; und die Laenge der
Gruenphase spielt keine Rolle mehr.

DAMIT ES TRAEGT, MUESSEN DREI DINGE STIMMEN -- die werden hier gezaehlt:

    A  Der Zyklus ist mindestens 5 s lang. Sonst greift das Fenster in die
       Anzeige VOR dem Gruen-AN.
    B  Der erste fallende Kegel liegt in den letzten 4 s (Sekunde 2 bis 5).
       Faellt er frueher, sitzt er in der Grundliniensekunde und zaehlt
       faelschlich als "lag schon".
    C  In der Grundliniensekunde steht die Anzeige still. Wechselt sie dort,
       ist die Grundlinie nicht eindeutig.

Aufruf:

    .venv/Scripts/python.exe tools/messe_rueckwaertsfenster.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import statistics
from pathlib import Path


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
    p.add_argument("--fenster", type=float, default=5.0,
                   help="Laenge des Rueckblicks in Sekunden")
    p.add_argument("--grundlinie", type=float, default=1.0,
                   help="Davon die ersten so viele Sekunden als Grundlinie")
    a = p.parse_args()

    fenster = int(a.fenster * a.fps)
    grundsek = int(a.grundlinie * a.fps)
    zyklen = gruenzyklen(a.lauf)
    starts = {b: [x for x, _ in v] for b, v in zyklen.items()}

    with (a.lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as f:
        wuerfe = [r for r in csv.DictReader(f, delimiter=";")
                  if r["Herkunft"] == "gruenzyklus"]
    art = {}
    for r in wuerfe:
        b, fr = r["Bahn"], int(r["Frame"])
        z = next(((x, y) for x, y in zyklen.get(b, []) if x <= fr <= y + 60), None)
        if z:
            art[(b, z[1])] = "Raeumen" if r["Raeumen"] == "ja" else "Vollen"

    # Lampenstand je Frame je Zyklus (inkl. "alle aus")
    stand = collections.defaultdict(dict)
    with (a.lauf / "lampenspur.csv").open(encoding="utf-8-sig") as f:
        f.readline()
        for zeile in f:
            t = zeile.split(";")
            if t[9].strip() == "live":
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
            eintrag = stand[(b, aus)].setdefault(fr, set())
            if t[5] == "ON":
                eintrag.add(int(t[3].rsplit("_", 1)[1]))

    z = collections.Counter()
    zuKurz = collections.defaultdict(list)
    frueh = collections.defaultdict(list)
    abstand = collections.defaultdict(list)
    for (b, aus), frames in stand.items():
        if not frames:
            continue
        an = next(x for x, y in zyklen[b] if y == aus)
        kategorie = art.get((b, aus), "Vollen")
        z[kategorie] += 1

        # A -- Zykluslaenge
        if aus - an < fenster:
            z[(kategorie, "A zu kurz")] += 1
            zuKurz[kategorie].append((b, aus, aus - an))

        # B -- erster fallender Kegel, gemessen VON HINTEN
        fs = sorted(frames)
        basis = frames[fs[0]]
        erster = next((fr for fr in fs if frames[fr] - basis), None)
        if erster is not None:
            rueck = aus - erster          # Frames vor Gruen-AUS
            abstand[kategorie].append(rueck)
            if rueck > fenster - grundsek:
                z[(kategorie, "B faellt zu frueh")] += 1
                frueh[kategorie].append((b, aus, rueck))

        # C -- steht die Anzeige in der Grundliniensekunde still?
        gs = [frames[fr] for fr in fs
              if aus - fenster <= fr < aus - fenster + grundsek]
        if len(gs) >= 2 and len({frozenset(x) for x in gs}) > 1:
            z[(kategorie, "C unruhig")] += 1

    print(f"Fenster {a.fenster} s ({fenster} Frames), davon "
          f"{a.grundlinie} s Grundlinie ({grundsek} Frames), {a.fps} fps\n")
    print(f"{'Art':<9} {'Zyklen':>7} {'A zu kurz':>11} {'B zu frueh':>12} "
          f"{'C unruhig':>11}")
    for k in ("Vollen", "Raeumen"):
        n = z[k]
        if not n:
            continue
        print(f"{k:<9} {n:>7} "
              f"{z[(k,'A zu kurz')]:>5} {100*z[(k,'A zu kurz')]/n:>5.1f}% "
              f"{z[(k,'B faellt zu frueh')]:>6} {100*z[(k,'B faellt zu frueh')]/n:>5.1f}% "
              f"{z[(k,'C unruhig')]:>5} {100*z[(k,'C unruhig')]/n:>5.1f}%")

    print("\nAbstand erster fallender Kegel vor Gruen-AUS (Frames):")
    for k in ("Vollen", "Raeumen"):
        v = sorted(abstand[k])
        if not v:
            continue
        pp = lambda q: v[min(len(v) - 1, int(len(v) * q))]
        print(f"  {k:<9} N={len(v):>4}  Median {statistics.median(v):>4.0f}  "
              f"p90 {pp(0.90):>4}  p99 {pp(0.99):>4}  max {v[-1]:>5}")
    for k in ("Vollen", "Raeumen"):
        if zuKurz[k]:
            print(f"\n  kuerzeste Zyklen ({k}): "
                  + ", ".join(f"Bahn {b} F{aus} {d}F" for b, aus, d
                              in sorted(zuKurz[k], key=lambda x: x[2])[:5]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
