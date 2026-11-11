"""Tests der Zaehl- und Zykluslogik.

Die 15er-Zyklusrechnung ist die klassische Off-by-one-Falle des Projekts:
`throw_number % 15` liefert bei Wurf 15 den Wert 0 statt 15.
"""

from __future__ import annotations

import pytest

from kegel_cv.models.scoring import (
    LaneScore,
    bitmap_to_pins,
    cycle_number,
    is_cycle_end,
    pins_to_bitmap,
    throw_in_cycle,
)


class TestZyklusRechnung:
    @pytest.mark.parametrize(
        "throw,expected_in_cycle,expected_cycle",
        [
            (1, 1, 1),
            (2, 2, 1),
            (14, 14, 1),
            (15, 15, 1),    # NICHT 0 -- das ist die Falle
            (16, 1, 2),
            (29, 14, 2),
            (30, 15, 2),    # NICHT 0
            (31, 1, 3),
            (45, 15, 3),
        ],
    )
    def test_wurf_im_zyklus_und_zyklusnummer(self, throw, expected_in_cycle, expected_cycle):
        assert throw_in_cycle(throw) == expected_in_cycle
        assert cycle_number(throw) == expected_cycle

    @pytest.mark.parametrize("throw,expected", [(14, False), (15, True), (16, False), (30, True)])
    def test_zyklusende(self, throw, expected):
        assert is_cycle_end(throw) is expected

    def test_wurfnummer_ist_1_basiert(self):
        with pytest.raises(ValueError, match="1-basiert"):
            throw_in_cycle(0)

    def test_abweichende_zykluslaenge(self):
        """Die Zykluslaenge kommt aus der Konfiguration, nicht aus dem Code."""
        assert throw_in_cycle(10, throws_per_cycle=10) == 10
        assert cycle_number(11, throws_per_cycle=10) == 2


class TestBitmap:
    @pytest.mark.parametrize(
        "pins,bitmap",
        [
            ([], 0),
            ([1], 0b000000001),
            ([9], 0b100000000),
            ([1, 3, 5, 6, 8], 0b010110101),
            ([1, 2, 3, 4, 5, 6, 7, 8, 9], 511),
        ],
    )
    def test_hin_und_rueckwandlung(self, pins, bitmap):
        assert pins_to_bitmap(pins) == bitmap
        assert bitmap_to_pins(bitmap) == tuple(pins)

    def test_ungueltige_kegelnummer(self):
        with pytest.raises(ValueError, match="zwischen 1 und 9"):
            pins_to_bitmap([10])

    def test_ungueltige_bitmap(self):
        with pytest.raises(ValueError, match="zwischen 0 und 511"):
            bitmap_to_pins(512)


class TestLaneScore:
    def test_laufende_summe(self):
        score = LaneScore(lane=1)
        assert score.register(1, 7) == (7, None)
        assert score.register(2, 5) == (12, None)
        assert score.register(3, 0) == (12, None)   # Leerwurf zaehlt mit

    def test_zwischensumme_nach_15_wuerfen(self):
        score = LaneScore(lane=1)
        for throw in range(1, 15):
            total, series = score.register(throw, 5)
            assert series is None, f"Wurf {throw} darf keine Zwischensumme liefern"

        total, series = score.register(15, 3)
        assert total == 14 * 5 + 3 == 73
        assert series == 73, "Nach Wurf 15 muss die Zyklussumme vorliegen"

    def test_zweiter_zyklus_zaehlt_ab_null(self):
        score = LaneScore(lane=1)
        for throw in range(1, 16):
            score.register(throw, 4)          # Zyklus 1: 60
        for throw in range(16, 30):
            score.register(throw, 2)
        total, series = score.register(30, 2)

        assert total == 60 + 15 * 2 == 90
        assert series == 30, "Zyklus 2 darf nur die eigenen Wuerfe summieren"
        assert score.cycle_totals == [60, 30]

    def test_double_counting_wird_abgelehnt(self):
        """Dieselbe Wurfnummer zweimal zu buchen ist ein Fehler, kein Sonderfall."""
        score = LaneScore(lane=1)
        score.register(5, 7)
        with pytest.raises(ValueError, match="Double Counting"):
            score.register(5, 7)
        with pytest.raises(ValueError):
            score.register(4, 3)   # rueckwaerts ebenfalls

    def test_luecke_wird_erkannt(self):
        score = LaneScore(lane=1)
        score.register(7, 5)
        assert score.has_gap(8) == 0
        assert score.has_gap(9) == 1
        assert score.has_gap(12) == 4

    def test_erwartete_summe(self):
        score = LaneScore(lane=1)
        score.register(1, 7)
        assert score.expected_total(5) == 12

    def test_bahnen_sind_unabhaengig(self):
        """Prinzip P6: Ein Ereignis auf einer Bahn darf keine andere beeinflussen."""
        lanes = {n: LaneScore(lane=n) for n in range(1, 5)}
        lanes[1].register(1, 9)
        lanes[1].register(2, 9)

        assert lanes[1].running_total == 18
        for n in (2, 3, 4):
            assert lanes[n].running_total == 0
            assert lanes[n].last_throw_number == 0
