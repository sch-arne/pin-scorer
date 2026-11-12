"""Der Knopf "Weitere Bahnen finden" in der Oberflaeche.

WOFUER -- Frage des Nutzers am 2026-09-09:

    "gibt es das Autokalibrieren auch schon in dem Tool, das ich immer nutze?"

Bis dahin nein: Es lag nur als Kommandozeilenwerkzeug vor
(`tools/kalibriere_automatisch.py`). Vor Ort in einer fremden Halle hilft das
wenig -- dort steht man vor der Oberflaeche.

Geprueft wird die VERDRAHTUNG, nicht der Merkmalsabgleich selbst; der hat
seine eigenen Tests in `test_board_finder.py`.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication          # noqa: E402

from kegel_cv.calibration.model import Calibration, LaneCalibration  # noqa: E402
from kegel_cv.config import load_config             # noqa: E402
from kegel_cv.gui import main_window as mw          # noqa: E402
from kegel_cv.video.source import Frame             # noqa: E402

pytestmark = pytest.mark.gui

ECKEN = [[10.0, 10.0], [90.0, 10.0], [90.0, 90.0], [10.0, 90.0]]


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fenster(qt_app):
    f = mw.MainWindow(load_config())
    yield f
    f.close()


class UnechterPlayer:
    def __init__(self, frame):
        self.current_frame = frame
        self.source_id = "test.mp4"
        self.is_live = False
        self.is_loaded = frame is not None

    def pause(self):
        pass

    def close(self):
        """Das Fenster gibt die Videoquelle beim Schliessen frei -- unter
        Windows blockiert ein offenes VideoCapture sonst die Datei."""
        self.is_loaded = False


def bild() -> np.ndarray:
    return np.full((200, 300, 3), 90, dtype=np.uint8)


class TestDerKnopfIstDa:
    def test_er_existiert(self, fenster):
        assert hasattr(fenster, "btn_find_lanes")

    def test_er_erklaert_sich(self, fenster):
        """Ein Knopf ohne Erklaerung ist eine Falle -- besonders einer, der
        die ganze Kalibrierung ersetzt."""
        hinweis = fenster.btn_find_lanes.toolTip()
        assert "Muster" in hinweis and "Bahnnummern" in hinweis

    def test_er_haengt_am_handler(self, fenster):
        assert hasattr(fenster, "_on_find_lanes")


class TestOhneGrundlagePassiertNichts:
    def test_ohne_bild_keine_suche(self, fenster, monkeypatch):
        gezeigt = []
        monkeypatch.setattr(mw.QMessageBox, "information",
                            lambda *a, **k: gezeigt.append(a))
        fenster.player = UnechterPlayer(None)
        fenster.session.calibration = Calibration(
            lanes=[LaneCalibration(lane_id=1, quad=ECKEN)])
        fenster._on_find_lanes()
        assert gezeigt, "ohne Bild muss ein Hinweis kommen"

    def test_ohne_kalibrierte_bahn_keine_suche(self, fenster, monkeypatch):
        gezeigt = []
        monkeypatch.setattr(mw.QMessageBox, "information",
                            lambda *a, **k: gezeigt.append(a))
        fenster.player = UnechterPlayer(Frame(1, 0.0, bild()))
        fenster.session.calibration = Calibration(lanes=[])
        fenster._on_find_lanes()
        assert gezeigt, "ohne Muster gibt es nichts zu suchen"


class TestKeinTreffer:
    def test_der_nutzer_erfaehrt_warum(self, fenster, monkeypatch):
        """Ein stilles Nichts waere das Schlimmste -- der Nutzer wuesste nicht,
        ob es gesucht hat."""
        warnungen = []
        monkeypatch.setattr(mw.QMessageBox, "warning",
                            lambda *a, **k: warnungen.append(a))
        fenster.player = UnechterPlayer(Frame(1, 0.0, bild()))
        fenster.session.calibration = Calibration(
            lanes=[LaneCalibration(lane_id=1, quad=ECKEN)])
        fenster._on_find_lanes()
        assert warnungen
        text = " ".join(str(x) for x in warnungen[0])
        assert "Bautyp" in text or "Blickwinkel" in text


class TestDieBahnnummernWerdenGefragt:
    """Welche Nummer welche Tafel traegt, steht an der Wand -- der Rechner
    kann es nicht wissen."""

    def _mit_treffern(self, fenster, monkeypatch, anzahl=3):
        from kegel_cv.calibration.board_finder import Treffer

        treffer = [
            Treffer(quad=[[x, 10.0], [x + 80, 10.0], [x + 80, 90.0], [x, 90.0]],
                    inlier=40 + i, paare=60, vorlage_index=0)
            for i, x in enumerate((10.0, 110.0, 210.0)[:anzahl])
        ]
        monkeypatch.setattr(
            "kegel_cv.calibration.board_finder.BoardFinder.finde_alle",
            lambda self, ziel, vorlagen, **kw: treffer)
        fenster.player = UnechterPlayer(Frame(1, 0.0, bild()))
        fenster.session.calibration = Calibration(
            lanes=[LaneCalibration(lane_id=1, quad=ECKEN)])
        return treffer

    def test_die_eingabe_wird_uebernommen(self, fenster, monkeypatch):
        self._mit_treffern(fenster, monkeypatch)
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("7 8 9", True))
        fenster._on_find_lanes()
        nummern = [l.display_number for l in fenster.session.calibration.lanes]
        assert nummern == [7, 8, 9]

    def test_abbruch_aendert_nichts(self, fenster, monkeypatch):
        self._mit_treffern(fenster, monkeypatch)
        vorher = len(fenster.session.calibration.lanes)
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("", False))
        fenster._on_find_lanes()
        assert len(fenster.session.calibration.lanes) == vorher

    def test_falsche_anzahl_wird_abgelehnt(self, fenster, monkeypatch):
        self._mit_treffern(fenster, monkeypatch)
        warnungen = []
        monkeypatch.setattr(mw.QMessageBox, "warning",
                            lambda *a, **k: warnungen.append(a))
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("2 3", True))
        fenster._on_find_lanes()
        assert warnungen, "zwei Nummern fuer drei Tafeln muessen auffallen"
        assert len(fenster.session.calibration.lanes) == 1

    def test_die_rois_des_musters_werden_uebernommen(self, fenster, monkeypatch):
        """Der ganze Sinn: Die Felder folgen aus den Ecken, kein Klick mehr."""
        self._mit_treffern(fenster, monkeypatch)
        muster = fenster.session.calibration.lanes[0]
        muster.rois = []
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("1 2 3", True))
        fenster._on_find_lanes()
        for bahn in fenster.session.calibration.lanes:
            assert bahn.rois == muster.rois

    def test_die_tafeln_bleiben_von_links_nach_rechts(self, fenster, monkeypatch):
        self._mit_treffern(fenster, monkeypatch)
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("4 5 6", True))
        fenster._on_find_lanes()
        mitten = [np.float32(l.quad)[:, 0].mean()
                  for l in fenster.session.calibration.lanes]
        assert mitten == sorted(mitten)
