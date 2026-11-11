"""Wurfnummer UND Lampen jeden Frame -- wie genau liegt der Sprung?

WOZU (Nutzer, 2026-09-28): *„miss das bitte genau, denn das ist ein
Frameproblem. Physikalisch ist es nicht möglich, dass der Wurfzähler hochgeht,
nachdem ein Kegel fällt.... Weil wenn die Kugel die hälfte der Bahn
überschreitet, steigt der Wurfzähler. Da ist noch weit kein Kegel in der
Nähe."*

Damit ist die Reihenfolge physikalisch festgelegt: erst der Sprung, dann die
Kegel. Eine Messung, die etwas anderes zeigt, ist falsch.

Und die bisherige Messung KONNTE es nicht zeigen: Ihre Spur hatte einen Takt
von fuenf Frames, und der gemessene Abstand betrug im Median genau fuenf
Frames. Das ist die Aufloesungsgrenze, kein Befund.

Hier wird deshalb JEDER Frame gelesen -- Wurfnummer und Kegellampen zugleich,
damit beide aus demselben Bild stammen. Nur ueber einen kurzen Abschnitt; das
ist teuer (rund 7 ms je Frame und Bahn) und fuer einen Lauf nicht tragbar,
fuer eine Messung schon.

Aufruf:

    .venv/Scripts/python.exe tools/messe_sprung_genau.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45 \
        --kalibrierung data/calibrations/2Spieltag.json \
        --quelle "<stream>" --von 14000 --bis 16000
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
import statistics
import sys
from pathlib import Path

import cv2

sys.path.insert(0, "src")

from kegel_cv.analysis.lane_processor import LaneProcessor      # noqa: E402
from kegel_cv.calibration.model import Calibration              # noqa: E402
from kegel_cv.config import load_config                         # noqa: E402


class Bild:
    def __init__(self, bild, index: int, fps: float) -> None:
        self.image, self.index, self.timestamp = bild, index, index / fps


def gruenzyklen(lauf: Path):
    folge = collections.defaultdict(list)
    with (lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            folge[r["Bahn"]].append((int(r["Frame"]), r["Zustand"]))
    zyklen = collections.defaultdict(list)
    for bahn, reihe in folge.items():
        reihe.sort()
        an = vor = None
        for frame, zustand in reihe:
            if zustand == "ON" and vor != "ON":
                an = frame
            elif zustand == "OFF" and vor == "ON" and an is not None:
                zyklen[bahn].append((an, frame))
                an = None
            if zustand in ("ON", "OFF"):
                vor = zustand
    return zyklen


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--quelle", default="")
    p.add_argument("--von", type=int, required=True)
    p.add_argument("--bis", type=int, required=True)
    p.add_argument("--fps", type=float, default=20.0)
    p.add_argument("--spur", type=Path,
                   default=Path("scratchpad/sprung_genau.csv"))
    p.add_argument("--nur-auswerten", action="store_true")
    a = p.parse_args()

    if not a.nur_auswerten:
        cfg = load_config()
        kal = Calibration.load(str(a.kalibrierung))
        kamera = cv2.VideoCapture(a.quelle)
        if not kamera.isOpened():
            raise SystemExit("Quelle nicht zu oeffnen")
        kamera.set(cv2.CAP_PROP_POS_FRAMES, a.von)
        prozessoren: dict[int, LaneProcessor] = {}
        a.spur.parent.mkdir(parents=True, exist_ok=True)
        with a.spur.open("w", encoding="utf-8-sig", newline="") as datei:
            datei.write("Frame;Bahn;Wurfnummer;Guete;Lampen\n")
            n = a.von
            while n <= a.bis:
                ok, bild = kamera.read()
                if not ok:
                    break
                if not prozessoren:
                    for lane in kal.lanes:
                        pr = LaneProcessor(lane, cfg)
                        pr.prepare(bild.shape)
                        prozessoren[lane.real_lane_number or lane.lane_id] = pr
                rahmen = Bild(bild, n, a.fps)
                for bahn, pr in prozessoren.items():
                    z = pr.read_digits(rahmen, felder=("throw_number",)).get(
                        "throw_number")
                    lampen = pr._read_pin_lamps(rahmen)
                    an = " ".join(str(x) for x in sorted(lampen.pins)) if lampen else ""
                    datei.write(f"{n};{bahn};{z.text if z else ''};"
                                f"{z.confidence if z else 0:.2f};{an}\n")
                if (n - a.von) % 200 == 0:
                    print(f"  Frame {n}", flush=True)
                n += 1
        kamera.release()
        print(f"\nSpur: {a.spur}")

    # --- Auswertung ---
    zyklen = gruenzyklen(a.lauf)
    spur = collections.defaultdict(list)
    with a.spur.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            spur[r["Bahn"]].append(
                (int(r["Frame"]), r["Wurfnummer"], float(r["Guete"]),
                 frozenset(int(x) for x in r["Lampen"].split())))

    print(f"\nSprung MINUS erste Lampenaenderung, jeder Frame gelesen")
    print(f"{'Bahn':>4} {'Zyklen':>7} {'Median':>7} {'min':>6} {'max':>6} "
          f"{'Nummer zuerst':>14}")
    alle = []
    einzeln = []
    for bahn in sorted(spur):
        reihe = sorted(spur[bahn])
        werte = []
        for an, aus in zyklen.get(bahn, []):
            if an < a.von or aus > a.bis:
                continue
            innen = [x for x in reihe if an <= x[0] <= aus]
            if len(innen) < 10:
                continue
            basis = innen[0][3]
            regung = next((fr for fr, _, _, pins in innen if pins - basis), None)
            zahlen = [(fr, int(t)) for fr, t, g, _ in innen if t.isdigit()]
            sprung = next((f2 for (f1, n1), (f2, n2)
                           in zip(zahlen, zahlen[1:]) if n2 == n1 + 1), None)
            if regung is None or sprung is None:
                continue
            werte.append(sprung - regung)
            einzeln.append((bahn, aus, sprung, regung, sprung - regung))
        if not werte:
            continue
        alle += werte
        v = sorted(werte)
        n = sum(1 for x in v if x < 0)
        print(f"{bahn:>4} {len(v):>7} {statistics.median(v):>7.0f} {v[0]:>6} "
              f"{v[-1]:>6} {n:>5} {100*n/len(v):>6.0f}%")
    if alle:
        v = sorted(alle)
        n = sum(1 for x in v if x < 0)
        print(f"\ngesamt {len(v)} Zyklen: Median {statistics.median(v):.0f} Frames "
              f"({statistics.median(v)/a.fps:.2f} s), "
              f"Nummer zuerst in {n} ({100*n/len(v):.0f} %)")
        print("\nDie Faelle, in denen die Lampe zuerst kam:")
        for bahn, aus, s, r, d in sorted(einzeln, key=lambda x: -x[4])[:10]:
            if d >= 0:
                print(f"  Bahn {bahn} Gruen-AUS {aus}: Sprung {s}, "
                      f"Lampe {r}, Abstand {d:+d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
