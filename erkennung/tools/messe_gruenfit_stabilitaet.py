"""Wie viele Bilder braucht eine Lagebestimmung der Gruenlampe?

WOZU (Nutzer, 2026-10-02): *„aber koennte man daraus nicht bei einem
Livestream theoretisch ein fitting bauen?"*

Die Korrektur auf Bahn 5 vom selben Tag stammt aus 36 Referenzframes, die
Gegenprobe ueber 2000 Bilder hat sie bestaetigt. Das heisst NICHT, dass 36
Frames zuverlaessig dieselbe Lage finden -- es kann Glueck gewesen sein. Wer
daraus einen mitlaufenden Wachhund bauen will, muss vorher wissen, ab wann
die Schaetzung steht. Sonst verschiebt er ROIs auf Rauschen.

DAS KRITERIUM IST OTSU, NICHT `fit_green_lamp`. Jenes Werkzeug braucht
etikettierte Referenzframes aus der Gruenspur eines FERTIGEN Laufs -- die hat
ein Livestream nicht. Otsu trennt die beiden Wolken ohne jedes Vorwissen
darueber, wann die Lampe an war, und ist damit genau das Mass, das ein
Wachhund zur Verfuegung haette. Gemessen wird also die Stabilitaet DESSEN,
was man einbauen wuerde.

UND ES IST DAS MASS, DAS GEGEN DEN SCHLIMMSTEN FALL SCHUETZT: Rutscht die ROI
von der Lampe, liest sie dauerhaft hell oder dauerhaft dunkel -- dann gibt es
keine zwei Wolken mehr und die Trennschaerfe faellt auf null. Ein Mass wie
"maximiere die Helligkeit" wuerde genau dorthin laufen.

Gerechnet wird auf der Ablage von `tools/sammle_gruenfelder.py`, also ohne
das Video erneut zu lesen.

Aufruf:

    .venv/Scripts/python.exe tools/messe_gruenfit_stabilitaet.py \
        --ablage scratchpad/gruenfelder.npz
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.config import load_config                            # noqa: E402

# Suchraum. Der Versatz bleibt INNERHALB der vom Nutzer kalibrierten
# Umgebung -- das ist die Leitplanke gegen das Abwandern.
#
# WEIT GENUG, SONST MISST MAN DEN RAND: Der erste Anlauf suchte nur -3..+3 px
# und 0,7..1,0 -- und fand auf ALLEN VIER Bahnen das Optimum bei dx = -3 und
# dreimal bei Groesse 0,7, also jedes Mal am Anschlag. Zwei Parameter am Rand
# heissen: ausserhalb liegt etwas Besseres. Gegenprobe ueber die Groesse
# allein zeigte ein echtes Optimum bei 0,5 bis 0,7 (Bahn 4: Fisher 16,5 bei
# 1,0 / 29,1 bei 0,7 / 34,0 bei 0,5 / 14,7 bei 0,35) -- das Kriterium ist
# also nicht entartet, der Suchraum war zu klein.
VERSATZ = range(-6, 7)
GROESSEN = (0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0)


def integralbilder(stapel: np.ndarray, unten, oben) -> np.ndarray:
    """Je Bild die Summentafel seiner Gruenmaske.

    WARUM: Jeder Kandidat braucht den Gruenanteil in EINEM Rechteck. Ueber die
    Summentafel kostet das vier Zugriffe statt einer Maske je Kandidat und
    Bild -- aus 1183 x 16001 Maskenberechnungen werden 1183 vektorisierte
    Differenzen. Das ist nicht nur bequem: Es zeigt zugleich, dass ein
    mitlaufender Wachhund rechnerisch nichts kostet.
    """
    n, h, b = stapel.shape[:3]
    aus = np.zeros((n, h + 1, b + 1), dtype=np.int32)
    for i, bild in enumerate(stapel):
        hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
        maske = (cv2.inRange(hsv, unten, oben) > 0).astype(np.int32)
        aus[i, 1:, 1:] = maske.cumsum(0).cumsum(1)
    return aus


def anteil_im_kasten(integral: np.ndarray, y0: int, x0: int,
                     hh: int, bb: int) -> np.ndarray:
    """Gruenanteil in Prozent je Bild fuer EIN Rechteck."""
    y1, x1 = y0 + hh, x0 + bb
    summe = (integral[:, y1, x1] - integral[:, y0, x1]
             - integral[:, y1, x0] + integral[:, y0, x0])
    return summe / float(hh * bb) * 100.0


# Jede Wolke muss so viel der Messungen tragen. Die Gruenlampe ist ueber
# einen Spieltag rund die Haelfte der Zeit an; 10 % ist also grosszuegig.
MINDESTANTEIL = 0.10
# Untergrenze der Streuung in (Prozentpunkten)^2. Verhindert die Division
# durch fast nichts.
STREUUNG_MIN = 1.0


def trennschaerfe(werte: np.ndarray) -> tuple[float, float]:
    """(Fisher, Graubereich) nach Otsu -- mit zwei Sicherungen.

    OHNE DIESE SICHERUNGEN IST DAS MASS WERTLOS, und zwar genau im
    gefaehrlichsten Fall. Gemessen am 2026-10-02: Laesst man den Suchraum bis
    an den Rand der Lampenumgebung laufen, gewinnen auf drei von vier Bahnen
    die ECKEN -- also Lagen vollstaendig neben der Lampe -- mit einem Fisher
    von 5,6e+31. Dort liest die ROI fast immer denselben Wert; Otsu zerlegt
    auch das in zwei Haeufchen, beide mit Streuung nahe null, und der
    Quotient Abstand^2/Streuung explodiert.

    Die Wolken verschmelzen also NICHT, wenn die ROI von der Lampe rutscht --
    sie werden zu zwei Punkten. Die Annahme, ein Trennschaerfemass sei
    bauartbedingt gegen das Abwandern geschuetzt, ist damit widerlegt.

    Zwei Sicherungen: Jede Wolke muss einen Mindestanteil der Messungen
    tragen, und die Streuung bekommt eine Untergrenze.
    """
    if werte.size < 50:
        return float("nan"), float("nan")
    ganz = np.clip(werte, 0, 100).astype(np.uint8)
    schwelle, _ = cv2.threshold(ganz, 0, 255,
                                cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    unten, oben = werte[werte <= schwelle], werte[werte > schwelle]
    mindest = max(5, int(werte.size * MINDESTANTEIL))
    if unten.size < mindest or oben.size < mindest:
        return float("nan"), float("nan")
    abstand = float(oben.mean() - unten.mean())
    streuung = max(STREUUNG_MIN, float(oben.var() + unten.var()))
    grau = float(np.mean(np.abs(werte - schwelle) < abstand / 4) * 100)
    return abstand ** 2 / streuung, grau


def kandidaten(hoehe: int, breite: int, rand: int):
    """(dx, dy, groesse) -> Ausschnittsgrenzen im abgelegten Bild."""
    h, b = hoehe - 2 * rand, breite - 2 * rand
    mitte_y, mitte_x = rand + h / 2, rand + b / 2
    for g in GROESSEN:
        hh, bb = max(2, round(h * g)), max(2, round(b * g))
        for dy in VERSATZ:
            for dx in VERSATZ:
                y0 = int(round(mitte_y + dy - hh / 2))
                x0 = int(round(mitte_x + dx - bb / 2))
                if y0 < 0 or x0 < 0 or y0 + hh > hoehe or x0 + bb > breite:
                    continue
                yield (dx, dy, g), (y0, x0, hh, bb)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ablage", required=True, type=Path)
    p.add_argument("--fenster", default="200,400,800,1600,3200",
                   help="Fenstergroessen in Messungen")
    a = p.parse_args()

    cfg = load_config().detection.green
    unten = np.array([cfg.hue_min, cfg.saturation_min, cfg.value_min],
                     dtype=np.uint8)
    oben = np.array([cfg.hue_max, 255, 255], dtype=np.uint8)

    d = np.load(a.ablage)
    rand = int(d["rand"][0])
    bahnen = sorted(int(k[4:]) for k in d.files if k.startswith("bahn"))
    groessen = [int(x) for x in a.fenster.split(",")]

    for bahn in bahnen:
        stapel = d[f"bahn{bahn}"]
        n, hoehe, breite = stapel.shape[:3]
        print(f"\n=== Bahn {bahn}: {n} Ausschnitte, "
              f"{breite}x{hoehe} px (Rand {rand}) ===")

        # Einmal alle Kandidaten ueber ALLE Bilder -- das ist die Wahrheit,
        # gegen die die kurzen Fenster gemessen werden.
        integral = integralbilder(stapel, unten, oben)
        werte: dict[tuple, np.ndarray] = {}
        for schluessel, (y0, x0, hh, bb) in kandidaten(hoehe, breite, rand):
            werte[schluessel] = anteil_im_kasten(integral, y0, x0, hh, bb)
        gesamt = {k: trennschaerfe(v)[0] for k, v in werte.items()}
        beste = max(gesamt, key=lambda k: (gesamt[k] if gesamt[k] == gesamt[k]
                                           else -1))
        jetzt = (0, 0, 1.0)
        print(f"   Ueber alle {n} Bilder: beste Lage {beste} "
              f"Fisher {gesamt[beste]:.1f}   (heutige Lage {jetzt} "
              f"Fisher {gesamt.get(jetzt, float('nan')):.1f})")

        print(f"   {'Fenster':>8} {'Anzahl':>7} {'trifft beste':>13} "
              f"{'|dx| median':>12} {'|dx| max':>9} {'Groesse median':>15}")
        for w in groessen:
            if w > n:
                continue
            treffer, dxs, gs = 0, [], []
            fenster = 0
            for anfang in range(0, n - w + 1, w):
                teil = {k: trennschaerfe(v[anfang:anfang + w])[0]
                        for k, v in werte.items()}
                gut = {k: x for k, x in teil.items() if x == x}
                if not gut:
                    continue
                fenster += 1
                wahl = max(gut, key=gut.get)
                treffer += (wahl == beste)
                dxs.append(abs(wahl[0] - beste[0]))
                gs.append(wahl[2])
            if not fenster:
                continue
            print(f"   {w:>8} {fenster:>7} "
                  f"{treffer}/{fenster:<11} {np.median(dxs):>12.1f} "
                  f"{max(dxs):>9} {np.median(gs):>15.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
