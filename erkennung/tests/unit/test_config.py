"""Tests der Konfiguration.

Konfigurationsfehler muessen beim Laden auffallen, nicht mitten in der Analyse.
"""

from __future__ import annotations

import logging
import os

import pytest
import yaml

from kegel_cv.config.loader import _deep_merge, find_project_root, load_config
from kegel_cv.config.schema import AppConfig, GreenDetectionConfig, SamplingConfig


class TestDefaults:
    def test_standardkonfiguration_ist_gueltig(self):
        cfg = AppConfig()
        assert cfg.scoring.throws_per_cycle == 15
        assert cfg.scoring.pin_count == 9
        assert cfg.calibration.lane_count == 4

    def test_mitgelieferte_datei_laedt(self):
        """Die ausgelieferte default.yaml muss dem Schema entsprechen."""
        cfg = load_config()
        assert cfg.detection.green.on_threshold > cfg.detection.green.off_threshold
        assert cfg.project_root.is_dir()

    def test_projektwurzel_wird_gefunden(self):
        root = find_project_root()
        assert (root / "config" / "default.yaml").is_file()


class TestHysterese:
    def test_gueltige_hysterese(self):
        cfg = GreenDetectionConfig(on_threshold=45.0, off_threshold=35.0)
        assert cfg.on_threshold > cfg.off_threshold

    @pytest.mark.parametrize("on,off", [(40.0, 40.0), (30.0, 50.0)])
    def test_ungueltige_hysterese_wird_abgelehnt(self, on, off):
        """Gleiche oder invertierte Schwellen machen die Hysterese wirkungslos --
        das zeigt sich sonst erst als sporadisches Zustandsflattern."""
        with pytest.raises(ValueError, match="off_threshold"):
            GreenDetectionConfig(on_threshold=on, off_threshold=off)

    def test_hue_bereich_wird_geprueft(self):
        with pytest.raises(ValueError, match="hue_min"):
            GreenDetectionConfig(hue_min=90, hue_max=40)


class TestSampling:
    def test_gueltige_offsets(self):
        cfg = SamplingConfig(frames_after_green_off=[2, 5], frames_before_green_on=[-3])
        # Das Fenster muss laenger sein als eine Blink-Dunkelphase (gemessen
        # bis 15 Frames), deshalb mehr Frames als urspruenglich angesetzt.
        assert cfg.max_frames_per_event == 10

    def test_negative_offsets_nach_green_off_abgelehnt(self):
        with pytest.raises(ValueError, match="frames_after_green_off"):
            SamplingConfig(frames_after_green_off=[-2])

    def test_positive_offsets_vor_green_on_abgelehnt(self):
        with pytest.raises(ValueError, match="frames_before_green_on"):
            SamplingConfig(frames_before_green_on=[5])


class TestLaneMapping:
    def test_passende_laenge(self):
        cfg = AppConfig.model_validate(
            {"calibration": {"lane_count": 4, "lane_number_mapping": [2, 3, 4, 5]}}
        )
        assert cfg.calibration.lane_number_mapping == [2, 3, 4, 5]

    def test_falsche_laenge_wird_abgelehnt(self):
        with pytest.raises(ValueError, match="genau 4 Eintraege"):
            AppConfig.model_validate(
                {"calibration": {"lane_count": 4, "lane_number_mapping": [1, 2]}}
            )


class TestLaden:
    def test_datei_fehlt(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "gibtsnicht.yaml")

    def test_ungueltiger_wert_nennt_die_datei(self, tmp_path):
        path = tmp_path / "kaputt.yaml"
        path.write_text(
            yaml.safe_dump({"detection": {"green": {"on_threshold": 10, "off_threshold": 20}}}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="kaputt.yaml"):
            load_config(path)

    def test_overrides_uebersteuern_die_datei(self):
        cfg = load_config(overrides={"logging": {"level": "DEBUG"}})
        assert cfg.logging.level == "DEBUG"

    def test_leere_datei_nutzt_standardwerte(self, tmp_path):
        path = tmp_path / "leer.yaml"
        path.write_text("", encoding="utf-8")
        cfg = load_config(path)
        assert cfg.scoring.throws_per_cycle == 15


class TestDeepMerge:
    def test_verschachtelte_werte_werden_gemischt(self):
        """Eine Nutzerkonfiguration soll einzelne Werte aendern koennen,
        ohne den ganzen Block wiederholen zu muessen."""
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        result = _deep_merge(base, {"a": {"y": 99}})
        assert result == {"a": {"x": 1, "y": 99}, "b": 3}

    def test_original_bleibt_unveraendert(self):
        base = {"a": {"x": 1}}
        _deep_merge(base, {"a": {"x": 2}})
        assert base["a"]["x"] == 1


class TestPfadaufloesung:
    def test_relative_pfade_gegen_projektwurzel(self):
        cfg = load_config()
        assert cfg.resolve("debug") == cfg.project_root / "debug"

    def test_absolute_pfade_bleiben_unveraendert(self, tmp_path):
        cfg = load_config()
        assert cfg.resolve(str(tmp_path)) == tmp_path


class TestEnvDatei:
    """Zugangsdaten kommen aus einer `.env`-Datei, nicht aus der YAML.

    Die YAML liegt in der Versionsverwaltung -- Schluessel duerfen das nie. Der
    uebliche Windows-Weg `setx` schreibt dauerhaft in die Registrierung des
    Benutzers; eine Datei im Projekt ist sichtbar und jederzeit loeschbar.
    """

    def test_liest_eintraege(self, tmp_path, monkeypatch):
        from kegel_cv.config.loader import load_env_file

        monkeypatch.delenv("TEST_SCHLUESSEL", raising=False)
        datei = tmp_path / ".env"
        datei.write_text('TEST_SCHLUESSEL="geheim-123"\n', encoding="utf-8")

        assert load_env_file(datei) == 1
        assert os.environ["TEST_SCHLUESSEL"] == "geheim-123"

    def test_ueberschreibt_gesetzte_variablen_nicht(self, tmp_path, monkeypatch):
        """Wer den Wert bewusst im System gesetzt hat, soll ihn behalten."""
        from kegel_cv.config.loader import load_env_file

        monkeypatch.setenv("TEST_SCHLUESSEL", "aus-dem-system")
        datei = tmp_path / ".env"
        datei.write_text("TEST_SCHLUESSEL=aus-der-datei\n", encoding="utf-8")

        load_env_file(datei)
        assert os.environ["TEST_SCHLUESSEL"] == "aus-dem-system"

    def test_warnt_wenn_umgebung_die_datei_ueberstimmt(self, tmp_path, monkeypatch,
                                                       caplog):
        """Der Vorrang bleibt -- aber still darf er nicht bleiben.

        Gemessen am 2026-09-07: In der Benutzerumgebung stand aus einem
        frueheren `setx` ein alter Schluessel. Jede Aenderung an `.env` blieb
        wirkungslos, und nichts sagte warum. Waere dabei auf einen
        Schreibschluessel umgestellt worden, haette die Analyse einen ganzen
        Spieltag in den Versandpuffer geschrieben, ohne dass es auffaellt.
        """
        from kegel_cv.config.loader import load_env_file

        monkeypatch.setenv("TEST_SCHLUESSEL", "aus-dem-system")
        datei = tmp_path / ".env"
        datei.write_text("TEST_SCHLUESSEL=aus-der-datei\n", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            load_env_file(datei)

        assert any("TEST_SCHLUESSEL" in s.message for s in caplog.records), \
            "Der Konflikt muss im Log stehen"
        assert os.environ["TEST_SCHLUESSEL"] == "aus-dem-system", \
            "Der Vorrang selbst aendert sich nicht"

    def test_gleicher_wert_warnt_nicht(self, tmp_path, monkeypatch, caplog):
        """Stimmen beide ueberein, gibt es nichts zu melden."""
        from kegel_cv.config.loader import load_env_file

        monkeypatch.setenv("TEST_SCHLUESSEL", "derselbe-wert")
        datei = tmp_path / ".env"
        datei.write_text("TEST_SCHLUESSEL=derselbe-wert\n", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            load_env_file(datei)

        assert not caplog.records

    def test_kommentare_und_leerzeilen_stoeren_nicht(self, tmp_path, monkeypatch):
        from kegel_cv.config.loader import load_env_file

        monkeypatch.delenv("TEST_A", raising=False)
        datei = tmp_path / ".env"
        datei.write_text("# ein Kommentar\n\nTEST_A=1\n", encoding="utf-8")

        assert load_env_file(datei) == 1

    def test_fehlende_datei_ist_kein_fehler(self, tmp_path):
        from kegel_cv.config.loader import load_env_file

        assert load_env_file(tmp_path / "gibtsnicht") == 0
