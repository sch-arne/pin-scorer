"""Traegt die Ziffernrahmen des Fehlwurfzaehlers nach -- und prueft sie sofort.

Notlage am Spieltag: Die Analyse laeuft, die Oberflaeche nimmt die Klicks fuer
das Einrahmen nicht an, und der Fehlwurfzaehler wird deshalb gar nicht gelesen
(im Log: "4 Ziffernfelder (0 davon stellenweise eingerahmt)"). Ohne ihn fehlen
Wuerfe ohne Kegel ersatzlos (Q10).

Die Rahmen sind am Feingitter der laufenden Aufnahme abgelesen
(tools/grid_from_run.py, Raster 0,005):

    Bahn 1   x 0,183..0,238 / 0,253..0,305   y 0,723..0,822
    Bahn 2   x 0,186..0,235 / 0,253..0,302   y 0,725..0,815
    Bahn 3   x 0,180..0,230 / 0,248..0,298   y 0,727..0,820
    Bahn 4   x 0,190..0,242 / 0,258..0,310   y 0,715..0,815

GEPRUEFT wird direkt danach an den Tafelbildern desselben Laufs: Die Anzeige
steht dort auf `00`, der Leser muss also 0 liefern. Koordinaten ohne Gegenprobe
waeren nur eine besser aussehende Vermutung.

Aufruf:
    .venv/Scripts/python.exe tools/patch_left_display_live.py [LAUFORDNER]
"""

from __future__ import annotations

import glob
import json
import logging
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

QUELLE = Path("data/calibrations/kalibrierung_2026-08-29_1227.json")
ZIEL = Path("data/calibrations/kalibrierung_2026-08-29_fehlwurf.json")
LAUF = ("debug/manifest-oci-us-ashburn-1-vop1.edgemv.mux.com_rendition.m3u8/"
        "lauf_2026-08-29_12-31-46")

# (x, y, Breite, Hoehe) je Bahn und Stelle, in normierten Tafelkoordinaten
STELLEN: dict[int, dict[int, list[float]]] = {
    1: {1: [0.181, 0.720, 0.059, 0.104], 2: [0.251, 0.720, 0.056, 0.104]},
    2: {1: [0.184, 0.722, 0.053, 0.096], 2: [0.251, 0.722, 0.053, 0.096]},
    3: {1: [0.178, 0.724, 0.054, 0.099], 2: [0.246, 0.724, 0.054, 0.099]},
    4: {1: [0.188, 0.712, 0.056, 0.105], 2: [0.256, 0.712, 0.056, 0.105]},
}


def schreiben() -> None:
    daten = json.loads(QUELLE.read_text(encoding="utf-8"))
    for lane in daten["lanes"]:
        stellen = STELLEN.get(lane["lane_id"])
        if stellen is None:
            continue
        vorhanden = {r["name"] for r in lane["rois"]}
        for roi in lane["rois"]:
            if roi["name"] == "left_display":
                roi["enabled"] = True
        for nummer, rect in stellen.items():
            name = f"digit_left_display_{nummer}"
            if name in vorhanden:
                for roi in lane["rois"]:
                    if roi["name"] == name:
                        roi["rect"] = rect
                        roi["enabled"] = True
            else:
                lane["rois"].append({"name": name, "rect": rect,
                                     "enabled": True, "pin_number": None})
    ZIEL.write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"Geschrieben: {ZIEL}")
    print(f"(die Vorlage {QUELLE.name} bleibt unveraendert)\n")


def pruefen(ordner: Path, hoechstens: int = 60) -> None:
    """Liest das Feld aus den Tafelbildern des Laufs.

    Die Bilder sind Ausschnitte. Fuer die ROI-Umrechnung wird ein Vollframe
    gebraucht -- der Ausschnitt wird deshalb an seiner urspruenglichen Stelle
    in eine schwarze Leinwand gesetzt. Alles ausserhalb bleibt schwarz, was
    fuer diesen Zweck genuegt: Gelesen wird nur innerhalb der Tafel.
    """
    from kegel_cv.analysis.lane_processor import LaneProcessor
    from kegel_cv.calibration import Calibration
    from kegel_cv.config import load_config
    from kegel_cv.video.source import Frame

    cfg = load_config()
    cal = Calibration.load(ZIEL)

    print(f"{'Bahn':<6}{'lesbar':>16}   Werte")
    for lane in cal.lanes:
        p = LaneProcessor(lane, cfg)
        if not p.prepare((1080, 1920, 3)):
            print(f"{lane.lane_id:<6}   Bahn nicht vorbereitbar")
            continue
        if "left_display" not in p._digit_cell_boxes:
            print(f"{lane.lane_id:<6}   left_display NICHT stellenweise eingerahmt")
            continue

        xs = [pt[0] for pt in lane.quad]
        ys = [pt[1] for pt in lane.quad]
        x0, y0 = int(min(xs)), int(min(ys))

        bilder = sorted(glob.glob(str(ordner / f"lane_{lane.lane_id}"
                                      / "event_*" / "*_tafel.png")))[-hoechstens:]
        werte = []
        for i, pfad in enumerate(bilder):
            tafel = cv2.imread(pfad)
            if tafel is None:
                continue
            leinwand = np.zeros((1080, 1920, 3), dtype=np.uint8)
            h, w = tafel.shape[:2]
            if y0 + h > 1080 or x0 + w > 1920:
                continue
            leinwand[y0:y0 + h, x0:x0 + w] = tafel
            lesung = p.read_digits(Frame(i, 0.0, leinwand)).get("left_display")
            if lesung is not None and lesung.is_readable:
                werte.append(lesung.value)

        anteil = 100 * len(werte) / max(1, len(bilder))
        haeufig = dict(sorted(Counter(werte).most_common(4)))
        print(f"{lane.lane_id:<6}{len(werte):>6} / {len(bilder):<5} {anteil:>4.0f}%   {haeufig}")


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    ordner = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(LAUF)
    schreiben()
    print("Gegenprobe an den Tafelbildern des Laufs (Anzeige steht auf 00):")
    pruefen(ordner)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
