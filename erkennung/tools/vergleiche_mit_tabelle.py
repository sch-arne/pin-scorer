#!/usr/bin/env python
"""Vergleicht die erfassten Wuerfe mit der Ergebnistabelle des Streams.

WOFUER

Die Uebertragung blendet links und rechts die Ergebnistabellen ein -- je
Spieler die Kegelzahl auf jeder der vier Bahnen. Das ist die Wahrheit, gegen
die sich die Erfassung messen laesst, und zwar ueber einen ganzen Spieltag.

Verglichen wird auf drei Ebenen, von grob nach fein:

    Gesamtsumme       eine Zahl, sofort sichtbar ob etwas grundsaetzlich fehlt
    Summe je Bahn     zeigt, ob eine einzelne Bahn ausfaellt
    Wurfzahl je Bahn  jeder Spieler wirft 120, vier Spieler also 480 je Bahn

Die Wahrheitsdatei enthaelt KEINE Namen: Die Zahlen genuegen, und Namen
realer Spieler gehoeren nicht in ein Repository.

    .venv/Scripts/python.exe tools/vergleiche_mit_tabelle.py \
        --lauf debug/<quelle>/lauf_<zeit> --wahrheit wahrheit.json
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


def lies_lauf(lauf: Path) -> tuple[dict[int, int], dict[int, int], Counter]:
    """Summe und Wurfzahl je Bahn aus dem Wurfprotokoll."""
    pfad = lauf / "wuerfe.csv"
    if not pfad.is_file():
        raise SystemExit(f"Kein Wurfprotokoll unter {pfad}")
    kegel: dict[int, int] = defaultdict(int)
    wuerfe: dict[int, int] = defaultdict(int)
    status: Counter = Counter()
    with pfad.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            try:
                bahn = int(r["Bahn"])
                zahl = int(r["Kegel"])
            except (KeyError, ValueError, TypeError):
                continue
            kegel[bahn] += zahl
            wuerfe[bahn] += 1
            status[r.get("Status", "?")] += 1
    return dict(kegel), dict(wuerfe), status


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--wahrheit", required=True, type=Path)
    p.add_argument("--wuerfe-je-bahn", type=int, default=480,
                   help="Sollzahl der Wuerfe je Bahn (Spieler x 120)")
    a = p.parse_args()

    kegel, wuerfe, status = lies_lauf(a.lauf)
    wahr = json.loads(a.wahrheit.read_text(encoding="utf-8"))
    je_bahn = {int(k): v for k, v in wahr["je_bahn"].items()}

    print("Status der erfassten Wuerfe:",
          ", ".join(f"{k} {v}" for k, v in status.most_common()))
    print()
    print("%5s %10s %10s %10s %8s | %8s %8s"
          % ("Bahn", "erfasst", "Tabelle", "Differenz", "Anteil",
             "Wuerfe", "Soll"))
    ges_ist = ges_soll = 0
    for bahn in sorted(je_bahn):
        ist = kegel.get(bahn, 0)
        soll = je_bahn[bahn]["gesamt"]
        ges_ist += ist
        ges_soll += soll
        anteil = f"{100 * ist / soll:5.1f}%" if soll else "  --  "
        print("%5d %10d %10d %+10d %8s | %8d %8d"
              % (bahn, ist, soll, ist - soll, anteil,
                 wuerfe.get(bahn, 0), a.wuerfe_je_bahn))
    anteil = f"{100 * ges_ist / ges_soll:5.1f}%" if ges_soll else "  --  "
    print("%5s %10d %10d %+10d %8s | %8d %8d"
          % ("alle", ges_ist, ges_soll, ges_ist - ges_soll, anteil,
             sum(wuerfe.values()), a.wuerfe_je_bahn * len(je_bahn)))

    print("\nZur Einordnung: Die Tabelle des Streams ist selbst nicht ganz "
          "widerspruchsfrei.")
    print("Eine Gastzeile nennt als Summe 798, ihre vier Bahnwerte ergeben "
          "aber 804.")
    print("Die Summe je Mannschaft (4859 und 4515) ist dagegen in sich "
          "stimmig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
