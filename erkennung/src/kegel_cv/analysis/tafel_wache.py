"""Was auf der Tafel nicht hingehoert -- fuer Bilder, die veroeffentlicht werden.

WARUM ES DIESE DATEI GIBT

Die Personenmaske (`detection/person_maske.py`) findet bewegten Vordergrund.
Sie hat eine Grenze, die dort auch benannt ist: **Wer stillsteht, wandert ins
Hintergrundmodell und wird nicht mehr geschwaerzt.**

Genau dieser Fall ist am 2026-09-13 im Liveticker aufgetaucht. GEMESSEN am
Mitschnitt vom 2026-09-08, Bahn 2, Frame 13489 -- ein Mensch beugt sich ueber
die Tafel und ist im Bild voll zu sehen:

    Verdeckung (Bewegung)                    0,081   unter der Schwelle 0,14
    groesster bewegter Fleck auf der Tafel   0,09 Tafelflaechen
    -> die Bewegungsmaske sieht ihn NICHT

Der Grund ist kein Fehler, sondern das Verfahren: Er bewegt sich nicht mehr.

DIE ANTWORT: EINE BEWACHTE REFERENZ

Ein Hintergrundmodell lernt bedingungslos weiter. Diese Referenz nicht -- sie
lernt **nur nach, wenn die Tafel normal aussieht**. Damit kann ein Mensch nie
hineinwandern, solange er davorsteht.

Verglichen wird nur auf den STABILEN Pixeln: Gehaeuse und Fensterrahmen. Die
Anzeigen aendern sich zu Recht, und die Maske dafuer gibt es schon
(`board_match.stabile_maske`) -- dieselbe, mit der die Tafel gefunden wird.

GEMESSEN am selben Mitschnitt, 2705 Messungen ueber 15 Minuten:

    Normalbetrieb    Median 1,41 %   95. Perzentil 2,55 %
    mit dem Menschen davor          11,9 bis 14,1 %

14,27 % ist zugleich das Maximum des ganzen Mitschnitts -- es gab genau dieses
eine Ereignis, und genau dort steht das Bild mit dem Gesicht.

WAS DAMIT NICHT GEMEINT IST

Diese Wache entscheidet **nichts** ueber Wuerfe. Sie schwaerzt Bilder, die das
Haus verlassen. Ob ein Wurf gilt, klaeren Gruenlampe, Lampen und die
Verdeckungsbremse -- wie bisher.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from ..calibration.geometry import norm_rect_to_frame_bbox

log = logging.getLogger(__name__)

# Schwelle, ab der eine Flaeche als Anzeigefenster gilt -- dieselbe wie in
# `board_match.stabile_maske`, aus demselben Grund.
DUNKEL = 57


def stabile_maske_im_ausschnitt(rois, transform, box, frame_shape,
                                rand: float = 0.02) -> np.ndarray:
    """Was im Tafelausschnitt unveraenderlich ist: 1 = vergleichbar.

    Dasselbe Prinzip wie `board_match.stabile_maske`, nur in den Koordinaten
    des AUSSCHNITTS statt der Vorlage: Alles, was leuchtet oder Text zeigt,
    faellt heraus -- Lampen, Ziffernfelder, Anzeigen. Uebrig bleiben Gehaeuse
    und Fensterrahmen.

    Die einzelnen Ziffernstellen werden uebergangen: Ihr Feld deckt sie ab, und
    einzeln gerechnet fraesse der Rand die Rahmen mit weg.
    """
    x, y, w, h = box
    maske = np.ones((h, w), bool)
    r = max(2, int(rand * max(w, h)))
    for roi in rois:
        if roi.name.startswith("digit_"):
            continue
        bx, by, bw, bh = norm_rect_to_frame_bbox(transform, roi.rect, frame_shape)
        x0, y0 = max(0, bx - x - r), max(0, by - y - r)
        x1, y1 = min(w, bx - x + bw + r), min(h, by - y + bh + r)
        if x1 > x0 and y1 > y0:
            maske[y0:y1, x0:x1] = False
    return maske


class TafelWache:
    """Haelt eine Referenz der eigenen Tafel und meldet, was nicht dazugehoert.

    Eine Wache je Bahn: Die Tafeln stehen verschieden im Bild und werden
    verschieden ausgeleuchtet.
    """

    def __init__(self, stabil: np.ndarray | None, *,
                 abweichung_grau: int = 40, schwelle: float = 0.05,
                 nachlernen_unter: float = 0.10, lernrate: float = 0.05,
                 wachstum: float = 0.10) -> None:
        # Welche Pixel des Ausschnitts vergleichbar sind (Gehaeuse, Rahmen).
        self._stabil = stabil
        self.abweichung_grau = abweichung_grau
        self.schwelle = schwelle
        self.nachlernen_unter = nachlernen_unter
        self.lernrate = lernrate
        self.wachstum = wachstum
        self._referenz: np.ndarray | None = None
        self._leiste_geprueft = False

    @property
    def bereit(self) -> bool:
        return self._referenz is not None and self._stabil is not None

    def setze_stabil(self, stabil) -> None:
        """Legt fest, welche Pixel vergleichbar sind.

        Getrennt vom Konstruktor, weil die Maske die BILDGROESSE braucht --
        die steht erst in `LaneProcessor.prepare` fest. Ohne sie vergleicht die
        Wache nichts und meldet nie etwas.
        """
        self._stabil = stabil
        self._leiste_geprueft = False
        self._referenz = None

    def vergiss_referenz(self) -> None:
        """Wirft die Referenz weg; die naechste Beobachtung lernt sie neu.

        DER GRUND (BUG-026, gemessen 2026-09-14): Die Bewachung der Referenz
        schuetzt davor, dass ein Mensch hineinwandert -- nachgelernt wird nur
        unterhalb `nachlernen_unter`. Genau das macht sie aber auch unfaehig,
        sich von einer ECHTEN Aenderung zu erholen. Im Hallenmitschnitt
        verschob sich das Bild bei Frame 215 um wenige Pixel, die Abweichung
        sprang von 3,4 auf 13 %, und die Wache haengt seither bei 25 % fest --
        13 000 Frames lang, Bahn 5 dauerhaft eingefroren.

        Wer das hier ruft, uebernimmt die Verantwortung dafuer, dass gerade
        NIEMAND vor der Tafel steht. Der einzige Aufrufer im Programm
        (`LaneProcessor`) laesst sich das vom Personenmodell bestaetigen.
        """
        self._referenz = None

    def _ohne_matrixleiste(self, ausschnitt: np.ndarray) -> None:
        """Nimmt die obere Matrixleiste aus der stabilen Maske.

        Sie ist als einzige Flaeche kein ROI und zeigt WECHSELNDEN Text -- den
        Spielernamen. Bliebe sie drin, meldete die Wache bei jedem Namenswechsel
        einen Fremdkoerper. Gefunden wird sie wie in `board_match`: breit,
        flach, dunkel, ganz oben.
        """
        if self._stabil is None or self._leiste_geprueft:
            return
        self._leiste_geprueft = True
        grau = cv2.cvtColor(ausschnitt, cv2.COLOR_BGR2GRAY)
        hoehe, breite = grau.shape[:2]
        _, dunkel = cv2.threshold(grau, DUNKEL, 255, cv2.THRESH_BINARY_INV)
        anzahl, _, kennzahlen, _ = cv2.connectedComponentsWithStats(dunkel, 8)
        for i in range(1, anzahl):
            x = kennzahlen[i, cv2.CC_STAT_LEFT]
            y = kennzahlen[i, cv2.CC_STAT_TOP]
            w = kennzahlen[i, cv2.CC_STAT_WIDTH]
            h = kennzahlen[i, cv2.CC_STAT_HEIGHT]
            if y < 0.20 * hoehe and w > 0.7 * breite and h < 0.25 * hoehe:
                self._stabil[max(0, y - 3):y + h + 3,
                             max(0, x - 3):x + w + 3] = False

    def _passend(self, ausschnitt: np.ndarray) -> np.ndarray | None:
        """Die stabile Maske auf die Groesse dieses Ausschnitts."""
        if self._stabil is None or ausschnitt.size == 0:
            return None
        h, b = ausschnitt.shape[:2]
        if self._stabil.shape[:2] != (h, b):
            self._stabil = cv2.resize(self._stabil.astype(np.uint8), (b, h),
                                      interpolation=cv2.INTER_NEAREST).astype(bool)
        return self._stabil

    def abweichung(self, ausschnitt: np.ndarray) -> float:
        """Anteil der stabilen Pixel, die von der Referenz abweichen."""
        stabil = self._passend(ausschnitt)
        if stabil is None or self._referenz is None:
            return 0.0
        if self._referenz.shape != ausschnitt.shape[:2]:
            return 0.0
        grau = cv2.cvtColor(ausschnitt, cv2.COLOR_BGR2GRAY).astype(np.float32)
        anders = (np.abs(grau - self._referenz) > self.abweichung_grau) & stabil
        nenner = int(stabil.sum())
        return float(anders.sum() / nenner) if nenner else 0.0

    def beobachte(self, ausschnitt: np.ndarray) -> float:
        """Einen Ausschnitt ansehen und die Referenz BEDINGT nachfuehren.

        Genau hier liegt der Unterschied zum Hintergrundmodell: Nachgelernt
        wird nur, solange die Tafel normal aussieht. Wer davorsteht, wandert
        deshalb nie hinein -- egal wie lange er steht.
        """
        if ausschnitt is None or ausschnitt.size == 0:
            return 0.0
        grau = cv2.cvtColor(ausschnitt, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if self._referenz is None or self._referenz.shape != grau.shape:
            self._referenz = grau.copy()
            self._leiste_geprueft = False
            self._ohne_matrixleiste(ausschnitt)
            if self._stabil is not None:
                log.info("Tafelwache eingelernt: %d von %d Pixeln vergleichbar "
                         "(%.0f %%)", int(self._stabil.sum()),
                         self._stabil.size, 100 * self._stabil.mean())
            return 0.0
        anteil = self.abweichung(ausschnitt)
        if anteil < self.nachlernen_unter:
            self._referenz = ((1 - self.lernrate) * self._referenz
                              + self.lernrate * grau)
        return anteil

    def fremdmaske(self, ausschnitt: np.ndarray) -> np.ndarray | None:
        """Was auf diesem Ausschnitt nicht hingehoert -- oder None.

        Die rohe Abweichung ist loechrig: Wo die Kleidung zufaellig die Farbe
        des Gehaeuses trifft, bleibt ein Loch. Ein halb geschwaerztes Gesicht
        ist kein geschwaerztes Gesicht -- deshalb wird die Maske geschlossen
        und verbreitert, und zwar im Verhaeltnis zur Tafel (`wachstum`), nicht
        in festen Pixeln.
        """
        if ausschnitt is None or ausschnitt.size == 0 or self._referenz is None:
            return None
        stabil = self._passend(ausschnitt)
        if stabil is None or self._referenz.shape != ausschnitt.shape[:2]:
            return None
        if self.abweichung(ausschnitt) < self.schwelle:
            return None

        grau = cv2.cvtColor(ausschnitt, cv2.COLOR_BGR2GRAY).astype(np.float32)
        # Fuer die MASKE zaehlt jede Abweichung, auch auf den Anzeigen: Steht
        # jemand davor, verdeckt er sie mit. Die stabile Maske entscheidet nur,
        # OB jemand da ist -- nicht, was geschwaerzt wird.
        maske = (np.abs(grau - self._referenz)
                 > self.abweichung_grau).astype(np.uint8) * 255
        kern = max(3, int(self.wachstum * min(ausschnitt.shape[:2]))) | 1
        form = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kern, kern))
        maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, form)
        maske = cv2.dilate(maske, form)
        return maske if cv2.countNonZero(maske) else None
