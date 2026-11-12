"""Der Schiedsrichter im Vergleich Lampen/Ziffer darf nicht raten.

Das Werkzeug `tools/vergleiche_lampen_ziffern.py` entscheidet Widersprueche
zwischen Kegelkranz und Kegelziffer ueber den Zuwachs der Summenanzeige. Genau
darin liegt sein Wert -- und genau dort kann es still danebenliegen: Ein
Zuwachs ueber eine Spielgrenze oder ueber eine Luecke hinweg gehoert zu ZWEI
Wuerfen und wuerde beide Zeugen zu Unrecht widerlegen.
"""

from __future__ import annotations

from tools.vergleiche_lampen_ziffern import Wurf, summenzeuge


def wurf(frame: int, bahn: int = 2, lampen: int | None = 5,
         ziffer: int | None = 5, nummer: int | None = 1,
         spiel: int | None = 1, summe: int | None = 0) -> Wurf:
    return Wurf(zeit="0:00", frame=frame, bahn=bahn, lampen=lampen,
                ziffer=ziffer, nummer=nummer, spiel=spiel, summe=summe,
                status="VALID", pruefungen="")


class TestSummenzeuge:
    def test_zuwachs_nennt_die_kegel_des_vorigen_wurfs(self):
        """Die Tafel haengt einen Wurf zurueck (BUG-010) -- also gilt
        SummeTafel(N+1) - SummeTafel(N) fuer Wurf N."""
        wuerfe = [wurf(100, nummer=1, summe=0),
                  wurf(200, nummer=2, summe=7),
                  wurf(300, nummer=3, summe=13)]
        assert summenzeuge(wuerfe) == {100: 7, 200: 6}

    def test_spielgrenze_wird_nicht_ueberbrueckt(self):
        """Ueber einen Spielwechsel faellt die Summe zurueck auf 0 -- der
        'Zuwachs' waere dann negativ oder sinnlos."""
        wuerfe = [wurf(100, nummer=1, spiel=1, summe=120),
                  wurf(200, nummer=2, spiel=2, summe=0)]
        assert summenzeuge(wuerfe) == {}

    def test_luecke_in_der_wurfnummer_schweigt(self):
        """Fehlt ein Wurf dazwischen, zaehlt der Zuwachs zwei Wuerfe
        zusammen -- er darf dann keinem von beiden zugeschrieben werden."""
        wuerfe = [wurf(100, nummer=1, summe=0),
                  wurf(200, nummer=3, summe=15)]
        assert summenzeuge(wuerfe) == {}

    def test_unlesbare_summe_schweigt(self):
        wuerfe = [wurf(100, nummer=1, summe=None),
                  wurf(200, nummer=2, summe=7),
                  wurf(300, nummer=3, summe=None)]
        assert summenzeuge(wuerfe) == {}

    def test_unmoeglicher_zuwachs_zaehlt_nicht_als_aussage(self):
        """Mehr als neun Kegel legt kein Wurf. Ein solcher Sprung ist ein
        Lesefehler der Summe und darf keinen Zeugen abgeben."""
        wuerfe = [wurf(100, nummer=1, summe=0),
                  wurf(200, nummer=2, summe=70)]
        assert summenzeuge(wuerfe) == {}

    def test_bahnen_bleiben_getrennt(self):
        """P3: Die Bahnen sind unabhaengig -- eine Summe der einen darf nie
        gegen einen Wurf der anderen gerechnet werden."""
        wuerfe = [wurf(100, bahn=2, nummer=1, summe=0),
                  wurf(150, bahn=3, nummer=2, summe=90)]
        assert summenzeuge(wuerfe) == {}


class TestEinigkeit:
    def test_stumme_ziffer_ist_kein_widerspruch(self):
        """Eine nicht gelesene Ziffer ist Schweigen, nicht Null."""
        assert wurf(1, lampen=5, ziffer=None).einig is None

    def test_null_kegel_und_null_ziffer_sind_einig(self):
        """Der Fehlwurf ist ein gueltiges Ergebnis -- 0 == 0."""
        assert wurf(1, lampen=0, ziffer=0).einig is True

    def test_abweichung_wird_erkannt(self):
        assert wurf(1, lampen=9, ziffer=2).einig is False
