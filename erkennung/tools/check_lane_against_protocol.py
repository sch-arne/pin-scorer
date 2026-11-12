"""Vergleicht eine Bahn Wurf fuer Wurf mit dem Protokoll -- innerhalb der Saetze.

WOZU: Die Mustersuche (`locate_protocol.py`) findet einen Satz nur, wenn er
weitgehend stimmt. Genau dort, wo es Probleme gibt, versagt sie deshalb -- auf
Bahn 5 blieben drei Saetze "unsicher", und damit war ueber die Fehler nichts
gesagt.

Der Ausweg (Idee des Nutzers, 2026-08-30): Auf einer SAUBEREN Bahn liegen die
Saetze fest. Immer wenn dort ein VOK-Spieler warf, war zeitgleich einer auf der
fraglichen Bahn. Das Zeitfenster der sauberen Bahn ist damit der Anker, und
innerhalb dieses Fensters laesst sich Wurf fuer Wurf ausrichten -- auch wenn
mehrere Werte falsch sind.

Ausgerichtet wird mit Needleman-Wunsch. Eine LUECKE muss teurer sein als ein
falscher Wert, sonst erklaert die Ausrichtung jede Abweichung lieber durch
"fehlt + zuviel" statt durch einen Lesefehler.
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

TREFFER, DANEBEN, LUECKE = 2, -1, -3


def lies_protokoll(pfad: Path) -> dict:
    saetze: dict = collections.OrderedDict()
    with pfad.open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            saetze.setdefault((int(r["Bahn"]), r["Spieler"]), []).append(
                (int(r["Wurf"]), int(r["Kegel"])))
    return {k: [k2 for _, k2 in sorted(v)] for k, v in saetze.items()}


def lies_lauf(pfad: Path) -> dict:
    je: dict = collections.defaultdict(list)
    with pfad.open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            je[int(r["Bahn"])].append({
                "frame": int(r["Frame"]), "kegel": int(r["Kegel"]),
                "wurfnr": r["Wurfnummer"], "status": r["Status"],
                "conf": r["Confidence"], "t": float(r["Zeitstempel_s"])})
    for b in je:
        je[b].sort(key=lambda x: x["frame"])
    return dict(je)


def richte_aus(a: list[int], b: list[int]):
    """Needleman-Wunsch. Gibt Paare (i, j) zurueck; None = Luecke."""
    n, m = len(a), len(b)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i * LUECKE
    for j in range(1, m + 1):
        d[0][j] = j * LUECKE
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            passt = TREFFER if a[i - 1] == b[j - 1] else DANEBEN
            d[i][j] = max(d[i - 1][j - 1] + passt,
                          d[i - 1][j] + LUECKE, d[i][j - 1] + LUECKE)
    paare, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            passt = TREFFER if a[i - 1] == b[j - 1] else DANEBEN
            if d[i][j] == d[i - 1][j - 1] + passt:
                paare.append((i - 1, j - 1)); i -= 1; j -= 1; continue
        if i > 0 and d[i][j] == d[i - 1][j] + LUECKE:
            paare.append((i - 1, None)); i -= 1; continue
        paare.append((None, j - 1)); j -= 1
    return list(reversed(paare))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--protocol", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True, help="zu pruefende Bahn")
    p.add_argument("--anchor-lane", type=int, required=True,
                   help="saubere Bahn, deren Saetze das Zeitfenster liefern")
    p.add_argument("--pad", type=int, default=60,
                   help="Sekunden Luft um das Fenster (Standard 60)")
    a = p.parse_args()

    saetze = lies_protokoll(a.protocol)
    lauf = lies_lauf(a.run / "wuerfe.csv")
    if a.lane not in lauf or a.anchor_lane not in lauf:
        raise SystemExit("Bahn nicht im Lauf")

    # 1) Anker: die Saetze der sauberen Bahn exakt lokalisieren
    anker_folge = [w["kegel"] for w in lauf[a.anchor_lane]]
    fenster = []
    for (bahn, spieler), kegel in saetze.items():
        if bahn != a.anchor_lane:
            continue
        best, pos = -1, 0
        for i in range(len(anker_folge) - len(kegel) + 1):
            t = sum(1 for x, y in zip(kegel, anker_folge[i:i + len(kegel)])
                    if x == y)
            if t > best:
                best, pos = t, i
        if best < len(kegel) * 0.9:
            print(f"  Anker {spieler} nur {best}/{len(kegel)} -- uebersprungen")
            continue
        von = lauf[a.anchor_lane][pos]["t"]
        bis = lauf[a.anchor_lane][pos + len(kegel) - 1]["t"]
        fenster.append((von, bis, spieler, best, len(kegel)))
    fenster.sort()

    print(f"Anker Bahn {a.anchor_lane}: {len(fenster)} Saetze lokalisiert")
    for von, bis, spieler, best, n in fenster:
        print(f"   {von / 60:6.1f}-{bis / 60:6.1f} min  {spieler:<22} {best}/{n}")

    # 2) In jedem Zeitfenster die Wuerfe der fraglichen Bahn ausrichten
    print(f"\n{'=' * 72}\nBAHN {a.lane} -- Wurf fuer Wurf im jeweiligen Fenster\n")
    summe_t = summe_f = summe_l = summe_u = 0
    for von, bis, anker_spieler, _, _ in fenster:
        kandidaten = [w for w in lauf[a.lane]
                      if von - a.pad <= w["t"] <= bis + a.pad]
        if not kandidaten:
            continue
        # Welcher Protokollsatz dieser Bahn passt in dieses Fenster?
        best_satz, best_score = None, -1
        for (bahn, spieler), kegel in saetze.items():
            if bahn != a.lane:
                continue
            paare = richte_aus(kegel, [w["kegel"] for w in kandidaten])
            t = sum(1 for i, j in paare if i is not None and j is not None
                    and kegel[i] == kandidaten[j]["kegel"])
            if t > best_score:
                best_score, best_satz = t, (spieler, kegel)
        if best_satz is None:
            continue
        spieler, kegel = best_satz
        paare = richte_aus(kegel, [w["kegel"] for w in kandidaten])

        treffer = fehler = luecken = ueberzaehlig = 0
        zeilen = []
        for i, j in paare:
            if i is not None and j is not None:
                w = kandidaten[j]
                if kegel[i] == w["kegel"]:
                    treffer += 1
                else:
                    fehler += 1
                    zeilen.append(f"      Wurf {i + 1:>2}: Protokoll {kegel[i]} "
                                  f"<-> erkannt {w['kegel']}  "
                                  f"F{w['frame']} t={w['t'] / 60:.1f}min "
                                  f"{w['status']} conf {w['conf']} "
                                  f"Wurfnr {w['wurfnr']}")
            elif i is not None:
                luecken += 1
                zeilen.append(f"      Wurf {i + 1:>2}: Protokoll {kegel[i]} "
                              f"<-> FEHLT")
            else:
                w = kandidaten[j]
                ueberzaehlig += 1
                zeilen.append(f"      ZUVIEL: erkannt {w['kegel']} Kegel  "
                              f"F{w['frame']} t={w['t'] / 60:.1f}min "
                              f"{w['status']} conf {w['conf']} "
                              f"Wurfnr {w['wurfnr']}")
        summe_t += treffer; summe_f += fehler
        summe_l += luecken; summe_u += ueberzaehlig
        print(f"  {von / 60:6.1f}-{bis / 60:6.1f} min  (Bahn {a.anchor_lane}: "
              f"{anker_spieler})  ->  {spieler}")
        print(f"      {treffer}/{len(kegel)} richtig, {fehler} falsch, "
              f"{luecken} fehlen, {ueberzaehlig} zuviel")
        for z in zeilen:
            print(z)
        print()

    print(f"{'=' * 72}\nBahn {a.lane} gesamt: {summe_t} richtig, {summe_f} falsch, "
          f"{summe_l} fehlen, {summe_u} zuviel")
    gesamt = summe_t + summe_f + summe_l
    if gesamt:
        print(f"Trefferquote: {summe_t / gesamt * 100:.1f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
