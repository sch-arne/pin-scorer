"""Wertet die Lampenspur aus: Sitzt die Grundlinie je Lampe richtig?

WOZU: Die Kegellampen arbeiten mit einem anderen Verfahren als die gruene
Lampe. Statt zwei Wolken zu trennen, messen sie NUR das AUS-Niveau (15.
Perzentil ueber 400 Messungen) und legen die Schwellen anteilig zwischen dieses
Niveau und die Saettigung (255). Das ist begruendet -- eine leuchtende
Kegellampe ist im Bild gesaettigt (gemessen: AN min 229,1, Median 253,7) --
setzt aber voraus, dass die Grundlinie im AUS-Bereich bleibt.

DIE FRAGE, die diese Auswertung beantwortet: Tut sie das? Steht eine Lampe
lange an, koennte ihr Bezugswert mitwandern und sie sich am Ende selbst
abschalten. Dagegen gibt es zwei Sicherungen (`baseline_ignore_above` und eine
harte Klammer), aber ob sie richtig sitzen, ist seit ihrer Einfuehrung nicht
mehr am Material nachgeprueft worden.

Gezeigt wird je Bahn und Lampe:

    * die Verteilung der Helligkeit -- zweigipflig, wie erwartet?
    * wo die Grundlinie darin liegt: unter der AUS-Wolke (richtig) oder
      mitten in ihr (dann werden AUS-Messungen zu UNKNOWN)
    * der Anteil UNKNOWN, also der Messungen, die zwischen den Schwellen
      liegen und damit nichts entscheiden
    * wie weit die Grundlinie ueber den Lauf gewandert ist

Das Werkzeug entscheidet nichts. Es sagt, wo der Massstab steht.
"""

from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--trace", required=True, type=Path,
                   help="lampenspur.csv eines Laufs")
    p.add_argument("--lane", type=int, default=None)
    p.add_argument("--details", action="store_true",
                   help="je Lampe eine Zeile statt nur je Bahn")
    a = p.parse_args()

    # Je (Bahn, Lampe): Helligkeiten, Zustaende, Grundlinien, Schwellen
    hell: dict = collections.defaultdict(list)
    zustand: dict = collections.defaultdict(collections.Counter)
    grund: dict = collections.defaultdict(list)
    an_s: dict = collections.defaultdict(list)
    aus_s: dict = collections.defaultdict(list)

    with a.trace.open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            bahn = int(r["Bahn"])
            if a.lane is not None and bahn != a.lane:
                continue
            schluessel = (bahn, r["Lampe"])
            hell[schluessel].append(float(r["Helligkeit"]))
            zustand[schluessel][r["Zustand"]] += 1
            g = float(r["Grundlinie"])
            if not np.isnan(g):
                grund[schluessel].append(g)
            an_s[schluessel].append(float(r["AN_Schwelle"]))
            aus_s[schluessel].append(float(r["AUS_Schwelle"]))

    if not hell:
        raise SystemExit("Keine Zeilen gefunden")

    print(f"{sum(len(v) for v in hell.values())} Messungen, "
          f"{len(hell)} Lampen\n")

    # --- Je Bahn zusammengefasst ---
    print("JE BAHN")
    print(f"  {'Bahn':>5} {'Messungen':>10} {'AN':>7} {'AUS':>7} "
          f"{'UNKNOWN':>9} {'Grundlinie':>18} {'AUS-Wolke (P50)':>16}")
    bahnen = sorted({b for b, _ in hell})
    for bahn in bahnen:
        teile = [k for k in hell if k[0] == bahn]
        alle = np.concatenate([hell[k] for k in teile])
        z = collections.Counter()
        for k in teile:
            z.update(zustand[k])
        gesamt = sum(z.values())
        g = np.concatenate([grund[k] for k in teile if grund[k]]) if any(
            grund[k] for k in teile) else np.array([np.nan])
        # Die AUS-Wolke: alles unterhalb der Mitte zwischen den Schwellen
        schwelle = float(np.mean([np.mean(aus_s[k]) for k in teile]))
        aus_wolke = alle[alle <= schwelle]
        print(f"  {bahn:>5} {gesamt:>10} "
              f"{z['ON'] / gesamt:>6.1%} {z['OFF'] / gesamt:>6.1%} "
              f"{z['UNKNOWN'] / gesamt:>8.1%} "
              f"{np.nanmin(g):>7.1f}-{np.nanmax(g):<10.1f} "
              f"{np.percentile(aus_wolke, 50) if aus_wolke.size else float('nan'):>16.1f}")

    # --- Wo liegt die Grundlinie in der AUS-Wolke? ---
    print("\nWO DIE GRUNDLINIE IN DER AUS-WOLKE LIEGT")
    print("  Richtig ist: unterhalb. Liegt sie MITTEN in der Wolke, werden")
    print("  echte AUS-Messungen zu UNKNOWN und die Zaehlung unvollstaendig.\n")
    print(f"  {'Bahn':>5} {'Lampe':>12} {'Grundl.':>8} {'AUS-Wolke':>18} "
          f"{'Perzentil':>10} {'UNKNOWN':>9}")
    for schluessel in sorted(hell):
        bahn, lampe = schluessel
        if not grund[schluessel]:
            continue
        alle = np.array(hell[schluessel])
        schwelle = float(np.mean(aus_s[schluessel]))
        wolke = alle[alle <= schwelle]
        if wolke.size < 20:
            continue
        g = float(np.median(grund[schluessel]))
        # An welcher Stelle der AUS-Wolke sitzt die Grundlinie?
        perzentil = float((wolke < g).mean() * 100.0)
        z = zustand[schluessel]
        gesamt = sum(z.values())
        auffaellig = " <<" if perzentil > 40 else ""
        if not a.details and not auffaellig:
            continue
        print(f"  {bahn:>5} {lampe:>12} {g:>8.1f} "
              f"{np.percentile(wolke, 5):>7.1f}-{np.percentile(wolke, 95):<10.1f} "
              f"{perzentil:>9.0f}% {z['UNKNOWN'] / gesamt:>8.1%}{auffaellig}")

    # --- Wanderung ueber den Lauf ---
    print("\nWANDERUNG DER GRUNDLINIE (min -> max je Lampe)")
    print(f"  {'Bahn':>5} {'groesste Wanderung':>20} {'Lampe':>14}")
    for bahn in bahnen:
        teile = [k for k in hell if k[0] == bahn and grund[k]]
        if not teile:
            continue
        weiteste = max(teile, key=lambda k: max(grund[k]) - min(grund[k]))
        spanne = max(grund[weiteste]) - min(grund[weiteste])
        print(f"  {bahn:>5} {spanne:>19.1f} {weiteste[1]:>14}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
