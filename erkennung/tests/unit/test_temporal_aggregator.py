"""Tests der zeitlichen Aggregation (Auftrag Paragraph 8).

Kernanforderung: Ein einzelnes Messergebnis wird nie uebernommen. Bleibt es
uneindeutig, ist das Ergebnis None -- es wird NICHT die haeufigste Variante
geraten.
"""

from __future__ import annotations

import pytest

from kegel_cv.analysis.temporal_aggregator import TemporalAggregator


class TestGrundfall:
    def test_einige_messungen_ergeben_das_ergebnis(self):
        agg = TemporalAggregator(min_confidence=0.5)
        for frame in range(4):
            agg.add("7", 0.9, frame)
        result = agg.result()
        assert result.value == "7"
        assert result.agreement == 1.0
        assert result.confidence > 0.8

    def test_unsichere_messungen_werden_verworfen(self):
        agg = TemporalAggregator(min_confidence=0.5)
        assert agg.add("7", 0.9) is True
        assert agg.add("1", 0.2) is False      # unter der Schwelle
        result = agg.result()
        assert result.value == "7"
        assert result.rejected == 1

    def test_none_wird_verworfen(self):
        """Ein unlesbares Feld ist keine Messung, sondern ihr Fehlen."""
        agg = TemporalAggregator()
        assert agg.add(None, 0.9) is False
        assert agg.result().value is None

    def test_ohne_messung_kein_ergebnis(self):
        assert TemporalAggregator().result().value is None


class TestFlackernAusDemAuftrag:
    def test_beispiel_aus_paragraph_8(self):
        """Frame 1 -> 7, Frame 2 -> unlesbar, Frame 3 -> 7, Frame 4 -> Mischbild.
        Erwartet: 7 mit hoher Confidence."""
        agg = TemporalAggregator(min_confidence=0.5)
        agg.add("7", 0.91, 1)
        agg.add(None, 0.12, 2)
        agg.add("7", 0.88, 3)
        agg.add("1", 0.34, 4)          # unter min_confidence -> verworfen

        result = agg.result()
        assert result.value == "7"
        assert result.confidence > 0.8
        assert result.rejected == 2

    def test_eine_klare_messung_schlaegt_zwei_unsichere(self):
        """Gewichtet wird nach Confidence, nicht nach blosser Haeufigkeit."""
        agg = TemporalAggregator(min_confidence=0.4)
        agg.add("8", 0.99, 1)
        agg.add("3", 0.45, 2)
        agg.add("3", 0.42, 3)
        assert agg.result().value == "8"


class TestUneindeutigkeit:
    def test_patt_ergibt_kein_ergebnis(self):
        """Lieber kein Wert als ein geratener."""
        agg = TemporalAggregator(min_confidence=0.5, min_agreement=0.6)
        agg.add("3", 0.8, 1)
        agg.add("8", 0.8, 2)
        result = agg.result()
        assert result.value is None
        assert not result.is_decided

    def test_uneinigkeit_senkt_die_confidence(self):
        einig = TemporalAggregator(min_confidence=0.5)
        for _ in range(4):
            einig.add("5", 0.9)

        uneinig = TemporalAggregator(min_confidence=0.5, min_agreement=0.4)
        for _ in range(3):
            uneinig.add("5", 0.9)
        uneinig.add("6", 0.9)

        assert uneinig.result().confidence < einig.result().confidence

    def test_systematischer_fehler_wird_nicht_geheilt(self):
        """WICHTIG (am Material beobachtet): Aggregation hilft gegen ZUFAELLIGE
        Fehler. Liest der Detektor konstant falsch -- gemessen 25 von 25 Frames
        "4" statt "9" --, bestaetigt die Aggregation den Fehler nur.
        Dieser Test haelt diese Grenze bewusst fest."""
        agg = TemporalAggregator(min_confidence=0.5)
        for frame in range(25):
            agg.add("4", 0.8, frame)      # konstant falsch
        result = agg.result()
        assert result.value == "4"
        assert result.confidence > 0.7, (
            "Die Aggregation kann einen systematischen Fehler nicht erkennen -- "
            "dagegen hilft nur ein besserer Detektor"
        )


class TestMindestanzahl:
    def test_zu_wenige_messungen(self):
        agg = TemporalAggregator(min_confidence=0.5, min_votes=3)
        agg.add("7", 0.9)
        agg.add("7", 0.9)
        assert agg.result().value is None

    def test_genug_messungen(self):
        agg = TemporalAggregator(min_confidence=0.5, min_votes=3)
        for _ in range(3):
            agg.add("7", 0.9)
        assert agg.result().value == "7"


class TestNachvollziehbarkeit:
    def test_erklaerung_nennt_die_stimmen(self):
        agg = TemporalAggregator(min_confidence=0.5)
        agg.add("7", 0.9, 10)
        agg.add("7", 0.8, 11)
        agg.add("1", 0.6, 12)
        text = agg.result().explain()
        assert "7" in text and "Einigkeit" in text

    def test_alle_stimmen_bleiben_erhalten(self):
        """Fuer die Evidence des Wurfs -- nicht nur das Endergebnis zaehlt."""
        agg = TemporalAggregator(min_confidence=0.5)
        agg.add("7", 0.9, 10)
        agg.add("1", 0.7, 11)
        result = agg.result()
        assert len(result.votes) == 2
        assert result.votes[0].frame_index == 10

    def test_reset(self):
        agg = TemporalAggregator()
        agg.add("7", 0.9)
        agg.reset()
        assert agg.vote_count == 0
        assert agg.result().value is None


class TestZahlenwerte:
    def test_funktioniert_auch_mit_ganzzahlen(self):
        agg = TemporalAggregator(min_confidence=0.5)
        for _ in range(3):
            agg.add(63, 0.9)
        assert agg.result().value == 63
