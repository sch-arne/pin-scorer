"""Legt Frames als Bildbeleg ab -- mit den kalibrierten Rahmen darin.

WOZU: Bei Frame 40903 lieferte die Tafel auf Bahn 5 gleichzeitig eine
unlesbare Wurfnummer, einen unlesbaren Fehlwurfzaehler UND unlesbare
Kegellampen -- und trotzdem einen Gruenwechsel. Aus Zahlen laesst sich nicht
entscheiden, ob die ROIs falsch sitzen oder ob im Bild schlicht nichts zu
sehen war. Das entscheidet nur das Bild selbst.

Ausgegeben wird je Frame eine Tafel:

    links   die entzerrte Anzeigetafel, vergroessert, mit ALLEN kalibrierten
            Rahmen (Lampen gelb, Gruenlampe gruen, Ziffernfelder farbig,
            einzelne Stellen duenn)
    rechts  jede einzeln eingerahmte Stelle so, wie die Erkennung sie sieht:
            Rohausschnitt, Rotmaske, und das daraus gelesene Zeichen

Zusaetzlich auf der Konsole je Frame: Gruen-Score, Helligkeit der Ziffern
(95. Perzentil des Rotkanals -- daran scheitert die Lesung zuerst) und die
Zahl der lesbaren Kegellampen. Das Werkzeug entscheidet nichts, es zeigt nur.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration, PerspectiveTransform  # noqa: E402
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.detection.digit_detector import SevenSegmentDetector  # noqa: E402
from kegel_cv.detection.digit_reader import CalibratedDigitReader  # noqa: E402
from kegel_cv.detection.lamp_detectors import (  # noqa: E402
    HsvGreenDetector, WarmthLampDetector)

# Tafelgroesse fuer die Entzerrung -- dieselben Werte wie in verify_rois.py,
# damit die Bilder beider Werkzeuge vergleichbar bleiben.
BREITE, HOEHE = 440, 530
# Die Tafel misst im Original 133x135 px. Ohne Vergroesserung ist eine Ziffer
# 8x14 px gross und fuer das Auge nicht beurteilbar (gemessen 2026-08-30).
ZELLE_B, ZELLE_H = 60, 100

FARBEN = {
    "pin_lamp": (0, 255, 255),
    "green_lamp": (0, 255, 0),
    "pin_count": (255, 128, 0),
    "throw_number": (255, 0, 255),
    "total_a": (0, 128, 255),
    "total_b": (0, 128, 255),
    "left_display": (160, 160, 160),
}
FELDER = ("throw_number", "pin_count", "total_a", "total_b", "left_display")


def farbe(name: str) -> tuple[int, int, int]:
    kern = name.removeprefix("digit_") if name.startswith("digit_") else name
    for schluessel, wert in FARBEN.items():
        if kern.startswith(schluessel) or name.startswith(schluessel):
            return wert
    return (200, 200, 200)


def zeichne_tafel(warped: np.ndarray, rois, faktor: int) -> np.ndarray:
    """Entzerrte Tafel mit allen kalibrierten Rahmen."""
    leinwand = cv2.resize(warped, None, fx=faktor, fy=faktor,
                          interpolation=cv2.INTER_NEAREST)
    h, b = leinwand.shape[:2]
    for roi in rois:
        if not roi.enabled:
            continue
        x, y, w, hh = roi.rect
        p1 = (int(x * b), int(y * h))
        p2 = (int((x + w) * b), int((y + hh) * h))
        # Einzelne Stellen duenn und ohne Beschriftung -- sie liegen in den
        # Feldrahmen und wuerden das Bild sonst zukleistern.
        cv2.rectangle(leinwand, p1, p2, farbe(roi.name), 1)
        if not roi.name.startswith("digit_"):
            cv2.putText(leinwand, roi.name.replace("pin_lamp_", "L"),
                        (p1[0], max(10, p1[1] - 3)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.35, farbe(roi.name), 1, cv2.LINE_AA)
    return leinwand


def stelle_zeigen(patch: np.ndarray, maske: np.ndarray, zeichen: str,
                  hell: float) -> np.ndarray:
    """Eine Stelle als Saeule: Rohausschnitt, Rotmaske, gelesenes Zeichen."""
    roh = cv2.resize(patch, (ZELLE_B, ZELLE_H), interpolation=cv2.INTER_NEAREST)
    mask_bgr = cv2.cvtColor(cv2.resize(maske, (ZELLE_B, ZELLE_H),
                                       interpolation=cv2.INTER_NEAREST),
                            cv2.COLOR_GRAY2BGR)
    kopf = np.zeros((26, ZELLE_B, 3), np.uint8)
    ton = (0, 255, 0) if zeichen.isdigit() else (0, 0, 255)
    cv2.putText(kopf, zeichen, (4, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, ton, 2,
                cv2.LINE_AA)
    cv2.putText(kopf, f"{hell:.0f}", (26, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (180, 180, 180), 1, cv2.LINE_AA)
    saeule = np.vstack([kopf, roh, mask_bgr])
    return cv2.copyMakeBorder(saeule, 2, 2, 2, 2, cv2.BORDER_CONSTANT,
                              value=(60, 60, 60))


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    # BEWUSST str, nicht Path: Eine Stream-URL wuerde von Path zerstoert.
    # Genau daran scheiterte tools/verify_rois.py.
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--lane", type=int, required=True, help="reale Bahnnummer")
    p.add_argument("--frames", default=None, help="Frames, mit Komma getrennt")
    p.add_argument("--around", type=int, default=None,
                   help="Mittelframe; zusammen mit --span und --step")
    p.add_argument("--span", type=int, default=40)
    p.add_argument("--step", type=int, default=10)
    p.add_argument("--faktor", type=int, default=2,
                   help="Vergroesserung der entzerrten Tafel")
    p.add_argument("--out", type=Path, default=Path("debug/roi_frames"))
    a = p.parse_args()

    if a.frames:
        nummern = [int(x) for x in a.frames.split(",")]
    elif a.around is not None:
        nummern = list(range(a.around - a.span, a.around + a.span + 1, a.step))
    else:
        raise SystemExit("Entweder --frames oder --around angeben")

    cal = Calibration.load(a.calibration)
    lane = next((l for l in cal.lanes if l.display_number == a.lane), None)
    if lane is None:
        raise SystemExit(f"Bahn {a.lane} nicht in der Kalibrierung")

    cfg = load_config()
    leser = CalibratedDigitReader(cfg.detection.digits)
    vorbereiter = SevenSegmentDetector(cfg.detection.digits)
    gruen = HsvGreenDetector(cfg.detection.green)
    lampen = WarmthLampDetector(cfg.detection.lamps)

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 20000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 15000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")

    a.out.mkdir(parents=True, exist_ok=True)
    tf = None
    print(f"  {'Frame':>8} {'Gruen':>7} {'an/lesbar':>12}  Ziffernhelligkeit")
    for n in nummern:
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(n))
        ok, bild = cap.read()
        if not ok or bild is None:
            print(f"  {n:>8}   nicht lesbar")
            continue
        if tf is None:
            tf = lane.transform(bild.shape[1], bild.shape[0])

        def ausschnitt(rect):
            bx, by, bw, bh = norm_rect_to_frame_bbox(tf, rect, bild.shape)
            return bild[by:by + bh, bx:bx + bw]

        # --- Messwerte fuer die Konsole ---
        g_roi = lane.get_roi("green_lamp")
        g_score = gruen.score(ausschnitt(g_roi.rect)) if g_roi else float("nan")

        an = lesbar = 0
        for roi in lane.pin_lamps():
            if not roi.enabled:
                continue
            messung = lampen.detect_one(ausschnitt(roi.rect), roi.name)
            if messung.state.name != "UNKNOWN":
                lesbar += 1
                if messung.state.name == "ON":
                    an += 1

        # --- Bild: entzerrte Tafel mit Rahmen ---
        warped = PerspectiveTransform(lane.to_quad(), BREITE, HOEHE).warp(bild)
        tafel = zeichne_tafel(warped, lane.rois, a.faktor)

        # --- Bild: jede einzeln eingerahmte Stelle ---
        saeulen: list[np.ndarray] = []
        helligkeiten: list[str] = []
        for feld in FELDER:
            zellen = lane.digit_rois(feld)
            if not zellen:
                continue
            hellsten: list[float] = []
            for zelle in zellen:
                patch = ausschnitt(zelle.rect)
                if patch.size == 0:
                    continue
                hell = float(np.percentile(patch[:, :, 2], 95))
                hellsten.append(hell)
                maske = vorbereiter._red_mask(patch)
                zeichen, _, _ = leser.read_digit_full(patch)
                saeulen.append(stelle_zeigen(patch, maske, zeichen, hell))
            if hellsten:
                helligkeiten.append(f"{feld[:9]}={max(hellsten):.0f}")
            if saeulen:
                saeulen.append(np.zeros((saeulen[-1].shape[0], 10, 3), np.uint8))

        print(f"  {n:>8} {g_score:7.1f} {an:>5}/{lesbar:<6}  "
              f"{'  '.join(helligkeiten)}")

        if saeulen:
            streifen = np.hstack(saeulen)
            hoehe = max(tafel.shape[0], streifen.shape[0])
            links = cv2.copyMakeBorder(tafel, 0, hoehe - tafel.shape[0], 0, 0,
                                       cv2.BORDER_CONSTANT, value=(0, 0, 0))
            rechts = cv2.copyMakeBorder(streifen, 0, hoehe - streifen.shape[0],
                                        0, 0, cv2.BORDER_CONSTANT,
                                        value=(0, 0, 0))
            gesamt = np.hstack([links, rechts])
        else:
            gesamt = tafel

        kopf = np.zeros((30, gesamt.shape[1], 3), np.uint8)
        cv2.putText(kopf, f"Bahn {a.lane}  Frame {n}  Gruen-Score {g_score:.1f}"
                    f"  Lampen an {an} / lesbar {lesbar}",
                    (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255),
                    1, cv2.LINE_AA)
        pfad = a.out / f"bahn{a.lane}_F{n:06d}.png"
        cv2.imwrite(str(pfad), np.vstack([kopf, gesamt]))
    cap.release()
    print(f"\nGeschrieben nach {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
