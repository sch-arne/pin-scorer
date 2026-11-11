"""Stellenweise Aggregation mehrstelliger Ziffernfelder."""

from __future__ import annotations

from kegel_cv.analysis.temporal_aggregator import FieldAggregator


def lesung(text: str, score: float = 0.8):
    return tuple(text), tuple([score] * len(text))


class TestFieldAggregator:
    def test_eine_wackelige_stelle_reisst_das_feld_nicht_mit(self):
        """GEMESSEN an 40 Frames einer unveraenderten Anzeige ("0040"):
        Drei Stellen waren eindeutig, eine kippte 35:5 zwischen '4' und '9'.

        Ueber den Gesamtwert abgestimmt fiel die ganze Summe durch, sobald der
        Anteil unter die Schwelle sank. Stellenweise gewinnt die 4.
        """
        a = FieldAggregator(digits=4, min_agreement=0.5)
        for _ in range(7):
            a.add(*lesung("0040"))
        a.add(*lesung("0090"))

        assert a.result()[0] == 40

    def test_unlesbare_stelle_entwertet_die_uebrigen_nicht(self):
        a = FieldAggregator(digits=4, min_agreement=0.5)
        a.add(*lesung("00?0"))     # dritte Stelle unlesbar
        a.add(*lesung("0040"))
        a.add(*lesung("0040"))

        assert a.result()[0] == 40

    def test_durchgehend_unlesbare_stelle_ergibt_kein_ergebnis(self):
        """Lieber gar kein Wert als ein erfundener: Aus '00?0' laesst sich
        keine Zahl bilden, ohne eine Ziffer zu raten."""
        a = FieldAggregator(digits=4, min_agreement=0.5)
        for _ in range(4):
            a.add(*lesung("00?0"))

        assert a.result()[0] is None

    def test_andere_stellenzahl_wird_ignoriert(self):
        """Eine Lesung mit abweichender Stellenzahl liesse sich nur raten
        zuordnen -- links oder rechts ausgerichtet?"""
        a = FieldAggregator(digits=4, min_agreement=0.5)
        a.add(*lesung("040"))      # drei statt vier Stellen
        a.add(*lesung("0040"))

        assert a.result()[0] == 40

    def test_confidence_folgt_der_schwaechsten_stelle(self):
        a = FieldAggregator(digits=2)
        a.add(("1", "2"), (0.9, 0.3))

        wert, confidence = a.result()
        assert wert == 12
        assert confidence == 0.3

    def test_ohne_messungen_kein_ergebnis(self):
        assert FieldAggregator(digits=4).result() == (None, 0.0)


class TestMehrheitBug020:
    """BUG-020: Zeitliche Einigkeit ist etwas anderes als Bildguete.

    GEMESSEN am 2026-09-04 (Bahn 4, F126593): Zehn Frames lasen einstimmig
    '000', die fuehrenden Stellen aber nur mit Score 0,35 -- unter
    `min_confidence` 0,5. `result()` verwirft dort jede Stimme und liefert
    None; die Information "zehn von zehn sagen dasselbe" ging verloren.
    """

    def _sperrzyklus(self):
        agg = FieldAggregator(digits=3, min_confidence=0.5, min_agreement=0.5)
        for _ in range(10):
            agg.add(("0", "0", "0"), [0.35, 0.35, 0.66])
        return agg

    def test_result_scheitert_an_der_bildguete(self):
        """Das bisherige Verhalten -- bewusst unveraendert."""
        assert self._sperrzyklus().result() == (None, 0.0)

    def test_mehrheit_sieht_die_einigkeit(self):
        wert, einigkeit = self._sperrzyklus().mehrheit(ignoriere_fuehrende=1)
        assert wert == 0
        assert einigkeit == 1.0

    def test_uneinigkeit_schlaegt_durch(self):
        """Streuen die Frames, sinkt die Einigkeit -- genau das soll sie zeigen."""
        agg = FieldAggregator(digits=3, min_confidence=0.5, min_agreement=0.5)
        for _ in range(6):
            agg.add(("0", "0", "0"), [0.35, 0.35, 0.66])
        for _ in range(4):
            agg.add(("0", "0", "8"), [0.35, 0.35, 0.66])
        wert, einigkeit = agg.mehrheit(ignoriere_fuehrende=1)
        assert wert == 0
        assert einigkeit == 0.6, "6 von 10 -- unter der Schwelle von 0,9"

    def test_fuehrende_stelle_blockiert_nicht(self):
        """Die Hunderterstelle darf das Feld nicht scheitern lassen: Es gibt
        keinen hundertsten Wurf, die Stelle steht dauerhaft dunkel."""
        agg = FieldAggregator(digits=3, min_confidence=0.5, min_agreement=0.5)
        for i in range(10):
            # Die fuehrende Stelle flackert, die hinteren sind einig
            fuehrend = "0" if i % 2 else "8"
            agg.add((fuehrend, "1", "2"), [0.35, 0.90, 0.90])
        wert, einigkeit = agg.mehrheit(ignoriere_fuehrende=1)
        assert einigkeit == 1.0, "Nur die bewerteten Stellen zaehlen"
        assert wert in (12, 812), "Der Wert entsteht aus den Mehrheitsziffern"


class TestAlsLesung:
    """Das Feld als Lesung MIT Kandidaten -- Grundlage des geführten Lesens.

    `result()` und `mehrheit()` dampfen jede Stelle auf ihren Sieger ein.
    Genau die Schwankung ist aber die Information, die eine Erwartung ehrlich
    auflösen kann (siehe `analysis/gefuehrtes_lesen.py`).
    """

    def test_eine_schwankende_stelle_behaelt_beide_lesarten(self):
        """Derselbe Fall wie oben: 35 mal '0040', 5 mal '0090'."""
        a = FieldAggregator(digits=4, min_agreement=0.5)
        for _ in range(35):
            a.add(*lesung("0040"))
        for _ in range(5):
            a.add(*lesung("0090"))
        l = a.als_lesung()
        assert l.digits == ("0", "0", "4", "0")
        assert l.candidates[2] == (4, 9)
        assert l.candidates[0] == (0,)

    def test_ein_einzelner_ausreisser_wird_kein_kandidat(self):
        """Eine Stimme unter fünfzig macht eine Stelle nicht beliebig."""
        a = FieldAggregator(digits=4)
        for _ in range(49):
            a.add(*lesung("0040"))
        a.add(*lesung("0070"))
        assert a.als_lesung().candidates[2] == (4,)

    def test_eine_nie_gelesene_stelle_bleibt_offen(self):
        a = FieldAggregator(digits=4)
        for _ in range(10):
            a.add(*lesung("00?0"))
        l = a.als_lesung()
        assert l.digits[2] == "?"
        assert l.candidates[2] == ()
        assert l.value is None

    def test_ohne_messungen_bleibt_alles_offen(self):
        l = FieldAggregator(digits=4).als_lesung()
        assert l.digits == ("?", "?", "?", "?")
        assert l.value is None
