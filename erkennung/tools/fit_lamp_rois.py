"""Zentriert die Kegellampen-ROIs auf die Lampe und verkleinert sie -- als neue Datei.

WOZU -- gemessen am 2026-09-01 mit `tools/measure_roi_shrink.py` ueber 10 800
Ausschnitte: Die Kegellampen-ROIs sind 12 x 11 Pixel gross, und die Lampe sitzt
darin im Median 4 bis 10 % oberhalb und links der Mitte, im Extremfall 15 %
daneben. Der Rahmen faengt deshalb Gehaeuse mit, das bei heller Ausleuchtung
den AUS-Wert hebt -- besonders auf Bahn 4.

Trennluecke `p5(AN) - p95(AUS)` auf Bahn 4, dem knappsten Fall:

    heute (voller Rahmen, core_percentile 70)     44,8 frueh / 33,7 spaet
    50 % Zuschnitt, zentriert, ohne Kernfilter    61,8 frueh / 44,8 spaet

ZWEI DINGE GEHOEREN ZUSAMMEN, sonst verpufft die Haelfte:

1. **Verkleinern UND nachzentrieren.** Bei 80 % Zuschnitt bringt geometrisches
   Zentrieren 49,0, das Zentrieren auf die gemessene Lampenmitte 54,3.
2. **Den Kernfilter abschalten** (`core_percentile: 0`). Er ist ein Notbehelf
   fuer einen zu weiten Rahmen: Bei vollem Rahmen braucht es ihn (44,8 mit,
   16,3 ohne), bei engem schadet er (42,1 mit, 61,8 ohne) -- er nimmt einer
   ohnehin kleinen Pixelmenge nochmals 70 %.

Die Einblendung wandert ueber 2,6 Stunden um hoechstens 4,8 % der
Kantenlaenge; ein 50 %-Zuschnitt laesst 25 % Rand je Seite und hat davon
reichlich Reserve.

WORAUF DER SCHWERPUNKT BERUHT: nur auf LEUCHTENDEN Messungen. Bei
ausgeschalteter Lampe ist im Rahmen nichts, woran sich eine Mitte festmachen
liesse -- solche Frames wuerden sie verrauschen.

GENAUIGKEITSGRENZE: `norm_rect_to_frame_bbox` rundet auf ganze Pixel. Bei
12 Pixeln Kantenlaenge sind das bis zu 4 % Unschaerfe bei der Ruecrechnung in
normierte Koordinaten -- klein gegen den gemessenen Versatz, aber nicht null.

Das Werkzeug schreibt IMMER eine neue Datei. Die Kalibrierung ist Handarbeit
des Nutzers; sie wird nicht ueberschrieben, solange kein Lauf die Aenderung
bestaetigt hat.

AUFRUF:

    .venv/Scripts/python.exe tools/fit_lamp_rois.py \
        --calibration data/calibrations/1Spieltag.json \
        --patches debug/roi_proben/patches_frueh.pkl \
                  debug/roi_proben/patches_spaet.pkl \
        --faktor 0.5 \
        --out data/calibrations/1Spieltag_enge_lampen.json

Die Ausschnitte entstehen mit `tools/measure_roi_shrink.py sammeln`.
"""

from __future__ import annotations

import argparse
import json
import pickle
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np

LAMP_PREFIX = "pin_lamp_"

# Ab hier gilt eine Messung als leuchtend. Gemessen: die AN-Wolke sitzt bei
# 246-255, die AUS-Wolke reicht bis 214.
AN_AB = 240.0


def hell_schwerpunkt(patch: np.ndarray) -> tuple[float, float]:
    """Schwerpunkt der hellsten Pixel (y, x) in Patch-Koordinaten."""
    value = patch.max(axis=2).astype(np.float32)
    hell = value >= np.percentile(value, 90.0)
    if not hell.any():
        return (patch.shape[0] / 2.0, patch.shape[1] / 2.0)
    ys, xs = np.nonzero(hell)
    return (float(ys.mean()), float(xs.mean()))


def kern_value(patch: np.ndarray) -> float:
    """Helligkeit wie der heutige Detektor -- nur zum Einordnen AN/AUS."""
    value = patch.max(axis=2).astype(np.float32)
    kern = value >= np.percentile(value, 70.0)
    if not kern.any():
        kern = np.ones_like(value, dtype=bool)
    return float(value[kern].mean())


def schwerpunkte(dateien: list[Path]) -> dict:
    """(Bahn, Lampenname) -> (cy, cx, hoehe, breite) in Patch-Pixeln."""
    roh = defaultdict(list)
    groessen = {}
    for pfad in dateien:
        with pfad.open("rb") as datei:
            for _, bahn, lampe, patch in pickle.load(datei):
                groessen[(bahn, lampe)] = patch.shape[:2]
                if kern_value(patch) >= AN_AB:
                    roh[(bahn, lampe)].append(hell_schwerpunkt(patch))

    ergebnis = {}
    for schluessel, punkte in roh.items():
        if len(punkte) < 5:
            continue
        hoehe, breite = groessen[schluessel]
        ergebnis[schluessel] = (st.median([p[0] for p in punkte]),
                                st.median([p[1] for p in punkte]),
                                hoehe, breite)
    return ergebnis


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--patches", required=True, nargs="+", type=Path)
    parser.add_argument("--faktor", type=float, default=0.5,
                        help="Kantenlaenge des neuen ROI, Anteil des alten "
                             "(Standard 0,5)")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    if not 0.1 <= args.faktor <= 1.0:
        print("--faktor muss zwischen 0,1 und 1,0 liegen")
        return 1
    if args.out.exists():
        print(f"{args.out} gibt es schon -- eine bestehende Kalibrierung "
              "wird nicht ueberschrieben.")
        return 1

    for pfad in args.patches:
        if not pfad.is_file():
            print(f"fehlt: {pfad}")
            return 1

    mitten = schwerpunkte(args.patches)
    if not mitten:
        print("Keine leuchtenden Messungen gefunden -- passen die Ausschnitte "
              "zu dieser Kalibrierung?")
        return 1

    with args.calibration.open(encoding="utf-8") as datei:
        kalib = json.load(datei)

    print(f"{'Bahn':>4} {'Lampe':>7} {'Versatz x':>11} {'Versatz y':>11} "
          f"{'neu w':>8} {'neu h':>8}")
    geaendert = ohne_messung = 0
    for lane in kalib["lanes"]:
        bahn = lane.get("real_lane_number", lane["lane_id"])
        for roi in lane["rois"]:
            if not roi["name"].startswith(LAMP_PREFIX):
                continue
            schluessel = (bahn, roi["name"].removeprefix(LAMP_PREFIX))
            if schluessel not in mitten:
                ohne_messung += 1
                continue

            cy, cx, hoehe_px, breite_px = mitten[schluessel]
            x, y, w, h = roi["rect"]

            # Patch-Pixel zurueck in normierte Koordinaten: Der Ausschnitt
            # deckt genau das Rechteck (x, y, w, h) ab.
            mitte_x = x + (cx + 0.5) / breite_px * w
            mitte_y = y + (cy + 0.5) / hoehe_px * h

            w_neu, h_neu = w * args.faktor, h * args.faktor
            x_neu = min(max(mitte_x - w_neu / 2.0, 0.0), 1.0 - w_neu)
            y_neu = min(max(mitte_y - h_neu / 2.0, 0.0), 1.0 - h_neu)

            print(f"{bahn:>4} {roi['name'].removeprefix(LAMP_PREFIX):>7} "
                  f"{100 * (mitte_x - (x + w / 2)) / w:>+10.1f}% "
                  f"{100 * (mitte_y - (y + h / 2)) / h:>+10.1f}% "
                  f"{w_neu:>8.4f} {h_neu:>8.4f}")
            roi["rect"] = [x_neu, y_neu, w_neu, h_neu]
            geaendert += 1

    if ohne_messung:
        print(f"\nOHNE MESSUNG GEBLIEBEN: {ohne_messung} Lampen -- ihre ROIs "
              "stehen unveraendert. Wo nicht gemessen wurde, wird nicht "
              "geraten.")

    kalib["name"] = f"{kalib.get('name', 'unbenannt')} (enge Lampen-ROIs)"
    hinweis = (f"Kegellampen-ROIs auf {args.faktor:.0%} verkleinert und auf "
               f"die gemessene Lampenmitte zentriert (tools/fit_lamp_rois.py, "
               f"{len(args.patches)} Messstrecken). Dazu gehoert "
               f"`lamp_detection.pin.core_percentile: 0` -- ohne das verpufft "
               f"die Haelfte.")
    kalib["source_hint"] = dict(kalib.get("source_hint", {}))
    kalib["source_hint"]["note"] = hinweis

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as datei:
        json.dump(kalib, datei, ensure_ascii=False, indent=2)
    print(f"\n{geaendert} Lampen-ROIs angepasst -> {args.out}")
    print("NICHT VERGESSEN: core_percentile auf 0 setzen und die vier "
          "Schwellwerte neu bestimmen -- der Zuschnitt verschiebt alle Niveaus.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
