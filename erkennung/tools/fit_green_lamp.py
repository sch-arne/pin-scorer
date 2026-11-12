"""Sucht die beste Lage der Gruenlampen-ROI -- am Bild gemessen, nicht geraten.

WOZU: Am 2026-08-30 zeigte Bahn 5 nur den halben Kontrast der anderen Bahnen
(Abstand zwischen AN und AUS: +13,4 gegen +27,5 auf Bahn 2). Die Folge waren
sechs Scheinzyklen von unter einer Sekunde -- Rauschen, das die Schwelle
kreuzte -- und drei Protokollsaetze, die sich nicht mehr zuordnen liessen.

DAS KRITERIUM IST NICHT DER SCORE, SONDERN DER KONTRAST. Eine ROI, die einen
hohen Wert liefert, aber im dunklen Zustand ebenso, ist wertlos. Gesucht ist
die Lage, bei der AN und AUS am weitesten auseinanderliegen -- das ist genau
die Groesse, an der die Zustandsmaschine scheitert oder nicht.

Die Referenzframes kommen aus der Gruenspur eines echten Laufs: Frames, die
dort mit klarem Abstand als ON bzw. OFF gefuehrt wurden. Damit misst das
Werkzeug gegen belegte Zustaende und nicht gegen die eigene Vermutung.

Aufruf:
    .venv/Scripts/python.exe tools/fit_green_lamp.py \
        --source "https://.../rendition.m3u8?..." \
        --calibration data/calibrations/1Spieltag.json \
        --run debug/.../lauf_2026-08-30_10-56-21 --lane 5
"""

from __future__ import annotations

import argparse
import collections
import csv
import random
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.calibration import Calibration
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox
from kegel_cv.config import load_config
from kegel_cv.detection.lamp_detectors import HsvGreenDetector

# Wie viele Referenzframes je Zustand. Mehr ist genauer, aber jeder Frame
# kostet einen Sprung im Stream.
FRAMES_JE_ZUSTAND = 12
# Suchraster in Tafelkoordinaten (0..1). 0.004 entspricht etwa einem halben
# Pixel im Originalbild -- feiner waere Scheingenauigkeit.
SCHRITT = 0.004
SCHRITTE = 5          # -5..+5 -> +-2,7 px
# Groessenvarianten, relativ zur bisherigen Kantenlaenge
GROESSEN = (0.8, 1.0, 1.25, 1.5)


def referenzframes(run: Path, lane: int) -> tuple[list[int], list[int], list[int]]:
    """Frames mit belegtem Zustand aus der Gruenspur eines Laufs.

    WARUM NICHT DIE KLARSTEN FAELLE: Der erste Anlauf nahm die hoechsten ON-
    und niedrigsten OFF-Werte. Das ergab einen Kontrast von +74, waehrend der
    Lauf real +13 zeigte -- gemessen wurde an Faellen, die ohnehin nie ein
    Problem waren. Entschieden wird die Sache aber an den SCHWACHEN ON-Phasen:
    dort kreuzt das Rauschen die Schwelle und erzeugt Scheinzyklen.

    Deshalb drei Mengen: ein repraesentatives ON-Sample, ein repraesentatives
    OFF-Sample, und getrennt davon die schwaechsten ON-Frames als Haerteprobe.
    """
    an, aus = [], []
    with (run / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            if int(r["Bahn"]) != lane:
                continue
            wert = (float(r["Score"]), int(r["Frame"]))
            if r["Zustand"] == "ON":
                an.append(wert)
            elif r["Zustand"] == "OFF":
                aus.append(wert)
    random.seed(1)
    hell = random.sample(an, min(FRAMES_JE_ZUSTAND, len(an)))
    dunkel = random.sample(aus, min(FRAMES_JE_ZUSTAND, len(aus)))
    # Haerteprobe: die schwaechsten ON-Frames, gestreut statt am Stueck
    schwach = random.sample(sorted(an)[:400], min(FRAMES_JE_ZUSTAND, 400))
    return (sorted(f for _, f in hell), sorted(f for _, f in dunkel),
            sorted(f for _, f in schwach))


def hole_frames(quelle: str, nummern: list[int]) -> dict[int, np.ndarray]:
    cap = cv2.VideoCapture()
    cap.open(quelle, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 15000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 10000])
    if not cap.isOpened():
        raise SystemExit(f"Quelle nicht erreichbar: {quelle}")
    bilder = {}
    for n in nummern:
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(n))
        ok, bild = cap.read()
        if ok and bild is not None:
            bilder[n] = bild
    cap.release()
    return bilder


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True,
                   help="Bahnnummer wie in der Ausgabe (display_number)")
    a = p.parse_args()

    cfg = load_config()
    cal = Calibration.load(a.calibration)
    lane = next((l for l in cal.lanes if l.display_number == a.lane), None)
    if lane is None:
        raise SystemExit(f"Bahn {a.lane} nicht in der Kalibrierung")
    roi = lane.get_roi("green_lamp")
    if roi is None:
        raise SystemExit("Diese Bahn hat keine green_lamp-ROI")

    an, aus, schwach = referenzframes(a.run, a.lane)
    print(f"Referenzframes: {len(an)} GRUEN, {len(aus)} DUNKEL, "
          f"{len(schwach)} SCHWACH-GRUEN (Haerteprobe)")
    bilder = hole_frames(a.source, sorted(set(an + aus + schwach)))
    print(f"Geladen: {len(bilder)}\n")
    an = [f for f in an if f in bilder]
    aus = [f for f in aus if f in bilder]
    schwach = [f for f in schwach if f in bilder]
    if not an or not aus or not schwach:
        raise SystemExit("Zu wenige Frames geladen")

    erstes = bilder[an[0]]
    tf = lane.transform(erstes.shape[1], erstes.shape[0])
    det = HsvGreenDetector(cfg.detection.green)
    x0, y0, w0, h0 = roi.rect

    def messe(rect) -> tuple[float, float, float, float]:
        """(Kontrast der Haerteprobe, ON-Median, OFF-Median, SCHWACH-Median).

        Bewertet wird der Abstand zwischen den SCHWAECHSTEN ON-Frames und den
        OFF-Frames. Das ist die Groesse, an der die Zustandsmaschine kippt --
        der Abstand der klaren Faelle sagt darueber nichts.
        """
        werte = {}
        for name, liste in (("an", an), ("aus", aus), ("schwach", schwach)):
            s = []
            for f in liste:
                bx, by, bw, bh = norm_rect_to_frame_bbox(
                    tf, rect, bilder[f].shape)
                if bw <= 0 or bh <= 0:
                    return (-999.0, 0.0, 0.0, 0.0)
                s.append(det.score(bilder[f][by:by + bh, bx:bx + bw]))
            s.sort()
            werte[name] = s[len(s) // 2]
        return (werte["schwach"] - werte["aus"],
                werte["an"], werte["aus"], werte["schwach"])

    kontrast = messe
    jetzt = messe(roi.rect)
    print(f"BISHER   x={x0:.4f} y={y0:.4f} w={w0:.4f} h={h0:.4f}")
    print(f"         AN {jetzt[1]:5.1f}  AUS {jetzt[2]:5.1f}  "
          f"SCHWACH {jetzt[3]:5.1f}")
    print(f"         -> KRITISCHER ABSTAND (schwach - aus) {jetzt[0]:+6.1f}\n")

    ergebnisse = []
    for fw in GROESSEN:
        for fh in GROESSEN:
            w, h = w0 * fw, h0 * fh
            # Um denselben Mittelpunkt herum variieren
            cx, cy = x0 + w0 / 2, y0 + h0 / 2
            for dx in range(-SCHRITTE, SCHRITTE + 1):
                for dy in range(-SCHRITTE, SCHRITTE + 1):
                    rect = (cx - w / 2 + dx * SCHRITT,
                            cy - h / 2 + dy * SCHRITT, w, h)
                    k, sa, so, ss = messe(rect)
                    ergebnisse.append((k, sa, so, ss, rect, dx, dy, fw, fh))

    ergebnisse.sort(reverse=True)
    print("Die 10 besten Lagen (sortiert nach kritischem Abstand):")
    print(f"  {'kritisch':>9} {'AN':>6} {'AUS':>6} {'SCHWACH':>8}  "
          f"{'dx':>3} {'dy':>3} {'x Breite':>9} {'x Hoehe':>8}")
    for k, sa, so, ss, rect, dx, dy, fw, fh in ergebnisse[:10]:
        print(f"  {k:+9.1f} {sa:6.1f} {so:6.1f} {ss:8.1f}  {dx:>3} {dy:>3} "
              f"{fw:>9.2f} {fh:>8.2f}")

    best = ergebnisse[0]
    print(f"\nBESTE LAGE: kritischer Abstand {best[0]:+.1f} statt "
          f"{jetzt[0]:+.1f} ({best[0] - jetzt[0]:+.1f})")
    bx, by, bw, bh = best[4]
    print(f"   rect = [{bx:.4f}, {by:.4f}, {bw:.4f}, {bh:.4f}]")
    if best[0] - jetzt[0] < 3.0:
        print("\n   Der Gewinn ist klein. Dann liegt die Ursache NICHT an der "
              "Lage der ROI, und ein Verschieben waere Kosmetik.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
