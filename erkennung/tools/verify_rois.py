"""Sichtpruefung der ROI-Platzierung.

Entzerrt eine Anzeigetafel und zeichnet die konfigurierten ROIs ein. Damit
laesst sich ohne GUI pruefen, ob die ROI-Positionen zum realen Material passen
-- die Grundlage fuer Prinzip P7 ("nicht raten, messen").

    python tools/verify_rois.py --video kegelVideos/xyz.mp4 --frame 90
    python tools/verify_rois.py --calibration data/calibrations/session.json

Ohne --calibration werden die Tafeln automatisch gesucht und das
Standard-ROI-Layout darueber gelegt.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration, PerspectiveTransform, Quad  # noqa: E402
from kegel_cv.calibration.session import default_roi_layout  # noqa: E402
from kegel_cv.calibration.roi_preview import (  # noqa: E402
    FARBEN as COLORS, roi_farbe as roi_color, zeichne_rois as draw_rois)
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.video.factory import open_source  # noqa: E402
from kegel_cv.video.source import VideoSourceError  # noqa: E402

def detect_boards(image: np.ndarray,
                  region: tuple[int, int, int, int] = (420, 20, 1080, 290),
                  ) -> list[tuple[int, int, int, int]]:
    """Sucht die Anzeigetafeln anhand ihres hellen, warmen Gehaeuses.

    Nur ein Startpunkt fuer die Analyse -- die verbindliche Kalibrierung macht
    der Nutzer per Klick.

    Die Maske erfasst das gesamte beige Gehaeuse einschliesslich des Rahmens um
    das untere Zeilendisplay. Eine Erweiterung nach unten waere also falsch und
    wuerde alle ROI-Positionen nach oben verschieben.
    """
    x0, y0, w0, h0 = region
    crop = image[y0:y0 + h0, x0:x0 + w0]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (10, 25, 120), (40, 120, 255))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boards: list[tuple[int, int, int, int]] = []
    for contour in contours:
        if cv2.contourArea(contour) < 4000:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        if not 0.6 < w / h < 1.6:
            continue
        # Das untere Zeilendisplay liegt ausserhalb der Beige-Maske:
        # Hoehe um ein Fuenftel erweitern, damit es mit erfasst wird.
        boards.append((x + x0, y + y0, w, h))

    return sorted(boards, key=lambda b: b[0])


def main() -> int:
    parser = argparse.ArgumentParser(description="ROI-Platzierung visuell pruefen")
    # KEIN `type=Path`: Windows macht aus "https://..." ein "https:/..." --
    # der doppelte Schraegstrich faellt beim Zusammenfassen weg, und die
    # Adresse ist hin. Streams und YouTube-Links kaemen so nie an.
    parser.add_argument("--video",
                        default="kegelVideos/2026-08-22 09-15-50.mp4")
    parser.add_argument("--frame", type=int, default=90)
    parser.add_argument("--calibration", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=Path("debug/roi_check"))
    parser.add_argument("--width", type=int, default=440)
    parser.add_argument("--height", type=int, default=530)
    args = parser.parse_args()

    # UEBER DIE QUELLENFABRIK, nicht ueber cv2 direkt. Sonst beantwortet
    # dieses Werkzeug die Frage "was ist das fuer eine Quelle" anders als die
    # Oberflaeche -- und eine YouTube-Adresse ist fuer cv2 nur eine Webseite.
    try:
        quelle = open_source(args.video, load_config())
        quelle.open()
    except VideoSourceError as exc:
        print(f"Video konnte nicht geoeffnet werden: {exc}", file=sys.stderr)
        return 1
    try:
        if args.frame and not quelle.seek(args.frame):
            # Ein Stream kennt keinen Ruecksprung -- dann eben vorspulen.
            for _ in range(args.frame):
                if quelle.read() is None:
                    break
        frame = quelle.read()
    finally:
        quelle.close()
    if frame is None:
        print(f"Frame {args.frame} konnte nicht gelesen werden", file=sys.stderr)
        return 1
    image = frame.image

    args.out.mkdir(parents=True, exist_ok=True)

    if args.calibration:
        calibration = Calibration.load(args.calibration)
        lanes = [(lane.lane_id, lane.to_quad(), lane.rois) for lane in calibration.lanes]
    else:
        rois = default_roi_layout()
        lanes = []
        for i, (x, y, w, h) in enumerate(detect_boards(image), start=1):
            quad = Quad.from_points([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
            lanes.append((i, quad, rois))
        print(f"{len(lanes)} Tafeln automatisch erkannt")

    for lane_id, quad, rois in lanes:
        transform = PerspectiveTransform(quad, args.width, args.height)
        warped = transform.warp(image)
        canvas = draw_rois(warped, rois)
        path = args.out / f"lane{lane_id}_frame{args.frame:06d}_rois.png"
        cv2.imwrite(str(path), canvas)
        print(f"Bahn {lane_id}: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
