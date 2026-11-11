"""Wacht darueber, dass die Lampen ueberhaupt noch etwas melden.

WARUM ES DIESE DATEI GIBT

Am 2026-09-07 lief eine Analyse ueber 67 Wuerfe, ohne dass auf einer der vier
Bahnen auch nur EINE Lampe ansprach. Jeder Wurf wurde als "0 Kegel" gebucht und
so an die Datenbank geschickt. Die Ursache war eine alte Kalibrierung mit
doppelt so grossen Lampen-ROIs (0,080 x 0,075 statt 0,040 x 0,0375): Der
Detektor mittelt ueber den Ausschnitt, und der dunkle Ring um die Lampe zog den
Mittelwert von 250 auf 203 -- knapp unter die Schwelle von 206.

Das Programm hat das nicht gemerkt. Es stand zwar in jeder Logzeile
("Lampen zeigen 0, Anzeige 9"), aber nirgends stand, dass hier etwas
GRUNDSAETZLICH nicht stimmt. Genau solche lautlosen Ausfaelle kosten einen
ganzen Spieltag -- der Fehler faellt erst beim Auswerten auf, wenn niemand mehr
nachkalibrieren kann.

DIE PRUEFUNG

Gemeldet wird nicht "0 Kegel" -- das ist ein regulaeres Ergebnis (Pumpe). Auch
nicht "wenige Kegel" -- das waere Geschmackssache. Gemeldet wird der
WIDERSPRUCH zwischen zwei unabhaengigen Quellen: Die Lampen sagen null, die
Anzeigetafel sagt etwas anderes als null. Ein einzelner solcher Fall ist
Rauschen; mehrere hintereinander auf derselben Bahn sind es nicht.

Das folgt P1 (Nachvollziehbarkeit) und der Regel, bei widerspruechlichen
Quellen keine "wegzuentscheiden": Der Widerspruch existiert, um Fehler zu
zeigen -- hier zeigt er einen.
"""

from __future__ import annotations

import logging

from ..models.throw import ThrowResult

log = logging.getLogger(__name__)


class LampWatchdog:
    """Zaehlt je Bahn, wie oft Lampen und Anzeige einander widersprechen.

    Bewusst ohne I/O und ohne Konfigurationsobjekt: Die Klasse laesst sich so
    ohne Video, ohne Kalibrierung und ohne Pipeline pruefen.
    """

    def __init__(self, threshold: int = 5) -> None:
        if threshold < 1:
            raise ValueError("threshold muss mindestens 1 sein")
        self.threshold = threshold
        self._streak: dict[int, int] = {}
        self._reported: set[int] = set()

    def streak(self, lane: int) -> int:
        """Wie viele Widersprueche auf dieser Bahn zuletzt aufeinander folgten."""
        return self._streak.get(lane, 0)

    def observe(self, throw: ThrowResult) -> str | None:
        """Nimmt einen Wurf auf und liefert EINMAL je Bahn eine Meldung.

        Rueckgabe ist der fertige Meldungstext oder None. Dass die Klasse den
        Text zurueckgibt statt selbst zu protokollieren, hat einen Grund: So
        laesst sich im Test pruefen, WAS gemeldet wird, ohne Logs abzufangen.
        """
        lane = throw.lane
        angezeigt = throw.displayed_pin_count

        # Ohne zweite Quelle gibt es keinen Widerspruch -- weder zaehlen noch
        # zuruecksetzen. Eine fehlende Quelle ist etwas anderes als eine
        # widersprechende.
        if angezeigt is None:
            return None

        # JEDE Abweichung zaehlt, nicht nur die auf null.
        #
        # ERWEITERT am 2026-09-08. Der erste Entwurf schlug nur an, wenn die
        # Lampen NULL meldeten -- weil der Ausfall vom 2026-09-07 so aussah.
        # Am naechsten Abend sah derselbe Defekt anders aus: Die Lampen meldeten
        # 5, waehrend die Tafel 8 zeigte, dann 3 gegen 8, dann 2 gegen 7. Eine
        # einzige leuchtende Lampe genuegte, um den Zaehler zurueckzusetzen --
        # und der Wachhund schwieg einen ganzen Trainingsabend lang, obwohl in
        # jeder zweiten Zeile ein Widerspruch stand.
        #
        # Was beide Faelle verbindet, ist nicht die Null, sondern dass die
        # Lampen dauerhaft WENIGER melden als die Tafel.
        #
        # NUR DIESE RICHTUNG. Mehr Lampen als Ziffern ist ein regulaerer
        # Raeumwurf: Die Lampen zeigen alle liegenden Kegel, die Tafel nur
        # die dieses Wurfs (gemessen: vier Wuerfe mit neun Lampen gegen
        # Ziffer 1, 2, 3 und 4 -- die Ziffer hatte jedes Mal recht).
        # Diese Richtung zu melden hiesse, jeden Raeumwurf anzuschwaerzen.
        if throw.pins_count < angezeigt:
            self._streak[lane] = self._streak.get(lane, 0) + 1
        else:
            # Uebereinstimmung ist der Beweis, dass die Messung grundsaetzlich
            # funktioniert -- die Kette beginnt von vorn.
            self._streak[lane] = 0
            return None

        if self._streak[lane] < self.threshold or lane in self._reported:
            return None

        self._reported.add(lane)
        if throw.pins_count == 0:
            ursache = (
                "Die Lampen melden NULL, waehrend die Tafel Kegel zeigt. Sehr "
                "wahrscheinlich sitzen die Lampen-ROIs falsch oder sind zu "
                "gross: Ein zu grosser Ausschnitt mittelt die leuchtende Lampe "
                "mit ihrer dunklen Umgebung und bleibt unter der Schwelle. "
                "BITTE DIE KALIBRIERUNG PRUEFEN, Sollgroesse 0,040 x 0,0375."
            )
        else:
            ursache = (
                "Die Lampen melden durchgehend eine ANDERE Zahl als die Tafel. "
                "Zu pruefen: Passen die Schwellen zu dieser Quelle? An einer "
                "ausgebrannten Tafel verwirft die Waermeschranke leuchtende "
                "Lampen, obwohl die Helligkeit stimmt -- dann steht im "
                "Lampenprotokoll UNKNOWN bei Helligkeit 255. Welche "
                "Konfiguration geladen ist, steht in der ersten Logzeile."
            )
        return (
            f"Bahn {lane}: {self._streak[lane]} Wuerfe in Folge widersprechen "
            f"einander -- Lampen {throw.pins_count}, Anzeigetafel {angezeigt}. "
            f"Das ist kein Spielverlauf, sondern ein Messfehler. {ursache} "
            f"Die Analyse laeuft weiter, die Ergebnisse dieser Bahn sind aber "
            f"nicht verlaesslich."
        )

    def observe_and_log(self, throw: ThrowResult) -> bool:
        """Wie `observe`, schreibt die Meldung aber gleich ins Log.

        Bewusst als ERROR und nicht als WARNING: Eine Bahn, die nichts mehr
        misst, ist kein Schoenheitsfehler.
        """
        meldung = self.observe(throw)
        if meldung is None:
            return False
        log.error("%s", meldung)
        return True
