"""Misst, was ein engerer Kegellampen-ROI bringt -- und was er kostet.

WOZU: Die Kegellampen-ROIs sind 12 x 11 Pixel gross. Die Lampe fuellt sie
nicht aus, deshalb misst der Detektor nur den hellen Kern
(`core_percentile`, heute 70). Die Frage war, ob ein engerer Rahmen die
Trennung zwischen AN und AUS verbessert -- besonders auf Bahn 4, wo sie am
knappsten ist.

DIE KENNZAHL ist die TRENNLUECKE `p5(AN) - p95(AUS)`: der Abstand zwischen dem
dunkelsten Zwanzigstel der leuchtenden und dem hellsten der dunklen
Messungen. Sie sagt, wieviel Platz eine Schwelle haette. Der Kontrast der
Mediane taugt nicht -- er kann gross sein, waehrend die Raender sich beruehren.

Eingeordnet wird immer am VOLLEN Rahmen (>= 240 AN, <= 215 AUS, Totzone
weggelassen). Wuerde die verkleinerte Messung sich selbst einordnen, benotete
sich jede Variante selbst.

GEMESSEN am 2026-09-01 ueber 10 800 Ausschnitte, zwei Strecken (Frames
15000-30000 und 250000-265000), Spieltag 2026-08-22:

    Trennluecke Bahn 4     frueh   spaet
    heute (100 %, Kern 70)  44,8    33,7
    80 % + Kern 70          54,3    37,5
    50 % ohne Kern          61,8    44,8
    40 % ohne Kern          61,7    51,2

DREI BEFUNDE, die man einzeln kennen sollte:

1. **Der halbe Gewinn kommt vom Nachzentrieren, nicht vom Verkleinern.**
   Bahn 4, 80 %: ohne Nachzentrieren 49,0, mit 54,3 (heute 44,8). Die Lampen
   sitzen im Median 4-10 % oberhalb und links der Rahmenmitte, im Extremfall
   15 % daneben -- bei 12 Pixeln knapp zwei Pixel.

2. **Kernfilter und Rahmengroesse ersetzen einander.** Bei weitem Rahmen
   braucht es den Filter (Bahn 4: 44,8 mit, 16,3 ohne). Bei engem Rahmen
   schadet er (bei 50 %: 42,1 mit, 61,8 ohne) -- er nimmt einer ohnehin
   kleinen Pixelmenge nochmals 70 %. `core_percentile` ist ein Notbehelf fuer
   einen zu weiten Rahmen.

3. **Die Position ist stabil, die Helligkeit nicht.** Zwischen den beiden
   Strecken (rund 2,6 Stunden) wandert der Lampenschwerpunkt um median 2 %,
   hoechstens 4,8 % der Kantenlaenge -- ein 50 %-Zuschnitt haette davon
   reichlich Reserve. Das AUS-Niveau steigt im selben Zeitraum dagegen um 10
   bis 23 Punkte, und die Trennluecke schrumpft entsprechend. Der Zuschnitt
   loest die Drift nicht; er vergroessert nur den Abstand, den sie aufzehrt.

WAS DARAUS NICHT FOLGT: dass man die Zahl einfach eintragen kann. Ein anderer
Zuschnitt verschiebt ALLE Niveaus -- bei 50 % ohne Kernfilter faellt AN p5 auf
Bahn 4 auf 240,0. Die Schwellen (`brightness_on_threshold`,
`brightness_off_threshold`, `baseline_on_fraction`, `baseline_off_fraction`)
muessten mitbestimmt werden, und ein Vollauf gehoert dagegen gehalten.

AUFRUF -- erst sammeln, dann beliebig oft auswerten:

    .venv/Scripts/python.exe tools/measure_roi_shrink.py sammeln \
        --source <Datei oder Stream-URL> \
        --calibration data/calibrations/1Spieltag.json \
        --von 15000 --bis 30000 --ziel debug/patches_frueh.pkl

    .venv/Scripts/python.exe tools/measure_roi_shrink.py auswerten \
        debug/patches_frueh.pkl debug/patches_spaet.pkl

Das Trennen lohnt, weil das Lesen einer entfernten Quelle Minuten dauert und
jede neue Frage sonst neu lesen muesste.
"""

from __future__ import annotations

import argparse
import pickle
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration, norm_rect_to_frame_bbox  # noqa: E402

# Eindeutige Faelle. Die Totzone dazwischen bleibt aussen vor -- sie ist ja
# gerade das, was gemessen werden soll.
AN_AB, AUS_BIS = 240.0, 215.0

STUFEN = (1.0, 0.8, 0.6, 0.5, 0.4, 0.3)
KERN_STUFEN = (70.0, 50.0, 0.0)

# Die Kalibrierung zaehlt die Tafeln 1..4, der Sport zaehlt die Bahnen 2..5.
REALE_BAHN = {1: 2, 2: 3, 3: 4, 4: 5}


def kern_value(patch: np.ndarray, core_percentile: float = 70.0) -> float:
    """Helligkeit wie der Detektor: Mittel ueber den hellen Kern von max(B,G,R).

    `core_percentile <= 0` mittelt alle Pixel -- die Variante ohne Kernfilter.
    """
    value = patch.max(axis=2).astype(np.float32)
    if core_percentile <= 0.0:
        return float(value.mean())
    kern = value >= np.percentile(value, core_percentile)
    if not kern.any():
        kern = np.ones_like(value, dtype=bool)
    return float(value[kern].mean())


def zuschnitt(patch: np.ndarray, anteil: float,
              mitte: tuple[float, float] | None = None) -> np.ndarray:
    """Zentrierter Ausschnitt. `mitte` in Pixeln (y, x), sonst geometrisch."""
    hoehe, breite = patch.shape[:2]
    nh = max(2, int(round(hoehe * anteil)))
    nb = max(2, int(round(breite * anteil)))
    cy, cx = (hoehe / 2.0, breite / 2.0) if mitte is None else mitte
    y0 = int(round(min(max(cy - nh / 2.0, 0), hoehe - nh)))
    x0 = int(round(min(max(cx - nb / 2.0, 0), breite - nb)))
    return patch[y0:y0 + nh, x0:x0 + nb]


def hell_schwerpunkt(patch: np.ndarray) -> tuple[float, float]:
    """Schwerpunkt der hellsten Pixel (y, x) -- wo sitzt die Lampe im Rahmen?"""
    value = patch.max(axis=2).astype(np.float32)
    hell = value >= np.percentile(value, 90.0)
    if not hell.any():
        return (patch.shape[0] / 2.0, patch.shape[1] / 2.0)
    ys, xs = np.nonzero(hell)
    return (float(ys.mean()), float(xs.mean()))


def perzentil(werte: list[float], q: float) -> float:
    werte = sorted(werte)
    return werte[min(len(werte) - 1, int(len(werte) * q / 100))]


def schwerpunkte(proben: list[tuple]) -> dict:
    """Lampenmitte je (Bahn, Lampe) -- nur aus leuchtenden Messungen.

    Bei ausgeschalteter Lampe ist im Rahmen nichts zu sehen, woran sich ein
    Schwerpunkt festmachen liesse; solche Frames wuerden ihn verrauschen.
    """
    roh = defaultdict(list)
    for _, bahn, lampe, patch in proben:
        if kern_value(patch) >= AN_AB:
            roh[(bahn, lampe)].append(hell_schwerpunkt(patch))
    return {k: (st.median([s[0] for s in v]), st.median([s[1] for s in v]))
            for k, v in roh.items() if len(v) >= 5}


# --------------------------------------------------------------- sammeln ----

def sammeln(quelle: str, kalibrierung: Path, von: int, bis: int,
            schritt: int, ziel: Path) -> int:
    cal = Calibration.load(kalibrierung)
    transforms = {lane.lane_id: lane.transform(440, 530) for lane in cal.lanes}

    cap = cv2.VideoCapture(quelle)
    if not cap.isOpened():
        print(f"Quelle nicht lesbar: {quelle}")
        return 1

    # Sprung statt Vorspulen -- 250 000 Frames sequentiell zu lesen dauert ueber
    # eine Stunde. Ob die Quelle den Sprung beherrscht, sagt erst der Versuch,
    # deshalb wird die erreichte Stelle geprueft statt blind gemessen.
    frame = 0
    if von > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, von)
        frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if abs(frame - von) > 5000:
            print(f"Sprung nach {von} landete bei {frame} -- Abbruch, "
                  "sonst wuerde die falsche Stelle gemessen.")
            cap.release()
            return 1

    proben: list[tuple] = []
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
                            patch = bild[y:y + h, x:x + w]
                            if patch.size == 0:
                                continue
                            proben.append((
                                frame, REALE_BAHN.get(lane.lane_id, lane.lane_id),
                                roi.name.removeprefix("pin_lamp_"),
                                np.ascontiguousarray(patch)))
                if (frame - von) % (schritt * 30) == 0:
                    print(f"  Frame {frame} ... {len(proben)} Ausschnitte",
                          flush=True)
            frame += 1
    finally:
        cap.release()

    if not proben:
        print("Keine Ausschnitte -- sitzt die Kalibrierung auf dieser Quelle?")
        return 1

    ziel.parent.mkdir(parents=True, exist_ok=True)
    with ziel.open("wb") as datei:
        pickle.dump(proben, datei, protocol=4)
    hellste = max(kern_value(p[3]) for p in proben)
    print(f"Fertig: {len(proben)} Ausschnitte -> {ziel} "
          f"({ziel.stat().st_size / 1e6:.1f} MB)")
    if hellste < AN_AB:
        print(f"WARNUNG: keine Messung erreicht {AN_AB:.0f} (hoechster Wert "
              f"{hellste:.1f}). Vermutlich sitzt die Kalibrierung nicht auf "
              "dieser Quelle -- dann ist die Sammlung wertlos.")
    return 0


# ------------------------------------------------------------ auswerten ----

def eine_strecke(proben: list[tuple], titel: str) -> dict:
    mitten = schwerpunkte(proben)
    hoehe, breite = proben[0][3].shape[:2]

    print(f"\n\n=== {titel} ===")
    print(f"{len(proben)} Ausschnitte, Rahmen {breite} x {hoehe} Pixel")

    print("\n--- Sitzt die Lampe mittig? "
          "(Versatz von der Rahmenmitte, % der Kantenlaenge) ---")
    print(f"{'Bahn':>4} {'Lampen':>7} {'senkrecht':>11} {'waagerecht':>12} "
          f"{'groesster':>10}")
    for bahn in (2, 3, 4, 5):
        eintraege = [v for k, v in mitten.items() if k[0] == bahn]
        if not eintraege:
            continue
        dy = [100.0 * (v[0] - hoehe / 2.0) / hoehe for v in eintraege]
        dx = [100.0 * (v[1] - breite / 2.0) / breite for v in eintraege]
        groesst = max(max(abs(a) for a in dy), max(abs(a) for a in dx))
        print(f"{bahn:>4} {len(eintraege):>7} {st.median(dy):>+10.1f}% "
              f"{st.median(dx):>+11.1f}% {groesst:>9.1f}%")

    for kern in KERN_STUFEN:
        werte = defaultdict(lambda: defaultdict(list))
        for _, bahn, lampe, patch in proben:
            voll = kern_value(patch)
            zustand = ("AN" if voll >= AN_AB
                       else "AUS" if voll <= AUS_BIS else None)
            if zustand is None:
                continue
            mitte = mitten.get((bahn, lampe))
            for stufe in STUFEN:
                werte[(bahn, stufe)][zustand].append(
                    kern_value(zuschnitt(patch, stufe, mitte), kern))

        name = ("ohne Kernfilter (alle Pixel)" if kern <= 0
                else f"core_percentile {kern:.0f} "
                     f"(hellste {100 - kern:.0f} %)")
        print(f"\n--- Trennluecke, auf den Lampenschwerpunkt zentriert, "
              f"{name} ---")
        print(f"{'Stufe':>6} " + "".join(f"{'Bahn ' + str(b):>10}"
                                         for b in (2, 3, 4, 5)))
        for stufe in STUFEN:
            zeile = f"{stufe:>5.0%} "
            for bahn in (2, 3, 4, 5):
                aus = werte[(bahn, stufe)]["AUS"]
                an = werte[(bahn, stufe)]["AN"]
                if len(aus) < 20 or len(an) < 20:
                    zeile += f"{'-':>10}"
                    continue
                zeile += f"{perzentil(an, 5) - perzentil(aus, 95):>10.1f}"
            print(zeile)
    return mitten


def auswerten(dateien: list[Path]) -> int:
    strecken = []
    for pfad in dateien:
        if not pfad.is_file():
            print(f"fehlt: {pfad}")
            return 1
        with pfad.open("rb") as datei:
            strecken.append((pfad.name, pickle.load(datei)))

    mitten = [eine_strecke(proben, name) for name, proben in strecken]

    if len(strecken) < 2:
        print("\n\n(Nur eine Strecke -- ob die Einblendung ueber die Zeit "
              "wandert, bleibt damit ungemessen.)")
        return 0

    hoehe, breite = strecken[0][1][0][3].shape[:2]
    print("\n\n=== Wandert die Einblendung zwischen den Strecken? ===")
    print(f"Versatz zwischen '{strecken[0][0]}' und '{strecken[-1][0]}', "
          "in % der Kantenlaenge")
    print(f"{'Bahn':>4} {'Lampen':>7} {'senkrecht':>11} {'waagerecht':>12} "
          f"{'groesster':>10}")
    for bahn in (2, 3, 4, 5):
        gemeinsam = [k for k in mitten[0] if k[0] == bahn and k in mitten[-1]]
        if not gemeinsam:
            continue
        dy = [100.0 * (mitten[-1][k][0] - mitten[0][k][0]) / hoehe
              for k in gemeinsam]
        dx = [100.0 * (mitten[-1][k][1] - mitten[0][k][1]) / breite
              for k in gemeinsam]
        groesst = max(max(abs(a) for a in dy), max(abs(a) for a in dx))
        print(f"{bahn:>4} {len(gemeinsam):>7} {st.median(dy):>+10.1f}% "
              f"{st.median(dx):>+11.1f}% {groesst:>9.1f}%")
    print("\nEin Zuschnitt auf X % vertraegt eine Wanderung bis (100-X)/2 %,")
    print("bevor die Lampe aus dem Rahmen laeuft.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    unter = parser.add_subparsers(dest="befehl", required=True)

    s = unter.add_parser("sammeln", help="Ausschnitte aus der Quelle sichern")
    s.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    s.add_argument("--calibration", required=True, type=Path)
    s.add_argument("--von", type=int, default=15000)
    s.add_argument("--bis", type=int, default=30000)
    s.add_argument("--schritt", type=int, default=100)
    s.add_argument("--ziel", required=True, type=Path)

    a = unter.add_parser("auswerten", help="gesammelte Ausschnitte vergleichen")
    a.add_argument("dateien", nargs="+", type=Path)

    args = parser.parse_args()
    if args.befehl == "sammeln":
        return sammeln(args.source, args.calibration, args.von, args.bis,
                       args.schritt, args.ziel)
    return auswerten(args.dateien)


if __name__ == "__main__":
    raise SystemExit(main())
