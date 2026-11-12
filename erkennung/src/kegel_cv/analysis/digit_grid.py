"""Vermessung des Ziffernrasters eines 7-Segment-Displays.

Der Befund, der diese Datei begruendet: Die Ziffernerkennung scheiterte nicht an
der Dekodierung, sondern an der **Positionierung der Ziffernzellen**. Alle drei
zuvor erprobten Verfahren (Segment-Dekodierung, Template Matching, das Ableiten
der Segmentflaechen aus Beispieldaten) liefen auf dieselbe Ursache hinaus.

GEMESSEN an Bahn 4, Feld `total_b` (ROI 53 px breit, 4 Ziffern), gemittelt ueber
100 Frames mit wechselnden Anzeigewerten:

    echte Grenzen:          5 | 15 | 26 | 38 | 49
    gleichmaessige Teilung: 0 | 13 | 26 | 40 | 53

Die erste Ziffer beginnt erst bei x=5, und eine Ziffer ist rund 11 px breit statt
der angenommenen 13,2. Der Versatz betraegt damit fast eine halbe Ziffernbreite --
genug, um jede Segmentmessung unbrauchbar zu machen.

Das Raster ist **Hardware**: Die Ziffernpositionen eines Displays liegen fest.
Ueber viele Frames mit unterschiedlichen Ziffern zeichnen sie sich zuverlaessig
ab, weil zwischen zwei Ziffern immer eine Luecke bleibt -- unabhaengig davon,
welche Ziffern gerade anliegen.

⚠ **STAND: Die Messung funktioniert, ihre ANWENDUNG bislang nicht.**

Das gemessene Raster ist plausibel und reproduzierbar. Wird es dem Detektor
jedoch vorgegeben, sinkt die Trefferquote deutlich:

    ohne Raster                      6/11
    mit Raster (proportional)        2/11
    mit Raster (ohne Zuschnitt)      0/11
    mit Raster (nur vert. Zuschnitt) 1/11

Vermutete Ursache, noch nicht belegt: Das Raster wurde an einem anderen Video
derselben Session gemessen; die ROI-Pixelgrenzen unterscheiden sich durch
Rundung in `norm_rect_to_frame_bbox` um ein bis zwei Pixel. Bei 11 px
Ziffernbreite genuegt das. Zudem entfaellt mit dem festen Raster die adaptive
Ausrichtung am Zifferninhalt, die Ungenauigkeiten bisher aufgefangen hat.

**Dieses Modul ist deshalb derzeit ein Messwerkzeug, kein Bestandteil der
Erkennung.** Wer es aktivieren will, misst das Raster zuerst an genau dem Video,
auf das es angewendet wird -- und prueft die Trefferquote gegen bekannte Werte,
bevor er es scharf schaltet.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class DigitGrid:
    """Gemessene Ziffernpositionen eines Feldes."""

    boxes: tuple[tuple[int, int], ...]      # (x0, x1) je Ziffer, in ROI-Pixeln
    samples: int = 0                        # wie viele Frames einflossen
    confident: bool = False                 # trennen sich die Ziffern klar?

    def __len__(self) -> int:
        return len(self.boxes)

    def describe(self) -> str:
        grenzen = " | ".join(str(b[0]) for b in self.boxes)
        letzte = self.boxes[-1][1] if self.boxes else 0
        return (f"{len(self.boxes)} Ziffern bei x = {grenzen} | {letzte} "
                f"(aus {self.samples} Frames, "
                f"{'klar' if self.confident else 'unsicher'})")


@dataclass
class DigitGridMeasurer:
    """Sammelt Spaltenprofile und leitet daraus das Ziffernraster ab.

    Die Messung laeuft nebenher: Jeder ausgewertete Frame liefert ein Profil,
    und sobald genug zusammengekommen sind, steht das Raster.
    """

    expected_digits: int
    min_samples: int = 25
    _profiles: list[np.ndarray] = field(default_factory=list)
    _grid: DigitGrid | None = None

    @property
    def grid(self) -> DigitGrid | None:
        return self._grid

    @property
    def ready(self) -> bool:
        return self._grid is not None

    def add(self, mask: np.ndarray) -> None:
        """Nimmt die Binaermaske eines Frames auf.

        Frames ohne Inhalt werden uebergangen -- eine unbeleuchtete Anzeige
        traegt nichts zur Rastermessung bei.
        """
        if mask.size == 0 or mask.max() == 0:
            return
        profile = (mask > 0).sum(axis=0).astype(np.float32)
        if profile.max() <= 0:
            return
        self._profiles.append(profile)

        if self._grid is None and len(self._profiles) >= self.min_samples:
            self._grid = self._measure()

    def _measure(self) -> DigitGrid | None:
        """Leitet das Raster aus dem gemittelten Spaltenprofil ab."""
        width = min(p.size for p in self._profiles)
        stacked = np.stack([p[:width] for p in self._profiles])
        profile = stacked.mean(axis=0)

        peak = profile.max()
        if peak <= 0:
            return None

        # Taeler im Profil sind die Luecken zwischen den Ziffern.
        # Der Schwellwert ist relativ zum Maximum, damit die Messung von der
        # absoluten Helligkeit unabhaengig bleibt.
        low = profile < 0.55 * peak
        segments: list[tuple[int, int]] = []
        start: int | None = None
        for x in range(width):
            if not low[x] and start is None:
                start = x
            elif low[x] and start is not None:
                segments.append((start, x))
                start = None
        if start is not None:
            segments.append((start, width))

        # Sehr schmale Gruppen sind Rauschen
        segments = [(a, b) for a, b in segments if b - a >= 2]

        if len(segments) == self.expected_digits:
            grid = DigitGrid(tuple(segments), len(self._profiles), confident=True)
            log.info("Ziffernraster gemessen: %s", grid.describe())
            return grid

        # Nicht genau die erwartete Anzahl -- aus der Gesamtausdehnung
        # gleichmaessig teilen. Immer noch besser als die rohe ROI-Breite,
        # weil der leere Rand links und rechts entfaellt.
        if segments:
            first, last = segments[0][0], segments[-1][1]
            pitch = (last - first) / self.expected_digits
            boxes = tuple(
                (int(round(first + i * pitch)), int(round(first + (i + 1) * pitch)))
                for i in range(self.expected_digits)
            )
            grid = DigitGrid(boxes, len(self._profiles), confident=False)
            log.info("Ziffernraster geschaetzt (%d Gruppen statt %d): %s",
                     len(segments), self.expected_digits, grid.describe())
            return grid

        return None

    def reset(self) -> None:
        self._profiles.clear()
        self._grid = None
