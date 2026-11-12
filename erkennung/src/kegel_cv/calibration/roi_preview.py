"""ROIs sichtbar machen -- die einzige Art, eine Kalibrierung zu beurteilen.

WOFUER -- Einwand des Nutzers am 2026-09-10, nach dem ersten Livelauf:

    "ich brauche schon das die ROIs eingeblendet werden ... sonst kann ich ja
     nicht entscheiden, ob es sitzt oder nicht"

Ein Rahmen um die Tafel beweist nur, dass die Tafel gefunden wurde. Ob die
Gruenlampe auf der Gruenlampe liegt und die Ziffernstellen auf den Ziffern,
zeigt sich erst in der ENTZERRTEN Tafel -- im Vollbild misst eine Tafel rund
160 Pixel, eine Lampen-ROI darin sechs.

Die Farben trennen die ROI-Arten. Eine Fehlplatzierung faellt dadurch sofort
auf: eine gelbe Lampenmarkierung mitten im Ziffernfeld sieht falsch aus, lange
bevor man die Namen liest.
"""

from __future__ import annotations

import cv2
import numpy as np

from .geometry import PerspectiveTransform, Quad

# Farbe je ROI-Art (BGR). Getrennte Farben machen Fehlplatzierungen sichtbar.
FARBEN = {
    "pin_lamp": (0, 255, 255),      # gelb
    "green_lamp": (0, 255, 0),      # gruen
    "pin_count": (255, 128, 0),     # blau
    "throw_number": (255, 0, 255),  # magenta
    "total_a": (0, 128, 255),       # orange
    "total_b": (0, 128, 255),
    "left_display": (128, 128, 128),
}
STANDARDFARBE = (200, 200, 200)


def roi_farbe(name: str) -> tuple[int, int, int]:
    for anfang, farbe in FARBEN.items():
        if name.startswith(anfang):
            return farbe
    return STANDARDFARBE


def zeichne_rois(tafel: np.ndarray, rois, skalierung: int = 2,
                 mit_namen: bool = True) -> np.ndarray:
    """Zeichnet die ROIs in eine entzerrte Tafel.

    `rois` liegen in normierten Tafelkoordinaten (0..1) -- deshalb gilt diese
    Funktion fuer jede Tafelgroesse und jeden Blickwinkel.
    """
    bild = cv2.resize(tafel, None, fx=skalierung, fy=skalierung,
                      interpolation=cv2.INTER_CUBIC)
    hoehe, breite = bild.shape[:2]
    for roi in rois:
        if not getattr(roi, "enabled", True):
            continue
        x, y, w, h = roi.rect
        p1 = (int(x * breite), int(y * hoehe))
        p2 = (int((x + w) * breite), int((y + h) * hoehe))
        farbe = roi_farbe(roi.name)
        cv2.rectangle(bild, p1, p2, farbe, 1)
        if mit_namen:
            cv2.putText(bild, roi.name.replace("pin_lamp_", "L"),
                        (p1[0], max(9, p1[1] - 3)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.30, farbe, 1, cv2.LINE_AA)
    return bild


def quadmasse(ecken) -> tuple[float, float]:
    """Breite und Hoehe eines Vierecks, ueber die Gegenkanten gemittelt."""
    q = np.asarray(ecken, dtype=float)
    breite = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    hoehe = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    return float(breite), float(hoehe)


def tafelmontage(bild: np.ndarray, bahnen, breite: int = 220,
                 abstand: int = 10, skalierung: int = 2) -> np.ndarray:
    """Legt alle Bahnen entzerrt und mit ROIs nebeneinander.

    Nebeneinander und nicht einzeln, weil der Vergleich die Fehler zeigt:
    Sitzt EINE Tafel anders als die drei anderen, sieht man das im Nebeneinander
    sofort -- an einem Einzelbild nicht.

    IM WAHREN SEITENVERHAELTNIS, nicht im Rechenformat. Die Analyse entzerrt
    auf 440x530 (Verhaeltnis 0,83); die Tafel selbst ist aber praktisch
    quadratisch. GEMESSEN 2026-09-10 ueber drei Kalibrierungen und zwei
    Kameras: 0,97 bis 1,01 -- die Rechendarstellung streckt sie also um den
    Faktor 1,2 in die Hoehe.

    Fuer die Analyse ist das gleichgueltig, weil die ROIs in normierten
    Tafelkoordinaten liegen und die Streckung sich herauskuerzt. Fuers AUGE
    ist es das nicht: Wer beurteilen soll, ob ein Rahmen sitzt, will die Tafel
    sehen und nicht ihr Rechenformat.
    """
    kacheln = []
    for bahn in bahnen:
        ecken = [(float(p[0]), float(p[1])) for p in bahn.quad]
        b, h = quadmasse(ecken)
        hoehe = max(1, int(round(breite * h / b))) if b else breite
        transform = PerspectiveTransform(Quad.from_points(ecken), breite, hoehe)
        kacheln.append(zeichne_rois(transform.warp(bild), bahn.rois,
                                    skalierung))
    if not kacheln:
        return bild

    k_hoehe = max(k.shape[0] for k in kacheln)
    k_breite = sum(k.shape[1] for k in kacheln) + abstand * (len(kacheln) - 1)
    tafel = np.zeros((k_hoehe + 22, k_breite, 3), dtype=np.uint8)
    x = 0
    for i, kachel in enumerate(kacheln, start=1):
        h, b = kachel.shape[:2]
        tafel[22:22 + h, x:x + b] = kachel
        # Die Nummer zaehlt von links nach rechts -- in dieser Reihenfolge
        # werden die Bahnnummern abgefragt.
        cv2.putText(tafel, f"{i}", (x + 4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (255, 255, 255), 1, cv2.LINE_AA)
        x += b + abstand
    return tafel
