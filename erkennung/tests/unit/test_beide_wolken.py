"""Tests der zweiseitigen Schwellenanpassung (`adaptive_on_level`).

WAS SIE LOEST: Die aeltere Rechnung fuehrt nur die AUS-Seite mit und nimmt fuer
die AN-Seite `brightness_saturated` (255) an. Gemessen liegt die AN-Wolke je
nach Bahn bei 243 bis 253 -- auf Bahn 4 also 12 Punkte unter der Annahme. Weil
die Schwelle als Anteil dieses Abstands gerechnet wird, rutscht sie genau dort
nach oben, wo die Lampen am schwaechsten leuchten.

WAS SIE KOSTEN KOENNTE, und warum es hier nicht passiert: Wenn beide Seiten
mitwandern, kann ein System driften. Zwei Sperren verhindern das, und beide
werden hier geprueft:

    1. Das AN-Gedaechtnis wird an einer FESTEN Schranke gefuellt, nicht an der
       Klassifikation. Sonst entschiede die Schwelle darueber, welche Messungen
       sie selbst bestimmen.
    2. Beruehren sich die Wolken, wird nicht getrennt, sondern auf die
       bewaehrte Rechnung zurueckgefallen.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.config.schema import LampDetectionConfig
from kegel_cv.detection.lamp_detectors import WarmthLampDetector

LAMPE = "pin_lamp_1"


def _cfg(**abweichungen) -> LampDetectionConfig:
    """Wie `config/default.yaml`, nicht wie die Schema-Vorgaben.

    WICHTIG UND BEIM ERSTEN VERSUCH UEBERSEHEN: Die beiden Schranken muessen
    zueinander passen. Der Schema-Standard fuer `baseline_ignore_above` ist 235,
    `an_ignore_below` steht auf 225 -- damit landet jede Messung zwischen 225
    und 235 in BEIDEN Gedaechtnissen, die Wolken ueberlappen sich kuenstlich,
    und die Trennung faellt zurueck. In `default.yaml` liegt die erste Schranke
    deshalb bei 215: dazwischen bleibt ein Niemandsland, das keine Seite praegt.
    """
    grund = dict(adaptive_baseline=True, adaptive_on_level=True,
                 baseline_window=400, baseline_ignore_above=215.0,
                 an_ignore_below=225.0)
    grund.update(abweichungen)
    return LampDetectionConfig(**grund)


def _fuettern(detektor: WarmthLampDetector, werte, anzahl: int = 60) -> None:
    """Speist Helligkeiten ein, ohne den Umweg ueber Bildausschnitte."""
    for _ in range(anzahl):
        for wert in werte:
            if wert < detektor.cfg.baseline_ignore_above:
                detektor._history.setdefault(
                    LAMPE, __import__("collections").deque(maxlen=400)).append(wert)
            if wert > detektor.cfg.an_ignore_below:
                detektor._an_history.setdefault(
                    LAMPE, __import__("collections").deque(maxlen=400)).append(wert)


class TestSchwelleLiegtMittig:
    def test_mitte_zwischen_den_gemessenen_wolken(self):
        """Der Kern: keine Annahme ueber Saettigung mehr.

        AUS-Wolke um 160, AN-Wolke um 240 -- die Mitte liegt bei 200. Die alte
        Rechnung haette mit 255 als Bezug deutlich hoeher gelegen.
        """
        d = WarmthLampDetector(_cfg())
        _fuettern(d, [150.0, 160.0, 170.0, 235.0, 240.0, 245.0])

        an, aus = d._thresholds(LAMPE)
        mitte = (an + aus) / 2

        assert 195 < mitte < 210, (
            f"Mitte bei {mitte:.1f} -- erwartet zwischen den Wolken (160/240)")
        assert aus < an, "Die AUS-Schwelle muss unter der AN-Schwelle liegen"

    def test_dunklere_an_wolke_zieht_die_schwelle_mit(self):
        """Genau der Fall Bahn 4: Die Lampen leuchten schwaecher als anderswo."""
        hell = WarmthLampDetector(_cfg())
        _fuettern(hell, [150.0, 160.0, 170.0, 248.0, 252.0, 254.0])
        dunkel = WarmthLampDetector(_cfg())
        _fuettern(dunkel, [150.0, 160.0, 170.0, 228.0, 232.0, 236.0])

        an_hell, _ = hell._thresholds(LAMPE)
        an_dunkel, _ = dunkel._thresholds(LAMPE)

        assert an_dunkel < an_hell, (
            "Wo die AN-Wolke tiefer liegt, muss auch die Schwelle tiefer "
            "liegen -- sonst verliert man die schwaechste Lampe"
        )

    def test_reserve_zu_beiden_wolken(self):
        """Die Schwelle darf keine der beiden Wolken beruehren."""
        d = WarmthLampDetector(_cfg())
        aus_werte, an_werte = [150.0, 160.0, 175.0], [230.0, 240.0, 250.0]
        _fuettern(d, aus_werte + an_werte)

        an, aus = d._thresholds(LAMPE)

        assert aus > max(aus_werte), "AUS-Schwelle liegt in der AUS-Wolke"
        assert an < min(an_werte), "AN-Schwelle liegt in der AN-Wolke"


class TestSperrenGegenDrift:
    """Die beiden Sicherungen -- ohne sie waere die Rueckkopplung offen."""

    def test_an_gedaechtnis_haengt_nicht_an_der_klassifikation(self):
        """Messungen unter `an_ignore_below` duerfen die AN-Seite nicht praegen.

        Waere es anders, koennte eine zu tiefe Schwelle dunkle Messungen als AN
        einordnen, damit die AN-Wolke nach unten ziehen und die Schwelle noch
        tiefer legen -- bis alles als AN gilt.
        """
        d = WarmthLampDetector(_cfg(an_ignore_below=225.0))
        _fuettern(d, [150.0, 160.0, 170.0, 200.0, 210.0, 220.0])

        assert LAMPE not in d._an_history or not d._an_history[LAMPE], (
            "Keine dieser Messungen liegt ueber 225 -- das AN-Gedaechtnis "
            "muss leer bleiben"
        )
        # Ohne AN-Wolke faellt es auf die alte Rechnung zurueck.
        assert d._beide_wolken(LAMPE) is None

    def test_beruehrende_wolken_fallen_zurueck(self):
        """Liegt kaum Abstand zwischen den Wolken, wird nicht getrennt."""
        d = WarmthLampDetector(_cfg(min_wolken_abstand=20.0,
                                    an_ignore_below=225.0))
        # AUS bis 224, AN ab 226 -- die Wolken beruehren sich fast.
        _fuettern(d, [218.0, 221.0, 224.0, 226.0, 228.0, 230.0])

        assert d._beide_wolken(LAMPE) is None, (
            "Bei weniger als `min_wolken_abstand` darf keine Mitte gebildet "
            "werden -- die Schwelle laege sonst mitten im Signal"
        )

    def test_zu_wenige_messungen_fallen_zurueck(self):
        """Aus drei Messungen wird kein Bezugswert."""
        d = WarmthLampDetector(_cfg())
        _fuettern(d, [150.0, 250.0], anzahl=2)

        assert d._beide_wolken(LAMPE) is None


class TestAbschaltbar:
    def test_ohne_schalter_bleibt_es_bei_der_alten_rechnung(self):
        """Die Gegenprobe -- sonst waeren die Tests oben auch ohne Umbau gruen."""
        d = WarmthLampDetector(_cfg(adaptive_on_level=False))
        _fuettern(d, [150.0, 160.0, 170.0, 235.0, 240.0, 245.0])

        an, aus = d._thresholds(LAMPE)
        # Alte Rechnung: Niveau + (255 - Niveau) * Anteil, mit dem Niveau aus
        # dem 15. Perzentil der AUS-Messungen (rund 150).
        niveau = 150.0
        erwartet_an = niveau + (255.0 - niveau) * d.cfg.baseline_on_fraction
        assert abs(an - erwartet_an) < 6.0, (
            f"Ohne Schalter muss die alte Formel gelten (erwartet {erwartet_an:.1f}, "
            f"bekommen {an:.1f})"
        )
