"""Schwaerzt Menschen im Bild -- und meldet, welche Tafel dabei verdeckt war.

WARUM ES DIESE DATEI GIBT

Zwei Gruende, die dasselbe Verfahren teilen.

**1. Datenschutz.** Die Aufnahmen zeigen eine Halle mit Menschen. Debugbilder,
Tafelbilder in der Datenbank und Mitschnitte tragen deren Gesichter mit sich.
Der Nutzer hat das am 2026-09-09 zur ersten Priorität erklaert.

**2. Phantomwuerfe.** Laeuft jemand vor der Tafel durch, faellt der
Gruen-Score, und die Zustandsmaschine liest daraus einen Wurf, den es nie gab.
GEMESSEN am Trainingsmitschnitt vom 2026-09-08 (13 530 Frames):

    Frame 13224  Bahn 2  0 Kegel  Ziffer unlesbar  Einigkeit 0,00
                 Vordergrund im Tafelbereich 0,197  <- hoechster Wert des Laufs

Das war der hoechste Vordergrundwert der gesamten Aufzeichnung, und genau dort
steht der Nullwurf. Ein zweiter Fall bei Frame 171 auf Bahn 4, gleiches
Muster: Ziffer unlesbar, Einigkeit 0,00, Vordergrund 0,150.

Die vorhandene Sicherung (`discard_cycles_without_throw_number`) konnte nicht
greifen, weil sie 0,9 Einigkeit bei der Wurfnummer verlangt -- und die Ziffer
war ja gerade deshalb unlesbar, WEIL jemand davorstand.

WARUM BEWEGUNG UND KEIN PERSONENMODELL

Die Kamera steht fest. Alles, was sich bewegt, ist Vordergrund -- das erfasst
Menschen ohne Modell, ohne zusaetzliche Abhaengigkeit und in wenigen
Millisekunden. Ein Personenmodell waere Eskalationsstufe 5 und braucht laut
Projektregel den Nachweis, dass die einfachere Stufe versagt.

GRENZE, die man kennen muss: Wer minutenlang stillsteht, wandert ins
Hintergrundmodell und wird dann nicht mehr geschwaerzt. Fuer die
Verdeckungsbremse ist das unerheblich -- wer stillsteht, verdeckt die Tafel
dauerhaft, und das faellt ueber `verdeckte_bahnen` sofort auf. Fuer den
Datenschutz ist es eine echte Luecke; sie ist mit `history` steuerbar und
gehoert gemessen, bevor jemand ein Modell dazubaut.

WAS NIE GESCHWAERZT WIRD

Die kalibrierten Tafelbereiche. Ziffern und Lampen AENDERN sich -- sie sind
selbst bewegter Vordergrund. Wer sie schwaerzt, loescht genau das Signal, das
gelesen werden soll. Innerhalb der Tafeln wird deshalb nur GEMESSEN.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class MaskenErgebnis:
    """Was der Maskierer an einem Frame gefunden hat.

    `bild` ist das geschwaerzte Bild -- immer gesetzt, notfalls unveraendert.
    `verdeckung` nennt je Bahn den Anteil bewegten Vordergrunds im
    Tafelbereich; `verdeckte_bahnen` die, die darueber liegen.
    """

    bild: np.ndarray
    verdeckung: dict[int, float] = field(default_factory=dict)
    verdeckte_bahnen: frozenset[int] = frozenset()
    geschwaerzte_pixel: int = 0


class PersonMaske:
    """Findet bewegten Vordergrund, schwaerzt ihn und misst Tafelverdeckung.

    Zustandsbehaftet: Das Hintergrundmodell lernt ueber die Zeit. Deshalb
    genau EIN Aufruf je Frame -- ein zweiter Aufruf verfaelscht das Modell,
    derselbe Fehler wie beim Lampendetektor.
    """

    def __init__(self, *, history: int = 500, var_threshold: float = 32.0,
                 scale: int = 4, min_blob_px: int = 400,
                 dilate_px: int = 9, occlusion_fraction: float = 0.14,
                 warmup_frames: int = 60, enabled: bool = True) -> None:
        if scale < 1:
            raise ValueError("scale muss mindestens 1 sein")
        self.enabled = enabled
        self.scale = scale
        self.min_blob_px = min_blob_px
        self.dilate_px = dilate_px
        self.occlusion_fraction = occlusion_fraction
        self.warmup_frames = warmup_frames
        self._subtraktor = cv2.createBackgroundSubtractorMOG2(
            history=history, varThreshold=var_threshold, detectShadows=False)
        # Schutzbereiche: dort wird gemessen, aber nie geschwaerzt.
        self._tafeln: dict[int, tuple[int, int, int, int]] = {}
        self._frames = 0

    def set_tafeln(self, tafeln: dict[int, tuple[int, int, int, int]]) -> None:
        """Legt die Tafelbereiche fest (Bahnnummer -> x, y, w, h im Vollbild).

        Ohne sie wird nichts geschuetzt und nichts gemessen -- der Maskierer
        schwaerzt dann jede Bewegung, auch die Ziffern.
        """
        self._tafeln = dict(tafeln)

    def verarbeite(self, bild: np.ndarray) -> MaskenErgebnis:
        """Ein Frame: schwaerzen und messen. Genau einmal je Frame aufrufen."""
        if not self.enabled or bild is None or bild.size == 0:
            return MaskenErgebnis(bild=bild)

        self._frames += 1
        h, w = bild.shape[:2]
        klein = cv2.resize(bild, (w // self.scale, h // self.scale),
                           interpolation=cv2.INTER_AREA)
        maske = self._subtraktor.apply(klein)

        # Rauschen weg. Oeffnen entfernt Einzelpixel.
        kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN, kern)

        # GEMESSEN WIRD AUF DER SAUBEREN MASKE, NICHT AUF DER DILATIERTEN.
        #
        # Der erste Entwurf mass nach der Dilatation -- und meldete 159 von 300
        # Frames als verdeckt. Kein Wunder: Ein Dilatationskern von 9 Pixeln im
        # verkleinerten Bild sind rund 36 im Vollbild, und die Tafel ist nur
        # 192 Pixel breit. Die Dilatation dient dem SCHWAERZEN (eine Person
        # soll eine geschlossene Flaeche werden), nicht dem Messen.
        verdeckung = self._miss_tafeln(maske)

        # Erst jetzt die Person zu einer Flaeche schliessen -- ein halb
        # geschwaerztes Gesicht ist kein geschwaerztes Gesicht.
        if self.dilate_px > 1:
            gross = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE, (self.dilate_px, self.dilate_px))
            maske = cv2.dilate(maske, gross)
        maske = self._entferne_kleine_flecken(maske)

        # SOLANGE DAS MODELL NOCH LERNT, GILT NICHTS ALS VERDECKT. Im ersten
        # Frame ist alles Vordergrund -- gemessen: 1,0 auf allen vier Bahnen.
        # Ohne diese Sperre fiele der Start jedes Laufs in die Bremse.
        if self._frames <= self.warmup_frames:
            verdeckung = {nr: 0.0 for nr in verdeckung}

        voll = cv2.resize(maske, (w, h), interpolation=cv2.INTER_NEAREST)
        voll = self._schuetze_tafeln(voll)

        return MaskenErgebnis(
            bild=self._schwaerze(bild, voll),
            verdeckung=verdeckung,
            verdeckte_bahnen=frozenset(
                nr for nr, anteil in verdeckung.items()
                if anteil > self.occlusion_fraction),
            geschwaerzte_pixel=int(cv2.countNonZero(voll)),
        )

    @staticmethod
    def _schwaerze(bild: np.ndarray, voll: np.ndarray) -> np.ndarray:
        """Setzt alle markierten Pixel auf schwarz.

        GEMESSEN an einem Bild von 2304x1296:

            Kopie + b[maske > 0] = 0        22,7 ms
            bitwise_and mit Inverse          4,7 ms
            Vorabpruefung, nichts zu tun     0,08 ms

        NumPy indiziert Boolesch elementweise; OpenCV rechnet vektorisiert.
        Fuenffach schneller, und in einem Budget von 40 ms je Frame ist das
        der Unterschied zwischen machbar und nicht.
        """
        if cv2.countNonZero(voll) == 0:
            return bild
        return cv2.bitwise_and(bild, bild, mask=cv2.bitwise_not(voll))

    # ------------------------------------------------------------- intern

    def _miss_tafeln(self, maske: np.ndarray) -> dict[int, float]:
        """Anteil bewegten Vordergrunds je Tafelbereich.

        GEMESSEN 2026-09-08 ueber 13 530 Frames: Echte Wuerfe erreichten
        hoechstens 0,128; die beiden Phantomwuerfe lagen bei 0,150 und 0,197.
        Der Median liegt bei 0,001 -- das Signal ist selten und deutlich.
        """
        werte: dict[int, float] = {}
        for nr, (x, y, bw, bh) in self._tafeln.items():
            mx, my = x // self.scale, y // self.scale
            mw, mh = max(1, bw // self.scale), max(1, bh // self.scale)
            aus = maske[my:my + mh, mx:mx + mw]
            werte[nr] = float((aus > 0).mean()) if aus.size else 0.0
        return werte

    def _entferne_kleine_flecken(self, maske: np.ndarray) -> np.ndarray:
        """Wirft alles weg, was zu klein fuer einen Menschen ist.

        Sonst schwaerzt jede Kugel und jeder fallende Kegel Loecher ins Bild.
        Die Schranke gilt im VERKLEINERTEN Bild.
        """
        if self.min_blob_px <= 0:
            return maske
        anzahl, marken, stats, _ = cv2.connectedComponentsWithStats(
            (maske > 0).astype(np.uint8), connectivity=8)
        behalten = np.zeros_like(maske)
        schwelle = self.min_blob_px // (self.scale * self.scale)
        for i in range(1, anzahl):
            if stats[i, cv2.CC_STAT_AREA] >= schwelle:
                behalten[marken == i] = 255
        return behalten

    def _schuetze_tafeln(self, voll: np.ndarray) -> np.ndarray:
        """Nimmt die Tafelbereiche aus der Schwaerzung heraus.

        Ziffern und Lampen aendern sich staendig und sind damit selbst
        bewegter Vordergrund. Wer sie schwaerzt, loescht das Signal.
        """
        for x, y, w, h in self._tafeln.values():
            voll[y:y + h, x:x + w] = 0
        return voll
