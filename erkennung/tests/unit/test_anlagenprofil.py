"""Das Anlagenprofil -- was mitreist, wenn das Werkzeug die Halle wechselt.

DER ANLASS (Nutzer, 2026-09-15): *"Brainstorm wie bekommen wir die ganze Sache
skaliert fuer neue Bahnen? Andere Bahnen funktionieren anders ... da sind die
Kegellampen mal gruen mal rot."*

Bis dahin stand alles in einer einzigen `config/default.yaml`. Zwei Hallen
hiessen zwei Konfigurationsdateien -- und man konnte die zweite nicht einmal
ausprobieren, ohne die erste umzustellen.

DIE TRENNLINIE, und sie ist der eigentliche Gegenstand dieser Tests:

    Aendert sich der Wert beim Hallenwechsel?  -> Anlage, reist mit dem Typ
    Nein                                       -> Verfahren, bleibt global

Der gefaehrlichste Fehler hier waere nicht "es geht nicht", sondern dass ein
Profil still eine Zahl verstellt, die es nicht verstellen sollte. Deshalb
prueft der groesste Teil dieser Datei, was NICHT passiert.
"""

from __future__ import annotations

import pytest

from kegel_cv.calibration.anlage import ZUORDNUNG, AnlagenProfil, wende_an
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi
from kegel_cv.config import load_config


def bahn() -> LaneCalibration:
    return LaneCalibration(
        lane_id=1, quad=[[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]],
        rois=[Roi(name="green_lamp", rect=(0.4, 0.7, 0.1, 0.1))])


class TestOhneProfilAendertSichNichts:
    """Die Bedingung fuer den ganzen Umbau: Eine Kalibrierung aus der Zeit
    davor muss sich exakt wie vorher verhalten. Sonst verstellt der Umbau
    gemessene Zahlen, und zwar unbemerkt."""

    def test_ein_leeres_profil_gibt_dieselbe_konfiguration_zurueck(self):
        cfg = load_config()
        assert wende_an(cfg, AnlagenProfil()) is cfg

    def test_auch_kein_profil_ist_in_ordnung(self):
        cfg = load_config()
        assert wende_an(cfg, None) is cfg

    def test_eine_alte_kalibrierung_bringt_ein_leeres_profil_mit(self):
        kal = Calibration.load("data/calibrations/Fastlane.json")
        assert not kal.anlage
        assert kal.anlage.gesetzt == {}


class TestWasDasProfilVorgibt:
    def test_die_lampenfarbe(self):
        """Der einzige Wert, der eine fremde Anlage sicher ausser Gefecht
        setzt: Die Erkennung sucht Gruen. Eine andere Bereitschaftsfarbe
        faellt nicht schlechter aus, sondern gar nicht."""
        cfg = load_config()
        neu = wende_an(cfg, AnlagenProfil(hue_min=0, hue_max=15))
        assert (neu.detection.green.hue_min,
                neu.detection.green.hue_max) == (0, 15)

    def test_kegelzahl_und_zyklus(self):
        cfg = load_config()
        neu = wende_an(cfg, AnlagenProfil(pin_count=10, throws_per_cycle=20))
        assert neu.scoring.pin_count == 10
        assert neu.scoring.throws_per_cycle == 20

    def test_die_kegelnummern(self):
        cfg = load_config()
        neu = wende_an(cfg, AnlagenProfil(
            pin_number_mapping=[1, 2, 3, 4, 5, 6, 7, 8, 9]))
        assert neu.calibration.pin_number_mapping == list(range(1, 10))

    def test_die_ziffernfelder(self):
        cfg = load_config()
        neu = wende_an(cfg, AnlagenProfil(late_fields=["total_a"],
                                          foul_field="rechts"))
        assert neu.detection.digits.late_fields == ["total_a"]
        assert neu.detection.digits.foul_field == "rechts"

    def test_die_sperre_gegen_farblose_reflexe(self):
        """Kegellampen werden ueber HELLIGKEIT erkannt -- eine rote leuchtet
        so hell wie eine gelbe. `warmth_min` ist nur die Sperre gegen helle,
        aber farblose Reflexe, und die muss bei kalt leuchtenden Lampen
        herunter."""
        cfg = load_config()
        neu = wende_an(cfg, AnlagenProfil(warmth_min=0.0))
        assert neu.detection.lamps.warmth_min == 0.0


class TestWasDasProfilNichtAnfasst:
    """Verfahrensgroessen bleiben, wo sie sind -- sie beschreiben, WIE
    gemessen wird, nicht was dasteht."""

    def test_die_urspruengliche_konfiguration_bleibt_unveraendert(self):
        """Eine Kopie, kein Umschreiben: Die geladene Konfiguration soll auch
        nach einem Lauf noch beschreiben, wie das Werkzeug eingestellt ist."""
        cfg = load_config()
        vorher = cfg.detection.green.hue_min
        wende_an(cfg, AnlagenProfil(hue_min=0, hue_max=20))
        assert cfg.detection.green.hue_min == vorher

    def test_fenstergroessen_und_hysterese_bleiben(self):
        cfg = load_config()
        neu = wende_an(cfg, AnlagenProfil(hue_min=0, hue_max=20, pin_count=10))
        for pfad in (("detection", "green", "histogram_window"),
                     ("detection", "green", "occlusion_edge_fraction"),
                     ("detection", "lamps", "brightness_on_threshold"),
                     ("sampling", "frames_after_green_off"),
                     ("detection", "person_model", "patrol_interval")):
            a, b = cfg, neu
            for stufe in pfad:
                a, b = getattr(a, stufe), getattr(b, stufe)
            assert a == b, pfad

    def test_nur_die_zugeordneten_felder_koennen_ueberhaupt_wandern(self):
        """Wer ein Feld ergaenzt, muss es in `ZUORDNUNG` eintragen -- sonst
        wuesste `wende_an` nicht, wohin damit."""
        assert set(AnlagenProfil()._felder) == set(ZUORDNUNG)


class TestUnmoeglicheProfileWerdenAbgelehnt:
    def test_farbton_verkehrt_herum(self):
        with pytest.raises(ValueError, match="hue_min"):
            AnlagenProfil(hue_min=90, hue_max=40)

    def test_kegelnummern_doppelt_vergeben(self):
        with pytest.raises(ValueError, match="genau einmal"):
            AnlagenProfil(pin_number_mapping=[1, 1, 3, 4, 5, 6, 7, 8, 9])

    def test_kegelnummern_passen_nicht_zur_kegelzahl(self):
        """Ein Widerspruch, der sonst erst beim ersten Wurf auffiele -- und
        dann als falsche Kegelnummer, nicht als Fehler."""
        with pytest.raises(ValueError, match="pin_count"):
            AnlagenProfil(pin_count=10, pin_number_mapping=[1, 2, 3])

    def test_ein_einzelner_farbwert_ist_erlaubt(self):
        """Wer nur die Saettigung anheben will, soll nicht den ganzen
        Farbbereich wiederholen muessen."""
        assert AnlagenProfil(saturation_min=120).saturation_min == 120


class TestDerWegDurchDieKalibrierung:
    def test_profil_ueberlebt_speichern_und_laden(self, tmp_path):
        kal = Calibration(lanes=[bahn()], anlage=AnlagenProfil(
            hue_min=0, hue_max=15, pin_count=9, throws_per_cycle=20))
        ziel = tmp_path / "halle.json"
        kal.save(ziel)
        wieder = Calibration.load(ziel)
        assert wieder.anlage.gesetzt == {
            "hue_min": 0, "hue_max": 15, "pin_count": 9,
            "throws_per_cycle": 20}

    def test_die_pipeline_wendet_es_an(self):
        from kegel_cv.analysis.pipeline import AnalysisPipeline
        cfg = load_config()
        kal = Calibration(lanes=[bahn()],
                          anlage=AnlagenProfil(throws_per_cycle=20))
        pipeline = AnalysisPipeline(kal, cfg, video_id="profiltest")
        assert pipeline.cfg.scoring.throws_per_cycle == 20
        assert cfg.scoring.throws_per_cycle == 15, "das Original bleibt"

    def test_ein_wechsel_im_lauf_wird_gemeldet_und_nicht_gemacht(self, caplog):
        """Die Schwellen der Lampenerkennung sind zur Laufzeit eingelernt.
        Sie mitten im Spiel zu tauschen hiesse, mit halb gelernten Wolken
        weiterzumessen."""
        from kegel_cv.analysis.pipeline import AnalysisPipeline
        cfg = load_config()
        kal = Calibration(lanes=[bahn()],
                          anlage=AnlagenProfil(throws_per_cycle=20))
        pipeline = AnalysisPipeline(kal, cfg, video_id="profilwechsel")
        pipeline.prepare((720, 1280, 3))

        andere = Calibration(lanes=[bahn()],
                             anlage=AnlagenProfil(throws_per_cycle=30))
        with caplog.at_level("WARNING"):
            pipeline.uebernimm_kalibrierung(andere, (720, 1280, 3))
        assert "Anlagenprofil" in caplog.text
        assert pipeline.cfg.scoring.throws_per_cycle == 20
