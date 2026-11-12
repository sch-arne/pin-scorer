"""Schnittstellen der Detektoren.

Der Auftrag verlangt, Verfahren spaeter austauschen zu koennen (klassische CV →
Template Matching → OCR → ML). Deshalb steht hinter jeder Erkennung ein Protocol,
und die Auswahl erfolgt ueber die Konfiguration -- nie ueber `isinstance` oder
einen Codeumbau.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np

from ..models.readings import LampReading, PinLampReading


class DetectionError(RuntimeError):
    """Detektion nicht moeglich (ROI leer, Bild unbrauchbar).

    Erwartete Unsicherheit ist KEIN Fehler -- dafuer gibt es `LampState.UNKNOWN`
    und die Confidence. Diese Ausnahme meint echte Ausnahmen.
    """


@runtime_checkable
class GreenLampDetector(Protocol):
    """Erkennt den Zustand der gruenen Lampe -- der zentrale Trigger."""

    def detect(self, patch: np.ndarray) -> LampReading:
        """Args: patch -- ROI-Ausschnitt (BGR) der gruenen Lampe."""
        ...


@runtime_checkable
class PinLampDetector(Protocol):
    """Erkennt, welche der neun Kegellampen leuchten."""

    def detect(self, patches: list[np.ndarray],
               pin_numbers: list[int]) -> PinLampReading:
        """Args:
            patches: ROI-Ausschnitte der Lampen, in Reihenfolge der Lampenindizes.
            pin_numbers: zugehoerige Kegelnummern -- NICHT die Lampenindizes.
                Die Zuordnung steht in `calibration.pin_number_mapping`
                und landet je Lampe als `pin_number` in der Kalibrierung.
        """
        ...
