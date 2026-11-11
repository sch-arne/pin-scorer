"""Uebertraegt eine Kalibrierung auf eine Aufnahme mit anderer Kameraposition.

WOZU: Die ROIs stehen in TAFELKOORDINATEN (0..1 je Anzeigetafel) -- alle
Handarbeit steckt also im Inneren der Tafel und ist von der Kameraposition
unabhaengig. Nur die vier Eckpunkte je Bahn sind Pixelkoordinaten, und nur die
aendern sich, wenn die Kamera verstellt wurde.

GEMESSEN 2026-08-31 an zwei Aufnahmen derselben Halle:

    alte Aufnahme   Tafeln bei x  534 .. 1380
    neue Aufnahme   Tafeln bei x  464 .. 1452

Die Verschiebung ist nicht einheitlich (Bahn 2 wandert 70 px nach links,
Bahn 5 68 px nach rechts) -- die Kamera wurde also nicht nur verschoben,
sondern auch anders gezoomt. Ein fester Versatz traegt nicht.

DAS GUETEMASS, ohne das jede Anpassung geraten waere -- dieselben zwei
Groessen, die schon `fit_digit_offsets.py` benutzt:

    1. Die gruene Lampe muss ueberhaupt Gruen sehen. Sitzt die Tafel falsch,
       ist der Score null (das ist die Verdeckungserkennung, die dann dauernd
       ausloest).
    2. Die fuehrende Stelle eines mehrstelligen Feldes ist auf dieser Tafel
       IMMER null (Wurfnummern 001-030, Summen 0-270). Eine Lesung, bei der
       sie nicht null ist, ist nachweislich falsch -- ohne dass man den wahren
       Wert kennen muss.

Gesucht wird die Verschiebung und Streckung, die beide Groessen zugleich am
besten macht. Die Form des Vierecks bleibt dabei erhalten: Die perspektivische
Verzerrung der Tafel aendert sich beim Zoomen kaum, und sie neu zu schaetzen
haette weit mehr Freiheitsgrade als Messpunkte.

Das Werkzeug schreibt immer eine NEUE Datei.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration, PerspectiveTransform, Quad  # noqa: E402
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.detection.digit_reader import CalibratedDigitReader  # noqa: E402
from kegel_cv.detection.lamp_detectors import HsvGreenDetector  # noqa: E402

FELDER = ("throw_number", "total_b")


def verschoben(quad: list, dx: float, dy: float, sx: float, sy: float) -> list:
    """Viereck um seinen Mittelpunkt strecken und dann verschieben."""
    p = np.array(quad, dtype=np.float64)
    mx, my = p[:, 0].mean(), p[:, 1].mean()
    p[:, 0] = mx + (p[:, 0] - mx) * sx + dx
    p[:, 1] = my + (p[:, 1] - my) * sy + dy
    return p.tolist()


def bewerten(lane, quad, bilder, leser, gruen) -> tuple[float, float, float]:
    """(Gesamtguete, Gruenanteil, Anteil plausibler Ziffernlesungen)."""
    lane.quad = quad
    tf = lane.transform(bilder[0].shape[1], bilder[0].shape[0])
    g_roi = lane.get_roi("green_lamp")

    gruenwerte = []
    lesbar = plausibel = 0
    for bild in bilder:
        if g_roi is not None:
            bx, by, bw, bh = norm_rect_to_frame_bbox(tf, g_roi.rect, bild.shape)
            if bw > 0 and bh > 0:
                gruenwerte.append(gruen.score(bild[by:by + bh, bx:bx + bw]))
        for feld in FELDER:
            zellen = lane.digit_rois(feld)
            if len(zellen) < 2:
                continue
            stuecke = []
            for z in zellen:
                bx, by, bw, bh = norm_rect_to_frame_bbox(tf, z.rect, bild.shape)
                stuecke.append(bild[by:by + bh, bx:bx + bw])
            lesung = leser.read_field(stuecke)
            if not lesung.is_readable:
                continue
            lesbar += 1
            if lesung.text[0] == "0":
                plausibel += 1

    # Die gruene Lampe: Ihr Score darf nicht null sein (dann liegt die ROI
    # neben der Tafel), und er soll ueber die Bilder streuen -- eine Lampe,
    # die mal an und mal aus ist, belegt die richtige Stelle besser als ein
    # konstanter Wert irgendwo auf dem Gehaeuse.
    if gruenwerte:
        g = np.array(gruenwerte)
        gruen_gut = float((g > 5).mean()) * min(1.0, float(g.std()) / 10.0 + 0.5)
    else:
        gruen_gut = 0.0
    ziffern_gut = plausibel / max(1, lesbar)
    # Wenig lesbare Felder sind selbst ein schlechtes Zeichen.
    dichte = lesbar / max(1, len(bilder) * len(FELDER))
    return gruen_gut + ziffern_gut + 0.5 * dichte, gruen_gut, ziffern_gut


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path,
                   help="Kalibrierung, deren ROI-Layout uebernommen wird")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--frames", default="50000,90000,130000,170000,210000,250000",
                   help="Stichproben ueber die Aufnahme verteilt")
    p.add_argument("--span", type=float, default=90.0,
                   help="wie weit die Suche in Pixeln geht")
    a = p.parse_args()

    cal = Calibration.load(a.calibration)
    cfg = load_config()
    leser = CalibratedDigitReader(cfg.detection.digits)
    gruen = HsvGreenDetector(cfg.detection.green)

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 20000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 15000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")
    bilder = []
    for n in (int(x) for x in a.frames.split(",")):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(n))
        ok, bild = cap.read()
        if ok and bild is not None:
            bilder.append(bild)
    cap.release()
    if not bilder:
        raise SystemExit("Keine Frames gelesen")
    print(f"{len(bilder)} Stichproben geladen\n")

    roh = json.loads(a.calibration.read_text(encoding="utf-8"))
    for lane, roh_lane in zip(cal.lanes, roh["lanes"]):
        ausgang = [list(p) for p in lane.quad]
        bester = (None, -1.0, 0.0, 0.0)
        # Grob, dann fein -- eine vollstaendige Suche ueber vier Groessen
        # waere hier weder noetig noch bezahlbar.
        for stufe, (schritt, spanne) in enumerate(
                ((12.0, a.span), (4.0, 24.0), (1.0, 6.0))):
            mitte = bester[0] if bester[0] is not None else ausgang
            for dx in np.arange(-spanne, spanne + 1, schritt):
                for dy in np.arange(-spanne / 2, spanne / 2 + 1, schritt):
                    for s in (0.90, 0.95, 1.00, 1.05, 1.10) if stufe == 0 else (1.0,):
                        kandidat = verschoben(mitte, dx, dy, s, s)
                        note, g, z = bewerten(lane, kandidat, bilder, leser, gruen)
                        if note > bester[1]:
                            bester = (kandidat, note, g, z)
        lane.quad = bester[0]
        roh_lane["quad"] = [[round(x, 4), round(y, 4)] for x, y in bester[0]]
        xs = [x for x, _ in bester[0]]
        ys = [y for _, y in bester[0]]
        print(f"  Bahn {lane.display_number}: x {min(xs):.0f}-{max(xs):.0f}  "
              f"y {min(ys):.0f}-{max(ys):.0f}   Note {bester[1]:.2f}  "
              f"(gruen {bester[2]:.2f}, Ziffern {bester[3]:.0%})")

    roh["name"] = f"{roh.get('name', '')} (Eckpunkte neu gefittet)".strip()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(roh, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"\nGeschrieben: {a.out}")
    print("PRUEFEN: tools/export_roi_frames.py mit dieser Datei -- das Auge "
          "entscheidet, ob die Rahmen sitzen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
