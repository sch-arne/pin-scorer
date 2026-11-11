"""`--config` ersetzt die Vorgabedatei -- das muss auffallen.

AM 2026-09-29 hat das einen halben Messtag gekostet. Eine Override-Datei mit
der einen Zeile `sampling.baseline_from_previous_state: true` liess zwanzig
Werte auf die Schema-Vorgaben zurueckfallen:

    detection.lamps.adaptive_on_level        True  -> False
    detection.lamps.brightness_on_threshold   213  -> 210
    detection.lamps.core_percentile             0  -> 70
    calibration.lane_number_mapping     [2,3,4,5]  -> [None, None, None, None]
    sampling.breakpoint_from_throw_number   False  -> True
    output.supabase.enabled                  True  -> False

Zwei gezielte Laeufe und ein anderthalbstuendiger Vollauf waren damit
wertlos. Schlimmer: Ein Wurf wurde scheinbar schlechter, und die Fehlersuche
lief eine Stunde lang in die falsche Richtung -- bis der Vergleich der ROHEN
Helligkeitswerte zeigte, dass die Laeufe gar nicht dasselbe gemessen hatten.

Eine WARNUNG, kein Fehler: Ein knappes Profil kann gewollt sein.
"""

from __future__ import annotations

import logging

import pytest

from kegel_cv.config import load_config


@pytest.fixture
def vorgabe(tmp_path):
    """Eine Projektwurzel mit einer Vorgabedatei aus mehreren Abschnitten."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "default.yaml").write_text(
        "sampling:\n"
        "  baseline_from_previous_state: false\n"
        "detection:\n"
        "  lamps:\n"
        "    brightness_on_threshold: 213\n"
        "scoring:\n"
        "  game_reset_number_only: true\n",
        encoding="utf-8")
    return tmp_path


def test_knappe_datei_warnt(vorgabe, caplog):
    knapp = vorgabe / "config" / "nur_ein_schluessel.yaml"
    knapp.write_text("sampling:\n  baseline_from_previous_state: true\n",
                     encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="kegel_cv.config.loader"):
        load_config(knapp, root=vorgabe)
    meldung = " ".join(r.getMessage() for r in caplog.records)
    assert "ERSETZT" in meldung
    assert "detection" in meldung and "scoring" in meldung
    assert "sampling" not in meldung.split(":")[-1]


def test_vollkopie_warnt_nicht(vorgabe, caplog):
    voll = vorgabe / "config" / "vollkopie.yaml"
    voll.write_text(
        (vorgabe / "config" / "default.yaml").read_text(encoding="utf-8")
        .replace("baseline_from_previous_state: false",
                 "baseline_from_previous_state: true"),
        encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="kegel_cv.config.loader"):
        cfg = load_config(voll, root=vorgabe)
    assert cfg.sampling.baseline_from_previous_state is True
    assert not [r for r in caplog.records if "ERSETZT" in r.getMessage()]


def test_die_vorgabe_selbst_warnt_nie(vorgabe, caplog):
    with caplog.at_level(logging.WARNING, logger="kegel_cv.config.loader"):
        load_config(vorgabe / "config" / "default.yaml", root=vorgabe)
    assert not [r for r in caplog.records if "ERSETZT" in r.getMessage()]


def test_ohne_pfad_warnt_nie(vorgabe, caplog):
    with caplog.at_level(logging.WARNING, logger="kegel_cv.config.loader"):
        load_config(root=vorgabe)
    assert not [r for r in caplog.records if "ERSETZT" in r.getMessage()]


def test_die_echte_messdatei_ist_eine_vollkopie(caplog):
    """Die Datei, mit der der Vollauf vom 2026-09-29 laeuft. Fehlt sie, ist
    nichts zu pruefen -- sie liegt im Scratchpad und gehoert nicht ins
    Repository."""
    from pathlib import Path

    from kegel_cv.config.loader import find_project_root

    datei = find_project_root() / "scratchpad" / "vorstand.yaml"
    if not datei.is_file():
        pytest.skip("Messdatei nicht vorhanden")
    with caplog.at_level(logging.WARNING, logger="kegel_cv.config.loader"):
        cfg = load_config(datei)
    assert not [r for r in caplog.records if "ERSETZT" in r.getMessage()]
    vorgabe = load_config()
    a, b = cfg.model_dump(), vorgabe.model_dump()
    a.pop("config_path", None), b.pop("config_path", None)
    unterschiede = _abweichungen(a, b)
    # Seit der Vollauf die Regel bestaetigt hat, ist sie die Vorgabe -- dann
    # unterscheidet sich die Messdatei in GAR NICHTS mehr. Vorher war es
    # genau dieser eine Wert. Beides ist richtig, mehr darf es nie sein.
    assert set(unterschiede) <= {"sampling.baseline_from_previous_state"}, \
        unterschiede
    assert isinstance(Path(datei), Path)


def _abweichungen(a, b, pfad=""):
    """Alle Pfade, an denen sich zwei verschachtelte Abbildungen unterscheiden."""
    if isinstance(a, dict) and isinstance(b, dict):
        aus = []
        for schluessel in sorted(set(a) | set(b)):
            aus += _abweichungen(a.get(schluessel), b.get(schluessel),
                                 f"{pfad}.{schluessel}".lstrip("."))
        return aus
    return [] if a == b else [pfad]
