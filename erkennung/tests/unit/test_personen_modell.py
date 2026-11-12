"""Das Personenmodell -- der vierte Zeuge.

DER ANLASS (Nutzer, 2026-09-13): *"Am einfachsten waere es, wenn du Personen
zielsicher erkennen und permanent schwaerzen wuerdest, dann haetten wir das
Problem gar nicht."*

DIE MESSUNG, die diesem Modul seine Form gab -- Livestream Fastlane:

    Zuschnitt                        Beweisstelle F42237   Fehlalarme/600
    ----------------------------------------------------------------------
    Tafel allein (136x136 px)         19 von 70 Frames            0
    Band ueber alle vier Tafeln       53 von 70 Frames            0
    Band, nach unten verlaengert      57 von 70 Frames            0

    Gegenprobe an den 1682 Bildern, die wirklich in die Datenbank gingen:
    auf dem blanken Tafelausschnitt 0 von 2 bekannten Gesichtern gefunden.

Deshalb sucht das Modul in EINEM Band ueber alle Tafeln und nicht viermal im
einzelnen Ausschnitt -- und deshalb pruefen die Tests hier vor allem die
Geometrie und die Sparsamkeit, nicht die Treffsicherheit des Netzes. Die
haengt an einer 20 MB grossen Gewichtsdatei, die nicht im Repo liegt.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration.model import LaneCalibration, Roi
from kegel_cv.config import load_config
from kegel_cv.detection.personen_modell import PersonenModell

FORM = (1080, 1920, 3)
TAFELN = {2: (500, 70, 140, 140), 3: (760, 72, 140, 140),
          4: (960, 76, 140, 140), 5: (1210, 80, 140, 140)}


def modell(**kw) -> PersonenModell:
    grund = dict(eingang=640, vertrauen=0.25, luft_unten=1.0, luft_seitlich=0.05)
    grund.update(kw)
    return PersonenModell(None, **grund)


class TestOhneModelldateiBleibtEsStill:
    """Die Gewichtsdatei liegt nicht im Repo. Fehlt sie, darf das die Analyse
    NICHT anhalten (Projektregel P8) -- eine Warnung, kein Fehler."""

    def test_fehlende_datei_ist_kein_fehler(self):
        m = modell()
        assert m.bereit is False

    def test_suche_liefert_leer_statt_zu_werfen(self):
        m = modell()
        m.setze_tafeln(TAFELN, FORM)
        assert m.suche(np.zeros(FORM, np.uint8), 1) == []

    def test_abgeschaltet_laedt_gar_nicht(self):
        m = PersonenModell("models/gibtsnicht.onnx", aktiv=False)
        assert m.bereit is False

    def test_die_konfiguration_zeigt_auf_ein_apache_modell(self):
        """Das Projekt steht unter MIT. YOLOv8n (Ultralytics) waere AGPL-3.0
        und liesse sich damit nicht vereinbaren -- ein Werk mit AGPL-Teilen
        kann nicht unter MIT stehen. YOLOX (Megvii) ist Apache-2.0."""
        pm = load_config().detection.person_model
        assert "yolox" in pm.model_path.lower()
        assert "Megvii" in pm.model_url

    def test_unlesbare_datei_haelt_nicht_an(self, tmp_path):
        murks = tmp_path / "kaputt.onnx"
        murks.write_bytes(b"das ist kein ONNX")
        m = PersonenModell(murks)
        assert m.bereit is False


class TestDasBand:
    """Ein Rechteck ueber alle Tafeln -- der einzige Suchbereich."""

    def test_umschliesst_alle_tafeln(self):
        m = modell(luft_unten=0.0, luft_seitlich=0.0)
        m.setze_tafeln(TAFELN, FORM)
        x, y, w, h = m._band
        for tx, ty, tw, th in TAFELN.values():
            assert x <= tx and y <= ty
            assert x + w >= tx + tw and y + h >= ty + th

    def test_reicht_nach_unten_ueber_die_tafeln_hinaus(self):
        """Dort steht der Rumpf, und mit Rumpf findet das Netz den Menschen
        sicherer: GEMESSEN 57 statt 53 von 70 Beweisframes."""
        ohne = modell(luft_unten=0.0)
        mit = modell(luft_unten=1.0)
        ohne.setze_tafeln(TAFELN, FORM)
        mit.setze_tafeln(TAFELN, FORM)
        assert mit._band[3] > ohne._band[3] * 1.9

    def test_bleibt_im_bild(self):
        m = modell(luft_unten=4.0, luft_seitlich=1.0)
        m.setze_tafeln(TAFELN, FORM)
        x, y, w, h = m._band
        assert x >= 0 and y >= 0
        assert x + w <= FORM[1] and y + h <= FORM[0]

    def test_ohne_tafeln_kein_band(self):
        m = modell()
        m.setze_tafeln({2: None, 3: None}, FORM)
        assert m._band is None
        assert m.bereit is False

    def test_unbrauchbare_bahnen_ziehen_das_band_nicht_auf(self):
        """Eine Bahn ohne Kalibrierung darf das Band nicht ueber das halbe
        Bild spannen -- die anderen drei wuerden mitbezahlen."""
        m = modell(luft_unten=0.0, luft_seitlich=0.0)
        m.setze_tafeln({**TAFELN, 6: None}, FORM)
        assert m._band[2] <= 1210 + 140 - 500


class TestHoechstensEinLaufJeFrame:
    """Vier Bahnen fragen, das Netz rechnet einmal -- sonst kostet ein Frame
    das Vierfache."""

    def test_zweite_frage_im_selben_frame_rechnet_nicht_neu(self, monkeypatch):
        m = modell()
        m.setze_tafeln(TAFELN, FORM)
        m._netz = object()                       # gilt jetzt als geladen
        laeufe = []
        monkeypatch.setattr(m, "_netz_fragen",
                            lambda bild: laeufe.append(1) or [(10, 10, 20, 40, 0.9)])
        bild = np.zeros(FORM, np.uint8)
        for _ in range(4):
            m.suche(bild, 100)
        assert len(laeufe) == 1

    def test_naechster_frame_rechnet_wieder(self, monkeypatch):
        m = modell()
        m.setze_tafeln(TAFELN, FORM)
        m._netz = object()
        laeufe = []
        monkeypatch.setattr(m, "_netz_fragen",
                            lambda bild: laeufe.append(1) or [])
        bild = np.zeros(FORM, np.uint8)
        m.suche(bild, 100)
        m.suche(bild, 101)
        assert len(laeufe) == 2


class TestWasDasModellDerBahnSagt:
    def test_anteil_der_bedeckten_tafel(self):
        m = modell()
        m.setze_tafeln(TAFELN, FORM)
        m._netz = object()
        m._ergebnisse[7] = [(500, 70, 70, 140, 0.9)]   # linke Haelfte Tafel 2
        assert m.auf_tafel(TAFELN[2], 7) == pytest.approx(0.5, abs=0.02)
        assert m.auf_tafel(TAFELN[3], 7) == 0.0

    def test_ohne_fund_null(self):
        m = modell()
        m.setze_tafeln(TAFELN, FORM)
        m._netz = object()
        m._ergebnisse[7] = []
        assert m.auf_tafel(TAFELN[2], 7) == 0.0

    def test_maske_liegt_im_ausschnitt_und_trifft_die_stelle(self):
        m = modell()
        m.setze_tafeln(TAFELN, FORM)
        m._netz = object()
        m._ergebnisse[7] = [(520, 90, 40, 40, 0.8)]
        maske = m.maske_im_ausschnitt(TAFELN[2], 7)
        assert maske is not None
        assert maske.shape == (140, 140)
        assert maske[30, 30] == 255           # 90-70=20 .. 60, also drin
        assert maske[120, 120] == 0

    def test_fund_ausserhalb_gibt_keine_maske(self):
        m = modell()
        m.setze_tafeln(TAFELN, FORM)
        m._netz = object()
        m._ergebnisse[7] = [(1500, 600, 40, 40, 0.8)]
        assert m.maske_im_ausschnitt(TAFELN[2], 7) is None


def bahn() -> LaneCalibration:
    rois = [Roi(name="green_lamp", rect=(0.45, 0.75, 0.06, 0.05))]
    rois += [Roi(name=f"pin_lamp_{i}", rect=(0.10 + 0.08 * i, 0.30, 0.04, 0.04),
                 pin_number=i) for i in range(1, 10)]
    return LaneCalibration(lane_id=1,
                           quad=[[500.0, 70.0], [640.0, 70.0],
                                 [640.0, 210.0], [500.0, 210.0]], rois=rois)


class TestDieBahnFragtSparsam:
    """Projektregel 4: billige Trigger steuern teure Analyse. Ein Aufruf
    kostet gemessen 68 ms, das Budget je Frame sind 40 ms."""

    def prozessor(self, takt: int = 10, schwelle: float = 0.0) -> LaneProcessor:
        cfg = load_config()
        cfg.detection.person_model.patrol_interval = takt
        cfg.detection.green.occlusion_score = schwelle
        p = LaneProcessor(bahn(), cfg)
        p.prepare(FORM)
        return p

    class Attrappe:
        bereit = True

        def __init__(self):
            self.gefragt = 0
            self.anteil = 0.0
            self.letzter_lauf = None

        def suche(self, bild, index):
            self.gefragt += 1
            self.letzter_lauf = index
            return []

        def merke(self, bild, index):
            pass

        def auf_tafel(self, kasten, index):
            return self.anteil

        def maske_im_ausschnitt(self, kasten, index):
            return None

    class Gruen:
        def __init__(self, score):
            self.score = score

    class Frame:
        def __init__(self, index):
            self.index = index

    def test_ruhiger_frame_fragt_nicht(self):
        p = self.prozessor(takt=0)
        a = self.Attrappe()
        p.setze_personenmodell(a)
        p.setze_rohbild(np.zeros(FORM, np.uint8))
        p._frage_das_modell(self.Frame(101), self.Gruen(80.0))
        assert a.gefragt == 0
        assert p._modell_meldet_person is False

    def test_gefallener_gruenscore_fragt(self):
        p = self.prozessor(takt=0, schwelle=8.0)
        a = self.Attrappe()
        a.anteil = 0.3
        p.setze_personenmodell(a)
        p.setze_rohbild(np.zeros(FORM, np.uint8))
        p._frage_das_modell(self.Frame(101), self.Gruen(0.0))
        assert a.gefragt == 1
        assert p._modell_meldet_person is True

    def test_die_wache_fragt_mit(self):
        p = self.prozessor(takt=0)
        a = self.Attrappe()
        p.setze_personenmodell(a)
        p.setze_rohbild(np.zeros(FORM, np.uint8))
        p._wache_meldet_fremdes = True
        p._frage_das_modell(self.Frame(101), self.Gruen(80.0))
        assert a.gefragt == 1

    def test_die_streife_fragt_im_takt(self):
        """Fuer den Menschen, der auf der Tafel steht, ohne die gruene Lampe
        zu beruehren -- den sieht sonst kein Zeuge."""
        p = self.prozessor(takt=10)
        a = self.Attrappe()
        p.setze_personenmodell(a)
        p.setze_rohbild(np.zeros(FORM, np.uint8))
        for i in range(100, 130):
            p._frage_das_modell(self.Frame(i), self.Gruen(80.0))
        assert a.gefragt == 3

    def test_im_alarm_wird_nicht_jeder_frame_gefragt(self):
        """GEMESSEN: EIN festhaengender Zeuge (Tafelwache auf Bahn 5, 2704 von
        3000 Frames) trieb das Netz sonst in 94 % aller Frames und den
        Durchsatz von 32 auf 11 Frames/s."""
        p = self.prozessor(takt=10, schwelle=8.0)
        a = self.Attrappe()
        p.setze_personenmodell(a)
        p.setze_rohbild(np.zeros(FORM, np.uint8))
        for i in range(100, 120):
            p._frage_das_modell(self.Frame(i), self.Gruen(0.0))
        assert a.gefragt == 4          # alle 5 Frames, nicht 20-mal

    def test_eine_frische_antwort_wird_mitgelesen(self):
        """Der Abstand zaehlt ueber alle Bahnen: Das Netz sucht in EINEM Band
        ueber alle vier Tafeln, seine Antwort gilt fuer alle zugleich. Je Bahn
        gerechnet trieben die vier die Quote von 20 auf 33 %."""
        p = self.prozessor(takt=10, schwelle=8.0)
        a = self.Attrappe()
        a.letzter_lauf = 100           # eine andere Bahn hat schon gefragt
        a.anteil = 0.5
        p.setze_personenmodell(a)
        p.setze_rohbild(np.zeros(FORM, np.uint8))
        p._frage_das_modell(self.Frame(102), self.Gruen(0.0))
        assert a.gefragt == 0
        assert p._modell_meldet_person is True

    def test_die_streife_schliesst_die_luecke_am_laufanfang(self):
        """GEMESSEN als Nebenbefund am 2026-09-13: Solange noch kein AUS-Niveau
        gelernt ist, faellt die Verdeckungsschwelle auf den festen Wert 0
        zurueck -- und ein Gruen-Score von exakt 0,0 ist NICHT kleiner als 0.
        Eine vollstaendig verdeckte Lampe kaeme am Laufanfang also an allen
        drei billigen Zeugen vorbei. Die Streife fragt trotzdem."""
        p = self.prozessor(takt=10, schwelle=0.0)
        assert p._verdeckungsschwelle() == 0.0
        a = self.Attrappe()
        a.anteil = 0.4
        p.setze_personenmodell(a)
        p.setze_rohbild(np.zeros(FORM, np.uint8))
        p._frage_das_modell(self.Frame(100), self.Gruen(0.0))
        assert a.gefragt == 1
        assert p._modell_meldet_person is True

    def test_ohne_rohbild_wird_nicht_gefragt(self):
        p = self.prozessor(takt=1)
        a = self.Attrappe()
        p.setze_personenmodell(a)
        p._frage_das_modell(self.Frame(100), self.Gruen(0.0))
        assert a.gefragt == 0

    def test_ohne_modell_bleibt_alles_beim_alten(self):
        p = self.prozessor(takt=1)
        p.setze_rohbild(np.zeros(FORM, np.uint8))
        p._frage_das_modell(self.Frame(100), self.Gruen(0.0))
        assert p._modell_meldet_person is False


class TestDieFremdmaskeVereinigtBeideQuellen:
    """Die Wache findet auch, was kein Mensch ist; das Modell findet auch den,
    der so still steht, dass die Referenz ihn fast schon kennt."""

    def test_modellmaske_kommt_hinzu(self):
        cfg = load_config()
        p = LaneProcessor(bahn(), cfg)
        p.prepare(FORM)

        class NurModell:
            bereit = True

            def maske_im_ausschnitt(self, kasten, index):
                m = np.zeros((kasten[3], kasten[2]), np.uint8)
                m[:20, :20] = 255
                return m

        p.setze_personenmodell(NurModell())
        maske = p.fremdmaske(np.zeros(FORM, np.uint8), 5)
        assert maske is not None
        assert maske[5, 5] == 255

    def test_ohne_beide_quellen_keine_maske(self):
        cfg = load_config()
        p = LaneProcessor(bahn(), cfg)
        p.prepare(FORM)
        assert p.fremdmaske(None) is None


class TestDasGedaechtnisFuerRoheBandausschnitte:
    """Das veroeffentlichte Tafelbild stammt NICHT aus dem laufenden Frame,
    sondern aus einem Sample-Frame -- bis zu 34 Frames zurueck. Der Ringpuffer
    der Pipeline haelt aber nur MASKIERTE Bilder, und auf denen verliert das
    Netz den Menschen: GEMESSEN an 12 Beweisframes in 2 davon (F265723 und
    F265724, beide roh sicher gefunden). Deshalb dieses Gedaechtnis."""

    def bereites(self, monkeypatch, tiefe=5):
        m = modell(gedaechtnis=tiefe)
        m.setze_tafeln(TAFELN, FORM)
        m._netz = object()
        self.laeufe = []
        monkeypatch.setattr(
            m, "_netz_fragen",
            lambda bild: self.laeufe.append(1) or [(0, 0, 40, 40, 0.9)])
        return m

    def test_ein_alter_frame_ist_noch_abfragbar(self, monkeypatch):
        m = self.bereites(monkeypatch)
        bild = np.zeros(FORM, np.uint8)
        for i in range(100, 104):
            m.merke(bild, i)
        assert m.funde_fuer(100) != []

    def test_gerechnet_wird_je_frame_genau_einmal(self, monkeypatch):
        m = self.bereites(monkeypatch)
        m.merke(np.zeros(FORM, np.uint8), 100)
        for _ in range(4):
            m.funde_fuer(100)
        assert len(self.laeufe) == 1

    def test_was_herausgefallen_ist_wird_nicht_geraten(self, monkeypatch):
        """Lieber nichts behaupten als die Kaesten eines anderen Frames
        benutzen -- ein Mensch bewegt sich, und eine versetzte Schwaerzung
        traefe daneben."""
        m = self.bereites(monkeypatch, tiefe=3)
        bild = np.zeros(FORM, np.uint8)
        for i in range(100, 110):
            m.merke(bild, i)
        assert m.funde_fuer(100) == []
        assert m.funde_fuer(109) != []

    def test_das_gedaechtnis_waechst_nicht_unbegrenzt(self, monkeypatch):
        m = self.bereites(monkeypatch, tiefe=4)
        bild = np.zeros(FORM, np.uint8)
        for i in range(500):
            m.merke(bild, i)
            m.funde_fuer(i)
        assert len(m._gedaechtnis) <= 4
        assert len(m._ergebnisse) <= 4

    def test_vorskaliert_auf_die_arbeitsaufloesung(self):
        """Das Band wird ohnehin auf `eingang` heruntergerechnet -- klein
        aufgehoben spart Faktor vier, ohne dass das Netz weniger sieht."""
        m = modell(eingang=640)
        klein, faktor = m._vorskaliert(np.zeros((440, 1324, 3), np.uint8))
        assert max(klein.shape[:2]) == 640
        assert faktor == pytest.approx(640 / 1324, abs=0.001)

    def test_kleines_band_wird_nicht_hochskaliert(self):
        m = modell(eingang=640)
        klein, faktor = m._vorskaliert(np.zeros((100, 300, 3), np.uint8))
        assert klein.shape[:2] == (100, 300)
        assert faktor == 1.0

    def test_kaesten_kommen_in_bildkoordinaten_zurueck(self, monkeypatch):
        """Vorskalierung und Bandversatz muessen beide zurueckgerechnet
        werden -- sonst schwaerzt die Maske an der falschen Stelle."""
        m = modell(gedaechtnis=5, luft_unten=0.0, luft_seitlich=0.0)
        m.setze_tafeln(TAFELN, FORM)
        m._netz = object()
        klein, faktor = m._vorskaliert(
            np.zeros((m._band[3], m._band[2], 3), np.uint8))
        monkeypatch.setattr(m, "_netz_fragen",
                            lambda bild: [(0, 0, 10, 10, 0.9)])
        m.merke(np.zeros(FORM, np.uint8), 42)
        (x, y, w, h, _), = m.funde_fuer(42)
        assert (x, y) == (m._band[0], m._band[1])
        assert w == pytest.approx(10 / faktor, abs=2)


class TestDieSchwaerzungBrauchtDenRichtigenFrame:
    def test_ohne_index_bleibt_allein_die_wache(self):
        """Wer kein Frame nennt, bekommt keine Modellkaesten -- die des
        laufenden Frames traefen bei einem Sample-Frame daneben."""
        cfg = load_config()
        p = LaneProcessor(bahn(), cfg)
        p.prepare(FORM)

        class Meckert:
            bereit = True

            def maske_im_ausschnitt(self, kasten, index):
                raise AssertionError("darf ohne Frame nicht gefragt werden")

        p.setze_personenmodell(Meckert())
        p.fremdmaske(np.zeros(FORM, np.uint8))


class TestDasAnkergitter:
    """YOLOX meldet keine Bildkoordinaten, sondern je Ankerpunkt eine
    Verschiebung. Ein falsch aufgebautes Gitter gibt Kaesten, die plausibel
    aussehen und an der falschen Stelle liegen -- der Fehler, den man am
    schwersten sieht."""

    def test_zahl_der_anker_passt_zur_eingangskante(self):
        for kante, erwartet in ((416, 3549), (640, 8400)):
            gitter, schritte = PersonenModell._ankergitter(kante)
            assert len(gitter) == erwartet, kante
            assert len(schritte) == erwartet, kante

    def test_die_drei_stufen_kommen_in_der_richtigen_reihenfolge(self):
        gitter, schritte = PersonenModell._ankergitter(416)
        assert schritte[0] == 8
        assert schritte[-1] == 32
        # Die erste Stufe belegt (416/8)^2 Plaetze, dann wechselt der Schritt
        assert schritte[(416 // 8) ** 2 - 1] == 8
        assert schritte[(416 // 8) ** 2] == 16

    def test_jede_stufe_deckt_das_ganze_bild_ab(self):
        """Je Stufe muss der letzte Anker bei Kante minus Schrittweite liegen
        -- sonst bleibt ein Rand des Bandes unbeobachtet."""
        gitter, schritte = PersonenModell._ankergitter(416)
        ecken = gitter * schritte
        assert ecken.min() == 0
        for s in (8, 16, 32):
            stufe = ecken[(schritte == s).ravel()]
            assert stufe.max() == 416 - s, s

    def test_die_eingangskante_bestimmt_das_gitter(self):
        """Passt `input_size` nicht zur Modelldatei, stimmt nichts mehr --
        deshalb wird das Gitter aus derselben Zahl gerechnet."""
        m = modell(eingang=416)
        assert len(m._gitter) == 3549
        assert len(modell(eingang=640)._gitter) == 8400


class TestEinFalschesGitterMachtKeinenLaerm:
    """Der gefaehrlichste Fehler in diesem Modul: Steht `input_size` nicht auf
    der Eingangskante der Modelldatei, kommen Kaesten heraus, die plausibel
    aussehen und an der falschen Stelle liegen -- eine Schwaerzung NEBEN dem
    Gesicht. Kein Fehler, keine Ausnahme, nur ein stiller Datenschutzbruch."""

    def test_falsche_ankerzahl_schaltet_das_modell_ab(self, monkeypatch, caplog):
        m = modell(eingang=416)
        m.setze_tafeln(TAFELN, FORM)

        class Netz:
            def setInput(self, blob):
                pass

            def forward(self):
                return np.zeros((1, 8400, 85), np.float32)   # 640er Gitter

        m._netz = Netz()
        assert m.bereit is True
        with caplog.at_level("ERROR"):
            assert m._netz_fragen(np.zeros((300, 900, 3), np.uint8)) == []
        assert "input_size" in caplog.text
        assert m.bereit is False, "lieber gar nichts sagen als etwas Falsches"

    def test_passende_ankerzahl_laeuft_durch(self):
        m = modell(eingang=416)
        m.setze_tafeln(TAFELN, FORM)

        class Netz:
            def setInput(self, blob):
                pass

            def forward(self):
                return np.zeros((1, 3549, 85), np.float32)

        m._netz = Netz()
        assert m._netz_fragen(np.zeros((300, 900, 3), np.uint8)) == []
        assert m.bereit is True


class TestDieFesthaengendeWacheWirdGeloest:
    """BUG-026. Die Bewachung der Referenz verhindert, dass ein Mensch
    hineinwandert -- und macht die Wache damit unfaehig, sich von einer ECHTEN
    Aenderung zu erholen.

    GEMESSEN 2026-09-14 am Hallenmitschnitt: Bei Frame 215 verschiebt sich das
    Bild um wenige Pixel, die Abweichung auf Bahn 5 springt von 3,4 auf 13 %
    -- ueber `wache_nachlernen_unter` -- und bleibt danach 13 000 Frames bei
    25,2 % stehen. Median gleich Maximum: voellig unbewegt, wie es ein Mensch
    nie waere. Die Bahn war den ganzen Mitschnitt eingefroren, ohne dass
    irgendetwas davorstand. Das Modell sah dort auf 0,6 % der Messpunkte einen
    Menschen, die Wache meldete auf 98,3 %.
    """

    def prozessor(self, neustart: int = 20) -> LaneProcessor:
        cfg = load_config()
        cfg.detection.person_mask.wache_neustart_frames = neustart
        p = LaneProcessor(bahn(), cfg)
        p.prepare(FORM)
        p.wache._referenz = np.zeros((140, 140), np.float32)
        return p

    class Modell:
        bereit = True

        def __init__(self, person=False):
            self.person = person

    def treibe(self, p, n, person=False):
        p.setze_personenmodell(self.Modell())
        for i in range(n):
            p._wache_meldet_fremdes = True
            p._modell_meldet_person = person
            p._pruefe_festhaengende_wache(TestDieBahnFragtSparsam.Frame(i))

    def test_dauermeldung_ohne_mensch_verwirft_die_referenz(self):
        p = self.prozessor(neustart=20)
        assert p.wache._referenz is not None
        self.treibe(p, 20)
        assert p.wache._referenz is None
        # Auch die Meldung selbst faellt weg -- sonst ginge die Bahn im selben
        # Frame trotzdem noch einmal in die Bremse.
        assert p._wache_meldet_fremdes is False
        assert p._wache_daueralarm == 0

    def test_kurze_meldung_ruehrt_nichts_an(self):
        """Eine echte Verdeckung dauert im Median 30 Frames, die laengste
        gemessene 250. Die Schwelle steht auf 750 -- niemand wird
        weggeraeumt, weil er eine Weile davorsteht."""
        p = self.prozessor(neustart=20)
        self.treibe(p, 19)
        assert p.wache._referenz is not None

    def test_ein_gesehener_mensch_haelt_den_zaehler_bei_null(self):
        p = self.prozessor(neustart=20)
        self.treibe(p, 100, person=True)
        assert p.wache._referenz is not None
        assert p._wache_daueralarm == 0

    def test_eine_unterbrechung_setzt_zurueck(self):
        p = self.prozessor(neustart=20)
        self.treibe(p, 15)
        p.setze_personenmodell(self.Modell())
        p._wache_meldet_fremdes = False
        p._pruefe_festhaengende_wache(TestDieBahnFragtSparsam.Frame(99))
        assert p._wache_daueralarm == 0
        self.treibe(p, 15)
        assert p.wache._referenz is not None

    def test_ohne_modell_passiert_gar_nichts(self):
        """Lieber eine eingefrorene Bahn als ein Gesicht in der Datenbank:
        Ohne Zeugen wird die Referenz nie verworfen."""
        p = self.prozessor(neustart=20)
        for i in range(200):
            p._wache_meldet_fremdes = True
            p._pruefe_festhaengende_wache(TestDieBahnFragtSparsam.Frame(i))
        assert p.wache._referenz is not None

    def test_abschaltbar(self):
        p = self.prozessor(neustart=0)
        self.treibe(p, 500)
        assert p.wache._referenz is not None

    def test_die_wache_lernt_danach_wieder(self):
        """Nach dem Verwerfen muss die naechste Beobachtung eine neue Referenz
        aufbauen -- sonst haette man die Bahn nur anders kaputtgemacht."""
        p = self.prozessor(neustart=20)
        self.treibe(p, 20)
        assert p.wache.bereit is False
        p.wache.beobachte(np.full((140, 140, 3), 120, np.uint8))
        assert p.wache.bereit is True
        assert p.wache.abweichung(np.full((140, 140, 3), 120, np.uint8)) == 0.0
