"""Die geladene Konfiguration muss im Protokoll stehen.

WARUM ES DIESEN TEST GIBT -- Trainingsabend am 2026-09-08:

Die Oberflaeche lief einen ganzen Abend mit den Overlay-Schwellen
(`warmth_min: 12.0`), waehrend danebenher mit den Kamera-Schwellen
(`0.0`) nachgemessen wurde. Beide Laeufe sahen im Protokoll identisch aus.
Die Lampen meldeten UNKNOWN bei Helligkeit 255 -- und niemand konnte sehen,
warum, weil nirgends stand, WELCHE Einstellungen gerade galten.

Der erste Anlauf schrieb die Zeile in `load_config`. Sie kam trotzdem nie an:
Die Oberflaeche laedt die Konfiguration, BEVOR sie das Logging aufsetzt --
sie braucht die Konfiguration ja dafuer. Deshalb traegt `AppConfig` den Pfad
mit, und `main.py` meldet ihn, sobald das Log steht.
"""

from __future__ import annotations

import logging

from kegel_cv.config import load_config


class TestDerPfadWirdMitgetragen:
    def test_config_path_zeigt_auf_die_geladene_datei(self):
        cfg = load_config()
        assert cfg.config_path is not None
        assert cfg.config_path.name == "default.yaml"
        assert cfg.config_path.is_file()

    def test_ein_anderer_pfad_wird_auch_so_gemeldet(self, tmp_path):
        ziel = tmp_path / "eigene.yaml"
        ziel.write_text(
            load_config().config_path.read_text(encoding="utf-8"),
            encoding="utf-8")
        cfg = load_config(ziel)
        assert cfg.config_path == ziel

    def test_der_pfad_landet_nicht_in_der_serialisierung(self):
        """`exclude=True` wie `project_root` -- er beschreibt die Herkunft,
        nicht die Einstellung."""
        cfg = load_config()
        assert "config_path" not in cfg.model_dump()


class TestDieMeldung:
    def test_loader_meldet_die_entscheidenden_werte(self, caplog):
        """Fuer Werkzeuge, die ihr Logging VOR dem Laden aufsetzen."""
        with caplog.at_level(logging.INFO, logger="kegel_cv.config.loader"):
            cfg = load_config()
        text = " ".join(r.getMessage() for r in caplog.records)
        assert "Konfiguration" in text
        assert "Verdeckungsschwelle" in text and "Waermeschranke" in text
        # "aus" statt einer Zahl, wenn die Schranke abgeschaltet ist. Eine
        # Null waere irrefuehrend: Sie war es lange, und genau daran lag ein
        # Fehler (siehe `detection.lamps.warmth_min`).
        waerme = cfg.detection.lamps.warmth_min
        assert ("aus" if waerme is None else "%.1f" % waerme) in text

    def test_main_meldet_sie_nach_dem_logging_aufbau(self, caplog, monkeypatch):
        """Der eigentliche Fall: Die Oberflaeche laedt vor dem Logging.

        Geprueft wird die Reihenfolge in `main.main` -- die Meldung muss NACH
        `setup_logging` kommen, sonst geht sie verloren.
        """
        from kegel_cv import main as m

        reihenfolge: list[str] = []
        monkeypatch.setattr(m, "setup_logging",
                            lambda *a, **k: reihenfolge.append("logging"))

        def kein_qt(*a, **k):
            reihenfolge.append("gui")
            raise SystemExit(0)

        monkeypatch.setattr(m, "log", logging.getLogger("kegel_cv.main.test"))
        with caplog.at_level(logging.INFO, logger="kegel_cv.main.test"):
            try:
                m.main(["--config", str(load_config().config_path)])
            except (SystemExit, ImportError, Exception):
                pass

        text = " ".join(r.getMessage() for r in caplog.records)
        assert "Konfiguration:" in text, \
            "ohne diese Zeile ist nicht erkennbar, welche Schwellen gelten"
        assert "Waermeschranke" in text
        assert reihenfolge and reihenfolge[0] == "logging", \
            "die Meldung darf nicht vor dem Logging-Aufbau entstehen"
