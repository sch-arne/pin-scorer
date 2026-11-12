"""Misst, wann die untere Reihe auf `000  0000` steht -- unabhaengig von der Pipeline.

WOZU: Die Spielwechsel-Erkennung zaehlt bei nahezu gleicher Wurfzahl (~370 je
Bahn) voellig verschieden viele Spielenden -- Bahn 2 nur 2, Bahn 3 dreizehn.
Zugleich meldet sie manche zweimal. Beides kann zwei ganz verschiedene Ursachen
haben, und aus dem Ergebnis allein sind sie nicht zu trennen:

    (a) Die Tafel zeigt den Nullzustand gar nicht -- oder nicht lesbar.
    (b) Die Tafel zeigt ihn, aber die Pipeline sieht in diesem Moment nicht hin.

Der Unterschied ist entscheidend: Bei (a) waere die Ziffernerkennung schuld,
bei (b) die Bedingung, unter der ueberhaupt gelesen wird. Heute liest die
Pipeline die spaeten Felder NUR, solange das Wurffenster offen ist -- also
zwischen GREEN_OFF und dem naechsten GREEN_ON.

Dieses Werkzeug liest dieselben zwei Felder OHNE jede Bedingung, Frame fuer
Frame, fuer alle vier Bahnen. Damit steht fest, was die Tafel gezeigt hat, und
die Frage nach dem Warum wird beantwortbar statt vermutbar.

Ausgegeben werden die zusammenhaengenden Abschnitte, in denen Wurfnummer UND
Summe null zeigen: Beginn, Ende, Dauer, und wie zuverlaessig darin gelesen wurde.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration  # noqa: E402
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.detection.digit_reader import CalibratedDigitReader  # noqa: E402

FELDER = ("throw_number", "total_b")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--from-frame", type=int, required=True)
    p.add_argument("--to-frame", type=int, required=True)
    p.add_argument("--every", type=int, default=5)
    # Eine Luecke von so vielen Frames trennt zwei Abschnitte. Grosszuegig, weil
    # eine einzelne unlesbare Messung keinen Abschnitt zerreissen darf.
    p.add_argument("--gap", type=int, default=250)
    p.add_argument("--csv", type=Path, default=None)
    a = p.parse_args()

    cal = Calibration.load(a.calibration)
    cfg = load_config()
    leser = CalibratedDigitReader(cfg.detection.digits)

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 20000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 15000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")
    cap.set(cv2.CAP_PROP_POS_FRAMES, float(a.from_frame))

    tfs: dict[int, object] = {}
    zeilen: list[dict] = []
    # Je Bahn: Messungen und wie viele davon null zeigten
    treffer: dict[int, list[int]] = {}
    gelesen: dict[int, int] = {}
    gesamt: dict[int, int] = {}

    n = a.from_frame
    while n <= a.to_frame:
        ok, bild = cap.read()
        if not ok:
            break
        if (n - a.from_frame) % a.every == 0:
            zeile = {"Frame": n}
            for lane in cal.lanes:
                bahn = lane.display_number
                if bahn not in tfs:
                    tfs[bahn] = lane.transform(bild.shape[1], bild.shape[0])
                    treffer[bahn], gelesen[bahn], gesamt[bahn] = [], 0, 0
                tf = tfs[bahn]
                werte = {}
                for feld in FELDER:
                    zellen = lane.digit_rois(feld)
                    if not zellen:
                        werte[feld] = None
                        continue
                    stuecke = []
                    for z in zellen:
                        bx, by, bw, bh = norm_rect_to_frame_bbox(
                            tf, z.rect, bild.shape)
                        stuecke.append(bild[by:by + bh, bx:bx + bw])
                    lesung = leser.read_field(stuecke)
                    werte[feld] = lesung.value if lesung.is_readable else None
                    zeile[f"B{bahn}_{feld}"] = ("" if werte[feld] is None
                                                else werte[feld])
                gesamt[bahn] += 1
                if all(v is not None for v in werte.values()):
                    gelesen[bahn] += 1
                if all(v == 0 for v in werte.values()):
                    treffer[bahn].append(n)
            zeilen.append(zeile)
        n += 1
    cap.release()

    print(f"Frames {a.from_frame}-{n - 1}, jeder {a.every}. gemessen\n")
    print(f"  {'Bahn':>5} {'Messungen':>10} {'beide lesbar':>13} "
          f"{'davon 000/0000':>15}")
    for bahn in sorted(gesamt):
        print(f"  {bahn:>5} {gesamt[bahn]:>10} "
              f"{gelesen[bahn] / max(1, gesamt[bahn]):>12.1%} "
              f"{len(treffer[bahn]):>15}")

    print("\nZusammenhaengende Abschnitte mit 000/0000:")
    for bahn in sorted(treffer):
        abschnitte: list[list[int]] = []
        for f in treffer[bahn]:
            if abschnitte and f - abschnitte[-1][-1] <= a.gap:
                abschnitte[-1].append(f)
            else:
                abschnitte.append([f])
        if not abschnitte:
            print(f"  Bahn {bahn}: keiner")
            continue
        for ab in abschnitte:
            dauer = ab[-1] - ab[0]
            moeglich = dauer // a.every + 1
            print(f"  Bahn {bahn}: F{ab[0]}-F{ab[-1]}  {dauer:>5} Frames "
                  f"({dauer / 25:>5.1f} s)  {len(ab)}/{moeglich} Messungen "
                  f"zeigten null")

    if a.csv and zeilen:
        a.csv.parent.mkdir(parents=True, exist_ok=True)
        spalten = sorted({k for z in zeilen for k in z} - {"Frame"})
        with a.csv.open("w", encoding="utf-8-sig", newline="") as d:
            s = csv.DictWriter(d, fieldnames=["Frame"] + spalten, delimiter=";")
            s.writeheader()
            s.writerows(zeilen)
        print(f"\nGeschrieben: {a.csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
