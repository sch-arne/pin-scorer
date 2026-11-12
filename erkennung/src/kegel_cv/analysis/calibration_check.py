"""Qualitaetspruefung einer Kalibrierung.

Eine ungenau platzierte ROI erzeugt keinen Fehler -- sie erzeugt ein schwaches,
mehrdeutiges Signal. Das ist die tueckischste Form von Fehlkalibrierung: Die
Analyse laeuft scheinbar, findet aber nichts.

Diese Pruefung misst ueber mehrere Frames und sagt dem Nutzer konkret, welche
Bahn nachjustiert werden muss -- statt ihn raten zu lassen, warum keine Wuerfe
erkannt werden.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from ..calibration.geometry import GeometryError, norm_rect_to_frame_bbox
from ..calibration.model import Calibration
from ..config.schema import AppConfig
from ..detection.lamp_detectors import HsvGreenDetector
from ..video.source import VideoSource

log = logging.getLogger(__name__)


class CheckVerdict(str, Enum):
    GOOD = "GOOD"           # klare Trennung, Signal eindeutig
    WEAK = "WEAK"           # Signal vorhanden, aber schwach getrennt
    NO_SIGNAL = "NO_SIGNAL" # kein Wechsel beobachtet (kann auch normal sein)
    BROKEN = "BROKEN"       # ROI unbrauchbar


@dataclass
class LaneCheck:
    """Pruefergebnis einer Bahn."""

    lane_id: int
    display_number: int
    verdict: CheckVerdict
    min_score: float = 0.0
    max_score: float = 0.0
    frames_on: int = 0
    frames_off: int = 0
    frames_ambiguous: int = 0
    message: str = ""

    @property
    def span(self) -> float:
        return self.max_score - self.min_score

    def describe(self) -> str:
        symbol = {CheckVerdict.GOOD: "OK", CheckVerdict.WEAK: "SCHWACH",
                  CheckVerdict.NO_SIGNAL: "KEIN WECHSEL",
                  CheckVerdict.BROKEN: "FEHLER"}[self.verdict]
        return (f"Bahn {self.display_number}: {symbol} "
                f"(Score {self.min_score:.0f}-{self.max_score:.0f}) -- {self.message}")


@dataclass
class CalibrationReport:
    """Gesamtergebnis der Pruefung."""

    lanes: list[LaneCheck] = field(default_factory=list)
    frames_checked: int = 0

    @property
    def has_problems(self) -> bool:
        return any(l.verdict in (CheckVerdict.BROKEN, CheckVerdict.WEAK)
                   for l in self.lanes)

    def summary(self) -> str:
        lines = [f"Kalibrierung geprueft ueber {self.frames_checked} Frames:"]
        lines.extend("  " + lane.describe() for lane in self.lanes)
        return "\n".join(lines)


def check_calibration(source: VideoSource, calibration: Calibration,
                      cfg: AppConfig, max_frames: int = 250) -> CalibrationReport:
    """Prueft die Gruenlampen-ROIs aller Bahnen ueber mehrere Frames.

    Args:
        source: geoeffnete Videoquelle (wird sequenziell gelesen).
        max_frames: Wie viele Frames geprueft werden. Mehr Frames erhoehen die
            Chance, einen echten Zustandswechsel zu sehen.
    """
    detector = HsvGreenDetector(cfg.detection.green)
    green_cfg = cfg.detection.green

    boxes: dict[int, tuple[int, int, int, int] | None] = {}
    scores: dict[int, list[float]] = {}
    lanes_by_id = {lane.lane_id: lane for lane in calibration.lanes}

    frames = 0
    first_shape: tuple[int, ...] | None = None

    while frames < max_frames:
        frame = source.read()
        if frame is None:
            break

        if first_shape is None:
            first_shape = frame.image.shape
            for lane in calibration.lanes:
                boxes[lane.lane_id] = _green_box(lane, cfg, first_shape)
                scores[lane.lane_id] = []

        for lane_id, box in boxes.items():
            if box is None:
                continue
            x, y, w, h = box
            if w <= 0 or h <= 0:
                continue
            scores[lane_id].append(detector.score(frame.image[y:y + h, x:x + w]))

        frames += 1

    report = CalibrationReport(frames_checked=frames)

    for lane in calibration.lanes:
        values = scores.get(lane.lane_id, [])
        if boxes.get(lane.lane_id) is None or not values:
            report.lanes.append(LaneCheck(
                lane.lane_id, lane.display_number, CheckVerdict.BROKEN,
                message="ROI der gruenen Lampe fehlt oder liegt ausserhalb des Bildes",
            ))
            continue

        on = sum(1 for v in values if v >= green_cfg.on_threshold)
        off = sum(1 for v in values if v <= green_cfg.off_threshold)
        ambiguous = len(values) - on - off

        check = LaneCheck(
            lane_id=lane.lane_id, display_number=lane.display_number,
            verdict=CheckVerdict.GOOD, min_score=min(values), max_score=max(values),
            frames_on=on, frames_off=off, frames_ambiguous=ambiguous,
        )

        ambiguous_ratio = ambiguous / len(values)
        # Ein Zustand gilt erst als real, wenn er so lange anhaelt, wie die
        # Zustandsmaschine zur Bestaetigung verlangt. Alles darunter ist Rauschen
        # -- und wuerde von der Analyse ohnehin verworfen.
        stable = green_cfg.min_stable_frames

        if ambiguous_ratio > 0.35:
            # Das eigentliche Problem: Das Signal haengt zwischen den Schwellen.
            # Die Analyse laeuft, erkennt aber nie einen Wechsel.
            check.verdict = CheckVerdict.WEAK
            check.message = (
                f"{ambiguous_ratio:.0%} der Messwerte liegen zwischen den Schwellen "
                f"({green_cfg.off_threshold:.0f}-{green_cfg.on_threshold:.0f}). "
                f"Die ROI der gruenen Lampe sitzt vermutlich nicht mittig -- "
                f"bitte neu setzen."
            )
        elif on >= stable and off >= stable:
            check.message = f"klarer Wechsel erkannt ({on} AN / {off} AUS)"
        elif 0 < on < stable or 0 < off < stable:
            # Vereinzelte Ausreisser ueber eine Schwelle sind KEIN Wechsel.
            # Wuerde das als "gut" durchgehen, suchte der Nutzer den Fehler
            # spaeter in der Erkennung statt in der Kalibrierung.
            rare, rare_name = ((on, "AN") if 0 < on < stable else (off, "AUS"))
            check.verdict = CheckVerdict.WEAK
            check.message = (
                f"nur {rare} Frame(s) im Zustand {rare_name} (Minimum {stable}) -- "
                f"vermutlich Rauschen statt echtem Wechsel. Score schwankt "
                f"{check.min_score:.0f}-{check.max_score:.0f}; ROI bitte pruefen."
            )
        elif on:
            check.verdict = CheckVerdict.NO_SIGNAL
            check.message = "durchgehend AN -- auf dieser Bahn wurde nicht geworfen"
        elif off:
            check.verdict = CheckVerdict.NO_SIGNAL
            check.message = "durchgehend AUS -- auf dieser Bahn wurde nicht geworfen"
        else:
            check.verdict = CheckVerdict.WEAK
            check.message = "kein eindeutiger Zustand messbar"

        report.lanes.append(check)

    log.info("%s", report.summary())
    return report


def _green_box(lane, cfg: AppConfig,
               frame_shape: tuple[int, ...]) -> tuple[int, int, int, int] | None:
    roi = lane.get_roi("green_lamp")
    if roi is None:
        return None
    try:
        transform = lane.transform(cfg.calibration.warped_width,
                                   cfg.calibration.warped_height)
    except GeometryError:
        return None
    return norm_rect_to_frame_bbox(transform, roi.rect, frame_shape)
