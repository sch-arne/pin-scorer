"""Prueft einen Lauf gegen die Ergebnistafel der Anlage.

WOZU: Am Ende eines Spieltags zeigt die Anlage seitlich eine Tabelle -- je
Spieler und je Bahn die Summe seiner 30 Wuerfe. Das ist eine bessere Wahrheit
als ein handgefuehrtes Wurfprotokoll: Sie kommt von der Anlage selbst, deckt
BEIDE Mannschaften ab, und sie ist unabhaengig von allem, was wir messen.

Geprueft wird ZWEIERLEI, und der Unterschied ist die eigentliche Diagnose:

  (a) GLEITENDES FENSTER ueber alle erkannten Wuerfe. Gesucht werden Stellen,
      an denen 30 aufeinanderfolgende Wuerfe genau eine Tafelzahl ergeben.
      Das kommt OHNE die Zykluserkennung aus -- Warmwerfen davor und danach
      verschiebt das Fenster nur. Geprueft wird damit die Wurferkennung und
      die Zaehlung fuer sich.

  (b) DIE ERKANNTEN SPIELE. Dieselbe Summe, aber ueber die Gruppen, die die
      Spielwechsel-Erkennung abgegrenzt hat.

      (a)   (b)    Bedeutung
      ---   ---    ---------
       ok    ok    alles stimmt
       ok    --    Wuerfe richtig, SATZABGRENZUNG falsch
       --    --    Wuerfe falsch -- die Abweichungshoehe sagt dann, ob es
                   einzelne Kegel sind oder ein verrutschter Satz

GEGENPROBE gegen Zufall: Bei Summen zwischen 177 und 232 kann ein Fenster auch
zufaellig passen. Deshalb wird geprueft, ob sich die gefundenen Fenster einer
Bahn UEBERSCHNEIDEN -- zwoelf Saetze auf einer Bahn liegen hintereinander, nicht
uebereinander. Ueberlappende Funde sind ein Warnzeichen und werden ausgewiesen.
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

WUERFE_JE_SATZ = 30


def lies_tafel(pfad: Path) -> dict[int, list[tuple[str, int]]]:
    """Je Bahn: (Spieler, Sollsumme)."""
    je_bahn: dict[int, list[tuple[str, int]]] = collections.defaultdict(list)
    with pfad.open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            for bahn in (2, 3, 4, 5):
                je_bahn[bahn].append((r["Spieler"], int(r[f"Bahn{bahn}"])))
    return dict(je_bahn)


def lies_lauf(pfad: Path) -> dict[int, list[dict]]:
    je: dict[int, list[dict]] = collections.defaultdict(list)
    with pfad.open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            je[int(r["Bahn"])].append(r)
    for b in je:
        je[b].sort(key=lambda x: int(x["Frame"]))
    return dict(je)


def fenster_suchen(kegel: list[int], soll: int) -> list[int]:
    """Startpositionen aller 30er-Fenster mit genau dieser Summe."""
    if len(kegel) < WUERFE_JE_SATZ:
        return []
    treffer = []
    summe = sum(kegel[:WUERFE_JE_SATZ])
    if summe == soll:
        treffer.append(0)
    for i in range(1, len(kegel) - WUERFE_JE_SATZ + 1):
        summe += kegel[i + WUERFE_JE_SATZ - 1] - kegel[i - 1]
        if summe == soll:
            treffer.append(i)
    return treffer


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--scoreboard", required=True, type=Path)
    a = p.parse_args()

    tafel = lies_tafel(a.scoreboard)
    lauf = lies_lauf(a.run / "wuerfe.csv")

    print(f"Ergebnistafel: {sum(len(v) for v in tafel.values())} Sollwerte "
          f"({len(tafel[2])} Spieler x 4 Bahnen)")
    print(f"Lauf         : {sum(len(v) for v in lauf.values())} Wuerfe\n")

    # ---------------------------------------------------------------- (a)
    print("(a) GLEITENDES FENSTER -- ohne die Zykluserkennung\n")
    gefunden_gesamt = 0
    belegung: dict[int, list] = {}
    for bahn in sorted(tafel):
        wuerfe = lauf.get(bahn, [])
        kegel = [int(w["Kegel"]) for w in wuerfe]
        print(f"  Bahn {bahn} ({len(kegel)} Wuerfe erkannt)")
        stellen = []
        for spieler, soll in tafel[bahn]:
            treffer = fenster_suchen(kegel, soll)
            if not treffer:
                print(f"    {spieler:<24} {soll:>4}   NICHT GEFUNDEN")
                continue
            gefunden_gesamt += 1
            for i in treffer:
                stellen.append((i, i + WUERFE_JE_SATZ, spieler, soll))
            zeit = float(wuerfe[treffer[0]]["Zeitstempel_s"]) / 60
            mehr = f"   ({len(treffer)} Stellen)" if len(treffer) > 1 else ""
            print(f"    {spieler:<24} {soll:>4}   Wurf {treffer[0] + 1}-"
                  f"{treffer[0] + WUERFE_JE_SATZ}, t={zeit:.1f} min{mehr}")
        belegung[bahn] = stellen
    print(f"\n  {gefunden_gesamt} von {sum(len(v) for v in tafel.values())} "
          f"Sollwerten wiedergefunden")

    # ---------------------------------------------------------------- Zufall?
    print("\n  Gegenprobe -- ueberschneiden sich die Funde?")
    for bahn in sorted(belegung):
        # Je Spieler nur die erste Fundstelle, sonst zaehlt Mehrdeutigkeit doppelt
        erste: dict = {}
        for von, bis, spieler, soll in belegung[bahn]:
            erste.setdefault(spieler, (von, bis))
        bereiche = sorted(erste.values())
        ueberlappt = sum(1 for i in range(1, len(bereiche))
                         if bereiche[i][0] < bereiche[i - 1][1])
        zustand = "sauber" if not ueberlappt else f"{ueberlappt} Ueberlappungen"
        print(f"    Bahn {bahn}: {len(bereiche)} Saetze, {zustand}")

    # ---------------------------------------------------------------- (b)
    print("\n(b) DIE ERKANNTEN SPIELE\n")
    for bahn in sorted(tafel):
        wuerfe = lauf.get(bahn, [])
        spiele: dict = collections.OrderedDict()
        for w in wuerfe:
            spiele.setdefault(int(w["Spiel"]), []).append(int(w["Kegel"]))
        sollwerte = collections.Counter(s for _, s in tafel[bahn])
        passend = 0
        zeilen = []
        for nr, k in spiele.items():
            summe = sum(k)
            treffer = summe in sollwerte and len(k) == WUERFE_JE_SATZ
            if treffer:
                passend += 1
            zeilen.append((nr, len(k), summe, treffer))
        print(f"  Bahn {bahn}: {passend} von {len(spiele)} erkannten Spielen "
              f"treffen einen Sollwert")
        for nr, n, summe, ok in zeilen:
            marke = "  <-- trifft" if ok else ""
            print(f"    Spiel {nr:>2}: {n:>3} Wuerfe, Summe {summe:>4}{marke}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
