"""Die Tafelsuche muss innerhalb ihrer Zeitgrenze fertig werden -- und reden.

DER FEHLER (Nutzer, 2026-09-11): *"es ist gescheitert, weil die automatisierte
Kalibrierung nicht lief"*.

WAS WIRKLICH GESCHAH, reproduziert am Stream:

    Bild 1 (volles Raster)   20,5 s   -> Zeitgrenze (20 s) vorbei
    Bild 2 (enges Raster)     1,3 s   -> haette gereicht, kam nie dran

Die Suche SAH im ersten Bild alle vier Tafeln (Guete 0,82 / 0,80 / 0,75 /
0,74). Sie zaehlten nur nicht: `boardtype_min_frames` verlangt, dass eine Tafel
in zwei Bildern an derselben Stelle auftaucht. Zum zweiten Bild kam es nie.

ZWEI URSACHEN, und beide sind hier festgehalten:

1. **Die Zeitgrenze wurde nie nachgemessen.** Sie stammte aus der Zeit des
   Merkmalsabgleichs (7 s je Bild) und blieb beim Umbau auf Bild in Bild (18 s
   je Bild) unveraendert stehen.
2. **Die Suche schwieg.** Zwischen "Bibliothek geladen" und dem Programmende
   lagen 38 Sekunden ohne eine einzige Protokollzeile. Eine Handlung, die eine
   halbe Minute dauert und scheitert, muss eine Spur hinterlassen.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
import pytest

import kegel_cv.calibration.board_match as bm
from kegel_cv.calibration.board_library import LaufendeSuche, Tafeltyp
from kegel_cv.calibration.model import (Calibration, LaneCalibration, Roi)
from kegel_cv.config import load_config


def muster() -> np.ndarray:
    """Eine Tafel mit Struktur -- gleichmaessiges Grau findet man nirgends."""
    bild = np.full((60, 60, 3), 110, dtype=np.uint8)
    cv2.rectangle(bild, (6, 6), (53, 20), (30, 30, 30), -1)
    cv2.rectangle(bild, (10, 30), (25, 45), (200, 200, 200), -1)
    cv2.circle(bild, (40, 38), 6, (60, 60, 60), -1)
    cv2.putText(bild, "K", (30, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (240, 240, 240), 1)
    return bild


def ein_typ() -> Tafeltyp:
    kal = Calibration(lanes=[LaneCalibration(
        lane_id=1, quad=[[0.0, 0.0], [60.0, 0.0], [60.0, 60.0], [0.0, 60.0]],
        rois=[Roi(name="green_lamp", rect=(0.6, 0.55, 0.2, 0.2))])])
    return Tafeltyp(name="Probe", muster=muster(), kalibrierung=kal)


def szene(anzahl: int = 2) -> np.ndarray:
    """Ein Bild mit `anzahl` Tafeln nebeneinander, in Rauschen gebettet."""
    hintergrund = np.random.default_rng(7).integers(
        20, 60, (300, 500, 3), dtype=np.uint8)
    for i in range(anzahl):
        x = 40 + i * 140
        hintergrund[80:140, x:x + 60] = muster()
    return hintergrund


class TestDasZweistufigeRaster:
    """GEMESSEN an der Aufzeichnung: 19 s -> 4,3 s bei gleicher Geometrie
    (Lampenmitte im Mittel 0,47 gegen 0,46 px)."""

    def test_es_findet_dieselben_tafeln(self):
        bild = szene(2)
        m = cv2.cvtColor(muster(), cv2.COLOR_BGR2GRAY)
        maske = np.ones(m.shape, np.uint8)

        bm.GROB_FAKTOR = 1.0
        voll = bm.finde_tafeln(bild, m, maske, max_tafeln=2, min_guete=0.3)
        bm.GROB_FAKTOR = 0.5
        zwei = bm.finde_tafeln(bild, m, maske, max_tafeln=2, min_guete=0.3)

        assert len(zwei) == len(voll) == 2
        for a, b in zip(voll, zwei):
            assert abs(a.mitte[0] - b.mitte[0]) < 3
            assert abs(a.mitte[1] - b.mitte[1]) < 3

    def test_das_grobe_raster_kann_zurueckfallen(self):
        """Findet der Grobdurchgang nichts, wird wie bisher das volle Raster
        abgesucht -- lieber langsam als falsch."""
        leer = np.zeros((80, 80), np.uint8)
        m = cv2.cvtColor(muster(), cv2.COLOR_BGR2GRAY)
        skalen, winkel = bm._grob(leer, m, np.ones(m.shape, np.uint8),
                                  leer, (0, 0))
        assert skalen is None and winkel is None

    def test_ein_vorgegebenes_raster_bleibt_unberuehrt(self):
        """Die Folgebilder suchen eng um das Gefundene -- da waere ein
        Grobdurchgang nur zusaetzliche Arbeit."""
        bild = szene(1)
        m = cv2.cvtColor(muster(), cv2.COLOR_BGR2GRAY)
        funde = bm.finde_tafeln(bild, m, np.ones(m.shape, np.uint8),
                                max_tafeln=1, skalen=[1.0], winkel=[0.0],
                                min_guete=0.3)
        assert len(funde) == 1


class TestDieZeitgrenzeTraegt:
    def test_sie_reicht_fuer_mehrere_bilder(self):
        """Ein einzelnes Bild zaehlt nicht (`min_frames`) -- die Grenze muss
        also fuer MEHRERE reichen, nicht fuer eines."""
        cfg = load_config()
        erstes_bild_s = 4.3      # gemessen 2026-09-11 am 1920x1080-Stream
        weiteres_bild_s = 1.3
        noetig = erstes_bild_s + cfg.calibration.boardtype_min_frames * (
            weiteres_bild_s + cfg.calibration.boardtype_sample_wait_s)
        assert cfg.calibration.boardtype_live_timeout_s > noetig, (
            "Die Zeitgrenze muss fuer das erste Bild UND die Wiederholungen "
            "reichen -- sonst scheitert die Suche, obwohl sie alles sieht")


class TestSieSchweigtNichtMehr:
    def test_ein_misserfolg_steht_im_protokoll(self, caplog):
        """38 stumme Sekunden waren das eigentliche Problem: Ohne Spur liess
        sich nicht einmal erkennen, DASS gesucht wurde."""
        suche = LaufendeSuche([ein_typ()], ziel_anzahl=4, min_frames=2)
        suche.fuettere(szene(2))
        with caplog.at_level(logging.WARNING):
            assert suche.ergebnis() is None
        assert any("ohne Ergebnis" in s for s in caplog.messages), \
            caplog.messages

    def test_die_meldung_nennt_die_ursache(self, caplog):
        """Sie muss sagen, wie viele Bilder gesehen wurden und wie viele
        noetig sind -- genau daran haette man den Fehler erkannt."""
        suche = LaufendeSuche([ein_typ()], ziel_anzahl=4, min_frames=2)
        suche.fuettere(szene(2))
        with caplog.at_level(logging.WARNING):
            suche.ergebnis()
        text = " ".join(caplog.messages)
        assert "1 Bilder" in text and "2 Bilder" in text

    def test_ein_erfolg_steht_ebenfalls_drin(self, caplog):
        suche = LaufendeSuche([ein_typ()], ziel_anzahl=2, min_frames=2)
        bild = szene(2)
        with caplog.at_level(logging.INFO):
            suche.fuettere(bild)
            suche.fuettere(bild)
            ergebnis = suche.ergebnis()
        assert ergebnis is not None
        assert any("Laufende Suche" in s for s in caplog.messages)
