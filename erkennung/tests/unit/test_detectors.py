"""Tests der Detektoren und der Kalibrierungspruefung.

Synthetische Bilder statt echter Frames: Der Sollwert ist per Konstruktion
bekannt. Ein Test gegen echtes Material pruefte immer zwei Dinge gleichzeitig
(Erkennung UND Annahme ueber das Material) -- beim Fehlschlag waere unklar,
welches der beiden falsch war.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.calibration_check import CheckVerdict
from kegel_cv.config.schema import GreenDetectionConfig, LampDetectionConfig
from kegel_cv.detection.lamp_detectors import HsvGreenDetector, WarmthLampDetector
from kegel_cv.models.readings import (
    LampReading,
    LampState,
    confidence_from_threshold,
)


def patch(color: tuple[int, int, int], size: int = 12) -> np.ndarray:
    """Einfarbiger BGR-Ausschnitt."""
    return np.full((size, size, 3), color, dtype=np.uint8)


# Gemessene Referenzfarben aus dem echten Material
GREEN_LIT = (60, 220, 60)        # leuchtende gruene Lampe
BEIGE_HOUSING = (150, 175, 195)  # Tafelgehaeuse -- hat selbst Gruenanteil
# Kegellampen: GEMESSEN Helligkeit AUS 154 +- 23, AN 254 +- 3
LAMP_LIT = (170, 235, 255)       # leuchtend: gesaettigt hell, warm
LAMP_DARK = (140, 148, 155)      # matt: deutlich dunkler


class TestHsvGreenDetector:
    @pytest.fixture
    def detector(self):
        return HsvGreenDetector(GreenDetectionConfig())

    def test_leuchtende_lampe_wird_als_an_erkannt(self, detector):
        reading = detector.detect(patch(GREEN_LIT))
        assert reading.state is LampState.ON
        assert reading.score > 45.0
        assert reading.confidence > 0.5

    def test_gehaeuse_wird_als_aus_erkannt(self, detector):
        reading = detector.detect(patch(BEIGE_HOUSING))
        assert reading.state is LampState.OFF

    def test_leerer_roi_ist_unknown_nicht_aus(self, detector):
        """Entscheidend: Ein leerer ROI heisst NICHT 'Lampe aus'. Waere es so,
        wuerde eine fehlerhafte Kalibrierung einen Wurf-Trigger ausloesen.
        Siehe BUG-001."""
        reading = detector.detect(np.empty((0, 0, 3), dtype=np.uint8))
        assert reading.state is LampState.UNKNOWN
        assert reading.confidence == 0.0

    def test_wert_in_der_hysteresezone_ist_unknown(self, detector):
        """Zwischen den Schwellen entscheidet die Zustandsmaschine, nicht der
        Detektor -- sonst waere die Hysterese wirkungslos."""
        cfg = GreenDetectionConfig(on_threshold=80.0, off_threshold=20.0)
        detector = HsvGreenDetector(cfg)
        # Halb gruen, halb Gehaeuse -> Score um 50
        mixed = np.concatenate([patch(GREEN_LIT), patch(BEIGE_HOUSING)], axis=0)
        assert detector.detect(mixed).state is LampState.UNKNOWN

    def test_score_ist_ein_prozentanteil(self, detector):
        assert detector.score(patch(GREEN_LIT)) == pytest.approx(100.0, abs=1.0)
        assert 0.0 <= detector.score(patch(BEIGE_HOUSING)) <= 100.0


class TestWarmthLampDetector:
    @pytest.fixture
    def detector(self):
        return WarmthLampDetector(LampDetectionConfig())

    def test_leuchtende_lampe(self, detector):
        reading = detector.detect_one(patch(LAMP_LIT), "pin_lamp_1")
        assert reading.state is LampState.ON

    def test_bug_006_helligkeit_entscheidet_nicht_die_waerme(self, detector):
        """BUG-006: Eine klar leuchtende Lampe (Helligkeit 255) darf nicht an
        einer knapp verfehlten Waerme-Schwelle scheitern.

        Realfall: Helligkeit 255, Waerme 31 -- frueher UNKNOWN, weil beide
        Kriterien mit UND verknuepft waren und die Waerme-Schwelle bei 40 lag."""
        # R-B = 255-224 = 31, also genau der gemessene Problemfall
        reading = detector.detect_one(patch((224, 240, 255)), "pin_lamp_1")
        assert reading.state is LampState.ON, (
            "Helligkeit muss entscheiden -- die Waerme ist nur Plausibilitaet"
        )

    def test_ohne_schranke_zaehlt_allein_die_helligkeit(self, detector):
        """VORGABE seit 2026-09-16: `warmth_min` ist None, also aus.

        Vorher stand dort 0,0 mit dem Kommentar "abgeschaltet" -- das war es
        nicht. Die Waerme (`rot - blau`) wird bei einer weiss gesaettigten
        Lampe negativ, und das Vorzeichen eines Rauschwerts entschied ueber
        ON oder UNKNOWN. GEMESSEN auf Bahn 2, F6600-6960: Helligkeit konstant
        255,0, Zustand sechsmal gewechselt, ohne dass jemand warf.
        """
        assert detector.cfg.warmth_min is None
        reading = detector.detect_one(patch((250, 250, 252)), "pin_lamp_1")
        assert reading.state is LampState.ON

    def test_mit_schranke_gilt_ein_farbloser_reflex_nicht_als_lampe(self):
        """Eingeschaltet wirkt sie weiter -- fuer Anlagen mit FARBIGEN Lampen.

        Der Nutzer zur Vorgabe: *"wenn ich jetzt weiter denke, eben an andere
        Bahnen, die vielleicht mit Gruen oder Roten Lampen die Kegel anzeigen,
        waere dann NUR Helligkeit nicht cleverer?"* -- ja. `rot - blau` ist
        auf ROTE Lampen zugeschnitten; gruene fielen durch. Wer die Schranke
        trotzdem braucht, schaltet sie im Anlagenprofil ein.
        """
        from kegel_cv.config import load_config
        cfg = load_config().detection.lamps.model_copy(
            update={"warmth_min": 12.0})
        eigener = WarmthLampDetector(cfg)
        reading = eigener.detect_one(patch((250, 250, 252)), "pin_lamp_1")
        assert reading.state is not LampState.ON

    def test_matte_lampe(self, detector):
        reading = detector.detect_one(patch(LAMP_DARK), "pin_lamp_2")
        assert reading.state is LampState.OFF

    def test_neun_lampen_ergeben_die_gefallenen_kegel(self, detector):
        """Gemessener Realfall: Bahn 3, Frame 90 -- Lampen 1,3,5,6,8,9 leuchten."""
        lit = {1, 3, 5, 6, 8, 9}
        patches = [patch(LAMP_LIT if pin in lit else LAMP_DARK)
                   for pin in range(1, 10)]

        reading = detector.detect(patches, list(range(1, 10)))

        assert reading.pins == (1, 3, 5, 6, 8, 9)
        assert reading.count == 6
        assert reading.is_complete
        assert reading.bitmap == 0b110110101

    def test_kein_kegel_gefallen(self, detector):
        reading = detector.detect([patch(LAMP_DARK)] * 9, list(range(1, 10)))
        assert reading.count == 0
        assert reading.pins == ()

    def test_alle_neune(self, detector):
        reading = detector.detect([patch(LAMP_LIT)] * 9, list(range(1, 10)))
        assert reading.count == 9
        assert reading.bitmap == 511

    def test_unlesbare_lampe_macht_die_zaehlung_unvollstaendig(self, detector):
        """Eine unlesbare Lampe darf nicht stillschweigend als 'aus' gelten --
        die Zaehlung waere dann falsch, ohne dass es auffiele."""
        patches = [patch(LAMP_LIT)] * 8 + [np.empty((0, 0, 3), dtype=np.uint8)]
        reading = detector.detect(patches, list(range(1, 10)))

        assert reading.is_complete is False
        assert reading.confidence == 0.0

    def test_abweichende_kegelnummerierung(self, detector):
        """Das Mapping Lampe -> Kegel ist konfigurierbar (offene Frage Q5)."""
        patches = [patch(LAMP_LIT)] + [patch(LAMP_DARK)] * 8
        reading = detector.detect(patches, [9, 8, 7, 6, 5, 4, 3, 2, 1])
        assert reading.pins == (9,)

    def test_laengenkonflikt_wird_abgelehnt(self, detector):
        with pytest.raises(ValueError, match="Kegelnummern"):
            detector.detect([patch(LAMP_LIT)] * 3, [1, 2])

    def test_gesamtconfidence_ist_die_schwaechste_messung(self, detector):
        """Eine unsichere Lampe macht die ganze Zaehlung unsicher."""
        patches = [patch(LAMP_LIT)] * 8 + [np.empty((0, 0, 3), dtype=np.uint8)]
        reading = detector.detect(patches, list(range(1, 10)))
        assert reading.confidence == min(l.confidence for l in reading.lamps)


class TestConfidence:
    def test_weit_ueber_der_schwelle_ist_sicher(self):
        assert confidence_from_threshold(100.0, 45.0, 35.0, 10.0) == 1.0

    def test_weit_unter_der_schwelle_ist_sicher(self):
        assert confidence_from_threshold(0.0, 45.0, 35.0, 10.0) == 1.0

    def test_in_der_hysteresezone_ist_unsicher(self):
        assert confidence_from_threshold(40.0, 45.0, 35.0, 10.0) == 0.25

    def test_knapp_ueber_der_schwelle_ist_maessig(self):
        value = confidence_from_threshold(45.5, 45.0, 35.0, 10.0)
        assert 0.5 <= value < 0.6

    def test_confidence_bleibt_im_gueltigen_bereich(self):
        for score in (-50.0, 0.0, 40.0, 45.0, 1000.0):
            assert 0.0 <= confidence_from_threshold(score, 45.0, 35.0, 10.0) <= 1.0


class TestLampReading:
    def test_unknown_ist_nicht_an(self):
        assert LampReading.unknown("x").is_on is False

    def test_is_known(self):
        assert LampState.ON.is_known and LampState.OFF.is_known
        assert not LampState.UNKNOWN.is_known


class TestCheckVerdict:
    def test_alle_bewertungen_vorhanden(self):
        assert {v.value for v in CheckVerdict} == {
            "GOOD", "WEAK", "NO_SIGNAL", "BROKEN"
        }


class TestBug011AdaptiverBezugswert:
    """Absolute Helligkeitsschwellen halten ueber lange Aufnahmen nicht.

    GEMESSEN ueber 52 Minuten: Das AUS-Niveau der Kegellampen steigt von Median
    151 auf 185; am Ende liegen 24 % aller AUS-Messungen ueber der festen
    Schwelle von 195 und werden dadurch UNKNOWN.
    """

    @staticmethod
    def _lampe(helligkeit: int, waerme: int = 40) -> np.ndarray:
        """Baut einen ROI mit gegebener Helligkeit und Farbwaerme (BGR)."""
        patch = np.zeros((6, 6, 3), dtype=np.uint8)
        patch[:, :, 2] = helligkeit                      # rot
        patch[:, :, 0] = max(0, helligkeit - waerme)     # blau
        return patch

    def _detektor(self, **anpassungen):
        cfg = LampDetectionConfig(**anpassungen)
        return WarmthLampDetector(cfg)

    def test_gedrifteter_aus_wert_bleibt_aus(self):
        """Der Kern des Bugs: Eine AUS-Lampe bei 201 lag ueber der Schwelle 195
        und wurde UNKNOWN -- obwohl sie eindeutig nicht leuchtete."""
        detektor = self._detektor()
        # Gedaechtnis mit dem gedrifteten AUS-Niveau fuellen
        for _ in range(detektor.cfg.baseline_window):
            detektor.detect_one(self._lampe(200), name="pin_lamp_1")

        ergebnis = detektor.detect_one(self._lampe(201), name="pin_lamp_1")

        assert ergebnis.state is LampState.OFF, \
            "eine gedriftete AUS-Lampe darf nicht UNKNOWN werden"

    def test_leuchtende_lampe_bleibt_an(self):
        """Die Anpassung darf nicht dazu fuehren, dass AN verlorengeht."""
        detektor = self._detektor()
        for _ in range(detektor.cfg.baseline_window):
            detektor.detect_one(self._lampe(200), name="pin_lamp_1")

        ergebnis = detektor.detect_one(self._lampe(254), name="pin_lamp_1")

        assert ergebnis.state is LampState.ON

    def test_ohne_gedaechtnis_gelten_die_absoluten_schwellen(self):
        """Ein Bezugswert aus drei Messungen waere schlechter als die belegte
        Einstellung -- solange gilt die absolute Schwelle."""
        detektor = self._detektor()

        ergebnis = detektor.detect_one(self._lampe(254), name="pin_lamp_1")

        assert ergebnis.state is LampState.ON

    def test_dauerleuchten_zieht_den_bezugswert_nicht_beliebig_mit(self):
        """Stuende eine Lampe sehr lange an, zoege sie sonst ihren eigenen
        Bezugswert nach oben und wuerde am Ende als AUS gelesen."""
        detektor = self._detektor()
        for _ in range(detektor.cfg.baseline_window * 2):
            detektor.detect_one(self._lampe(254), name="pin_lamp_1")

        ergebnis = detektor.detect_one(self._lampe(254), name="pin_lamp_1")

        assert ergebnis.state is LampState.ON, \
            "eine dauerhaft leuchtende Lampe darf sich nicht selbst ausschalten"

    def test_abschaltbar(self):
        detektor = self._detektor(adaptive_baseline=False)
        for _ in range(detektor.cfg.baseline_window):
            detektor.detect_one(self._lampe(200), name="pin_lamp_1")

        ergebnis = detektor.detect_one(self._lampe(201), name="pin_lamp_1")

        assert ergebnis.state is LampState.UNKNOWN, \
            "abgeschaltet gelten wieder die absoluten Schwellen"


class TestBug011GruenlampeDriftet:
    """Auch die gruene Lampe driftet -- und dort kostet es den Messzeitpunkt.

    GEMESSEN ueber 52 Minuten: Das AUS-Niveau steigt von 28,3 auf 36,4, das
    AN-Niveau sinkt von 75,8 auf 74,7. Die feste AUS-Schwelle (35) liegt am Ende
    mitten in der AUS-Verteilung (95%-Perzentil 43,4).
    """

    @staticmethod
    def _patch(gruenanteil: float) -> np.ndarray:
        """ROI mit dem gewuenschten Anteil gruener Pixel (in Prozent)."""
        patch = np.zeros((10, 10, 3), dtype=np.uint8)
        patch[:, :] = (30, 30, 30)                       # neutraler Hintergrund
        anzahl = int(round(gruenanteil / 100.0 * 100))
        for k in range(anzahl):
            patch[k // 10, k % 10] = (40, 255, 40)       # gesaettigtes Gruen
        return patch

    def _detektor(self, **anpassungen):
        return HsvGreenDetector(GreenDetectionConfig(**anpassungen))

    def _fuellen(self, detektor, aus: float, an: float) -> None:
        """Gedaechtnis mit einem realistischen Wechsel beider Zustaende fuellen."""
        for i in range(detektor.cfg.adaptive_window):
            detektor.detect(self._patch(an if i % 3 == 0 else aus))

    def test_gedriftetes_aus_wird_wieder_als_aus_erkannt(self):
        """Der Kern: Bei einem AUS-Niveau von 37 lag die feste Schwelle (35)
        darunter -- die Lampe galt als UNKNOWN, und GREEN_OFF loeste zu spaet
        aus. Gemessen 180 Frames, in denen die Anlage bereits neu aufstellte."""
        detektor = self._detektor()
        self._fuellen(detektor, aus=37.0, an=70.0)

        assert detektor.detect(self._patch(37.0)).state is LampState.OFF

    def test_an_bleibt_an(self):
        detektor = self._detektor()
        self._fuellen(detektor, aus=37.0, an=70.0)

        assert detektor.detect(self._patch(70.0)).state is LampState.ON

    def test_ohne_gedaechtnis_gelten_die_festen_schwellen(self):
        detektor = self._detektor()

        assert detektor.detect(self._patch(70.0)).state is LampState.ON
        assert detektor.detect(self._patch(20.0)).state is LampState.OFF

    def test_dauerhaft_ein_zustand_faellt_auf_feste_schwellen_zurueck(self):
        """War die Lampe im ganzen Fenster in EINEM Zustand, liegen beide
        Perzentile dicht beieinander. Eine Schwelle 'zwischen ihnen' laege dann
        mitten in diesem Zustand -- schlimmer als die feste Schwelle."""
        detektor = self._detektor()
        for _ in range(detektor.cfg.adaptive_window):
            detektor.detect(self._patch(70.0))

        assert detektor.detect(self._patch(70.0)).state is LampState.ON

    def test_abschaltbar(self):
        """Alle mitlaufenden Verfahren aus -> es gelten wieder die festen.

        Seit dem gleitenden Histogramm reicht `adaptive_thresholds=False`
        allein nicht mehr: Das Histogramm ist ein eigenes Verfahren mit
        Vorrang. Seit der Anlaufregel (2026-10-06) sind es DREI -- sie
        ueberstimmt die festen Schwellen bewusst, weil auf Bahn 4 beide
        Wolken darueber lagen. Wer die festen Schwellen will, muss alle drei
        abschalten.
        """
        detektor = self._detektor(adaptive_thresholds=False,
                                  histogram_thresholds=False,
                                  warmup_min_change=0.0)
        self._fuellen(detektor, aus=37.0, an=70.0)

        assert detektor.detect(self._patch(37.0)).state is LampState.UNKNOWN

    def test_ohne_lerner_traegt_die_anlaufregel(self):
        """Gegenprobe zum vorigen: Laesst man die Anlaufregel an, meldet sie
        bei derselben Folge ein AUS -- 37 gegen ein Niveau von 70 ist eine
        Aenderung von 33, und das ist mehr als `warmup_min_change`."""
        detektor = self._detektor(adaptive_thresholds=False,
                                  histogram_thresholds=False)
        self._fuellen(detektor, aus=37.0, an=70.0)

        assert detektor.detect(self._patch(37.0)).state is LampState.OFF

    def test_perzentile_bleiben_ohne_histogramm_erhalten(self):
        """Der alte Weg muss weiter tragen -- er ist die Rueckfallebene."""
        detektor = self._detektor(histogram_thresholds=False)
        self._fuellen(detektor, aus=37.0, an=70.0)

        assert detektor.detect(self._patch(37.0)).state is LampState.OFF
        assert detektor.detect(self._patch(70.0)).state is LampState.ON


class TestBug013RauschenAlsWechsel:
    """Bei durchgehend leuchtender Lampe darf Rauschen kein Wechsel werden.

    GEMESSEN in einer Nutzersitzung (Bahn 4, Frames 16600-16780): Der Score der
    gruenen Lampe blieb durchgehend zwischen 78 und 89 -- also klar ueber der
    absoluten AN-Schwelle von 45. Trotzdem kippte der Zustand:

        16664  Score 85,9  ON
        16666  Score 78,8  OFF     <- Wechsel bei 78,8
        16730  Score 79,8  ON      <- und zurueck bei 79,8

    Ursache waren die mitlaufenden Schwellen: Leuchtet die Lampe lange
    durchgehend, liegen 20%- und 90%-Perzentil in DERSELBEN Verteilung, und die
    Schwelle dazwischen trennt blosses Rauschen. Aus einem Wurf wurden zwei.
    """

    @staticmethod
    def _patch(anteil: float) -> np.ndarray:
        patch = np.zeros((10, 10, 3), dtype=np.uint8)
        patch[:, :] = (30, 30, 30)
        for k in range(int(round(anteil))):
            patch[k // 10, k % 10] = (40, 255, 40)
        return patch

    def test_dauerhaft_an_kippt_nicht_durch_rauschen(self):
        cfg = GreenDetectionConfig()
        detektor = HsvGreenDetector(cfg)

        # Lange durchgehend AN, mit dem gemessenen Rauschen von rund 10 Punkten
        for i in range(cfg.adaptive_window):
            detektor.detect(self._patch(79 + (i % 10)))

        zustaende = {detektor.detect(self._patch(wert)).state
                     for wert in (78, 79, 80, 85, 88)}

        assert zustaende == {LampState.ON}, (
            f"Rauschen zwischen 78 und 88 ergab {zustaende} -- "
            f"die Lampe leuchtet durchgehend"
        )

    def test_echter_wechsel_wird_weiterhin_erkannt(self):
        """Die Sicherung darf die Anpassung nicht ganz abschalten."""
        cfg = GreenDetectionConfig()
        detektor = HsvGreenDetector(cfg)

        for i in range(cfg.adaptive_window):
            detektor.detect(self._patch(80 if i % 3 == 0 else 25))

        assert detektor.detect(self._patch(80)).state is LampState.ON
        assert detektor.detect(self._patch(25)).state is LampState.OFF


class TestA2GleitendesHistogramm:
    """Die Schwelle kommt ins Tal zwischen den Wolken -- oder gar nicht.

    GEMESSEN am 2026-08-30 auf Bahn 5, Frames 40894-40914:

        Frame   Score    P20    P90  Spanne  AUS-Schwelle  Zustand
        40903    47,8   40,0   70,0    30,0          52,0  OFF
        40906    47,8   41,8   70,0    28,2  fest: 35,0    ON

    DERSELBE Score, zwei Zustaende. Die Bahn lag 71 % des Fensters auf AN,
    also war das 20. Perzentil kein AUS-Niveau, sondern der untere Rand der
    AN-Wolke -- und die AUS-Schwelle (52,0) lag mitten in der AN-Wolke. Der
    daraus entstandene GREEN_OFF erzeugte einen Wurf, den es nie gab.
    """

    @staticmethod
    def _patch(anteil: float) -> np.ndarray:
        patch = np.zeros((10, 10, 3), dtype=np.uint8)
        patch[:, :] = (30, 30, 30)
        for k in range(int(round(anteil))):
            patch[k // 10, k % 10] = (40, 255, 40)
        return patch

    def _fuellen(self, detektor, werte) -> None:
        for wert in werte:
            detektor.detect(self._patch(wert))

    def test_schiefes_verhaeltnis_kippt_die_schwelle_nicht(self):
        """Der gemessene Fall: 71 % AN, 16 % AUS, Rest Flanken.

        Mit Perzentilen landete die AUS-Schwelle bei 52,0 und machte aus
        Score 47,8 ein AUS. Das Tal des Histogramms liegt bei 37.
        """
        cfg = GreenDetectionConfig()
        detektor = HsvGreenDetector(cfg)

        werte = []
        for i in range(cfg.histogram_min_samples * 2):
            rest = i % 100
            if rest < 16:
                werte.append(24.0)          # AUS-Wolke
            elif rest < 29:
                werte.append(30.0 + rest)   # Flanken, duenn verteilt
            else:
                werte.append(56.0)          # AN-Wolke
        self._fuellen(detektor, werte)

        assert detektor.detect(self._patch(47.8)).state is LampState.ON, (
            "47,8 liegt in der AN-Wolke -- genau der Wert, den die "
            "Perzentile als AUS gelesen haben"
        )
        assert detektor.detect(self._patch(24.0)).state is LampState.OFF

    def test_nur_eine_wolke_sperrt_die_anpassung(self):
        """Der Kern der Regel des Nutzers -- und wortwoertlich BUG-013.

        Leuchtet die Lampe durchgehend, gibt es KEINE zweite Wolke. Dann darf
        keine Schwelle daraus abgeleitet werden, sonst wird im leuchtenden
        Signal ein kuenstliches AUS gesucht.
        """
        cfg = GreenDetectionConfig()
        detektor = HsvGreenDetector(cfg)

        self._fuellen(detektor, [79 + (i % 10)
                                 for i in range(cfg.histogram_min_samples * 2)])

        zustaende = {detektor.detect(self._patch(wert)).state
                     for wert in (78, 79, 80, 85, 88)}

        assert zustaende == {LampState.ON}, (
            f"Rauschen zwischen 78 und 88 ergab {zustaende} -- "
            f"die Lampe leuchtet durchgehend"
        )

    def test_sperre_behaelt_die_zuletzt_gemessene_schwelle(self):
        """Bei einer Wolke bleibt die letzte gemessene stehen -- nicht die feste.

        Sonst entsteht genau der Sprung, der den Phantomwurf erzeugte: Die
        Schwelle sprang von 52,0 auf 35,0, und derselbe Score bedeutete
        ploetzlich etwas anderes.
        """
        cfg = GreenDetectionConfig()
        detektor = HsvGreenDetector(cfg)

        # Erst ein sauberer Wechsel -- daraus wird eine Schwelle gemessen.
        self._fuellen(detektor, [70.0 if i % 3 else 24.0
                                 for i in range(cfg.histogram_min_samples * 2)])
        gemessen = detektor._histogramm.schwellen()
        assert detektor._histogramm.gemessen

        # Danach durchgehend AN, bis das Fenster nur noch eine Wolke enthaelt.
        self._fuellen(detektor, [70.0] * cfg.histogram_window)

        assert detektor._histogramm.schwellen() == gemessen, (
            "Bei einer einzigen Wolke muss die zuletzt gemessene Schwelle "
            "stehen bleiben"
        )

    def test_vor_der_mindestmenge_gelten_die_festen_schwellen(self):
        cfg = GreenDetectionConfig()
        detektor = HsvGreenDetector(cfg)

        self._fuellen(detektor, [70.0 if i % 3 else 24.0 for i in range(200)])

        assert not detektor._histogramm.gemessen
        assert detektor.detect(self._patch(70.0)).state is LampState.ON
        assert detektor.detect(self._patch(24.0)).state is LampState.OFF

    def test_verdeckte_tafel_kommt_nicht_ins_histogramm(self):
        """Ein Spieler vor der Tafel ist keine AUS-Messung, sondern ihr Fehlen.

        GEMESSEN ueber 52 Minuten: 1213 Frames mit Score 0-1, verteilt auf acht
        Abschnitte von 1 bis 18 Sekunden. Als AUS-Wolke gezaehlt zoegen sie die
        Schwelle nach unten, und echte AUS-Phasen gingen danach durch.
        """
        cfg = GreenDetectionConfig()
        detektor = HsvGreenDetector(cfg)

        self._fuellen(detektor, [0.0] * (cfg.histogram_min_samples * 2))

        assert not detektor._histogramm.gemessen, (
            "Eine verdeckte Tafel darf keine Wolke bilden"
        )

    def test_abschaltbar(self):
        cfg = GreenDetectionConfig(histogram_thresholds=False)
        detektor = HsvGreenDetector(cfg)

        assert detektor._histogramm is None
