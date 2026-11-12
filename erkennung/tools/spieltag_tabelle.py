"""Baut je Bahn die Wurftabelle des Spieltags -- Zeilen Wurf, Spalten Spiel.

WOZU (Nutzer, 2026-09-24): Eine Tabelle zum Gegenlesen gegen den
Papierspielbericht. Die `wuerfe.csv` des Laufs ist chronologisch und mischt
alle vier Bahnen; abgleichen laesst sich damit nichts.

DIE SPALTEN kommen aus dem Ablauf des Spieltags, nicht aus den Daten:
zwei Warmwerfen zu Beginn, dann vier Durchgaenge, und vor jedem weiteren
Durchgang nochmals Warmwerfen. Das laesst sich an den Wurfzahlen nachpruefen
und wird auch nachgeprueft -- Warmwerfen hat 20 Wuerfe, ein Durchgang 30.
Stimmt das Muster nicht, sagt das Werkzeug es, statt still falsch zu sortieren.

DIE KORREKTUR DER LAMPE 8 (Bahn 5). Gemessen am 2026-09-24: Die ROI der
Lampe 8 auf Bahn 5 sitzt rund zwei Pixel zu tief (`tools/messe_lampenversatz.py`
-- p99 der Helligkeit 218 an Ort und Stelle, 248 zwei Pixel hoeher). Die Lampe
wird dadurch regelmaessig als AUS gelesen, obwohl sie leuchtet. Das schlaegt
auf zwei Wegen durch:

    * beim Wurfergebnis  -> ein Kegel zu wenig gebucht
    * in der Grundlinie  -> der Kegel gilt als neu gefallen, einer zu viel

Beide Faelle sind nur dann eine Korrektur wert, wenn die ZIFFER widerspricht
und die Abweichung genau eins betraegt -- die Ziffer ist hier der
Schiedsrichter, und der Kegel 8 ist die einzige Erklaerung, die zu ihr passt.
Alles andere bleibt unangetastet und wird gemeldet.

Aufruf:

    .venv/Scripts/python.exe tools/spieltag_tabelle.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45 \
        --ziel scratchpad/spieltag_tabellen
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

# Der Ablauf des Spieltags. Der Index in dieser Liste ist die Spielnummer,
# die die Analyse vergeben hat (sie zaehlt ab 1).
SPALTEN = [
    "Warmwerfen 1", "Warmwerfen 2",
    "Lauf 1.1", "Lauf 1.2", "Lauf 1.3", "Lauf 1.4",
    "Warmwerfen 3",
    "Lauf 2.1", "Lauf 2.2", "Lauf 2.3", "Lauf 2.4",
    "Warmwerfen 4",
    "Lauf 3.1", "Lauf 3.2", "Lauf 3.3", "Lauf 3.4",
]
# Sollwurfzahl je Spalte -- nur zur Pruefung des Musters.
SOLL = [20 if s.startswith("Warmwerfen") else 30 for s in SPALTEN]
WUERFE_JE_SPIEL = 30

# Die Bahn und die Lampe, um die es geht. Beides steht hier und nicht als
# Zahl im Code, weil es ein Befund ist und kein Naturgesetz: Sitzt die
# Kalibrierung nach, faellt die Korrektur ersatzlos weg.
FEHLERHAFTE_BAHN = "5"
FEHLERHAFTE_LAMPE = 8


def summenzeugen(wuerfe: list[dict],
                 gebucht: dict[int, int] | None = None) -> dict[int, int]:
    """Was die TAFELSUMME je Wurf sagt -- nur wo sie eindeutig zuzuordnen ist.

    Sie hinkt einen Wurf hinterher: Die Differenz zweier Staende ist die Summe
    ALLER Wuerfe dazwischen. Einem einzelnen Wurf zuzuordnen ist sie deshalb
    nur, wenn von den Wuerfen der Spanne hoechstens EINER offen ist -- alle
    anderen muessen ihre eigene Kegelziffer hinter sich haben. Deren Beitrag
    wird abgezogen, was uebrig bleibt, gehoert dem offenen Wurf.

    `gebucht` sind die Kegelzahlen NACH der Ziffernkorrektur. Ein Zirkelschluss
    entsteht dadurch nicht: Abgezogen werden nur Wuerfe, die ihre eigene,
    unabhaengige Ziffer bestaetigt.

    WOZU (gemessen 2026-09-24): Bei drei Raeumwuerfen auf Bahn 5 war die
    Kegelziffer nicht lesbar. Ohne zweiten Zeugen blieb die Lampe-8-Korrektur
    dort aus, obwohl die Lampenspur sie belegt -- Lampe 8 lag ueber das ganze
    Ergebnisfenster 1 bis 4 Punkte unter ihrer AN-Schwelle, waehrend die
    Nachbarlampen 30 Punkte darueber lagen. Die Tafelsumme sagte jedes Mal
    genau einen Kegel mehr, und die GIFs der Tafel zeigen dort dieselbe Zahl.
    """
    def stand(w: dict) -> int | None:
        try:
            return int(w["SummeTafel"])
        except (TypeError, ValueError):
            return None

    def wert(w: dict) -> int:
        nr = int(w["Wurfnummer"])
        if gebucht is not None and nr in gebucht:
            return gebucht[nr]
        return int(w["Kegel"])

    def bestaetigt(w: dict) -> bool:
        """Steht dieser Wurf durch seine EIGENE Kegelziffer fest?"""
        try:
            return int(w["Ziffer"]) == wert(w)
        except (TypeError, ValueError):
            return False

    zeuge: dict[int, int] = {}
    anker = [i for i, w in enumerate(wuerfe) if stand(w) is not None]
    for i, j in zip(anker, anker[1:]):
        spanne = wuerfe[i:j]
        nummern = [int(w["Wurfnummer"]) for w in spanne] + [int(wuerfe[j]["Wurfnummer"])]
        if nummern != list(range(nummern[0], nummern[0] + len(nummern))):
            continue                       # in der Spanne fehlt ein Wurf
        offen = [w for w in spanne if not bestaetigt(w)]
        if len(offen) != 1:
            continue
        rest = stand(wuerfe[j]) - stand(wuerfe[i])
        rest -= sum(wert(w) for w in spanne if w is not offen[0])
        if 0 <= rest <= 9:
            zeuge[int(offen[0]["Wurfnummer"])] = rest
    return zeuge


def korrigiere(reihe: dict, soll: int | None = None
               ) -> tuple[list[int], str, str] | None:
    """Prueft, ob die Lampe 8 diesen Wurf erklaert. Gibt das Wurfbild zurueck.

    Schiedsrichter ist zuerst die KEGELZIFFER. Schweigt sie, tritt die
    TAFELSUMME (`soll`) an ihre Stelle -- sie steht in einem anderen
    Ziffernfeld und ist damit ein eigenstaendiger Zeuge. Nie beide zugleich:
    Wo die Ziffer lesbar ist, entscheidet sie.

    Rueckgabe `None` heisst: nicht durch diese Lampe erklaerbar, Finger weg.
    """
    if reihe["Bahn"] != FEHLERHAFTE_BAHN:
        return None
    try:
        kegel = int(reihe["Kegel"])
    except (TypeError, ValueError):
        return None
    try:
        wahrheit, zeuge = int(reihe["Ziffer"]), "Kegelziffer"
    except (TypeError, ValueError):
        if soll is None:
            return None
        wahrheit, zeuge = soll, "Tafelsumme"

    bild = [int(x) for x in reihe["Kegelnummern"].split()] if reihe["Kegelnummern"] else []
    if wahrheit == kegel + 1 and FEHLERHAFTE_LAMPE not in bild:
        # Die Lampe wurde beim ERGEBNIS als aus gelesen -- der Kegel fehlt.
        return sorted(bild + [FEHLERHAFTE_LAMPE]), "Kegel 8 ergaenzt", zeuge
    if wahrheit == kegel - 1 and FEHLERHAFTE_LAMPE in bild:
        # Die Lampe wurde in der GRUNDLINIE als aus gelesen -- der Kegel lag
        # schon und gilt faelschlich als neu gefallen.
        return (sorted(x for x in bild if x != FEHLERHAFTE_LAMPE),
                "Kegel 8 entfernt", zeuge)
    return None


def korrigiere_spiel(wuerfe: list[dict]) -> dict[int, tuple[list[int], str, str]]:
    """Alle Lampe-8-Korrekturen EINES Spiels, nach Wurfnummer.

    Der Ablauf steht bewusst an einer einzigen Stelle: Er hat zwei Durchgaenge,
    und als Tabellenbau und Pruefung ihn getrennt nachbildeten, liefen sie am
    2026-09-24 sofort auseinander (39 gegen 38 Korrekturen).

    1. Was allein die KEGELZIFFER entscheidet.
    2. Was die TAFELSUMME entscheidet, nachdem die bestaetigten Wuerfe der
       Spanne abgezogen sind.
    """
    nach_ziffer: dict[int, int] = {}
    ergebnis: dict[int, tuple[list[int], str, str]] = {}
    for r in wuerfe:
        try:
            nummer, kegel = int(r["Wurfnummer"]), int(r["Kegel"])
        except (TypeError, ValueError):
            continue
        fix = korrigiere(r)
        nach_ziffer[nummer] = len(fix[0]) if fix else kegel
        if fix:
            ergebnis[nummer] = fix

    zeugen = summenzeugen(wuerfe, nach_ziffer)
    for r in wuerfe:
        try:
            nummer = int(r["Wurfnummer"])
        except (TypeError, ValueError):
            continue
        if nummer in ergebnis:
            continue
        fix = korrigiere(r, zeugen.get(nummer))
        if fix:
            ergebnis[nummer] = fix
    return ergebnis


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--ziel", required=True, type=Path)
    p.add_argument("--ohne-korrektur", action="store_true",
                   help="Die Lampe-8-Korrektur NICHT anwenden.")
    a = p.parse_args()

    quelle = a.lauf / "wuerfe.csv"
    with quelle.open(encoding="utf-8-sig", newline="") as f:
        reihen = list(csv.DictReader(f, delimiter=";"))

    # Bahn -> Spiel -> Wurfnummer -> (Kegel, Wurfbild)
    tafel: dict[str, dict[int, dict[int, tuple[int, str]]]] = \
        defaultdict(lambda: defaultdict(dict))
    korrekturen: list[dict] = []
    ungeklaert: list[dict] = []

    nach_spiel: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in reihen:
        nach_spiel[(r["Bahn"], int(r["Spiel"]))].append(r)
    fixes = {k: korrigiere_spiel(v) for k, v in nach_spiel.items()}

    for r in reihen:
        spiel, nummer = int(r["Spiel"]), int(r["Wurfnummer"])
        try:
            kegel = int(r["Kegel"])
        except ValueError:
            continue
        bild = r["Kegelnummern"]
        fix = fixes[(r["Bahn"], spiel)].get(nummer)
        if fix is not None and not a.ohne_korrektur:
            neu, grund, zeuge = fix
            korrekturen.append({
                "Bahn": r["Bahn"], "Spiel": spiel, "Wurf": nummer,
                "Frame": r["Frame"], "Zeit": r["Zeit"],
                "vorher": kegel, "vorher_Wurfbild": bild,
                "nachher": len(neu), "nachher_Wurfbild": " ".join(map(str, neu)),
                "Ziffer": r["Ziffer"], "Grund": grund, "Zeuge": zeuge,
                "Raeumen": r["Raeumen"], "Grundlinie": r["Grundlinie"],
            })
            kegel, bild = len(neu), " ".join(map(str, neu))
        elif r["Ziffer"] and r["Ziffer"] != r["Kegel"]:
            ungeklaert.append({
                "Bahn": r["Bahn"], "Spiel": spiel, "Wurf": nummer,
                "Frame": r["Frame"], "Lampen": r["Kegel"],
                "Wurfbild": bild, "Ziffer": r["Ziffer"],
                "Raeumen": r["Raeumen"], "Grundlinie": r["Grundlinie"],
            })
        tafel[r["Bahn"]][spiel][nummer] = (kegel, bild)

    a.ziel.mkdir(parents=True, exist_ok=True)

    for bahn in sorted(tafel):
        # Muster pruefen, bevor die Spalten vergeben werden.
        for spiel, spalte in enumerate(SPALTEN, start=1):
            gezaehlt = len(tafel[bahn].get(spiel, {}))
            if gezaehlt and abs(gezaehlt - SOLL[spiel - 1]) > 2:
                print(f"  ACHTUNG Bahn {bahn}: Spiel {spiel} hat {gezaehlt} "
                      f"Wuerfe, '{spalte}' erwartet {SOLL[spiel - 1]}")
        unbekannt = [s for s in tafel[bahn] if s > len(SPALTEN)]
        if unbekannt:
            print(f"  ACHTUNG Bahn {bahn}: Spiele {unbekannt} haben keine "
                  f"Spalte -- der Spieltag hatte mehr Spiele als geplant")

        ziel = a.ziel / f"bahn_{bahn}.csv"
        with ziel.open("w", encoding="utf-8-sig", newline="") as f:
            s = csv.writer(f, delimiter=";")
            kopf = ["Wurfnummer"]
            for name in SPALTEN:
                kopf += [name, f"{name} Wurfbild"]
            s.writerow(kopf)
            for nummer in range(1, WUERFE_JE_SPIEL + 1):
                zeile = [nummer]
                for spiel in range(1, len(SPALTEN) + 1):
                    eintrag = tafel[bahn].get(spiel, {}).get(nummer)
                    zeile += list(eintrag) if eintrag else ["", ""]
                s.writerow(zeile)
        print(f"  {ziel}")

    def schreibe(name: str, zeilen: list[dict]) -> None:
        if not zeilen:
            return
        ziel = a.ziel / name
        with ziel.open("w", encoding="utf-8-sig", newline="") as f:
            s = csv.DictWriter(f, fieldnames=list(zeilen[0]), delimiter=";")
            s.writeheader()
            s.writerows(zeilen)
        print(f"  {ziel}  ({len(zeilen)} Zeilen)")

    schreibe("korrekturen_lampe8.csv", korrekturen)
    schreibe("offene_abweichungen.csv", ungeklaert)
    print(f"\n{len(korrekturen)} Wuerfe korrigiert, "
          f"{len(ungeklaert)} Abweichungen bleiben offen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
