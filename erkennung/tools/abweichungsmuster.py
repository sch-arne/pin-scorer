"""Sucht SYSTEM in den Abweichungen eines Laufs, statt Einzelfaelle zu zeigen.

WOZU (Nutzer, 2026-09-24): *"Wir speichern ja relativ viel Metainformationen
mit. Kannst du da schon so etwas auswerten (bspw. die meisten Abweichungen
beginnen ab Wurf 15 -> dann wird vermutlich Räumen nicht mehr erkannt) oder
konsequent wenn das Board eine 2 meldet, melden wir eine 9?"*

`vergleiche_lampen_ziffern.py` sagt, WIE VIELE Wuerfe auseinandergehen.
Dieses Werkzeug fragt, WORAN man sie erkennt -- und zwar an Groessen, die der
Lauf ohnehin mitschreibt:

    nach Wurf im Zyklus   1-15 sind "in die Vollen", 16-30 das Abraeumen.
                          Bricht es erst in der zweiten Haelfte, ist die
                          Grundlinie schuld, nicht das Lesen.
    nach Zyklus           dasselbe, eine Ebene groeber
    nach Raeumen-Merker   erkennt das Werkzeug das Abraeumen ueberhaupt?
    Kreuztabelle          was zeigt die Tafel, was buchen wir? Eine feste
                          Verwechslung (Tafel 2 -> wir 9) sieht anders aus als
                          ein Rauschen um eins.
    nach Spiel            wandert der Fehler ueber die Zeit?
    nach Bahn             oder haengt er an einer Kalibrierung?

Grundlage ist `wuerfe.csv`; wenn vorhanden, wird `gegenprobe.csv` fuer das
Urteil der Summe dazugenommen.

Aufruf:

    .venv/Scripts/python.exe tools/abweichungsmuster.py <laufordner>
    ... --bahn 2
"""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


def zahl(text: str) -> int | None:
    text = (text or "").strip()
    try:
        return int(text)
    except ValueError:
        return None


def lies(pfad: Path) -> list[dict[str, str]]:
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        return list(csv.DictReader(datei, delimiter=";"))


def balken(anteil: float, breite: int = 30) -> str:
    voll = int(round(anteil * breite))
    return "#" * voll + "." * (breite - voll)


def quote(zeilen: list[tuple[int, int]], titel: str, spalte: str) -> None:
    """Gibt je Schluessel aus, wie oft Lampen und Ziffer auseinandergingen."""
    je: dict[int, list[int]] = defaultdict(list)
    for schluessel, abweichung in zeilen:
        je[schluessel].append(abweichung)
    if not je:
        return
    print(f"\n{titel}")
    print(f"  {spalte:>6s} {'Wuerfe':>6s} {'uneinig':>7s} {'Quote':>7s}  "
          f"{'Mittel':>6s}  Verteilung")
    for schluessel in sorted(je):
        werte = je[schluessel]
        streit = [w for w in werte if w != 0]
        anteil = len(streit) / len(werte)
        mittel = sum(streit) / len(streit) if streit else 0.0
        print(f"  {schluessel:>6d} {len(werte):>6d} {len(streit):>7d} "
              f"{100 * anteil:>6.1f}% {mittel:>+6.2f}  {balken(anteil)}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("lauf", type=Path)
    p.add_argument("--bahn", type=int, default=0)
    a = p.parse_args()

    wuerfe = lies(a.lauf / "wuerfe.csv")
    if a.bahn:
        wuerfe = [w for w in wuerfe if zahl(w["Bahn"]) == a.bahn]

    # Nur Wuerfe, bei denen BEIDE Zeugen sprechen -- sonst ist "uneinig"
    # nicht definiert und eine stumme Ziffer wuerde als Einigkeit zaehlen.
    paare = []
    for w in wuerfe:
        lampen, ziffer = zahl(w["Kegel"]), zahl(w["Ziffer"])
        if lampen is None or ziffer is None:
            continue
        paare.append((w, lampen - ziffer))

    print(f"Lauf: {a.lauf}")
    print(f"{len(wuerfe)} Wuerfe, davon {len(paare)} mit lesbarer Ziffer "
          f"({100 * len(paare) / max(1, len(wuerfe)):.1f} %)")
    streit = [(w, d) for w, d in paare if d != 0]
    print(f"{len(streit)} uneinig "
          f"({100 * len(streit) / max(1, len(paare)):.1f} %)")

    quote([(zahl(w["WurfImZyklus"]) or 0, d) for w, d in paare],
          "Nach Wurf im Zyklus (1-15 in die Vollen, danach Abraeumen)",
          "Wurf")
    quote([(zahl(w["Zyklus"]) or 0, d) for w, d in paare],
          "Nach Zyklus", "Zyklus")
    quote([(zahl(w["Bahn"]) or 0, d) for w, d in paare], "Nach Bahn", "Bahn")
    quote([(zahl(w["Spiel"]) or 0, d) for w, d in paare], "Nach Spiel",
          "Spiel")
    quote([(zahl(w["Grundlinie"]) or 0, d) for w, d in paare],
          "Nach gebuchter Grundlinie (wie viele Kegel wir abgezogen haben)",
          "Grundl")

    # --- Raeumen erkannt oder nicht? ---
    mit = [(w, d) for w, d in paare if (w["Raeumen"] or "").strip()]
    ohne = [(w, d) for w, d in paare if not (w["Raeumen"] or "").strip()]
    print("\nNach Raeumen-Merker")
    for name, gruppe in (("Raeumen erkannt", mit), ("kein Raeumen", ohne)):
        if not gruppe:
            continue
        s = [d for _, d in gruppe if d != 0]
        print(f"  {name:<18s} {len(gruppe):>5d} Wuerfe, {len(s):>4d} uneinig "
              f"({100 * len(s) / len(gruppe):5.1f} %), Mittel "
              f"{sum(s) / len(s) if s else 0:+.2f}")

    # --- Kreuztabelle: was zeigt die Tafel, was buchen wir? ---
    print("\nKreuztabelle -- Zeile: Ziffer der Tafel, Spalte: von uns gebucht")
    tabelle: dict[int, Counter] = defaultdict(Counter)
    for w, _ in paare:
        tabelle[zahl(w["Ziffer"])][zahl(w["Kegel"])] += 1
    kopf = "  Tafel |" + "".join(f"{k:>5d}" for k in range(10)) + "   Summe"
    print(kopf)
    print("  " + "-" * (len(kopf) - 2))
    for ziffer in sorted(tabelle):
        zeile = tabelle[ziffer]
        gesamt = sum(zeile.values())
        felder = "".join(
            (f"{zeile[k]:>5d}" if zeile[k] else "    .") for k in range(10))
        print(f"  {ziffer:>5d} |{felder}   {gesamt:>5d}")

    # --- Urteil der Summe, falls die Gegenprobe mitgeschrieben wurde ---
    gp = a.lauf / "gegenprobe.csv"
    if gp.exists():
        zeilen = lies(gp)
        if a.bahn:
            zeilen = [z for z in zeilen if zahl(z["Bahn"]) == a.bahn]
        print(f"\nUrteil der Gegenprobe ({len(zeilen)} Eintraege)")
        for urteil, wie_oft in Counter(
                z["Urteil"] for z in zeilen).most_common():
            print(f"  {urteil:<28s} {wie_oft:>5d}")
        unklar = sum(1 for z in zeilen if (z["LampenUnklar"] or "0") != "0")
        grundlage = sum(1 for z in zeilen
                        if (z["GrundlageUnklar"] or "0") not in ("0", ""))
        print(f"  davon Lampen unklar: {unklar}, Grundlage unklar: {grundlage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
