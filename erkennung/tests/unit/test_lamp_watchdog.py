"""Tests des Wachhunds gegen den lautlosen Lampenausfall.

Der Anlass steht in `src/kegel_cv/analysis/lamp_watchdog.py`: Ein Lauf ueber 67
Wuerfe buchte auf allen vier Bahnen "0 Kegel", weil eine alte Kalibrierung zu
grosse Lampen-ROIs mitbrachte. Nichts hat gewarnt.
"""

from __future__ import annotations

import logging

import pytest

from kegel_cv.analysis.lamp_watchdog import LampWatchdog
from kegel_cv.models.throw import ThrowResult, ThrowStatus


def wurf(lane: int, kegel: int, angezeigt: int | None,
         nummer: int = 1) -> ThrowResult:
    """Baut einen Wurf mit Lampenzahl und angezeigter Ziffer."""
    return ThrowResult(
        lane=lane, throw_number=nummer, throw_number_in_series=nummer,
        pins=tuple(range(1, kegel + 1)), pins_count=kegel,
        displayed_pin_count=angezeigt,
        status=ThrowStatus.VALID if kegel else ThrowStatus.EMPTY,
        running_total=0,
    )


class TestSchwelle:
    def test_meldet_erst_ab_der_schwelle(self):
        w = LampWatchdog(threshold=5)
        for i in range(4):
            assert w.observe(wurf(2, 0, 9, i + 1)) is None, \
                "vier Widersprueche sind noch kein Beweis"
        meldung = w.observe(wurf(2, 0, 9, 5))
        assert meldung is not None
        assert "Bahn 2" in meldung

    def test_meldet_nur_einmal_je_bahn(self):
        """Sonst stuende die Meldung in jeder weiteren Zeile und ginge unter."""
        w = LampWatchdog(threshold=2)
        assert w.observe(wurf(2, 0, 9)) is None
        assert w.observe(wurf(2, 0, 9)) is not None
        assert w.observe(wurf(2, 0, 9)) is None
        assert w.observe(wurf(2, 0, 9)) is None

    def test_jede_bahn_wird_getrennt_gezaehlt(self):
        """P6: Die Bahnen sind unabhaengig, auch beim Melden von Fehlern."""
        w = LampWatchdog(threshold=2)
        assert w.observe(wurf(2, 0, 9)) is None
        assert w.observe(wurf(3, 0, 9)) is None
        assert w.observe(wurf(2, 0, 9)) is not None, "Bahn 2 ist voll"
        assert w.observe(wurf(3, 0, 9)) is not None, "Bahn 3 unabhaengig davon"

    def test_schwelle_null_wird_abgelehnt(self):
        with pytest.raises(ValueError, match="threshold"):
            LampWatchdog(threshold=0)


class TestWasNichtZaehlt:
    def test_eine_einzige_lampe_setzt_zurueck(self):
        """Meldet die Bahn auch nur einen Kegel, sitzen die ROIs."""
        w = LampWatchdog(threshold=3)
        w.observe(wurf(2, 0, 9))
        w.observe(wurf(2, 0, 9))
        assert w.streak(2) == 2
        w.observe(wurf(2, 1, 1))
        assert w.streak(2) == 0
        w.observe(wurf(2, 0, 9))
        w.observe(wurf(2, 0, 9))
        assert w.observe(wurf(2, 0, 9)) is not None

    def test_echter_leerwurf_zaehlt_nicht(self):
        """Lampen 0 UND Anzeige 0 ist eine Pumpe -- ein regulaeres Ergebnis.

        Genau hier haette eine naive Pruefung ("viele Nullwuerfe") Fehlalarm
        geschlagen. Gemeldet wird nur der WIDERSPRUCH zweier Quellen.
        """
        w = LampWatchdog(threshold=2)
        for _ in range(10):
            assert w.observe(wurf(2, 0, 0)) is None
        assert w.streak(2) == 0

    def test_fehlende_ziffer_zaehlt_weder_noch(self):
        """Ohne zweite Quelle gibt es keinen Widerspruch -- und kein Urteil."""
        w = LampWatchdog(threshold=2)
        w.observe(wurf(2, 0, 9))
        assert w.streak(2) == 1
        for _ in range(5):
            assert w.observe(wurf(2, 0, None)) is None
        assert w.streak(2) == 1, "unveraendert -- weder gezaehlt noch geloescht"

    def test_mehr_lampen_als_ziffern_ist_ein_raeumwurf(self):
        """Diese Richtung meldet er NICHT -- sonst schwaerzt er jeden
        Raeumwurf an.

        Beim Raeumen zeigen die Lampen ALLE liegenden Kegel, die Tafel nur die
        dieses Wurfs. GEMESSEN: vier Wuerfe mit neun leuchtenden Lampen gegen
        Ziffer 1, 2, 3 und 4 -- die Ziffer hatte jedes Mal recht.
        """
        w = LampWatchdog(threshold=2)
        for _ in range(10):
            assert w.observe(wurf(2, 9, 3)) is None


class TestZuWenigeLampen:
    """ERWEITERT am 2026-09-08 nach einem verlorenen Trainingsabend.

    Der erste Entwurf schlug nur bei NULL Lampen an -- so sah der Ausfall vom
    2026-09-07 aus. Am naechsten Abend sah derselbe Defekt anders aus:

        Lampen 5, Tafel 8 | Lampen 3, Tafel 8 | Lampen 2, Tafel 7

    Eine einzige leuchtende Lampe setzte den Zaehler zurueck, und der Wachhund
    schwieg den ganzen Abend -- obwohl in jeder zweiten Zeile ein Widerspruch
    stand. Ursache war eine Konfiguration, deren Waermeschranke leuchtende
    Lampen verwarf.
    """

    def test_dauerhaft_zu_wenige_lampen_werden_gemeldet(self):
        w = LampWatchdog(threshold=3)
        assert w.observe(wurf(3, 5, 8)) is None
        assert w.observe(wurf(3, 3, 8)) is None
        meldung = w.observe(wurf(3, 2, 7))
        assert meldung is not None
        assert "Lampen 2" in meldung and "Anzeigetafel 7" in meldung

    def test_eine_uebereinstimmung_setzt_zurueck(self):
        """Stimmt es einmal, funktioniert die Messung grundsaetzlich."""
        w = LampWatchdog(threshold=3)
        w.observe(wurf(3, 5, 8))
        w.observe(wurf(3, 3, 8))
        assert w.observe(wurf(3, 9, 9)) is None
        assert w.streak(3) == 0

    def test_die_meldung_nennt_die_schwellen_als_verdacht(self):
        w = LampWatchdog(threshold=1)
        meldung = w.observe(wurf(3, 5, 8))
        assert "Waermeschranke" in meldung
        assert "Konfiguration" in meldung


class TestMeldung:
    def test_nennt_die_wahrscheinliche_ursache(self):
        w = LampWatchdog(threshold=1)
        meldung = w.observe(wurf(4, 0, 8))
        assert "KALIBRIERUNG" in meldung.upper()
        assert "0,040" in meldung, "die Sollgroesse gehoert in die Meldung"
        assert "Bahn 4" in meldung

    def test_schreibt_als_error_ins_log(self, caplog):
        """WARNING geht in einem langen Lauf unter -- das hier ist ein Ausfall."""
        w = LampWatchdog(threshold=1)
        with caplog.at_level(logging.WARNING):
            assert w.observe_and_log(wurf(2, 0, 9)) is True
        assert any(s.levelno == logging.ERROR for s in caplog.records)

    def test_ohne_befund_kein_log(self, caplog):
        w = LampWatchdog(threshold=5)
        with caplog.at_level(logging.WARNING):
            assert w.observe_and_log(wurf(2, 0, 9)) is False
        assert not caplog.records


class TestAmEchtenFall:
    def test_der_lauf_vom_2026_09_07_haette_gewarnt(self):
        """Nachgestellt aus `wuerfe.csv` des fehlerhaften Laufs.

        Dort meldeten die Bahnen 2, 3, 4 und 5 zwischen 12 und 17 Wuerfe in
        Folge null Lampen bei einer Anzeige groesser null. Bei Schwelle 5 muss
        jede Bahn anschlagen, und zwar lange vor dem Ende des Laufs.
        """
        w = LampWatchdog(threshold=5)
        serien = {2: 17, 3: 16, 4: 12, 5: 16}
        gemeldet = {}
        for bahn, laenge in serien.items():
            for i in range(laenge):
                if w.observe(wurf(bahn, 0, 9, i + 1)) is not None:
                    gemeldet[bahn] = i + 1
        assert set(gemeldet) == {2, 3, 4, 5}, "jede Bahn muss anschlagen"
        assert all(n == 5 for n in gemeldet.values()), \
            f"und zwar beim fuenften Wurf, nicht spaeter: {gemeldet}"

    def test_der_gesunde_lauf_haette_geschwiegen(self):
        """Im Lauf vom 2026-09-04 (1677 Wuerfe) war die laengste Serie 1."""
        w = LampWatchdog(threshold=5)
        for i in range(1677):
            # Alle 800 Wuerfe ein einzelner Widerspruch, wie gemessen.
            widerspruch = i in (400, 1200)
            wurf_ = wurf(2, 0, 9, i + 1) if widerspruch else wurf(2, 6, 6, i + 1)
            assert w.observe(wurf_) is None
