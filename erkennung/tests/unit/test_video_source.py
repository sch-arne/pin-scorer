"""Tests der Videoquelle und des Frame-Puffers.

Ohne echtes Video: Die Abstraktion muss auch mit einer Attrappe funktionieren --
genau das macht sie spaeter fuer Livestreams tauglich.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.video.source import (
    Frame,
    FrameBuffer,
    VideoInfo,
    VideoSource,
    VideoSourceError,
)


class FakeVideoSource(VideoSource):
    """Attrappe mit vorgegebener Frame-Anzahl -- ersetzt ein echtes Video im Test."""

    def __init__(self, frame_count: int = 10, fps: float = 25.0) -> None:
        self._info = VideoInfo(width=64, height=48, fps=fps,
                               frame_count=frame_count, source_id="fake")
        self._index = 0
        self._open = False

    def open(self) -> None:
        self._open = True

    def read(self) -> Frame | None:
        if not self._open:
            raise VideoSourceError("nicht geoeffnet")
        if self._index >= (self._info.frame_count or 0):
            return None
        frame = Frame(
            index=self._index,
            timestamp=self._index / self._info.fps,
            image=np.full((48, 64, 3), self._index, dtype=np.uint8),
        )
        self._index += 1
        return frame

    def close(self) -> None:
        self._open = False

    @property
    def info(self) -> VideoInfo:
        return self._info

    @property
    def is_open(self) -> bool:
        return self._open


class TestVideoInfo:
    def test_dauer_wird_berechnet(self):
        info = VideoInfo(1920, 1080, 25.0, 500, "test.mp4")
        assert info.duration_s == pytest.approx(20.0)

    def test_stream_ohne_laenge(self):
        """Bei einem Livestream gibt es keine Frame-Anzahl -- und das ist gueltig."""
        info = VideoInfo(1920, 1080, 25.0, None, "rtsp://...")
        assert info.duration_s is None


class TestVideoSourceAbstraktion:
    def test_sequenzielles_lesen(self):
        with FakeVideoSource(frame_count=5) as source:
            frames = list(source.frames())
        assert [f.index for f in frames] == [0, 1, 2, 3, 4]

    def test_timestamps_folgen_der_framerate(self):
        with FakeVideoSource(frame_count=3, fps=25.0) as source:
            timestamps = [f.timestamp for f in source.frames()]
        assert timestamps == pytest.approx([0.0, 0.04, 0.08])

    def test_context_manager_schliesst(self):
        source = FakeVideoSource()
        with source:
            assert source.is_open
        assert not source.is_open

    def test_lesen_ohne_open_schlaegt_fehl(self):
        with pytest.raises(VideoSourceError):
            FakeVideoSource().read()

    def test_seek_ist_optional(self):
        """Streams koennen nicht springen -- die Basisklasse meldet das ehrlich."""
        assert FakeVideoSource().seek(5) is False


class TestFrame:
    def test_copy_entkoppelt_den_bildpuffer(self):
        original = Frame(1, 0.04, np.zeros((4, 4, 3), dtype=np.uint8))
        copy = original.copy()
        copy.image[0, 0, 0] = 255
        assert original.image[0, 0, 0] == 0

    def test_frame_ist_unveraenderlich(self):
        frame = Frame(1, 0.04, np.zeros((4, 4, 3), dtype=np.uint8))
        with pytest.raises(Exception):
            frame.index = 2  # type: ignore[misc]


class TestFrameBuffer:
    def _frame(self, index: int) -> Frame:
        return Frame(index, index / 25.0, np.zeros((4, 4, 3), dtype=np.uint8))

    def test_haelt_nur_die_kapazitaet(self):
        buffer = FrameBuffer(capacity=3)
        for i in range(10):
            buffer.append(self._frame(i))

        assert len(buffer) == 3
        assert buffer.oldest().index == 7
        assert buffer.newest().index == 9

    def test_zugriff_ueber_frame_nummer(self):
        buffer = FrameBuffer(capacity=5)
        for i in range(5):
            buffer.append(self._frame(i))

        assert buffer.get_by_index(2).index == 2
        assert buffer.get_by_index(99) is None

    def test_relativer_zugriff_fuer_sampling(self):
        """Der Kern des rueckwirkenden Frame-Samplings: Frames rund um ein
        Ereignis holen, ohne im Video zurueckzuspringen."""
        buffer = FrameBuffer(capacity=20)
        for i in range(20):
            buffer.append(self._frame(i))

        assert buffer.get_relative(10, -2).index == 8
        assert buffer.get_relative(10, +5).index == 15
        assert buffer.get_relative(10, +100) is None

    def test_ausserhalb_des_puffers_liefert_none(self):
        """Ein zu kleiner Puffer darf nicht raten, sondern muss None liefern."""
        buffer = FrameBuffer(capacity=3)
        for i in range(10):
            buffer.append(self._frame(i))
        assert buffer.get_relative(9, -5) is None

    def test_kapazitaet_muss_positiv_sein(self):
        with pytest.raises(ValueError):
            FrameBuffer(capacity=0)

    def test_clear(self):
        buffer = FrameBuffer(capacity=3)
        buffer.append(self._frame(1))
        buffer.clear()
        assert len(buffer) == 0
        assert buffer.newest() is None


class TestDropframes:
    """BUG-003: Videoende darf nicht als Dropframe gemeldet werden.

    Ein fehlgeschlagener read() ist zweideutig -- erst das folgende Ereignis
    entscheidet, ob es ein Dropframe oder das Ende war.
    """

    class FlakyCapture:
        """VideoCapture-Attrappe mit steuerbaren Lesefehlern."""

        def __init__(self, pattern: list[bool]) -> None:
            self.pattern = list(pattern)
            self.calls = 0

        def read(self):
            self.calls += 1
            ok = self.pattern.pop(0) if self.pattern else False
            return ok, (np.zeros((4, 4, 3), dtype=np.uint8) if ok else None)

        def release(self):
            pass

        def isOpened(self):  # noqa: N802 -- OpenCV-Namenskonvention
            return True

    def _source(self, pattern: list[bool], max_failures: int = 5):
        from kegel_cv.video.file_source import FileVideoSource
        from kegel_cv.video.source import VideoInfo

        source = FileVideoSource.__new__(FileVideoSource)
        source._path = __import__("pathlib").Path("test.mp4")
        source._max_read_failures = max_failures
        source._cap = self.FlakyCapture(pattern)
        source._info = VideoInfo(4, 4, 25.0, None, "test.mp4")
        source._next_index = 0
        source._consecutive_failures = 0
        return source

    def test_videoende_liefert_none_ohne_warnung(self, caplog):
        source = self._source([True, True] + [False] * 10, max_failures=5)
        assert source.read().index == 0
        assert source.read().index == 1

        with caplog.at_level("WARNING"):
            assert source.read() is None
        assert not [r for r in caplog.records if "Dropframe" in r.message], \
            "Das Videoende darf keine Dropframe-Warnung erzeugen"

    def test_echter_dropframe_wird_gemeldet(self, caplog):
        """Fehlschlag, danach wieder Erfolg -> das war wirklich ein Dropframe."""
        source = self._source([True, False, False, True, True], max_failures=5)
        source.read()

        with caplog.at_level("WARNING"):
            frame = source.read()

        assert frame is not None
        assert any("Dropframe" in r.message for r in caplog.records)

    def test_index_zaehlt_ueber_dropframes_hinweg_weiter(self):
        """Sonst driftet die Zeitachse gegenueber dem echten Video."""
        source = self._source([True, False, False, True], max_failures=5)
        assert source.read().index == 0
        assert source.read().index == 3, "Uebersprungene Frames zaehlen mit"

    def test_viele_fehlschlaege_beenden_die_quelle(self):
        source = self._source([True] + [False] * 20, max_failures=3)
        source.read()
        assert source.read() is None
