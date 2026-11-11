"""Vier Messungen, die einander befragen.

DIE IDEE (Nutzer, 2026-09-15): *"ich moechte erreichen, dass wir 2 Messsysteme
parallel laufen haben, die sich am Ende gegenseitig korrigieren."* Vorerst
beobachtend: Die Gegenprobe zaehlt aus, wer wem widerspricht, und aendert kein
einziges Ergebnis.

DIE VIER ZEUGEN und was jeder allein NICHT kann:

    Lampen              messen das Ergebnis -- koennen aber verdeckt sein
    Kegelziffer         zweite Messung derselben Zahl -- oft unlesbar
    Summendifferenz     Summe(N+1) - Summe(N) = Kegel bei Wurf N. Unabhaengig
                        von beiden, kommt einen Wurf zu spaet
    Wurfnummer          sagt, OB geworfen wurde
    Fehlwurfzaehler     unterscheidet den echten Nullwurf von dem Wurf, den es
                        nie gab -- bei beiden bleibt die Summe stehen

Der Nutzer zum letzten Punkt: *"bei einem Fehlwurf steht da ja auch eine 0 und
Wurfnummer geht um 1 hoch, und die Summe steigt halt eben nicht."*
"""

from __future__ import annotations

from dataclasses import dataclass

from kegel_cv.analysis.gegenprobe import (EINIG, EINIG_OHNE_SUMME,
                                          LAMPEN_VERDAECHTIG, NUR_LAMPEN,
                                          STRITTIG, UNKLAR, WURF_FEHLT,
                                          WURF_UNBESTAETIGT,
                                          ZIFFER_FALSCH, Gegenprobe)


@dataclass
class Wurf:
    """Nur die Felder, die die Gegenprobe liest."""

    lane: int = 2
    throw_number: int = 1
    source_frame: int | None = 1000
    pins_count: int = 0
    displayed_pin_count: int | None = None
    displayed_total: int | None = None
    displayed_throw_number: int | None = None
    displayed_foul_count: int | None = None


def folge(*wuerfe):
    """Schickt eine Wurffolge durch und gibt die Befunde zurueck."""
    g = Gegenprobe()
    for w in wuerfe:
        g.nimm(w)
    return g


class TestDerErsteWurfWirdNochNichtBeurteilt:
    def test_ohne_nachfolger_kein_befund(self):
        g = Gegenprobe()
        assert g.nimm(Wurf(pins_count=5, displayed_total=0)) is None
        assert g.befunde == []

    def test_der_befund_gilt_dem_VORHERIGEN_wurf(self):
        """Die Summe auf der Tafel ist der Stand VOR dem Wurf. Erst der
        naechste Wurf verraet, was dieser gebracht hat."""
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_total=0,
                 displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=5,
                 displayed_throw_number=2))
        assert len(g.befunde) == 1
        assert g.befunde[0].wurf == 1
        assert g.befunde[0].differenz == 5


class TestWennSichAlleEinigSind:
    def test_summe_lampen_und_ziffer_stimmen(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=5,
                 displayed_total=0, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_pin_count=3,
                 displayed_total=5, displayed_throw_number=2))
        assert g.befunde[0].urteil == EINIG

    def test_ohne_kegelziffer_genuegt_die_summe(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_total=0,
                 displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=5,
                 displayed_throw_number=2))
        assert g.befunde[0].urteil == EINIG
        assert "nicht gelesen" in g.befunde[0].bemerkung


class TestWennSichZweiWidersprechen:
    def test_die_summe_stuetzt_die_lampen(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=9,
                 displayed_total=0, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=5,
                 displayed_throw_number=2))
        assert g.befunde[0].urteil == ZIFFER_FALSCH

    def test_die_summe_stuetzt_die_ziffer(self):
        """Der interessante Fall: Zwei unabhaengige Quellen bestreiten
        gemeinsam ein gebuchtes Ergebnis."""
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=9,
                 displayed_total=0, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=9,
                 displayed_throw_number=2))
        assert g.befunde[0].urteil == LAMPEN_VERDAECHTIG

    def test_keiner_bestaetigt(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=9,
                 displayed_total=0, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=7,
                 displayed_throw_number=2))
        assert g.befunde[0].urteil == UNKLAR


class TestDieWurfnummerSagtObGeworfenWurde:
    def test_stillstand_heisst_die_anlage_zaehlte_keinen_wurf(self):
        """Die Signatur eines Phantomwurfs. Und sie faellt auch dann auf, wenn
        ohnehin kein Kegel gefallen waere -- der Summenvergleich koennte das
        nicht."""
        g = folge(
            Wurf(throw_number=1, pins_count=0, displayed_total=40,
                 displayed_throw_number=7, displayed_foul_count=2),
            Wurf(throw_number=2, pins_count=4, displayed_total=40,
                 displayed_throw_number=7, displayed_foul_count=2))
        assert g.befunde[0].urteil == WURF_UNBESTAETIGT
        assert "Fehlwurfzaehler ebenfalls unveraendert" in g.befunde[0].bemerkung

    def test_ein_sprung_heisst_ein_wurf_fehlt(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_total=0,
                 displayed_throw_number=3),
            Wurf(throw_number=2, pins_count=3, displayed_total=12,
                 displayed_throw_number=6))
        assert g.befunde[0].urteil == WURF_FEHLT
        assert "2 Wurf" in g.befunde[0].bemerkung

    def test_der_ruecksprung_beim_spielwechsel_ist_kein_fehler(self):
        g = folge(
            Wurf(throw_number=30, pins_count=5, displayed_total=140,
                 displayed_throw_number=30),
            Wurf(throw_number=1, pins_count=3, displayed_total=0,
                 displayed_throw_number=1))
        assert g.befunde[0].urteil != WURF_FEHLT


class TestDerFehlwurfzaehler:
    def test_beim_nullwurf_muss_er_steigen(self):
        """Ein Fehlwurf: 0 Kegel, Wurfnummer plus eins, Summe unveraendert --
        und der Fehlwurfzaehler plus eins."""
        g = folge(
            Wurf(throw_number=1, pins_count=0, displayed_pin_count=0,
                 displayed_total=40, displayed_throw_number=7,
                 displayed_foul_count=2),
            Wurf(throw_number=2, pins_count=4, displayed_total=40,
                 displayed_throw_number=8, displayed_foul_count=3))
        assert g.befunde[0].urteil == EINIG
        assert g.befunde[0].fehlwurf_stimmt == "ja"

    def test_ein_nullwurf_ohne_fehlwurf_faellt_auf(self):
        g = folge(
            Wurf(throw_number=1, pins_count=0, displayed_pin_count=0,
                 displayed_total=40, displayed_throw_number=7,
                 displayed_foul_count=2),
            Wurf(throw_number=2, pins_count=4, displayed_total=40,
                 displayed_throw_number=8, displayed_foul_count=2))
        assert g.befunde[0].fehlwurf_stimmt == "nein"

    def test_bei_gefallenen_kegeln_muss_er_stehen_bleiben(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_total=0,
                 displayed_throw_number=1, displayed_foul_count=2),
            Wurf(throw_number=2, pins_count=3, displayed_total=5,
                 displayed_throw_number=2, displayed_foul_count=2))
        assert g.befunde[0].fehlwurf_stimmt == "ja"


class TestDieGrenzenDesMoeglichen:
    def test_ein_unmoeglicher_summensprung_entwertet_die_summe(self):
        """Mehr als neun Kegel faellt kein Wurf. Ein groesserer Sprung heisst,
        dass eine der Summen falsch gelesen wurde -- dann zaehlt sie nicht als
        Schiedsrichter, und es bleibt beim Vergleich der uebrigen."""
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=9,
                 displayed_total=10, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=30,
                 displayed_throw_number=2))
        assert g.befunde[0].urteil == STRITTIG
        assert "ausserhalb" in g.befunde[0].bemerkung

    def test_eine_rueckwaerts_laufende_summe(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=5,
                 displayed_total=30, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=10,
                 displayed_throw_number=2))
        assert g.befunde[0].urteil == EINIG_OHNE_SUMME

    def test_ohne_summe_und_ohne_ziffer_bleibt_nur_die_lampe(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_throw_number=2))
        assert g.befunde[0].urteil == NUR_LAMPEN


class TestWennDieSummeSchweigt:
    """GEMESSEN am Hallenmitschnitt: Die Summe liegt nur in 2 von 57 Faellen
    auf beiden Seiten vor, die Kegelziffer dagegen in 56. Ein Urteil, das ohne
    Summe schweigt, schwiege dort in 95 % der Faelle -- die Summe ist der
    Schiedsrichter, nicht die Grundlage."""

    def test_lampen_und_ziffer_einig(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=5,
                 displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_throw_number=2))
        assert g.befunde[0].urteil == EINIG_OHNE_SUMME

    def test_lampen_und_ziffer_uneinig_ohne_schiedsrichter(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=9,
                 displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_throw_number=2))
        assert g.befunde[0].urteil == STRITTIG

    def test_eine_unbrauchbare_summe_zaehlt_wie_keine(self):
        """Am Hallenmitschnitt stand einmal 2837 im Summenfeld. Das ist keine
        Messung, sondern ein Lesefehler -- so ein Wert darf nicht als
        Schiedsrichter auftreten."""
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=5,
                 displayed_total=2837, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=0,
                 displayed_throw_number=2))
        assert g.befunde[0].urteil == EINIG_OHNE_SUMME
        assert "unbrauchbar" in g.befunde[0].bemerkung


class TestBahnenBleibenGetrennt:
    def test_jede_bahn_hat_ihre_eigene_kette(self):
        """Prinzip P6. Die Summe der Bahn 3 sagt nichts ueber Bahn 2."""
        g = Gegenprobe()
        g.nimm(Wurf(lane=2, throw_number=1, pins_count=5, displayed_total=0,
                    displayed_throw_number=1))
        g.nimm(Wurf(lane=3, throw_number=1, pins_count=2, displayed_total=100,
                    displayed_throw_number=1))
        assert g.befunde == []
        g.nimm(Wurf(lane=2, throw_number=2, pins_count=3, displayed_total=5,
                    displayed_throw_number=2))
        assert len(g.befunde) == 1
        assert g.befunde[0].bahn == 2 and g.befunde[0].urteil == EINIG


class TestDerBericht:
    def test_ohne_befunde_sagt_er_das(self):
        assert "keine" in Gegenprobe().bericht()

    def test_er_nennt_jede_kategorie_und_die_strittigen(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_pin_count=9,
                 displayed_total=0, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=9,
                 displayed_throw_number=2),
            Wurf(throw_number=3, pins_count=1, displayed_total=12,
                 displayed_throw_number=3))
        text = g.bericht()
        assert "Summe stuetzt die ZIFFER" in text
        assert "widersprechen" in text
        assert "Wurf 1" in text

    def test_die_zeilen_sind_tabellenfaehig(self):
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_total=0,
                 displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=5,
                 displayed_throw_number=2))
        zeile = g.befunde[0].als_zeile()
        assert zeile["Lampen"] == 5 and zeile["Differenz"] == 5
        assert all(not isinstance(w, (dict, list)) for w in zeile.values())


class TestSieAendertNichts:
    def test_die_gegenprobe_fasst_den_wurf_nicht_an(self):
        """Die Lampen behalten ihr Hoheitsrecht. Erst wenn die Zahlen zeigen,
        dass ein Zeuge dem anderen ueberlegen ist, wird korrigiert."""
        w = Wurf(throw_number=1, pins_count=5, displayed_pin_count=9,
                 displayed_total=0, displayed_throw_number=1)
        g = Gegenprobe()
        g.nimm(w)
        g.nimm(Wurf(throw_number=2, pins_count=3, displayed_total=9,
                    displayed_throw_number=2))
        assert w.pins_count == 5


class TestGefuehrtGeleseneSumme:
    """Eine Summe, die aus den Lampen gewonnen wurde, darf die Lampen nicht
    bestätigen -- sonst zählte eine Messung zweimal.

    Siehe `analysis/gefuehrtes_lesen.py`, "Die Richtung entscheidet über die
    Ehrlichkeit".
    """

    @staticmethod
    def lesung(text, kandidaten=()):
        from kegel_cv.detection.digit_detector import DigitReading
        ziffern = tuple(text)
        if not kandidaten:
            kandidaten = tuple((int(z),) if z.isdigit() else ()
                               for z in ziffern)
        return DigitReading(
            text=text, value=int(text) if text.isdigit() else None,
            confidence=0.9, digits=ziffern, candidates=kandidaten,
            scores=(0.9,) * len(ziffern))

    def test_eine_gefuehrte_summe_ist_kein_schiedsrichter(self):
        """Die Führung hat die Summe aus den Lampen abgeleitet. Sie stimmt
        deshalb zwangsläufig mit ihnen überein -- und sagt nichts."""
        g = Gegenprobe()
        g.spur(2).kennt_wurfnummer(20)
        g.nimm(Wurf(throw_number=1, pins_count=5, displayed_pin_count=5,
                    displayed_throw_number=20),
               self.lesung("0100"))
        # Zweite Lesung schwankt an der letzten Stelle zwischen 5 und 9 --
        # die Erwartung (100 + 5) löst sie auf.
        g.nimm(Wurf(throw_number=2, pins_count=3, displayed_throw_number=21),
               self.lesung("010?", ((0,), (1,), (0,), (5, 9))))
        assert g.befunde[0].urteil == EINIG_OHNE_SUMME
        assert "gefuehrt" in g.befunde[0].bemerkung

    def test_eine_eindeutig_aufgeloeste_summe_zaehlt_dagegen_schon(self):
        """Ließ die Systematik allein nur einen Wert zu, wurden die Lampen
        nicht befragt -- dann bleibt die Summe ein eigener Zeuge."""
        g = Gegenprobe()
        g.spur(2).kennt_wurfnummer(20)
        g.nimm(Wurf(throw_number=1, pins_count=5, displayed_pin_count=5,
                    displayed_throw_number=20),
               self.lesung("0100"))
        g.nimm(Wurf(throw_number=2, pins_count=3, displayed_throw_number=21),
               self.lesung("0105"))
        assert g.befunde[0].urteil == EINIG

    def test_eine_unmoegliche_summe_erreicht_das_urteil_gar_nicht(self):
        """GEMESSEN: Bahn 2 meldete Werte wie 2823 und 3813. Die Systematik
        verwirft sie, bevor sie als Schiedsrichter auftreten können."""
        g = Gegenprobe()
        g.spur(2).kennt_wurfnummer(20)
        g.nimm(Wurf(throw_number=1, pins_count=5, displayed_pin_count=5,
                    displayed_throw_number=20),
               self.lesung("2823"))
        g.nimm(Wurf(throw_number=2, pins_count=3, displayed_throw_number=21),
               self.lesung("3813"))
        assert g.befunde[0].summe_vorher is None
        assert g.befunde[0].urteil == EINIG_OHNE_SUMME

    def test_ohne_lesung_bleibt_alles_beim_alten(self):
        """Wer keine Lesung mitgibt, bekommt das bisherige Verhalten."""
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_total=0,
                 displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_total=5,
                 displayed_throw_number=2))
        assert g.befunde[0].urteil == EINIG

    def test_jede_bahn_hat_ihre_eigene_spur(self):
        """Regel 3: Die Bahnen sind unabhängig."""
        g = Gegenprobe()
        g.spur(2).kennt_wurfnummer(20)
        assert g.spur(3).wuerfe == 0
        assert g.spur(2) is not g.spur(3)


class TestUnklareLampenWerdenAusgewiesen:
    """BUG-027: Eine unklare Lampe fällt still aus der Kegelliste und wirkt
    wie „steht". Beim ABRÄUMEN ist das Ergebnis die Differenz zweier
    Messungen — eine unklare Lampe in der AUSGANGSLAGE wird dann abgezogen,
    obwohl niemand weiß, ob der Kegel lag.

    Gemessen wurde das am Einzelfall (Bahn 2 Wurf 21: 5 gebucht, Ziffer und
    Summe sagten 4). Damit es über viele Würfe zählbar wird, steht es jetzt in
    der Tabelle.
    """

    @dataclass
    class WurfMitLampen(Wurf):
        lamps_unknown: int = 0
        baseline_unknown: int | None = None

    def test_die_zahlen_stehen_im_befund(self):
        g = Gegenprobe()
        g.nimm(self.WurfMitLampen(throw_number=1, pins_count=5,
                                  displayed_throw_number=1,
                                  lamps_unknown=2, baseline_unknown=1))
        g.nimm(self.WurfMitLampen(throw_number=2, pins_count=3,
                                  displayed_throw_number=2))
        assert g.befunde[0].lampen_unklar == 2
        assert g.befunde[0].grundlage_unklar == 1

    def test_sie_stehen_auch_in_der_tabelle(self):
        g = Gegenprobe()
        g.nimm(self.WurfMitLampen(throw_number=1, pins_count=5,
                                  displayed_throw_number=1,
                                  lamps_unknown=1, baseline_unknown=3))
        g.nimm(self.WurfMitLampen(throw_number=2, pins_count=3,
                                  displayed_throw_number=2))
        zeile = g.befunde[0].als_zeile()
        assert zeile["LampenUnklar"] == 1
        assert zeile["GrundlageUnklar"] == 3

    def test_der_bericht_nennt_die_gefaehrlichere_zuerst(self):
        g = Gegenprobe()
        g.nimm(self.WurfMitLampen(throw_number=1, pins_count=5,
                                  displayed_throw_number=1,
                                  baseline_unknown=2))
        g.nimm(self.WurfMitLampen(throw_number=2, pins_count=3,
                                  displayed_throw_number=2))
        text = g.bericht()
        assert "Unklare Kegellampen" in text
        assert "in der Grundlage" in text
        assert "Punktestand" in text

    def test_ohne_unklare_lampen_schweigt_der_bericht(self):
        """Eine Zeile mit lauter Nullen ist Rauschen."""
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_throw_number=2))
        assert "Unklare Kegellampen" not in g.bericht()

    def test_ein_wurf_ohne_die_felder_bleibt_lesbar(self):
        """Alte Wurfobjekte kennen die Zaehler nicht -- das darf nicht
        auffallen."""
        g = folge(
            Wurf(throw_number=1, pins_count=5, displayed_throw_number=1),
            Wurf(throw_number=2, pins_count=3, displayed_throw_number=2))
        assert g.befunde[0].lampen_unklar == 0
        assert g.befunde[0].grundlage_unklar is None
