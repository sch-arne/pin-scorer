"""Misst die Farbkanaele der Kegellampen je Bahn -- entscheidet Farbfragen.

WOZU: Bahn 4 liefert dreimal so viele unentschiedene Lampenmessungen wie
Bahn 2 (6-9 % gegen 0,3 %). Die naheliegende Vermutung war ein Farbstich, den
ein Weissabgleich beheben koennte. Aus Helligkeitswerten allein laesst sich das
nicht entscheiden -- die Lampenspur schreibt nur `value`, nicht die Kanaele.

DAS MASS, das die Frage entscheidet: Der Detektor misst
`value = max(B, G, R)` ueber den hellen ROI-Kern (`WarmthLampDetector.score`).
Ein Weissabgleich skaliert die Kanaele je einzeln. Er kann den Messwert also
nur dann verschieben, wenn bei AUS ein ANDERER Kanal dominiert als bei AN.

GEMESSEN am 2026-09-01 ueber 5400 Messungen (Frames 15000-30000, alle 100):
Rot ist in 99,7 bis 100 % aller Faelle der groesste Kanal -- auf jeder Bahn,
bei AUS wie bei AN. `max(B,G,R)` haengt damit ausschliesslich am Rotkanal.
Blau und Gruen zu skalieren aendert den Messwert nicht, Rot zu skalieren
verschiebt AUS und AN gemeinsam. **Ein Weissabgleich kann hier nichts
bewirken.**

Bahn 4 ist nicht farbstichig, sondern gleichmaessig aufgehellt:

    Bahn 2 AUS   B 120,0   G 128,4   R 147,9
    Bahn 4 AUS   B 159,6   G 163,0   R 181,1     (rund +34 auf jedem Kanal)

Das ist ein Schwarzwert-Versatz, und der ist additiv. Ein Weissabgleich ist
multiplikativ -- er ist das falsche Werkzeug fuer diese Form von Fehler.

AUFRUF:

    .venv/Scripts/python.exe tools/measure_lamp_channels.py \
        --source <Datei oder Stream-URL> \
        --calibration data/calibrations/1Spieltag.json \
        --von 15000 --bis 30000 --schritt 100

ACHTUNG: Die Kalibrierung gehoert zu EINER Quelle. Die Overlay-Position
variiert zwischen Sessions -- auf fremdem Material sitzen die ROIs daneben.
Darum warnt das Werkzeug am Ende, wenn keine einzige Messung den AN-Bereich
erreicht: dann sind alle Zahlen wertlos.
"""

from __future__ import annotations

import argparse
import collections
import csv
import statistics as st
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration, norm_rect_to_frame_bbox  # noqa: E402

# Wie im WarmthLampDetector: nur der helle Kern des ROI zaehlt, der Rand ist
# Gehaeuse. Ein Mittelwert ueber alles wuerde das Signal verwaessern.
CORE_PERCENTILE = 70.0

# Grenzen fuer die Einordnung. Gemessen: die AN-Wolke sitzt bei 246-255, die
# AUS-Wolke reicht bis 214. Dazwischen liegt die Totzone.
AN_AB, AUS_BIS = 240.0, 215.0

# Die Kalibrierung zaehlt die Tafeln 1..4, der Sport zaehlt die Bahnen 2..5.
REALE_BAHN = {1: 2, 2: 3, 3: 4, 4: 5}


def kern_kanaele(patch: np.ndarray) -> tuple[float, float, float, float] | None:
    """(B, G, R, value) gemittelt ueber den hellen Kern -- wie der Detektor."""
    if patch is None or patch.size == 0:
        return None
    value = patch.max(axis=2).astype(np.float32)
    kern = value >= np.percentile(value, CORE_PERCENTILE)
    if not kern.any():
        kern = np.ones_like(value, dtype=bool)
    b, g, r = (patch[:, :, i].astype(np.float32) for i in range(3))
    return (float(b[kern].mean()), float(g[kern].mean()),
            float(r[kern].mean()), float(value[kern].mean()))


def messen(quelle: str, kalibrierung: Path, von: int, bis: int,
           schritt: int) -> list[tuple]:
    """Liest die Quelle sequentiell und misst jeden `schritt`-ten Frame."""
    cal = Calibration.load(kalibrierung)
    transforms = {lane.lane_id: lane.transform(440, 530) for lane in cal.lanes}

    cap = cv2.VideoCapture(quelle)
    if not cap.isOpened():
        raise SystemExit(f"Quelle nicht lesbar: {quelle}")

    zeilen: list[tuple] = []
    frame = 0
    try:
        while frame < bis:
            if not cap.grab():
                print(f"Quelle endet bei Frame {frame}")
                break
            if frame >= von and (frame - von) % schritt == 0:
                ok, bild = cap.retrieve()
                if ok:
                    for lane in cal.lanes:
                        for roi in lane.pin_lamps():
                            x, y, w, h = norm_rect_to_frame_bbox(
                                transforms[lane.lane_id], roi.rect, bild.shape)
                            if w <= 0 or h <= 0:
                                continue
                            werte = kern_kanaele(bild[y:y + h, x:x + w])
                            if werte is None:
                                continue
                            zeilen.append((
                                frame,
                                REALE_BAHN.get(lane.lane_id, lane.lane_id),
                                roi.name.removeprefix("pin_lamp_"),
                                *(round(wert, 2) for wert in werte)))
                if (frame - von) % (schritt * 20) == 0:
                    print(f"  Frame {frame} ... {len(zeilen)} Messungen",
                          flush=True)
            frame += 1
    finally:
        cap.release()
    return zeilen


def auswerten(zeilen: list[tuple]) -> None:
    """Kanalmittel je Bahn und Zustand, und wer `max(B,G,R)` traegt."""
    nach = collections.defaultdict(lambda: collections.defaultdict(list))
    dominant: collections.Counter = collections.Counter()
    anzahl: collections.Counter = collections.Counter()
    for _, bahn, _, blau, gruen, rot, value in zeilen:
        zustand = ("AN" if value >= AN_AB
                   else "AUS" if value <= AUS_BIS else "Totzone")
        for name, wert in (("B", blau), ("G", gruen),
                           ("R", rot), ("value", value)):
            nach[(bahn, zustand)][name].append(wert)
        anzahl[(bahn, zustand)] += 1
        groesster = max((("B", blau), ("G", gruen), ("R", rot)),
                        key=lambda paar: paar[1])[0]
        dominant[(bahn, zustand, groesster)] += 1

    bahnen = sorted({zeile[1] for zeile in zeilen})

    print("\n=== Kanalmittel je Bahn und Zustand ===")
    print(f"{'Bahn':>4} {'Zustand':>8} {'n':>6} {'B':>7} {'G':>7} {'R':>7} "
          f"{'value':>7} {'B/R':>6}")
    for bahn in bahnen:
        for zustand in ("AUS", "Totzone", "AN"):
            werte = nach[(bahn, zustand)]
            if not werte["value"]:
                continue
            mittel = {c: st.median(werte[c]) for c in ("B", "G", "R", "value")}
            print(f"{bahn:>4} {zustand:>8} {anzahl[(bahn, zustand)]:>6} "
                  f"{mittel['B']:>7.1f} {mittel['G']:>7.1f} "
                  f"{mittel['R']:>7.1f} {mittel['value']:>7.1f} "
                  f"{mittel['B'] / max(mittel['R'], 1):>6.2f}")
        print()

    print("=== Traegt bei AUS ein anderer Kanal als bei AN? ===")
    print("Nur dann kann ein Weissabgleich den Kontrast veraendern.")
    print(f"{'Bahn':>4} {'AUS':>9} {'Totzone':>9} {'AN':>9}"
          "   (Anteil ROT groesster Kanal)")
    for bahn in bahnen:
        spalten = []
        for zustand in ("AUS", "Totzone", "AN"):
            gesamt = anzahl[(bahn, zustand)]
            spalten.append(
                f"{100.0 * dominant[(bahn, zustand, 'R')] / gesamt:>8.1f}%"
                if gesamt else f"{'-':>9}")
        print(f"{bahn:>4} " + " ".join(spalten))

    print("\n=== Kontrast (Median AN minus Median AUS) ===")
    for bahn in bahnen:
        an = nach[(bahn, "AN")]["value"]
        aus = nach[(bahn, "AUS")]["value"]
        if an and aus:
            print(f"  Bahn {bahn}: {st.median(an) - st.median(aus):>6.1f}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--von", type=int, default=15000)
    parser.add_argument("--bis", type=int, default=30000)
    parser.add_argument("--schritt", type=int, default=100)
    parser.add_argument("--csv", type=Path, default=None,
                        help="Rohwerte zusaetzlich hierhin schreiben")
    args = parser.parse_args()

    zeilen = messen(args.source, args.calibration,
                    args.von, args.bis, args.schritt)
    if not zeilen:
        print("Keine Messungen -- sitzt die Kalibrierung auf dieser Quelle?")
        return 1

    if args.csv:
        with args.csv.open("w", encoding="utf-8", newline="") as datei:
            schreiber = csv.writer(datei, delimiter=";")
            schreiber.writerow(["Frame", "Bahn", "Kegel", "B", "G", "R", "value"])
            schreiber.writerows(zeilen)
        print(f"Rohwerte: {args.csv}")

    auswerten(zeilen)

    hellste = max(zeile[6] for zeile in zeilen)
    if hellste < AN_AB:
        print(f"\nWARNUNG: keine Messung erreicht {AN_AB:.0f} (hoechster Wert "
              f"{hellste:.1f}). Vermutlich sitzt die Kalibrierung nicht auf "
              "dieser Quelle -- dann sind alle Zahlen oben wertlos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
