"""Geführtes Lesen der Summe -- die Anzeige wird gefragt, nicht geraten.

DIE IDEE (Nutzer, 2026-09-15): *"Können wir nicht irgendwie vielleicht
geführtes Lesen der Summe machen? So im Sinne von, naja -> gerade standen wir
bei 0172 -> jetzt melden Ziffer und Lampen eine 3 -> sicher dass du hier eine
8176 melden willst und nicht eher eine 0175?"*

Der Ziffernleser meldet je Stelle nicht nur ein Zeichen, sondern auch, ZWISCHEN
WELCHEN Ziffern er schwankte (`DigitReading.candidates`, siehe
`digit_reader.segment_candidates`). Diese Kandidaten sind bisher nur bei der
Kegelziffer genutzt worden. Bei der Summe sind sie mehr wert, denn dort gibt es
eine Erwartung: Der Stand vor dem Wurf ist bekannt, die gefallenen Kegel auch.

DIE RICHTUNG ENTSCHEIDET ÜBER DIE EHRLICHKEIT

Eine Erwartung darf zwischen den Kandidaten WÄHLEN -- sie darf keine Ziffer
setzen, die die Messung ausschließt. Deshalb wird hier nichts "korrigiert";
gefragt wird in dieser Reihenfolge:

    1. Welche Werte lässt die Anzeige zu, ohne die Systematik zu verletzen?

       keiner   -> UNMÖGLICH. Die Lesung wird verworfen, nicht geglättet.
       genau 1  -> EINDEUTIG. Die Anzeige hat sich selbst erklärt; die Lampen
                   wurden nicht gebraucht. Der Wert bleibt ein eigener Zeuge,
                   auch wenn er der Erwartung widerspricht -- gerade dann.
       mehrere  -> die Anzeige allein entscheidet es nicht. Weiter zu 2.

    2. Ist der erwartete Wert (Stand + gefallene Kegel) darunter?

       ja   -> GEFÜHRT. Der Wert wird gebucht, gilt aber nicht als Zeuge:
               Er wurde aus den Lampen gewonnen.
       nein -> WIDERSPRUCH. Die Anzeige lässt Werte zu, aber keinen, den die
               Lampen erklären. Auch das wird gemeldet.

Die Reihenfolge ist keine Geschmacksfrage. Würde die Erwartung zuerst gefragt,
verlöre jede Summe ihren Beweiswert, sobald sie zufällig passt -- auch eine,
die aus sich heraus vollkommen eindeutig war. `Deutung.unabhaengig` hält beides
auseinander: Wer einen geführten Wert als Bestätigung zählte, ließe zwei
Messungen zu einer verschmelzen und hielte das Ergebnis für doppelt belegt.

WAS DIE SUMME SYSTEMATISCH TUN MUSS

Der Nutzer, nachdem eine feste Obergrenze von 9 * 30 = 270 zur Debatte stand:
*"es ist nur der Regelfall, wer weiß was manche Leute im Training oder so
machen, also bitte keine harte Grenze einbauen.... eher das systematische
fördern, es muss eigentlich immer mit 0 losgehen und dann steigen."*

Genau das wird geprüft, und nur das:

    sie beginnt bei null
    sie fällt nie
    sie steigt je Wurf um höchstens `pin_count`

Daraus folgt eine Schranke, die MITWÄCHST statt festzustehen: Nach N Würfen
kann höchstens `N * pin_count` auf der Tafel stehen. Beim ersten Wurf eines
Spiels ist das die Null, nach dreißig Würfen sind es 270 -- und wer im Training
hundert Würfe macht, wird nicht ausgebremst.

GEMESSEN am Hallenmitschnitt (13.530 Frames, jeder zehnte gelesen, 1.353
Summenlesungen je Bahn; die Wurfnummer der Tafel liefert die Schranke):

    Bahn    eindeutig   widerspruch   unmöglich
      2           35            36        1250
      3         1332             4          12
      4         1202            21         107
      5          391           922          36

"Eindeutig" heißt: Die Systematik ließ genau einen Wert zu, die Lesung war
damit aufgelöst -- OHNE die Lampen zu befragen. Auf Bahn 3 und 4 trägt das
89 bis 98 % der Lesungen. Bahn 2 fällt dagegen in 92 % der Fälle durch: Dort
stimmt etwas am Feld selbst nicht (Werte wie 2823, 3237, 3813). Die Regel
korrigiert das nicht -- sie macht es sichtbar, und das ist ihre Aufgabe.

Bahn 5 zeigt den dritten Fall: 922 Widersprüche heißt nicht "falsch", sondern
"mehrere Werte wären möglich, und ohne Erwartung ist keiner zu bevorzugen".
Dort hilft erst die Führung durch die Lampen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Wie die Deutung zustande kam -- entscheidend fuer ihren Beweiswert.
VERANKERT = "verankert"        # erste brauchbare Lesung, setzt den Stand
GEFUEHRT = "gefuehrt"          # die Erwartung passte zur Anzeige
EINDEUTIG = "eindeutig"        # die Anzeige laesst genau einen anderen Wert zu
WIDERSPRUCH = "widerspruch"    # mehrere moeglich, aber die Erwartung nicht
UNMOEGLICH = "unmoeglich"      # gar kein systematisch zulaessiger Wert passt
STUMM = "stumm"                # nichts gelesen


def erlaubte_ziffern(lesung, stelle: int) -> tuple[int, ...]:
    """Welche Ziffern kann an dieser Stelle gestanden haben?

    Grundlage ist das gemeldete Zeichen VEREINIGT mit den Kandidaten. Beides
    zusammen, weil der Leser bei einem unbekannten Segmentmuster auf das
    naechstliegende ausweicht (`read_digit_full`) -- dann steht in `digits` ein
    Wert, der nicht unter den Kandidaten auftaucht. Ihn zu unterschlagen hiesse,
    die Messung enger zu machen, als sie ist; das erzeugte Widersprueche, wo
    keine sind.

    Eine Stelle ohne jede Aussage ("?" ohne Kandidaten) laesst alles zu.
    """
    erlaubt: set[int] = set()
    zeichen = lesung.digits[stelle] if stelle < len(lesung.digits) else "?"
    if zeichen.isdigit():
        erlaubt.add(int(zeichen))
    if stelle < len(lesung.candidates):
        erlaubt.update(lesung.candidates[stelle])
    if not erlaubt:
        return tuple(range(10))
    return tuple(sorted(erlaubt))


def passt_zur_lesung(lesung, wert: int) -> bool:
    """Kann die Anzeige diesen Wert gezeigt haben?

    Der Wert wird auf die Stellenzahl des Feldes mit Nullen aufgefuellt -- die
    Tafel zeigt fuehrende Nullen ("0172"), also muss der Vergleich das auch tun.
    """
    stellen = len(lesung.digits)
    if stellen == 0 or wert < 0:
        return False
    text = str(wert).zfill(stellen)
    if len(text) > stellen:
        return False           # passt nicht einmal in das Feld
    return all(int(z) in erlaubte_ziffern(lesung, i)
               for i, z in enumerate(text))


def moegliche_werte(lesung, von: int, bis: int) -> tuple[int, ...]:
    """Alle Werte in [von, bis], die zur Anzeige passen.

    Der Bereich ist im Gebrauch klein (ein Wurf weit), deshalb wird er
    durchgezaehlt statt die Kandidaten zu kombinieren -- das ist einfacher zu
    lesen und kann nicht kombinatorisch entgleisen.
    """
    if bis < von:
        return ()
    return tuple(w for w in range(max(0, von), bis + 1)
                 if passt_zur_lesung(lesung, w))


@dataclass
class Deutung:
    """Was aus einer Summenlesung wurde."""

    wert: int | None
    art: str
    bemerkung: str = ""

    @property
    def unabhaengig(self) -> bool:
        """Darf dieser Wert als eigener Zeuge auftreten?

        Ein gefuehrter Wert nicht: Er wurde aus den Lampen gewonnen und kann
        sie deshalb nicht bestaetigen.
        """
        return self.art in (VERANKERT, EINDEUTIG)

    @property
    def brauchbar(self) -> bool:
        return self.wert is not None


@dataclass
class Summenspur:
    """Die Summe EINER Bahn ueber ein Spiel hinweg.

    Sie ist bewusst nachsichtig: Passt nichts, wird nichts gebucht und der
    Stand bleibt, wie er war. Ein Lesefehler soll die Spur nicht entgleisen
    lassen -- sonst waere ein einziger falscher Frame teurer als gar keine
    Fuehrung.
    """

    pin_count: int = 9
    stand: int | None = None
    wuerfe: int = 0
    # Nach wie vielen unmoeglichen Lesungen in Folge der Stand aufgegeben wird.
    # GEMESSEN: Bahn 5 verankerte sich auf eine 0 aus Frame 230 und hielt
    # danach 1352 von 1353 Lesungen fuer unmoeglich -- ein falscher Anker ist
    # ohne Notausgang endgueltig. Drei Lesungen sind rund eine Sekunde; ein
    # einzelner Flackerframe reicht damit nicht zum Verwerfen.
    geduld: int = 3
    _irrtuemer: int = 0
    # Wie oft die Fuehrung gegriffen hat -- fuer den Bericht.
    zaehler: dict[str, int] = field(default_factory=dict)

    def _zaehle(self, art: str) -> None:
        self.zaehler[art] = self.zaehler.get(art, 0) + 1

    @property
    def obergrenze(self) -> int:
        """Was nach den bisherigen Wuerfen hoechstens dort stehen kann.

        Keine feste Zahl, sondern eine mitwachsende: `wuerfe * pin_count`.
        Vor dem ersten Wurf ist das null -- die Summe muss mit null beginnen.
        Nach dreissig Wuerfen sind es 270, nach hundert 900; ein langer
        Trainingsabend laeuft nicht gegen eine Wand.
        """
        return self.wuerfe * self.pin_count

    def kennt_wurfnummer(self, nummer: int | None) -> None:
        """Die Tafel sagt selbst, der wievielte Wurf gerade laeuft.

        Das ist der einzige Weg, mitten in ein Spiel einzusteigen: Ohne diese
        Angabe muesste die Spur annehmen, sie habe von Anfang an zugesehen, und
        wuerde jeden Stand ueber `wuerfe * pin_count` fuer unmoeglich halten.
        GEMESSEN am Hallenmitschnitt: Bahn 2 stand beim ersten lesbaren Frame
        bereits bei 117.
        """
        if nummer is not None and nummer > self.wuerfe:
            self.wuerfe = nummer

    def neues_spiel(self) -> None:
        """Spielwechsel -- die Spur faengt wieder bei null an."""
        self.stand = None
        self.wuerfe = 0
        self._irrtuemer = 0

    def deute(self, lesung, gefallen: int | None = None,
              wuerfe_seither: int = 1) -> Deutung:
        """Deutet eine Summenlesung im Licht dessen, was bisher geschah.

        `gefallen` sind die Kegel, die seit dem Stand gefallen sein muessten --
        bei der Tafel mit ihrem Nachlauf also die des VORHERIGEN Wurfs. Ist das
        unbekannt (`None`), gibt es keine Erwartung, und es bleibt bei der
        Systematik: Die Summe kann seither nur gestiegen sein, hoechstens um
        `wuerfe_seither * pin_count`.
        """
        if lesung is None or not lesung.digits:
            self._zaehle(STUMM)
            return Deutung(None, STUMM, "keine Lesung")

        if self.stand is None:
            return self._verankere(lesung)

        spielraum = max(0, wuerfe_seither) * self.pin_count

        # ERST DIE SYSTEMATIK, DANN DIE ERWARTUNG. Die Reihenfolge ist keine
        # Geschmacksfrage, sie entscheidet ueber den Beweiswert: Laesst die
        # Anzeige ohnehin nur einen Wert zu, wurden die Lampen nicht gebraucht
        # -- die Summe bleibt dann ein eigener Zeuge. Erst wenn mehrere Werte
        # moeglich sind, muss die Erwartung waehlen, und ab da ist die Summe
        # keine unabhaengige Messung mehr.
        moeglich = moegliche_werte(lesung, self.stand, self.stand + spielraum)

        if not moeglich:
            self._zaehle(UNMOEGLICH)
            self._irrtuemer += 1
            gewesen = self.stand
            zusatz = ""
            if self._irrtuemer >= self.geduld:
                # Nicht die Anzeige irrt, sondern der Anker. Einmal falsch
                # verankert waere die Spur sonst fuer den Rest des Spiels
                # blind -- lieber den Stand aufgeben und neu suchen.
                self.stand = None
                self._irrtuemer = 0
                zusatz = (f"; Stand {gewesen} nach {self.geduld} "
                          f"unmoeglichen Lesungen aufgegeben")
            return Deutung(
                None, UNMOEGLICH,
                f"Anzeige laesst keinen Wert in "
                f"{gewesen}..{gewesen + spielraum} zu "
                f"(roh {lesung.value}){zusatz}")

        self._irrtuemer = 0

        if len(moeglich) == 1:
            # ACHTUNG, HIER LAG EIN FEHLER (2026-09-15, vom Nutzer bemerkt).
            #
            # "Genau ein Wert passt ins Fenster" heisst NICHT "die Anzeige ist
            # eindeutig". Es heisst nur: von den Werten, die das Fenster
            # zulaesst, passt einer. Ist das Fenster falsch -- weil der Stand
            # veraltet ist --, dann wird ein NEBENKANDIDAT der Lesung
            # hineingezwungen und als sicher gemeldet.
            #
            # GEMESSEN auf Bahn 4, F5695-6070: Die Tafel zeigte nachweislich
            # `0133` (siehe `debug/summe_bahn4.gif`). Der Stand stand noch auf
            # 116, das Fenster reichte bis 125. Aus der Lesung `01?3` passte
            # dort nur 123 -- und genau das wurde als "eindeutig" gebucht.
            # Daraus entstand der falsche Befund, die Tafel haenge zwei Wuerfe
            # zurueck.
            #
            # Eindeutig ist eine Lesung nur, wenn ihre EIGENE beste Lesart im
            # Fenster liegt. Tut sie das nicht, ist das ein Widerspruch
            # zwischen Anzeige und Spur -- und der gehoert gemeldet, nicht
            # stillschweigend aufgeloest.
            eigene = lesung.value
            if eigene is not None and eigene != moeglich[0]:
                self._zaehle(WIDERSPRUCH)
                return Deutung(
                    None, WIDERSPRUCH,
                    f"Anzeige liest {eigene}, das Fenster "
                    f"{self.stand}..{self.stand + spielraum} laesst nur "
                    f"{moeglich[0]} zu -- nicht entscheidbar")

            vorher, self.stand = self.stand, moeglich[0]
            self._zaehle(EINDEUTIG)
            hinweis = ("" if moeglich[0] == eigene
                       else f"unlesbare Stelle aufgeloest zu {moeglich[0]}")
            if gefallen is not None and moeglich[0] != vorher + gefallen:
                hinweis = (f"erwartet war {vorher + gefallen}, die Anzeige "
                           f"laesst nur {moeglich[0]} zu")
            return Deutung(moeglich[0], EINDEUTIG, hinweis)

        if gefallen is not None:
            erwartet = self.stand + gefallen
            if erwartet in moeglich:
                self.stand = erwartet
                self._zaehle(GEFUEHRT)
                hinweis = f"aus {list(moeglich)} gewaehlt"
                if lesung.value != erwartet:
                    hinweis = (f"rohe Lesung {lesung.value} verworfen, "
                               f"Anzeige laesst {erwartet} zu")
                return Deutung(erwartet, GEFUEHRT, hinweis)
            self._zaehle(WIDERSPRUCH)
            return Deutung(
                None, WIDERSPRUCH,
                f"erwartet war {erwartet}, moeglich sind {list(moeglich)}")

        self._zaehle(WIDERSPRUCH)
        return Deutung(
            None, WIDERSPRUCH,
            f"ohne Erwartung nicht zu entscheiden, moeglich sind "
            f"{list(moeglich)}")

    def _verankere(self, lesung) -> Deutung:
        """Die erste Buchung -- hier gibt es keine Erwartung, nur die Regel.

        Zulaessig ist alles zwischen null und dem, was in den bisherigen
        Wuerfen ueberhaupt erreichbar war. Beim allerersten Wurf ist das nur
        die Null selbst.
        """
        moeglich = moegliche_werte(lesung, 0, self.obergrenze)
        if not moeglich:
            self._zaehle(UNMOEGLICH)
            return Deutung(
                None, UNMOEGLICH,
                f"Lesung {lesung.value} liegt ausserhalb 0..{self.obergrenze}, "
                f"was nach {self.wuerfe} Wuerfen erreichbar waere")
        if len(moeglich) > 1:
            # Ohne Stand gibt es nichts zu entscheiden. Der GROESSTE Wert waere
            # geraten; lieber weiter warten, bis ein Wurf die Wahl einengt.
            self._zaehle(WIDERSPRUCH)
            return Deutung(
                None, WIDERSPRUCH,
                f"noch kein Stand, und die Anzeige laesst {len(moeglich)} "
                f"Werte zu")
        self.stand = moeglich[0]
        self._zaehle(VERANKERT)
        return Deutung(moeglich[0], VERANKERT,
                       f"Stand auf {moeglich[0]} gesetzt")

    def buche_wurf(self) -> None:
        """Ein Wurf ist gefallen -- die Schranke waechst mit."""
        self.wuerfe += 1
