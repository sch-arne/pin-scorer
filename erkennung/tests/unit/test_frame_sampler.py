"""Tests des Frame-Samplings (Phase 5, Auftrag Paragraph 7).

Der Kern: Frames NACH dem Trigger existieren zum Triggerzeitpunkt noch nicht und
muessen eingesammelt werden; Frames DAVOR liegen bereits im Ringpuffer.
Zurueckspringen im Video ist ausgeschlossen.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.frame_sampler import FrameSampler, SampleEvent
from kegel_cv.config.schema import SamplingConfig
from kegel_cv.models.throw import FrameRole
from kegel_cv.video.source import Frame, FrameBuffer

FPS = 25.0


def frame(index: int) -> Frame:
    return Frame(index, index / FPS, np.zeros((4, 4, 3), dtype=np.uint8))


@pytest.fixture
def cfg() -> SamplingConfig:
    return SamplingConfig(
        frames_after_green_off=[2, 5, 10],
        frames_before_green_on=[-2],
        max_frames_per_event=8,          # gross genug, damit nichts abgeschnitten wird
    )


@pytest.fixture
def sampler(cfg) -> FrameSampler:
    return FrameSampler(lane_id=1, cfg=cfg)


class TestVorwaertsSammeln:
    def test_ausloeser_gehoert_immer_dazu(self, sampler):
        event = sampler.start(frame(100))
        assert len(event.frames) == 1
        assert event.frames[0].role is FrameRole.GREEN_OFF
        assert event.frames[0].offset == 0

    def test_gewuenschte_offsets_werden_gesammelt(self, sampler):
        sampler.start(frame(100))
        for i in range(101, 115):
            sampler.offer(frame(i))

        event = sampler.open_event
        assert event.frame_indices == [100, 102, 105, 110]
        assert event.is_complete

    def test_nicht_gewuenschte_frames_werden_ignoriert(self, sampler):
        sampler.start(frame(100))
        for i in (101, 103, 104, 106):
            sampler.offer(frame(i))
        assert sampler.open_event.frame_indices == [100]

    def test_ohne_offenes_ereignis_passiert_nichts(self, sampler):
        sampler.offer(frame(50))          # darf nicht krachen
        assert sampler.open_event is None


class TestRueckwaertsAusDemPuffer:
    def test_frames_vor_green_on_kommen_aus_dem_puffer(self, sampler):
        """Diese Frames liegen bereits vor -- kein Zuruecksprung noetig."""
        buffer = FrameBuffer(capacity=50)
        sampler.start(frame(100))
        for i in range(101, 121):
            f = frame(i)
            buffer.append(f)
            sampler.offer(f)

        green_on = frame(120)
        buffer.append(green_on)
        event = sampler.finish(green_on, buffer)

        assert event is not None
        assert 118 in event.frame_indices, "Frame vor GREEN_ON muss enthalten sein"
        assert event.closed and event.close_reason == "GREEN_ON"

    def test_fehlender_puffer_frame_ist_kein_fehler(self, sampler):
        """Bei kleinem Puffer oder sehr kurzem Wurf fehlt der Frame -- die
        Auswertung stuetzt sich dann auf weniger Material, bricht aber nicht ab."""
        buffer = FrameBuffer(capacity=2)
        sampler.start(frame(100))
        event = sampler.finish(frame(200), buffer)

        assert event is not None
        assert event.closed

    def test_green_on_frame_wird_aufgenommen(self, sampler):
        buffer = FrameBuffer(capacity=50)
        sampler.start(frame(100))
        green_on = frame(130)
        buffer.append(green_on)
        event = sampler.finish(green_on, buffer)

        roles = {s.role for s in event.frames}
        assert FrameRole.GREEN_ON in roles


class TestObergrenze:
    def test_max_frames_wird_eingehalten(self):
        """Sonst faellt bei langen Wuerfen unbegrenzt Material an."""
        cfg = SamplingConfig(frames_after_green_off=[1, 2, 3, 4, 5, 6, 7, 8],
                             frames_before_green_on=[-1],
                             max_frames_per_event=4)
        sampler = FrameSampler(1, cfg)
        sampler.start(frame(100))
        for i in range(101, 120):
            sampler.offer(frame(i))

        assert len(sampler.open_event.frames) <= 4

    def test_obergrenze_gilt_auch_beim_abschluss(self):
        cfg = SamplingConfig(frames_after_green_off=[1, 2],
                             frames_before_green_on=[-3, -2, -1],
                             max_frames_per_event=3)
        sampler = FrameSampler(1, cfg)
        buffer = FrameBuffer(capacity=50)
        sampler.start(frame(100))
        for i in range(101, 130):
            f = frame(i)
            buffer.append(f)
            sampler.offer(f)
        event = sampler.finish(frame(129), buffer)

        assert len(event.frames) <= 3


class TestLebenszyklus:
    def test_neuer_trigger_verwirft_das_offene_ereignis(self, sampler):
        """Kann nur passieren, wenn ein neuer Wurf gemeldet wird, bevor der alte
        ausgewertet war -- dann ist das aeltere Material unbrauchbar."""
        first = sampler.start(frame(100))
        second = sampler.start(frame(200))

        assert first.closed
        assert "ersetzt" in first.close_reason
        assert second.event_id == 2
        assert sampler.open_event is second

    def test_ereignisse_werden_fortlaufend_nummeriert(self, sampler):
        buffer = FrameBuffer(capacity=10)
        for start in (100, 200, 300):
            sampler.start(frame(start))
            sampler.finish(frame(start + 30), buffer)
        assert sampler._event_counter == 3

    def test_abbruch_schliesst_mit_begruendung(self, sampler):
        sampler.start(frame(100))
        event = sampler.abort("Timeout")
        assert event.closed
        assert event.close_reason == "Timeout"
        assert sampler.open_event is None

    def test_abbruch_ohne_offenes_ereignis(self, sampler):
        assert sampler.abort("Timeout") is None

    def test_reset_setzt_den_zaehler_zurueck(self, sampler):
        sampler.start(frame(100))
        sampler.reset()
        assert sampler.open_event is None
        assert sampler._event_counter == 0

    def test_finish_ohne_offenes_ereignis(self, sampler):
        assert sampler.finish(frame(100), FrameBuffer(10)) is None


class TestSampleEvent:
    def test_frames_sind_chronologisch_sortierbar(self, sampler):
        buffer = FrameBuffer(capacity=50)
        sampler.start(frame(100))
        for i in range(101, 121):
            f = frame(i)
            buffer.append(f)
            sampler.offer(f)
        event = sampler.finish(frame(120), buffer)

        indices = [s.index for s in event.sorted_frames()]
        assert indices == sorted(indices)

    def test_beschreibung_nennt_bahn_und_frames(self, sampler):
        sampler.start(frame(4580))
        text = sampler.open_event.describe()
        assert "Bahn 1" in text
        assert "4580" in text

    def test_leeres_ereignis_ist_unvollstaendig(self):
        event = SampleEvent(lane_id=1, event_id=1, trigger_frame=0,
                            trigger_timestamp=0.0, pending_offsets=[2])
        assert not event.is_complete
