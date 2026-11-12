"""Ziffernerkennung fuer die roten 7-Segment-Anzeigen.

Warum keine OCR: Die Displays sind 7-Segment-Anzeigen, keine Schrift. Klassische
OCR ist auf Fliesstext trainiert und schneidet hier schlechter ab als eine
direkte Segment-Dekodierung -- die zudem vollstaendig erklaerbar ist: Jede
Entscheidung laesst sich auf ein einzelnes Segment zurueckfuehren.

    Segmentbelegung          Ziffer -> aktive Segmente
      aaaa                   0 = a b c d e f
     f    b                  1 =   b c
     f    b                  2 = a b   d e   g
      gggg                   3 = a b c d     g
     e    c                  4 =   b c     f g
     e    c                  5 = a   c d   f g
      dddd                   6 = a   c d e f g
                             7 = a b c
                             8 = a b c d e f g
                             9 = a b c d   f g

GEMESSEN am realen Material: Eine Ziffer misst im Originalframe rund 13x18 px,
die Segmente sind 2-3 px dick. Das ist wenig -- deshalb wird der Ausschnitt vor
der Auswertung vergroessert und jedes Segment ueber einen Bereich gemittelt,
statt einzelne Pixel abzufragen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from ..config.schema import DigitDetectionConfig

log = logging.getLogger(__name__)

# Bitmuster je Ziffer: (a, b, c, d, e, f, g)
SEGMENT_PATTERNS: dict[tuple[bool, ...], int] = {
    (True, True, True, True, True, True, False): 0,
    (False, True, True, False, False, False, False): 1,
    (True, True, False, True, True, False, True): 2,
    (True, True, True, True, False, False, True): 3,
    (False, True, True, False, False, True, True): 4,
    (True, False, True, True, False, True, True): 5,
    (True, False, True, True, True, True, True): 6,
    (True, True, True, False, False, False, False): 7,
    (True, True, True, True, True, True, True): 8,
    (True, True, True, True, False, True, True): 9,
}

# Segmentflaechen in normierten Ziffernkoordinaten: (x, y, w, h)
# Bewusst grosszuegig und von den Ecken weggerueckt -- an den Ecken beruehren
# sich benachbarte Segmente, dort waere die Messung mehrdeutig.
SEGMENT_BOXES: dict[str, tuple[float, float, float, float]] = {
    "a": (0.25, 0.00, 0.50, 0.16),   # oben
    "b": (0.72, 0.10, 0.28, 0.32),   # rechts oben
    "c": (0.72, 0.58, 0.28, 0.32),   # rechts unten
    "d": (0.25, 0.84, 0.50, 0.16),   # unten
    "e": (0.00, 0.58, 0.28, 0.32),   # links unten
    "f": (0.00, 0.10, 0.28, 0.32),   # links oben
    "g": (0.25, 0.42, 0.50, 0.16),   # Mitte
}
SEGMENT_ORDER = ("a", "b", "c", "d", "e", "f", "g")

# Zielgroesse einer Ziffer fuer die Auswertung. Deutlich groesser als das
# Original (13x18 px), damit die Segmentflaechen genug Pixel enthalten.
DIGIT_WIDTH = 30
DIGIT_HEIGHT = 50


@dataclass(frozen=True)
class DigitReading:
    """Ergebnis einer Zifferngruppe."""

    text: str                       # z.B. "012"; "?" fuer unlesbare Stellen
    value: int | None               # None, wenn nicht vollstaendig lesbar
    confidence: float
    digits: tuple[str, ...] = ()    # Einzelziffern
    scores: tuple[float, ...] = ()  # Confidence je Stelle
    # Moegliche Werte je Stelle, wenn die Lesung nicht eindeutig war.
    #
    # Statt eine unentschiedene Ziffer nur als '?' zu melden, wird
    # weitergereicht, ZWISCHEN WELCHEN Ziffern sie schwankt. Damit kann eine
    # andere Quelle sie aufloesen -- und die Pruefung bleibt trotzdem ehrlich:
    # Liegt der Wert der anderen Quelle nicht unter den Kandidaten, ist es ein
    # echter Widerspruch.
    candidates: tuple[tuple[int, ...], ...] = ()
    # Wahrscheinlichkeitsverteilung je Stelle, absteigend sortiert:
    # ((9, 0.85), (4, 0.12), (8, 0.02), ...)
    #
    # DIE IDEE (Nutzer, 2026-09-15): *"jede Ziffer gibt an, zu 0,1% eine 1, zu
    # 5,2% eine 2 usw. und zu 85% eine 9 -- dann koennten wir uns immer die
    # top Kandidaten anschauen und daraus Rueckschluesse ziehen."*
    #
    # `candidates` sagt WELCHE Werte moeglich sind, diese Verteilung sagt WIE
    # WAHRSCHEINLICH jeder ist. Der Unterschied entscheidet: {4, 9} kann ein
    # klarer Fall mit einem Zweifel sein oder ein echter Muenzwurf -- und nur
    # im zweiten Fall darf eine andere Quelle die Lesung ueberstimmen.
    verteilung: tuple[tuple[tuple[int, float], ...], ...] = ()

    def wahrscheinlichkeit(self, stelle: int, wert: int) -> float:
        """Wie wahrscheinlich ist dieser Wert an dieser Stelle?

        Ohne Verteilung wird auf das Gemeldete zurueckgefallen: die gelesene
        Ziffer gilt als sicher, ein Kandidat als gleichverteilt moeglich. So
        bleibt der Aufrufer von der Frage verschont, ob es eine Verteilung gibt.
        """
        if stelle < len(self.verteilung) and self.verteilung[stelle]:
            for w, p in self.verteilung[stelle]:
                if w == wert:
                    return p
            return 0.0
        if stelle < len(self.digits) and self.digits[stelle].isdigit():
            return 1.0 if int(self.digits[stelle]) == wert else 0.0
        if stelle < len(self.candidates) and self.candidates[stelle]:
            return (1.0 / len(self.candidates[stelle])
                    if wert in self.candidates[stelle] else 0.0)
        return 0.1        # nichts bekannt: zehn Ziffern, gleichverteilt

    @property
    def is_readable(self) -> bool:
        return self.value is not None

    @classmethod
    def unreadable(cls, reason: str = "") -> DigitReading:
        return cls(text="", value=None, confidence=0.0)

    def to_dict(self) -> dict:
        return {"text": self.text, "value": self.value,
                "confidence": round(self.confidence, 3),
                "digits": list(self.digits),
                "candidates": [list(k) for k in self.candidates],
                "verteilung": [[[w, round(p, 4)] for w, p in stelle]
                               for stelle in self.verteilung]}


class SevenSegmentDetector:
    """Liest rote 7-Segment-Ziffern aus einem ROI-Ausschnitt."""

    def __init__(self, cfg: DigitDetectionConfig) -> None:
        self.cfg = cfg

    # ------------------------------------------------------------ Vorstufen

    def _red_mask(self, patch: np.ndarray) -> np.ndarray:
        """Isoliert die leuchtenden Segmente vom dunklen Displayhintergrund.

        GEMESSEN -- und das Ergebnis war nicht das erwartete: Die Anzeige ist
        stark ueberstrahlt. Die Segmentmitten sind nahezu weiss (R=255, G=141,
        B=178), nur die Raender bleiben gesaettigt rot. Eine Maske ueber die
        Rot-Dominanz (R-G > 45) erfasst deshalb nur die Umrisse und liefert
        hohle Ziffern, die kein Segmentmuster ergeben.

        Was traegt, ist die Trennung **hell gegen dunkel**: Das Display ist
        schwarz (Messwert 24), die Segmente sind hell (bis 255). Otsu findet
        diese Schwelle selbst und bleibt damit unabhaengig von Belichtung und
        Bahnposition -- ein fester Wert muesste je Tafel nachgezogen werden.
        """
        red = patch[:, :, 2]
        if red.size == 0:
            return np.zeros_like(red, dtype=np.uint8)

        _, mask = cv2.threshold(red, 0, 255,
                                cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return mask

    @staticmethod
    def _drop_small_components(mask: np.ndarray,
                               min_height_ratio: float = 0.45) -> np.ndarray:
        """Entfernt Bildteile, die zu flach fuer eine Ziffer sind.

        Ziffern reichen ueber nahezu die volle Displayhoehe. Reflexe,
        Rahmenstuecke und Streupixel sind flach -- die Hoehe trennt beides
        zuverlaessig, waehrend die Flaeche es nicht taete (eine "1" ist
        flaechenarm, aber voll hoch).
        """
        if mask.size == 0 or mask.max() == 0:
            return mask

        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        if count <= 1:
            return mask

        heights = stats[1:, cv2.CC_STAT_HEIGHT]
        if heights.size == 0:
            return mask

        threshold = max(2.0, float(heights.max()) * min_height_ratio)
        keep = np.zeros_like(mask)
        for index in range(1, count):
            if stats[index, cv2.CC_STAT_HEIGHT] >= threshold:
                keep[labels == index] = 255

        return keep if keep.max() > 0 else mask

    @staticmethod
    def _trim_vertical(mask: np.ndarray) -> np.ndarray:
        """Nur vertikal zuschneiden -- Gehaeusestreifen weg, x-Nullpunkt bleibt.

        Wird gebraucht, wenn ein horizontales Ziffernraster in ROI-Koordinaten
        vorliegt: Dann darf sich der x-Nullpunkt nicht verschieben, die
        vertikale Ausrichtung ist aber trotzdem noetig.
        """
        if mask.size == 0:
            return mask
        cleaned = SevenSegmentDetector._drop_small_components(mask)
        row_fill = (cleaned > 0).mean(axis=1)
        keep = row_fill < 0.92
        if not keep.any():
            return cleaned
        height = mask.shape[0]
        first = int(np.argmax(keep))
        last = height - int(np.argmax(keep[::-1]))
        trimmed = cleaned[first:last, :]
        if trimmed.size == 0:
            return cleaned
        rows = np.where((trimmed > 0).any(axis=1))[0]
        if rows.size == 0:
            return trimmed
        return trimmed[rows[0]:rows[-1] + 1, :]

    @staticmethod
    def _trim_to_digits(mask: np.ndarray) -> np.ndarray:
        """Beschneidet die Maske auf den tatsaechlichen Zifferninhalt.

        Zwei Aufgaben:

        1. Der ROI enthaelt am Rand oft einen Streifen Tafelgehaeuse. Das ist
           hell und wuerde als Segment zaehlen. Solche Zeilen sind fast
           vollstaendig gefuellt -- daran lassen sie sich erkennen.
        2. Der Zuschnitt macht die Erkennung **tolerant gegen ungenaue
           Kalibrierung**: Sitzt der ROI ein paar Pixel daneben, richtet sich
           die Auswertung trotzdem am Zifferninhalt aus.
        """
        if mask.size == 0:
            return mask

        height, width = mask.shape

        # Stoerflecken entfernen, BEVOR die Bounding-Box bestimmt wird. Sie sind
        # nicht harmlos: Ein Fleck am linken Rand zieht die Box auf, die Ziffern
        # liegen dann versetzt in ihren Zellen, und JEDE Segmentmessung danach
        # ist falsch. Genau daran ist die erste Fassung gescheitert.
        #
        # Gefiltert wird ueber die HOEHE der Komponenten, nicht ueber ihre
        # Flaeche: Eine "1" hat wenig Flaeche, ist aber so hoch wie eine "8".
        # Ein Reflex oder Rahmenstueck ist dagegen flach.
        cleaned = SevenSegmentDetector._drop_small_components(mask)

        row_fill = (cleaned > 0).mean(axis=1)
        # Zeilen, die fast durchgehend hell sind, sind Gehaeuse -- keine Ziffer
        # hat eine vollstaendig gefuellte Zeile.
        keep = row_fill < 0.92
        if not keep.any():
            return cleaned

        first, last = int(np.argmax(keep)), height - int(np.argmax(keep[::-1]))
        trimmed = cleaned[first:last, :]
        if trimmed.size == 0:
            return cleaned

        # Zuschnitt nur auf Zeilen/Spalten mit nennenswertem Inhalt. Ein
        # einzelnes Pixel darf die Bounding-Box nicht aufziehen.
        min_pixels = max(1, int(0.06 * trimmed.shape[0]))
        rows = np.where((trimmed > 0).sum(axis=1) >= 1)[0]
        cols = np.where((trimmed > 0).sum(axis=0) >= min_pixels)[0]
        if rows.size == 0 or cols.size == 0:
            return trimmed
        return trimmed[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]

    def _digit_boxes(self, mask: np.ndarray, expected: int) -> list[tuple[int, int]]:
        """Teilt die Maske in `expected` Ziffernspalten.

        Drei Stufen, von der verlaesslichsten zur allgemeinsten:

        1. **Echte Luecken** zwischen den Ziffern -- am genauesten, aber nur
           nutzbar, wenn sich genau `expected` Gruppen ergeben.
        2. **Rechtsbuendig mit fester Ziffernbreite.** GEMESSEN: Eine Ziffer ist
           rund 0,65 mal so breit wie hoch (Werte 0,53-0,71 ueber alle Felder).
           Rechtsbuendig, weil die Displays fuehrende Nullen zeigen und jede
           Ziffer 0-9 rechts ein Segment besitzt -- der rechte Rand ist damit
           immer eine echte Ziffernkante. Der linke ist es nicht: Eine fuehrende
           "1" hat links nichts, wodurch sich der Inhalt scheinbar verschiebt.
           Genau daran scheiterte die gleichmaessige Teilung bei "001".
        3. **Gleichmaessig teilen** -- nur als letzter Ausweg.
        """
        height, width = mask.shape
        filled = mask.sum(axis=0) > 0

        groups: list[tuple[int, int]] = []
        start: int | None = None
        for x, is_filled in enumerate(filled):
            if is_filled and start is None:
                start = x
            elif not is_filled and start is not None:
                groups.append((start, x))
                start = None
        if start is not None:
            groups.append((start, len(filled)))

        groups = [(a, b) for a, b in groups if b - a >= 2]
        if len(groups) == expected:
            return groups

        # Stufe 2: feste Ziffernbreite aus der Hoehe, rechtsbuendig aufgereiht
        pitch = width / expected
        expected_pitch = self.cfg.digit_aspect_ratio * height
        if not (0.55 * height <= pitch <= 0.85 * height):
            pitch = expected_pitch

        boxes: list[tuple[int, int]] = []
        for i in range(expected):
            # von rechts nach links abzaehlen
            right = width - (expected - 1 - i) * pitch
            left = right - pitch
            boxes.append((max(0, int(round(left))), min(width, int(round(right)))))
        return boxes

    def _segment_threshold(self, fills: list[float]) -> float:
        """Bestimmt die Schwelle zwischen aktiven und inaktiven Segmenten.

        Ein fester Wert traegt nicht: GEMESSEN lagen echte Werte bei 0,25 (aktiv)
        und 0,39 (inaktiv) -- beide dicht an einer festen Schwelle von 0,35, aber
        auf der jeweils falschen Seite. Grund sind Ueberstrahlung und die geringe
        Aufloesung von 13x18 px je Ziffer.

        Innerhalb EINER Ziffer sind die Verhaeltnisse dagegen stabil: Aktive
        Segmente sind deutlich voller als inaktive. Die groesste Luecke in den
        sortierten Fuellgraden trennt beide Gruppen zuverlaessiger als jeder
        absolute Wert.

        Der konfigurierte Wert bleibt die Rueckfallebene -- etwa wenn alle
        Segmente aehnlich gefuellt sind (Ziffer "8" oder leeres Feld).
        """
        ordered = sorted(fills)
        best_gap, best_threshold = 0.0, self.cfg.segment_on_ratio

        for lower, upper in zip(ordered, ordered[1:]):
            gap = upper - lower
            if gap > best_gap:
                best_gap, best_threshold = gap, (lower + upper) / 2

        # Zu kleine Luecke heisst: keine klare Trennung -- dann lieber die
        # konfigurierte Schwelle als eine willkuerliche.
        if best_gap < self.cfg.min_segment_gap:
            return self.cfg.segment_on_ratio
        return best_threshold

    def _read_digit(self, cell: np.ndarray) -> tuple[str, float]:
        """Dekodiert eine einzelne Ziffer. Liefert (Zeichen, Confidence)."""
        if cell.size == 0:
            return "?", 0.0

        # Vertikal auf den Zifferninhalt zuschneiden -- aber NICHT horizontal.
        #
        # Vertikal ist es noetig: Ein Versatz von zwei Pixeln laesst das obere
        # oder untere Segment aus seiner Messflaeche rutschen. GEMESSEN sind
        # genau solche Faelle aufgetreten: einmal fehlte "a", einmal "d" --
        # gegenlaeufig, also kein fester Offset, sondern Lage im Einzelfall.
        #
        # Horizontal waere derselbe Zuschnitt ein Fehler: Eine "1" belegt nur
        # die rechte Haelfte ihrer Zelle. Auf volle Breite gestreckt laegen ihre
        # Segmente b und c in der Mitte -- und die Ziffer waere unlesbar.
        rows = np.where((cell > 0).any(axis=1))[0]
        if rows.size >= 2:
            cell = cell[rows[0]:rows[-1] + 1, :]

        cell = cv2.resize(cell, (DIGIT_WIDTH, DIGIT_HEIGHT),
                          interpolation=cv2.INTER_AREA)

        fills: list[float] = []
        for name in SEGMENT_ORDER:
            x, y, w, h = SEGMENT_BOXES[name]
            x0, y0 = int(x * DIGIT_WIDTH), int(y * DIGIT_HEIGHT)
            x1, y1 = int((x + w) * DIGIT_WIDTH), int((y + h) * DIGIT_HEIGHT)
            region = cell[y0:y1, x0:x1]
            fills.append(float(region.mean() / 255.0) if region.size else 0.0)

        active = tuple(f >= self._segment_threshold(fills) for f in fills)
        digit = SEGMENT_PATTERNS.get(active)

        if digit is None:
            # Kein gueltiges Muster -- naechstliegendes suchen, aber die
            # Unsicherheit im Ergebnis abbilden statt sie zu verschweigen.
            best, best_distance = None, 99
            for pattern, value in SEGMENT_PATTERNS.items():
                distance = sum(1 for p, a in zip(pattern, active) if p != a)
                if distance < best_distance:
                    best, best_distance = value, distance
            if best is None or best_distance > 1:
                return "?", 0.0
            return str(best), 0.35

        # Confidence aus der Trennschaerfe: Wie weit liegen die Fuellgrade von
        # der Schwelle entfernt? Klare Segmente ergeben hohe Sicherheit.
        margins = [abs(f - self.cfg.segment_on_ratio) for f in fills]
        confidence = min(1.0, 0.5 + 2.0 * min(margins))
        return str(digit), confidence

    # ---------------------------------------------------------------- Lesen

    def detect(self, patch: np.ndarray, expected_digits: int) -> DigitReading:
        """Liest eine Zifferngruppe aus einem ROI-Ausschnitt.

        Args:
            patch: BGR-Ausschnitt des Displays.
            expected_digits: Erwartete Stellenzahl (3 fuer die Wurfnummer usw.).
        """
        if patch is None or patch.size == 0 or expected_digits < 1:
            return DigitReading.unreadable("leerer Ausschnitt")

        mask = self._red_mask(patch)
        if mask.max() == 0:
            # Anzeige dunkel oder ROI falsch platziert -- kein Wert, aber auch
            # kein Fehler: Das unterscheidet sich von einer Fehlmessung.
            return DigitReading.unreadable("keine leuchtenden Segmente")

        mask = self._trim_to_digits(mask)
        if mask.size == 0 or mask.max() == 0:
            return DigitReading.unreadable("kein Zifferninhalt nach Zuschnitt")

        # Vergroessern, damit die Segmentflaechen genug Pixel enthalten
        scale = max(1, int(np.ceil(DIGIT_HEIGHT / max(1, mask.shape[0]))))
        if scale > 1:
            mask = cv2.resize(mask, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_LINEAR)

        characters: list[str] = []
        scores: list[float] = []
        for x0, x1 in self._digit_boxes(mask, expected_digits):
            character, score = self._read_digit(mask[:, x0:x1])
            characters.append(character)
            scores.append(score)

        text = "".join(characters)
        value = int(text) if text.isdigit() else None
        confidence = float(np.mean(scores)) if scores else 0.0
        if value is None:
            confidence = min(confidence, 0.3)

        return DigitReading(text=text, value=value, confidence=confidence,
                            digits=tuple(characters), scores=tuple(scores))
