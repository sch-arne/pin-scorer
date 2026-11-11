"""Schreibt den Messwert der gruenen Lampe fuer jeden Frame mit.

WARUM: Die gruene Lampe steuert die Wurferkennung. Loest sie falsch aus, liegt
die Ursache in den Frames VOR dem Ereignis -- und genau die speichert der
Bilder-Mitschnitt nicht, denn er beginnt beim Ausloeser.

Beim Untersuchen eines Fehlwurfs stand deshalb die Frage "wieso hat er hier
ausgeloest?" im Raum, und sie war mit dem vorhandenen Material NICHT zu
beantworten: Die Zustandsmaschine braucht drei stabile Messungen, die
entscheidenden drei Frames lagen aber vor dem ersten gespeicherten Bild.

Bewusst eine schlichte CSV statt einer Datenbank: Sie laesst sich in jeder
Tabellenkalkulation oeffnen, und der Nutzer soll selbst nachsehen koennen.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models.readings import LampReading

log = logging.getLogger(__name__)


class GreenTrace:
    """Protokolliert Score und Zustand der gruenen Lampe je Frame und Bahn."""

    def __init__(self, ziel: Path, aktiv: bool = True) -> None:
        self.aktiv = aktiv
        self.pfad = ziel
        self._datei = None
        self._zeilen = 0

    def _oeffnen(self) -> None:
        if self._datei is not None or not self.aktiv:
            return
        try:
            self.pfad.parent.mkdir(parents=True, exist_ok=True)
            self._datei = self.pfad.open("w", encoding="utf-8-sig", newline="")
            self._datei.write("Frame;Zeit_s;Bahn;Score;Zustand\n")
        except OSError as exc:
            # Ein Protokollierungsfehler darf die Analyse nicht anhalten.
            log.warning("Gruenspur nicht schreibbar: %s", exc)
            self.aktiv = False

    def add(self, frame_index: int, timestamp: float, lane: int,
            reading: LampReading) -> None:
        if not self.aktiv:
            return
        self._oeffnen()
        if self._datei is None:
            return
        try:
            self._datei.write(f"{frame_index};{timestamp:.2f};{lane};"
                              f"{reading.score:.1f};{reading.state.value}\n")
            self._zeilen += 1
        except OSError as exc:
            log.warning("Gruenspur abgebrochen: %s", exc)
            self.aktiv = False

    def close(self) -> None:
        if self._datei is not None:
            self._datei.close()
            self._datei = None
            log.info("Gruenspur geschrieben: %s (%d Zeilen)", self.pfad, self._zeilen)
