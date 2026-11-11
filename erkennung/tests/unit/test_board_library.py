"""Die Bibliothek bekannter Tafelbauarten.

WOFUER -- Wunsch des Nutzers am 2026-09-09:

    "cool waere, wenn er standardmaessig wenn ein Stream startet schaut, ob er
     eins der bekannten Kegelboards aus seinem Repertoire kennt. Langfristig
     sollen alle typischen Boards selbststaendig erkannt werden."

Ein Typ besteht aus einem Musterbild und den ROIs darauf. Wird das Muster in
einem neuen Bild wiedergefunden, folgen alle Felder aus den vier Ecken -- die
ROIs liegen in normierten Tafelkoordinaten.

GEMESSEN 2026-09-09 mit dem Typ FUNK_klassisch (Muster von der Hallenkamera,
190x191 px):

    eigene Hallenkamera, Frame 11000     4 Tafeln, 316 tragende Merkmale
    fremdes Overlay-Video, Frame 81000   4 Tafeln, 179 tragende Merkmale

Zwei verschiedene Kameras, Aufloesungen und Blickwinkel -- dasselbe Muster.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from kegel_cv.calibration.board_library import (Erkennung, Tafeltyp, erkenne,
                                                lade_bibliothek, speichere_typ,
                                                uebernimm)
from kegel_cv.calibration.board_finder import Treffer
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi

BILD_H, BILD_B = 300, 620


def tafel(breite=110, hoehe=120, keim=5) -> np.ndarray:
    rng = np.random.default_rng(keim)
    b = rng.integers(0, 255, (hoehe, breite, 3), dtype=np.uint8)
    v = keim % 5 * 6
    cv2.rectangle(b, (8 + v, 8), (breite - 8, 34 + v), (255, 255, 255), 2)
    cv2.rectangle(b, (16, 50), (breite - 16 - v, hoehe - 12), (0, 0, 0), 2)
    cv2.circle(b, (breite // 2 + v, hoehe // 2), 10 + keim % 3,
               (255, 255, 255), -1)
    for i in range(3):
        cv2.line(b, (5, 45 + i * 18 + v), (breite - 5, 50 + i * 18),
                 (0, 0, 0), 1)
    return b


def szene(t: np.ndarray, stellen=(20, 180, 340)) -> np.ndarray:
    bild = np.full((BILD_H, BILD_B, 3), 55, dtype=np.uint8)
    h, b = t.shape[:2]
    for x in stellen:
        bild[60:60 + h, x:x + b] = t
    return bild


def eine_kalibrierung(breite=110, hoehe=120) -> Calibration:
    return Calibration(lanes=[LaneCalibration(
        lane_id=1,
        quad=[[20.0, 60.0], [20.0 + breite, 60.0],
              [20.0 + breite, 60.0 + hoehe], [20.0, 60.0 + hoehe]],
        real_lane_number=3,
        rois=[Roi(name="green_lamp", rect=(0.4, 0.8, 0.05, 0.05)),
              Roi(name="digit_total_b_1", rect=(0.2, 0.85, 0.06, 0.1))],
    )])


class TestBibliothekLaden:
    def test_ein_typ_wird_gefunden(self, tmp_path):
        speichere_typ(tmp_path, "Testbauart", szene(tafel()),
                      eine_kalibrierung())
        typen = lade_bibliothek(tmp_path)
        assert [t.name for t in typen] == ["Testbauart"]

    def test_ohne_musterbild_wird_uebersprungen(self, tmp_path):
        """Eine unvollstaendige Bibliothek darf den Start nicht verhindern."""
        eine_kalibrierung().save(tmp_path / "ohne_bild.json")
        assert lade_bibliothek(tmp_path) == []

    def test_eine_kaputte_datei_nimmt_die_anderen_nicht_mit(self, tmp_path):
        speichere_typ(tmp_path, "Gut", szene(tafel()), eine_kalibrierung())
        (tmp_path / "Kaputt.json").write_text("{kein json", encoding="utf-8")
        cv2.imwrite(str(tmp_path / "Kaputt.png"), tafel())
        assert [t.name for t in lade_bibliothek(tmp_path)] == ["Gut"]

    def test_ein_leerer_ordner_ist_kein_fehler(self, tmp_path):
        assert lade_bibliothek(tmp_path / "gibtsnicht") == []

    def test_das_muster_hat_beobachtete_groesse(self, tmp_path):
        """GEMESSEN: Eine auf 440x530 entzerrte Vorlage gegen eine 192 px
        grosse Tafel fand nur eine von vier Tafeln."""
        speichere_typ(tmp_path, "T", szene(tafel()), eine_kalibrierung())
        typ = lade_bibliothek(tmp_path)[0]
        h, b = typ.muster.shape[:2]
        assert abs(b - 110) <= 2 and abs(h - 120) <= 2


class TestErkennen:
    def test_die_eigene_szene_wird_erkannt(self, tmp_path):
        bild = szene(tafel())
        speichere_typ(tmp_path, "Testbauart", bild, eine_kalibrierung())
        typen = lade_bibliothek(tmp_path)
        treffer = erkenne(bild, typen, min_inlier=10)
        assert treffer is not None
        assert treffer.typ.name == "Testbauart"
        assert len(treffer.treffer) == 3, "drei gleiche Tafeln im Bild"

    def test_eine_fremde_szene_wird_nicht_erkannt(self, tmp_path):
        speichere_typ(tmp_path, "Testbauart", szene(tafel(keim=5)),
                      eine_kalibrierung())
        typen = lade_bibliothek(tmp_path)
        leer = np.full((BILD_H, BILD_B, 3), 55, dtype=np.uint8)
        assert erkenne(leer, typen, min_inlier=10) is None

    def test_ohne_typen_kein_treffer(self):
        assert erkenne(szene(tafel()), [], min_inlier=10) is None

    def test_ein_leeres_bild_stuerzt_nicht_ab(self, tmp_path):
        speichere_typ(tmp_path, "T", szene(tafel()), eine_kalibrierung())
        typen = lade_bibliothek(tmp_path)
        assert erkenne(np.zeros((0, 0, 3), np.uint8), typen) is None


class TestUebernehmen:
    def _erkennung(self, tmp_path):
        bild = szene(tafel())
        speichere_typ(tmp_path, "T", bild, eine_kalibrierung())
        return erkenne(bild, lade_bibliothek(tmp_path), min_inlier=10)

    def test_die_bahnnummern_werden_gesetzt(self, tmp_path):
        kal = uebernimm(self._erkennung(tmp_path), [2, 3, 4])
        assert [l.display_number for l in kal.lanes] == [2, 3, 4]

    def test_die_rois_des_typs_werden_uebernommen(self, tmp_path):
        """Der ganze Sinn: kein einziger Klick fuer Lampen und Ziffern."""
        kal = uebernimm(self._erkennung(tmp_path), [1, 2, 3])
        namen = {r.name for r in kal.lanes[0].rois}
        assert namen == {"green_lamp", "digit_total_b_1"}
        for bahn in kal.lanes:
            assert {r.name for r in bahn.rois} == namen

    def test_die_position_von_links_wird_zur_lane_id(self, tmp_path):
        kal = uebernimm(self._erkennung(tmp_path), [7, 8, 9])
        assert [l.lane_id for l in kal.lanes] == [1, 2, 3]

    def test_falsche_anzahl_wird_abgelehnt(self, tmp_path):
        with pytest.raises(ValueError, match="Bahnnummern"):
            uebernimm(self._erkennung(tmp_path), [1, 2])


class TestErkennungsGuete:
    def test_merkmale_sind_die_summe(self):
        t = [Treffer(quad=[[0, 0]] * 4, inlier=n, paare=n + 5,
                     vorlage_index=0) for n in (20, 30)]
        e = Erkennung(typ=Tafeltyp("x", np.zeros((2, 2, 3), np.uint8),
                                   eine_kalibrierung()), treffer=t)
        assert e.merkmale == 50


class TestUeberMehrereFrames:
    """Ein einzelnes Standbild genuegt nicht.

    GEMESSEN 2026-09-10, 16 Stichproben ueber ein Spiel von 3:08 h mit vier
    gleichen Tafeln im Bild: viermal wurden 3 Tafeln gefunden, nur einmal alle
    4, fuenfmal gar keine. Brennende Kegellampen und wechselnde Ziffern
    veraendern genau die Merkmale, an denen der Abgleich haengt -- die LAGE der
    Tafeln aendert sich dagegen nie.
    """

    def _bilder(self, n=4):
        """Dasselbe Arrangement, jedes Bild etwas anders belichtet."""
        t = tafel()
        return [np.clip(szene(t).astype(np.int16) + k * 4, 0, 255)
                .astype(np.uint8) for k in range(n)]

    def test_die_tafeln_werden_gefunden(self, tmp_path):
        from kegel_cv.calibration.board_library import erkenne_ueber_frames
        bilder = self._bilder()
        speichere_typ(tmp_path, "T", bilder[0], eine_kalibrierung())
        treffer = erkenne_ueber_frames(bilder, lade_bibliothek(tmp_path),
                                       min_inlier=10, anker_inlier=6)
        assert treffer is not None
        assert len(treffer.treffer) == 3

    def test_von_links_nach_rechts(self, tmp_path):
        """Die Bahnnummern werden in dieser Reihenfolge abgefragt -- eine
        andere Sortierung vertauscht stillschweigend die Bahnen."""
        from kegel_cv.calibration.board_library import erkenne_ueber_frames
        bilder = self._bilder()
        speichere_typ(tmp_path, "T", bilder[0], eine_kalibrierung())
        treffer = erkenne_ueber_frames(bilder, lade_bibliothek(tmp_path),
                                       min_inlier=10, anker_inlier=6)
        mitten = [np.array(t.quad, float)[:, 0].mean() for t in treffer.treffer]
        assert mitten == sorted(mitten)

    def test_was_nur_einmal_auftaucht_zaehlt_nicht(self, tmp_path):
        """Die Wiederholung ersetzt die hohe Schranke: Ein Zufallstreffer
        wiederholt sich nicht an derselben Stelle."""
        from kegel_cv.calibration.board_library import erkenne_ueber_frames
        bilder = self._bilder()
        speichere_typ(tmp_path, "T", bilder[0], eine_kalibrierung())
        typen = lade_bibliothek(tmp_path)
        streng = erkenne_ueber_frames(bilder, typen, min_inlier=10,
                                      anker_inlier=6, min_frames=len(bilder) + 1)
        assert streng is None

    def test_ohne_bilder_kein_treffer(self, tmp_path):
        from kegel_cv.calibration.board_library import erkenne_ueber_frames
        speichere_typ(tmp_path, "T", szene(tafel()), eine_kalibrierung())
        assert erkenne_ueber_frames([], lade_bibliothek(tmp_path)) is None

    def test_leere_bilder_werden_uebergangen(self, tmp_path):
        from kegel_cv.calibration.board_library import erkenne_ueber_frames
        bilder = self._bilder()
        speichere_typ(tmp_path, "T", bilder[0], eine_kalibrierung())
        gemischt = [np.zeros((0, 0, 3), np.uint8), None] + bilder
        treffer = erkenne_ueber_frames(gemischt, lade_bibliothek(tmp_path),
                                       min_inlier=10, anker_inlier=6)
        assert treffer is not None

    def test_eine_fremde_szene_bleibt_fremd(self, tmp_path):
        from kegel_cv.calibration.board_library import erkenne_ueber_frames
        speichere_typ(tmp_path, "T", szene(tafel(keim=5)), eine_kalibrierung())
        leer = [np.full((BILD_H, BILD_B, 3), 55, dtype=np.uint8)] * 3
        assert erkenne_ueber_frames(leer, lade_bibliothek(tmp_path),
                                    min_inlier=10) is None


class TestBuendeln:
    """Zwei Funde an derselben Stelle sind dieselbe Tafel."""

    def _fund(self, x, inlier=20):
        from kegel_cv.calibration.board_finder import Treffer
        return (Treffer(quad=[[x, 0.0], [x + 100, 0.0],
                              [x + 100, 100.0], [x, 100.0]],
                        inlier=inlier, paare=inlier + 5, vorlage_index=0),
                np.zeros((2, 2, 3), np.uint8))

    def test_dieselbe_stelle_ein_buendel(self):
        from kegel_cv.calibration.board_library import _einsortieren
        g = []
        _einsortieren(g, self._fund(100))
        _einsortieren(g, self._fund(104))
        assert len(g) == 1 and len(g[0]) == 2

    def test_nachbartafeln_bleiben_getrennt(self):
        """GEMESSEN: Die Mitten liegen bei 554, 863, 1096, 1392 Pixel bei 159
        Pixel Tafelbreite -- rund eine ganze Breite auseinander."""
        from kegel_cv.calibration.board_library import _einsortieren
        g = []
        _einsortieren(g, self._fund(100))
        _einsortieren(g, self._fund(300))
        assert len(g) == 2


class TestLaufendeSuche:
    """Die Suche fuer den Livestream: Bilder kommen nacheinander an.

    GEMESSEN 2026-09-10 an acht Stellen einer Aufzeichnung, ein Bild je 0,8 s
    Streamzeit: sechsmal alle vier Tafeln nach 2,4 bis 14,4 Sekunden (im
    Mittel 4,8), zweimal nur zwei bzw. drei bis zur Zeitgrenze von 20 s.
    """

    def _suche(self, tmp_path, ziel=3):
        from kegel_cv.calibration.board_library import LaufendeSuche
        bilder = [szene(tafel()) for _ in range(3)]
        speichere_typ(tmp_path, "T", bilder[0], eine_kalibrierung())
        return (LaufendeSuche(lade_bibliothek(tmp_path), ziel_anzahl=ziel,
                              min_inlier=10, anker_inlier=6), bilder)

    def test_am_anfang_ist_nichts_gefunden(self, tmp_path):
        suche, _ = self._suche(tmp_path)
        assert suche.gefunden == 0 and not suche.fertig
        assert suche.ergebnis() is None

    def test_sie_waechst_mit_jedem_bild(self, tmp_path):
        suche, bilder = self._suche(tmp_path)
        for b in bilder:
            suche.fuettere(b)
        assert suche.gefunden == 3

    def test_fertig_sobald_das_ziel_erreicht_ist(self, tmp_path):
        """Das Abbruchkriterium ist der ERFOLG, nicht die Zeit -- sonst
        wartet man zwanzig Sekunden, obwohl nach dreien alles da war."""
        suche, bilder = self._suche(tmp_path, ziel=2)
        for b in bilder:
            suche.fuettere(b)
            if suche.fertig:
                break
        assert suche.fertig

    def test_ein_zu_hohes_ziel_bleibt_offen(self, tmp_path):
        suche, bilder = self._suche(tmp_path, ziel=7)
        for b in bilder:
            suche.fuettere(b)
        assert not suche.fertig
        assert suche.ergebnis() is not None, \
            "was gefunden wurde, wird trotzdem gemeldet"

    def test_leere_bilder_zaehlen_nicht(self, tmp_path):
        suche, _ = self._suche(tmp_path)
        suche.fuettere(None)
        suche.fuettere(np.zeros((0, 0, 3), np.uint8))
        assert suche.bilder_gesehen == 0

    def test_von_links_nach_rechts(self, tmp_path):
        suche, bilder = self._suche(tmp_path)
        for b in bilder:
            suche.fuettere(b)
        mitten = [np.array(t.quad, float)[:, 0].mean()
                  for t in suche.ergebnis().treffer]
        assert mitten == sorted(mitten)

    def test_ohne_typen_findet_sie_nichts(self):
        from kegel_cv.calibration.board_library import LaufendeSuche
        suche = LaufendeSuche([], ziel_anzahl=4)
        suche.fuettere(szene(tafel()))
        assert suche.ergebnis() is None and suche.gefunden == 0


class TestHerkunftDerAufloesung:
    """HIER LAG EIN FEHLER (gemessen im Livelauf 2026-09-10): Die
    uebernommene Kalibrierung erbte die Aufloesung des MUSTERBILDES. Der Typ
    FUNK_klassisch stammt von der Hallenkamera (2304x1296), der Stream lieferte
    1920x1080 -- und die Oberflaeche warnte "ROIs passen vermutlich nicht",
    obwohl sie perfekt sassen. Eine Warnung, die immer kommt, wird ignoriert;
    dann fehlt sie, wenn sie stimmt."""

    def _erkennung(self, tmp_path):
        bild = szene(tafel())
        kal = eine_kalibrierung()
        kal.source_hint.width, kal.source_hint.height = 2304, 1296
        speichere_typ(tmp_path, "T", bild, kal)
        return erkenne(bild, lade_bibliothek(tmp_path), min_inlier=10), bild

    def test_die_neue_aufloesung_wird_uebernommen(self, tmp_path):
        erkennung, bild = self._erkennung(tmp_path)
        kal = uebernimm(erkennung, [1, 2, 3], bild)
        assert (kal.source_hint.width, kal.source_hint.height) \
            == (bild.shape[1], bild.shape[0])

    def test_keine_warnung_gegen_das_eigene_bild(self, tmp_path):
        erkennung, bild = self._erkennung(tmp_path)
        kal = uebernimm(erkennung, [1, 2, 3], bild)
        assert kal.check_against_video(bild.shape[1], bild.shape[0]) == []

    def test_ohne_bild_bleibt_die_herkunft_offen(self, tmp_path):
        """Lieber gar keine Angabe als eine falsche."""
        erkennung, _ = self._erkennung(tmp_path)
        kal = uebernimm(erkennung, [1, 2, 3])
        assert kal.source_hint.width is None


class TestMassstab:
    """Die Vorlage ist entzerrt -- was nicht passt, ist die GROESSE.

    Frage des Nutzers am 2026-09-10 zur verzerrt wirkenden Vorschau: "Die
    Schablone ist ja auch entzerrt, vielleicht wird dann auch das Ergebnis
    besser". Entzerrt ist sie schon; das Muster FUNK_klassisch ist aber
    190x191 Pixel gross (Hallenkamera) und die Tafeln im Overlay messen rund
    158 -- ein Sprung von 1,2, und ORB ist nur schwach massstabsunabhaengig.

    GEMESSEN 2026-09-10 an acht Stellen: An einer fand NUR der Massstab 0,9
    einen Anker (18 tragende Merkmale), vorher blieb die Suche dort leer.
    Ueber sechs Stichproben stieg das Ergebnis von 4 auf 6 vollstaendige
    Funde von acht.
    """

    def test_die_eigene_groesse_wird_zuerst_versucht(self, tmp_path):
        """Sie trifft in sechs von acht Faellen und kostet ein Viertel der
        Zeit -- teure Arbeit nur dort, wo die billige versagt (P4)."""
        from kegel_cv.calibration.board_finder import BoardFinder
        from kegel_cv.calibration.board_library import finde_anker
        bild = szene(tafel())
        speichere_typ(tmp_path, "T", bild, eine_kalibrierung())
        typ = lade_bibliothek(tmp_path)[0]

        versuche = []
        finder = BoardFinder(min_inlier=10)
        echt = finder.finde_alle

        def zaehlen(ziel, vorlagen, **kw):
            versuche.append(vorlagen[0].shape[:2])
            return echt(ziel, vorlagen, **kw)

        finder.finde_alle = zaehlen
        assert finde_anker(finder, bild, typ.muster, [0.9, 1.2]) is not None
        assert len(versuche) == 1, "bei Erfolg keine weiteren Massstaebe"

    def test_bei_misserfolg_werden_stufen_probiert(self, tmp_path):
        from kegel_cv.calibration.board_finder import BoardFinder
        from kegel_cv.calibration.board_library import finde_anker
        speichere_typ(tmp_path, "T", szene(tafel()), eine_kalibrierung())
        typ = lade_bibliothek(tmp_path)[0]
        leer = np.full((BILD_H, BILD_B, 3), 55, dtype=np.uint8)

        groessen = []
        finder = BoardFinder(min_inlier=10)
        echt = finder.finde_alle

        def zaehlen(ziel, vorlagen, **kw):
            groessen.append(vorlagen[0].shape[1])
            return echt(ziel, vorlagen, **kw)

        finder.finde_alle = zaehlen
        assert finde_anker(finder, leer, typ.muster, [0.9, 1.2, 0.8]) is None
        assert len(groessen) == 4, "eigene Groesse plus drei Stufen"
        assert len(set(groessen)) == 4, "jede Stufe eine andere Groesse"

    def test_ohne_stufen_bleibt_es_bei_einem_versuch(self, tmp_path):
        from kegel_cv.calibration.board_finder import BoardFinder
        from kegel_cv.calibration.board_library import finde_anker
        speichere_typ(tmp_path, "T", szene(tafel()), eine_kalibrierung())
        typ = lade_bibliothek(tmp_path)[0]
        leer = np.full((BILD_H, BILD_B, 3), 55, dtype=np.uint8)
        assert finde_anker(BoardFinder(min_inlier=10), leer, typ.muster,
                           None) is None

    def test_kleine_massstaebe_bleiben_brauchbar(self):
        """Ein zu klein gerechnetes Muster darf nicht auf null Pixel fallen."""
        from kegel_cv.calibration.board_library import _skaliert
        winzig = _skaliert(np.zeros((10, 10, 3), np.uint8), 0.1)
        assert winzig.shape[0] >= 8 and winzig.shape[1] >= 8


class TestMitteln:
    """Der Median ueber die Funde statt des besten Einzeltreffers.

    Die vier Tafeln im Overlay sind baugleich -- wie unterschiedlich sie nach
    der Kalibrierung aussehen, ist Schaetzrauschen. GEMESSEN 2026-09-10 ueber
    acht Stellen des Spiels, Streuung der ROI-Lagen zwischen den vier Tafeln:

        bester Einzeltreffer   1,41 px
        Median ueber die Funde 1,25 px

    Der Median gewann in allen acht Faellen oder lag gleichauf.
    """

    def _funde(self, verschiebungen, inlier=None):
        from kegel_cv.calibration.board_finder import Treffer
        inlier = inlier or [20] * len(verschiebungen)
        gruppe = []
        for v, n in zip(verschiebungen, inlier):
            quad = [[10.0 + v, 10.0], [90.0 + v, 10.0],
                    [90.0 + v, 90.0], [10.0 + v, 90.0]]
            gruppe.append((Treffer(quad=quad, inlier=n, paare=n + 5,
                                   vorlage_index=0),
                           np.zeros((2, 2, 3), np.uint8)))
        return gruppe

    def test_die_ecken_werden_gemittelt(self):
        from kegel_cv.calibration.board_library import _gemittelt
        t = _gemittelt(self._funde([-2.0, 0.0, 2.0]))
        assert t.quad[0][0] == pytest.approx(10.0)

    def test_ein_ausreisser_zieht_nicht_mit(self):
        """MEDIAN, nicht Mittelwert: Eine Tafel, vor der jemand steht, wuerde
        den Mittelwert verschieben."""
        from kegel_cv.calibration.board_library import _gemittelt
        t = _gemittelt(self._funde([0.0, 0.0, 0.0, 0.0, 40.0]))
        assert t.quad[0][0] == pytest.approx(10.0)

    def test_die_merkmale_kommen_vom_besten(self):
        """Sie beschreiben die Sicherheit des Fundes, nicht die Lage."""
        from kegel_cv.calibration.board_library import _gemittelt
        t = _gemittelt(self._funde([0.0, 1.0, 2.0], inlier=[12, 90, 30]))
        assert t.inlier == 90

    def test_ein_einzelner_fund_bleibt_wie_er_ist(self):
        from kegel_cv.calibration.board_library import _gemittelt
        einer = self._funde([3.0])
        assert _gemittelt(einer) is einer[0][0]

    def test_die_suche_nutzt_den_median(self, tmp_path):
        from kegel_cv.calibration.board_library import LaufendeSuche
        bilder = [szene(tafel()) for _ in range(3)]
        speichere_typ(tmp_path, "T", bilder[0], eine_kalibrierung())
        suche = LaufendeSuche(lade_bibliothek(tmp_path), ziel_anzahl=3,
                              min_inlier=10, anker_inlier=6)
        for b in bilder:
            suche.fuettere(b)
        assert suche.ergebnis() is not None


class TestNachlauf:
    """Nach dem vollstaendigen Fund noch weitersammeln.

    WOFUER: Die Ecken werden ueber die Funde gemittelt, und gegen
    Schaetzrauschen hilft Mitteln nur, wenn es genug zu mitteln gibt.
    GEMESSEN 2026-09-10 ueber acht Stellen eines Spiels, Streuung der
    ROI-Lagen zwischen den vier baugleichen Tafeln:

        11 bis 13 Funde je Tafel    0,9 px
         2 bis  7 Funde je Tafel    1,8 px

    Die Suche ist meist nach zwei bis vier Bildern vollstaendig -- genau im
    schlechten Bereich.
    """

    def _suche(self, tmp_path, nachlauf):
        from kegel_cv.calibration.board_library import LaufendeSuche
        bilder = [szene(tafel()) for _ in range(12)]
        speichere_typ(tmp_path, "T", bilder[0], eine_kalibrierung())
        return LaufendeSuche(lade_bibliothek(tmp_path), ziel_anzahl=3,
                             min_inlier=10, anker_inlier=6,
                             nachlauf=nachlauf), bilder

    def test_fertig_und_genug_sind_zweierlei(self, tmp_path):
        suche, bilder = self._suche(tmp_path, nachlauf=4)
        for b in bilder:
            suche.fuettere(b)
            if suche.fertig:
                break
        assert suche.fertig
        assert not suche.genug, "der Nachlauf steht noch aus"

    def test_nach_dem_nachlauf_ist_schluss(self, tmp_path):
        suche, bilder = self._suche(tmp_path, nachlauf=3)
        verbraucht = 0
        for b in bilder:
            suche.fuettere(b)
            verbraucht += 1
            if suche.genug:
                break
        assert suche.genug
        assert verbraucht >= 4, "Fund plus drei weitere Bilder"

    def test_ohne_nachlauf_wie_bisher(self, tmp_path):
        suche, bilder = self._suche(tmp_path, nachlauf=0)
        for b in bilder:
            suche.fuettere(b)
            if suche.fertig:
                break
        assert suche.genug

    def test_es_sammelt_mehr_funde_je_tafel(self, tmp_path):
        """Der eigentliche Zweck -- mehr Funde, ueber die gemittelt wird."""
        from kegel_cv.calibration.board_library import LaufendeSuche
        bilder = [szene(tafel()) for _ in range(12)]
        speichere_typ(tmp_path, "T", bilder[0], eine_kalibrierung())
        typen = lade_bibliothek(tmp_path)

        def funde(nachlauf):
            s = LaufendeSuche(typen, ziel_anzahl=3, min_inlier=10,
                              anker_inlier=6, nachlauf=nachlauf)
            for b in bilder:
                s.fuettere(b)
                if s.genug:
                    break
            stand = next(iter(s._stand.values()))
            return max(len(g) for g in stand["gruppen"])

        assert funde(5) > funde(0)

    def test_unvollstaendig_bleibt_unvollstaendig(self, tmp_path):
        """Ein zu hohes Ziel darf den Nachlauf nicht auslassen -- und die
        Suche nicht vorzeitig fuer fertig erklaeren."""
        suche, bilder = self._suche(tmp_path, nachlauf=2)
        suche.ziel_anzahl = 9
        for b in bilder:
            suche.fuettere(b)
        assert not suche.fertig and not suche.genug
