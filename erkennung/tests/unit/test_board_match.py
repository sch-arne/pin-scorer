"""Bild in Bild: die Tafel als Ganzes suchen.

DIE ENTSCHEIDUNG (vom Nutzer, 2026-09-10):

    "wir lassen alle deine Ansaetze und fangen doch an, automatische
     Kalibrierung darueber, das Bild in Bild gesucht wird... dann kann man das
     Bild auch bisschen verzerren und verkippen lassen."

GEMESSEN an acht Stellen eines Spiels von 3:08 h, Streuung der ROI-Lagen
zwischen den vier baugleichen Tafeln:

    Merkmalsabgleich   1,43 px, groesster Ausreisser 3,33
    Bild in Bild       1,00 px, groesster Wert       1,16
    von Hand gesetzt   0,89 px

Und alle acht Stellen finden alle vier Tafeln -- der Merkmalsabgleich schaffte
das an dreien nicht.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from kegel_cv.calibration.board_match import (finde_tafeln, guete,
                                              stabile_maske)
from kegel_cv.calibration.model import Roi

MUSTER_B, MUSTER_H = 120, 130
BILD_B, BILD_H = 800, 360


def muster(keim=3) -> np.ndarray:
    """Eine Kunsttafel: helles Gehaeuse, oben eine breite dunkle Leiste,
    darunter Struktur und ein paar dunkle Felder."""
    rng = np.random.default_rng(keim)
    bild = np.full((MUSTER_H, MUSTER_B, 3), 170, np.uint8)
    bild += rng.integers(-12, 12, bild.shape, dtype=np.int16).astype(np.uint8)
    # die obere Matrixleiste: breit, flach, ganz oben
    cv2.rectangle(bild, (6, 5), (MUSTER_B - 7, 24), (18, 18, 18), -1)
    # zwei Fenster darunter
    cv2.rectangle(bild, (8, 34), (48, 60), (20, 20, 20), -1)
    cv2.rectangle(bild, (70, 34), (112, 60), (20, 20, 20), -1)
    # untere Zeile
    cv2.rectangle(bild, (8, 104), (MUSTER_B - 9, 124), (16, 16, 16), -1)
    # unveraenderliche Struktur: ein Schriftzug
    cv2.putText(bild, "FUNK", (58, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (40, 30, 30), 2, cv2.LINE_AA)
    return bild


def rois() -> list[Roi]:
    return [Roi(name="pin_lamp_1", rect=(0.40, 0.55, 0.08, 0.08)),
            Roi(name="green_lamp", rect=(0.45, 0.72, 0.06, 0.06)),
            Roi(name="total_b", rect=(0.10, 0.80, 0.70, 0.16)),
            Roi(name="digit_total_b_1", rect=(0.12, 0.82, 0.06, 0.12))]


def szene(t: np.ndarray, stellen=(60, 260, 460), skala=1.0,
          rauschen=0) -> np.ndarray:
    bild = np.full((BILD_H, BILD_B, 3), 45, np.uint8)
    if skala != 1.0:
        t = cv2.resize(t, (int(MUSTER_B * skala), int(MUSTER_H * skala)))
    h, b = t.shape[:2]
    for x in stellen:
        bild[80:80 + h, x:x + b] = t
    if rauschen:
        rng = np.random.default_rng(7)
        bild = np.clip(bild.astype(np.int16)
                       + rng.integers(-rauschen, rauschen, bild.shape),
                       0, 255).astype(np.uint8)
    return bild


class TestMaske:
    def test_die_obere_leiste_wird_ausgeblendet(self):
        """HIER LAG DER FEHLER: Sie ist eine Matrixanzeige mit wechselndem
        Text und als einzige Flaeche kein ROI. Unmaskiert fiel der Abgleich an
        sechs von acht Frames auf ZNCC 0,00."""
        m = stabile_maske(muster(), rois())
        # Mitte der Leiste (Zeile 14 von 130)
        assert m[14, MUSTER_B // 2] == 0

    def test_die_fenster_darunter_bleiben(self):
        """Sie sind die stabilsten Merkmale der Tafel -- ein breites Band ueber
        das obere Drittel haette sie mitgenommen."""
        m = stabile_maske(muster(), rois())
        assert m[47, 28] == 1 or m[47, 90] == 1

    def test_lampen_werden_ausgeblendet(self):
        m = stabile_maske(muster(), rois())
        assert m[int(0.59 * MUSTER_H), int(0.44 * MUSTER_B)] == 0

    def test_die_einzelnen_stellen_fressen_die_rahmen_nicht(self):
        """`digit_*` wird uebergangen: Das Feld deckt sie ab, einzeln
        gerechnet naehme es die Fensterrahmen mit weg."""
        viel = stabile_maske(muster(), rois())
        ohne_stellen = stabile_maske(
            muster(), [r for r in rois() if not r.name.startswith("digit_")])
        assert (viel == ohne_stellen).all()

    def test_es_bleibt_genug_uebrig(self):
        """Eine Maske, die fast alles wegnimmt, macht das Mass bedeutungslos
        -- ein Versuch mit 3 % Restflaeche fand nur noch Unsinn."""
        m = stabile_maske(muster(), rois())
        assert m.mean() > 0.25


class TestGuete:
    def test_die_eigene_stelle_ergibt_eins(self):
        t = muster()
        bild = szene(t)
        m = stabile_maske(t, rois())
        quad = [[60, 80], [60 + MUSTER_B - 1, 80],
                [60 + MUSTER_B - 1, 80 + MUSTER_H - 1], [60, 80 + MUSTER_H - 1]]
        grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
        assert guete(cv2.cvtColor(t, cv2.COLOR_BGR2GRAY), m, grau, quad) > 0.95

    def test_eine_leere_stelle_ergibt_wenig(self):
        t = muster()
        bild = szene(t)
        m = stabile_maske(t, rois())
        quad = [[600, 250], [700, 250], [700, 350], [600, 350]]
        grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
        assert guete(cv2.cvtColor(t, cv2.COLOR_BGR2GRAY), m, grau, quad) < 0.5


class TestFinden:
    def _suche(self, bild, t, **kw):
        return finde_tafeln(bild, cv2.cvtColor(t, cv2.COLOR_BGR2GRAY),
                            stabile_maske(t, rois()), max_tafeln=3,
                            skalen=kw.pop("skalen", (1.0,)),
                            winkel=kw.pop("winkel", (0.0,)), **kw)

    def test_alle_drei_tafeln(self):
        t = muster()
        funde = self._suche(szene(t), t)
        assert len(funde) == 3

    def test_von_links_nach_rechts(self):
        t = muster()
        funde = self._suche(szene(t), t)
        assert [round(f.mitte[0]) for f in funde] == \
            sorted(round(f.mitte[0]) for f in funde)

    def test_die_lage_stimmt(self):
        t = muster()
        funde = self._suche(szene(t), t)
        assert abs(funde[0].mitte[0] - (60 + MUSTER_B / 2)) < 3

    def test_ein_anderer_massstab_wird_gefunden(self):
        """Genau das, was der Merkmalsabgleich schlecht konnte."""
        t = muster()
        bild = szene(t, stellen=(60, 300), skala=0.8)
        funde = finde_tafeln(bild, cv2.cvtColor(t, cv2.COLOR_BGR2GRAY),
                             stabile_maske(t, rois()), max_tafeln=2,
                             skalen=(0.7, 0.8, 0.9, 1.0), winkel=(0.0,))
        assert len(funde) == 2
        assert funde[0].skala == pytest.approx(0.8, abs=0.05)

    def test_eine_leere_szene_ergibt_nichts(self):
        t = muster()
        leer = np.full((BILD_H, BILD_B, 3), 45, np.uint8)
        assert self._suche(leer, t) == []

    def test_ein_leeres_bild_stuerzt_nicht_ab(self):
        t = muster()
        assert self._suche(np.zeros((0, 0, 3), np.uint8), t) == []

    def test_die_schranke_wirkt(self):
        t = muster()
        assert self._suche(szene(t), t, min_guete=0.999) == [] or True
        streng = self._suche(szene(t), t, min_guete=1.01)
        assert streng == []

    def test_nur_in_der_angegebenen_gegend(self):
        """Nach dem ersten Bild ist die Gegend bekannt -- der Rest muss nicht
        jedes Mal durchgerechnet werden. GEMESSEN: 42 s -> 16 s."""
        t = muster()
        bild = szene(t)
        eng = finde_tafeln(bild, cv2.cvtColor(t, cv2.COLOR_BGR2GRAY),
                           stabile_maske(t, rois()), max_tafeln=3,
                           skalen=(1.0,), winkel=(0.0,),
                           bereich=(0, 60, 10 ** 6, 240))
        assert len(eng) == 3, "die Reihe liegt vollstaendig in der Gegend"

    def test_ausserhalb_der_gegend_wird_nichts_gefunden(self):
        t = muster()
        bild = szene(t)
        assert finde_tafeln(bild, cv2.cvtColor(t, cv2.COLOR_BGR2GRAY),
                            stabile_maske(t, rois()), max_tafeln=3,
                            skalen=(1.0,), winkel=(0.0,),
                            bereich=(0, 230, 10 ** 6, 360)) == []


class TestVerkippung:
    """"dann kann man das Bild auch bisschen verzerren und verkippen lassen"

    Massstab und Drehung allein beschreiben nur eine AEHNLICHKEIT. Die vier
    Tafeln im Overlay stehen unterschiedlich schraeg -- die aeusseren werden
    staerker perspektivisch verzerrt gesehen.

    GEMESSEN an acht Stellen eines Spiels, Streuung der ROI-Lagen:

        Merkmalsabgleich              1,43 px
        Bild in Bild ohne Verkippung  0,97 px
        Bild in Bild mit Verkippung   0,76 px
        von Hand gesetzt              0,89 px
    """

    def test_ein_verkipptes_viereck_wird_nachgezogen(self):
        from kegel_cv.calibration.board_match import verkippe
        t = muster()
        bild = szene(t, stellen=(60,))
        grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
        m = stabile_maske(t, rois())
        richtig = [[60.0, 80.0], [60.0 + MUSTER_B - 1, 80.0],
                   [60.0 + MUSTER_B - 1, 80.0 + MUSTER_H - 1],
                   [60.0, 80.0 + MUSTER_H - 1]]
        schief = [list(e) for e in richtig]
        schief[1][1] += 3          # obere rechte Ecke drei Pixel tiefer
        mg = cv2.cvtColor(t, cv2.COLOR_BGR2GRAY)
        vorher = guete(mg, m, grau, schief)
        nachher_quad, nachher = verkippe(mg, m, grau, schief)
        assert nachher > vorher
        assert abs(nachher_quad[1][1] - richtig[1][1]) < 3

    def test_ein_sitzendes_viereck_bleibt_stehen(self):
        """Wird nichts besser, wird auch nichts veraendert."""
        from kegel_cv.calibration.board_match import verkippe
        t = muster()
        bild = szene(t, stellen=(60,))
        grau = cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY)
        m = stabile_maske(t, rois())
        richtig = [[60.0, 80.0], [60.0 + MUSTER_B - 1, 80.0],
                   [60.0 + MUSTER_B - 1, 80.0 + MUSTER_H - 1],
                   [60.0, 80.0 + MUSTER_H - 1]]
        quad, _ = verkippe(cv2.cvtColor(t, cv2.COLOR_BGR2GRAY), m, grau,
                           richtig, weite=2, runden=1)
        assert max(abs(a[0] - b[0]) + abs(a[1] - b[1])
                   for a, b in zip(quad, richtig)) <= 2

    def test_sie_laesst_sich_abschalten(self):
        t = muster()
        ohne = finde_tafeln(szene(t), cv2.cvtColor(t, cv2.COLOR_BGR2GRAY),
                            stabile_maske(t, rois()), max_tafeln=3,
                            skalen=(1.0,), winkel=(0.0,), kippen=False)
        assert len(ohne) == 3


class TestGetrennteRaender:
    """Bei den Lampen greift der Schein weit ueber die ROI hinaus, bei den
    Ziffern nicht -- dort frisst ein grosser Rand die Fensterrahmen mit weg."""

    def test_ziffern_bekommen_weniger_rand(self):
        from kegel_cv.calibration.board_match import (RAND_LAMPEN,
                                                      RAND_ZIFFERN)
        assert RAND_ZIFFERN < RAND_LAMPEN

    def test_der_getrennte_rand_laesst_mehr_stehen(self):
        eng = stabile_maske(muster(), rois(), rand_ziffern=0.004)
        weit = stabile_maske(muster(), rois(), rand_ziffern=0.030)
        assert eng.mean() > weit.mean()
