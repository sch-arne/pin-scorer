"""Ein gefundenes Viereck auf die Kanten im Bild nachziehen.

WOFUER -- Einwand des Nutzers am 2026-09-10 beim Blick auf die Uebersicht:

    "du triffst den Rand ja aber auch 0,0 nutze mal bitte einen Hochpassfilter,
     da es drumherum ueberwiegend schwarz ist muesste der eigentlich greifen"

Er hatte recht, und meine ersten beiden Messungen lagen daneben:

1. Globale Helligkeitsmaske -- lieferte fuer alle vier Seiten exakt den
   Suchrand zurueck, weil die helle Flaeche den ganzen Ausschnitt fuellte.
2. Staerkste Kante in einem Band von +-14 px -- erwischte oben und unten das
   schwarze Anzeigefenster, dessen Rand staerker ist als die Silhouette.

Mit einem ENGEN Band (+-8 px) um die Rahmenkante trennen sich beide sauber:
Die Streuung fiel von 3 bis 5 Pixeln auf 0,4 bis 1,5.

WAS DIE MESSUNG DANN ZEIGTE -- und was der eigentliche Fehler war:

    Bahn 4, linke Kante:  Anfang -6 px, Mitte +2 px, Ende +3 px

Die Rahmenkante laeuft nicht parallel zur Tafelkante, sie ist GEKIPPT. Ueber
16 Kanten gemessen: im Mittel 2,3 Pixel Kippung, groesste 9,0. Ein blosser
Versatz waere harmlos -- er kuerzt sich heraus, weil die ROIs in normierten
Koordinaten derselben Bezugsflaeche liegen. Eine Kippung tut das nicht: Sie
verschiebt die ROIs an verschiedenen Stellen der Tafel VERSCHIEDEN weit, und
ein Pixel entschied bei den Ziffern ueber neun Prozentpunkte.

DAS VERFAHREN

Je Kante werden Stuetzstellen abgetastet, an jeder die staerkste
Helligkeitsaenderung im Band gesucht, durch die Treffer eine Gerade gelegt
(robust, mit Ausreisserabweisung) und die vier Geraden geschnitten. Das
Ergebnis sind die nachgezogenen Ecken.

WORAUF ES SICH AUSRICHTET, ist bewusst nicht als "die Silhouette" benannt: Am
oberen Rand ist die beige Leiste nur rund fuenf Pixel breit, dort kann ebenso
gut die Oberkante des Anzeigefensters gewinnen. Das ist unschaedlich, SOLANGE
Vorlage und Ziel auf dasselbe Merkmal gezogen werden -- die Bezugsflaeche muss
dieselbe sein, nicht eine bestimmte.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)


def hochpass(bild: np.ndarray) -> np.ndarray:
    """Betrag des Gradienten -- die Kanten, ohne die Flaechen."""
    grau = bild if bild.ndim == 2 else cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
    grau = cv2.GaussianBlur(grau, (3, 3), 0)
    gx = cv2.Sobel(grau, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(grau, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def _kantenpunkte(kanten: np.ndarray, a: np.ndarray, b: np.ndarray,
                  band: int, stuetzen: int, min_kontrast: float
                  ) -> tuple[np.ndarray, np.ndarray]:
    """Versatz der staerksten Kante je Stuetzstelle, in Bandkoordinaten."""
    richtung = b - a
    laenge = float(np.linalg.norm(richtung))
    if laenge < 4:
        return np.empty(0), np.empty(0)
    normale = np.array([richtung[1], -richtung[0]]) / laenge
    lagen, versaetze = [], []
    for t in np.linspace(0.12, 0.88, stuetzen):
        p = a + richtung * t
        werte = np.empty(2 * band + 1)
        for i, d in enumerate(range(-band, band + 1)):
            q = p + normale * d
            x, y = int(round(q[0])), int(round(q[1]))
            werte[i] = (kanten[y, x]
                        if 0 <= y < kanten.shape[0] and 0 <= x < kanten.shape[1]
                        else np.nan)
        if np.isnan(werte).any() or werte.max() < min_kontrast:
            continue
        lagen.append(t)
        versaetze.append(int(np.argmax(werte)) - band)
    return np.array(lagen), np.array(versaetze, dtype=float)


def _gerade(lagen: np.ndarray, versaetze: np.ndarray) -> tuple[float, float]:
    """Robuste Gerade `versatz = achse + steigung * lage`.

    Erst kleinste Quadrate, dann die Ausreisser weg und noch einmal: Ein
    einzelner Fehltreffer -- eine Schraube, ein Kabel, ein Spieler im Bild --
    zieht die Gerade sonst um mehrere Pixel.
    """
    steigung, achse = np.polyfit(lagen, versaetze, 1)
    rest = np.abs(versaetze - (achse + steigung * lagen))
    grenze = np.median(rest) * 3 + 1.0
    behalten = rest <= grenze
    if behalten.sum() >= max(6, len(lagen) // 3):
        steigung, achse = np.polyfit(lagen[behalten], versaetze[behalten], 1)
    return float(achse), float(steigung)


def _schnittpunkt(p1, r1, p2, r2):
    """Schnitt zweier Geraden (Punkt + Richtung). None, wenn parallel."""
    nenner = r1[0] * r2[1] - r1[1] * r2[0]
    if abs(nenner) < 1e-9:
        return None
    d = p2 - p1
    t = (d[0] * r2[1] - d[1] * r2[0]) / nenner
    return p1 + r1 * t


def ziehe_nach(bild: np.ndarray, quad, *, band: int = 8, stuetzen: int = 61,
               min_kontrast: float = 12.0, max_korrektur: float = 12.0,
               kanten: np.ndarray | None = None) -> list[list[float]] | None:
    """Zieht ein Viereck auf die Kanten im Bild nach.

    Rueckgabe None, wenn eine Kante zu wenige brauchbare Stuetzstellen hat
    oder die noetige Korrektur groesser ausfaellt als `max_korrektur` -- dann
    ist die Ausgangslage vermutlich falsch, und Nachziehen wuerde den Irrtum
    vergroessern statt ihn zu beheben.
    """
    if bild is None or bild.size == 0:
        return None
    ecken = np.asarray(quad, dtype=float)
    if ecken.shape != (4, 2):
        return None
    if kanten is None:
        kanten = hochpass(bild)

    geraden = []
    for i in range(4):
        a, b = ecken[i], ecken[(i + 1) % 4]
        lagen, versaetze = _kantenpunkte(kanten, a, b, band, stuetzen,
                                         min_kontrast)
        if len(lagen) < max(8, stuetzen // 4):
            log.debug("Nachziehen abgebrochen: Kante %d hat nur %d "
                      "Stuetzstellen", i, len(lagen))
            return None
        achse, steigung = _gerade(lagen, versaetze)
        richtung = b - a
        normale = np.array([richtung[1], -richtung[0]]) \
            / float(np.linalg.norm(richtung))
        # Die nachgezogene Kante: Anfangspunkt plus Normalenversatz, und die
        # Richtung folgt der Steigung ueber die Kantenlaenge.
        p0 = a + normale * achse
        p1 = b + normale * (achse + steigung)
        geraden.append((p0, p1 - p0))

    neu = []
    for i in range(4):
        # Ecke i ist der Schnitt der Kante (i-1 -> i) mit der Kante (i -> i+1)
        vorher = geraden[(i - 1) % 4]
        jetzt = geraden[i]
        punkt = _schnittpunkt(vorher[0], vorher[1], jetzt[0], jetzt[1])
        if punkt is None:
            return None
        neu.append(punkt)

    neu = np.array(neu, dtype=float)
    korrektur = float(np.max(np.linalg.norm(neu - ecken, axis=1)))
    if korrektur > max_korrektur:
        log.info("Nachziehen verworfen: Korrektur %.1f px ueber der Grenze "
                 "%.1f px", korrektur, max_korrektur)
        return None
    log.debug("Viereck nachgezogen, groesste Eckverschiebung %.1f px",
              korrektur)
    return [[float(x), float(y)] for x, y in neu]
