"""Ziffernrahmen um wenige Pixel verschieben.

WOFUER -- Beobachtung des Nutzers am 2026-09-09, mit blossem Auge:

    "die Ziffern passen noch nicht ueberall... Fehlwurfziffern sind alle zu
     weit rechts unten. Die Wurfnummern sind ebenfalls alle zu weit rechts"

Nachgemessen an 66 von Hand abgelesenen Stellen:

    Versatz    richtig   falsch   unlesbar
      0 px      54        7         5
     -1 px      60        3         3
     -2 px      45       19         2

EIN Pixel entscheidet ueber neun Prozentpunkte. Sechs von sieben Fehlern
waren `1` gelesen als `3`, und sie verschwinden vollstaendig.
"""

from __future__ import annotations

import pytest

from kegel_cv.calibration.digit_shift import (ist_ziffern_roi, tafelmasse,
                                              verschiebe_ziffern)
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi


def kalibrierung(breite=200.0, hoehe=100.0) -> Calibration:
    return Calibration(lanes=[LaneCalibration(
        lane_id=1,
        quad=[[0.0, 0.0], [breite, 0.0], [breite, hoehe], [0.0, hoehe]],
        rois=[
            Roi(name="throw_number", rect=(0.10, 0.80, 0.20, 0.10)),
            Roi(name="digit_throw_number_1", rect=(0.12, 0.82, 0.05, 0.08)),
            Roi(name="digit_throw_number_2", rect=(0.18, 0.82, 0.05, 0.08)),
            Roi(name="digit_total_b_1", rect=(0.50, 0.82, 0.05, 0.08)),
            Roi(name="green_lamp", rect=(0.45, 0.70, 0.04, 0.04)),
            Roi(name="pin_lamp_5", rect=(0.45, 0.40, 0.04, 0.04)),
        ])])


class TestWasAlsZifferGilt:
    """HIER LAG EIN FEHLER: Ein Filter auf die Feldnamen allein trifft die
    einzelnen Stellen NICHT -- sie heissen `digit_<feld>_<n>`. Die
    Verschiebung kam dadurch nicht an, und die Gegenprobe zeigte scheinbar
    keinerlei Wirkung."""

    @pytest.mark.parametrize("name", [
        "throw_number", "digit_throw_number_1", "total_b", "digit_total_b_4",
        "left_display", "digit_left_display_2", "pin_count", "total_a"])
    def test_ziffernfelder_und_ihre_stellen(self, name):
        assert ist_ziffern_roi(name)

    @pytest.mark.parametrize("name", [
        "green_lamp", "pin_lamp_5", "digit_unbekannt_1", "quad"])
    def test_alles_andere_nicht(self, name):
        assert not ist_ziffern_roi(name)


class TestTafelmasse:
    def test_ein_rechteck(self):
        assert tafelmasse([[0, 0], [200, 0], [200, 100], [0, 100]]) \
            == (200.0, 100.0)

    def test_gemittelt_ueber_gegenueberliegende_kanten(self):
        b, h = tafelmasse([[0, 0], [200, 0], [180, 100], [0, 100]])
        assert b == 190.0


class TestVerschieben:
    def test_ein_pixel_nach_links(self):
        kal = kalibrierung(breite=200.0)
        verschiebe_ziffern(kal, -1, 0)
        roi = next(r for r in kal.lanes[0].rois
                   if r.name == "digit_throw_number_1")
        # 1 px von 200 px Tafelbreite = 0,005 in Tafelkoordinaten
        assert roi.rect[0] == pytest.approx(0.12 - 0.005)

    def test_die_groesse_bleibt(self):
        kal = kalibrierung()
        vorher = [r.rect[2:] for r in kal.lanes[0].rois]
        verschiebe_ziffern(kal, -2, 3)
        assert [r.rect[2:] for r in kal.lanes[0].rois] == vorher

    def test_lampen_bleiben_unberuehrt(self):
        """Die Lampen sitzen richtig -- nur die Ziffern nicht."""
        kal = kalibrierung()
        vorher = {r.name: r.rect for r in kal.lanes[0].rois
                  if not ist_ziffern_roi(r.name)}
        verschiebe_ziffern(kal, -3, 2)
        nachher = {r.name: r.rect for r in kal.lanes[0].rois
                   if not ist_ziffern_roi(r.name)}
        assert nachher == vorher

    def test_die_zahl_der_verschobenen_wird_gemeldet(self):
        kal = kalibrierung()
        assert verschiebe_ziffern(kal, -1, 0) == 4

    def test_null_verschiebt_nichts(self):
        kal = kalibrierung()
        vorher = [r.rect for r in kal.lanes[0].rois]
        assert verschiebe_ziffern(kal, 0, 0) == 0
        assert [r.rect for r in kal.lanes[0].rois] == vorher

    def test_kleine_tafel_braucht_groesseren_anteil(self):
        """Ein Pixel ist auf einer kleinen Tafel mehr als auf einer grossen."""
        klein, gross = kalibrierung(breite=100.0), kalibrierung(breite=400.0)
        verschiebe_ziffern(klein, -1, 0)
        verschiebe_ziffern(gross, -1, 0)
        x_klein = next(r.rect[0] for r in klein.lanes[0].rois
                       if r.name == "digit_total_b_1")
        x_gross = next(r.rect[0] for r in gross.lanes[0].rois
                       if r.name == "digit_total_b_1")
        assert x_klein < x_gross

    def test_der_rahmen_bleibt_in_der_tafel(self):
        """Ein ROI ausserhalb 0..1 wird vom Datenmodell abgelehnt -- und das
        mitten in einer Nutzereingabe."""
        kal = kalibrierung(breite=20.0, hoehe=20.0)
        verschiebe_ziffern(kal, -50, -50)
        for r in kal.lanes[0].rois:
            x, y, w, h = r.rect
            assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0
            assert x + w <= 1.0 + 1e-9 and y + h <= 1.0 + 1e-9

    def test_mehrere_bahnen_werden_einzeln_gerechnet(self):
        kal = kalibrierung(breite=200.0)
        zweite = kal.lanes[0].model_copy(deep=True)
        zweite.lane_id = 2
        zweite.quad = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0]]
        kal.lanes.append(zweite)
        verschiebe_ziffern(kal, -1, 0)
        a = next(r.rect[0] for r in kal.lanes[0].rois
                 if r.name == "digit_total_b_1")
        b = next(r.rect[0] for r in kal.lanes[1].rois
                 if r.name == "digit_total_b_1")
        assert b < a, "die schmalere Tafel verschiebt anteilig weiter"
