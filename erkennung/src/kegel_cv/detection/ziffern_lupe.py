"""Zeigt beim Einrahmen, was der Leser aus einer Ziffer macht.

DIE IDEE (Nutzer, 2026-09-15): *"vielleicht ermöglichen, dass der Nutzer die 7
Einheiten legt? Zum Beispiel dass er wenn er eine Ziffer einrahmt die
Mittelpunkte der einzelnen Felder angezeigt bekommt und dadurch dann sieht wie
er die Ziffer zu platzieren hat?"*

WARUM DAS NÖTIG IST -- eine teuer bezahlte Einsicht. Am selben Tag wurde
versucht, die Messflächen global zu verschieben (`segment_shear`,
`segment_middle_inset`). Am beschrifteten Datensatz sah es gut aus, am
laufenden Material war es schlechter: Bahn 2 fiel von 73,7 % auf 52,8 %, weil
die neue Geometrie GÜLTIGE Muster erzeugte, wo vorher geschwiegen wurde -- und
die waren falsch.

Der Grund für das Scheitern war nicht die Richtung, sondern die Blindheit:
Niemand konnte sehen, wo die sieben Flächen auf der echten Ziffer landen. Der
Nutzer hat mit einer Handskizze in zehn Sekunden genauer getroffen als eine
Rasterung über 63 Einstellungen. Diese Lupe gibt ihm das Bild, das er dafür
braucht.

WAS SIE ZEIGT, UND WARUM GENAU DAS

    1. der Ausschnitt, wie ihn der Leser bekommt
    2. die Rotmaske daraus
    3. dieselbe Maske auf 24x40 gestaucht, MIT den sieben Messflächen
    4. je Fläche ihr Füllgrad und ob sie als "an" gilt
    5. die gelesene Ziffer und die wahrscheinlichsten Alternativen

Punkt 3 ist der Kern: Dort entscheidet sich alles, und dort sieht man sofort,
ob eine Fläche neben ihrem Segment liegt.

DIE LUPE MUSS DENSELBEN WEG GEHEN WIE DER LESER. Sie bekommt deshalb den
Ausschnitt aus dem ORIGINALBILD, nicht aus der entzerrten Tafel -- der Leser
arbeitet auf einem achsparallelen Rechteck im Frame
(`norm_rect_to_frame_bbox`). Eine Lupe, die etwas anderes zeigt als die
Messung, wäre schlimmer als keine.
"""

from __future__ import annotations

import cv2
import numpy as np

from .digit_reader import (CELL_HEIGHT, CELL_WIDTH, SEGMENT_ORDER,
                           segment_regions)

# Farben (BGR)
_AN = (80, 230, 80)
_AUS = (70, 110, 240)
_TEXT = (230, 230, 230)
_LEISE = (150, 150, 150)


def _vergroessert(bild: np.ndarray, zoom: int) -> np.ndarray:
    """Ohne Glaettung -- gezeigt werden sollen die Pixel, nicht ein Eindruck."""
    if bild.ndim == 2:
        bild = cv2.cvtColor(bild, cv2.COLOR_GRAY2BGR)
    return cv2.resize(bild, (bild.shape[1] * zoom, bild.shape[0] * zoom),
                      interpolation=cv2.INTER_NEAREST)


def _beschriftet(bild: np.ndarray, titel: str, hoehe: int) -> np.ndarray:
    rahmen = np.zeros((hoehe + 22, bild.shape[1] + 12, 3), np.uint8)
    rahmen[22:22 + bild.shape[0], 6:6 + bild.shape[1]] = bild
    cv2.putText(rahmen, titel, (4, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                _LEISE, 1)
    return rahmen


def zeichne_lupe(patch: np.ndarray, leser, *, zoom: int = 9,
                 breite: int = 560) -> np.ndarray:
    """Baut das Lupenbild zu EINEM Ziffernausschnitt.

    Args:
        patch: der Ausschnitt aus dem Originalbild (BGR), genau der Bereich,
            den auch `CalibratedDigitReader` bekommt.
        leser: ein `CalibratedDigitReader`. Uebergeben statt selbst gebaut,
            damit die Lupe DESSEN Einstellungen benutzt -- eine Lupe mit
            anderen Schwellen zeigte etwas, das nie gemessen wird.
        zoom: Vergroesserungsfaktor der gestauchten Zelle.
        breite: Zielbreite des fertigen Bildes.

    Returns:
        BGR-Bild. Bei unbrauchbarem Ausschnitt ein Bild mit Hinweistext --
        nie None, damit der Aufrufer nichts abfangen muss.
    """
    tafel = np.zeros((1, breite, 3), np.uint8)

    def hinweis(text: str) -> np.ndarray:
        bild = np.zeros((70, breite, 3), np.uint8)
        cv2.putText(bild, text, (8, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    _AUS, 1)
        return bild

    if patch is None or patch.size == 0:
        return hinweis("Ausschnitt leer -- Rahmen liegt ausserhalb des Bildes")

    fills = leser.segment_fills(patch)
    if fills is None:
        return hinweis("zu dunkel oder keine roten Pixel -- nichts zu messen")

    schwelle = leser._threshold(fills)
    zeichen, score, kandidaten, verteilung = \
        leser.read_digit_verteilung(patch)

    maske = leser._preprocessor._red_mask(patch)
    beschnitten = leser._preprocessor._trim_vertical(maske)
    genutzt = beschnitten if (beschnitten.size and beschnitten.max() > 0) \
        else maske
    zelle = cv2.resize(genutzt, (CELL_WIDTH, CELL_HEIGHT),
                       interpolation=cv2.INTER_AREA)

    # Die Zelle gross, abgedunkelt, mit den Flaechen darauf
    gross = (_vergroessert(zelle, zoom) * 0.5).astype(np.uint8)
    regionen = segment_regions(shear=leser.cfg.segment_shear,
                               middle_inset=leser.cfg.segment_middle_inset)
    for i, name in enumerate(SEGMENT_ORDER):
        rx, ry, rw, rh = regionen[name]
        an = fills[i] >= schwelle
        farbe = _AN if an else _AUS
        cv2.rectangle(gross, (rx * zoom, ry * zoom),
                      ((rx + rw) * zoom, (ry + rh) * zoom), farbe, 2)
        # Der Mittelpunkt -- danach hatte der Nutzer ausdruecklich gefragt.
        cv2.drawMarker(gross, ((rx + rw // 2) * zoom, (ry + rh // 2) * zoom),
                       farbe, cv2.MARKER_CROSS, 9, 1)
        cv2.putText(gross, name, (rx * zoom + 3, ry * zoom + 13),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, farbe, 1)

    roh = _vergroessert(patch, max(2, zoom // 2))
    rohmaske = _vergroessert(maske, max(2, zoom // 2))

    hoehe = max(gross.shape[0], roh.shape[0], rohmaske.shape[0])
    teile = [_beschriftet(roh, "Ausschnitt", hoehe),
             _beschriftet(rohmaske, "Rotmaske", hoehe),
             _beschriftet(gross, f"{CELL_WIDTH}x{CELL_HEIGHT} + Flaechen",
                          hoehe)]

    # Zahlenspalte
    spalte = np.zeros((hoehe + 22, 150, 3), np.uint8)
    cv2.putText(spalte, f"gelesen: {zeichen}", (4, 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, _TEXT, 1)
    cv2.putText(spalte, f"Schwelle {schwelle:.3f}", (4, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, _LEISE, 1)
    for i, name in enumerate(SEGMENT_ORDER):
        an = fills[i] >= schwelle
        cv2.putText(spalte, f"{name} {fills[i]:.3f}", (4, 62 + i * 17),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, _AN if an else _AUS, 1)
    for j, (wert, p) in enumerate(verteilung[:3]):
        cv2.putText(spalte, f"{wert}: {100 * p:.1f}%", (4, 200 + j * 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    _AN if j == 0 else (0, 190, 240), 1)
    teile.insert(0, spalte)

    gesamt = sum(t.shape[1] for t in teile)
    tafel = np.zeros((hoehe + 22, max(breite, gesamt), 3), np.uint8)
    x = 0
    for t in teile:
        tafel[:t.shape[0], x:x + t.shape[1]] = t
        x += t.shape[1]
    return tafel
