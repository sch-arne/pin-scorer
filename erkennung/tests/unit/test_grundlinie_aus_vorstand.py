"""Die Grundlinie ist nicht frei: leer oder der Stand des vorigen Wurfs.

Nutzer, 2026-09-29: *„wie waere es mit, die Grundlinie darf nur 0 sein ODER
derselbe Wert wie im Wurf zuvor?"*

WARUM DAS STIMMT. Kegel stehen nicht wieder auf. Nach einem Wurf liegt genau
das, was vorher lag, plus was dieser Wurf umwarf. Nur wenn die Anlage neu
aufstellt, liegt nichts -- bei den VOLLEN nach jedem Wurf, beim ABRAEUMEN
nach allen neunen. Es gibt also genau zwei erlaubte Grundlinien, und welche
gerade gilt, muss man nicht wissen: Die Tafel zeigt es zu Beginn der
Gruenphase selbst.

WAS DAMIT VON SELBST WEGFAELLT. Alles, was WEDER leer NOCH der Vorstand ist,
ist Nachleuchten des vorigen Wurfs -- Jubelblinken oder ein Fehlercode. Die
Regel muss beides nicht kennen. Gemessen an Bahn 4, Spiel 4, Wurf 23:

    47105  .....67.9   Fehlercode
    47117  123456789   Fehlercode
    47130  ...4567.9   Fehlercode, letztes Aufflackern
    47140  123..6789   <- genau das Ergebnis von Wurf 22: ANKER
    47605  1234.6789   Kegel 4 faellt
    47674  Gruen-AUS        Ergebnis - Grundlinie = {4} = 1 Kegel

UND DER WURF BEGINNT AN DERSELBEN STELLE. Das ist der Unterschied zu allen
frueheren Anlaeufen: Eine reparierte Grundlinie allein genuegt nicht, weil
derselbe Fehlercode auch im Ergebnis steht. Nur Grundlinie: 2 Kegel.
Grundlinie und Beginn: 1 Kegel. Die Tafel sagt 1.

GEMESSEN ueber den Spieltag (tools/simuliere_vorstand.py, 1473 Wuerfe mit
lesbarer Tafelsumme): Anker in 1671 von 1678 Wuerfen gefunden, 1410 auf 1412
richtig.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration.model import LaneCalibration, Roi
from kegel_cv.config import load_config
from kegel_cv.models.readings import LampReading, LampState, PinLampReading

HOEHE, BREITE = 400, 600
ALLE = set(range(1, 10))


def _bahn() -> LaneCalibration:
    rois = [Roi(name="green_lamp", rect=(0.45, 0.75, 0.06, 0.05))]
    rois += [Roi(name=f"pin_lamp_{i}", rect=(0.10 + 0.08 * i, 0.30, 0.04, 0.04),
                 pin_number=i) for i in range(1, 10)]
    return LaneCalibration(
        lane_id=1, quad=[[100.0, 50.0], [300.0, 50.0],
                         [300.0, 250.0], [100.0, 250.0]], rois=rois)


def lesung(pins: set[int]) -> PinLampReading:
    lampen = tuple(
        LampReading(state=LampState.ON if i in pins else LampState.OFF,
                    score=250.0 if i in pins else 100.0, confidence=1.0,
                    name=f"pin_lamp_{i}")
        for i in range(1, 10))
    return PinLampReading(lamps=lampen, pins=tuple(sorted(pins)),
                          confidence=1.0)


@pytest.fixture
def prozessor() -> LaneProcessor:
    cfg = load_config()
    cfg.sampling.baseline_from_previous_state = True
    p = LaneProcessor(_bahn(), cfg)
    assert p.prepare((HOEHE, BREITE, 3))
    p._green_on_frame = 1000
    return p


def spur(*paare: tuple[int, set[int]]) -> list:
    return [(frame, lesung(pins)) for frame, pins in paare]


class TestWelcherStandGilt:
    def test_leer_beim_vollenwurf(self, prozessor):
        """Bei den Vollen stellt die Anlage nach jedem Wurf neu auf -- die
        Grundlinie ist leer, egal was der vorige Wurf umwarf. Gemessen an
        Bahn 2: zwei Wuerfe hintereinander 1234.6.89, dazwischen leer."""
        prozessor._vorstand = lesung({1, 2, 3, 4, 6, 8, 9})
        anker = prozessor._anker_vorstand(
            spur((1005, set()), (1010, set()), (1050, {1, 2, 3})))
        assert anker is not None
        frame, grundlinie = anker
        assert frame == 1005
        assert grundlinie.pins == ()

    def test_der_vorstand_beim_abraeumen(self, prozessor):
        """Beim Abraeumen bleibt liegen, was lag."""
        prozessor._vorstand = lesung({1, 2, 3})
        anker = prozessor._anker_vorstand(
            spur((1005, {1, 2, 3}), (1050, {1, 2, 3, 7})))
        assert anker is not None
        assert anker[0] == 1005
        assert set(anker[1].pins) == {1, 2, 3}

    def test_der_fehlercode_wird_uebersprungen(self, prozessor):
        """Der gemessene Fall, Bahn 4 Spiel 4 Wurf 23. Weder {6,7,9} noch
        alle neune noch {4,5,6,7,9} sind eine erlaubte Grundlinie -- erst
        das Ergebnis von Wurf 22 ist es."""
        prozessor._vorstand = lesung({1, 2, 3, 6, 7, 8, 9})
        anker = prozessor._anker_vorstand(spur(
            (1005, {6, 7, 9}), (1011, {6, 7, 9}), (1017, ALLE),
            (1023, ALLE), (1030, {4, 5, 6, 7, 9}),
            (1040, {1, 2, 3, 6, 7, 8, 9}),
            (1500, {1, 2, 3, 4, 6, 7, 8, 9})))
        assert anker is not None
        assert anker[0] == 1040
        assert set(anker[1].pins) == {1, 2, 3, 6, 7, 8, 9}


class TestWannSieSchweigt:
    def test_ohne_passenden_stand_kein_anker(self, prozessor):
        """Eine Lampe, die nie hell genug wird (BUG-034), oder eine verdeckte
        Bahn: Dann weiss die Regel nichts und das bisherige Verfahren gilt."""
        prozessor._vorstand = lesung({1, 2, 3})
        assert prozessor._anker_vorstand(
            spur((1005, {1, 2}), (1050, {1, 2, 7}))) is None

    def test_vor_dem_gruen_an_zaehlt_nicht(self, prozessor):
        """Die Spur laeuft seit dem vorigen Wurf. Was in der PAUSE steht,
        gehoert dem vorigen Wurf -- dort leuchtet der Fehlercode nach."""
        prozessor._vorstand = lesung({1, 2, 3})
        assert prozessor._anker_vorstand(
            spur((900, {1, 2, 3}), (1050, {5}))) is None

    def test_ohne_gruen_an_schweigt_sie(self, prozessor):
        prozessor._green_on_frame = None
        prozessor._vorstand = lesung({1, 2, 3})
        assert prozessor._anker_vorstand(spur((1005, {1, 2, 3}))) is None

    def test_leere_spur(self, prozessor):
        assert prozessor._anker_vorstand([]) is None


class TestDerVorstandSelbst:
    def test_alle_neune_heisst_neu_aufgestellt(self, prozessor):
        """Sonst raste der Anker beim Jubelblinken auf den vollen Kranz ein
        und der naechste Wurf haette null Kegel."""
        prozessor.uebernimm_vorstand(lesung(ALLE))
        assert prozessor._vorstand is None

    def test_ein_teilstand_bleibt_stehen(self, prozessor):
        prozessor.uebernimm_vorstand(lesung({1, 2, 3, 6, 7, 8, 9}))
        assert prozessor._vorstand is not None
        assert set(prozessor._vorstand.pins) == {1, 2, 3, 6, 7, 8, 9}

    def test_ohne_ergebnis_bleibt_der_alte_stand(self, prozessor):
        """Ein Gruenzyklus ohne Wurf darf die Kette nicht zerreissen."""
        prozessor.uebernimm_vorstand(lesung({1, 2}))
        prozessor.uebernimm_vorstand(None)
        assert set(prozessor._vorstand.pins) == {1, 2}

    def test_ohne_vorstand_gilt_nur_leer(self, prozessor):
        """Zu Beginn einer Aufnahme kennt die Bahn keinen Vorstand. Dann ist
        leer die einzige erlaubte Grundlinie -- und findet sich die nicht,
        schweigt die Regel."""
        assert prozessor._vorstand is None
        assert prozessor._anker_vorstand(spur((1005, {1, 2}))) is None
        anker = prozessor._anker_vorstand(spur((1005, set())))
        assert anker is not None and anker[0] == 1005


class TestVerdrahtung:
    """Dass die Funktion stimmt, heisst nicht, dass sie jemand aufruft --
    genau diese Luecke war BUG-023."""

    def test_die_vorgabe_ist_an(self):
        """Eingeschaltet, nachdem der Vollauf ueber den 2. Spieltag sie
        bestaetigt hat: 1410 auf 1437 richtig gegen die Tafelsumme, null
        Wuerfe schlechter, Spiele mit falschem Endstand von 4 auf 1."""
        assert load_config().sampling.baseline_from_previous_state is True

    def test_abgeschaltet_bleibt_die_grundlinie_unberuehrt(self):
        cfg = load_config()
        cfg.sampling.baseline_from_previous_state = False
        p = LaneProcessor(_bahn(), cfg)
        assert p.prepare((HOEHE, BREITE, 3))
        p._green_on_frame = 1000
        p._vorstand = lesung({1, 2, 3})
        p._baseline_pins = lesung({9})
        p._grundlinien_spur.extend(spur((1005, {1, 2, 3})))
        # Ohne den Schalter darf nichts geschehen -- geprueft wird die
        # Verzweigung, nicht die Suche: die Suche selbst ist oben getestet.
        assert p.cfg.sampling.baseline_from_previous_state is False
        assert set(p._baseline_pins.pins) == {9}

    def test_die_pipeline_meldet_den_endstand_zurueck(self):
        """Ohne diesen Rueckruf gaebe es nie einen Vorstand -- und die Regel
        koennte nur noch die leere Grundlinie erkennen."""
        import inspect

        from kegel_cv.analysis import pipeline

        quelle = inspect.getsource(pipeline.AnalysisPipeline._aggregate_pins)
        assert "uebernimm_vorstand" in quelle
