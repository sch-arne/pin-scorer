"""Tests des Wurfbelegs (`debug/throw_sheet.py`).

Der Beleg ist die Antwort auf die Frage "warum kam dieses Ergebnis zustande?"
-- er muss deshalb dreierlei leisten und wird auf genau das geprueft:

1. Er entsteht ueberhaupt, und zwar als lesbares Bild.
2. Er traegt die Werte, um die es geht -- Kegelzahl, Tafelziffer, Pruefungen.
3. Er haelt die Analyse nicht auf, wenn beim Schreiben etwas schiefgeht.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from kegel_cv.calibration import Roi
from kegel_cv.debug.throw_sheet import ThrowSheet
from kegel_cv.models.throw import (Evidence, PlausibilityCheck, ThrowResult,
                                   ThrowStatus)

TAFEL_B, TAFEL_H = 44, 53


def _tafel() -> np.ndarray:
    """Eine Miniatur-Tafel -- Inhalt egal, nur Form und Typ zaehlen hier."""
    return np.full((TAFEL_H, TAFEL_B, 3), 60, dtype=np.uint8)


def _rois() -> list[Roi]:
    rois = [Roi(name="green_lamp", rect=(0.45, 0.60, 0.10, 0.08))]
    for i in range(1, 10):
        rois.append(Roi(name=f"pin_lamp_{i}", pin_number=i,
                        rect=(0.1 + (i % 3) * 0.3, 0.3 + (i // 3) * 0.1,
                              0.04, 0.0375)))
    rois.append(Roi(name="digit_throw_number_1", rect=(0.1, 0.9, 0.05, 0.06)))
    return rois


def _wurf(pins=(1, 2, 3), ziffer: int | None = 3,
          status: ThrowStatus = ThrowStatus.VALID,
          checks: tuple = ()) -> ThrowResult:
    return ThrowResult(
        lane=4, throw_number=17, throw_number_in_series=2,
        pins=tuple(pins), pins_count=len(pins),
        displayed_pin_count=ziffer, status=status,
        running_total=42, game_number=3, confidence=0.94,
        evidence=Evidence(checks=tuple(checks)),
    )


@pytest.fixture
def blatt(tmp_path):
    return ThrowSheet(tmp_path, aktiv=True, faktor=2)


class TestBelegEntsteht:
    def test_datei_wird_geschrieben_und_ist_lesbar(self, blatt, tmp_path):
        pfad = blatt.add(_wurf(), _tafel(), _rois(), frame_index=4580,
                         timestamp=184.23)

        assert pfad is not None and pfad.is_file()
        bild = cv2.imread(str(pfad))
        assert bild is not None, "Der Beleg muss sich als Bild lesen lassen"
        # Kopfzeile ueber der Tafel, Werteblock darunter -- also hoeher als die
        # vergroesserte Tafel allein.
        assert bild.shape[0] > TAFEL_H * 2

    def test_pfad_nennt_bahn_spiel_und_wurf(self, blatt):
        """Ohne sprechenden Pfad muesste man jedes Bild oeffnen, um es zu finden."""
        pfad = blatt.add(_wurf(), _tafel(), _rois(), 4580, 184.23)

        assert "bahn4" in pfad.parts
        assert "spiel03" in pfad.name and "wurf017" in pfad.name

    def test_abgeschaltet_entsteht_nichts(self, tmp_path):
        blatt = ThrowSheet(tmp_path, aktiv=False)

        assert blatt.add(_wurf(), _tafel(), _rois(), 4580, 184.23) is None
        assert not list(tmp_path.rglob("*.jpg"))


class TestNurAuffaellige:
    """Die sparsame Betriebsart: nur ablegen, was spaeter jemand ansieht."""

    def test_sauberer_wurf_wird_uebergangen(self, tmp_path):
        blatt = ThrowSheet(tmp_path, aktiv=True, nur_auffaellige=True)

        # Lampen und Tafelziffer einig, Status VALID -- nichts zu klaeren.
        assert blatt.add(_wurf(pins=(1, 2, 3), ziffer=3), _tafel(), _rois(),
                         4580, 184.23) is None

    def test_widerspruch_wird_abgelegt(self, tmp_path):
        blatt = ThrowSheet(tmp_path, aktiv=True, nur_auffaellige=True)

        pfad = blatt.add(_wurf(pins=(1, 2, 3), ziffer=5), _tafel(), _rois(),
                         4580, 184.23)

        assert pfad is not None, (
            "Lampen zeigen 3, die Tafel 5 -- genau dieser Fall ist der Grund, "
            "warum es den Beleg gibt"
        )

    def test_nicht_valider_wurf_wird_abgelegt(self, tmp_path):
        blatt = ThrowSheet(tmp_path, aktiv=True, nur_auffaellige=True)

        pfad = blatt.add(_wurf(status=ThrowStatus.ERROR), _tafel(), _rois(),
                         4580, 184.23)

        assert pfad is not None

    def test_unlesbare_ziffer_gilt_nicht_als_auffaellig(self, tmp_path):
        """Sonst waere jeder Wurf ohne Tafelziffer ein Fall -- das sind viele.

        GEMESSEN am Spieltag 2026-08-22: 74 von 1695 Wuerfen hatten keine
        lesbare Ziffer. Sie sind nicht falsch, nur unbelegt -- und ein Beleg
        ohne zweite Quelle klaert nichts.
        """
        blatt = ThrowSheet(tmp_path, aktiv=True, nur_auffaellige=True)

        assert blatt.add(_wurf(ziffer=None), _tafel(), _rois(),
                         4580, 184.23) is None


class TestRobustheit:
    def test_leere_tafel_stoppt_nicht(self, blatt):
        """Ein fehlendes Bild darf keine Ausnahme werfen -- der Lauf geht weiter."""
        assert blatt.add(_wurf(), np.empty((0, 0, 3), np.uint8), _rois(),
                         4580, 184.23) is None

    def test_pruefungen_landen_im_bild(self, blatt):
        """Die Pruefungen sind der Grund fuer den Status -- ohne sie fehlt das Warum.

        Geprueft wird ueber die Bildhoehe: Jede Pruefzeile macht den Werteblock
        hoeher. Den Text selbst zu lesen hiesse, eine Schrifterkennung zu
        testen statt des Belegs.
        """
        ohne = blatt.add(_wurf(), _tafel(), _rois(), 4580, 184.23)
        hoehe_ohne = cv2.imread(str(ohne)).shape[0]

        mit_pruefungen = _wurf(checks=(
            PlausibilityCheck(name="Summe", expected=42, actual=42, passed=True),
            PlausibilityCheck(name="Wurfnummer", expected=17, actual=18,
                              passed=False),
        ))
        # Anderer Wurf, damit nicht dieselbe Datei ueberschrieben wird
        object.__setattr__(mit_pruefungen, "throw_number", 18)
        mit = blatt.add(mit_pruefungen, _tafel(), _rois(), 4580, 184.23)

        assert cv2.imread(str(mit)).shape[0] > hoehe_ohne
