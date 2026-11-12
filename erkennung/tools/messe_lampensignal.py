"""Wo sitzt die Gruenlampe wirklich? Aus dem Unterschied AN minus AUS.

WOZU (Nutzer, 2026-10-02): *„wie waere es, wenn wir anhand aller
Gruenlampenbilder die wir haben auch dort ein Bild-in-Bild suche machen? Bei
der Grundkalibrierung war das ja schon deutlich staerker als alle anderen
Verfahren."*

WARUM DER SUCHANSATZ VORHER SCHEITERTE. `messe_gruenfit_stabilitaet.py`
optimiert eine Kennzahl (Fisher nach Otsu) ueber Lage und Groesse. Eine
Kennzahl weiss nicht, wie eine Lampe aussieht, und hat deshalb entartete
Richtungen: Ohne Sicherungen gewannen die ECKEN des Suchraums mit Fisher
5,6e+31 (eine ROI neben der Lampe liest fast immer denselben Wert, Otsu
zerlegt auch das in zwei Punkte, der Quotient explodiert). Mit Sicherungen
lief die Groesse an den Rand. Und die Lage streute auf Bahn 4 und 5 um bis zu
12 px zwischen Fenstern -- ausgerechnet auf den beiden Bahnen, die einen
Fehler hatten.

DIESER WEG BRAUCHT GAR KEINE SUCHE. Ist bekannt, wann die Lampe an war, dann
ist

    Signal(Pixel) = P(Pixel gruen | AN) - P(Pixel gruen | AUS)

ein direktes Bild der Lampe: Es zeigt genau die Pixel, die den Zustand
tragen. Daraus folgen Mittelpunkt und Ausdehnung ohne Optimierung -- es gibt
keinen Suchraum, an dessen Rand etwas laufen koennte, und keine
Groessenfreiheit, die ins Entartete zieht.

DIE ETIKETTEN SIND LEICHT ZIRKULAER: AN und AUS stammen aus der Gruenspur,
also aus der bisherigen ROI. Das ist vertretbar -- eine falsch sitzende ROI
liest immer noch 50 gegen 25 und trennt die Zustaende grob richtig -- aber es
wird gegengeprueft, indem die Schaetzung einer Bahn mit der einer anderen
verglichen wird (die Tafeln sind baugleich).

Gerechnet wird auf der Ablage von `tools/sammle_gruenfelder.py`.

Aufruf:

    .venv/Scripts/python.exe tools/messe_lampensignal.py \
        --ablage scratchpad/gruenfelder.npz \
        --lauf debug/Vorstand-Grundlinie/lauf_2026-09-29_13-52-42
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.config import load_config                            # noqa: E402


def zustaende(lauf: Path, bahn: int) -> dict[int, str]:
    aus: dict[int, str] = {}
    with (lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if int(r["Bahn"]) == bahn:
                aus[int(r["Frame"])] = r["Zustand"]
    return aus


def signalbild(masken: np.ndarray, an: np.ndarray,
               aus: np.ndarray) -> np.ndarray:
    """P(gruen | AN) - P(gruen | AUS), je Pixel, in [-1, 1]."""
    return masken[an].mean(axis=0) - masken[aus].mean(axis=0)


def schwerpunkt(signal: np.ndarray, anteil: float = 0.5):
    """(Zeile, Spalte, Flaeche) des Bereichs oberhalb `anteil` des Gipfels."""
    gipfel = float(signal.max())
    if gipfel <= 0:
        return None
    maske = signal >= gipfel * anteil
    gewicht = np.where(maske, signal, 0.0)
    summe = gewicht.sum()
    yy, xx = np.indices(signal.shape)
    return (float((gewicht * yy).sum() / summe),
            float((gewicht * xx).sum() / summe),
            int(maske.sum()), gipfel)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ablage", required=True, type=Path)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--fenster", default="200,400,800,1600,3200")
    a = p.parse_args()

    cfg = load_config().detection.green
    unten = np.array([cfg.hue_min, cfg.saturation_min, cfg.value_min],
                     dtype=np.uint8)
    oben = np.array([cfg.hue_max, 255, 255], dtype=np.uint8)

    d = np.load(a.ablage)
    rand = int(d["rand"][0])
    frames = d["frames"]
    bahnen = sorted(int(k[4:]) for k in d.files if k.startswith("bahn"))
    groessen = [int(x) for x in a.fenster.split(",")]
    mittelpunkte = {}

    for bahn in bahnen:
        stapel = d[f"bahn{bahn}"]
        n, hoehe, breite = stapel.shape[:3]
        masken = np.empty((n, hoehe, breite), dtype=np.float32)
        for i, bild in enumerate(stapel):
            hsv = cv2.cvtColor(bild, cv2.COLOR_BGR2HSV)
            masken[i] = (cv2.inRange(hsv, unten, oben) > 0)

        zu = zustaende(a.lauf, bahn)
        etikett = np.array([zu.get(int(f), "?") for f in frames])
        an = np.flatnonzero(etikett == "ON")
        aus = np.flatnonzero(etikett == "OFF")
        print(f"\n=== Bahn {bahn}: {n} Ausschnitte, {breite}x{hoehe} px, "
              f"{len(an)} AN / {len(aus)} AUS ===")
        if len(an) < 50 or len(aus) < 50:
            print("   zu wenige etikettierte Bilder")
            continue

        signal = signalbild(masken, an, aus)
        y, x, flaeche, gipfel = schwerpunkt(signal)
        # Mitte der heutigen ROI im Ausschnitt
        my, mx = rand + (hoehe - 2 * rand) / 2, rand + (breite - 2 * rand) / 2
        mittelpunkte[bahn] = (y, x)
        print(f"   Gipfel {gipfel:.2f}   Flaeche ueber dem halben Gipfel "
              f"{flaeche} px")
        print(f"   Lampenmitte (Zeile {y:.1f}, Spalte {x:.1f})   "
              f"heutige ROI-Mitte ({my:.1f}, {mx:.1f})   "
              f"Versatz dx {x - mx:+.1f}  dy {y - my:+.1f}")
        print("   Signalbild (Zehntel des Gipfels, '.' = unter 0):")
        for zeile in signal:
            print("     " + "".join(
                "." if v <= 0 else str(min(9, int(v / gipfel * 10)))
                for v in zeile))

        print(f"\n   {'Fenster':>8} {'Anzahl':>7} {'dx median':>10} "
              f"{'dx Streuung':>12} {'dx max-Abw':>11} {'dy max-Abw':>11}")
        for w in groessen:
            if w > n:
                continue
            dxs, dys, fenster = [], [], 0
            for anfang in range(0, n - w + 1, w):
                teil = slice(anfang, anfang + w)
                a_an = an[(an >= anfang) & (an < anfang + w)]
                a_aus = aus[(aus >= anfang) & (aus < anfang + w)]
                if len(a_an) < 20 or len(a_aus) < 20:
                    continue
                s = signalbild(masken, a_an, a_aus)
                tr = schwerpunkt(s)
                if tr is None:
                    continue
                fenster += 1
                dxs.append(tr[1] - x)
                dys.append(tr[0] - y)
            if not fenster:
                continue
            print(f"   {w:>8} {fenster:>7} {np.median(dxs):>10.2f} "
                  f"{np.std(dxs):>12.2f} {max(abs(v) for v in dxs):>11.2f} "
                  f"{max(abs(v) for v in dys):>11.2f}")

    if len(mittelpunkte) > 1:
        print("\n=== Quervergleich der Bahnen (die Tafeln sind baugleich) ===")
        for bahn, (y, x) in sorted(mittelpunkte.items()):
            print(f"   Bahn {bahn}: Zeile {y:5.2f}  Spalte {x:5.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
