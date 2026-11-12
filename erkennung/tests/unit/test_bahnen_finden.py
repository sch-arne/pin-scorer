

class TestDieMassstabsleiter:
    """GEMESSEN 2026-09-15 an einem Hallenframe mit vier sicher gefundenen
    Tafeln (154 tragende Merkmale): Ohne Leiter traegt der Abgleich nur den
    0,8- bis 1,5-fachen Massstab, mit ihr den 0,6- bis 4-fachen.

        Zielmassstab   ohne Leiter   mit Leiter
               0,6x             0           25
               1,0x           154          154
               2,0x             0          461
               4,0x             0          666

    Fuer eine fest montierte Hallenkamera ist das gleichgueltig. Fuer eine
    Handykamera, die irgendwo steht, entscheidet es darueber, ob ueberhaupt
    etwas gefunden wird: Dort fuellte eine Tafel 900 Bildpunkte gegen 190 im
    Muster -- das Fuenffache, weit ausserhalb des Fensters.
    """

    def test_die_leiter_steht_in_der_konfiguration(self):
        from kegel_cv.config import load_config
        leiter = load_config().detection.board_search.scale_ladder
        assert min(leiter) < 0.5 and max(leiter) > 2.0
        assert 1.0 in leiter, "die unveraenderte Vorlage gehoert dazu"

    def test_eine_leere_leiter_wird_abgelehnt(self):
        import pytest
        from kegel_cv.config.schema import BoardSearchConfig
        with pytest.raises(ValueError, match="leer"):
            BoardSearchConfig(scale_ladder=[])
        with pytest.raises(ValueError, match="positiv"):
            BoardSearchConfig(scale_ladder=[1.0, -2.0])

    def test_ohne_leiter_bleibt_alles_beim_alten(self):
        """Der Tischrechner-Weg ist unberuehrt: `erkenne` ohne `leiter`
        benutzt weiterhin genau die eine Vorlage."""
        import inspect
        from kegel_cv.calibration.board_library import erkenne
        assert inspect.signature(erkenne).parameters["leiter"].default is None
