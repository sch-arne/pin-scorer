"""Abstraktion der Videoquelle.

Der Auftrag verlangt, dass spaeter ein Livestream ohne Umbau der Anwendung
ergaenzt werden kann (Paragraph 3). Deshalb kennt die Analyse ausschliesslich
`VideoSource` -- nie einen Dateipfad, nie `cv2.VideoCapture`, nie `frame_count`
als Abbruchbedingung.

    VideoSource (ABC)
    +-- FileVideoSource      (heute)
    +-- StreamVideoSource    (spaeter)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Iterator

import numpy as np

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoInfo:
    """Eigenschaften einer Videoquelle."""

    width: int
    height: int
    fps: float
    frame_count: int | None      # None bei Streams -- dort gibt es keine Laenge
    source_id: str               # Dateiname oder Stream-URL, fuer Debug-Pfade

    @property
    def duration_s(self) -> float | None:
        if self.frame_count is None or self.fps <= 0:
            return None
        return self.frame_count / self.fps


@dataclass(frozen=True)
class Frame:
    """Ein Frame mit seiner zeitlichen Verortung.

    Ein nacktes np.ndarray verliert die Zeitinformation -- und die wird fuer
    jede Debug-Ausgabe und jedes Ergebnis gebraucht.
    """

    index: int              # 0-basierte Frame-Nummer der Quelle
    timestamp: float        # Sekunden seit Start
    image: np.ndarray       # BGR

    @property
    def shape(self) -> tuple[int, ...]:
        return self.image.shape

    def copy(self) -> Frame:
        """Kopie mit eigenem Bildpuffer -- noetig beim Puffern und beim Thread-Wechsel."""
        return Frame(self.index, self.timestamp, self.image.copy())


class VideoSourceError(RuntimeError):
    """Fehler beim Zugriff auf eine Videoquelle."""


class VideoSource(ABC):
    """Basisklasse aller Videoquellen."""

    @abstractmethod
    def open(self) -> None:
        """Oeffnet die Quelle. Mehrfachaufruf ist erlaubt und wirkungslos."""

    @abstractmethod
    def read(self) -> Frame | None:
        """Liefert den naechsten Frame oder None am Ende der Quelle."""

    @abstractmethod
    def close(self) -> None:
        """Gibt alle Ressourcen frei. Mehrfachaufruf ist erlaubt."""

    @property
    @abstractmethod
    def info(self) -> VideoInfo:
        """Eigenschaften der Quelle. Erst nach open() gueltig."""

    @property
    @abstractmethod
    def is_open(self) -> bool: ...

    def seek(self, frame_index: int) -> bool:
        """Springt zu einem Frame.

        Optional: Streams unterstuetzen kein Seeking und liefern False.
        In der Analyse NICHT verwenden -- nur fuer GUI-Navigation
        (siehe Skill `kegel-video-pipeline`).
        """
        return False

    def frames(self) -> Iterator[Frame]:
        """Iteriert sequenziell ueber alle Frames -- der bevorzugte Analyseweg."""
        while (frame := self.read()) is not None:
            yield frame

    def __enter__(self) -> VideoSource:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class FrameBuffer:
    """Ringpuffer der zuletzt gelesenen Frames.

    Ermoeglicht rueckwirkendes Frame-Sampling rund um ein Ereignis, ohne im Video
    zurueckzuspringen. Seeking waere bei h264 langsam und ungenau -- und bei einem
    Livestream gar nicht moeglich.

    Speicherbedarf: 1920x1080x3 = ca. 6 MB pro Frame.
    """

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError(f"Puffergroesse muss >= 1 sein, erhalten: {capacity}")
        self._buffer: deque[Frame] = deque(maxlen=capacity)

    @property
    def capacity(self) -> int:
        return self._buffer.maxlen or 0

    def __len__(self) -> int:
        return len(self._buffer)

    def append(self, frame: Frame) -> None:
        """Legt einen Frame ab. Der Aufrufer stellt sicher, dass der Bildpuffer
        nicht anderweitig weiterverwendet wird (OpenCV recycelt Puffer nicht,
        aber die GUI koennte das Bild verandern)."""
        self._buffer.append(frame)

    def get_by_index(self, frame_index: int) -> Frame | None:
        """Frame mit dieser Quell-Frame-Nummer, falls noch im Puffer."""
        for frame in self._buffer:
            if frame.index == frame_index:
                return frame
        return None

    def get_relative(self, reference_index: int, offset: int) -> Frame | None:
        """Frame mit `reference_index + offset`, falls vorhanden."""
        return self.get_by_index(reference_index + offset)

    def newest(self) -> Frame | None:
        return self._buffer[-1] if self._buffer else None

    def oldest(self) -> Frame | None:
        return self._buffer[0] if self._buffer else None

    def clear(self) -> None:
        self._buffer.clear()
