"""Tests der Zustandsmaschine.

Der wichtigste Teil des Projekts: Aus einem verrauschten Signalstrom muss genau
EIN Ereignis je Wurf entstehen -- nicht keines, nicht zwei.
"""

from __future__ import annotations

import pytest

from kegel_cv.config.schema import StateMachineConfig
from kegel_cv.detection.state_machine import (
    EventType,
    LaneState,
    LaneStateMachine,
)
from kegel_cv.models.readings import LampReading, LampState

FPS = 25.0


def reading(state: LampState, score: float = 0.0) -> LampReading:
    return LampReading(state=state, score=score, confidence=0.9, name="green_lamp")


ON = reading(LampState.ON, 70.0)
OFF = reading(LampState.OFF, 20.0)
UNKNOWN = reading(LampState.UNKNOWN, 40.0)


@pytest.fixture
def machine() -> LaneStateMachine:
    return LaneStateMachine(lane_id=1, cfg=StateMachineConfig(), min_stable_frames=3)


def feed(machine: LaneStateMachine, value: LampReading, count: int,
         start_frame: int = 0) -> list:
    """Fuettert dieselbe Messung mehrfach und liefert die ausgeloesten Ereignisse."""
    events = []
    for i in range(count):
        frame = start_frame + i
        event = machine.update(value, frame, frame / FPS)
        if event is not None:
            events.append(event)
    return events


class TestStabilitaet:
    def test_ein_einzelner_frame_loest_nichts_aus(self, machine):
        """min_stable_frames=3 -- zwei Frames duerfen nicht reichen."""
        assert feed(machine, ON, 2) == []
        assert machine.state is LaneState.READY

    def test_dritter_frame_loest_aus(self, machine):
        events = feed(machine, ON, 3)
        assert len(events) == 1
        assert events[0].event is EventType.GREEN_ON

    def test_einzelner_stoerframe_kippt_zustand_nicht(self, machine):
        """Der Kernschutz gegen Flackern: ein Ausreisser setzt die Zaehlung
        zurueck, statt den Zustand zu wechseln."""
        feed(machine, ON, 5)
        assert machine.state is LaneState.GREEN_ON

        machine.update(OFF, 10, 10 / FPS)          # ein einzelner Stoerframe
        assert machine.state is LaneState.GREEN_ON, "Ein Frame darf nichts kippen"

        feed(machine, ON, 3, start_frame=11)
        assert machine.state is LaneState.GREEN_ON

    def test_unknown_veraendert_den_zustand_nicht(self, machine):
        """Werte in der Hysteresezone sind bewusst unentschieden -- sie duerfen
        weder den Zustand wechseln noch die Zaehlung zuruecksetzen."""
        feed(machine, ON, 5)
        state_before = machine.state

        feed(machine, UNKNOWN, 10, start_frame=10)
        assert machine.state is state_before


class TestGruenZyklus:
    def test_vollstaendiger_zyklus(self, machine):
        feed(machine, ON, 4)
        assert machine.state is LaneState.GREEN_ON

        events = feed(machine, OFF, 4, start_frame=10)
        assert len(events) == 1
        assert events[0].event is EventType.GREEN_OFF
        assert machine.state is LaneState.GREEN_OFF
        assert machine.green_off_frame == 12

    def test_green_off_ohne_vorheriges_green_on_wird_verworfen(self, machine):
        """Q8: Eine unbespielte Bahn zeigt einen alten Spielstand. Startet die
        Analyse dort, darf daraus kein Wurf entstehen."""
        events = feed(machine, OFF, 10)
        assert events == [], "Ohne vorheriges GREEN_ON darf kein Ereignis entstehen"
        assert machine.state is LaneState.READY

    def test_dauerhaft_gruen_an_erzeugt_genau_ein_ereignis(self, machine):
        """Eine Bahn, auf der nicht gespielt wird, erzeugt keine Phantomwuerfe."""
        events = feed(machine, ON, 200)
        assert len(events) == 1
        assert events[0].event is EventType.GREEN_ON


class TestDoubleCounting:
    def test_ein_wurf_ergibt_genau_ein_ereignis(self, machine):
        """Ein Wurf ist ueber viele Frames sichtbar -- daraus darf nur EIN
        THROW_CONFIRMED entstehen."""
        feed(machine, ON, 5)
        feed(machine, OFF, 5, start_frame=10)

        confirmed = machine.confirm_throw(20, 20 / FPS)
        assert confirmed is not None
        assert machine.state is LaneState.WAIT_FOR_NEXT_GREEN

        # Weitere OFF-Frames desselben Wurfs
        assert feed(machine, OFF, 40, start_frame=21) == []

        # Ein zweiter Buchungsversuch im Sperrzustand greift nicht
        assert machine.confirm_throw(30, 30 / FPS) is None

    def test_naechster_wurf_erst_nach_erneutem_gruen(self, machine):
        feed(machine, ON, 5)
        feed(machine, OFF, 5, start_frame=10)
        machine.confirm_throw(20, 20 / FPS)

        # Gruen geht wieder an -> Sperre faellt
        events = feed(machine, ON, 4, start_frame=60)
        assert any(e.event is EventType.GREEN_ON for e in events)
        assert machine.state is LaneState.GREEN_ON

        events = feed(machine, OFF, 4, start_frame=100)
        assert len(events) == 1
        assert events[0].event is EventType.GREEN_OFF

    def test_zu_schneller_folgewurf_wird_verworfen(self, machine):
        """min_frames_between_throws: Ein physisch unmoeglicher Folgewurf
        ist eine Fehlerkennung (Auftrag Paragraph 22)."""
        machine.cfg = StateMachineConfig(min_frames_between_throws=50)

        feed(machine, ON, 5)
        feed(machine, OFF, 5, start_frame=10)
        machine.confirm_throw(20, 20 / FPS)

        feed(machine, ON, 4, start_frame=25)
        events = feed(machine, OFF, 4, start_frame=30)   # nur 10 Frames spaeter
        assert events == [], "Folgewurf nach 10 Frames muss verworfen werden"


class TestTimeouts:
    def test_analyzing_faellt_nach_timeout_zurueck(self, machine):
        """Ohne Timeout bliebe die Bahn nach einer Fehlerkennung fuer immer
        haengen -- alle weiteren Wuerfe wuerden fehlen."""
        machine.cfg = StateMachineConfig(analyzing_timeout_s=1.0)
        feed(machine, ON, 5)
        feed(machine, OFF, 5, start_frame=10)
        machine.mark_analyzing(20, 20 / FPS)
        assert machine.state is LaneState.ANALYZING

        event = machine.update(UNKNOWN, 200, 200 / FPS)   # 8 s spaeter
        assert event is not None
        assert event.event is EventType.TIMEOUT
        assert machine.state is LaneState.READY

    def test_langes_warten_auf_gruen_ist_kein_fehler(self, machine):
        """'Spieler werfen lange nicht' ist regulaer (Auftrag Paragraph 22)."""
        machine.cfg = StateMachineConfig(wait_green_timeout_s=300.0)
        feed(machine, ON, 5)
        feed(machine, OFF, 5, start_frame=10)
        machine.confirm_throw(20, 20 / FPS)

        event = machine.update(UNKNOWN, 2000, 80.0)       # 80 s Pause
        assert event is None
        assert machine.state is LaneState.WAIT_FOR_NEXT_GREEN


class TestBahnUnabhaengigkeit:
    def test_bahnen_beeinflussen_sich_nicht(self):
        """Prinzip P6 -- der schwerwiegendste denkbare Architekturfehler."""
        machines = {n: LaneStateMachine(lane_id=n, cfg=StateMachineConfig(),
                                        min_stable_frames=3)
                    for n in range(1, 5)}

        feed(machines[1], ON, 5)
        feed(machines[1], OFF, 5, start_frame=10)

        assert machines[1].state is LaneState.GREEN_OFF
        for n in (2, 3, 4):
            assert machines[n].state is LaneState.READY
            assert machines[n].green_off_frame is None

    def test_reset_setzt_alles_zurueck(self, machine):
        feed(machine, ON, 5)
        feed(machine, OFF, 5, start_frame=10)
        machine.confirm_throw(20, 20 / FPS)

        machine.reset()
        assert machine.state is LaneState.READY
        assert machine.green_state is LampState.UNKNOWN
        assert machine.green_off_frame is None


class TestEreignisbeschreibung:
    def test_beschreibung_nennt_bahn_zustand_und_frame(self, machine):
        events = feed(machine, ON, 3)
        text = events[0].describe()
        assert "Bahn 1" in text
        assert "GREEN_ON" in text
        assert "Frame 2" in text
