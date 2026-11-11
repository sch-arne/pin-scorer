"""Die gemeldete Bahnnummer muss vor Ort einstellbar sein.

WARUM ES DIESES FEATURE GIBT -- Wunsch des Nutzers am 2026-09-09:

    "Ich brauche die Moeglichkeit selbst zu bestimmen, welche Bahnnummer in
     Supabase geschrieben werden"

Die Tafeln im Bild sind von links durchnummeriert (`lane_id` 1..4), die
Ergebnisse tragen aber die BAHNNUMMER der Halle. In der Stammhalle sind das
die Bahnen 2 bis 5; auswaerts kann dieselbe Anordnung 1 bis 4 oder 6 bis 9
heissen. Bisher kam die Zuordnung allein aus `calibration.lane_number_mapping`
und liess sich nur in der Konfigurationsdatei aendern -- also nicht dort, wo
man vor Ort steht.

Diese Zahl ist es, die als `lane` in der Datenbank landet:
`ThrowAnalyzer(lane.lane_id, cfg, lane.display_number)`.
"""

from __future__ import annotations

import pytest

from kegel_cv.calibration.model import Calibration, LaneCalibration
from kegel_cv.calibration.session import CalibrationSession


@pytest.fixture
def sitzung() -> CalibrationSession:
    s = CalibrationSession()
    # Ein Viereck ist Pflicht -- fuer diese Tests genuegt ein beliebiges.
    ecken = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    s.calibration = Calibration(lanes=[
        LaneCalibration(lane_id=i, quad=ecken, real_lane_number=i + 1)
        for i in range(1, 5)
    ])
    return s


class TestNummerAendern:
    def test_die_neue_nummer_gilt(self, sitzung):
        assert sitzung.set_real_lane_number(1, 7) is None
        bahn = sitzung.calibration.lanes[0]
        assert bahn.display_number == 7

    def test_die_anderen_bahnen_bleiben_unberuehrt(self, sitzung):
        """P6: Die Bahnen sind unabhaengig -- auch beim Umbenennen."""
        vorher = [l.display_number for l in sitzung.calibration.lanes[1:]]
        sitzung.set_real_lane_number(1, 7)
        assert [l.display_number for l in sitzung.calibration.lanes[1:]] == vorher

    def test_zuruecksetzen_faellt_auf_die_tafelnummer(self, sitzung):
        """Ohne eigene Nummer gilt die Position von links."""
        sitzung.set_real_lane_number(3, None)
        assert sitzung.calibration.lanes[2].display_number == 3

    def test_eine_unbekannte_bahn_ist_ein_fehler(self, sitzung):
        with pytest.raises(KeyError, match="9"):
            sitzung.set_real_lane_number(9, 1)


class TestDoppelteNummer:
    """Zwei Tafeln mit derselben Nummer verschmelzen in der Datenbank zu einer
    Bahn -- lautlos. Deshalb wird gewarnt."""

    def test_eine_dublette_wird_gemeldet(self, sitzung):
        warnung = sitzung.set_real_lane_number(1, 3)   # Tafel 2 meldet schon 3
        assert warnung is not None
        assert "3" in warnung and "doppelt" in warnung.lower()

    def test_sie_wird_aber_nicht_verhindert(self, sitzung):
        """Beim Umsortieren ist ein Zwischenzustand unvermeidlich."""
        sitzung.set_real_lane_number(1, 3)
        assert sitzung.calibration.lanes[0].display_number == 3

    def test_ohne_dublette_keine_warnung(self, sitzung):
        assert sitzung.set_real_lane_number(1, 42) is None

    def test_nach_dem_aufloesen_schweigt_sie_wieder(self, sitzung):
        sitzung.set_real_lane_number(1, 3)
        assert sitzung.set_real_lane_number(1, 8) is None


class TestWasInDerDatenbankLandet:
    def test_der_analyzer_bekommt_die_eingestellte_nummer(self, sitzung):
        """Der Weg von der Einstellung bis zum Datensatz -- eine Kette, die
        sonst niemand prueft."""
        from kegel_cv.analysis.throw_analyzer import ThrowAnalyzer
        from kegel_cv.config import load_config

        sitzung.set_real_lane_number(1, 7)
        bahn = sitzung.calibration.lanes[0]
        analyzer = ThrowAnalyzer(bahn.lane_id, load_config(), bahn.display_number)
        assert analyzer.score.lane == 7 or analyzer.display_number == 7

    def test_die_nummer_ueberlebt_das_speichern(self, sitzung, tmp_path):
        sitzung.set_real_lane_number(2, 11)
        ziel = tmp_path / "k.json"
        sitzung.calibration.save(ziel)
        wieder = Calibration.load(ziel)
        assert wieder.lanes[1].display_number == 11
