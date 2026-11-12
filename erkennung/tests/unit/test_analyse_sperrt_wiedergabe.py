"""Waehrend der Analyse gehoert die Anzeige der Analyse.

WARUM ES DIESEN TEST GIBT -- Meldung des Nutzers am 2026-09-07:

    "jetzt flackert mein Bild auch wieder zwischen verschiedenen Frames hin
     und her... nur weil ich Analyse starten geklickt habe"

Aus seiner Bildschirmaufnahme gemessen: In der Statusleiste wechselten sich
ZWEI Reihen ab, die beide fortschritten -- die Analyse (2880, 2895, 2900, 2904,
2909, 2915, 2921, 2925, 2929, 2934, 2940, 2949) und der Player rund 650 Frames
dahinter (2230, 2234, 2282). Das Overlay zeigte durchgehend die Analyse. Ein
Bild, zwei Schreiber: Jeder Frame des Players riss die Anzeige 26 Sekunden
zurueck, der naechste Vorschau-Frame der Analyse wieder nach vorn.

Geprueft wird am ECHTEN Hauptfenster, nicht an einer Nachbildung -- der Fehler
sass genau in der Verdrahtung zwischen Player, Worker und Anzeige.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                  # noqa: E402
from PySide6.QtGui import QKeyEvent            # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402

from kegel_cv.config import load_config        # noqa: E402
from kegel_cv.gui.main_window import MainWindow  # noqa: E402
from kegel_cv.video.source import Frame        # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fenster(qt_app):
    fenster = MainWindow(load_config())
    yield fenster
    fenster.close()


def bild(wert: int) -> np.ndarray:
    return np.full((32, 48, 3), wert, dtype=np.uint8)


def frame(index: int, wert: int) -> Frame:
    return Frame(index=index, timestamp=index / 25.0, image=bild(wert))


def tastendruck(fenster: MainWindow, key) -> None:
    fenster.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, key, Qt.NoModifier))


class TestAnzeigeGehoertDerAnalyse:
    def test_player_frame_wird_waehrend_der_analyse_verworfen(self, fenster):
        """Der Kern des Fehlers: zwei Schreiber auf einer Anzeige."""
        fenster._analyse_aktiv = True
        fenster._on_frame(frame(2282, 120))
        assert fenster._current_frame is None, \
            "ein Frame des Players darf die Anzeige nicht uebernehmen"

    def test_ohne_analyse_zeigt_der_player_wieder_an(self, fenster):
        fenster._analyse_aktiv = False
        fenster._on_frame(frame(2282, 120))
        assert fenster._current_frame is not None
        assert fenster._current_frame.index == 2282

    def test_vorschau_der_analyse_kommt_durch(self, fenster):
        """Die Sperre darf nur den Player treffen, nicht die Analyse."""
        fenster._analyse_aktiv = True
        fenster._on_preview(2949, bild(200))
        assert "2949" in fenster.position_label.text()


class TestBedienelemente:
    def test_transport_ist_waehrend_der_analyse_gesperrt(self, fenster):
        fenster._analyse_aktiv = True
        fenster._update_controls()
        for knopf in (fenster.btn_play, fenster.btn_next, fenster.btn_prev):
            assert not knopf.isEnabled()
        assert not fenster.position_slider.isEnabled()

    def test_danach_wieder_bedienbar_wenn_ein_video_geladen_ist(self, fenster):
        """`_reset_analysis_button` ist der Punkt, an dem die Analyse endet."""
        fenster._analyse_aktiv = True
        fenster._slider_erlaubt = True
        fenster._update_controls()
        assert not fenster.btn_play.isEnabled()

        fenster._reset_analysis_button()
        assert fenster._analyse_aktiv is False
        # Ohne geladenes Video bleibt alles aus -- das ist unabhaengig davon.
        assert fenster.btn_play.isEnabled() is fenster.player.is_loaded

    def test_schieber_bleibt_beim_stream_gesperrt(self, fenster):
        """Nach der Analyse darf nicht eingeschaltet werden, was vorher aus war.

        Bei einem Stream gibt es nichts zu spulen. Ein `setEnabled(True)` nach
        dem Lauf haette dort Erwartungen geweckt, die die Quelle nicht erfuellt.
        """
        fenster._slider_erlaubt = False
        fenster._analyse_aktiv = False
        fenster._update_controls()
        assert not fenster.position_slider.isEnabled()


class TestTastatur:
    """Die Tastatur umgeht gesperrte Knoepfe -- sie braucht eine eigene Sperre."""

    @pytest.mark.parametrize("key", [Qt.Key_Space, Qt.Key_Right, Qt.Key_Left])
    def test_transporttasten_wirken_nicht_waehrend_der_analyse(self, fenster, key,
                                                               monkeypatch):
        gerufen: list[str] = []
        monkeypatch.setattr(fenster.player, "toggle",
                            lambda: gerufen.append("toggle"))
        monkeypatch.setattr(fenster.player, "step_forward",
                            lambda: gerufen.append("vor"))
        monkeypatch.setattr(fenster.player, "step_backward",
                            lambda: gerufen.append("zurueck"))

        fenster._analyse_aktiv = True
        tastendruck(fenster, key)
        assert gerufen == [], f"Taste {key} hat die Wiedergabe angefasst"

    @pytest.mark.parametrize("key,erwartet", [
        (Qt.Key_Space, "toggle"),
        (Qt.Key_Right, "vor"),
        (Qt.Key_Left, "zurueck"),
    ])
    def test_ohne_analyse_wirken_sie_wie_bisher(self, fenster, key, erwartet,
                                                monkeypatch):
        gerufen: list[str] = []
        monkeypatch.setattr(fenster.player, "toggle",
                            lambda: gerufen.append("toggle"))
        monkeypatch.setattr(fenster.player, "step_forward",
                            lambda: gerufen.append("vor"))
        monkeypatch.setattr(fenster.player, "step_backward",
                            lambda: gerufen.append("zurueck"))

        fenster._analyse_aktiv = False
        tastendruck(fenster, key)
        assert gerufen == [erwartet]
