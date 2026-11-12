"""Was eine ANLAGE ausmacht -- und was das Verfahren.

DIE FRAGE, die diese Datei beantwortet: Wenn dasselbe Werkzeug in einer
zweiten Halle laufen soll, welche Zahlen muessen mitreisen?

Die Trennlinie ist einfach zu pruefen:

    Aendert sich der Wert, wenn ich in eine andere Halle fahre?
    Ja  -> er gehoert zur Anlage und damit zum Tafeltyp.
    Nein -> er gehoert zum Verfahren und bleibt in `config/default.yaml`.

Danach gehoeren zur ANLAGE: die Farbe der Bereitschaftslampe, die Zahl der
Kegel und ihre Nummerierung, die Laenge eines Zyklus, welche Ziffernfelder es
gibt und was sie bedeuten. Zum VERFAHREN gehoeren Fenstergroessen, Hysterese,
Mindest-Merkmale, Abtastversaetze -- die beschreiben, WIE gemessen wird, nicht
WAS dasteht.

WARUM DAS UEBERHAUPT NOETIG IST. Bis hierher stand alles in einer einzigen
`config/default.yaml`. Zwei Hallen hiessen damit zwei Konfigurationsdateien --
und man konnte nicht einmal ausprobieren, ob die zweite laeuft, ohne die erste
umzustellen. Der Nutzer dazu am 2026-09-14: *"Wir bauen ein Tool, was immer
funktioniert ... 1 Tool und das muss tragen."*

WAS HIER BEWUSST NICHT STEHT. Ob eine Kegellampe leuchtet, WEIL der Kegel
gefallen ist, oder weil er steht. Das ist ebenfalls eine Anlageneigenschaft,
aber es gibt bisher kein Material einer Anlage, die es andersherum macht -- und
ein ungetesteter Schalter ist schlimmer als eine dokumentierte Luecke. Siehe
`docs/OPEN_QUESTIONS.md`.

ALLE FELDER SIND OPTIONAL. `None` heisst: Es gilt, was in der Konfiguration
steht. Eine Kalibrierung ohne Profil verhaelt sich damit exakt wie vorher --
das ist keine Bequemlichkeit, sondern die Bedingung dafuer, dass der Umbau
keine gemessene Zahl verstellt.
"""

from __future__ import annotations

import logging
from typing import Any

from ..schema import BaseModel, Field, model_validator

log = logging.getLogger(__name__)

# Wohin jedes Feld in der Konfiguration gehoert. Die Zuordnung steht hier an
# EINER Stelle, damit sie sich pruefen laesst -- verteilt ueber den Code waere
# sie in einem halben Jahr nicht mehr auffindbar.
ZUORDNUNG: dict[str, tuple[str, ...]] = {
    "hue_min": ("detection", "green"),
    "hue_max": ("detection", "green"),
    "saturation_min": ("detection", "green"),
    "value_min": ("detection", "green"),
    "warmth_min": ("detection", "lamps"),
    "late_fields": ("detection", "digits"),
    "foul_field": ("detection", "digits"),
    "pin_number_mapping": ("calibration",),
    "pin_count": ("scoring",),
    "throws_per_cycle": ("scoring",),
}


class AnlagenProfil(BaseModel):
    """Die Eigenschaften EINER Kegelanlage, die das Werkzeug kennen muss."""

    # --- Die Bereitschaftslampe -------------------------------------------
    #
    # Der Farbton ist die einzige Groesse, die eine fremde Anlage sicher
    # ausser Gefecht setzt: Die Erkennung sucht Gruen (Farbton 40 bis 90).
    # Eine Anlage, deren Bereitschaftslampe anders leuchtet, faellt damit
    # vollstaendig aus -- nicht schlechter, sondern gar nicht.
    #
    # Die SCHWELLEN dagegen muessen nicht mitreisen: Die Gruenerkennung misst
    # sie im Betrieb selbst aus dem gleitenden Histogramm.
    hue_min: int | None = Field(default=None, ge=0, le=179)
    hue_max: int | None = Field(default=None, ge=0, le=179)
    saturation_min: int | None = Field(default=None, ge=0, le=255)
    value_min: int | None = Field(default=None, ge=0, le=255)

    # --- Die Kegellampen ---------------------------------------------------
    #
    # Sie werden ueber HELLIGKEIT erkannt, nicht ueber Farbe (gemessen:
    # Trennschaerfe 7,66 gegen 3,35). Eine rote Lampe leuchtet so hell wie
    # eine gelbe -- die Farbe ist hier also gutmuetig.
    #
    # `warmth_min` ist nur die Sperre gegen helle, aber FARBLOSE Reflexe. Bei
    # einer kalt leuchtenden Lampe (gruen, blau) muesste sie herunter, sonst
    # verwirft sie die echten Treffer mit.
    # None heisst hier "nicht ueberschreiben" -- die Vorgabe der
    # Konfiguration ist selbst None, also aus. Eine Anlage mit FARBIGEN
    # Kegellampen kann die Schranke mit einem positiven Wert einschalten;
    # fuer weiss gesaettigte Lampen ist sie schaedlich (siehe
    # `detection.lamps.warmth_min`).
    warmth_min: float | None = Field(default=None, ge=0.0)

    # --- Was auf der Tafel steht -------------------------------------------
    pin_count: int | None = Field(default=None, ge=1)
    throws_per_cycle: int | None = Field(default=None, ge=1)
    # Welche Ziffer welche Kegelnummer meint. Reihenfolge wie die ROIs
    # `pin_lamp_1..n`; siehe `config/default.yaml` fuer die Skizze.
    pin_number_mapping: list[int] | None = None
    # Felder, die die Anlage erst NACH dem Wurf aktualisiert.
    late_fields: list[str] | None = None
    # Welches Feld den Fehlwurfzaehler traegt.
    foul_field: str | None = None

    @model_validator(mode="after")
    def _pruefe(self) -> AnlagenProfil:
        if (self.hue_min is not None and self.hue_max is not None
                and self.hue_min >= self.hue_max):
            raise ValueError("hue_min muss kleiner als hue_max sein")
        if self.pin_number_mapping is not None:
            erwartet = list(range(1, len(self.pin_number_mapping) + 1))
            if sorted(self.pin_number_mapping) != erwartet:
                raise ValueError(
                    "pin_number_mapping muss jede Kegelnummer genau einmal "
                    f"vergeben, ist aber {self.pin_number_mapping}")
        if (self.pin_count is not None and self.pin_number_mapping is not None
                and len(self.pin_number_mapping) != self.pin_count):
            raise ValueError(
                f"pin_number_mapping hat {len(self.pin_number_mapping)} "
                f"Eintraege, pin_count sagt {self.pin_count}")
        return self

    @property
    def gesetzt(self) -> dict[str, Any]:
        """Nur die Felder, die dieses Profil wirklich vorgibt."""
        return {name: getattr(self, name) for name in self._felder
                if getattr(self, name) is not None}

    def __bool__(self) -> bool:
        return bool(self.gesetzt)


def wende_an(cfg, profil: AnlagenProfil | None):
    """Legt das Profil ueber die Konfiguration und gibt eine KOPIE zurueck.

    Eine Kopie, kein Umschreiben: Die geladene Konfiguration beschreibt, wie
    das Werkzeug eingestellt ist, und soll das auch nach einem Analyselauf
    noch tun. Wer sie an Ort und Stelle veraendert, hinterlaesst eine Datei,
    die nicht mehr zu dem passt, was auf dem Bildschirm steht.
    """
    if not profil:
        return cfg
    neu = cfg.model_copy(deep=True)
    for name, wert in profil.gesetzt.items():
        ziel = neu
        for stufe in ZUORDNUNG[name]:
            ziel = getattr(ziel, stufe)
        setattr(ziel, name, wert)
    log.info("Anlagenprofil angewandt: %s",
             ", ".join(f"{k}={v}" for k, v in sorted(profil.gesetzt.items())))
    return neu
