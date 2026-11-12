"""Nachkalibrieren: eine Tafel anklicken, gross sehen, Bereiche ziehen.

WOFUER -- Wunsch des Nutzers am 2026-09-11:

    "ich brauche einen Button 'Nachkalibrieren' ... an dem ich jedes Board das
     ich aendern will anklicken kann, das wird mir gross gezeigt und ich kann
     die ROIs anpassen"

WAS DIESE TESTS FESTHALTEN, und zwar aus Erfahrung:

1. **Der Klick darf nicht ziehen.** Die Bereiche bedecken die ganze Tafel. Ist
   das Ziehen an, greift der Auswahlklick den Bereich darunter und VERSCHIEBT
   ihn -- statt die Tafel zu oeffnen. Genau dieser Fehler ist beim Einbau des
   Ziehens schon einmal passiert (siehe `VideoView.set_drag_enabled`).
2. **Abbrechen muss folgenlos bleiben.** Der Dialog arbeitet auf Kopien; wer
   sich verzieht, kommt sonst nicht mehr zurueck -- und genau deswegen ist er
   hier.
3. **Kein Bereich darf die Tafel verlassen.** `Roi` prueft das beim Anlegen,
   `model_copy` prueft gar nichts. Ein hinausgezogener Bereich waere still
   kaputt und erst beim Speichern aufgefallen.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt                      # noqa: E402
from PySide6.QtGui import QKeyEvent                        # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog        # noqa: E402

from kegel_cv.calibration.model import (Calibration,       # noqa: E402
                                        LaneCalibration, Roi)
from kegel_cv.config import load_config                    # noqa: E402
from kegel_cv.gui import board_editor as be                # noqa: E402
from kegel_cv.gui import main_window as mw                 # noqa: E402
from kegel_cv.video.source import Frame                    # noqa: E402

pytestmark = pytest.mark.gui


@pytest.fixture(scope="module")
def qt_app():
    return QApplication.instance() or QApplication([])


def bild(wert=90, breite=400, hoehe=300) -> np.ndarray:
    return np.full((hoehe, breite, 3), wert, dtype=np.uint8)


def eine_bahn(lane_id=1, x=10.0) -> LaneCalibration:
    """Eine quadratische Tafel mit drei unterschiedlich grossen Bereichen."""
    return LaneCalibration(
        lane_id=lane_id,
        quad=[[x, 20.0], [x + 100, 20.0], [x + 100, 120.0], [x, 120.0]],
        rois=[
            Roi(name="green_lamp", rect=(0.45, 0.70, 0.06, 0.06)),
            Roi(name="digit_throw_number_1", rect=(0.20, 0.85, 0.05, 0.08)),
            Roi(name="throw_number", rect=(0.15, 0.83, 0.30, 0.12)),
        ])


@pytest.fixture
def fenster(qt_app):
    f = mw.MainWindow(load_config())
    f.session.calibration = Calibration(
        lanes=[eine_bahn(1, 10.0), eine_bahn(2, 150.0)])
    f._current_frame = Frame(index=0, timestamp=0.0, image=bild())
    yield f
    f.close()


# ------------------------------------------------------------------ Der Knopf

class TestDerKnopf:
    def test_er_existiert(self, fenster):
        assert hasattr(fenster, "btn_nachkalibrieren")

    def test_er_erklaert_sich(self, fenster):
        hinweis = fenster.btn_nachkalibrieren.toolTip()
        assert "anklicken" in hinweis and "gross" in hinweis

    def test_ohne_kalibrierung_kommt_eine_erklaerung(self, fenster, monkeypatch):
        fenster.session.calibration = Calibration(lanes=[])
        gezeigt = []
        monkeypatch.setattr(mw.QMessageBox, "information",
                            lambda *a, **k: gezeigt.append(a))
        fenster._on_nachkalibrieren()
        assert gezeigt, "ohne Bahnen gibt es nichts nachzuziehen"

    def test_eine_einzige_tafel_wird_direkt_geoeffnet(self, fenster, monkeypatch):
        """Bei nur einer Tafel gibt es nichts auszuwaehlen -- ein Klick, der
        keine Wahl laesst, ist ein ueberfluessiger Klick."""
        fenster.session.calibration = Calibration(lanes=[eine_bahn(1)])
        geoeffnet = []
        monkeypatch.setattr(fenster, "_oeffne_tafel_editor", geoeffnet.append)
        fenster._on_nachkalibrieren()
        assert len(geoeffnet) == 1
        assert not fenster._nachkal_auswahl


# ------------------------------------------------------------ Die Tafelauswahl

class TestTafelAnklicken:
    def test_der_klick_zieht_nicht(self, fenster):
        """DER FEHLER, DEN ES ZU VERHINDERN GILT: Bliebe das Ziehen an,
        verschoebe der Auswahlklick den Bereich unter dem Zeiger."""
        fenster._on_nachkalibrieren()
        assert fenster._nachkal_auswahl
        assert not fenster.video_view._drag_erlaubt

    def test_ein_ereignis_darf_das_ziehen_nicht_zurueckholen(self, fenster):
        """`_update_calibration_hint` laeuft bei jedem Anlass -- und schaltet
        sonst das Ziehen wieder ein."""
        fenster._on_nachkalibrieren()
        fenster._update_calibration_hint()
        assert not fenster.video_view._drag_erlaubt

    def test_klick_in_die_tafel_oeffnet_genau_diese(self, fenster, monkeypatch):
        geoeffnet = []
        monkeypatch.setattr(fenster, "_oeffne_tafel_editor", geoeffnet.append)
        fenster._on_nachkalibrieren()
        fenster._on_video_clicked(180.0, 70.0)      # in Tafel 2
        assert [b.lane_id for b in geoeffnet] == [2]

    def test_daneben_bleibt_die_auswahl_stehen(self, fenster, monkeypatch):
        """Ein Fehlklick darf den Vorgang nicht abbrechen -- sonst muss man den
        Knopf erneut suchen, nur weil man 5 Pixel danebengetroffen hat."""
        geoeffnet = []
        monkeypatch.setattr(fenster, "_oeffne_tafel_editor", geoeffnet.append)
        fenster._on_nachkalibrieren()
        fenster._on_video_clicked(5.0, 5.0)
        assert not geoeffnet
        assert fenster._nachkal_auswahl

    def test_esc_beendet_die_auswahl(self, fenster):
        fenster._on_nachkalibrieren()
        fenster._on_cancel_calibration()
        assert not fenster._nachkal_auswahl
        assert fenster.video_view._drag_erlaubt, "danach muss wieder ziehbar sein"

    def test_waehrend_der_auswahl_wird_nichts_gesetzt(self, fenster, monkeypatch):
        """Der Klick darf auch keinen Kalibrierpunkt setzen."""
        monkeypatch.setattr(fenster, "_oeffne_tafel_editor", lambda lane: None)
        fenster._on_nachkalibrieren()
        vorher = list(fenster.session.pending_points)
        fenster._on_video_clicked(60.0, 70.0)
        assert list(fenster.session.pending_points) == vorher


# ----------------------------------------------------------------- Die Leinwand

class TestLeinwand:
    def _leinwand(self, qt_app):
        leinwand = be.TafelLeinwand(eine_bahn().rois, (100, 100))
        leinwand.resize(400, 400)
        leinwand.set_bild(bild(120, 100, 100))
        return leinwand

    def test_sie_arbeitet_auf_kopien(self, qt_app):
        bahn = eine_bahn()
        leinwand = be.TafelLeinwand(bahn.rois, (100, 100))
        leinwand._aendere("green_lamp", "move", 0.1, 0.1)
        assert bahn.rois[0].rect[0] == pytest.approx(0.45), \
            "die Bahn selbst darf sich erst beim Uebernehmen aendern"

    def test_verschieben_setzt_die_mitte(self, qt_app):
        leinwand = self._leinwand(qt_app)
        leinwand._aendere("green_lamp", "move", 0.30, 0.40)
        roi = leinwand._roi("green_lamp")
        assert roi.center == pytest.approx((0.30, 0.40), abs=1e-6)

    def test_die_groesse_bleibt_beim_verschieben(self, qt_app):
        leinwand = self._leinwand(qt_app)
        leinwand._aendere("green_lamp", "move", 0.30, 0.40)
        assert leinwand._roi("green_lamp").rect[2:] == pytest.approx((0.06, 0.06))

    def test_kein_bereich_verlaesst_die_tafel(self, qt_app):
        """`model_copy` prueft nichts -- ein hinausgezogener Bereich waere
        still kaputt und erst beim Speichern aufgefallen."""
        leinwand = self._leinwand(qt_app)
        for ziel in ((-5.0, 0.5), (7.0, 0.5), (0.5, -3.0), (0.5, 9.0)):
            leinwand._aendere("green_lamp", "move", *ziel)
            x, y, w, h = leinwand._roi("green_lamp").rect
            assert 0.0 <= x and 0.0 <= y and x + w <= 1.0001 and y + h <= 1.0001

    def test_rand_ziehen_aendert_die_groesse(self, qt_app):
        leinwand = self._leinwand(qt_app)
        vorher = leinwand._roi("digit_throw_number_1").rect
        leinwand._aendere("digit_throw_number_1", "r", 0.40, 0.90)
        nachher = leinwand._roi("digit_throw_number_1").rect
        assert nachher[2] > vorher[2]
        assert nachher[0] == pytest.approx(vorher[0]), "der linke Rand bleibt"

    def test_ein_bereich_laesst_sich_nicht_auf_null_ziehen(self, qt_app):
        from kegel_cv.calibration.session import CalibrationSession
        leinwand = self._leinwand(qt_app)
        leinwand._aendere("digit_throw_number_1", "r", 0.0, 0.9)
        assert (leinwand._roi("digit_throw_number_1").rect[2]
                >= CalibrationSession.MINDESTKANTE - 1e-9)

    def test_der_kleinste_bereich_gewinnt(self, qt_app):
        """Eine Ziffernstelle liegt INNERHALB ihres Gesamtfeldes -- gemeint ist
        die Stelle."""
        from PySide6.QtCore import QPointF
        leinwand = self._leinwand(qt_app)
        f = leinwand._kasten(leinwand._roi("digit_throw_number_1"))
        treffer = leinwand._treffer(QPointF(f.center()))
        assert treffer is not None and treffer[0] == "digit_throw_number_1"

    def test_die_mitte_verschiebt_der_rand_verzieht(self, qt_app):
        from PySide6.QtCore import QPointF
        leinwand = self._leinwand(qt_app)
        kasten = leinwand._kasten(leinwand._roi("green_lamp"))
        assert leinwand._kante(QPointF(kasten.center()), kasten) == "move"
        rechts = QPointF(kasten.right(), kasten.center().y())
        assert "r" in leinwand._kante(rechts, kasten)

    def test_pfeiltaste_schiebt_um_einen_tafelpixel(self, qt_app):
        """Mit der Maus ist ein einzelner Pixel nicht zu treffen -- und genau
        um einen einzelnen geht es bei den Ziffern (gemessen: ein Pixel = neun
        Prozentpunkte Lesegenauigkeit)."""
        leinwand = self._leinwand(qt_app)
        leinwand.waehle(["green_lamp"])
        vorher = leinwand._roi("green_lamp").center
        leinwand.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right,
                                         Qt.NoModifier))
        nachher = leinwand._roi("green_lamp").center
        assert nachher[0] - vorher[0] == pytest.approx(1 / 100, abs=1e-9)
        assert nachher[1] == pytest.approx(vorher[1])

    def test_ohne_auswahl_tut_die_pfeiltaste_nichts(self, qt_app):
        leinwand = self._leinwand(qt_app)
        vorher = [r.rect for r in leinwand.rois]
        leinwand.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right,
                                         Qt.NoModifier))
        assert [r.rect for r in leinwand.rois] == vorher


# ------------------------------------------------------------------- Entzerren

class TestEntzerren:
    def test_die_tafel_kommt_im_wahren_seitenverhaeltnis(self, qt_app):
        """Nicht im Rechenformat 440x530 -- wer beurteilen soll, ob ein Rahmen
        sitzt, will die Tafel sehen und nicht ihr Rechenformat."""
        tafel = be.entzerre(bild(), eine_bahn().quad)
        assert tafel is not None
        hoehe, breite = tafel.shape[:2]
        assert breite == pytest.approx(hoehe, abs=2), "die Tafel ist quadratisch"

    def test_ein_entartetes_viereck_stuerzt_nicht_ab(self, qt_app):
        """P8: Fehler beenden nichts. Waehrend des Ziehens an einer Tafelecke
        ist das Viereck kurzzeitig entartet."""
        platt = [[10.0, 10.0], [10.0, 10.0], [10.0, 10.0], [10.0, 10.0]]
        assert be.entzerre(bild(), platt) is None


# --------------------------------------------------------------- Der Dialog

class TestDialog:
    def test_er_passt_auf_den_bildschirm(self, qt_app):
        """Derselbe Fehler wie beim Bestaetigungsdialog soll sich nicht
        wiederholen: 'kann man wegen der Fenstergroesse nicht bestaetigen'."""
        d = be.TafelEditorDialog(eine_bahn(), bild())
        platz = QApplication.primaryScreen().availableGeometry()
        assert d.width() <= platz.width() and d.height() <= platz.height()

    def test_ohne_zweite_tafel_keine_uebertragungsfrage(self, qt_app):
        d = be.TafelEditorDialog(eine_bahn(), bild(), tafeln=1)
        assert d.alle is None

    def test_mit_mehreren_tafeln_gibt_es_die_wahl(self, qt_app):
        d = be.TafelEditorDialog(eine_bahn(), bild(), tafeln=4)
        assert d.alle is not None and not d.alle.isChecked(), \
            "uebertragen wird nur auf Wunsch -- meist sitzt nur eine daneben"

    def test_zuruecksetzen_stellt_den_ausgangsstand_her(self, qt_app):
        d = be.TafelEditorDialog(eine_bahn(), bild())
        d.leinwand._aendere("green_lamp", "move", 0.1, 0.1)
        d.leinwand.setze_rois(d._ausgang)
        assert d.leinwand._roi("green_lamp").center == pytest.approx((0.48, 0.73))


class TestUebernehmen:
    """Was der Dialog liefert, muss in der Sitzung ankommen -- und beim
    Abbrechen eben NICHT."""

    class UnechterDialog:
        def __init__(self, rois, angenommen=True, auf_alle=False):
            self.rois = rois
            self.auf_alle = auf_alle
            self._angenommen = angenommen

        def __call__(self, *args, **kwargs):
            return self

        def exec(self):
            return QDialog.Accepted if self._angenommen else QDialog.Rejected

    def _mit_dialog(self, fenster, monkeypatch, dialog):
        monkeypatch.setattr(be, "TafelEditorDialog", dialog)
        fenster._oeffne_tafel_editor(fenster.session.calibration.lanes[0])

    def test_uebernehmen_schreibt_die_bereiche(self, fenster, monkeypatch):
        neu = [Roi(name="green_lamp", rect=(0.10, 0.10, 0.06, 0.06))]
        self._mit_dialog(fenster, monkeypatch, self.UnechterDialog(neu))
        bahn = fenster.session.calibration.get_lane(1)
        assert bahn.get_roi("green_lamp").rect[0] == pytest.approx(0.10)

    def test_abbrechen_aendert_nichts(self, fenster, monkeypatch):
        neu = [Roi(name="green_lamp", rect=(0.10, 0.10, 0.06, 0.06))]
        self._mit_dialog(fenster, monkeypatch,
                         self.UnechterDialog(neu, angenommen=False))
        bahn = fenster.session.calibration.get_lane(1)
        assert bahn.get_roi("green_lamp").rect[0] == pytest.approx(0.45)

    def test_nur_die_angeklickte_tafel_aendert_sich(self, fenster, monkeypatch):
        neu = [Roi(name="green_lamp", rect=(0.10, 0.10, 0.06, 0.06))]
        self._mit_dialog(fenster, monkeypatch, self.UnechterDialog(neu))
        andere = fenster.session.calibration.get_lane(2)
        assert andere.get_roi("green_lamp").rect[0] == pytest.approx(0.45)

    def test_auf_wunsch_alle(self, fenster, monkeypatch):
        """Die Bereiche liegen in normierten Tafelkoordinaten -- was auf einer
        Tafel sitzt, sitzt auf jeder derselben Bauart."""
        neu = [Roi(name="green_lamp", rect=(0.10, 0.10, 0.06, 0.06))]
        self._mit_dialog(fenster, monkeypatch,
                         self.UnechterDialog(neu, auf_alle=True))
        for bahn in fenster.session.calibration.lanes:
            assert bahn.get_roi("green_lamp").rect[0] == pytest.approx(0.10)

    def test_die_rois_werden_danach_gezeichnet(self, fenster, monkeypatch):
        """Ohne Neuzeichnen sieht man die Korrektur nicht -- derselbe Fehler
        wie nach der automatischen Kalibrierung (2026-09-10)."""
        neu = [Roi(name="green_lamp", rect=(0.10, 0.10, 0.06, 0.06))]
        self._mit_dialog(fenster, monkeypatch, self.UnechterDialog(neu))
        assert fenster.video_view._rois

    def test_ein_stream_wird_nicht_angehalten(self, fenster, monkeypatch):
        """Der Player holt neue Bilder nur, solange er laeuft. Angehalten
        stuende im Dialog dieselbe Anzeige wie vor fuenf Minuten -- und ob eine
        Ziffernbox sitzt, entscheidet sich an WECHSELNDEN Ziffern."""
        fenster.player = self.StummerPlayer(live=True)
        self._mit_dialog(fenster, monkeypatch, self.UnechterDialog([]))
        assert not fenster.player.angehalten

    def test_eine_datei_wird_angehalten(self, fenster, monkeypatch):
        """Dort laeuft sonst das Spiel weiter, waehrend man zieht."""
        fenster.player = self.StummerPlayer(live=False)
        self._mit_dialog(fenster, monkeypatch, self.UnechterDialog([]))
        assert fenster.player.angehalten

    class StummerPlayer:
        def __init__(self, live: bool):
            self.is_live = live
            self.is_loaded = True
            self.angehalten = False
            self.current_frame = Frame(index=0, timestamp=0.0, image=bild())

        def pause(self):
            self.angehalten = True

        def close(self):
            self.is_loaded = False

    def test_es_werden_kopien_geschrieben(self, fenster, monkeypatch):
        """Sonst haengen zwei Bahnen am selben Objekt, und das Ziehen an der
        einen verschiebt die andere mit."""
        neu = [Roi(name="green_lamp", rect=(0.10, 0.10, 0.06, 0.06))]
        self._mit_dialog(fenster, monkeypatch,
                         self.UnechterDialog(neu, auf_alle=True))
        bahnen = fenster.session.calibration.lanes
        assert (bahnen[0].get_roi("green_lamp")
                is not bahnen[1].get_roi("green_lamp"))


class TestMehrereZugleich:
    """"je Tafel die Moeglichkeit, ein Offset von x und y zu setzen ... dafuer
    soll er die ROIs anklicken, die er gleichzeitig verschieben moechte"
    (Nutzer, 2026-09-11).

    Der Grund ist nicht Bequemlichkeit: Was zusammen danebenliegt, gehoert
    zusammen verschoben. Die untere Ziffernzeile wandert GEMESSEN als Ganzes --
    sie einzeln nachzuziehen hiesse, denselben Fehler achtmal zu schaetzen.
    """

    def _leinwand(self, qt_app):
        leinwand = be.TafelLeinwand(eine_bahn().rois, (100, 100))
        leinwand.resize(400, 400)
        leinwand.set_bild(bild(120, 100, 100))
        return leinwand

    def test_die_auswahl_laesst_sich_setzen(self, qt_app):
        leinwand = self._leinwand(qt_app)
        leinwand.waehle(["green_lamp", "throw_number"])
        assert leinwand.auswahl == {"green_lamp", "throw_number"}

    def test_unbekannte_namen_werden_uebergangen(self, qt_app):
        leinwand = self._leinwand(qt_app)
        leinwand.waehle(["green_lamp", "gibt_es_nicht"])
        assert leinwand.auswahl == {"green_lamp"}

    def test_alle_gewaehlten_wandern_gleich_weit(self, qt_app):
        leinwand = self._leinwand(qt_app)
        vorher = {r.name: r.rect for r in leinwand.rois}
        leinwand.waehle(["green_lamp", "throw_number"])
        leinwand.versetze(3, -2)
        for name in ("green_lamp", "throw_number"):
            neu = leinwand._roi(name).rect
            assert neu[0] - vorher[name][0] == pytest.approx(3 / 100, abs=1e-9)
            assert neu[1] - vorher[name][1] == pytest.approx(-2 / 100, abs=1e-9)

    def test_nicht_gewaehlte_bleiben_stehen(self, qt_app):
        leinwand = self._leinwand(qt_app)
        vorher = leinwand._roi("digit_throw_number_1").rect
        leinwand.waehle(["green_lamp"])
        leinwand.versetze(3, 3)
        assert leinwand._roi("digit_throw_number_1").rect == vorher

    def test_der_versatz_ist_ein_GESAMTwert(self, qt_app):
        """Wer von +2 auf +3 dreht, verschiebt um einen Pixel, nicht um drei --
        sonst liefe ein Drehen am Eingabefeld davon."""
        leinwand = self._leinwand(qt_app)
        vorher = leinwand._roi("green_lamp").rect[0]
        leinwand.waehle(["green_lamp"])
        leinwand.versetze(2, 0)
        leinwand.versetze(3, 0)
        assert leinwand._roi("green_lamp").rect[0] - vorher == \
            pytest.approx(3 / 100, abs=1e-9)

    def test_ohne_auswahl_passiert_nichts(self, qt_app):
        leinwand = self._leinwand(qt_app)
        vorher = {r.name: r.rect for r in leinwand.rois}
        leinwand.versetze(5, 5)
        assert {r.name: r.rect for r in leinwand.rois} == vorher

    def test_auch_gemeinsam_bleibt_alles_in_der_tafel(self, qt_app):
        leinwand = self._leinwand(qt_app)
        leinwand.waehle([r.name for r in leinwand.rois])
        leinwand.versetze(90, 90)
        for roi in leinwand.rois:
            x, y, w, h = roi.rect
            assert 0.0 <= x and x + w <= 1.0001
            assert 0.0 <= y and y + h <= 1.0001

    def test_pfeiltaste_bewegt_die_ganze_auswahl(self, qt_app):
        leinwand = self._leinwand(qt_app)
        leinwand.waehle(["green_lamp", "throw_number"])
        vorher = {r.name: r.rect[0] for r in leinwand.rois}
        leinwand.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Right,
                                         Qt.NoModifier))
        for name in ("green_lamp", "throw_number"):
            assert leinwand._roi(name).rect[0] - vorher[name] == \
                pytest.approx(1 / 100, abs=1e-9)


class TestDieBedienelemente:
    def test_die_gruppenknoepfe_waehlen_richtig(self, qt_app):
        d = be.TafelEditorDialog(eine_bahn(), bild())
        from PySide6.QtWidgets import QPushButton
        knoepfe = {k.text(): k for k in d.findChildren(QPushButton)}
        knoepfe["Lampen"].click()
        assert d.leinwand.auswahl == {"green_lamp"}
        knoepfe["Ziffern"].click()
        assert d.leinwand.auswahl == {"digit_throw_number_1", "throw_number"}

    def test_der_versatz_wirkt_ueber_das_eingabefeld(self, qt_app):
        d = be.TafelEditorDialog(eine_bahn(), bild())
        vorher = d.leinwand._roi("green_lamp").rect[0]
        d.leinwand.waehle(["green_lamp"])
        d.versatz_x.setValue(4)
        assert d.leinwand._roi("green_lamp").rect[0] > vorher

    def test_eine_neue_auswahl_setzt_den_versatz_zurueck(self, qt_app):
        """Bliebe der alte Wert stehen, verschoebe sich die naechste Auswahl
        beim ersten Dreh um die Differenz zu einem Wert, der sie nie betraf."""
        d = be.TafelEditorDialog(eine_bahn(), bild())
        d.leinwand.waehle(["green_lamp"])
        d.versatz_x.setValue(4)
        d.leinwand.waehle(["throw_number"])
        assert d.versatz_x.value() == 0

    def test_ohne_auswahl_sagt_er_es(self, qt_app):
        d = be.TafelEditorDialog(eine_bahn(), bild())
        d.versatz_x.setValue(3)
        assert "anklicken" in d.auswahl_info.text()
        assert d.versatz_x.value() == 0
