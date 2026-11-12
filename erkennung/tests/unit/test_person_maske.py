"""Menschen schwaerzen -- und dabei die Anzeigetafel nicht zerstoeren.

WARUM ES DIESE TESTS GIBT -- Auftrag des Nutzers am 2026-09-09:

    "Wir muessen Menschen (vor allem Gesichter, aber besser Menschen)
     gaenzlich schwaerzen. Automatisiert und Live.... das hat jetzt Prio 0,
     das soll bitte passieren, bevor Gruenzyklus etc. analysiert wird.
     Gestern haben wir naemlich einen 0 Wurf erzeugt, weil ein Mensch durch
     die Gruenphase gelaufen ist."

Nachgemessen am Mitschnitt: Frame 13224, Bahn 2, 0 Kegel, Ziffer unlesbar --
und im Tafelbereich der hoechste Vordergrundanteil des ganzen Laufs (0,197).

DIE GEFAEHRLICHSTE STELLE ist nicht das Schwaerzen, sondern das, was NICHT
geschwaerzt werden darf: Ziffern und Lampen aendern sich staendig und sind
damit selbst bewegter Vordergrund. Wer sie schwaerzt, loescht genau das
Signal, das gelesen werden soll -- und merkt es erst, wenn die Analyse
schweigt.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.detection.person_maske import PersonMaske

HOEHE, BREITE = 360, 640
TAFEL = (400, 20, 120, 120)          # x, y, w, h -- oben rechts


def hintergrund() -> np.ndarray:
    """Eine ruhige, gleichmaessige Szene."""
    return np.full((HOEHE, BREITE, 3), 120, dtype=np.uint8)


def mit_person(bild: np.ndarray, x: int = 60, y: int = 150,
               w: int = 90, h: int = 160) -> np.ndarray:
    b = bild.copy()
    b[y:y + h, x:x + w] = 240
    return b


def maske(**kw) -> PersonMaske:
    m = PersonMaske(history=50, scale=2, min_blob_px=200, dilate_px=5,
                    warmup_frames=0, occlusion_fraction=0.14, **kw)
    m.set_tafeln({2: TAFEL})
    return m


def einlernen(m: PersonMaske, runden: int = 40) -> None:
    """Hintergrundmodell mit einer ruhigen Szene fuellen."""
    for _ in range(runden):
        m.verarbeite(hintergrund())


class TestSchwaerzen:
    def test_eine_person_wird_geschwaerzt(self):
        m = maske()
        einlernen(m)
        e = m.verarbeite(mit_person(hintergrund()))
        ausschnitt = e.bild[150:310, 60:150]
        assert (ausschnitt == 0).mean() > 0.5, \
            "die Person muss ueberwiegend schwarz sein"

    def test_der_ruhige_hintergrund_bleibt(self):
        m = maske()
        einlernen(m)
        e = m.verarbeite(mit_person(hintergrund()))
        ruhig = e.bild[0:100, 200:380]
        assert (ruhig == 120).all(), "unbewegter Hintergrund darf nicht leiden"

    def test_ohne_bewegung_wird_nichts_geschwaerzt(self):
        m = maske()
        einlernen(m)
        e = m.verarbeite(hintergrund())
        assert e.geschwaerzte_pixel == 0

    def test_abgeschaltet_geht_das_bild_unveraendert_durch(self):
        m = PersonMaske(enabled=False)
        bild = mit_person(hintergrund())
        e = m.verarbeite(bild)
        assert e.bild is bild
        assert e.verdeckte_bahnen == frozenset()


class TestDieTafelBleibtUnangetastet:
    """Der teuerste denkbare Fehler: das Signal wegschwaerzen."""

    def test_die_tafel_wird_nie_geschwaerzt(self):
        m = maske()
        einlernen(m)
        # Eine Person GENAU ueber der Tafel
        x, y, w, h = TAFEL
        e = m.verarbeite(mit_person(hintergrund(), x, y, w, h))
        tafel = e.bild[y:y + h, x:x + w]
        assert (tafel == 0).mean() < 0.01, \
            "im Tafelbereich darf nichts geschwaerzt werden"

    def test_aber_sie_wird_als_verdeckt_gemeldet(self):
        """Nicht schwaerzen heisst nicht wegsehen -- die Bahn wird
        eingefroren."""
        m = maske()
        einlernen(m)
        x, y, w, h = TAFEL
        e = m.verarbeite(mit_person(hintergrund(), x, y, w, h))
        assert 2 in e.verdeckte_bahnen
        assert e.verdeckung[2] > 0.5

    def test_ohne_tafeln_wird_nichts_geschuetzt(self):
        """Ein vergessenes `set_tafeln` muss auffallen, nicht stillschweigend
        funktionieren."""
        m = PersonMaske(history=50, scale=2, min_blob_px=200, warmup_frames=0)
        einlernen(m)
        e = m.verarbeite(mit_person(hintergrund()))
        assert e.verdeckung == {}


class TestVerdeckungWirdSauberGemessen:
    def test_eine_person_abseits_der_tafel_verdeckt_nichts(self):
        m = maske()
        einlernen(m)
        e = m.verarbeite(mit_person(hintergrund(), x=60, y=150))
        assert e.verdeckte_bahnen == frozenset()
        assert e.verdeckung[2] < 0.05

    def test_gemessen_wird_vor_der_dilatation(self):
        """DER FEHLER, DEN DIESER TEST BEWACHT -- 2026-09-09 gebaut und
        sofort wieder ausgebaut:

        Der erste Entwurf mass NACH der Dilatation und meldete 159 von 300
        Frames als verdeckt. Ein Kern von 9 Pixeln im verkleinerten Bild sind
        rund 36 im Vollbild, und die Tafel ist nur 192 breit.

        Geprueft wird ueber den Vergleich: Eine kleine Bewegung DICHT NEBEN
        der Tafel darf sie nicht verdecken -- mit Dilatation im Messweg
        taete sie es.
        """
        m = maske()
        einlernen(m)
        x, y, w, h = TAFEL
        # direkt links neben der Tafel, 30 Pixel breit
        e = m.verarbeite(mit_person(hintergrund(), x=x - 34, y=y, w=30, h=h))
        assert e.verdeckung[2] < 0.10, (
            f"Bewegung NEBEN der Tafel darf nicht als Verdeckung zaehlen "
            f"(gemessen {e.verdeckung[2]:.3f})")


class TestKleineDingeSindKeineMenschen:
    def test_eine_kugel_wird_nicht_geschwaerzt(self):
        """Sonst schwaerzt jeder fliegende Kegel Loecher ins Bild."""
        m = maske()
        einlernen(m)
        b = hintergrund()
        b[200:208, 300:308] = 240          # 8x8 Pixel
        e = m.verarbeite(b)
        assert e.geschwaerzte_pixel == 0


class TestEinlaufen:
    def test_waehrend_des_einlaufens_gilt_nichts_als_verdeckt(self):
        """Im ersten Frame ist ALLES Vordergrund -- gemessen 1,0 auf allen
        vier Bahnen. Ohne Sperre faellt jeder Laufstart in die Bremse."""
        m = PersonMaske(history=50, scale=2, warmup_frames=10)
        m.set_tafeln({2: TAFEL})
        for _ in range(10):
            e = m.verarbeite(mit_person(hintergrund(), *TAFEL))
            assert e.verdeckte_bahnen == frozenset()

    def test_danach_greift_sie_wieder(self):
        m = PersonMaske(history=50, scale=2, min_blob_px=200, warmup_frames=5)
        m.set_tafeln({2: TAFEL})
        einlernen(m)
        x, y, w, h = TAFEL
        e = m.verarbeite(mit_person(hintergrund(), x, y, w, h))
        assert 2 in e.verdeckte_bahnen


class TestSchlechteEingaben:
    def test_ein_leeres_bild_stuerzt_nicht_ab(self):
        m = maske()
        e = m.verarbeite(np.zeros((0, 0, 3), dtype=np.uint8))
        assert e.verdeckte_bahnen == frozenset()

    def test_none_stuerzt_nicht_ab(self):
        m = maske()
        assert m.verarbeite(None).bild is None

    def test_scale_null_wird_abgelehnt(self):
        with pytest.raises(ValueError, match="scale"):
            PersonMaske(scale=0)
