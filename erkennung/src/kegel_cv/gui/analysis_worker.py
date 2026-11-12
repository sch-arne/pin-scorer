"""Analyse im Hintergrundthread.

Die wichtigste Regel dieser Datei (siehe Skill `kegel-gui`):
**Der Worker beruehrt niemals ein Qt-Widget.** Er meldet ausschliesslich ueber
Signals. Ein direkter Widget-Zugriff aus einem Worker-Thread fuehrt nicht
zuverlaessig zum Absturz, sondern zu sporadischen, kaum reproduzierbaren Fehlern
-- die tueckischste Fehlerklasse dieses Projekts.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from PySide6.QtCore import QMutex, QMutexLocker, QThread, Signal

from ..analysis.pipeline import AnalysisPipeline, FrameResult
from ..calibration.model import Calibration
from ..config.schema import AppConfig
from ..sinks.factory import build_sink
from ..video.factory import open_source, source_label
from ..video.source import VideoSourceError

log = logging.getLogger(__name__)

#: Sonderwert fuer `AnalysisWorker.seeking`: Der Sprung laeuft, ein Fortschritt
#: laesst sich nicht messen. Kein gueltiger Framewert, deshalb negativ.
SPRUNG_LAEUFT = -1


class AnalysisWorker(QThread):
    """Liest ein Video sequenziell und analysiert es Frame fuer Frame.

    Die Videoquelle wird bewusst NICHT mit der GUI geteilt: Ein `VideoCapture`
    ist nicht thread-sicher. Der Worker oeffnet seine eigene Quelle und liest
    sequenziell -- so, wie es die Analyse ohnehin verlangt.
    """

    #: Ein Frame wurde verarbeitet. Nutzlast: FrameResult
    frame_processed = Signal(object)
    #: Ein Bild zur Anzeige (bereits kopiert, thread-sicher). Nutzlast: (index, ndarray)
    preview_ready = Signal(int, object)
    #: Analyse abgeschlossen. Nutzlast: Zusammenfassungstext
    finished_analysis = Signal(str)
    progress = Signal(int, int)          # aktueller Frame, Gesamtzahl
    #: Zwischenstand beim Vorspulen. Nutzlast: (erreicht, Ziel).
    #: `erreicht = SPRUNG_LAEUFT` bedeutet: Es wird gesprungen, ein Fortschritt
    #: laesst sich dabei nicht messen (die Quelle springt in einem Zug).
    seeking = Signal(int, int)
    error = Signal(str)

    def __init__(self, video_path: str, calibration: Calibration, cfg: AppConfig,
                 preview_every: int = 2, start_frame: int = 0,
                 sending_enabled: bool = True, spielname: str = "",
                 parent=None) -> None:
        super().__init__(parent)
        self._video_path = video_path
        # Der Name, den der Nutzer der Partie gegeben hat. Geht als `game_name`
        # mit in die Datenbank und benennt den Debug-Ordner. Bei mehreren
        # Geraeten auf allen denselben -- daran finden die Wuerfe zusammen.
        self._spielname = spielname.strip()
        self._calibration = calibration
        self._cfg = cfg
        self._preview_every = max(1, preview_every)
        self._start_frame = max(0, start_frame)

        self._mutex = QMutex()
        self._stop_requested = False
        self._paused = False
        self._throttle_fps = 0.0        # 0 = so schnell wie moeglich
        # Versand getrennt schaltbar: Vor dem Spiel wird warmgespielt, und
        # diese Wuerfe gehoeren nicht in die Datenbank. Ausgewertet, angezeigt
        # und protokolliert werden sie trotzdem -- nur eben nicht gesendet.
        self._sending = sending_enabled
        # Eine im laufenden Betrieb nachgezogene Kalibrierung, die beim
        # naechsten Frame uebernommen wird. Bewusst eine KOPIE und keine
        # geteilte Referenz: Sonst laese der Worker mitten im Ziehen einen
        # halb geaenderten Zustand.
        self._neue_kalibrierung: Calibration | None = None

    # ------------------------------------------------------------- Steuerung

    def request_stop(self) -> None:
        with QMutexLocker(self._mutex):
            self._stop_requested = True

    def set_paused(self, paused: bool) -> None:
        with QMutexLocker(self._mutex):
            self._paused = paused

    def set_throttle_fps(self, fps: float) -> None:
        """Begrenzt die Verarbeitungsgeschwindigkeit.

        In der Entwicklung ist Echtzeit oft angenehmer als Vollgas: Man will beim
        Zuschauen erkennen, was passiert. 0 bedeutet ungebremst.
        """
        with QMutexLocker(self._mutex):
            self._throttle_fps = max(0.0, fps)

    def _flags(self) -> tuple[bool, bool, float]:
        with QMutexLocker(self._mutex):
            return self._stop_requested, self._paused, self._throttle_fps

    def set_sending(self, aktiv: bool) -> None:
        """Schaltet den Versand um -- waehrend die Analyse weiterlaeuft."""
        with QMutexLocker(self._mutex):
            self._sending = aktiv
        log.info("Versand an die Datenbank %s", "eingeschaltet" if aktiv else "PAUSIERT")

    @property
    def sending(self) -> bool:
        with QMutexLocker(self._mutex):
            return self._sending

    def uebernimm_kalibrierung(self, kalibrierung: Calibration) -> None:
        """Reicht nachgezogene Bereiche in den laufenden Lauf hinein.

        WOFUER -- Befund des Nutzers am 2026-09-11: Wer waehrend der Analyse
        einen Rahmen zieht, aendert nichts; die Analyse liest die Rechtecke,
        die sie beim Start ausgerechnet hat. Das geschah stillschweigend.

        Uebernommen wird beim naechsten Frame, nicht sofort: Mitten in der
        Auswertung eines Frames die Messstellen zu tauschen, hiesse zwei
        verschiedene Kalibrierungen in einem Ergebnis zu mischen.
        """
        with QMutexLocker(self._mutex):
            self._neue_kalibrierung = kalibrierung.model_copy(deep=True)

    def _abgeholte_kalibrierung(self) -> Calibration | None:
        with QMutexLocker(self._mutex):
            neue, self._neue_kalibrierung = self._neue_kalibrierung, None
        return neue

    # ------------------------------------------------------------------- Lauf

    def _vorspulen(self, source, first):
        """Rueckt bis zum gewuenschten Startframe vor.

        Erst wird ein Sprung versucht. Geht der nicht -- Streams koennen das
        nicht, und auch mancher Codec springt unzuverlaessig -- werden die
        Frames gelesen und verworfen. Das dauert laenger, funktioniert aber
        ueberall.
        """
        ziel = self._start_frame

        # Waehrend des Sprungs gibt es NICHTS zu melden: `seek` kehrt erst
        # zurueck, wenn es fertig ist. Frueher wurde hier `0` gesendet -- die
        # Oberflaeche zeigte dann die ganze Zeit "0 %", und bei einem Stream
        # ueber Netz dauert das lange genug, dass es wie ein Absturz aussieht
        # (gemeldet am 2026-09-07). Ein eigener Wert sagt die Wahrheit: Es
        # laeuft, aber der Fortschritt ist nicht messbar.
        self.seeking.emit(SPRUNG_LAEUFT, ziel)
        if source.seek(ziel):
            frame = source.read()
            if frame is not None:
                log.info("Analyse beginnt bei Frame %d (gesprungen)", frame.index)
            # Die Anzeige auf "fertig" setzen, sonst bleibt die letzte Meldung
            # stehen, bis der erste Fortschritt der Analyse eintrifft.
            self.seeking.emit(ziel, ziel)
            return frame

        log.info("Kein Sprung moeglich -- es wird bis Frame %d vorgespult", ziel)
        self.seeking.emit(0, ziel)
        frame = first
        while frame is not None and frame.index < ziel:
            if self._flags()[0]:
                log.info("Vorspulen abgebrochen bei Frame %d", frame.index)
                return None
            frame = source.read()
            # Haeufig genug melden, dass die Oberflaeche nicht tot wirkt.
            # GEMESSEN: Ohne Rueckmeldung dauerte das Vorspulen auf Frame 11344
            # 77 Sekunden, in denen die Anwendung fuer den Nutzer haengen blieb.
            if frame is not None and frame.index % 250 == 0:
                self.seeking.emit(frame.index, ziel)
        if frame is not None:
            log.info("Analyse beginnt bei Frame %d (vorgespult)", frame.index)
        return frame

    def run(self) -> None:  # noqa: C901
        pipeline = AnalysisPipeline(self._calibration, self._cfg,
                                    video_id=source_label(self._video_path),
                                    game_name=self._spielname)
        # Wohin die Ergebnisse gehen. Der Versand haengt bewusst HIER und nicht
        # in der Analyse: Die Auswertung soll nicht wissen muessen, ob ihre
        # Ergebnisse in eine Datenbank, eine Datei oder ins Nichts gehen
        # (Schichtenregel, siehe tests/unit/test_architecture.py).
        sink = build_sink(self._cfg, video_id=source_label(self._video_path),
                          game_name=self._spielname)
        # Datei oder Stream -- die Entscheidung faellt in der Fabrik, nicht hier.
        source = open_source(self._video_path, self._cfg)

        try:
            source.open()
        except VideoSourceError as exc:
            log.error("Analyse konnte nicht starten: %s", exc)
            self.error.emit(str(exc))
            return

        info = source.info
        total = info.frame_count or 0

        try:
            first = source.read()
            if first is None:
                self.error.emit("Video enthaelt keine lesbaren Frames")
                return

            # An die gewuenschte Stelle vorruecken -- etwa um das Warmspielen
            # vor dem eigentlichen Spiel zu ueberspringen.
            if self._start_frame > 0:
                first = self._vorspulen(source, first)
                if first is None:
                    self.error.emit("Startposition liegt hinter dem Videoende")
                    return

            usable = pipeline.prepare(first.image.shape)
            if not usable:
                self.error.emit(
                    "Keine nutzbare Bahn in der Kalibrierung -- bitte pruefen, ob "
                    "die Tafelecken und die gruene Lampe gesetzt sind."
                )
                return

            log.info("Analyse gestartet: %s (%d Bahnen: %s)",
                     info.source_id, len(usable), usable)

            frame = first
            # Fester Takt statt gemessener Abstaende. WARUM: Der erste Anlauf
            # rechnete die Wartezeit aus dem Abstand zum letzten Frame -- damit
            # geht jede Ungenauigkeit von `msleep` in den naechsten Takt ein und
            # summiert sich. GEMESSEN 2026-08-30: bei eingestellten 25 fps lief
            # die Analyse mit 1,12facher Geschwindigkeit. Ein absoluter
            # Zeitplan driftet nicht, weil jeder Takt vom START gerechnet wird.
            naechster_takt = time.perf_counter()

            while frame is not None:
                stop, paused, throttle = self._flags()
                if stop:
                    log.info("Analyse auf Anforderung beendet (Frame %d)", frame.index)
                    break

                if paused:
                    self.msleep(50)
                    continue

                # Nachgezogene Bereiche VOR der Auswertung uebernehmen -- sonst
                # gehoert das Ergebnis dieses Frames halb zur alten und halb
                # zur neuen Kalibrierung.
                neue = self._abgeholte_kalibrierung()
                if neue is not None:
                    betroffen = pipeline.uebernimm_kalibrierung(
                        neue, frame.image.shape)
                    log.info("Kalibrierung im Lauf uebernommen bei Frame %d "
                             "(%d Bahnen geaendert)", frame.index,
                             len(betroffen))

                result = pipeline.process(frame)

                # Jeden Wurf sofort weitergeben -- der Spielleiter soll ihn
                # sehen, waehrend noch gespielt wird. `send` legt ihn nur in
                # eine Warteschlange und kehrt sofort zurueck; das Netz haelt
                # die Analyse also nie auf.
                for throw in result.throws:
                    # Immer analysieren und protokollieren -- gesendet wird nur,
                    # wenn der Versand gerade freigegeben ist.
                    if self.sending:
                        sink.send(throw)
                    else:
                        log.info("Bahn %d: %d Kegel %s -- NICHT gesendet "
                                 "(Versand pausiert)",
                                 throw.lane, throw.pins_count, list(throw.pins))
                self.frame_processed.emit(result)

                # Vorschaubild nur gelegentlich -- 25 Bilder/s durch die
                # Signal-Queue zu schicken wuerde die Oberflaeche ausbremsen.
                if frame.index % self._preview_every == 0:
                    # .copy() ist Pflicht: Der Worker liest den naechsten Frame
                    # weiter, waehrend die GUI dieses Bild noch zeichnet.
                    self.preview_ready.emit(frame.index, frame.image.copy())

                if total and frame.index % 25 == 0:
                    self.progress.emit(frame.index, total)

                if throttle > 0:
                    naechster_takt += 1.0 / throttle
                    rest = naechster_takt - time.perf_counter()
                    if rest > 0:
                        # Aufrunden statt abschneiden: `msleep` nimmt nur ganze
                        # Millisekunden, und Abschneiden macht jeden Takt
                        # systematisch zu kurz.
                        self.msleep(int(rest * 1000 + 0.999))
                    else:
                        # Die Analyse kommt nicht hinterher. Dann NICHT
                        # aufholen wollen -- sonst laeuft sie anschliessend
                        # ungebremst, bis der Rueckstand abgearbeitet ist.
                        naechster_takt = time.perf_counter()

                frame = source.read()

            summary = pipeline.performance.summary(info.fps)
            log.info("Analyse beendet -- %s", summary)
            self.finished_analysis.emit(summary)

        except Exception as exc:  # noqa: BLE001
            # Ein Absturz im Worker wuerde die Anwendung sonst stumm zuruecklassen:
            # Der Thread endet, die GUI wartet weiter auf Signale.
            log.exception("Analyse abgebrochen: %s", exc)
            self.error.emit(f"Analyse abgebrochen: {exc}")
        finally:
            source.close()
            pipeline.close()
            # Erst schliessen, wenn alles draussen ist. Was dann noch nicht
            # versendet werden konnte, landet im Zwischenspeicher und geht beim
            # naechsten Start raus.
            try:
                sink.flush()
                sink.close()
            except Exception as exc:  # noqa: BLE001
                log.warning("Versand konnte nicht sauber beendet werden: %s", exc)
