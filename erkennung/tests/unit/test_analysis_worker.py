"""Steuerung der laufenden Analyse.

Zwei Anforderungen des Nutzers (2026-08-26):

1. Eine Aufzeichnung soll **ab einer bestimmten Stelle** ausgewertet werden --
   vor einem Spiel wird warmgespielt, und diese Wuerfe gehoeren nicht dazu.
2. Der **Versand** muss getrennt abschaltbar sein: "stopp vom Senden,
   analysieren und loggen darf es immer".

Der zweite Punkt ist der wichtigere. Waere nur die ganze Analyse abschaltbar,
muesste man beim Warmspielen zwischen "nichts sehen" und "Datenbank verschmutzen"
waehlen.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.calibration.model import Calibration
from kegel_cv.config.schema import AppConfig
from kegel_cv.gui.analysis_worker import AnalysisWorker
from kegel_cv.video.source import Frame


class UnechteQuelle:
    """Liefert Frames der Reihe nach; kann springen oder auch nicht."""

    def __init__(self, anzahl: int = 500, kann_springen: bool = True) -> None:
        self.anzahl = anzahl
        self.kann_springen = kann_springen
        self.naechster = 0
        self.gelesen = 0

    def read(self) -> Frame | None:
        if self.naechster >= self.anzahl:
            return None
        frame = Frame(self.naechster, self.naechster / 25.0,
                      np.zeros((4, 4, 3), dtype=np.uint8))
        self.naechster += 1
        self.gelesen += 1
        return frame

    def seek(self, index: int) -> bool:
        if not self.kann_springen:
            return False
        self.naechster = index
        return True


@pytest.fixture
def worker() -> AnalysisWorker:
    return AnalysisWorker("egal.mp4", Calibration(), AppConfig())


class TestVersandSchalter:
    def test_standardmaessig_wird_gesendet(self, worker):
        assert worker.sending is True

    def test_laesst_sich_abschalten(self, worker):
        worker.set_sending(False)
        assert worker.sending is False

    def test_laesst_sich_wieder_einschalten(self, worker):
        worker.set_sending(False)
        worker.set_sending(True)
        assert worker.sending is True

    def test_startzustand_ist_waehlbar(self):
        """Beim Warmspielen startet man die Analyse mit abgeschaltetem Versand."""
        still = AnalysisWorker("egal.mp4", Calibration(), AppConfig(),
                               sending_enabled=False)
        assert still.sending is False


class TestVorspulen:
    def test_springt_wenn_die_quelle_es_kann(self, worker):
        worker._start_frame = 300
        quelle = UnechteQuelle(kann_springen=True)

        frame = worker._vorspulen(quelle, quelle.read())

        assert frame is not None and frame.index == 300
        assert quelle.gelesen <= 3, "ein Sprung liest nicht alles davor"

    def test_spult_vor_wenn_kein_sprung_moeglich(self, worker):
        """Streams koennen nicht springen, mancher Codec springt unzuverlaessig.
        Dann werden die Frames gelesen und verworfen -- langsamer, aber es
        funktioniert ueberall."""
        worker._start_frame = 120
        quelle = UnechteQuelle(kann_springen=False)

        frame = worker._vorspulen(quelle, quelle.read())

        assert frame is not None and frame.index == 120
        assert quelle.gelesen > 100, "ohne Sprung muss gelesen werden"

    def test_startposition_hinter_dem_ende_ergibt_nichts(self, worker):
        worker._start_frame = 9999
        quelle = UnechteQuelle(anzahl=50, kann_springen=False)

        assert worker._vorspulen(quelle, quelle.read()) is None

    def test_abbruch_beim_vorspulen_wird_beachtet(self, worker):
        """Sonst haengt das Programm minutenlang, wenn jemand es sich anders
        ueberlegt."""
        worker._start_frame = 100000
        worker.request_stop()
        quelle = UnechteQuelle(anzahl=200000, kann_springen=False)

        assert worker._vorspulen(quelle, quelle.read()) is None
        assert quelle.gelesen < 100, "der Abbruch muss sofort greifen"


class TestRueckmeldungBeimVorspulen:
    """Ohne Rueckmeldung wirkt die Anwendung haengen.

    GEMESSEN in einer Nutzersitzung: Das Vorspulen auf Frame 11344 dauerte
    77 Sekunden, in denen die Oberflaeche nichts anzeigte. Der Nutzer hat die
    Anwendung fuer kaputt gehalten und geschlossen.
    """

    def test_meldet_zwischenstaende(self, worker, qtbot=None):
        worker._start_frame = 1200
        quelle = UnechteQuelle(anzahl=2000, kann_springen=False)
        meldungen = []
        worker.seeking.connect(lambda a, b: meldungen.append((a, b)))

        worker._vorspulen(quelle, quelle.read())

        assert len(meldungen) >= 4, (
            f"nur {len(meldungen)} Meldungen -- zu selten, um lebendig zu wirken"
        )
        assert all(ziel == 1200 for _, ziel in meldungen)

    def test_meldet_auch_beim_sprung(self, worker):
        """Damit der Nutzer sieht, dass ueberhaupt etwas passiert."""
        worker._start_frame = 300
        quelle = UnechteQuelle(kann_springen=True)
        meldungen = []
        worker.seeking.connect(lambda a, b: meldungen.append((a, b)))

        worker._vorspulen(quelle, quelle.read())

        assert meldungen, "auch ein Sprung braucht eine Rueckmeldung"

    def test_sprung_meldet_keine_falsche_prozentzahl(self, worker):
        """Waehrend eines Sprungs gibt es keinen messbaren Fortschritt.

        Frueher wurde hier `0` gesendet. Die Oberflaeche zeigte daraufhin die
        ganze Zeit "0 %", und bei einem Stream ueber Netz dauert der Sprung
        lange genug, dass das nach einem Absturz aussieht -- so am 2026-09-07
        gemeldet. `SPRUNG_LAEUFT` sagt stattdessen die Wahrheit.
        """
        from kegel_cv.gui.analysis_worker import SPRUNG_LAEUFT

        worker._start_frame = 300
        quelle = UnechteQuelle(kann_springen=True)
        meldungen = []
        worker.seeking.connect(lambda a, b: meldungen.append((a, b)))

        worker._vorspulen(quelle, quelle.read())

        assert meldungen[0] == (SPRUNG_LAEUFT, 300), \
            f"der Sprung muss sich als solcher melden, war: {meldungen[0]}"
        assert (0, 300) not in meldungen, "keine irrefuehrende Null"
        assert meldungen[-1] == (300, 300), \
            "am Ende muss die Anzeige auf fertig stehen, sonst bleibt sie haengen"

    def test_vorspulen_meldet_weiterhin_echte_zwischenstaende(self, worker):
        """Der Sonderwert darf den messbaren Fall nicht mit erfassen."""
        from kegel_cv.gui.analysis_worker import SPRUNG_LAEUFT

        worker._start_frame = 1200
        quelle = UnechteQuelle(anzahl=2000, kann_springen=False)
        meldungen = []
        worker.seeking.connect(lambda a, b: meldungen.append((a, b)))

        worker._vorspulen(quelle, quelle.read())

        echte = [a for a, _ in meldungen if a != SPRUNG_LAEUFT]
        assert len(echte) >= 4, f"zu wenige echte Zwischenstaende: {echte}"
        assert echte == sorted(echte), "der Fortschritt muss steigen"
