"""Im Anlauf entscheidet die AENDERUNG, nicht die absolute Schwelle.

DAS PROBLEM (gemessen am 2. Spieltag, 2026-10-02). Der Detektor lernt seine
Schwellen im Betrieb -- aus dem gleitenden Histogramm, hilfsweise aus
Perzentilen. Beides braucht BEIDE Zustaende im Fenster. Zu Beginn einer
Aufzeichnung ist die Anlage aber freigegeben und die Lampe durchgehend an:

    erstes AUS   Bahn 2: Frame 7558   Bahn 3: 10400
                 Bahn 4: Frame 10480  Bahn 5:  5607

Auf Bahn 4 trug also achteinhalb Minuten lang allein die feste Schwelle
(45/35). Eine nach Trennschaerfe bessere Gruenlampen-ROI (Fisher 16,0 auf
25,7, Graubereich 9,3 auf 5,1 Prozent) hob das AUS-Niveau von 31,4 auf 50,3
-- ueber die feste AN-Schwelle. Damit galt die Lampe dauerhaft als an, und
die ersten drei Wuerfe des Spieltags gingen verloren (6, 8 und 9 Kegel,
Endstand des Spiels 127 statt 150).

DIE LOESUNG kam vom Nutzer (2026-10-06): *„wir hoffen ja nur, dass aus
irgendwo drunter liegt und an irgendwo drueber ... ich denke wir sollten
eher mal schauen, ob wir es dadurch schaffen, dass wir sagen am Anfang
brauchen wir eine Aenderung > 10 oder so."*

Eine Aenderung braucht die absolute Lage nicht und haengt damit an keiner
ROI. Sie braucht nur, dass die Wolken weit genug auseinanderliegen -- und
das ist die eine Groesse, die ueber alle vier Bahnen stabil ist (Spanne 35
bis 48, mit der neuen Bahn-4-ROI 39,6).

GEMESSEN an beiden Vollaeufen, Frame des ersten erkannten Gruen-AUS:

                       absolut   >5     >10     >15     >20
    alte ROIs Bahn 2     7558    161   3200    7557    7558
              Bahn 3    10400     40  10392   10392   10399
              Bahn 4    10480     79   1801   10479   14124
              Bahn 5     5607    977   5605    5605    5605
    neue ROI  Bahn 4     KEINS    91   2097   10470   10479
              Bahn 5     5607     87   5605    5605    5605

Bei 15 trifft die Regel ueberall dasselbe AUS wie die absolute Schwelle --
ohne Fehlausloeser davor -- und findet es auch dort, wo die absolute
Schwelle nichts findet.

SIE ERSETZT DIE SCHWELLEN NICHT, sie kommt hinzu. Sonst waere die Lampe
beim ersten Bild "unbekannt" statt "an", und das waere schlechter als der
Fehler, den sie behebt.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.config import load_config
from kegel_cv.detection.lamp_detectors import HsvGreenDetector
from kegel_cv.models.readings import LampState


def patch(score: float, kante: int = 10) -> np.ndarray:
    """Ein Bild mit genau `score` Prozent gruenen Pixeln."""
    bild = np.full((kante, kante, 3), 30, dtype=np.uint8)
    gruen = int(round(kante * kante * score / 100.0))
    flach = bild.reshape(-1, 3)
    flach[:gruen] = (40, 255, 40)
    return flach.reshape(kante, kante, 3)


@pytest.fixture
def detektor() -> HsvGreenDetector:
    cfg = load_config()
    # Die Lernverfahren stillegen -- geprueft wird allein der Anlauf.
    g = cfg.detection.green.model_copy(update={"histogram_thresholds": False,
                                               "adaptive_thresholds": False})
    return HsvGreenDetector(g)


class TestDerFallDerDreiWuerfe:
    def test_beide_wolken_ueber_der_festen_schwelle(self, detektor):
        """Bahn 4 mit der besseren ROI: AUS 50, AN 85, feste Schwelle 45/35.

        Die absolute Schwelle sieht hier NIE ein AUS -- beide Wolken liegen
        darueber. Genau das kostete die ersten drei Wuerfe des Spieltags.
        """
        for _ in range(50):
            assert detektor.detect(patch(85.0)).state is LampState.ON
        assert detektor.detect(patch(50.0)).state is LampState.OFF

    def test_ohne_die_regel_bliebe_sie_an(self):
        cfg = load_config()
        g = cfg.detection.green.model_copy(
            update={"histogram_thresholds": False, "adaptive_thresholds": False,
                    "warmup_min_change": 0.0})
        d = HsvGreenDetector(g)
        for _ in range(50):
            d.detect(patch(85.0))
        assert d.detect(patch(50.0)).state is LampState.ON


class TestSieErsetztDieSchwellenNicht:
    def test_das_erste_bild_urteilt_nach_der_schwelle(self, detektor):
        """Beim ersten Bild gibt es kein Niveau. Haette die Regel Vorrang,
        waere die Lampe minutenlang 'unbekannt' statt 'an'."""
        assert detektor.detect(patch(70.0)).state is LampState.ON

    def test_ein_eindeutiges_aus_bleibt_aus(self, detektor):
        assert detektor.detect(patch(10.0)).state is LampState.OFF

    def test_die_hysteresezone_bleibt_unbestimmt(self, detektor):
        detektor.detect(patch(40.0))
        assert detektor.detect(patch(40.0)).state is LampState.UNKNOWN


class TestWasSieNichtTunDarf:
    def test_rauschen_unter_der_schwelle_kippt_nichts(self, detektor):
        """BUG-013 in neuem Gewand: Die Lampe darf nicht durch Rauschen
        wechseln. Gemessen schwankt sie um wenige Punkte."""
        detektor.detect(patch(85.0))
        for wert in (84.0, 86.0, 83.0, 87.0, 85.0, 82.0, 88.0):
            assert detektor.detect(patch(wert)).state is LampState.ON

    def test_langsame_drift_wird_mitgenommen(self, detektor):
        """Zieht die Saalbeleuchtung ueber Minuten, soll das Niveau folgen
        und nicht irgendwann einen Wechsel melden, den es nicht gab."""
        detektor.detect(patch(85.0))
        for _ in range(40):
            for wert in (84.0, 83.0, 82.0, 81.0, 80.0):
                assert detektor.detect(patch(wert)).state is LampState.ON

    def test_eine_verdeckte_tafel_zaehlt_nicht(self):
        """Steht ein Spieler davor, faellt der Score auf nahe null. Das ist
        keine Messung der Lampe, sondern ihr Fehlen -- als Aenderung
        gewertet meldete es ein AUS, das es nie gab."""
        cfg = load_config()
        g = cfg.detection.green.model_copy(
            update={"histogram_thresholds": False, "adaptive_thresholds": False,
                    "occlusion_score": 5.0})
        d = HsvGreenDetector(g)
        for _ in range(20):
            d.detect(patch(85.0))
        d.detect(patch(0.0))
        # Das Niveau darf die Verdeckung nicht uebernommen haben.
        assert d._anlauf_niveau is not None and d._anlauf_niveau > 50.0


class TestSieHoertAufWennGelerntWird:
    def test_das_histogramm_uebernimmt(self):
        """Die Regel ist eine Ueberbrueckung. Sobald ein Tal gefunden ist,
        gilt wieder das Gelernte -- sonst waere sie eine Fessel."""
        cfg = load_config()
        d = HsvGreenDetector(cfg.detection.green)
        assert d._im_anlauf()
        for _ in range(cfg.detection.green.histogram_window):
            d.detect(patch(80.0))
            d.detect(patch(20.0))
        assert d._histogramm.gemessen
        assert not d._im_anlauf()

    def test_abschaltbar(self):
        cfg = load_config()
        g = cfg.detection.green.model_copy(update={"warmup_min_change": 0.0})
        assert not HsvGreenDetector(g)._im_anlauf()

    def test_die_vorgabe_ist_fuenfzehn(self):
        assert load_config().detection.green.warmup_min_change == 15.0


class TestVerdrahtung:
    def test_eine_verschobene_roi_vergisst_auch_das_niveau(self, detektor):
        """Behielte man es, saehe die neue ROI beim ersten Bild eine riesige
        'Aenderung' und meldete einen Wechsel, den es nie gab (BUG-024)."""
        detektor.detect(patch(85.0))
        assert detektor._anlauf_niveau is not None
        detektor.vergiss()
        assert detektor._anlauf_niveau is None
