"""Ziffernrahmen an den Nullen ausrichten.

WOFUER -- Vorschlag des Nutzers am 2026-09-10:

    "wie waere es, wenn er Anfangs die Ziffern ganz unten verschiebt, bis er
     die 0en halbwegs sicher sieht? Auch bei der Fehlwurfanzeige? so koennen
     wir das niemandem als 'automatisierte Kalibrierung' verkaufen..."

WARUM DAS NICHT ZIRKULAER IST: Zu Spielbeginn steht auf der Tafel `000`, `0`,
`0000`. Das ist ein BEKANNTER Sollwert, keine Vermutung -- verschoben wird
also nicht auf die Lesequalitaet hin, sondern auf einen Inhalt, der
unabhaengig davon feststeht. Ein frueherer Versuch (Ausrichtung an den
Anzeigefenstern) ist genau an dieser Unterscheidung gescheitert.

GEMESSEN 2026-09-10 am Hallenstream: angepasst an EINEM Bild, gemessen an
ACHT spaeteren, an denen nicht angepasst wurde:

    unlesbare Ziffernstellen   69/320 = 21,6 %  ->  56/320 = 17,5 %
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.calibration.digit_zero_fit import (NULLFELDER, Nullpassung,
                                                 passe_an_nullen_an,
                                                 passe_feld_an)
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi

KANTE = 300


class Leser:
    """Ein Leser, der nur an EINER Stelle Nullen sieht.

    Er meldet "0" je Stelle, solange der Ausschnitt hell genug ist -- und
    genau das ist er nur, wenn der Rahmen ueber dem gezeichneten Fleck sitzt.
    """

    class Lesung:
        def __init__(self, text, confidence):
            self.text, self.confidence = text, confidence

    def read_field(self, ausschnitte):
        zeichen, guete = [], []
        for a in ausschnitte:
            if a.size == 0:
                zeichen.append("?")
                guete.append(0.0)
                continue
            hell = float(a.mean())
            if hell > 120:
                zeichen.append("0")
                guete.append(min(1.0, hell / 200))
            else:
                zeichen.append("?")
                guete.append(0.0)
        return self.Lesung("".join(zeichen), float(np.mean(guete)))


def tafel(fleck=(0.40, 0.80, 0.10, 0.10)) -> np.ndarray:
    """Dunkle Tafel mit EINEM hellen Fleck -- dort steht die 'Null'."""
    bild = np.full((KANTE, KANTE, 3), 20, dtype=np.uint8)
    x, y, w, h = fleck
    bild[int(y * KANTE):int((y + h) * KANTE),
         int(x * KANTE):int((x + w) * KANTE)] = 220
    return bild


def bahn(zelle=(0.40, 0.80, 0.10, 0.10)) -> LaneCalibration:
    return LaneCalibration(
        lane_id=1, display_number=2,
        quad=[[0.0, 0.0], [300.0, 0.0], [300.0, 300.0], [0.0, 300.0]],
        rois=[Roi(name="total_b", rect=zelle),
              Roi(name="digit_total_b_1", rect=zelle),
              Roi(name="green_lamp", rect=(0.1, 0.1, 0.05, 0.05))])


class TestFeldAnpassen:
    def test_ein_versatz_wird_gefunden(self):
        """Der Rahmen sitzt daneben, der helle Fleck nicht."""
        verrutscht = bahn((0.42, 0.80, 0.10, 0.10))
        p = passe_feld_an(Leser(), tafel(), verrutscht, "total_b",
                          suchweite=8, tafel_px=KANTE)
        assert p is not None and p.sicher
        assert p.dx < 0, "der Rahmen muss nach links"

    def test_ohne_nullen_kein_ergebnis(self):
        """Mitten im Spiel steht dort keine Null -- dann schweigt es."""
        dunkel = np.full((KANTE, KANTE, 3), 20, dtype=np.uint8)
        assert passe_feld_an(Leser(), dunkel, bahn(), "total_b",
                             tafel_px=KANTE) is None

    def test_ein_feld_ohne_stellen_wird_uebergangen(self):
        ohne = LaneCalibration(
            lane_id=1,
            quad=[[0.0, 0.0], [300.0, 0.0], [300.0, 300.0], [0.0, 300.0]],
            rois=[Roi(name="total_b", rect=(0.4, 0.8, 0.1, 0.1))])
        assert passe_feld_an(Leser(), tafel(), ohne, "total_b",
                             tafel_px=KANTE) is None

    def test_die_mitte_des_plateaus_wird_genommen(self):
        """Nicht der beste Punkt: Ein Rahmen am Rand des lesbaren Bereichs
        liest heute richtig und morgen nicht. GEMESSEN 2026-09-09 entschied
        EIN Pixel ueber neun Prozentpunkte."""
        p = passe_feld_an(Leser(), tafel(), bahn(), "total_b",
                          suchweite=6, tafel_px=KANTE)
        assert p is not None
        assert abs(p.dx) < 0.01 and abs(p.dy) < 0.01, \
            "sitzt der Rahmen schon mittig, bleibt er stehen"
        assert p.plateau > 1


class TestSicherheit:
    def test_ein_einzelner_treffer_genuegt_nicht(self):
        """Sechs von sieben Segmenten einer Null sind aktiv -- da liest sich
        manches versehentlich als Null."""
        assert not Nullpassung("total_b", 0.0, 0.0, guete=0.9,
                               plateau=1).sicher

    def test_schwache_lesung_genuegt_nicht(self):
        assert not Nullpassung("total_b", 0.0, 0.0, guete=0.2,
                               plateau=5).sicher

    def test_plateau_und_guete_zusammen_genuegen(self):
        assert Nullpassung("total_b", 0.0, 0.0, guete=0.8, plateau=3).sicher


class TestUeberAlleBahnen:
    def _kalibrierung(self, zelle):
        return Calibration(lanes=[bahn(zelle)])

    def test_die_kalibrierung_wird_nachgezogen(self):
        kal = self._kalibrierung((0.42, 0.80, 0.10, 0.10))
        vorher = kal.lanes[0].get_roi("digit_total_b_1").rect[0]
        bericht = passe_an_nullen_an(kal, {1: tafel()}, Leser(), suchweite=8)
        assert bericht, "die Bahn muss im Bericht auftauchen"
        assert kal.lanes[0].get_roi("digit_total_b_1").rect[0] < vorher

    def test_lampen_bleiben_unberuehrt(self):
        kal = self._kalibrierung((0.42, 0.80, 0.10, 0.10))
        passe_an_nullen_an(kal, {1: tafel()}, Leser(), suchweite=8)
        assert kal.lanes[0].get_roi("green_lamp").rect == (0.1, 0.1, 0.05, 0.05)

    def test_ohne_tafelbild_geschieht_nichts(self):
        kal = self._kalibrierung((0.42, 0.80, 0.10, 0.10))
        vorher = [r.rect for r in kal.lanes[0].rois]
        assert passe_an_nullen_an(kal, {}, Leser()) == {}
        assert [r.rect for r in kal.lanes[0].rois] == vorher

    def test_ohne_nullen_bleibt_alles_stehen(self):
        kal = self._kalibrierung((0.42, 0.80, 0.10, 0.10))
        vorher = [r.rect for r in kal.lanes[0].rois]
        dunkel = np.full((KANTE, KANTE, 3), 20, dtype=np.uint8)
        assert passe_an_nullen_an(kal, {1: dunkel}, Leser()) == {}
        assert [r.rect for r in kal.lanes[0].rois] == vorher

    def test_die_fehlwurfanzeige_ist_dabei(self):
        """HIER LAG EIN FEHLER: Sie hatte gefehlt, und ich hatte sie ausserdem
        mit `pin_count` verwechselt. Die Fehlwurfanzeige ist `left_display`
        (`detection.foul_field`) und zeigt zu Spielbeginn `00`."""
        assert "left_display" in NULLFELDER

    def test_pin_count_richtet_sich_nicht_selbst_aus(self):
        """Das Feld in der Mitte der unteren Zeile ist zu Spielbeginn DUNKEL
        -- es zeigt keinen Wert, auch keine Null."""
        assert "pin_count" not in NULLFELDER

    def test_pin_count_erbt_von_seinen_nachbarn(self):
        """"der Abstand zwischen der linkesten 0 bei Gesamtsumme und dem
        rechtesten bei Wurfnummer zu dem Wert in der Mitte ist immer
        identisch" -- dieselbe Zeile, derselbe Versatz."""
        from kegel_cv.calibration.digit_zero_fit import ERBEN
        assert ERBEN["pin_count"] == ("throw_number", "total_b")
