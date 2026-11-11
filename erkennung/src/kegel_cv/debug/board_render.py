"""Zeichnet die entzerrte Anzeigetafel mit Rahmen und gemessenen Werten.

WOZU: Ein Wurfergebnis ohne nachvollziehbare Herkunft gilt in diesem Projekt
als unfertig. Eine Zahlenzeile in der CSV beantwortet aber nicht, WARUM sie so
zustande kam -- das entscheidet nur das Bild. Dieses Modul erzeugt den Beleg:
die Tafel, wie die Erkennung sie gesehen hat, mit allen Rahmen und dem, was
darin gelesen wurde.

WARUM HIER UND NICHT IM WERKZEUG: Dieselbe Darstellung wird an zwei Stellen
gebraucht -- von `tools/export_roi_frames.py` fuer die Fehlersuche von Hand und
von `debug/throw_sheet.py` fuer den Beleg je Wurf. Zwei Zeichenroutinen, die
dasselbe zeigen sollen, laufen mit der Zeit auseinander; dann zeigt der Beleg
etwas anderes als das Werkzeug, und niemand weiss mehr, welches Bild gilt.
"""

from __future__ import annotations

import cv2
import numpy as np

# Farben je Feldart (BGR). Bewusst kraeftig und unterscheidbar -- das Bild wird
# oft klein betrachtet.
FARBEN: dict[str, tuple[int, int, int]] = {
    "pin_lamp": (0, 255, 255),
    "green_lamp": (0, 255, 0),
    "throw_number": (255, 128, 0),
    "pin_count": (255, 200, 0),
    "total_a": (0, 165, 255),
    "total_b": (0, 165, 255),
    "left_display": (160, 160, 160),
}

KOPFZEILE_HOEHE = 26


def farbe_von(name: str) -> tuple[int, int, int]:
    """Rahmenfarbe zu einem ROI-Namen, auch fuer einzelne Ziffernstellen."""
    kern = name.removeprefix("digit_") if name.startswith("digit_") else name
    for schluessel, wert in FARBEN.items():
        if kern.startswith(schluessel) or name.startswith(schluessel):
            return wert
    return (200, 200, 200)


def zeichne_tafel(warped: np.ndarray, rois, faktor: int = 3) -> np.ndarray:
    """Entzerrte Tafel, vergroessert, mit allen kalibrierten Rahmen.

    `INTER_NEAREST` ist Absicht: Eine Kegellampe misst rund 6 Pixel. Jede
    glaettende Vergroesserung erfindet Zwischenwerte und laesst den Beleg
    schaerfer aussehen, als die Messung war.
    """
    leinwand = cv2.resize(warped, None, fx=faktor, fy=faktor,
                          interpolation=cv2.INTER_NEAREST)
    hoehe, breite = leinwand.shape[:2]
    for roi in rois:
        if not roi.enabled:
            continue
        x, y, w, h = roi.rect
        p1 = (int(x * breite), int(y * hoehe))
        p2 = (int((x + w) * breite), int((y + h) * hoehe))
        cv2.rectangle(leinwand, p1, p2, farbe_von(roi.name), 1)
        # Einzelne Ziffernstellen bleiben unbeschriftet -- sie liegen innerhalb
        # der Feldrahmen und wuerden das Bild sonst zukleistern.
        if not roi.name.startswith("digit_"):
            cv2.putText(leinwand, roi.name.replace("pin_lamp_", "L"),
                        (p1[0], max(10, p1[1] - 3)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.35, farbe_von(roi.name), 1, cv2.LINE_AA)
    return leinwand


def _textblock(zeilen: list[tuple[str, tuple[int, int, int]]], breite: int,
               zeilenhoehe: int = 22, rand: int = 8) -> np.ndarray:
    """Schwarze Flaeche mit farbigen Textzeilen."""
    hoehe = rand * 2 + zeilenhoehe * max(1, len(zeilen))
    block = np.zeros((hoehe, breite, 3), np.uint8)
    for i, (text, ton) in enumerate(zeilen):
        cv2.putText(block, text, (rand, rand + zeilenhoehe * (i + 1) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, ton, 1, cv2.LINE_AA)
    return block


def mit_kopf_und_werten(tafel: np.ndarray, kopf: str,
                        werte: list[tuple[str, tuple[int, int, int]]]
                        ) -> np.ndarray:
    """Setzt eine Kopfzeile ueber die Tafel und die Messwerte darunter.

    Der Kopf traegt Zeitpunkt und Herkunft, damit ein einzeln herausgegriffenes
    Bild noch fuer sich steht -- ohne den Dateinamen zu kennen.
    """
    breite = tafel.shape[1]
    kopfband = np.zeros((KOPFZEILE_HOEHE, breite, 3), np.uint8)
    cv2.putText(kopfband, kopf, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (255, 255, 255), 1, cv2.LINE_AA)
    teile = [kopfband, tafel]
    if werte:
        teile.append(_textblock(werte, breite))
    return np.vstack(teile)
