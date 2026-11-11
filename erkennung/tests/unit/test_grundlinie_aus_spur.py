"""Die Grundlinie kommt aus der laufenden Messung, nicht aus einem Fenster.

BUG-031. Bis hierher wurde die Grundlinie -- wie viele Kegel vor dem Wurf schon
lagen -- in genau einem Fenster von 25 Frames nach dem ERKANNTEN Grün-AN
gemessen. Trifft dieses Fenster den falschen Augenblick, ist die gebuchte
Kegelzahl falsch, und zwar dauerhaft: Sie verschwindet in einer Subtraktion.

An einem Spieltag geschah das dreimal, jedes Mal aus einem anderen Grund --
Fenster kürzer als die Grünphase, Fenster 87 Sekunden vor dem Wurf, Bahn
währenddessen verdeckt. Die Grünzeiten waren also nie die Ursache, sie
entschieden nur, WELCHER falsche Augenblick getroffen wurde.

Die Antwort stand jedes Mal in Messungen, die ohnehin anfallen. Genau die
prüfen diese Tests.
"""

from __future__ import annotations

from collections import deque

import numpy as np
import pytest

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration.model import LaneCalibration, Roi
from kegel_cv.config import load_config
from kegel_cv.models.readings import (LampReading, LampState, PinLampReading,
                                      grundlinie_aus_spur)

HOEHE, BREITE = 720, 1280


def messung(pins: set[int]) -> PinLampReading:
    lampen = tuple(
        LampReading(name=f"pin_lamp_{i}",
                    state=LampState.ON if i in pins else LampState.OFF,
                    score=250.0 if i in pins else 150.0, confidence=1.0)
        for i in range(1, 10))
    return PinLampReading(lamps=lampen, pins=tuple(sorted(pins)),
                          confidence=1.0)


class TestGrundlinieAusGruppen:
    """Der kleinste Stand, aber ueber BLINKFESTE Gruppen.

    Die Lampen blinken mit 28-30 Frames Periode, die Dunkelphase dauert bis zu
    15 Frames (BUG-007a). Je `gruppe` aufeinanderfolgende Messungen werden
    darum zusammengefasst -- eine Lampe gilt als AN, wenn sie in mindestens
    einer leuchtete -- und erst diese Gruppen werden verglichen.
    """

    def test_raeumwurf_findet_die_liegenden_kegel(self):
        """Beim Räumen bleiben die alten Lampen an -- der kleinste Stand seit
        dem vorigen Wurf IST die Grundlinie."""
        spur = ([messung({1, 2, 3, 4, 6, 8, 9})] * 8
                + [messung(set(range(1, 10)))] * 8)
        assert grundlinie_aus_spur(spur, 8).pins == (1, 2, 3, 4, 6, 8, 9)

    def test_nach_dem_neuaufstellen_ist_sie_leer(self):
        """Der Fall Bahn 5 F60871: Die Anlage stellte während einer 87 Sekunden
        langen Grünphase neu auf. Das Fenster sah davon nichts, die Spur schon."""
        spur = ([messung({1, 2, 3, 6, 7, 8, 9})] * 8      # Ergebnis des Vorwurfs
                + [messung(set())] * 8                    # neu aufgestellt
                + [messung(set(range(1, 10)))] * 8)       # alle neune
        assert grundlinie_aus_spur(spur, 8).pins == ()

    def test_eine_dunkelphase_erfindet_keine_grundlinie(self):
        """DER REGRESSIONSTEST ZU BUG-031 (2026-09-18).

        Der erste Anlauf verlangte drei GLEICHE Messungen hintereinander --
        geeicht an der `lampenspur.csv` mit Takt 25 (also 75 Frames), gebaut
        fuer den Lesetakt 5 (also 15 Frames, exakt die maximale Dunkelphase).
        Der Spieltagslauf verlor dadurch zwei zuvor richtige Wuerfe:
        Bahn 4 F180292 (2 statt 9) und F198502 (1 statt 8).

        Hier steht genau dieses Muster: drei dunkle Messungen mitten in einer
        Strecke, auf der sieben Kegel liegen.
        """
        spur = ([messung({1, 2, 3, 4, 6, 8, 9})] * 5
                + [messung(set())] * 3                    # Dunkelphase
                + [messung({1, 2, 3, 4, 6, 8, 9})] * 5)
        assert grundlinie_aus_spur(spur, 8).pins == (1, 2, 3, 4, 6, 8, 9), (
            "Eine Dunkelphase des Blinkens darf keine leere Grundlinie ergeben"
        )

    def test_zu_kleine_gruppe_faellt_darauf_herein(self):
        """Die Gegenprobe -- sonst waere nicht belegt, dass die Gruppengroesse
        ueberhaupt etwas tut. Genau so verhielt sich der erste Anlauf."""
        spur = ([messung({1, 2, 3, 4, 6, 8, 9})] * 5
                + [messung(set())] * 3
                + [messung({1, 2, 3, 4, 6, 8, 9})] * 5)
        assert grundlinie_aus_spur(spur, 3).pins == ()

    def test_nimmt_auch_eine_deque(self):
        """DER REGRESSIONSTEST ZUM SPIELTAG 2026-09-19.

        Der Aufrufer reicht eine `deque` herein (`_grundlinien_spur`), und die
        laesst sich nicht schneiden -- `messungen[i:i+gruppe]` warf TypeError.
        Der Aufruf stand in der GREEN_OFF-Behandlung VOR dem Zuruecksetzen der
        Ergebnisliste; P8 fing die Ausnahme auf, also lief die Bahn weiter --
        mit der Ergebnisliste des vorigen Wurfs. Jeder Wurf erbte danach das
        Raeumbild mit allen neun Lampen.

        Ueber den Spieltag: 628 von 1248 Wuerfen mit lesbarer Ziffer falsch,
        46 von 46 Spielenden zu hoch (+20 bis +55).
        """
        spur = deque([messung({1, 2, 3, 4, 6, 8, 9})] * 8
                     + [messung(set(range(1, 10)))] * 8, maxlen=600)
        assert grundlinie_aus_spur(spur, 8).pins == (1, 2, 3, 4, 6, 8, 9)

    def test_zu_kurze_spur_schweigt(self):
        """Lieber der alte Weg als eine geratene Grundlinie."""
        assert grundlinie_aus_spur([messung({1, 2})], 8) is None
        assert grundlinie_aus_spur([], 8) is None

    def test_eine_lampe_gilt_als_an_wenn_sie_einmal_leuchtete(self):
        """Innerhalb einer Gruppe wird VEREINIGT, nicht gemittelt.

        Eine Lampe kann waehrend einer Dunkelphase faelschlich aus erscheinen,
        aber nie faelschlich an -- dieselbe Begruendung wie in
        `aggregate_pin_readings`."""
        spur = [messung({1, 2}), messung({3}), messung({1, 2}), messung({3})]
        assert grundlinie_aus_spur(spur, 4).pins == (1, 2, 3)

    def test_der_kleinste_gewinnt_auch_spaet(self):
        """Die Reihenfolge darf nicht entscheiden."""
        spur = ([messung({1, 2, 3})] * 8 + [messung(set())] * 8
                + [messung({1, 2, 3, 4, 5})] * 8)
        assert grundlinie_aus_spur(spur, 8).pins == ()


def _bahn() -> LaneCalibration:
    rois = [Roi(name="green_lamp", rect=(0.45, 0.75, 0.06, 0.05))]
    rois += [Roi(name=f"pin_lamp_{i}", rect=(0.10 + 0.08 * i, 0.30, 0.04, 0.04),
                 pin_number=i) for i in range(1, 10)]
    return LaneCalibration(
        lane_id=1, quad=[[100.0, 50.0], [300.0, 50.0],
                         [300.0, 250.0], [100.0, 250.0]], rois=rois)


@pytest.fixture
def prozessor() -> LaneProcessor:
    cfg = load_config()
    p = LaneProcessor(_bahn(), cfg)
    assert p.prepare((HOEHE, BREITE, 3))
    return p


class TestVerdrahtung:
    """Dass die Funktion stimmt, heisst nicht, dass sie jemand aufruft.

    Genau diese Lücke war BUG-023: gebaut, committet, getestet -- und nie
    ausgeführt.
    """

    def test_die_laufende_messung_landet_in_der_spur(self, prozessor):
        from kegel_cv.video.source import Frame

        takt = prozessor._live_interval
        assert takt > 0, "ohne Live-Takt gäbe es die Spur gar nicht"
        bild = np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)
        vorher = len(prozessor._grundlinien_spur)
        for i in range(0, takt * 4 + 1):
            prozessor.process(Frame(index=i, timestamp=i / 25.0, image=bild))
        assert len(prozessor._grundlinien_spur) > vorher, (
            "Die Messungen für die Anzeige müssen in der Grundlinienspur "
            "aufgehoben werden -- sonst ist die ganze Reparatur wirkungslos"
        )

    def test_die_gruppe_deckt_eine_blinkperiode_ab(self, prozessor):
        """Die Gruppengroesse muss sich aus dem LESETAKT ergeben, nicht aus
        einer Zahl, die irgendwo geeicht wurde (BUG-031)."""
        takt = max(1, prozessor._live_interval)
        fenster = prozessor.cfg.sampling.baseline_trace_window_frames
        gruppe = max(2, -(-fenster // takt))
        assert gruppe * takt >= 30, (
            f"Gruppe {gruppe} x Takt {takt} = {gruppe * takt} Frames deckt "
            f"keine Blinkperiode (28-30 Frames) ab"
        )

    def test_konfiguration_ist_vorhanden_und_an(self, prozessor):
        """Ein Schalter, den niemand kennt, ist keiner."""
        assert prozessor.cfg.sampling.baseline_from_trace is True
        assert prozessor.cfg.sampling.baseline_trace_window_frames >= 30, (
            "Das Fenster muss laenger sein als eine Blinkperiode (28-30 "
            "Frames) -- sonst erfindet eine Dunkelphase eine leere "
            "Grundlinie (BUG-031)"
        )
