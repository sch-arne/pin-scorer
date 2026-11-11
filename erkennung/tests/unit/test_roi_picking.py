"""Tests des gefuehrten ROI-Anklickens.

Der Nutzer klickt am Anfang jedes Videos die Tafelecken und anschliessend die
einzelnen Bereiche (Raute, gruene Lampe, Anzeigefelder). Diese Umrechnung
Frame-Pixel -> normierte Tafelkoordinaten ist die Stelle, an der ein Fehler
alle nachfolgenden Messungen unbrauchbar machen wuerde.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.calibration.session import (
    CalibrationSession,
    CalibrationStep,
    default_pick_order,
    default_roi_size,
    roi_label,
)

SQUARE = [(100.0, 100.0), (300.0, 100.0), (300.0, 300.0), (100.0, 300.0)]


@pytest.fixture
def session() -> CalibrationSession:
    """Sitzung mit einer bereits per Ecken kalibrierten Bahn 1."""
    s = CalibrationSession(warped_width=440, warped_height=530)
    s.start_lane(1)
    for point in SQUARE:
        s.add_point(*point)
    s.try_commit()
    return s


class TestAbfragereihenfolge:
    def test_erst_die_raute_dann_die_felder(self):
        order = default_pick_order()
        assert order[:9] == [f"pin_lamp_{i}" for i in range(1, 10)]
        assert order[9] == "green_lamp"
        # `left_display` ist seit 2026-08-28 dabei: Es zaehlt die Fehlwuerfe
        # und ist die einzige Quelle fuer Wuerfe ohne Kegel (Q10). Vorher war
        # es mit "Bedeutung nicht geklaert" ausgeschlossen.
        assert set(order[10:]) == {"pin_count", "throw_number", "total_a",
                                   "total_b", "left_display"}

    def test_von_hand_gesetzt_heisst_eingeschaltet(self):
        """Wer einen Bereich setzt, will ihn benutzt haben.

        BEOBACHTET: Der Fehlwurfzaehler wird aus der Vorlage abgeschaltet
        angelegt. Wurde er dann gesetzt, verschob die Oberflaeche nur das
        Rechteck und liess den Schalter aus -- kein Rahmen wurde gezeichnet
        (abgeschaltete Bereiche werden uebersprungen), und gelesen wurde das
        Feld auch nicht. Es sah aus, als liesse es sich nicht kalibrieren.
        """
        from kegel_cv.calibration.model import Roi

        s = CalibrationSession(warped_width=440, warped_height=530)
        s.start_lane(1)
        for punkt in SQUARE:
            s.add_point(*punkt)
        s.try_commit()

        lane = s.calibration.get_lane(1)
        lane.set_roi(Roi(name="left_display", rect=(0.1, 0.6, 0.26, 0.13),
                         enabled=False))

        s.start_roi_picking(["left_display"])
        s.place_roi(200.0, 200.0)

        gesetzt = s.calibration.get_lane(1).get_roi("left_display")
        assert gesetzt.enabled is True, (
            "ein von Hand gesetzter Bereich muss eingeschaltet sein -- sonst "
            "wird er weder gezeichnet noch gelesen")

    def test_naechste_bahn_uebernimmt_die_rois_der_ersten(self):
        """Vier baugleiche Tafeln haben dieselben normierten Koordinaten.

        Die ROIs stehen in TAFELkoordinaten -- bezogen auf das entzerrte
        Viereck, nicht auf das Bild. Wer eine Bahn sauber eingestellt hat,
        soll die Arbeit fuer die uebrigen drei geschenkt bekommen.

        Vorher bekam jede Bahn die allgemeine Vorlage aus einer anderen Halle
        und musste komplett neu gesetzt werden.
        """
        from kegel_cv.calibration.model import Roi

        s = CalibrationSession(warped_width=440, warped_height=530)
        s.start_lane(1)
        for punkt in SQUARE:
            s.add_point(*punkt)
        s.try_commit()
        s.calibration.get_lane(1).set_roi(
            Roi(name="digit_left_display_1", rect=(0.187, 0.712, 0.053, 0.088)))

        s.start_lane(2)
        for punkt in [(400.0, 100.0), (600.0, 100.0), (600.0, 300.0), (400.0, 300.0)]:
            s.add_point(*punkt)
        s.try_commit()

        uebernommen = s.calibration.get_lane(2).get_roi("digit_left_display_1")
        assert uebernommen is not None, "die Ziffernstelle muss mitkommen"
        assert uebernommen.rect == (0.187, 0.712, 0.053, 0.088)

    def test_uebernommene_rois_sind_unabhaengig(self):
        """Kopie, nicht Verweis -- sonst verschoebe eine Korrektur alle Bahnen."""
        from kegel_cv.calibration.model import Roi

        s = CalibrationSession(warped_width=440, warped_height=530)
        for lane_id, punkte in ((1, SQUARE),
                                (2, [(400.0, 100.0), (600.0, 100.0),
                                     (600.0, 300.0), (400.0, 300.0)])):
            s.start_lane(lane_id)
            for punkt in punkte:
                s.add_point(*punkt)
            s.try_commit()

        s.calibration.get_lane(2).set_roi(
            Roi(name="green_lamp", rect=(0.9, 0.9, 0.01, 0.01)))

        assert s.calibration.get_lane(1).get_roi("green_lamp").rect != (
            0.9, 0.9, 0.01, 0.01)

    def test_erste_bahn_bekommt_die_allgemeine_vorlage(self):
        s = CalibrationSession(warped_width=440, warped_height=530)
        s.start_lane(1)
        for punkt in SQUARE:
            s.add_point(*punkt)
        s.try_commit()

        assert s.calibration.get_lane(1).get_roi("green_lamp") is not None

    def test_einzelne_ziffernstelle_wird_ueber_zwei_ecken_gesetzt(self):
        """Eine Ziffer braucht ihre Box, keinen Klick in die Mitte.

        BEOBACHTET am Spieltag: Wer eine einzelne Stelle nachsetzen wollte,
        landete in `PICK_ROIS` und bekam eine Standardbox um den Klickpunkt --
        die Stelle "hing sonst wo". Aus der Box ergeben sich die
        Segmentflaechen rein geometrisch; eine Standardgroesse trifft keine.
        """
        s = CalibrationSession(warped_width=440, warped_height=530)
        s.start_lane(1)
        for punkt in SQUARE:
            s.add_point(*punkt)
        s.try_commit()

        assert s.select_roi("digit_left_display_2") is True
        assert s.step is CalibrationStep.FRAME_DIGITS
        assert s.digit_corner_label == "oben links"

        s.frame_digit(180.0, 190.0)
        assert s.digit_corner_label == "unten rechts"
        assert s.frame_digit(210.0, 230.0) is True

        roi = s.calibration.get_lane(1).get_roi("digit_left_display_2")
        assert roi is not None and roi.enabled is True

    def test_nicht_ziffern_bleiben_beim_einzelklick(self):
        s = CalibrationSession(warped_width=440, warped_height=530)
        s.start_lane(1)
        for punkt in SQUARE:
            s.add_point(*punkt)
        s.try_commit()

        s.select_roi("green_lamp")

        assert s.step is CalibrationStep.PICK_ROIS

    def test_jede_ziffernstelle_ist_einzeln_waehlbar(self):
        """Sitzt eine Stelle daneben, soll man nur sie neu setzen muessen."""
        from kegel_cv.calibration.session import single_roi_choices

        auswahl = single_roi_choices()
        assert "digit_left_display_1" in auswahl
        assert "digit_left_display_2" in auswahl
        assert "digit_pin_count_1" in auswahl
        assert "digit_total_b_4" in auswahl
        # und die Gesamtfelder bleiben ebenfalls waehlbar
        assert "left_display" in auswahl
        assert "green_lamp" in auswahl

    def test_reale_bahnnummer_kommt_aus_der_zuordnung(self):
        """Die Tafel ganz links im Overlay ist nicht zwangslaeufig Bahn 1.

        BEOBACHTET: Eine frisch angelegte Kalibrierung trug auf allen vier
        Bahnen `real_lane_number: null` und meldete sie damit als 1..4 --
        auch im Versand, wo der Spielleiter 2..5 erwartet. Die Zuordnung aus
        der Konfiguration wurde nur fuer die Platzhalter-Anzeige benutzt.
        """
        s = CalibrationSession(warped_width=440, warped_height=530,
                               lane_number_mapping=[2, 3, 4, 5])
        for lane_id in (1, 3):
            s.start_lane(lane_id)
            for punkt in SQUARE:
                s.add_point(*punkt)
            s.try_commit()

        assert s.calibration.get_lane(1).display_number == 2
        assert s.calibration.get_lane(3).display_number == 4

    def test_ohne_zuordnung_bleibt_die_position_die_nummer(self):
        s = CalibrationSession(warped_width=440, warped_height=530)
        s.start_lane(1)
        for punkt in SQUARE:
            s.add_point(*punkt)
        s.try_commit()

        assert s.calibration.get_lane(1).display_number == 1

    def test_fehlwurfzaehler_ist_in_der_vorlage_eingeschaltet(self):
        """Ohne ihn fehlen Wuerfe ohne Kegel ersatzlos (Q10)."""
        from kegel_cv.calibration.session import default_roi_layout

        vorlage = {r.name: r for r in default_roi_layout()}
        assert vorlage["left_display"].enabled is True

    def test_fehlwurfzaehler_ist_stellenweise_kalibrierbar(self):
        """Ohne diese zwei Rahmen fehlen Wuerfe ohne Kegel ersatzlos.

        Faellt bei einem Wurf kein Kegel, schaltet die Anlage die gruene Lampe
        gar nicht aus -- der Wurf ist fuer den Trigger unsichtbar (Q10). Der
        Fehlwurfzaehler im linken Display ist die einzige unabhaengige Quelle
        dafuer, und er wird nur gelesen, wenn seine Stellen eingerahmt sind.
        """
        from kegel_cv.calibration.session import digit_pick_order

        assert digit_pick_order() == [
            "digit_throw_number_1", "digit_throw_number_2", "digit_throw_number_3",
            "digit_pin_count_1",
            "digit_total_b_1", "digit_total_b_2", "digit_total_b_3", "digit_total_b_4",
            "digit_left_display_1", "digit_left_display_2",
        ]

    def test_fehlwurfzaehler_einzeln_nachtragbar(self):
        from kegel_cv.calibration.session import digit_pick_order

        assert digit_pick_order(["left_display"]) == [
            "digit_left_display_1", "digit_left_display_2"]

    def test_beschriftungen_sind_deutsch_und_verstaendlich(self):
        assert roi_label("pin_lamp_3") == "Kegellampe 3"
        assert roi_label("green_lamp") == "gruene Lampe"
        assert "Wurfnummer" in roi_label("throw_number")

    def test_unbekannter_name_faellt_auf_sich_selbst_zurueck(self):
        assert roi_label("etwas_neues") == "etwas_neues"


class TestZiehen:
    """Gesetzte Ecken und Bereiche lassen sich nachtraeglich verschieben.

    Ohne das muss ein danebengesetzter Eckpunkt ueber "Zurueck" abgeraeumt und
    die ganze Reihe neu geklickt werden -- bei vier Bahnen zu je vier Ecken und
    17 Bereichen ist das der Unterschied zwischen Nachjustieren und Neuanfangen.
    """

    def test_ecke_verschieben(self, session):
        assert session.move_quad_corner(1, 1, 320.0, 90.0) is True
        assert session.calibration.get_lane(1).quad[1] == [320.0, 90.0]

    def test_rois_wandern_mit_dem_viereck(self, session):
        """Der eigentliche Gewinn der normierten Tafelkoordinaten: Wird die
        Tafel neu umrandet, bleiben alle Bereiche relativ zu ihr stehen."""
        vorher = session.calibration.get_lane(1).get_roi("green_lamp").rect

        session.move_quad_corner(1, 1, 320.0, 90.0)

        assert session.calibration.get_lane(1).get_roi("green_lamp").rect == vorher

    def test_entartetes_viereck_faellt_beim_loslassen_auf(self, session):
        """Waehrend des Ziehens sind Zwischenlagen zwangslaeufig ungueltig --
        geprueft wird deshalb erst am Ende, dafuer aber verstaendlich."""
        session.move_quad_corner(1, 1, 100.0, 100.0)      # auf Ecke 0 gelegt

        ok, meldung = session.validate_quad(1)

        assert ok is False
        assert "doppelte" in meldung.lower() or "entartet" in meldung.lower()

    def test_bereich_verschieben_behaelt_die_groesse(self, session):
        vorher = session.calibration.get_lane(1).get_roi("green_lamp").rect[2:]

        assert session.move_roi(1, "green_lamp", 150.0, 250.0) is True

        nachher = session.calibration.get_lane(1).get_roi("green_lamp")
        assert nachher.rect[2:] == vorher

    def test_verschobener_bereich_ist_eingeschaltet(self, session):
        """Wer einen Bereich anfasst, will ihn benutzt haben."""
        from kegel_cv.calibration.model import Roi

        lane = session.calibration.get_lane(1)
        lane.set_roi(Roi(name="left_display", rect=(0.1, 0.6, 0.26, 0.13),
                         enabled=False))

        session.move_roi(1, "left_display", 200.0, 200.0)

        assert lane.get_roi("left_display").enabled is True

    def test_ziehen_ausserhalb_der_tafel_wird_abgelehnt(self, session):
        vorher = session.calibration.get_lane(1).get_roi("green_lamp").rect

        assert session.move_roi(1, "green_lamp", 900.0, 900.0) is False
        assert session.calibration.get_lane(1).get_roi("green_lamp").rect == vorher


class TestRoiPicking:
    def test_ohne_kalibrierte_bahn_nicht_moeglich(self):
        """Ohne Viereck gibt es keine Tafelkoordinaten -- ein Klick waere sinnlos."""
        s = CalibrationSession()
        s.start_lane(1)
        assert s.start_roi_picking() is False

    def test_gefuehrter_durchlauf(self, session):
        assert session.start_roi_picking() is True
        assert session.step is CalibrationStep.PICK_ROIS
        assert session.current_roi_label == "Kegellampe 1"

        order = default_pick_order()
        for i, _ in enumerate(order):
            done = session.place_roi(200.0, 200.0)
            assert done == (i == len(order) - 1)

        assert session.step is CalibrationStep.EDIT_ROIS
        assert session.current_roi_label is None
        assert session.calibration.get_lane(1).missing_rois() == []

    def test_fortschritt_wird_gezaehlt(self, session):
        session.start_roi_picking()
        assert session.roi_progress == (0, 15)
        session.place_roi(200.0, 200.0)
        assert session.roi_progress == (1, 15)

    def test_klick_landet_an_der_richtigen_stelle(self, session):
        """Ein Klick in die Mitte des Quadrats ergibt die ROI-Mitte (0.5, 0.5)."""
        session.start_roi_picking(["green_lamp"])
        session.place_roi(200.0, 200.0)

        roi = session.calibration.get_lane(1).get_roi("green_lamp")
        assert roi.center == pytest.approx((0.5, 0.5), abs=1e-3)

    def test_klick_ausserhalb_der_tafel_wird_abgelehnt(self, session):
        """Bewusst nicht klemmen: Eine an den Rand geschobene ROI saehe gesetzt
        aus, waere aber falsch -- der Fehler fiele erst bei der Erkennung auf."""
        session.start_roi_picking(["green_lamp"])
        before = session.calibration.get_lane(1).get_roi("green_lamp").rect

        assert session.place_roi(900.0, 900.0) is False
        assert session.current_roi_label == "gruene Lampe"   # bleibt stehen
        assert session.calibration.get_lane(1).get_roi("green_lamp").rect == before

    def test_groesse_bleibt_beim_verschieben_erhalten(self, session):
        session.start_roi_picking(["pin_count"])
        before = session.calibration.get_lane(1).get_roi("pin_count").rect[2:]
        session.place_roi(150.0, 250.0)
        after = session.calibration.get_lane(1).get_roi("pin_count").rect[2:]
        assert after == before

    def test_ueberspringen_laesst_roi_unveraendert(self, session):
        session.start_roi_picking()
        before = session.calibration.get_lane(1).get_roi("pin_lamp_1").rect

        session.skip_roi()

        assert session.current_roi_label == "Kegellampe 2"
        assert session.calibration.get_lane(1).get_roi("pin_lamp_1").rect == before

    def test_nur_raute_setzen(self, session):
        """Teilmenge: Nur die neun Lampen neu setzen, Felder unangetastet."""
        lamps = [f"pin_lamp_{i}" for i in range(1, 10)]
        session.start_roi_picking(lamps)
        assert session.roi_progress == (0, 9)

        for i in range(9):
            done = session.place_roi(200.0, 200.0)
            assert done == (i == 8)

        assert session.step is CalibrationStep.EDIT_ROIS

    def test_einzelne_roi_gezielt_neu_setzen(self, session):
        assert session.select_roi("total_b") is True
        assert session.current_roi_label == "Summenfeld B (untere Zeile)"

        session.place_roi(150.0, 150.0)
        assert session.step is CalibrationStep.EDIT_ROIS

    def test_klick_ohne_aktiven_modus_wird_ignoriert(self, session):
        assert session.step is CalibrationStep.EDIT_ROIS
        assert session.place_roi(200.0, 200.0) is False

    def test_abbrechen_leert_die_warteschlange(self, session):
        session.start_roi_picking()
        session.cancel()
        assert session.roi_queue == []
        assert session.active_roi is None
        assert session.step is CalibrationStep.IDLE

    def test_pin_number_wird_bei_neuen_lampen_gesetzt(self):
        """Auch eine von Hand gesetzte Lampe bekommt ihre KEGELNUMMER.

        Der ROI-Name zaehlt die Lampen so, wie sie auf der Tafel von oben nach
        unten liegen; die Kegelnummer zaehlt von vorn. Beides faellt NICHT
        zusammen -- `pin_lamp_7` ist die vordere linke Lampe und damit Kegel 2
        (siehe `calibration.pin_number_mapping`, geklaert am 2026-09-01).

        Frueher stand hier `== 7`. Das war die unbelegte Annahme aus Q5,
        Lampenindex und Kegelnummer seien dasselbe.
        """
        from kegel_cv.config import load_config
        zuordnung = load_config().calibration.pin_number_mapping

        s = CalibrationSession()
        s.start_lane(1)
        for point in SQUARE:
            s.add_point(*point)
        s.commit_quad(default_rois=False)          # bewusst ohne Vorbelegung

        s.start_roi_picking(["pin_lamp_7"])
        s.place_roi(200.0, 200.0)

        roi = s.calibration.get_lane(1).get_roi("pin_lamp_7")
        assert roi is not None
        assert roi.pin_number == zuordnung[6]
        assert roi.pin_number == 2, "pin_lamp_7 liegt vorn links -- Kegel 2"

    def test_jede_kegelnummer_genau_einmal(self):
        """Eine Zuordnung, die eine Nummer doppelt vergibt, wuerde zwei Kegel
        stillschweigend verschmelzen -- die Zaehlung bliebe richtig, das
        Wurfbild waere falsch, und niemand saehe es."""
        from kegel_cv.config import load_config
        zuordnung = load_config().calibration.pin_number_mapping

        assert sorted(zuordnung) == list(range(1, 10))

    def test_standardlayout_traegt_die_kegelnummern(self):
        from kegel_cv.calibration.session import default_roi_layout

        lampen = {r.name: r.pin_number for r in default_roi_layout()
                  if r.name.startswith("pin_lamp_")}
        assert lampen["pin_lamp_1"] == 9, "oben auf der Tafel ist hinten"
        assert lampen["pin_lamp_9"] == 1, "unten auf der Tafel ist vorn"
        assert lampen["pin_lamp_5"] == 5, "die Mitte bleibt die Mitte"
        assert sorted(lampen.values()) == list(range(1, 10))

    def test_neue_roi_bleibt_innerhalb_der_tafel(self):
        """Ein Klick dicht am Rand darf keine ROI erzeugen, die hinausragt."""
        s = CalibrationSession()
        s.start_lane(1)
        for point in SQUARE:
            s.add_point(*point)
        s.commit_quad(default_rois=False)

        s.start_roi_picking(["total_b"])
        s.place_roi(101.0, 101.0)      # ganz oben links in der Tafel

        x, y, w, h = s.calibration.get_lane(1).get_roi("total_b").rect
        assert x >= 0 and y >= 0
        assert x + w <= 1.0 and y + h <= 1.0


class TestRoiGroessen:
    def test_lampen_fassen_nur_die_leuchtflaeche(self):
        """Eng, nicht weit -- der Rahmen darf kein Gehaeuse mitfangen.

        GEMESSEN am 2026-09-02 (`tools/measure_roi_shrink.py`): Der frueher
        weite Rahmen (0,080 x 0,075) fing Gehaeuse mit, das bei heller
        Ausleuchtung den AUS-Wert hebt. Halbiert steigt die Trennung zwischen
        AN und AUS auf Bahn 4 von 33,7 auf 44,8 Punkte, die unentschiedenen
        Messungen fallen von 6,73 % auf 0,50 %.

        Die Obergrenze haelt diesen Befund fest: Waechst der Rahmen wieder
        ueber 0,05, ist der Gewinn dahin. Die Untergrenze schuetzt vor dem
        anderen Fehler -- unter 0,02 blieben bei 12 x 11 Pixeln Rohgroesse zu
        wenige Bildpunkte fuer eine stabile Messung.
        """
        w, h = default_roi_size("pin_lamp_1")
        assert 0.02 < w < 0.05 and 0.02 < h < 0.05

    def test_summenfelder_sind_breit(self):
        """Vierstellige Displays brauchen deutlich mehr Breite als eine Lampe."""
        assert default_roi_size("total_b")[0] > default_roi_size("pin_count")[0] * 2

    def test_unbekannte_roi_bekommt_brauchbaren_standard(self):
        w, h = default_roi_size("unbekannt")
        assert 0 < w <= 1 and 0 < h <= 1
