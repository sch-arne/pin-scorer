"""Findet die Wuerfe eines Protokolls in einem Analyselauf wieder.

WOZU: `compare_protocol.py` setzt voraus, dass Protokoll und Lauf DASSELBE
enthalten -- es richtet zwei vollstaendige Folgen aneinander aus. Bei einem
Spieltag stimmt das nicht:

* Im Protokoll stehen nur die Spieler EINER Mannschaft.
* Es spielen immer nur zwei von ihnen gleichzeitig, auf wechselnden Bahnen.
* Dazwischen wird warmgeworfen -- das steht in keinem Protokoll, erzeugt aber
  Gruenzyklen und damit Wuerfe in unseren Daten.

Der Lauf enthaelt also VIEL MEHR als das Protokoll. Eine Ausrichtung ueber die
ganze Folge waere sinnlos; gesucht ist stattdessen, WO jeder einzelne Satz im
Lauf liegt.

VERFAHREN: Jeder Satz ist eine Folge von 30 Kegelzahlen. Fuer jede Bahn wird
diese Folge mit einem gleitenden Fenster ueber die Wurffolge des Laufs
geschoben und die Trefferzahl gezaehlt. Die beste Stelle gewinnt -- sofern sie
deutlich besser ist als die zweitbeste. Sonst ist die Fundstelle nicht
belastbar, und das wird gesagt statt geraten.

Aufruf:
    .venv/Scripts/python.exe tools/locate_protocol.py \
        --run debug/.../lauf_2026-08-30_10-56-21 \
        --protocol data/ground_truth/wurfprotokoll_spieltag_1.csv
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

# Ein Fund gilt als belastbar, wenn er mindestens so viele Wuerfe trifft ...
MINDESTQUOTE = 0.70
# ... und mindestens so viel besser ist als die zweitbeste Stelle (in Treffern).
MINDESTABSTAND = 4


def lies_protokoll(pfad: Path) -> dict:
    """Ergibt {(bahn, satz, spieler): [kegel, ...]} in Wurfreihenfolge."""
    saetze: dict = collections.OrderedDict()
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        for r in csv.DictReader(datei, delimiter=";"):
            schluessel = (int(r["Bahn"]), int(r["Satz"]), r["Spieler"])
            saetze.setdefault(schluessel, []).append(
                (int(r["Wurf"]), int(r["Kegel"])))
    return {k: [kegel for _, kegel in sorted(v)] for k, v in saetze.items()}


def lies_lauf(pfad: Path) -> dict:
    """Ergibt {bahn: [(frame, kegel, status), ...]} in Wurfreihenfolge."""
    je_bahn: dict = collections.defaultdict(list)
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        for r in csv.DictReader(datei, delimiter=";"):
            je_bahn[int(r["Bahn"])].append(
                (int(r["Frame"]), int(r["Kegel"]), r["Status"]))
    for b in je_bahn:
        je_bahn[b].sort()
    return dict(je_bahn)


def suche(muster: list[int], folge: list[int]) -> list[tuple[int, int]]:
    """Alle Startpositionen mit ihrer Trefferzahl, beste zuerst."""
    n, m = len(folge), len(muster)
    if m > n:
        return []
    ergebnis = []
    for i in range(n - m + 1):
        treffer = sum(1 for a, b in zip(muster, folge[i:i + m]) if a == b)
        ergebnis.append((treffer, i))
    ergebnis.sort(reverse=True)
    return ergebnis


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, type=Path,
                   help="Ordner eines Analyselaufs (enthaelt wuerfe.csv)")
    p.add_argument("--protocol", required=True, type=Path)
    a = p.parse_args()

    saetze = lies_protokoll(a.protocol)
    lauf = lies_lauf(a.run / "wuerfe.csv")

    print(f"Protokoll : {a.protocol.name} -- {len(saetze)} Saetze, "
          f"{sum(len(v) for v in saetze.values())} Wuerfe")
    print(f"Lauf      : {a.run.name} -- "
          f"{sum(len(v) for v in lauf.values())} Wuerfe auf {len(lauf)} Bahnen\n")

    gefunden = 0
    getroffen_gesamt = 0
    wuerfe_gesamt = 0
    belegt: dict = collections.defaultdict(list)

    for (bahn, satz, spieler), kegel in sorted(saetze.items()):
        if bahn not in lauf:
            print(f"  Bahn {bahn} Satz {satz} {spieler:<22} -- Bahn nicht im Lauf")
            continue
        folge = [k for _, k, _ in lauf[bahn]]
        treffer = suche(kegel, folge)
        wuerfe_gesamt += len(kegel)
        if not treffer:
            print(f"  Bahn {bahn} Satz {satz} {spieler:<22} -- Lauf zu kurz")
            continue

        best, pos = treffer[0]
        zweit = treffer[1][0] if len(treffer) > 1 else 0
        quote = best / len(kegel)
        frame_von = lauf[bahn][pos][0]
        frame_bis = lauf[bahn][pos + len(kegel) - 1][0]
        sicher = quote >= MINDESTQUOTE and (best - zweit) >= MINDESTABSTAND

        marke = "" if sicher else "   << UNSICHER"
        print(f"  Bahn {bahn} Satz {satz} {spieler:<22} "
              f"{best:>2}/{len(kegel)} ({quote * 100:5.1f} %)  "
              f"Wurf {pos + 1}-{pos + len(kegel)}  "
              f"t={frame_von / 25 / 60:6.1f}-{frame_bis / 25 / 60:.1f} min"
              f"  [zweitbeste: {zweit}]{marke}")
        if sicher:
            gefunden += 1
            getroffen_gesamt += best
            belegt[bahn].append((pos, pos + len(kegel), spieler, satz))

    print(f"\n{gefunden} von {len(saetze)} Saetzen sicher zugeordnet")
    if wuerfe_gesamt:
        print(f"Getroffene Wuerfe in den sicheren Funden: {getroffen_gesamt}")

    print("\nBelegung je Bahn (was NICHT im Protokoll steht, ist Warmwerfen "
          "oder ein fremder Spieler):")
    for bahn in sorted(lauf):
        n = len(lauf[bahn])
        abgedeckt = set()
        for von, bis, _, _ in belegt.get(bahn, []):
            abgedeckt.update(range(von, bis))
        print(f"  Bahn {bahn}: {len(abgedeckt):>3} von {n:>3} Wuerfen "
              f"({len(abgedeckt) / max(n, 1) * 100:4.1f} %) einem Satz zugeordnet")
        for von, bis, spieler, satz in sorted(belegt.get(bahn, [])):
            print(f"        Wurf {von + 1:>3}-{bis:>3}  Satz {satz}  {spieler}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
