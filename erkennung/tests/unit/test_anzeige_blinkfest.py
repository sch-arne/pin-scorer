"""Die LIVE-ANZEIGE darf nicht mitblinken.

WARUM ES DIESEN TEST GIBT -- Meldung des Nutzers am 2026-09-08:

    "aber Pinlamp9 also Kegel 1 hat trotzdem manchmal noch bisschen Probleme...
     ueber die Zeit laeuft es, aber unten im 5 Frame abtaster, meldet er
     trotzdem manchmal aus"

GEMESSEN an der Hallenkamera: Die neun Kegellampen blinken GEMEINSAM, Periode
rund 15 Frames (1 Sekunde), etwa 40 Prozent davon dunkel:

    Bahn 3:  9 9 9 0 0 0 9 9 9 0 0 9 9 9 9 ...

Das Wurfergebnis stoert das nicht -- es fasst viele Frames zusammen. Die
Anzeige las dagegen EINEN Frame und meldete darum regelmaessig "aus", obwohl
die Lampe sichtbar leuchtete.

Geprueft wird die Zusammenfassung selbst, ohne Video und ohne Pipeline.
"""

from __future__ import annotations

from kegel_cv.models.readings import (LampReading, LampState, PinLampReading,
                                      aggregate_pin_readings)


def messung(*an: int) -> PinLampReading:
    """Eine Lampenmessung: die genannten Kegel leuchten, der Rest ist aus."""
    lampen = tuple(
        LampReading(
            state=LampState.ON if pin in an else LampState.OFF,
            score=255.0 if pin in an else 110.0,
            confidence=0.9,
            name=f"pin_lamp_{pin}",
        )
        for pin in range(1, 10)
    )
    return PinLampReading(lamps=lampen, pins=tuple(sorted(an)), confidence=0.9)


# Die gemessene Blinkfolge: drei Messungen an, zwei aus.
BLINKFOLGE = [messung(1, 2, 3), messung(1, 2, 3), messung(1, 2, 3),
              messung(), messung()]


class TestGlaettung:
    def test_eine_einzelne_messung_kann_daneben_liegen(self):
        """Der Ausgangspunkt: Genau das sah der Nutzer."""
        assert BLINKFOLGE[3].pins == (), "in der Dunkelphase meldet sie nichts"

    def test_ueber_die_folge_bleibt_die_lampe_an(self):
        zusammen = aggregate_pin_readings(BLINKFOLGE)
        assert zusammen is not None
        assert zusammen.pins == (1, 2, 3)

    def test_auch_wenn_die_letzte_messung_dunkel_ist(self):
        """Der haeufigste Fall -- die Anzeige friert sonst auf 'aus' ein."""
        zusammen = aggregate_pin_readings(BLINKFOLGE)
        assert zusammen.pins == (1, 2, 3)

    def test_eine_dauerhaft_dunkle_lampe_bleibt_dunkel(self):
        """Die Glaettung darf nichts erfinden -- Kegel 9 leuchtet nie."""
        zusammen = aggregate_pin_readings(BLINKFOLGE)
        assert 9 not in zusammen.pins

    def test_nur_dunkle_messungen_ergeben_nichts(self):
        zusammen = aggregate_pin_readings([messung(), messung(), messung()])
        assert zusammen.pins == ()


class TestDasFensterDecktEinePeriode:
    def test_zwanzig_frames_bei_takt_fuenf_sind_vier_messungen(self):
        """20 // 5 = 4 Messungen decken bei 15 fps eine Blinkperiode ab.

        Die Periode wurde mit rund 15 Frames gemessen; bei jedem fuenften
        Frame sind das drei Messungen. Vier lassen Luft.
        """
        from kegel_cv.config import load_config

        cfg = load_config()
        takt = max(1, cfg.detection.lamps.live_preview_interval)
        messungen = cfg.detection.lamps.live_preview_smoothing_frames // takt
        assert messungen >= 3, (
            "das Fenster muss eine ganze Blinkperiode fassen, sonst koennen "
            "alle Messungen darin dunkel sein")

    def test_die_zaehlung_benutzt_diesen_wert_nicht(self):
        """Die Glaettung ist reine Anzeige. Faende sie sich in der Zaehlung,
        waere sie eine Beschoenigung statt einer Lesehilfe."""
        import inspect

        from kegel_cv.analysis import lane_processor

        quelle = inspect.getsource(lane_processor.LaneProcessor)
        aufrufe = quelle.count("self._geglaettete_anzeige()")
        assert aufrufe == 1, (
            "erwartet: genau EIN Aufruf, naemlich im Snapshot fuer die "
            f"Oberflaeche -- gefunden: {aufrufe}")
        # Und das Ergebnis darf nirgends in die Wurfmessungen wandern.
        for verboten in ("_result_samples.append(self._geglaettete",
                         "_pause_samples.append(self._geglaettete",
                         "_baseline_samples.append(self._geglaettete"):
            assert verboten not in quelle, (
                f"die Glaettung darf nicht in die Zaehlung: {verboten}")
