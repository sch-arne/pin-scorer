"""Tests des Wurf-Datenmodells und seiner Nachvollziehbarkeit."""

from __future__ import annotations

import pytest

from kegel_cv.models.throw import (
    Evidence,
    FrameRef,
    FrameRole,
    PlausibilityCheck,
    ThrowResult,
    ThrowStatus,
)


def make_throw(**kwargs) -> ThrowResult:
    defaults = dict(
        lane=1, throw_number=7, throw_number_in_series=7,
        pins=(1, 3, 5, 6, 8), pins_count=5, displayed_pin_count=5,
        status=ThrowStatus.VALID, running_total=42, confidence=0.94,
        timestamp=123.42, source_frame=3702,
    )
    defaults.update(kwargs)
    return ThrowResult(**defaults)


class TestThrowStatus:
    @pytest.mark.parametrize("status,expected", [
        (ThrowStatus.VALID, True),
        (ThrowStatus.EMPTY, True),      # 0 Kegel ist ein regulaerer Wurf
        (ThrowStatus.INVALID, False),
        (ThrowStatus.ERROR, False),
        (ThrowStatus.UNKNOWN, False),
    ])
    def test_gewertete_wuerfe(self, status, expected):
        assert status.is_valid_throw is expected

    def test_leerwurf_ist_gueltig(self):
        """Ein Wurf mit 0 Kegeln ist fachlich korrekt und zaehlt mit."""
        throw = make_throw(status=ThrowStatus.EMPTY, pins=(), pins_count=0,
                           displayed_pin_count=0)
        assert throw.valid is True
        assert throw.pins_count == 0


class TestBitmap:
    def test_pins_bitmap(self):
        assert make_throw(pins=(1, 3, 5, 6, 8)).pins_bitmap == 0b010110101
        assert make_throw(pins=()).pins_bitmap == 0
        assert make_throw(pins=tuple(range(1, 10))).pins_bitmap == 511


class TestQuellenabgleich:
    def test_uebereinstimmung(self):
        assert make_throw(pins_count=5, displayed_pin_count=5).sources_agree is True

    def test_widerspruch(self):
        assert make_throw(pins_count=5, displayed_pin_count=4).sources_agree is False

    def test_fehlende_zweite_quelle_ist_kein_widerspruch(self):
        """Eine fehlende Ziffer ist etwas anderes als eine widersprechende."""
        assert make_throw(displayed_pin_count=None).sources_agree is True


class TestSerialisierung:
    def test_to_dict_enthaelt_alle_pflichtfelder(self):
        data = make_throw().to_dict()
        for key in ("lane", "throw_number", "pins", "pins_count", "pins_bitmap",
                    "displayed_pin_count", "valid", "status", "running_total",
                    "confidence", "timestamp", "source_frame", "evidence"):
            assert key in data, f"Feld {key} fehlt"

    def test_status_wird_als_text_serialisiert(self):
        assert make_throw().to_dict()["status"] == "VALID"


class TestEvidence:
    def test_erklaerung_enthaelt_frames_und_entscheidungen(self):
        """Auftrag Paragraph 27: Das Ergebnis muss sich selbst erklaeren koennen."""
        evidence = Evidence(
            frames=(
                FrameRef(4580, 184.23, FrameRole.GREEN_OFF),
                FrameRef(4583, 184.35, FrameRole.SAMPLE),
            ),
            green_scores=(21.4, 20.9),
            checks=(
                PlausibilityCheck("Lampen == Ziffer", 5, 5, True),
                PlausibilityCheck("Summe", 42, 42, True),
            ),
            decisions=("GREEN_OFF bei t=184.23 (3 Frames bestaetigt)",),
        )
        text = make_throw(evidence=evidence).explain()

        assert "Wurf 7" in text
        assert "4580" in text
        assert "GREEN_OFF" in text
        assert "Lampen == Ziffer" in text
        assert "VALID" in text

    def test_fehlgeschlagene_pruefung_wird_als_abweichung_ausgewiesen(self):
        check = PlausibilityCheck("Lampen == Ziffer", 5, 4, False)
        assert "ABWEICHUNG" in check.describe()

    def test_leere_evidence_ist_zulaessig(self):
        """Ein Wurf ohne Beweiskette darf erzeugt werden -- er ist nur unvollstaendig,
        nicht ungueltig."""
        assert make_throw().evidence.to_dict()["frames"] == []


class TestUnveraenderlichkeit:
    def test_wurf_kann_nicht_mutiert_werden(self):
        """Ein Wurf wird nicht nachtraeglich geaendert; bei einer Korrektur
        entsteht ein neues Objekt."""
        throw = make_throw()
        with pytest.raises(Exception):
            throw.pins_count = 9  # type: ignore[misc]
