"""Blinkende Lampen und Raeumwuerfe.

Beide Verhalten stammen aus Messungen am realen Material, nicht aus der
Spezifikation -- deshalb halten Tests sie fest.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.models.readings import (LampReading, LampState, PinLampReading,
                                      aggregate_pin_readings)


def lampen(*zustaende: bool, confidence: float = 0.9) -> PinLampReading:
    """Baut eine Messung: True = Lampe an."""
    reading = []
    for i, an in enumerate(zustaende, start=1):
        reading.append(LampReading(
            state=LampState.ON if an else LampState.OFF,
            score=200.0 if an else 100.0,
            confidence=confidence,
            name=f"pin_lamp_{i}",
        ))
    pins = tuple(i for i, an in enumerate(zustaende, start=1) if an)
    return PinLampReading(lamps=tuple(reading), pins=pins, confidence=confidence)


class TestBlinkenBug007:
    def test_eine_dunkelphase_loescht_die_lampe_nicht(self):
        """BUG-007: Die Kegellampen blinken.

        GEMESSEN ueber 100 Frames eines Wurfs: 8 Lampen -> 0 -> 8 -> 0 -> 8,
        waehrend die Ziffer konstant "8" zeigte. Ein einzelner Messzeitpunkt
        traf die Dunkelphase und meldete einen Leerwurf.
        """
        zusammen = aggregate_pin_readings([
            lampen(True, True, False),     # Hellphase
            lampen(False, False, False),   # Dunkelphase -- hier wurde gemessen
            lampen(True, True, False),     # Hellphase
        ])

        assert zusammen.pins == (1, 2)
        assert zusammen.count == 2

    def test_dauerhaft_dunkle_lampe_bleibt_aus(self):
        """Die Asymmetrie darf nicht zum Dauerbrenner werden: Eine Lampe, die
        in KEINER Messung leuchtet, bleibt aus."""
        zusammen = aggregate_pin_readings([lampen(False, False, False)] * 4)

        assert zusammen.pins == ()
        assert zusammen.count == 0

    def test_leere_messreihe_ergibt_nichts(self):
        assert aggregate_pin_readings([]) is None

    def test_unlesbare_lampe_bleibt_unlesbar(self):
        """Unbekannt darf nicht stillschweigend zu 'aus' werden -- sonst zaehlt
        eine unlesbare Lampe als nicht gefallener Kegel."""
        unbekannt = PinLampReading(
            lamps=(LampReading(LampState.UNKNOWN, 150.0, 0.2, "pin_lamp_1"),),
            pins=(), confidence=0.2)

        zusammen = aggregate_pin_readings([unbekannt, unbekannt])

        assert not zusammen.is_complete


class TestGrundlinieNachGruenAn:
    """Die Raeum-Grundlinie muss NACH GREEN_ON gemessen werden.

    Vom Nutzer erklaert (2026-08-25): "die Lampen gehen bereits an, waehrend die
    Lampe gruen ist, in dieser Zeit duerfen Kegel fallen. Wenn der Wurfzaehler um
    1 steigt sind es ab dann genau 4 Sekunden. Danach erlischt die gruene Lampe
    und die anderen Lampen zeigen, welche Kegel gefallen sind."

    Vor GREEN_ON steht deshalb noch das Ergebnis des VORHERIGEN Wurfs auf der
    Tafel. Wurde dort gemessen, enthielt die Grundlinie dessen Kegel, und die
    Differenz ergab null -- gemessen bei acht Wuerfen, bei denen alle neun
    Lampen mit Helligkeit 254 klar leuchteten und trotzdem "0 Kegel" herauskam.
    """

    def test_offsets_zeigen_nach_vorn(self):
        from kegel_cv.config.schema import SamplingConfig

        cfg = SamplingConfig()
        assert all(o >= 0 for o in cfg.baseline_offsets), \
            "negative Offsets laegen im Fenster des vorherigen Wurfs"

    def test_negative_offsets_werden_abgelehnt(self):
        import pytest
        from kegel_cv.config.schema import SamplingConfig

        with pytest.raises(ValueError, match="negative"):
            SamplingConfig(baseline_offsets=[0, -5])

    def test_spanne_deckt_die_zeit_vor_dem_aufschlag(self):
        """Der Ball braucht Zeit. Die Grundlinie muss davor liegen: Nach dem
        Hochzaehlen des Wurfzaehlers vergehen rund 4 Sekunden (100 Frames) bis
        GREEN_OFF -- die Spanne bleibt deutlich darunter."""
        from kegel_cv.config.schema import SamplingConfig

        cfg = SamplingConfig()
        assert max(cfg.baseline_offsets) <= 50, \
            "sonst koennten bereits Kegel dieses Wurfs erfasst sein"
