"""Tests des Tafelbilds, das jedem Wurf beiliegt.

Der Zweck des Bildes ist Nachvollziehbarkeit (P1): Wer im Liveticker einen Wurf
korrigiert, soll sehen, worueber er entscheidet. Zwei Dinge muessen dafuer
stimmen -- es zeigt NUR die eingemessene Tafel, und ein fehlendes Bild haelt
niemals einen Wurf auf (P8).
"""

from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest

from kegel_cv.analysis.board_image import crop_board, encode_board
from kegel_cv.models.throw import ThrowResult, ThrowStatus
from kegel_cv.sinks.payload import throw_to_row


def bild(breite=200, hoehe=150, wert=90) -> np.ndarray:
    return np.full((hoehe, breite, 3), wert, dtype=np.uint8)


class TestZuschnitt:
    def test_schneidet_genau_die_tafel(self):
        img = bild()
        img[40:90, 30:110] = 200          # die "Tafel"
        aus = crop_board(img, (30, 40, 80, 50))
        assert aus.shape == (50, 80, 3)
        assert int(aus.mean()) == 200, "nur die Tafel, nichts drumherum"

    def test_ueber_den_rand_hinaus_wird_begrenzt(self):
        """numpy schneidet still ab -- hier soll trotzdem ein Bild entstehen."""
        aus = crop_board(bild(200, 150), (150, 100, 400, 400))
        assert aus is not None
        assert aus.shape == (50, 50, 3)

    def test_ohne_bild_oder_ohne_rechteck_kein_zuschnitt(self):
        assert crop_board(None, (0, 0, 10, 10)) is None
        assert crop_board(bild(), None) is None

    def test_leeres_rechteck_liefert_nichts(self):
        assert crop_board(bild(), (10, 10, 0, 30)) is None
        assert crop_board(bild(), (10, 10, 30, -5)) is None

    def test_rechteck_ganz_ausserhalb_liefert_nichts(self):
        assert crop_board(bild(200, 150), (500, 500, 40, 40)) is None


class TestKodierung:
    def test_liefert_dekodierbares_jpeg(self):
        text = encode_board(bild(), (10, 10, 80, 60), quality=40)
        assert text is not None
        roh = base64.b64decode(text)
        assert roh[:2] == b"\xff\xd8", "JPEG-Kennung fehlt"
        zurueck = cv2.imdecode(np.frombuffer(roh, np.uint8), cv2.IMREAD_COLOR)
        assert zurueck.shape == (60, 80, 3)

    def test_kein_data_praefix(self):
        """Das Praefix setzt die Anzeige -- in der Datenbank stoert es nur."""
        text = encode_board(bild(), (0, 0, 40, 40))
        assert not text.startswith("data:")

    def test_niedrigere_qualitaet_ergibt_kleineres_bild(self):
        # Rauschen statt Flaeche, sonst komprimiert alles auf dieselbe Groesse.
        rng = np.random.default_rng(0)
        img = rng.integers(0, 255, (150, 200, 3), dtype=np.uint8)
        klein = len(encode_board(img, (0, 0, 200, 150), quality=20))
        gross = len(encode_board(img, (0, 0, 200, 150), quality=95))
        assert klein < gross

    @pytest.mark.parametrize("qualitaet", [0, -5, 200])
    def test_unsinnige_qualitaet_wird_eingefangen(self, qualitaet):
        """Ein falscher Wert in der Konfiguration darf keinen Lauf abbrechen."""
        assert encode_board(bild(), (0, 0, 40, 40), quality=qualitaet) is not None

    def test_ohne_bild_gibt_es_None_statt_eines_Fehlers(self):
        assert encode_board(None, (0, 0, 10, 10)) is None
        assert encode_board(bild(), None) is None


class TestAmWurf:
    def test_bild_geht_mit_in_die_zeile(self):
        wurf = ThrowResult(
            lane=2, throw_number=1, throw_number_in_series=1,
            pins=(1, 2), pins_count=2, displayed_pin_count=2,
            status=ThrowStatus.VALID, running_total=2,
            board_image="AAAA",
        )
        assert throw_to_row(wurf)["board_jpeg"] == "AAAA"

    def test_ohne_bild_keine_spalte(self):
        """Sonst schickte jeder Wurf ein leeres Feld mit."""
        wurf = ThrowResult(
            lane=2, throw_number=1, throw_number_in_series=1,
            pins=(1,), pins_count=1, displayed_pin_count=1,
            status=ThrowStatus.VALID, running_total=1,
        )
        assert "board_jpeg" not in throw_to_row(wurf)

    def test_abschaltbar(self):
        wurf = ThrowResult(
            lane=2, throw_number=1, throw_number_in_series=1,
            pins=(1,), pins_count=1, displayed_pin_count=1,
            status=ThrowStatus.VALID, running_total=1,
            board_image="AAAA",
        )
        assert "board_jpeg" not in throw_to_row(wurf, mit_bild=False)

    def test_debug_json_traegt_das_bild_nicht_mit(self):
        """Base64 in jedem Protokoll machte es unlesbar -- nur ein Vermerk."""
        wurf = ThrowResult(
            lane=2, throw_number=1, throw_number_in_series=1,
            pins=(1,), pins_count=1, displayed_pin_count=1,
            status=ThrowStatus.VALID, running_total=1,
            board_image="A" * 5000,
        )
        d = wurf.to_dict()
        assert d["has_board_image"] is True
        assert "board_image" not in d
        assert "A" * 100 not in repr(d)


class TestFrameAuswahl:
    """Die Anlage laesst die Kegellampen blinken -- ein Frame kann leer sein.

    GEMESSEN am 2026-09-07 (Bahn 1, Ereignis 7, Wurf 20, neun Kegel): Von zehn
    gesampelten Frames waren FUENF voellig dunkel, waehrend das untere Display
    durchgehend `020 9 0129` zeigte. Vom Nutzer gemeldet: "bei einer 9 oder 8
    ist es manchmal leer... also alle Lampen aus".
    """

    LAMPEN = [(10, 10, 6, 6), (30, 10, 6, 6), (50, 10, 6, 6)]

    def _frame(self, lampenwert: int) -> np.ndarray:
        img = bild(100, 40, 30)
        for x, y, w, h in self.LAMPEN:
            img[y:y + h, x:x + w] = lampenwert
        return img

    def test_nimmt_den_frame_mit_den_hellsten_lampen(self):
        from kegel_cv.analysis.board_image import pick_board_frame

        dunkel, mittel, hell = self._frame(40), self._frame(150), self._frame(250)
        gewaehlt = pick_board_frame([dunkel, mittel, hell], self.LAMPEN)
        assert gewaehlt is hell

    def test_die_dunkle_blinkphase_wird_uebergangen(self):
        """Der Ausloeser steht vorn -- trotzdem gewinnt der leuchtende Frame."""
        from kegel_cv.analysis.board_image import pick_board_frame

        ausloeser_dunkel = self._frame(35)
        spaeter_hell = self._frame(255)
        gewaehlt = pick_board_frame([ausloeser_dunkel, spaeter_hell], self.LAMPEN)
        assert gewaehlt is spaeter_hell, "sonst zeigt das Bild eine leere Raute"

    def test_bei_gleichstand_bleibt_es_beim_ausloeser(self):
        """Ein Wurf ohne Kegel: alle Frames gleich dunkel, keiner ist besser."""
        from kegel_cv.analysis.board_image import pick_board_frame

        a, b, c = self._frame(40), self._frame(40), self._frame(40)
        assert pick_board_frame([a, b, c], self.LAMPEN) is a

    def test_ohne_lampenrechtecke_der_erste(self):
        from kegel_cv.analysis.board_image import pick_board_frame

        a, b = self._frame(40), self._frame(255)
        assert pick_board_frame([a, b], []) is a
        assert pick_board_frame([a, b], None) is a

    def test_ohne_frames_nichts(self):
        from kegel_cv.analysis.board_image import pick_board_frame

        assert pick_board_frame([], self.LAMPEN) is None

    def test_helligkeit_misst_nur_die_lampen(self):
        """Ein helles Display anderswo darf die Wahl nicht bestimmen."""
        from kegel_cv.analysis.board_image import lamp_brightness

        mit_lampen = self._frame(250)
        nur_display = bild(100, 40, 30)
        nur_display[25:35, 5:95] = 255        # helles Feld, aber keine Lampe
        assert lamp_brightness(mit_lampen, self.LAMPEN) > \
               lamp_brightness(nur_display, self.LAMPEN)


class TestVorherBild:
    def test_fertiger_ausschnitt_wird_kodiert(self):
        from kegel_cv.analysis.board_image import encode_crop

        text = encode_crop(bild(60, 50), quality=40)
        assert text is not None
        roh = base64.b64decode(text)
        assert roh[:2] == b"\xff\xd8"

    def test_leerer_ausschnitt_ergibt_nichts(self):
        from kegel_cv.analysis.board_image import encode_crop

        assert encode_crop(None) is None
        assert encode_crop(np.empty((0, 0, 3), dtype=np.uint8)) is None

    def test_beide_bilder_gehen_in_die_zeile(self):
        wurf = ThrowResult(
            lane=2, throw_number=1, throw_number_in_series=1,
            pins=(1,), pins_count=1, displayed_pin_count=1,
            status=ThrowStatus.VALID, running_total=1,
            board_image="NACHHER", board_image_before="VORHER",
        )
        # Das Vorher-Bild geht nur mit, wenn es ausdruecklich verlangt wird --
        # es ist vorerst abgeschaltet, weil sein Zeitpunkt nicht stimmt.
        zeile = throw_to_row(wurf, mit_vorher=True)
        assert zeile["board_jpeg"] == "NACHHER"
        assert zeile["board_before_jpeg"] == "VORHER"

    def test_vorher_bild_laesst_sich_abschalten(self):
        """Es soll sich einzeln abstellen lassen, ohne das Ergebnisbild."""
        wurf = ThrowResult(
            lane=2, throw_number=1, throw_number_in_series=1,
            pins=(1,), pins_count=1, displayed_pin_count=1,
            status=ThrowStatus.VALID, running_total=1,
            board_image="NACHHER", board_image_before="VORHER",
        )
        zeile = throw_to_row(wurf, mit_vorher=False)
        assert zeile["board_jpeg"] == "NACHHER", "das Ergebnisbild bleibt"
        assert "board_before_jpeg" not in zeile

    def test_ohne_vorher_bild_keine_spalte(self):
        wurf = ThrowResult(
            lane=2, throw_number=1, throw_number_in_series=1,
            pins=(1,), pins_count=1, displayed_pin_count=1,
            status=ThrowStatus.VALID, running_total=1,
            board_image="NACHHER",
        )
        assert "board_before_jpeg" not in throw_to_row(wurf)
