"""Schreibt eine Auswertung als CSV -- eine Zeile je Wurf, alles Messbare drin.

Zweck: Der Nutzer soll die Ergebnisse in einer Tabelle selbst durchsehen koennen,
ohne durch JSON zu waten. Deshalb je Wurf ALLE Quellen nebeneinander -- Lampen,
Ziffern, Summen, Pruefungen -- damit Widersprueche sofort ins Auge fallen.

Getrennt wird mit Semikolon und in UTF-8 mit BOM geschrieben, damit Excel die
Datei ohne Import-Dialog korrekt oeffnet.

Aufruf:
    .venv/Scripts/python.exe tools/export_csv.py [EINGABE.json] [AUSGABE.csv]
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

EINGABE = Path("debug/vollauswertung.json")
AUSGABE = Path("debug/wuerfe.csv")

SPALTEN = [
    "Zeit", "Frame", "Bahn", "Spiel", "Wurf", "Wurf_im_Zyklus", "Zyklus",
    "Kegel", "Status", "Confidence",
    "Lampen_Anzahl", "Lampen_Kegel",
    "Grundlinie_Anzahl", "Grundlinie_Kegel", "Raeumen",
    "Ziffer_Kegelzahl", "Ziffer_Kandidaten",
    "Tafel_Summe", "Tafel_Summe_Zuwachs", "Summe_intern", "Zwischensumme",
    "Pruefungen_bestanden", "Pruefungen_gescheitert", "Gescheiterte_Pruefungen",
    "Entscheidungen",
] + [f"Lampe_Kegel_{i}" for i in range(1, 10)] + ["Sample_Frames"]
# Die Lampen stehen nach KEGELNUMMER, nicht nach Lampenindex: die Namen
# in `lamps[].name` tragen seit Q5 die Kegelnummer (1 vorn, 9 hinten).


def zeit(frame: int | None, fps: float = 25.0) -> str:
    if frame is None:
        return ""
    sekunden = frame / fps
    return f"{int(sekunden // 60):02d}:{int(sekunden % 60):02d}"


def main() -> int:
    quelle = Path(sys.argv[1]) if len(sys.argv) > 1 else EINGABE
    ziel = Path(sys.argv[2]) if len(sys.argv) > 2 else AUSGABE
    if not quelle.exists():
        print(f"Keine Auswertung unter {quelle}")
        return 1

    daten = json.loads(quelle.read_text(encoding="utf-8"))
    wuerfe = daten["wuerfe"]

    # Die Spielnummer steht seit dem Ergebnisversand im Wurf selbst. Fuer
    # aeltere Auswertungen wird sie weiterhin aus dem Rueckfall der Wurfnummer
    # abgeleitet -- so bleiben alte JSON-Dateien lesbar.
    spiel: dict[int, int] = {}
    letzte_nummer: dict[int, int] = {}
    vorige_summe: dict[int, int | None] = {}

    ziel.parent.mkdir(parents=True, exist_ok=True)
    with ziel.open("w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.writer(datei, delimiter=";")
        schreiber.writerow(SPALTEN)

        for wurf in wuerfe:
            bahn = wurf["lane"]
            nummer = wurf["throw_number"]
            if nummer <= letzte_nummer.get(bahn, 0):
                spiel[bahn] = spiel.get(bahn, 1) + 1
                vorige_summe[bahn] = None
            letzte_nummer[bahn] = nummer

            beweis = wurf.get("evidence") or {}
            roh = beweis.get("raw") or {}
            lampen = roh.get("pins") or {}
            grund = roh.get("baseline") or {}
            pruefungen = beweis.get("checks") or []
            gescheitert = [c["name"] for c in pruefungen if not c.get("passed")]

            summe = roh.get("displayed_total")
            zuwachs = ""
            if summe is not None and vorige_summe.get(bahn) is not None:
                zuwachs = summe - vorige_summe[bahn]
            if summe is not None:
                vorige_summe[bahn] = summe

            zustaende = {l["name"]: l["state"] for l in lampen.get("lamps", [])}

            schreiber.writerow([
                zeit(wurf.get("source_frame")),
                wurf.get("source_frame"),
                bahn,
                wurf.get("game_number", spiel.get(bahn, 1)),
                nummer,
                wurf.get("throw_number_in_series"),
                wurf.get("cycle_number"),
                wurf["pins_count"],
                wurf["status"],
                round(wurf.get("confidence") or 0.0, 2),

                lampen.get("count", ""),
                " ".join(str(p) for p in lampen.get("pins", [])),
                grund.get("count", ""),
                " ".join(str(p) for p in grund.get("pins", [])),
                "ja" if roh.get("clearing") else "",

                wurf.get("displayed_pin_count") if wurf.get("displayed_pin_count") is not None else "",
                " ".join(str(k) for k in (roh.get("displayed_candidates") or [])),

                summe if summe is not None else "",
                zuwachs,
                wurf.get("running_total"),
                wurf.get("series_total") if wurf.get("series_total") is not None else "",

                sum(1 for c in pruefungen if c.get("passed")),
                len(gescheitert),
                " | ".join(gescheitert),
                " | ".join(beweis.get("decisions") or []),

                *[zustaende.get(f"pin_lamp_{i}", "") for i in range(1, 10)],
                " ".join(str(f["index"]) for f in (beweis.get("frames") or [])),
            ])

    print(f"{len(wuerfe)} Wuerfe geschrieben -> {ziel}")
    print(f"{len(SPALTEN)} Spalten, Trennzeichen ';', UTF-8 mit BOM (Excel-tauglich)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
