"""Das mitlaufende Wurfprotokoll (wuerfe.csv).

WARUM ES DAS GIBT: Ein Lauf schrieb vorher nur die Gruenspur und die
Ereignisbilder. Die Wurfergebnisse gab es ausschliesslich ueber die Werkzeuge,
also erst in einem ZWEITEN Durchlauf ueber dasselbe Video. An einem Spieltag
laeuft die Analyse aber genau einmal, live -- und danach muss nachlesbar sein,
was sie gesehen hat.

Der wichtigste Test ist deshalb nicht, DASS geschrieben wird, sondern dass die
Datei auch dann brauchbar ist, wenn der Lauf mittendrin endet.
"""

from __future__ import annotations

import csv

from kegel_cv.debug.throw_log import ThrowLog
from kegel_cv.models.throw import (
    Evidence,
    FrameRef,
    FrameRole,
    PlausibilityCheck,
    ThrowResult,
    ThrowStatus,
)


def wurf(lane: int = 2, nummer: int = 1, kegel: tuple[int, ...] = (1, 2, 3),
         status: ThrowStatus = ThrowStatus.VALID,
         gescheiterte_pruefung: bool = False,
         quelle: str | None = None) -> ThrowResult:
    checks = [PlausibilityCheck("Lampen == angezeigte Kegelzahl", 3, 3, True)]
    if gescheiterte_pruefung:
        checks.append(PlausibilityCheck("Summe der Tafel", 10, 7, False))
    roh = {"clearing": False, "displayed_total": 12,
           "baseline": {"count": 0, "pins": []}}
    if quelle:
        roh["source"] = quelle
    return ThrowResult(
        lane=lane, throw_number=nummer, throw_number_in_series=nummer,
        cycle_number=1, game_number=1, pins=kegel, pins_count=len(kegel),
        displayed_pin_count=len(kegel), status=status,
        running_total=len(kegel), series_total=None, confidence=0.95,
        timestamp=125.4, source_frame=3135,
        evidence=Evidence(frames=(FrameRef(3135, 125.4, FrameRole.GREEN_OFF),),
                          checks=tuple(checks), decisions=(), raw=roh),
    )


def lesen(pfad):
    with pfad.open(encoding="utf-8-sig", newline="") as datei:
        return list(csv.DictReader(datei, delimiter=";"))


class TestWurfprotokoll:
    def test_ein_wurf_landet_vollstaendig_in_der_zeile(self, tmp_path):
        protokoll = ThrowLog(tmp_path / "wuerfe.csv")
        protokoll.add(wurf(lane=4, nummer=7, kegel=(1, 3, 5, 9)))
        protokoll.close()

        zeilen = lesen(tmp_path / "wuerfe.csv")
        assert len(zeilen) == 1
        z = zeilen[0]
        assert z["Bahn"] == "4"
        assert z["Kegel"] == "4"
        assert z["Kegelnummern"] == "1 3 5 9"
        assert z["Wurfnummer"] == "7"
        assert z["Frame"] == "3135"
        assert z["Zeit"] == "2:05", "die Videozeit zum Nachschlagen im Bild"
        assert z["Status"] == "VALID"

    def test_datei_ist_schon_vor_dem_schliessen_lesbar(self, tmp_path):
        """Der eigentliche Zweck: Bricht der Lauf ab, ist nichts verloren.

        Eine Datei, die erst am Ende geschrieben wird, ist genau dann leer,
        wenn man sie am dringendsten braucht.
        """
        protokoll = ThrowLog(tmp_path / "wuerfe.csv")
        protokoll.add(wurf(nummer=1))
        protokoll.add(wurf(nummer=2))
        # BEWUSST kein close() -- der Lauf haengt noch

        zeilen = lesen(tmp_path / "wuerfe.csv")
        assert len(zeilen) == 2, "beide Wuerfe muessen schon auf der Platte sein"

    def test_gescheiterte_pruefungen_stehen_in_der_zeile(self, tmp_path):
        """Sonst muesste man fuer jeden Verdacht ins Text-Log zurueck."""
        protokoll = ThrowLog(tmp_path / "wuerfe.csv")
        protokoll.add(wurf(gescheiterte_pruefung=True))
        protokoll.close()

        assert "Summe der Tafel" in lesen(tmp_path / "wuerfe.csv")[0]["Pruefungen"]

    def test_herkunft_wird_ausgewiesen(self, tmp_path):
        """Ein Wurf ohne Lampenmessung muss sagen, woher er kommt -- sonst
        sieht er aus wie ein Fehler."""
        protokoll = ThrowLog(tmp_path / "wuerfe.csv")
        protokoll.add(wurf(kegel=(), quelle="fehlwurfzaehler"))
        protokoll.add(wurf(nummer=2))
        protokoll.close()

        zeilen = lesen(tmp_path / "wuerfe.csv")
        assert zeilen[0]["Herkunft"] == "fehlwurfzaehler"
        assert zeilen[1]["Herkunft"] == "gruenzyklus"

    def test_abschaltbar(self, tmp_path):
        protokoll = ThrowLog(tmp_path / "wuerfe.csv", aktiv=False)
        protokoll.add(wurf())
        protokoll.close()

        assert not (tmp_path / "wuerfe.csv").exists()

    def test_schreibfehler_stoppt_die_analyse_nicht(self, tmp_path):
        """P8: Ein Protokollierungsfehler darf die Auswertung nicht anhalten."""
        protokoll = ThrowLog(tmp_path / "gibt-es-nicht" / "x" / "wuerfe.csv")
        protokoll.pfad = tmp_path      # ein Verzeichnis, keine Datei
        protokoll.add(wurf())          # darf nicht werfen
        protokoll.close()

        assert protokoll.aktiv is False
