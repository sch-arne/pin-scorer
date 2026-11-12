"""Tests der Ansichts-Transformation (Zoom, Verschiebung, Koordinatenwechsel).

Diese Rechnung ist die fehleranfaelligste Stelle der Oberflaeche: Sitzt sie
falsch, landen ALLE Kalibrierpunkte daneben -- und der Fehler faellt erst
viel spaeter auf, weit weg von seiner Ursache.

Deshalb liegt sie ohne Qt in einer eigenen Klasse und wird hier vollstaendig
geprueft.
"""

from __future__ import annotations

import pytest

from kegel_cv.gui.view_transform import MAX_ZOOM, MIN_ZOOM, ViewTransform


@pytest.fixture
def view() -> ViewTransform:
    """1920x1080-Bild in einem 960x540-Widget -- also base_scale 0.5."""
    v = ViewTransform()
    v.set_frame_size(1920, 1080)
    v.set_widget_size(960, 540)
    return v


class TestGrundabbildung:
    def test_base_scale_passt_das_bild_ein(self, view):
        assert view.base_scale == pytest.approx(0.5)
        assert view.scale == pytest.approx(0.5)

    def test_bildmitte_liegt_in_der_widgetmitte(self, view):
        assert view.frame_to_widget(960, 540) == pytest.approx((480, 270))

    def test_ecken(self, view):
        assert view.frame_to_widget(0, 0) == pytest.approx((0, 0))
        assert view.frame_to_widget(1920, 1080) == pytest.approx((960, 540))

    def test_hin_und_rueckrechnung(self, view):
        for point in [(0, 0), (100, 200), (1919, 1079), (960, 540)]:
            back = view.widget_to_frame(*view.frame_to_widget(*point))
            assert back == pytest.approx(point, abs=1e-6)

    def test_ungleiches_seitenverhaeltnis_laesst_rand(self, view):
        """Bei breitem Widget entsteht oben/unten kein Rand, links/rechts schon."""
        view.set_widget_size(1920, 540)
        assert view.base_scale == pytest.approx(0.5)   # Hoehe begrenzt
        left, _ = view.frame_to_widget(0, 0)
        assert left == pytest.approx(480)              # zentriert


class TestZoom:
    def test_zoom_vergroessert_die_skalierung(self, view):
        view.set_zoom(4.0)
        assert view.scale == pytest.approx(2.0)

    def test_zoom_am_zeiger_haelt_den_punkt_fest(self, view):
        """Der Kern der Bedienbarkeit: Was unter der Maus ist, bleibt dort.

        Ohne diese Verankerung wandert die anvisierte Lampe beim Zoomen weg.
        """
        mouse = (700.0, 400.0)
        before = view.widget_to_frame(*mouse)

        view.zoom_at(*mouse, 2.0)

        after = view.widget_to_frame(*mouse)
        assert after == pytest.approx(before, abs=0.5)

    def test_mehrfaches_zoomen_bleibt_verankert(self, view):
        mouse = (300.0, 150.0)
        before = view.widget_to_frame(*mouse)
        for _ in range(5):
            view.zoom_at(*mouse, 1.25)
        assert view.widget_to_frame(*mouse) == pytest.approx(before, abs=1.0)

    def test_zoom_ist_nach_oben_begrenzt(self, view):
        for _ in range(100):
            view.zoom_at(480, 270, 2.0)
        assert view.zoom == pytest.approx(MAX_ZOOM)

    def test_zoom_ist_nach_unten_begrenzt(self, view):
        """Kleiner als das eingepasste Bild ergibt keinen Sinn."""
        for _ in range(50):
            view.zoom_at(480, 270, 0.5)
        assert view.zoom == pytest.approx(MIN_ZOOM)

    def test_reset_stellt_die_gesamtansicht_her(self, view):
        view.zoom_at(100, 100, 8.0)
        view.reset()
        assert view.zoom == 1.0
        assert view.frame_to_widget(960, 540) == pytest.approx((480, 270))


class TestZoomAufBereich:
    def test_tafel_fuellt_das_widget(self, view):
        """Eine Anzeigetafel (160x155 px) soll formatfuellend erscheinen."""
        view.zoom_to_rect(1026, 50, 160, 157)

        assert view.zoom > 2.0
        centre = view.frame_to_widget(1026 + 160 / 2, 50 + 157 / 2)
        assert centre == pytest.approx((480, 270), abs=0.5)

    def test_tafel_passt_vollstaendig_ins_bild(self, view):
        view.zoom_to_rect(1026, 50, 160, 157)
        x, y, w, h = view.visible_rect
        assert x <= 1026 and y <= 50
        assert x + w >= 1026 + 160
        assert y + h >= 50 + 157

    def test_entartete_bereiche_werden_ignoriert(self, view):
        before = view.zoom
        view.zoom_to_rect(100, 100, 0, 50)
        assert view.zoom == before


class TestVerschieben:
    def test_pan_verschiebt_gegenlaeufig(self, view):
        """Ziehen nach rechts holt Bildinhalt von links ins Bild."""
        view.set_zoom(4.0)
        before = view.center_x
        view.pan_by_widget(100, 0)
        assert view.center_x < before

    def test_pan_ohne_zoom_bleibt_zentriert(self, view):
        view.pan_by_widget(200, 200)
        assert view.center_x == pytest.approx(960)
        assert view.center_y == pytest.approx(540)

    def test_ausschnitt_bleibt_am_bild(self, view):
        """Sonst liesse sich das Bild aus dem Fenster schieben, bis nur noch
        Hintergrund zu sehen ist -- ohne Weg zurueck."""
        view.set_zoom(4.0)
        for _ in range(50):
            view.pan_by_widget(500, 500)

        x, y, w, h = view.visible_rect
        assert x + w <= 1920 + 1
        assert y + h <= 1080 + 1

        for _ in range(100):
            view.pan_by_widget(-500, -500)
        x, y, _, _ = view.visible_rect
        assert x >= -1 and y >= -1


class TestBereichspruefung:
    def test_punkte_im_bild(self, view):
        assert view.contains_frame_point(0, 0)
        assert view.contains_frame_point(1920, 1080)
        assert view.contains_frame_point(960, 540)

    def test_punkte_ausserhalb(self, view):
        assert not view.contains_frame_point(-1, 500)
        assert not view.contains_frame_point(1921, 500)
        assert not view.contains_frame_point(500, -1)


class TestBildwechsel:
    def test_neue_bildgroesse_setzt_die_ansicht_zurueck(self, view):
        view.set_zoom(6.0)
        view.set_frame_size(1280, 720)
        assert view.zoom == 1.0
        assert view.center_x == pytest.approx(640)

    def test_gleiche_bildgroesse_behaelt_den_zoom(self, view):
        """Beim naechsten Frame desselben Videos darf der Zoom nicht springen."""
        view.set_zoom(6.0)
        centre = view.center_x
        view.set_frame_size(1920, 1080)
        assert view.zoom == pytest.approx(6.0)
        assert view.center_x == pytest.approx(centre)

    def test_ohne_bild_keine_division_durch_null(self):
        """Vor dem ersten Frame darf nichts abstuerzen -- die GUI ruft die
        Umrechnung auch dann auf, wenn noch kein Video geladen ist."""
        empty = ViewTransform()
        assert empty.base_scale == 1.0
        assert empty.scale > 0
        x, y = empty.widget_to_frame(10, 10)
        assert isinstance(x, float) and isinstance(y, float)
        empty.zoom_at(10, 10, 2.0)      # darf ebenfalls nicht krachen
        empty.pan_by_widget(5, 5)
