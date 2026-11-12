"""Prueft die Wurftabellen gegen das, was die Tafel selbst gezaehlt hat.

WOZU (Nutzer, 2026-09-24): *"kannst du jetzt dann die korrigierten csvs
einfach mal abchecken, ob die so Sinn ergeben?"*

Eine Korrektur, die nur zu der Ziffer passt, aus der sie abgeleitet wurde,
beweist nichts. Deshalb wird hier gegen drei UNABHAENGIGE Groessen geprueft:

    1. Vollstaendigkeit -- 30 Wuerfe je Spiel, 20 beim Warmwerfen, keine Luecke
    2. Die Tafelsumme    -- SummeTafel(N+1) - SummeTafel(N) muss der gebuchten
                            Kegelzahl von Wurf N entsprechen. Sie kommt aus
                            einem anderen Ziffernfeld und weiss nichts von den
                            Lampen.
    3. Der Endstand      -- die Summe aller Wuerfe eines Spiels gegen den
                            letzten Stand, den die Tafel selbst anzeigte.

Aufruf:

    .venv/Scripts/python.exe tools/pruefe_spieltag_tabelle.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, "tools")

from spieltag_tabelle import (SOLL, SPALTEN,                 # noqa: E402
                              korrigiere_spiel)


def zahl(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--ohne-korrektur", action="store_true")
    p.add_argument("--ziel", type=Path, default=None,
                   help="Ordner fuer tafelprobe_strittig.csv -- die Liste der "
                        "Wuerfe, denen die Tafelsumme widerspricht.")
    a = p.parse_args()

    with (a.lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as f:
        reihen = list(csv.DictReader(f, delimiter=";"))

    roh: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in reihen:
        roh[(r["Bahn"], int(r["Spiel"]))].append(r)
    # Dieselbe Stelle wie im Tabellenbau -- nicht nachgebaut.
    fixes = {k: korrigiere_spiel(v) for k, v in roh.items()}

    je_spiel: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for r in reihen:
        kegel = zahl(r["Kegel"])
        if kegel is None:
            continue
        schluessel = (r["Bahn"], int(r["Spiel"]))
        fix = (None if a.ohne_korrektur
               else fixes[schluessel].get(int(r["Wurfnummer"])))
        r = dict(r, Kegel=str(len(fix[0])) if fix else r["Kegel"],
                 Korrigiert=fix[2] if fix else "")
        je_spiel[schluessel].append(r)

    gesamt = defaultdict(int)
    strittig: list[dict] = []
    print(f"{'Bahn':>4} {'Spiel':<13} {'Wuerfe':>6} {'Luecken':>7} "
          f"{'Summe':>6} {'Tafel':>6} {'ab':>4} {'Tafelprobe':>12} {'korr':>5} {'eigen':>6}")
    for (bahn, spiel), wuerfe in sorted(je_spiel.items(),
                                        key=lambda kv: (kv[0][0], kv[0][1])):
        name = SPALTEN[spiel - 1] if spiel <= len(SPALTEN) else f"Spiel {spiel}?"
        soll = SOLL[spiel - 1] if spiel <= len(SOLL) else 30
        nummern = sorted(int(w["Wurfnummer"]) for w in wuerfe)
        luecken = [n for n in range(1, soll + 1) if n not in nummern]
        summe = sum(int(w["Kegel"]) for w in wuerfe)

        # Der Endstand, wie die Tafel ihn sieht.
        #
        # Die Tafel hinkt einen Wurf hinterher: Ihr letzter Stand plus die
        # Kegel des letzten Wurfs ist das Spielergebnis. Nur dieser eine Wurf
        # geht aus UNSERER Zaehlung ein -- alles davor kommt von der Tafel.
        # Eine Schaetzung ueber alle Anker zu mitteln waere bequemer, wuerde
        # aber unsere eigenen Zahlen in den Massstab hineinrechnen und damit
        # genau die Fehler verdecken, die hier auffallen sollen.
        #
        # ALS ANKER TAUGT NUR EIN STAND, DER ZUR REIHE PASST. GEMESSEN am
        # 2026-09-24: Auf Bahn 5, Lauf 2.2, stand in der letzten Zeile 210,
        # nachdem die vorige schon 211 zeigte -- ein Lesefehler im
        # vierstelligen Summenfeld. Daran gemessen fehlten dem Spiel acht
        # Kegel, die es hatte. Ein Stand, der kleiner ist als ein frueherer,
        # ist keiner.
        anker = hoechster = None
        for i, w in enumerate(wuerfe):
            stand = zahl(w["SummeTafel"])
            if stand is None or (hoechster is not None and stand < hoechster):
                continue
            hoechster = stand
            anker = (i, stand)
        tafel = None
        offen = 0
        if anker is not None:
            i, stand = anker
            offen = len(wuerfe) - i          # so viele Wuerfe steuern WIR bei
            tafel = stand + sum(int(x["Kegel"]) for x in wuerfe[i:])

        # Gegen die Tafelsumme -- ueber LUECKEN HINWEG.
        #
        # Frueher wurden nur Nachbarzeilen verglichen. War die Summe in einer
        # Zeile nicht lesbar, schwieg die Pruefung fuer beide angrenzenden
        # Wuerfe. GEMESSEN am 2026-09-24: Auf Bahn 5, Lauf 3.4, fiel Wurf 20
        # genau so durchs Raster -- weder Kegelziffer noch Nachbarsumme
        # lesbar. Er war der einzige fehlende Kegel des Spiels.
        #
        # Zwischen zwei lesbaren Staenden muss die Summe ALLER Wuerfe dazwischen
        # stimmen. Umfasst die Spanne genau einen Wurf, ist die Abweichung ihm
        # zuzuordnen; sonst wird die Spanne als ganze gemeldet.
        anker_i = [i for i, w in enumerate(wuerfe)
                   if zahl(w["SummeTafel"]) is not None]
        passt = pruefbar = 0
        for i, j in zip(anker_i, anker_i[1:]):
            x, y = wuerfe[i], wuerfe[j]
            sx, sy = zahl(x["SummeTafel"]), zahl(y["SummeTafel"])
            spanne = wuerfe[i:j]
            if not 0 <= sy - sx <= 9 * len(spanne):
                continue
            pruefbar += 1
            gebucht = sum(int(w["Kegel"]) for w in spanne)
            if (sy - sx) == gebucht:
                passt += 1
            else:
                einzeln = len(spanne) == 1
                strittig.append({
                    "Bahn": bahn, "Spalte": name, "Spiel": spiel,
                    "Wurf": (x["Wurfnummer"] if einzeln
                             else f'{x["Wurfnummer"]}-{wuerfe[j-1]["Wurfnummer"]}'),
                    "Wuerfe_in_Spanne": len(spanne),
                    "Frame": x["Frame"], "Zeit": x["Zeit"],
                    "gebucht": gebucht,
                    "Wurfbild": x["Kegelnummern"] if einzeln else "",
                    "Ziffer": x["Ziffer"] if einzeln else "",
                    "Tafelsumme_sagt": sy - sx,
                    "korrigiert": x["Korrigiert"] if einzeln else "",
                    "Raeumen": x["Raeumen"] if einzeln else "",
                    "Grundlinie": x["Grundlinie"] if einzeln else "",
                })
        korr = sum(1 for w in wuerfe if w["Korrigiert"])

        gesamt["wuerfe"] += len(wuerfe)
        gesamt["luecken"] += len(luecken)
        gesamt["passt"] += passt
        gesamt["pruefbar"] += pruefbar
        gesamt["korr"] += korr
        if tafel is not None and tafel != summe:
            gesamt["endstand_falsch"] += 1

        marke = "" if tafel is None or tafel == summe else "  <-- Endstand"
        print(f"{bahn:>4} {name:<13} {len(wuerfe):>6} {len(luecken):>7} "
              f"{summe:>6} {str(tafel):>6} {summe - tafel if tafel else 0:>+4} "
              f"{f'{passt}/{pruefbar}':>12} {korr:>5} "
              f"{offen:>6}{marke}")
        if luecken:
            print(f"     fehlende Wurfnummern: {luecken}")

    q = gesamt["pruefbar"] or 1
    print(f"\n{gesamt['wuerfe']} Wuerfe, {gesamt['luecken']} Luecken, "
          f"{gesamt['korr']} korrigiert.")
    print(f"Tafelprobe Wurf fuer Wurf: {gesamt['passt']}/{gesamt['pruefbar']} "
          f"({100 * gesamt['passt'] / q:.1f} %)")
    print(f"Spiele mit abweichendem Endstand: "
          f"{gesamt['endstand_falsch']} von {len(je_spiel)}")

    if a.ziel and strittig:
        a.ziel.mkdir(parents=True, exist_ok=True)
        pfad = a.ziel / "tafelprobe_strittig.csv"
        with pfad.open("w", encoding="utf-8-sig", newline="") as f:
            schreiber = csv.DictWriter(f, fieldnames=list(strittig[0]),
                                       delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(strittig)
        print(f"\nWuerfe, denen die Tafelsumme widerspricht: {pfad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
