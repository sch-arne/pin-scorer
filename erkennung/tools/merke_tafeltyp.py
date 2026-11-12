#!/usr/bin/env python
"""Nimmt eine kalibrierte Tafel in die Bibliothek bekannter Bauarten auf.

WOFUER

Ist eine Bauart einmal vermessen, soll das Werkzeug sie ueberall
wiedererkennen -- auch in einer fremden Halle, mit anderer Kamera und anderem
Licht. Dafuer braucht es zwei Dinge: ein Musterbild der geradegerechneten
Tafel und die ROIs darauf. Beides legt dieses Werkzeug ab.

EIN TYP IST EINE BAUART, KEINE HALLE. Dieselbe FUNK-Anlage steht in vielen
Vereinen; der Name sollte deshalb die Anlage benennen, nicht den Ort.

    .venv/Scripts/python.exe tools/merke_tafeltyp.py \
        --kalibrierung data/calibrations/Training.json --bahn 3 \
        --video debug/....mp4 --frame 3000 --name FUNK_klassisch
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration.board_library import (  # noqa: E402
    lade_bibliothek, speichere_typ)
from kegel_cv.calibration.model import Calibration  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.video.factory import open_source  # noqa: E402


def hole_frame(pfad: str, index: int, cfg):
    """Liest sequentiell bis zum gewuenschten Frame -- ohne zu springen."""
    quelle = open_source(pfad, cfg)
    quelle.open()
    bild = None
    n = 0
    try:
        while n < index:
            f = quelle.read()
            if f is None:
                break
            n += 1
            bild = f.image
    finally:
        quelle.close()
    return bild


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--video", required=True)
    p.add_argument("--frame", type=int, default=3000)
    p.add_argument("--name", required=True,
                   help="Name der BAUART, nicht der Halle")
    p.add_argument("--bahn", type=int, default=None,
                   help="welche Bahn als Muster dient (Vorgabe: die erste)")
    p.add_argument("--ordner", type=Path, default=Path("data/boardtypes"))
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = load_config()
    kal = Calibration.load(a.kalibrierung)
    if not kal.lanes:
        print("Die Kalibrierung enthaelt keine Bahn.")
        return 1

    lane_id = None
    if a.bahn is not None:
        passend = [l for l in kal.lanes
                   if a.bahn in (l.lane_id, l.display_number)]
        if not passend:
            print(f"Bahn {a.bahn} steht nicht in der Kalibrierung.")
            return 1
        lane_id = passend[0].lane_id

    bild = hole_frame(a.video, a.frame, cfg)
    if bild is None:
        print("Aus dem Video kam kein Frame.")
        return 1

    ziel = speichere_typ(a.ordner, a.name, bild, kal, lane_id)
    print(f"\nTafeltyp gespeichert: {ziel}")
    print("Bibliothek enthaelt jetzt:")
    for typ in lade_bibliothek(a.ordner):
        h, b = typ.muster.shape[:2]
        print(f"   {typ.name:<24} Muster {b}x{h} px, "
              f"{len(typ.bahn.rois)} Felder")
    print("\nWaehle als Frame ein Bild OHNE Person vor der Tafel und ohne "
          "Bewegungsunschaerfe -- ein schlechtes Muster kostet die halbe "
          "Erkennung.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
