"""Der Ereignisstrom fuer die App `pin-scorer`.

WOFUER -- Auftrag des Nutzers am 2026-09-09, Punkt 5:

    "Wir muessen aus einem anderen GitHub Projekt eine TestSupabase crawlen,
     um zu versuchen, dort unsere erkannten Wuerfe zu hinterlegen."

Das Projekt ist `sch-arne/pin-scorer`. Dessen `docs/wurferkennung-plan.md`
legt den Kontrakt fest und verlangt vor der ersten Zeile Code eine echte
Aufzeichnung als Fixture.

DER FALLSTRICK, den diese Tests bewachen: Deren `bildVor`/`bildNach` sind die
STEHENDEN Kegel. Wir messen die GEFALLENEN -- die Lampen der Anlage leuchten,
wenn ein Kegel liegt. Wer das verwechselt, liefert konsequent das Gegenteil,
und es faellt erst auf, wenn eine 9 als Fehlwurf ankommt.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from tools.export_erkennungs_fixture import (ALLE_KEGEL, baue_ereignisse,
                                             braucht_neues_bild, ist_vollen)

BEGINN = datetime(2026, 9, 8, 20, 12, 22)


def zeile(bahn: int, wurfnummer: int, gefallen: str, t: float = 0.0,
          confidence: str = "1.0") -> dict:
    return {"Bahn": str(bahn), "Wurfnummer": str(wurfnummer),
            "Kegelnummern": gefallen, "Zeitstempel_s": str(t),
            "Confidence": confidence}


def baue(zeilen: list[dict]) -> list[dict]:
    ereignisse, _ = baue_ereignisse(zeilen, "Testhalle", BEGINN, "lauf_test")
    return ereignisse


class TestPhase:
    """Volle sind die Wuerfe 1-15 eines Spiels, Abraeumen 16-30."""

    @pytest.mark.parametrize("nummer", [1, 8, 15, 31, 45])
    def test_volle(self, nummer):
        assert ist_vollen(nummer)

    @pytest.mark.parametrize("nummer", [16, 22, 30, 46, 60])
    def test_abraeumen(self, nummer):
        assert not ist_vollen(nummer)


class TestNeuAufstellen:
    """Regel des Nutzers (2026-09-07): neu, wenn nichts mehr steht oder nur
    noch der Koenig."""

    def test_leeres_bild(self):
        assert braucht_neues_bild([])

    def test_nur_der_koenig(self):
        assert braucht_neues_bild([5])

    def test_ein_anderer_einzelner_kegel_nicht(self):
        assert not braucht_neues_bild([7])

    def test_zwei_kegel_nicht(self):
        assert not braucht_neues_bild([5, 7])


class TestStehendStattGefallen:
    """Der Kern der Umrechnung -- und der teuerste denkbare Fehler."""

    def test_neun_gefallene_ergeben_ein_leeres_bild(self):
        e = baue([zeile(3, 1, "1 2 3 4 5 6 7 8 9")])[0]
        assert e["bildVor"] == ALLE_KEGEL
        assert e["bildNach"] == []

    def test_ein_fehlwurf_laesst_das_bild_unveraendert(self):
        """Deren Anforderung 1: Fehlwuerfe MUESSEN kommen, sonst stimmt die
        Wurfzahl im Teilsatz nicht."""
        e = baue([zeile(3, 1, "")])[0]
        assert e["bildVor"] == e["bildNach"] == ALLE_KEGEL

    def test_das_beispiel_aus_deren_plan(self):
        """Im Plan steht `bildNach: [5, 7]` -- gefallen waeren 1,2,3,4,6,8,9."""
        e = baue([zeile(3, 1, "1 2 3 4 6 8 9")])[0]
        assert e["bildNach"] == [5, 7]


class TestVolleUndAbraeumen:
    def test_bei_vollen_steht_vor_jedem_wurf_das_volle_bild(self):
        ereignisse = baue([zeile(2, 1, "1 2 3", t=1),
                           zeile(2, 2, "4 5", t=2)])
        assert all(e["bildVor"] == ALLE_KEGEL for e in ereignisse)

    def test_beim_abraeumen_traegt_das_bild_weiter(self):
        ereignisse = baue([zeile(2, 16, "1 2 3", t=1),
                           zeile(2, 17, "4", t=2)])
        assert ereignisse[0]["bildNach"] == [4, 5, 6, 7, 8, 9]
        assert ereignisse[1]["bildVor"] == [4, 5, 6, 7, 8, 9]
        assert ereignisse[1]["bildNach"] == [5, 6, 7, 8, 9]

    def test_leergeraeumt_erzeugt_ein_aufstellungsereignis(self):
        """Deren Anforderung 4: ein EIGENES Ereignis, nicht ein Wurf mit neun
        stehenden Kegeln."""
        ereignisse = baue([zeile(2, 16, "1 2 3 4 5 6 7 8 9", t=1),
                           zeile(2, 17, "1", t=2)])
        arten = [e["art"] for e in ereignisse]
        assert arten == ["wurf", "aufstellung", "wurf"]
        assert ereignisse[1]["bildNach"] == ALLE_KEGEL


class TestBahnenSindUnabhaengig:
    def test_zwei_bahnen_teilen_kein_bild(self):
        """P6 -- der Klassiker unter den Fehlern."""
        ereignisse = baue([zeile(2, 16, "1 2 3", t=1),
                           zeile(3, 16, "7", t=2)])
        assert ereignisse[0]["bildNach"] == [4, 5, 6, 7, 8, 9]
        assert ereignisse[1]["bildNach"] == [1, 2, 3, 4, 5, 6, 8, 9]


class TestIdempotenz:
    """Deren Anforderung 5: `eventId` traegt die Idempotenz."""

    def test_derselbe_wurf_ergibt_dieselbe_id(self):
        a = baue([zeile(2, 1, "1 2", t=12.5)])[0]
        b = baue([zeile(2, 1, "1 2", t=12.5)])[0]
        assert a["eventId"] == b["eventId"]

    def test_verschiedene_wuerfe_verschiedene_ids(self):
        ereignisse = baue([zeile(2, 1, "1 2", t=12.5),
                           zeile(2, 2, "1 2", t=20.0)])
        assert ereignisse[0]["eventId"] != ereignisse[1]["eventId"]

    def test_seq_steigt_lueckenlos(self):
        ereignisse = baue([zeile(2, i, "1", t=i) for i in range(1, 6)])
        assert [e["seq"] for e in ereignisse] == [1, 2, 3, 4, 5]


class TestWiderspruchWirdNichtVersteckt:
    """Bei widerspruechlichen Quellen keine wegentscheiden -- deren
    Drift-Erkennung lebt davon, dass `bildVor` ehrlich mitkommt."""

    def test_ein_unmoeglicher_kegel_wird_vermerkt(self):
        ereignisse = baue([zeile(2, 16, "1 2 3", t=1),
                           zeile(2, 17, "1", t=2)])
        assert "hinweis" in ereignisse[1]
        assert "1" in ereignisse[1]["hinweis"]

    def test_der_wurf_kommt_trotzdem(self):
        ereignisse = baue([zeile(2, 16, "1 2 3", t=1),
                           zeile(2, 17, "1", t=2)])
        assert ereignisse[1]["art"] == "wurf"

    def test_ohne_widerspruch_kein_hinweis(self):
        e = baue([zeile(2, 1, "1 2")])[0]
        assert "hinweis" not in e


class TestUnbrauchbareZeilen:
    def test_zeilen_ohne_bahn_werden_gezaehlt_nicht_geraten(self):
        _, uebersprungen = baue_ereignisse(
            [{"Bahn": "", "Wurfnummer": "1"}, zeile(2, 1, "1")],
            "Testhalle", BEGINN, "lauf_test")
        assert uebersprungen == 1
