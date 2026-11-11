"""Auswertung eines Sampling-Ereignisses zu einem Wurfergebnis (Phase 8/9).

Hier laufen alle Quellen zusammen:

    Kegellampen (zuverlaessig)  --+
    Ziffernfelder (unsicher)    --+--> Plausibilitaetspruefung --> ThrowResult
    Wurfnummer der Tafel        --+
    laufende Summe              --+

**Die Lampen sind die Hauptquelle** fuer die Kegelanzahl, nicht die Ziffern. Das
ist am Material begruendet: Die Lampenerkennung reproduziert den Sollzustand
exakt (Waerme trennt mit Faktor 3), waehrend die Ziffernerkennung bei 13x18 px
je Ziffer nur rund 60 % erreicht. Die Ziffern dienen als **Gegenprobe** -- sie
koennen einen Wurf bestaetigen oder in Frage stellen, aber sie ersetzen die
Lampen nicht.

Bei Widerspruch wird keine Quelle "weggewaehlt": Das Ergebnis behaelt beide
Werte, die Confidence sinkt, und der Fall wird protokolliert. Die Redundanz
existiert, um Fehler zu zeigen.
"""

from __future__ import annotations

import logging

from ..config.schema import AppConfig
from ..models.readings import PinLampReading
from ..models.scoring import LaneScore, cycle_number, is_cycle_end, throw_in_cycle
from ..models.throw import (
    Evidence,
    FrameRef,
    FrameRole,
    PlausibilityCheck,
    ThrowResult,
    ThrowStatus,
)
from .frame_sampler import SampleEvent

log = logging.getLogger(__name__)


class ThrowAnalyzer:
    """Baut aus einem Sampling-Ereignis ein Wurfergebnis. Eine Instanz je Bahn."""

    def __init__(self, lane_id: int, cfg: AppConfig, display_number: int | None = None) -> None:
        self.lane_id = lane_id
        self.display_number = display_number if display_number is not None else lane_id
        self.cfg = cfg
        self.score = LaneScore(lane=lane_id,
                               throws_per_cycle=cfg.scoring.throws_per_cycle)
        self._last_throw_number: int | None = None
        # Wuerfe seit dem letzten Spielwechsel. Zwei Zeugen melden denselben
        # Wechsel zu verschiedenen Zeitpunkten -- ohne diesen Abstand wird er
        # zweimal gebucht, und der erste Wurf des neuen Spiels landet allein
        # in einem eigenen Spiel.
        self._throws_since_game_change = 10 ** 6
        self._foul_count: int | None = None
        # Die zuletzt von der TAFEL gelesenen Staende -- nicht die intern
        # fortgezaehlten. Nur an ihnen laesst sich ablesen, ob die Anlage
        # ueberhaupt etwas registriert hat (siehe `_nichts_hat_sich_geregt`).
        self._last_read_throw_number: int | None = None
        self._last_read_foul_count: int | None = None

    # ------------------------------------------------------------- Auswertung

    def analyze(self, event: SampleEvent, pins: PinLampReading | None,
                baseline: PinLampReading | None = None,
                displayed_count: int | None = None,
                displayed_candidates: tuple[int, ...] = (),
                throw_number: int | None = None,
                displayed_total: int | None = None,
                foul_count: int | None = None,
                display_reset: bool = False,
                throw_number_confidence: float = 0.0,
                window_was_occluded: bool = False,
                throw_number_majority: tuple[int | None, float] = (None, 0.0),
                total_majority: tuple[int | None, float] = (None, 0.0)
                ) -> ThrowResult | None:
        """Wertet ein Ereignis aus.

        Args:
            event: abgeschlossenes Sampling-Ereignis.
            pins: Lampenmessung zum Zeitpunkt GREEN_OFF (Hauptquelle).
            baseline: Lampenstand zu Beginn des Wurfs (GREEN_ON). Beim RAEUMEN
                leuchten bereits Lampen, bevor geworfen wird -- diese Kegel
                gehoeren nicht zu diesem Wurf und werden abgezogen.
            displayed_count: Kegelanzahl laut Ziffernfeld (Gegenprobe, optional).
            displayed_candidates: Werte, zwischen denen die Ziffer schwankte,
                falls sie nicht eindeutig lesbar war. Die Lampen duerfen dann
                zwischen ihnen WAEHLEN -- aber keinen neuen Wert setzen.
            throw_number: Wurfnummer laut Tafel (optional, aber wertvoll --
                sie ist die einzige Quelle, die Double Counting fachlich
                ausschliesst).
            displayed_total: Summe laut Tafel (optional).
            foul_count: Fehlwurfzaehler laut Tafel (optional, Gegenprobe fuer
                Leerwuerfe -- siehe offene Frage Q2).
            throw_number_confidence: Wie einig sich die abgetasteten Frames
                ueber die Wurfnummer waren (0..1). NUR bei hoher Einigkeit darf
                ihr Stillstand einen Wurf verwerfen -- eine Fehllesung
                flackert, ein echter Stillstand nicht. Der Standardwert 0
                heisst "unbekannt" und verwirft nie.
            display_reset: Vor diesem Wurf stand die untere Reihe auf
                `000  0000`. Die Anlage hat damit ein neues Spiel begonnen --
                unabhaengig davon, welche Wurfnummer gelesen wurde.
            throw_number_majority: (Mehrheitswert, zeitliche Einigkeit) der
                Wurfnummer -- was die Frames MEHRHEITLICH gesehen haben, ohne
                Ruecksicht darauf, wie gut die Ziffern auf dem Bild zu erkennen
                waren. Bewusst getrennt von `throw_number_confidence`, die
                genau das Gegenteil misst (BUG-020).
            total_majority: (Mehrheitswert, Einigkeit) der Summe -- zweiter,
                unabhaengiger Zeuge fuer den Nullzustand der Anzeige (Q16).
            window_was_occluded: Die Tafel war irgendwann zwischen GREEN_OFF
                und GREEN_ON dieses Fensters verdeckt (siehe BUG-017). Ein
                Ergebnis von 0 Kegeln ist dann kein Messwert, sondern eine
                Luecke -- die Verdeckungsbremse friert die Lampenmessung ein,
                aber das Fenster kann trotzdem "fertig" werden.

        Returns:
            Das Wurfergebnis, oder None wenn der Wurf verworfen wurde
            (Doppelzaehlung).
        """
        checks: list[PlausibilityCheck] = []
        decisions: list[str] = []

        # WURFNUMMER 000 -- ES GAB KEINEN WURF, PUNKT (Nutzerbeobachtung,
        # 2026-09-03).
        #
        # Die Anlage zaehlt die Wurfnummer hoch, BEVOR der Einschlag im Bild
        # sichtbar wird -- ein Frame, bevor der Ball tatsaechlich trifft,
        # registriert die Lichtschranke den Wurf und die Anzeige springt auf
        # 001. Umgekehrt zwingend: Solange sie 000 zeigt, hat noch KEIN Wurf
        # stattgefunden. Das gilt unabhaengig davon, was die Kegellampen oder
        # die Kegelzahl-Ziffer in diesem Moment zeigen -- sie koennen noch das
        # ERGEBNIS des vorherigen Wurfs zeigen (siehe die 9, die auf Bahn 4 von
        # F30000 bis F30323 nachleuchtete, waehrend die Lampen laengst aus
        # waren).
        #
        # KORREKTUR (2026-09-03, voller Spieltag durchlaufen): Die vier
        # Wuerfe, die diese Regel urspruenglich beheben sollte -- die "21."
        # eines 20-Wurf-Warmwerf-Blocks, Bahn 3 F218448, Bahn 4 F126593,
        # Bahn 4 F218644, Bahn 5 F220170 -- zeigten GEMESSEN throw_number=21,
        # NICHT 000. Diese Regel hat im ganzen Lauf kein einziges Mal
        # gegriffen (0 Treffer im Log). Behoben sind sie seit dem
        # 2026-09-04 durch die 000/0000-Pruefung weiter unten (BUG-020): Die
        # Anzeige zeigte dort sehr wohl 000, nur kam die 0 wegen der
        # Confidence-Schwelle nie bei einer Regel an. Ein Zwischenversuch
        # (BUG-018) wurde zurueckgebaut, weil er nie griff und ausserdem
        # Wurf 21 eines regulaeren Satzes mitgefangen haette.
        #
        # Die Regel HIER bleibt trotzdem stehen: Sie ist eigenstaendig
        # sinnvoll fuer den Fall, den die urspruengliche Nutzerbeobachtung
        # meinte (Wurfzaehler springt VOR dem sichtbaren Einschlag auf 001;
        # das Gegenstueck davon ist Wurfnummer 000 nach dem letzten Wurf), nur
        # eben nicht fuer den Warmwerf-Sperrzyklus -- fuer DEN liest die
        # Anlage keine 000. WAS SIE ZEIGT, IST UNGEMESSEN: Erst die neue
        # CSV-Spalte `WurfnummerRoh` wird das beantworten.
        #
        # WARUM VOR `_resolve_throw_number` und nicht danach: Deren Fallback
        # ("Wurfnummer <= letzte -- vermutlich Lesefehler") zaehlt eine 0
        # sonst blind auf `letzte + 1` hoch, WENN der Ruecksprung-Erkennung
        # (`game_reset_after`/`game_reset_below`) aus irgendeinem Grund nicht
        # greift -- genau das erzeugte die scheinbare Wurfnummer 21. Diese
        # Pruefung hier ist unabhaengig von jener Fallback-Logik: Sie laesst
        # `_last_throw_number` und `self.score` VOELLIG unberuehrt, der Zyklus
        # wird behandelt, als haette er nie stattgefunden. Den Spielwechsel
        # bucht dann der naechste, ECHTE erste Wurf -- semantisch sauberer als
        # ihn an einem Geisterzyklus festzumachen.
        # Stand sichern: Wird dieser Zyklus gleich als Stoerung verworfen, darf
        # die Wurfnummernkette NICHT weitergedreht worden sein. Genau daran
        # scheiterte es bisher -- ein verworfener Wurf verschob alles Folgende.
        wurfnummer_vorher = self._last_throw_number
        # BUG-019: ... aber wenn in DIESEM Aufruf ein Spielwechsel gebucht
        # wurde, gehoert der gesicherte Stand zum ALTEN Spiel und darf NICHT
        # wiederhergestellt werden. Gezaehlt wird ueber `score.game_totals`,
        # weil das beide Spielwechsel-Pfade erfasst (Anzeige auf 000/0000 und
        # Ruecksprung der Wurfnummer) und kein zusaetzliches Zustandsfeld
        # braucht, das irgendwann nicht mitgepflegt wird.
        spiele_vorher = len(self.score.game_totals)

        # --- Wurfnummer bestimmen ---
        number = self._resolve_throw_number(throw_number, checks, decisions,
                                            display_reset, displayed_total)
        spielwechsel_gebucht = len(self.score.game_totals) > spiele_vorher
        self._throws_since_game_change += 1
        if number is None:
            return None      # als Doppelzaehlung verworfen

        # --- Kegelanzahl: Lampen sind die Hauptquelle ---
        #
        # RAEUMEN (vom Nutzer erklaert, 2026-08-25): Beim Raeumen muessen nur die
        # noch stehenden Kegel getroffen werden. Man erkennt es daran, dass beim
        # Einschalten der gruenen Lampe bereits Kegellampen leuchten -- diese
        # Kegel liegen schon und zaehlen NICHT zu diesem Wurf. Im Normalfall
        # ("in die Vollen") ist die Grundlinie leer und die Differenz aendert
        # nichts.
        #
        # GEMESSEN, was das Ignorieren kostete: Vier Wuerfe zeigten neun
        # leuchtende Lampen, waehrend die Tafel 1, 2, 3 bzw. 4 Kegel anzeigte.
        # Das sah nach Ziffern-Lesefehlern aus -- tatsaechlich waren es
        # Raeumwuerfe, und die Ziffer hatte jedes Mal recht.
        end_pins = set(pins.pins) if pins is not None else set()
        base_pins = set(baseline.pins) if baseline is not None else set()
        neu_gefallen = end_pins - base_pins

        if base_pins:
            decisions.append(
                f"Raeumen: {len(base_pins)} Kegel lagen bereits vor dem Wurf "
                f"({sorted(base_pins)}) -- abgezogen"
            )
        # Kegel, die vorher lagen und jetzt nicht mehr: Die Anlage hat neu
        # aufgestellt. Dann ist die Grundlinie hinfaellig, nicht das Ergebnis.
        verschwunden = base_pins - end_pins
        if verschwunden:
            decisions.append(
                f"Kegel {sorted(verschwunden)} lagen vorher, stehen jetzt wieder "
                f"-- neu aufgestellt, Grundlinie verworfen"
            )
            neu_gefallen = end_pins
            base_pins = set()

        pin_numbers = tuple(sorted(neu_gefallen))
        count = len(pin_numbers)
        lamps_complete = pins.is_complete if pins is not None else False

        # KEIN WURF: Die Tafel war waehrend dieses Fensters verdeckt (BUG-017).
        #
        # Die Verdeckungsbremse in lane_processor friert Zustand und Messung
        # waehrend einer Verdeckung ein -- aber wenn eine Person GENAU beim
        # Wiedersichtbarwerden wieder aus dem Bild tritt, meldet die
        # Zustandsmaschine sofort GREEN_ON und das Fenster gilt als "fertig".
        # 0 Kegel ist dann kein Messwert, sondern eine Luecke: Die Kamera hat
        # schlicht nichts gesehen, waehrend die Person davorstand.
        #
        # GEMESSEN an drei Faellen -- in allen dreien faellt der rohe
        # Gruen-Score irgendwo im Fenster auf exakt 0.0 (Kamera komplett
        # verdeckt), waehrend die vier Faelle des Warmwerf-Sperrzyklus
        # (BUG-018) nie unter 17 fallen:
        #
        #     Bahn 5 F15569    Minimum 0.00   Bahn 5 F16256   Minimum 0.00
        #     Bahn 2 F265724   Minimum 0.00
        #
        # Beschraenkt auf `count == 0`: Kommt trotz Verdeckung ein Kegelbild
        # durch (Lampen leuchteten schon vor oder nach der Verdeckung), ist
        # das eher ein zusaetzlicher Beleg als ein Widerspruch -- ein
        # NICHT-leeres Ergebnis waehrend einer Verdeckung ist in diesem
        # Material nicht beobachtet und wird deshalb nicht angetastet.
        if (self.cfg.scoring.discard_occluded_zero_throws
                and window_was_occluded and count == 0):
            log.warning(
                "Bahn %d: Gruenzyklus bei Frame %d faellt mit einer "
                "Verdeckung der Tafel zusammen -- 0 Kegel ist hier keine "
                "Messung, sondern eine Luecke. Wird verworfen.",
                self.display_number, event.trigger_frame)
            self._kette_wiederherstellen(wurfnummer_vorher,
                                         spielwechsel_gebucht)
            return None

        # KEIN WURF: Die Kegelraute zeigt am Ende genau dasselbe wie am Anfang.
        #
        # Dann ist nichts gefallen -- und ein Wurf, bei dem nichts faellt,
        # erzeugt gar keinen Gruenzyklus: Die Anlage hat nichts zu zaehlen und
        # nichts aufzustellen, die Bahn bleibt freigegeben (Q10). Solche Wuerfe
        # kommen ueber den Fehlwurfzaehler herein, nicht hier.
        #
        # Ein Zyklus ohne Veraenderung ist deshalb kein Wurf, sondern eine
        # Stoerung -- beobachtet, wenn jemand kurz vor der Tafel steht.
        #
        # GEMESSEN ueber 479 Gruenzyklen des 52-Minuten-Videos: GENAU EINER
        # hatte eine unveraenderte Kegelraute, und genau der stand nicht im
        # handgefuehrten Wurfprotokoll.
        #
        # Zwei Bedingungen halten die Regel eng bei dem, was gemessen ist:
        #
        # 1. Es mussten Kegel LIEGEN (`base_pins` nicht leer). Der Fall "nichts
        #    vorher, nichts nachher" bleibt ein gueltiger Leerwurf -- fuer ihn
        #    gibt es in diesem Material keinen Beleg, dass er eine Stoerung
        #    waere, und ohne Beleg wird nichts verworfen.
        # 2. Die Lampenmessung muss VOLLSTAENDIG sein. Waren Lampen unlesbar,
        #    sagt die Gleichheit nichts -- dann koennte eine Messung ausgefallen
        #    sein statt nichts gefallen.
        if (self.cfg.scoring.discard_unchanged_cycles
                and not neu_gefallen and lamps_complete
                and base_pins and end_pins == base_pins):
            log.warning("Bahn %d: Gruenzyklus bei Frame %d ohne Veraenderung "
                        "der Kegelraute (%s vorher wie nachher) -- kein Wurf",
                        self.display_number, event.trigger_frame,
                        sorted(end_pins) or "leer")
            return None

        # KEIN WURF: Nichts hat sich geregt.
        #
        # GEMESSEN am 2026-08-30 (Spieltag 2026-08-29, Bahn 5): Ein kurzer
        # Gruenzyklus erzeugte einen Wurf mit 0 Kegeln. Die Wurfnummer lief
        # danach um EINS VERSETZT weiter, und jeder folgende Wurf des Satzes
        # wurde dem falschen Protokollwurf zugeordnet:
        #
        #     Spieler A, F40903    16/30  ->  29/30 nach Korrektur
        #     Spieler D, F179349  27/30  ->  30/30 nach Korrektur
        #
        # EIN eingeschobener Wurf kostete also 13 bzw. 3 Wuerfe. Der Schaden
        # entsteht nicht durch den falschen Wurf selbst, sondern durch den
        # Versatz, den er hinterlaesst.
        #
        # Die Regel stuetzt sich auf ZWEI unabhaengige Zeugen der Anlage --
        # nicht auf die Dauer des Gruenzyklus. Die taugt nachweislich nicht:
        # ein echter Wurf lief ueber 7 Frames, ein falscher ueber 46. Die
        # Bereiche ueberlappen vollstaendig.
        #
        # Wurde wirklich geworfen, dann hat die Anlage entweder die Wurfnummer
        # erhoeht oder -- bei einem Wurf ohne Kegel -- den Fehlwurfzaehler.
        # Ruehrt sich keiner von beiden und liegt ausserdem kein Kegel, war es
        # kein Wurf. GEGENPROBE: Bei F40903 zaehlte der Fehlwurfzaehler auf
        # Bahn 5 nicht hoch; sein naechster Anstieg lag bei F125540.
        # KEIN WURF: Die Anlage hat nicht mitgezaehlt.
        #
        # Die staerkere der beiden Regeln, und sie braucht die Kegelzahl gar
        # nicht. GEMESSEN am 2026-08-31 auf dem zweiten Spieltag, Bahn 3:
        #
        #     Wurf 17  F247487   3 Kegel   Tafel: 3,  Wurfnummer 17
        #     Wurf 18  F247898   1 Kegel   Tafel: unlesbar, Nummer BLEIBT 17
        #     Wurf 19  F248578   1 Kegel   Tafel: 1,  Wurfnummer 18
        #
        # Der eingeschobene Wurf zeigte EINEN Kegel. Die Regel darunter
        # verlangt null und konnte ihn deshalb nicht fassen; der Satz kam auf
        # 219 Kegel in 31 Wuerfen statt der 218 in 30, die die Ergebnistafel
        # der Anlage auswies.
        #
        # Die Anlage zaehlt ihre Wuerfe selbst. Ruehrt sich ihr Zaehler nicht,
        # hat kein Wurf stattgefunden -- was auch immer die Lampen zeigen.
        # Die Schwelle auf die Einigkeit ist der ganze Unterschied zu BUG-008:
        # Dort wurde bei nicht steigender Wurfnummer verworfen, was 20 von 71
        # Wuerfen kostete (28 %) -- weil die Nummer FEHLGELESEN war. Eine
        # Fehllesung flackert; ein echter Stillstand ist ueber alle
        # abgetasteten Frames hinweg felsenfest.
        if (self.cfg.scoring.discard_cycles_without_throw_number
                and throw_number is not None
                and self._last_read_throw_number is not None
                and throw_number == self._last_read_throw_number
                and throw_number_confidence
                >= self.cfg.scoring.throw_number_min_confidence):
            log.warning(
                "Bahn %d: Gruenzyklus bei Frame %d ohne Wurf -- die Tafel "
                "steht unveraendert auf Wurf %d (Einigkeit %.2f), obwohl die "
                "Lampen %d Kegel zeigen. Wird verworfen, damit die "
                "Wurfnummernkette nicht verrutscht.",
                self.display_number, event.trigger_frame, throw_number,
                throw_number_confidence, count)
            self._kette_wiederherstellen(wurfnummer_vorher,
                                         spielwechsel_gebucht)
            return None

        # WURFNUMMER UND SUMME BEIDE AUF NULL -- ES GAB KEINEN WURF.
        #
        # WARUM HIER UND NICHT VOR `_resolve_throw_number` (gemessen
        # 2026-09-04, Teillauf F110000-230000): Dort stand die Pruefung
        # zuerst -- und verschluckte den SPIELWECHSEL. Der Gruenzyklus,
        # in dem das Zeichen `display_reset` ankommt, ist genau der, den
        # diese Regel verwirft. Wird er vor der Aufloesung abgebrochen,
        # ruft niemand `start_new_game()`, das Zeichen verfaellt, und
        # zwei Saetze wachsen zu einem zusammen:
        #
        #     Bahn 4  F183107  Wurf 30      <- Satzende
        #     Bahn 4  F186293  Wurf 31      <- haette Wurf 1 sein muessen
        #
        # Hinter der Aufloesung ist der Spielwechsel gebucht, und
        # `_kette_wiederherstellen` setzt die Wurfnummernkette korrekt
        # zurueck (BUG-019). Genau dafuer steht sie dort.
        #
        # ZWEI FELDER, NICHT EINS (Q16). Die 9 wird an der Einerstelle in 25 %
        # der Faelle als 0 gelesen -- systematisch, mit voller zeitlicher
        # Einigkeit. GEMESSEN am 2026-09-04 an acht echten Neunern:
        #
        #     Bahn 3, Wurf 9  ->  ('0','3','0')   Einigkeit 1,00
        #     Bahn 4, Wurf 9  ->  ('0','1','0')   Einigkeit 1,00
        #
        # Beide entgingen der Regel nur, weil die ZEHNERSTELLE ebenfalls
        # falsch war -- durch Zufall, nicht durch Konstruktion. Eine gelesene
        # 0 allein darf deshalb keinen Wurf verwerfen; ein falsch verworfener
        # Wurf mit neun Kegeln verfaelscht die Satzsumme.
        #
        # Die Summe ist der zweite, UNABHAENGIGE Zeuge: Beim Spielwechsel
        # zeigt die Anlage "000 0000", ein echter Wurf hat dagegen eine Summe
        # ueber null. Damit muessten zwei getrennt gelesene Felder
        # gleichzeitig falsch sein.
        nummer_mehrheit, nummer_einigkeit = throw_number_majority
        summe_mehrheit, summe_einigkeit = total_majority
        schwelle = self.cfg.scoring.throw_number_min_agreement
        summe_null = (not self.cfg.scoring.discard_zero_requires_zero_total
                      or (summe_mehrheit == 0 and summe_einigkeit >= schwelle))
        # DER DRITTE ZEUGE (BUG-032). Wurfnummer und Summe sind getrennt
        # gelesen und trotzdem nicht unabhaengig: Beim ERSTEN Wurf eines Spiels
        # stehen beide legitim auf null, solange die Anlage nicht gebucht hat.
        # Genau dort verlor der Spieltagslauf einen Wurf -- sechs Kegel lagen
        # sichtbar, die Kegelziffer zeigte 6, und verworfen wurde trotzdem.
        #
        # Die Kegelraute haengt an keinem Ziffernfeld. Liegt am Ende des Zyklus
        # etwas, ist etwas umgefallen.
        raute_leer = (not self.cfg.scoring.discard_zero_requires_empty_diamond
                      or not end_pins)
        if (self.cfg.scoring.discard_zero_throw_number
                and nummer_mehrheit == 0
                and nummer_einigkeit >= schwelle
                and summe_null
                and raute_leer):
            log.warning(
                "Bahn %d: Anzeige steht bei Frame %d auf 000/0000 "
                "(Wurfnummer %d%% einig, Summe %s, Kegelraute leer) -- kein "
                "Wurf hat stattgefunden. Wird verworfen.",
                self.display_number, event.trigger_frame,
                round(nummer_einigkeit * 100),
                "nicht geprueft" if not self.cfg.scoring.discard_zero_requires_zero_total
                else f"{round(summe_einigkeit * 100)}% einig")
            self._kette_wiederherstellen(wurfnummer_vorher,
                                         spielwechsel_gebucht)
            return None

        if (self.cfg.scoring.discard_zero_throw_number
                and nummer_mehrheit == 0
                and nummer_einigkeit >= schwelle
                and summe_null and not raute_leer):
            # Nicht verworfen -- und das muss im Beweis stehen (P1). Sonst
            # sieht man einem gebuchten Wurf nicht an, dass er knapp an einer
            # Verwerfung vorbeigekommen ist.
            decisions.append(
                f"Anzeige stand auf 000/0000, aber {len(end_pins)} Kegel lagen "
                f"({sorted(end_pins)}) -- erster Wurf eines Spiels, noch nicht "
                f"gebucht (BUG-032)"
            )
            log.info(
                "Bahn %d: Anzeige steht bei Frame %d auf 000/0000, aber %d "
                "Kegel liegen -- das ist der erste Wurf eines Spiels, den die "
                "Anlage noch nicht gebucht hat. Wird NICHT verworfen.",
                self.display_number, event.trigger_frame, len(end_pins))

        # NULL KEGEL BRAUCHT EINEN ZEUGEN.
        #
        # Ein Gruenzyklus, an dessen Ende kein Kegel liegt, ist ein Widerspruch
        # in sich: Faellt nichts, gibt es nichts aufzustellen -- die Anlage
        # schaltet die gruene Lampe gar nicht erst aus (Q10). Ein solcher
        # Zyklus entsteht deshalb fast immer aus etwas anderem als einem Wurf.
        #
        # GEMESSEN am Spieltag 2026-08-22 (Lauf 2026-09-03_11-14-04), alle 19
        # Wuerfe mit null Kegeln:
        #
        #     Herkunft            Anzahl   Tafel-Ziffer   Lage im Abschnitt
        #     fehlwurfzaehler          4   immer 0        mitten im Satz
        #     gruenzyklus             15   nie vorhanden  erster/letzter Wurf
        #
        # Die Trennung ist vollstaendig: Jeder echte Nullwurf kommt vom
        # Fehlwurfzaehler und traegt die Ziffer 0 als Beleg. Jeder aus einem
        # Gruenzyklus stammende steht am RAND eines Abschnitts -- acht davon
        # als erster Wurf nach einem Spielwechsel, fuenf als letzter eines
        # Warmwerf-Blocks.
        #
        # WARUM `discard_static_zero_cycles` das nicht faengt: Jene Regel
        # verlangt, dass sich die Wurfnummer NICHT geaendert hat. Beim
        # Spielwechsel springt sie aber von 30 auf 1 -- eine Aenderung, und die
        # Regel greift nicht. Genau dort entstehen diese Faelle.
        #
        # DREI ZEUGEN KOMMEN IN FRAGE, einer genuegt:
        #
        #   1. die Tafelziffer 0                  -- die Anlage zeigt es an
        #   2. ein um eins gestiegener Fehlwurfzaehler
        #   3. eine um genau eins gestiegene Wurfnummer
        #
        # Der dritte Punkt ist der entscheidende Unterschied zum ersten
        # Versuch: Beim SPIELWECHSEL springt die Wurfnummer von 30 auf 1
        # zurueck. Das ist zwar eine Aenderung, aber kein Weiterzaehlen -- die
        # Anlage hat nicht geworfen, sie hat zurueckgesetzt. Genau dort
        # entstehen acht der fuenfzehn Faelle.
        #
        # WAS ES KOSTET: Ein echter Nullwurf, bei dem alle drei Zeugen
        # schweigen, geht verloren. Das ist der bewusste Preis -- ein
        # erfundener Wurf verschiebt die ganze Wurfnummernkette dahinter, ein
        # fehlender nur sich selbst.
        # DER SPIELWECHSEL SELBST IST DER FALL, um den es geht.
        #
        # Beim Zuruecksetzen steht die Anzeige auf `000 0000`, und der
        # Gruenzyklus, in dem das geschieht, wird als erster Wurf des neuen
        # Spiels gebucht -- mit null Kegeln, weil die Raute leer ist. GEMESSEN
        # am Spieltag 2026-08-22: acht der neunzehn Nullwuerfe entstehen so.
        # Im Log stehen sie unmittelbar untereinander:
        #
        #     Bahn 4: Anzeige stand auf 000/0000 -- voriges Spiel endete mit 195
        #     Bahn 4: Wurf 1 erkannt -- 0 Kegel [], Gesamt 0, EMPTY
        #
        # Ein erster Versuch prueft stattdessen die Wurfnummer und griff nicht:
        # Dort ist sie NICHT LESBAR (die Anzeige steht ja auf null), und
        # Schweigen darf nichts verwerfen (BUG-008). Das Spielwechsel-Zeichen
        # ist das richtige Kriterium -- es sagt genau, was hier geschehen ist.
        if (self.cfg.scoring.discard_zero_without_digit and count == 0
                and display_reset and displayed_count is None):
            log.warning(
                "Bahn %d: Gruenzyklus bei Frame %d faellt mit dem "
                "Spielwechsel zusammen -- 0 Kegel, keine Tafelziffer. Das ist "
                "das Zuruecksetzen der Anlage, kein Wurf. Wird verworfen.",
                self.display_number, event.trigger_frame)
            self._kette_wiederherstellen(wurfnummer_vorher,
                                         spielwechsel_gebucht)
            return None

        # NUR BEI LESBAREN ZEUGEN URTEILEN. Schweigt die Wurfnummer, weil sie
        # nicht zu lesen war, ist das kein Beleg gegen den Wurf -- der
        # Gruenzyklus selbst beweist, dass die Anlage etwas getan hat. Genau
        # diese Verwechslung kostete in BUG-008 28 % der Wuerfe, und der
        # Regressionstest dazu haelt sie fest
        # (`test_unlesbare_staende_verwerfen_nichts`).
        if (self.cfg.scoring.discard_zero_without_digit and count == 0
                and throw_number is not None
                and wurfnummer_vorher is not None):
            zaehler_stieg = (foul_count is not None
                             and self._last_read_foul_count is not None
                             and foul_count > self._last_read_foul_count)
            nummer_stieg = throw_number == wurfnummer_vorher + 1

            if not (displayed_count is not None or zaehler_stieg
                    or nummer_stieg):
                log.warning(
                    "Bahn %d: Gruenzyklus bei Frame %d ohne Wurf -- 0 Kegel, "
                    "keine Tafelziffer, Fehlwurfzaehler unveraendert und die "
                    "Wurfnummer (%s, vorher %s) nicht weitergezaehlt. Wird "
                    "verworfen; ein echter Nullwurf hat wenigstens einen "
                    "dieser drei Zeugen.",
                    self.display_number, event.trigger_frame,
                    throw_number, wurfnummer_vorher)
                self._kette_wiederherstellen(wurfnummer_vorher,
                                             spielwechsel_gebucht)
                return None

        if (self.cfg.scoring.discard_static_zero_cycles
                and count == 0
                and self._nichts_hat_sich_geregt(throw_number, foul_count)):
            log.warning(
                "Bahn %d: Gruenzyklus bei Frame %d ohne Wurf -- 0 Kegel, "
                "Wurfnummer unveraendert (%s), Fehlwurfzaehler unveraendert "
                "(%s). Wird verworfen, damit die Wurfnummernkette nicht "
                "verrutscht.",
                self.display_number, event.trigger_frame,
                self._last_read_throw_number, self._last_read_foul_count)
            self._kette_wiederherstellen(wurfnummer_vorher,
                                         spielwechsel_gebucht)
            return None

        # Ab hier gilt der Wurf als echt -- die gelesenen Staende der Tafel
        # werden zum neuen Bezugspunkt.
        if throw_number is not None:
            self._last_read_throw_number = throw_number
        if foul_count is not None:
            self._last_read_foul_count = foul_count

        if pins is None:
            decisions.append("Keine Lampenmessung vorhanden -- Ergebnis unsicher")
        elif not lamps_complete:
            decisions.append("Nicht alle Kegellampen lesbar -- Anzahl unsicher")

        # --- Gegenprobe Ziffernfeld ---
        sources_agree = True
        if displayed_count is not None and displayed_count != count                 and count in displayed_candidates:
            # Die Ziffer wurde zwar auf einen Wert zusammengefasst, aber der
            # Leser hielt die Lampenzahl ueber das Ereignis hinweg ebenfalls fuer
            # moeglich. Dann hat die Mehrheitsabstimmung nur eine von mehreren
            # gleich plausiblen Lesungen gewaehlt.
            #
            # GEMESSEN: Bei fuenf von vierzehn Widerspruechen stand der
            # Lampenwert in den Frame-Kandidaten (etwa Lampen 8, gelesen 7,
            # moeglich waren {7, 8}). Die Information war da und ging beim
            # Zusammenfassen verloren.
            #
            # Die Lampen sind die Hauptquelle (Prinzip P5) -- sie duerfen
            # zwischen plausiblen Lesungen waehlen. Was sie NICHT duerfen: einen
            # Wert setzen, den der Leser nie in Betracht zog. Genau daran bleibt
            # die Gegenprobe pruefbar.
            sources_agree = True
            checks.append(PlausibilityCheck(
                "Lampen unter den moeglichen Ziffern",
                list(displayed_candidates), count, True))
            decisions.append(
                f"Ziffer zusammengefasst auf {displayed_count}, moeglich waren "
                f"{list(displayed_candidates)} -- durch die Lampen auf {count} "
                f"aufgeloest"
            )

        elif displayed_count is not None:
            sources_agree = (displayed_count == count)
            checks.append(PlausibilityCheck(
                "Lampen == angezeigte Kegelzahl", displayed_count, count,
                sources_agree))
            if not sources_agree:
                log.warning("Bahn %d Wurf %d: Lampen zeigen %d, Anzeige %d "
                            "(moeglich waren %s)",
                            self.display_number, number, count, displayed_count,
                            list(displayed_candidates) or "nur dieser Wert")

        elif len(displayed_candidates) > 1:
            # Die Ziffer war nicht eindeutig -- aber sie hat die Auswahl
            # eingegrenzt. Beispiel aus dem Material: Auf einer Bahn stand
            # {4, 9} zur Wahl, weil sich beide Muster in einem einzigen Segment
            # unterscheiden (siehe BUG-009) und genau dieses auf der Schwelle lag.
            #
            # Die Lampen duerfen dann WAEHLEN, aber keinen neuen Wert setzen.
            # Genau darin liegt der Unterschied zu einer Scheinpruefung: Melden
            # die Lampen einen Wert, der nicht zur Auswahl steht, bleibt es ein
            # Widerspruch -- die Gegenprobe ist also weiterhin in der Lage,
            # die Lampen zu widerlegen.
            #
            # Vollstaendig unabhaengig bleibt ohnehin die Summenanzeige: Sie
            # wird aus einem anderen Ziffernfeld gelesen und muss um genau die
            # gezaehlte Kegelzahl steigen.
            sources_agree = count in displayed_candidates
            checks.append(PlausibilityCheck(
                "Lampen unter den moeglichen Ziffern",
                list(displayed_candidates), count, sources_agree))
            if sources_agree:
                decisions.append(
                    f"Ziffer war nicht eindeutig ({list(displayed_candidates)}) "
                    f"-- durch die Lampen auf {count} aufgeloest"
                )
            else:
                log.warning("Bahn %d Wurf %d: Lampen zeigen %d, moeglich waren %s",
                            self.display_number, number, count,
                            list(displayed_candidates))

        # --- Gegenprobe Summe ---
        #
        # Die Anlage traegt das Wurfergebnis erst kurz vor dem naechsten
        # Gruen-AN in die Summe ein (BUG-010). Seit der Wurf schon 1,6 Sekunden
        # nach Gruen-AUS gemeldet wird, steht dort also noch der Stand VOR
        # diesem Wurf.
        #
        # GEMESSEN ueber einen ganzen Lauf, was die Anzeige zum Meldezeitpunkt
        # zeigt:
        #     vorherige Summe   294
        #     aktuelle Summe      4
        #     weder noch          7
        #     nicht lesbar      175
        #
        # Gegen die AKTUELLE Summe geprueft schlaegt die Probe deshalb fast
        # immer fehl -- eine Pruefung, die immer meckert, ist so wertlos wie
        # eine, die nie prueft.
        #
        # Die Kette bleibt trotzdem geschlossen: Der Stand vor Wurf N enthaelt
        # das Ergebnis von Wurf N-1. Jeder Wurf wird also bestaetigt, nur einen
        # Wurf spaeter.
        if displayed_total is not None and self.cfg.scoring.check_running_total:
            if self.cfg.scoring.displayed_total_lags:
                erwartet = self.score.running_total
                name = "Summe der Tafel == Stand vor diesem Wurf"
            else:
                erwartet = self.score.expected_total(count)
                name = "Summe alt + Kegel == Summe neu"
            total_ok = (displayed_total == erwartet)
            checks.append(PlausibilityCheck(name, erwartet, displayed_total,
                                            total_ok))
            if not total_ok:
                log.warning("Bahn %d Wurf %d: Summe erwartet %d, Tafel zeigt %d",
                            self.display_number, number, erwartet, displayed_total)

        # --- Gegenprobe Fehlwurfzaehler (Q2) ---
        if foul_count is not None and self.cfg.scoring.check_foul_count:
            self._check_foul_count(foul_count, count, checks, decisions)

        # --- Status bestimmen ---
        status = self._determine_status(count, pins, sources_agree, checks)

        # --- Buchen ---
        running_total, series_total = self.score.register(number, count)

        confidence = self._confidence(pins, sources_agree, checks)
        evidence = Evidence(
            frames=tuple(FrameRef(s.index, s.timestamp, s.role)
                         for s in event.sorted_frames()),
            checks=tuple(checks),
            decisions=tuple(decisions),
            raw={"pins": pins.to_dict() if pins is not None else None,
                 "baseline": baseline.to_dict() if baseline is not None else None,
                 "clearing": bool(base_pins),
                 "displayed_count": displayed_count,
                 "displayed_candidates": list(displayed_candidates),
                 "displayed_total": displayed_total,
                 # ROHE Wurfnummer der Tafel, VOR `_resolve_throw_number`.
                 # WARUM SIE HIER STEHT: Zweimal am 2026-09-03 wurde eine
                 # Regel auf die Annahme gebaut, die Tafel habe einen
                 # bestimmten Wert gezeigt -- belegt wurde das jeweils mit
                 # der Spalte `Wurfnummer` der `wuerfe.csv`, die aber die
                 # AUFGELOESTE Nummer zeigt. Beide Regeln griffen im echten
                 # Lauf nicht (siehe BUG-018-Nachtrag). Ohne die Rohlesung
                 # laesst sich ueber die Tafel nichts belegen.
                 "throw_number_raw": throw_number,
                 "throw_number_confidence": throw_number_confidence},
        )

        result = ThrowResult(
            lane=self.display_number,
            throw_number=number,
            throw_number_in_series=throw_in_cycle(number, self.cfg.scoring.throws_per_cycle),
            cycle_number=cycle_number(number, self.cfg.scoring.throws_per_cycle),
            # Wie viele Spiele auf dieser Bahn bereits abgeschlossen sind, plus
            # das laufende. Wird bei jedem Spielwechsel hochgezaehlt (siehe
            # LaneScore.start_new_game).
            game_number=len(self.score.game_totals) + 1,
            # UNKLARE LAMPEN, getrennt nach Ergebnis und Ausgangslage. Eine
            # unklare Lampe in der AUSGANGSLAGE ist die gefaehrlichere von
            # beiden: Beim Abraeumen wird sie abgezogen, obwohl niemand weiss,
            # ob sie lag (BUG-027).
            lamps_unknown=sum(
                1 for lamp in pins.lamps if not lamp.state.is_known),
            baseline_unknown=(
                None if baseline is None
                else sum(1 for lamp in baseline.lamps
                         if not lamp.state.is_known)),
            pins=pin_numbers,
            pins_count=count,
            displayed_pin_count=displayed_count,
            # Was die Tafel im selben Moment zeigte -- Beleg, keine Rechnung.
            displayed_throw_number=throw_number,
            displayed_foul_count=foul_count,
            displayed_total=displayed_total,
            status=status,
            running_total=running_total,
            series_total=series_total,
            confidence=confidence,
            timestamp=event.trigger_timestamp,
            source_frame=event.trigger_frame,
            evidence=evidence,
        )

        log.info("Bahn %d: Wurf %d erkannt -- %d Kegel %s, Gesamt %d, %s (%.2f)",
                 self.display_number, number, count, list(pin_numbers),
                 running_total, status.value, confidence)
        if series_total is not None:
            log.info("Bahn %d: Zyklus %d abgeschlossen, Zwischensumme %d",
                     self.display_number, result.cycle_number, series_total)
        return result

    def analyze_zero_throw(self, frame_index: int, timestamp: float,
                           throw_number: int | None = None) -> ThrowResult:
        """Bucht einen Wurf ohne Kegel, ausgeloest vom Fehlwurfzaehler.

        Hier gibt es KEIN Sampling-Ereignis, weil es keines geben kann: Faellt
        kein Kegel, schaltet die Anlage die gruene Lampe nicht aus -- es ist
        nichts zu zaehlen und nichts aufzustellen. Der Wurf ist damit fuer den
        Gruenlampen-Trigger unsichtbar (Q10).

        Belegt sind solche Wuerfe trotzdem, und zwar unabhaengig vom Bild der
        Kegelraute: Der Fehlwurfzaehler im linken Display zaehlt sie. Ueber 52
        Minuten gemessen stieg er auf Bahn 2 genau einmal -- an der Stelle, an
        der im handgefuehrten Wurfprotokoll der einzige Nullwurf dieser Bahn
        steht.

        Der Zeitstempel ist der des ZAEHLERSTANDS, nicht des Ballwurfs. Genauer
        geht es nicht: Der Wurf selbst hinterlaesst keine Spur, an der man ihn
        festmachen koennte.

        WARUM DIE WURFNUMMER MITKOMMT: Frueher wurde hier blind fortgezaehlt
        (`_resolve_throw_number(None, ...)`). Damit war dieser Pfad blind fuer
        SPIELGRENZEN -- der einzige Zeuge, der einen Spielwechsel erkennen
        kann, war gar nicht im Spiel.

        GEMESSEN am 2026-08-31, zweiter Spieltag, Bahn 3:

            Wurf 30  F194771   Satz zu Ende
            Wurf 31  F201410   Fehlwurf, 4,4 Minuten spaeter
                               Tafel zeigt: throw_number = 1

        Die Tafel hatte laengst auf den ersten Wurf des naechsten Satzes
        zurueckgesetzt. Der Fehlwurf gehoerte dorthin, wurde aber noch dem
        alten Spiel angehaengt -- 31 Wuerfe statt 30. Auf die Summe wirkte es
        sich nicht aus (0 Kegel), auf die Zuordnung schon.
        """
        checks = [PlausibilityCheck(
            "Fehlwurfzaehler gestiegen", 1, 1, True)]
        decisions = ["Wurf ohne Kegel: Der Fehlwurfzaehler ist gestiegen. "
                     "Die gruene Lampe bleibt bei einem solchen Wurf an, "
                     "deshalb gibt es kein Wurffenster."]

        number = self._resolve_throw_number(throw_number, checks, decisions)
        running_total, series_total = self.score.register(number, 0)

        evidence = Evidence(
            frames=(FrameRef(frame_index, timestamp, FrameRole.GREEN_OFF),),
            checks=tuple(checks),
            decisions=tuple(decisions),
            raw={"pins": None, "baseline": None, "clearing": False,
                 "displayed_count": 0, "displayed_candidates": [],
                 "displayed_total": None, "source": "fehlwurfzaehler",
                 # Siehe `analyze()`: Auf diesem Pfad ist die Rohlesung noch
                 # wichtiger, weil sie aus EINEM Frame stammt (Q15).
                 "throw_number_raw": throw_number,
                 "throw_number_confidence": None},
        )

        result = ThrowResult(
            lane=self.display_number,
            throw_number=number,
            throw_number_in_series=throw_in_cycle(
                number, self.cfg.scoring.throws_per_cycle),
            cycle_number=cycle_number(number, self.cfg.scoring.throws_per_cycle),
            game_number=len(self.score.game_totals) + 1,
            pins=(),
            pins_count=0,
            displayed_pin_count=0,
            status=ThrowStatus.VALID,
            running_total=running_total,
            series_total=series_total,
            confidence=1.0,
            timestamp=timestamp,
            source_frame=frame_index,
            evidence=evidence,
        )
        log.info("Bahn %d: Wurf %d erkannt -- 0 Kegel (Fehlwurfzaehler), "
                 "Gesamt %d", self.display_number, number, running_total)
        return result

    # ---------------------------------------------------------------- Details

    def _kette_wiederherstellen(self, wurfnummer_vorher: int | None,
                                spielwechsel_gebucht: bool) -> None:
        """Setzt die Wurfnummernkette zurueck, nachdem ein Zyklus verworfen wurde.

        WARUM UEBERHAUPT WIEDERHERSTELLEN: Ein verworfener Stoerzyklus darf die
        Kette nicht weiterdrehen -- sonst traegt jeder folgende Wurf eine um
        eins zu hohe Nummer, und beim Abgleich mit dem Wurfprotokoll rutscht
        der ganze Satz.

        WARUM NICHT IMMER (BUG-019): War derselbe Zyklus zugleich der
        SPIELWECHSEL, wurde `start_new_game()` bereits ausgefuehrt -- der
        gesicherte Stand gehoert dann zum ALTEN Spiel. Ihn wiederherzustellen
        laesst den neuen Satz bei 31 statt bei 1 beginnen, sobald die
        Wurfnummer des ersten neuen Wurfs nicht lesbar ist (dann zaehlt
        `_resolve_throw_number` auf `_last_throw_number + 1` fort).

        GEMESSEN am Spieltag 2026-09-03: 5 von 64 Spielen betroffen, auf
        Bahn 4 drei (Spiel 4: 31-60, Spiel 5: 61-90, Spiel 11: 31-60).
        """
        self._last_throw_number = 0 if spielwechsel_gebucht else wurfnummer_vorher

    def _spielwechsel_erlaubt(self, decisions: list[str], quelle: str) -> bool:
        """Darf jetzt ein Spielwechsel gebucht werden -- oder war schon einer?

        Ein Spiel hat 30 Wuerfe. Zwei Spielenden im Abstand von einem Wurf gibt
        es nicht; der zweite ist derselbe Wechsel, nur vom anderen Zeugen
        gemeldet.

        GEMESSEN ueber den vollen Spieltag 2026-08-29: Bahn 2 zaehlte 25 Spiele,
        davon ACHT mit genau einem Wurf. Jedes Mal dasselbe Muster --

            Spiel 4  Wurf 30    Satz zu Ende
            Spiel 5  Wurf  1    Wechsel erkannt
            Spiel 6  Wurf  2    zweiter Wechsel, einen Wurf spaeter

        Beide Zeugen sind gewollt und sollen bleiben: Der Nullzustand traegt
        auch dann, wenn die Wurfnummer unlesbar war, der Rueckfall auch dann,
        wenn die Pause zu kurz zum Messen war. Sie treffen nur nicht
        gleichzeitig ein.
        """
        abstand = self.cfg.scoring.game_reset_min_gap_throws
        if self._throws_since_game_change >= abstand:
            return True
        log.info("Bahn %d: Spielwechsel (%s) verworfen -- der letzte liegt "
                 "erst %d Wuerfe zurueck, ein Spiel hat 30.",
                 self.display_number, quelle, self._throws_since_game_change)
        decisions.append(
            f"Spielwechsel ({quelle}) verworfen -- der letzte liegt erst "
            f"{self._throws_since_game_change} Wuerfe zurueck"
        )
        return False

    def _resolve_throw_number(self, throw_number: int | None,
                              checks: list[PlausibilityCheck],
                              decisions: list[str],
                              display_reset: bool = False,
                              displayed_total: int | None = None) -> int | None:
        """Bestimmt die Wurfnummer und schuetzt vor Doppelzaehlung.

        Die Wurfnummer der Tafel ist die einzige Quelle, die Double Counting
        FACHLICH ausschliesst -- die Zustandsmaschine kann es nur zeitlich.
        Fehlt sie, wird hochgezaehlt; dann traegt allein die Zustandsmaschine.
        """
        # SPIELWECHSEL ueber den Nullzustand der Anzeige. Diese Pruefung steht
        # VOR allen anderen, weil sie die staerkste ist: Sie stuetzt sich auf
        # zwei getrennt gelesene Felder, die ueber zwanzig Sekunden lang beide
        # null zeigen -- nicht auf eine einzelne Ziffer im richtigen Moment.
        #
        # Sie ergaenzt den Ruecksprung der Wurfnummer, ersetzt ihn nicht: Der
        # Ruecksprung greift auch dann, wenn die Pause zu kurz war oder die
        # Summe waehrenddessen nicht lesbar. Beide fuehren zu genau einem
        # `start_new_game`, weil danach in jedem Fall zurueckgekehrt wird.
        if (display_reset and self.cfg.scoring.game_reset_by_zero_display
                and self._spielwechsel_erlaubt(decisions, "Anzeige auf 000/0000")):
            endstand = self.score.start_new_game()
            self._throws_since_game_change = 0
            log.info("Bahn %d: Anzeige stand auf 000/0000 -- voriges Spiel "
                     "endete mit %d Kegeln", self.display_number, endstand)
            decisions.append(
                f"Neues Spiel (Anzeige auf 000/0000): voriges endete mit "
                f"{endstand} Kegeln"
            )
            # EINE GELESENE NULL IST KEINE WURFNUMMER (BUG-032). Die
            # Anlage zaehlt ab 1; 000 heisst 'noch nicht gebucht', nicht
            # 'Wurf null'. Wurde sie frueher trotzdem durchgereicht,
            # scheiterte `score.register` an '0 ist nicht groesser als
            # 0'. Erreichbar war das bis BUG-032 nie, weil solche Zyklen
            # vorher immer verworfen wurden.
            number = throw_number if throw_number else 1
            self._last_throw_number = number
            return number

        # DRITTER ZEUGE: EINE NULL IN DER SUMME (BUG-029).
        #
        # Die Tafel traegt das Ergebnis verspaetet nach -- zum Meldezeitpunkt
        # steht dort der Stand VOR diesem Wurf. Eine gelesene Null heisst
        # deshalb: Vor diesem Wurf stand die Anlage auf null, sie hat also
        # zurueckgesetzt. Das gilt UNABHAENGIG von der Wurfnummer.
        #
        # WARUM DAS GEBRAUCHT WIRD: Die beiden anderen Wege haengen beide an
        # der Wurfnummer. Auf einer Bahn, deren Wurfnummernfeld schlecht
        # lesbar ist, versagen sie gemeinsam. GEMESSEN auf Bahn 5 (Stream
        # 2026-09-17): Der Nullzustand wurde nie erkannt (die Wurfnummer las
        # nie dreimal 000), bei F51552 war sie unlesbar -- der Wurf wurde
        # "fortgezaehlt auf 31" und landete im alten Spiel. Erst beim naechsten
        # Wurf griff der Rueckfall, und das neue Spiel begann bei Wurf 2. Der
        # erste Wurf und seine neun Kegel fehlten dem Spiel dauerhaft.
        #
        # WARUM DIE NULL TRAEGT, GEMESSEN am selben Lauf (315 Wuerfe): Genau
        # 12 Wuerfe hatten `SummeTafel == 0`, und 11 davon waren der erste Wurf
        # ihres Spiels. Der zwoelfte war der kaputte Fall von Bahn 5 -- also
        # zwoelf von zwoelf, wenn man ihn als das zaehlt, was er haette sein
        # sollen. Kein einziger Wurf mitten im Spiel zeigte eine Null.
        if (displayed_total == 0 and self.cfg.scoring.game_reset_by_zero_total
                and self._spielwechsel_erlaubt(decisions, "Summe der Tafel auf 0")):
            endstand = self.score.start_new_game()
            self._throws_since_game_change = 0
            log.info("Bahn %d: Summe der Tafel steht auf 0 -- die Anlage hat "
                     "vor diesem Wurf zurueckgesetzt, voriges Spiel endete "
                     "mit %d Kegeln", self.display_number, endstand)
            decisions.append(
                f"Neues Spiel (Summe der Tafel auf 0): voriges endete mit "
                f"{endstand} Kegeln")
            # EINE GELESENE NULL IST KEINE WURFNUMMER (BUG-032). Die
            # Anlage zaehlt ab 1; 000 heisst 'noch nicht gebucht', nicht
            # 'Wurf null'. Wurde sie frueher trotzdem durchgereicht,
            # scheiterte `score.register` an '0 ist nicht groesser als
            # 0'. Erreichbar war das bis BUG-032 nie, weil solche Zyklen
            # vorher immer verworfen wurden.
            number = throw_number if throw_number else 1
            self._last_throw_number = number
            return number

        if throw_number is None:
            number = (self._last_throw_number or self.score.last_throw_number) + 1
            decisions.append(f"Wurfnummer nicht lesbar -- fortgezaehlt auf {number}")
            self._last_throw_number = number
            return number

        last = self.score.last_throw_number

        # SPIELWECHSEL: Faellt die Wurfnummer von einem hohen Wert auf einen
        # sehr kleinen, hat die Anlage ein neues Spiel begonnen.
        #
        # GEMESSEN ueber 52 Minuten: Die Tafel setzt nach 30 Wuerfen zurueck --
        # Wurfnummer auf 1, Summe auf 0. Beobachtet auf drei Bahnen bei den
        # Wuerfen 29/30, 59/60 und 89/90. Der Nutzer hatte darauf hingewiesen.
        #
        # Warum das KEIN Lesefehler ist (und die Regel aus BUG-008 hier nicht
        # gilt): Zwei Bahnen sprangen im Abstand von zwei Sekunden gemeinsam von
        # 33 auf 4. Zwei unabhaengige Lesefehler treffen nicht gleichzeitig
        # denselben Wert. Der Unterschied zum Lesefehler ist die HOEHE des
        # Rueckfalls: Ein Lesefehler verschiebt um wenige Stellen, ein
        # Spielwechsel faellt von ueber 30 auf unter 5 zurueck.
        if (last >= self.cfg.scoring.game_reset_after
                and throw_number <= self.cfg.scoring.game_reset_below
                and self._spielwechsel_erlaubt(decisions,
                                               "Rueckfall der Wurfnummer")):
            endstand = self.score.start_new_game()
            self._throws_since_game_change = 0
            log.info("Bahn %d: Spiel beendet mit %d Kegeln nach %d Wuerfen -- "
                     "Tafel beginnt neu bei Wurf %d",
                     self.display_number, endstand, last, throw_number)
            decisions.append(
                f"Neues Spiel: voriges endete mit {endstand} Kegeln "
                f"nach {last} Wuerfen"
            )
            # Auch hier gilt: Eine gelesene 0 ist keine Wurfnummer, sondern
            # ein noch nicht gebuchter erster Wurf (BUG-032).
            number = throw_number if throw_number else 1
            self._last_throw_number = number
            return number

        if throw_number <= last:
            # KEIN Verwerfen. Der Gruenzyklus hat bereits BEWIESEN, dass geworfen
            # wurde -- eine Ziffernlesung darf diesen Beweis nicht aufheben.
            #
            # GEMESSEN, was das Verwerfen kostete: 71 Gruenzyklen, aber nur 51
            # gemeldete Wuerfe -- 28 % verloren, auf Bahn 4 sogar 10 von 18.
            # Der Ablauf war eine Kettenreaktion: Eine einzelne zu hoch gelesene
            # Nummer (echte 7 als "10") schob `last` nach vorn, und danach fielen
            # die echten Wuerfe 8, 9, 10 saemtlich unter "bereits gebucht".
            # Ein Lesefehler loeschte so eine ganze Serie -- unsichtbar, weil
            # die Wuerfe nie in der Tabelle erschienen.
            #
            # Gegen Doppelzaehlung schuetzt die Zustandsmaschine (P3): Sie ruft
            # diese Methode genau einmal je Gruenzyklus. Die Wurfnummer ist
            # Gegenprobe, nicht Torwaechter.
            fallback = last + 1
            log.warning("Bahn %d: Wurfnummer %d liegt nicht ueber der letzten (%d) "
                        "-- vermutlich Lesefehler, zaehle auf %d fort",
                        self.display_number, throw_number, last, fallback)
            decisions.append(
                f"Wurfnummer {throw_number} nicht plausibel (zuletzt {last}), "
                f"fortgezaehlt auf {fallback}"
            )
            checks.append(PlausibilityCheck(
                "Wurfnummer steigt", f"> {last}", throw_number, False,
                affects_result=False))
            self._last_throw_number = fallback
            return fallback

        # Unplausibel grosser Sprung -> die Ziffer wurde falsch gelesen.
        #
        # BEOBACHTET am realen Material: Nach Wurf 2 meldete die Ziffernerkennung
        # "703". Uebernaehme man das, waere der Zaehler dieser Bahn dauerhaft
        # zerstoert -- alle folgenden Wuerfe fielen unter "bereits gebucht" und
        # wuerden verworfen. Ein einzelner Lesefehler wuerde so die restliche
        # Bahn stilllegen.
        #
        # Die Wurfnummer ist eine Hilfsgroesse, kein Selbstzweck: Bei
        # Unplausibilitaet wird sie verworfen und schlicht fortgezaehlt. Die
        # Zustandsmaschine hat den Wurf ohnehin bereits belegt.
        jump = throw_number - last
        if last > 0 and jump > self.cfg.scoring.max_throw_number_jump:
            fallback = last + 1
            log.warning("Bahn %d: Wurfnummer %d unplausibel (Sprung %d nach %d) -- "
                        "vermutlich Lesefehler, zaehle auf %d fort",
                        self.display_number, throw_number, jump, last, fallback)
            decisions.append(
                f"Wurfnummer {throw_number} verworfen (Sprung {jump}), "
                f"fortgezaehlt auf {fallback}"
            )
            checks.append(PlausibilityCheck(
                "Wurfnummer plausibel", f"<= {last + self.cfg.scoring.max_throw_number_jump}",
                throw_number, False, affects_result=False))
            self._last_throw_number = fallback
            return fallback

        gap = self.score.has_gap(throw_number)
        if gap:
            # Luecke NICHT stillschweigend schliessen -- sichtbar machen.
            log.warning("Bahn %d: Luecke erkannt, %d Wurf/Wuerfe zwischen %d und %d "
                        "verpasst", self.display_number, gap, last, throw_number)
            decisions.append(f"{gap} Wurf/Wuerfe verpasst (Sprung {last} -> {throw_number})")
            checks.append(PlausibilityCheck(
                "Wurfnummer lueckenlos", last + 1, throw_number, False,
                affects_result=False))
        else:
            checks.append(PlausibilityCheck(
                "Wurfnummer lueckenlos", last + 1, throw_number, True,
                affects_result=False))

        self._last_throw_number = throw_number
        return throw_number

    def _nichts_hat_sich_geregt(self, throw_number: int | None,
                                foul_count: int | None) -> bool:
        """Hat die Anlage bei diesem Zyklus ueberhaupt etwas registriert?

        Beide Staende muessen LESBAR und UNVERAENDERT sein. Ist einer davon
        nicht lesbar, wird nichts verworfen: Der Gruenzyklus ist ein Beweis,
        dass die Anlage etwas getan hat, und eine ausgefallene Ziffernlesung
        darf diesen Beweis nicht aufheben (dieselbe Regel wie in BUG-008, wo
        das Verwerfen bei unsicherer Lesung 28 % der Wuerfe kostete).
        """
        if throw_number is None or foul_count is None:
            return False
        if self._last_read_throw_number is None or self._last_read_foul_count is None:
            # Noch kein Bezugspunkt -- der erste Wurf wird nie verworfen.
            return False
        return (throw_number == self._last_read_throw_number
                and foul_count == self._last_read_foul_count)

    def _check_foul_count(self, foul_count: int, pins_count: int,
                          checks: list[PlausibilityCheck],
                          decisions: list[str]) -> None:
        """Prueft den Fehlwurfzaehler gegen die erkannten Leerwuerfe (Q2).

        Ein Wurf mit 0 Kegeln aendert weder Kegelanzeige noch Summe -- er ist
        der am leichtesten zu uebersehende Fall. Der Zaehler der Tafel muss
        genau dann steigen, wenn ein Leerwurf erkannt wurde.
        """
        if self._foul_count is None:
            self._foul_count = foul_count
            return

        expected = self._foul_count + (1 if pins_count == 0 else 0)
        matches = (foul_count == expected)
        checks.append(PlausibilityCheck("Fehlwurfzaehler", expected, foul_count, matches))
        if not matches:
            log.warning("Bahn %d: Fehlwurfzaehler erwartet %d, Tafel zeigt %d -- "
                        "moeglicherweise ein Leerwurf uebersehen",
                        self.display_number, expected, foul_count)
            decisions.append("Fehlwurfzaehler weicht ab -- Leerwurf uebersehen?")
        self._foul_count = foul_count

    def _determine_status(self, count: int, pins: PinLampReading | None,
                          sources_agree: bool,
                          checks: list[PlausibilityCheck]) -> ThrowStatus:
        """Legt den Status fest (siehe Skill `kegel-domain`, Abschnitt 7)."""
        if pins is None or not pins.is_complete:
            return ThrowStatus.ERROR

        # Nur Pruefungen zaehlen, die etwas ueber das ERGEBNIS aussagen.
        #
        # Eine falsch gelesene Wurfnummer sagt nichts darueber, wie viele Kegel
        # gefallen sind -- sie betrifft die Buchfuehrung. Frueher zaehlte sie
        # mit, und ein sauber gemessener Wurf wurde allein deshalb als ERROR
        # ausgegeben, weil die dreistellige Nummer flackerte. Der Widerspruch
        # bleibt in der Beweiskette sichtbar und senkt die Confidence; er
        # entwertet das Ergebnis aber nicht mehr.
        failed = sum(1 for c in checks if not c.passed and c.affects_result)
        if failed >= 2:
            # Mehrere widersprechende Quellen -- Ergebnis nicht uebernehmen
            return ThrowStatus.ERROR

        if count == 0:
            # Ein Wurf ohne Kegel ist regulaer ("Pumpe"), kein Fehler
            return ThrowStatus.EMPTY
        return ThrowStatus.VALID

    def _confidence(self, pins: PinLampReading | None, sources_agree: bool,
                    checks: list[PlausibilityCheck]) -> float:
        """Gesamt-Confidence aus den Einzelquellen.

        Kein erfundener Festwert: Ausgangspunkt ist die Lampenmessung, davon
        gehen Abschlaege fuer jede verletzte Pruefung ab.
        """
        confidence = pins.confidence if pins is not None else 0.0
        if not sources_agree:
            confidence -= self.cfg.scoring.mismatch_confidence_penalty
        for check in checks:
            if not check.passed:
                # Buchfuehrungsfehler kosten weniger als Ergebnisfehler
                confidence -= 0.15 if check.affects_result else 0.05
        return max(0.0, min(1.0, confidence))

    def reset(self) -> None:
        self.score = LaneScore(lane=self.lane_id,
                               throws_per_cycle=self.cfg.scoring.throws_per_cycle)
        self._last_throw_number = None
        self._foul_count = None
