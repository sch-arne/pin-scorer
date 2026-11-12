"""Uebersetzt ein Wurfergebnis in eine flache Zeile fuer die Datenbank.

Bewusst FLACH und ohne verschachtelte Strukturen: Die Zeile soll sich in einer
Tabelle ansehen und filtern lassen, ohne dass die lesende Anwendung JSON
auspacken muss. Der Spielleiter vor Ort schaut auf eine Tabelle, nicht auf ein
Dokument.

Die vollstaendige Beweiskette bleibt als `evidence` erhalten -- sie wird
gebraucht, wenn ein Ergebnis angezweifelt wird, steht aber nicht im Weg.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models.throw import ThrowResult


def throw_to_row(throw: ThrowResult, video_id: str = "",
                 mit_bild: bool = True,
                 mit_vorher: bool = False,
                 game_name: str = "",
                 game_name_column: str = "game_name") -> dict[str, Any]:
    """Baut die Datenbankzeile eines Wurfs -- bewusst KNAPP.

    Uebertragen wird nur, was GEMESSEN ist:

        Bahn | Anzahl Kegel | Kegelnummern | Zeitstempel

    Alles andere -- laufende Summe, Zyklus, Spielnummer, Wurfnummer,
    Zwischensummen -- wird zwar weiterhin berechnet und in der Oberflaeche
    angezeigt, aber NICHT gesendet. Der Grund ist die Erfahrung aus diesem
    Projekt: Genau diese abgeleiteten Groessen sind schiefgegangen.

    - Die Wurfnummer aus der Anzeige loeschte 28 % der Wuerfe (BUG-008)
    - Die Spielerkennung nach 30 Wuerfen traf den Bahnwechsel nicht
    - Die laufende Summe driftete von der Tafel ab, sobald ein Wurf fehlte

    Diese Groessen setzen Regelwissen voraus, das die auswertende Anwendung
    besser kennt als die Bilderkennung: wann ein Bahnwechsel ansteht, wann ein
    Spiel endet, wie gewertet wird. Was hier gemessen wird, ist allein: Auf
    dieser Bahn sind zu diesem Zeitpunkt diese Kegel gefallen.

    Vom Nutzer so festgelegt (2026-08-26).

    ERGAENZUNG 2026-09-14: Dazu kommen vier ABLESUNGEN DER TAFEL, alle
    nullbar. Der Unterschied zu den oben verworfenen Groessen ist wesentlich:

        verworfen  abgeleitet -- laufende Summe, Zyklus, Spielnummer.
                   Sie setzen Regelwissen voraus und sind genau daran
                   gescheitert.
        neu        abgelesen -- was auf der Tafel STAND. Keine Rechnung,
                   keine Regel, kein Zustand ueber mehrere Wuerfe hinweg.

    Der Nutzer dazu: *"nullable mitsenden, dann kann jeder selbst entscheiden,
    was er macht."* `None` heisst "nicht sicher gelesen" und ist ein gueltiger
    Zustand -- die lesende Anwendung muss damit rechnen. Wer sie zum Rechnen
    benutzt, tut das auf eigene Verantwortung; `pins_count` bleibt die einzige
    gemessene Wahrheit.

    `total_a` faehrt bewusst NICHT mit: Der Nutzer nennt es "irgendwie Quatsch
    fuer uns", es hat als einziges Feld keine Ziffernzellen kalibriert, und es
    geht in keine Pruefung ein.
    """
    row = {
        "video_id": video_id,
        "lane": throw.lane,
        "pins_count": throw.pins_count,
        "pins": list(throw.pins),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        # Zeitpunkt IM VIDEO -- ordnet die Wuerfe auch dann richtig, wenn
        # nachtraeglich eine Aufzeichnung ausgewertet wird.
        "video_time_s": round(throw.timestamp, 2),
    }
    # Was die Tafel im Moment des Wurfs zeigte. Nur Beleg -- siehe oben.
    # Immer gesetzt, auch als None: Eine fehlende Spalte und eine leere Spalte
    # sind fuer die lesende Anwendung zweierlei, und "nicht gelesen" ist eine
    # Aussage.
    row["displayed_throw_number"] = throw.displayed_throw_number
    row["displayed_pin_count"] = throw.displayed_pin_count
    row["displayed_foul_count"] = throw.displayed_foul_count
    row["displayed_total"] = throw.displayed_total
    # Der Beleg zum Ergebnis: die eingemessene Anzeigetafel als Base64-JPEG.
    # Nur wenn es eines gibt -- ein fehlendes Bild darf den Wurf nicht
    # aufhalten (P8). Der Ticker holt die Spalte nur fuer den Wurf, den
    # jemand anklickt; die Liveliste laedt sie nicht mit.
    if mit_bild and throw.board_image:
        row["board_jpeg"] = throw.board_image
    if mit_bild and mit_vorher and throw.board_image_before:
        row["board_before_jpeg"] = throw.board_image_before
    # DER SPIELNAME, den der Nutzer vergeben hat -- neben `video_id`, nicht
    # an deren Stelle. `video_id` sagt, WELCHER SENSOR geliefert hat, der
    # Spielname, WELCHE PARTIE es war. Im Multisensor-Aufbau schreiben beide
    # Geraete denselben Namen und bleiben trotzdem unterscheidbar.
    #
    # Nur wenn einer vergeben wurde: Eine leere Spalte mitzuschicken hiesse,
    # eine Aussage zu machen, wo keine ist.
    if game_name and game_name_column:
        row[game_name_column] = game_name
    return row
