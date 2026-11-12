"""Ziffernerkennung per Template Matching mit Positionssuche.

Warum diese Stufe: Die direkte Segment-Dekodierung (`digit_detector.py`) wurde am
realen Material gemessen und erreichte nur 5 von 11 bekannten Werten. Die Ursache
ist nicht die Dekodierung selbst, sondern die **Positionierung der Ziffernzellen**:
Bei 13x18 px je Ziffer verschiebt schon ein Versatz von zwei Pixeln ein Segment
aus seiner Messflaeche. Eine hoehere Aufloesung half nicht -- gemessen identische
Trefferquote bei 440x530, 880x1060 und 1320x1590, weil Interpolation keine
Information hinzufuegt.

Template Matching loest genau dieses Problem: Statt die Zellgrenzen vorab zu
bestimmen, wird jede Ziffer **gesucht**. Ein Versatz zeigt sich dann als
schlechtere Korrelation und nicht als falsche Ziffer.

Die Templates werden aus der 7-Segment-Geometrie **synthetisch erzeugt**, nicht
aus Bildmaterial gelernt. Damit gibt es keine Trainingsdaten zu pflegen, und die
Erkennung bleibt vollstaendig erklaerbar.
"""

from __future__ import annotations

import logging
from functools import lru_cache

import cv2
import numpy as np

from ..config.schema import DigitDetectionConfig
from .digit_detector import DigitReading, SevenSegmentDetector

log = logging.getLogger(__name__)

# Welche Segmente je Ziffer leuchten
DIGIT_SEGMENTS: dict[int, str] = {
    0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg",
    5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg",
}

TEMPLATE_WIDTH = 20
TEMPLATE_HEIGHT = 32


@lru_cache(maxsize=4)
def build_templates(width: int = TEMPLATE_WIDTH,
                    height: int = TEMPLATE_HEIGHT,
                    thickness: int = 4) -> dict[int, np.ndarray]:
    """Erzeugt fuer jede Ziffer ein synthetisches 7-Segment-Bild.

    Gezeichnet wird mit dicken Linien, damit das Template der verwaschenen
    Realaufnahme aehnelt -- ein scharf gezeichnetes Muster korreliert mit einem
    unscharfen Bild schlechter als ein ebenfalls weiches.
    """
    margin = thickness // 2 + 1
    left, right = margin, width - margin
    top, middle, bottom = margin, height // 2, height - margin

    # Endpunkte je Segment
    lines: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
        "a": ((left, top), (right, top)),
        "b": ((right, top), (right, middle)),
        "c": ((right, middle), (right, bottom)),
        "d": ((left, bottom), (right, bottom)),
        "e": ((left, middle), (left, bottom)),
        "f": ((left, top), (left, middle)),
        "g": ((left, middle), (right, middle)),
    }

    templates: dict[int, np.ndarray] = {}
    for digit, segments in DIGIT_SEGMENTS.items():
        canvas = np.zeros((height, width), dtype=np.uint8)
        for name in segments:
            start, end = lines[name]
            cv2.line(canvas, start, end, 255, thickness)
        # Weichzeichnen: Die reale Anzeige ist ueberstrahlt und unscharf
        templates[digit] = cv2.GaussianBlur(canvas, (3, 3), 0)
    return templates


class TemplateDigitDetector:
    """Erkennt Ziffern durch Korrelation mit synthetischen Vorlagen."""

    def __init__(self, cfg: DigitDetectionConfig) -> None:
        self.cfg = cfg
        self._preprocessor = SevenSegmentDetector(cfg)
        self._templates = build_templates()

    def _match_digit(self, cell: np.ndarray) -> tuple[str, float]:
        """Vergleicht eine Zelle mit allen zehn Vorlagen.

        Returns:
            (Zeichen, Confidence). Die Confidence ergibt sich aus dem Abstand
            zwischen bester und zweitbester Uebereinstimmung -- ein knappes
            Rennen ist ein unsicheres Ergebnis, und das soll sichtbar sein.
        """
        if cell.size == 0:
            return "?", 0.0

        rows = np.where((cell > 0).any(axis=1))[0]
        if rows.size >= 2:
            cell = cell[rows[0]:rows[-1] + 1, :]
        if cell.size == 0:
            return "?", 0.0

        resized = cv2.resize(cell, (TEMPLATE_WIDTH, TEMPLATE_HEIGHT),
                             interpolation=cv2.INTER_AREA)
        resized = cv2.GaussianBlur(resized, (3, 3), 0)

        scores: list[tuple[float, int]] = []
        for digit, template in self._templates.items():
            result = cv2.matchTemplate(resized, template, cv2.TM_CCOEFF_NORMED)
            scores.append((float(result.max()), digit))

        scores.sort(reverse=True)
        best_score, best_digit = scores[0]
        second_score = scores[1][0] if len(scores) > 1 else 0.0

        if best_score < self.cfg.template_min_score:
            return "?", 0.0

        # Abstand zum Zweitplatzierten als Sicherheitsmass
        margin = best_score - second_score
        confidence = min(1.0, 0.5 + 2.5 * margin)
        return str(best_digit), confidence

    def detect(self, patch: np.ndarray, expected_digits: int,
               grid: tuple[tuple[int, int], ...] | None = None) -> DigitReading:
        """Liest eine Zifferngruppe.

        Args:
            grid: Optional das gemessene Ziffernraster (x0, x1 je Ziffer, in
                ROI-Pixeln). Ist es gesetzt, wird es dem Aufteilen nach
                Luecken vorgezogen -- GEMESSEN weicht das echte Raster um bis
                zu eine halbe Ziffernbreite von der gleichmaessigen Teilung ab
                (siehe analysis/digit_grid.py).
        """
        if patch is None or patch.size == 0 or expected_digits < 1:
            return DigitReading.unreadable("leerer Ausschnitt")

        # Ist die Anzeige beleuchtet? Otsu normalisiert und macht sonst aus
        # blossem Rauschen eine scheinbare Ziffer (siehe digit_reader.py).
        # GEMESSEN: klar lesbar 255, verblassend 196-212, fast erloschen 76-96.
        if np.percentile(patch[:, :, 2], 95) < self.cfg.min_display_brightness:
            return DigitReading.unreadable("Anzeige zu dunkel")

        mask = self._preprocessor._red_mask(patch)
        if mask.max() == 0:
            return DigitReading.unreadable("keine leuchtenden Segmente")

        if grid:
            # Das Raster gilt in ROI-Koordinaten. Deshalb hier NICHT zuschneiden:
            # Der Zuschnitt verschiebt den Nullpunkt, und das Raster laege
            # anschliessend genau um den abgeschnittenen Rand daneben -- also um
            # den Fehler, den es beheben soll. (Eine proportionale Umrechnung
            # ist ebenfalls falsch: Zuschneiden verschiebt, es skaliert nicht.)
            # Vertikal ausrichten, horizontal den Nullpunkt behalten
            mask = self._preprocessor._trim_vertical(mask)
            if mask.size == 0 or mask.max() == 0:
                return DigitReading.unreadable("kein Zifferninhalt")
            boxes = [(max(0, a), min(mask.shape[1], b)) for a, b in grid]
        else:
            mask = self._preprocessor._trim_to_digits(mask)
            if mask.size == 0 or mask.max() == 0:
                return DigitReading.unreadable("kein Zifferninhalt")
            boxes = None

        scale = max(1, int(np.ceil(TEMPLATE_HEIGHT / max(1, mask.shape[0]))))
        if scale > 1:
            mask = cv2.resize(mask, None, fx=scale, fy=scale,
                              interpolation=cv2.INTER_LINEAR)
            if boxes:
                boxes = [(int(a * scale), int(b * scale)) for a, b in boxes]

        if not boxes:
            boxes = self._preprocessor._digit_boxes(mask, expected_digits)

        characters: list[str] = []
        scores: list[float] = []
        for x0, x1 in boxes:
            character, score = self._match_digit(mask[:, x0:x1])
            characters.append(character)
            scores.append(score)

        text = "".join(characters)
        value = int(text) if text.isdigit() else None
        confidence = float(np.mean(scores)) if scores else 0.0
        if value is None:
            confidence = min(confidence, 0.3)

        return DigitReading(text=text, value=value, confidence=confidence,
                            digits=tuple(characters), scores=tuple(scores))
