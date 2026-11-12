"""Baut je Bahn eine Tabelle: Wurfnummer x Abschnitt (Warmwerfen / Saetze).

WOZU: Die Wurfliste eines Laufs ist eine lange Kette -- Warmwerfen, Satz,
Warmwerfen, Satz. Wer die Wuerfe eines Spielers sehen will, muss wissen, wo
sein Satz anfaengt. Genau das leistet diese Tabelle.

WIE DIE ABSCHNITTE ZUSTANDE KOMMEN: Nicht durch Raten, sondern durch die
Spielwechsel-Erkennung der Pipeline (Spalte `Spiel` in `wuerfe.csv`). Sie
stuetzt sich auf den Nullzustand der Anzeige und den Rueckfall der Wurfnummer.

DAS WURFBILD je Wurf steht in einer eigenen Spalte neben dem Wert. Es nennt
die Kegel, die DIESER Wurf umgeworfen hat, in der Nummerierung des Nutzers.

WAS DARIN NICHT STEHT, und warum: Welche Kegel vor einem RAEUMWURF bereits
lagen, weiss der Lauf nur als Anzahl, nicht mit Nummern. Bei einem Wurf in die
Vollen ist das gleichbedeutend -- was nicht fiel, stand. Bei einem Raeumwurf
laesst sich das stehende Bild daraus nicht rekonstruieren, und es wird deshalb
auch nicht behauptet.

WAS EINEN SATZ AUSMACHT: seine Laenge. Ein Satz hat 30 Wuerfe, ein
Warmwerf-Block deutlich weniger. GEMESSEN ueber zwei Spieltage:

    Warmwerfen   1 bis 20 Wuerfe
    Saetze      29 bis 31 Wuerfe

Dazwischen liegt eine leere Luecke von 21 bis 28. Die Grenze bei
`MINDEST_WUERFE_SATZ` trennt also sauber, ohne dass eine Zahl geraten waere.

WARUM NICHT AUF GENAU 30 BESTEHEN: Es gibt Saetze mit 31 Wuerfen -- etwa wenn
ein Wurf von Hand zurueckgenommen wurde, weil ein Kegel aus seiner Fassung
fiel (die Anlage merkt das nicht). Ein solcher Satz als "Warmwerfen"
auszuweisen waere schlimmer als ihn mit 31 Zeilen zu zeigen: Der ueberzaehlige
Wurf steht dann in der Tabelle und laesst sich von Hand beurteilen. Die
Zeile "Wuerfe" am Fuss nennt die Laenge, damit solche Faelle auffallen.

NULLWUERFE IN DEN VOLLEN werden gestrichen (`--nullwuerfe-vor`, Standard 16).
In den ersten 15 Wuerfen stehen vor jedem Wurf alle neun Kegel; ein Wurf ohne
gefallenen Kegel waere dort ein Fehlwurf, und die sind selten -- das
handgefuehrte Wurfprotokoll weist auf 720 Wuerfe genau ZWEI aus.

GEMESSEN am ersten Spieltag: Sieben Abschnitte enthielten eine solche Null.

    Bahn 2  Lauf 1.3   31 Wuerfe, Null bei Wurf 12  -> danach genau 30
    Bahn 2  Lauf 3.3   31 Wuerfe, Null bei Wurf  9  -> danach genau 30
    Bahn 2  Lauf 3.4   31 Wuerfe, Null bei Wurf  1  -> danach genau 30
    Bahn 4  Lauf 2.4   31 Wuerfe, Null bei Wurf  1  -> danach genau 30
    Bahn 5  Lauf 2.3   31 Wuerfe, Null bei Wurf  1  -> danach genau 30
    Bahn 5  Lauf 3.2   31 Wuerfe, Null bei Wurf  1  -> danach genau 30
    Bahn 5  Lauf 3.3   32 Wuerfe, Null bei Wurf  1  -> danach 31

Sechs von sieben ergeben danach GENAU 30 Wuerfe. Kein Satz, der bereits 30
hatte, ist betroffen -- die Regel kann also nichts kaputt machen, was stimmte.
Die Summe aendert sich nie (null Kegel).

Gestrichene Wuerfe verschwinden nicht stillschweigend: Jeder wird beim Bauen
der Tabelle genannt.

Mehr braucht es nicht, und mehr steht im Betrieb auch nicht zur Verfuegung:
KEINE Spielernamen. Die kennt die Anlage waehrend des Spiels nicht, und die
Ergebnistafel erscheint erst am Ende.

Wer will, kann eine Ergebnistafel zum PRUEFEN mitgeben (`--scoreboard`). Dann
wird je Satz ausgewiesen, ob seine Summe dort vorkommt. Das ist eine
Gegenprobe, keine Voraussetzung -- die Tabelle entsteht auch ohne sie.

DIE STRUKTUR EINES SPIELTAGS (vom Nutzer erklaert, 2026-09-01): Ein DURCHGANG
besteht aus VIER Saetzen zu je 30 Wuerfen. Die vier Spieler eines Durchgangs
rotieren ueber die vier Bahnen; auf einer einzelnen Bahn folgen ihre Saetze
deshalb ohne Warmwerfen aufeinander. Erst danach werfen sich die naechsten vier
Spieler ein. Bei zwoelf Spielern sind das drei Durchgaenge, also zwoelf Saetze
je Bahn -- genau die zwoelf Zahlen, die die Ergebnistafel je Bahn ausweist.

    Warmwerfen 1 | Lauf 1.1 | 1.2 | 1.3 | 1.4 | Warmwerfen 2 | Lauf 2.1 | ...
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

WUERFE_JE_SATZ = 30
# Ab so vielen Wuerfen gilt ein Abschnitt als Satz. GEMESSEN ueber zwei
# Spieltage: Warmwerfen 1-20 Wuerfe, Saetze 29-31. Dazwischen ist die Luecke
# 21-28 leer, die Grenze ist also nicht geraten.
MINDEST_WUERFE_SATZ = 25
# Vier Saetze bilden einen Durchgang: Die vier Spieler eines Durchgangs
# rotieren ueber die vier Bahnen. Erst danach werfen sich die naechsten
# vier ein.
SAETZE_JE_DURCHGANG = 4

# Die Kegelnummern kommen fertig aus dem Lauf: Die Kalibrierung ordnet jeder
# Lampe ihre Kegelnummer zu (`calibration.pin_number_mapping`, Q5). Hier wird
# NICHT noch einmal umgerechnet -- das waere eine zweite Wahrheit, und zwei
# Wahrheiten ueber dieselbe Zahl gehen irgendwann auseinander.
#
# ACHTUNG bei alten Laeufen: Wurde ein Lauf vor dem 2026-09-01 erzeugt, stehen
# in seiner `wuerfe.csv` noch die alten Nummern (Lampenindex statt Kegel).
# Solche Tabellen sind an der Kegelraute erkennbar -- dort stuende die 1 hinten.


def lies_tafel(pfad: Path) -> dict[int, list[tuple[str, int]]]:
    je: dict[int, list[tuple[str, int]]] = collections.defaultdict(list)
    with pfad.open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            for bahn in (2, 3, 4, 5):
                je[bahn].append((r["Spieler"], int(r[f"Bahn{bahn}"])))
    return dict(je)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--scoreboard", type=Path, default=None,
                   help="optional: Ergebnistafel zum Gegenpruefen der Summen")
    p.add_argument("--out", type=Path, default=Path("debug/wurftabellen"))
    p.add_argument("--nullwuerfe-vor", type=int, default=16,
                   help="Wuerfe ohne gefallenen Kegel VOR dieser Wurfnummer "
                        "streichen (0 = nichts streichen). In den Vollen "
                        "stehen alle neun Kegel; eine Null ist dort ein "
                        "seltener Fehlwurf -- gemessen 2 auf 720 Wuerfe.")
    a = p.parse_args()

    tafel = lies_tafel(a.scoreboard) if a.scoreboard else {}
    wuerfe: dict[int, list[dict]] = collections.defaultdict(list)
    with (a.run / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            wuerfe[int(r["Bahn"])].append(r)
    for b in wuerfe:
        wuerfe[b].sort(key=lambda x: int(x["Frame"]))

    a.out.mkdir(parents=True, exist_ok=True)
    for bahn in sorted(wuerfe):
        abschnitte: dict[int, list[dict]] = collections.OrderedDict()
        for w in wuerfe[bahn]:
            abschnitte.setdefault(int(w["Spiel"]), []).append(w)

        # Nullwuerfe in den Vollen streichen -- siehe Modulkopf.
        if a.nullwuerfe_vor > 0:
            for nr, block in abschnitte.items():
                behalten = []
                for i, w in enumerate(block, start=1):
                    if i < a.nullwuerfe_vor and int(w["Kegel"]) == 0:
                        print(f"  Bahn {bahn}, Abschnitt {nr}: Wurf {i} mit "
                              f"0 Kegeln bei Frame {w['Frame']} gestrichen "
                              f"({len(block)} Wuerfe im Abschnitt)")
                        continue
                    behalten.append(w)
                abschnitte[nr] = behalten

        # Zum Gegenpruefen, falls eine Ergebnistafel mitgegeben wurde
        sollwerte = collections.Counter(w for _, w in tafel.get(bahn, []))

        spalten: list[tuple[str, list[dict], str]] = []
        warm = 0
        durchgang, im_durchgang = 1, 0
        for nr, block in abschnitte.items():
            summe = sum(int(w["Kegel"]) for w in block)
            if len(block) >= MINDEST_WUERFE_SATZ:
                # Ein Satz. Vier davon bilden einen Durchgang -- die vier
                # Spieler rotieren ueber die Bahnen, deshalb folgen ihre Saetze
                # auf EINER Bahn ohne Warmwerfen aufeinander.
                if im_durchgang == SAETZE_JE_DURCHGANG:
                    durchgang += 1
                    im_durchgang = 0
                im_durchgang += 1
                titel = f"Lauf {durchgang}.{im_durchgang}"
            else:
                # Warmwerfen beendet den laufenden Durchgang.
                if im_durchgang:
                    durchgang += 1
                    im_durchgang = 0
                warm += 1
                titel = f"Warmwerfen {warm}"
            pruefung = ""
            if sollwerte and len(block) >= MINDEST_WUERFE_SATZ:
                pruefung = "trifft" if sollwerte[summe] else "WEICHT AB"
                if len(block) != WUERFE_JE_SATZ:
                    pruefung += f" ({len(block)} statt 30 Wuerfe!)"
            spalten.append((titel, block, pruefung))

        pfad = a.out / f"bahn{bahn}.csv"
        hoehe = max(len(b) for _, b, _ in spalten)
        with pfad.open("w", encoding="utf-8-sig", newline="") as d:
            schreiber = csv.writer(d, delimiter=";")
            kopf = ["Wurfnummer"]
            for t, _, _ in spalten:
                kopf += [t, f"{t} Wurfbild"]
            schreiber.writerow(kopf)
            for i in range(hoehe):
                zeile = [i + 1]
                for _, block, _ in spalten:
                    if i < len(block):
                        w = block[i]
                        gefallen = sorted(
                            int(n) for n in w["Kegelnummern"].split()
                            if n.isdigit())
                        zeile += [w["Kegel"], " ".join(str(k) for k in gefallen)]
                    else:
                        zeile += ["", ""]
                schreiber.writerow(zeile)
            fuss = ["Summe"]
            for _, b, _ in spalten:
                fuss += [sum(int(w["Kegel"]) for w in b), ""]
            schreiber.writerow(fuss)
            fuss = ["Wuerfe"]
            for _, b, _ in spalten:
                fuss += [len(b), ""]
            schreiber.writerow(fuss)

        saetze = sum(1 for t, _, _ in spalten if t.startswith("Lauf"))
        print(f"  Bahn {bahn}: {len(spalten)} Abschnitte, davon {saetze} "
              f"Saetze -> {pfad}")
        for t, b, pruefung in spalten:
            summe = sum(int(w["Kegel"]) for w in b)
            print(f"      {t:<16} {len(b):>3} Wuerfe  Summe {summe:>4}  "
                  f"F{b[0]['Frame']}-{b[-1]['Frame']}  {pruefung}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
