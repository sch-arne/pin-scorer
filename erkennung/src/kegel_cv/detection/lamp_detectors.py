"""Detektoren fuer die gruene Lampe und die neun Kegellampen.

Alle Schwellwerte stammen aus Messungen am realen Material
(siehe docs/VIDEO_ANALYSIS.md und tools/measure_signal.py), nicht aus Schaetzung.
"""

from __future__ import annotations

import logging

import cv2
from collections import deque

import numpy as np

from ..config.schema import GreenDetectionConfig, LampDetectionConfig
from ..models.readings import (
    LampReading,
    LampState,
    PinLampReading,
    confidence_from_threshold,
)

log = logging.getLogger(__name__)


class GleitendesHistogramm:
    """Trennt die AUS- von der AN-Wolke ueber ein rollendes Histogramm.

    WARUM NICHT PERZENTILE: Sie setzen voraus, dass beide Zustaende im
    Fenster ungefaehr im erwarteten Verhaeltnis vorkommen. GEMESSEN am
    2026-08-30 auf Bahn 5 lag die Bahn 71 % der letzten 60 Sekunden auf AN.
    Damit war das 20. Perzentil (40,0) kein AUS-Niveau mehr, sondern der
    untere Rand der AN-Wolke -- und die daraus errechnete AUS-Schwelle (52,0)
    lag mitten in der AN-Wolke. Score 47,8 wurde als AUS gelesen, drei Frames
    spaeter derselbe Score als AN. Der dabei entstandene GREEN_OFF erzeugte
    einen Wurf, den es nie gab.

    Ein Histogramm setzt das nicht voraus. Es zeigt die Wolken so, wie sie
    sind, und die Schwelle kommt ins Tal dazwischen.

    DIE SPERRE ist der wichtigere Teil: Gibt es nur EINE Wolke, wird keine
    Schwelle gerechnet und die zuletzt gemessene behalten. Ohne sie passiert
    genau das, was BUG-013 schon einmal angerichtet hat -- in einem
    durchgehend leuchtenden Signal wird ein kuenstliches AUS gesucht, und aus
    einem Wurf werden zwei.
    """

    def __init__(self, cfg: GreenDetectionConfig) -> None:
        self.cfg = cfg
        self._anzahl_bins = int(100.0 / cfg.histogram_bin) + 1
        self._bins = np.zeros(self._anzahl_bins, dtype=np.int32)
        self._werte: deque[int] = deque()
        self._schwellen = (cfg.on_threshold, cfg.off_threshold)
        self._gemessen = False
        self._seit_takt = 0
        # Wo die AUS-Wolke liegt. Nicht die Schwelle, sondern das NIVEAU --
        # daran misst sich, was "deutlich darunter" heisst (Verdeckung).
        self._aus_niveau: float | None = None
        # Der UNTERE RAND derselben Wolke -- die Stelle, an der sie duenn wird.
        # Er ist die bessere Bezugsgroesse fuer eine Verdeckung als der Gipfel;
        # warum, steht bei `_untere_flanke`.
        self._aus_rand: float | None = None

    @property
    def gemessen(self) -> bool:
        """Stammen die Schwellen aus einem zweigipfligen Fenster?"""
        return self._gemessen

    @property
    def aus_niveau(self) -> float | None:
        """Wo die AUS-Wolke liegt -- None, solange keine zwei Wolken da sind."""
        return self._aus_niveau

    @property
    def aus_rand(self) -> float | None:
        """Der untere Rand der AUS-Wolke -- None ohne zwei Wolken."""
        return self._aus_rand

    def vergiss(self) -> None:
        """Wirft das Gedaechtnis weg -- nach einer verschobenen ROI.

        WOFUER: Wird die ROI der gruenen Lampe im laufenden Betrieb gezogen,
        misst dieselbe Lampe ab sofort ANDERE Pegel. Die alten Werte im Fenster
        beschreiben dann eine Lage, die es nicht mehr gibt, und das Tal
        dazwischen liegt falsch. Lieber eine Minute ohne gemessene Schwelle
        (dann gelten die festen aus der Konfiguration) als eine Schwelle, die
        aus zwei verschiedenen Messstellen zusammengesetzt ist.
        """
        self._bins[:] = 0
        self._werte.clear()
        self._schwellen = (self.cfg.on_threshold, self.cfg.off_threshold)
        self._gemessen = False
        self._seit_takt = 0
        self._aus_niveau = None
        self._aus_rand = None

    def hinzufuegen(self, wert: float) -> None:
        i = min(self._anzahl_bins - 1, max(0, int(wert / self.cfg.histogram_bin)))
        self._werte.append(i)
        self._bins[i] += 1
        while len(self._werte) > self.cfg.histogram_window:
            self._bins[self._werte.popleft()] -= 1

    def _tal_suchen(self) -> tuple[float, float] | None:
        """Tal zwischen den zwei groessten Gipfeln -- None bei einer Wolke."""
        gesamt = int(self._bins.sum())
        # Ein noch kaum gefuelltes Fenster sagt nichts ueber die Wolken aus.
        if gesamt < self.cfg.histogram_min_samples:
            return None

        kern = np.ones(self.cfg.histogram_smoothing, dtype=np.float32)
        kern /= self.cfg.histogram_smoothing
        h = np.convolve(self._bins.astype(np.float32), kern, mode="same")

        hoechster = int(np.argmax(h))
        mindest_bins = int(self.cfg.histogram_min_gap / self.cfg.histogram_bin)
        maske = np.abs(np.arange(self._anzahl_bins) - hoechster) >= mindest_bins
        if not maske.any() or h[maske].max() <= 0:
            return None
        zweiter = int(np.flatnonzero(maske)[int(np.argmax(h[maske]))])

        links, rechts = sorted((hoechster, zweiter))
        bereich = h[links + 1:rechts]
        if bereich.size < 1:
            return None
        # MITTE der tiefsten Stelle, nicht ihr linker Rand.
        #
        # Zwischen zwei klar getrennten Wolken ist das Tal meist mehrere Bins
        # breit und komplett leer. `argmin` liefert dort den ERSTEN dieser
        # Bins -- also die Schwelle direkt an der Flanke der unteren Wolke.
        # Gemessen an einem synthetischen Wechsel 37/70 laege die AUS-Schwelle
        # dann bei 35,6, und ein AUS-Wert von 37,0 bliebe UNKNOWN.
        tiefste = np.flatnonzero(bereich <= bereich.min() + 1e-6)
        tal = links + 1 + int(tiefste[len(tiefste) // 2])

        # ZWEI Wolken -- oder eine mit einer Delle? Beide Bedingungen noetig.
        unten = int(self._bins[:tal].sum())
        oben = int(self._bins[tal:].sum())
        if min(unten, oben) < self.cfg.histogram_min_cloud * gesamt:
            return None
        kleinerer = float(min(h[links], h[rechts]))
        if kleinerer <= 0 or h[tal] > self.cfg.histogram_max_valley * kleinerer:
            return None

        tal_wert = (tal + 0.5) * self.cfg.histogram_bin
        rand = self.cfg.histogram_hysteresis * (rechts - links) * self.cfg.histogram_bin
        # Die untere Wolke ist das AUS-Niveau dieser Bahn. Es wird gebraucht,
        # um eine VERDECKUNG von einem gewoehnlichen AUS zu unterscheiden:
        # Verdeckt heisst deutlich unter dem, was AUS normalerweise misst.
        self._aus_niveau = (links + 0.5) * self.cfg.histogram_bin
        self._aus_rand = self._untere_flanke(h, links)
        return (tal_wert + rand, tal_wert - rand)

    def _untere_flanke(self, h: np.ndarray, gipfel: int) -> float:
        """Wo die AUS-Wolke nach unten hin duenn wird.

        WARUM NICHT EIN QUANTIL. Das naheliegende Mass fuer "unterer Rand der
        Wolke" waere ihr 1. Perzentil. Es ist unbrauchbar, weil die Wolke
        VERSCHMUTZT ist: Jeder Frame, in dem ein Mensch vor der Lampe stand,
        liegt als 0,0 mit darin, und ein Quantil zaehlt ihn mit.

        GEMESSEN 2026-09-14 ueber 42 400 Frames des Livestreams -- Wahrheit ist
        das 1. Perzentil der mit Wache und Personenmodell GEREINIGTEN Wolke:

            Bahn   Wahrheit   Quantil roh   Flanke roh
              2       20,8         20,8         25,0
              3       18,5          0,0         22,0
              4       25,0          0,0         30,0
              5       16,2         16,2         20,0

        Auf den Bahnen 3 und 4 zieht ein Bruchteil verdeckter Frames das
        Quantil auf null -- und damit haette die Verdeckungsbremse sich selbst
        abgeschaltet, ausgerechnet dort, wo sie am besten arbeitet. Kein Test
        waere rot geworden.

        Der Abstieg vom Gipfel sieht den Schmutz nicht, solange zwischen ihm
        und der Wolke eine Luecke liegt. Mittlerer Abstand zur Wahrheit ueber
        beide Quellen und alle acht Bahnen: 2,1 statt 5,4, groesster Fehler
        5,0 statt 25,0.

        Wo Wolke und Schmutz VERSCHMELZEN -- an der Hallenkamera liest ein
        echtes AUS auf Bahn 2 selbst 0,0 -- liefert der Abstieg richtigerweise
        0. Dort kann der Gruen-Score nichts trennen, und die Bremse schweigt.
        """
        grenze = self.cfg.histogram_edge_fraction * float(h[gipfel])
        i = gipfel
        while i > 0 and h[i - 1] >= grenze:
            i -= 1
        return i * self.cfg.histogram_bin

    def schwellen(self) -> tuple[float, float]:
        """Aktuelle (AN, AUS). Die Talsuche laeuft nur getaktet."""
        self._seit_takt += 1
        if self._seit_takt < self.cfg.histogram_interval:
            return self._schwellen
        self._seit_takt = 0

        neu = self._tal_suchen()
        if neu is None:
            # SPERRE -- keine Rueckschluesse aus einer einzigen Wolke.
            return self._schwellen
        self._schwellen = neu
        self._gemessen = True
        return neu


class HsvGreenDetector:
    """Gruene Lampe ueber den Anteil gruener Pixel im ROI.

    GEMESSEN (Video 2026-08-22, 4 Bahnen, 122 Frames):
        AUS -> Score 17,3 - 24,0
        AN  -> Score 59,9 - 74,3

    Die Baseline ist nicht null: Das beige Tafelgehaeuse hat selbst einen
    Gruenanteil. Ein Schwellwert nahe 0 wuerde also immer "AN" melden.
    """

    def __init__(self, cfg: GreenDetectionConfig) -> None:
        self.cfg = cfg
        self._lower = np.array([cfg.hue_min, cfg.saturation_min, cfg.value_min],
                               dtype=np.uint8)
        self._upper = np.array([cfg.hue_max, 255, 255], dtype=np.uint8)
        # Normierung der Confidence: Abstand, ab dem eine Messung als sicher gilt
        self._span = max(1.0, cfg.on_threshold - cfg.off_threshold)
        self._history: deque[float] = deque(maxlen=cfg.adaptive_window)
        self._histogramm = (GleitendesHistogramm(cfg)
                            if cfg.histogram_thresholds else None)
        # Anlaufregel: Niveau des laufenden Zustands, und der Zustand selbst.
        # UNKNOWN heisst hier ehrlich "noch nichts gesehen" -- erst nach der
        # ersten Aenderung ueber `warmup_min_change` gibt es eine Aussage.
        self._anlauf_niveau: float | None = None
        # Was die Anlaufregel ZULETZT gemeldet hat. None heisst: noch nie
        # eine Aenderung gesehen -- dann gilt das Schwellenurteil.
        self._anlauf_zustand: LampState | None = None

    @property
    def aus_niveau(self) -> float | None:
        """Das gemessene AUS-Niveau dieser Lampe -- None, wenn unbekannt.

        NUR aus dem Histogramm. Der Rueckfall auf ein Perzentil des gleitenden
        Fensters ist bewusst NICHT eingebaut: Liegt die Bahn ueberwiegend auf
        AN -- und das ist der Normalfall --, liefert jedes Perzentil das
        AN-Niveau. GEMESSEN an einem Abschnitt von 1100 Frames: 73,3 statt der
        wahren 25. Die Verdeckungsschwelle waere damit 22 statt 7 und laege
        mitten in der AUS-Wolke.

        Gebraucht wird es fuer die Verdeckungsbremse:
        VERDECKT heisst deutlich unter dem, was AUS normalerweise misst -- und
        was das ist, haengt an Kamera, Lampe und Ausschnitt, nicht an einer
        Zahl in der Konfiguration.
        """
        if self._histogramm is not None:
            return self._histogramm.aus_niveau
        return None

    @property
    def aus_rand(self) -> float | None:
        """Der UNTERE RAND der AUS-Wolke -- None, wenn unbekannt.

        Die Bezugsgroesse der Verdeckungsbremse. Der Gipfel der Wolke taugt
        dafuer nicht: Er sagt, wo AUS ueblicherweise liegt, aber nichts
        darueber, wie weit die Wolke nach unten reicht -- und genau dort
        entscheidet sich, ob ein niedriger Wert noch ein AUS ist oder schon
        eine Verdeckung.

        GEMESSEN 2026-09-14, Hallenkamera: Bahn 4 hat eine AUS-Wolke von 7,1
        bis 11,7, Bahn 2 eine von 0,0 bis 0,7. Gleiche Halle, gleiches Licht,
        gleicher Frame -- der Gipfel liegt bei 11,7 gegen 0,7, der untere Rand
        bei 7,0 gegen 0,0. Am Gipfel gemessen bekam Bahn 2 eine Schwelle von
        0,9 und bremste in 28 % aller Frames auf voellig freier Tafel.
        """
        if self._histogramm is not None:
            return self._histogramm.aus_rand
        return None

    def vergiss(self) -> None:
        """Gedaechtnis leeren -- nach einer verschobenen ROI (siehe dort)."""
        self._history.clear()
        if self._histogramm is not None:
            self._histogramm.vergiss()
        # Auch das Anlaufniveau gehoert zur alten Messstelle. Behielte man es,
        # saehe die neue ROI beim ersten Bild eine riesige "Aenderung" und
        # meldete einen Zustandswechsel, den es nie gab.
        self._anlauf_niveau = None
        self._anlauf_zustand = None

    def _thresholds(self) -> tuple[float, float]:
        """Schwellen (AN, AUS) -- anteilig zwischen den beobachteten Niveaus.

        GEMESSEN ueber 52 Minuten je Bahn: Beide Verteilungen wandern
        aufeinander zu, ueberlappen aber nie.

                        AUS 50%  AUS 95% |  AN 5%  AN 50%   Abstand
            Min 1-3        28,3     38,4 |   71,7    75,8    +33,3
            Min 47-49      36,4     43,4 |   69,7    74,7    +26,3
            Min 47-49 B4   36,1     41,7 |   56,5    63,0    +14,8

        Die festen Schwellen (35/45) liegen am Ende mitten in der
        AUS-Verteilung. Beobachtete Folge: Ueber 100 von 130 Messungen landeten
        im Graubereich, `GREEN_OFF` loeste erst 180 Frames spaeter aus -- und
        zu diesem Zeitpunkt hatte die Anlage die Kegellampen bereits
        zurueckgesetzt, sodass das Wurfergebnis als 0 gelesen wurde.

        Ein fester Wert kann das nicht auffangen, weil sich BEIDE Niveaus
        verschieben. Anteilig zwischen ihnen liegt die Schwelle dagegen immer
        richtig, solange sich die Verteilungen nicht beruehren.
        """
        absolut = (self.cfg.on_threshold, self.cfg.off_threshold)
        # Das Histogramm hat Vorrang: Es setzt nicht voraus, dass beide
        # Zustaende im erwarteten Verhaeltnis im Fenster liegen.
        if self._histogramm is not None:
            return self._histogramm.schwellen()
        if not self.cfg.adaptive_thresholds:
            return absolut
        if len(self._history) < self.cfg.adaptive_window // 3:
            return absolut

        werte = np.fromiter(self._history, dtype=np.float32)
        aus_niveau = float(np.percentile(werte, self.cfg.adaptive_off_percentile))
        an_niveau = float(np.percentile(werte, self.cfg.adaptive_on_percentile))
        spanne = an_niveau - aus_niveau

        # War die Lampe im ganzen Fenster in einem Zustand, liegen beide
        # Niveaus dicht beieinander. Dann sagt die Messung nichts ueber die
        # Trennung aus -- und eine Schwelle mitten im einen Zustand waere
        # schlimmer als die feste.
        if spanne < self.cfg.adaptive_min_span:
            return absolut

        return (aus_niveau + self.cfg.adaptive_on_fraction * spanne,
                aus_niveau + self.cfg.adaptive_off_fraction * spanne)

    def score(self, patch: np.ndarray) -> float:
        """Anteil gruener Pixel in Prozent."""
        if patch is None or patch.size == 0:
            return 0.0
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, self._lower, self._upper)
        return float(mask.mean() / 255.0 * 100.0)

    def _im_anlauf(self) -> bool:
        """Hat noch keines der beiden Lernverfahren etwas zu sagen?

        Sobald eines spricht, ist die Anlaufregel erledigt -- sie ist eine
        Ueberbrueckung, keine Dauerloesung. Das Histogramm meldet sich, wenn
        es ein Tal gefunden hat; die Perzentile, wenn die Spanne reicht.
        """
        if self.cfg.warmup_min_change <= 0:
            return False
        if self._histogramm is not None and self._histogramm.gemessen:
            return False
        if self.cfg.adaptive_thresholds and len(self._history) >= (
                self.cfg.adaptive_window // 3):
            werte = np.fromiter(self._history, dtype=np.float32)
            spanne = (float(np.percentile(werte, self.cfg.adaptive_on_percentile))
                      - float(np.percentile(werte,
                                            self.cfg.adaptive_off_percentile)))
            if spanne >= self.cfg.adaptive_min_span:
                return False
        return True

    def _anlaufzustand(self, value: float, bisher: LampState) -> LampState:
        """Ein Zustandswechsel allein aus der AENDERUNG, ohne absoluten Bezug.

        WOZU (Nutzer, 2026-10-06): *„wir hoffen ja nur, dass aus irgendwo
        drunter liegt und an irgendwo drueber... wir sollten eher mal
        schauen, ob wir es dadurch schaffen, dass wir sagen am Anfang
        brauchen wir eine Aenderung > 10 oder so."*

        Eine feste Schwelle muss wissen, WO die Wolken liegen, und haengt
        damit an der ROI. Eine Aenderung muss das nicht -- sie braucht nur,
        dass die Wolken WEIT GENUG auseinanderliegen, und das ist die eine
        Groesse, die ueber alle vier Bahnen stabil ist (Spanne 35 bis 48).

        SIE ERSETZT DIE SCHWELLEN NICHT. Beim ersten Bild gibt es noch kein
        Niveau; dann gilt, was die Schwellen sagen. Erst wenn ein Wert um
        mehr als `warmup_min_change` vom laufenden Niveau abweicht, meldet
        diese Regel einen Wechsel -- und darf dabei auch ein eindeutiges
        Schwellenurteil ueberstimmen. Genau das ist noetig: Auf Bahn 4 lagen
        mit der besseren ROI BEIDE Wolken ueber der festen AN-Schwelle (AUS
        50,0 gegen 45), die Lampe galt also dauerhaft als an.

        HOEHER HEISST AN -- gruene Pixel entstehen nur, wenn die Lampe
        leuchtet. Das Niveau wird sonst langsam nachgefuehrt, damit eine
        driftende Saalbeleuchtung mitgenommen wird, eine einzelne Messung
        aber nicht.

        Die Messtabelle steht bei `warmup_min_change` in der Konfiguration.
        """
        schwelle = self.cfg.warmup_min_change
        if self._anlauf_niveau is None:
            self._anlauf_niveau = value
            return bisher
        if value > self._anlauf_niveau + schwelle:
            self._anlauf_niveau = value
            self._anlauf_zustand = LampState.ON
        elif value < self._anlauf_niveau - schwelle:
            self._anlauf_niveau = value
            self._anlauf_zustand = LampState.OFF
        else:
            d = self.cfg.warmup_level_decay
            self._anlauf_niveau = (1.0 - d) * self._anlauf_niveau + d * value
        # SIE HAELT IHREN ZUSTAND. Gaebe sie zwischen zwei Aenderungen das
        # Schwellenurteil zurueck, waere sie wirkungslos: Gemessen auf Bahn 4
        # meldete sie bei Frame 10470 richtig AUS (Score 77,1 auf 64,6) und
        # fiel beim naechsten Bild sofort auf AN zurueck, weil 56,2 ueber der
        # festen AN-Schwelle von 45 liegt. Ein einzelnes AUS aber reicht der
        # Zustandsmaschine nicht (`min_stable_frames`), und der Wurf blieb
        # verloren.
        return bisher if self._anlauf_zustand is None else self._anlauf_zustand

    def detect(self, patch: np.ndarray) -> LampReading:
        if patch is None or patch.size == 0:
            # Leerer ROI heisst NICHT "Lampe aus" -- er heisst, dass nichts
            # gemessen werden konnte. Der Unterschied ist wesentlich, weil
            # "aus" den Trigger ausloesen wuerde. Siehe BUG-001.
            return LampReading.unknown(name="green_lamp")

        value = self.score(patch)
        # VERDECKTE TAFEL gehoert nicht ins Gedaechtnis. Steht ein Spieler vor
        # der Tafel, faellt der Score auf nahe null -- das ist keine Messung
        # der Lampe, sondern ihr Fehlen. Als AUS-Wolke gezaehlt zoege es die
        # Schwelle nach unten und liesse spaeter echte AUS-Phasen durchgehen.
        verdeckt = value < self.cfg.occlusion_score
        if not verdeckt:
            if self._histogramm is not None:
                self._histogramm.hinzufuegen(value)
            if self.cfg.adaptive_thresholds:
                self._history.append(value)
        an_schwelle, aus_schwelle = self._thresholds()

        if value >= an_schwelle:
            state = LampState.ON
        elif value <= aus_schwelle:
            state = LampState.OFF
        else:
            # In der Hysteresezone: Der bisherige Zustand bleibt bestehen.
            # Darueber entscheidet die Zustandsmaschine, nicht der Detektor.
            state = LampState.UNKNOWN

        # ZUSAETZLICH, nicht ersatzweise: Solange keines der Lernverfahren
        # spricht, darf auch eine AENDERUNG einen Wechsel melden. Die festen
        # Schwellen bleiben unangetastet -- sie tragen den Normalfall, die
        # Aenderung faengt den Fall ab, in dem beide Wolken ueber der festen
        # Schwelle liegen (siehe `_anlaufzustand`).
        if not verdeckt and self._im_anlauf():
            state = self._anlaufzustand(value, state)

        return LampReading(
            state=state,
            score=value,
            confidence=confidence_from_threshold(
                value, an_schwelle, aus_schwelle,
                max(1.0, an_schwelle - aus_schwelle)
            ),
            name="green_lamp",
        )


class WarmthLampDetector:
    """Kegellampen ueber Farbwaerme und Helligkeit.

    GEMESSEN ueber 3600 Einzelmessungen (4 Tafeln x 9 Lampen x 100 Frames,
    Video 2026-08-22 09-24-46):
        Helligkeit  AUS 154 +- 23   AN 254 +- 3    Trennguete 7,66
        Waerme      AUS  19 +- 10   AN  57 +- 13   Trennguete 3,35

    Die **Helligkeit** trennt mehr als doppelt so gut: Eine leuchtende Lampe ist
    im Bild gesaettigt, daher die winzige Streuung. Die Waerme dient nur noch als
    Plausibilitaetsschranke gegen helle, aber farblose Reflexe.

    (Eine fruehere Messung an einem einzelnen Frame legte das Gegenteil nahe.
    Sie beruhte auf zu wenigen Datenpunkten -- ein Beleg dafuer, Schwellwerte
    ueber viele Frames und alle Bahnen zu bestimmen, nicht an einem Standbild.)

    Gemessen wird nur der helle Kern des ROI (oberstes Perzentil), weil die Lampe
    den rechteckigen ROI nie ganz ausfuellt -- ein Mittelwert ueber alles wuerde
    das Signal mit Gehaeusefarbe verwaessern.
    """

    def __init__(self, cfg: LampDetectionConfig) -> None:
        self.cfg = cfg
        self._span = max(1.0, cfg.brightness_on_threshold - cfg.brightness_off_threshold)
        # Gedaechtnis je Lampe fuer den mitlaufenden AUS-Bezugswert
        self._history: dict[str, deque[float]] = {}
        # Zweites Gedaechtnis fuer die LEUCHTENDEN Messungen -- siehe
        # `_beide_wolken`.
        self._an_history: dict[str, deque[float]] = {}

    def vergiss(self) -> None:
        """Beide Gedaechtnisse leeren -- nach verschobenen Lampen-ROIs.

        Der mitlaufende AUS-Bezugswert ist an die MESSSTELLE gebunden. Wandert
        sie, beschreibt er die alte Stelle weiter und die Schwelle sitzt falsch.
        """
        self._history.clear()
        self._an_history.clear()

    def _beide_wolken(self, name: str) -> tuple[float, float] | None:
        """Schwellen aus BEIDEN gemessenen Wolken -- oder None, wenn zu duenn.

        WARUM DAS NOETIG WURDE: Die aeltere Rechnung fuehrt nur die AUS-Seite
        mit und nimmt fuer die AN-Seite `brightness_saturated` (255) an. Diese
        Annahme ist gemessen falsch, und zwar unterschiedlich je Bahn:

            Bahn   AN-Wolke (Median)   angenommen   Fehler
               2               252,6          255     +2,4
               3               249,0          255     +6,0
               4               243,3          255    +11,7
               5               246,2          255     +8,8

        Weil die Schwelle als ANTEIL dieses Abstands gerechnet wird, rutscht
        sie genau dort nach oben, wo die Lampen ohnehin am schwaechsten
        leuchten -- der Fehler verstaerkt sich selbst. Auf Bahn 4 blieben
        dadurch nur 5,8 Punkte zwischen Schwelle und AN-Wolke, und der einzige
        Wurf, der gegen das Wurfprotokoll falsch war (F289308), ging genau dort
        verloren: eine Lampe mit 227,7 gegen eine Schwelle von 228,9.

        Werden BEIDE Wolken gemessen, entfaellt jede Annahme ueber Saettigung.
        Die Schwellen liegen dann mittig zwischen den gemessenen Raendern.

        DIE RUECKKOPPLUNG IST BEWUSST DURCHBROCHEN: Das AN-Gedaechtnis wird
        NICHT aus der Klassifikation gefuellt, sondern aus einer festen
        Schranke (`an_ignore_below`). Sonst entschiede die Schwelle darueber,
        welche Messungen die Schwelle bestimmen -- ein Kreis, der beliebig weit
        driften kann.
        """
        aus_werte = self._history.get(name)
        an_werte = self._an_history.get(name)
        mindest = max(20, self.cfg.baseline_window // 8)
        if (aus_werte is None or an_werte is None
                or len(aus_werte) < mindest or len(an_werte) < mindest):
            return None

        aus_rand = float(np.percentile(
            np.fromiter(aus_werte, dtype=np.float32), self.cfg.aus_rand_percentile))
        an_rand = float(np.percentile(
            np.fromiter(an_werte, dtype=np.float32), self.cfg.an_rand_percentile))

        # Beruehren sich die Wolken, ist die Trennung ohnehin nicht zu retten.
        # Dann lieber die bewaehrte Rechnung als eine Schwelle mitten im Signal.
        if an_rand - aus_rand < self.cfg.min_wolken_abstand:
            return None

        mitte = (aus_rand + an_rand) / 2.0
        halbe_totzone = (an_rand - aus_rand) * self.cfg.totzone_anteil / 2.0
        return (mitte + halbe_totzone, mitte - halbe_totzone)

    def _thresholds(self, name: str) -> tuple[float, float]:
        """Schwellen (AN, AUS) fuer diese Lampe -- ggf. an die Drift angepasst.

        GEMESSEN ueber 52 Minuten: Die Helligkeit der AUSGESCHALTETEN Lampen
        steigt von Median 151 auf 185. Am Ende liegen 24 % aller AUS-Messungen
        ueber der festen Schwelle 195 und werden dadurch UNKNOWN -- 22 der 31
        Fehlerfaelle eines ganzen Trainings gingen darauf zurueck, und alle 22
        lagen in der zweiten Haelfte des Videos.

        Die Drift betrifft nur die Tafeln, nicht das uebrige Bild. Ein globaler
        Helligkeitsausgleich wuerde also nichts nuetzen; der Bezugswert muss von
        der Lampe selbst kommen.

        Solange das Gedaechtnis zu duenn ist, gelten die absoluten Schwellen --
        lieber die bewaehrte Einstellung als ein Bezugswert aus drei Messungen.
        """
        absolut = (self.cfg.brightness_on_threshold, self.cfg.brightness_off_threshold)
        if not self.cfg.adaptive_baseline:
            return absolut

        # Erst der Weg ohne Annahme ueber die Saettigung. Er greift nur, wenn
        # beide Wolken belegt sind -- sonst faellt es auf die Rechnung darunter
        # zurueck, die mit der AUS-Seite allein auskommt.
        if self.cfg.adaptive_on_level:
            beide = self._beide_wolken(name)
            if beide is not None:
                return beide

        werte = self._history.get(name)
        if werte is None or len(werte) < self.cfg.baseline_window // 4:
            return absolut

        niveau = float(np.percentile(np.fromiter(werte, dtype=np.float32),
                                     self.cfg.baseline_percentile))
        # Nie unter das gemessene Ausgangsniveau und nie unbegrenzt darueber:
        # Stuende eine Lampe ungewoehnlich lange an, zoege sie sonst ihren
        # eigenen Bezugswert mit nach oben und wuerde am Ende als AUS gelesen.
        untergrenze = self.cfg.brightness_off_threshold - self.cfg.baseline_off_margin
        obergrenze = untergrenze + self.cfg.baseline_max_drift
        niveau = min(max(niveau, untergrenze), obergrenze)

        # ANTEILIG statt additiv. Ein fester Abstand setzt voraus, dass das
        # AN-Niveau mit der Grundlinie mitwandert -- das kann es nicht, eine
        # leuchtende Lampe ist im Bild GESAETTIGT.
        #
        # GEMESSEN ueber 479 Wuerfe (4311 Einzelmessungen):
        #     AN    min 229,1   Median 253,7   max 255,0
        #     AUS   min 134,2   Median 164,3   max 212,1
        #
        # Beobachtet wurde der Bruch an einer Lampe mit ungewoehnlich hohem
        # AUS-Niveau (212 statt 164): Additiv landete ihre AN-Schwelle bei
        # 212 + 45 = 257 -- oberhalb der Saettigung. Sie leuchtete mit 254 und
        # wurde als UNKNOWN gelesen, waehrend die Anzeige sie mitzaehlte.
        #
        # Anteilig bleibt die Schwelle immer zwischen Grundlinie und Saettigung:
        #     Niveau 164 -> AN 209  (additiv waeren es 209 gewesen)
        #     Niveau 212 -> AN 233  (additiv 257, also unerreichbar)
        spielraum = max(1.0, self.cfg.brightness_saturated - niveau)
        return (niveau + spielraum * self.cfg.baseline_on_fraction,
                niveau + spielraum * self.cfg.baseline_off_fraction)

    def schwellen_von(self, name: str) -> tuple[float, float, float]:
        """(AN, AUS, Grundlinie) einer Lampe -- NUR zum Nachsehen.

        Aendert nichts und liest kein Bild. Gebraucht von der Lampenspur
        (`debug/lamp_trace.py`): Ein Messwert allein sagt nichts darueber, ob
        er richtig eingeordnet wurde -- dafuer muss der Massstab mit
        aufgeschrieben werden, gegen den gemessen wurde.
        """
        an, aus = self._thresholds(name)
        werte = self._history.get(name)
        if werte is None or not self.cfg.adaptive_baseline:
            return an, aus, float("nan")
        if len(werte) < self.cfg.baseline_window // 4:
            return an, aus, float("nan")
        return an, aus, float(np.percentile(
            np.fromiter(werte, dtype=np.float32), self.cfg.baseline_percentile))

    def score(self, patch: np.ndarray) -> tuple[float, float]:
        """(Waerme, Helligkeit) des hellen ROI-Kerns."""
        if patch is None or patch.size == 0:
            return 0.0, 0.0

        blue = patch[:, :, 0].astype(np.float32)
        red = patch[:, :, 2].astype(np.float32)
        value = patch.max(axis=2).astype(np.float32)

        threshold = np.percentile(value, self.cfg.core_percentile)
        core = value >= threshold
        if not core.any():
            core = np.ones_like(value, dtype=bool)

        return float((red[core] - blue[core]).mean()), float(value[core].mean())

    def detect_one(self, patch: np.ndarray, name: str = "") -> LampReading:
        if patch is None or patch.size == 0:
            return LampReading.unknown(name=name)

        warmth, brightness = self.score(patch)

        # Nur moeglicherweise-AUS-Messungen praegen das Gedaechtnis. Eine
        # leuchtende Lampe darf ihr eigenes AUS-Niveau nicht anheben -- sonst
        # schaltet sie sich nach laengerem Dauerleuchten selbst ab.
        if (self.cfg.adaptive_baseline and name
                and brightness < self.cfg.baseline_ignore_above):
            self._history.setdefault(
                name, deque(maxlen=self.cfg.baseline_window)).append(brightness)

        # Dasselbe fuer die andere Wolke -- und aus demselben Grund an einer
        # FESTEN Schranke, nicht an der Klassifikation. Wuerde hier stehen
        # "wenn als AN erkannt", entschiede die Schwelle darueber, welche
        # Messungen die Schwelle bestimmen; eine solche Rueckkopplung kann
        # beliebig weit driften, ohne dass es auffaellt.
        if (self.cfg.adaptive_baseline and self.cfg.adaptive_on_level and name
                and brightness > self.cfg.an_ignore_below):
            self._an_history.setdefault(
                name, deque(maxlen=self.cfg.baseline_window)).append(brightness)

        an_schwelle, aus_schwelle = self._thresholds(name)

        # HELLIGKEIT ist das Hauptkriterium, nicht die Waerme.
        #
        # GEMESSEN ueber 3600 Einzelmessungen (4 Tafeln x 9 Lampen x 100 Frames):
        #     Helligkeit  AUS 154 +- 23   AN 254 +- 3    Trennguete 7,66
        #     Waerme      AUS  19 +- 10   AN  57 +- 13   Trennguete 3,35
        #
        # Eine leuchtende Lampe ist im Bild gesaettigt -- deshalb die winzige
        # Streuung von +-3. Die Waerme streut dagegen so stark, dass sich die
        # Verteilungen ueberlappen.
        #
        # Frueher waren beide Kriterien mit UND verknuepft. Das war der Fehler:
        # Bei einer UND-Verknuepfung bestimmt das SCHWAECHERE Kriterium das
        # Ergebnis. Klar leuchtende Lampen (Helligkeit 255) wurden als UNKNOWN
        # gemeldet, weil ihre Waerme mit 31 knapp unter der Schwelle lag.
        # Die Waerme dient jetzt nur noch als Plausibilitaetsschranke gegen
        # helle, aber farblose Reflexe -- und ist standardmaessig AUS.
        #
        # NACHTRAG 2026-09-16: Sie war nie wirklich aus. `warmth_min: 0.0`
        # sollte das ausdruecken, aber die Waerme (`rot - blau`) wird bei
        # einer weiss gesaettigten Lampe negativ. GEMESSEN auf Bahn 2,
        # F6600-6960: Helligkeit konstant 255,0, Waerme pendelnd zwischen
        # -0,3 und +0,3 -- der Zustand sprang sechsmal zwischen ON und
        # UNKNOWN, ohne dass jemand warf. Ueber den ganzen Mitschnitt traf es
        # 99 von 3685 hellen Messungen der Bahn 2 (2,7 %), auf Bahn 3 und 4
        # keine einzige.
        #
        # Ein solcher UNKNOWN-Kegel faellt aus der Liste der liegenden Kegel
        # und wirkt damit wie "steht". Bei einem Raeumwurf ist das Ergebnis
        # eine Differenz zweier Messungen -- der Punktestand war betroffen
        # (Bahn 2 Wurf 21: 5 gebucht, Ziffer und Summe sagten 4).
        warm_genug = (self.cfg.warmth_min is None
                      or warmth >= self.cfg.warmth_min)
        if brightness >= an_schwelle and warm_genug:
            state = LampState.ON
        elif brightness <= aus_schwelle:
            state = LampState.OFF
        else:
            state = LampState.UNKNOWN

        return LampReading(
            state=state,
            score=brightness,
            confidence=confidence_from_threshold(
                brightness, an_schwelle, aus_schwelle,
                max(1.0, an_schwelle - aus_schwelle)
            ),
            name=name,
        )

    def detect(self, patches: list[np.ndarray],
               pin_numbers: list[int]) -> PinLampReading:
        if len(patches) != len(pin_numbers):
            raise ValueError(
                f"{len(patches)} Ausschnitte, aber {len(pin_numbers)} Kegelnummern"
            )

        readings: list[LampReading] = []
        pins: list[int] = []

        for patch, pin in zip(patches, pin_numbers):
            reading = self.detect_one(patch, name=f"pin_lamp_{pin}")
            readings.append(reading)
            if reading.is_on:
                pins.append(pin)

        # Gesamt-Confidence = schwaechste Einzelmessung. Eine unsichere Lampe
        # macht die Zaehlung unsicher, egal wie eindeutig die anderen acht sind.
        confidence = min((r.confidence for r in readings), default=0.0)

        return PinLampReading(
            lamps=tuple(readings),
            pins=tuple(sorted(pins)),
            confidence=confidence,
        )
