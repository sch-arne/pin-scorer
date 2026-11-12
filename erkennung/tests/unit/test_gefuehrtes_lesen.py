"""Geführtes Lesen der Summe -- darf wählen, nicht setzen."""

from kegel_cv.analysis.gefuehrtes_lesen import (EINDEUTIG, GEFUEHRT, STUMM,
                                                UNMOEGLICH, VERANKERT,
                                                WIDERSPRUCH, Summenspur,
                                                erlaubte_ziffern,
                                                moegliche_werte,
                                                passt_zur_lesung)
from kegel_cv.detection.digit_detector import DigitReading


def lesung(text: str, kandidaten: tuple[tuple[int, ...], ...] = ()):
    """Baut eine Lesung so, wie der Ziffernleser sie liefern würde."""
    ziffern = tuple(text)
    if not kandidaten:
        kandidaten = tuple((int(z),) if z.isdigit() else () for z in ziffern)
    wert = int(text) if text.isdigit() else None
    return DigitReading(text=text, value=wert, confidence=0.9,
                        digits=ziffern, candidates=kandidaten,
                        scores=(0.9,) * len(ziffern))


class TestWasEineStelleZulaesst:
    def test_eine_sichere_ziffer_laesst_nur_sich_selbst(self):
        assert erlaubte_ziffern(lesung("0172"), 1) == (1,)

    def test_eine_fragliche_stelle_laesst_ihre_kandidaten(self):
        l = lesung("01?2", ((0,), (1,), (3, 9), (2,)))
        assert erlaubte_ziffern(l, 2) == (3, 9)

    def test_eine_stelle_ohne_jede_aussage_laesst_alles(self):
        l = lesung("01?2", ((0,), (1,), (), (2,)))
        assert erlaubte_ziffern(l, 2) == tuple(range(10))

    def test_gemeldete_ziffer_zaehlt_auch_wenn_sie_nicht_kandidat_ist(self):
        """GEMESSEN auf Bahn 2: Der Leser meldete '2823', die Kandidatenliste
        derselben Lesung lautete [2] [8] [3] [3]. Die dritte Stelle wich ab,
        weil bei unbekanntem Segmentmuster auf das nächstliegende ausgewichen
        wird. Beides muss gelten, sonst entstünde ein Widerspruch aus einer
        Eigenart des Lesers."""
        l = lesung("2823", ((2,), (8,), (3,), (3,)))
        assert erlaubte_ziffern(l, 2) == (2, 3)


class TestPasstZurLesung:
    def test_der_gelesene_wert_passt_immer(self):
        assert passt_zur_lesung(lesung("0172"), 172)

    def test_fuehrende_nullen_werden_ergaenzt(self):
        """Die Tafel zeigt '0175', nicht '175'."""
        assert passt_zur_lesung(lesung("017?", ((0,), (1,), (7,), (5, 6))), 175)

    def test_ein_wert_der_nicht_ins_feld_passt_passt_nicht(self):
        assert not passt_zur_lesung(lesung("172"), 1720)

    def test_das_beispiel_des_nutzers(self):
        """*"gerade standen wir bei 0172 -> jetzt melden Ziffer und Lampen eine
        3 -> sicher dass du hier eine 8176 melden willst und nicht eher eine
        0175?"* -- die Anzeige muss 0175 zulassen und 8176 nicht."""
        l = lesung("8176", ((8, 0), (1,), (7,), (6, 5)))
        assert passt_zur_lesung(l, 175)
        assert passt_zur_lesung(l, 8176)      # die rohe Lesung bleibt möglich

    def test_negative_werte_passen_nie(self):
        assert not passt_zur_lesung(lesung("0000"), -1)


class TestMoeglicheWerte:
    def test_zaehlt_den_bereich_ab(self):
        l = lesung("017?", ((0,), (1,), (7,), (2, 5)))
        assert moegliche_werte(l, 170, 179) == (172, 175)

    def test_leerer_bereich_bleibt_leer(self):
        assert moegliche_werte(lesung("0000"), 5, 3) == ()


class TestDieSpurBeginntBeiNull:
    """Der Nutzer: *"es muss eigentlich immer mit 0 losgehen und dann
    steigen."* Vor dem ersten Wurf ist deshalb nur die Null verankerbar."""

    def test_vor_dem_ersten_wurf_zaehlt_nur_die_null(self):
        s = Summenspur()
        assert s.deute(lesung("0000")).art == VERANKERT
        assert s.stand == 0

    def test_ein_grosser_wert_beim_ersten_wurf_ist_unmoeglich(self):
        """GEMESSEN: Bahn 2 meldete 2823 als erste Summe des Mitschnitts."""
        s = Summenspur()
        d = s.deute(lesung("2823"))
        assert d.art == UNMOEGLICH
        assert s.stand is None

    def test_die_schranke_waechst_mit_den_wuerfen(self):
        """Keine feste Grenze -- nach zwanzig Würfen sind 180 erreichbar."""
        s = Summenspur()
        for _ in range(20):
            s.buche_wurf()
        assert s.obergrenze == 180
        assert s.deute(lesung("0175")).art == VERANKERT

    def test_kein_deckel_bei_270(self):
        """*"wer weiß was manche Leute im Training oder so machen"* -- nach
        hundert Würfen sind 700 systematisch erreichbar."""
        s = Summenspur()
        for _ in range(100):
            s.buche_wurf()
        assert s.deute(lesung("0700")).art == VERANKERT


class TestDieFuehrung:
    def test_die_erwartung_loest_eine_schwankende_stelle_auf(self):
        s = Summenspur(stand=172)
        d = s.deute(lesung("017?", ((0,), (1,), (7,), (5, 9))), gefallen=3)
        assert d.art == GEFUEHRT
        assert d.wert == 175
        assert s.stand == 175

    def test_ein_gefuehrter_wert_ist_kein_zeuge(self):
        """Wer aus den Lampen liest, darf damit nicht die Lampen bestätigen."""
        s = Summenspur(stand=172)
        d = s.deute(lesung("017?", ((0,), (1,), (7,), (5, 9))), gefallen=3)
        assert not d.unabhaengig

    def test_die_fuehrung_darf_die_rohe_lesung_ueberstimmen(self):
        """Das Beispiel des Nutzers: gelesen wird 8176, gemeint ist 0175."""
        s = Summenspur(stand=172)
        d = s.deute(lesung("8176", ((8, 0), (1,), (7,), (6, 5))), gefallen=3)
        assert d.wert == 175
        assert "8176" in d.bemerkung

    def test_eine_unmoegliche_erwartung_wird_gemeldet_nicht_geglaettet(self):
        """Lässt die Anzeige die Erwartung NICHT zu, ist das ein echter
        Widerspruch. Er darf nicht verschwinden."""
        s = Summenspur(stand=172)
        d = s.deute(lesung("0177"), gefallen=3)
        assert d.art == EINDEUTIG
        assert d.wert == 177
        assert d.unabhaengig
        assert s.stand == 177

    def test_gar_nichts_passendes_laesst_den_stand_stehen(self):
        s = Summenspur(stand=172)
        d = s.deute(lesung("9999"), gefallen=3)
        assert d.art == UNMOEGLICH
        assert d.wert is None
        assert s.stand == 172

    def test_mehrere_moegliche_werte_entscheiden_nichts(self):
        s = Summenspur(stand=172)
        d = s.deute(lesung("017?", ((0,), (1,), (7,), (4, 7))), gefallen=3)
        assert d.art == WIDERSPRUCH
        assert d.wert is None
        assert s.stand == 172

    def test_ohne_lesung_bleibt_alles_wie_es_war(self):
        s = Summenspur(stand=172)
        assert s.deute(None).art == STUMM
        assert s.stand == 172

    def test_ein_neues_spiel_setzt_die_spur_zurueck(self):
        s = Summenspur(stand=172, wuerfe=30)
        s.neues_spiel()
        assert s.stand is None and s.obergrenze == 0


class TestMittenInsSpiel:
    """Der Mitschnitt beginnt nicht beim ersten Wurf. Ohne die Wurfnummer der
    Tafel hielte die Spur jeden Stand für unmöglich -- GEMESSEN: Bahn 2 stand
    beim ersten lesbaren Frame bereits bei 117."""

    def test_die_wurfnummer_hebt_die_schranke(self):
        s = Summenspur()
        assert s.deute(lesung("0117")).art == UNMOEGLICH
        s.kennt_wurfnummer(20)
        assert s.obergrenze == 180
        assert s.deute(lesung("0117")).art == VERANKERT

    def test_eine_kleinere_wurfnummer_senkt_die_schranke_nicht(self):
        """Ein Lesefehler bei der Wurfnummer darf die Spur nicht verengen."""
        s = Summenspur()
        s.kennt_wurfnummer(20)
        s.kennt_wurfnummer(3)
        assert s.obergrenze == 180


class TestDerNotausgang:
    """GEMESSEN: Bahn 5 verankerte sich auf eine 0 aus Frame 230 und hielt
    danach 1352 von 1353 Lesungen für unmöglich. Ein falscher Anker war ohne
    Notausgang endgültig."""

    def test_nach_drei_unmoeglichen_lesungen_wird_der_anker_aufgegeben(self):
        s = Summenspur(stand=0, wuerfe=30, geduld=3)
        for _ in range(2):
            assert s.deute(lesung("0150")).art == UNMOEGLICH
            assert s.stand == 0
        d = s.deute(lesung("0150"))
        assert d.art == UNMOEGLICH
        assert "aufgegeben" in d.bemerkung
        assert s.stand is None
        # Danach trägt die Spur wieder.
        assert s.deute(lesung("0150")).art == VERANKERT

    def test_eine_gute_lesung_dazwischen_setzt_die_geduld_zurueck(self):
        """Ein einzelner Flackerframe darf den Stand nicht kosten."""
        s = Summenspur(stand=100, wuerfe=30, geduld=3)
        for _ in range(5):
            assert s.deute(lesung("0999")).art == UNMOEGLICH
            assert s.deute(lesung("0100")).art == EINDEUTIG
        assert s.stand == 100


class TestKeineFalscheZuversicht:
    """GEMESSEN auf Bahn 4, F5695-6070 (`debug/summe_bahn4.gif`): Die Tafel
    zeigte nachweislich `0133`. Der Stand der Spur stand noch auf 116, das
    Fenster reichte bis 125 -- aus `01?3` passte dort nur 123, und genau das
    wurde als "eindeutig" gebucht.

    Der Nutzer dazu: *"das kann eigentlich nicht sein, wirklich nicht!"* -- er
    hatte recht. Der Befund "die Tafel hängt zwei Würfe zurück" war ein
    Artefakt der Spur, kein Verhalten der Anlage.
    """

    def test_eine_lesung_ausserhalb_des_fensters_wird_verworfen(self):
        """`0133` bei Stand 116: nichts im Fenster 116..125 passt. Das ist
        UNMÖGLICH -- und damit ein Signal, dass der Stand veraltet ist."""
        s = Summenspur(stand=116, wuerfe=30)
        d = s.deute(lesung("0133"))
        assert d.art == UNMOEGLICH
        assert d.wert is None
        assert s.stand == 116

    def test_nach_drei_solchen_lesungen_gibt_die_spur_den_stand_auf(self):
        """Der Notausgang greift genau hier: Drei unmögliche Lesungen in Folge
        heißen, dass nicht die Anzeige irrt, sondern der Anker."""
        s = Summenspur(stand=116, wuerfe=30, geduld=3)
        for _ in range(3):
            s.deute(lesung("0133"))
        assert s.stand is None
        assert s.deute(lesung("0133")).art == VERANKERT
        assert s.stand == 133

    def test_eine_definite_lesung_wird_nicht_auf_einen_nachbarn_gebogen(self):
        """Steht in der Anzeige ein lesbarer Wert, darf das Fenster ihn nicht
        durch einen Nebenkandidaten ersetzen -- auch nicht, wenn nur dieser
        hineinpasst. Genau das war der Fehler auf Bahn 4."""
        s = Summenspur(stand=176, wuerfe=30)
        # Gelesen wird 175; die letzte Stelle könnte auch eine 9 sein. Im
        # Fenster 176..185 liegt nur 179 -- aber die Anzeige sagt 175.
        d = s.deute(lesung("0175", ((0,), (1,), (7,), (5, 9))))
        assert d.art == WIDERSPRUCH
        assert d.wert is None
        assert "175" in d.bemerkung and "179" in d.bemerkung

    def test_eine_unlesbare_stelle_darf_weiterhin_aufgeloest_werden(self):
        """Der Fall, für den die Spur gebaut ist, bleibt erhalten: Die Anzeige
        behauptet selbst nichts Gegenteiliges."""
        s = Summenspur(stand=170, wuerfe=30)
        d = s.deute(lesung("01?5", ((0,), (1,), (7, 8), (5,))))
        assert d.art == EINDEUTIG and d.wert == 175
