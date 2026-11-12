"""Sind die Ziffern ueberhaupt trennbar? Ohne Segmentlogik nachgesehen.

WOZU -- Einwand des Nutzers am 2026-08-30: "die Ziffern erkennt sprichwoertlich
ein blinder Mensch". Die Messung gibt ihm recht. Von 4320 beleuchteten
Ziffernzellen ergaben nur 58 % ein GUELTIGES Sieben-Segment-Muster:

    gelesen               2504   58,0 %
    gelesen (geraten)     1388   32,1 %   <- Muster existiert nicht, es wird
    Helligkeitssperre      422    9,8 %      auf das naechstliegende geraten
    kein Muster              4    0,1 %
    mehrdeutig               2    0,0 %

Ein Drittel aller Lesungen ist also keine Lesung, sondern eine Reparatur: Die
gemessenen Segmente ergeben kein bekanntes Muster, und es wird die Ziffer
genommen, die genau ein Segment entfernt liegt. Auf einem 7-Segment-Code liegen
viele Ziffernpaare genau einen Schritt auseinander (0/8, 8/9, 3/9, 5/6) -- die
Reparatur ist dort ein Muenzwurf, der als Ergebnis auftritt.

Die Schwaeche liegt damit NICHT bei der Bildqualitaet, sondern beim Abtasten:
Die Segmentflaechen werden geometrisch aus der Zellenbox abgeleitet (Drittel
waagerecht, Haelften senkrecht). Bei 8x14 px je Ziffer ist ein senkrechtes
Segment rund 2 px breit -- ein Versatz von einem Pixel verschiebt die Messung
um die halbe Segmentbreite.

DIESES WERKZEUG ENTSCHEIDET NICHTS. Es prueft nur die Vorfrage, ohne die jeder
neue Erkenner geraten waere: Bilden die Zellen im Bild ueberhaupt saubere,
trennbare Formen? Dazu werden die binaeren Masken gesammelt, auf eine
einheitliche Groesse gebracht und OHNE jede Segmentlogik geclustert. Sind die
Cluster sauber, traegt ein Naechster-Nachbar-Erkenner -- und zwar ohne dass
irgendwo eine Segmentschwelle geraten werden muesste.

Ausgegeben wird zusaetzlich ein Bild der Cluster-Mittelpunkte. Nur daran laesst
sich mit dem Auge pruefen, welche Ziffer ein Cluster ist.
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
from kegel_cv.detection.digit_detector import SevenSegmentDetector  # noqa: E402
from kegel_cv.detection.digit_reader import CalibratedDigitReader  # noqa: E402

FELDER = ("throw_number", "pin_count", "total_a", "total_b", "left_display")
# Ab hier gilt eine Zelle als beleuchtet (gemessen: dunkel 114-119,
# leuchtend 246-255).
LEUCHTET_AB = 200
# Groesse, auf die jede Maske gebracht wird. Bewusst groesser als das Original
# (8x14): Beim Verkleinern gingen die duennen Segmente verloren.
BREITE, HOEHE = 12, 20


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--blocks", default="40000,120000,200000,280000")
    p.add_argument("--block-length", type=int, default=1200)
    p.add_argument("--every", type=int, default=8)
    p.add_argument("--clusters", type=int, default=14,
                   help="mehr als zehn: manche Ziffer hat zwei Schreibweisen")
    p.add_argument("--out", type=Path, default=Path("debug/ziffer_cluster"))
    a = p.parse_args()

    cal = Calibration.load(a.calibration)
    cfg = load_config()
    leser = CalibratedDigitReader(cfg.detection.digits)
    vor = SevenSegmentDetector(cfg.detection.digits)

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 20000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 15000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")

    formen: list[np.ndarray] = []
    lesungen: list[str] = []
    tfs: dict[int, object] = {}

    for start in (int(x) for x in a.blocks.split(",")):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(start))
        for k in range(a.block_length):
            ok, bild = cap.read()
            if not ok:
                break
            if k % a.every:
                continue
            for lane in cal.lanes:
                if lane.display_number not in tfs:
                    tfs[lane.display_number] = lane.transform(bild.shape[1],
                                                              bild.shape[0])
                tf = tfs[lane.display_number]
                for feld in FELDER:
                    for zelle in lane.digit_rois(feld):
                        bx, by, bw, bh = norm_rect_to_frame_bbox(
                            tf, zelle.rect, bild.shape)
                        patch = bild[by:by + bh, bx:bx + bw]
                        if patch.size == 0:
                            continue
                        if int(patch[:, :, 2].max()) < LEUCHTET_AB:
                            continue
                        maske = vor._red_mask(patch)
                        if maske.max() == 0:
                            continue
                        beschnitten = vor._trim_vertical(maske)
                        if beschnitten.size and beschnitten.max() > 0:
                            maske = beschnitten
                        form = cv2.resize(maske, (BREITE, HOEHE),
                                          interpolation=cv2.INTER_AREA)
                        formen.append(form.astype(np.float32).ravel() / 255.0)
                        zeichen, _, _ = leser.read_digit_full(patch)
                        lesungen.append(zeichen)
    cap.release()

    if len(formen) < a.clusters * 10:
        raise SystemExit(f"Nur {len(formen)} Zellen -- zu wenig")
    daten = np.vstack(formen)
    print(f"{len(daten)} beleuchtete Ziffernzellen gesammelt\n")

    kriterium = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 60, 0.5)
    _, marken, mitten = cv2.kmeans(daten, a.clusters, None, kriterium, 8,
                                   cv2.KMEANS_PP_CENTERS)
    marken = marken.ravel()

    # Wie einig ist sich ein Cluster? Das ist die eigentliche Antwort: Sind die
    # Formen trennbar, faellt in einem Cluster fast nur EIN Zeichen an --
    # einschliesslich der Zellen, die heute nur geraten werden.
    print(f"  {'Cluster':>8} {'Zellen':>7} {'haeufigste Lesung':>18} "
          f"{'Anteil':>7}  Verteilung")
    rein_gesamt = 0
    for c in range(a.clusters):
        maske = marken == c
        n = int(maske.sum())
        if not n:
            continue
        zaehler = collections.Counter(np.array(lesungen)[maske])
        zeichen, wie_oft = zaehler.most_common(1)[0]
        rein_gesamt += wie_oft
        rest = "  ".join(f"{z}:{m}" for z, m in zaehler.most_common(5))
        print(f"  {c:>8} {n:>7} {zeichen:>18} {wie_oft / n:>6.1%}  {rest}")
    print(f"\nGewichtete Reinheit gegenueber der heutigen Lesung: "
          f"{rein_gesamt / len(daten):.1%}")
    print("Ein hoher Wert heisst: Die Formen sind trennbar, und die heutige "
          "Lesung\nist dort, wo sie funktioniert, mit der Form einig.")

    # Bild der Mittelpunkte -- nur mit dem Auge zu beurteilen.
    a.out.mkdir(parents=True, exist_ok=True)
    zoom = 8
    kacheln = []
    for c in range(a.clusters):
        bild = (mitten[c].reshape(HOEHE, BREITE) * 255).astype(np.uint8)
        gross = cv2.resize(bild, (BREITE * zoom, HOEHE * zoom),
                           interpolation=cv2.INTER_NEAREST)
        gross = cv2.cvtColor(gross, cv2.COLOR_GRAY2BGR)
        kopf = np.zeros((22, gross.shape[1], 3), np.uint8)
        n = int((marken == c).sum())
        cv2.putText(kopf, f"{c}  n={n}", (3, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (255, 255, 255), 1, cv2.LINE_AA)
        kacheln.append(cv2.copyMakeBorder(np.vstack([kopf, gross]), 3, 3, 3, 3,
                                          cv2.BORDER_CONSTANT, value=(70, 70, 70)))
    pfad = a.out / "mittelpunkte.png"
    cv2.imwrite(str(pfad), np.hstack(kacheln))
    print(f"\nMittelpunkte: {pfad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
