"""Schreibt jeden erkannten Wurf sofort in eine CSV.

WARUM: Bisher schrieb ein Lauf nur die Gruenspur und die Ereignisbilder. Die
Wurfergebnisse gab es ausschliesslich ueber die Werkzeuge -- also erst in einem
ZWEITEN Durchlauf ueber dasselbe Video. An einem Spieltag ist das wertlos: Dort
laeuft die Analyse einmal, live, und was sie dabei gesehen hat, muss danach
nachlesbar sein.

Geschrieben wird ZEILENWEISE und sofort geleert. Wird die Analyse abgebrochen,
stuerzt die Anwendung ab oder faellt der Strom aus, steht alles bis zum letzten
Wurf trotzdem in der Datei. Eine Datei, die erst am Ende geschrieben wird, ist
genau dann leer, wenn man sie am dringendsten braucht.

Die Spalten gehen ueber das hinaus, was gesendet wird: Der Versand traegt nur
Gemessenes (Bahn, Kegel, Zeit), hier steht zusaetzlich alles Abgeleitete und
die Herkunft -- fuer die Fehlersuche, nicht fuer die Auswertung.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from ..models.throw import ThrowResult

log = logging.getLogger(__name__)

SPALTEN = [
    "Zeit",            # mm:ss im Video -- zum Nachschlagen im Bild
    "Frame",
    "Bahn",
    "Kegel",
    "Kegelnummern",
    "Wurfnummer",
    "Spiel",
    "Zyklus",
    "WurfImZyklus",
    "LaufendeSumme",
    "Zwischensumme",
    "Status",
    "Confidence",
    "Ziffer",          # was die Tafel als Kegelzahl anzeigte
    "WurfnummerRoh",   # Wurfnummer der Tafel VOR der Aufloesung -- ohne
                       # sie laesst sich ueber die Tafel nichts belegen
    "NummerEinigkeit", # wie einig die abgetasteten Frames darueber waren
    "SummeTafel",
    "FehlwurfTafel",   # Stand des Fehlwurfzaehlers (left_display) beim Wurf
    "Raeumen",
    "Grundlinie",      # wie viele Kegel schon lagen
    "Herkunft",        # Gruenzyklus oder Fehlwurfzaehler
    "Zeitstempel_s",
    "Pruefungen",      # gescheiterte Gegenproben, damit sie auffallen
]


class ThrowLog:
    """Protokolliert erkannte Wuerfe als CSV, Zeile fuer Zeile."""

    def __init__(self, ziel: Path, aktiv: bool = True) -> None:
        self.aktiv = aktiv
        self.pfad = ziel
        self._datei = None
        self._schreiber: csv.DictWriter | None = None
        self._zeilen = 0

    def _oeffnen(self) -> None:
        if self._datei is not None or not self.aktiv:
            return
        try:
            self.pfad.parent.mkdir(parents=True, exist_ok=True)
            self._datei = self.pfad.open("w", encoding="utf-8-sig", newline="")
            self._schreiber = csv.DictWriter(self._datei, fieldnames=SPALTEN,
                                             delimiter=";")
            self._schreiber.writeheader()
            self._datei.flush()
        except OSError as exc:
            # Ein Protokollierungsfehler darf die Analyse nicht anhalten (P8).
            log.warning("Wurfprotokoll nicht schreibbar: %s", exc)
            self.aktiv = False

    def add(self, throw: ThrowResult) -> None:
        if not self.aktiv:
            return
        self._oeffnen()
        if self._schreiber is None or self._datei is None:
            return

        roh = (throw.evidence.raw if throw.evidence else {}) or {}
        grundlinie = roh.get("baseline") or {}
        gescheitert = [p.name for p in (throw.evidence.checks if throw.evidence
                                        else ()) if not p.passed]
        sekunden = throw.timestamp

        try:
            self._schreiber.writerow({
                "Zeit": f"{int(sekunden // 60)}:{int(sekunden % 60):02d}",
                "Frame": throw.source_frame,
                "Bahn": throw.lane,
                "Kegel": throw.pins_count,
                "Kegelnummern": " ".join(str(p) for p in throw.pins),
                "Wurfnummer": throw.throw_number,
                "Spiel": throw.game_number,
                "Zyklus": throw.cycle_number,
                "WurfImZyklus": throw.throw_number_in_series,
                "LaufendeSumme": throw.running_total,
                "Zwischensumme": ("" if throw.series_total is None
                                  else throw.series_total),
                "Status": throw.status.value,
                "Confidence": f"{throw.confidence:.2f}",
                "Ziffer": ("" if throw.displayed_pin_count is None
                           else throw.displayed_pin_count),
                "WurfnummerRoh": ("" if roh.get("throw_number_raw") is None
                                  else roh["throw_number_raw"]),
                "NummerEinigkeit": (
                    "" if roh.get("throw_number_confidence") is None
                    else f'{roh["throw_number_confidence"]:.2f}'),
                "SummeTafel": ("" if roh.get("displayed_total") is None
                               else roh["displayed_total"]),
                "FehlwurfTafel": ("" if throw.displayed_foul_count is None
                                  else throw.displayed_foul_count),
                "Raeumen": "ja" if roh.get("clearing") else "",
                "Grundlinie": grundlinie.get("count", ""),
                "Herkunft": roh.get("source", "gruenzyklus"),
                "Zeitstempel_s": f"{sekunden:.2f}",
                "Pruefungen": " | ".join(gescheitert),
            })
            # Sofort leeren: Bricht der Lauf ab, steht alles bis hierher drin.
            self._datei.flush()
            self._zeilen += 1
        except (OSError, ValueError) as exc:
            log.warning("Wurfprotokoll abgebrochen: %s", exc)
            self.aktiv = False

    def close(self) -> None:
        if self._datei is not None:
            self._datei.close()
            self._datei = None
            self._schreiber = None
            log.info("Wurfprotokoll geschrieben: %s (%d Wuerfe)",
                     self.pfad, self._zeilen)
