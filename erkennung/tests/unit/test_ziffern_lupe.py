"""Die Lupe muss zeigen, was der Leser misst -- und nie abstürzen.

DIE IDEE (Nutzer, 2026-09-15): *"vielleicht ermöglichen, dass der Nutzer die 7
Einheiten legt? Zum Beispiel dass er wenn er eine Ziffer einrahmt die
Mittelpunkte der einzelnen Felder angezeigt bekommt."*

Sie ist Hilfe beim Kalibrieren, nicht Voraussetzung. Ein unbrauchbarer
Ausschnitt darf deshalb ein Hinweisbild liefern, aber keine Ausnahme.
"""

from __future__ import annotations

import numpy as np

from kegel_cv.config import load_config
from kegel_cv.detection.digit_reader import CalibratedDigitReader
from kegel_cv.detection.ziffern_lupe import zeichne_lupe


def leser():
    return CalibratedDigitReader(load_config().detection.digits)


def rote_ziffer(breite: int = 12, hoehe: int = 20) -> np.ndarray:
    """Ein Ausschnitt mit roten Segmenten -- grob eine '1' (b und c)."""
    bild = np.zeros((hoehe, breite, 3), np.uint8)
    bild[2:hoehe - 2, breite - 4:breite - 1] = (40, 40, 255)
    return bild


class TestDieLupeLiefertImmerEinBild:
    def test_ein_leerer_ausschnitt_gibt_einen_hinweis(self):
        bild = zeichne_lupe(np.zeros((0, 0, 3), np.uint8), leser())
        assert bild.ndim == 3 and bild.shape[2] == 3
        assert bild.size > 0

    def test_ein_schwarzer_ausschnitt_gibt_einen_hinweis(self):
        """Zu dunkel heißt: nichts zu messen -- kein Absturz, ein Satz."""
        bild = zeichne_lupe(np.zeros((20, 12, 3), np.uint8), leser())
        assert bild.ndim == 3 and bild.size > 0

    def test_none_wird_vertragen(self):
        assert zeichne_lupe(None, leser()).size > 0

    def test_eine_lesbare_ziffer_gibt_ein_breiteres_bild(self):
        """Mit Messwerten kommen vier Spalten zusammen: Zahlen, Ausschnitt,
        Rotmaske und die gestauchte Zelle mit den Flächen."""
        hinweis = zeichne_lupe(np.zeros((20, 12, 3), np.uint8), leser())
        echt = zeichne_lupe(rote_ziffer(), leser())
        assert echt.shape[0] > hinweis.shape[0]

    def test_der_zoom_wirkt_auf_die_groesse(self):
        klein = zeichne_lupe(rote_ziffer(), leser(), zoom=4)
        gross = zeichne_lupe(rote_ziffer(), leser(), zoom=12)
        assert gross.shape[0] > klein.shape[0]


class TestDieLupeZeigtDieselbeMessung:
    def test_sie_nutzt_die_schwellen_des_uebergebenen_lesers(self):
        """Eine Lupe mit eigenen Einstellungen zeigte etwas, das nie gemessen
        wird. Deshalb bekommt sie den Leser, statt sich einen zu bauen."""
        import inspect

        from kegel_cv.detection import ziffern_lupe
        quelle = inspect.getsource(ziffern_lupe.zeichne_lupe)
        assert "leser.segment_fills" in quelle
        assert "leser._threshold" in quelle
        assert "leser.read_digit_verteilung" in quelle
        # Kein eigener Leser, keine eigene Konfiguration
        assert "load_config" not in quelle
        assert "CalibratedDigitReader(" not in quelle
