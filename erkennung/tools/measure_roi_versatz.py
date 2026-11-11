"""Misst, ob die Bereiche JE TAFEL verschieden daneben liegen.

DIE FRAGE (Nutzer, 2026-09-11):

    "Die Lampen und die Ziffern lagen zum Teil leicht daneben, das habe ich
     gerade haendisch angepasst. Ich hatte das Gefuehl, dass aber jedes Board
     leicht anders verschoben war."

DAS MASS, DAS NICHT ZIRKULAER IST: Verglichen wird die ENTZERRTE Tafel mit dem
MUSTERBILD der Bauart -- Bild gegen Bild, nicht Bild gegen Leseergebnis. Ein
Kriterium, das am Leseergebnis haengt, hat in diesem Projekt schon einmal in
die falsche Richtung geschoben (`digit_align`, verworfen 2026-09-10).

Gerechnet wird gruppenweise: Was sich um die Lampenraute herum verschiebt, muss
nicht dasselbe sein wie unter der Ziffernzeile -- genau das ist die Frage.
Verglichen werden nur die MASKIERTEN Pixel, also Gehaeuse und Fensterrahmen;
brennende Lampen und wechselnde Ziffern bleiben aussen vor.

Aufruf:

    .venv/Scripts/python.exe tools/measure_roi_versatz.py QUELLE [--stellen 6]
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration.board_library import lade_bibliothek       # noqa: E402
from kegel_cv.calibration.board_match import (finde_tafeln,          # noqa: E402
                                              stabile_maske)
from kegel_cv.config import load_config                              # noqa: E402

# Suchweite in Vorlagenpixeln. Groesser als der erwartete Fehler, sonst misst
# man die Grenze des Fensters statt den Versatz.
WEITE = 5
# Rand um eine Gruppe. Ohne ihn liegt der Rahmen des Anzeigefensters -- die
# eigentliche Struktur -- genau auf der Kante des Ausschnitts.
POLSTER = 10
# Unter so vielen vergleichbaren Pixeln ist ein Ergebnis nicht belastbar.
MIN_PIXEL = 200

# Welche Bereiche zusammen gemessen werden. Getrennt, weil die Frage lautet,
# ob sie sich UNTERSCHIEDLICH verschieben.
GRUPPEN = {
    "lampen": lambda n: n.startswith("pin_lamp"),
    "gruenlampe": lambda n: n == "green_lamp",
    "zeile_unten": lambda n: n in ("throw_number", "pin_count", "total_b"),
    "summe_oben": lambda n: n == "total_a",
    "fehlwurf": lambda n: n == "left_display",
}


def kasten(rois, passt, breite: int, hoehe: int):
    """Umfassendes Rechteck einer Gruppe in Vorlagenpixeln, mit Polster."""
    teile = [r.rect for r in rois if passt(r.name)]
    if not teile:
        return None
    x0 = min(x for x, _, _, _ in teile) * breite - POLSTER
    y0 = min(y for _, y, _, _ in teile) * hoehe - POLSTER
    x1 = max(x + w for x, _, w, _ in teile) * breite + POLSTER
    y1 = max(y + h for _, y, _, h in teile) * hoehe + POLSTER
    return (int(max(0, x0)), int(max(0, y0)),
            int(min(breite, x1)), int(min(hoehe, y1)))


def zncc(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float:
    if m.sum() < MIN_PIXEL:
        return float("nan")
    x = a[m].astype(np.float64)
    y = b[m].astype(np.float64)
    x -= x.mean()
    y -= y.mean()
    nenner = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / nenner) if nenner > 0 else float("nan")


def scheitel(links: float, mitte: float, rechts: float) -> float:
    """Scheitel einer Parabel durch drei Punkte -- Subpixel ohne Iteration."""
    nenner = links - 2 * mitte + rechts
    if abs(nenner) < 1e-12:
        return 0.0
    return float(np.clip(0.5 * (links - rechts) / nenner, -1.0, 1.0))


def versatz(muster: np.ndarray, maske: np.ndarray, ziel: np.ndarray,
            bereich) -> tuple[float, float, float, float, int]:
    """Bester Versatz eines Ausschnitts gegen die Vorlage.

    Zurueck: dx, dy (Vorlagenpixel), ZNCC vorher, ZNCC nachher, Pixelzahl.
    """
    x0, y0, x1, y1 = bereich
    vorlage = muster[y0:y1, x0:x1]
    m = maske[y0:y1, x0:x1].astype(bool)
    if m.sum() < MIN_PIXEL:
        return 0.0, 0.0, float("nan"), float("nan"), int(m.sum())

    gitter = np.full((2 * WEITE + 1, 2 * WEITE + 1), -2.0)
    for iy, dy in enumerate(range(-WEITE, WEITE + 1)):
        for ix, dx in enumerate(range(-WEITE, WEITE + 1)):
            ausschnitt = ziel[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
            if ausschnitt.shape != vorlage.shape:
                continue
            wert = zncc(vorlage, ausschnitt, m)
            if not np.isnan(wert):
                gitter[iy, ix] = wert

    iy, ix = np.unravel_index(int(np.argmax(gitter)), gitter.shape)
    dy, dx = iy - WEITE, ix - WEITE
    # Subpixel nur, wenn das Maximum nicht am Rand des Fensters klebt -- dort
    # liegt der wahre Scheitel ausserhalb, und die Parabel loege.
    if 0 < ix < 2 * WEITE:
        dx += scheitel(gitter[iy, ix - 1], gitter[iy, ix], gitter[iy, ix + 1])
    if 0 < iy < 2 * WEITE:
        dy += scheitel(gitter[iy - 1, ix], gitter[iy, ix], gitter[iy + 1, ix])
    return (float(dx), float(dy), float(gitter[WEITE, WEITE]),
            float(gitter[iy, ix]), int(m.sum()))


def entzerrt(grau: np.ndarray, quad, breite: int, hoehe: int) -> np.ndarray:
    ecken = np.float32([[0, 0], [breite - 1, 0], [breite - 1, hoehe - 1],
                        [0, hoehe - 1]])
    M = cv2.getPerspectiveTransform(ecken, np.float32(quad))
    return cv2.warpPerspective(grau, M, (breite, hoehe),
                               flags=cv2.WARP_INVERSE_MAP)


def main() -> int:
    zerleger = argparse.ArgumentParser()
    zerleger.add_argument("quelle")
    zerleger.add_argument("--stellen", type=int, default=6)
    zerleger.add_argument("--abstand", type=int, default=1500,
                          help="Frames zwischen zwei Stellen")
    zerleger.add_argument("--start", type=int, default=0)
    zerleger.add_argument("--typ", default="FUNK_klassisch")
    argumente = zerleger.parse_args()

    cfg = load_config()
    typen = lade_bibliothek(cfg.resolve(cfg.calibration.boardtype_directory))
    typ = next(t for t in typen if t.name == argumente.typ)
    muster_farbe = typ.muster
    muster = cv2.cvtColor(muster_farbe, cv2.COLOR_BGR2GRAY)
    maske = stabile_maske(muster_farbe, typ.bahn.rois)
    hoehe, breite = muster.shape[:2]
    print(f"Vorlage {breite}x{hoehe}, Maske {100 * maske.mean():.0f} % nutzbar")

    gruppen = {name: kasten(typ.bahn.rois, passt, breite, hoehe)
               for name, passt in GRUPPEN.items()}
    for name, k in gruppen.items():
        print(f"  {name:12s} {k}")

    kamera = cv2.VideoCapture(argumente.quelle)
    if not kamera.isOpened():
        print("Quelle laesst sich nicht oeffnen")
        return 1

    # dx/dy je (Tafel, Gruppe) ueber alle Stellen
    sammlung: dict[tuple[int, str], list[tuple[float, float]]] = defaultdict(list)
    guete_nachher: dict[str, list[float]] = defaultdict(list)
    guete_vorher: dict[str, list[float]] = defaultdict(list)

    for stelle in range(argumente.stellen):
        pos = argumente.start + stelle * argumente.abstand
        kamera.set(cv2.CAP_PROP_POS_FRAMES, pos)
        ok, bild = kamera.read()
        if not ok or bild is None:
            print(f"Frame {pos}: nichts gelesen")
            continue
        grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
        funde = finde_tafeln(bild, muster, maske, max_tafeln=4,
                             min_guete=cfg.calibration.boardmatch_min_guete)
        funde.sort(key=lambda f: f.mitte[0])
        print(f"\nFrame {pos}: {len(funde)} Tafeln")
        for i, fund in enumerate(funde, start=1):
            ziel = entzerrt(grau, fund.quad, breite, hoehe)
            zeile = [f"  Tafel {i} (Guete {fund.guete:.3f})"]
            for name, k in gruppen.items():
                if k is None:
                    continue
                dx, dy, vorher, nachher, pixel = versatz(muster, maske, ziel, k)
                sammlung[(i, name)].append((dx, dy))
                guete_vorher[name].append(vorher)
                guete_nachher[name].append(nachher)
                zeile.append(f"{name} {dx:+5.2f}/{dy:+5.2f} "
                             f"({vorher:.2f}->{nachher:.2f}, {pixel}px)")
            print("\n      ".join(zeile))

    print("\n=== Mittel je Tafel und Gruppe (Median ueber die Stellen) ===")
    print(f"{'Gruppe':12s}" + "".join(f"{'Tafel ' + str(i):>16s}"
                                      for i in range(1, 5)))
    for name in gruppen:
        felder = []
        for i in range(1, 5):
            werte = sammlung.get((i, name))
            if not werte:
                felder.append(f"{'--':>16s}")
                continue
            dx = float(np.median([w[0] for w in werte]))
            dy = float(np.median([w[1] for w in werte]))
            felder.append(f"{dx:+7.2f}/{dy:+6.2f}")
        print(f"{name:12s}" + "".join(felder))

    print("\n=== Streuung derselben Tafel ueber die Stellen (Standardabw.) ===")
    for name in gruppen:
        teile = []
        for i in range(1, 5):
            werte = sammlung.get((i, name))
            if not werte or len(werte) < 2:
                continue
            teile.append(f"T{i} {np.std([w[0] for w in werte]):.2f}/"
                         f"{np.std([w[1] for w in werte]):.2f}")
        print(f"{name:12s} " + "  ".join(teile))

    print("\n=== Was der Versatz an Uebereinstimmung bringt ===")
    for name in gruppen:
        v = [g for g in guete_vorher[name] if not np.isnan(g)]
        n = [g for g in guete_nachher[name] if not np.isnan(g)]
        if v and n:
            print(f"{name:12s} ZNCC {np.mean(v):.3f} -> {np.mean(n):.3f}")
    kamera.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
