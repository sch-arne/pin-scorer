"""Der Breakpoint: die Wurfnummer trennt Grundlinie und Ergebnis.

Nutzer, 2026-09-28: *„wenn die Wurfnummer hochzählt, beginnen die 4 sek. sonst
nehmen wir das als Breakpoint und davor ist Grundlinie und danach bis Grün aus
ist Ergebnis."*

WARUM DAS BESSER IST ALS EIN ZEITFENSTER. Bisher haengt die Grundlinie an
festen Frameversaetzen nach dem Gruen-AN. Gemessen ueber den Spieltag:

  * Zwischen Gruen-AN und dem ersten fallenden Kegel liegen beim Raeumen im
    Median 84 Frames, p05 nur 38 -- ein festes Fenster passt dort nicht.
  * Ein Fehlercode leuchtet nach dem Gruen-AN noch rund zwei Sekunden nach
    und faellt damit mitten ins Grundlinienfenster (BUG-036).
  * Gruen-AUS wird auf Bahn 5 in jedem sechsten Wurf ueber eine Sekunde zu
    spaet erklaert -- ein rueckwaerts gemessenes Zeitfenster verrutscht damit.

Die Wurfnummer hat diese Probleme nicht. Gemessen ueber 100 Gruenzyklen aller
vier Bahnen: in 100 % der Zyklen lesbar, der Sprung in 88 bis 96 % zu sehen,
und er liegt 3,95 bis 4,35 s vor Gruen-AUS.

WAS HIER GEPRUEFT WIRD, ist vor allem, dass der Breakpoint SCHWEIGT, wo er
nichts weiss -- dann gilt unveraendert das bisherige Verfahren.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration.model import LaneCalibration, Roi
from kegel_cv.config import load_config

HOEHE, BREITE = 400, 600


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
    # AUSDRUECKLICH EINSCHALTEN. Die Vorgabe ist aus -- am ganzen Spieltag
    # gemessen kostete der Breakpoint zwanzig Wuerfe, siehe
    # `config/default.yaml`. Die Mechanik soll trotzdem gepflegt und
    # geprueft bleiben, damit sie wieder eingeschaltet werden kann.
    cfg.sampling.breakpoint_from_throw_number = True
    p = LaneProcessor(_bahn(), cfg)
    assert p.prepare((HOEHE, BREITE, 3))
    p._green_on_frame = 1000
    return p


def test_die_vorgabe_ist_aus():
    """Gemessen ueber den ganzen Spieltag: 65,8 % auf 64,0 %, zwanzig Wuerfe
    verloren, dreimal so viele verworfene Zyklen. Die Physik stimmt -- die
    Nummer springt immer zuerst --, aber nur um sechs Frames, und die Guete
    des Ziffernfeldes bricht genau im Sprungmoment ein."""
    assert load_config().sampling.breakpoint_from_throw_number is False


class TestWoDerSchnittLiegt:
    def test_der_sprung_um_eins_ist_der_schnitt(self, prozessor):
        prozessor._nummer_spur.extend(
            [(1000, 17), (1005, 17), (1010, 18), (1015, 18)])
        assert prozessor._breakpoint() == 1010

    def test_bei_zwei_spruengen_gilt_der_LETZTE(self, prozessor):
        """Ein Fehlwurf schaltet Gruen nicht aus (BUG-035) -- dann zaehlt die
        Tafel innerhalb EINER Gruenphase zweimal hoch. Gemessen am 2. Spieltag
        fuenfmal, einmal ueber 683 Frames von 026 auf 028. Das Ergebnis am
        Ende der Phase gehoert dem spaeteren Wurf."""
        prozessor._nummer_spur.extend(
            [(1000, 26), (1010, 27), (1020, 27), (1030, 28), (1040, 28)])
        assert prozessor._breakpoint() == 1030

    def test_nur_was_in_der_gruenphase_liegt(self, prozessor):
        """Die Spur laeuft seit dem vorigen Wurf und enthaelt auch die Pause.
        Ein Sprung von DAVOR gehoert zum vorigen Wurf."""
        prozessor._nummer_spur.extend(
            [(900, 16), (910, 17), (1005, 17), (1010, 17)])
        assert prozessor._breakpoint() is None


class TestWannErSchweigt:
    def test_ohne_sprung_kein_schnitt(self, prozessor):
        prozessor._nummer_spur.extend([(1000, 17), (1005, 17), (1010, 17)])
        assert prozessor._breakpoint() is None

    def test_ein_sprung_um_zwei_ist_kein_schnitt(self, prozessor):
        """Da fehlt eine Lesung oder ein Wurf. Raten waere schlimmer als
        schweigen -- dann gilt das bisherige Verfahren."""
        prozessor._nummer_spur.extend([(1000, 17), (1010, 19)])
        assert prozessor._breakpoint() is None

    def test_ein_rueckfall_ist_kein_schnitt(self, prozessor):
        """Beim Spielwechsel faellt die Nummer von 30 auf 1."""
        prozessor._nummer_spur.extend([(1000, 30), (1010, 1), (1020, 1)])
        assert prozessor._breakpoint() is None

    def test_leere_spur(self, prozessor):
        assert prozessor._breakpoint() is None

    def test_abgeschaltet_schweigt_immer(self, prozessor):
        prozessor.cfg.sampling.breakpoint_from_throw_number = False
        prozessor._nummer_spur.extend([(1000, 17), (1010, 18)])
        assert prozessor._breakpoint() is None


class TestVerdrahtung:
    """Dass die Funktion stimmt, heisst nicht, dass sie jemand aufruft --
    genau diese Luecke war BUG-023."""

    def test_die_spuren_tragen_ihren_frame(self, prozessor):
        """Ohne Framenummer laesst sich an keinem Schnitt trennen. Die Spur
        hielt frueher nur die Messung."""
        from kegel_cv.video.source import Frame

        takt = prozessor._live_interval
        assert takt > 0
        bild = np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)
        for i in range(0, takt * 4 + 1):
            prozessor.process(Frame(index=i, timestamp=i / 25.0, image=bild))
        assert prozessor._grundlinien_spur, "ohne Spur kein Schnitt"
        for eintrag in prozessor._grundlinien_spur:
            assert isinstance(eintrag, tuple) and len(eintrag) == 2
            assert isinstance(eintrag[0], int)

    def test_die_wurfnummer_wird_mitgeschrieben(self, prozessor):
        """Gemessen: 1,99 ms fuer alle vier Bahnen, weniger als die neun
        Lampen daneben. Ohne diesen Aufruf gaebe es nie einen Breakpoint."""
        from kegel_cv.video.source import Frame

        # Gelesen wird nur, WAEHREND Gruen an ist -- in der Pause springt
        # keine Wurfnummer, und das Lesen kostete dort nur Rechenzeit.
        prozessor._green_on_frame = 0
        prozessor._window_open = False
        gelesen = []
        echt = prozessor.read_digits

        def merken(frame, felder=None):
            gelesen.append(felder)
            return echt(frame, felder)

        prozessor.read_digits = merken
        bild = np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)
        for i in range(0, prozessor._live_interval * 3 + 1):
            prozessor.process(Frame(index=i, timestamp=i / 25.0, image=bild))
        knapp = [f for f in gelesen if f == ("throw_number",)]
        assert len(knapp) >= prozessor._live_interval * 3, (
            f"Die Wurfnummer muss JEDEN Frame mitgelesen werden, gelesen "
            f"wurde sie {len(knapp)}-mal")
        # Der volle Satz kostet das Siebenfache (14,70 gegen 1,99 ms) und darf
        # NICHT im Live-Takt mitlaufen. Er hat einen eigenen, viel groeberen
        # Takt: die Nullzustandspruefung alle
        # `scoring.game_reset_check_interval` Frames.
        voll = [f for f in gelesen if f is None]
        erlaubt = len(range(0, prozessor._live_interval * 3 + 1,
                            prozessor.cfg.scoring.game_reset_check_interval))
        assert len(voll) <= erlaubt, (
            f"{len(voll)} volle Ziffernsaetze bei hoechstens {erlaubt} "
            f"erlaubten -- der volle Satz laeuft im Live-Takt mit")


class TestNurEinFeldLesen:
    def test_felder_schraenkt_ein(self, prozessor):
        from kegel_cv.video.source import Frame

        bild = np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)
        rahmen = Frame(index=0, timestamp=0.0, image=bild)
        alle = prozessor.read_digits(rahmen)
        eins = prozessor.read_digits(rahmen, felder=("throw_number",))
        assert set(eins) <= {"throw_number"}
        assert len(alle) >= len(eins)
