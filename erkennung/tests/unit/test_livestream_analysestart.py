"""Was beim Klick auf "Analyse starten" mit einem LIVESTREAM passieren muss.

WARUM ES DIESEN TEST GIBT -- Trainingsabend am 2026-09-08. Der Nutzer:

    "sobald ich Analysestarten klicke geht der Stream wieder kaputt......"

Aus seinem Protokoll gemessen, zwei getrennte Fehler in derselben Zeile:

    18:59:12  Sprung auf Frame 6081 nicht moeglich (Quelle steht bei 0)
    18:59:12  Kein Sprung moeglich -- es wird bis Frame 6081 vorgespult
    [ WARN:0@421.5] Stream timeout triggered after 5043 ms
    [ WARN:1@422.5] Stream timeout triggered after 5083 ms
    ... im Wechsel, alle fuenf Sekunden, beide Faeden

1. VORSPULEN IN EINEM LIVESTREAM. Der Framezaehler des Players lief seit dem
   Laden mit. Bei 15 fps sind 6081 Frames knapp sieben Minuten -- und in einer
   Live-Uebertragung gibt es diese Frames noch nicht. Der Worker haette sie in
   Echtzeit abwarten muessen, waehrend im Saal gespielt wird.

2. ZWEI VERBINDUNGEN ZUR SELBEN KAMERA. `WARN:0` und `WARN:1` sind zwei
   OpenCV-Faeden: die Vorschau und die Analyse. Ab dem Moment, in dem die
   Analyse ihre Verbindung oeffnete, standen beide. Denn `pause()` haelt bei
   einem Stream nur die ANZEIGE an -- der Lesefaden holt absichtlich weiter
   Frames. Bei einer Datei ist das harmlos, bei einer Kamera nicht.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication          # noqa: E402

from kegel_cv.config import load_config             # noqa: E402
from kegel_cv.gui import main_window as mw          # noqa: E402
from kegel_cv.video.source import Frame, VideoInfo             # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


class UnechterPlayer:
    """Ersatz fuer den Player -- merkt sich, ob geschlossen oder nur pausiert."""

    def __init__(self, quelle: str, live: bool, position: int) -> None:
        self.source_id = quelle
        self.is_live = live
        self.is_loaded = True
        self.current_frame = Frame(index=position, timestamp=0.0, image=None)
        self.geschlossen = False
        self.pausiert = False
        self.geladen_mit: list[str] = []
        # Der echte Player hat diese Angabe immer. Die Analyse merkt sie sich
        # beim Start, weil ein Livestream-Player danach geschlossen ist.
        self.info = VideoInfo(width=1920, height=1080, fps=25.0,
                              frame_count=None if live else 10000,
                              source_id=quelle)

    def close(self) -> None:
        self.geschlossen = True
        self.source_id = None
        self.info = None

    def pause(self) -> None:
        self.pausiert = True

    def load(self, pfad, playback_fps=25.0) -> bool:
        self.geladen_mit.append(str(pfad))
        self.source_id = str(pfad)
        return True


class UnechterWorker:
    """Faengt ab, mit welcher Startposition der Worker gebaut wurde."""

    letzte: dict = {}

    def __init__(self, video_path, calibration, cfg, start_frame=0,
                 sending_enabled=False, spielname="", parent=None) -> None:
        UnechterWorker.letzte = {"video_path": video_path,
                                 "start_frame": start_frame,
                                 "spielname": spielname,
                                 "bahnen": list(cfg.processing.lanes)}
        for name in ("frame_processed", "preview_ready", "progress",
                     "seeking", "finished_analysis", "error"):
            setattr(self, name, _Signal())

    def set_throttle_fps(self, wert) -> None: pass
    def start(self) -> None: pass
    def isRunning(self) -> bool: return False          # noqa: N802
    def request_stop(self) -> None: pass
    def wait(self, ms) -> bool: return True


class _Signal:
    def connect(self, slot) -> None: pass


@pytest.fixture
def fenster(qt_app, monkeypatch):
    monkeypatch.setattr(mw, "AnalysisWorker", UnechterWorker)
    f = mw.MainWindow(load_config())
    # Eine Kalibrierung mit gruener Lampe, sonst bricht der Start vorher ab.
    from kegel_cv.calibration.model import Calibration
    f.session.calibration = Calibration.load("data/calibrations/Training.json")
    yield f
    f.close()


def starte(fenster, *, live: bool, ab_hier: bool, position: int = 6081):
    fenster.player = UnechterPlayer("rtsp://kamera/stream" if live
                                    else "kegelVideos/spieltag.mp4",
                                    live, position)
    fenster.chk_ab_hier.setChecked(ab_hier)
    fenster.chk_senden.setChecked(False)
    fenster._start_analysis()
    return fenster.player


class TestKeinVorspulenImLivestream:
    def test_livestream_startet_immer_jetzt(self, fenster):
        """6081 Frames bei 15 fps sind sieben Minuten Warten auf Frames,
        die es noch nicht gibt."""
        starte(fenster, live=True, ab_hier=True)
        assert UnechterWorker.letzte["start_frame"] == 0

    def test_aufzeichnung_darf_weiterhin_vorspulen(self, fenster):
        """Dort ist es sinnvoll -- das Warmspielen ueberspringen."""
        starte(fenster, live=False, ab_hier=True)
        assert UnechterWorker.letzte["start_frame"] == 6081

    def test_ohne_ab_hier_beginnt_auch_die_datei_vorn(self, fenster):
        starte(fenster, live=False, ab_hier=False)
        assert UnechterWorker.letzte["start_frame"] == 0


class TestNurEineVerbindungZurKamera:
    def test_vorschau_wird_beim_stream_geschlossen(self, fenster):
        player = starte(fenster, live=True, ab_hier=False)
        assert player.geschlossen, \
            "zwei Verbindungen zur selben Kamera blockieren sich gegenseitig"

    def test_datei_wird_nur_pausiert(self, fenster):
        """Eine Datei kostet keine zweite Kameraverbindung -- und der
        Framezaehler soll stehenbleiben, wo er ist."""
        player = starte(fenster, live=False, ab_hier=False)
        assert player.pausiert and not player.geschlossen

    def test_der_worker_bekommt_die_adresse_trotz_schliessen(self, fenster):
        """Der Pfad muss VOR dem Schliessen gesichert werden -- danach ist
        `source_id` leer."""
        starte(fenster, live=True, ab_hier=False)
        assert UnechterWorker.letzte["video_path"] == "rtsp://kamera/stream"

    def test_nach_der_analyse_kommt_die_vorschau_zurueck(self, fenster):
        player = starte(fenster, live=True, ab_hier=False)
        fenster._reset_analysis_button()
        assert player.geladen_mit == ["rtsp://kamera/stream"]

    def test_die_datei_wird_nicht_neu_geladen(self, fenster):
        """Sie wurde nie geschlossen -- ein Neuladen wuerde sie an den Anfang
        zuruecksetzen."""
        player = starte(fenster, live=False, ab_hier=False)
        fenster._reset_analysis_button()
        assert player.geladen_mit == []

    def test_zweites_zuruecksetzen_laedt_nicht_erneut(self, fenster):
        """`_reset_analysis_button` kann aus Stopp UND Abschluss kommen."""
        player = starte(fenster, live=True, ab_hier=False)
        fenster._reset_analysis_button()
        fenster._reset_analysis_button()
        assert player.geladen_mit == ["rtsp://kamera/stream"]
