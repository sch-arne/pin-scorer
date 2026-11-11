"""Tests der Wurfauswertung (Phase 8/9).

Hier laufen alle Quellen zusammen. Der wichtigste Testfall ist nicht der
Normalfall, sondern der Umgang mit widerspruechlichen Angaben: Die Redundanz
existiert, um Fehler zu zeigen -- nicht, um sie wegzuentscheiden.
"""

from __future__ import annotations

import pytest

from kegel_cv.analysis.frame_sampler import SampleEvent, SampledFrame
from kegel_cv.analysis.throw_analyzer import ThrowAnalyzer
from kegel_cv.config.schema import AppConfig
from kegel_cv.models.readings import LampReading, LampState, PinLampReading
from kegel_cv.models.throw import FrameRole, ThrowStatus
from kegel_cv.video.source import Frame

import numpy as np


def make_event(lane_id: int = 1, trigger: int = 100) -> SampleEvent:
    frame = Frame(trigger, trigger / 25.0, np.zeros((4, 4, 3), dtype=np.uint8))
    event = SampleEvent(lane_id=lane_id, event_id=1, trigger_frame=trigger,
                        trigger_timestamp=trigger / 25.0)
    event.frames.append(SampledFrame(frame, 0, FrameRole.GREEN_OFF))
    return event


def make_pins(pins: tuple[int, ...], complete: bool = True,
              confidence: float = 0.9) -> PinLampReading:
    lamps = tuple(
        LampReading(
            state=(LampState.ON if p in pins else
                   (LampState.OFF if complete else LampState.UNKNOWN)),
            score=50.0, confidence=confidence, name=f"pin_lamp_{p}")
        for p in range(1, 10)
    )
    return PinLampReading(lamps=lamps, pins=pins, confidence=confidence)


@pytest.fixture
def cfg() -> AppConfig:
    return AppConfig()


@pytest.fixture
def analyzer(cfg) -> ThrowAnalyzer:
    return ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)


class TestNormalfall:
    def test_gueltiger_wurf(self, analyzer):
        result = analyzer.analyze(make_event(), make_pins((1, 3, 5, 6, 8)),
                                  displayed_count=5, throw_number=1)
        assert result is not None
        assert result.status is ThrowStatus.VALID
        assert result.pins_count == 5
        assert result.running_total == 5
        assert result.lane == 2, "Die reale Bahnnummer wird ausgewiesen"

    def test_summe_waechst_ueber_mehrere_wuerfe(self, analyzer):
        for number, pins in enumerate([(1, 2, 3), (4, 5), (1, 2, 3, 4, 5, 6, 7)], start=1):
            result = analyzer.analyze(make_event(trigger=number * 100),
                                      make_pins(pins), throw_number=number)
        assert result.running_total == 3 + 2 + 7

    def test_leerwurf_ist_gueltig(self, analyzer):
        """Ein Wurf mit 0 Kegeln ist regulaer -- kein Fehler."""
        result = analyzer.analyze(make_event(), make_pins(()), displayed_count=0,
                                  throw_number=1)
        assert result.status is ThrowStatus.EMPTY
        assert result.valid is True
        assert result.pins_count == 0

    def test_zwischensumme_nach_zyklusende(self, cfg):
        analyzer = ThrowAnalyzer(1, cfg)
        for number in range(1, 15):
            result = analyzer.analyze(make_event(trigger=number * 100),
                                      make_pins((1, 2, 3)), throw_number=number)
            assert result.series_total is None

        result = analyzer.analyze(make_event(trigger=1500), make_pins((1, 2)),
                                  throw_number=15)
        assert result.series_total == 14 * 3 + 2
        assert result.throw_number_in_series == 15


class TestWurfnummer:
    def test_bug_008_wiederholte_nummer_verwirft_den_wurf_nicht(self, analyzer):
        """BUG-008: Eine nicht steigende Wurfnummer darf den Wurf NICHT loeschen.

        Der Gruenzyklus hat bereits bewiesen, dass geworfen wurde. Frueher gab
        `analyze` hier None zurueck -- gemessen gingen dadurch 20 von 71 Wuerfen
        verloren (28 %), auf einer Bahn 10 von 18.
        """
        analyzer.analyze(make_event(), make_pins((1, 2)), throw_number=5)
        zweiter = analyzer.analyze(make_event(trigger=200), make_pins((1, 2)),
                                   throw_number=5)

        assert zweiter is not None, "der Wurf darf nicht verschwinden"
        assert zweiter.throw_number == 6, "es wird fortgezaehlt"
        # ... und der Widerspruch bleibt sichtbar, statt still behoben zu werden
        assert any(not c.passed and "Wurfnummer" in c.name
                   for c in zweiter.evidence.checks)

    def test_bug_008_ein_lesefehler_loescht_keine_serie(self, analyzer):
        """BUG-008: Die Kettenreaktion, die den Fehler so teuer machte.

        Wird EIN Wurf zu hoch gelesen (echte 7 als "10"), lagen alle folgenden
        echten Nummern darunter und fielen saemtlich unter "bereits gebucht".
        Ein einziger Lesefehler loeschte so den Rest der Serie.
        """
        for nummer in (5, 6):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1,)),
                             throw_number=nummer)
        # der Lesefehler
        analyzer.analyze(make_event(trigger=700), make_pins((2,)), throw_number=10)
        # die echten Wuerfe 8 und 9 -- ihre Nummern liegen jetzt unter der 10
        weiter = [analyzer.analyze(make_event(trigger=n * 100), make_pins((3,)),
                                   throw_number=n)
                  for n in (8, 9)]

        assert all(w is not None for w in weiter),             "nach einem Lesefehler darf kein weiterer Wurf verlorengehen"
        assert [w.throw_number for w in weiter] == [11, 12]

    def test_bug_005_unplausibler_sprung_legt_bahn_nicht_stille(self, analyzer):
        """BUG-005: Eine falsch gelesene Wurfnummer (703) haette den Zaehler
        dauerhaft zerstoert -- alle folgenden Wuerfe waeren als bereits gebucht
        verworfen worden."""
        analyzer.analyze(make_event(), make_pins((1, 2)), throw_number=1)
        analyzer.analyze(make_event(trigger=200), make_pins((3,)), throw_number=2)

        # Lesefehler
        result = analyzer.analyze(make_event(trigger=300), make_pins((4, 5)),
                                  throw_number=703)
        assert result is not None
        assert result.throw_number == 3, "muss fortzaehlen statt 703 zu uebernehmen"

        # Entscheidend: Die Bahn laeuft danach normal weiter
        weiter = analyzer.analyze(make_event(trigger=400), make_pins((6,)),
                                  throw_number=4)
        assert weiter is not None
        assert weiter.throw_number == 4

    def test_kleiner_sprung_wird_akzeptiert(self, analyzer):
        """Eine echte Luecke (verpasster Wurf) ist plausibel und bleibt erhalten."""
        analyzer.analyze(make_event(), make_pins((1,)), throw_number=1)
        result = analyzer.analyze(make_event(trigger=200), make_pins((2,)),
                                  throw_number=3)
        assert result.throw_number == 3

    def test_luecke_wird_dokumentiert_nicht_kaschiert(self, analyzer):
        analyzer.analyze(make_event(), make_pins((1,)), throw_number=1)
        result = analyzer.analyze(make_event(trigger=200), make_pins((2,)),
                                  throw_number=4)
        assert any(not c.passed and "lueckenlos" in c.name for c in result.evidence.checks)
        assert any("verpasst" in d for d in result.evidence.decisions)

    def test_ohne_wurfnummer_wird_fortgezaehlt(self, analyzer):
        """Ist die Ziffer unlesbar, traegt allein die Zustandsmaschine."""
        first = analyzer.analyze(make_event(), make_pins((1,)), throw_number=None)
        second = analyzer.analyze(make_event(trigger=200), make_pins((2,)),
                                  throw_number=None)
        assert (first.throw_number, second.throw_number) == (1, 2)
        assert any("fortgezaehlt" in d for d in first.evidence.decisions)


class TestWiderspruch:
    def test_lampen_und_ziffer_uneinig_senkt_confidence(self, analyzer):
        einig = analyzer.analyze(make_event(), make_pins((1, 2, 3)),
                                 displayed_count=3, throw_number=1)
        uneinig = analyzer.analyze(make_event(trigger=200), make_pins((1, 2, 3)),
                                   displayed_count=7, throw_number=2)
        assert uneinig.confidence < einig.confidence
        assert uneinig.sources_agree is False

    def test_widerspruch_wird_als_pruefung_festgehalten(self, analyzer):
        result = analyzer.analyze(make_event(), make_pins((1, 2, 3)),
                                  displayed_count=7, throw_number=1)
        check = next(c for c in result.evidence.checks if "Lampen" in c.name)
        assert check.passed is False
        assert check.expected == 7 and check.actual == 3

    def test_lampen_bleiben_die_hauptquelle(self, analyzer):
        """Bei Widerspruch gilt die Lampenzaehlung -- sie ist am Material
        deutlich zuverlaessiger als die Ziffernerkennung."""
        result = analyzer.analyze(make_event(), make_pins((1, 2, 3)),
                                  displayed_count=7, throw_number=1)
        assert result.pins_count == 3
        assert result.displayed_pin_count == 7, "beide Werte bleiben erhalten"

    def test_unlesbare_lampen_ergeben_error(self, analyzer):
        result = analyzer.analyze(make_event(), make_pins((1, 2), complete=False),
                                  throw_number=1)
        assert result.status is ThrowStatus.ERROR

    def test_mehrere_verletzte_pruefungen_ergeben_error(self, analyzer):
        analyzer.analyze(make_event(), make_pins((1,)), throw_number=1)
        result = analyzer.analyze(make_event(trigger=200), make_pins((2, 3)),
                                  displayed_count=9,      # Widerspruch 1
                                  throw_number=4,          # Luecke -> Widerspruch 2
                                  displayed_total=999)     # Widerspruch 3
        assert result.status is ThrowStatus.ERROR

    def test_summenpruefung_gegen_den_nachhinkenden_stand(self, analyzer):
        """Die Anzeige hinkt einen Wurf hinterher.

        Die Anlage traegt das Ergebnis erst kurz vor dem naechsten GREEN_ON ein
        (BUG-010), gemeldet wird der Wurf aber schon 1,6 s nach GREEN_OFF.
        GEMESSEN ueber einen ganzen Lauf: 294-mal stand dort die vorherige
        Summe, viermal die aktuelle.

        Geprueft wird deshalb gegen den Stand VOR diesem Wurf -- hier also die
        3 aus dem ersten Wurf.
        """
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=1)
        result = analyzer.analyze(make_event(trigger=200), make_pins((4, 5)),
                                  throw_number=2, displayed_total=3)

        check = next(c for c in result.evidence.checks if "Summe" in c.name)
        assert check.passed is True and check.expected == 3

    def test_falsche_summe_faellt_weiterhin_auf(self, analyzer):
        """Die Kette bleibt geschlossen: Waere der erste Wurf falsch gebucht,
        passte der Stand beim zweiten nicht mehr."""
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=1)
        result = analyzer.analyze(make_event(trigger=200), make_pins((4, 5)),
                                  throw_number=2, displayed_total=7)

        check = next(c for c in result.evidence.checks if "Summe" in c.name)
        assert check.passed is False

    def test_altes_verhalten_bleibt_einstellbar(self, cfg):
        """Wird wieder erst beim naechsten GREEN_ON gemeldet, steht die
        aktuelle Summe da -- dann gilt wieder die alte Rechnung."""
        cfg.scoring.displayed_total_lags = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=1)

        result = analyzer.analyze(make_event(trigger=200), make_pins((4, 5)),
                                  throw_number=2, displayed_total=5)

        check = next(c for c in result.evidence.checks if "Summe" in c.name)
        assert check.passed is True and check.expected == 5


class TestFehlwurfzaehler:
    def test_zaehler_steigt_bei_leerwurf(self, analyzer):
        analyzer.analyze(make_event(), make_pins((1, 2)), throw_number=1, foul_count=0)
        result = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                  throw_number=2, foul_count=1)
        check = next(c for c in result.evidence.checks if "Fehlwurf" in c.name)
        assert check.passed is True

    def test_abweichung_deutet_auf_uebersehenen_leerwurf(self, analyzer):
        """Q2: Der Zaehler ist die einzige unabhaengige Quelle fuer Leerwuerfe."""
        analyzer.analyze(make_event(), make_pins((1, 2)), throw_number=1, foul_count=0)
        result = analyzer.analyze(make_event(trigger=200), make_pins((3,)),
                                  throw_number=2, foul_count=1)
        check = next(c for c in result.evidence.checks if "Fehlwurf" in c.name)
        assert check.passed is False
        assert any("Leerwurf" in d for d in result.evidence.decisions)


class TestNachvollziehbarkeit:
    def test_ergebnis_erklaert_sich_selbst(self, analyzer):
        result = analyzer.analyze(make_event(trigger=4580), make_pins((1, 3, 5, 6, 8)),
                                  displayed_count=5, throw_number=17)
        text = result.explain()
        assert "Wurf 17" in text
        assert "4580" in text
        assert "VALID" in text

    def test_evidence_enthaelt_die_frames(self, analyzer):
        result = analyzer.analyze(make_event(trigger=4580), make_pins((1,)),
                                  throw_number=1)
        assert result.evidence.frames[0].index == 4580

    def test_reset_setzt_den_zaehler_zurueck(self, analyzer):
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=1)
        analyzer.reset()
        result = analyzer.analyze(make_event(trigger=200), make_pins((1,)),
                                  throw_number=1)
        assert result.running_total == 1


class TestRaeumen:
    """Beim Raeumen leuchten schon vor dem Wurf Lampen.

    Vom Nutzer erklaert (2026-08-25): Stehengebliebene Kegel muessen geraeumt
    werden. Man erkennt es daran, dass beim Einschalten der gruenen Lampe
    bereits Kegellampen leuchten -- diese Kegel liegen schon und zaehlen NICHT
    zu diesem Wurf.
    """

    def test_bereits_liegende_kegel_zaehlen_nicht_mit(self, analyzer):
        # Vor dem Wurf lagen 1, 2, 3 -- danach liegen zusaetzlich 4 und 5
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2, 3, 4, 5)),
            baseline=make_pins((1, 2, 3)),
        )

        assert ergebnis.pins_count == 2, "nur die NEU gefallenen Kegel zaehlen"
        assert ergebnis.pins == (4, 5)

    def test_ohne_grundlinie_zaehlt_der_ganze_stand(self, analyzer):
        """In die Vollen: Die Grundlinie ist leer, nichts wird abgezogen."""
        ergebnis = analyzer.analyze(make_event(), make_pins((1, 2, 3)),
                                    baseline=make_pins(()))

        assert ergebnis.pins_count == 3

    def test_raeumen_wird_in_der_beweiskette_ausgewiesen(self, analyzer):
        ergebnis = analyzer.analyze(make_event(), make_pins((1, 2, 3)),
                                    baseline=make_pins((1,)))

        assert ergebnis.evidence.raw["clearing"] is True
        assert any("Raeumen" in d for d in ergebnis.evidence.decisions)

    def test_neu_aufgestellt_verwirft_die_grundlinie(self, analyzer):
        """Lagen vorher Kegel, die jetzt wieder stehen, hat die Anlage neu
        aufgestellt. Dann ist die Grundlinie hinfaellig -- nicht das Ergebnis.

        Ohne diese Regel entstuende eine negative Kegelzahl.
        """
        ergebnis = analyzer.analyze(make_event(), make_pins((7, 8)),
                                    baseline=make_pins((1, 2, 3)))

        assert ergebnis.pins_count == 2
        assert ergebnis.pins == (7, 8)
        assert any("aufgestellt" in d for d in ergebnis.evidence.decisions)


class TestStatusUndWurfnummer:
    """Eine falsch gelesene Wurfnummer darf ein sauberes Ergebnis nicht entwerten.

    Vom Nutzer angemerkt (2026-08-25): "nur weil die Wurfnummer nicht richtig
    erkannt wird, soll bitte das Ergebnis noch nicht direkt als ERROR ausgegeben
    werden."

    Der Grund dahinter: Die Wurfnummer betrifft die Buchfuehrung, nicht die
    Messung. Wie viele Kegel gefallen sind, sagen die Lampen -- und die koennen
    einwandfrei sein, waehrend die dreistellige Nummer flackert.
    """

    def test_wurfnummer_fehler_macht_keinen_error(self, analyzer):
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=5)
        # Nummer wiederholt sich UND es entsteht eine Luecke -- zwei Verstoesse,
        # die frueher zusammen ERROR ausgeloest haetten
        zweiter = analyzer.analyze(make_event(trigger=200), make_pins((1, 2, 3)),
                                   throw_number=5)

        assert zweiter.status is ThrowStatus.VALID
        assert zweiter.pins_count == 3

    def test_widerspruch_bleibt_trotzdem_sichtbar(self, analyzer):
        analyzer.analyze(make_event(), make_pins((1,)), throw_number=5)
        zweiter = analyzer.analyze(make_event(trigger=200), make_pins((1,)),
                                   throw_number=5)

        gescheitert = [c for c in zweiter.evidence.checks if not c.passed]
        assert gescheitert, "die Abweichung muss in der Beweiskette stehen"
        assert all(not c.affects_result for c in gescheitert)
        assert zweiter.confidence < 1.0, "und die Confidence senken"

    def test_ergebnisrelevante_widersprueche_ergeben_weiter_error(self, analyzer):
        """Die Lockerung darf nur fuer die Buchfuehrung gelten: Widersprechen
        sich zwei Quellen ueber das ERGEBNIS, bleibt es ein Fehler."""
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2, 3)),
            displayed_count=8,        # Ziffer widerspricht den Lampen
            displayed_total=999,      # und die Summe passt ebenfalls nicht
        )

        assert ergebnis.status is ThrowStatus.ERROR


class TestSpielwechsel:
    """Nach 30 Würfen setzt die Anlage Wurfnummer und Summe zurück.

    Vom Nutzer angekündigt, über 52 Minuten bestätigt: Rücksetzungen bei den
    Würfen 29/30, 59/60 und 89/90 auf drei Bahnen unabhängig.
    """

    def test_rueckfall_von_hoch_auf_niedrig_startet_neues_spiel(self, analyzer):
        for nummer in range(1, 31):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1, 2)),
                             throw_number=nummer)
        assert analyzer.score.running_total == 60

        neu = analyzer.analyze(make_event(trigger=3100), make_pins((1, 2, 3)),
                               throw_number=1)

        assert neu.throw_number == 1, "die Tafel beginnt neu bei 1"
        assert neu.running_total == 3, "und die Summe ebenfalls"
        assert analyzer.score.game_totals == [60], "der Endstand ist festgehalten"

    def test_kleiner_rueckfall_bleibt_ein_lesefehler(self, analyzer):
        """Die Abgrenzung zu BUG-008: Ein Lesefehler verschiebt um wenige
        Stellen, ein Spielwechsel fällt von über 30 auf unter 5 zurück."""
        for nummer in (10, 11, 12):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1,)),
                             throw_number=nummer)

        weiter = analyzer.analyze(make_event(trigger=1300), make_pins((1,)),
                                  throw_number=11)

        assert weiter.throw_number == 13, "fortgezaehlt, nicht neues Spiel"
        assert analyzer.score.game_totals == []

    def test_niedrige_nummer_am_anfang_ist_kein_spielwechsel(self, analyzer):
        """Zu Beginn steht `last` auf 0 -- da darf nichts zurueckgesetzt werden."""
        erster = analyzer.analyze(make_event(), make_pins((1, 2)), throw_number=1)

        assert erster.running_total == 2
        assert analyzer.score.game_totals == []

    def test_spielwechsel_steht_in_der_beweiskette(self, analyzer):
        for nummer in range(1, 31):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1,)),
                             throw_number=nummer)
        neu = analyzer.analyze(make_event(trigger=3100), make_pins((1,)),
                               throw_number=1)

        assert any("Neues Spiel" in d for d in neu.evidence.decisions)


class TestSpielwechselUeberDieNullanzeige:
    """Die untere Reihe steht zwischen zwei Spielen auf `000  0000`.

    Vom Nutzer beschrieben (2026-08-28). GEMESSEN mit
    tools/measure_display_reset.py am 52-Minuten-Video: 20 bis 90 Sekunden
    Standzeit, an allen drei Satzgrenzen auf allen vier Bahnen, und kein
    einziger Treffer in 3000 Kontrollframes mitten im Satz.

    Warum zusaetzlich zum Ruecksprung der Wurfnummer: Der Ruecksprung braucht
    mindestens `game_reset_after` vorher gezaehlte Wuerfe. Endet ein Spiel
    frueher -- der Nutzer sagt "meistens nach 30 Wurf, aber nicht immer" --
    ist es damit nicht erkennbar.
    """

    def test_nullanzeige_startet_neues_spiel(self, analyzer):
        for nummer in range(1, 31):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1, 2)),
                             throw_number=nummer)
        assert analyzer.score.running_total == 60

        neu = analyzer.analyze(make_event(trigger=3100), make_pins((1, 2, 3)),
                               throw_number=1, display_reset=True)

        assert neu.running_total == 3, "die Summe beginnt neu"
        assert analyzer.score.game_totals == [60]

    def test_wirkt_auch_ohne_lesbare_wurfnummer(self, analyzer):
        """Der eigentliche Gewinn: Der Ruecksprung braucht eine gelesene
        Wurfnummer, der Nullzustand nicht."""
        for nummer in range(1, 31):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1, 2)),
                             throw_number=nummer)

        neu = analyzer.analyze(make_event(trigger=3100), make_pins((5,)),
                               throw_number=None, display_reset=True)

        assert neu.running_total == 1
        assert analyzer.score.game_totals == [60]

    def test_wirkt_auch_bei_kurzem_spiel(self, analyzer):
        """Die Luecke, die der Ruecksprung offen laesst: Endet ein Spiel nach
        weniger als `game_reset_after` Wuerfen, faellt die Wurfnummer nicht
        weit genug zurueck, um als Spielwechsel zu gelten."""
        for nummer in (1, 2, 3):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1, 2)),
                             throw_number=nummer)
        assert analyzer.score.running_total == 6

        neu = analyzer.analyze(make_event(trigger=400), make_pins((4,)),
                               throw_number=1, display_reset=True)

        assert neu.running_total == 1, "trotz kurzem Spiel wird zurueckgesetzt"
        assert analyzer.score.game_totals == [6]

    def test_ohne_nullanzeige_bleibt_alles_beim_alten(self, analyzer):
        """Die Gegenprobe: Das Merkmal darf nicht von allein feuern."""
        for nummer in (1, 2, 3):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1, 2)),
                             throw_number=nummer)

        weiter = analyzer.analyze(make_event(trigger=400), make_pins((4,)),
                                  throw_number=4, display_reset=False)

        assert weiter.running_total == 7
        assert analyzer.score.game_totals == []

    def test_abschaltbar(self, cfg):
        """Kein Verfahren ohne Notausgang -- die Anlage koennte sich anders
        verhalten als die eine gemessene."""
        cfg.scoring.game_reset_by_zero_display = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        for nummer in (1, 2, 3):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1, 2)),
                             throw_number=nummer)

        weiter = analyzer.analyze(make_event(trigger=400), make_pins((4,)),
                                  throw_number=4, display_reset=True)

        assert weiter.running_total == 7, "das Merkmal wird ignoriert"
        assert analyzer.score.game_totals == []

    def test_spielwechsel_steht_in_der_beweiskette(self, analyzer):
        for nummer in range(1, 31):
            analyzer.analyze(make_event(trigger=nummer * 100), make_pins((1,)),
                             throw_number=nummer)
        neu = analyzer.analyze(make_event(trigger=3100), make_pins((1,)),
                               throw_number=1, display_reset=True)

        assert any("000/0000" in d for d in neu.evidence.decisions), \
            "der Grund muss am Ergebnis haengen, nicht nur im Log"


class TestZyklusOhneVeraenderung:
    """Zeigt die Kegelraute am Ende dasselbe wie am Anfang, war es kein Wurf.

    Denn ein Wurf, bei dem nichts faellt, erzeugt gar keinen Gruenzyklus: Die
    Anlage hat nichts zu zaehlen und nichts aufzustellen, die Bahn bleibt
    freigegeben (Q10). Solche Wuerfe kommen ueber den Fehlwurfzaehler.

    GEMESSEN ueber 479 Gruenzyklen des 52-Minuten-Videos: GENAU EINER hatte
    eine unveraenderte Kegelraute, und genau der stand nicht im handgefuehrten
    Wurfprotokoll (Bahn 2, F4032 -- sechs Kegel lagen vorher wie nachher).
    """

    def test_unveraenderte_raute_ergibt_keinen_wurf(self, analyzer):
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2, 4, 7, 8, 9)),
            baseline=make_pins((1, 2, 4, 7, 8, 9)))

        assert ergebnis is None

    def test_leere_raute_bleibt_ein_gueltiger_leerwurf(self, analyzer):
        """Die Regel bleibt eng bei dem, was gemessen ist: Fuer 'nichts vorher,
        nichts nachher' gibt es keinen Beleg, dass es eine Stoerung waere."""
        ergebnis = analyzer.analyze(make_event(), make_pins(()),
                                    baseline=make_pins(()))

        assert ergebnis is not None
        assert ergebnis.pins_count == 0

    def test_unvollstaendige_messung_wird_nicht_verworfen(self, analyzer):
        """Waren Lampen unlesbar, sagt die Gleichheit nichts -- dann koennte
        eine Messung ausgefallen sein statt nichts gefallen."""
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2), complete=False),
            baseline=make_pins((1, 2)))

        assert ergebnis is not None

    def test_raeumwurf_mit_zuwachs_bleibt_erhalten(self, analyzer):
        """Die Abgrenzung: Beim Raeumen liegen Kegel, aber es kommen welche
        dazu. Das ist ein Wurf und muss einer bleiben."""
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2, 4, 7, 8, 9)),
            baseline=make_pins((1, 2, 4)))

        assert ergebnis is not None
        assert ergebnis.pins_count == 3, "nur die neu gefallenen zaehlen"

    def test_abschaltbar(self, cfg):
        cfg.scoring.discard_unchanged_cycles = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)

        ergebnis = analyzer.analyze(make_event(), make_pins((1, 2)),
                                    baseline=make_pins((1, 2)))

        assert ergebnis is not None


class TestNullwurfUeberDenFehlwurfzaehler:
    """Wuerfe ohne Kegel kommen nicht aus dem Gruenzyklus.

    GEMESSEN (Q10): Faellt bei einem Wurf kein Kegel, schaltet die Anlage die
    gruene Lampe gar nicht aus -- es gibt nichts zu zaehlen und nichts
    aufzustellen. Belegt an der Gruenspur: Bahn 4, F16366 bis F17477, eine
    einzige Gruenphase von 1111 Frames, darin zwei Wuerfe.

    Der Fehlwurfzaehler im linken Display zaehlt sie trotzdem. Ueber 52 Minuten
    stieg er auf Bahn 2 genau einmal -- an der Stelle, an der im handgefuehrten
    Wurfprotokoll der einzige Nullwurf dieser Bahn steht.
    """

    def test_nullwurf_wird_gebucht(self, analyzer):
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1)

        leer = analyzer.analyze_zero_throw(frame_index=500, timestamp=20.0)

        assert leer.pins_count == 0
        assert leer.pins == ()
        assert leer.throw_number == 2, "er zaehlt in der Wurffolge mit"
        assert leer.running_total == 3, "und aendert die Summe nicht"

    def test_zeitstempel_ist_der_des_zaehlerstands(self, analyzer):
        """Genauer geht es nicht: Der Wurf selbst hinterlaesst keine Spur."""
        leer = analyzer.analyze_zero_throw(frame_index=51230, timestamp=2049.2)

        assert leer.source_frame == 51230
        assert leer.timestamp == 2049.2

    def test_herkunft_steht_in_der_beweiskette(self, analyzer):
        """Ein Wurf ohne Lampenmessung muss sagen, woher er kommt -- sonst
        sieht er wie ein verlorener Wurf aus."""
        leer = analyzer.analyze_zero_throw(frame_index=500, timestamp=20.0)

        assert leer.evidence.raw["source"] == "fehlwurfzaehler"
        assert any("Fehlwurfzaehler" in d for d in leer.evidence.decisions)

    def test_zaehlt_in_der_summenkette_weiter(self, analyzer):
        """Der naechste echte Wurf darf nicht aus dem Tritt geraten."""
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1)
        analyzer.analyze_zero_throw(frame_index=500, timestamp=20.0)
        danach = analyzer.analyze(make_event(trigger=900), make_pins((4, 5)))

        assert danach.throw_number == 3
        assert danach.running_total == 5


class TestAufloesungUeberDieLampen:
    """Uneindeutige Ziffern duerfen von den Lampen aufgeloest werden.

    Vom Nutzer vorgeschlagen (2026-08-25): "wenn er eine 4 oder 9 als Text
    erkennt, und oben 9 Lampen leuchten => 9". Der Gedanke dahinter ist, die
    Quellen einander aufloesen zu lassen, statt einzelne Messwerte zu jagen.

    Entscheidend fuer die Ehrlichkeit der Pruefung ist die RICHTUNG: Die Lampen
    duerfen zwischen den Kandidaten waehlen, aber keinen neuen Wert setzen.
    """

    def test_lampen_waehlen_zwischen_den_kandidaten(self, analyzer):
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2, 3, 4)),      # vier Kegel
            displayed_candidates=(4, 9),                # Ziffer schwankte
        )

        assert ergebnis.status is ThrowStatus.VALID
        pruefung = [c for c in ergebnis.evidence.checks
                    if c.name == "Lampen unter den moeglichen Ziffern"]
        assert pruefung and pruefung[0].passed
        assert any("aufgeloest" in d for d in ergebnis.evidence.decisions)

    def test_wert_ausserhalb_der_kandidaten_bleibt_widerspruch(self, analyzer):
        """Der Kern: Die Gegenprobe muss die Lampen weiterhin widerlegen
        koennen. Sonst waere sie eine Scheinpruefung."""
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2, 3, 4, 5, 6, 7)),   # sieben Kegel
            displayed_candidates=(4, 9),                       # 7 stand nie zur Wahl
        )

        pruefung = [c for c in ergebnis.evidence.checks
                    if c.name == "Lampen unter den moeglichen Ziffern"]
        assert pruefung and not pruefung[0].passed

    def test_harter_vergleich_wenn_die_lampen_nicht_zur_wahl_standen(self, analyzer):
        """Steht der Lampenwert NICHT unter den Kandidaten, gilt der harte
        Vergleich -- die Auswahl darf den Widerspruch nicht wegdefinieren."""
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2, 3)),          # drei Kegel
            displayed_count=8, displayed_candidates=(8, 9),   # 3 stand nie zur Wahl
        )

        namen = [c.name for c in ergebnis.evidence.checks]
        assert "Lampen == angezeigte Kegelzahl" in namen
        assert "Lampen unter den moeglichen Ziffern" not in namen

    def test_ohne_kandidaten_keine_zusaetzliche_pruefung(self, analyzer):
        ergebnis = analyzer.analyze(make_event(), make_pins((1, 2, 3)))

        namen = [c.name for c in ergebnis.evidence.checks]
        assert "Lampen unter den moeglichen Ziffern" not in namen


class TestAufloesungBeiScheinbarEindeutigerZiffer:
    """Auch eine zusammengefasste Ziffer kann eine von mehreren Lesungen sein.

    GEMESSEN: Bei fuenf von vierzehn Widerspruechen stand der Lampenwert in den
    Frame-Kandidaten (etwa Lampen 8, gelesen 7, moeglich waren {7, 8}).
    """

    def test_lampenwert_unter_den_kandidaten_loest_auf(self, analyzer):
        ergebnis = analyzer.analyze(
            make_event(), make_pins(tuple(range(1, 9))),   # acht Kegel
            displayed_count=7,                             # zusammengefasst auf 7
            displayed_candidates=(7, 8),                   # beide waren moeglich
        )

        assert ergebnis.status is ThrowStatus.VALID
        assert any("aufgeloest" in d for d in ergebnis.evidence.decisions)

    def test_lampenwert_ausserhalb_bleibt_widerspruch(self, analyzer):
        """Der Schutz: Was der Leser nie in Betracht zog, wird nicht akzeptiert."""
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2)),               # zwei Kegel
            displayed_count=7,
            displayed_candidates=(7, 8),                   # 2 stand nie zur Wahl
        )

        pruefung = [c for c in ergebnis.evidence.checks
                    if c.name == "Lampen == angezeigte Kegelzahl"]
        assert pruefung and not pruefung[0].passed

    def test_uebereinstimmung_braucht_keine_aufloesung(self, analyzer):
        ergebnis = analyzer.analyze(
            make_event(), make_pins((1, 2, 3)),
            displayed_count=3, displayed_candidates=(3, 9),
        )

        assert not any("aufgeloest" in d for d in ergebnis.evidence.decisions)


class TestZyklusOhneRegung:
    """Ein Gruenzyklus, bei dem sich NICHTS geregt hat, ist kein Wurf.

    TEUER GELERNT am 2026-08-30 (Spieltag 2026-08-29, Bahn 5): Ein kurzer
    Gruenzyklus erzeugte einen Wurf mit 0 Kegeln. Die Wurfnummer lief danach um
    EINS VERSETZT weiter, und jeder folgende Wurf des Satzes wurde dem falschen
    Protokollwurf zugeordnet:

        Spieler A, F40903    16/30  ->  29/30 nach Korrektur
        Spieler D, F179349  27/30  ->  30/30 nach Korrektur

    EIN eingeschobener Wurf kostete 13 bzw. 3 Wuerfe. Der Schaden entsteht
    durch den VERSATZ, den er hinterlaesst -- nicht durch den falschen Wurf.

    Die Dauer des Zyklus taugt als Kriterium NICHT: gemessen wurde ein echter
    Wurf ueber 7 Frames und ein falscher ueber 46.
    """

    def _erster_wurf(self, analyzer):
        """Bezugspunkt setzen -- ohne ihn wird nie verworfen."""
        return analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                                throw_number=5, foul_count=0)

    def test_ohne_regung_kein_wurf(self, analyzer):
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=5, foul_count=0)

        assert ergebnis is None

    def test_die_wurfnummernkette_bleibt_stehen(self, analyzer):
        """Der eigentliche Schaden. Nach dem verworfenen Zyklus muss der
        naechste echte Wurf dieselbe Nummer bekommen wie ohne ihn."""
        self._erster_wurf(analyzer)
        analyzer.analyze(make_event(trigger=200), make_pins(()),
                         throw_number=5, foul_count=0)

        weiter = analyzer.analyze(make_event(trigger=300), make_pins((4, 5)),
                                  throw_number=6, foul_count=0)

        assert weiter is not None
        assert weiter.throw_number == 6, "kein Versatz durch den verworfenen Zyklus"

    def test_steigende_wurfnummer_wird_nicht_verworfen(self, analyzer):
        """Die Anlage hat gezaehlt -- also wurde geworfen, auch ohne Kegel."""
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=6, foul_count=0)

        assert ergebnis is not None
        assert ergebnis.pins_count == 0

    def test_steigender_fehlwurfzaehler_wird_nicht_verworfen(self, analyzer):
        """Ein Wurf ohne Kegel erhoeht den Fehlwurfzaehler -- das ist der
        zweite unabhaengige Zeuge."""
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=5, foul_count=1)

        assert ergebnis is not None

    def test_unlesbare_staende_verwerfen_nichts(self, analyzer):
        """Der Gruenzyklus ist ein Beweis, dass die Anlage etwas getan hat.
        Eine ausgefallene Ziffernlesung darf ihn nicht aufheben -- dieselbe
        Regel wie in BUG-008, wo das 28 % der Wuerfe kostete."""
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=None, foul_count=None)

        assert ergebnis is not None

    def test_gefallene_kegel_werden_nie_verworfen(self, analyzer):
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins((7,)),
                                    throw_number=5, foul_count=0)

        assert ergebnis is not None
        assert ergebnis.pins_count == 1

    def test_abschaltbar(self, cfg):
        """Beide Nullwurf-Regeln muessen aus, sonst prueft der Test nichts.

        `discard_zero_without_digit` (2026-09-03) faengt denselben Fall: null
        Kegel, keine Tafelziffer, Wurfnummer nicht weitergezaehlt. Bliebe sie
        an, waere dieser Test gruen, ohne die Abschaltbarkeit der hier
        gemeinten Regel zu belegen.
        """
        cfg.scoring.discard_static_zero_cycles = False
        cfg.scoring.discard_zero_without_digit = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=5, foul_count=0)

        assert ergebnis is not None


class TestNullKegelBrauchtEinenZeugen:
    """`discard_zero_without_digit` -- die falschen Nullen herausnehmen.

    GEMESSEN am Spieltag 2026-08-22, alle 19 Wuerfe mit null Kegeln:

        Herkunft            Anzahl   Tafel-Ziffer   Lage im Abschnitt
        fehlwurfzaehler          4   immer 0        mitten im Satz
        gruenzyklus             15   nie vorhanden  erster/letzter Wurf

    Acht der fuenfzehn stehen als ERSTER Wurf nach einem Spielwechsel -- dort
    springt die Wurfnummer von 30 auf 1 zurueck. `discard_static_zero_cycles`
    faengt sie nicht, weil jene Regel eine UNVERAENDERTE Wurfnummer verlangt.
    """

    def _erster_wurf(self, analyzer):
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=30, foul_count=0)

    def test_rueckspringende_wurfnummer_verwirft(self, cfg):
        """Der Kern: 30 -> 1 ist ein Ruecksetzen, kein Weiterzaehlen."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=1, foul_count=0)

        assert ergebnis is None

    def test_tafelziffer_null_rettet_den_wurf(self, cfg):
        """Zeigt die Anlage selbst eine 0, ist der Wurf echt."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=1, foul_count=0,
                                    displayed_count=0)

        assert ergebnis is not None

    def test_weitergezaehlte_wurfnummer_rettet_den_wurf(self, cfg):
        """Zaehlt die Anlage um eins weiter, hat sie einen Wurf registriert."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=31, foul_count=0)

        assert ergebnis is not None

    def test_unlesbare_wurfnummer_verwirft_nichts(self, cfg):
        """Die Lehre aus BUG-008: Schweigen ist kein Beleg gegen den Wurf."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=None, foul_count=None)

        assert ergebnis is not None

    def test_abschaltbar(self, cfg):
        cfg.scoring.discard_zero_without_digit = False
        cfg.scoring.discard_static_zero_cycles = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=1, foul_count=0)

        assert ergebnis is not None


class TestZweiZeugenEinSpielwechsel:
    """Denselben Spielwechsel meldet nicht jeder Zeuge fuer sich.

    Es gibt ZWEI Zeugen, beide gewollt: der Nullzustand der Anzeige
    (`000  0000`) und der Rueckfall der Wurfnummer. Sie treffen aber nicht
    gleichzeitig ein -- der Nullzustand wird um bis zu zwei Wuerfe
    weitergereicht, weil er im Fenster des VORIGEN Wurfs gesehen wird.

    GEMESSEN ueber den vollen Spieltag 2026-08-29, Wuerfe je erkanntem Spiel:

        Bahn 2   25 Spiele: 1,1,1,1,1,1,1,1, 19,19,19, 29x5, 30x6, 32
        Bahn 3   16 Spiele: 1, 19,20,21, 29, 30x11
        Bahn 5   20 Spiele: 1,2, 20,21,21,28, 30x8, 31x3

    Die Ein- und Zwei-Wurf-Spiele sind ausnahmslos dieses Muster:

        Spiel 4  Wurf 30    Satz zu Ende
        Spiel 5  Wurf  1    Wechsel erkannt
        Spiel 6  Wurf  2    zweiter Wechsel, EINEN Wurf spaeter
    """

    def _analyzer(self, **anpassungen):
        cfg = AppConfig()
        for k, v in anpassungen.items():
            setattr(cfg.scoring, k, v)
        return ThrowAnalyzer(lane_id=1, cfg=cfg)

    def test_zweiter_zeuge_einen_wurf_spaeter_zaehlt_nicht(self):
        a = self._analyzer()
        for n in range(1, 31):
            a.analyze(make_event(), make_pins((1, 2)), throw_number=n)
        spiele_vorher = len(a.score.game_totals)

        # Wurf 1 des neuen Spiels: Der Rueckfall der Wurfnummer greift sofort.
        a.analyze(make_event(), make_pins((1,)), throw_number=1)
        assert len(a.score.game_totals) == spiele_vorher + 1

        # Wurf 2: Jetzt trifft der Nullzustand ein -- derselbe Wechsel.
        a.analyze(make_event(), make_pins((2,)), throw_number=2,
                  display_reset=True)

        assert len(a.score.game_totals) == spiele_vorher + 1, (
            "Derselbe Spielwechsel wurde zweimal gebucht -- der erste Wurf des "
            "neuen Spiels landet dann allein in einem eigenen Spiel"
        )

    def test_der_naechste_echte_wechsel_zaehlt_wieder(self):
        a = self._analyzer()
        for n in range(1, 31):
            a.analyze(make_event(), make_pins((1, 2)), throw_number=n)
        a.analyze(make_event(), make_pins((1,)), throw_number=1)
        a.analyze(make_event(), make_pins((2,)), throw_number=2,
                  display_reset=True)
        spiele = len(a.score.game_totals)

        for n in range(3, 31):
            a.analyze(make_event(), make_pins((1, 2)), throw_number=n)
        a.analyze(make_event(), make_pins((1,)), throw_number=1)

        assert len(a.score.game_totals) == spiele + 1, (
            "Nach einem vollen Satz muss der naechste Wechsel wieder zaehlen"
        )

    def test_nullzustand_allein_traegt_weiterhin(self):
        """Der zweite Zeuge soll bleiben -- er traegt, wenn die Wurfnummer
        unlesbar ist."""
        a = self._analyzer()
        for n in range(1, 31):
            a.analyze(make_event(), make_pins((1, 2)), throw_number=n)
        spiele = len(a.score.game_totals)

        a.analyze(make_event(), make_pins((1,)), throw_number=None,
                  display_reset=True)

        assert len(a.score.game_totals) == spiele + 1

    def test_abschaltbar(self):
        a = self._analyzer(game_reset_min_gap_throws=0)
        for n in range(1, 31):
            a.analyze(make_event(), make_pins((1, 2)), throw_number=n)
        spiele = len(a.score.game_totals)

        a.analyze(make_event(), make_pins((1,)), throw_number=1)
        a.analyze(make_event(), make_pins((2,)), throw_number=2,
                  display_reset=True)

        assert len(a.score.game_totals) == spiele + 2


class TestStillstandDerWurfnummer:
    """Ruehrt sich der Zaehler der Anlage nicht, hat kein Wurf stattgefunden.

    GEMESSEN am 2026-08-31 auf dem zweiten Spieltag (Bahn 3, Satz mit
    Sollsumme 218 laut der Ergebnistafel der Anlage):

        Wurf 17  F247487   3 Kegel   Tafel: 3,  Wurfnummer 17
        Wurf 18  F247898   1 Kegel   Tafel: unlesbar, Wurfnummer BLEIBT 17
        Wurf 19  F248578   1 Kegel   Tafel: 1,  Wurfnummer 18

    Der eingeschobene Wurf zeigte EINEN Kegel -- `discard_static_zero_cycles`
    verlangt null und konnte ihn nicht fassen. Der Satz kam dadurch auf 219
    Kegel in 31 Wuerfen statt 218 in 30.

    DIE GRENZE ZU BUG-008: Dort wurde bei nicht steigender Wurfnummer verworfen
    und das kostete 20 von 71 Wuerfen (28 %) -- weil die Nummer FEHLGELESEN
    war. Eine Fehllesung flackert; ein echter Stillstand ist ueber alle
    abgetasteten Frames felsenfest. Gemessen ueber 120 Frames je Wurf, alle
    zehn abgetastet, war der Stillstand beim Phantomwurf ausnahmslos derselbe
    Wert. Genau diese Einigkeit verlangt die Regel.
    """

    def test_stillstand_bei_hoher_einigkeit_verwirft(self, analyzer):
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=17,
                         throw_number_confidence=1.0)
        phantom = analyzer.analyze(make_event(trigger=400), make_pins((1,)),
                                   throw_number=17, throw_number_confidence=1.0)

        assert phantom is None, (
            "Die Tafel stand unveraendert auf 17 -- das war kein Wurf"
        )

    def test_die_kette_verrutscht_nicht(self, analyzer):
        """Der eigentliche Schaden war nicht der falsche Wurf, sondern der
        Versatz, den er hinterliess."""
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=17,
                         throw_number_confidence=1.0)
        analyzer.analyze(make_event(trigger=400), make_pins((1,)),
                         throw_number=17, throw_number_confidence=1.0)
        naechster = analyzer.analyze(make_event(trigger=800), make_pins((1,)),
                                     throw_number=18, throw_number_confidence=1.0)

        assert naechster.throw_number == 18

    def test_wackelige_lesung_verwirft_nichts(self, analyzer):
        """BUG-008 in einer Zeile: Eine Fehllesung darf keinen Wurf kosten."""
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=17,
                         throw_number_confidence=1.0)
        zweiter = analyzer.analyze(make_event(trigger=400), make_pins((1, 2)),
                                   throw_number=17, throw_number_confidence=0.4)

        assert zweiter is not None, (
            "Bei unsicherer Lesung bleibt der Wurf -- der Gruenzyklus hat "
            "bewiesen, dass geworfen wurde"
        )

    def test_ohne_angabe_wird_nie_verworfen(self, analyzer):
        """Wer die Einigkeit nicht kennt, darf nicht verwerfen."""
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=17)
        zweiter = analyzer.analyze(make_event(trigger=400), make_pins((1, 2)),
                                   throw_number=17)

        assert zweiter is not None

    def test_steigende_nummer_bleibt_unangetastet(self, analyzer):
        analyzer.analyze(make_event(), make_pins((1, 2, 3)), throw_number=17,
                         throw_number_confidence=1.0)
        zweiter = analyzer.analyze(make_event(trigger=400), make_pins((1,)),
                                   throw_number=18, throw_number_confidence=1.0)

        assert zweiter is not None and zweiter.throw_number == 18

    def test_abschaltbar(self, cfg):
        cfg.scoring.discard_cycles_without_throw_number = False
        a = ThrowAnalyzer(1, cfg)
        a.analyze(make_event(), make_pins((1, 2, 3)), throw_number=17,
                  throw_number_confidence=1.0)
        zweiter = a.analyze(make_event(trigger=400), make_pins((1,)),
                            throw_number=17, throw_number_confidence=1.0)

        assert zweiter is not None


class TestFehlwurfKennrtSpielgrenzen:
    """Ein Fehlwurf darf nicht im alten Spiel landen.

    GEMESSEN am 2026-08-31, zweiter Spieltag, Bahn 3:

        Wurf 30  F194771   Satz zu Ende
        Wurf 31  F201410   Fehlwurf, 4,4 Minuten spaeter
                           Tafel zeigt: throw_number = 1

    Die Tafel hatte laengst auf den ersten Wurf des naechsten Satzes
    zurueckgesetzt. Frueher zaehlte `analyze_zero_throw` blind fort
    (`_resolve_throw_number(None, ...)`) und war damit blind fuer Spielgrenzen.
    """

    def test_fehlwurf_mit_wurfnummer_eins_beginnt_ein_neues_spiel(self, cfg):
        a = ThrowAnalyzer(1, cfg)
        for n in range(1, 31):
            a.analyze(make_event(trigger=n * 500), make_pins((1, 2)),
                      throw_number=n)
        spiele = len(a.score.game_totals)

        a.analyze_zero_throw(200000, 8000.0, throw_number=1)

        assert len(a.score.game_totals) == spiele + 1, (
            "Die Tafel stand auf Wurf 1 -- der Fehlwurf gehoert ins neue Spiel"
        )

    def test_ohne_wurfnummer_wird_weiterhin_fortgezaehlt(self, cfg):
        """Ist die Nummer nicht lesbar, bleibt es beim alten Verhalten."""
        a = ThrowAnalyzer(1, cfg)
        a.analyze(make_event(), make_pins((1, 2)), throw_number=5)

        leer = a.analyze_zero_throw(1000, 40.0)

        assert leer.throw_number == 6


class TestSpielwechselIstKeinWurf:
    """Der Gruenzyklus, in dem die Anlage zuruecksetzt, ist kein Wurf.

    GEMESSEN am Spieltag 2026-08-22: Acht der neunzehn Nullwuerfe entstehen
    so. Im Log stehen sie unmittelbar untereinander:

        Bahn 4: Anzeige stand auf 000/0000 -- voriges Spiel endete mit 195
        Bahn 4: Wurf 1 erkannt -- 0 Kegel [], Gesamt 0, EMPTY

    Ueber die WURFNUMMER laesst sich das nicht fassen: Waehrend des
    Nullzustands ist sie nicht lesbar, und Schweigen darf nichts verwerfen
    (BUG-008). Das Spielwechsel-Zeichen sagt dagegen genau, was geschehen ist.
    """

    def _erster_wurf(self, analyzer):
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=30, foul_count=0)

    def test_nullwurf_beim_spielwechsel_wird_verworfen(self, cfg):
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=None, foul_count=None,
                                    display_reset=True)

        assert ergebnis is None

    def test_mit_kegeln_bleibt_der_wurf_auch_beim_spielwechsel(self, cfg):
        """Nur die LEERE Raute ist das Zuruecksetzen -- fallen Kegel, war es
        ein Wurf, egal was die Anzeige daneben tut."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins((1, 2)),
                                    throw_number=None, foul_count=None,
                                    display_reset=True)

        assert ergebnis is not None

    def test_tafelziffer_null_rettet_auch_hier(self, cfg):
        """Zeigt die Anlage eine 0, hat sie einen Fehlwurf registriert."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=None, foul_count=None,
                                    display_reset=True, displayed_count=0)

        assert ergebnis is not None

    def test_ohne_spielwechsel_greift_diese_regel_nicht(self, cfg):
        """Gegenprobe -- sonst waere der erste Test auch ohne die Regel gruen."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=2)
        self._erster_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=None, foul_count=None,
                                    display_reset=False)

        assert ergebnis is not None


class TestWurfnummerNullIstKeinWurf:
    """`discard_zero_throw_number` -- die staerkste der Nullwurf-Regeln.

    Seit BUG-020 haengt sie an der ZEITLICHEN EINIGKEIT
    (`throw_number_majority`), nicht mehr an der Bildguete der Ziffern.
    Deshalb geben diese Tests beides mit.

    Nutzerbeobachtung (2026-09-03): Die Anlage zaehlt die Wurfnummer hoch,
    BEVOR der Einschlag im Bild sichtbar wird. Umgekehrt zwingend: Solange sie
    000 zeigt, hat noch KEIN Wurf stattgefunden -- unabhaengig von Kegelzahl,
    Tafelziffer oder Spielwechsel-Erkennung.

    KORREKTUR (2026-09-03, voller Spieltag durchlaufen): Die vier Faelle, die
    diese Regel urspruenglich beheben sollte (die "21." eines 20-Wurf-
    Warmwerf-Blocks), zeigten GEMESSEN Wurfnummer 21, nicht 000 -- diese
    Regel hat im echten Lauf kein einziges Mal gegriffen. Sie bleibt trotzdem
    fuer ihren urspruenglichen Fall bestehen; die vier Warmwerf-Faelle deckt
    sind bis heute nicht behoben (BUG-018 wurde zurueckgebaut, siehe
    dessen SKILL.md).
    """

    def _zwanzig_wuerfe(self, analyzer):
        for nummer in range(1, 21):
            analyzer.analyze(make_event(trigger=nummer * 100),
                             make_pins((1, 2, 3)), throw_number=nummer,
                             foul_count=0)

    def test_wurfnummer_null_wird_verworfen(self, cfg):
        """Der Kern: 000 nach einer langen Kette wird nicht zu 'Wurf 21'."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._zwanzig_wuerfe(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=2100), make_pins(()),
                                    throw_number=0, throw_number_confidence=1.0,
                                    throw_number_majority=(0, 1.0),
                                    total_majority=(0, 1.0))

        assert ergebnis is None

    def test_zaehlung_bleibt_unberuehrt(self, cfg):
        """Der verworfene Zyklus darf die Wurfnummernkette nicht verschieben.

        Der naechste ECHTE Wurf (throw_number=1, neues Spiel) muss weiterhin
        korrekt als Wurf 1 ankommen -- nicht als 'Wurf 22' oder aehnliches.
        """
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._zwanzig_wuerfe(analyzer)
        analyzer.analyze(make_event(trigger=2100), make_pins(()),
                         throw_number=0, throw_number_confidence=1.0,
                         throw_number_majority=(0, 1.0),
                         total_majority=(0, 1.0))

        ergebnis = analyzer.analyze(make_event(trigger=2200),
                                    make_pins((1, 2, 3, 4, 5, 6, 7)),
                                    throw_number=1, throw_number_confidence=1.0)

        assert ergebnis is not None
        assert ergebnis.throw_number == 1

    def test_mit_kegeln_bleibt_der_wurf_trotz_wurfnummer_null(self, cfg):
        """Liegen Kegel, bleibt der Wurf -- SEIT BUG-032.

        Hier stand bis zum 2026-09-18 das Gegenteil: *"Die Regel ist bewusst
        absolut: throw_number==0 heisst IMMER kein Wurf, unabhaengig von der
        Kegelzahl."* Der Spieltagslauf hat das widerlegt.

        Bahn 5, Spiel 5, Frame 71033: Sechs Kegel fielen sichtbar um, die
        Kegelziffer zeigte 6, die Summe des naechsten Wurfs bestaetigte 6 --
        und der Wurf wurde verworfen, weil Wurfnummer und Summe auf 000/0000
        standen. Genau das tun sie beim ERSTEN Wurf eines Spiels: Die Anlage
        hat ihn noch nicht gebucht (dieselbe Verspaetung wie BUG-010). Die
        beiden Zeugen sind also getrennt gelesen und trotzdem abhaengig -- sie
        schweigen aus demselben Grund.

        GEMESSEN ueber alle 18 Verwerfungen dieser Regel im Lauf vom
        2026-09-18, gegen die Lampenspur: 17 mal fiel nichts um (zu Recht
        verworfen), einmal fielen sechs Kegel. Die Kegelraute trennt die
        Faelle vollstaendig.
        """
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._zwanzig_wuerfe(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=2100),
                                    make_pins((1, 2)),
                                    throw_number=0, throw_number_confidence=1.0,
                                    throw_number_majority=(0, 1.0),
                                    total_majority=(0, 1.0))

        assert ergebnis is not None, (
            "Liegen am Ende des Zyklus Kegel, ist etwas umgefallen -- die "
            "Anzeige darf das nicht ueberstimmen (BUG-032)"
        )
        assert any("BUG-032" in d for d in ergebnis.evidence.decisions), (
            "Der knapp vermiedene Verwurf gehoert in den Beweis (P1)"
        )

    def test_ohne_kegel_wird_weiter_verworfen(self, cfg):
        """Die Gegenprobe: Der eigentliche Zweck der Regel bleibt.

        Ohne diesen Test waere nicht belegt, dass BUG-032 die Regel nur
        einschraenkt und nicht abschaltet -- sie griff an einem Spieltag
        17 von 18 Mal richtig.
        """
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._zwanzig_wuerfe(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=2100), make_pins(()),
                                    throw_number=0, throw_number_confidence=1.0,
                                    throw_number_majority=(0, 1.0),
                                    total_majority=(0, 1.0))

        assert ergebnis is None

    def test_schalter_stellt_das_alte_verhalten_her(self, cfg):
        """`discard_zero_requires_empty_diamond: false` -- ohne Codeaenderung."""
        cfg.scoring.discard_zero_requires_empty_diamond = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._zwanzig_wuerfe(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=2100),
                                    make_pins((1, 2)),
                                    throw_number=0, throw_number_confidence=1.0,
                                    throw_number_majority=(0, 1.0),
                                    total_majority=(0, 1.0))

        assert ergebnis is None

    def _ein_wurf(self, analyzer):
        """Nur EIN vorheriger Wurf -- nicht zwanzig.

        Wichtig fuer die beiden folgenden Tests: Bei `last >= 10`
        (`game_reset_after`) naehme `_resolve_throw_number` fuer throw_number=0
        den Ruecksprung-Pfad, riefe `start_new_game()` auf und setzte
        `last_throw_number` selbst auf 0 -- danach crasht `self.score.record`
        an "0 ist nicht groesser als 0", VOELLIG unabhaengig von dieser Regel.
        Mit nur einem Vorwurf bleibt der harmlose Fallback-Pfad (`last + 1`),
        und der Test prueft wirklich nur `discard_zero_throw_number`.
        """
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1, foul_count=0)

    def test_niedrige_einigkeit_verwirft_nichts(self, cfg):
        """Schutz gegen Fehllesung: Eine unsichere '0' koennte eine falsch
        gelesene andere Zahl sein. Nur eine EINIGE Lesung darf verwerfen --
        dieselbe Lehre wie bei `discard_cycles_without_throw_number`.

        `displayed_count=9` (die nachleuchtende alte Ziffer) haelt den
        AELTEREN Filter `discard_zero_without_digit` davon ab, hier
        einzugreifen -- der haelt "es gibt eine Ziffer" fuer einen
        ausreichenden Zeugen, ohne ihre Einigkeit zu pruefen. Damit testet
        dieser Fall wirklich nur `discard_zero_throw_number`.
        """
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._ein_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=0, throw_number_confidence=0.3,
                                    throw_number_majority=(0, 0.3),
                                    displayed_count=9)

        assert ergebnis is not None

    def test_abschaltbar(self, cfg):
        """Zeigt zugleich, warum diese Regel staerker ist als die aeltere:
        Mit `displayed_count=9` (Nachleuchten) wuerde `discard_zero_without_digit`
        HIER NICHT verwerfen -- sie haelt die falsche alte Ziffer fuer einen
        gueltigen Zeugen. Nur `discard_zero_throw_number` durchschaut das.
        """
        cfg.scoring.discard_zero_throw_number = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._ein_wurf(analyzer)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=0, throw_number_confidence=1.0,
                                    throw_number_majority=(0, 1.0),
                                    displayed_count=9)

        assert ergebnis is not None


class TestVerdeckungImFenster:
    """`discard_occluded_zero_throws` (BUG-017).

    Nutzerbeobachtung (2026-09-03): "koennte man Live nicht Personen
    detektieren, und wenn ein Mensch 'durch' die Gruenphase laeuft...".

    GEMESSEN an drei Faellen (Bahn5 F15569, Bahn5 F16256, Bahn2 F265724):
    Der rohe Gruen-Score faellt in allen dreien irgendwo im Fenster auf
    exakt 0.0 -- die Kamera sieht die Tafel schlicht nicht mehr, waehrend
    eine Person davorsteht. Alle drei wurden als "0 Kegel, EMPTY" gebucht.
    """

    def test_verdeckung_mit_null_kegeln_wird_verworfen(self, analyzer):
        """Der Kern: 0 Kegel waehrend einer Verdeckung ist keine Messung."""
        ergebnis = analyzer.analyze(make_event(), make_pins(()),
                                    displayed_count=0, throw_number=1,
                                    window_was_occluded=True)

        assert ergebnis is None, (
            "Auch eine scheinbar bestaetigende Tafelziffer (0) darf hier "
            "nicht durchgreifen -- waehrend der Verdeckung koennte auch sie "
            "korrumpiert sein. Die Verdeckung entscheidet zuerst."
        )

    def test_ohne_verdeckung_bleibt_der_wurf_gueltig(self, analyzer):
        """Gegenprobe: Derselbe Fall ohne Verdeckung bleibt ein normaler
        Leerwurf."""
        ergebnis = analyzer.analyze(make_event(), make_pins(()),
                                    displayed_count=0, throw_number=1,
                                    window_was_occluded=False)

        assert ergebnis is not None
        assert ergebnis.status is ThrowStatus.EMPTY

    def test_verdeckung_mit_kegeln_bleibt_gueltig(self, analyzer):
        """Beschraenkt auf 0 Kegel: Fallen trotz Verdeckung Kegel, ist das
        kein Widerspruch, sondern ein zusaetzlicher Beleg."""
        ergebnis = analyzer.analyze(make_event(), make_pins((1, 2, 3)),
                                    throw_number=1, window_was_occluded=True)

        assert ergebnis is not None
        assert ergebnis.pins_count == 3

    def test_zaehlung_bleibt_unberuehrt(self, cfg):
        """Der verworfene Zyklus darf die Wurfnummernkette nicht verschieben."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1)
        analyzer.analyze(make_event(trigger=200), make_pins(()),
                         displayed_count=0, throw_number=2,
                         window_was_occluded=True)

        ergebnis = analyzer.analyze(make_event(trigger=300),
                                    make_pins((4, 5)), throw_number=2)

        assert ergebnis is not None
        assert ergebnis.throw_number == 2, (
            "Der verworfene Zyklus hat keine Wurfnummer verbraucht -- der "
            "naechste echte Wurf ist wieder Wurf 2."
        )

    def test_abschaltbar(self, cfg):
        cfg.scoring.discard_occluded_zero_throws = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)

        ergebnis = analyzer.analyze(make_event(), make_pins(()),
                                    displayed_count=0, throw_number=1,
                                    window_was_occluded=True)

        assert ergebnis is not None


class TestVerworfenerSpielwechselVerschiebtDieKette:
    """BUG-019: Ein verworfener Zyklus, der zugleich der Spielwechsel war,
    stellt die ALTE Wurfnummer wieder her -- der neue Satz zaehlt weiter.

    GEMESSEN am Spieltag 2026-09-03 (`lauf_2026-09-03_16-51-04`), Bahn 4:

        Spiel  3   Wurfnummern  1-30    korrekt
        Spiel  4   Wurfnummern 31-60    falsch, sollte 1-30 sein
        Spiel  5   Wurfnummern 61-90    falsch
        Spiel 11   Wurfnummern 31-60    falsch

    Alle drei falschen folgen im Log unmittelbar auf ein "Gruenzyklus ...
    faellt mit dem Spielwechsel zusammen ... Wird verworfen", die korrekten
    nicht. Insgesamt 5 von 64 Spielen ueber alle Bahnen betroffen.

    Die Wiederherstellung von `_last_throw_number` ist fuer eine STOERUNG
    mitten im Spiel richtig -- aber wenn im selben Aufruf ein Spielwechsel
    gebucht wurde, gehoert der wiederhergestellte Stand zum ALTEN Spiel und
    ist danach bedeutungslos: Das neue Spiel beginnt bei 1.
    """

    def _dreissig_wuerfe(self, analyzer):
        for nummer in range(1, 31):
            analyzer.analyze(make_event(trigger=nummer * 100),
                             make_pins((1, 2, 3)), throw_number=nummer,
                             foul_count=0)

    def test_neuer_satz_beginnt_bei_eins(self, cfg):
        """Der Kern: Nach verworfenem Spielwechsel-Zyklus beginnt der naechste
        Satz bei Wurf 1 -- auch wenn dessen Wurfnummer unlesbar ist."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._dreissig_wuerfe(analyzer)

        # Der Spielwechsel-Zyklus: Anzeige auf 000/0000, 0 Kegel, keine
        # Ziffer -- wird von `discard_zero_without_digit` verworfen.
        verworfen = analyzer.analyze(make_event(trigger=3100), make_pins(()),
                                     display_reset=True, foul_count=0)
        assert verworfen is None, "Vorbedingung: Der Zyklus wird verworfen"

        # Erster echter Wurf des neuen Satzes -- Wurfnummer nicht lesbar.
        ergebnis = analyzer.analyze(make_event(trigger=3200),
                                    make_pins((1, 2, 3, 4, 7, 8, 9)),
                                    throw_number=None, foul_count=0)

        assert ergebnis is not None
        assert ergebnis.throw_number == 1, (
            "Nach einem gebuchten Spielwechsel beginnt die Zaehlung neu. "
            "Der wiederhergestellte Stand (30) gehoert zum alten Spiel."
        )

    def test_stoerung_ohne_spielwechsel_stellt_wieder_her(self, cfg):
        """Gegenprobe: OHNE Spielwechsel bleibt die Wiederherstellung richtig.

        Genau dafuer wurde sie gebaut -- ein verworfener Stoerzyklus darf die
        Wurfnummernkette nicht verschieben.
        """
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        for nummer in range(1, 6):
            analyzer.analyze(make_event(trigger=nummer * 100),
                             make_pins((1, 2, 3)), throw_number=nummer,
                             foul_count=0)

        # Stoerzyklus mitten im Spiel: 0 Kegel, keine Ziffer, Wurfnummer
        # unveraendert -- wird verworfen, KEIN Spielwechsel.
        verworfen = analyzer.analyze(make_event(trigger=600), make_pins(()),
                                     throw_number=5, foul_count=0)
        assert verworfen is None, "Vorbedingung: Der Zyklus wird verworfen"

        ergebnis = analyzer.analyze(make_event(trigger=700),
                                    make_pins((4, 5)), throw_number=None,
                                    foul_count=0)

        assert ergebnis is not None
        assert ergebnis.throw_number == 6, (
            "Ohne Spielwechsel zaehlt die Kette normal weiter -- der "
            "verworfene Zyklus hat keine Nummer verbraucht."
        )


class TestEinigkeitStattBildguete:
    """BUG-020: `discard_zero_throw_number` konnte strukturell nie greifen.

    GEMESSEN am 2026-09-04, Bahn 4, Sperrzyklus F126593 (10 Sample-Frames):

        alle zehn Frames lasen '0','0','0'    -> voellig einig
        Scores der fuehrenden Stellen: 0,35   -> unter `min_confidence` 0,5

    Jede einzelne Stimme fiel an der Confidence-Schwelle durch, das Feld
    wurde `None`, und die Regel sah nie eine 0. Die Schwelle
    `throw_number_min_confidence` (0,9) haette sie zusaetzlich blockiert: Das
    Aggregat meldet die BILDGUETE der schwaechsten Stelle (0,35), nicht die
    zeitliche Einigkeit (1,00).

    Die Regel bekommt jetzt die Einigkeit -- genau das, was ihr Kommentar
    immer schon meinte: "Eine Fehllesung flackert; ein echter Stillstand ist
    ueber alle abgetasteten Frames hinweg felsenfest."
    """

    def test_einige_null_wird_verworfen(self, cfg):
        """Der Kern: Zehn einige Frames mit '000' verwerfen den Zyklus --
        auch wenn die Ziffern schwach zu lesen waren."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1, foul_count=0)

        ergebnis = analyzer.analyze(
            make_event(trigger=200), make_pins(()),
            # Genau die Lage im Messfenster: das Feld ist unlesbar (None),
            # die Frames sind sich aber einig, dass dort 0 steht.
            throw_number=None, throw_number_confidence=0.0,
            throw_number_majority=(0, 1.0), total_majority=(0, 1.0),
            displayed_count=9)

        assert ergebnis is None

    def test_uneinige_null_verwirft_nichts(self, cfg):
        """BUG-008-Schutz: Streuen die Frames, wird nichts verworfen."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1, foul_count=0)

        ergebnis = analyzer.analyze(
            make_event(trigger=200), make_pins(()),
            throw_number=None, throw_number_majority=(0, 0.6),
            displayed_count=9)

        assert ergebnis is not None, (
            "0,6 liegt unter throw_number_min_agreement (0,9) -- eine "
            "flackernde Lesung darf keinen Wurf verwerfen."
        )

    def test_einige_andere_zahl_verwirft_nichts(self, cfg):
        """Nur die 0 verwirft. Eine einige 3 ist ein ganz normaler Wurf --
        die Gegenprobe gegen die Verwechslung 003/008/009 mit 000."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1, foul_count=0)

        for nummer in (3, 8, 9):
            ergebnis = analyzer.analyze(
                make_event(trigger=200 + nummer), make_pins((4, 5)),
                throw_number=nummer, throw_number_majority=(nummer, 1.0))
            assert ergebnis is not None, f"Wurf {nummer} darf nicht verworfen werden"

    def test_ohne_mehrheit_verwirft_nichts(self, cfg):
        """Standardwert (None, 0.0): Wer nichts weiss, verwirft nichts."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1, foul_count=0)

        ergebnis = analyzer.analyze(make_event(trigger=200), make_pins(()),
                                    throw_number=None, displayed_count=9)

        assert ergebnis is not None


class TestNeunWirdNichtZurNull:
    """Q16: Die 9 wird an der Einerstelle systematisch als 0 gelesen.

    GEMESSEN am 2026-09-04 an acht echten Neunern ueber alle vier Bahnen:

        Bahn 3, Wurf 9  ->  ('0','3','0')   Einigkeit 1,00   Summe 71
        Bahn 4, Wurf 9  ->  ('0','1','0')   Einigkeit 1,00   Summe unlesbar

    Zwei von acht (25 %) las der Detektor an der Einerstelle als 0 -- in
    zehn von zehn Frames. Zeitliche Einigkeit hilft dagegen NICHT: Sie
    schuetzt gegen Flackern, nicht gegen systematische Fehllesung.

    Der Nutzer wies darauf hin ("ein 9 als 30 ist durchaus sehr nah an 00").
    Beide Faelle entgingen der Regel nur, weil die ZEHNERSTELLE ebenfalls
    falsch war -- Zufall, keine Konstruktion. Deshalb verlangt die Regel
    jetzt die SUMME als zweiten, unabhaengigen Zeugen: Beim Spielwechsel
    steht "000 0000", ein echter Wurf hat eine Summe ueber null.
    """

    def _ein_wurf(self, analyzer):
        analyzer.analyze(make_event(trigger=100), make_pins((1, 2, 3)),
                         throw_number=1, foul_count=0)

    def test_falsch_gelesene_null_mit_summe_bleibt_ein_wurf(self, cfg):
        """Der Kern: Wurfnummer faelschlich 0, aber die Summe steht auf 71 --
        das ist ein echter Wurf und darf nicht verworfen werden."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._ein_wurf(analyzer)

        ergebnis = analyzer.analyze(
            make_event(trigger=200), make_pins((1, 2, 3, 4, 5, 6, 7, 8, 9)),
            throw_number=None, throw_number_majority=(0, 1.0),
            total_majority=(71, 1.0))

        assert ergebnis is not None, (
            "Eine gelesene 0 allein darf keinen Wurf verwerfen -- die Summe "
            "belegt, dass gespielt wurde."
        )
        assert ergebnis.pins_count == 9

    def test_unlesbare_summe_verwirft_nichts(self, cfg):
        """Schweigen der Summe ist kein Beleg fuer den Nullzustand (BUG-008)."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._ein_wurf(analyzer)

        ergebnis = analyzer.analyze(
            make_event(trigger=200), make_pins(()),
            throw_number=None, throw_number_majority=(0, 1.0),
            total_majority=(None, 0.0), displayed_count=9)

        assert ergebnis is not None

    def test_beide_felder_null_verwirft(self, cfg):
        """Der echte Spielwechsel: Nummer UND Summe stehen auf null."""
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._ein_wurf(analyzer)

        ergebnis = analyzer.analyze(
            make_event(trigger=200), make_pins(()),
            throw_number=None, throw_number_majority=(0, 1.0),
            total_majority=(0, 1.0), displayed_count=9)

        assert ergebnis is None

    def test_absicherung_abschaltbar(self, cfg):
        """Ohne Summen-Absicherung genuegt die Wurfnummer -- der Zustand vor
        Q16. Bewusst abschaltbar, um die Wirkung messen zu koennen."""
        cfg.scoring.discard_zero_requires_zero_total = False
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._ein_wurf(analyzer)

        ergebnis = analyzer.analyze(
            make_event(trigger=200), make_pins(()),
            throw_number=None, throw_number_majority=(0, 1.0),
            total_majority=(71, 1.0), displayed_count=9)

        assert ergebnis is None


class TestVerworfenerZyklusBehaeltDenSpielwechsel:
    """Der verworfene Zyklus ist genau der, der das Spielwechsel-Zeichen traegt.

    GEMESSEN am 2026-09-04 (Teillauf F110000-230000, Bahn 4): Die 000/0000-
    Regel stand zunaechst VOR `_resolve_throw_number` und brach dort ab.
    Damit rief niemand `start_new_game()`, das Zeichen `display_reset`
    verfiel, und zwei Saetze wuchsen zu einem zusammen:

        F183107  Wurf 30      <- Satzende
        F186293  Wurf 31      <- haette Wurf 1 eines neuen Spiels sein muessen

    Kein Unit-Test hatte das erfasst -- erst der Lauf zeigte es. Deshalb
    dieser hier.
    """

    def _fuenf_wuerfe(self, analyzer):
        for nummer in range(1, 6):
            analyzer.analyze(make_event(trigger=nummer * 100),
                             make_pins((1, 2, 3)), throw_number=nummer,
                             foul_count=0)

    def test_spielwechsel_ueberlebt_das_verwerfen(self, cfg):
        analyzer = ThrowAnalyzer(lane_id=1, cfg=cfg, display_number=4)
        self._fuenf_wuerfe(analyzer)
        spiele_vorher = len(analyzer.score.game_totals)

        # Der Zyklus, in dem der Spielwechsel ankommt: Anzeige auf 000/0000.
        verworfen = analyzer.analyze(
            make_event(trigger=600), make_pins(()), display_reset=True,
            throw_number=None, throw_number_majority=(0, 1.0),
            total_majority=(0, 1.0), foul_count=0)
        assert verworfen is None, "Vorbedingung: Der Zyklus wird verworfen"
        assert len(analyzer.score.game_totals) == spiele_vorher + 1, (
            "Der Spielwechsel muss trotz des Verwerfens gebucht sein -- sonst "
            "wachsen zwei Saetze zu einem zusammen."
        )

        # Der erste echte Wurf des neuen Satzes, Wurfnummer unlesbar.
        ergebnis = analyzer.analyze(make_event(trigger=700),
                                    make_pins((1, 2, 3, 4, 5, 6, 7, 8)),
                                    throw_number=None, foul_count=0)

        assert ergebnis is not None
        assert ergebnis.throw_number == 1, (
            "Nach dem gebuchten Spielwechsel beginnt die Zaehlung neu."
        )
