"""Was nach Gruen-AUS blinkt: Jubel behalten, Fehlercode verwerfen.

Nach Gruen-AUS faellt kein Kegel mehr -- das hat der Nutzer von Anfang an so
erklaert, und es stimmt. Das ABLESEN ist dort aber nicht fertig, und genau
daran ist ein erster Versuch gescheitert.

DER FEHLVERSUCH (2026-09-28). Nutzer: *„sobald Grünaus geht, müssen wir
fertig sein mit unserer Zählung."* Also die Lampen bei Gruen-AUS abschneiden.
GEMESSEN ueber die ersten 42 Minuten des Spieltags:

    alt   318 Wuerfe, 220 von 225 richtig   97,8 %
    neu   315 Wuerfe, 209 von 222 richtig   94,1 %

    11 Wuerfe veraendert -- 0 besser, 9 schlechter, jedes Mal ZU NIEDRIG
    (9 -> 1, 8 -> 1, 9 -> 3)

Der Grund: Bei „alle Neune" und beim 8er Kranz blinkt die Anzeige, und oft
waren es die Frames nach Gruen-AUS, die eine Lampe ueberhaupt einmal
leuchtend erwischten.

IM SELBEN ZEITRAUM liegt aber auch der Fehlercode der Tafel (BUG-036,
gemessen sieben Frames nach Gruen-AUS). Beide sind nur an ihrer FORM zu
trennen:

    Jubel        alles, was leuchtet, blinkt -- keine Lampe steht fest
    Fehlercode   ein Teil leuchtet fest, der andere blinkt

Am Material: Bahn 4, Spiel 4, wo der Nutzer den Code an der Tafel ablas.

    Wurf 22   alt 9 Kegel   jetzt 7   Tafel sagt 7
    Wurf 23   alt 9 Kegel   jetzt 1   Tafel sagt 1
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.frame_sampler import SampledFrame, SampleEvent
from kegel_cv.analysis.pipeline import AnalysisPipeline
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi
from kegel_cv.config import load_config
from kegel_cv.models.readings import (LampReading, LampState, PinLampReading,
                                      ist_fehlercode)
from kegel_cv.models.throw import FrameRole
from kegel_cv.video.source import Frame

HOEHE, BREITE = 400, 600
GRUEN_AUS = 1000
ALLE = set(range(1, 10))
KRANZ = ALLE - {5}


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


class TestDasMusterAllein:
    """`ist_fehlercode` ohne Pipeline -- die Regel selbst."""

    def test_fest_und_blinkend_zugleich(self):
        """Der gemessene Code auf Bahn 4: 6,7,9 fest, der Rest blinkt."""
        folge = [lesung({6, 7, 9}), lesung(ALLE), lesung({6, 7, 9}),
                 lesung(ALLE), lesung({6, 7, 9})]
        assert ist_fehlercode(folge)

    def test_alle_neune_blinken_ist_kein_fehlercode(self):
        folge = [lesung(ALLE), lesung(set()), lesung(ALLE), lesung(set()),
                 lesung(ALLE)]
        assert not ist_fehlercode(folge)

    def test_der_8er_kranz_auch_nicht(self):
        """Die 5 ist AUS, nicht dauerleuchtend -- vom Nutzer ausdruecklich
        richtiggestellt. Waere sie dauerleuchtend, saehe der Kranz wie ein
        Fehlercode aus und die Regel waere wertlos."""
        folge = [lesung(KRANZ), lesung(set()), lesung(KRANZ), lesung(set()),
                 lesung(KRANZ)]
        assert not ist_fehlercode(folge)

    def test_ein_ruhiges_ergebnis_ist_kein_fehlercode(self):
        folge = [lesung({1, 2, 3})] * 5
        assert not ist_fehlercode(folge)

    def test_ein_einzelnes_aus_reicht_nicht(self):
        """Bahn 5 Kegel 8 liest sich regelmaessig als aus, obwohl sie
        leuchtet (BUG-034). Sie darf kein Dauerblinker werden."""
        folge = [lesung({1, 2, 3, 8}), lesung({1, 2, 3}), lesung({1, 2, 3, 8}),
                 lesung({1, 2, 3, 8}), lesung({1, 2, 3, 8})]
        assert not ist_fehlercode(folge)

    def test_zu_wenige_messungen_entscheiden_nichts(self):
        assert not ist_fehlercode([lesung({6, 7, 9}), lesung(ALLE)])


class TestEineEinzelneLampeIstKeinMuster:
    """Nutzer, 2026-09-29: *„es gab nur 2 Fehlercodes im ganzen Spiel und
    meines Wissens nach alle auf Bahn 4."*

    Gezaehlt wurden ueber denselben Spieltag fuenf. Die vier ueberzaehligen
    lagen alle auf Bahn 5, und alle vier waren Kegel 8, die binnen zwei
    Sekunden ZWEIMAL flackerte -- damit reicht das Zaehlen von Dunkelphasen
    allein nicht mehr aus, das es gegen BUG-034 schuetzen sollte.
    """

    def test_zweimal_flackern_ist_noch_kein_code(self):
        """Der gemessene Fehlalarm auf Bahn 5 bei Gruen-AUS 32120."""
        folge = [lesung(ALLE), lesung(ALLE - {8}), lesung(ALLE),
                 lesung(ALLE - {8}), lesung(ALLE - {8})]
        assert not ist_fehlercode(folge)
        # Mit der alten Schwelle war genau das der Fehlalarm.
        assert ist_fehlercode(folge, mindest_blinkende=1)

    def test_beide_echten_codes_bleiben_erkannt(self):
        """Fall 1: 6,7,9 fest. Fall 2: 6,7,8,9 fest. Beide mit mehreren
        blinkenden Lampen -- ein Code ist ein Muster, kein Wackelkontakt."""
        eins = [lesung({6, 7, 9}), lesung(ALLE), lesung({6, 7, 9}),
                lesung(ALLE), lesung({6, 7, 9})]
        zwei = [lesung({6, 7, 8, 9}), lesung(ALLE), lesung({6, 7, 8, 9}),
                lesung(ALLE), lesung({6, 7, 8, 9})]
        assert ist_fehlercode(eins)
        assert ist_fehlercode(zwei)

    def test_die_vorgabe_verlangt_zwei(self):
        from kegel_cv.config import load_config
        assert load_config().sampling.error_code_min_blinking_lamps == 2


def bild() -> np.ndarray:
    return np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)


class Prozessor:
    """Ein Prozessor, dessen Lampenlesung vom Frame abhaengt."""

    def __init__(self, nach: list[set[int]], bis: set[int]) -> None:
        self.lane = _bahn()
        self.display_number = 4
        self._nach = nach
        self._bis = bis
        self.result_samples = [lesung(bis)]
        # Der echte Prozessor sammelt die Live-Messungen nach Gruen-AUS hier;
        # die Pipeline entscheidet ueber sie gemeinsam mit den Abtastframes.
        self.nach_samples: list[PinLampReading] = []
        self.result_pins = lesung(bis)
        # Der Endstand ist die Grundlinie des naechsten Wurfs; die Pipeline
        # meldet ihn hierher zurueck.
        self.vorstand: PinLampReading | None = None

    def uebernimm_vorstand(self, ergebnis: PinLampReading | None) -> None:
        self.vorstand = ergebnis

    def read_pin_lamps_at(self, frame: Frame) -> PinLampReading:
        if frame.index <= GRUEN_AUS:
            return lesung(self._bis)
        i = min((frame.index - GRUEN_AUS) // 5, len(self._nach) - 1)
        return lesung(self._nach[i])


def ereignis() -> SampleEvent:
    e = SampleEvent(lane_id=1, event_id=1, trigger_frame=GRUEN_AUS,
                    trigger_timestamp=GRUEN_AUS / 20.0, pending_offsets=[])
    for versatz, rolle in ((0, FrameRole.GREEN_OFF), (5, FrameRole.SAMPLE),
                           (10, FrameRole.SAMPLE), (15, FrameRole.SAMPLE),
                           (20, FrameRole.SAMPLE), (25, FrameRole.SAMPLE)):
        nummer = GRUEN_AUS + versatz
        e.frames.append(SampledFrame(
            frame=Frame(index=nummer, timestamp=nummer / 20.0, image=bild()),
            offset=versatz, role=rolle))
    return e


@pytest.fixture
def pipeline() -> AnalysisPipeline:
    return AnalysisPipeline(Calibration(name="test", lanes=[_bahn()]),
                            load_config())


class TestInDerPipeline:
    def test_fehlercode_zaehlt_nicht_zum_wurf(self, pipeline):
        """Der Fall Bahn 4: bei Gruen-AUS liegen sieben, danach meldet die
        Tafel eine Stoerung mit allen neun."""
        p = Prozessor(nach=[{6, 7, 9}, ALLE, {6, 7, 9}, ALLE, {6, 7, 9},
                            {6, 7, 9}],
                      bis={1, 2, 3, 6, 7, 8, 9})
        ergebnis = pipeline._aggregate_pins(p, ereignis())
        assert set(ergebnis.pins) == {1, 2, 3, 6, 7, 8, 9}

    def test_jubel_zaehlt_sehr_wohl(self, pipeline):
        """DER FALL, DEN DER HARTE SCHNITT KAPUTT MACHTE. Bei Gruen-AUS ist
        die Anzeige gerade dunkel; ohne die Frames danach waere der Neuner
        eine Null."""
        p = Prozessor(nach=[set(), ALLE, set(), ALLE, set(), ALLE],
                      bis=set())
        ergebnis = pipeline._aggregate_pins(p, ereignis())
        assert set(ergebnis.pins) == ALLE

    def test_ruhiges_nachspiel_zaehlt_auch(self, pipeline):
        p = Prozessor(nach=[{1, 2, 3}] * 6, bis={1, 2})
        ergebnis = pipeline._aggregate_pins(p, ereignis())
        assert set(ergebnis.pins) == {1, 2, 3}
