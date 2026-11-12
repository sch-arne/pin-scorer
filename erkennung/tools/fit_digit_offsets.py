"""Findet je Bahn und Ziffernfeld die beste waagerechte Verschiebung der ROIs.

WOZU -- gemessen am 2026-08-31: Auf Bahn 4 wurde die fuehrende Stelle des
Summenfeldes als "3" gelesen, wo die Tafel eine "0" zeigte. Ueber den vollen
Spieltag betraf das 37 von 234 lesbaren Summen (16 %), und es kostete die
Erkennung von acht Spielenden: Die Pruefung auf `000 0000` verlangt eine Summe
von null, gelesen wurde aber `3000`.

    Bahn 4   a=0.99 b=0.76 c=0.74 d=0.88 e=0.21 f=0.20 g=0.23  -> "3"

Eine "0" ist abcdef. Fehlen die linken Segmente e und f, bleibt abcd --
naechstliegend die "3". Fehlt zusaetzlich d, bleibt abc: genau die "7". Beide
beobachteten Fehlwerte sind dieselbe abgeschnittene Null.

DAS MASS, ohne das jede Verschiebung geraten waere: **Die fuehrende Stelle
eines mehrstelligen Feldes ist auf dieser Tafel immer null.**

    throw_number   001 .. 030      -> erste Stelle 0
    total_a/b      0 .. 270        -> erste Stelle 0 (1000 Kegel braeuchten
                                      112 Wuerfe)
    left_display   00 .. 0x        -> erste Stelle 0

Eine von null verschiedene fuehrende Stelle ist damit nachweislich falsch --
ohne dass man den wahren Wert kennen muss. Das ist ein objektives Guetemass,
das sich ueber tausende Frames auswerten laesst.

GEGENPROBE, warum NICHT die linke Kante verbreitert wird: Leerraum links
schiebt die Ziffer beim Normieren auf die 24x40-Zelle nach rechts, und die
geometrischen Segmentflaechen sammeln dann Zwischenraum ein. Gemessen wurde die
Trefferquote dadurch schlechter, nicht besser. `_trim_vertical` schneidet nur
senkrecht zu, nicht waagerecht -- mit gutem Grund, denn eine "1" nutzt die
Zellenbreite nicht aus.

Das Werkzeug aendert nichts. Es sagt nur, welche Verschiebung sich lohnt.
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
from kegel_cv.detection.digit_reader import CalibratedDigitReader  # noqa: E402

# Nur mehrstellige Felder -- bei einer einzelnen Stelle gibt es keine
# fuehrende Null, an der sich etwas ablesen liesse.
FELDER = ("throw_number", "total_a", "total_b", "left_display")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True, help="reale Bahnnummer")
    p.add_argument("--from-frame", type=int, required=True)
    p.add_argument("--to-frame", type=int, required=True)
    p.add_argument("--every", type=int, default=25)
    p.add_argument("--steps", default="-0.002,0,0.002,0.004,0.006,0.008")
    a = p.parse_args()

    cal = Calibration.load(a.calibration)
    lane = next((l for l in cal.lanes if l.display_number == a.lane), None)
    if lane is None:
        raise SystemExit(f"Bahn {a.lane} nicht in der Kalibrierung")
    leser = CalibratedDigitReader(load_config().detection.digits)
    schritte = [float(x) for x in a.steps.split(",")]

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 20000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 15000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")
    cap.set(cv2.CAP_PROP_POS_FRAMES, float(a.from_frame))

    # [feld][schritt] -> (lesbar, fuehrende Stelle nicht null)
    lesbar: dict = collections.defaultdict(lambda: collections.defaultdict(int))
    falsch: dict = collections.defaultdict(lambda: collections.defaultdict(int))
    versuche = 0
    tf = None
    n = a.from_frame
    while n <= a.to_frame:
        ok, bild = cap.read()
        if not ok:
            break
        if (n - a.from_frame) % a.every == 0:
            if tf is None:
                tf = lane.transform(bild.shape[1], bild.shape[0])
            versuche += 1
            for feld in FELDER:
                zellen = lane.digit_rois(feld)
                if len(zellen) < 2:
                    continue
                for s in schritte:
                    stuecke = []
                    for z in zellen:
                        x, y, w, h = z.rect
                        bx, by, bw, bh = norm_rect_to_frame_bbox(
                            tf, (x + s, y, w, h), bild.shape)
                        stuecke.append(bild[by:by + bh, bx:bx + bw])
                    lesung = leser.read_field(stuecke)
                    if not lesung.is_readable:
                        continue
                    lesbar[feld][s] += 1
                    if lesung.text[0] != "0":
                        falsch[feld][s] += 1
        n += 1
    cap.release()

    print(f"Bahn {a.lane}, {versuche} Frames (F{a.from_frame}-F{a.to_frame})")
    print("Mass: Anteil der Lesungen, deren FUEHRENDE STELLE nicht null ist.")
    print("Auf dieser Tafel ist sie immer null -- alles andere ist falsch.\n")
    empfehlung = {}
    for feld in FELDER:
        if feld not in lesbar:
            continue
        print(f"  {feld}")
        print(f"    {'Verschiebung':>13} {'lesbar':>9} {'erste Stelle != 0':>19}")
        bester, beste_quote = None, None
        for s in schritte:
            n_les = lesbar[feld][s]
            if not n_les:
                print(f"    {s:>13.3f} {0:>8}% {'--':>19}")
                continue
            quote = falsch[feld][s] / n_les
            anteil_lesbar = n_les / max(1, versuche)
            print(f"    {s:>13.3f} {anteil_lesbar:>8.0%} {quote:>18.0%}")
            # Bester Wert: zuerst wenig Falsches, dann viel Lesbares.
            schluessel = (round(quote, 3), -round(anteil_lesbar, 3))
            if beste_quote is None or schluessel < beste_quote:
                bester, beste_quote = s, schluessel
        empfehlung[feld] = bester
        print(f"    -> empfohlen: {bester:+.3f}\n")

    print("Zusammenfassung Bahn %d -- Anteil falscher fuehrender Stelle:" % a.lane)
    print(f"  {'Feld':<15} {'heute':>8} {'empfohlen':>11} {'dort':>8}  Urteil")
    for feld, s in empfehlung.items():
        n0 = lesbar[feld].get(0.0, 0)
        heute = falsch[feld].get(0.0, 0) / n0 if n0 else float("nan")
        nb = lesbar[feld][s]
        dort = falsch[feld][s] / nb if nb else float("nan")
        # Nur wo heute nachweislich Schaden entsteht, lohnt eine Aenderung.
        urteil = "AENDERN" if (heute == heute and heute > 0.02
                               and dort < heute - 0.02) else "lassen"
        print(f"  {feld:<15} {heute:>7.0%} {s:>+11.3f} {dort:>7.0%}  {urteil}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
