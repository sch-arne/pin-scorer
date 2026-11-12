"""Woran genau scheitert die Ziffernerkennung? Ursache fuer Ursache.

WOZU: Bekannt war nur die Trefferquote. Die sagt nicht, WO der Weg abbricht --
und ohne das laesst sich nicht entscheiden, ob eine Schranke falsch steht oder
ob der Erkenner selbst nicht taugt. Der Nutzer hat am Bildbeleg zu F40903
darauf hingewiesen, dass die Ziffern in der Rotmaske eindeutig lesbar sind und
die Erkennung sie trotzdem verwirft.

Der Weg einer Ziffer hat vier Stellen, an denen er enden kann:

    1. HELLIGKEITSSPERRE   95. Perzentil des Rotkanals < min_display_brightness
                           -> "die Anzeige ist dunkel"
    2. LEERE MASKE         die Rotmaske findet keinen einzigen Pixel
    3. MEHRDEUTIG          ein Segment liegt so nah an der Schwelle, dass sein
                           Umkippen eine ANDERE gueltige Ziffer ergaebe
    4. KEIN MUSTER         die aktiven Segmente ergeben kein bekanntes Muster,
                           und das naechstliegende ist mehr als ein Segment weg

Zusaetzlich wird gezaehlt, ob in der Zelle ueberhaupt etwas leuchtet -- daran
entscheidet sich, ob ein "?" richtig oder falsch ist. Als Kriterium dient das
MAXIMUM des Rotkanals: gemessen ueber 4800 Zellen erreicht eine dunkle Zelle
114-119, eine leuchtende 246-255. Dazwischen liegt eine Luecke von ueber 120
Punkten, waehrend das 95. Perzentil dort 24,9 % aller Zellen ablegt.

Das Werkzeug entscheidet nichts. Es sagt nur, an welcher der vier Stellen wie
viel verloren geht.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration  # noqa: E402
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.detection.digit_detector import SevenSegmentDetector  # noqa: E402
from kegel_cv.detection.digit_reader import (  # noqa: E402
    CELL_HEIGHT, CELL_WIDTH, SEGMENT_ORDER, SEGMENT_PATTERNS,
    CalibratedDigitReader, segment_candidates, segment_regions)

FELDER = ("throw_number", "pin_count", "total_a", "total_b", "left_display")
# Ab hier gilt eine Zelle als beleuchtet. Gemessen: dunkel 114-119,
# leuchtend 246-255.
LEUCHTET_AB = 200


def ursache(patch: np.ndarray, leser: CalibratedDigitReader,
            vor: SevenSegmentDetector, regionen: dict,
            min_hell: int) -> tuple[str, str]:
    """(Ursache, gelesenes Zeichen) fuer eine einzelne Zelle."""
    if patch is None or patch.size == 0:
        return "leerer Ausschnitt", "?"

    if np.percentile(patch[:, :, 2], 95) < min_hell:
        return "Helligkeitssperre", "?"

    maske = vor._red_mask(patch)
    if maske.max() == 0:
        return "leere Maske", "?"

    beschnitten = vor._trim_vertical(maske)
    if beschnitten.size and beschnitten.max() > 0:
        maske = beschnitten
    zelle = cv2.resize(maske, (CELL_WIDTH, CELL_HEIGHT),
                       interpolation=cv2.INTER_AREA)

    fuellungen = []
    for name in SEGMENT_ORDER:
        x, y, w, h = regionen[name]
        bereich = zelle[y:y + h, x:x + w]
        fuellungen.append(float(bereich.mean() / 255.0) if bereich.size else 0.0)

    schwelle = leser._threshold(fuellungen)
    aktiv = tuple(f >= schwelle for f in fuellungen)
    kandidaten = segment_candidates(fuellungen, schwelle,
                                    leser.cfg.segment_ambiguous_band)
    if len(kandidaten) > 1:
        return "mehrdeutig", "?"

    ziffer = SEGMENT_PATTERNS.get(aktiv)
    if ziffer is not None:
        return "gelesen", str(ziffer)

    abstand = min(sum(1 for p, a in zip(muster, aktiv) if p != a)
                  for muster in SEGMENT_PATTERNS)
    if abstand > 1:
        return "kein Muster", "?"
    return "gelesen (geraten)", "?"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--blocks", default="40000,120000,200000,280000",
                   help="Startframes der Bloecke, mit Komma getrennt")
    p.add_argument("--block-length", type=int, default=600)
    p.add_argument("--every", type=int, default=20,
                   help="nur jeden n-ten Frame auswerten")
    a = p.parse_args()

    cal = Calibration.load(a.calibration)
    cfg = load_config()
    leser = CalibratedDigitReader(cfg.detection.digits)
    vor = SevenSegmentDetector(cfg.detection.digits)
    regionen = segment_regions()
    min_hell = cfg.detection.digits.min_display_brightness

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 20000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 15000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")

    # Getrennt gezaehlt nach der einzigen Frage, die zaehlt: leuchtet in der
    # Zelle etwas? Ein "?" auf einer dunklen Zelle ist richtig.
    hell: collections.Counter[str] = collections.Counter()
    dunkel: collections.Counter[str] = collections.Counter()
    je_feld: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter)
    tfs: dict[int, object] = {}

    for start in (int(x) for x in a.blocks.split(",")):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(start))
        for k in range(a.block_length):
            ok, bild = cap.read()
            if not ok:
                break
            if k % a.every:
                continue
            for lane in cal.lanes:
                if lane.display_number not in tfs:
                    tfs[lane.display_number] = lane.transform(bild.shape[1],
                                                             bild.shape[0])
                tf = tfs[lane.display_number]
                for feld in FELDER:
                    for zelle in lane.digit_rois(feld):
                        bx, by, bw, bh = norm_rect_to_frame_bbox(
                            tf, zelle.rect, bild.shape)
                        patch = bild[by:by + bh, bx:bx + bw]
                        if patch.size == 0:
                            continue
                        grund, _ = ursache(patch, leser, vor, regionen, min_hell)
                        if int(patch[:, :, 2].max()) >= LEUCHTET_AB:
                            hell[grund] += 1
                            je_feld[feld][grund] += 1
                        else:
                            dunkel[grund] += 1
    cap.release()

    gesamt_hell = sum(hell.values())
    gesamt_dunkel = sum(dunkel.values())
    print(f"{gesamt_hell + gesamt_dunkel} Ziffernzellen: "
          f"{gesamt_hell} beleuchtet, {gesamt_dunkel} dunkel\n")

    print("BELEUCHTETE ZELLEN -- hier gehoert eine Ziffer gelesen:")
    for grund, n in hell.most_common():
        print(f"   {grund:<22} {n:6d}  {n / max(1, gesamt_hell):6.1%}")
    print("\nDUNKLE ZELLEN -- hier ist '?' die richtige Antwort:")
    for grund, n in dunkel.most_common():
        print(f"   {grund:<22} {n:6d}  {n / max(1, gesamt_dunkel):6.1%}")

    print("\nJe Feld, nur beleuchtete Zellen:")
    print(f"   {'Feld':<15} {'gelesen':>8} {'Sperre':>8} {'mehrdeut':>9} "
          f"{'kein Mst':>9} {'sonst':>7}")
    for feld in FELDER:
        c = je_feld[feld]
        summe = sum(c.values())
        if not summe:
            continue
        sonst = summe - (c["gelesen"] + c["Helligkeitssperre"]
                         + c["mehrdeutig"] + c["kein Muster"])
        print(f"   {feld:<15} {c['gelesen'] / summe:7.1%} "
              f"{c['Helligkeitssperre'] / summe:7.1%} "
              f"{c['mehrdeutig'] / summe:8.1%} {c['kein Muster'] / summe:8.1%} "
              f"{sonst / summe:6.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
