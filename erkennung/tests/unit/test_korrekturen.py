"""Gemerkte Feinkorrekturen: was an einer Anlage von Hand nachgezogen wurde.

WOFUER -- Wunsch des Nutzers am 2026-09-11:

    "Am besten waere es, wenn sich der Code das merkt, und wenn das naechste
     Mal der Tafeltyp ausgewaehlt wird, dann schlaegt er automatisch vielleicht
     verschiedene Kalibrierungen vor oder so."

DIE ENTSCHEIDUNG, die diese Tests festhalten: Gemerkt werden **nur die
Versaetze** gegenueber der Bauart, je Tafelposition -- nicht die Tafelecken.
Die haengen an Kamera, Zoom und Blickwinkel und sind in der naechsten Halle
wertlos. Und angewandt wird nur auf Wunsch: Ob eine Korrektur aus einer anderen
Halle hier passt, weiss der Mensch davor.
"""

from __future__ import annotations

import pytest

from kegel_cv.calibration import korrekturen as ko
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi


def bahn(lane_id: int, x: float, versatz: float = 0.0) -> LaneCalibration:
    return LaneCalibration(
        lane_id=lane_id,
        quad=[[x, 20.0], [x + 100, 20.0], [x + 100, 120.0], [x, 120.0]],
        rois=[
            Roi(name="green_lamp", rect=(0.45 + versatz, 0.70, 0.06, 0.06)),
            Roi(name="pin_lamp_1", rect=(0.20, 0.30, 0.04, 0.04), pin_number=1),
            Roi(name="throw_number", rect=(0.15, 0.85 + versatz, 0.30, 0.10)),
        ])


def vorlage() -> list[Roi]:
    return bahn(1, 0.0).rois


class TestAusVergleich:
    def test_ohne_unterschied_nichts_zu_merken(self):
        kal = Calibration(lanes=[bahn(1, 10.0), bahn(2, 150.0)])
        k = ko.aus_vergleich(vorlage(), kal, "Probe")
        assert k.tafeln == {}

    def test_der_versatz_wird_gefunden(self):
        kal = Calibration(lanes=[bahn(1, 10.0), bahn(2, 150.0, versatz=0.02)])
        k = ko.aus_vergleich(vorlage(), kal, "Probe")
        assert set(k.tafeln) == {2}, "nur die veraenderte Tafel"
        assert k.tafeln[2]["green_lamp"][0] == pytest.approx(0.02)

    def test_die_tafeln_zaehlen_von_links(self):
        """Dieselbe Reihenfolge, in der die Bahnnummern abgefragt werden --
        sonst landet die Korrektur auf der falschen Tafel."""
        kal = Calibration(lanes=[bahn(2, 150.0, versatz=0.02), bahn(1, 10.0)])
        k = ko.aus_vergleich(vorlage(), kal, "Probe")
        assert set(k.tafeln) == {2}

    def test_rundungsrauschen_wird_uebergangen(self):
        kal = Calibration(lanes=[bahn(1, 10.0, versatz=1e-7)])
        k = ko.aus_vergleich(vorlage(), kal, "Probe")
        assert k.tafeln == {}


class TestAnwenden:
    def test_die_bereiche_wandern(self):
        kal = Calibration(lanes=[bahn(1, 10.0), bahn(2, 150.0, versatz=0.02)])
        k = ko.aus_vergleich(vorlage(), kal, "Probe")

        frisch = Calibration(lanes=[bahn(1, 10.0), bahn(2, 150.0)])
        # Zwei Bereiche: die Hilfsfunktion verschiebt die gruene Lampe in x
        # und die Wurfnummer in y.
        assert ko.wende_an(frisch, k) == 2
        assert frisch.lanes[1].get_roi("green_lamp").rect[0] == \
            pytest.approx(0.47)
        assert frisch.lanes[1].get_roi("throw_number").rect[1] == \
            pytest.approx(0.87)

    def test_die_unberuehrte_tafel_bleibt(self):
        kal = Calibration(lanes=[bahn(1, 10.0), bahn(2, 150.0, versatz=0.02)])
        k = ko.aus_vergleich(vorlage(), kal, "Probe")
        frisch = Calibration(lanes=[bahn(1, 10.0), bahn(2, 150.0)])
        ko.wende_an(frisch, k)
        assert frisch.lanes[0].get_roi("green_lamp").rect[0] == \
            pytest.approx(0.45)

    def test_weniger_tafeln_verschieben_nichts_um_eine_stelle(self):
        """Wurden weniger Tafeln gefunden als beim Merken, bleibt die fehlende
        Position leer -- sonst landete die Korrektur der dritten auf der
        zweiten."""
        k = ko.Korrektur(name="x", tafeln={
            1: {"green_lamp": (0.01, 0.0)}, 3: {"green_lamp": (0.05, 0.0)}})
        frisch = Calibration(lanes=[bahn(1, 10.0), bahn(2, 150.0)])
        assert ko.wende_an(frisch, k) == 1
        assert frisch.lanes[1].get_roi("green_lamp").rect[0] == \
            pytest.approx(0.45)

    def test_kein_bereich_verlaesst_die_tafel(self):
        k = ko.Korrektur(name="x", tafeln={1: {"green_lamp": (9.0, 9.0)}})
        frisch = Calibration(lanes=[bahn(1, 10.0)])
        ko.wende_an(frisch, k)
        x, y, w, h = frisch.lanes[0].get_roi("green_lamp").rect
        assert 0.0 <= x and x + w <= 1.0001 and 0.0 <= y and y + h <= 1.0001

    def test_unbekannte_bereiche_stoeren_nicht(self):
        k = ko.Korrektur(name="x", tafeln={1: {"gibt_es_nicht": (0.01, 0.0)}})
        frisch = Calibration(lanes=[bahn(1, 10.0)])
        assert ko.wende_an(frisch, k) == 0


class TestSpeichern:
    def test_hin_und_zurueck(self, tmp_path):
        k = ko.Korrektur(name="Halle Nord", erstellt="2026-09-11T10:00:00",
                         tafeln={1: {"green_lamp": (0.012345, -0.004)}})
        ko.speichere(tmp_path, "FUNK_klassisch", [k])
        zurueck = ko.lade(tmp_path, "FUNK_klassisch")
        assert len(zurueck) == 1
        assert zurueck[0].name == "Halle Nord"
        assert zurueck[0].tafeln[1]["green_lamp"][0] == pytest.approx(0.012345)

    def test_ohne_datei_leere_liste(self, tmp_path):
        assert ko.lade(tmp_path, "GibtEsNicht") == []

    def test_eine_kaputte_datei_haelt_nichts_auf(self, tmp_path, caplog):
        """P8: Eine unlesbare Datei darf die Kalibrierung nicht verhindern."""
        (tmp_path / f"X{ko.ENDUNG}").write_text("{kaputt", encoding="utf-8")
        assert ko.lade(tmp_path, "X") == []

    def test_die_beschreibung_nennt_das_wesentliche(self):
        k = ko.Korrektur(name="Halle Nord", erstellt="2026-09-11T10:00:00",
                         tafeln={1: {"a": (0.1, 0.1)}, 2: {"b": (0.1, 0.1)}})
        text = k.beschreibung()
        assert "Halle Nord" in text and "2 Tafeln" in text and "2026-09-11" in text


class TestKeineEckenImGepaeck:
    """Die Tafelecken duerfen NICHT gemerkt werden -- sie haengen an Kamera,
    Zoom und Blickwinkel und sind in der naechsten Halle wertlos."""

    def test_die_ecken_bleiben_unberuehrt(self):
        kal = Calibration(lanes=[bahn(1, 10.0, versatz=0.02)])
        k = ko.aus_vergleich(vorlage(), kal, "Probe")
        frisch = Calibration(lanes=[bahn(1, 999.0)])
        vorher = [list(p) for p in frisch.lanes[0].quad]
        ko.wende_an(frisch, k)
        assert [list(p) for p in frisch.lanes[0].quad] == vorher

    def test_gespeichert_wird_nur_der_versatz(self, tmp_path):
        import json
        kal = Calibration(lanes=[bahn(1, 10.0, versatz=0.02)])
        k = ko.aus_vergleich(vorlage(), kal, "Probe")
        pfad = ko.speichere(tmp_path, "T", [k])
        text = pfad.read_text(encoding="utf-8")
        assert "quad" not in text and "999" not in text
        assert json.loads(text)["korrekturen"][0]["tafeln"]["1"]


class TestKorrekturdateienSindKeineTafeltypen:
    """`<Typ>.korrekturen.json` landete als Tafeltyp in der Bibliothek, wurde
    wegen des fehlenden Musterbildes verworfen und hinterliess bei jedem Start
    eine Warnung, die nach einem Fehler aussieht (gefunden 2026-09-15 beim
    ersten Bibliothekslauf auf dem Telefon)."""

    def test_sie_werden_uebergangen(self, tmp_path, caplog):
        import cv2
        import numpy as np
        from kegel_cv.calibration.board_library import lade_bibliothek
        from kegel_cv.calibration.model import (Calibration, LaneCalibration,
                                                Roi)

        kal = Calibration(lanes=[LaneCalibration(
            lane_id=1, quad=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
            rois=[Roi(name="green_lamp", rect=(0.1, 0.1, 0.2, 0.2))])])
        kal.save(tmp_path / "Typ.json")
        cv2.imwrite(str(tmp_path / "Typ.png"),
                    np.full((20, 20, 3), 128, np.uint8))
        (tmp_path / "Typ.korrekturen.json").write_text("{}", encoding="utf-8")

        with caplog.at_level("WARNING"):
            typen = lade_bibliothek(tmp_path)
        assert [t.name for t in typen] == ["Typ"]
        assert "korrekturen" not in caplog.text
