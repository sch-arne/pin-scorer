"""Findet Gruenzyklen, deren Grundlinie durch ein spaetes GREEN_ON verdorben ist.

HINTERGRUND (BUG-016): Die Grundlinie eines Wurfs wird bei GREEN_ON plus
`sampling.baseline_offsets` gemessen. Meldet der Detektor das Gruen-AN zu spaet,
rutscht dieses Fenster in die Zeit, in der die Kegel bereits fallen -- und weil
`aggregate_pin_readings` ueber die Frames VEREINIGT, genuegt eine einzige zu
spaete Messung, um die Grundlinie auf den Endstand zu heben. Ergebnis und
Grundlinie sind dann gleich, und `discard_unchanged_cycles` verwirft den Wurf.

WORAN MAN ES ERKENNT, ohne das Video zu oeffnen: Vor dem ersten ON-Frame liegt
eine lange Strecke UNKNOWN -- der Score kriecht durch die Totzone zwischen
AUS- und AN-Schwelle, statt sie zu ueberspringen. Gemessen am Spieltag
2026-08-22: gesunde Zyklen haben 1 bis 6 Frames Anlauf, der verlorene Wurf auf
Bahn 2 hatte 56.

Der Anlauf allein ist kein Fehler -- er wird erst einer, wenn am Ende der Phase
kein Wurf steht. Darum werden beide Bedingungen zusammen geprueft.

GRENZE DIESER HEURISTIK, am Vollauf vom 2026-09-01 gemessen: Sie findet nicht
alle Faelle. Von den fuenf Wuerfen, die der Fix zurueckgeholt hat, hatte einer
(Bahn 4, Gruen-AN F41026) nur 7 Frames Anlauf und blieb hier unsichtbar; dafuer
meldet sie Bahn 4 F47150, der aus einem anderen Grund verworfen wurde (Q13).
Der gemeinsame Nenner der fuenf ist nicht der Anlauf, sondern ein SCHWACHES
Gruensignal -- Maximalscore 44 bis 70, wo gesunde Zyklen 77 bis 79 erreichen.
Wer die Suche schaerfen will, misst den Maximalscore der Phase, nicht nur den
Anlauf davor.

AUFRUF:

    .venv/Scripts/python.exe tools/measure_green_onset.py <laufordner>

Der Laufordner ist das Verzeichnis mit `gruenspur.csv` und `wuerfe.csv`. Die
Gruenspur entsteht nur, wenn `debug.green_trace` eingeschaltet war.
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

# Kuerzere ON-Strecken sind Flackern, kein Zyklus. 25 Frames = 1 s; der
# kuerzeste echte Zyklus des Spieltags 2026-08-22 mass 106 Frames.
MIN_ZYKLUS_FRAMES = 25

# Ab hier gilt der Anlauf als auffaellig. Gemessen: gesunde Zyklen 1-6 Frames,
# die fuenf Verdachtsfaelle des Spieltags 46 bis 92.
ANLAUF_VERDAECHTIG = 20

# Suchfenster fuer den zugehoerigen Wurf nach dem Ende der Gruenphase.
# `sampling.report_after_green_off` steht auf 40; 80 laesst Luft.
WURF_FENSTER_FRAMES = 80


def lies_gruenspur(pfad: Path) -> dict[int, list[tuple[int, str]]]:
    """Frame und Zustand je Bahn, aufsteigend sortiert."""
    je_bahn: dict[int, list[tuple[int, str]]] = collections.defaultdict(list)
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        for zeile in csv.DictReader(datei, delimiter=";"):
            je_bahn[int(zeile["Bahn"])].append(
                (int(zeile["Frame"]), zeile["Zustand"]))
    for bahn in je_bahn:
        je_bahn[bahn].sort()
    return je_bahn


def lies_wurfframes(pfad: Path) -> dict[int, list[int]]:
    je_bahn: dict[int, list[int]] = collections.defaultdict(list)
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        for zeile in csv.DictReader(datei, delimiter=";"):
            je_bahn[int(zeile["Bahn"])].append(int(zeile["Frame"]))
    for bahn in je_bahn:
        je_bahn[bahn].sort()
    return je_bahn


def on_phasen(punkte: list[tuple[int, str]]) -> list[tuple[int, int, int]]:
    """ON-Phasen als (Beginn, Ende, Anlauf in UNKNOWN-Frames).

    UNKNOWN haelt den letzten bekannten Zustand -- so verfaehrt auch der
    Zustandsautomat. Die UNKNOWN-Frames unmittelbar VOR dem ersten ON sind der
    Anlauf: die Zeit, in der die Lampe schon leuchtete, der Detektor sich aber
    noch nicht festlegen wollte.
    """
    phasen: list[tuple[int, int, int]] = []
    zustand: str | None = None
    beginn = 0
    anlauf = 0
    offen_unbekannt = 0
    for frame, z in punkte:
        if z == "UNKNOWN":
            offen_unbekannt += 1
            continue
        if z != zustand:
            if zustand == "ON":
                phasen.append((beginn, frame - 1, anlauf))
            if z == "ON":
                beginn, anlauf = frame, offen_unbekannt
            zustand = z
        offen_unbekannt = 0
    if zustand == "ON":
        phasen.append((beginn, punkte[-1][0], anlauf))
    return phasen


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("lauf", type=Path,
                   help="Ordner mit gruenspur.csv und wuerfe.csv")
    a = p.parse_args()

    spur = a.lauf / "gruenspur.csv"
    wuerfe = a.lauf / "wuerfe.csv"
    for pfad in (spur, wuerfe):
        if not pfad.is_file():
            print(f"fehlt: {pfad}")
            return 1

    je_bahn = lies_gruenspur(spur)
    wurfframes = lies_wurfframes(wuerfe)

    print(f"{'Bahn':>4} {'Zyklen':>7} {'ohne Wurf':>10} "
          f"{'Anlauf>%d' % ANLAUF_VERDAECHTIG:>11} {'beides':>8}")
    verdaechtig: list[tuple[int, int, int, int]] = []
    for bahn in sorted(je_bahn):
        ziele = wurfframes.get(bahn, [])
        phasen = [ph for ph in on_phasen(je_bahn[bahn])
                  if ph[1] - ph[0] >= MIN_ZYKLUS_FRAMES]
        ohne = lang = beides = 0
        for beginn, ende, anlauf in phasen:
            hat_wurf = any(ende <= t <= ende + WURF_FENSTER_FRAMES for t in ziele)
            if not hat_wurf:
                ohne += 1
            if anlauf > ANLAUF_VERDAECHTIG:
                lang += 1
                if not hat_wurf:
                    beides += 1
                    verdaechtig.append((bahn, beginn, ende, anlauf))
        print(f"{bahn:>4} {len(phasen):>7} {ohne:>10} {lang:>11} {beides:>8}")

    print()
    if not verdaechtig:
        print("Kein Zyklus mit langem Anlauf UND fehlendem Wurf.")
        return 0

    print("Verdacht auf BUG-016 -- langer Anlauf und kein Wurf am Ende:")
    print(f"  {'Bahn':>4} {'ON von':>8} {'bis':>8} {'Laenge':>7} {'Anlauf':>7}")
    for bahn, beginn, ende, anlauf in verdaechtig:
        print(f"  {bahn:>4} {beginn:>8} {ende:>8} "
              f"{ende - beginn:>7} {anlauf:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
