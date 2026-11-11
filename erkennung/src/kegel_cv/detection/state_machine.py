"""Zustandsmaschine einer Bahn.

Pro Bahn eine eigene Instanz -- die Spieler werfen nicht synchron (Prinzip P6,
gemessen belegt: Bahn 2 wechselt bei Frame 78, die anderen drei nicht).

Kernaufgabe: Aus einem verrauschten Strom von Lampenmessungen genau EIN Ereignis
je Wurf ableiten. Ein einzelner Stoerframe darf nichts kippen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from ..config.schema import StateMachineConfig
from ..models.readings import LampReading, LampState

log = logging.getLogger(__name__)


class LaneState(str, Enum):
    """Zustaende einer Bahn (Auftrag Paragraph 9)."""

    READY = "READY"
    GREEN_ON = "GREEN_ON"
    GREEN_OFF = "GREEN_OFF"
    ANALYZING = "ANALYZING"
    RESULT_STABILIZATION = "RESULT_STABILIZATION"
    RESULT_CONFIRMED = "RESULT_CONFIRMED"
    WAIT_FOR_NEXT_GREEN = "WAIT_FOR_NEXT_GREEN"


class EventType(str, Enum):
    """Ereignisse, die die Zustandsmaschine nach aussen meldet."""

    GREEN_ON = "GREEN_ON"
    GREEN_OFF = "GREEN_OFF"
    ANALYSIS_DUE = "ANALYSIS_DUE"       # Sampling-Frames liegen vor
    THROW_CONFIRMED = "THROW_CONFIRMED"
    TIMEOUT = "TIMEOUT"


@dataclass(frozen=True)
class LaneEvent:
    """Ein Zustandswechsel mit seinem Kontext."""

    lane_id: int
    event: EventType
    frame_index: int
    timestamp: float
    from_state: LaneState
    to_state: LaneState
    green_score: float = 0.0
    detail: str = ""

    def describe(self) -> str:
        return (f"Bahn {self.lane_id}: {self.event.value} "
                f"({self.from_state.value} -> {self.to_state.value}) "
                f"bei Frame {self.frame_index}, t={self.timestamp:.2f}s")


@dataclass
class LaneStateMachine:
    """Verfolgt den Zustand einer Bahn ueber die Zeit.

    Der wichtigste Schutz liegt in `WAIT_FOR_NEXT_GREEN`: Nach einem bestaetigten
    Wurf kann erst wieder gebucht werden, wenn Gruen erneut AN und dann AUS war.
    Ohne diese Sperre entstuende aus einem Wurf, der ueber 40 Frames sichtbar ist,
    40 Wuerfe.
    """

    lane_id: int
    cfg: StateMachineConfig
    min_stable_frames: int = 3

    state: LaneState = LaneState.READY
    green_state: LampState = LampState.UNKNOWN

    # Abstimmung ueber mehrere Frames -- ein einzelner Frame entscheidet nie
    _on_votes: int = 0
    _off_votes: int = 0
    _state_since_ts: float = 0.0
    _state_since_frame: int = 0
    _green_off_frame: int | None = None
    _green_off_ts: float = 0.0
    _last_throw_frame: int | None = None
    _events: list[LaneEvent] = field(default_factory=list)

    @property
    def green_off_frame(self) -> int | None:
        """Frame, an dem die gruene Lampe zuletzt ausging (Sampling-Bezugspunkt)."""
        return self._green_off_frame

    @property
    def is_waiting_for_result(self) -> bool:
        return self.state in (LaneState.GREEN_OFF, LaneState.ANALYZING,
                              LaneState.RESULT_STABILIZATION)

    def update(self, reading: LampReading, frame_index: int,
               timestamp: float) -> LaneEvent | None:
        """Verarbeitet eine Gruenlampen-Messung.

        Returns:
            Das ausgeloeste Ereignis, oder None wenn sich nichts geaendert hat.
        """
        # UNKNOWN heisst: liegt in der Hysteresezone oder ROI unbrauchbar.
        # Beides darf den Zustand NICHT veraendern -- sonst waere die Hysterese
        # wirkungslos.
        if reading.state is LampState.ON:
            self._on_votes += 1
            self._off_votes = 0
        elif reading.state is LampState.OFF:
            self._off_votes += 1
            self._on_votes = 0
        else:
            return self._check_timeout(frame_index, timestamp)

        if self._on_votes >= self.min_stable_frames and self.green_state is not LampState.ON:
            return self._on_green_on(reading, frame_index, timestamp)

        if self._off_votes >= self.min_stable_frames and self.green_state is not LampState.OFF:
            return self._on_green_off(reading, frame_index, timestamp)

        return self._check_timeout(frame_index, timestamp)

    def _on_green_on(self, reading: LampReading, frame_index: int,
                     timestamp: float) -> LaneEvent:
        self.green_state = LampState.ON
        previous = self.state

        # Gruen wieder AN beendet die Sperre -- ab jetzt ist ein neuer Wurf moeglich
        target = LaneState.GREEN_ON
        return self._transition(target, EventType.GREEN_ON, frame_index, timestamp,
                                reading.score, previous)

    def _on_green_off(self, reading: LampReading, frame_index: int,
                      timestamp: float) -> LaneEvent | None:
        self.green_state = LampState.OFF
        previous = self.state

        # Ein GREEN_OFF loest nur dann ein Ereignis aus, wenn zuvor GREEN_ON war.
        # Startet die Analyse mitten in einer laufenden Phase, wird der erste
        # Wechsel bewusst verworfen: Ohne vorangegangenes GREEN_ON ist unbekannt,
        # ob dazwischen ein Wurf lag.
        if previous not in (LaneState.GREEN_ON,):
            log.debug("Bahn %d: GREEN_OFF ohne vorheriges GREEN_ON -- kein Ereignis "
                      "(Zustand %s)", self.lane_id, previous.value)
            self.state = LaneState.READY
            self._state_since_frame, self._state_since_ts = frame_index, timestamp
            return None

        if self._too_soon(frame_index):
            log.warning("Bahn %d: Wurf nach nur %d Frames verworfen (Minimum %d) -- "
                        "vermutlich Fehlerkennung", self.lane_id,
                        frame_index - (self._last_throw_frame or 0),
                        self.cfg.min_frames_between_throws)
            return None

        self._green_off_frame = frame_index
        self._green_off_ts = timestamp
        return self._transition(LaneState.GREEN_OFF, EventType.GREEN_OFF,
                                frame_index, timestamp, reading.score, previous)

    def _too_soon(self, frame_index: int) -> bool:
        """Ist seit dem letzten Wurf zu wenig Zeit vergangen?

        Ein physisch unmoeglich schneller Folgewurf ist eine Fehlerkennung
        (Auftrag Paragraph 22).
        """
        if self._last_throw_frame is None:
            return False
        return frame_index - self._last_throw_frame < self.cfg.min_frames_between_throws

    def mark_analyzing(self, frame_index: int, timestamp: float) -> LaneEvent | None:
        """Meldet, dass die Sampling-Frames vorliegen und ausgewertet werden."""
        if self.state is not LaneState.GREEN_OFF:
            return None
        return self._transition(LaneState.ANALYZING, EventType.ANALYSIS_DUE,
                                frame_index, timestamp, 0.0, self.state)

    def confirm_throw(self, frame_index: int, timestamp: float,
                      detail: str = "") -> LaneEvent | None:
        """Bucht einen Wurf und aktiviert die Sperre gegen Doppelzaehlung."""
        if self.state not in (LaneState.ANALYZING, LaneState.RESULT_STABILIZATION,
                              LaneState.GREEN_OFF):
            log.debug("Bahn %d: confirm_throw im Zustand %s ignoriert",
                      self.lane_id, self.state.value)
            return None

        previous = self.state
        self._last_throw_frame = frame_index
        event = self._transition(LaneState.WAIT_FOR_NEXT_GREEN,
                                 EventType.THROW_CONFIRMED, frame_index, timestamp,
                                 0.0, previous, detail)
        return event

    def _check_timeout(self, frame_index: int, timestamp: float) -> LaneEvent | None:
        """Verhindert, dass eine Bahn nach einer Fehlerkennung dauerhaft haengt."""
        elapsed = timestamp - self._state_since_ts
        limit = {
            LaneState.ANALYZING: self.cfg.analyzing_timeout_s,
            LaneState.RESULT_STABILIZATION: self.cfg.stabilization_timeout_s,
            LaneState.WAIT_FOR_NEXT_GREEN: self.cfg.wait_green_timeout_s,
        }.get(self.state)

        if limit is None or elapsed < limit:
            return None

        log.warning("Bahn %d: Zeitueberschreitung in %s nach %.1fs -- zurueck auf READY",
                    self.lane_id, self.state.value, elapsed)
        return self._transition(LaneState.READY, EventType.TIMEOUT,
                                frame_index, timestamp, 0.0, self.state,
                                f"Timeout nach {elapsed:.1f}s")

    def _transition(self, target: LaneState, event_type: EventType,
                    frame_index: int, timestamp: float, green_score: float,
                    previous: LaneState, detail: str = "") -> LaneEvent:
        self.state = target
        self._state_since_frame = frame_index
        self._state_since_ts = timestamp

        event = LaneEvent(
            lane_id=self.lane_id, event=event_type, frame_index=frame_index,
            timestamp=timestamp, from_state=previous, to_state=target,
            green_score=green_score, detail=detail,
        )
        self._events.append(event)
        log.debug("%s", event.describe())
        return event

    def reset(self) -> None:
        """Setzt die Bahn auf den Ausgangszustand zurueck (neues Video)."""
        self.state = LaneState.READY
        self.green_state = LampState.UNKNOWN
        self._on_votes = self._off_votes = 0
        self._green_off_frame = None
        self._last_throw_frame = None
        self._events.clear()
