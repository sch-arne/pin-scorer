#!/usr/bin/env python
"""Kalibriert alle Bahnen aus EINER von Hand vermessenen Tafel.

DER ABLAUF (so vom Nutzer gewuenscht, 2026-09-09)

    "ich moechte, dass ich wenn es eine komplett unbekannte Bahn ist, eine
     verzerrte Tafel kalibriere, und er dann auch alle anderen Bahnen dazu
     findet (Sie muessen immer derselbe Bautyp sein). Also soll auch hier
     bitte immer nur ein Template genommen werden, um die Bahnen zu finden.
     Am Ende sollte dann eine Abfrage kommen, wie welche Bahn heisst."

In einer fremden Halle also: EINE Tafel in der Oberflaeche kalibrieren,
speichern, dieses Werkzeug laufen lassen. Die uebrigen Tafeln findet der
Rechner, und die Bahnnummern vergibst du am Ende.

Das funktioniert, weil die ROIs in NORMIERTEN Tafelkoordinaten liegen: Sind
die vier Ecken gefunden, folgen alle Lampen und Ziffern daraus.

WELCHE TAFEL SICH ALS VORLAGE EIGNET -- gemessen, und es widerspricht der
Erwartung: Eine moeglichst FRONTAL gesehene Tafel traegt besser als eine
schraege. Beim Geraderechnen wird eine schraege aus weniger Pixeln gestreckt,
das Ergebnis ist unschaerfer und traegt weniger Merkmale. Mit dem gelockerten
Verhaeltnistest (siehe `BoardFinder`) gelingen inzwischen beide, aber die
frontale bleibt die sichere Wahl.

    .venv/Scripts/python.exe tools/kalibriere_automatisch.py \
        --vorlage data/calibrations/EineBahn.json \
        --video kegelVideos/neue_halle.mp4 \
        --ausgabe data/calibrations/NeueHalle.json
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration.board_finder import (BoardFinder, entzerre,  # noqa: E402
                                               quad_groesse)
from kegel_cv.calibration.model import Calibration  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.video.factory import open_source  # noqa: E402

log = logging.getLogger("kalibriere_automatisch")


def hole_frames(pfad: str, indizes: list[int], cfg) -> dict[int, np.ndarray]:
    """Liest genau die genannten Frames -- sequentiell, ohne zu springen.

    Bei einem Stream gibt es kein Zurueck, und bei einer Datei landet ein
    Sprung auf dem naechsten Schluesselbild statt auf dem gewuenschten Frame.
    """
    gesucht = set(indizes)
    quelle = open_source(pfad, cfg)
    quelle.open()
    bilder: dict[int, np.ndarray] = {}
    n = 0
    try:
        while n <= max(gesucht):
            f = quelle.read()
            if f is None:
                break
            n += 1
            if n in gesucht:
                bilder[n] = f.image.copy()
    finally:
        quelle.close()
    return bilder


def frage_bahnnummern(anzahl: int, vorgabe: list[int] | None) -> list[int]:
    """Fragt, welche Bahnnummer welche gefundene Tafel traegt.

    Die Tafeln kommen von LINKS NACH RECHTS. Welche Nummer sie in der Halle
    tragen, kann der Rechner nicht wissen -- das steht nur an der Wand.
    """
    if vorgabe is not None:
        if len(vorgabe) != anzahl:
            raise SystemExit(
                f"--bahnen nennt {len(vorgabe)} Nummern, gefunden wurden "
                f"aber {anzahl} Tafeln.")
        return vorgabe

    print(f"\n{anzahl} Tafeln gefunden, von links nach rechts.")
    print("Welche Bahnnummern tragen sie? (z. B. 2 3 4 5 -- Enter fuer "
          f"1 bis {anzahl})")
    eingabe = input("> ").strip()
    if not eingabe:
        return list(range(1, anzahl + 1))
    teile = eingabe.replace(",", " ").split()
    if len(teile) != anzahl:
        raise SystemExit(f"{len(teile)} Nummern fuer {anzahl} Tafeln.")
    try:
        return [int(t) for t in teile]
    except ValueError as exc:
        raise SystemExit(f"Keine Zahl: {exc}") from exc


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vorlage", required=True, type=Path,
                   help="Kalibrierung mit der von Hand vermessenen Tafel")
    p.add_argument("--video", required=True,
                   help="Video oder Stream, der kalibriert werden soll")
    p.add_argument("--vorlagen-video", default=None,
                   help="Video zur Vorlage, falls ein anderes als --video")
    p.add_argument("--ausgabe", required=True, type=Path)
    p.add_argument("--vorlage-bahn", type=int, default=None,
                   help="welche Bahn der Vorlage als Muster dient "
                        "(Vorgabe: die erste)")
    p.add_argument("--vorlagen-frame", type=int, default=3000,
                   help="aus diesem Frame wird die Vorlage geschnitten")
    p.add_argument("--frame", type=int, default=300,
                   help="in diesem Frame des Zielvideos wird gesucht")
    p.add_argument("--min-inlier", type=int, default=18,
                   help="weniger tragende Merkmale gelten als kein Treffer")
    p.add_argument("--max-tafeln", type=int, default=8)
    p.add_argument("--ohne-verfeinerung", action="store_true",
                   help="den zweiten Durchgang mit einer Vorlage aus "
                        "dem Zielbild ueberspringen")
    p.add_argument("--bahnen", default=None,
                   help="Bahnnummern von links nach rechts, ohne Rueckfrage")
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    kal = Calibration.load(a.vorlage)
    if not kal.lanes:
        print("Die Vorlage enthaelt keine kalibrierte Bahn.")
        return 1

    muster = kal.lanes[0]
    if a.vorlage_bahn is not None:
        passend = [l for l in kal.lanes
                   if a.vorlage_bahn in (l.lane_id, l.display_number)]
        if not passend:
            print(f"Bahn {a.vorlage_bahn} steht nicht in der Vorlage.")
            return 1
        muster = passend[0]

    vorlagen_video = a.vorlagen_video or a.video
    print(f"Vorlage: Bahn {muster.display_number} aus {vorlagen_video}, "
          f"Frame {a.vorlagen_frame}")
    quelle_bilder = hole_frames(vorlagen_video, [a.vorlagen_frame], cfg)
    vorlagen_bild = quelle_bilder.get(a.vorlagen_frame)
    if vorlagen_bild is None:
        print("Aus dem Vorlagenvideo kam kein Frame.")
        return 1

    groesse = quad_groesse(muster.quad)
    muster_bild = entzerre(vorlagen_bild, muster.quad, groesse)
    print(f"  Muster {groesse[0]}x{groesse[1]} px")

    print(f"Suche in {a.video}, Frame {a.frame}")
    ziel_bilder = hole_frames(a.video, [a.frame], cfg)
    ziel = ziel_bilder.get(a.frame)
    if ziel is None:
        print("Aus dem Zielvideo kam kein Frame.")
        return 1

    finder = BoardFinder(min_inlier=a.min_inlier)
    treffer = finder.finde_alle(ziel, [muster_bild], max_tafeln=a.max_tafeln)

    # ZWEITER DURCHGANG MIT EINER VORLAGE AUS DEM ZIELBILD SELBST.
    #
    # Die mitgebrachte Vorlage stammt aus einer anderen Aufnahme -- anderes
    # Licht, andere Kamera, anderer Massstab. Sobald der erste Durchgang eine
    # Tafel gefunden hat, laesst sich aus dem ZIELBILD eine Vorlage schneiden,
    # die zu allen uebrigen Tafeln desselben Bildes viel besser passt.
    #
    # GEMESSEN 2026-09-09, Vorlage von der Hallenkamera gegen ein
    # Overlay-Video einer anderen Kamera:
    #
    #     Tafel     Durchgang 1   Durchgang 2   Verschiebung
    #     x= 555      25 Merkmale   39            1,9 px
    #     x= 863      36            85            1,0 px
    #     x=1096      19            37            3,0 px
    #     x=1386      12            15           16,3 px
    #
    # Die Merkmale verdoppeln sich fast, und die am schlechtesten sitzende
    # Tafel rueckt um 16 Pixel an die richtige Stelle.
    if treffer and not a.ohne_verfeinerung:
        bester = max(treffer, key=lambda t: t.inlier)
        eigene = entzerre(ziel, bester.quad, quad_groesse(bester.quad))
        zweite = BoardFinder(min_inlier=a.min_inlier).finde_alle(
            ziel, [eigene], max_tafeln=a.max_tafeln)
        if len(zweite) >= len(treffer) and sum(t.inlier for t in zweite) > \
                sum(t.inlier for t in treffer):
            print(f"  Zweiter Durchgang mit einer Vorlage aus dem Zielbild: "
                  f"{sum(t.inlier for t in treffer)} -> "
                  f"{sum(t.inlier for t in zweite)} tragende Merkmale")
            treffer = zweite
        else:
            print("  Zweiter Durchgang brachte nichts -- es bleibt beim ersten")

    if not treffer:
        print("\nKeine Tafel gefunden. Moegliche Gruende: anderer Bautyp, "
              "sehr anderer Blickwinkel, oder der gewaehlte Frame taugt "
              "nicht (Person davor, Bewegungsunschaerfe).")
        return 2

    print(f"\n{len(treffer)} Tafeln gefunden:")
    for i, t in enumerate(treffer, start=1):
        mitte = np.float32(t.quad).mean(axis=0)
        print(f"  {i}. Bildmitte x={mitte[0]:.0f} y={mitte[1]:.0f} | "
              f"{t.inlier} von {t.paare} Merkmalen tragen ({t.guete:.0%})")

    vorgabe = None
    if a.bahnen:
        vorgabe = [int(x) for x in a.bahnen.replace(",", " ").split()]
    nummern = frage_bahnnummern(len(treffer), vorgabe)

    bahnen = []
    for i, (t, nummer) in enumerate(zip(treffer, nummern), start=1):
        neu = muster.model_copy(deep=True)
        neu.lane_id = i                 # Position von links, 1-basiert
        neu.real_lane_number = nummer
        neu.quad = t.quad
        bahnen.append(neu)

    ergebnis = kal.model_copy(deep=True)
    ergebnis.lanes = bahnen
    ergebnis.name = a.ausgabe.stem
    hoehe, breite = ziel.shape[:2]
    ergebnis.source_hint = type(kal.source_hint)(
        width=breite, height=hoehe, video=str(a.video))
    a.ausgabe.parent.mkdir(parents=True, exist_ok=True)
    ergebnis.save(a.ausgabe)

    zuordnung = ", ".join(f"Tafel {i} von links = Bahn {n}"
                          for i, n in enumerate(nummern, start=1))
    print(f"\n{zuordnung}")
    print(f"Gespeichert: {a.ausgabe}")
    print("Vor dem Ernstfall in der Oberflaeche nachsehen, ob die Rahmen "
          "sitzen -- der Rechner findet die Tafel, nicht die Wahrheit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
