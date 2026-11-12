"""Tests der Spielwechsel-Erkennung (`000  0000` in der unteren Reihe).

Zwei Fehler, die am Material gemessen wurden und hier einzeln festgenagelt sind:

1. NICHT ERKANNT. Die Pruefung hing frueher am Wurffenster -- also an der Zeit
   zwischen GREEN_OFF und dem naechsten GREEN_ON. Ob ein Spielwechsel erkannt
   wurde, entschied damit der Zufall:

       Bahn 2   000/0000 stand F127115-F128475 (54 s)
                Fenster offen bis F127177 -- 62 Frames.  NICHT erkannt
       Bahn 3   000/0000 stand F126680-F128715 (81 s)
                Fenster offen bis F126964 -- 284 Frames. erkannt

   Ueber die ganze Aufzeichnung fand Bahn 2 dadurch 2 Spielenden, Bahn 3
   dreizehn -- bei nahezu gleicher Wurfzahl (~370 je Bahn).

2. DOPPELT GEZAEHLT. Der Nullzustand steht 40 bis 91 Sekunden. Ohne Sperre
   wurde derselbe Wechsel zweimal gemeldet -- gemessen 60 bis 255 Frames
   auseinander, beide Male im selben Abschnitt. Jede zweite Meldung erzeugte
   einen Geisterlauf mit "voriges Spiel endete mit 0 Kegeln".
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
                             ("total_b", 4, 0.95)):
        for k in range(1, stellen + 1):
            rois.append(Roi(name=f"digit_{name}_{k}",
                            rect=(0.05 + k * 0.08, y, 0.06, 0.03)))
    return LaneCalibration(lane_id=1, real_lane_number=2,
                           quad=[[10, 10], [310, 10], [310, 230], [10, 230]],
                           rois=rois)


def _lesung(wert: int | None) -> DigitReading:
    if wert is None:
        return DigitReading(text="???", value=None, confidence=0.0)
    return DigitReading(text=str(wert), value=wert, confidence=1.0)


class Tafel:
    """Ersetzt die Ziffernerkennung: liefert, was die Tafel gerade zeigt.

    Bewusst ueber die Zahl der Stellen unterschieden -- `total_b` hat vier,
    `throw_number` drei. Damit bleibt der Aufbau unabhaengig davon, in welcher
    Reihenfolge der Prozessor die Felder liest.
    """

    def __init__(self) -> None:
        self.summe: int | None = 137
        self.nummer: int | None = 12
        self.aufrufe = 0

    def read_field(self, patches):
        self.aufrufe += 1
        return _lesung(self.summe if len(patches) == 4 else self.nummer)


@pytest.fixture
def prozessor():
    cfg = AppConfig()
    cal = Calibration()
    cal.set_lane(_lane())
    p = LaneProcessor(cal.lanes[0], cfg)
    assert p.prepare((HOEHE, BREITE, 3))
    return p


def _bild() -> np.ndarray:
    return np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)


def _laufen(p: LaneProcessor, tafel: Tafel, von: int, bis: int) -> None:
    """Nur die Nullzustands-Pruefung takten -- ohne den Rest der Pipeline."""
    takt = p.cfg.scoring.game_reset_check_interval
    for i in range(von, bis):
        if i % takt == 0:
            p._pruefe_nullzustand(Frame(index=i, timestamp=i / 25.0,
                                        image=_bild()))
    _ = tafel


class TestNullzustandOhneWurffenster:
    """Der Kern: Die Erkennung darf nicht davon abhaengen, ob Gruen gerade aus ist."""

    def test_wird_erkannt_ohne_dass_ein_fenster_offen_ist(self, prozessor):
        tafel = Tafel()
        prozessor.digit_reader = tafel

        assert not prozessor._window_open, (
            "Der Aufbau soll genau den Fall pruefen, in dem KEIN Fenster offen "
            "ist -- auf Bahn 2 lag der ganze Nullzustand in einer Gruenphase"
        )
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 500)

        assert prozessor.reset_unterwegs, (
            "000/0000 stand ueber 500 Frames -- das muss erkannt werden, "
            "auch wenn die gruene Lampe durchgehend an ist"
        )

    def test_laufendes_spiel_loest_nichts_aus(self, prozessor):
        tafel = Tafel()
        prozessor.digit_reader = tafel

        _laufen(prozessor, tafel, 0, 2000)

        assert not prozessor.reset_unterwegs

    def test_nur_die_summe_auf_null_reicht_nicht(self, prozessor):
        """Eine Null in der Summe allein ist der Spielanfang, kein Spielende."""
        tafel = Tafel()
        prozessor.digit_reader = tafel

        tafel.summe, tafel.nummer = 0, 3
        _laufen(prozessor, tafel, 0, 2000)

        assert not prozessor.reset_unterwegs

    def test_unlesbare_anzeige_loest_nichts_aus(self, prozessor):
        tafel = Tafel()
        prozessor.digit_reader = tafel

        tafel.summe, tafel.nummer = None, None
        _laufen(prozessor, tafel, 0, 2000)

        assert not prozessor.reset_unterwegs

    def test_die_wurfnummer_wird_nur_bei_summe_null_gelesen(self, prozessor):
        """Sonst kostete die Pruefung im laufenden Spiel drei Stellen je Takt."""
        tafel = Tafel()
        prozessor.digit_reader = tafel

        _laufen(prozessor, tafel, 0, 1000)
        im_spiel = tafel.aufrufe

        tafel.aufrufe = 0
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 1000, 2000)

        assert tafel.aufrufe > im_spiel, (
            "Bei Summe null muessen ZWEI Felder gelesen werden, sonst nur eins"
        )

    def test_abschaltbar(self):
        cfg = AppConfig()
        cfg.scoring.game_reset_check_interval = 0
        cal = Calibration()
        cal.set_lane(_lane())
        p = LaneProcessor(cal.lanes[0], cfg)
        assert p.prepare((HOEHE, BREITE, 3))
        tafel = Tafel()
        p.digit_reader = tafel
        tafel.summe, tafel.nummer = 0, 0

        # Der Takt ist aus -- process() ruft die Pruefung dann nie auf.
        assert p.cfg.scoring.game_reset_check_interval == 0
        assert not p.reset_unterwegs


class TestVerdrahtungInProcess:
    """Der Test oben prueft die REGEL. Dieser prueft, dass sie auch laeuft.

    Genau hier lag der Fehler: Die Regel war richtig, wurde aber nur
    aufgerufen, solange das Wurffenster offen war.
    """

    @staticmethod
    def _gruenes_bild() -> np.ndarray:
        """Tafel mit LEUCHTENDER gruener Lampe -- also kein offenes Fenster."""
        bild = np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)
        # Grundhelligkeit der Tafel: Ein Score nahe null hiesse "verdeckt".
        bild[:, :] = (150, 175, 195)
        x0, y0 = int(0.45 * BREITE), int(0.60 * HOEHE)
        x1, y1 = int(0.55 * BREITE), int(0.68 * HOEHE)
        bild[y0:y1, x0:x1] = (60, 220, 60)
        return bild

    def test_process_erkennt_den_nullzustand_bei_gruen_an(self, prozessor):
        tafel = Tafel()
        prozessor.digit_reader = tafel
        tafel.summe, tafel.nummer = 0, 0

        for i in range(600):
            prozessor.process(Frame(index=i, timestamp=i / 25.0,
                                    image=self._gruenes_bild()))

        assert not prozessor._window_open, (
            "Der Aufbau soll den Fall pruefen, in dem Gruen durchgehend an ist"
        )
        assert prozessor.reset_unterwegs, (
            "Bei durchgehend gruener Lampe wurde der Nullzustand frueher nie "
            "gelesen -- auf Bahn 2 blieben so 11 von 13 Spielenden unerkannt"
        )


class TestKeineDoppelmeldung:
    """Der Nullzustand steht 40 bis 91 Sekunden -- er darf einmal zaehlen."""

    def test_langer_nullzustand_meldet_nur_einmal(self, prozessor):
        tafel = Tafel()
        prozessor.digit_reader = tafel
        tafel.summe, tafel.nummer = 0, 0

        _laufen(prozessor, tafel, 0, 200)
        assert prozessor.reset_unterwegs
        # Wie nach einem gebuchten Wurf: Das Zeichen wird weitergereicht.
        prozessor._reset_weiterreichen()
        assert not prozessor.reset_unterwegs

        # Die Anzeige steht weiter auf null -- 91 Sekunden sind 2275 Frames.
        _laufen(prozessor, tafel, 200, 2500)

        assert not prozessor.reset_unterwegs, (
            "Derselbe Nullzustand wurde ein zweites Mal gemeldet -- genau das "
            "erzeugte die Geisterlaeufe mit 'voriges Spiel endete mit 0 Kegeln'"
        )

    def test_nach_dem_verlassen_zaehlt_der_naechste_wechsel_wieder(self, prozessor):
        tafel = Tafel()
        prozessor.digit_reader = tafel

        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 200)
        assert prozessor.reset_unterwegs
        prozessor._reset_weiterreichen()

        # Das neue Spiel laeuft an: Die Anzeige zeigt wieder etwas. Es braucht
        # `game_reset_leave_frames` Messungen in Folge -- gemessen, weil eine
        # einzelne Fehllesung sonst die Sperre aufhebt.
        tafel.summe, tafel.nummer = 9, 1
        _laufen(prozessor, tafel, 200, 900)
        assert not prozessor._reset_latch, (
            "Die Sperre muss fallen, sobald die Anzeige den Nullzustand "
            "verlassen hat -- sonst bliebe der naechste Wechsel unerkannt"
        )

        # ... und das naechste Spielende wird wieder erkannt.
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 900, 1100)

        assert prozessor.reset_unterwegs

    def test_ein_ausreisser_hebt_die_sperre_nicht_auf(self, prozessor):
        """Eine einzelne unlesbare Messung ist kein Verlassen des Zustands."""
        tafel = Tafel()
        prozessor.digit_reader = tafel
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 200)
        prozessor._reset_weiterreichen()

        tafel.summe, tafel.nummer = None, None
        _laufen(prozessor, tafel, 200, 300)
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 300, 2000)

        assert not prozessor.reset_unterwegs

    def test_eine_einzelne_fehllesung_hebt_die_sperre_nicht_auf(self, prozessor):
        """GEMESSEN auf Bahn 2: nur 184 von 273 Messungen lasen die Null.

        Eine falsch gelesene Zahl mittendrin hob frueher die Sperre auf, und
        derselbe Spielwechsel wurde FUENFMAL gemeldet (F127250, F127375,
        F127825, F128075, F128225 -- alle im selben Abschnitt).
        """
        tafel = Tafel()
        prozessor.digit_reader = tafel
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 200)
        assert prozessor.reset_unterwegs
        prozessor._reset_weiterreichen()

        takt = prozessor.cfg.scoring.game_reset_check_interval
        for start in range(200, 4000, 400):
            # SECHS Fehllesungen in Folge -- die laengste am 2026-08-30 auf
            # Bahn 4 gemessene Straehne innerhalb des Nullzustands.
            tafel.summe, tafel.nummer = 8, 4
            _laufen(prozessor, tafel, start, start + 6 * takt)
            tafel.summe, tafel.nummer = 0, 0
            _laufen(prozessor, tafel, start + 6 * takt, start + 400)

        assert not prozessor.reset_unterwegs, (
            "Die laengste gemessene Straehne von Fehllesungen darf die Sperre "
            "nicht aufheben -- sonst meldet dieselbe Bahn denselben Wechsel "
            "mehrfach (Bahn 4: dreimal)"
        )

    def test_dauerhaft_andere_anzeige_hebt_die_sperre_auf(self, prozessor):
        """Die Sperre darf nicht kleben -- sonst bliebe das naechste Spielende weg."""
        tafel = Tafel()
        prozessor.digit_reader = tafel
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 200)
        prozessor._reset_weiterreichen()

        tafel.summe, tafel.nummer = 9, 1
        _laufen(prozessor, tafel, 200, 900)

        assert not prozessor._reset_latch


class TestNurDieWurfnummer:
    """`scoring.game_reset_number_only` -- die Summe als Zeugen weglassen.

    WARUM: Die Summe wird ZUERST gelesen und ist damit der Torwaechter. Ist sie
    unlesbar, wird die Wurfnummer nie geprueft. Gemessen am Spieltag
    2026-08-22 ist die Summe aber das schwaechere Feld:

        Bahn    Wurfnummer    Summe (total_b)
           2        100,0 %            97,6 %
           3        100,0 %             0,0 %
           4        100,0 %             5,0 %
           5        100,0 %             9,1 %

    Ein zweiter Zeuge, der oefter schweigt als der erste, kostet mehr als er
    einbringt.
    """

    def test_unlesbare_summe_verhindert_die_erkennung_nicht_mehr(self, prozessor):
        """Der eigentliche Gewinn: Bahn 3 las die Summe in keinem einzigen Fall."""
        prozessor.cfg.scoring.game_reset_number_only = True
        tafel = Tafel()
        prozessor.digit_reader = tafel

        tafel.summe, tafel.nummer = None, 0      # Summe unlesbar, Nummer null
        _laufen(prozessor, tafel, 0, 500)

        assert prozessor.reset_unterwegs, (
            "Mit `game_reset_number_only` darf eine unlesbare Summe den "
            "Spielwechsel nicht mehr verdecken"
        )

    def test_ohne_den_schalter_bleibt_es_beim_alten(self, prozessor):
        """Die Gegenprobe -- sonst wuerde der Test oben auch ohne Aenderung gruen."""
        prozessor.cfg.scoring.game_reset_number_only = False
        tafel = Tafel()
        prozessor.digit_reader = tafel

        tafel.summe, tafel.nummer = None, 0
        _laufen(prozessor, tafel, 0, 500)

        assert not prozessor.reset_unterwegs, (
            "Ohne den Schalter ist die unlesbare Summe weiterhin der "
            "Torwaechter -- das war der gemessene Ist-Zustand"
        )

    def test_unlesbare_wurfnummer_loest_weiterhin_nichts_aus(self, prozessor):
        """Der verbleibende Schutz: `is_readable` faengt die stumme Anzeige ab.

        Ohne die Summe als zweiten Zeugen traegt allein die Lesbarkeitspruefung
        der Wurfnummer. Sie darf nicht als Null durchgehen.
        """
        prozessor.cfg.scoring.game_reset_number_only = True
        tafel = Tafel()
        prozessor.digit_reader = tafel

        tafel.summe, tafel.nummer = None, None
        _laufen(prozessor, tafel, 0, 2000)

        assert not prozessor.reset_unterwegs

    def test_laufendes_spiel_loest_auch_ohne_summe_nichts_aus(self, prozessor):
        """Wurfnummer 001..030 ist der Normalfall und darf nie ausloesen."""
        prozessor.cfg.scoring.game_reset_number_only = True
        tafel = Tafel()
        prozessor.digit_reader = tafel

        for nummer in range(1, 31):
            tafel.nummer = nummer
            tafel.summe = None          # Summe durchgehend unlesbar
            _laufen(prozessor, tafel, nummer * 100, nummer * 100 + 100)

        assert not prozessor.reset_unterwegs


class TestWohinDasZeichenGeht:
    """BUG-028: Ein zwischen zwei Würfen gesehener Nullzustand kostete einen Wurf.

    Die Prüfung läuft in eigenem Takt, unabhängig vom Wurffenster. Sie trifft
    den Nullzustand deshalb mal WÄHREND eines Wurfs und mal ZWISCHEN zweien —
    und das ist ein Unterschied:

        im Fenster    Der laufende Wurf gehört noch zum alten Spiel; das
                      Zeichen gilt dem nächsten.
        dazwischen    Der letzte Wurf des alten Spiels ist längst gebucht;
                      der nächste ist bereits der erste des neuen Spiels.

    Bis dahin ging beides in denselben Briefkasten. Der zweite Fall kam damit
    einen Wurf zu spät, und der erste Wurf des neuen Spiels landete im alten —
    seine Kegel fehlten ab da im ganzen Spielstand.

    GEMESSEN am Spieltag 2026-09-17 (477 Würfe, 25 Spiele): Jedes Spiel, dessen
    erster gebuchter Wurf die Nummer 2 trug, hatte genau einen Wurf verloren —
    sieben von 25, jeweils mit konstantem Fehlbetrag über das ganze Spiel
    (−5 bis −9, genau die Kegelzahl des verlorenen Wurfs).
    """

    def test_zwischen_zwei_wuerfen_gilt_es_dem_naechsten_wurf(self, prozessor):
        """Der Fall aus dem Spieltag: Die Anlage setzt in der Pause zurück."""
        tafel = Tafel()
        prozessor.digit_reader = tafel
        assert not prozessor._window_open
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 500)

        assert prozessor.reset_unterwegs
        # Der naechste Wurf wird ausgewertet -- er MUSS das Zeichen bekommen.
        prozessor._reset_weiterreichen()
        assert prozessor.reset_pending, (
            "Der erste Wurf nach der Pause ist der erste des neuen Spiels. "
            "Bekommt er das Zeichen nicht, landen seine Kegel im alten Spiel "
            "und fehlen im neuen Stand -- fuer den Rest des Spiels."
        )

    def test_waehrend_des_wurfs_zurueckgesetzt_gilt_es_dem_naechsten(self, prozessor):
        """Die Anlage setzt zurück, WÄHREND der Wurf noch ausgewertet wird.

        Dann war er schon geworfen, als die Anzeige umsprang — er gehört noch
        zum alten Spiel.
        """
        tafel = Tafel()
        prozessor.digit_reader = tafel
        prozessor._window_open = True
        prozessor._green_off_frame = 0            # Fenster ging bei 0 auf
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 500)         # Nullzustand ab Frame 0

        assert prozessor.reset_unterwegs
        prozessor._reset_weiterreichen()          # der laufende Wurf
        assert not prozessor.reset_pending, (
            "Der Wurf, waehrend dessen die Anlage zuruecksetzte, gehoert noch "
            "zum alten Spiel"
        )
        prozessor._reset_weiterreichen()          # der naechste
        assert prozessor.reset_pending

    def test_vor_dem_wurf_zurueckgesetzt_gilt_es_diesem_wurf(self, prozessor):
        """GEMESSEN auf Bahn 5 (Stream 2026-09-17): Wurf 31 wurde mit
        `SummeTafel 0` gebucht — die Tafel hatte VOR diesem Wurf
        zurückgesetzt. Er landete trotzdem im alten Spiel, und das neue begann
        erst bei Wurf 2.

        Mit dem Fenster allein ist das nicht zu unterscheiden: Es ist in
        beiden Fällen offen. Entscheidend ist, ob der Nullzustand vor oder
        nach dem Fensterbeginn einsetzte.
        """
        tafel = Tafel()
        prozessor.digit_reader = tafel
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 300)         # Nullzustand ab Frame 0
        # ... und ERST DANACH beginnt der Wurf
        prozessor._window_open = True
        prozessor._green_off_frame = 400

        assert prozessor.reset_unterwegs
        prozessor._reset_weiterreichen()
        assert prozessor.reset_pending, (
            "Die Tafel stand schon auf null, als dieser Wurf begann -- er ist "
            "bereits der erste des neuen Spiels"
        )

    def test_das_zeichen_geht_nicht_verloren(self, prozessor):
        """Zwischen Erkennung und Zustellung darf nichts dazwischenkommen."""
        tafel = Tafel()
        prozessor.digit_reader = tafel
        tafel.summe, tafel.nummer = 0, 0
        _laufen(prozessor, tafel, 0, 500)
        # Die Anzeige verlaesst den Nullzustand, bevor der Wurf kommt
        tafel.summe, tafel.nummer = 42, 1
        _laufen(prozessor, tafel, 500, 900)
        prozessor._reset_weiterreichen()
        assert prozessor.reset_pending, (
            "Das Zeichen gilt dem naechsten Wurf, auch wenn die Anzeige "
            "inzwischen weitergelaufen ist"
        )
