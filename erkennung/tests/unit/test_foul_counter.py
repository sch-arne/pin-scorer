"""Tests des Fehlwurfzaehlers -- besonders seiner Plausibilitaetsgrenze.

Der Zaehler ist die einzige Quelle fuer einen Wurf, bei dem kein Kegel faellt:
Solche Wuerfe erzeugen keinen Gruenzyklus und waeren sonst unsichtbar. Genau
deshalb darf er nicht jeden Messwert glauben.

GEMESSEN ueber den vollen Spieltag 2026-08-29 (1731 Wuerfe, 4 Bahnen) -- alle
Anstiege des Zaehlers nach Sprunghoehe:

    Bahn 2   +1: 1
    Bahn 3   keine
    Bahn 4   +1: 1,  +3: 14      <-- 14 Spruenge um drei, alle auf EINER Bahn
    Bahn 5   +1: 2

Jeder Dreiersprung buchte drei Nullwuerfe; zusammen 42 erfundene Wuerfe. Bahn 4
zaehlte dadurch 463 Wuerfe bei nur 426 Gruenzyklen, und Spieler Cs
Satz fiel auf 11 von 30 Treffern.

BILDBELEG (Frame 270290, Bahn 4): Die Tafel zeigt `00`, gelesen wurde `03`.
Das Protokoll kennt auf 720 Wuerfen genau ZWEI Nullwuerfe.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration, LaneCalibration, Roi
from kegel_cv.config.schema import AppConfig
from kegel_cv.detection.digit_detector import DigitReading
from kegel_cv.video.source import Frame

BREITE, HOEHE = 320, 240


def _lane() -> LaneCalibration:
    rois = [Roi(name="green_lamp", rect=(0.45, 0.60, 0.10, 0.08))]
    for i in range(1, 10):
        spalte, zeile = (i - 1) % 3, (i - 1) // 3
        rois.append(Roi(name=f"pin_lamp_{i}", pin_number=i,
                        rect=(0.20 + spalte * 0.25, 0.20 + zeile * 0.15,
                              0.08, 0.08)))
    for name, stellen, y in (("throw_number", 3, 0.90),
                             ("pin_count", 1, 0.90),
                             ("total_b", 4, 0.95),
                             ("left_display", 2, 0.80)):
        for k in range(1, stellen + 1):
            rois.append(Roi(name=f"digit_{name}_{k}",
                            rect=(0.05 + k * 0.08, y, 0.06, 0.03)))
    return LaneCalibration(lane_id=1, real_lane_number=4,
                           quad=[[10, 10], [310, 10], [310, 230], [10, 230]],
                           rois=rois)


class Zaehler:
    """Ersetzt die Ziffernerkennung fuer das Fehlwurffeld (zwei Stellen)."""

    def __init__(self) -> None:
        self.wert: int | None = 0

    def read_field(self, patches):
        if self.wert is None:
            return DigitReading(text="??", value=None, confidence=0.0)
        return DigitReading(text=str(self.wert), value=self.wert,
                            confidence=1.0)


@pytest.fixture
def prozessor():
    cfg = AppConfig()
    cal = Calibration()
    cal.set_lane(_lane())
    p = LaneProcessor(cal.lanes[0], cfg)
    assert p.prepare((HOEHE, BREITE, 3))
    return p


def _lesen(p: LaneProcessor, wie_oft: int, ab_frame: int = 0) -> int:
    """Laesst den Zaehler `wie_oft` mal lesen. Gibt den naechsten Frame zurueck."""
    bild = np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)
    takt = p.cfg.detection.digits.foul_read_interval
    f = ab_frame
    for _ in range(wie_oft):
        p._pruefe_fehlwurfzaehler(Frame(index=f, timestamp=f / 25.0, image=bild))
        f += takt
    return f


class TestEchterNullwurf:
    def test_anstieg_um_eins_meldet_einen_wurf(self, prozessor):
        zaehler = Zaehler()
        prozessor.digit_reader = zaehler

        f = _lesen(prozessor, 8)              # Stand 0 einpendeln
        zaehler.wert = 1
        _lesen(prozessor, 8, f)

        assert len(prozessor.take_zero_throws()) == 1

    def test_ruecksetzung_ist_kein_wurf(self, prozessor):
        """Beim Spielwechsel setzt die Anlage den Zaehler mit allem zurueck."""
        zaehler = Zaehler()
        prozessor.digit_reader = zaehler

        f = _lesen(prozessor, 8)
        zaehler.wert = 1
        f = _lesen(prozessor, 8, f)
        prozessor.take_zero_throws()
        zaehler.wert = 0
        _lesen(prozessor, 8, f)

        assert prozessor.take_zero_throws() == []

    def test_unlesbares_feld_meldet_nichts(self, prozessor):
        zaehler = Zaehler()
        prozessor.digit_reader = zaehler
        zaehler.wert = None

        _lesen(prozessor, 20)

        assert prozessor.take_zero_throws() == []


class TestSprungIstFehllesung:
    """Der Kern: Ein Sprung um mehr als eins kann kein Wurf sein.

    Gelesen wird alle 10 Frames, ein Wurfzyklus dauert 216 bis 338 Frames --
    zwischen zwei Lesungen liegt also hoechstens EIN Wurf.
    """

    def test_sprung_um_drei_bucht_keinen_wurf(self, prozessor):
        zaehler = Zaehler()
        prozessor.digit_reader = zaehler

        f = _lesen(prozessor, 8)
        zaehler.wert = 3                      # der gemessene Stoerwert
        _lesen(prozessor, 8, f)

        assert prozessor.take_zero_throws() == [], (
            "Ein Sprung 0 -> 3 buchte drei Wuerfe. Ueber den Spieltag waren "
            "das 42 erfundene Wuerfe auf Bahn 4"
        )

    def test_der_stoerwert_wird_nicht_zum_bezugspunkt(self, prozessor):
        """Sonst gilt der Ruecksprung auf den richtigen Wert als Spielwechsel
        -- und der naechste ECHTE Nullwurf danach faellt aus."""
        zaehler = Zaehler()
        prozessor.digit_reader = zaehler

        f = _lesen(prozessor, 8)
        zaehler.wert = 3
        f = _lesen(prozessor, 8, f)
        zaehler.wert = 0                      # die Tafel zeigte die ganze Zeit 0
        f = _lesen(prozessor, 8, f)
        prozessor.take_zero_throws()

        zaehler.wert = 1                      # ein echter Nullwurf
        _lesen(prozessor, 8, f)

        assert len(prozessor.take_zero_throws()) == 1, (
            "Nach einer verworfenen Fehllesung muss der naechste echte "
            "Nullwurf wieder zaehlen"
        )

    def test_grenze_ist_einstellbar(self):
        cfg = AppConfig()
        cfg.detection.digits.foul_max_rise = 3
        cal = Calibration()
        cal.set_lane(_lane())
        p = LaneProcessor(cal.lanes[0], cfg)
        assert p.prepare((HOEHE, BREITE, 3))
        zaehler = Zaehler()
        p.digit_reader = zaehler

        f = _lesen(p, 8)
        zaehler.wert = 3
        _lesen(p, 8, f)

        assert len(p.take_zero_throws()) == 3
