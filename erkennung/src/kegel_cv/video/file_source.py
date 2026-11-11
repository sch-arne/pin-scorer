"""Videoquelle fuer lokale Dateien (Entwicklungsphase 1)."""

from __future__ import annotations

import logging
from pathlib import Path

import cv2

from .source import Frame, VideoInfo, VideoSource, VideoSourceError

log = logging.getLogger(__name__)


class FileVideoSource(VideoSource):
    """Liest Frames aus einer lokalen Videodatei.

    Timestamps werden aus `index / fps` berechnet und nicht aus
    CAP_PROP_POS_MSEC gelesen -- letzteres ist bei h264 nach einem Seek
    unzuverlaessig (siehe Skill `kegel-video-pipeline`).
    """

    def __init__(self, path: str | Path, max_read_failures: int = 10) -> None:
        self._path = Path(path)
        self._max_read_failures = max_read_failures
        self._cap: cv2.VideoCapture | None = None
        self._info: VideoInfo | None = None
        self._next_index = 0
        self._consecutive_failures = 0

    @property
    def path(self) -> Path:
        return self._path

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def info(self) -> VideoInfo:
        if self._info is None:
            raise VideoSourceError("Videoquelle wurde noch nicht geoeffnet")
        return self._info

    @property
    def position(self) -> int:
        """Nummer des naechsten zu lesenden Frames."""
        return self._next_index

    def open(self) -> None:
        if self.is_open:
            return

        if not self._path.is_file():
            raise VideoSourceError(f"Videodatei nicht gefunden: {self._path}")

        cap = cv2.VideoCapture(str(self._path))
        if not cap.isOpened():
            cap.release()
            raise VideoSourceError(
                f"Video konnte nicht geoeffnet werden (Codec nicht unterstuetzt "
                f"oder Datei beschaedigt): {self._path}"
            )

        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            # Ohne FPS gibt es keine belastbaren Timestamps. Lieber ein
            # dokumentierter Ersatzwert mit Warnung als stille Falschzeiten.
            log.warning("Video meldet keine gueltige FPS, verwende 25.0: %s", self._path)
            fps = 25.0

        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        self._cap = cap
        self._info = VideoInfo(
            width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
            height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            fps=float(fps),
            frame_count=frame_count if frame_count > 0 else None,
            source_id=self._path.name,
        )
        self._next_index = 0
        self._consecutive_failures = 0

        log.info(
            "Video geoeffnet: %s (%dx%d, %.2f fps, %s Frames)",
            self._path.name, self._info.width, self._info.height,
            self._info.fps, self._info.frame_count or "unbekannt",
        )

    def read(self) -> Frame | None:
        """Liest den naechsten Frame. None am Ende der Quelle.

        Ein fehlgeschlagener read() ist zweideutig: Er kann ein Dropframe sein
        oder das Videoende. Unterscheiden laesst sich das erst im Nachhinein --
        kommt danach noch ein Frame, war es ein Dropframe; kommt keiner mehr,
        war es das Ende. Deshalb wird erst beim naechsten Erfolg gewarnt.
        Siehe BUG-003.
        """
        if self._cap is None or self._info is None:
            raise VideoSourceError("Videoquelle wurde noch nicht geoeffnet")

        skipped = 0
        while True:
            ok, image = self._cap.read()

            if ok:
                break

            skipped += 1
            self._consecutive_failures += 1
            # Der Index wird trotzdem hochgezaehlt, sonst driftet die Zeitachse
            # gegenueber dem tatsaechlichen Video (Auftrag Paragraph 22).
            self._next_index += 1

            if self._consecutive_failures >= self._max_read_failures:
                log.debug("Videoende erreicht: %s (nach Frame %d)",
                          self._path.name, self._next_index - skipped - 1)
                return None

        if skipped:
            # Jetzt erst steht fest, dass es ein echter Dropframe war
            log.warning("%d Frame(s) uebersprungen (Dropframe) vor Frame %d in %s",
                        skipped, self._next_index, self._path.name)

        self._consecutive_failures = 0
        index = self._next_index
        self._next_index += 1
        return Frame(index=index, timestamp=index / self._info.fps, image=image)

    def seek(self, frame_index: int) -> bool:
        """Springt zu einem Frame. Nur fuer GUI-Navigation.

        In der Analyse nicht verwenden: Seeking ist bei h264 langsam und je nach
        OpenCV-Build ungenau.
        """
        if self._cap is None:
            raise VideoSourceError("Videoquelle wurde noch nicht geoeffnet")
        if frame_index < 0:
            return False

        if not self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_index)):
            log.warning("Seek zu Frame %d fehlgeschlagen", frame_index)
            return False

        self._next_index = frame_index
        self._consecutive_failures = 0
        return True

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            log.debug("Video geschlossen: %s", self._path.name)
        # _info bleibt erhalten, damit Metadaten nach dem Schliessen abrufbar sind.


def list_videos(directory: str | Path,
                extensions: tuple[str, ...] = (".mp4", ".mkv", ".mov", ".avi")) -> list[Path]:
    """Listet Videodateien eines Verzeichnisses, alphabetisch sortiert."""
    path = Path(directory)
    if not path.is_dir():
        return []
    return sorted(
        p for p in path.iterdir()
        if p.is_file() and p.suffix.lower() in extensions
    )
