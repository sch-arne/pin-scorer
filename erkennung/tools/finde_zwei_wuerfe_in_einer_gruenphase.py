# -*- coding: utf-8 -*-
"""Findet Gruenphasen, in denen ZWEI Wuerfe stecken.

WOZU. „Eine Gruenphase = ein Wurf" steht nirgends als Pruefung, sondern in der
Form der Zustandsmaschine (BUG-035). Wo die Annahme nicht gilt, wird der
zweite Wurf nicht gebucht -- und seine Kegel bekommt still der Folgewurf.
BUG-035 hat das vorhergesagt:

    „Fiele in einer verschmolzenen Gruenphase auch nur ein Kegel, bekaeme ihn
     still der Folgewurf zugeschlagen, und NICHTS wuerde es melden."

Am 1. Spieltag ist genau das passiert, und zwar mit allen neun Kegeln.

WIE UNTERSCHEIDET MAN ZWEI WUERFE VON EINEM BLINKEN? Beides ist ein Bild, das
verschwindet und wiederkommt. Der Unterschied ist die Pause:

    Blinken (Alle Neune, 8er Kranz)   rund 30 Frames Takt
    zweiter Wurf                      die Anlage raeumt, stellt auf, der
                                      Spieler holt aus -- Hunderte Frames

Deshalb wird alles zusammengelegt, was weniger als `BLINKLUECKE` Frames
auseinanderliegt, und nur gemeldet, wenn danach noch eine Pause von
mindestens `MINDESTPAUSE` Frames uebrig bleibt.

UND EINE DRITTE BEDINGUNG, ohne die es nicht traegt: Das erste Bild muss NACH
dem Raeumen entstanden sein. Steht es schon beim Gruen-AN, ist es das
Nachleuchten des vorigen Wurfs -- ohne diese Bedingung meldet das Werkzeug
genau einen Fehlalarm je Spieltag.

GEMESSEN ueber zwei volle Spieltage (3359 Wuerfe):

    1. Spieltag   1 Fund   Bahn 5, Frame 286570-287402  -- der echte Fall
    2. Spieltag   0 Funde

Aufruf:

    .venv/Scripts/python.exe tools/finde_zwei_wuerfe_in_einer_gruenphase.py \
        debug/<quelle>/lauf_<zeit>
"""

from __future__ import annotations

import argparse
import collections
import csv
from pathlib import Path

# Gemessener Blinktakt auf dieser Anlage: rund 30 Frames (1,2 s bei 25 fps).
# Das Doppelte laesst Raum fuer ein unregelmaessiges Blinken, ohne in die
# Pause zwischen zwei Wuerfen zu reichen (die kuerzeste gemessene ist 220).
BLINKLUECKE = 60

# So lange muss es dunkel gewesen sein, damit aus zwei Bildern zwei Wuerfe
# werden. Kuerzeste gemessene Pause zwischen zwei echten Wuerfen: 220 Frames.
MINDESTPAUSE = 120

# So weit nach dem Gruen-AN muss das erste Bild beginnen. Nachleuchten des
# vorigen Wurfs steht sofort da (gemessen: 0 bis 55 Frames).
MINDESTABSTAND_ZUM_GRUEN_AN = 100


def gruenphasen(ordner: Path) -> dict[str, list[tuple[int, int]]]:
    """Je Bahn die Abschnitte zwischen Gruen-AN und dem naechsten Gruen-AUS."""
    phasen: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    zustand: dict[str, str] = {}
    beginn: dict[str, int] = {}
    with (ordner / "gruenspur.csv").open(encoding="utf-8-sig",
                                         newline="") as datei:
        for zeile in csv.DictReader(datei, delimiter=";"):
            bahn, frame, z = zeile["Bahn"], int(zeile["Frame"]), zeile["Zustand"]
            if z == "ON" and zustand.get(bahn) != "ON":
                beginn[bahn] = frame
            elif z == "OFF" and zustand.get(bahn) == "ON":
                phasen[bahn].append((beginn.get(bahn, frame), frame))
            if z in ("ON", "OFF"):
                zustand[bahn] = z
    return phasen


def kegelbilder(ordner: Path) -> dict[str, dict[int, set[int]]]:
    """Je Bahn und Frame die Menge der brennenden Kegellampen."""
    bild: dict[str, dict[int, set[int]]] = collections.defaultdict(dict)
    with (ordner / "lampenspur.csv").open(encoding="utf-8-sig",
                                          newline="") as datei:
        for zeile in csv.DictReader(datei, delimiter=";"):
            frame = int(zeile["Frame"])
            menge = bild[zeile["Bahn"]].setdefault(frame, set())
            if zeile["Zustand"] == "ON":
                menge.add(int(zeile["Lampe"].split("_")[-1]))
    return bild


def gruppen(frames: list[int], bild: dict[int, set[int]]) -> list[list[int]]:
    """Zusammenhaengende Abschnitte mit Licht, Blinkluecken zugeklebt."""
    gefunden: list[list[int]] = []
    for frame in frames:
        if not bild[frame]:
            continue
        if gefunden and frame - gefunden[-1][-1] <= BLINKLUECKE:
            gefunden[-1].append(frame)
        else:
            gefunden.append([frame])
    return gefunden


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("lauf", type=Path, help="Ordner eines Laufs")
    a = p.parse_args()

    phasen = gruenphasen(a.lauf)
    bilder = kegelbilder(a.lauf)

    print(f"{'Bahn':<6}{'Gruenphase':<22}{'Laenge':>8}{'Bilder':>8}"
          f"   je Bild: Frames / groesste Kegelzahl")
    funde = 0
    for bahn in sorted(phasen):
        rahmen = sorted(bilder[bahn])
        for von, bis in phasen[bahn]:
            innen = [f for f in rahmen if von <= f <= bis]
            teile = gruppen(innen, bilder[bahn])
            if len(teile) < 2:
                continue
            pausen = [teile[i + 1][0] - teile[i][-1]
                      for i in range(len(teile) - 1)]
            if max(pausen) < MINDESTPAUSE:
                continue
            if teile[0][0] - von < MINDESTABSTAND_ZUM_GRUEN_AN:
                continue
            funde += 1
            beschreibung = " | ".join(
                f"{g[0]}-{g[-1]}/{max(len(bilder[bahn][f]) for f in g)}"
                for g in teile)
            print(f"{bahn:<6}{f'{von}-{bis}':<22}{bis - von:>8}"
                  f"{len(teile):>8}   {beschreibung}")

    print(f"\n{funde} Gruenphase(n) mit mehr als einem Kegelbild.")
    if funde:
        print("Das erste Bild gehoert zu einem Wurf, der nie gebucht wurde.\n"
              "Seine Kegel stecken im Ergebnis des zweiten (BUG-035).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
