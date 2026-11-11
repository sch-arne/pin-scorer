"""Schwaerzt die Personenmaske wirklich, bevor irgendetwas ausgewertet wird?

DIE FRAGE (Nutzer, 2026-09-13): *"Funktioniert denn mittlerweile das onTheFly
Menschen schwaerzen? Bevor das Video verarbeitet wird"*

Verdrahtet ist es (`AnalysisPipeline.process` maskiert als erste Handlung).
Dieses Werkzeug prueft, ob es auch WIRKT -- und zwar an drei Zahlen, die
verschiedene Fragen beantworten:

    geschwaerzt   Anteil des Bildes, der schwarz wird. Zu wenig heisst
                  "sieht niemanden", zu viel heisst "schwaerzt das Spiel".
    Tafelanteil   Wie viel davon in den Tafelbereichen liegt. Muss NULL sein:
                  Dort wird gemessen, nie geschwaerzt -- sonst loescht die
                  Maske genau das Signal, das gelesen werden soll.
    Verdeckung    Der gemeldete Vordergrundanteil je Bahn.

Und es legt Bildbelege ab: das Bild vorher, das Bild nachher.

Aufruf:

    .venv/Scripts/python.exe tools/pruefe_personenmaske.py QUELLE \
        --kalibrierung data/calibrations/1Spieltag.json --von 5000 --bis 5600
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.analysis.lane_processor import LaneProcessor    # noqa: E402
from kegel_cv.calibration.model import Calibration            # noqa: E402
from kegel_cv.config import load_config                       # noqa: E402
from kegel_cv.detection.person_maske import PersonMaske       # noqa: E402


def main() -> int:
    zerleger = argparse.ArgumentParser()
    zerleger.add_argument("quelle")
    zerleger.add_argument("--kalibrierung", required=True)
    zerleger.add_argument("--von", type=int, default=5000)
    zerleger.add_argument("--bis", type=int, default=5600)
    zerleger.add_argument("--ordner", default="debug/personenmaske")
    argumente = zerleger.parse_args()

    cfg = load_config()
    m = cfg.detection.person_mask
    print(f"Personenmaske: enabled={m.enabled}, history={m.history}, "
          f"scale={m.scale}, min_blob_px={m.min_blob_px}, "
          f"dilate_px={m.dilate_px}, occlusion_fraction={m.occlusion_fraction}, "
          f"warmup_frames={m.warmup_frames}")
    if not m.enabled:
        print("ABGESCHALTET -- es wird nichts geschwaerzt.")
        return 1

    kal = Calibration.load(argumente.kalibrierung)
    kamera = cv2.VideoCapture(argumente.quelle)
    if not kamera.isOpened():
        print("Quelle laesst sich nicht oeffnen")
        return 1
    kamera.set(cv2.CAP_PROP_POS_FRAMES, argumente.von)
    ok, erstes = kamera.read()
    if not ok:
        print("Nichts gelesen")
        return 1

    prozessoren = [LaneProcessor(b, cfg) for b in kal.lanes]
    for p in prozessoren:
        p.prepare(erstes.shape)
    maske = PersonMaske(
        history=m.history, var_threshold=m.var_threshold, scale=m.scale,
        min_blob_px=m.min_blob_px, dilate_px=m.dilate_px,
        occlusion_fraction=m.occlusion_fraction,
        warmup_frames=m.warmup_frames, enabled=m.enabled)
    tafeln = {p.display_number: p.lane_box() for p in prozessoren}
    maske.set_tafeln(tafeln)

    ordner = Path(argumente.ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    kamera.set(cv2.CAP_PROP_POS_FRAMES, argumente.von)

    bester = (0.0, None, None, None)      # Anteil, Frame, vorher, nachher
    anteile: list[float] = []
    in_tafeln = 0
    verdeckt_gemeldet = 0

    for nummer in range(argumente.von, argumente.bis):
        ok, bild = kamera.read()
        if not ok or bild is None:
            break
        vorher = bild.copy()
        ergebnis = maske.verarbeite(bild)
        nachher = ergebnis.bild

        # Was wurde geschwaerzt? Genau die Pixel, die jetzt schwarz sind und
        # vorher nicht.
        schwarz = (nachher.max(axis=2) == 0) & (vorher.max(axis=2) > 0)
        anteil = float(schwarz.mean())
        anteile.append(anteil)
        if ergebnis.verdeckte_bahnen:
            verdeckt_gemeldet += 1

        # SCHUTZZONEN: Innerhalb der Tafeln darf NICHTS schwarz werden.
        for (x, y, w, h) in tafeln.values():
            if schwarz[y:y + h, x:x + w].any():
                in_tafeln += 1
                break

        if anteil > bester[0]:
            bester = (anteil, nummer, vorher, nachher.copy())
    kamera.release()

    a = np.array(anteile)
    print(f"\n{len(a)} Bilder (Frames {argumente.von}-{argumente.bis})")
    print(f"  geschwaerzt: Median {100 * np.median(a):.2f} %, "
          f"95. Perzentil {100 * np.percentile(a, 95):.2f} %, "
          f"Maximum {100 * a.max():.2f} %")
    print(f"  Bilder ganz ohne Schwaerzung: {int((a == 0).sum())}")
    print(f"  Bilder mit Schwaerzung IN einem Tafelbereich: {in_tafeln} "
          f"(muss 0 sein)")
    print(f"  Bilder mit gemeldeter Verdeckung: {verdeckt_gemeldet}")

    if bester[2] is not None:
        cv2.imwrite(str(ordner / f"frame{bester[1]}_vorher.jpg"), bester[2])
        cv2.imwrite(str(ordner / f"frame{bester[1]}_nachher.jpg"), bester[3])
        print(f"\nStaerkste Schwaerzung bei Frame {bester[1]} "
              f"({100 * bester[0]:.2f} %) -- Bildbelege in {ordner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
