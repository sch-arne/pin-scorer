"""Misst, ob ein Ziffernfeld wirklich auf seiner Stelle sitzt.

WOZU (Nutzer, 2026-09-29): *"okay, dann miss das mal, vielleicht habe ich da
den Frame auch schlecht gesetzt."*

Auf Bahn 4 liest der Ziffernleser die Kegelzahl neunmal als `3`, wo die Tafel
etwas anderes zeigt -- siebenmal eine `7`, zweimal eine `1`:

    Frame 204625   Tafel 001 | 7 | 0000    gelesen 3
    Frame  35111   Tafel 030 | 1 | 0188    gelesen 3

Beide Male wird eine SEGMENTARME Ziffer zu einer 3. Eine `7` sind drei
Segmente (abc), eine `1` zwei (bc), eine `3` fuenf (abcdg). Der Leser sieht
also Segmente, die nicht leuchten -- das Bild eines Rahmens, der zu gross ist
oder zu weit sitzt und Streulicht der Nachbarstellen mitnimmt.

DAS MASS, ohne das jede Verschiebung geraten waere: die TAFELSUMME. Es gilt
`SummeTafel(N+1) - SummeTafel(N) = Kegelzahl von Wurf N`. Dieser Zeuge weiss
nichts von den Lampen und nichts vom Ziffernleser -- er kommt aus einem
anderen Feld derselben Tafel. Fuer jede probeweise Verschiebung wird gezaehlt,
wie oft die gelesene Ziffer mit ihm uebereinstimmt.

    (`tools/fit_digit_offsets.py` misst die MEHRSTELLIGEN Felder an ihrer
    fuehrenden Null. Die Kegelzahl ist einstellig, dort greift das nicht.)

Gemessen wird auf den Tafelbildern, die der Lauf ohnehin gespeichert hat
(`lane_N/event_*/…_tafel.png`) -- kein Sprung in die Quelle noetig.

Aufruf:

    .venv/Scripts/python.exe tools/messe_ziffernversatz.py \
        --lauf debug/Vorstand-Grundlinie/lauf_2026-09-29_13-52-42 \
        --kalibrierung data/calibrations/2Spieltag_neu.json
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, "src")

from kegel_cv.analysis.lane_processor import LaneProcessor      # noqa: E402
from kegel_cv.calibration.model import Calibration              # noqa: E402
from kegel_cv.config import load_config                         # noqa: E402

TAFEL_RAND = 8          # wie `messe_lampenversatz.py` und der Frame-Logger
FRAME_IM_NAMEN = re.compile(r"frame_(\d+)")


def sollwerte(lauf: Path) -> dict[tuple[str, int], int]:
    """(Bahn, Frame) -> Kegelzahl laut Tafelsumme."""
    nach: dict[str, list] = collections.defaultdict(list)
    with (lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            nach[r["Bahn"]].append(r)
    soll: dict[tuple[str, int], int] = {}
    for bahn, reihe in nach.items():
        reihe.sort(key=lambda r: int(r["Frame"]))
        for r, n in zip(reihe, reihe[1:]):
            if r["Spiel"] != n["Spiel"]:
                continue
            try:
                d = int(n["SummeTafel"]) - int(r["SummeTafel"])
            except (TypeError, ValueError):
                continue
            if 0 <= d <= 9:
                soll[(bahn, int(r["Frame"]))] = d
    return soll


def ecke(lane) -> tuple[int, int]:
    """Linke obere Ecke des gespeicherten Tafelbildes im Vollframe."""
    xs = [p[0] for p in lane.quad]
    ys = [p[1] for p in lane.quad]
    return (max(0, int(min(xs)) - TAFEL_RAND),
            max(0, int(min(ys)) - TAFEL_RAND))


def lies(prozessor: LaneProcessor, bild: np.ndarray, boxen: list,
         x0: int, y0: int, dx: int, dy: int):
    """Liest ein Ziffernfeld aus dem Tafelbild mit verschobenem Rahmen."""
    h, w = bild.shape[:2]
    ausschnitte = []
    for bx, by, bw, bh in boxen:
        xx, yy = bx - x0 + dx, by - y0 + dy
        if xx < 0 or yy < 0 or xx + bw > w or yy + bh > h:
            return None
        ausschnitte.append(bild[yy:yy + bh, xx:xx + bw])
    lesung = prozessor.digit_reader.read_field(ausschnitte)
    return getattr(lesung, "value", None)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--feld", default="pin_count")
    p.add_argument("--radius", type=int, default=3)
    p.add_argument("--bahnen", default="",
                   help="nur diese Bahnen, z.B. 4 oder 2,4")
    a = p.parse_args()

    cfg = load_config()
    kal = Calibration.load(str(a.kalibrierung))
    soll = sollwerte(a.lauf)
    nur = {int(x) for x in a.bahnen.split(",") if x.strip()} if a.bahnen else None
    versatz = range(-a.radius, a.radius + 1)

    for lane in sorted(kal.lanes, key=lambda x: x.real_lane_number or x.lane_id):
        bahn = lane.real_lane_number or lane.lane_id
        if nur is not None and bahn not in nur:
            continue
        prozessor = LaneProcessor(lane, cfg)
        if not prozessor.prepare((1080, 1920, 3)):
            print(f"Bahn {bahn}: Kalibrierung nicht vorbereitbar")
            continue
        boxen = prozessor._digit_cell_boxes.get(a.feld)
        if not boxen:
            print(f"Bahn {bahn}: Feld {a.feld} nicht stellenweise eingerahmt")
            continue
        x0, y0 = ecke(lane)

        # Je Ereignis: alle gespeicherten Tafelbilder und der Sollwert.
        faelle = []
        for ordner in sorted((a.lauf / f"lane_{lane.lane_id}").glob("event_*")):
            datei = ordner / "event.json"
            if not datei.is_file():
                continue
            try:
                ausloeser = json.loads(datei.read_text())["trigger_frame"]
            except (OSError, ValueError, KeyError):
                continue
            treffer = [(abs(fr - ausloeser), fr) for (b, fr) in soll
                       if b == str(bahn) and abs(fr - ausloeser) <= 120]
            if not treffer:
                continue
            wahr = soll[(str(bahn), min(treffer)[1])]
            bilder = [cv2.imread(str(x))
                      for x in sorted(ordner.glob("*_tafel.png"))]
            bilder = [b for b in bilder if b is not None]
            if bilder:
                faelle.append((bilder, wahr))
        if not faelle:
            print(f"Bahn {bahn}: keine Ereignisse mit Tafelsumme")
            continue

        ergebnis: dict[tuple[int, int], int] = {}
        verwechslung: dict[tuple[int, int], collections.Counter] = {}
        for dy in versatz:
            for dx in versatz:
                richtig = 0
                paare: collections.Counter = collections.Counter()
                for bilder, wahr in faelle:
                    stimmen = collections.Counter(
                        v for v in (lies(prozessor, b, boxen, x0, y0, dx, dy)
                                    for b in bilder) if v is not None)
                    if not stimmen:
                        continue
                    gelesen = stimmen.most_common(1)[0][0]
                    try:
                        zahl = int(gelesen)
                    except (TypeError, ValueError):
                        continue
                    if zahl == wahr:
                        richtig += 1
                    else:
                        paare[(wahr, zahl)] += 1
                ergebnis[(dx, dy)] = richtig
                verwechslung[(dx, dy)] = paare

        hier = ergebnis.get((0, 0), 0)
        best, wert = max(ergebnis.items(), key=lambda kv: kv[1])
        print(f"\n=== Bahn {bahn}, Feld {a.feld} "
              f"({len(faelle)} Wuerfe mit Tafelsumme) ===")
        kopf = "dy\\dx " + "".join(f"{d:>6}" for d in versatz)
        print(kopf)
        for dy in versatz:
            zeile = "".join(f"{ergebnis[(dx, dy)]:>6}" for dx in versatz)
            print(f"{dy:>5} {zeile}")
        print(f"\nheute (0,0): {hier} von {len(faelle)} "
              f"({hier / max(1, len(faelle)):.1%})")
        print(f"bester Versatz {best}: {wert} "
              f"({wert / max(1, len(faelle)):.1%}), {wert - hier:+d}")
        for schluessel, name in (((0, 0), "heute"), (best, "dort")):
            haeufig = verwechslung[schluessel].most_common(5)
            if haeufig:
                print(f"  haeufigste Verwechslungen {name}: " + ", ".join(
                    f"{w} gelesen als {g} ({n}x)" for (w, g), n in haeufig))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
