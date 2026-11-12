"""Zeigt Raeumwuerfe als Bildfolge -- damit die Differenzbildung pruefbar wird.

Beim Raeumen liegen schon Kegel, bevor geworfen wird. Das Ergebnis ist deshalb
die Differenz zwischen dem Stand bei Gruen-AUS und dem bei Gruen-AN. Diese
Rechnung laesst sich in einer Tabelle schlecht glauben -- man muss sehen, dass
die abgezogenen Lampen tatsaechlich schon vorher leuchteten.

Deshalb je Raeumwurf ein Streifen ueber den ganzen Wurf: vom Beginn (Gruen an,
Grundlinie steht) bis nach dem Ergebnis. Ueber jedem Bild die Zahl, die der
Detektor daraus gemacht hat.

Aufruf:
    .venv/Scripts/python.exe tools/export_clearing_throws.py [ANZAHL]
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.video import FileVideoSource

QUELLE = Path("debug/vollauswertung.json")
VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/raeumwuerfe")

# Wo im Wurf geschaut wird, relativ zum Ausloeser (Gruen-AUS).
# Negative Werte liegen im laufenden Wurf, als die gruene Lampe noch an war.
OFFSETS = [-260, -200, -140, -80, -20, 0, 40, 90]
SKALIERUNG = 2.0


def zeit(frame: int) -> str:
    s = frame / 25.0
    return f"{int(s // 60)}:{int(s % 60):02d}"


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    anzahl = int(sys.argv[1]) if len(sys.argv) > 1 else 12

    if not QUELLE.exists():
        print(f"Keine Auswertung unter {QUELLE} -- zuerst run_full_analysis.py")
        return 1

    daten = json.loads(QUELLE.read_text(encoding="utf-8"))
    raeum = [w for w in daten["wuerfe"]
             if (w.get("evidence") or {}).get("raw", {}).get("clearing")]
    print(f"{len(raeum)} Raeumwuerfe insgesamt, die ersten {anzahl} werden gerendert\n")

    cfg = load_config()
    cal = Calibration.load(KALIBRIERUNG)
    src = FileVideoSource(VIDEO)
    src.open()
    erster = src.read()

    prozessoren = {}
    for lane in cal.lanes:
        p = LaneProcessor(lane, cfg)
        if p.prepare(erster.image.shape):
            prozessoren[lane.display_number] = p

    AUSGABE.mkdir(parents=True, exist_ok=True)
    blaetter: list[np.ndarray] = []

    for wurf in raeum[:anzahl]:
        dn = wurf["lane"]
        p = prozessoren.get(dn)
        if p is None:
            continue
        trigger = wurf["source_frame"]
        roh = wurf["evidence"]["raw"]
        grund = roh.get("baseline") or {}
        ende = roh.get("pins") or {}

        teile = []
        for offset in OFFSETS:
            index = trigger + offset
            if index < 0:
                continue
            src.seek(index)
            frame = src.read()
            if frame is None:
                continue
            messung = p.read_pin_lamps_at(frame)
            gruen = p.green_detector.detect(p._crop(frame.image, p._green_box))

            x, y, w, h = p.lane_box()
            bild = frame.image[y:y + h, x:x + w].copy()
            bild = cv2.resize(bild, None, fx=SKALIERUNG, fy=SKALIERUNG,
                              interpolation=cv2.INTER_LANCZOS4)
            bild = cv2.copyMakeBorder(bild, 44, 6, 4, 4, cv2.BORDER_CONSTANT,
                                      value=(0, 0, 0))
            cv2.putText(bild, f"{offset:+d}", (6, 13), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (170, 170, 170), 1)
            cv2.putText(bild, f"{messung.count if messung else '?'} Lampen",
                        (6, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            cv2.putText(bild, "gruen AN" if gruen.is_on else "gruen aus",
                        (6, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.36,
                        (80, 255, 80) if gruen.is_on else (140, 140, 140), 1)
            if offset == 0:
                cv2.rectangle(bild, (1, 1), (bild.shape[1] - 2, bild.shape[0] - 2),
                              (0, 180, 255), 2)
            teile.append(bild)

        if not teile:
            continue

        streifen = np.hstack(teile)
        streifen = cv2.copyMakeBorder(streifen, 46, 6, 4, 4, cv2.BORDER_CONSTANT,
                                      value=(0, 0, 0))
        cv2.putText(streifen,
                    f"Bahn {dn} | Wurf {wurf['throw_number']} | {zeit(trigger)}",
                    (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        cv2.putText(streifen,
                    f"lagen schon: {grund.get('count')} {grund.get('pins')}   "
                    f"am Ende: {ende.get('count')} {ende.get('pins')}   "
                    f"=> gewertet {wurf['pins_count']}",
                    (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

        name = AUSGABE / f"bahn{dn}_{trigger:06d}.png"
        cv2.imwrite(str(name), streifen)
        blaetter.append(streifen)
        print(f"   Bahn {dn} Wurf {wurf['throw_number']:>3} {zeit(trigger)}: "
              f"{grund.get('count')} lagen schon, {ende.get('count')} am Ende "
              f"-> {wurf['pins_count']} gewertet")

    src.close()

    if blaetter:
        breite = max(b.shape[1] for b in blaetter)
        blaetter = [cv2.copyMakeBorder(b, 0, 10, 0, breite - b.shape[1],
                                       cv2.BORDER_CONSTANT, value=(40, 40, 40))
                    for b in blaetter]
        cv2.imwrite(str(AUSGABE / "uebersicht.png"), np.vstack(blaetter))
        print(f"\nSammelblatt: {AUSGABE / 'uebersicht.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
