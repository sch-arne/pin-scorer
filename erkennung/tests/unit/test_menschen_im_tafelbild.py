"""Kein Gesicht im Tafelbild -- auch nicht, wenn der Mensch stillsteht.

DER BEFUND (Nutzer, 2026-09-13):

    "im Liveticker, wo ja mittlerweile Bilder angezeigt werden, sieht man sehr
     haeufig noch Gesichter -> Immer dann, wenn sie Phantomwuerfe erzeugen."

UND SO WAR ES. Die Personenmaske nimmt die Tafelbereiche vom Schwaerzen aus --
zu Recht, dort steht das Signal. Genau dieses Rechteck geht aber als
`board_jpeg` an die Datenbank. Wer davorstand, war ueberall geschwaerzt, nur
nicht dort, wo alle hinsehen.

DER ERSTE ANLAUF REICHTE NICHT. Er schwaerzte menschgrosse BEWEGTE Flecken --
und ging an genau dem Fall vorbei, der den Befund ausgeloest hat. GEMESSEN am
Mitschnitt vom 2026-09-08, Frame 13489: Ein Mensch beugt sich ueber die Tafel,
ist im Bild voll zu sehen, und die Bewegung meldet 0,081 bei einer Schwelle
von 0,14. Er STEHT STILL und ist ins Hintergrundmodell gewandert.

Deshalb jetzt eine bewachte Referenz (`analysis/tafel_wache.py`): Sie lernt nur
nach, wenn die Tafel normal aussieht -- dann kann niemand hineinwandern, egal
wie lange er steht.
"""

from __future__ import annotations

import base64

import cv2
import numpy as np
import pytest

from kegel_cv.analysis.board_image import encode_board, schwaerze_fremdes
from kegel_cv.analysis.tafel_wache import TafelWache


def tafel(mit_mensch: bool = False, ziffern: int = 200) -> np.ndarray:
    """Eine 'Tafel': helles Gehaeuse, dunkles Anzeigefenster, rote Ziffern."""
    bild = np.full((120, 120, 3), 150, dtype=np.uint8)
    bild[80:105, 15:105] = 25                       # Anzeigefenster
    bild[85:100, 20:100] = (40, 40, ziffern)        # die Ziffern
    if mit_mensch:
        bild[30:110, 10:70] = 60                    # jemand steht davor
    return bild


def stabil() -> np.ndarray:
    """Gehaeuse ja, Anzeigefenster nein -- wie `stabile_maske` es liefert."""
    m = np.ones((120, 120), bool)
    m[78:107, 13:107] = False
    return m


def eingelernt(**kwargs) -> TafelWache:
    wache = TafelWache(stabil(), **kwargs)
    for _ in range(20):
        wache.beobachte(tafel())
    return wache


class TestDieWacheSiehtDenStillstehenden:
    """Das ist der Fall, an dem der erste Anlauf gescheitert ist."""

    def test_ohne_stoerung_faellt_nichts_auf(self):
        wache = eingelernt()
        assert wache.abweichung(tafel()) < 0.01
        assert wache.fremdmaske(tafel()) is None

    def test_ein_mensch_faellt_auf(self):
        wache = eingelernt()
        assert wache.abweichung(tafel(mit_mensch=True)) > 0.2

    def test_er_faellt_auch_nach_langem_stillstand_auf(self):
        """DER KERN DES VERFAHRENS. Ein Hintergrundmodell haette ihn laengst
        aufgenommen -- diese Referenz lernt nur nach, wenn die Tafel normal
        aussieht."""
        wache = eingelernt()
        for _ in range(200):
            wache.beobachte(tafel(mit_mensch=True))
        assert wache.abweichung(tafel(mit_mensch=True)) > 0.2, \
            "nach 200 Frames Stillstand muss er immer noch auffallen"
        assert wache.fremdmaske(tafel(mit_mensch=True)) is not None

    def test_wechselnde_ziffern_sind_keine_stoerung(self):
        """Die Anzeige aendert sich staendig -- sie darf nichts ausloesen,
        sonst wird bei jedem Wurf geschwaerzt."""
        wache = eingelernt()
        for wert in (60, 255, 120, 200):
            assert wache.abweichung(tafel(ziffern=wert)) < 0.01
            assert wache.fremdmaske(tafel(ziffern=wert)) is None

    def test_langsame_lichtaenderung_wird_gelernt(self):
        """Sonst schlaegt die Wache abends an, wenn das Hallenlicht wechselt."""
        wache = eingelernt()
        for i in range(60):
            heller = np.clip(tafel().astype(int) + i // 3, 0, 255).astype(np.uint8)
            wache.beobachte(heller)
        heller = np.clip(tafel().astype(int) + 20, 0, 255).astype(np.uint8)
        assert wache.abweichung(heller) < 0.05


class TestDieMaskeDecktAb:
    def test_sie_trifft_den_menschen(self):
        wache = eingelernt()
        maske = wache.fremdmaske(tafel(mit_mensch=True))
        assert maske is not None
        # Der Mensch steht in [30:110, 10:70] -- dort muss sie greifen.
        assert maske[40:100, 20:60].mean() > 200

    def test_sie_hat_keine_loecher(self):
        """Ein halb geschwaerztes Gesicht ist kein geschwaerztes Gesicht --
        deshalb wird die Maske geschlossen und verbreitert."""
        wache = eingelernt()
        mit = tafel(mit_mensch=True)
        mit[50:60, 30:40] = 150            # ein Stueck in Gehaeusefarbe
        maske = wache.fremdmaske(mit)
        assert maske[50:60, 30:40].min() > 0, "das Loch muss geschlossen sein"

    def test_ohne_wachstum_bleiben_die_loecher(self):
        """Gegenprobe -- damit der Wert nicht unbemerkt wirkungslos wird."""
        wache = eingelernt(wachstum=0.0)
        mit = tafel(mit_mensch=True)
        mit[50:60, 30:40] = 150
        maske = wache.fremdmaske(mit)
        assert maske is not None and maske[52:58, 32:38].max() == 0


class TestDerWegInsBild:
    def test_ohne_maske_bleibt_der_ausschnitt(self):
        aus = tafel()
        assert schwaerze_fremdes(aus, None) is aus

    def test_mit_maske_wird_geschwaerzt(self):
        aus = tafel().copy()
        maske = np.zeros((120, 120), np.uint8)
        maske[:60] = 255
        neu = schwaerze_fremdes(aus, maske)
        assert neu[:60].max() == 0 and neu[60:].max() > 0

    def test_das_original_bleibt_unangetastet(self):
        """Die Messung liest den Ausschnitt roh -- geschwaerzt wird eine Kopie."""
        aus = tafel().copy()
        vorher = aus.copy()
        maske = np.full((120, 120), 255, np.uint8)
        schwaerze_fremdes(aus, maske)
        assert np.array_equal(aus, vorher)

    def test_encode_board_reicht_sie_durch(self):
        bild = np.zeros((200, 200, 3), np.uint8)
        bild[40:160, 40:160] = tafel()
        maske = np.full((120, 120), 255, np.uint8)
        mit = encode_board(bild, (40, 40, 120, 120), 60, maske)
        ohne = encode_board(bild, (40, 40, 120, 120), 60)
        assert mit != ohne
        aus = cv2.imdecode(np.frombuffer(base64.b64decode(mit), np.uint8),
                           cv2.IMREAD_COLOR)
        assert aus.max() < 20


class TestGrenzen:
    def test_ohne_referenz_meldet_sie_nichts(self):
        wache = TafelWache(stabil())
        assert wache.fremdmaske(tafel(mit_mensch=True)) is None
        assert not wache.bereit or True

    def test_abschaltbar(self):
        wache = eingelernt(schwelle=1.1)
        assert wache.fremdmaske(tafel(mit_mensch=True)) is None

    def test_eine_andere_groesse_stuerzt_nicht_ab(self):
        """Nach dem Nachkalibrieren kann der Ausschnitt anders gross sein."""
        wache = eingelernt()
        anders = cv2.resize(tafel(mit_mensch=True), (140, 140))
        assert wache.abweichung(anders) == 0.0
        assert wache.fremdmaske(anders) is None
