"""Die Ausrichtung gegen das handgefuehrte Wurfprotokoll.

WARUM ES DIESEN TEST GIBT. Das Protokoll ist der einzige Zeuge, der nicht aus
dem Bild stammt -- und damit die einzige Zahl, an der sich eine Aenderung am
Erkenner wirklich messen laesst. Wochenlang stand sie bei 88,8 Prozent, und
niemand hat ihr misstraut.

Sie war ein Ausrichtungsfehler. `wurfprotokoll_spieltag_1.csv` deckt nur EINE
Mannschaft ab; zwischen zwei Protokollbloecken liegen die 30 Wuerfe des
Gegners. Die alte Ausrichtung nahm die Bahn als eine einzige Wurffolge und
klebte einen Block ueber zwei Spiele hinweg zusammen. Gemessen am 1. Spieltag:

    frei    639 von 720 "richtig"  -- und in ALLEN 81 angeblich falschen
                                      Wuerfen stimmten unsere Lampen mit der
                                      Kegelziffer der Tafel ueberein
    block   720 von 720

ZWEI ANNAHMEN HABEN SICH DABEI ALS FALSCH ERWIESEN, beide hier festgehalten:

1. *„Die Bloecke kommen in derselben Reihenfolge wie unsere Spiele."* Nein.
   Im Protokoll stehen sie nach Satz und Spieler sortiert, auf der Bahn
   spielen die Saetze verschraenkt, weil ein Trio die Bahnen 3-4-5-2
   durchwandert und das andere 5-2-3-4. Eine Ausrichtung mit Monotonie kam
   auf 68,2 Prozent -- schlechter als der Fehler, den sie beheben sollte.

2. *„Ein Spiel unseres Laufs ist ein Block."* Meistens. Hat die Anlage
   mittendrin neu begonnen, steht es bei uns als zwei Spiele mit sich
   ergaenzenden Wurfnummern (gemessen: Bahn 5, 1-18 und 19-30).
"""

from __future__ import annotations

import sys

import pytest

sys.path.insert(0, "tools")

from compare_protocol import (bloecke_der_wahrheit,       # noqa: E402
                              paare_block_spiel,
                              spiele_des_laufs,
                              vergleiche_block)


def soll(satz: int, spieler: str, kegel: list[int]) -> list[dict]:
    return [{"satz": satz, "spieler": spieler, "wurf": i, "kegel": k,
             "modus": "Volle" if i <= 15 else "Abraeumen"}
            for i, k in enumerate(kegel, start=1)]


def lauf(spiel: int, kegel: list[int], ab: int = 1,
         frame: int = 0) -> list[dict]:
    return [{"lane": 2, "spiel": spiel, "pins_count": k,
             "throw_number": i, "source_frame": frame + i,
             "pins": [], "timestamp": 0.0, "status": "VALID",
             "displayed_pin_count": k, "raeumen": ""}
            for i, k in enumerate(kegel, start=ab)]


class TestBloeckeBilden:
    def test_satz_und_spieler_trennen(self):
        zeilen = soll(1, "A", [9] * 3) + soll(1, "B", [8] * 3) + soll(
            3, "A", [7] * 3)
        bloecke = bloecke_der_wahrheit(zeilen)
        assert [len(b) for b in bloecke] == [3, 3, 3]
        assert [b[0]["spieler"] for b in bloecke] == ["A", "B", "A"]

    def test_derselbe_spieler_in_zwei_saetzen_sind_zwei_bloecke(self):
        bloecke = bloecke_der_wahrheit(soll(1, "A", [9]) + soll(3, "A", [8]))
        assert len(bloecke) == 2


class TestSpieleBilden:
    def test_ein_spiel_bleibt_ein_spiel(self):
        spiele = spiele_des_laufs(lauf(1, [9] * 30), 30)
        assert [len(s) for s in spiele] == [30]

    def test_ein_geteiltes_spiel_wird_zusammengelegt(self):
        """Gemessen auf Bahn 5: die Anlage begann mittendrin neu, und der
        Lauf meldete 1-18 und 19-30 als zwei Spiele."""
        geteilt = lauf(15, [9] * 18) + lauf(16, [8] * 12, ab=19, frame=100)
        spiele = spiele_des_laufs(geteilt, 30)
        assert [len(s) for s in spiele] == [30]

    def test_gleiche_wurfnummern_werden_nicht_zusammengelegt(self):
        """Das Warmwerfen zaehlt wieder ab 1. Wuerde es mit dem ersten Spiel
        verschmelzen, verschoebe sich die ganze Bahn."""
        zwei = lauf(2, [9] * 10) + lauf(3, [8] * 10, frame=100)
        assert [len(s) for s in spiele_des_laufs(zwei, 30)] == [10, 10]


class TestZuordnung:
    def test_findet_das_spiel_zwischen_fremden(self):
        """Dazwischen liegen die Spiele der anderen Mannschaft."""
        block = soll(1, "A", [9, 8, 7, 6, 5])
        spiele = [lauf(1, [1, 1, 1, 1, 1]), lauf(2, [9, 8, 7, 6, 5]),
                  lauf(3, [2, 2, 2, 2, 2])]
        assert paare_block_spiel([block], spiele) == [(0, 1)]

    def test_die_reihenfolge_darf_sich_drehen(self):
        """Das ist der Fall, an dem die monotone Ausrichtung gescheitert ist:
        Block 1 gehoert zum SPAETEREN Spiel."""
        bloecke = [soll(1, "A", [9, 9, 9]), soll(3, "B", [1, 1, 1])]
        spiele = [lauf(1, [1, 1, 1]), lauf(2, [9, 9, 9])]
        assert paare_block_spiel(bloecke, spiele) == [(0, 1), (1, 0)]

    def test_kein_spiel_zweimal(self):
        bloecke = [soll(1, "A", [9, 9, 9]), soll(3, "B", [9, 9, 9])]
        spiele = [lauf(1, [9, 9, 9]), lauf(2, [5, 5, 5])]
        gewaehlt = [j for _, j in paare_block_spiel(bloecke, spiele)]
        assert sorted(gewaehlt) == [0, 1]


class TestVergleichImBlock:
    def test_ueber_die_wurfnummer_der_tafel(self):
        block = soll(1, "A", [9, 8, 7])
        paare = vergleiche_block(block, lauf(1, [9, 8, 7]))
        assert all(w["pins_count"] == s["kegel"] for w, s in paare)

    def test_ein_verlorener_wurf_verschiebt_nichts(self):
        """DAS ist der Grund fuer den Umbau. Fehlt Wurf 2, darf das Wurf 3
        nicht zu Wurf 2 machen -- sonst wird aus einem Fehler ein Dutzend."""
        block = soll(1, "A", [9, 8, 7, 6])
        ohne_zwei = [w for w in lauf(1, [9, 8, 7, 6])
                     if w["throw_number"] != 2]
        paare = vergleiche_block(block, ohne_zwei)
        fehlt = [s for w, s in paare if w is None]
        falsch = [s for w, s in paare
                  if w is not None and s is not None
                  and w["pins_count"] != s["kegel"]]
        assert [s["wurf"] for s in fehlt] == [2]
        assert falsch == []

    def test_ein_wurf_zuviel_wird_gemeldet(self):
        block = soll(1, "A", [9, 8])
        paare = vergleiche_block(block, lauf(1, [9, 8, 7]))
        assert sum(1 for w, s in paare if s is None) == 1

    def test_ohne_zugeordnetes_spiel_fehlt_alles(self):
        paare = vergleiche_block(soll(1, "A", [9, 8]), None)
        assert all(w is None for w, _ in paare)


class TestDieZahlDieZaehlt:
    @pytest.mark.parametrize("weg,erwartet", [("Wurfnummer", 3)])
    def test_die_wurfnummer_ist_der_schluessel(self, weg, erwartet):
        """Sie stammt aus der Tafel -- weder aus unseren Lampen noch aus dem
        Protokoll. Damit ist die Zuordnung im Block nicht selbstbestaetigend.
        """
        block = soll(1, "A", [9, 8, 7])
        gedreht = list(reversed(lauf(1, [9, 8, 7])))
        paare = vergleiche_block(block, gedreht)
        treffer = sum(1 for w, s in paare
                      if w and s and w["pins_count"] == s["kegel"])
        assert treffer == erwartet
