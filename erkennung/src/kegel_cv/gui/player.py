"""Wiedergabesteuerung.

Trennt die Abspiel-Logik vom Fenster: Das Hauptfenster stellt dar, dieser
Controller entscheidet, wann welcher Frame kommt.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ..video import (FileVideoSource, Frame, VideoInfo, VideoSourceError,
                     VideoSource, is_stream, open_source)

log = logging.getLogger(__name__)


class _StreamReader(threading.Thread):
    """Holt Frames eines Livestreams -- in einem eigenen Faden.

    WARUM: Der Player laeuft an einer QTimer, also im GUI-Thread. Ein
    `read()` auf einem Stream kann sekundenlang blockieren; bei
    weggelaufener Verbindung sogar bis zum Zeitlimit. Passiert das im
    GUI-Thread, friert die gesamte Oberflaeche ein -- gemessen, nachdem die
    Verbindung waehrend zweier Minuten Kalibrierarbeit weggelaufen war.

    Ausserdem gilt: **Ein Livestream ist ein Livestream.** Er wartet nicht.
    Wird waehrend des Kalibrierens nicht gelesen, staut sich der Puffer oder
    die Verbindung stirbt. Deshalb liest dieser Faden DURCHGEHEND weiter --
    unabhaengig davon, ob die Anzeige gerade laeuft.

    Aufgehoben wird nur der JUENGSTE Frame. Aeltere sind bei einem Livestream
    wertlos: Wer zurueckliegt, will aufholen, nicht nachspielen.
    """

    def __init__(self, source: VideoSource, fps: float = 25.0) -> None:
        super().__init__(daemon=True, name="StreamReader")
        self._source = source
        # Takt der Quelle. Ein ECHTER Livestream liefert ohnehin nur in
        # Echtzeit -- da bremst das nichts. Eine AUFZEICHNUNG hinter derselben
        # Adresse (etwa ein Mux-VOD) laedt dagegen so schnell wie die Leitung
        # hergibt, und das Video liefe im Zeitraffer.
        self._interval_s = 1.0 / max(fps, 1.0)
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        # NICHT `_stop` nennen: `threading.Thread` hat eine interne Methode
        # dieses Namens, und `join()` ruft sie auf. Ein Attribut gleichen
        # Namens ueberdeckt sie, und jedes join() bricht mit
        # "'Event' object is not callable" ab.
        self._halt = threading.Event()
        self._ended = False

    def run(self) -> None:
        naechster = time.perf_counter()
        while not self._halt.is_set():
            # Auf den Takt der Quelle warten, bevor der naechste Frame geholt
            # wird. `wait` statt `sleep`, damit das Anhalten sofort greift.
            naechster += self._interval_s
            rest = naechster - time.perf_counter()
            if rest > 0:
                if self._halt.wait(rest):
                    return
            else:
                # Wir hinken hinterher -- nicht aufsummieren lassen, sonst
                # holt der Faden die Verzoegerung spaeter im Eiltempo nach.
                naechster = time.perf_counter()
            try:
                frame = self._source.read()
            except Exception as exc:  # noqa: BLE001
                log.error("Stream-Lesefaden: %s", exc)
                self._ended = True
                return
            if frame is None:
                log.info("Stream beendet")
                self._ended = True
                return
            with self._lock:
                self._latest = frame

    def newest(self) -> Frame | None:
        """Der zuletzt gelesene Frame -- oder None, solange keiner da ist."""
        with self._lock:
            return self._latest

    @property
    def ended(self) -> bool:
        return self._ended

    def stop(self) -> None:
        self._halt.set()
        self.join(timeout=3.0)


class VideoPlayer(QObject):
    """Spielt eine Videoquelle ab und meldet jeden Frame per Signal.

    Die Anzeigerate ist von der Videorate entkoppelt: Bei 25 fps waere ein
    synchroner Neuaufbau der Oberflaeche pro Frame zu teuer, und spaeter laeuft
    die Analyse ohnehin schneller oder langsamer als Echtzeit.
    """

    frame_ready = Signal(object)        # Frame
    opened = Signal(object)             # VideoInfo
    finished = Signal()
    error = Signal(str)
    state_changed = Signal(bool)        # True = laeuft

    def __init__(self, max_read_failures: int = 10, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._source: VideoSource | None = None
        self._source_id: str | None = None
        self._reader: _StreamReader | None = None
        self._max_read_failures = max_read_failures
        self._current: Frame | None = None

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------ Status

    @property
    def is_loaded(self) -> bool:
        return self._source is not None and self._source.is_open

    @property
    def is_playing(self) -> bool:
        return self._timer.isActive()

    @property
    def info(self) -> VideoInfo | None:
        if self._source is None:
            return None
        try:
            return self._source.info
        except VideoSourceError:
            return None

    @property
    def source_path(self) -> Path | None:
        """Pfad des geladenen Videos -- None bei einem Stream."""
        quelle = getattr(self._source, "path", None)
        return quelle if isinstance(quelle, Path) else None

    @property
    def source_id(self) -> str | None:
        """Was geladen ist: Dateipfad ODER Stream-URL.

        Die Analyse oeffnet ihre eigene Quelle, weil VideoCapture nicht
        thread-sicher ist -- sie braucht dafuer diese Angabe.
        """
        return self._source_id

    @property
    def is_live(self) -> bool:
        """Laeuft gerade ein Stream? Dann gibt es kein Spulen und kein Ende."""
        return self._source is not None and is_stream(self._source_id or "")

    @property
    def current_frame(self) -> Frame | None:
        return self._current

    @property
    def position(self) -> int:
        return self._current.index if self._current else 0

    # ------------------------------------------------------------------ Laden

    def load(self, path: str | Path, playback_fps: float = 25.0) -> bool:
        """Laedt ein Video oder einen Stream und zeigt den ersten Frame.

        Ob Datei oder Stream, entscheidet `video.factory.open_source` anhand des
        Schemas -- an einer Stelle, nicht an zweien.
        """
        self.close()

        try:
            source = open_source(path)
            source.open()
        except VideoSourceError as exc:
            log.error("Video konnte nicht geladen werden: %s", exc)
            self.error.emit(str(exc))
            return False

        self._source = source
        self._source_id = str(path)
        # Bei einem Stream uebernimmt ein eigener Faden das Lesen -- sonst
        # blockiert die Oberflaeche (siehe _StreamReader).
        if is_stream(path):
            self._reader = _StreamReader(source, fps=source.info.fps)
            self._reader.start()
        self._interval_ms = max(1, int(1000.0 / max(playback_fps, 0.1)))
        self.opened.emit(source.info)

        self.step_forward()
        return True

    def close(self) -> None:
        """Schliesst die Quelle und gibt den Datei-Handle frei.

        Wichtig unter Windows: Ein offenes VideoCapture blockiert das Verschieben
        oder Loeschen der Datei.
        """
        self.pause()
        if self._reader is not None:
            self._reader.stop()
            self._reader = None
        if self._source is not None:
            self._source.close()
            self._source = None
        self._source_id = None
        self._current = None

    # ------------------------------------------------------------- Wiedergabe

    def play(self) -> None:
        if not self.is_loaded or self.is_playing:
            return
        self._timer.start(self._interval_ms)
        self.state_changed.emit(True)
        log.debug("Wiedergabe gestartet")

    def pause(self) -> None:
        """Haelt die ANZEIGE an -- ein Stream laeuft im Hintergrund weiter.

        Ein Livestream ist ein Livestream: Er wartet nicht, bis jemand mit dem
        Kalibrieren fertig ist. Der Lesefaden holt deshalb weiter Frames, damit
        die Verbindung nicht wegläuft und kein Rueckstand entsteht. Stehen
        bleibt nur das angezeigte Bild -- darauf laesst sich in Ruhe klicken.
        """
        if not self._timer.isActive():
            return
        self._timer.stop()
        self.state_changed.emit(False)
        log.debug("Anzeige angehalten")

    def toggle(self) -> None:
        self.pause() if self.is_playing else self.play()

    def _on_tick(self) -> None:
        if not self.step_forward():
            self.pause()
            self.finished.emit()

    def step_forward(self) -> bool:
        """Liest den naechsten Frame. False am Videoende."""
        if not self.is_loaded:
            return False

        assert self._source is not None
        if self._reader is not None:
            # Livestream: den juengsten Frame nehmen, nicht den naechsten.
            # Aeltere Frames sind hier wertlos -- wer zurueckliegt, will
            # aufholen, nicht nachspielen.
            if self._reader.ended:
                return False
            frame = self._reader.newest()
            if frame is None:
                return True     # noch kein Bild -- kein Fehler, nur zu frueh
        else:
            try:
                frame = self._source.read()
            except VideoSourceError as exc:
                log.error("Fehler beim Lesen: %s", exc)
                self.error.emit(str(exc))
                return False

        if frame is None:
            log.info("Videoende erreicht")
            return False

        self._current = frame
        self.frame_ready.emit(frame)
        return True

    def step_backward(self) -> bool:
        """Springt einen Frame zurueck.

        Nutzt Seeking -- nur in der Navigation zulaessig, nicht in der Analyse
        (siehe Skill `kegel-video-pipeline`).
        """
        if not self.is_loaded or self._current is None:
            return False
        return self.seek(max(0, self._current.index - 1))

    def seek(self, frame_index: int) -> bool:
        """Springt zu einem Frame und zeigt ihn an."""
        if not self.is_loaded:
            return False

        assert self._source is not None
        was_playing = self.is_playing
        self.pause()

        if not self._source.seek(frame_index):
            return False

        ok = self.step_forward()
        if was_playing and ok:
            self.play()
        return ok
