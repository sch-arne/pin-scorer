"""Ziffernrahmen an einer BEKANNTEN Anzeige ausrichten -- den Nullen.

WOFUER -- Vorschlag des Nutzers am 2026-09-10:

    "wie waere es, wenn er Anfangs die Ziffern ganz unten verschiebt, bis er
     die 0en halbwegs sicher sieht? Auch bei der Fehlwurfanzeige? so koennen
     wir das niemandem als 'automatisierte Kalibrierung' verkaufen..."

WARUM DAS NICHT ZIRKULAER IST

Am Anfang eines Spiels steht auf der Tafel `000`, `0`, `0000`. Das ist keine
Vermutung, sondern eine BEKANNTE Vorgabe -- also ein echter Sollwert. Damit
unterscheidet sich das Verfahren grundlegend von "verschieben, bis die
Lesung gut aussieht": Es wird nicht auf die Guete optimiert, sondern auf
einen Inhalt, der unabhaengig davon feststeht.

Ein frueherer Versuch, die Felder an ihren Anzeigefenstern auszurichten, ist
genau an dieser Unterscheidung gescheitert: Der Massstab dort mass hinterher,
was die Korrektur hergestellt hatte. Hier nicht.

DIE MITTE DES PLATEAUS, NICHT DER BESTE PUNKT

Gesucht wird nicht der Versatz mit der hoechsten Lesequalitaet, sondern die
MITTE des Bereichs, in dem alle Stellen sicher als Null gelesen werden. Ein
Rahmen am Rand dieses Bereichs liest heute richtig und morgen nicht --
genau das war der Befund vom 2026-09-09, als EIN Pixel ueber neun
Prozentpunkte entschied.

WANN ES SCHWEIGT

Zeigt die Tafel gerade keine Nullen -- mitten im Spiel, jemand steht davor,
das Feld ist dunkel -- findet sich kein Versatz, bei dem alle Stellen Null
lesen. Dann bleibt das Feld, wo es war. Ein geratener Ruck waere schlimmer
als keiner.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from .digit_shift import ist_ziffern_roi
from .model import Calibration, LaneCalibration

log = logging.getLogger(__name__)

# Felder, die zu Spielbeginn nachweislich Null zeigen.
#
# `left_display` ist die FEHLWURFANZEIGE (`detection.foul_field`) und zeigt
# `00`. Sie hatte hier zunaechst gefehlt, und ich hatte sie ausserdem mit
# `pin_count` verwechselt -- der Nutzer hat beides richtiggestellt.
NULLFELDER: tuple[str, ...] = ("throw_number", "total_a", "total_b",
                               "left_display")

# WAS SICH NICHT SELBST AUSRICHTEN KANN, ERBT VON SEINEN NACHBARN.
#
# `pin_count` -- das Feld in der Mitte der unteren Zeile -- zeigt zu
# Spielbeginn keinen Wert; es ist dunkel. Auf Nullen laesst es sich also nicht
# einstellen. Es steht aber in DERSELBEN Anzeigezeile wie Wurfnummer und
# Gesamtsumme, und der Nutzer kennt die Anlage:
#
#     "der Abstand zwischen der linkesten 0 bei Gesamtsumme und dem
#      rechtesten bei Wurfnummer zu dem Wert in der Mitte ist immer identisch"
#
# Dieselbe Zeile, derselbe Versatz. Also wird der Mittelwert dessen
# uebernommen, was fuer die beiden Nachbarn gefunden wurde.
ERBEN: dict[str, tuple[str, ...]] = {
    "pin_count": ("throw_number", "total_b"),
}
# Suchbereich in Pixeln der Originaltafel, in beiden Richtungen.
SUCHWEITE = 3
# So sicher muss eine Stelle gelesen sein, damit sie als Null zaehlt.
MIN_GUETE = 0.5


@dataclass
class Nullpassung:
    """Was die Suche fuer ein Feld gefunden hat."""

    feld: str
    dx: float
    dy: float
    guete: float
    plateau: int          # wie viele Versaetze alle Stellen als Null lasen

    @property
    def sicher(self) -> bool:
        """Ein Plateau aus mehreren Versaetzen ist mehr wert als ein Punkt.

        Ein einzelner Treffer kann Zufall sein: Sechs von sieben Segmenten
        einer Null sind aktiv, da liest sich manches versehentlich als Null.
        """
        return self.plateau >= 2 and self.guete >= MIN_GUETE


def _zellen(bahn: LaneCalibration, feld: str):
    return bahn.digit_rois(feld)


def _lies_als_null(leser, tafel: np.ndarray, zellen, dx: float,
                   dy: float) -> tuple[bool, float]:
    """Liest ein Feld mit verschobenen Rahmen. Alles Null? Und wie sicher?"""
    hoehe, breite = tafel.shape[:2]
    ausschnitte = []
    for zelle in zellen:
        x, y, w, h = zelle.rect
        x0 = int(round((x + dx) * breite))
        y0 = int(round((y + dy) * hoehe))
        x1 = int(round((x + dx + w) * breite))
        y1 = int(round((y + dy + h) * hoehe))
        if x0 < 0 or y0 < 0 or x1 > breite or y1 > hoehe or x1 <= x0 \
                or y1 <= y0:
            return False, 0.0
        ausschnitte.append(tafel[y0:y1, x0:x1])
    lesung = leser.read_field(ausschnitte)
    alles_null = bool(lesung.text) and set(lesung.text) == {"0"}
    return alles_null, float(lesung.confidence)


def passe_feld_an(leser, tafel: np.ndarray, bahn: LaneCalibration, feld: str,
                  *, suchweite: int = SUCHWEITE,
                  tafel_px: float = 160.0) -> Nullpassung | None:
    """Sucht den Versatz, bei dem das Feld sicher Nullen zeigt."""
    zellen = _zellen(bahn, feld)
    if not zellen:
        return None
    schritt = 1.0 / max(tafel_px, 1.0)

    treffer: list[tuple[float, float, float]] = []
    for i in range(-suchweite, suchweite + 1):
        for j in range(-suchweite, suchweite + 1):
            dx, dy = i * schritt, j * schritt
            null, guete = _lies_als_null(leser, tafel, zellen, dx, dy)
            if null and guete >= MIN_GUETE:
                treffer.append((dx, dy, guete))
    if not treffer:
        return None

    # DIE MITTE DES PLATEAUS: der Schwerpunkt aller Versaetze, die sicher
    # Null lesen -- nicht der einzelne beste.
    a = np.array(treffer)
    dx, dy = float(a[:, 0].mean()), float(a[:, 1].mean())
    return Nullpassung(feld=feld, dx=dx, dy=dy, guete=float(a[:, 2].max()),
                       plateau=len(treffer))


def _verschiebe(bahn: LaneCalibration, feld: str, dx: float, dy: float) -> int:
    betroffen = 0
    for roi in bahn.rois:
        if not ist_ziffern_roi(roi.name):
            continue
        if roi.name != feld and not roi.name.startswith(f"digit_{feld}_"):
            continue
        x, y, w, h = roi.rect
        roi.rect = (min(max(0.0, x + dx), 1.0 - w),
                    min(max(0.0, y + dy), 1.0 - h), w, h)
        betroffen += 1
    return betroffen


def passe_an_nullen_an(kalibrierung: Calibration, tafeln: dict[int, np.ndarray],
                       leser, *, felder: tuple[str, ...] = NULLFELDER,
                       suchweite: int = SUCHWEITE) -> dict[int, list[Nullpassung]]:
    """Richtet die Ziffernfelder aller Bahnen an ihren Nullen aus.

    `tafeln` sind die entzerrten Tafelbilder je `lane_id`. Zurueck kommt, was
    je Bahn angepasst wurde -- Felder ohne sicheren Fund fehlen darin und
    bleiben unveraendert.
    """
    bericht: dict[int, list[Nullpassung]] = {}
    for bahn in kalibrierung.lanes:
        tafel = tafeln.get(bahn.lane_id)
        if tafel is None or tafel.size == 0:
            continue
        q = np.asarray(bahn.quad, dtype=float)
        kante = (np.ptp(q[:, 0]) + np.ptp(q[:, 1])) / 2 or 160.0
        angepasst = []
        for feld in felder:
            passung = passe_feld_an(leser, tafel, bahn, feld,
                                    suchweite=suchweite, tafel_px=kante)
            if passung is None or not passung.sicher:
                log.debug("Bahn %d, %s: keine sichere Nullstellung",
                          bahn.display_number, feld)
                continue
            if _verschiebe(bahn, feld, passung.dx, passung.dy):
                angepasst.append(passung)
        # Was sich nicht selbst ausrichten kann, erbt von seinen Nachbarn
        # in derselben Anzeigezeile.
        gefunden = {p.feld: p for p in angepasst}
        for feld, nachbarn in ERBEN.items():
            quellen = [gefunden[n] for n in nachbarn if n in gefunden]
            if not quellen or not bahn.digit_rois(feld):
                continue
            dx = float(np.mean([q.dx for q in quellen]))
            dy = float(np.mean([q.dy for q in quellen]))
            if _verschiebe(bahn, feld, dx, dy):
                angepasst.append(Nullpassung(
                    feld=feld, dx=dx, dy=dy,
                    guete=min(q.guete for q in quellen),
                    plateau=min(q.plateau for q in quellen)))
                log.debug("Bahn %d: %s von %s geerbt", bahn.display_number,
                          feld, " und ".join(q.feld for q in quellen))

        if angepasst:
            bericht[bahn.display_number] = angepasst
            log.info("Bahn %d an den Nullen ausgerichtet: %s",
                     bahn.display_number,
                     ", ".join(f"{p.feld} um {p.dx * kante:+.1f}/"
                               f"{p.dy * kante:+.1f} px (Plateau {p.plateau})"
                               for p in angepasst))
    return bericht
