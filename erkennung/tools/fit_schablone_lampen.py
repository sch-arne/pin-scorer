"""Zieht die Kegellampen der SCHABLONE auf die gemessene Lampenmitte.

WOFUER (Nutzer, 2026-09-11): *"baust du die Kalibrierschablone so um, dass sie
die Kegellampen etwas besser abbildet"*.

WAS KORRIGIERT WIRD UND WAS NICHT -- das ist der ganze Kern:

Gemessen wird je Lampe ueber ALLE Tafeln im Bild. Dabei fallen zwei Dinge an,
die nichts miteinander zu tun haben:

* ein Anteil, den alle Tafeln TEILEN -- das ist ein Fehler der Bauart und
  gehoert in die Schablone;
* ein Anteil, der je Tafel ANDERS ausfaellt -- das ist das Schaetzrauschen des
  Fundes. Wer den in die Schablone schreibt, verschlechtert drei Tafeln, um
  eine zu verbessern.

Getrennt werden sie ueber den Standardfehler: Korrigiert wird eine Lampe nur,
wenn ihr gemeinsamer Versatz groesser ist als die Streuung zwischen den Tafeln,
geteilt durch die Wurzel ihrer Zahl. GEMESSEN 2026-09-11 an vier Tafeln:

    Lampe   gemeinsam        Streuung   korrigiert?
    2       -0,18/-0,52 %        0,34       ja
    5       -0,47/-0,33 %        0,40       ja
    6       +0,11/+0,06 %        0,75       nein -- reines Rauschen
    9       -0,08/-0,07 %        0,21       nein -- sitzt bereits

WORAUF DIE MESSUNG BERUHT: nur auf LEUCHTENDEN Lampen. Bei ausgeschalteter
Lampe ist im Rahmen nichts, woran sich eine Mitte festmachen liesse. Und
gemessen wird in einem Fenster, das groesser ist als die ROI -- der Rahmen
bestimmt so nur, wo gesucht wird, nicht was gefunden wird.

Aufruf (erst ohne `--schreiben` ansehen):

    .venv/Scripts/python.exe tools/fit_schablone_lampen.py QUELLE \
        --kalibrierung debug/endstand.json \
        --typ data/boardtypes/FUNK_klassisch.json [--schreiben]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_lampenmitte import fenster_um, schwerpunkt        # noqa: E402

from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.calibration.model import Calibration                 # noqa: E402
from kegel_cv.config import load_config                            # noqa: E402

# So viele leuchtende Messungen muss eine Lampe je Tafel liefern.
MINDESTMESSUNGEN = 30
# Weiter als das ist kein Feinschliff -- dann stimmt etwas anderes nicht.
GRENZE = 0.02      # Anteil der Tafelkante, rund 3 px bei 160 px Kante


def messe(quelle: str, kal: Calibration, cfg, von: int, bis: int,
          schritt: int) -> dict[str, list[tuple[float, float]]]:
    """Versatz je Lampe und Tafel, in Anteilen der Tafelkante."""
    breite, hoehe = cfg.calibration.warped_width, cfg.calibration.warped_height
    kamera = cv2.VideoCapture(quelle)
    if not kamera.isOpened():
        raise SystemExit("Quelle laesst sich nicht oeffnen")
    kamera.set(cv2.CAP_PROP_POS_FRAMES, von)

    roh: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    kaesten = None
    masse: dict[int, tuple[float, float]] = {}
    for nummer in range(von, bis):
        ok, bild = kamera.read()
        if not ok or bild is None:
            break
        if (nummer - von) % schritt:
            continue
        if kaesten is None:
            kaesten = {}
            for bahn in sorted(kal.lanes, key=lambda l: l.quad[0][0]):
                t = bahn.transform(breite, hoehe)
                ecken = np.array(bahn.quad, float)
                masse[bahn.lane_id] = (
                    float(np.linalg.norm(ecken[1] - ecken[0])),
                    float(np.linalg.norm(ecken[3] - ecken[0])))
                for roi in bahn.pin_lamps():
                    kaesten[(bahn.lane_id, roi.name)] = norm_rect_to_frame_bbox(
                        t, roi.rect, bild.shape)
        for (lane_id, lampe), box in kaesten.items():
            fx, fy, fw, fh = fenster_um(box, bild.shape)
            mitte = schwerpunkt(bild[fy:fy + fh, fx:fx + fw])
            if mitte is None:
                continue
            # Am Fensterrand ist der Schwerpunkt abgeschnitten -- eine solche
            # Messung sagt nur, dass das Fenster zu klein war.
            if not (1 < mitte[0] < fw - 2 and 1 < mitte[1] < fh - 2):
                continue
            bp, hp = masse[lane_id]
            roh[(lane_id, lampe)].append(
                ((fx + mitte[0] - (box[0] + box[2] / 2)) / bp,
                 (fy + mitte[1] - (box[1] + box[3] / 2)) / hp))
    kamera.release()

    je_lampe: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for (_, lampe), werte in roh.items():
        if len(werte) >= MINDESTMESSUNGEN:
            je_lampe[lampe].append((float(np.median([w[0] for w in werte])),
                                    float(np.median([w[1] for w in werte]))))
    return je_lampe


def main() -> int:
    zerleger = argparse.ArgumentParser()
    zerleger.add_argument("quelle")
    zerleger.add_argument("--kalibrierung", required=True,
                          help="aus der Bauart gewonnene Kalibrierung")
    zerleger.add_argument("--typ", default="data/boardtypes/FUNK_klassisch.json")
    zerleger.add_argument("--von", type=int, default=20000)
    zerleger.add_argument("--bis", type=int, default=32000)
    zerleger.add_argument("--schritt", type=int, default=10)
    zerleger.add_argument("--schreiben", action="store_true")
    argumente = zerleger.parse_args()

    cfg = load_config()
    kal = Calibration.load(argumente.kalibrierung)
    je_lampe = messe(argumente.quelle, kal, cfg, argumente.von, argumente.bis,
                     argumente.schritt)
    if not je_lampe:
        print("Keine leuchtende Lampe gemessen -- andere Stelle waehlen")
        return 1

    typ = Calibration.load(argumente.typ)
    bahn = typ.lanes[0]
    print(f"{'Lampe':12s} {'gemeinsam':>16s} {'Streuung':>9s} "
          f"{'Fehler':>8s} {'korrigiert':>11s}")
    geaendert = 0
    for roi in bahn.pin_lamps():
        werte = je_lampe.get(roi.name, [])
        if len(werte) < 2:
            print(f"{roi.name:12s} {'zu wenige Tafeln':>16s}")
            continue
        mx = float(np.median([w[0] for w in werte]))
        my = float(np.median([w[1] for w in werte]))
        streuung = float(np.hypot(np.std([w[0] for w in werte]),
                                  np.std([w[1] for w in werte])))
        fehler = streuung / np.sqrt(len(werte))
        betrag = float(np.hypot(mx, my))
        # KORRIGIERT WIRD NUR, WAS SICH VON DER STREUUNG ABHEBT.
        nehmen = fehler < betrag <= GRENZE
        if nehmen:
            x, y, w, h = roi.rect
            bahn.set_roi(roi.model_copy(update={"rect": (x + mx, y + my, w, h)}))
            geaendert += 1
        print(f"{roi.name:12s} {mx * 100:+7.2f}/{my * 100:+6.2f} "
              f"{streuung * 100:9.2f} {fehler * 100:8.2f} "
              f"{('ja' if nehmen else 'nein'):>11s}")

    print(f"\n{geaendert} von {len(bahn.pin_lamps())} Lampen korrigiert "
          f"({len(next(iter(je_lampe.values())))} Tafeln gemessen)")
    if argumente.schreiben:
        typ.save(argumente.typ)
        print(f"{argumente.typ} geschrieben")
    else:
        print("Nichts geschrieben -- mit --schreiben uebernehmen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
