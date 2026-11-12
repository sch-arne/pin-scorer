"""Tests der Kalibrierung: Geometrie, ROIs, Persistenz."""

from __future__ import annotations

import json

import numpy as np
import pytest

from kegel_cv.calibration.geometry import (
    GeometryError,
    PerspectiveTransform,
    Quad,
    norm_rect_to_frame_bbox,
)
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi, SourceHint
from kegel_cv.calibration.session import CalibrationSession, CalibrationStep, default_roi_layout

SQUARE = [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)]


class TestQuad:
    def test_gueltiges_viereck(self):
        quad = Quad.from_points(SQUARE)
        quad.validate()
        assert quad.area == pytest.approx(40_000)
        assert quad.is_convex()

    def test_falsche_punktzahl(self):
        with pytest.raises(GeometryError, match="genau 4 Punkte"):
            Quad.from_points([(0, 0), (1, 1)])

    def test_doppelte_punkte(self):
        quad = Quad.from_points([(0, 0), (0, 0), (10, 10), (0, 10)])
        with pytest.raises(GeometryError, match="doppelte Punkte"):
            quad.validate()

    def test_entartetes_viereck(self):
        """Alle Punkte auf einer Linie -- Flaeche null."""
        quad = Quad.from_points([(0, 0), (10, 0), (20, 0), (30, 0)])
        with pytest.raises(GeometryError):
            quad.validate()

    def test_vertauschte_reihenfolge_wird_erkannt(self):
        """Sanduhr-Form durch vertauschte Punkte 3 und 4.

        Ohne diese Pruefung entstuende eine Homographie, die ein gespiegeltes
        Tafelbild liefert -- der Fehler faellt sonst erst bei der Erkennung auf.
        """
        quad = Quad.from_points([(100, 100), (300, 100), (100, 300), (300, 300)])
        with pytest.raises(GeometryError, match="nicht konvex"):
            quad.validate()

    def test_perspektivisches_viereck_ist_gueltig(self):
        """Realistischer Fall: Tafel schraeg im Bild."""
        quad = Quad.from_points([(105, 40), (295, 45), (300, 290), (100, 285)])
        quad.validate()


class TestPerspectiveTransform:
    @pytest.fixture
    def transform(self):
        return PerspectiveTransform(Quad.from_points(SQUARE), width=100, height=200)

    def test_ecken_werden_auf_zielrechteck_abgebildet(self, transform):
        corners = np.array(SQUARE, dtype=np.float32)
        warped = transform.frame_to_warped(corners)
        expected = np.array([[0, 0], [100, 0], [100, 200], [0, 200]], dtype=np.float32)
        np.testing.assert_allclose(warped, expected, atol=1e-3)

    def test_rueckwaerts_ist_die_umkehrung(self, transform):
        points = np.array([[150.0, 180.0], [250.0, 220.0]], dtype=np.float32)
        roundtrip = transform.warped_to_frame(transform.frame_to_warped(points))
        np.testing.assert_allclose(roundtrip, points, atol=1e-3)

    def test_normierte_koordinaten(self, transform):
        """Mitte der Tafel (0.5, 0.5) liegt in der Mitte des Quadrats."""
        center = transform.norm_to_frame(np.array([[0.5, 0.5]], dtype=np.float32))
        np.testing.assert_allclose(center[0], [200.0, 200.0], atol=1e-3)

    def test_norm_roundtrip(self, transform):
        norm = np.array([[0.25, 0.75]], dtype=np.float32)
        back = transform.frame_to_norm(transform.norm_to_frame(norm))
        np.testing.assert_allclose(back, norm, atol=1e-4)

    def test_warp_liefert_zielgroesse(self, transform):
        frame = np.zeros((400, 400, 3), dtype=np.uint8)
        assert transform.warp(frame).shape == (200, 100, 3)

    def test_ungueltige_zielgroesse(self):
        with pytest.raises(GeometryError):
            PerspectiveTransform(Quad.from_points(SQUARE), width=0, height=100)

    def test_bbox_aus_normiertem_rechteck(self, transform):
        x, y, w, h = norm_rect_to_frame_bbox(transform, (0.0, 0.0, 0.5, 0.5))
        assert (x, y) == (100, 100)
        assert w == pytest.approx(100, abs=1)
        assert h == pytest.approx(100, abs=1)

    def test_bbox_wird_auf_bildgrenzen_begrenzt(self, transform):
        """Eine ROI am Rand darf keine negativen Indizes erzeugen."""
        small_frame = (150, 150, 3)
        x, y, w, h = norm_rect_to_frame_bbox(transform, (0.5, 0.5, 0.5, 0.5), small_frame)
        assert x >= 0 and y >= 0
        assert x + w <= 150 and y + h <= 150


class TestRoi:
    def test_gueltige_roi(self):
        roi = Roi(name="green_lamp", rect=(0.4, 0.6, 0.1, 0.05))
        assert roi.center == pytest.approx((0.45, 0.625))

    @pytest.mark.parametrize("rect", [
        (0.0, 0.0, 0.0, 0.1),     # Breite null
        (0.0, 0.0, 0.1, -0.1),    # negative Hoehe
        (0.9, 0.5, 0.5, 0.1),     # ragt rechts hinaus
        (-0.1, 0.5, 0.2, 0.1),    # negative Position
    ])
    def test_ungueltige_rects_werden_abgelehnt(self, rect):
        with pytest.raises(ValueError):
            Roi(name="test", rect=rect)

    def test_verschieben_erhaelt_groesse(self):
        roi = Roi(name="test", rect=(0.1, 0.1, 0.2, 0.1))
        moved = roi.moved_to(0.5, 0.5)
        assert moved.center == pytest.approx((0.5, 0.5))
        assert moved.rect[2:] == roi.rect[2:]


class TestCalibrationPersistence:
    @pytest.fixture
    def calibration(self):
        cal = Calibration(name="test", source_hint=SourceHint(width=1920, height=1080))
        cal.set_lane(LaneCalibration(
            lane_id=1,
            quad=[[100, 100], [300, 100], [300, 300], [100, 300]],
            rois=[Roi(name="green_lamp", rect=(0.45, 0.65, 0.09, 0.05))],
        ))
        return cal

    def test_speichern_und_laden(self, calibration, tmp_path):
        path = calibration.save(tmp_path / "test.json")
        loaded = Calibration.load(path)

        assert loaded.name == "test"
        assert len(loaded.lanes) == 1
        assert loaded.get_lane(1).get_roi("green_lamp").rect == pytest.approx(
            (0.45, 0.65, 0.09, 0.05)
        )

    def test_schema_version_wird_geschrieben(self, calibration, tmp_path):
        path = calibration.save(tmp_path / "test.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1

    def test_zu_neue_schema_version_wird_abgelehnt(self, calibration, tmp_path):
        """Ohne diese Pruefung wuerde eine neuere Datei still falsch gelesen."""
        path = tmp_path / "future.json"
        data = calibration.model_dump()
        data["schema_version"] = 99
        path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(ValueError, match="Schema-Version"):
            Calibration.load(path)

    def test_fehlende_datei(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            Calibration.load(tmp_path / "gibtsnicht.json")

    def test_warnung_bei_abweichender_aufloesung(self, calibration):
        warnings = calibration.check_against_video(1280, 720)
        assert any("Breite" in w for w in warnings)
        assert calibration.check_against_video(1920, 1080) == []

    def test_lane_wird_ersetzt_nicht_dupliziert(self, calibration):
        calibration.set_lane(LaneCalibration(
            lane_id=1, quad=[[0, 0], [10, 0], [10, 10], [0, 10]]
        ))
        assert len(calibration.lanes) == 1

    def test_fehlende_rois_werden_gemeldet(self):
        lane = LaneCalibration(lane_id=1, quad=[[0, 0], [10, 0], [10, 10], [0, 10]])
        missing = lane.missing_rois()
        assert "green_lamp" in missing
        assert "pin_lamp_9" in missing
        assert len(missing) == 5 + 9


class TestCalibrationSession:
    def test_vollstaendiger_ablauf(self):
        session = CalibrationSession()
        assert session.step is CalibrationStep.IDLE

        session.start_lane(1)
        assert session.step is CalibrationStep.PICK_CORNERS
        assert session.next_corner_label == "oben links"

        for i, point in enumerate(SQUARE):
            complete = session.add_point(*point)
            assert complete == (i == 3)

        # Sammeln und Uebernehmen sind bewusst getrennt: Bei einem ungueltigen
        # Viereck soll die GUI die gesetzten Punkte behalten koennen, statt den
        # Nutzer neu beginnen zu lassen.
        assert session.step is CalibrationStep.PICK_CORNERS
        ok, _ = session.try_commit()
        assert ok is True

        assert session.step is CalibrationStep.EDIT_ROIS
        lane = session.calibration.get_lane(1)
        assert lane is not None
        assert len(lane.rois) == 15   # 9 Lampen + 6 Displays
        assert session.pending_points == []

    def test_klick_ohne_aktive_bahn_wird_ignoriert(self):
        session = CalibrationSession()
        assert session.add_point(10, 10) is False
        assert session.pending_points == []

    def test_punkt_zuruecknehmen(self):
        session = CalibrationSession()
        session.start_lane(1)
        session.add_point(*SQUARE[0])
        session.add_point(*SQUARE[1])

        assert session.undo_point() is True
        assert len(session.pending_points) == 1
        assert session.next_corner_label == "oben rechts"

        session.undo_point()
        assert session.undo_point() is False

    def test_ungueltiges_viereck_meldet_fehler_ohne_exception(self):
        """Ein Bedienfehler soll eine Meldung erzeugen, keinen Stacktrace."""
        session = CalibrationSession()
        session.start_lane(1)
        for point in [(100, 100), (300, 100), (100, 300), (300, 300)]:
            session.add_point(*point)

        ok, message = session.try_commit()
        assert ok is False
        assert "konvex" in message
        assert session.calibration.get_lane(1) is None

    def test_bestehende_rois_bleiben_bei_neukalibrierung_erhalten(self):
        """Wer die Ecken korrigiert, will seine ROI-Anpassungen nicht verlieren."""
        session = CalibrationSession()
        session.start_lane(1)
        for point in SQUARE:
            session.add_point(*point)
        session.try_commit()

        lane = session.calibration.get_lane(1)
        lane.set_roi(Roi(name="green_lamp", rect=(0.11, 0.22, 0.05, 0.05)))

        session.start_lane(1)
        for point in [(110, 110), (310, 110), (310, 310), (110, 310)]:
            session.add_point(*point)
        session.try_commit()

        roi = session.calibration.get_lane(1).get_roi("green_lamp")
        assert roi.rect == pytest.approx((0.11, 0.22, 0.05, 0.05))


class TestDefaultRoiLayout:
    def test_neun_kegellampen_plus_displays(self):
        rois = default_roi_layout()
        lamps = [r for r in rois if r.name.startswith("pin_lamp_")]
        assert len(lamps) == 9
        assert {r.pin_number for r in lamps} == set(range(1, 10))

    def test_alle_rois_liegen_innerhalb_der_tafel(self):
        for roi in default_roi_layout():
            x, y, w, h = roi.rect
            assert 0 <= x and 0 <= y
            assert x + w <= 1.001 and y + h <= 1.001

    def test_lampen_bilden_eine_raute(self):
        """Zeilenbelegung 1-2-3-2-1 wie das deutsche Kegelbild."""
        lamps = sorted(
            (r for r in default_roi_layout() if r.name.startswith("pin_lamp_")),
            key=lambda r: r.pin_number,
        )
        rows: dict[float, int] = {}
        for lamp in lamps:
            cy = round(lamp.center[1], 3)
            rows[cy] = rows.get(cy, 0) + 1
        assert sorted(rows.values(), reverse=True) == [3, 2, 2, 1, 1]


class TestLampenBekommenDieSollgroesse:
    """Gemeldet 2026-09-04: Die gefuehrte Kalibrierung fuegte zu grosse
    Lampen-ROIs ein.

    URSACHE: `set_roi_at` verschob eine bereits vorhandene ROI nur
    (`moved_to`) und liess ihre Groesse unangetastet. Beim gefuehrten Setzen
    existieren die ROIs aber IMMER schon -- aus der Vorlage `_roi_muster()`
    oder der Raute `default_roi_layout()`. `default_roi_size()` kam damit nie
    zum Zug, und eine Vorlage mit weiten Lampen (0,080 x 0,075 aus einer
    aelteren Kalibrierung) vererbte ihre Groesse an jede neu geklickte Bahn.

    Die Lampengroesse ist gemessen und entscheidet ueber die Trennschaerfe
    zwischen AN und AUS -- sie darf nicht aus einer Vorlage stammen.
    """

    def _session_mit_weiter_lampe(self):
        from kegel_cv.calibration.session import CalibrationSession, default_roi_size
        from kegel_cv.calibration.model import Roi
        sitzung = CalibrationSession()
        sitzung.start_lane(1)
        for punkt in ((100, 100), (300, 100), (300, 250), (100, 250)):
            sitzung.add_point(*punkt)
        sitzung.commit_quad(default_rois=False)
        bahn = sitzung.calibration.get_lane(sitzung.active_lane)
        assert bahn is not None, "Vorbedingung: Bahn ist kalibriert"
        # Eine ROI mit der ALTEN, weiten Groesse -- wie sie aus einer
        # aelteren Kalibrierung als Vorlage kaeme.
        bahn.set_roi(Roi(name="pin_lamp_1", rect=(0.4, 0.3, 0.080, 0.075),
                         pin_number=1))
        return sitzung, default_roi_size

    def test_gefuehrtes_setzen_zieht_die_lampe_zusammen(self):
        sitzung, default_roi_size = self._session_mit_weiter_lampe()
        sitzung.start_roi_picking(["pin_lamp_1"])
        sitzung.place_roi(200, 175)

        roi = sitzung.calibration.get_lane(sitzung.active_lane).get_roi("pin_lamp_1")
        soll_w, soll_h = default_roi_size("pin_lamp_1")
        assert roi.rect[2] == pytest.approx(soll_w), (
            "Die Lampe muss auf die gemessene Sollbreite gesetzt werden, "
            "nicht die Groesse der Vorlage behalten."
        )
        assert roi.rect[3] == pytest.approx(soll_h)

    def test_ziffernfeld_behaelt_seine_groesse(self):
        """Gegenprobe: Bei Ziffern kann eine angepasste Groesse gewollt sein."""
        from kegel_cv.calibration.model import Roi
        sitzung, _ = self._session_mit_weiter_lampe()
        bahn = sitzung.calibration.get_lane(sitzung.active_lane)
        bahn.set_roi(Roi(name="pin_count", rect=(0.4, 0.3, 0.222, 0.191)))

        sitzung.start_roi_picking(["pin_count"])
        sitzung.place_roi(200, 175)

        roi = bahn.get_roi("pin_count")
        assert roi.rect[2] == pytest.approx(0.222), "Breite bleibt erhalten"
        assert roi.rect[3] == pytest.approx(0.191), "Hoehe bleibt erhalten"
