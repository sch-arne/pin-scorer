"""Verschiebt die Ziffernrahmen einer Kalibrierung um wenige Pixel.

WARUM DAS EIN EIGENES MODUL IST

Eine automatisch gefundene Tafel sitzt auf ein bis drei Pixel genau. Fuer die
Lampen genuegt das -- fuer die Ziffern nicht.

GEMESSEN 2026-09-09 an der Aufzeichnung eines Verbandsligaspiels, 66 von Hand
abgelesene Stellen:

    Versatz    richtig   falsch   unlesbar
      0 px      54        7         5
     -1 px      60        3         3
     -2 px      45       19         2

EIN Pixel entscheidet ueber neun Prozentpunkte. Der Grund steckt im Leser: Er
beschneidet die Ziffer nur SENKRECHT -- eine "1" nutzt nicht die volle Breite,
ein waagerechter Zuschnitt zoege sie auf die ganze Zelle -- und skaliert dann
auf eine feste Zellbreite. Sitzt der Rahmen ein Pixel zu weit rechts, rutscht
der Balken der "1" zur Zellmitte, und die WAAGERECHTEN Segmente greifen: aus
1 wird 3. Sechs von sieben Fehlern waren genau das.

Sowohl die Oberflaeche als auch `tools/richte_ziffern_aus.py` brauchen diese
Rechnung. Zwei Kopien derselben Formel waeren zwei Gelegenheiten, sie
verschieden falsch zu machen.
"""

from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)

# Diese Felder tragen Ziffern; alles andere bleibt unberuehrt.
ZIFFERNFELDER: tuple[str, ...] = ("throw_number", "pin_count", "total_a",
                                  "total_b", "left_display")

# Die einzelnen Stellen heissen `digit_<feld>_<n>`.
#
# ACHTUNG, HIER LAG EIN FEHLER: Ein Filter auf die Feldnamen allein trifft sie
# NICHT. Er verschiebt dann nur die Sammel-ROI des Feldes, die zum Lesen gar
# nicht benutzt wird -- die Messung sieht keinerlei Wirkung, und man sucht den
# Fehler an der falschen Stelle.
DIGIT_PRAEFIX = "digit_"


def ist_ziffern_roi(name: str, felder: tuple[str, ...] = ZIFFERNFELDER) -> bool:
    """Trifft sowohl das Sammelfeld als auch seine einzelnen Stellen."""
    if name.startswith(felder):
        return True
    if not name.startswith(DIGIT_PRAEFIX):
        return False
    return name[len(DIGIT_PRAEFIX):].startswith(felder)


def tafelmasse(quad) -> tuple[float, float]:
    """Mittlere Kantenlaengen des Tafelvierecks in Pixeln (Breite, Hoehe).

    Gemittelt ueber die gegenueberliegenden Kanten -- bei einer schraeg
    gesehenen Tafel sind sie verschieden lang.
    """
    q = np.asarray(quad, dtype=np.float64)
    breite = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    hoehe = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    return float(breite), float(hoehe)


def verschiebe_ziffern(kalibrierung, dx: float, dy: float = 0.0, *,
                       felder: tuple[str, ...] = ZIFFERNFELDER) -> int:
    """Verschiebt alle Ziffern-ROIs um dx/dy PIXEL. Aendert die Kalibrierung.

    Gerechnet wird je Bahn: Die ROIs liegen in normierten TAFELkoordinaten
    (0..1 der Tafel, nicht des Bildes), und die Tafeln sind verschieden gross.
    Ein Pixel ist auf einer kleinen Tafel ein groesserer Anteil als auf einer
    grossen.

    Rueckgabe: die Zahl der verschobenen ROIs.
    """
    if dx == 0 and dy == 0:
        return 0

    geaendert = 0
    for bahn in kalibrierung.lanes:
        breite, hoehe = tafelmasse(bahn.quad)
        if breite <= 0 or hoehe <= 0:
            log.warning("Bahn %s: unbrauchbares Viereck, nicht verschoben",
                        getattr(bahn, "display_number", "?"))
            continue
        nx, ny = dx / breite, dy / hoehe
        for roi in bahn.rois:
            if not ist_ziffern_roi(roi.name, felder):
                continue
            x, y, w, h = roi.rect
            # Innerhalb der Tafel bleiben -- ein ROI ausserhalb 0..1 wird vom
            # Datenmodell abgelehnt, und das mitten in einer Nutzereingabe.
            roi.rect = (min(max(x + nx, 0.0), 1.0 - w),
                        min(max(y + ny, 0.0), 1.0 - h), w, h)
            geaendert += 1
    return geaendert
