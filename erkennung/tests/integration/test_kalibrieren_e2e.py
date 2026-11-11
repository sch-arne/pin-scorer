"""Kalibrieren wie ein Mensch: echte Mausklicks auf das echte Widget.

WARUM ES DIESEN TEST GIBT -- Vorwurf des Nutzers, und er trifft:

    "man kann keine Ziffern setzen, weil man das Feld darunter verschieben
     wuerde.... mach doch mal ein e2e Test das wuerde dir alles auffallen,
     wenn du das Tool nutzen wuerdest, wie ein Mensch."

Genau so war es. Das Ziehen von Bereichen wurde eingebaut und hat im selben
Zug das Setzen zerstoert: Ein Klick griff den darunterliegenden Bereich, statt
den Punkt zu setzen -- und da jede Ziffernstelle INNERHALB ihres Gesamtfeldes
liegt, war keine einzige Ziffer mehr einrahmbar.

Die Unit-Tests blieben gruen. Sie pruefen `session.frame_digit(x, y)` direkt --
also den Schritt NACH dem Klick. Dass der Klick dort gar nicht mehr ankommt,
konnten sie nicht sehen.

Dieser Test klickt deshalb auf das Widget: `QTest.mouseClick` und
`mousePress/Move/Release`, so wie eine Hand es tut. Er braucht keinen
Bildschirm (`QT_QPA_PLATFORM=offscreen`).
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt          # noqa: E402
from PySide6.QtTest import QTest               # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402

from kegel_cv.calibration.session import (      # noqa: E402
    CalibrationSession,
    CalibrationStep,
)
from kegel_cv.gui.video_view import VideoView   # noqa: E402

BREITE, HOEHE = 640, 360


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def oberflaeche(qt_app):
    """Ein Videofenster mit Bild und angeschlossener Kalibriersitzung.

    Bewusst NICHT das ganze Hauptfenster: Der Fehler sass in der Kette
    Klick -> VideoView -> Session, und die laesst sich hier vollstaendig
    nachstellen, ohne halbe Anwendung hochzufahren.
    """
    view = VideoView()
    view.resize(BREITE, HOEHE)
    view.set_frame(np.full((HOEHE, BREITE, 3), 60, dtype=np.uint8))
    view.show()

    session = CalibrationSession(warped_width=440, warped_height=530)
    protokoll: list[tuple] = []

    def bei_klick(x: float, y: float) -> None:
        if session.step is CalibrationStep.FRAME_DIGITS:
            session.frame_digit(x, y)
        elif session.step is CalibrationStep.PICK_ROIS:
            session.place_roi(x, y)
        elif session.step is CalibrationStep.PICK_CORNERS:
            if session.add_point(x, y):
                session.try_commit()
        _spiegeln(view, session)

    def bei_eckzug(lane_id: int, index: int, x: float, y: float) -> None:
        session.move_quad_corner(lane_id, index, x, y)
        protokoll.append(("ecke", lane_id, index))
        _spiegeln(view, session)

    def bei_bereichzug(lane_id: int, name: str, x: float, y: float) -> None:
        session.move_roi(lane_id, name, x, y)
        protokoll.append(("bereich", lane_id, name))
        _spiegeln(view, session)

    def bei_verziehen(lane_id: int, name: str, kante: str,
                      x: float, y: float) -> None:
        session.resize_roi(lane_id, name, kante, x, y)
        protokoll.append(("verzogen", lane_id, name, kante))
        _spiegeln(view, session)

    view.clicked.connect(bei_klick)
    view.quad_corner_dragged.connect(bei_eckzug)
    view.roi_dragged.connect(bei_bereichzug)
    view.roi_resized.connect(bei_verziehen)

    view.session = session          # fuer die Tests erreichbar
    view.protokoll = protokoll
    yield view
    view.close()


def _spiegeln(view: VideoView, session: CalibrationSession) -> None:
    """Zeichnet den Sitzungszustand ins Widget -- wie das Hauptfenster."""
    view.set_drag_enabled(
        session.step in (CalibrationStep.IDLE, CalibrationStep.EDIT_ROIS))
    for lane in session.calibration.lanes:
        view.set_lane_quad(lane.lane_id,
                           [(p[0], p[1]) for p in lane.quad], f"Bahn {lane.lane_id}")
        try:
            transform = lane.transform(session.warped_width, session.warped_height)
        except Exception:      # noqa: BLE001 -- entartetes Viereck beim Ziehen
            continue
        polygone = []
        for roi in lane.rois:
            if not roi.enabled:
                continue
            x, y, w, h = roi.rect
            ecken = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
                             dtype=np.float32)
            punkte = transform.norm_to_frame(ecken)
            polygone.append((roi.name,
                             [(float(p[0]), float(p[1])) for p in punkte]))
        view.set_lane_rois(lane.lane_id, polygone)
    view.set_pending_points(session.active_lane, session.pending_points)


def klick(view: VideoView, fx: float, fy: float) -> None:
    """Klickt auf eine FRAME-Koordinate -- so wie ein Mensch auf das Bild."""
    QTest.mouseClick(view, Qt.LeftButton, Qt.NoModifier,
                     view.frame_to_widget(fx, fy))


def ziehen(view: VideoView, von: tuple[float, float],
           nach: tuple[float, float]) -> None:
    """Druecken, bewegen, loslassen -- eine echte Ziehbewegung."""
    start = view.frame_to_widget(*von)
    ziel = view.frame_to_widget(*nach)
    QTest.mousePress(view, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(view, ziel)
    QTest.mouseRelease(view, Qt.LeftButton, Qt.NoModifier, ziel)


def bahn_anlegen(view: VideoView, lane_id: int,
                 ecken=((100.0, 60.0), (300.0, 60.0),
                        (300.0, 260.0), (100.0, 260.0))) -> None:
    view.session.start_lane(lane_id)
    _spiegeln(view, view.session)
    for x, y in ecken:
        klick(view, x, y)


class TestKalibrierenWieEinMensch:
    def test_bahn_ueber_vier_klicks_anlegen(self, oberflaeche):
        bahn_anlegen(oberflaeche, 1)

        lane = oberflaeche.session.calibration.get_lane(1)
        assert lane is not None, "vier Klicks muessen eine Bahn ergeben"
        assert oberflaeche.session.step is CalibrationStep.EDIT_ROIS

    def test_ziffer_einrahmen_trotz_darunterliegendem_feld(self, oberflaeche):
        """DER FEHLER, den der Nutzer gemeldet hat.

        Die Ziffernstelle liegt INNERHALB des Gesamtfeldes `left_display`.
        Griff der Klick den Bereich darunter, liess sich keine Ziffer setzen.
        """
        bahn_anlegen(oberflaeche, 1)
        session = oberflaeche.session

        # Das Gesamtfeld dorthin legen, wo gleich geklickt wird -- so wie es
        # nach dem Anlegen aus der Vorlage kommt.
        session.select_roi("left_display")
        _spiegeln(oberflaeche, session)
        klick(oberflaeche, 200.0, 160.0)

        vorher = session.calibration.get_lane(1).get_roi("left_display").rect

        # Jetzt eine Ziffer MITTEN in dieses Feld einrahmen
        session.select_roi("digit_left_display_1")
        _spiegeln(oberflaeche, session)
        assert session.step is CalibrationStep.FRAME_DIGITS
        klick(oberflaeche, 190.0, 150.0)
        klick(oberflaeche, 215.0, 175.0)

        ziffer = session.calibration.get_lane(1).get_roi("digit_left_display_1")
        assert ziffer is not None, (
            "die Ziffer muss gesetzt werden -- der Klick darf nicht das "
            "darunterliegende Feld greifen")
        assert ziffer.enabled is True
        assert session.calibration.get_lane(1).get_roi("left_display").rect == vorher, (
            "das Feld darunter darf sich dabei NICHT verschieben")

    def test_bereich_setzen_verschiebt_keinen_anderen(self, oberflaeche):
        """Auch beim Einzelklick-Setzen darf nichts gegriffen werden."""
        bahn_anlegen(oberflaeche, 1)
        session = oberflaeche.session
        vorher = {r.name: r.rect
                  for r in session.calibration.get_lane(1).rois
                  if r.name != "green_lamp"}

        session.select_roi("green_lamp")
        _spiegeln(oberflaeche, session)
        klick(oberflaeche, 210.0, 170.0)

        nachher = {r.name: r.rect
                   for r in session.calibration.get_lane(1).rois
                   if r.name != "green_lamp"}
        assert nachher == vorher, "kein anderer Bereich darf sich mitbewegen"

    def test_alle_ziffern_eines_feldes_nacheinander(self, oberflaeche):
        """Der ganze Ablauf 'nur Fehlwurfzaehler (2)' -- acht Klicks."""
        from kegel_cv.calibration.session import digit_pick_order

        bahn_anlegen(oberflaeche, 1)
        session = oberflaeche.session
        session.start_digit_framing(digit_pick_order(["left_display"]))
        _spiegeln(oberflaeche, session)

        for links, oben in ((150.0, 120.0), (200.0, 120.0)):
            klick(oberflaeche, links, oben)
            klick(oberflaeche, links + 25.0, oben + 30.0)

        lane = session.calibration.get_lane(1)
        assert lane.get_roi("digit_left_display_1") is not None
        assert lane.get_roi("digit_left_display_2") is not None


class TestRaenderVerziehen:
    """Bereiche lassen sich in der GROESSE aendern, nicht nur verschieben.

    Vom Nutzer verlangt: "besser als dass man nur den Rahmen verschieben kann
    waere, wenn man jeden Rand verziehen kann". Eine Ziffernbox muss in der
    Groesse stimmen -- aus ihr ergeben sich die Segmentflaechen geometrisch.
    """

    def _kasten(self, view, name: str = "green_lamp"):
        """Der Bereich in FRAME-Koordinaten (links, oben, rechts, unten)."""
        lane = view.session.calibration.get_lane(1)
        transform = lane.transform(view.session.warped_width,
                                   view.session.warped_height)
        x, y, w, h = lane.get_roi(name).rect
        ecken = np.array([[x, y], [x + w, y + h]], dtype=np.float32)
        punkte = transform.norm_to_frame(ecken)
        return (float(punkte[0][0]), float(punkte[0][1]),
                float(punkte[1][0]), float(punkte[1][1]))

    def test_rechten_rand_nach_aussen_ziehen(self, oberflaeche):
        bahn_anlegen(oberflaeche, 1)
        _spiegeln(oberflaeche, oberflaeche.session)
        links, oben, rechts, unten = self._kasten(oberflaeche)
        breite_vorher = rechts - links

        # Am rechten Rand anfassen und nach aussen ziehen
        ziehen(oberflaeche, (rechts, (oben + unten) / 2),
               (rechts + 25.0, (oben + unten) / 2))

        l2, o2, r2, u2 = self._kasten(oberflaeche)
        assert r2 - l2 > breite_vorher, "der Bereich muss breiter geworden sein"
        assert abs(l2 - links) < 2.0, "der linke Rand bleibt, wo er war"

    def test_ecke_ziehen_aendert_beide_richtungen(self, oberflaeche):
        bahn_anlegen(oberflaeche, 1)
        _spiegeln(oberflaeche, oberflaeche.session)
        links, oben, rechts, unten = self._kasten(oberflaeche)

        ziehen(oberflaeche, (rechts, unten), (rechts + 20.0, unten + 20.0))

        l2, o2, r2, u2 = self._kasten(oberflaeche)
        assert r2 - l2 > rechts - links
        assert u2 - o2 > unten - oben

    def test_mitte_anfassen_verschiebt_statt_zu_verziehen(self, oberflaeche):
        bahn_anlegen(oberflaeche, 1)
        _spiegeln(oberflaeche, oberflaeche.session)
        links, oben, rechts, unten = self._kasten(oberflaeche)
        breite, hoehe = rechts - links, unten - oben

        ziehen(oberflaeche, ((links + rechts) / 2, (oben + unten) / 2),
               ((links + rechts) / 2 + 20.0, (oben + unten) / 2))

        l2, o2, r2, u2 = self._kasten(oberflaeche)
        assert abs((r2 - l2) - breite) < 2.0, "die Breite bleibt"
        assert abs((u2 - o2) - hoehe) < 2.0, "die Hoehe bleibt"
        assert l2 > links, "aber der Bereich ist gewandert"


class TestGefuehrteKalibrierung:
    """Der Ablauf, den der Nutzer beschrieben hat.

    "ich wuerde gerne die erste Bahn vollstaendig kalibrieren und dann soll es
    mit Bahn 2 losgehen, dort wird dann Bahn 1 gemapped, dann Bahn 3 und Bahn 4
    und dann kann man alle Felder einzeln korrigieren"
    """

    def _durchlaufen(self, view, bahnen: int = 4) -> None:
        from kegel_cv.calibration.session import GuideStep

        session = view.session
        session.start_guide(lanes=bahnen)
        _spiegeln(view, session)

        schutz = 0
        while session.guide_active and schutz < 500:
            schutz += 1
            if session.guide_step is GuideStep.ECKEN:
                versatz = (session.guide_lane - 1) * 40
                for x, y in ((100.0 + versatz, 60.0), (280.0 + versatz, 60.0),
                             (280.0 + versatz, 240.0), (100.0 + versatz, 240.0)):
                    klick(view, x, y)
                _spiegeln(view, session)
                session.guide_advance()
            elif session.guide_step is GuideStep.BEREICHE:
                while session.step is CalibrationStep.PICK_ROIS:
                    if session.place_roi(190.0, 150.0):
                        break
                session.guide_advance()
            else:
                while session.step is CalibrationStep.FRAME_DIGITS:
                    session.frame_digit(180.0, 140.0)
                    if session.frame_digit(200.0, 160.0):
                        break
                session.guide_advance()
            _spiegeln(view, session)

    def test_alle_bahnen_werden_kalibriert(self, oberflaeche):
        from kegel_cv.calibration.session import GuideStep

        self._durchlaufen(oberflaeche)

        assert oberflaeche.session.guide_step is GuideStep.FERTIG
        assert len(oberflaeche.session.calibration.lanes) == 4

    def test_spaetere_bahnen_erben_die_felder_der_ersten(self, oberflaeche):
        """Der Kern: Bahn 2 bis 4 brauchen nur noch die vier Tafelecken."""
        self._durchlaufen(oberflaeche)

        erste = oberflaeche.session.calibration.get_lane(1)
        for lane_id in (2, 3, 4):
            spaeter = oberflaeche.session.calibration.get_lane(lane_id)
            assert {r.name for r in spaeter.rois} == {r.name for r in erste.rois}
            ziffern = [r for r in spaeter.rois if r.name.startswith("digit_")]
            assert ziffern, f"Bahn {lane_id} hat keine Ziffernstellen geerbt"

    def test_am_ende_laesst_sich_alles_nachziehen(self, oberflaeche):
        self._durchlaufen(oberflaeche)
        _spiegeln(oberflaeche, oberflaeche.session)

        ziehen(oberflaeche, (280.0, 60.0), (290.0, 55.0))

        assert ("ecke", 1, 1) in oberflaeche.protokoll

    def test_der_hinweis_sagt_immer_was_zu_tun_ist(self, oberflaeche):
        from kegel_cv.calibration.session import GuideStep

        session = oberflaeche.session
        session.start_guide(lanes=2)
        assert "Bahn 1 von 2" in session.guide_hint
        assert "oben links" in session.guide_hint

        self._durchlaufen(oberflaeche, bahnen=2)
        assert session.guide_step is GuideStep.FERTIG
        assert "nachbessern" in session.guide_hint


class TestZiehenWieEinMensch:
    def test_ecke_ziehen_wenn_nichts_gesetzt_wird(self, oberflaeche):
        bahn_anlegen(oberflaeche, 1)
        _spiegeln(oberflaeche, oberflaeche.session)   # Schritt EDIT_ROIS

        ziehen(oberflaeche, (300.0, 60.0), (320.0, 50.0))

        assert ("ecke", 1, 1) in oberflaeche.protokoll
        assert oberflaeche.session.calibration.get_lane(1).quad[1] == [320.0, 50.0]

    def test_ziehen_ist_gesperrt_waehrend_gesetzt_wird(self, oberflaeche):
        """Sonst greift der Klick statt zu setzen -- genau der gemeldete Fehler."""
        bahn_anlegen(oberflaeche, 1)
        oberflaeche.session.select_roi("digit_left_display_1")
        _spiegeln(oberflaeche, oberflaeche.session)

        ziehen(oberflaeche, (300.0, 60.0), (320.0, 50.0))

        assert oberflaeche.protokoll == [], "waehrend des Setzens wird nicht gezogen"
        assert oberflaeche.session.calibration.get_lane(1).quad[1] == [300.0, 60.0]

    def test_rois_wandern_beim_eckziehen_mit(self, oberflaeche):
        """Der Gewinn der normierten Tafelkoordinaten -- sichtbar gemacht."""
        bahn_anlegen(oberflaeche, 1)
        _spiegeln(oberflaeche, oberflaeche.session)
        vorher = oberflaeche.session.calibration.get_lane(1).get_roi("green_lamp").rect

        ziehen(oberflaeche, (300.0, 60.0), (330.0, 45.0))

        nachher = oberflaeche.session.calibration.get_lane(1).get_roi("green_lamp").rect
        assert nachher == vorher, "die Bereiche bleiben relativ zur Tafel stehen"
