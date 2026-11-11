"""Automatisch kalibrieren: Bauart aus Bildern waehlen, Rest misst der Rechner.

WOFUER -- Ansage des Nutzers am 2026-09-10:

    "es fehlt die Bibliothek, ich moechte nicht mehr selbst kalibrieren.
     sondern das soll er selbst machen"
    "Automatisches Kalibrieren (klick) dann kommt ein Fenster 'Waehle dein
     Kegelboardtyp aus' ... und dort gibt es zusaetzlich 'neues Board
     aufnehmen' oder man klickt auf eins und dann wird das gesucht"

ZWEI FEHLER, DIE DIESE TESTS FESTHALTEN. Die Bibliothekspruefung war gebaut,
lief aber nie:

1. `cfg.resolve_path(...)` gibt es nicht -- die Methode heisst `resolve`. Der
   Aufruf haette mit AttributeError abgebrochen.
2. Sie hing an `_on_video_opened`, und dort ist noch KEIN Frame da: Der Player
   meldet `opened` VOR dem ersten `step_forward()`. Die Pruefung sah immer
   `current_frame is None` und kehrte still zurueck -- Fehler 1 blieb dadurch
   sogar unentdeckt.

Beides war ungetestet. Deshalb hier: die Verdrahtung, nicht der
Merkmalsabgleich -- der hat seine Tests in `test_board_finder.py`.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog     # noqa: E402

from kegel_cv.calibration.board_library import (  # noqa: E402
    Tafeltyp, lade_bibliothek, speichere_typ)
from kegel_cv.calibration.model import (Calibration,  # noqa: E402
                                        LaneCalibration, Roi)
from kegel_cv.config import load_config                 # noqa: E402
from kegel_cv.gui import main_window as mw              # noqa: E402
from kegel_cv.gui.boardtype_dialog import TafeltypDialog  # noqa: E402
from kegel_cv.video.source import Frame, VideoInfo      # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fenster(qt_app):
    f = mw.MainWindow(load_config())
    yield f
    f.close()


def bild(wert=90) -> np.ndarray:
    return np.full((200, 300, 3), wert, dtype=np.uint8)


def ein_typ(name="Testbauart") -> Tafeltyp:
    kal = Calibration(lanes=[LaneCalibration(
        lane_id=1,
        quad=[[10.0, 10.0], [90.0, 10.0], [90.0, 90.0], [10.0, 90.0]],
        rois=[Roi(name="green_lamp", rect=(0.4, 0.8, 0.05, 0.05))])])
    return Tafeltyp(name=name, muster=bild(140), kalibrierung=kal)


class UnechterPlayer:
    """Ein Player, der Standbilder liefert und Spruenge mitschreibt."""

    def __init__(self, live=False, gesamt=1000):
        self.current_frame = Frame(index=0, timestamp=0.0, image=bild())
        self.source_id = "test.mp4"
        self.is_live = live
        self.is_loaded = True
        self.position = 400
        self.info = VideoInfo(width=300, height=200, fps=25.0,
                              frame_count=gesamt, source_id="test.mp4")
        self.spruenge: list[int] = []

    def seek(self, index):
        self.spruenge.append(index)
        self.position = index
        self.current_frame = Frame(index=index, timestamp=0.0,
                                   image=bild(90 + index % 40))
        return True

    def step_forward(self):
        return True

    def pause(self):
        pass

    def close(self):
        self.is_loaded = False


# --------------------------------------------------------------- Der Knopf

class TestDerKnopf:
    def test_er_existiert(self, fenster):
        assert hasattr(fenster, "btn_auto_kalibrieren")

    def test_er_erklaert_sich(self, fenster):
        hinweis = fenster.btn_auto_kalibrieren.toolTip()
        assert "Bauart" in hinweis and "Bahnnummern" in hinweis

    def test_ohne_bild_kein_absturz(self, fenster, monkeypatch):
        """Der haeufigste Klick der Welt: auf den Knopf, bevor etwas offen
        ist."""
        gezeigt = []
        monkeypatch.setattr(mw.QMessageBox, "information",
                            lambda *a, **k: gezeigt.append(a))
        fenster._on_auto_kalibrieren()
        assert gezeigt, "es muss eine Erklaerung kommen"


class TestBibliothekWirdGefunden:
    """HIER LAG FEHLER 1: `cfg.resolve_path` gibt es nicht."""

    def test_der_ordner_wird_aufgeloest(self, fenster):
        typen = fenster._tafeltypen()
        assert isinstance(typen, list)

    def test_der_mitgelieferte_typ_ist_dabei(self, fenster):
        """Das Repo bringt FUNK_klassisch mit -- wenn der nicht auftaucht,
        stimmt der Pfad nicht."""
        assert "FUNK_klassisch" in [t.name for t in fenster._tafeltypen()]


class TestBilderSammeln:
    """HIER LAG FEHLER 2 -- und die Antwort darauf, warum EIN Bild nicht
    genuegt: Gemessen ueber 16 Stichproben eines Spiels lieferte ein einzelnes
    Bild nur einmal alle vier Tafeln und fuenfmal gar keine."""

    def test_mehrere_bilder_aus_einer_datei(self, fenster):
        fenster.player = UnechterPlayer()
        bilder = fenster._bilder_fuer_suche()
        assert len(bilder) == fenster.cfg.calibration.boardtype_sample_frames

    def test_die_bilder_sind_verschieden(self, fenster):
        """Sechsmal dasselbe Bild waere sechsmal dieselbe Antwort."""
        fenster.player = UnechterPlayer()
        bilder = fenster._bilder_fuer_suche()
        assert len({b[0, 0, 0] for b in bilder}) > 1

    def test_hinterher_steht_es_wieder_wo_es_war(self, fenster):
        """Wer kalibriert, schaut auf ein bestimmtes Standbild. Das darf ihm
        die Suche nicht wegziehen."""
        player = UnechterPlayer()
        fenster.player = player
        fenster._bilder_fuer_suche()
        assert player.spruenge[-1] == 400

    def test_am_dateiende_wird_rueckwaerts_gesucht(self, fenster):
        """Sonst bleiben am Schluss des Videos alle Stichproben leer."""
        player = UnechterPlayer(gesamt=420)
        player.position = 400
        fenster.player = player
        fenster._bilder_fuer_suche()
        assert all(0 <= s < 420 for s in player.spruenge)

    def test_beim_stream_wird_nicht_gesprungen(self, fenster):
        """Ein Livestream hat keine Vergangenheit -- ein Sprung dorthin
        zerlegt die Uebertragung."""
        player = UnechterPlayer(live=True)
        fenster.player = player
        fenster.cfg.calibration.boardtype_sample_wait_s = 0.0
        bilder = fenster._bilder_fuer_suche()
        assert player.spruenge == []
        assert len(bilder) == fenster.cfg.calibration.boardtype_sample_frames


class TestAuswahlfenster:
    def test_die_typen_stehen_zur_wahl(self, qt_app):
        d = TafeltypDialog([ein_typ("A"), ein_typ("B")])
        assert d.ergebnis is None

    def test_ein_klick_waehlt_den_typ(self, qt_app):
        typ = ein_typ()
        d = TafeltypDialog([typ])
        d._waehle(typ)
        assert d.ergebnis is typ

    def test_neues_board_ist_immer_moeglich(self, qt_app):
        """Auch bei leerer Bibliothek -- sonst gaebe es keinen Anfang."""
        d = TafeltypDialog([])
        d._waehle("neu")
        assert d.ergebnis == "neu"

    def test_eine_leere_bibliothek_ist_kein_fehler(self, qt_app):
        TafeltypDialog([])   # darf nicht werfen


class TestAblauf:
    def _oeffne_mit(self, fenster, monkeypatch, wahl, bestaetigt=True):
        fenster.player = UnechterPlayer()

        def auf(self):
            self.ergebnis = wahl
            return QDialog.Accepted

        monkeypatch.setattr(mw.TafeltypDialog, "exec", auf)
        # Der Bestaetigungsdialog ist MODAL -- ohne diesen Griff bliebe der
        # Test stehen, bis ihn jemand von Hand wegklickt.
        monkeypatch.setattr(
            mw.TrefferDialog, "exec",
            lambda self: QDialog.Accepted if bestaetigt else QDialog.Rejected)

    def test_abbruch_laesst_alles_wie_es_war(self, fenster, monkeypatch):
        self._oeffne_mit(fenster, monkeypatch, None)
        monkeypatch.setattr(mw.TafeltypDialog, "exec",
                            lambda self: QDialog.Rejected)
        fenster._on_auto_kalibrieren()
        assert fenster.session.calibration.lanes == []

    def test_neues_board_fuehrt_zur_aufnahme(self, fenster, monkeypatch):
        self._oeffne_mit(fenster, monkeypatch, "neu")
        gerufen = []
        monkeypatch.setattr(mw.MainWindow, "_on_board_aufnehmen",
                            lambda self: gerufen.append(1))
        fenster._on_auto_kalibrieren()
        assert gerufen == [1]

    def test_ohne_treffer_wird_erklaert_was_zu_tun_ist(self, fenster,
                                                      monkeypatch):
        self._oeffne_mit(fenster, monkeypatch, ein_typ())
        fenster.cfg.calibration.boardtype_sample_frames = 2
        texte = []
        monkeypatch.setattr(mw.QMessageBox, "warning",
                            lambda *a, **k: texte.append(a[2]))
        fenster._on_auto_kalibrieren()
        assert texte and "andere Stelle" in texte[0]

    def test_ein_treffer_wird_uebernommen(self, fenster, monkeypatch):
        """Der ganze Sinn: kein einziger Klick in die Tafel."""
        from kegel_cv.calibration.board_finder import Treffer
        from kegel_cv.calibration.board_library import Erkennung

        self._oeffne_mit(fenster, monkeypatch, ein_typ())
        treffer = [Treffer(quad=[[x, 10.0], [x + 80, 10.0],
                                 [x + 80, 90.0], [x, 90.0]],
                           inlier=40, paare=60, vorlage_index=0)
                   for x in (10.0, 120.0)]
        monkeypatch.setattr(
            "kegel_cv.calibration.board_library.LaufendeSuche.ergebnis",
            lambda self: Erkennung(typ=ein_typ(), treffer=treffer))
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("3 4", True))
        fenster._on_auto_kalibrieren()
        assert [l.display_number for l in fenster.session.calibration.lanes] \
            == [3, 4]
        assert {r.name for r in fenster.session.calibration.lanes[0].rois} \
            == {"green_lamp"}


class TestNeueBauartAufnehmen:
    def test_ohne_kalibrierung_wird_erklaert_wie(self, fenster, monkeypatch):
        fenster.player = UnechterPlayer()
        texte = []
        monkeypatch.setattr(mw.QMessageBox, "information",
                            lambda *a, **k: texte.append(a[2]))
        fenster._on_board_aufnehmen()
        assert texte and "Kalibrierung starten" in texte[0]

    def test_sie_landet_in_der_bibliothek(self, fenster, monkeypatch, tmp_path):
        fenster.player = UnechterPlayer()
        fenster.session.calibration = ein_typ().kalibrierung
        fenster.session.active_lane = 1
        fenster.cfg.calibration.boardtype_directory = str(tmp_path)
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("FUNK neu", True))
        monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: None)
        fenster._on_board_aufnehmen()
        assert [t.name for t in lade_bibliothek(tmp_path)] == ["FUNK_neu"], \
            "Leerzeichen im Namen wuerden den Dateinamen zerlegen"

    def test_ohne_namen_wird_nichts_angelegt(self, fenster, monkeypatch,
                                             tmp_path):
        fenster.player = UnechterPlayer()
        fenster.session.calibration = ein_typ().kalibrierung
        fenster.cfg.calibration.boardtype_directory = str(tmp_path)
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("", False))
        fenster._on_board_aufnehmen()
        assert lade_bibliothek(tmp_path) == []


class TestLivesuche:
    """Ein Stream hat keine Vergangenheit -- Einwand des Nutzers am 2026-09-10:

        "Das ganze soll ja spaeter im Livestream laufen, da kann er ja nicht
         einfach hin und herspringen ... eigentlich waere es besser, wenn er
         in den ersten 5-10 Sekunden das glattzieht ... und wenn es nach 20
         Sekunden immer noch nicht alle Boards gefunden hat"

    GEMESSEN an acht Stellen der Aufzeichnung, ein Bild je 0,8 s Streamzeit:
    sechsmal alle vier Tafeln nach 2,4 bis 14,4 s (im Mittel 4,8), zweimal
    nur zwei bzw. drei bis zur Zeitgrenze.
    """

    def _live(self, fenster, timeout=0.3):
        player = UnechterPlayer(live=True)
        fenster.player = player
        fenster.cfg.calibration.boardtype_sample_wait_s = 0.0
        fenster.cfg.calibration.boardtype_live_timeout_s = timeout
        return player

    def test_die_zeitgrenze_greift(self, fenster):
        """Ohne sie liefe die Suche endlos, wenn nichts zu finden ist."""
        import time as uhr
        self._live(fenster, timeout=0.3)
        t0 = uhr.monotonic()
        suche, _ = fenster._suche_tafeln([ein_typ()], ziel=4)
        assert uhr.monotonic() - t0 < 5.0
        assert not suche.fertig

    def test_im_stream_wird_nicht_gesprungen(self, fenster):
        player = self._live(fenster)
        fenster._suche_tafeln([ein_typ()], ziel=4)
        assert player.spruenge == []

    def test_ohne_typen_bleibt_es_ruhig(self, fenster):
        self._live(fenster)
        suche, _ = fenster._suche_tafeln([], ziel=4)
        assert suche.ergebnis() is None

    def test_die_datei_spult_statt_zu_warten(self, fenster):
        """Wo es eine Vergangenheit gibt, ist Springen schneller als Warten."""
        player = UnechterPlayer(live=False)
        fenster.player = player
        fenster._suche_tafeln([ein_typ()], ziel=4)
        assert player.spruenge, "in einer Datei wird gesprungen"


class TestNachfrageVorUebernahme:
    """"meinetwegen mich auch noch fragt 'sitzt dieses Board?'" """

    def _treffer(self):
        from kegel_cv.calibration.board_finder import Treffer
        from kegel_cv.calibration.board_library import Erkennung
        t = [Treffer(quad=[[10.0, 10.0], [90.0, 10.0], [90.0, 90.0],
                           [10.0, 90.0]], inlier=40, paare=60,
                     vorlage_index=0)]
        return Erkennung(typ=ein_typ(), treffer=t)

    def test_verwerfen_laesst_die_kalibrierung_unberuehrt(self, fenster,
                                                          monkeypatch):
        monkeypatch.setattr(mw.TrefferDialog, "exec",
                            lambda self: QDialog.Rejected)
        assert not fenster._bestaetige_treffer(self._treffer(), bild(), 4, 6)

    def test_zu_wenige_tafeln_werden_benannt(self, fenster, monkeypatch):
        """Wer 4 erwartet und 1 bekommt, muss das VOR dem Uebernehmen sehen."""
        koepfe = []

        def merken(self, uebersicht, tafeln, kopfzeile, parent=None):
            koepfe.append(kopfzeile)

        monkeypatch.setattr(mw.TrefferDialog, "__init__", merken)
        monkeypatch.setattr(mw.TrefferDialog, "exec",
                            lambda self: QDialog.Accepted)
        fenster._bestaetige_treffer(self._treffer(), bild(), 4, 6)
        assert "1 von 4" in koepfe[0]

    def test_die_rois_werden_eingeblendet(self, fenster, monkeypatch):
        """"ich brauche schon das die ROIs eingeblendet werden ... sonst kann
        ich ja nicht entscheiden, ob es sitzt oder nicht" -- ein Rahmen um die
        Tafel beweist nur, DASS sie gefunden wurde."""
        gezeigt = {}

        def merken(self, uebersicht, tafeln, kopfzeile, parent=None):
            gezeigt["tafeln"] = tafeln

        monkeypatch.setattr(mw.TrefferDialog, "__init__", merken)
        monkeypatch.setattr(mw.TrefferDialog, "exec",
                            lambda self: QDialog.Accepted)
        fenster._bestaetige_treffer(self._treffer(), bild(80), 1, 6)
        montage = gezeigt["tafeln"]
        assert montage is not None and montage.size
        # Die Gruenlampe wird rein gruen umrandet (0,255,0). Aus einem grauen
        # Standbild kann so ein Pixel nicht entstehen.
        rein_gruen = ((montage[:, :, 0] == 0) & (montage[:, :, 1] == 255)
                      & (montage[:, :, 2] == 0))
        assert rein_gruen.any(), "die ROI-Rahmen fehlen"

    def test_die_rahmen_werden_ins_bild_gemalt(self):
        """Zahlen ueber tragende Merkmale beantworten die Frage nicht."""
        from kegel_cv.gui.boardtype_dialog import zeichne_treffer
        roh = bild(0)
        gemalt = zeichne_treffer(roh, self._treffer().treffer)
        assert gemalt.max() > 0, "es muss etwas gezeichnet worden sein"
        assert roh.max() == 0, "das Originalbild bleibt unberuehrt"


class TestAnzahlIstEinstellbar:
    """"man kann ja auch sagen, nach wie vielen man sucht" """

    def test_das_feld_gibt_es(self, qt_app):
        assert TafeltypDialog([], vorgabe_anzahl=5).anzahl.value() == 5

    def test_die_vorgabe_kommt_aus_der_konfiguration(self, fenster,
                                                    monkeypatch):
        gesehen = {}
        echt = mw.TafeltypDialog.__init__

        def merken(self, typen, vorgabe_anzahl=4, korrekturen=None,
                   parent=None):
            gesehen["vorgabe"] = vorgabe_anzahl
            gesehen["korrekturen"] = korrekturen
            echt(self, typen, vorgabe_anzahl, korrekturen, parent)

        monkeypatch.setattr(mw.TafeltypDialog, "__init__", merken)
        monkeypatch.setattr(mw.TafeltypDialog, "exec",
                            lambda self: QDialog.Rejected)
        fenster.player = UnechterPlayer()
        fenster._on_auto_kalibrieren()
        assert gesehen["vorgabe"] == fenster.cfg.calibration.lane_count


class TestVorDerKalibrierung:
    """GEMESSEN im Livelauf 2026-09-10: Ein Dreh am Bahnnummernfeld, bevor
    etwas kalibriert war, warf `KeyError: Bahn 1 ist nicht kalibriert` mitten
    aus dem Qt-Signal heraus. `active_lane` steht auf 1, sobald das Fenster
    offen ist -- kalibriert ist deshalb noch lange nichts."""

    def test_es_wirft_nicht(self, fenster):
        fenster.session.calibration.lanes.clear()
        fenster.session.active_lane = 1
        fenster._on_lane_number_changed(7)      # darf nicht werfen

    def test_es_wird_erklaert(self, fenster):
        fenster.session.calibration.lanes.clear()
        fenster.session.active_lane = 1
        fenster._on_lane_number_changed(7)
        assert "kalibriert" in fenster.statusBar().currentMessage()


class TestPositionsanzeige:
    """Oben links laufen Frames und Zeit.

    Zwei Wuensche des Nutzers am 2026-09-10:

        "waere das cool, wenn das nicht stoppen wuerde, nur weil ich auf
         Analyse starten klicke"
        "waere das cool, wenn da auch noch die Zeit in HH:mm:ss angezeigt
         wird, weil 5621 Sekunden ist fuer mich nicht so eingaengig"
    """

    def test_stunden_minuten_sekunden(self):
        from kegel_cv.gui.main_window import als_uhrzeit
        assert als_uhrzeit(5621) == "01:33:41"
        assert als_uhrzeit(0) == "00:00:00"
        assert als_uhrzeit(11300) == "03:08:20"

    def test_unsinn_stuerzt_nicht_ab(self):
        from kegel_cv.gui.main_window import als_uhrzeit
        assert als_uhrzeit(-1) == "--:--:--"
        assert als_uhrzeit(float("nan")) == "--:--:--"

    def test_die_sekunden_bleiben_lesbar(self, fenster):
        """Sie stehen in Logs und Debug-Ordnern -- beide Angaben braucht es."""
        fenster._setze_position(140540, 296103, 5621.6)
        text = fenster.position_label.text()
        assert "01:33:41" in text and "5622 s" in text and "140540" in text

    def test_waehrend_der_analyse_laeuft_die_zeit_weiter(self, fenster):
        """HIER LAG DER FEHLER: Bei einem Livestream ist der Player waehrend
        der Analyse GESCHLOSSEN. `player.info` war None, also fehlte die
        Bildrate -- die Frames liefen, die Sekunden standen bei 0.00."""
        fenster.player = UnechterPlayer(live=True)
        fenster._analyse_info = fenster.player.info      # beim Start gemerkt
        fenster.player.close()
        fenster.player.info = None                       # Player ist zu
        fenster._on_preview(2500, bild())
        assert "00:01:40" in fenster.position_label.text()

    def test_ohne_gesamtzahl_keine_null(self, fenster):
        """"Frame 12345 / 0" sah aus wie ein Fehler und war nur ein Stream."""
        fenster._setze_position(12345, 0, 493.8)
        assert "/ 0" not in fenster.position_label.text()


class TestVorschauImWahrenFormat:
    """Frage des Nutzers am 2026-09-10 zur Montage: "Warum sind die denn alle
    so stark verzerrt?"

    GEMESSEN ueber drei Kalibrierungen und zwei Kameras: Die Tafel ist
    praktisch quadratisch (Verhaeltnis 0,97 bis 1,01). Entzerrt wird aber auf
    440x530 -- Verhaeltnis 0,83, also eine Streckung um den Faktor 1,2 in die
    Hoehe. Fuer die Analyse gleichgueltig (die ROIs sind normiert), fuers Auge
    nicht.
    """

    def _bahn(self, breite=160.0, hoehe=160.0):
        from kegel_cv.calibration.model import LaneCalibration
        return LaneCalibration(
            lane_id=1,
            quad=[[0.0, 0.0], [breite, 0.0], [breite, hoehe], [0.0, hoehe]],
            rois=[Roi(name="green_lamp", rect=(0.4, 0.8, 0.05, 0.05))])

    def test_eine_quadratische_tafel_bleibt_quadratisch(self):
        from kegel_cv.calibration.roi_preview import tafelmontage
        gross = np.full((400, 400, 3), 90, dtype=np.uint8)
        m = tafelmontage(gross, [self._bahn(160, 160)])
        hoehe, breite = m.shape[0] - 22, m.shape[1]
        assert abs(breite / hoehe - 1.0) < 0.05

    def test_eine_hohe_tafel_bleibt_hoch(self):
        from kegel_cv.calibration.roi_preview import tafelmontage
        gross = np.full((400, 400, 3), 90, dtype=np.uint8)
        m = tafelmontage(gross, [self._bahn(100, 200)])
        hoehe, breite = m.shape[0] - 22, m.shape[1]
        assert abs(breite / hoehe - 0.5) < 0.05

    def test_ohne_bahnen_kommt_das_bild_zurueck(self):
        from kegel_cv.calibration.roi_preview import tafelmontage
        roh = bild()
        assert tafelmontage(roh, []) is roh


class TestWeitersammeln:
    """"bau das mit dem Weitersammeln ein" -- nach dem vollstaendigen Fund
    noch ein paar Bilder, damit es genug zu mitteln gibt."""

    def test_die_datei_sammelt_ueber_den_fund_hinaus(self, fenster,
                                                     monkeypatch):
        player = UnechterPlayer()
        fenster.player = player
        gesehen = []

        class Attrappe:
            def __init__(self, *a, **k):
                self.bilder_gesehen = 0
                self.nachlauf = k.get("nachlauf", 0)
                self.gefunden = 0

            def fuettere(self, bild):
                self.bilder_gesehen += 1
                gesehen.append(bild)
                self.gefunden = 4 if self.bilder_gesehen >= 2 else 0

            @property
            def fertig(self):
                return self.gefunden >= 4

            @property
            def genug(self):
                return self.fertig and self.bilder_gesehen >= 2 + self.nachlauf

            def ergebnis(self):
                return None

        monkeypatch.setattr("kegel_cv.calibration.board_library.LaufendeSuche",
                            Attrappe)
        fenster.cfg.calibration.boardtype_nachlauf_bilder = 3
        fenster.cfg.calibration.boardtype_sample_frames = 10
        fenster._suche_tafeln([ein_typ()], ziel=4)
        assert len(gesehen) == 5, "zwei bis zum Fund, drei Nachlauf"

    def test_die_zeitgrenze_deckelt_den_nachlauf(self, fenster, monkeypatch):
        """Sonst haengt die Suche im Livestream am Nachlauf fest, wenn die
        Bilder nicht schnell genug kommen."""
        import time as uhr
        player = UnechterPlayer(live=True)
        fenster.player = player
        fenster.cfg.calibration.boardtype_sample_wait_s = 0.0
        fenster.cfg.calibration.boardtype_live_timeout_s = 0.3
        fenster.cfg.calibration.boardtype_nachlauf_bilder = 999
        t0 = uhr.monotonic()
        fenster._suche_tafeln([ein_typ()], ziel=4)
        assert uhr.monotonic() - t0 < 5.0

    def test_der_nutzer_erfaehrt_warum_es_weitergeht(self, fenster):
        """Alle Tafeln stehen da und trotzdem passiert nichts -- ohne Hinweis
        sieht das nach einem Haenger aus."""
        class Stand:
            gefunden, bilder_gesehen, fertig = 4, 7, True

        fenster._melde_suchstand(Stand(), 4)
        assert "weiter" in fenster.statusBar().currentMessage()


class TestDialogPasstAufDenSchirm:
    """"ansich hat das schon sehr gut funktioniert... nur kann man wegen der
    Fenstergroesse nicht bestaetigen" -- Nutzer, 2026-09-10.

    HIER LAG DER FEHLER: Die Uebersicht wurde auf ihre eigene Kantenlaenge
    skaliert, bei einem 1920er Bild also auf 1920 Pixel. Der Dialog wurde
    groesser als der Bildschirm (1536x816), und die Knoepfe rutschten hinaus.
    """

    def _bilder(self):
        gross = np.full((1080, 1920, 3), 90, dtype=np.uint8)
        tafeln = np.full((530, 1400, 3), 120, dtype=np.uint8)
        return gross, tafeln

    def test_er_bleibt_im_sichtbaren_bereich(self, qt_app):
        from PySide6.QtWidgets import QApplication
        from kegel_cv.gui.boardtype_dialog import TrefferDialog
        gross, tafeln = self._bilder()
        d = TrefferDialog(gross, tafeln, "vier Tafeln")
        platz = QApplication.primaryScreen().availableGeometry()
        assert d.width() <= platz.width()
        assert d.height() <= platz.height()

    def test_die_knoepfe_sind_da(self, qt_app):
        from PySide6.QtWidgets import QDialogButtonBox
        from kegel_cv.gui.boardtype_dialog import TrefferDialog
        gross, tafeln = self._bilder()
        d = TrefferDialog(gross, tafeln, "vier Tafeln")
        kasten = d.findChild(QDialogButtonBox)
        assert kasten is not None
        assert len(kasten.buttons()) == 2

    def test_ein_kleines_bild_wird_nicht_aufgeblasen(self, qt_app):
        """Pixel groesser zu machen bringt keine Erkenntnis."""
        from kegel_cv.gui.boardtype_dialog import TrefferDialog
        klein = np.full((80, 120, 3), 90, dtype=np.uint8)
        bereich = TrefferDialog._bildbereich(klein, 1200, 900)
        marke = bereich.widget()
        assert marke.pixmap().width() <= 120


class TestRoisInDerVorschau:
    """"ich brauche die ROIs in der Livepreview um sie dort noch hin und her
    zu schieben" -- Nutzer, 2026-09-10.

    HIER LAG DER FEHLER: Nach der automatischen Kalibrierung standen die ROIs
    zwar in der Sitzung, wurden aber nie ins Bild gezeichnet. Nachziehen war
    damit unmoeglich -- man sah ja nichts.
    """

    def _kalibriere(self, fenster, monkeypatch):
        from kegel_cv.calibration.board_finder import Treffer
        from kegel_cv.calibration.board_library import Erkennung
        fenster.player = UnechterPlayer()
        treffer = [Treffer(quad=[[x, 10.0], [x + 80, 10.0],
                                 [x + 80, 90.0], [x, 90.0]],
                           inlier=40, paare=60, vorlage_index=0)
                   for x in (10.0, 120.0)]
        monkeypatch.setattr(mw.QInputDialog, "getText",
                            lambda *a, **k: ("3 4", True))
        fenster._uebernimm_erkennung(
            Erkennung(typ=ein_typ(), treffer=treffer), bild())

    def test_die_tafeln_werden_eingezeichnet(self, fenster, monkeypatch):
        self._kalibriere(fenster, monkeypatch)
        assert len(fenster.video_view._quads) == 2

    def test_die_rois_werden_eingezeichnet(self, fenster, monkeypatch):
        self._kalibriere(fenster, monkeypatch)
        assert fenster.video_view._rois, "ohne sie laesst sich nichts ziehen"
        assert any(namen for namen in fenster.video_view._rois.values())

    def test_ziehen_ist_erlaubt(self, fenster, monkeypatch):
        """Sichtbar allein genuegt nicht -- sie muessen anfassbar sein."""
        self._kalibriere(fenster, monkeypatch)
        assert fenster.video_view._drag_erlaubt

    def test_ein_neues_bild_loescht_sie_nicht(self, fenster, monkeypatch):
        """Im Livestream kommt alle 40 ms ein Frame. Wuerden die Overlays
        dabei verschwinden, waere im Betrieb nie eine ROI zu sehen."""
        self._kalibriere(fenster, monkeypatch)
        vorher = len(fenster.video_view._rois)
        fenster.video_view.set_frame(bild(120))
        assert len(fenster.video_view._rois) == vorher
