"""Frame-Sampling rund um ein Ereignis (Auftrag Paragraph 7).

Zwei Richtungen, die unterschiedlich funktionieren:

    GREEN_OFF (Frame T)          GREEN_ON (Frame U)
          |                            |
          +--> T+2, T+5, T+10          +--> U-2
          |    liegen noch NICHT             liegt bereits im
          |    vor -> einsammeln,            Ringpuffer -> direkt
          |    waehrend sie kommen           entnehmen
          v                            v
       vorwaerts warten            rueckwaerts greifen

Deshalb ist der Sampler zustandsbehaftet: Er merkt sich offene Ereignisse und
sammelt ein, bis alle gewuenschten Offsets vorliegen oder das Ereignis endet.

Zurueckspringen im Video ist ausdruecklich kein Weg -- bei h264 waere es langsam
und ungenau, bei einem Livestream unmoeglich (siehe Skill `kegel-video-pipeline`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..config.schema import SamplingConfig
from ..models.throw import FrameRole
from ..video.source import Frame, FrameBuffer

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SampledFrame:
    """Ein fuer die Auswertung ausgewaehlter Frame."""

    frame: Frame
    offset: int          # relativ zum Ausloeser (negativ = davor)
    role: FrameRole

    @property
    def index(self) -> int:
        return self.frame.index

    @property
    def timestamp(self) -> float:
        return self.frame.timestamp

    def describe(self) -> str:
        return (f"Frame {self.index} (t={self.timestamp:.3f}s, "
                f"Offset {self.offset:+d}, {self.role.value})")


@dataclass
class SampleEvent:
    """Ein Sampling-Vorgang: alle Frames rund um einen erkannten Wurf."""

    lane_id: int
    event_id: int
    trigger_frame: int
    trigger_timestamp: float
    frames: list[SampledFrame] = field(default_factory=list)
    pending_offsets: list[int] = field(default_factory=list)
    closed: bool = False
    close_reason: str = ""

    @property
    def is_complete(self) -> bool:
        return not self.pending_offsets

    @property
    def frame_indices(self) -> list[int]:
        return [s.index for s in self.frames]

    def sorted_frames(self) -> list[SampledFrame]:
        """Chronologisch -- fuer Debug-Ausgaben und Aggregation."""
        return sorted(self.frames, key=lambda s: s.index)

    def describe(self) -> str:
        return (f"Bahn {self.lane_id}, Ereignis {self.event_id}: "
                f"{len(self.frames)} Frames {self.frame_indices} "
                f"um Frame {self.trigger_frame} (t={self.trigger_timestamp:.2f}s)")


class FrameSampler:
    """Sammelt die relevanten Frames je Ereignis. Eine Instanz pro Bahn.

    Der Sampler entscheidet nicht, ob ein Wurf vorliegt -- das tut die
    Zustandsmaschine. Er stellt nur das Bildmaterial bereit.
    """

    def __init__(self, lane_id: int, cfg: SamplingConfig) -> None:
        self.lane_id = lane_id
        self.cfg = cfg
        self._event_counter = 0
        self._open: SampleEvent | None = None

    @property
    def open_event(self) -> SampleEvent | None:
        return self._open

    # ------------------------------------------------------------------ Start

    def start(self, trigger: Frame) -> SampleEvent:
        """Beginnt ein Sampling bei GREEN_OFF.

        Ein noch offenes Ereignis wird verworfen: Das kann nur passieren, wenn
        die Zustandsmaschine einen neuen Wurf meldet, bevor der alte ausgewertet
        war -- dann ist das aeltere Material ohnehin unbrauchbar.
        """
        if self._open is not None and not self._open.closed:
            log.warning("Bahn %d: vorheriges Sampling (Ereignis %d) unvollstaendig "
                        "verworfen -- neuer Trigger bei Frame %d",
                        self.lane_id, self._open.event_id, trigger.index)
            self._open.closed = True
            self._open.close_reason = "durch neuen Trigger ersetzt"

        self._event_counter += 1
        event = SampleEvent(
            lane_id=self.lane_id,
            event_id=self._event_counter,
            trigger_frame=trigger.index,
            trigger_timestamp=trigger.timestamp,
            pending_offsets=sorted(set(self.cfg.frames_after_green_off)),
        )
        # Der Ausloeser selbst gehoert immer dazu -- er zeigt den Zustand im
        # Moment des Ereignisses.
        event.frames.append(SampledFrame(trigger, 0, FrameRole.GREEN_OFF))

        self._open = event
        log.debug("Bahn %d: Sampling gestartet bei Frame %d, erwarte Offsets %s",
                  self.lane_id, trigger.index, event.pending_offsets)
        return event

    # ------------------------------------------------------------- Einsammeln

    def offer(self, frame: Frame) -> None:
        """Bietet dem offenen Ereignis einen Frame an.

        Wird fuer jeden Frame aufgerufen. Passt der Offset, wird der Frame
        uebernommen. Der Aufwand ist ein Listenvergleich -- vernachlaessigbar.
        """
        event = self._open
        if event is None or event.closed or not event.pending_offsets:
            return

        offset = frame.index - event.trigger_frame
        if offset not in event.pending_offsets:
            return

        if len(event.frames) >= self.cfg.max_frames_per_event:
            # Obergrenze erreicht: Die restlichen Offsets werden verworfen,
            # damit nicht unbegrenzt Material anfaellt.
            log.debug("Bahn %d: max_frames_per_event (%d) erreicht, "
                      "verbleibende Offsets %s verworfen",
                      self.lane_id, self.cfg.max_frames_per_event,
                      event.pending_offsets)
            event.pending_offsets.clear()
            return

        event.frames.append(SampledFrame(frame, offset, FrameRole.SAMPLE))
        event.pending_offsets.remove(offset)
        log.debug("Bahn %d: Frame %d (Offset +%d) gesammelt, offen: %s",
                  self.lane_id, frame.index, offset, event.pending_offsets)

    # -------------------------------------------------------------- Abschluss

    def finish(self, green_on: Frame, buffer: FrameBuffer) -> SampleEvent | None:
        """Schliesst das Ereignis bei GREEN_ON ab.

        Die Frames kurz vor der erneuten Freigabe kommen rueckwirkend aus dem
        Ringpuffer -- zu diesem Zeitpunkt liegen sie bereits vor.

        Returns:
            Das abgeschlossene Ereignis, oder None wenn keines offen war.
        """
        event = self._open
        if event is None or event.closed:
            return None

        for offset in sorted(set(self.cfg.frames_before_green_on)):
            if len(event.frames) >= self.cfg.max_frames_per_event:
                break
            wanted = green_on.index + offset          # offset ist negativ
            frame = buffer.get_by_index(wanted)
            if frame is None:
                # Kein Grund zur Sorge, aber protokollieren: Bei sehr kurzen
                # Wuerfen oder kleinem Puffer kann der Frame fehlen.
                log.debug("Bahn %d: Frame %d (vor GREEN_ON) nicht mehr im Puffer",
                          self.lane_id, wanted)
                continue
            event.frames.append(SampledFrame(
                frame, frame.index - event.trigger_frame, FrameRole.CONTEXT
            ))

        if len(event.frames) < self.cfg.max_frames_per_event:
            event.frames.append(
                SampledFrame(green_on, green_on.index - event.trigger_frame,
                             FrameRole.GREEN_ON)
            )

        event.closed = True
        event.close_reason = "GREEN_ON"
        if event.pending_offsets:
            # Der Wurf war kuerzer als das Sampling-Fenster -- kein Fehler,
            # aber die Aggregation stuetzt sich dann auf weniger Frames.
            log.debug("Bahn %d: Ereignis %d endete vor Offsets %s",
                      self.lane_id, event.event_id, event.pending_offsets)
            event.pending_offsets.clear()

        log.info("Bahn %d: %s", self.lane_id, event.describe())
        self._open = None
        return event

    def abort(self, reason: str) -> SampleEvent | None:
        """Bricht ein offenes Sampling ab (Timeout, Videoende, Reset)."""
        event = self._open
        if event is None or event.closed:
            return None
        event.closed = True
        event.close_reason = reason
        event.pending_offsets.clear()
        log.debug("Bahn %d: Sampling %d abgebrochen (%s)",
                  self.lane_id, event.event_id, reason)
        self._open = None
        return event

    def reset(self) -> None:
        self.abort("Reset")
        self._event_counter = 0
