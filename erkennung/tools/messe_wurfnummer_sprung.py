"""Schreibt die WURFNUMMER durchgehend mit -- wann springt sie, je Bahn?

WOZU (Nutzer, 2026-09-28): *„wie gut können wir auf allen Bahnen eine
Veränderung bei der Wurfnummer sehen? Denn wenn die Wurfnummer hochzählt,
beginnen die 4 sek. sonst nehmen wir das als Breakpoint und davor ist
Grundlinie und danach bis Grün aus ist Ergebnis."*

Der Anker waere damit ein EREIGNIS AUF DER TAFEL statt einer Uhr -- und die
ganze Frage „wieviele Sekunden zurueck" faellt weg. Er traegt aber nur, wenn
der Sprung zuverlaessig und zeitlich scharf zu sehen ist.

Fuer die Lampen und die gruene Lampe gibt es laengst eine Spur. Fuer die
Ziffern nicht: Sie werden nur in den zehn Frames rund um Gruen-AUS gelesen.
Aus diesen zehn laesst sich nicht sagen, WANN die Nummer gesprungen ist.

Dieses Werkzeug liest einen zusammenhaengenden Abschnitt des Videos und
schreibt je `takt` Frames fuer jede Bahn die gelesene Wurfnummer mit. Danach
wird je Gruenzyklus bestimmt, an welchem Frame sie sich erhoeht hat.

Aufruf:

    .venv/Scripts/python.exe tools/messe_wurfnummer_sprung.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45 \
        --kalibrierung data/calibrations/2Spieltag.json \
        --quelle "<stream>" --von 33000 --bis 45000
"""

from __future__ import annotations

import argparse
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
    """Was der LaneProcessor als Frame erwartet."""

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


def auswerten(spur_datei: Path, lauf: Path, von: int, bis: int, fps: float):
    zyklen = gruenzyklen(lauf)
    spur = collections.defaultdict(list)
    with spur_datei.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            spur[r["Bahn"]].append((int(r["Frame"]), r["Wurfnummer"]))

    print(f"\n{'Bahn':>4} {'Zyklen':>7} {'Sprung gesehen':>16}   "
          f"Abstand vor Gruen-AUS")
    for bahn in sorted(spur):
        reihe = sorted(spur[bahn])
        passend = [(an, aus) for an, aus in zyklen.get(bahn, [])
                   if von <= an and aus <= bis]
        if not passend:
            continue
        abstaende = []
        lesbar = 0
        for an, aus in passend:
            innen = [(fr, t) for fr, t in reihe if an <= fr <= aus]
            zahlen = [(fr, int(t)) for fr, t in innen if t.isdigit()]
            if zahlen:
                lesbar += 1
            sprung = next((f2 for (f1, n1), (f2, n2)
                           in zip(zahlen, zahlen[1:]) if n2 == n1 + 1), None)
            if sprung is not None:
                abstaende.append(aus - sprung)
        if abstaende:
            v = sorted(abstaende)
            pq = lambda q: v[min(len(v) - 1, int(len(v) * q))]
            rest = (f"Median {statistics.median(v):>4.0f} F "
                    f"({statistics.median(v)/fps:.2f} s)  "
                    f"p10 {pq(0.10):>3}  p90 {pq(0.90):>3}  "
                    f"min {v[0]:>3}  max {v[-1]:>4}")
        else:
            rest = "kein einziger Sprung gesehen"
        print(f"{bahn:>4} {len(passend):>7} {len(abstaende):>6} "
              f"{100*len(abstaende)/len(passend):>6.1f}%   {rest}")
        print(f"     (in {lesbar} von {len(passend)} Zyklen war die Nummer "
              f"ueberhaupt lesbar)")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--quelle", default="")
    p.add_argument("--von", type=int, required=True)
    p.add_argument("--bis", type=int, required=True)
    p.add_argument("--takt", type=int, default=5)
    p.add_argument("--fps", type=float, default=20.0)
    p.add_argument("--spur", type=Path,
                   default=Path("scratchpad/wurfnummernspur.csv"))
    p.add_argument("--nur-auswerten", action="store_true",
                   help="Die Spur nicht neu lesen, nur die vorhandene deuten.")
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
            datei.write("Frame;Bahn;Wurfnummer;Guete\n")
            n, gelesen = a.von, 0
            while n <= a.bis:
                ok, bild = kamera.read()
                if not ok:
                    print(f"Quelle endet bei Frame {n}")
                    break
                if (n - a.von) % a.takt:
                    n += 1
                    continue
                if not prozessoren:
                    for lane in kal.lanes:
                        pr = LaneProcessor(lane, cfg)
                        pr.prepare(bild.shape)
                        prozessoren[lane.real_lane_number or lane.lane_id] = pr
                rahmen = Bild(bild, n, a.fps)
                for bahn, pr in prozessoren.items():
                    lesung = pr.read_digits(rahmen).get("throw_number")
                    datei.write(f"{n};{bahn};"
                                f"{lesung.text if lesung else ''};"
                                f"{lesung.confidence if lesung else 0:.2f}\n")
                gelesen += 1
                if gelesen % 200 == 0:
                    print(f"  Frame {n} ({gelesen} Messpunkte)", flush=True)
                n += 1
        kamera.release()
        print(f"\nSpur: {a.spur} ({gelesen} Messpunkte je Bahn)")

    auswerten(a.spur, a.lauf, a.von, a.bis, a.fps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
