"""Wie sauber trennt die Gruenlampe AN von AUS -- je Kalibrierung, je Bahn.

DIE FRAGE (Nutzer, 2026-09-11):

    "der erkennt ja gerade auf Bahn 5 gar nicht richtig ob sie aus ist... der
     sagt meist nur joa vermutlich an, wenn sie aus ist"

WARUM GENAU DIESES MASS: Die gruene Lampe steuert den ZEITPUNKT jeder Messung.
Liegt ihre ROI daneben, sinkt der AN-Pegel in Richtung des AUS-Pegels, die
beiden Wolken ruecken zusammen, und die Schwelle findet kein Tal mehr --
`GREEN_OFF` bleibt aus und ein ganzer Wurf fehlt. Gemessen wird deshalb die
TRENNSCHAERFE, nicht der Pegel.

Zwei Zahlen je Bahn:

    Abstand    Mittelwert der AN-Wolke minus Mittelwert der AUS-Wolke
    Fisher     (Abstand)^2 / (Streuung AN + Streuung AUS) -- wie weit die
               Wolken auseinanderliegen, GEMESSEN IN IHRER EIGENEN BREITE

Die Wolken werden mit Otsu getrennt, also ohne Vorwissen darueber, wann die
Lampe wirklich an war. Das Mass haengt damit an KEINEM Kriterium, auf das eine
Kalibrierung optimiert wurde -- und ist deshalb geeignet, zwischen
Kalibrierungen zu entscheiden.

Aufruf:

    .venv/Scripts/python.exe tools/measure_gruen_trennschaerfe.py QUELLE \
        --kalibrierung data/calibrations/1Spieltag.json=Hand \
        --kalibrierung debug/auto.json=automatisch \
        --von 14400 --bis 17400
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.calibration.model import Calibration                 # noqa: E402
from kegel_cv.config import load_config                            # noqa: E402
from kegel_cv.detection.lamp_detectors import HsvGreenDetector     # noqa: E402


def kaesten(kal: Calibration, cfg, form) -> dict[int, tuple[int, int, int, int]]:
    """Die Gruenlampen-Rechtecke aller Bahnen in Frame-Pixeln."""
    aus = {}
    for bahn in sorted(kal.lanes, key=lambda l: l.quad[0][0]):
        roi = bahn.get_roi("green_lamp")
        if roi is None:
            continue
        t = bahn.transform(cfg.calibration.warped_width,
                           cfg.calibration.warped_height)
        aus[bahn.display_number] = norm_rect_to_frame_bbox(t, roi.rect, form)
    return aus


def trennschaerfe(werte: np.ndarray) -> tuple[float, float, float, float, float]:
    """Otsu-Trennung der Punktwolke: AUS-Mittel, AN-Mittel, Abstand, Fisher, Grau.

    `Grau` ist der Anteil der Messungen, die naeher an der Schwelle liegen als
    ein Viertel des Abstands -- das sind die, bei denen die Zustandsmaschine
    "vermutlich an" sagt.
    """
    if werte.size < 50:
        return (float("nan"),) * 5
    ganz = np.clip(werte, 0, 100).astype(np.uint8)
    schwelle, _ = cv2.threshold(ganz, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    unten, oben = werte[werte <= schwelle], werte[werte > schwelle]
    if unten.size < 5 or oben.size < 5:
        return (float("nan"),) * 5
    abstand = float(oben.mean() - unten.mean())
    streuung = float(oben.var() + unten.var())
    fisher = abstand ** 2 / streuung if streuung > 0 else float("inf")
    grau = float(np.mean(np.abs(werte - schwelle) < abstand / 4) * 100)
    return float(unten.mean()), float(oben.mean()), abstand, fisher, grau


def main() -> int:
    zerleger = argparse.ArgumentParser()
    zerleger.add_argument("quelle")
    zerleger.add_argument("--kalibrierung", action="append", required=True,
                          help="PFAD oder PFAD=Name, mehrfach moeglich")
    zerleger.add_argument("--von", type=int, default=14400)
    zerleger.add_argument("--bis", type=int, default=17400)
    zerleger.add_argument("--schritt", type=int, default=2)
    argumente = zerleger.parse_args()

    cfg = load_config()
    detektor = HsvGreenDetector(cfg.detection.green)

    saetze = []
    for eintrag in argumente.kalibrierung:
        pfad, _, name = eintrag.partition("=")
        saetze.append((name or Path(pfad).stem, Calibration.load(pfad)))

    kamera = cv2.VideoCapture(argumente.quelle)
    if not kamera.isOpened():
        print("Quelle laesst sich nicht oeffnen")
        return 1
    kamera.set(cv2.CAP_PROP_POS_FRAMES, argumente.von)

    kasten_je_satz: list[dict] | None = None
    werte: dict[tuple[str, int], list[float]] = {}
    gelesen = 0
    for nummer in range(argumente.von, argumente.bis):
        ok, bild = kamera.read()
        if not ok or bild is None:
            break
        if (nummer - argumente.von) % argumente.schritt:
            continue
        if kasten_je_satz is None:
            kasten_je_satz = [kaesten(k, cfg, bild.shape) for _, k in saetze]
        gelesen += 1
        for (name, _), kaesten_ in zip(saetze, kasten_je_satz):
            for bahn, (x, y, w, h) in kaesten_.items():
                if w <= 0 or h <= 0:
                    continue
                wert = detektor.score(bild[y:y + h, x:x + w])
                werte.setdefault((name, bahn), []).append(wert)
    kamera.release()
    print(f"{gelesen} Bilder gemessen (Frame {argumente.von}-{argumente.bis})\n")

    for name, kal in saetze:
        roi = sorted(kal.lanes, key=lambda l: l.quad[0][0])[0].get_roi("green_lamp")
        print(f"=== {name} === (ROI {roi.rect[2]:.4f}x{roi.rect[3]:.4f} normiert)")
        print(f"{'Bahn':6s} {'AUS':>7s} {'AN':>7s} {'Abstand':>9s} "
              f"{'Fisher':>8s} {'Graubereich':>12s}")
        for (satz, bahn), liste in sorted(werte.items()):
            if satz != name:
                continue
            unten, oben, abstand, fisher, grau = trennschaerfe(np.array(liste))
            print(f"{bahn:<6d} {unten:7.1f} {oben:7.1f} {abstand:9.1f} "
                  f"{fisher:8.1f} {grau:11.1f} %")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
