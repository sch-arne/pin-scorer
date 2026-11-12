"""Je Bahn ein Blatt: Wuerfe in den Zeilen, Laeufe in den Spalten.

Vom Nutzer fuer den Spieltag gewuenscht (2026-08-28). Ein LAUF ist der
Abschnitt zwischen zwei Ruecksetzungen der Anlage -- sie zeigt dabei
`000  0000` und beginnt neu bei Wurf 1.

Der wichtigste Test ist der mit 35 Wuerfen. Der Nutzer hat ausdruecklich
darauf hingewiesen: "es koennte ja sein, dass jemand bis 35 Wurf trainiert,
dann soll der Zyklus nicht bei 30 enden, sondern erst wenn wieder annulliert
wird."
"""

from __future__ import annotations

import csv

from kegel_cv.debug.cycle_sheet import CycleSheet
from kegel_cv.models.throw import Evidence, ThrowResult, ThrowStatus


def wurf(lane: int, lauf: int, nummer: int, kegel: int) -> ThrowResult:
    return ThrowResult(
        lane=lane, throw_number=nummer, throw_number_in_series=nummer,
        cycle_number=1, game_number=lauf,
        pins=tuple(range(1, kegel + 1)), pins_count=kegel,
        displayed_pin_count=kegel, status=ThrowStatus.VALID,
        running_total=0, series_total=None, confidence=1.0,
        timestamp=float(nummer), source_frame=nummer * 100,
        evidence=Evidence(frames=(), checks=(), decisions=(), raw={}),
    )


def lesen(pfad):
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        return list(csv.reader(datei, delimiter=";"))


class TestZyklusblatt:
    def test_wuerfe_in_zeilen_laeufe_in_spalten(self, tmp_path):
        blatt = CycleSheet(tmp_path)
        for lauf, kegel in ((1, 9), (2, 7), (3, 5)):
            for nummer in range(1, 4):
                blatt.add(wurf(2, lauf, nummer, kegel))
        blatt.close()

        zeilen = lesen(tmp_path / "bahn2_laeufe.csv")
        assert zeilen[0] == ["Wurf", "Lauf 1", "Lauf 2", "Lauf 3"]
        assert zeilen[1] == ["1", "9", "7", "5"]
        assert zeilen[3] == ["3", "9", "7", "5"]

    def test_ein_lauf_mit_35_wuerfen_wird_nicht_bei_30_abgeschnitten(self, tmp_path):
        """Der Kern des Nutzerhinweises: Ein Lauf endet erst, wenn die Anlage
        zuruecksetzt -- nicht nach einer erwarteten Zahl von Wuerfen."""
        blatt = CycleSheet(tmp_path)
        for nummer in range(1, 36):
            blatt.add(wurf(3, 1, nummer, 6))
        blatt.close()

        zeilen = lesen(tmp_path / "bahn3_laeufe.csv")
        # Kopf + 35 Wuerfe + Summe + Anzahl
        assert zeilen[35] == ["35", "6"], "Wurf 35 muss in der Tabelle stehen"
        assert zeilen[36] == ["Summe", str(35 * 6)]
        assert zeilen[37] == ["Wuerfe", "35"]

    def test_unterschiedlich_lange_laeufe(self, tmp_path):
        """Die Zeilenzahl richtet sich nach dem LAENGSTEN Lauf; kuerzere
        bleiben in den fehlenden Zeilen leer."""
        blatt = CycleSheet(tmp_path)
        for nummer in range(1, 31):
            blatt.add(wurf(4, 1, nummer, 5))
        for nummer in range(1, 34):
            blatt.add(wurf(4, 2, nummer, 8))
        blatt.close()

        zeilen = lesen(tmp_path / "bahn4_laeufe.csv")
        assert zeilen[33] == ["33", "", "8"], "Lauf 1 endete bei 30, Lauf 2 nicht"
        assert zeilen[34] == ["Summe", str(30 * 5), str(33 * 8)]

    def test_je_bahn_eine_datei(self, tmp_path):
        blatt = CycleSheet(tmp_path)
        for bahn in (2, 3, 5):
            blatt.add(wurf(bahn, 1, 1, 9))
        geschrieben = blatt.close()

        assert len(geschrieben) == 3
        assert {p.name for p in geschrieben} == {
            "bahn2_laeufe.csv", "bahn3_laeufe.csv", "bahn5_laeufe.csv"}

    def test_ohne_wuerfe_keine_datei(self, tmp_path):
        assert CycleSheet(tmp_path).close() == []
        assert list(tmp_path.glob("*.csv")) == []

    def test_abschaltbar(self, tmp_path):
        blatt = CycleSheet(tmp_path, aktiv=False)
        blatt.add(wurf(2, 1, 1, 9))

        assert blatt.close() == []
