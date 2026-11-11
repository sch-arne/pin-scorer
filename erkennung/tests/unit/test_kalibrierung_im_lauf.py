"""Nachgezogene Bereiche wirken auch WAEHREND die Analyse laeuft.

DER BEFUND (Nutzer, 2026-09-11):

    "wenn man die ROIs im Livestream verschiebt, aendert sich ja gar nichts...
     ich habe Rahmen von Gruen weggezogen und von der Pin_Count und es lief
     einfach weiter, als haette ich nichts geaendert"

Und so war es: `LaneProcessor.prepare` rechnet die normierten Bereiche EINMAL
in Pixelrechtecke um; danach liest die Analyse nur noch diese Rechtecke. Wer
die normierten Koordinaten verschiebt, verschiebt nichts, was noch gelesen
wird -- und nichts sagte es.

An einem Spieltag ist das teuer: Man sieht im Bild, dass die Gruenlampe
danebensitzt, zieht sie zurecht, und es aendert sich nichts. Genau das ist am
2026-09-11 passiert, waehrend auf zwei Bahnen Wuerfe verloren gingen.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.pipeline import AnalysisPipeline
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi
from kegel_cv.config import load_config


def bahn(lane_id: int = 1, x: float = 100.0) -> LaneCalibration:
    return LaneCalibration(
        lane_id=lane_id,
        quad=[[x, 50.0], [x + 200, 50.0], [x + 200, 250.0], [x, 250.0]],
        rois=[Roi(name="green_lamp", rect=(0.45, 0.75, 0.06, 0.05))]
        + [Roi(name=f"pin_lamp_{i}", rect=(0.10 + 0.08 * i, 0.30, 0.04, 0.04),
               pin_number=i) for i in range(1, 10)]
        + [Roi(name="throw_number", rect=(0.15, 0.85, 0.25, 0.10))])


@pytest.fixture
def pipeline():
    cfg = load_config()
    kal = Calibration(lanes=[bahn(1, 100.0), bahn(2, 400.0)])
    p = AnalysisPipeline(kal, cfg, video_id="test")
    p.prepare((720, 1280, 3))
    return p


def verschobene_kalibrierung(um: float = 0.02) -> Calibration:
    kal = Calibration(lanes=[bahn(1, 100.0), bahn(2, 400.0)])
    roi = kal.lanes[0].get_roi("green_lamp")
    x, y, w, h = roi.rect
    kal.lanes[0].set_roi(roi.model_copy(update={"rect": (x, y + um, w, h)}))
    return kal


class TestDasRechteckWandertMit:
    def test_vorher_steht_es_fest(self, pipeline):
        """Der Ausgangszustand -- ohne ihn sagt der Vergleich nichts."""
        assert pipeline.processors[0]._green_box is not None

    def test_die_gruenlampe_bekommt_ein_neues_rechteck(self, pipeline):
        vorher = pipeline.processors[0]._green_box
        pipeline.uebernimm_kalibrierung(verschobene_kalibrierung(),
                                        (720, 1280, 3))
        assert pipeline.processors[0]._green_box != vorher, \
            "genau hier lief es vorher ins Leere"

    def test_die_unberuehrte_bahn_bleibt_stehen(self, pipeline):
        """Die Bahnen sind unabhaengig (P6) -- eine Aenderung an Bahn 1 darf
        Bahn 2 nicht anfassen."""
        vorher = pipeline.processors[1]._green_box
        pipeline.uebernimm_kalibrierung(verschobene_kalibrierung(),
                                        (720, 1280, 3))
        assert pipeline.processors[1]._green_box == vorher

    def test_gemeldet_wird_nur_die_geaenderte_bahn(self, pipeline):
        betroffen = pipeline.uebernimm_kalibrierung(
            verschobene_kalibrierung(), (720, 1280, 3))
        assert betroffen == [1]

    def test_die_schutzzonen_wandern_mit(self, pipeline):
        """Die Personenmaske darf nach dem Verschieben nicht in die Tafel
        hineinschwaerzen."""
        vorher = pipeline.person_maske._tafeln[1]
        kal = verschobene_kalibrierung()
        kal.lanes[0].quad = [[120.0, 60.0], [320.0, 60.0],
                             [320.0, 260.0], [120.0, 260.0]]
        pipeline.uebernimm_kalibrierung(kal, (720, 1280, 3))
        # Die Zone traegt einen Sicherheitsrand -- verglichen wird deshalb die
        # VERSCHIEBUNG, nicht die absolute Lage.
        assert pipeline.person_maske._tafeln[1][0] - vorher[0] == \
            pytest.approx(20, abs=2)


class TestDasGedaechtnisWirdGeleert:
    """Die mitlaufenden Schwellen haengen an der MESSSTELLE. Wandert sie,
    beschreiben die gesammelten Werte eine Lage, die es nicht mehr gibt."""

    def test_die_gruenschwellen_beginnen_von_vorn(self, pipeline):
        detektor = pipeline.processors[0].green_detector
        for wert in (70.0, 72.0, 30.0, 28.0) * 500:
            detektor._history.append(wert)
            if detektor._histogramm is not None:
                detektor._histogramm.hinzufuegen(wert)
        pipeline.uebernimm_kalibrierung(verschobene_kalibrierung(),
                                        (720, 1280, 3))
        assert not detektor._history
        if detektor._histogramm is not None:
            assert not detektor._histogramm.gemessen

    def test_ohne_aenderung_bleibt_das_gedaechtnis(self, pipeline):
        """Ein Neuzeichnen der Oberflaeche darf die Schwellen nicht wegwerfen
        -- sonst kostet jeder Klick eine Minute Blindflug."""
        detektor = pipeline.processors[0].green_detector
        detektor._history.extend([70.0] * 50)
        gleich = Calibration(lanes=[bahn(1, 100.0), bahn(2, 400.0)])
        betroffen = pipeline.uebernimm_kalibrierung(gleich, (720, 1280, 3))
        assert betroffen == []
        assert len(detektor._history) == 50

    def test_die_lampenschwellen_beginnen_von_vorn(self, pipeline):
        detektor = pipeline.processors[0].lamp_detector
        detektor._history["1"] = __import__("collections").deque([150.0] * 20)
        kal = Calibration(lanes=[bahn(1, 100.0), bahn(2, 400.0)])
        roi = kal.lanes[0].get_roi("pin_lamp_3")
        x, y, w, h = roi.rect
        kal.lanes[0].set_roi(roi.model_copy(update={"rect": (x + 0.01, y, w, h)}))
        pipeline.uebernimm_kalibrierung(kal, (720, 1280, 3))
        assert not detektor._history


class TestDerZustandBleibt:
    """Wurfzaehler und Zustandsmaschine haengen NICHT an der ROI-Lage. Sie neu
    zu setzen hiesse, Wuerfe doppelt oder gar nicht zu buchen."""

    def test_die_zustandsmaschine_ueberlebt(self, pipeline):
        zustand = pipeline.processors[0].state_machine.state
        pipeline.uebernimm_kalibrierung(verschobene_kalibrierung(),
                                        (720, 1280, 3))
        assert pipeline.processors[0].state_machine.state == zustand

    def test_der_auswerter_bleibt_derselbe(self, pipeline):
        vorher = pipeline.analyzers[1]
        pipeline.uebernimm_kalibrierung(verschobene_kalibrierung(),
                                        (720, 1280, 3))
        assert pipeline.analyzers[1] is vorher

    def test_eine_fehlende_bahn_wird_nicht_verloren(self, pipeline):
        """Eine laufende Analyse darf an einer Nachjustierung nicht
        stillschweigend Bahnen verlieren (P8)."""
        nur_eine = Calibration(lanes=[bahn(1, 100.0)])
        pipeline.uebernimm_kalibrierung(nur_eine, (720, 1280, 3))
        assert len(pipeline.processors) == 2


class TestDerWegDurchDenWorker:
    def test_der_worker_nimmt_eine_kopie(self):
        """Sonst laese er mitten im Ziehen einen halb geaenderten Zustand."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from kegel_cv.gui.analysis_worker import AnalysisWorker

        kal = Calibration(lanes=[bahn(1, 100.0)])
        worker = AnalysisWorker("x.mp4", kal, load_config())
        worker.uebernimm_kalibrierung(kal)
        abgeholt = worker._abgeholte_kalibrierung()
        assert abgeholt is not None and abgeholt is not kal
        assert abgeholt.lanes[0].get_roi("green_lamp").rect == \
            kal.lanes[0].get_roi("green_lamp").rect

    def test_zweimal_abholen_liefert_nichts_doppelt(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from kegel_cv.gui.analysis_worker import AnalysisWorker

        kal = Calibration(lanes=[bahn(1, 100.0)])
        worker = AnalysisWorker("x.mp4", kal, load_config())
        worker.uebernimm_kalibrierung(kal)
        assert worker._abgeholte_kalibrierung() is not None
        assert worker._abgeholte_kalibrierung() is None
