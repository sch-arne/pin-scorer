"""Die Verdeckungsschwelle misst sich am UNTEREN RAND der AUS-Wolke.

DER ANLASS (2026-09-13): Ein Mensch lief durch die Gruenphase von Bahn 2. Der
Gruen-Score fiel zehn Frames lang auf exakt 0,0 -- die Signatur einer
vollstaendigen Verdeckung. Die Bremse stand auf `occlusion_score: 0.0`, also
aus, und es wurde ein Wurf gebucht: 0 Kegel, und sein Gesicht als Beleg in der
Datenbank.

DER ERSTE ANLAUF nahm dafuer einen Anteil am GIPFEL der AUS-Wolke. Er war
besser als eine feste Zahl und trotzdem falsch: Der Gipfel sagt, wo AUS
ueblicherweise liegt, aber nichts darueber, wie weit die Wolke nach unten
reicht -- und genau dort entscheidet es sich.

GEMESSEN 2026-09-14 an der Hallenkamera, echte AUS-Wolke (nur Frames, in denen
Tafelwache UND Personenmodell schweigen):

    Bahn   Wolke         Gipfel   Rand   Schwelle alt   bremste alt
      2    0,0 .. 0,7       0,7    0,0           0,90       28,4 %
      3    1,4 .. 3,5       3,5    1,0           1,50        0,2 %
      4    7,1 .. 11,7     11,7    7,0           3,30        0,0 %

Gleiche Halle, gleiches Licht, derselbe Frame -- und drei voellig verschiedene
Lampen. Bahn 2 bremste in 28 % ALLER Frames auf voellig freier Tafel, weil ihr
echtes AUS selbst 0,0 liest.

Im Livestream wirkt dieselbe Regel umgekehrt: Wolken bei 14 bis 31, Rand bei
20 bis 30, Schwelle steigt von rund 8 auf 10 bis 15 -- schaerfer, bei
praktisch gleicher Bremsrate.

Der Nutzer dazu: *"Wir bauen ein Tool, was immer funktioniert, kein 'ja aber
wenn' -- 1 Tool und das muss tragen."*
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration.model import LaneCalibration, Roi
from kegel_cv.config import load_config


def bahn() -> LaneCalibration:
    rois = [Roi(name="green_lamp", rect=(0.45, 0.75, 0.06, 0.05))]
    rois += [Roi(name=f"pin_lamp_{i}", rect=(0.10 + 0.08 * i, 0.30, 0.04, 0.04),
                 pin_number=i) for i in range(1, 10)]
    return LaneCalibration(
        lane_id=1, quad=[[100.0, 50.0], [300.0, 50.0],
                         [300.0, 250.0], [100.0, 250.0]], rois=rois)


def prozessor(anteil: float = 0.5, fest: float = 0.0) -> LaneProcessor:
    cfg = load_config()
    cfg.detection.green.occlusion_edge_fraction = anteil
    cfg.detection.green.occlusion_score = fest
    p = LaneProcessor(bahn(), cfg)
    p.prepare((720, 1280, 3))
    return p


def lerne(p: LaneProcessor, aus, an: float = 70.0, n: int = 6000) -> None:
    """Fuettert das Histogramm mit einer AUS-Wolke und einer AN-Wolke.

    `aus` ist eine Folge von Werten -- so laesst sich die BREITE der Wolke
    vorgeben, und genau darum geht es hier.
    """
    aus = np.asarray(aus, dtype=float)
    h = p.green_detector._histogramm
    for i in range(n):
        h.hinzufuegen(an if i % 3 == 0 else float(aus[i % len(aus)]))
    h._seit_takt = 10 ** 6
    h.schwellen()


class TestDerRandZaehlt:
    def test_zwei_wolken_mit_gleichem_gipfel_geben_verschiedene_schwellen(self):
        """Der Kern der Aenderung. Beide Lampen liegen im Mittel bei 25 -- die
        eine streut von 20 bis 30, die andere von 2 bis 48. Am Gipfel gemessen
        bekaemen beide dieselbe Schwelle; das waere fuer die breite Wolke viel
        zu hoch."""
        eng = prozessor()
        lerne(eng, np.arange(20, 31))
        breit = prozessor()
        lerne(breit, np.arange(2, 49))

        assert eng.green_detector.aus_rand > breit.green_detector.aus_rand
        assert eng._verdeckungsschwelle() > breit._verdeckungsschwelle()

    def test_der_rand_liegt_unter_dem_gipfel(self):
        p = prozessor()
        lerne(p, np.arange(20, 31))
        assert p.green_detector.aus_rand < p.green_detector.aus_niveau

    def test_die_schwelle_bleibt_unter_der_wolke(self):
        """Sie darf nie in die echte AUS-Wolke hineinragen -- sonst bremst sie
        auf freier Tafel, und genau das ist auf Bahn 2 passiert."""
        p = prozessor()
        lerne(p, np.arange(20, 31))
        assert p._verdeckungsschwelle() < 20.0

    def test_eine_verdeckung_wird_trotzdem_gefangen(self):
        """Eine Verdeckung liest 0,0. Zwischen ihr und der Wolke liegt genug
        Platz -- die Schwelle muss deutlich ueber null bleiben."""
        p = prozessor()
        lerne(p, np.arange(20, 31))
        assert p._verdeckungsschwelle() > 5.0


class TestWoDerGruenScoreNichtsWeiss:
    """Hallenkamera, Bahn 2 und 5: Das echte AUS liest selbst 0,0. Dort kann
    dieser Zeuge nichts trennen -- dann schweigt er, statt zu raten."""

    def test_eine_bis_null_reichende_wolke_schaltet_den_zeugen_ab(self):
        p = prozessor(fest=0.0)
        lerne(p, np.arange(0, 4))
        assert p.green_detector.aus_rand == 0.0
        assert p._verdeckungsschwelle() == 0.0

    def test_die_anderen_zeugen_bleiben_unberuehrt(self):
        p = prozessor(fest=0.0)
        lerne(p, np.arange(0, 4))
        assert hasattr(p, "_wache_meldet_fremdes")
        assert hasattr(p, "_modell_meldet_person")
        assert hasattr(p, "_extern_verdeckt")


class TestSchmutzInDerWolke:
    """Jeder Frame, in dem ein Mensch vor der Lampe stand, liegt als 0,0 in der
    Wolke. Ein Quantil zaehlt ihn mit -- GEMESSEN zog das auf Bahn 3 und 4 des
    Streams das 1. Perzentil von 18,5 bzw. 25,0 auf null, und die Bremse haette
    sich selbst abgeschaltet, ohne dass ein Test rot wird."""

    def test_ein_schmutzfleck_bei_null_zieht_den_rand_nicht_herunter(self):
        sauber = prozessor()
        lerne(sauber, np.arange(20, 31))
        # 3 % der AUS-Messungen sind in Wahrheit Verdeckungen
        wolke = list(np.arange(20, 31)) * 32 + [0.0] * 11
        schmutzig = prozessor()
        lerne(schmutzig, wolke)

        assert schmutzig.green_detector.aus_rand == pytest.approx(
            sauber.green_detector.aus_rand, abs=2.0)

    def test_und_die_schwelle_bleibt_brauchbar(self):
        wolke = list(np.arange(20, 31)) * 32 + [0.0] * 11
        p = prozessor()
        lerne(p, wolke)
        assert 5.0 < p._verdeckungsschwelle() < 20.0


class TestDieRahmenbedingungen:
    def test_ohne_zwei_wolken_gilt_der_feste_wert(self):
        p = prozessor(fest=7.0)
        assert p.green_detector.aus_rand is None
        assert p._verdeckungsschwelle() == 7.0

    def test_der_feste_wert_ist_eine_untergrenze(self):
        p = prozessor(fest=20.0)
        lerne(p, np.arange(20, 31))
        assert p._verdeckungsschwelle() == 20.0

    def test_abschaltbar(self):
        p = prozessor(anteil=0.0, fest=4.0)
        lerne(p, np.arange(20, 31))
        assert p._verdeckungsschwelle() == 4.0

    def test_kein_perzentil_rueckfall(self):
        """GEMESSEN an 1100 Frames: Liegt die Bahn ueberwiegend auf AN,
        liefert jedes Perzentil des gleitenden Fensters das AN-Niveau -- 73,3
        statt der wahren 25."""
        p = prozessor()
        for _ in range(3000):
            p.green_detector._history.append(75.0)
        assert p.green_detector.aus_rand is None
        assert p.green_detector.aus_niveau is None

    def test_vergessen_loescht_auch_den_rand(self):
        """Nach einer verschobenen ROI misst dieselbe Lampe andere Pegel."""
        p = prozessor()
        lerne(p, np.arange(20, 31))
        assert p.green_detector.aus_rand is not None
        p.green_detector.vergiss()
        assert p.green_detector.aus_rand is None


class TestVierZeugen:
    """Jeder sieht etwas, das die anderen nicht sehen."""

    def test_alle_vier_sind_verdrahtet(self):
        p = prozessor()
        assert p._extern_verdeckt is False          # Bewegungsmaske
        assert p._wache_meldet_fremdes is False     # Tafelwache
        assert p._modell_meldet_person is False     # Personenmodell
        assert p._verdeckungsschwelle() >= 0.0      # Gruen-Score

    def test_die_wache_meldet_erst_wenn_sie_bereit_ist(self):
        """Vor der ersten Referenz weiss sie nichts -- und darf dann auch
        nichts behaupten, sonst friert jeder Laufstart ein."""
        p = prozessor()
        assert not p.wache.bereit or p.wache.abweichung(
            np.zeros((10, 10, 3), np.uint8)) == 0.0
