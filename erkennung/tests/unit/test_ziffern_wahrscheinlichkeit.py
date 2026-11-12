"""Wahrscheinlichkeiten je Ziffer statt einer Liste ohne Rangfolge.

DIE IDEE (Nutzer, 2026-09-15): *"jede Ziffer gibt an, zu 0,1% eine 1, zu 5,2%
eine 2 usw. und zu 85% eine 9 -- dann könnten wir uns immer die top Kandidaten
anschauen und daraus Rückschlüsse ziehen."*

Anlass war eine Frage, auf die es keine gute Antwort gab: *"Warum kann ich die
Ziffern in dem GIF so sauber erkennen aber unser Modell nicht? Ich finde die
Ziffern sind so glasklar, da gibt es keine 2 Möglichkeiten."* -- Die Antwort
stand in `debug/warum_falsch.png`: Das Modell sieht die Ziffer, es entscheidet
nur falsch.
"""

from __future__ import annotations

from kegel_cv.detection.digit_reader import (SEGMENT_ORDER,
                                             segment_probabilities)

SKALA = 0.04        # detection.digits.segment_probability_scale


def fills(**werte: float) -> list[float]:
    """Füllgrade in der Reihenfolge a b c d e f g."""
    return [werte.get(name, 0.0) for name in SEGMENT_ORDER]


class TestDerFallDerZurAenderungFuehrte:
    """GEMESSEN auf Bahn 4, F5400, letzte Stelle. Im Bild zweifelsfrei eine 9
    (`debug/warum_falsch.png`). Das Muster `abcg` steht in keiner Tabelle.

    Im Hamming-Abstand 1 liegen ZWEI Ziffern:

        3 (abcdg)   d müsste an   -- d = 0,000, also 0,31 von der Schwelle
        9 (abcfg)   f müsste an   -- f = 0,182, also 0,13 von der Schwelle

    Die alte Suche sah da keinen Unterschied und nahm die, die in der Tabelle
    früher steht: die 3. Die Ziffer wurde von einer Dictionary-Reihenfolge
    entschieden.
    """

    MESSUNG = fills(a=0.885, b=0.668, c=0.853, d=0.000, e=0.007, f=0.182,
                    g=0.853)
    SCHWELLE = 0.310

    def test_die_neun_gewinnt_deutlich(self):
        p = segment_probabilities(self.MESSUNG, self.SCHWELLE, SKALA)
        assert max(p, key=p.get) == 9
        assert p[9] > 0.9

    def test_die_drei_ist_praktisch_ausgeschlossen(self):
        p = segment_probabilities(self.MESSUNG, self.SCHWELLE, SKALA)
        assert p.get(3, 0.0) < 0.05
        assert p[9] > 20 * p.get(3, 0.0)


class TestWasEineWahrscheinlichkeitLeistet:
    def test_ein_klares_muster_ist_fast_sicher(self):
        """Eine 1: nur b und c leuchten, alles andere weit darunter."""
        p = segment_probabilities(
            fills(b=0.86, c=0.86), 0.30, SKALA)
        assert max(p, key=p.get) == 1
        assert p[1] > 0.99

    def test_ein_patt_zwischen_zwei_ziffern_sieht_auch_wie_eines_aus(self):
        """Der Fall aus BUG-009: "bcfg" (4) und "abcfg" (9) unterscheiden sich
        in genau einem Segment. Liegt dieses Segment auf der Schwelle, ist die
        Ziffer nicht bestimmbar -- und das muss man dem Ergebnis ansehen."""
        auf_kante = segment_probabilities(
            fills(a=0.30, b=0.80, c=0.80, d=0.00, e=0.00, f=0.70, g=0.80),
            0.30, SKALA)
        zwei_besten = sorted(auf_kante.items(), key=lambda wp: -wp[1])[:2]
        assert {w for w, _ in zwei_besten} == {4, 9}
        assert abs(zwei_besten[0][1] - zwei_besten[1][1]) < 0.05

    def test_ein_wackliges_segment_macht_die_ziffer_nicht_zwingend_unklar(self):
        """GEMESSEN auf Bahn 4, letzte Stelle, F5695-6000: Segment b lag bei
        0,300 gegen eine Schwelle von 0,301 -- ein echter Münzwurf.

        Trotzdem bleibt die Ziffer klar, denn beim Umkippen von b entsteht
        KEINE andere gültige Ziffer: "abcdg" ist die 3, "acdg" steht in keiner
        Tabelle. Genau das ist der Gewinn gegenüber einer Kandidatenliste --
        sie hätte hier zwei Möglichkeiten gemeldet, wo es nur eine gibt."""
        p = segment_probabilities(
            fills(a=0.86, b=0.301, c=0.84, d=0.81, e=0.02, f=0.18, g=0.84),
            0.301, SKALA)
        assert max(p, key=p.get) == 3
        assert p[3] > 0.85

    def test_die_summe_ist_eins(self):
        p = segment_probabilities(
            fills(a=0.5, b=0.5, c=0.5, d=0.5, e=0.5, f=0.5, g=0.5), 0.5, SKALA)
        assert abs(sum(p.values()) - 1.0) < 1e-9

    def test_ohne_messung_gibt_es_nichts_zu_rechnen(self):
        assert segment_probabilities([], 0.3, SKALA) == {}
        assert segment_probabilities(fills(a=0.5), 0.3, 0.0) == {}

    def test_beide_schreibweisen_der_neun_zaehlen_zusammen(self):
        """Diese Anlage zeichnet die 9 mit und ohne unteren Querbalken
        (BUG-009). Beide Muster sind dieselbe Ziffer -- ihre
        Wahrscheinlichkeiten müssen sich addieren, nicht konkurrieren."""
        # d genau auf der Kante: beide Schreibweisen etwa gleich stark
        p = segment_probabilities(
            fills(a=0.86, b=0.80, c=0.86, d=0.30, e=0.02, f=0.70, g=0.84),
            0.30, SKALA)
        assert max(p, key=p.get) == 9
        assert p[9] > 0.9


class TestDerLeserNutztDieVerteilung:
    def test_ungueltiges_muster_wird_nach_wahrscheinlichkeit_aufgeloest(self):
        """Der ganze Zweck der Änderung: kein Hamming-Abstand mehr."""
        import numpy as np

        from kegel_cv.config import load_config
        from kegel_cv.detection.digit_reader import CalibratedDigitReader

        cfg = load_config().detection.digits
        leser = CalibratedDigitReader(cfg)
        # Kein echtes Bild noetig -- geprueft wird die Entscheidungsregel.
        zeichen, score, kandidaten, verteilung = \
            leser.read_digit_verteilung(np.zeros((0, 0, 3), np.uint8))
        assert zeichen == "?" and verteilung == ()
