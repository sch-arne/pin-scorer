"""Die Bereiche je Tafel einzeln nachziehen -- gruppenweise gegen die Vorlage.

DIE BEOBACHTUNG (Nutzer, 2026-09-11):

    "Die Lampen und die Ziffern lagen zum Teil leicht daneben ... Ich hatte
     das Gefuehl, dass aber jedes Board leicht anders verschoben war."

GEMESSEN 2026-09-11, zwei Quellen (Aufzeichnung des Spieltags und
`verbandsliga_voll.mp4`), Versatz in Vorlagenpixeln gegen das Musterbild:

    Gruppe        Tafel 1   Tafel 2   Tafel 3   Tafel 4
    lampen        -0,07     -0,07     +0,14     -0,11      (dx)
    gruenlampe    -0,94     -0,36     +0,34     +0,69      (dx)
    zeile_unten   -0,48     -0,12     +0,44     +0,38      (dx)
    zeile_unten   -0,48     -0,45     -0,47     -0,48      (dy)

Zwei verschiedene Dinge stecken darin, und sie brauchen verschiedene Antworten:

1. **Ein Anteil, der auf allen vier Tafeln gleich ist** -- die untere
   Ziffernzeile sitzt durchweg 0,47 px zu tief, die Fehlwurfanzeige 0,45 px zu
   weit links. Das ist ein Fehler der BAUART, nicht des Fundes; er war auf
   beiden Quellen bis auf 0,03 px identisch.
2. **Ein Anteil, der je Tafel verschieden ist** -- und zwar von links nach
   rechts zunehmend. Die Gruenlampe wandert ueber die vier Tafeln um 1,6 px.
   Die Lampenraute macht das NICHT mit: Innerhalb einer Tafel wollen Lampen und
   Ziffernzeile unterschiedlich weit verschoben werden. Eine Verschiebung der
   ganzen Tafel kann das also gar nicht einfangen -- es ist eine Restverzerrung,
   die Massstab, Drehung und Eckenkorrektur uebriglassen.

Deshalb wird GRUPPENWEISE nachgezogen, nicht tafelweise.

WARUM DAS MASS NICHT ZIRKULAER IST: Verglichen wird die entzerrte Tafel mit dem
MUSTERBILD -- Bild gegen Bild. Ein Kriterium, das am Leseergebnis haengt, hat
hier schon einmal in die falsche Richtung geschoben (`digit_align`, verworfen
2026-09-10: die dunklen Fenster verschmelzen zu einem Fleck, dessen Schwerpunkt
mit den leuchtenden Ziffern wandert). Verglichen werden nur die MASKIERTEN
Pixel, also Gehaeuse und Fensterrahmen; brennende Lampen und wechselnde Ziffern
bleiben draussen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)

# NUR DIE LAMPEN -- und das ist gemessen, nicht vorsichtshalber.
#
# Der Feinschliff richtet an der STRUKTUR aus: Gehaeuse, Rahmen, Schattenkanten.
# Fuer eine Lampe ist das genau richtig -- sie SITZT an dieser Struktur. Fuer
# eine Ziffernstelle nicht: Ihr Rahmen sagt, wo das Fenster ist, aber nicht, wo
# die Zelle im Fenster beginnt.
#
# GEMESSEN 2026-09-11 an 7290 beleuchteten Ziffernzellen der Aufzeichnung,
# sauber gelesene Zellen je Feld:
#
#     Feld            automatisch   mit Ziffern-Feinschliff
#     throw_number        86,1 %          79,2 %
#     pin_count           71,5 %          47,8 %
#     total_b             26,4 %          31,9 %
#     left_display        70,0 %          77,8 %
#     insgesamt           56,8 %          57,2 %   (kein Muster 7,1 -> 8,5 %)
#
# Zwei Felder besser, zwei schlechter, insgesamt ein Nullsummenspiel mit einem
# klaren Verlierer (pin_count, minus 24 Punkte). Ein Verfahren, das mal so und
# mal so ausgeht, gehoert nicht eingeschaltet. Fuer die Ziffern gibt es das
# richtige Kriterium bereits: `digit_zero_fit` richtet an den NULLEN aus, also
# an einem bekannten Sollwert statt an der Gehaeusestruktur.
GRUPPEN: dict[str, tuple[str, ...]] = {
    "lampen": ("pin_lamp",),
    "gruenlampe": ("green_lamp",),
}

# Polster um eine Gruppe, in Vorlagenpixeln. Ohne es laege der Rahmen des
# Anzeigefensters -- die eigentliche Struktur -- genau auf der Schnittkante.
POLSTER = 10


@dataclass
class Feinversatz:
    """Was eine Gruppe an Versatz braucht, und wie sicher das ist."""

    dx: float
    dy: float
    vorher: float
    nachher: float
    pixel: int

    @property
    def betrag(self) -> float:
        return float(np.hypot(self.dx, self.dy))


def gruppe_von(name: str) -> str | None:
    """Zu welcher Gruppe gehoert ein Bereich? None = zu keiner."""
    for gruppe, anfaenge in GRUPPEN.items():
        if name.startswith(anfaenge):
            return gruppe
    return None


def kasten(rois, gruppe: str, breite: int, hoehe: int):
    """Umfassendes Rechteck einer Gruppe in Vorlagenpixeln, mit Polster."""
    teile = [r.rect for r in rois if gruppe_von(r.name) == gruppe]
    if not teile:
        return None
    x0 = min(x for x, _, _, _ in teile) * breite - POLSTER
    y0 = min(y for _, y, _, _ in teile) * hoehe - POLSTER
    x1 = max(x + w for x, _, w, _ in teile) * breite + POLSTER
    y1 = max(y + h for _, y, _, h in teile) * hoehe + POLSTER
    return (int(max(0, x0)), int(max(0, y0)),
            int(min(breite, x1)), int(min(hoehe, y1)))


def _zncc(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float:
    x = a[m].astype(np.float64)
    y = b[m].astype(np.float64)
    x -= x.mean()
    y -= y.mean()
    nenner = np.sqrt((x * x).sum() * (y * y).sum())
    return float((x * y).sum() / nenner) if nenner > 0 else float("nan")


def _scheitel(links: float, mitte: float, rechts: float) -> float:
    """Scheitel der Parabel durch drei Punkte -- Subpixel ohne Iteration."""
    nenner = links - 2 * mitte + rechts
    if abs(nenner) < 1e-12:
        return 0.0
    return float(np.clip(0.5 * (links - rechts) / nenner, -1.0, 1.0))


def entzerrt(grau: np.ndarray, quad, breite: int, hoehe: int) -> np.ndarray:
    """Das Bild im Raum der VORLAGE -- dort wird gemessen und geschoben."""
    ecken = np.float32([[0, 0], [breite - 1, 0], [breite - 1, hoehe - 1],
                        [0, hoehe - 1]])
    M = cv2.getPerspectiveTransform(ecken, np.float32(quad))
    return cv2.warpPerspective(grau, M, (breite, hoehe),
                               flags=cv2.WARP_INVERSE_MAP)


def feinversatz(muster: np.ndarray, maske: np.ndarray, ziel: np.ndarray,
                bereich, *, weite: int = 5,
                min_pixel: int = 200) -> Feinversatz | None:
    """Um wie viel liegt ein Ausschnitt der Tafel neben der Vorlage?

    None, wenn zu wenig Unveraenderliches im Ausschnitt liegt -- ein Ergebnis
    aus drei Dutzend Pixeln waere eine Zahl ohne Aussage.
    """
    x0, y0, x1, y1 = bereich
    vorlage = muster[y0:y1, x0:x1]
    m = maske[y0:y1, x0:x1].astype(bool)
    if m.sum() < min_pixel:
        return None

    gitter = np.full((2 * weite + 1, 2 * weite + 1), -2.0)
    for iy, dy in enumerate(range(-weite, weite + 1)):
        for ix, dx in enumerate(range(-weite, weite + 1)):
            ausschnitt = ziel[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
            if ausschnitt.shape != vorlage.shape:
                continue
            wert = _zncc(vorlage, ausschnitt, m)
            if not np.isnan(wert):
                gitter[iy, ix] = wert

    iy, ix = np.unravel_index(int(np.argmax(gitter)), gitter.shape)
    dy, dx = float(iy - weite), float(ix - weite)
    # Subpixel nur, wenn das Maximum nicht am Rand des Fensters klebt: Dort
    # liegt der wahre Scheitel ausserhalb, und die Parabel loege.
    if 0 < ix < 2 * weite:
        dx += _scheitel(gitter[iy, ix - 1], gitter[iy, ix], gitter[iy, ix + 1])
    if 0 < iy < 2 * weite:
        dy += _scheitel(gitter[iy - 1, ix], gitter[iy, ix], gitter[iy + 1, ix])
    return Feinversatz(dx, dy, float(gitter[weite, weite]),
                       float(gitter[iy, ix]), int(m.sum()))


def messe(bahn, muster: np.ndarray, maske: np.ndarray,
          bilder: list[np.ndarray], *, weite: int = 5, min_pixel: int = 200,
          max_versatz: float = 3.0) -> dict[str, tuple[float, float]]:
    """Versatz je Gruppe, Median ueber mehrere Bilder.

    MEHRERE BILDER, WEIL EINES SCHWANKT: GEMESSEN 2026-09-11 ueber vier
    Stellen streut derselbe Wert um bis zu 0,4 px -- in der Groessenordnung
    des Effekts selbst. Der Median ueber die Bilder, die die Suche ohnehin
    gesehen hat, kostet nichts und nimmt das Schwanken heraus.

    VERWORFEN WIRD, WAS NICHT BESSER WIRD: Ein Versatz, der die
    Uebereinstimmung nicht erhoeht, ist Rauschen. Und einer ueber
    `max_versatz` ist kein Feinschliff mehr -- dann stimmt etwas anderes
    nicht, und Schieben wuerde den Fehler nur verstecken.
    """
    hoehe, breite = muster.shape[:2]
    gefunden: dict[str, list[tuple[float, float]]] = {}
    for bild in bilder:
        grau = (cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY) if bild.ndim == 3
                else bild)
        ziel = entzerrt(grau, bahn.quad, breite, hoehe)
        for gruppe in GRUPPEN:
            k = kasten(bahn.rois, gruppe, breite, hoehe)
            if k is None:
                continue
            versatz = feinversatz(muster, maske, ziel, k, weite=weite,
                                  min_pixel=min_pixel)
            if versatz is None or versatz.nachher <= versatz.vorher:
                continue
            if versatz.betrag > max_versatz:
                log.debug("Bahn %s, %s: Versatz %.1f px verworfen (Grenze %.1f)",
                          bahn.lane_id, gruppe, versatz.betrag, max_versatz)
                continue
            gefunden.setdefault(gruppe, []).append((versatz.dx, versatz.dy))

    ergebnis: dict[str, tuple[float, float]] = {}
    for gruppe, werte in gefunden.items():
        ergebnis[gruppe] = (float(np.median([w[0] for w in werte])),
                            float(np.median([w[1] for w in werte])))
    return ergebnis


def schleife_nach(bahn, muster: np.ndarray, maske: np.ndarray,
                  bilder: list[np.ndarray], **kwargs) -> dict[str, tuple[float, float]]:
    """Misst den Versatz je Gruppe und wendet ihn auf die Bereiche an.

    Geschoben wird in normierten Tafelkoordinaten -- der gemessene Versatz
    steht in Vorlagenpixeln und wird durch die Vorlagenkante geteilt. Damit
    bleibt die Korrektur unabhaengig davon, wie gross die Tafel im Bild steht.
    """
    if not bilder:
        return {}
    hoehe, breite = muster.shape[:2]
    versatz = messe(bahn, muster, maske, bilder, **kwargs)
    if not versatz:
        return {}

    for i, roi in enumerate(bahn.rois):
        gruppe = gruppe_von(roi.name)
        if gruppe not in versatz:
            continue
        dx, dy = versatz[gruppe]
        x, y, w, h = roi.rect
        # In der Tafel bleiben: Ein Bereich, der darueber hinausragt, faellt
        # erst beim Speichern auf -- `model_copy` prueft nichts.
        neu_x = min(max(x + dx / breite, 0.0), max(0.0, 1.0 - w))
        neu_y = min(max(y + dy / hoehe, 0.0), max(0.0, 1.0 - h))
        bahn.rois[i] = roi.model_copy(update={"rect": (neu_x, neu_y, w, h)})

    log.info("Bahn %s feingeschliffen: %s", bahn.lane_id,
             ", ".join(f"{g} {d[0]:+.2f}/{d[1]:+.2f}"
                       for g, d in sorted(versatz.items())))
    return versatz
