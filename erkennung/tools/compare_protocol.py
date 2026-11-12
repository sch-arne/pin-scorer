"""Vergleicht die Erkennung gegen das handgefuehrte Wurfprotokoll.

Das ist die erste Messung in diesem Projekt gegen eine Quelle, die NICHT aus
dem Bild stammt. Alle bisherigen Kennzahlen ("Ziffer stimmt mit Lampen",
"Summenkette bestaetigt") vergleichen zwei Lesungen desselben Bildes -- wo die
sich einig sind, kann trotzdem beides falsch sein.

Verglichen wird je Bahn die chronologische Wurffolge. Dabei wird AUSGERICHTET
und nicht stur nach Index verglichen: Fehlt dem Werkzeug ein Wurf, verschoebe
sich sonst alles dahinter, und aus einem Fehler wuerden hundert. Die
Ausrichtung trennt sauber:

    passt      gleiche Kegelzahl an derselben Stelle
    falsch     Wurf erkannt, Kegelzahl daneben
    fehlt      im Protokoll, vom Werkzeug nicht gemeldet
    zuviel     vom Werkzeug gemeldet, im Protokoll nicht vorhanden

Aufruf -- entweder die `wuerfe.csv` eines Laufordners oder eine
`vollauswertung.json`:

    .venv/Scripts/python.exe tools/compare_protocol.py <laufordner>/wuerfe.csv \
        --wahrheit data/ground_truth/wurfprotokoll_spieltag_1.csv \
        --aus debug/protokollvergleich_spieltag1.csv

Ergebnis: je Zeile ein ausgerichtetes Wurfpaar.

ACHTUNG, wenn das Protokoll nur einen TEIL des Videos abdeckt: Die Ausrichtung
findet dann den passenden Abschnitt, aber alles davor und dahinter zaehlt als
"zuviel". Diese Zahl ist dann KEINE Fehlerquote -- sie sagt nur, wie viel
ausserhalb des Protokolls liegt. Aussagekraeftig sind "passt" und "falsch".

ZWEI AUSRICHTUNGEN (`--ausrichtung`), und die Wahl entscheidet das Ergebnis:

`frei` (bis 2026-10-06 der einzige Weg) richtet die GANZE Bahn als eine
Wurffolge aus. Das setzt voraus, dass das Protokoll die Bahn lueckenlos
abdeckt. Deckt es nur EINE Mannschaft ab -- und das tut
`wurfprotokoll_spieltag_1.csv` --, dann liegen zwischen zwei Protokollbloecken
die 30 Wuerfe des Gegners, und die Ausrichtung klebt einen Block ueber zwei
Spiele hinweg zusammen. GEMESSEN am 1. Spieltag: 639 von 720 "richtig", und in
ALLEN 81 angeblich falschen Wuerfen stimmten unsere Lampen mit der Kegelziffer
der Tafel ueberein. Ein Beleg, dass nicht die Erkennung danebenlag, sondern die
Zuordnung.

`block` (Vorgabe) nutzt die Struktur, die beide Seiten haben: Ein Block des
Protokolls (eine Bahn, ein Satz, ein Spieler, 30 Wuerfe) ist genau EIN Spiel
unseres Laufs. Zugeordnet wird auf Blockebene, verglichen wird innerhalb des
Paares ueber die WURFNUMMER der Tafel -- eine Groesse, die weder aus unseren
Lampen noch aus dem Protokoll stammt. Ein verlorener Wurf verschiebt damit
nichts mehr.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

AUSWERTUNG = Path("debug/vollauswertung.json")
WAHRHEIT = Path("data/ground_truth/wurfprotokoll_langes_video.csv")
AUSGABE = Path("debug/protokollvergleich.csv")

# Bewertung der Ausrichtung. Eine Luecke muss teurer sein als ein Zahlendreher,
# sonst erklaert die Ausrichtung jede falsche Zahl lieber durch "fehlt + zuviel"
# und die Statistik sieht kuenstlich gut aus.
TREFFER = 2
DANEBEN = -1
LUECKE = -3


def ausrichten(werkzeug: list[int], wahrheit: list[int]) -> list[tuple]:
    """Needleman-Wunsch ueber zwei Wurffolgen.

    Liefert Paare (index_werkzeug, index_wahrheit), wobei None fuer eine Luecke
    steht. 120 x 120 Felder je Bahn -- der Aufwand faellt nicht ins Gewicht.
    """
    n, m = len(werkzeug), len(wahrheit)
    punkte = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        punkte[i][0] = punkte[i - 1][0] + LUECKE
    for j in range(1, m + 1):
        punkte[0][j] = punkte[0][j - 1] + LUECKE

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            diagonal = punkte[i - 1][j - 1] + (
                TREFFER if werkzeug[i - 1] == wahrheit[j - 1] else DANEBEN)
            punkte[i][j] = max(diagonal,
                               punkte[i - 1][j] + LUECKE,
                               punkte[i][j - 1] + LUECKE)

    paare: list[tuple] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            diagonal = punkte[i - 1][j - 1] + (
                TREFFER if werkzeug[i - 1] == wahrheit[j - 1] else DANEBEN)
            if punkte[i][j] == diagonal:
                paare.append((i - 1, j - 1))
                i, j = i - 1, j - 1
                continue
        if i > 0 and punkte[i][j] == punkte[i - 1][j] + LUECKE:
            paare.append((i - 1, None))
            i -= 1
            continue
        paare.append((None, j - 1))
        j -= 1
    paare.reverse()
    return paare


def wuerfe_aus_csv(pfad: Path) -> list[dict]:
    """Liest eine `wuerfe.csv` in dieselbe Form wie die JSON-Auswertung.

    Damit laesst sich jeder Laufordner vergleichen, ohne vorher eine
    Gesamtauswertung zu erzeugen -- die CSV entsteht ohnehin bei jedem Lauf.
    """
    wuerfe: list[dict] = []
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        for zeile in csv.DictReader(datei, delimiter=";"):
            ziffer = zeile.get("Ziffer", "")
            wuerfe.append({
                "lane": int(zeile["Bahn"]),
                "pins_count": int(zeile["Kegel"]),
                "pins": [int(x) for x in zeile["Kegelnummern"].split()
                         if x.isdigit()],
                "throw_number": int(zeile["Wurfnummer"]),
                "source_frame": int(zeile["Frame"]),
                "timestamp": float(zeile.get("Zeitstempel_s") or 0.0),
                "spiel": (int(zeile["Spiel"]) if zeile.get("Spiel", "").strip()
                          .lstrip("-").isdigit() else None),
                "status": zeile["Status"],
                "displayed_pin_count": int(ziffer) if ziffer.isdigit() else None,
                "raeumen": zeile.get("Raeumen", ""),
            })
    return wuerfe


def wahrheit_lesen(pfad: Path) -> dict[int, list[dict]]:
    if not pfad.exists():
        raise SystemExit(f"Bodenwahrheit fehlt: {pfad}")
    je_bahn: dict[int, list[dict]] = {}
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        for zeile in csv.DictReader(datei, delimiter=";"):
            je_bahn.setdefault(int(zeile["Bahn"]), []).append({
                "satz": int(zeile["Satz"]),
                "spieler": zeile["Spieler"],
                "wurf": int(zeile["Wurf"]),
                "kegel": int(zeile["Kegel"]),
                "modus": zeile["Modus"],
            })
    return je_bahn


# ---------------------------------------------------------------- blockweise

# Ein uebersprungenes Spiel kostet nichts: Auf jeder Bahn spielt auch die
# Mannschaft, die das Protokoll nicht abdeckt, und davor steht das Warmwerfen.
# Ein uebersprungener Protokollblock dagegen darf nie die beste Loesung sein.
SPIEL_UEBERSPRINGEN = 0
BLOCK_UEBERSPRINGEN = -100


def bloecke_der_wahrheit(zeilen: list[dict]) -> list[list[dict]]:
    """Aufeinanderfolgende Zeilen mit gleichem Satz und Spieler sind ein Block."""
    bloecke: list[list[dict]] = []
    for zeile in zeilen:
        kennung = (zeile["satz"], zeile["spieler"])
        if not bloecke or (bloecke[-1][0]["satz"],
                           bloecke[-1][0]["spieler"]) != kennung:
            bloecke.append([])
        bloecke[-1].append(zeile)
    return bloecke


def spiele_des_laufs(wuerfe: list[dict], blockgroesse: int) -> list[list[dict]]:
    """Die Wuerfe einer Bahn nach Spielnummer gruppieren.

    Ein Spiel, das die Anlage mittendrin neu begonnen hat, steht bei uns als
    zwei Spiele mit sich ergaenzenden Wurfnummern (gemessen: Bahn 5 am
    1. Spieltag, 1-18 und 19-30). Die werden wieder zusammengelegt -- sonst
    faende die Zuordnung fuer einen Protokollblock nur eine Haelfte.
    """
    roh: list[list[dict]] = []
    for wurf in wuerfe:
        if not roh or roh[-1][0]["spiel"] != wurf["spiel"]:
            roh.append([])
        roh[-1].append(wurf)

    zusammen: list[list[dict]] = []
    for gruppe in roh:
        if zusammen:
            davor = zusammen[-1]
            nummern_davor = {w["throw_number"] for w in davor}
            nummern = {w["throw_number"] for w in gruppe}
            passt = (len(davor) + len(gruppe) <= blockgroesse
                     and not (nummern_davor & nummern))
            if passt:
                davor.extend(gruppe)
                continue
        zusammen.append(list(gruppe))
    return zusammen


def _treffer(block: list[dict], spiel: list[dict]) -> tuple[int, str]:
    """Wie gut passen Block und Spiel zusammen -- und auf welchem Weg.

    Erster Weg: ueber die WURFNUMMER der Tafel. Die kennt weder unsere
    Lampenauswertung noch das Protokoll, sie ist also ein unabhaengiger
    Schluessel. Zweiter Weg (Rueckfall): ueber die Position, falls die
    Wurfnummer einer Bahn durchgehend verschoben ist.
    """
    nach_nummer = {w["throw_number"]: w for w in spiel}
    ueber_nummer = sum(1 for z in block
                       if z["wurf"] in nach_nummer
                       and nach_nummer[z["wurf"]]["pins_count"] == z["kegel"])
    ueber_position = sum(1 for z, w in zip(block, spiel)
                         if w["pins_count"] == z["kegel"])
    if ueber_nummer >= ueber_position:
        return ueber_nummer, "Wurfnummer"
    return ueber_position, "Position"


def paare_block_spiel(bloecke: list[list[dict]],
                      spiele: list[list[dict]]) -> list[tuple]:
    """Welcher Protokollblock ist welches Spiel des Laufs?

    NICHT der Reihe nach. Das war der erste Versuch, und er ist GEMESSEN
    falsch: Die Bloecke stehen im Protokoll nach Satz und Spieler sortiert,
    auf der Bahn spielen die Saetze aber verschraenkt. Am 1. Spieltag, Bahn 3,
    ist die wahre Reihenfolge

        Satz 1 Spieler A | Satz 3 Spieler D | Satz 1 Spieler B | Satz 3 ...

    weil ein Trio die Bahnen 3-4-5-2 durchwandert und das andere 5-2-3-4. Eine
    Ausrichtung, die Monotonie voraussetzt, waehlt dann die falschen Spiele:
    68,2 Prozent gegen 92,6 Prozent mit freier Zuordnung (gemessen).

    Also eine echte Zuordnung: jeder Block bekommt genau ein Spiel, jedes
    Spiel hoechstens einen Block, und die Summe der Uebereinstimmungen wird
    maximiert. Tiefensuche mit oberer Schranke -- bei sechs Bloecken und
    fuenfzehn Spielen je Bahn ist das sofort fertig.
    """
    bewertung = [[_treffer(block, spiel)[0] for spiel in spiele]
                 for block in bloecke]
    beste = {"wert": -1, "wahl": None}
    obergrenze = [0] * (len(bloecke) + 1)
    for i in range(len(bloecke) - 1, -1, -1):
        obergrenze[i] = obergrenze[i + 1] + (max(bewertung[i])
                                             if bewertung[i] else 0)

    def suche(i: int, belegt: frozenset, summe: int, wahl: tuple) -> None:
        if summe + obergrenze[i] <= beste["wert"]:
            return
        if i == len(bloecke):
            beste.update(wert=summe, wahl=wahl)
            return
        rang = sorted(range(len(spiele)), key=lambda j: -bewertung[i][j])
        for j in rang:
            if j not in belegt:
                suche(i + 1, belegt | {j}, summe + bewertung[i][j],
                      wahl + (j,))

    if bloecke and spiele:
        suche(0, frozenset(), 0, ())
    wahl = beste["wahl"] or tuple([None] * len(bloecke))
    return list(enumerate(wahl))


def vergleiche_block(block: list[dict], spiel: list[dict]) -> list[tuple]:
    """Innerhalb eines Paares: Protokollwurf gegen unseren Wurf.

    Liefert Paare (unser Wurf oder None, Protokollzeile oder None).
    """
    if spiel is None:
        return [(None, z) for z in block]
    _, weg = _treffer(block, spiel)
    paare: list[tuple] = []
    if weg == "Wurfnummer":
        nach_nummer = {w["throw_number"]: w for w in spiel}
        benutzt = set()
        for zeile in block:
            wurf = nach_nummer.get(zeile["wurf"])
            if wurf is not None:
                benutzt.add(zeile["wurf"])
            paare.append((wurf, zeile))
        for wurf in spiel:
            if wurf["throw_number"] not in benutzt:
                paare.append((wurf, None))
        return paare
    for index in range(max(len(block), len(spiel))):
        paare.append((spiel[index] if index < len(spiel) else None,
                      block[index] if index < len(block) else None))
    return paare


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("quelle", nargs="?", type=Path, default=AUSWERTUNG,
                   help="wuerfe.csv eines Laufs ODER vollauswertung.json")
    p.add_argument("--wahrheit", type=Path, default=WAHRHEIT)
    p.add_argument("--aus", type=Path, default=AUSGABE)
    p.add_argument("--ausrichtung", choices=("block", "frei"), default="block",
                   help="block: ein Protokollblock ist ein Spiel, verglichen "
                        "ueber die Wurfnummer der Tafel (Vorgabe). "
                        "frei: die ganze Bahn als eine Folge ausrichten -- "
                        "nur richtig, wenn das Protokoll die Bahn lueckenlos "
                        "abdeckt.")
    a = p.parse_args()

    pfad = a.quelle
    if not pfad.exists():
        print(f"Keine Auswertung unter {pfad}")
        return 1

    if pfad.suffix.lower() == ".csv":
        alle_wuerfe = wuerfe_aus_csv(pfad)
        quelle_name = pfad.parent.name
    else:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        alle_wuerfe = daten["wuerfe"]
        quelle_name = daten.get("video", pfad.name)
    wahrheit = wahrheit_lesen(a.wahrheit)

    erkannt: dict[int, list[dict]] = {}
    for wurf in alle_wuerfe:
        erkannt.setdefault(wurf["lane"], []).append(wurf)
    for liste in erkannt.values():
        liste.sort(key=lambda w: w["source_frame"])

    print("=" * 78)
    print(f"VERGLEICH GEGEN DAS WURFPROTOKOLL   ({pfad.name})")
    print("=" * 78)
    print(f"Quelle    : {quelle_name}")
    print(f"Wahrheit  : {a.wahrheit.name}")
    print(f"Erkannt   : {len(alle_wuerfe)} Wuerfe")
    print(f"Protokoll : {sum(len(v) for v in wahrheit.values())} Wuerfe")
    print(f"Ausrichtung: {a.ausrichtung}\n")

    if a.ausrichtung == "block" and any(
            w.get("spiel") is None for w in alle_wuerfe):
        print("Keine Spielnummern in der Quelle -- es wird frei ausgerichtet.\n")
        a.ausrichtung = "frei"

    zeilen: list[dict] = []
    zugeordnet: list[tuple] = []
    gesamt = Counter()
    je_bahn_kennzahl = []

    for bahn in sorted(wahrheit):
        wuerfe = erkannt.get(bahn, [])
        soll = wahrheit[bahn]
        if a.ausrichtung == "block":
            bloecke = bloecke_der_wahrheit(soll)
            groesse = max(len(b) for b in bloecke)
            spiele = spiele_des_laufs(wuerfe, groesse)
            zuordnung = paare_block_spiel(bloecke, spiele)
            paare = []
            offen = list(range(len(spiele)))
            for i, j in zuordnung:
                spiel = spiele[j] if j is not None else None
                if spiel is not None:
                    offen.remove(j)
                    zugeordnet.append((bahn, bloecke[i][0]["satz"],
                                       bloecke[i][0]["spieler"],
                                       spiel[0]["spiel"], len(spiel),
                                       spiel[0]["source_frame"],
                                       spiel[-1]["source_frame"],
                                       _treffer(bloecke[i], spiel)[1]))
                paare.extend(vergleiche_block(bloecke[i], spiel))
            # Was uebrig bleibt, ist das Spiel der anderen Mannschaft oder
            # das Warmwerfen -- es zaehlt als "zuviel", nicht als Fehler.
            for j in offen:
                paare.extend((w, None) for w in spiele[j])
        else:
            paare = [(wuerfe[i] if i is not None else None,
                      soll[j] if j is not None else None)
                     for i, j in ausrichten([w["pins_count"] for w in wuerfe],
                                            [s["kegel"] for s in soll])]

        zaehler = Counter()
        for w, s in paare:
            if w is None:
                art = "fehlt"
            elif s is None:
                art = "zuviel"
            elif w["pins_count"] == s["kegel"]:
                art = "passt"
            else:
                art = "falsch"
            zaehler[art] += 1

            zeilen.append({
                "Bahn": bahn,
                "Art": art,
                "Satz": s["satz"] if s else "",
                "Spieler": s["spieler"] if s else "",
                "Wurf_Protokoll": s["wurf"] if s else "",
                "Kegel_Protokoll": s["kegel"] if s else "",
                "Modus": s["modus"] if s else "",
                "Kegel_Werkzeug": w["pins_count"] if w else "",
                "Ziffer_Werkzeug": (w.get("displayed_pin_count")
                                    if w and w.get("displayed_pin_count") is not None
                                    else ""),
                "Wurfnr_Werkzeug": w["throw_number"] if w else "",
                "Frame": w["source_frame"] if w else "",
                "Zeit": (f"{int(w['timestamp'] // 60)}:{int(w['timestamp'] % 60):02d}"
                         if w else ""),
                "Status": w["status"] if w else "",
                "Kegelnummern": " ".join(map(str, w["pins"])) if w else "",
                "Raeumen": ("ja" if w and (w.get("evidence") or {}).get(
                    "raw", {}).get("clearing") else ""),
            })

        gesamt.update(zaehler)
        vergleichbar = zaehler["passt"] + zaehler["falsch"]
        je_bahn_kennzahl.append((bahn, zaehler, vergleichbar, len(soll)))

    # -------------------------------------------------------------- Ausgabe
    print(f"{'Bahn':<6}{'passt':>8}{'falsch':>8}{'fehlt':>8}{'zuviel':>8}"
          f"{'erfasst':>10}{'richtig':>10}")
    for bahn, z, vergleichbar, anzahl_soll in je_bahn_kennzahl:
        print(f"{bahn:<6}{z['passt']:>8}{z['falsch']:>8}{z['fehlt']:>8}"
              f"{z['zuviel']:>8}"
              f"{100 * vergleichbar / anzahl_soll:>9.1f}%"
              f"{100 * z['passt'] / anzahl_soll:>9.1f}%")

    soll_gesamt = sum(len(v) for v in wahrheit.values())
    vergleichbar_gesamt = gesamt["passt"] + gesamt["falsch"]
    print("-" * 58)
    print(f"{'alle':<6}{gesamt['passt']:>8}{gesamt['falsch']:>8}"
          f"{gesamt['fehlt']:>8}{gesamt['zuviel']:>8}"
          f"{100 * vergleichbar_gesamt / soll_gesamt:>9.1f}%"
          f"{100 * gesamt['passt'] / soll_gesamt:>9.1f}%")

    if zugeordnet:
        print("")
        print("Zuordnung Protokollblock -> Spiel des Laufs")
        print(f"{'Bahn':<6}{'Satz':<6}{'Spiel':>7}{'Wuerfe':>8}"
              f"{'von Frame':>11}{'bis Frame':>11}   verglichen ueber")
        for bahn, satz, _, spiel, anzahl, f0, f1, weg in zugeordnet:
            warn = "" if anzahl == 30 else "   <-- nicht 30 Wuerfe"
            print(f"{bahn:<6}{satz:<6}{spiel:>7}{anzahl:>8}{f0:>11}{f1:>11}"
                  f"   {weg}{warn}")

    # Kegelsummen -- die Zahl, die am Ende auf dem Spielberichtsbogen steht
    print(f"\nKegel je Satz -- Werkzeug/Protokoll\n")
    print(f"{'Bahn':<6}{'Satz 1':>12}{'Satz 2':>12}{'Satz 3':>12}{'Satz 4':>12}"
          f"{'gesamt':>13}")
    for bahn in sorted(wahrheit):
        soll_satz = {}
        ist_satz = {}
        for zeile in zeilen:
            if zeile["Bahn"] != bahn or not zeile["Satz"]:
                continue
            satz = zeile["Satz"]
            if zeile["Kegel_Protokoll"] != "":
                soll_satz[satz] = soll_satz.get(satz, 0) + zeile["Kegel_Protokoll"]
            if zeile["Kegel_Werkzeug"] != "":
                ist_satz[satz] = ist_satz.get(satz, 0) + zeile["Kegel_Werkzeug"]
        teile = []
        for satz in (1, 2, 3, 4):
            ist, sollwert = ist_satz.get(satz, 0), soll_satz.get(satz, 0)
            marke = "  ok" if ist == sollwert else f"{ist - sollwert:+4d}"
            teile.append(f"{ist:>3}/{sollwert:<3}{marke}")
        print(f"{bahn:<6}" + "".join(f"{t:>12}" for t in teile)
              + f"{sum(ist_satz.values()):>8}/{sum(soll_satz.values())}")

    kegel_ist = sum(z["Kegel_Werkzeug"] for z in zeilen if z["Kegel_Werkzeug"] != "")
    kegel_soll = sum(z["Kegel_Protokoll"] for z in zeilen if z["Kegel_Protokoll"] != "")
    print(f"\nKegel gesamt: Werkzeug {kegel_ist}, Protokoll {kegel_soll} "
          f"({kegel_ist - kegel_soll:+d}, {100 * kegel_ist / kegel_soll:.1f} %)")

    # Wo es falsch war: Sagte die ZIFFER die Wahrheit? Das trennt einen Fehler
    # der Lampen von einem Fehler des Messzeitpunkts.
    falsche = [z for z in zeilen if z["Art"] == "falsch"]
    ziffer_haette_geholfen = [z for z in falsche
                              if z["Ziffer_Werkzeug"] == z["Kegel_Protokoll"]]
    print(f"\nVon {len(falsche)} falschen Wuerfen haette die Ziffernanzeige "
          f"{len(ziffer_haette_geholfen)} richtig gehabt.")

    abweichungen = Counter(z["Kegel_Werkzeug"] - z["Kegel_Protokoll"]
                           for z in falsche)
    if abweichungen:
        print("Abweichung (Werkzeug minus Protokoll):")
        for wert, anzahl in sorted(abweichungen.items()):
            print(f"   {wert:+d} Kegel: {anzahl:>3}x")

    a.aus.parent.mkdir(parents=True, exist_ok=True)
    with a.aus.open("w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.DictWriter(datei, fieldnames=list(zeilen[0]), delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)
    print(f"\nZeile fuer Zeile: {a.aus}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
