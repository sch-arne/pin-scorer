"""Verschiebt die linke Kante einer Ziffernzelle und misst, was dabei besser wird.

WOZU -- gemessen am 2026-08-31: Die fuehrende Stelle des Summenfeldes wird auf
Bahn 4 als "3" gelesen, wo die Tafel eine "0" zeigt. Die Segmentmessung sagt,
woran es liegt:

    Bahn 4   a=0.99  b=0.76  c=0.74  d=0.88  e=0.21  f=0.20  g=0.23  -> "3"
    Bahn 3   a=0.96  b=0.63  c=0.66  d=0.63  e=0.57  f=0.20  g=0.13  -> "0"

Eine "0" ist abcdef. Auf Bahn 4 sind e und f -- die beiden LINKEN Segmente --
dunkel; uebrig bleibt abcd, und das naechstliegende gueltige Muster ist die "3".
Fehlt zusaetzlich d, bleibt abc: genau die "7". Beide beobachteten Fehlwerte
sind also dieselbe abgeschnittene Null. Ueber den vollen Spieltag betraf das
37 von 234 lesbaren Summen (16 %).

Der Verdacht ist damit klar: Die ROI schneidet die linke Ziffernkante ab. Bei
10 px Zellenbreite genuegt ein Pixel.

DIESES WERKZEUG PROBIERT DAS DURCH. Es verschiebt die linke Kante in kleinen
Schritten nach aussen und misst je Schritt:

    * wie oft ein GUELTIGES Segmentmuster herauskommt (statt einer Reparatur
      auf das naechstliegende) -- das ist das eigentliche Guetemass,
    * die Fuellung der beiden linken Segmente e und f,
    * und, wo die Wahrheit bekannt ist, die Trefferquote.

Es aendert nichts. Die Kalibrierung bleibt unberuehrt; ausgegeben wird nur,
welcher Wert sich lohnen wuerde.
"""

from __future__ import annotations

import argparse
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
    CalibratedDigitReader, segment_regions)


def messen(patch, leser, vor, regionen):
    """(Zeichen, gueltiges Muster?, Fuellung e, Fuellung f)."""
    if patch.size == 0:
        return "?", False, 0.0, 0.0
    zeichen, _, _ = leser.read_digit_full(patch)
    maske = vor._red_mask(patch)
    if maske.max() == 0:
        return zeichen, False, 0.0, 0.0
    beschnitten = vor._trim_vertical(maske)
    if beschnitten.size and beschnitten.max() > 0:
        maske = beschnitten
    zelle = cv2.resize(maske, (CELL_WIDTH, CELL_HEIGHT),
                       interpolation=cv2.INTER_AREA)
    fuellungen = []
    for name in SEGMENT_ORDER:
        x, y, w, h = regionen[name]
        r = zelle[y:y + h, x:x + w]
        fuellungen.append(float(r.mean() / 255.0) if r.size else 0.0)
    schwelle = leser._threshold(fuellungen)
    aktiv = tuple(f >= schwelle for f in fuellungen)
    gueltig = SEGMENT_PATTERNS.get(aktiv) is not None
    i_e, i_f = SEGMENT_ORDER.index("e"), SEGMENT_ORDER.index("f")
    return zeichen, gueltig, fuellungen[i_e], fuellungen[i_f]


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True, help="reale Bahnnummer")
    p.add_argument("--field", default="total_b")
    p.add_argument("--from-frame", type=int, required=True)
    p.add_argument("--to-frame", type=int, required=True)
    p.add_argument("--every", type=int, default=25)
    p.add_argument("--soll", default=None,
                   help="erwarteter Feldwert, z.B. '0' -- dann wird auch die "
                        "Trefferquote ausgewiesen")
    p.add_argument("--steps", default="-0.016,-0.012,-0.008,-0.004,0,0.004,0.008",
                   help="Verschiebung in Tafelkoordinaten, negativ = nach "
                        "links (0,008 sind rund 1 px)")
    p.add_argument("--mode", choices=("verschieben", "verbreitern"),
                   default="verschieben",
                   help="verschieben: die ganze Box wandert. verbreitern: nur "
                        "die linke Kante geht nach aussen. GEMESSEN 2026-08-31: "
                        "Verbreitern hilft NICHT -- der Leerraum links schiebt "
                        "die Ziffer beim Normieren nach rechts, und die "
                        "geometrischen Segmentflaechen sitzen dann daneben. "
                        "`_trim_vertical` schneidet nur senkrecht zu.")
    a = p.parse_args()

    cal = Calibration.load(a.calibration)
    lane = next((l for l in cal.lanes if l.display_number == a.lane), None)
    if lane is None:
        raise SystemExit(f"Bahn {a.lane} nicht in der Kalibrierung")
    zellen = lane.digit_rois(a.field)
    if not zellen:
        raise SystemExit(f"Feld {a.field} ist nicht stellenweise kalibriert")

    cfg = load_config()
    leser = CalibratedDigitReader(cfg.detection.digits)
    vor = SevenSegmentDetector(cfg.detection.digits)
    regionen = segment_regions()
    schritte = [float(x) for x in a.steps.split(",")]

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 20000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 15000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")
    cap.set(cv2.CAP_PROP_POS_FRAMES, float(a.from_frame))

    # [schritt][stelle] -> Listen
    gueltig = {s: [[] for _ in zellen] for s in schritte}
    e_werte = {s: [[] for _ in zellen] for s in schritte}
    f_werte = {s: [[] for _ in zellen] for s in schritte}
    treffer = {s: [] for s in schritte}
    # Objektives Mass OHNE Sollwert: Eine Summe ueber 999 ist unmoeglich
    # (30 Wuerfe zu hoechstens 9 Kegeln). Jede solche Lesung ist falsch.
    unmoeglich = {s: [] for s in schritte}
    lesbar = {s: [] for s in schritte}
    tf = None
    n = a.from_frame
    gelesen = 0
    while n <= a.to_frame:
        ok, bild = cap.read()
        if not ok:
            break
        if (n - a.from_frame) % a.every == 0:
            if tf is None:
                tf = lane.transform(bild.shape[1], bild.shape[0])
            gelesen += 1
            for s in schritte:
                text = ""
                for i, z in enumerate(zellen):
                    x, y, w, h = z.rect
                    rect = ((x + s, y, w, h) if a.mode == "verschieben"
                            else (x - s, y, w + s, h))
                    bx, by, bw, bh = norm_rect_to_frame_bbox(tf, rect, bild.shape)
                    patch = bild[by:by + bh, bx:bx + bw]
                    zeichen, gilt, fe, ff = messen(patch, leser, vor, regionen)
                    gueltig[s][i].append(gilt)
                    e_werte[s][i].append(fe)
                    f_werte[s][i].append(ff)
                    text += zeichen
                if a.soll is not None:
                    treffer[s].append(text.isdigit() and int(text) == int(a.soll))
                lesbar[s].append(text.isdigit())
                if text.isdigit():
                    unmoeglich[s].append(int(text) > 999)
        n += 1
    cap.release()

    print(f"Bahn {a.lane}, Feld {a.field}, {gelesen} Frames "
          f"(F{a.from_frame}-F{a.to_frame})\n")
    kopf = f"  {'Kante':>7}"
    for i in range(len(zellen)):
        kopf += f" {'St' + str(i + 1) + ' gueltig':>12}"
    if a.soll is not None:
        kopf += f" {'Feld=' + a.soll:>10}"
    print(kopf)
    for s in schritte:
        zeile = f"  {s:>7.3f}"
        for i in range(len(zellen)):
            zeile += f" {np.mean(gueltig[s][i]):>11.0%}"
        if a.soll is not None:
            zeile += f" {np.mean(treffer[s]):>9.0%}"
        print(zeile)

    print("")
    print("  %7s %10s %14s" % ("Kante", "lesbar", "davon > 999"))
    for s_ in schritte:
        u = np.mean(unmoeglich[s_]) if unmoeglich[s_] else float("nan")
        print("  %7.3f %9.0f%% %13.0f%%" % (s_, 100*np.mean(lesbar[s_]), 100*u))
    print("\nFuellung der linken Segmente (e / f) -- sie fehlen bei der '0'")
    print(f"  {'Kante':>7}" + "".join(f" {'St' + str(i + 1):>14}"
                                      for i in range(len(zellen))))
    for s in schritte:
        zeile = f"  {s:>7.3f}"
        for i in range(len(zellen)):
            zeile += f"   {np.mean(e_werte[s][i]):.2f} / {np.mean(f_werte[s][i]):.2f}"
        print(zeile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
