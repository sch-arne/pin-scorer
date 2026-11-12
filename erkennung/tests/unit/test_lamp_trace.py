"""Tests der Lampenspur.

Die Spur ist ein Messwerkzeug, kein Erkennungsschritt -- sie darf die Analyse
weder verlangsamen noch beeinflussen. Geprueft wird deshalb dreierlei: dass sie
den MASSSTAB mitschreibt (nicht nur den Messwert), dass sie sich an ihren Takt
haelt, und dass ein Schreibfehler die Analyse nicht anhaelt.

WARUM DER MASSSTAB: Bei der gruenen Lampe liess sich der Phantomwurf vom
2026-08-30 nur deshalb aufklaeren, weil Score UND Zustand je Frame vorlagen --
derselbe Score (47,8) bedeutete einmal AUS und drei Frames spaeter AN. Nicht
das Signal hatte sich geaendert, sondern die Schwelle. Ohne die Schwelle in der
Datei waere dieser Fehler unsichtbar geblieben.
"""

from __future__ import annotations

import csv

import numpy as np
import pytest

from kegel_cv.config.schema import LampDetectionConfig
from kegel_cv.debug.lamp_trace import LampTrace
from kegel_cv.detection.lamp_detectors import WarmthLampDetector

LAMP_LIT = (170, 235, 255)
LAMP_DARK = (140, 148, 155)


def patch(farbe, groesse: int = 12) -> np.ndarray:
    return np.full((groesse, groesse, 3), farbe, dtype=np.uint8)


@pytest.fixture
def detektor():
    return WarmthLampDetector(LampDetectionConfig())


def _messung(detektor):
    patches = [patch(LAMP_LIT if p in (1, 3) else LAMP_DARK) for p in range(1, 10)]
    return detektor.detect(patches, list(range(1, 10)))


class TestSchwellenVon:
    """Der Detektor muss seinen Massstab herausgeben koennen -- ohne Nebenwirkung."""

    def test_liefert_beide_schwellen(self, detektor):
        an, aus, _ = detektor.schwellen_von("pin_lamp_1")
        assert an > aus

    def test_ohne_gedaechtnis_keine_grundlinie(self, detektor):
        """Solange zu wenig gemessen wurde, gelten die absoluten Schwellen --
        dann gibt es keine Grundlinie, und die Spur soll das auch zeigen."""
        _, _, grundlinie = detektor.schwellen_von("pin_lamp_1")
        assert np.isnan(grundlinie)

    def test_grundlinie_erscheint_mit_dem_gedaechtnis(self, detektor):
        for _ in range(detektor.cfg.baseline_window):
            detektor.detect_one(patch(LAMP_DARK), "pin_lamp_1")

        an, aus, grundlinie = detektor.schwellen_von("pin_lamp_1")
        assert not np.isnan(grundlinie)
        assert aus < an
        assert grundlinie < aus, "Die Grundlinie liegt unter beiden Schwellen"

    def test_nachsehen_veraendert_nichts(self, detektor):
        for _ in range(detektor.cfg.baseline_window):
            detektor.detect_one(patch(LAMP_DARK), "pin_lamp_1")
        vorher = detektor.schwellen_von("pin_lamp_1")

        for _ in range(20):
            detektor.schwellen_von("pin_lamp_1")

        assert detektor.schwellen_von("pin_lamp_1") == vorher


class TestSpur:
    def test_schreibt_je_lampe_eine_zeile_mit_massstab(self, tmp_path, detektor):
        ziel = tmp_path / "lampenspur.csv"
        spur = LampTrace(ziel, takt=1)

        spur.add(0, 0.0, 2, _messung(detektor), detektor)
        spur.close()

        zeilen = list(csv.DictReader(ziel.open(encoding="utf-8-sig"),
                                     delimiter=";"))
        assert len(zeilen) == 9
        assert {z["Lampe"] for z in zeilen} == {f"pin_lamp_{i}" for i in range(1, 10)}
        assert zeilen[0]["Bahn"] == "2"
        # Der Massstab gehoert dazu -- daran allein zeigt sich ein wandernder
        # Bezugswert unter einem ruhigen Signal.
        for feld in ("Helligkeit", "Zustand", "Grundlinie",
                     "AN_Schwelle", "AUS_Schwelle"):
            assert feld in zeilen[0]

    def test_haelt_den_takt(self, tmp_path, detektor):
        """Bei neun Lampen auf vier Bahnen waeren es sonst Millionen Zeilen."""
        ziel = tmp_path / "lampenspur.csv"
        spur = LampTrace(ziel, takt=25)
        messung = _messung(detektor)

        for f in range(100):
            spur.add(f, f / 25.0, 2, messung, detektor)
        spur.close()

        zeilen = list(csv.DictReader(ziel.open(encoding="utf-8-sig"),
                                     delimiter=";"))
        assert {int(z["Frame"]) for z in zeilen} == {0, 25, 50, 75}
        assert len(zeilen) == 4 * 9

    def test_abgeschaltet_entsteht_keine_datei(self, tmp_path, detektor):
        ziel = tmp_path / "lampenspur.csv"
        spur = LampTrace(ziel, aktiv=False, takt=1)

        spur.add(0, 0.0, 2, _messung(detektor), detektor)
        spur.close()

        assert not ziel.exists()

    def test_ein_schreibfehler_haelt_die_analyse_nicht_an(self, tmp_path, detektor):
        """Prinzip P8: Ein Fehler in der Protokollierung beendet nichts."""
        spur = LampTrace(tmp_path / "x" / "y.csv", takt=1)
        spur._oeffnen()

        class KaputteDatei:
            def write(self, _):
                raise OSError("Platte voll")

            def close(self):
                pass

        spur._datei = KaputteDatei()
        spur.add(0, 0.0, 2, _messung(detektor), detektor)   # darf nicht werfen

        assert not spur.aktiv
        spur.close()
