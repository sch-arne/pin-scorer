"""Stellt Lampen, Kegelziffer und Summenanzeige eines Laufs gegenueber.

WOZU (Nutzer, 2026-09-17): *"anschliessend suchst du die Unterschiede
zwischen Ziffer und Wuerfen"* -- und am 2026-09-18: *"Und dann schau dir die
Unterschiede zwischen Lampen und Ziffern an"*.

Drei Zeugen sagen zu jedem Wurf, wie viele Kegel gefallen sind, und sie sind
voneinander unabhaengig:

    Lampen   der Kegelkranz, Spalte `Kegel`
    Ziffer   das Feld `pin_count` der Tafel, Spalte `Ziffer`
    Summe    die Gesamtsumme der Tafel, Spalte `SummeTafel`

Die Summe ist der eigentliche Schiedsrichter. Sie steht in einem ANDEREN
Ziffernfeld und wird von der Anlage verspaetet nachgetragen (BUG-010): Beim
Melden von Wurf N zeigt sie den Stand VOR Wurf N. Damit gilt

    SummeTafel(N+1) - SummeTafel(N) = Kegel von Wurf N

Widersprechen sich Lampen und Ziffer, entscheidet also nicht die Mehrheit,
sondern dieser Zuwachs -- sofern er lesbar ist. Wo er fehlt, bleibt der Fall
offen und wird auch so ausgewiesen. Eine Gegenprobe, die im Zweifel eine Seite
zur Siegerin erklaert, waere keine.

DIE BEWEISREGEL DES NUTZERS (2026-09-18):

    "die Lampen luegen nie! Es ist immer unsere Auswertung... wenn die Ziffern
     sich gegenseitig bestaetigen, dann wissen wir, der Algorithmus der Lampen
     ausliest, ist kaputt"

Der Kegelkranz ist Wirklichkeit, keine Meinung. Was der Bericht "Lampen" nennt,
ist deshalb nie eine Aussage der Anlage, sondern IMMER unsere Rechnung darauf
-- Schwellen, Grundlinie, Abzug beim Raeumen. Bestaetigen Ziffer und Summe
einander, ist der Fall damit nicht unentschieden, sondern entschieden: Dann ist
diese Rechnung kaputt, und zwar bei uns. Der Bericht sagt das auch so.

Erster Fund mit dieser Regel: BUG-031 -- die Grundlinie wird beim Gruen-AN
gemessen und beim Gruen-AUS verwendet.

Aufruf:

    .venv/Scripts/python.exe tools/vergleiche_lampen_ziffern.py \
        debug/<quelle>/lauf_2026-09-18_07-30-02

    ... --bahn 2 --alle      # nur eine Bahn, und jeden Wurf einzeln
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Wurf:
    """Eine Zeile der `wuerfe.csv`, auf das Noetige eingedampft."""
    zeit: str
    frame: int
    bahn: int
    lampen: int | None
    ziffer: int | None
    nummer: int | None
    spiel: int | None
    summe: int | None
    status: str
    pruefungen: str

    @property
    def einig(self) -> bool | None:
        """True/False, wenn beide Zeugen sprechen -- sonst None."""
        if self.lampen is None or self.ziffer is None:
            return None
        return self.lampen == self.ziffer


def _zahl(text: str) -> int | None:
    """Leere Felder und Fragezeichen sind KEINE Null, sondern Schweigen."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def lies(pfad: Path) -> list[Wurf]:
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        return [
            Wurf(
                zeit=zeile.get("Zeit", ""),
                frame=_zahl(zeile.get("Frame", "")) or 0,
                bahn=_zahl(zeile.get("Bahn", "")) or 0,
                lampen=_zahl(zeile.get("Kegel", "")),
                ziffer=_zahl(zeile.get("Ziffer", "")),
                nummer=_zahl(zeile.get("Wurfnummer", "")),
                spiel=_zahl(zeile.get("Spiel", "")),
                summe=_zahl(zeile.get("SummeTafel", "")),
                status=(zeile.get("Status") or "").strip(),
                pruefungen=(zeile.get("Pruefungen") or "").strip(),
            )
            for zeile in csv.DictReader(datei, delimiter=";")
        ]


def summenzeuge(wuerfe: list[Wurf]) -> dict[int, int]:
    """Was der Summenzuwachs je Wurf sagt -- Schluessel ist der Frame.

    Nur ausgewertet, wenn BEIDE Summen lesbar sind, beide Wuerfe zum selben
    Spiel gehoeren und der zweite unmittelbar auf den ersten folgt. Sonst
    liegt zwischen ihnen womoeglich ein verlorener Wurf, und der Zuwachs
    zaehlte zwei Wuerfe zusammen.
    """
    aussage: dict[int, int] = {}
    je_bahn: dict[int, list[Wurf]] = defaultdict(list)
    for wurf in wuerfe:
        je_bahn[wurf.bahn].append(wurf)
    for reihe in je_bahn.values():
        reihe.sort(key=lambda w: w.frame)
        for davor, danach in zip(reihe, reihe[1:]):
            if davor.summe is None or danach.summe is None:
                continue
            if davor.spiel != danach.spiel:
                continue
            if (davor.nummer is None or danach.nummer is None
                    or danach.nummer != davor.nummer + 1):
                continue
            zuwachs = danach.summe - davor.summe
            # Mehr als neun Kegel kann ein Wurf nicht legen, weniger als null
            # auch nicht -- alles andere ist Lesefehler, nicht Aussage.
            if 0 <= zuwachs <= 9:
                aussage[davor.frame] = zuwachs
    return aussage


def bericht(wuerfe: list[Wurf], alle: bool) -> None:
    zeuge = summenzeuge(wuerfe)
    bahnen = sorted({w.bahn for w in wuerfe})

    print(f"{len(wuerfe)} Wuerfe, Bahnen {bahnen}\n")
    kopf = (f"{'Bahn':>4s} {'Wuerfe':>6s} {'beide da':>8s} "
            f"{'einig':>12s} {'uneinig':>8s} {'Ziffer stumm':>12s}")
    print(kopf)
    print("-" * len(kopf))

    streit_gesamt: list[tuple[Wurf, int | None]] = []
    for bahn in bahnen:
        reihe = [w for w in wuerfe if w.bahn == bahn]
        mit = [w for w in reihe if w.einig is not None]
        einig = [w for w in mit if w.einig]
        streit = [w for w in mit if not w.einig]
        stumm = len(reihe) - len(mit)
        anteil = f"{100 * len(einig) / len(mit):5.1f} %" if mit else "      - "
        print(f"{bahn:>4d} {len(reihe):>6d} {len(mit):>8d} "
              f"{len(einig):>5d} {anteil} {len(streit):>8d} {stumm:>12d}")
        streit_gesamt += [(w, zeuge.get(w.frame)) for w in streit]

    # --- Wie gross ist der Unterschied, und in welche Richtung? ---
    if streit_gesamt:
        print("\nUnterschied Lampen minus Ziffer:")
        verteilung = Counter(w.lampen - w.ziffer for w, _ in streit_gesamt)
        for abstand in sorted(verteilung):
            print(f"  {abstand:+3d}  {verteilung[abstand]:4d} "
                  f"{'#' * min(60, verteilung[abstand])}")

    # --- Der Schiedsrichter ---
    fuer_lampen = fuer_ziffer = fuer_keinen = ohne_zeuge = 0
    for wurf, sagt in streit_gesamt:
        if sagt is None:
            ohne_zeuge += 1
        elif sagt == wurf.lampen:
            fuer_lampen += 1
        elif sagt == wurf.ziffer:
            fuer_ziffer += 1
        else:
            fuer_keinen += 1

    print(f"\nWas die Summe zu den {len(streit_gesamt)} Streitfaellen sagt:")
    print(f"  Ziffer + Summe einig -> UNSERE Lampenrechnung ist falsch : "
          f"{fuer_ziffer}")
    print(f"  Lampen + Summe einig -> die Ziffer ist falsch gelesen    : "
          f"{fuer_lampen}")
    print(f"  Summe sagt etwas Drittes -> alle drei fraglich           : "
          f"{fuer_keinen}")
    print(f"  Summe schweigt -> offen                                  : "
          f"{ohne_zeuge}")

    # --- Und was sagt die Summe zu den Wuerfen, bei denen alle einig waren? ---
    # Ohne diese Zeile waere die Zahl darueber nicht einzuordnen: Erst wenn der
    # Schiedsrichter im unstrittigen Fall fast immer zustimmt, ist sein Urteil
    # im strittigen ueberhaupt etwas wert.
    einige = [w for w in wuerfe if w.einig and w.frame in zeuge]
    bestaetigt = sum(1 for w in einige if zeuge[w.frame] == w.lampen)
    if einige:
        print(f"\nZur Kontrolle -- unstrittige Wuerfe mit Summenzeugen: "
              f"{bestaetigt} von {len(einige)} bestaetigt "
              f"({100 * bestaetigt / len(einige):.1f} %)")

    # --- Die Streitfaelle im Einzelnen ---
    if streit_gesamt:
        print(f"\n{'Zeit':>8s} {'Frame':>7s} {'Bahn':>4s} {'Wurf':>4s} "
              f"{'Sp':>2s} {'Lampen':>6s} {'Ziffer':>6s} {'Summe':>6s}  "
              f"{'Urteil':<14s} Status")
        for wurf, sagt in sorted(streit_gesamt, key=lambda p: p[0].frame):
            urteil = ("offen" if sagt is None
                      else "Ziffer falsch" if sagt == wurf.lampen
                      else "WIR falsch" if sagt == wurf.ziffer
                      else f"weder ({sagt})")
            print(f"{wurf.zeit:>8s} {wurf.frame:>7d} {wurf.bahn:>4d} "
                  f"{'-' if wurf.nummer is None else wurf.nummer:>4} "
                  f"{'-' if wurf.spiel is None else wurf.spiel:>2} "
                  f"{wurf.lampen:>6d} {wurf.ziffer:>6d} "
                  f"{'-' if wurf.summe is None else wurf.summe:>6} "
                  f"{urteil:<14s} {wurf.status}")

    if alle:
        print(f"\nAlle Wuerfe:\n{'Zeit':>8s} {'Frame':>7s} {'Bahn':>4s} "
              f"{'Wurf':>4s} {'Lampen':>6s} {'Ziffer':>6s} {'Summe':>6s} "
              f"{'Zeuge':>5s}  Status")
        for wurf in sorted(wuerfe, key=lambda w: w.frame):
            print(f"{wurf.zeit:>8s} {wurf.frame:>7d} {wurf.bahn:>4d} "
                  f"{'-' if wurf.nummer is None else wurf.nummer:>4} "
                  f"{'-' if wurf.lampen is None else wurf.lampen:>6} "
                  f"{'-' if wurf.ziffer is None else wurf.ziffer:>6} "
                  f"{'-' if wurf.summe is None else wurf.summe:>6} "
                  f"{zeuge.get(wurf.frame, '-'):>5}  {wurf.status}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("lauf", type=Path,
                   help="Laufordner mit wuerfe.csv (oder die Datei selbst)")
    p.add_argument("--bahn", type=int, default=0,
                   help="nur diese Bahn betrachten")
    p.add_argument("--alle", action="store_true",
                   help="jeden Wurf einzeln auflisten, nicht nur die "
                        "Streitfaelle")
    a = p.parse_args()

    pfad = a.lauf if a.lauf.is_file() else a.lauf / "wuerfe.csv"
    if not pfad.exists():
        print(f"Keine wuerfe.csv unter {pfad}")
        return 1

    wuerfe = lies(pfad)
    if a.bahn:
        wuerfe = [w for w in wuerfe if w.bahn == a.bahn]
    if not wuerfe:
        print("Keine Wuerfe in dieser Auswahl")
        return 1

    print(f"Lauf: {pfad}\n")
    bericht(wuerfe, a.alle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
