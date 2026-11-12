"""Die Tafelwache schwärzt Bilder — sie hält nicht die Auswertung an.

BUG-030. Im Kopf von `analysis/tafel_wache.py` steht seit jeher:

    WAS DAMIT NICHT GEMEINT IST
    Diese Wache entscheidet nichts ueber Wuerfe. Sie schwaerzt Bilder, die das
    Haus verlassen.

In der Verdeckungsbremse stand sie trotzdem, mit derselben Schwelle wie fürs
Schwärzen. Eine festhängende Referenz hielt damit eine Bahn 1089 Frames an,
während Grün-Score (75,0) und Personenmodell beide sagten, dass nichts verdeckt
ist. Ein Wurf ging dabei verloren — Bahn 2, Spiel 6, sieben Kegel.

GEMESSEN am Stream vom 2026-09-17, Referenz im Normalbetrieb gelernt:

    Normalbetrieb                       0,000
    festhaengende Referenz (BUG-030)    0,123 bis 0,198
    halb verdeckt                       0,246
    alles schwarz                       0,551
    dunkle Tafel am Streamende          0,622
"""

from __future__ import annotations

import pytest

from kegel_cv.config import load_config


@pytest.fixture
def cfg():
    return load_config()


class TestZweiSchwellenFuerZweiFragen:
    def test_das_schwaerzen_bleibt_empfindlich(self, cfg):
        """Ein Bild zu viel zu schwärzen kostet nichts, ein Gesicht zu
        veröffentlichen schon."""
        assert cfg.detection.person_mask.wache_schwelle <= 0.10

    def test_das_bremsen_verlangt_sehr_viel_mehr(self, cfg):
        bremse = cfg.detection.person_mask.wache_bremse_schwelle
        schwaerzen = cfg.detection.person_mask.wache_schwelle
        assert bremse > schwaerzen * 3, (
            "Mit einer Schwelle fuer beides hielt eine festhaengende Referenz "
            "eine Bahn 1089 Frames an"
        )

    def test_eine_festhaengende_referenz_bremst_nicht(self, cfg):
        """GEMESSEN: 0,123 bis 0,198 — darunter darf nicht gebremst werden."""
        assert cfg.detection.person_mask.wache_bremse_schwelle > 0.20

    def test_eine_dunkle_tafel_bremst_weiterhin(self, cfg):
        """GEMESSEN: 0,551 (schwarz) und 0,622 (dunkles Streamende).

        Das ist der Fall, für den die Wache überhaupt in die Bremse kam: Dort
        sind Grün-Score und Personenmaske beide blind, und ohne sie wurden drei
        Würfe gebucht.
        """
        assert cfg.detection.person_mask.wache_bremse_schwelle < 0.55


class TestDieBremseFragtDenRichtigenZeugen:
    @staticmethod
    def _ohne_kommentare(quelle: str) -> str:
        """Nur der Code. Die Kommentare nennen beide Namen -- zu Recht."""
        return chr(10).join(z.split("#")[0] for z in quelle.splitlines())

    def test_die_bremse_nutzt_das_bremsflag(self):
        """Nicht `_wache_meldet_fremdes` — das gilt dem Schwärzen."""
        import inspect
        import re

        from kegel_cv.analysis import lane_processor
        code = self._ohne_kommentare(
            inspect.getsource(lane_processor.LaneProcessor.process))
        # Die Bedingung der Verdeckungsbremse herausgreifen
        treffer = re.search(r"if \(green\.score <[^:]+:", code, re.S)
        assert treffer, "Verdeckungsbremse nicht gefunden"
        bedingung = treffer.group(0)
        assert "_wache_bremst" in bedingung
        assert "_wache_meldet_fremdes" not in bedingung, (
            "Die Schwaerzungs-Schwelle darf die Auswertung nicht anhalten"
        )

    def test_die_erholung_haengt_weiter_am_schwaerzungsflag(self):
        """Eine festhängende Referenz soll weiter geheilt werden — sie
        schwärzt sonst dauerhaft zu viel, auch wenn sie nicht mehr bremst."""
        import inspect

        from kegel_cv.analysis import lane_processor
        quelle = inspect.getsource(
            lane_processor.LaneProcessor._pruefe_festhaengende_wache)
        assert "_wache_meldet_fremdes" in quelle
