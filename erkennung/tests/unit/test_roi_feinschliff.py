"""Feinschliff der Lampen je Tafel -- und die Grenze, die er nicht ueberschreitet.

ANLASS (Nutzer, 2026-09-11):

    "Die Lampen und die Ziffern lagen zum Teil leicht daneben ... Ich hatte das
     Gefuehl, dass aber jedes Board leicht anders verschoben war."

GEMESSEN und bestaetigt: Ueber die vier Tafeln wandert die Gruenlampe um
1,6 px, waehrend die Lampenraute stehenbleibt. Eine Verschiebung der ganzen
Tafel kann das nicht einfangen -- deshalb gruppenweise.

WAS DIESE TESTS VOR ALLEM FESTHALTEN: dass die ZIFFERN NICHT mitverschoben
werden. Das war gebaut und wurde nach der Messung wieder herausgenommen (7290
Zellen: pin_count von 71,5 auf 47,8 % sauber gelesen). Ein spaeterer, gut
gemeinter Griff, der sie wieder aufnimmt, faellt hier auf.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.calibration import roi_feinschliff as rf
from kegel_cv.calibration.model import LaneCalibration, Roi


def muster_mit_marken() -> tuple[np.ndarray, np.ndarray]:
    """Ein Musterbild mit zwei klar unterscheidbaren Strukturen.

    Oben ein Kreuz (die 'Lampenraute'), unten ein Rahmen (das 'Fenster') --
    beides scharfkantig, damit der Abgleich einen eindeutigen Scheitel hat.
    """
    bild = np.full((120, 120), 60, dtype=np.uint8)
    bild[28:32, 10:70] = 220
    bild[10:50, 38:42] = 220
    bild[80:110, 20:100] = 200
    bild[85:105, 25:95] = 40
    maske = np.ones((120, 120), np.uint8)
    return bild, maske


def eine_bahn() -> LaneCalibration:
    return LaneCalibration(
        lane_id=1,
        quad=[[0.0, 0.0], [120.0, 0.0], [120.0, 120.0], [0.0, 120.0]],
        rois=[
            Roi(name="pin_lamp_1", rect=(0.20, 0.20, 0.06, 0.06)),
            Roi(name="pin_lamp_2", rect=(0.40, 0.30, 0.06, 0.06)),
            Roi(name="green_lamp", rect=(0.30, 0.22, 0.05, 0.05)),
            Roi(name="throw_number", rect=(0.20, 0.70, 0.30, 0.15)),
            Roi(name="digit_throw_number_1", rect=(0.21, 0.71, 0.06, 0.12)),
            Roi(name="total_b", rect=(0.55, 0.70, 0.30, 0.15)),
        ])


def verschoben(bild: np.ndarray, dx: int, dy: int) -> np.ndarray:
    """Dasselbe Bild, um ganze Pixel versetzt -- der bekannte Sollwert."""
    M = np.float32([[1, 0, dx], [0, 1, dy]])
    import cv2
    return cv2.warpAffine(bild, M, (bild.shape[1], bild.shape[0]),
                          borderMode=cv2.BORDER_REPLICATE)


class TestNurDieLampen:
    """Die wichtigste Eigenschaft: Ziffernfelder bleiben unangetastet."""

    def test_ziffern_sind_keine_gruppe(self):
        assert rf.gruppe_von("throw_number") is None
        assert rf.gruppe_von("digit_total_b_2") is None
        assert rf.gruppe_von("total_a") is None
        assert rf.gruppe_von("left_display") is None

    def test_lampen_sind_gruppen(self):
        assert rf.gruppe_von("pin_lamp_7") == "lampen"
        assert rf.gruppe_von("green_lamp") == "gruenlampe"

    def test_kegellampen_und_gruenlampe_sind_getrennt(self):
        """Sie wandern gemessen unterschiedlich weit -- zusammengefasst
        hoben sie sich gegenseitig auf."""
        assert rf.GRUPPEN["lampen"] != rf.GRUPPEN["gruenlampe"]

    def test_ein_ziffernfeld_wird_nicht_verschoben(self):
        bild, maske = muster_mit_marken()
        bahn = eine_bahn()
        vorher = {r.name: r.rect for r in bahn.rois}
        rf.schleife_nach(bahn, bild, maske, [verschoben(bild, 2, 1)])
        for name in ("throw_number", "digit_throw_number_1", "total_b"):
            assert bahn.get_roi(name).rect == vorher[name], \
                f"{name} darf der Feinschliff nicht anfassen"


class TestDerVersatzWirdGefunden:
    def test_ein_bekannter_versatz_kommt_heraus(self):
        """Das Bild wird um +2/+1 px versetzt -- genau das muss herauskommen."""
        bild, maske = muster_mit_marken()
        kasten = rf.kasten(eine_bahn().rois, "lampen", 120, 120)
        versatz = rf.feinversatz(bild, maske, verschoben(bild, 2, 1), kasten,
                                 min_pixel=50)
        assert versatz is not None
        assert versatz.dx == pytest.approx(2.0, abs=0.3)
        assert versatz.dy == pytest.approx(1.0, abs=0.3)

    def test_ohne_versatz_kommt_null_heraus(self):
        bild, maske = muster_mit_marken()
        kasten = rf.kasten(eine_bahn().rois, "lampen", 120, 120)
        versatz = rf.feinversatz(bild, maske, bild.copy(), kasten, min_pixel=50)
        assert abs(versatz.dx) < 0.2 and abs(versatz.dy) < 0.2

    def test_die_rois_wandern_mit(self):
        bild, maske = muster_mit_marken()
        bahn = eine_bahn()
        vorher = bahn.get_roi("pin_lamp_1").rect
        rf.schleife_nach(bahn, bild, maske, [verschoben(bild, 2, 0)],
                         min_pixel=50)
        nachher = bahn.get_roi("pin_lamp_1").rect
        assert nachher[0] - vorher[0] == pytest.approx(2 / 120, abs=0.004)

    def test_zu_wenig_flaeche_sagt_nichts(self):
        """Ein Ergebnis aus drei Dutzend Pixeln waere eine Zahl ohne Aussage."""
        bild, maske = muster_mit_marken()
        assert rf.feinversatz(bild, maske, bild, (10, 10, 20, 20),
                              min_pixel=10_000) is None


class TestWasVerworfenWird:
    def test_ein_grosser_versatz_wird_verworfen(self):
        """Mehr als `max_versatz` heisst nicht Feinschliff, sondern dass
        etwas anderes nicht stimmt."""
        bild, maske = muster_mit_marken()
        bahn = eine_bahn()
        vorher = {r.name: r.rect for r in bahn.rois}
        rf.schleife_nach(bahn, bild, maske, [verschoben(bild, 4, 4)],
                         weite=5, min_pixel=50, max_versatz=1.0)
        assert {r.name: r.rect for r in bahn.rois} == vorher

    def test_ohne_bilder_passiert_nichts(self):
        bild, maske = muster_mit_marken()
        bahn = eine_bahn()
        vorher = {r.name: r.rect for r in bahn.rois}
        assert rf.schleife_nach(bahn, bild, maske, []) == {}
        assert {r.name: r.rect for r in bahn.rois} == vorher

    def test_kein_bereich_verlaesst_die_tafel(self):
        """`model_copy` prueft nichts -- ein hinausgeschobener Bereich waere
        still kaputt und erst beim Speichern aufgefallen."""
        bild, maske = muster_mit_marken()
        bahn = eine_bahn()
        bahn.set_roi(Roi(name="pin_lamp_1", rect=(0.955, 0.20, 0.04, 0.04)))
        rf.schleife_nach(bahn, bild, maske, [verschoben(bild, 5, 0)],
                         min_pixel=50, max_versatz=9.0)
        for roi in bahn.rois:
            x, y, w, h = roi.rect
            assert 0.0 <= x and x + w <= 1.0001
            assert 0.0 <= y and y + h <= 1.0001


class TestMedianUeberBilder:
    def test_ein_ausreisser_zieht_nicht_mit(self):
        """MEDIAN, nicht Mittelwert: Ein Bild, auf dem jemand vor der Tafel
        steht, darf die Lage nicht mitziehen."""
        bild, maske = muster_mit_marken()
        bahn = eine_bahn()
        bilder = [verschoben(bild, 1, 0), verschoben(bild, 1, 0),
                  verschoben(bild, 1, 0), verschoben(bild, 4, 0)]
        rf.schleife_nach(bahn, bild, maske, bilder, min_pixel=50,
                         max_versatz=9.0)
        dx = (bahn.get_roi("pin_lamp_1").rect[0] - 0.20) * 120
        assert dx == pytest.approx(1.0, abs=0.4)
