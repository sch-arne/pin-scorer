"""Die Wurftabelle des Spieltags und die Lampe-8-Korrektur.

WARUM ES DIESEN TEST GIBT. Am 2026-09-24 hat der Nutzer nach dem 2. Spieltag
gemeldet: *„Ebenfalls auf Bahn 5 wird die Lampe 8 manchmal irrtuemlich AUS
gelesen, obwohl sie an ist."* Gemessen an den rohen Pixeln stimmt das: Die
Lampe erreicht 207, wo ihre Nachbarn 226 bis 250 erreichen, weil ihre ROI rund
zwei Pixel zu tief sitzt. Ihre AN-Schwelle liegt bei 210.

Die Korrektur dafuer hat ZWEI Durchgaenge -- erst die Kegelziffer, dann die
Tafelsumme -- und genau daran ist sie schon einmal zerbrochen: Tabellenbau und
Pruefwerkzeug hatten den Ablauf getrennt nachgebaut und kamen auf 39 gegen 38
Korrekturen. Seitdem liegt er in `korrigiere_spiel`, und dieser Test haelt ihn
dort fest.

Das Gefaehrliche an einer solchen Korrektur ist nicht, dass sie zu wenig tut,
sondern dass sie zu viel tut. Die meisten Tests hier pruefen deshalb, dass sie
die Finger von etwas laesst.
"""

from __future__ import annotations

import csv
import subprocess
import sys

import pytest

sys.path.insert(0, "tools")

from spieltag_tabelle import (SPALTEN, korrigiere,        # noqa: E402
                              korrigiere_spiel, summenzeugen)

VOLLE_OHNE_8 = "1 2 3 4 5 6 7 9"
ALLE = "1 2 3 4 5 6 7 8 9"


def wurf(nr: int, kegel: int, bild: str = "", ziffer: str = "",
         summe: str = "", bahn: str = "5", **rest) -> dict:
    """Eine Zeile, wie sie in `wuerfe.csv` steht."""
    zeile = {
        "Bahn": bahn, "Spiel": "3", "Wurfnummer": str(nr),
        "Frame": str(1000 + nr), "Zeit": "1:00", "Kegel": str(kegel),
        "Kegelnummern": bild, "Ziffer": ziffer, "SummeTafel": summe,
        "Raeumen": "", "Grundlinie": "0", "Herkunft": "gruenzyklus",
    }
    zeile.update(rest)
    return zeile


class TestKegelzifferAlsSchiedsrichter:
    def test_ziffer_eins_hoeher_ergaenzt_den_kegel_8(self):
        neu, grund, zeuge = korrigiere(wurf(1, 8, VOLLE_OHNE_8, ziffer="9"))
        assert neu == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert grund == "Kegel 8 ergaenzt" and zeuge == "Kegelziffer"

    def test_ziffer_eins_niedriger_nimmt_ihn_weg(self):
        """Der Raeumfall: Die Grundlinie hat die Lampe uebersehen, der schon
        liegende Kegel gilt faelschlich als neu gefallen."""
        neu, grund, _ = korrigiere(wurf(1, 2, "6 8", ziffer="1"))
        assert neu == [6] and grund == "Kegel 8 entfernt"

    def test_andere_bahnen_bleiben_unberuehrt(self):
        """Die ROI sitzt auf Bahn 5 schief, sonst nirgends -- gemessen ueber
        alle 36 Lampen des Spieltags."""
        assert korrigiere(wurf(1, 8, VOLLE_OHNE_8, ziffer="9", bahn="4")) is None

    def test_abweichung_von_zwei_wird_nicht_angefasst(self):
        assert korrigiere(wurf(1, 7, "1 2 3 4 5 7 9", ziffer="9")) is None

    def test_kegel_8_schon_dabei_wird_nicht_verdoppelt(self):
        assert korrigiere(wurf(1, 8, "1 2 3 4 6 7 8 9", ziffer="9")) is None

    def test_ohne_zeugen_geschieht_nichts(self):
        assert korrigiere(wurf(1, 8, VOLLE_OHNE_8)) is None


class TestTafelsummeAlsErsatzzeuge:
    def test_springt_ein_wenn_die_ziffer_schweigt(self):
        neu, _, zeuge = korrigiere(wurf(1, 1, "5"), soll=2)
        assert neu == [5, 8] and zeuge == "Tafelsumme"

    def test_die_ziffer_hat_vorrang(self):
        """Sonst entschiede mal die eine, mal die andere Quelle -- und welche,
        haenge davon ab, ob die Nachbarzeile lesbar war."""
        assert korrigiere(wurf(1, 8, VOLLE_OHNE_8, ziffer="8"), soll=9) is None


class TestWelcherWurfDieSummeErbt:
    def test_genau_ein_wurf_zwischen_zwei_staenden(self):
        w = [wurf(1, 6, summe="10"), wurf(2, 3, summe="16")]
        assert summenzeugen(w) == {1: 6}

    def test_eine_fehlende_wurfnummer_macht_die_spanne_unbrauchbar(self):
        """Dort steckt ein verlorener Wurf drin, der die Differenz miterklaert
        -- gemessen auf Bahn 5, Lauf 1.4, Wurf 19."""
        w = [wurf(18, 8, summe="133"), wurf(20, 9, summe="142")]
        assert summenzeugen(w) == {}

    def test_spanne_mit_einem_offenen_wurf_wird_aufgeloest(self):
        """Der bestaetigte Nachbar wird abgezogen, der Rest gehoert dem offenen
        Wurf -- so kam Lauf 3.4 Wurf 20 zu seinem Zeugen."""
        w = [wurf(20, 1, "5", summe="140"),
             wurf(21, 9, ALLE, ziffer="9"),
             wurf(22, 7, summe="151")]
        assert summenzeugen(w, {20: 1, 21: 9})[20] == 2

    def test_zwei_offene_wuerfe_bleiben_offen(self):
        w = [wurf(20, 1, "5", summe="140"),
             wurf(21, 9, ALLE),
             wurf(22, 7, summe="151")]
        assert summenzeugen(w, {20: 1, 21: 9}) == {}

    def test_unplausible_differenz_wird_verworfen(self):
        """Ein verlesener Summenstand darf keine Korrektur ausloesen."""
        w = [wurf(1, 6, summe="100"), wurf(2, 3, summe="40")]
        assert summenzeugen(w) == {}


class TestBeideDurchgaengeZusammen:
    def test_die_ziffernkorrektur_speist_die_summenzuordnung(self):
        """Wurf 21 wird ueber seine Ziffer auf 9 korrigiert; erst mit diesem
        Wert bleibt fuer Wurf 20 die richtige Differenz uebrig."""
        w = [wurf(20, 1, "5", summe="140"),
             wurf(21, 8, VOLLE_OHNE_8, ziffer="9"),
             wurf(22, 7, summe="151")]
        fixes = korrigiere_spiel(w)
        assert fixes[21][0] == [1, 2, 3, 4, 5, 6, 7, 8, 9]
        assert fixes[20] == ([5, 8], "Kegel 8 ergaenzt", "Tafelsumme")


class TestDieDatei:
    """Was am Ende geliefert wird, muss ein Tabellenprogramm lesen koennen."""

    @pytest.fixture(scope="class")
    @classmethod
    def gebaut(cls, tmp_path_factory):
        lauf = tmp_path_factory.mktemp("lauf")
        felder = ["Zeit", "Frame", "Bahn", "Kegel", "Kegelnummern", "Wurfnummer",
                  "Spiel", "Zyklus", "WurfImZyklus", "LaufendeSumme",
                  "Zwischensumme", "Status", "Confidence", "Ziffer",
                  "WurfnummerRoh", "NummerEinigkeit", "SummeTafel",
                  "FehlwurfTafel", "Raeumen", "Grundlinie", "Herkunft",
                  "Zeitstempel_s", "Pruefungen"]
        zeilen = []
        for spiel in (1, 2):
            for nr in range(1, 31):
                if spiel == 2 and nr == 7:
                    continue                    # eine Luecke, wie im Ernstfall
                eintrag = dict.fromkeys(felder, "")
                eintrag.update({
                    "Bahn": "5", "Spiel": str(spiel), "Wurfnummer": str(nr),
                    "Kegel": "9", "Kegelnummern": ALLE, "Ziffer": "9",
                    "Frame": str(nr * 10), "Herkunft": "gruenzyklus",
                    "Grundlinie": "0",
                })
                zeilen.append(eintrag)
        with (lauf / "wuerfe.csv").open("w", encoding="utf-8-sig", newline="") as f:
            schreiber = csv.DictWriter(f, fieldnames=felder, delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(zeilen)
        ziel = lauf / "aus"
        subprocess.run([sys.executable, "tools/spieltag_tabelle.py",
                        "--lauf", str(lauf), "--ziel", str(ziel)],
                       check=True, capture_output=True)
        return ziel / "bahn_5.csv"

    def test_kopfzeile_ist_die_bestellte(self, gebaut):
        kopf = gebaut.read_text(encoding="utf-8-sig").splitlines()[0]
        erwartet = ["Wurfnummer"]
        for name in SPALTEN:
            erwartet += [name, f"{name} Wurfbild"]
        assert kopf.split(";") == erwartet

    def test_bom_damit_excel_die_umlaute_trifft(self, gebaut):
        assert gebaut.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_dreissig_zeilen_und_gleiche_breite(self, gebaut):
        with gebaut.open(encoding="utf-8-sig", newline="") as f:
            zeilen = [z for z in csv.reader(f, delimiter=";") if z]
        assert len(zeilen) == 31
        assert {len(z) for z in zeilen} == {33}
        assert [z[0] for z in zeilen[1:]] == [str(n) for n in range(1, 31)]

    def test_ein_fehlender_wurf_bleibt_leer_und_wird_nicht_geraten(self, gebaut):
        with gebaut.open(encoding="utf-8-sig", newline="") as f:
            zeilen = list(csv.reader(f, delimiter=";"))
        spalte = zeilen[0].index("Warmwerfen 2")
        assert zeilen[7][spalte:spalte + 2] == ["", ""], \
            "Wurf 7 des zweiten Spiels fehlt in der Quelle"
        assert zeilen[6][spalte] == "9"
