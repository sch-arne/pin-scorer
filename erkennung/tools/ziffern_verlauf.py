"""Zeigt Frame fuer Frame, was die Tafel in einem Bereich WIRKLICH anzeigt.

WOZU: Bei jedem Streit ueber eine Ziffer fehlte bisher genau das Bild dazu.
Dieses Werkzeug legt einen Kontaktbogen an -- je Frame der Tafelausschnitt,
die Frame-Nummer und die gelesenen Ziffernfelder. Damit laesst sich
beantworten, was die Anzeige zu einem BESTIMMTEN Zeitpunkt zeigte, statt es
aus abgeleiteten Spalten zu erschliessen (genau daran scheiterten BUG-018 und
die Vorgaengerregel `discard_zero_throw_number`).

Die Frames des MESSFENSTERS lassen sich hervorheben (`--fenster`), damit
sichtbar wird, ob die Anzeige zum Messzeitpunkt schon umgeschaltet hatte.

AUFRUF:

    .venv/Scripts/python.exe tools/ziffern_verlauf.py \
        --source <Stream-URL> --calibration <Pfad> \
        --bahn 4 --von 126300 --bis 126650 --jeder 5 \
        --fenster 126325-126363 \
        --out debug/ziffern_verlauf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kegel_cv.analysis.lane_processor import LaneProcessor  # noqa: E402
from kegel_cv.calibration import Calibration  # noqa: E402
from kegel_cv.config.loader import load_config  # noqa: E402
from kegel_cv.video.factory import open_source  # noqa: E402

# Diese Felder interessieren bei einer Wurfnummer-Frage. Andere Felder
# bleiben aussen vor, damit der Bogen lesbar bleibt.
FELDER = ("throw_number", "pin_count", "total_b", "left_display")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--bahn", required=True, type=int, help="Anzeigenummer der Bahn")
    p.add_argument("--von", required=True, type=int)
    p.add_argument("--bis", required=True, type=int)
    p.add_argument("--jeder", type=int, default=5, help="nur jeden N-ten Frame (Standard 5)")
    p.add_argument("--fenster", default="", help="VON-BIS des Messfensters, wird markiert")
    p.add_argument("--spalten", type=int, default=6)
    p.add_argument("--out", type=Path, default=Path("debug/ziffern_verlauf"))
    a = p.parse_args()

    fenster = (0, -1)
    if a.fenster:
        v, b = a.fenster.split("-")
        fenster = (int(v), int(b))

    cfg = load_config()
    cal = Calibration.load(a.calibration)

    quelle = open_source(a.source, cfg)
    quelle.open()
    erster = quelle.read()
    lane = next(l for l in cal.lanes if l.display_number == a.bahn)
    proz = LaneProcessor(lane, cfg)
    if not proz.prepare(erster.image.shape):
        print(f"Bahn {a.bahn} nicht kalibrierbar")
        return 1

    quelle.seek(a.von)
    frame = quelle.read()
    kacheln, zeilen_text = [], []

    while frame is not None and frame.index <= a.bis:
        if (frame.index - a.von) % a.jeder == 0:
            lesungen = proz.read_digits(frame)
            werte = {}
            for name in FELDER:
                r = lesungen.get(name)
                werte[name] = (str(r.value) if r is not None and r.is_readable
                               else "--")
            lx, ly, lw, lh = proz.lane_box()
            tafel = frame.image[ly:ly + lh, lx:lx + lw].copy()
            kacheln.append((frame.index, tafel, werte))
            im_fenster = fenster[0] <= frame.index <= fenster[1]
            zeilen_text.append(
                f"F{frame.index:>7} {'[MESSFENSTER]' if im_fenster else '             '} "
                + "  ".join(f"{n}={werte[n]:>4}" for n in FELDER))
        frame = quelle.read()
    quelle.close()

    if not kacheln:
        print("Keine Frames gelesen -- Bereich oder Quelle pruefen")
        return 1

    print("\n".join(zeilen_text))

    # --- Kontaktbogen zeichnen ---
    breite_kachel = 380
    hoehe_bild = int(breite_kachel * kacheln[0][1].shape[0] / kacheln[0][1].shape[1])
    hoehe_text = 58
    hoehe_kachel = hoehe_bild + hoehe_text
    spalten = a.spalten
    reihen = (len(kacheln) + spalten - 1) // spalten
    bogen = np.full((reihen * hoehe_kachel, spalten * breite_kachel, 3), 30, np.uint8)

    for i, (idx, tafel, werte) in enumerate(kacheln):
        r, c = divmod(i, spalten)
        y0, x0 = r * hoehe_kachel, c * breite_kachel
        bogen[y0:y0 + hoehe_bild, x0:x0 + breite_kachel] = cv2.resize(
            tafel, (breite_kachel, hoehe_bild))
        im_fenster = fenster[0] <= idx <= fenster[1]
        if im_fenster:
            cv2.rectangle(bogen, (x0 + 1, y0 + 1),
                          (x0 + breite_kachel - 2, y0 + hoehe_bild - 2),
                          (0, 200, 255), 3)
        farbe = (0, 200, 255) if im_fenster else (200, 200, 200)
        cv2.putText(bogen, f"F{idx}" + ("  MESSFENSTER" if im_fenster else ""),
                    (x0 + 6, y0 + hoehe_bild + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, farbe, 1, cv2.LINE_AA)
        cv2.putText(bogen, f"Wurfnr={werte['throw_number']}  Kegel={werte['pin_count']}",
                    (x0 + 6, y0 + hoehe_bild + 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(bogen, f"Summe={werte['total_b']}  Fehlw={werte['left_display']}",
                    (x0 + 6, y0 + hoehe_bild + 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (170, 170, 170), 1, cv2.LINE_AA)

    a.out.mkdir(parents=True, exist_ok=True)
    ziel = a.out / f"bahn{a.bahn}_F{a.von}-{a.bis}.png"
    cv2.imwrite(str(ziel), bogen)
    print(f"\n{len(kacheln)} Frames -> {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
