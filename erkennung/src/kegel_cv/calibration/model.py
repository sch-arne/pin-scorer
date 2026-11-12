"""Kalibrierungs-Datenmodell und Persistenz.

Warum Kalibrierung pro Session zwingend ist: Die Overlay-Position unterscheidet
sich nachweislich zwischen den Aufnahmen (2024: Gruenlampen bei x ca. 538/1079/1378,
2026: x ca. 572/876/1105/1399). Eine fest verdrahtete Position waere fuer genau
ein Video richtig.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from ..schema import BaseModel, Field, field_validator

from .anlage import AnlagenProfil
from .geometry import PerspectiveTransform, Quad

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

# Namen der ROIs, die eine Bahn fuer die vollstaendige Auswertung braucht.
ROI_GREEN_LAMP = "green_lamp"
ROI_PIN_COUNT = "pin_count"
ROI_THROW_NUMBER = "throw_number"
ROI_TOTAL_A = "total_a"
ROI_TOTAL_B = "total_b"
PIN_LAMP_PREFIX = "pin_lamp_"
DIGIT_PREFIX = "digit_"

# Ziffernfelder und ihre Stellenzahl. Jede Stelle kann einzeln kalibriert
# werden -- siehe digit_roi_name().
DIGIT_FIELDS: dict[str, int] = {
    "throw_number": 3,
    "pin_count": 1,
    "total_a": 4,
    "total_b": 4,
    "left_display": 2,
}

REQUIRED_ROIS = (ROI_GREEN_LAMP, ROI_PIN_COUNT, ROI_THROW_NUMBER, ROI_TOTAL_A, ROI_TOTAL_B)


def pin_lamp_name(index: int) -> str:
    """ROI-Name der n-ten Kegellampe (1-basiert)."""
    return f"{PIN_LAMP_PREFIX}{index}"


def digit_roi_name(field: str, position: int) -> str:
    """ROI-Name einer EINZELNEN Ziffernstelle (1-basiert, von links).

    Warum einzeln statt ein Feld zu teilen: Das automatische Aufteilen eines
    Feldes in N Stellen ist am realen Material gescheitert. Gemessen liegen die
    echten Ziffergrenzen bei x = 5|15|26|38|49, die gleichmaessige Teilung nimmt
    0|13|26|40|53 an -- ein Versatz von fast einer halben Ziffernbreite. Bei
    13x18 px je Ziffer macht das jede Segmentmessung unbrauchbar.

    Eine einzeln eingerahmte Stelle kennt ihre Grenzen dagegen exakt.
    """
    return f"{DIGIT_PREFIX}{field}_{position}"


class Roi(BaseModel):
    """Ein Bereich innerhalb der Anzeigetafel, in normierten Tafelkoordinaten.

    `rect` = (x, y, w, h), jeweils 0..1. Niemals Pixel -- sonst bricht die
    Kalibrierung bei jeder Aufloesungsaenderung.
    """

    name: str
    rect: tuple[float, float, float, float]
    enabled: bool = True
    # Nur bei Kegellampen gesetzt: welche Kegelnummer diese Lampe darstellt.
    # Konfigurierbar, weil das Mapping Lampenindex -> Kegelnummer noch nicht am
    # Material verifiziert ist (offene Frage Q5).
    pin_number: int | None = None

    @field_validator("rect")
    @classmethod
    def _check_rect(cls, v: tuple[float, float, float, float]):
        x, y, w, h = v
        if w <= 0 or h <= 0:
            raise ValueError(f"ROI-Groesse muss positiv sein: w={w}, h={h}")
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            raise ValueError(f"ROI-Position muss in Tafelkoordinaten 0..1 liegen: ({x}, {y})")
        if x + w > 1.001 or y + h > 1.001:
            raise ValueError(
                f"ROI ragt ueber die Tafel hinaus: x+w={x + w:.3f}, y+h={y + h:.3f}"
            )
        return v

    @property
    def center(self) -> tuple[float, float]:
        x, y, w, h = self.rect
        return x + w / 2, y + h / 2

    def moved_to(self, cx: float, cy: float) -> Roi:
        """Kopie mit auf (cx, cy) verschobenem Mittelpunkt (fuer GUI-Bearbeitung)."""
        _, _, w, h = self.rect
        return self.model_copy(update={"rect": (cx - w / 2, cy - h / 2, w, h)})


class LaneCalibration(BaseModel):
    """Kalibrierung einer Bahn: Tafel-Eckpunkte plus ihre ROIs."""

    lane_id: int
    quad: list[list[float]] = Field(min_length=4, max_length=4)
    rois: list[Roi] = Field(default_factory=list)
    # Reale Bahnnummer, falls sie von der Overlay-Position abweicht (offene Frage Q1)
    real_lane_number: int | None = None

    @field_validator("quad")
    @classmethod
    def _check_quad(cls, v: list[list[float]]):
        if any(len(p) != 2 for p in v):
            raise ValueError("Jeder Eckpunkt braucht genau zwei Koordinaten")
        return v

    def to_quad(self) -> Quad:
        return Quad.from_points([(p[0], p[1]) for p in self.quad])

    def transform(self, width: int, height: int) -> PerspectiveTransform:
        return PerspectiveTransform(self.to_quad(), width, height)

    def get_roi(self, name: str) -> Roi | None:
        return next((r for r in self.rois if r.name == name), None)

    def digit_rois(self, field: str) -> list[Roi]:
        """Einzeln kalibrierte Stellen eines Ziffernfeldes, von links nach rechts.

        Leere Liste, wenn das Feld nicht stellenweise kalibriert wurde -- dann
        greift die Auswertung auf das Gesamtfeld zurueck.
        """
        prefix = f"{DIGIT_PREFIX}{field}_"
        rois = [r for r in self.rois if r.name.startswith(prefix) and r.enabled]
        return sorted(rois, key=lambda r: int(r.name.removeprefix(prefix)))

    def pin_lamps(self) -> list[Roi]:
        """Kegellampen-ROIs, nach Lampenindex sortiert."""
        lamps = [r for r in self.rois if r.name.startswith(PIN_LAMP_PREFIX)]
        return sorted(lamps, key=lambda r: int(r.name.removeprefix(PIN_LAMP_PREFIX)))

    def set_roi(self, roi: Roi) -> None:
        """Fuegt eine ROI hinzu oder ersetzt die gleichnamige."""
        for i, existing in enumerate(self.rois):
            if existing.name == roi.name:
                self.rois[i] = roi
                return
        self.rois.append(roi)

    def missing_rois(self, pin_count: int = 9) -> list[str]:
        """Namen der ROIs, die fuer eine vollstaendige Auswertung noch fehlen."""
        present = {r.name for r in self.rois if r.enabled}
        expected = set(REQUIRED_ROIS) | {pin_lamp_name(i) for i in range(1, pin_count + 1)}
        return sorted(expected - present)

    @property
    def display_number(self) -> int:
        """Bahnnummer fuer die Anzeige -- reale Nummer, falls bekannt."""
        return self.real_lane_number if self.real_lane_number is not None else self.lane_id


class SourceHint(BaseModel):
    """Hinweis auf das Video, fuer das kalibriert wurde.

    Erlaubt beim Laden eine Warnung, wenn die Kalibrierung offensichtlich nicht
    zum aktuellen Video passt -- statt stillschweigend falsche ROIs zu verwenden.
    """

    width: int | None = None
    height: int | None = None
    video: str | None = None


class Calibration(BaseModel):
    """Vollstaendige Kalibrierung einer Aufnahme-Session."""

    schema_version: int = SCHEMA_VERSION
    name: str = "unbenannt"
    created: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    source_hint: SourceHint = Field(default_factory=SourceHint)
    # Was DIESE Anlage ausmacht -- Lampenfarbe, Kegelzahl, Zyklus. Leer heisst:
    # Es gilt, was in `config/default.yaml` steht. Siehe `anlage.py` fuer die
    # Trennlinie zwischen Anlage und Verfahren.
    anlage: AnlagenProfil = Field(default_factory=AnlagenProfil)
    lanes: list[LaneCalibration] = Field(default_factory=list)

    def get_lane(self, lane_id: int) -> LaneCalibration | None:
        return next((l for l in self.lanes if l.lane_id == lane_id), None)

    def set_lane(self, lane: LaneCalibration) -> None:
        for i, existing in enumerate(self.lanes):
            if existing.lane_id == lane.lane_id:
                self.lanes[i] = lane
                return
        self.lanes.append(lane)
        self.lanes.sort(key=lambda l: l.lane_id)

    @property
    def is_complete(self) -> bool:
        return bool(self.lanes) and all(not l.missing_rois() for l in self.lanes)

    def save(self, path: str | Path) -> Path:
        """Speichert als JSON. Legt fehlende Verzeichnisse an."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as fh:
            json.dump(self.model_dump(), fh, indent=2, ensure_ascii=False)
        log.info("Kalibrierung gespeichert: %s (%d Bahnen)", p, len(self.lanes))
        return p

    @classmethod
    def load(cls, path: str | Path) -> Calibration:
        """Laedt und validiert eine Kalibrierung.

        Raises:
            FileNotFoundError, ValueError
        """
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"Kalibrierung nicht gefunden: {p}")

        with p.open("r", encoding="utf-8") as fh:
            data: dict[str, Any] = json.load(fh)

        version = data.get("schema_version", 0)
        if version > SCHEMA_VERSION:
            raise ValueError(
                f"Kalibrierung {p.name} hat Schema-Version {version}, unterstuetzt "
                f"wird hoechstens {SCHEMA_VERSION}. Anwendung aktualisieren."
            )

        cal = cls.model_validate(data)
        log.info("Kalibrierung geladen: %s (%d Bahnen)", p, len(cal.lanes))
        return cal

    def check_against_video(self, width: int, height: int) -> list[str]:
        """Prueft die Kalibrierung gegen die Videomasse und liefert Warnungen.

        Keine Exception: Eine abweichende Aufloesung kann gewollt sein. Der Nutzer
        soll gewarnt, aber nicht blockiert werden.
        """
        warnings: list[str] = []
        hint = self.source_hint
        if hint.width and hint.width != width:
            warnings.append(
                f"Kalibrierung wurde fuer Breite {hint.width} erstellt, "
                f"Video hat {width} -- ROIs passen vermutlich nicht"
            )
        if hint.height and hint.height != height:
            warnings.append(
                f"Kalibrierung wurde fuer Hoehe {hint.height} erstellt, Video hat {height}"
            )
        for lane in self.lanes:
            for point in lane.quad:
                if not (0 <= point[0] <= width and 0 <= point[1] <= height):
                    warnings.append(
                        f"Bahn {lane.lane_id}: Eckpunkt {point} liegt ausserhalb des Bildes"
                    )
                    break
        return warnings


def list_calibrations(directory: str | Path) -> list[Path]:
    """Alle gespeicherten Kalibrierungen eines Verzeichnisses."""
    p = Path(directory)
    if not p.is_dir():
        return []
    return sorted(p.glob("*.json"))
