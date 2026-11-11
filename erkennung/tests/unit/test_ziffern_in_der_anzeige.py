"""Was der Ziffernleser gerade liest, steht im Bahnpanel.

WOFUER -- Wunsch des Nutzers am 2026-09-11:

    "Wir geben unten ja immer den aktuellen Wurf aus etc. ich haette gerne,
     dass dort auch steht, was er gerade an Ziffern erkannt hat. Also welche
     Werte angeblich wo stehen. Das wuerde mir helfen bei der Evaluierung, ob
     wir die Ziffern bald wieder reinnehmen, oder nicht."

DIE EIGENSCHAFT, DIE HIER VOR ALLEM GEPRUEFT WIRD: Diese Lesungen gehen in
KEINE Zaehlung. Die Ziffern sind aus der Wertung genommen (nur Bahn, Kegelzahl,
Kegelnummern und Zeitstempel werden gesendet, Entscheidung vom 2026-08-26) --
eine Anzeige, die sie stillschweigend wieder einspeist, wuerde genau die Frage
verwischen, die der Nutzer beantworten will.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kegel_cv.analysis.lane_processor import LaneProcessor            # noqa: E402
from kegel_cv.calibration.model import LaneCalibration, Roi           # noqa: E402
from kegel_cv.config import load_config                               # noqa: E402
from kegel_cv.detection.digit_detector import DigitReading            # noqa: E402
from kegel_cv.gui.lane_panel import (ANZEIGEFELDER, LEER_ANZEIGE,     # noqa: E402
                                     anzeige_zeile)
from kegel_cv.video.source import Frame                               # noqa: E402


def bahn() -> LaneCalibration:
    rois = [Roi(name="green_lamp", rect=(0.45, 0.75, 0.06, 0.05))]
    rois += [Roi(name=f"pin_lamp_{i}", rect=(0.10 + 0.08 * i, 0.30, 0.04, 0.04),
                 pin_number=i) for i in range(1, 10)]
    rois += [Roi(name="throw_number", rect=(0.15, 0.85, 0.20, 0.10))]
    rois += [Roi(name=f"digit_throw_number_{i}",
                 rect=(0.16 + 0.06 * i, 0.86, 0.05, 0.08)) for i in range(1, 4)]
    return LaneCalibration(
        lane_id=1, quad=[[100.0, 50.0], [300.0, 50.0],
                         [300.0, 250.0], [100.0, 250.0]], rois=rois)


def frame(index: int = 0) -> Frame:
    return Frame(index=index, timestamp=index / 25,
                 image=np.full((720, 1280, 3), 60, dtype=np.uint8))


@pytest.fixture
def prozessor():
    p = LaneProcessor(bahn(), load_config())
    p.prepare((720, 1280, 3))
    return p


# --------------------------------------------------------------- Die Zeile

class TestDieZeile:
    def test_ohne_lesung_steht_ein_strich(self):
        assert anzeige_zeile({}) == LEER_ANZEIGE

    def test_der_wert_steht_drin(self):
        zeile = anzeige_zeile(
            {"throw_number": DigitReading(text="012", value=12, confidence=0.9)})
        assert "012" in zeile and "Wurf" in zeile

    def test_unsicheres_wird_abgesetzt(self):
        """Eine unsichere Lesung ist die interessanteste Auskunft fuer den,
        der den Leser beurteilen will -- sie wird grau gezeigt, nicht
        verschwiegen."""
        sicher = anzeige_zeile(
            {"total_b": DigitReading(text="0063", value=63, confidence=0.9)})
        unsicher = anzeige_zeile(
            {"total_b": DigitReading(text="00?3", value=None, confidence=0.2)})
        assert "#ddd" in sicher
        assert "#ddd" not in unsicher and "00?3" in unsicher

    def test_die_reihenfolge_folgt_der_tafel(self):
        """Wer vergleicht, schaut abwechselnd auf Bild und Zeile -- dann muss
        dieselbe Zahl an derselben Stelle stehen."""
        namen = [n for n, _ in ANZEIGEFELDER]
        assert namen.index("throw_number") < namen.index("pin_count")
        assert namen.index("pin_count") < namen.index("total_b")
        # Der Fehlwurfzaehler steht oben links, also vor der unteren Zeile.
        assert namen.index("left_display") < namen.index("throw_number")

    def test_summenfeld_a_wird_nicht_mehr_gezeigt(self):
        """Nutzer 2026-09-14: "summe_a ist irgendwie Quatsch fuer uns." Es hat
        als einziges Feld keine Ziffernzellen kalibriert, geht in keine
        Pruefung ein und wird seither auch nicht mehr gelesen."""
        assert "total_a" not in [n for n, _ in ANZEIGEFELDER]

    def test_ein_unbekanntes_feld_stoert_nicht(self):
        zeile = anzeige_zeile({"gibt_es_nicht": DigitReading(
            text="9", value=9, confidence=0.9)})
        assert zeile == LEER_ANZEIGE


# ------------------------------------------------------- Der Weg zur Anzeige

class TestDieLesungKommtAn:
    def test_am_anfang_ist_nichts_da(self, prozessor):
        assert prozessor._observation(prozessor.green_detector.detect(
            np.zeros((4, 4, 3), np.uint8))).digits == {}

    def test_nach_dem_takt_steht_etwas_drin(self, prozessor):
        prozessor._lies_anzeige_live(frame())
        beobachtung = prozessor._observation(
            prozessor.green_detector.detect(np.zeros((4, 4, 3), np.uint8)))
        assert "throw_number" in beobachtung.digits

    def test_die_beobachtung_haelt_eine_kopie(self, prozessor):
        """Sonst zeigt die Oberflaeche einen Stand, der sich unter ihr
        weiterbewegt."""
        prozessor._lies_anzeige_live(frame())
        beobachtung = prozessor._observation(
            prozessor.green_detector.detect(np.zeros((4, 4, 3), np.uint8)))
        prozessor._live_digits.clear()
        assert beobachtung.digits, "die Kopie muss stehenbleiben"

    def test_abschaltbar(self):
        cfg = load_config()
        cfg.detection.digits.live_read_interval = 0
        p = LaneProcessor(bahn(), cfg)
        p.prepare((720, 1280, 3))
        for i in range(60):
            p.process(frame(i), None)
        assert p._live_digits == {}


class TestDieBahnenLesenVersetzt:
    """GEMESSEN 4,25 ms je Bahn und Lesung. Alle vier im selben Frame waeren
    17 ms auf einmal -- bei 29 ms Grundlast und 40 ms Budget ein verlorener
    Frame."""

    def test_zwei_bahnen_treffen_nicht_denselben_frame(self):
        cfg = load_config()
        takt = cfg.detection.digits.live_read_interval
        treffer = {}
        for lane_id in (1, 2, 3, 4):
            treffer[lane_id] = {i for i in range(takt * 3)
                                if (i - lane_id) % takt == 0}
        for a in (1, 2, 3, 4):
            for b in (1, 2, 3, 4):
                if a < b:
                    assert not (treffer[a] & treffer[b]), \
                        f"Bahn {a} und {b} lesen im selben Frame"

    def test_jede_bahn_kommt_trotzdem_dran(self):
        cfg = load_config()
        takt = cfg.detection.digits.live_read_interval
        for lane_id in (1, 2, 3, 4):
            assert any((i - lane_id) % takt == 0 for i in range(takt))


class TestKeineRueckwirkung:
    """Die wichtigste Eigenschaft: Diese Werte zaehlen nicht mit."""

    def test_die_anzeige_ruehrt_den_wurfzaehler_nicht_an(self, prozessor):
        vorher = (prozessor.throw_count, prozessor.running_total)
        prozessor._lies_anzeige_live(frame())
        assert (prozessor.throw_count, prozessor.running_total) == vorher

    def test_die_anzeige_ruehrt_die_spaeten_felder_nicht_an(self, prozessor):
        """`_late_samples` traegt die Werte, die in die Auswertung eingehen --
        die Anzeige darf dort nichts hineinschreiben."""
        prozessor._lies_anzeige_live(frame())
        assert not prozessor._late_samples

    def test_die_anzeige_ruehrt_den_fehlwurfzaehler_nicht_an(self, prozessor):
        vorher = dict(getattr(prozessor, "_foul_history", {}) or {})
        prozessor._lies_anzeige_live(frame())
        assert dict(getattr(prozessor, "_foul_history", {}) or {}) == vorher
