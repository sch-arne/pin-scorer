#!/usr/bin/env python
"""Ersetzt Klarnamen in den Ground-Truth-Dateien durch stabile Decknamen.

WARUM

`data/ground_truth/` ist die gemessene Wahrheit, gegen die die Zaehllogik
geprueft wird -- sie gehoert ins Repository. Sie enthielt aber die vollen
Namen realer Spieler samt ihrer Ergebnisse:

    Heimmannschaft;Spieler D;206;216;178;235;835;11

Fuer die Pruefung zaehlen ausschliesslich die ZAHLEN. Wer geworfen hat, spielt
darin keine Rolle. Also werden die Namen ersetzt -- nicht die Dateien
geloescht, sonst waere die Regressionsgrundlage weg.

DIE ZUORDNUNG IST STABIL UND DATEIUEBERGREIFEND. Derselbe Mensch bekommt in
jeder Datei denselben Decknamen, auch bei unterschiedlicher Schreibweise
("Spieler D" und "Spieler D"). Sonst liessen sich die Dateien
nicht mehr gegeneinander rechnen.

Die Klartext-Zuordnung wird lokal abgelegt und ist per .gitignore
ausgeschlossen -- so bleibt sie fuer eigene Auswertungen verfuegbar, ohne im
Repository zu landen.

    .venv/Scripts/python.exe tools/pseudonymisiere_ground_truth.py [--trocken]
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ORDNER = Path("data/ground_truth")
ZUORDNUNG = ORDNER / "klarnamen.local.json"

# Eintraege, die keine Personen sind und deshalb bleiben muessen -- sie
# markieren den Anfang einer Bahn im Wurfprotokoll.
KEINE_PERSON = {"", "-"}
KEIN_NAME_PRAEFIX = ("Start Bahn",)


def ist_person(wert: str) -> bool:
    wert = wert.strip()
    if wert in KEINE_PERSON:
        return False
    return not wert.startswith(KEIN_NAME_PRAEFIX)


def schluessel(name: str) -> str:
    """Erkennt denselben Menschen in beiden Schreibweisen.

    "Spieler D" und "Spieler D" muessen denselben Decknamen
    bekommen -- sonst zaehlen die Werkzeuge zwei Personen, wo eine ist.
    """
    teile = [t.strip() for t in name.replace(",", " ").split() if t.strip()]
    return " ".join(sorted(t.casefold() for t in teile))


def zurueck() -> int:
    """Setzt die Decknamen wieder auf die Klarnamen zurueck.

    Sinnvoll, seit `data/ground_truth/` per .gitignore ohnehin nicht ins
    Repository geht: Lokal sind die echten Namen nuetzlicher, weil sich damit
    gegen die gedruckten Wurfprotokolle abgleichen laesst.
    """
    if not ZUORDNUNG.is_file():
        print(f"Keine Zuordnung unter {ZUORDNUNG} -- nichts wiederherzustellen.")
        return 1
    z = json.loads(ZUORDNUNG.read_text(encoding="utf-8"))
    rueck = {**{k: v for k, v in z["personen"].items()},
             **{k: v for k, v in z["mannschaften"].items()}}
    ersetzt = 0
    for pfad in sorted(ORDNER.glob("*.csv")):
        with pfad.open(encoding="utf-8-sig", newline="") as fh:
            leser = csv.DictReader(fh, delimiter=";")
            felder = leser.fieldnames or []
            zeilen = list(leser)
        for zeile in zeilen:
            for feld in ("Spieler", "Mannschaft"):
                wert = (zeile.get(feld) or "").strip()
                if wert in rueck:
                    zeile[feld] = rueck[wert]
                    ersetzt += 1
        with pfad.open("w", encoding="utf-8", newline="") as fh:
            schreiber = csv.DictWriter(fh, fieldnames=felder, delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(zeilen)
    print(f"{ersetzt} Felder auf Klarnamen zurueckgesetzt.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--trocken", action="store_true",
                   help="nur zeigen, was geaendert wuerde")
    p.add_argument("--zurueck", action="store_true",
                   help="Klarnamen aus der lokalen Zuordnung wiederherstellen")
    a = p.parse_args()

    if a.zurueck:
        return zurueck()

    dateien = sorted(ORDNER.glob("*.csv"))
    if not dateien:
        print(f"Keine CSV-Dateien in {ORDNER}")
        return 1

    # Erst ALLE Namen sammeln, dann erst vergeben -- so haengt der Deckname
    # nicht davon ab, in welcher Reihenfolge die Dateien gelesen wurden.
    personen: dict[str, str] = {}
    vereine: dict[str, str] = {}
    for pfad in dateien:
        with pfad.open(encoding="utf-8-sig", newline="") as fh:
            for zeile in csv.DictReader(fh, delimiter=";"):
                name = (zeile.get("Spieler") or "").strip()
                if name and ist_person(name):
                    personen.setdefault(schluessel(name), name)
                verein = (zeile.get("Mannschaft") or "").strip()
                if verein:
                    vereine.setdefault(verein.casefold(), verein)

    deckname = {s: f"Spieler {i:02d}" % {} if False else f"Spieler {i:02d}"
                for i, s in enumerate(sorted(personen), start=1)}
    deckverein = {v: f"Mannschaft {chr(65 + i)}"
                  for i, v in enumerate(sorted(vereine))}

    print(f"{len(deckname)} Personen, {len(deckverein)} Mannschaften")
    geaendert = 0
    for pfad in dateien:
        with pfad.open(encoding="utf-8-sig", newline="") as fh:
            leser = csv.DictReader(fh, delimiter=";")
            felder = leser.fieldnames or []
            zeilen = list(leser)
        for z in zeilen:
            name = (z.get("Spieler") or "").strip()
            if name and ist_person(name):
                z["Spieler"] = deckname[schluessel(name)]
                geaendert += 1
            verein = (z.get("Mannschaft") or "").strip()
            if verein:
                z["Mannschaft"] = deckverein[verein.casefold()]
        if a.trocken:
            print(f"  {pfad.name}: {len(zeilen)} Zeilen")
            continue
        with pfad.open("w", encoding="utf-8", newline="") as fh:
            schreiber = csv.DictWriter(fh, fieldnames=felder, delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(zeilen)
        print(f"  {pfad.name}: geschrieben")

    if a.trocken:
        return 0

    # Die Klartext-Zuordnung bleibt lokal (siehe .gitignore).
    ZUORDNUNG.write_text(json.dumps(
        {"personen": {deckname[s]: personen[s] for s in sorted(personen)},
         "mannschaften": {deckverein[v]: vereine[v] for v in sorted(vereine)}},
        indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{geaendert} Namensfelder ersetzt. Zuordnung: {ZUORDNUNG} "
          f"(nicht im Repository)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
