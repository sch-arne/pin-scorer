"""Verarbeitung einer einzelnen Bahn.

Eine Instanz pro Bahn (Prinzip P6). Der Prozessor kennt die Kalibrierung seiner
Bahn, schneidet die ROIs aus jedem Frame und fuehrt die Zustandsmaschine.

Kostenstaffel (Auftrag Paragraph 20):
    JEDER Frame        -> nur die gruene Lampe (ein ROI von ca. 60 px)
    BEI GREEN_OFF      -> die neun Kegellampen als WURFERGEBNIS
    jeden n-ten Frame  -> die neun Kegellampen nur fuer die ANZEIGE
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from ..calibration.geometry import GeometryError, norm_rect_to_frame_bbox
from ..calibration.model import LaneCalibration
from ..config.schema import AppConfig
from ..detection.digit_detector import DigitReading
from ..detection.digit_reader import CalibratedDigitReader
from ..detection.digit_templates import TemplateDigitDetector
from ..detection.lamp_detectors import HsvGreenDetector, WarmthLampDetector
from ..detection.state_machine import EventType, LaneEvent, LaneState, LaneStateMachine
from ..models.readings import (LampReading, LampState, PinLampReading,
                              aggregate_pin_readings, baseline_aus_zwei,
                              grundlinie_aus_spur, ist_fehlercode)
from ..video.source import Frame, FrameBuffer
from .frame_sampler import FrameSampler, SampleEvent
from .board_image import encode_board
from .tafel_wache import TafelWache, stabile_maske_im_ausschnitt

log = logging.getLogger(__name__)


@dataclass
class LaneObservation:
    """Momentaufnahme einer Bahn -- das, was die GUI live anzeigt."""

    lane_id: int
    display_number: int
    state: LaneState
    green: LampReading
    pins: PinLampReading | None = None
    throw_count: int = 0
    running_total: int = 0
    last_event: LaneEvent | None = None
    sampling: bool = False          # laeuft gerade ein Sampling-Vorgang?
    # Was der Ziffernleser GERADE sieht, Feldname -> Lesung. NUR fuer die
    # Anzeige: Die Wurfzaehlung benutzt diese Werte nicht, sie fasst ihre
    # eigenen Messungen ueber das ganze Ereignisfenster zusammen.
    #
    # WOFUER -- Wunsch des Nutzers am 2026-09-11: "ich haette gerne, dass dort
    # auch steht, was er gerade an Ziffern erkannt hat ... Das wuerde mir
    # helfen bei der Evaluierung, ob wir die Ziffern bald wieder reinnehmen."
    digits: dict[str, DigitReading] = field(default_factory=dict)

    @property
    def green_text(self) -> str:
        return {LampState.ON: "AN", LampState.OFF: "AUS"}.get(self.green.state, "?")


class LaneProcessor:
    """Verarbeitet Frames einer Bahn und meldet Ereignisse."""

    def __init__(self, lane: LaneCalibration, cfg: AppConfig) -> None:
        self.lane = lane
        self.cfg = cfg
        self.lane_id = lane.lane_id
        self.display_number = lane.display_number

        self.green_detector = HsvGreenDetector(cfg.detection.green)
        self.lamp_detector = WarmthLampDetector(cfg.detection.lamps)
        self.state_machine = LaneStateMachine(
            lane_id=lane.lane_id,
            cfg=cfg.state_machine,
            min_stable_frames=cfg.detection.green.min_stable_frames,
        )
        # KEIN eigener Punktestand: Gebucht wird ausschliesslich im
        # ThrowAnalyzer. Zwei Zaehler waeren zwei Wahrheiten -- die Anzeige
        # zeigte 0, waehrend die Tabelle korrekte Summen enthielt.
        self.throw_count = 0
        self.running_total = 0

        # Die ROI-Rechtecke haengen nur von der Kalibrierung ab, nicht vom Frame.
        # Einmal vorberechnen statt 25-mal pro Sekunde -- das ist der Unterschied
        # zwischen Echtzeit und Diashow.
        self._transform = None
        self._green_box: tuple[int, int, int, int] | None = None
        self._lamp_boxes: list[tuple[int, int, int, int]] = []
        # Das Tafelbild, VOR dem der Spieler stand: der letzte Ausschnitt,
        # solange Gruen noch an war. Beim Abraeumen ist das die Aufstellung,
        # in die geworfen wird -- aus der Datenbank allein nicht zu
        # rekonstruieren. Roh gehalten und erst bei GREEN_OFF kodiert:
        # ein JPEG je Frame und Bahn waere reine Verschwendung.
        self._green_on_frame: int | None = None
        self._board_before: str | None = None
        self._pin_numbers: list[int] = []
        self._boxes_ready = False

        self._last_green = LampReading.unknown("green_lamp")
        # Ergebniswert (nur bei GREEN_OFF) und Anzeigewert (regelmaessig) sind
        # bewusst getrennt -- siehe process()
        self._result_pins: PinLampReading | None = None
        self._display_pins: PinLampReading | None = None
        # RAEUMEN (vom Nutzer erklaert): Geht die gruene Lampe an und es
        # leuchten bereits Kegellampen, muessen nur die noch stehenden Kegel
        # geraeumt werden. Die schon leuchtenden Lampen gehoeren NICHT zu diesem
        # Wurf. Das Wurfergebnis ist deshalb die DIFFERENZ zwischen dem Stand
        # bei GREEN_OFF und dem Stand bei GREEN_ON -- nicht der Endstand.
        self._pending_baseline: PinLampReading | None = None   # Wurf laeuft
        self._baseline_samples: list[PinLampReading] = []
        self._baseline_start: int | None = None                # Frame des GREEN_ON
        self._baseline_pins: PinLampReading | None = None      # Wurf beendet
        # DER STAND NACH DEM VORIGEN WURF. Eine der beiden einzigen erlaubten
        # Grundlinien des naechsten Wurfs -- die andere ist leer. Wird von der
        # Pipeline gesetzt, sobald sie das Wurfergebnis zusammengefasst hat
        # (`uebernimm_vorstand`), denn erst dort sind Gruenphase und die
        # Messungen danach zu einer Menge vereinigt.
        self._vorstand: PinLampReading | None = None
        # Alle Lampenmessungen des laufenden Ereignisses. Siehe BUG-007a:
        # Die Blinkperiode ist mit 28-30 Frames LAENGER als das Sampling-Fenster,
        # die Dunkelphase mit bis zu 15 Frames ebenfalls. Vier Frames innerhalb
        # von zehn koennen daher vollstaendig in einer Dunkelphase liegen.
        # Deshalb wird ueber das GANZE Fenster zwischen GREEN_OFF und dem
        # naechsten GREEN_ON gesammelt -- die Messungen dafuer laufen ohnehin.
        self._result_samples: list[PinLampReading] = []
        # Messungen NACH Gruen-AUS -- erst am Ende des Fensters wird
        # entschieden, ob sie ins Ergebnis gehoeren (siehe `result_samples`).
        self._nach_samples: list[PinLampReading] = []
        # Mitlesungen der SPAET aktualisierten Felder (Summe). Siehe
        # `read_late_fields`: Die Tafel traegt das Wurfergebnis erst kurz vor dem
        # naechsten GREEN_ON ein -- der Nutzer hat darauf hingewiesen, die
        # Messung bestaetigt es.
        self._late_samples: dict[str, deque[DigitReading]] = {}
        # SPIELWECHSEL (vom Nutzer beschrieben, 2026-08-28): Zwischen zwei
        # Spielen zeigt die untere Reihe `000  0000` -- Wurfnummer und Summe
        # zugleich auf null. GEMESSEN am 52-Minuten-Video: Der Zustand steht
        # 20 bis 90 Sekunden, tritt an allen drei Satzgrenzen auf allen vier
        # Bahnen auf und kam in 3000 Kontrollframes mitten im Satz KEIN
        # einziges Mal vor. Die Bahnen wechseln dabei NICHT gleichzeitig --
        # zwischen der ersten und der letzten lagen 36 Sekunden. Deshalb wird
        # je Bahn eigenstaendig gezaehlt (P6).
        #
        # Der Zustand steht in der PAUSE -- also im Fenster des LETZTEN Wurfs
        # des alten Spiels, nicht im Fenster des ersten neuen. GEMESSEN auf
        # Bahn 2 an der ersten Satzgrenze:
        #
        #     F18594   letzter Wurf Satz 1, gruen aus
        #     F18900   Nullzustand beginnt      <- Fenster dieses Wurfs
        #     F20025   Nullzustand endet
        #     F20148   erster Wurf Satz 2, gruen aus
        #
        # Deshalb wird das Zeichen um genau einen Wurf verzoegert weitergegeben.
        self._reset_observations = 0
        self._reset_latch = False
        self._verlassen_observations = 0
        self._reset_seen = False        # im laufenden Fenster gesehen
        self._reset_beginn = -1         # Frame, in dem der Nullzustand anfing
        self._reset_carry = False       # gilt dem naechsten ausgewerteten Wurf
        self._reset_pending = False     # gilt dem Wurf, der gerade ausgewertet wird

        # Das SAMMELFENSTER (Gruen-AUS bis zum naechsten Gruen-AN) ist nicht
        # mehr dasselbe wie das Wurffenster: Der Wurf wird frueher gemeldet
        # (`sampling.report_after_green_off`), aber Summe und Spielwechsel
        # stehen erst spaeter in der Anzeige und werden weiter mitgelesen.
        self._window_open = False
        self._green_off_frame: int | None = None
        # Lampenmessungen WAEHREND der Gruenphase -- dort fallen die Kegel.
        # (Frame, Messung) -- der Frame wird fuer den Breakpoint gebraucht.
        self._green_phase_samples: list[tuple[int, PinLampReading]] = []
        # VERDECKUNG IM LAUFENDEN FENSTER (BUG-017). Die Verdeckungsbremse
        # friert Zustand und Messung waehrend der Verdeckung zwar ein, aber
        # wenn das Fenster GENAU beim Wiedersichtbarwerden mit GREEN_ON
        # schliesst, geht ein leeres Ergebnis (0 Kegel) trotzdem als
        # bestaetigt durch -- dabei wurde in Wahrheit nichts gesehen, nicht
        # nichts geworfen. GEMESSEN an drei Faellen (Bahn5 F15569/F16256,
        # Bahn2 F265724): Alle drei haben eine Verdeckung MITTEN in ihrem
        # eigenen Sammelfenster, alle drei wurden als "0 Kegel, EMPTY"
        # gebucht. Deshalb: Merken, ob die Verdeckungsbremse waehrend eines
        # offenen Fensters ausgeloest hat, und dem Analyzer mitgeben.
        self._occlusion_during_window = False

        # FEHLWURFZAEHLER. Faellt bei einem Wurf kein Kegel, schaltet die
        # Anlage die gruene Lampe gar nicht aus -- es gibt nichts zu zaehlen
        # und nichts aufzustellen. Der Wurf ist damit fuer den Trigger
        # unsichtbar (Q10). Der Zaehler im linken Display ist die einzige
        # unabhaengige Quelle dafuer.
        #
        # Deshalb wird er IMMER gelesen, nicht nur im Wurffenster: Der Nullwurf
        # geschieht ja, waehrend die gruene Lampe an ist.
        self._foul_value: int | None = None        # letzter stabiler Stand
        self._foul_candidate: int | None = None
        self._foul_repeats = 0
        # Frame, Zeit, Wurfnummer der Tafel (soweit lesbar). Die Nummer
        # kommt mit, damit der Fehlwurf nicht blind fortgezaehlt wird --
        # sonst ist dieser Pfad blind fuer Spielgrenzen.
        self._foul_events: list[tuple[int, float, int | None]] = []

        # Wie viele Frames in Folge die Tafel verdeckt war
        self._occlusion_frames = 0
        # Verdeckung, die von AUSSEN gemeldet wird -- von der Personenmaske.
        # Sie ist das verlaesslichere Signal: Der Gruen-Score kann eine
        # Verdeckung nur erraten, die Maske hat die Person gesehen.
        self._extern_verdeckt = False
        self._live_interval = cfg.detection.lamps.live_preview_interval
        # Die letzten Anzeigemessungen -- NUR fuer die Live-Anzeige; die
        # Zaehlung ruehrt sie nicht an (siehe `_geglaettete_anzeige`).
        # Frames -> Messungen: Gelesen wird nur jeder `live_interval`-te.
        takt_anzeige = max(1, self._live_interval)
        self._display_history = deque(maxlen=max(1,
            cfg.detection.lamps.live_preview_smoothing_frames // takt_anzeige))

        # Der Lampenstand WAEHREND der Pause (BUG-016). Er ist die zweite,
        # von der Gruenerkennung unabhaengige Quelle fuer die Grundlinie:
        # Beim Raeumen bleiben die Ergebnislampen an, bis der naechste Wurf
        # abgeschlossen ist -- der Stand kurz vor dem Gruen-AN muss also
        # derselbe sein wie kurz danach. Weicht er ab, ist inzwischen etwas
        # gefallen, und das gehoert zum Wurf.
        takt = max(1, self._live_interval)
        self._pause_samples: deque[PinLampReading] = deque(
            maxlen=max(1, cfg.sampling.baseline_before_frames // takt))
        self._before_pins: PinLampReading | None = None
        # ALLE laufenden Lampenmessungen seit dem vorigen Wurf (BUG-031).
        # Aus ihnen kommt die Grundlinie, wenn `baseline_from_trace` gilt: Das
        # Fenster nach dem Gruen-AN trifft in seltenen Faellen einen ganz
        # anderen Augenblick als den Wurf, diese Spur nicht.
        #
        # 600 Eintraege reichen weit: Bei einem Takt von 25 Frames sind das
        # 15000 Frames = 10 Minuten. Die laengste gemessene Gruenphase eines
        # Spieltags betrug 2167 Frames.
        self._grundlinien_spur: deque[tuple[int, PinLampReading]] = deque(maxlen=600)
        # DIE WURFNUMMER IM SELBEN TAKT -- der Breakpoint (Nutzer, 2026-09-28):
        # *„wenn die Wurfnummer hochzählt, beginnen die 4 sek. sonst nehmen wir
        # das als Breakpoint und davor ist Grundlinie und danach bis Grün aus
        # ist Ergebnis."*
        #
        # GEMESSEN ueber 100 Gruenzyklen aller vier Bahnen: Die Nummer ist in
        # 100 % der Zyklen lesbar, der Sprung in 88 bis 96 % zu sehen, und er
        # liegt im Median 3,95 bis 4,35 s vor Gruen-AUS -- auf Bahn 2 und 3
        # liegen 80 % aller Zyklen zwischen 3,8 und 4,25 s.
        #
        # Der Anker ist damit ein EREIGNIS AUF DER TAFEL statt einer Uhr. Das
        # loest drei Dinge auf einmal: Die Grundlinie ist "alles bis zum
        # Sprung" statt eines festen Fensters (bei kurzen Raeumzyklen
        # entsprechend kurz), das Ergebnis ist "ab dem Sprung", und kein
        # Schwellwert muss zum Spieltag passen.
        self._nummer_spur: deque[tuple[int, int]] = deque(maxlen=600)
        # Wird von der Pipeline gesetzt. None heisst: keine Spur.
        self.lamp_trace = None
        # WACHE UEBER DEN TAFELAUSSCHNITT. Sie haelt eine Referenz der eigenen
        # Tafel und meldet, was nicht dazugehoert -- auch einen Menschen, der
        # STILLSTEHT und den die Bewegungsmaske deshalb nicht mehr sieht
        # (gemessen 2026-09-13, siehe `tafel_wache`). Nur fuer Bilder, die
        # veroeffentlicht werden; die Messung liest den Ausschnitt roh.
        self.wache = TafelWache(
            None,   # wird in `prepare` gesetzt -- vorher fehlt die Bildgroesse
            abweichung_grau=cfg.detection.person_mask.wache_abweichung_grau,
            schwelle=cfg.detection.person_mask.wache_schwelle,
            nachlernen_unter=cfg.detection.person_mask.wache_nachlernen_unter,
            lernrate=cfg.detection.person_mask.wache_lernrate,
            wachstum=cfg.detection.person_mask.wache_wachstum)
        self._wache_takt = cfg.detection.person_mask.wache_takt
        # Meldet die Wache gerade etwas Fremdes auf der Tafel?
        #
        # ZWEI FRAGEN, ZWEI SCHWELLEN (BUG-030). `_wache_meldet_fremdes` gilt
        # dem SCHWAERZEN und der Erholung einer festhaengenden Referenz;
        # `_wache_bremst` gilt dem ANHALTEN der Auswertung und verlangt sehr
        # viel mehr. Die Wache sagt in ihrem eigenen Kopf: "Diese Wache
        # entscheidet NICHTS ueber Wuerfe" -- mit einer Schwelle fuer beides
        # tat sie es trotzdem.
        self._wache_meldet_fremdes = False
        self._wache_bremst = False
        self._wache_bremse_schwelle = (
            cfg.detection.person_mask.wache_bremse_schwelle)
        # DAS PERSONENMODELL, der vierte Zeuge. Es gehoert der Pipeline, nicht
        # dieser Bahn -- alle vier Bahnen teilen sich EINEN Durchlauf je Frame
        # (siehe `detection/personen_modell.py`). Bis es gesetzt wird, arbeitet
        # die Bahn mit drei Zeugen weiter.
        self.personen_modell = None
        self._rohbild = None
        self._modell_meldet_person = False
        self._modell_anteil = 0.0
        self._modell_takt = cfg.detection.person_model.patrol_interval
        self._modell_alarmtakt = cfg.detection.person_model.alarm_interval
        self._modell_deckung = cfg.detection.person_model.board_coverage
        self._modell_zuletzt: int | None = None
        # Wie lange die Wache schon meldet, OHNE dass das Modell einen
        # Menschen sieht -- siehe `_pruefe_festhaengende_wache` (BUG-026).
        self._neustart_frames = cfg.detection.person_mask.wache_neustart_frames
        self._wache_daueralarm = 0
        self._late_interval = cfg.detection.digits.late_read_interval
        self._late_keep = cfg.detection.digits.late_keep
        # Die Ziffern fuer die LIVE-ANZEIGE -- siehe `_lies_anzeige_live`.
        # Sie gehen in keine Zaehlung.
        self._live_digit_interval = cfg.detection.digits.live_read_interval
        self._live_digits: dict[str, DigitReading] = {}
        self.sampler = FrameSampler(lane.lane_id, cfg.sampling)
        self._preview_warned = False

        # Ziffernfelder: Name -> Stellenzahl. Die Ziffern sind Gegenprobe,
        # nicht Hauptquelle (siehe throw_analyzer).
        self.digit_detector = TemplateDigitDetector(cfg.detection.digits)
        # Leser fuer einzeln eingerahmte Ziffern. Wird bevorzugt, wo Rahmen
        # vorliegen: GEMESSEN 8/12 gegenueber 7/12 -- und bei der Wurfnummer,
        # die den Double-Counting-Schutz traegt, 4/4 statt 2/4.
        self.digit_reader = CalibratedDigitReader(cfg.detection.digits)
        self._digit_boxes: dict[str, tuple[tuple[int, int, int, int], int]] = {}
        # Name -> Liste der Boxen je Stelle (nur wo einzeln eingerahmt)
        self._digit_cell_boxes: dict[str, list[tuple[int, int, int, int]]] = {}
        # Feinausrichtung je Stelle, einmal je Video bestimmt (siehe
        # refine_digit_boxes). Die Rahmen werden von Hand gesetzt; ein Versatz
        # von ein bis zwei Pixeln entscheidet bei 13x18 px grossen Ziffern
        # darueber, ob ein Segment in seiner Messflaeche liegt.
        self._digit_shifts: dict[str, list[tuple[int, int]]] = {}
        self._refined = False

    # ------------------------------------------------------------- Vorbereitung

    def prepare(self, frame_shape: tuple[int, ...]) -> bool:
        """Berechnet die ROI-Rechtecke fuer die Bildgroesse. Einmal pro Video."""
        try:
            self._transform = self.lane.transform(
                self.cfg.calibration.warped_width, self.cfg.calibration.warped_height
            )
        except GeometryError as exc:
            log.error("Bahn %d: Kalibrierung unbrauchbar: %s", self.display_number, exc)
            return False

        green_roi = self.lane.get_roi("green_lamp")
        if green_roi is None:
            log.error("Bahn %d: keine ROI fuer die gruene Lampe -- Bahn wird "
                      "uebersprungen", self.display_number)
            return False

        self._green_box = norm_rect_to_frame_bbox(
            self._transform, green_roi.rect, frame_shape
        )

        self._lamp_boxes = []
        self._pin_numbers = []
        for roi in self.lane.pin_lamps():
            if not roi.enabled:
                continue
            self._lamp_boxes.append(
                norm_rect_to_frame_bbox(self._transform, roi.rect, frame_shape)
            )
            # Fallback auf den Lampenindex, falls kein Mapping gepflegt ist.
            # Das trifft nur alte Kalibrierungen -- seit Q5 (2026-09-01) traegt
            # jede Lampe ihre Kegelnummer, und die ist NICHT ihr Index.
            self._pin_numbers.append(
                roi.pin_number if roi.pin_number is not None
                else int(roi.name.removeprefix("pin_lamp_"))
            )

        if not self._lamp_boxes:
            log.warning("Bahn %d: keine Kegellampen kalibriert -- nur "
                        "Gruenerkennung moeglich", self.display_number)

        # Ziffernfelder mit ihrer Stellenzahl
        self._digit_boxes = {}
        self._digit_cell_boxes = {}
        for name, digits in (("throw_number", 3), ("pin_count", 1),
                             ("total_a", 4), ("total_b", 4), ("left_display", 2)):
            # Einzeln eingerahmte Stellen haben Vorrang
            cells = self.lane.digit_rois(name)
            if cells:
                self._digit_cell_boxes[name] = [
                    norm_rect_to_frame_bbox(self._transform, c.rect, frame_shape)
                    for c in cells
                ]
                continue
            roi = self.lane.get_roi(name)
            if roi is None or not roi.enabled:
                continue
            self._digit_boxes[name] = (
                norm_rect_to_frame_bbox(self._transform, roi.rect, frame_shape), digits
            )

        # DIE WACHE BRAUCHT IHRE STABILE MASKE. Ohne sie vergleicht sie
        # nichts und meldet nie etwas -- genau das ist am 2026-09-13 passiert:
        # eingebaut, verdrahtet, getestet, und im Lauf ueber 312 783 Frames
        # kein einziges Mal ausgeloest, weil hier `None` stand.
        box = self.lane_box()
        if box is not None:
            self.wache.setze_stabil(stabile_maske_im_ausschnitt(
                self.lane.rois, self._transform, box, frame_shape))

        self._boxes_ready = True
        log.info("Bahn %d vorbereitet: Gruenlampe %s, %d Kegellampen, "
                 "%d Ziffernfelder (%d davon stellenweise eingerahmt)",
                 self.display_number, self._green_box, len(self._lamp_boxes),
                 len(self._digit_boxes) + len(self._digit_cell_boxes),
                 len(self._digit_cell_boxes))
        return True

    def uebernimm_kalibrierung(self, neue_bahn,
                               frame_shape: tuple[int, ...]) -> list[str]:
        """Nimmt im LAUFENDEN Betrieb geaenderte Bereiche entgegen.

        WOFUER -- Befund des Nutzers am 2026-09-11:

            "wenn man die ROIs im Livestream verschiebt, aendert sich ja gar
             nichts... ich habe Rahmen von Gruen weggezogen und von der
             Pin_Count und es lief einfach weiter, als haette ich nichts
             geaendert"

        Und so war es auch: `prepare` rechnet die normierten Bereiche EINMAL in
        Pixelrechtecke um, danach liest die Analyse nur noch diese Rechtecke.
        Wer die normierten Koordinaten verschiebt, verschiebt nichts, was noch
        gelesen wird. Das war nicht einmal sichtbar -- der Rahmen sprang im
        Bild, die Messung blieb.

        WAS DABEI VERGESSEN WERDEN MUSS: Die mitlaufenden Schwellen sind an die
        MESSSTELLE gebunden. Wandert sie, beschreiben die gesammelten Werte eine
        Lage, die es nicht mehr gibt. Deshalb wird das Gedaechtnis der
        betroffenen Detektoren geleert -- eine Minute mit den festen Schwellen
        aus der Konfiguration ist besser als eine Schwelle aus zwei
        verschiedenen Messstellen.

        Der ZUSTAND der Bahn bleibt: Wurfzaehler, Zustandsmaschine und Summen
        haengen nicht an der ROI-Lage, und sie neu zu setzen hiesse, Wuerfe
        doppelt oder gar nicht zu buchen.

        Zurueck kommt, was sich geaendert hat -- fuer das Protokoll.
        """
        alt_gruen = self.lane.get_roi("green_lamp")
        alt_lampen = [r.rect for r in self.lane.pin_lamps()]
        alt_ziffern = {r.name: r.rect for r in self.lane.rois
                       if r.name.startswith(("digit_", "throw_number",
                                             "pin_count", "total_", "left_"))}

        self.lane = neue_bahn
        if not self.prepare(frame_shape):
            return []

        neu_gruen = self.lane.get_roi("green_lamp")
        geaendert: list[str] = []
        if alt_gruen is None or neu_gruen is None or alt_gruen.rect != neu_gruen.rect:
            self.green_detector.vergiss()
            geaendert.append("Gruenlampe")
        if alt_lampen != [r.rect for r in self.lane.pin_lamps()]:
            self.lamp_detector.vergiss()
            geaendert.append("Kegellampen")
        if alt_ziffern != {r.name: r.rect for r in self.lane.rois
                           if r.name.startswith(("digit_", "throw_number",
                                                 "pin_count", "total_",
                                                 "left_"))}:
            geaendert.append("Ziffernfelder")

        if geaendert:
            log.info("Bahn %d: Kalibrierung im Lauf uebernommen (%s) -- die "
                     "mitlaufenden Schwellen beginnen von vorn",
                     self.display_number, ", ".join(geaendert))
        return geaendert

    def _lies_anzeige_live(self, frame: Frame) -> None:
        """Liest ALLE Ziffernfelder fuer die Anzeige -- ohne die Zaehlung.

        WOFUER -- Wunsch des Nutzers am 2026-09-11:

            "ich haette gerne, dass dort auch steht, was er gerade an Ziffern
             erkannt hat. Also welche Werte angeblich wo stehen. Das wuerde mir
             helfen bei der Evaluierung, ob wir die Ziffern bald wieder
             reinnehmen, oder nicht."

        STRIKT GETRENNT von allem, was zaehlt. Diese Werte gehen in keine
        Summe, in keine Gegenprobe und in keinen Versand -- sie werden nur
        angezeigt. Die Trennung ist kein Formalismus: Die Ziffern sind derzeit
        aus der Wertung genommen, und eine Anzeige, die sie stillschweigend
        wieder einspeist, wuerde genau die Frage verwischen, die der Nutzer
        beantworten will.

        Auch bewusst OHNE zeitliche Glaettung, anders als bei den Lampen: Wer
        beurteilen will, wie gut der Leser ist, will sehen, was er JETZT liest
        -- nicht, was eine Mehrheit der letzten zwei Sekunden ergab.

        Gelesen wird auf DEMSELBEN Weg wie in der Auswertung (`read_digits`):
        Eine Anzeige, die anders liest als die Analyse, taugte zur Beurteilung
        nichts.
        """
        try:
            self._live_digits = self.read_digits(frame)
        except Exception as exc:  # noqa: BLE001
            # P8: Eine unlesbare Anzeige beendet nichts -- sie wird eben nicht
            # angezeigt.
            log.debug("Bahn %d: Anzeige nicht lesbar: %s",
                      self.display_number, exc)

    def _read_late_fields(self, frame: Frame) -> None:
        """Liest die spaet aktualisierten Felder und behaelt die juengsten Werte.

        GEMESSEN auf Bahn 4 ueber drei vollstaendige Wurffenster (216-338 Frames
        zwischen GREEN_OFF und dem naechsten GREEN_ON):

            Wurf 1   frueh (+2 .. +30):  001 6 0000     Summe noch der alte Stand
                     spaet (-60 .. -8):  001 6 0006     Summe eingetragen (0+6)
            Wurf 3   frueh:              003 5 0014
                     spaet:              003 5 0019     14+5 stimmt

        Das Sampling-Fenster umfasst rund 34 Frames -- die Summe wurde damit
        ausnahmslos im ALTEN Stand gelesen. Genau daher passte der Summenzuwachs
        zum jeweils VORHERIGEN Wurf (gemessen 18 Treffer gegen 8).
        """
        for name in self.cfg.detection.digits.late_fields:
            boxes = self._digit_cell_boxes.get(name)
            if not boxes:
                continue
            try:
                reading = self.digit_reader.read_field(
                    [self._crop(frame.image, box) for box in boxes])
            except Exception as exc:  # noqa: BLE001
                log.debug("Bahn %d: Feld '%s' in Frame %d nicht lesbar: %s",
                          self.display_number, name, frame.index, exc)
                continue
            self._late_samples.setdefault(
                name, deque(maxlen=self._late_keep)).append(reading)

    def _pruefe_nullzustand(self, frame: Frame) -> None:
        """Zaehlt Frames, in denen die untere Reihe auf `000  0000` steht.

        WARUM UNABHAENGIG VOM WURFFENSTER: Frueher hing diese Pruefung an
        `_read_late_fields`, also an der Zeit zwischen GREEN_OFF und dem
        naechsten GREEN_ON. Ob ein Spielwechsel erkannt wurde, entschied damit
        der Zufall -- naemlich ob die Anlage die Anzeige gerade waehrend einer
        Gruenpause zuruecksetzte. GEMESSEN am 2026-08-30:

            Bahn 2   000/0000 stand F127115-F128475 (54 s)
                     Fenster offen bis F127177 -- 62 Frames.  NICHT erkannt
            Bahn 3   000/0000 stand F126680-F128715 (81 s)
                     Fenster offen bis F126964 -- 284 Frames. erkannt

        Ueber die ganze Aufzeichnung fand Bahn 2 dadurch 2 Spielenden, Bahn 3
        dreizehn -- bei nahezu gleicher Wurfzahl (~370 je Bahn).

        Die Wurfnummer wird NUR gelesen, wenn die Summe null zeigt. Damit
        kostet die Pruefung im laufenden Spiel fast nichts -- dort ist die
        Summe fast immer von null verschieden. Mit
        `scoring.game_reset_number_only` entfaellt diese Abkuerzung: Dann wird
        die Wurfnummer in jedem geprueften Frame gelesen, was Rechenzeit
        kostet. Das Tempo eines Laufs zeigt, wieviel.

        Warum urspruenglich beide Felder und nicht nur die Wurfnummer: Eine
        unlesbare Anzeige koennte einzeln als Null durchgehen. Zwei getrennt
        gelesene Felder, die gleichzeitig null zeigen, sind das nicht.

        WARUM DAS INZWISCHEN SCHADET (`scoring.game_reset_number_only`): Die
        Summe ist der TORWAECHTER -- ist sie unlesbar, wird die Wurfnummer nie
        geprueft. Gemessen am Spieltag 2026-08-22 ist die Summe aber genau das
        schwaechere der beiden Felder, die Wurfnummer das staerkere. Der zweite
        Zeuge kostet damit mehr, als er einbringt. Die Absicherung gegen eine
        einzelne Fehllesung leistet ohnehin `game_reset_min_frames`: Mehrere
        Messungen in Folge muessen null zeigen, und `is_readable` faengt die
        unlesbare Anzeige ab, bevor sie als Null durchgeht.
        """
        summe_boxes = self._digit_cell_boxes.get(
            self.cfg.scoring.game_reset_total_field)
        nummer_boxes = self._digit_cell_boxes.get(
            self.cfg.scoring.game_reset_number_field)
        nur_nummer = self.cfg.scoring.game_reset_number_only
        if not nummer_boxes or (not summe_boxes and not nur_nummer):
            return
        if not nur_nummer:
            try:
                summe = self.digit_reader.read_field(
                    [self._crop(frame.image, box) for box in summe_boxes])
            except Exception as exc:  # noqa: BLE001
                log.debug("Bahn %d: Summe in Frame %d nicht lesbar: %s",
                          self.display_number, frame.index, exc)
                return
            if not summe.is_readable:
                return
            if summe.value != 0:
                self._nullzustand_verlassen()
                return
        try:
            nummer = self.digit_reader.read_field(
                [self._crop(frame.image, box) for box in nummer_boxes])
        except Exception as exc:  # noqa: BLE001
            log.debug("Bahn %d: Wurfnummer in Frame %d nicht lesbar: %s",
                      self.display_number, frame.index, exc)
            return
        if not nummer.is_readable:
            return
        if nummer.value != 0:
            self._nullzustand_verlassen()
            return

        self._verlassen_observations = 0
        if self._reset_observations == 0:
            # WANN der Nullzustand ANFING, nicht wann wir ihn bemerkten.
            # Daran haengt, zu welchem Spiel der laufende Wurf gehoert
            # (siehe unten).
            self._reset_beginn = frame.index
        self._reset_observations += 1
        # SPERRE gegen Doppelmeldungen. Der Nullzustand steht gemessen 40 bis
        # 91 Sekunden; die Pruefung trifft ihn in dieser Zeit vielfach. Ohne
        # Sperre wurde derselbe Spielwechsel zweimal gemeldet -- GEMESSEN 60
        # bis 255 Frames auseinander, beide Male innerhalb desselben
        # Abschnitts. Jede zweite Meldung erzeugte einen Geisterlauf mit
        # "voriges Spiel endete mit 0 Kegeln".
        #
        # Die Sperre faellt erst, wenn die Anzeige den Nullzustand
        # nachweislich VERLASSEN hat -- nicht nach einer Zeitspanne. Wie lange
        # die Anlage stehen bleibt, entscheidet die Halle, nicht wir.
        if (not self._reset_latch
                and self._reset_observations >= self.cfg.scoring.game_reset_min_frames):
            # WOHIN DAS ZEICHEN GEHT, HAENGT DARAN, WANN ES GESEHEN WURDE.
            #
            # Diese Pruefung laeuft in EIGENEM Takt, unabhaengig vom
            # Wurffenster -- sie trifft den Nullzustand also mal waehrend
            # eines Wurfs und mal zwischen zweien. Das ist ein Unterschied:
            #
            #   im Fenster    Der Wurf, der gerade laeuft, gehoert noch zum
            #                 ALTEN Spiel. Das Zeichen gilt dem naechsten --
            #                 es geht nach `_reset_seen` und wird von
            #                 `_reset_weiterreichen` eine Stufe geschoben.
            #
            #   dazwischen    Der letzte Wurf des alten Spiels ist laengst
            #                 gebucht. Der naechste Wurf, der kommt, ist
            #                 bereits der ERSTE des neuen Spiels -- das
            #                 Zeichen gehoert ihm direkt, also nach
            #                 `_reset_carry`.
            #
            # BIS 2026-09-17 GING BEIDES NACH `_reset_seen` (BUG-028). Ein
            # zwischen zwei Wuerfen gesehener Nullzustand kostete dadurch
            # einen Wurf extra: Er wurde behandelt, als haette er im Fenster
            # des gerade fertigen Wurfs gelegen.
            #
            # GEMESSEN am Spieltag 2026-09-17 (477 Wuerfe, 25 Spiele): Jedes
            # Spiel, dessen erster gebuchter Wurf die Nummer 2 trug, hatte
            # genau einen Wurf verloren -- sieben von 25 Spielen, jeweils mit
            # konstantem Fehlbetrag ueber das ganze Spiel (-5 bis -9, genau
            # die Kegelzahl des verlorenen Wurfs). Die uebrigen begannen bei
            # Wurfnummer 1 und stimmten auf den Punkt.
            # Zwei Fragen, nicht eine: Laeuft gerade ein Wurf -- und hat der
            # Nullzustand VOR oder NACH dessen Beginn eingesetzt?
            #
            # Der Unterschied entscheidet, zu welchem Spiel der laufende Wurf
            # gehoert:
            #
            #   Nullzustand begann NACH dem Fensterbeginn
            #       Die Anlage hat waehrend des Wurfs zurueckgesetzt -- also
            #       nachdem er geworfen war. Er gehoert noch zum ALTEN Spiel,
            #       das Zeichen gilt dem naechsten.
            #
            #   Nullzustand begann VOR dem Fensterbeginn (oder gar kein Wurf)
            #       Die Tafel stand schon auf null, als dieser Wurf begann.
            #       Er ist bereits der ERSTE des neuen Spiels und bekommt das
            #       Zeichen direkt.
            #
            # GEMESSEN auf Bahn 5 (Stream vom 2026-09-17): Wurf 31 wurde mit
            # `SummeTafel 0` gebucht -- die Tafel hatte vor diesem Wurf
            # zurueckgesetzt. Er landete trotzdem im alten Spiel, und das neue
            # begann erst bei Wurf 2. Mit dem Fenster allein war das nicht zu
            # unterscheiden, denn in beiden Faellen ist es offen.
            im_alten_spiel = (self._window_open
                              and self._green_off_frame is not None
                              and self._reset_beginn >= self._green_off_frame)
            if im_alten_spiel:
                self._reset_seen = True
            else:
                self._reset_carry = True
            self._reset_latch = True
            log.info("Bahn %d: Anzeige steht bei Frame %d auf 000/0000 "
                     "-- die Anlage hat das Spiel beendet (%s)",
                     self.display_number, frame.index,
                     "waehrend des laufenden Wurfs" if im_alten_spiel
                     else "vor diesem Wurf -- er zaehlt schon zum neuen Spiel")

    def _nullzustand_verlassen(self) -> None:
        """Die Anzeige zeigt etwas anderes als null -- aber sagt EINE Messung das?

        Nein. GEMESSEN am 2026-08-30 auf Bahn 2, Frames 127115-128475: Die
        Anzeige stand 54 Sekunden auf 000/0000, aber nur 184 von 273 Messungen
        lasen sie auch so (67 %). Der Rest war unlesbar oder falsch.

        Eine einzelne Fehllesung hob dadurch die Sperre auf, und derselbe
        Spielwechsel wurde FUENFMAL gemeldet -- bei F127250, F127375, F127825,
        F128075 und F128225, alle innerhalb desselben Abschnitts.

        Deshalb dieselbe Regel wie beim Betreten: Erst mehrere Messungen in
        Folge belegen, dass die Anzeige den Nullzustand wirklich verlassen hat.

        WIE VIELE, ist gemessen (Abschnitt F164535-F166780, Takt 25 Frames):
        die laengste Straehne von Nicht-Null-Messungen INNERHALB des
        Nullzustands lag bei 6 (Bahn 4), auf Bahn 2 bei 3. Mit einer Schwelle
        von 3 meldete Bahn 4 denselben Wechsel dreimal.
        """
        self._reset_observations = 0
        self._verlassen_observations += 1
        if self._verlassen_observations >= self.cfg.scoring.game_reset_leave_frames:
            self._reset_latch = False

    def _pruefe_fehlwurfzaehler(self, frame: Frame) -> None:
        """Verfolgt den Fehlwurfzaehler und meldet stabile ANSTIEGE.

        Ein Anstieg heisst: Auf dieser Bahn ist ein Wurf gefallen, bei dem kein
        Kegel umging. Ein RUECKFALL ist der Spielwechsel -- die Anlage setzt
        den Zaehler mit allem anderen zurueck; das ist kein Wurf.

        GEMESSEN ueber 52 Minuten auf Bahn 2 (tools/verify_foul_counter.py):

            11 638 von 15 557 Messungen lesbar (74,8 %)
            Rohwerte: {0: 10711, 1: 776, 3: 147, 7: 3, 70: 1}

            nach dem Stabilitaetsfilter blieben drei Werte:
                F    35   Zaehler = 0
                F 51230   Zaehler = 1   <- der Nullwurf aus dem Wurfprotokoll
                F 58585   Zaehler = 0   <- Ruecksetzung beim Spielwechsel

        Genau EIN Anstieg, und genau an der Stelle, an der im handgefuehrten
        Protokoll der einzige Nullwurf dieser Bahn steht. Das Rauschen (147-mal
        "3") ueberstand den Filter nirgends.
        """
        boxes = self._digit_cell_boxes.get(self.cfg.detection.digits.foul_field)
        if not boxes:
            return          # Feld nicht stellenweise kalibriert -- nichts zu tun
        try:
            lesung = self.digit_reader.read_field(
                [self._crop(frame.image, box) for box in boxes])
        except Exception as exc:  # noqa: BLE001
            log.debug("Bahn %d: Fehlwurfzaehler in Frame %d nicht lesbar: %s",
                      self.display_number, frame.index, exc)
            return
        if not lesung.is_readable:
            return

        wert = lesung.value
        if wert == self._foul_candidate:
            self._foul_repeats += 1
        else:
            self._foul_candidate = wert
            self._foul_repeats = 1
        if self._foul_repeats < self.cfg.detection.digits.foul_stable_readings:
            return
        if wert == self._foul_value:
            return

        vorher = self._foul_value
        # PLAUSIBILITAET VOR UEBERNAHME: Ein zu grosser Sprung ist keine Serie
        # von Nullwuerfen, sondern eine Fehllesung -- und dann darf er auch
        # nicht zum neuen Bezugspunkt werden. Sonst gilt der Ruecksprung auf
        # den richtigen Wert anschliessend als Spielwechsel.
        #
        # Gelesen wird alle `foul_read_interval` Frames (10), ein Wurfzyklus
        # dauert gemessen 216 bis 338 Frames. Zwischen zwei Lesungen kann also
        # hoechstens EIN Wurf liegen.
        #
        # GEMESSEN ueber den vollen Spieltag 2026-08-29: Bahn 4 hatte 14
        # Spruenge um drei, die 42 Wuerfe erfanden. Bildbeleg Frame 270290 --
        # die Tafel zeigt `00`, gelesen wurde `03`.
        if (vorher is not None and wert > vorher
                and wert - vorher > self.cfg.detection.digits.foul_max_rise):
            log.warning(
                "Bahn %d: Fehlwurfzaehler springt %d -> %d bei Frame %d -- "
                "das waeren %d Wuerfe zwischen zwei Lesungen (10 Frames), "
                "ein Wurfzyklus dauert aber 216-338. Verworfen als Fehllesung.",
                self.display_number, vorher, wert, frame.index, wert - vorher)
            # Der Stoerwert muss sich neu bewaehren, bevor er wieder zaehlt.
            self._foul_candidate = None
            self._foul_repeats = 0
            return

        self._foul_value = wert
        if vorher is None:
            return          # erster stabiler Stand -- kein Ereignis
        if wert > vorher:
            log.info("Bahn %d: Fehlwurfzaehler %d -> %d bei Frame %d "
                     "-- Wurf ohne Kegel", self.display_number, vorher, wert,
                     frame.index)
            for _ in range(wert - vorher):
                # DER FRAME, BEI DEM DER ZAEHLER GESPRUNGEN IST -- vom
                # Nutzer so festgelegt (2026-09-07). Ein Wurf ohne Kegel hat
                # keinen Gruenzyklus und damit keine gesampelten Frames; dieser
                # hier ist der einzige Beleg, den es gibt.
                self._foul_events.append(
                    (frame.index, frame.timestamp,
                     self._wurfnummer_lesen(frame),
                     encode_board(frame.image, self.lane_box(),
                                  self.cfg.output.board_image_quality,
                                  self.fremdmaske(frame.image, frame.index))))
        else:
            log.info("Bahn %d: Fehlwurfzaehler faellt %d -> %d bei Frame %d "
                     "-- Spielwechsel, kein Wurf", self.display_number,
                     vorher, wert, frame.index)

    def _wurfnummer_lesen(self, frame: Frame) -> int | None:
        """Liest die Wurfnummer der Tafel -- nur bei einem Fehlwurf gebraucht.

        Bewusst NICHT im Takt mitgefuehrt: Fehlwuerfe sind selten (ueber einen
        ganzen Spieltag ein knappes Dutzend), und drei zusaetzliche
        Ziffernstellen alle zehn Frames waeren dafuer zu teuer.
        """
        boxes = self._digit_cell_boxes.get("throw_number")
        if not boxes:
            return None
        try:
            lesung = self.digit_reader.read_field(
                [self._crop(frame.image, box) for box in boxes])
        except Exception as exc:  # noqa: BLE001
            log.debug("Bahn %d: Wurfnummer bei Fehlwurf nicht lesbar: %s",
                      self.display_number, exc)
            return None
        return lesung.value if lesung.is_readable else None

    def take_zero_throws(self) -> list[tuple[int, float, int | None, str | None]]:
        """Holt die seit dem letzten Aufruf erkannten Nullwuerfe ab.

        Je Eintrag: Frame, Zeitpunkt, gelesene Wurfnummer und das
        Tafelbild jenes Frames (Base64-JPEG oder None).
        """
        ereignisse = self._foul_events
        self._foul_events = []
        return ereignisse

    def _reset_weiterreichen(self) -> None:
        """Schiebt das Spielwechsel-Zeichen um einen Wurf weiter.

        Wird genau dann aufgerufen, wenn ein Wurf tatsaechlich abgeschlossen
        wurde -- nicht bei einem als Flackern verworfenen Fenster. Sonst
        rutschte das Zeichen an einem Wurf vorbei und landete beim falschen.
        """
        self._reset_pending = self._reset_carry
        self._reset_carry = self._reset_seen
        self._reset_seen = False

    @property
    def reset_pending(self) -> bool:
        """Gilt fuer den Wurf, der gerade ausgewertet wird: neues Spiel?"""
        return self._reset_pending

    @property
    def reset_unterwegs(self) -> bool:
        """Ist ein Spielwechsel-Zeichen erkannt und noch nicht zugestellt?

        Es gibt zwei Briefkaesten, weil es zwei Zeitpunkte gibt: im
        Wurffenster gesehen (`_reset_seen`, gilt dem naechsten Wurf) oder
        zwischen zwei Wuerfen (`_reset_carry`, gilt direkt dem naechsten).
        Wer nur wissen will, OB erkannt wurde, soll nicht wissen muessen,
        welcher der beiden es war.
        """
        return self._reset_seen or self._reset_carry

    @property
    def window_was_occluded(self) -> bool:
        """War die Tafel waehrend DIESES Sammelfensters verdeckt? (BUG-017)

        Anders als `reset_pending` braucht das keinen Ein-Wurf-Verzug: Die
        Verdeckung betrifft immer das Fenster, in dem sie auftrat, nicht das
        naechste. Das Flag wird bei jedem GREEN_OFF (neues Fenster) auf False
        gesetzt und bleibt bis zum zugehoerigen GREEN_ON gueltig -- also genau
        bis der Analyzer diesen Wurf auswertet.
        """
        return self._occlusion_during_window

    @property
    def late_samples(self) -> dict[str, list[DigitReading]]:
        """Die juengsten Mitlesungen der spaet aktualisierten Felder."""
        return {name: list(werte) for name, werte in self._late_samples.items()}

    @property
    def result_samples(self) -> list[PinLampReading]:
        """Die Lampenmessungen BIS Gruen-AUS des letzten Ereignisses."""
        return list(self._result_samples)

    @property
    def nach_samples(self) -> list[PinLampReading]:
        """Die Messungen NACH Gruen-AUS -- ueber sie wird eigens entschieden.

        Dort blinkt entweder der Jubel-Effekt (dann sind diese Frames noetig,
        weil eine Lampe sonst in ihrer Dunkelphase fehlt) oder die Tafel
        meldet eine Stoerung (dann leuchten Lampen, die keinen gefallenen
        Kegel meinen, BUG-036).

        DIE ENTSCHEIDUNG FAELLT IN DER PIPELINE, gemeinsam mit den
        Abtastframes. Erst wurde sie an zwei Stellen getroffen -- hier ueber
        die Live-Messungen, dort ueber die Abtastframes. Die beiden Folgen
        sind verschieden dicht, und am 2026-09-28 erkannte die eine den
        Fehlercode und die andere nicht: Der Filter meldete sich, und der
        Wurf blieb trotzdem falsch.
        """
        return list(self._nach_samples)

    @property
    def baseline_pins(self) -> PinLampReading | None:
        """Lampenstand zu Beginn des zuletzt beendeten Wurfs (Raeumen)."""
        return self._baseline_pins

    def _anker_vorstand(
            self,
            spur_roh: "list[tuple[int, PinLampReading]]",
    ) -> "tuple[int, PinLampReading] | None":
        """Das erste Bild der Gruenphase, das eine erlaubte Grundlinie zeigt.

        Erlaubt sind genau zwei Staende: leer und der Stand des vorigen Wurfs.
        Gesucht wird ueber ALLE Messungen der Gruenphase in ihrer zeitlichen
        Reihenfolge -- die Anzeigemessungen (Takt `_live_interval`) und die
        dichteren Messungen der Gruenphase selbst.

        Schweigt die Suche, weiss sie nichts: eine verdeckte Bahn, eine Lampe,
        die nie hell genug wird (BUG-034), ein verschluckter Wurf. Dann gilt
        weiter das bisherige Verfahren -- Raten waere schlimmer.
        """
        if self._green_on_frame is None:
            return None
        erlaubt = {frozenset()}
        if self._vorstand is not None:
            erlaubt.add(frozenset(self._vorstand.pins))
        messungen = sorted(
            [(fr, m) for fr, m in spur_roh if fr >= self._green_on_frame]
            + list(self._green_phase_samples),
            key=lambda paar: paar[0])
        for fr, messung in messungen:
            if frozenset(messung.pins) in erlaubt:
                return fr, messung
        return None

    def uebernimm_vorstand(self, ergebnis: "PinLampReading | None") -> None:
        """Meldet den Endstand eines Wurfs -- die Grundlinie des naechsten.

        Von der Pipeline zu rufen, sobald sie die Lampen eines Wurfs zu EINER
        Menge zusammengefasst hat. Vorher ist der Stand nicht vollstaendig:
        Bei blinkender Anzeige fehlt in jeder einzelnen Messung etwas.

        LIEGEN ALLE NEUNE, STELLT DIE ANLAGE NEU AUF -- dann ist die
        Grundlinie des naechsten Wurfs leer, nicht etwa alle neun. Ohne diese
        Zeile fiele der Anker beim Jubelblinken auf den vollen Kranz, und der
        naechste Wurf haette null Kegel.
        """
        if ergebnis is None:
            return
        self._vorstand = None if len(ergebnis.pins) >= 9 else ergebnis

    def setze_verdeckung(self, verdeckt: bool) -> None:
        """Meldet, ob die Personenmaske diese Tafel gerade verdeckt sieht.

        Von der Pipeline VOR `process` zu setzen. Getrennt vom Gruen-Score,
        weil es eine andere Quelle ist -- und weil zwei Quellen, die sich
        widersprechen duerfen, mehr wert sind als eine, die immer recht hat.
        """
        self._extern_verdeckt = bool(verdeckt)

    def read_pin_lamps_at(self, frame: Frame) -> PinLampReading | None:
        """Liest die Kegellampen eines beliebigen Frames.

        Wird fuer die Aggregation ueber die Sample-Frames gebraucht -- siehe
        `AnalysisPipeline._aggregate_pins`. Geht also ins Wurfergebnis ein und
        gehoert deshalb ungekuerzt in die Spur.
        """
        return self._read_pin_lamps(frame, is_result=False, anlass="abtastung")

    def setze_personenmodell(self, modell) -> None:
        """Das von der Pipeline geteilte Personenmodell uebernehmen."""
        self.personen_modell = modell

    def setze_rohbild(self, bild) -> None:
        """Das UNGESCHWAERZTE Bild dieses Frames fuer das Modell.

        Nicht das maskierte: Die Bewegungsmaske schwaerzt alles ausserhalb der
        Tafeln -- also genau den Rumpf, an dem das Netz einen Menschen erkennt.
        Auf dem maskierten Bild suchte es nach einem Kopf ueber einem
        schwarzen Loch.
        """
        self._rohbild = bild

    def _frage_das_modell(self, frame: Frame, green) -> None:
        """Das Netz befragen -- aber nur, wenn es sich lohnt.

        Projektregel 4: billige Trigger steuern teure Analyse. Der Aufruf
        kostet gemessen 68 ms, das Budget je Frame sind 40 ms. Gefragt wird
        deshalb, wenn schon ein billiger Zeuge etwas meldet, und ausserdem in
        einem groben Takt als Streife -- fuer den Menschen, der auf der Tafel
        steht, ohne die gruene Lampe zu beruehren.

        UND IN BEIDEN FAELLEN MIT MINDESTABSTAND. Ein Zeuge kann festhaengen:
        GEMESSEN ueber 3000 Frames des Hallenmitschnitts meldete die Tafelwache
        auf Bahn 5 in 2704 Frames Fremdes, und das Netz lief dadurch in 94 %
        aller Frames -- der Durchsatz fiel von 32 auf 11 Frames/s. Ein Mensch
        steht rund 50 Frames im Bild; seine Anwesenheit aendert sich nicht im
        40-Millisekunden-Takt.

        DER ABSTAND ZAEHLT UEBER ALLE BAHNEN, nicht je Bahn. Das Netz sucht in
        EINEM Band ueber alle vier Tafeln -- wer sieht, dass die Antwort frisch
        genug ist, liest sie mit, statt eine zweite zu bestellen. Je Bahn
        gerechnet fragten die vier versetzt und trieben die Quote von 20 auf
        33 % (gemessen an denselben 3000 Frames).
        """
        modell = self.personen_modell
        if modell is None or not modell.bereit or self._rohbild is None:
            self._modell_meldet_person = False
            self._modell_anteil = 0.0
            return
        verdaechtig = (green.score < self._verdeckungsschwelle()
                       or self._extern_verdeckt or self._wache_meldet_fremdes)
        abstand = self._modell_alarmtakt if verdaechtig else self._modell_takt
        if abstand <= 0:
            return                      # Streife aus und nichts Verdaechtiges
        frisch = modell.letzter_lauf
        if frisch is not None and 0 <= frame.index - frisch < abstand:
            bezug = frisch              # kostenlos mitlesen
        else:
            modell.suche(self._rohbild, frame.index)
            bezug = frame.index
        self._modell_zuletzt = bezug
        self._modell_anteil = modell.auf_tafel(self.lane_box(), bezug)
        self._modell_meldet_person = self._modell_anteil > self._modell_deckung

    def _pruefe_festhaengende_wache(self, frame: Frame) -> None:
        """Loest eine Wache, die sich an einer echten Aenderung verhakt hat.

        DER FALL (BUG-026, gemessen 2026-09-14 am Hallenmitschnitt): Bei Frame
        215 verschiebt sich das Bild um wenige Pixel. Die Abweichung auf Bahn 5
        springt von 3,4 auf 13 %, also ueber `wache_nachlernen_unter` -- und
        bleibt danach 13 000 Frames bei 25,2 % stehen. Median gleich Maximum:
        voellig unbewegt, wie es ein Mensch nie waere. Die Bahn war den ganzen
        Mitschnitt lang eingefroren, ohne dass irgendetwas davorstand.

        Die Bewachung der Referenz ist richtig -- sie verhindert, dass ein
        Mensch hineinwandert. Sie kann nur nicht selbst unterscheiden, ob die
        Abweichung von einem Menschen kommt oder von einer verrutschten Kamera.
        Das Personenmodell kann es: Es sah dort auf 0,6 % der Messpunkte einen
        Menschen, die Wache meldete auf 98,3 %.

        DREI BEDINGUNGEN, alle noetig:
          * das Modell ist geladen -- sonst fehlt der Zeuge, und es passiert
            nichts (lieber eingefroren als ein Gesicht in der Datenbank),
          * es hat ueber die ganze Strecke keinen Menschen auf DIESER Tafel
            gesehen,
          * die Strecke ist laenger als jede gemessene echte Verdeckung
            (118 Verdeckungen: Median 30 Frames, laengste 250; die Schwelle
            steht seit 2026-09-17 auf 250 -- siehe
            `detection.person_mask.wache_neustart_frames`. Sie kostet seit
            BUG-030 keine Wuerfe mehr, weil die Verdeckungsbremse nicht mehr
            an dieser Wache haengt; sie steuert nur noch, wie lange eine
            festhaengende Referenz zu viel schwaerzt).
        """
        modell = self.personen_modell
        if (self._neustart_frames <= 0 or modell is None or not modell.bereit
                or not self._wache_meldet_fremdes or self._modell_meldet_person):
            self._wache_daueralarm = 0
            return
        self._wache_daueralarm += 1
        if self._wache_daueralarm < self._neustart_frames:
            return
        log.warning("Bahn %d: Wache meldet seit %d Frames Fremdes, das "
                    "Personenmodell sieht dort niemanden -- Referenz war "
                    "vermutlich vor einer Bildverschiebung gelernt. Sie wird "
                    "ab Frame %d neu aufgebaut.", self.display_number,
                    self._wache_daueralarm, frame.index)
        self.wache.vergiss_referenz()
        self._wache_meldet_fremdes = False
        self._wache_bremst = False
        self._wache_daueralarm = 0

    def fremdmaske(self, bild, frame_index: int | None = None) -> object:
        """Was auf dem Tafelausschnitt dieses Bildes nicht hingehoert.

        Zwei Quellen, vereinigt: die Tafelwache (jede Abweichung von der
        eigenen Referenz) und das Personenmodell (ein Mensch als Mensch).
        Die Wache findet auch, was kein Mensch ist; das Modell findet auch den,
        der so still steht, dass die Referenz ihn schon fast kennt.

        `frame_index` ist Pflicht, sobald das Bild NICHT der laufende Frame ist
        -- das veroeffentlichte Tafelbild stammt aus einem Sample-Frame, und
        die Kaesten eines anderen Frames traefen daneben. Fehlt der Index oder
        ist der Frame aus dem Gedaechtnis gefallen, bleibt allein die Wache.
        """
        box = self.lane_box()
        if box is None or bild is None:
            return None
        aus = self._crop(bild, box)
        if aus is None or not aus.size:
            return None
        von_wache = self.wache.fremdmaske(aus)
        vom_modell = None
        if self.personen_modell is not None and frame_index is not None:
            vom_modell = self.personen_modell.maske_im_ausschnitt(box, frame_index)
        if von_wache is None:
            return vom_modell
        if vom_modell is None:
            return von_wache
        return np.maximum(von_wache, vom_modell)

    def read_digits(self, frame: Frame,
                    felder: tuple[str, ...] | None = None
                    ) -> dict[str, DigitReading]:
        """Liest die Ziffernfelder eines Frames.

        Teuer im Vergleich zur Gruenlampe -- deshalb NUR fuer die Frames eines
        Ereignisses aufrufen, nie fuer jeden Frame (Auftrag Paragraph 20).

        `felder` schraenkt auf einzelne Felder ein. GEMESSEN am 2026-09-28 ueber
        31 Frames, alle vier Bahnen zusammen:

            nur `throw_number`       1,99 ms je Frame
            alle fuenf Felder       14,70 ms je Frame
            neun Kegellampen         4,73 ms je Frame   (laufen schon mit)

        Damit ist das EINE Feld billiger als die Lampen, die im selben Takt
        ohnehin gelesen werden -- bei einem Budget von 40 ms. Der Vorbehalt
        oben gilt weiter fuer den vollen Satz.
        """
        readings: dict[str, DigitReading] = {}
        # Einzeln eingerahmte Stellen -- der genauere Weg
        for name, boxes in self._digit_cell_boxes.items():
            if felder is not None and name not in felder:
                continue
            shifts = self._digit_shifts.get(name)
            readings[name] = self.digit_reader.read_field(
                [self._crop(frame.image, self._shifted(box, shifts, i))
                 for i, box in enumerate(boxes)]
            )
        # Rest ueber das Gesamtfeld
        for name, (box, digits) in self._digit_boxes.items():
            if felder is not None and name not in felder:
                continue
            readings[name] = self.digit_detector.detect(
                self._crop(frame.image, box), digits
            )
        return readings

    @staticmethod
    def _shifted(box: tuple[int, int, int, int],
                 shifts: list[tuple[int, int]] | None,
                 index: int) -> tuple[int, int, int, int]:
        """Verschiebt eine Ziffernbox um ihren Feinausrichtungs-Versatz."""
        if not shifts or index >= len(shifts):
            return box
        dx, dy = shifts[index]
        x, y, w, h = box
        return x + dx, y + dy, w, h

    def refine_digit_boxes(self, frames: list[Frame]) -> None:
        """Richtet die Ziffernrahmen einmal je Video pixelgenau aus.

        WARUM: Die Rahmen werden beim Kalibrieren von Hand gesetzt. Bei Ziffern
        von rund 13x18 px entscheidet ein Versatz von zwei Pixeln darueber, ob
        ein Segment noch in seiner Messflaeche liegt.

        GEMESSEN ueber 30 Frames einer unveraenderten Anzeige, Feld `total_b`:

            Bahn 3:  0 30x | 0 30x | 5 30x | 7 30x     alle vier Stellen sicher
            Bahn 4:  0 30x | 0 30x | 5 30x | 1 30x     alle vier Stellen sicher
            Bahn 2:  ...           | 1 13x / 4 10x     Stelle 3 kippt
            Bahn 5:  ...                    | ? 27x    Stelle 4 unlesbar

        Zwei Bahnen lasen fehlerfrei, zwei nicht -- bei identischem Verfahren.
        Der Unterschied lag also nicht im Leser, sondern in den Rahmen.

        Gesucht wird der Versatz mit der hoechsten mittleren Confidence ueber die
        uebergebenen Frames. Ein Versatz wird nur uebernommen, wenn er den
        bisherigen deutlich schlaegt (`min_refine_gain`) -- sonst gewinnt
        Rauschen, und die Ausrichtung wuerde von Video zu Video springen.
        """
        if self._refined or not frames:
            return
        self._refined = True

        spanne = self.cfg.detection.digits.refine_radius
        if spanne <= 0:
            return
        kandidaten = [(dx, dy)
                      for dy in range(-spanne, spanne + 1)
                      for dx in range(-spanne, spanne + 1)]

        for name, boxes in self._digit_cell_boxes.items():
            versaetze: list[tuple[int, int]] = []
            for box in boxes:
                bestes, beste_gute = (0, 0), -1.0
                for dx, dy in kandidaten:
                    verschoben = self._shifted(box, [(dx, dy)], 0)
                    werte = []
                    for frame in frames:
                        _, confidence = self.digit_reader.read_digit(
                            self._crop(frame.image, verschoben))
                        werte.append(confidence)
                    guete = float(np.mean(werte)) if werte else 0.0
                    # Bei Gleichstand gewinnt der kleinere Versatz: Die
                    # Handkalibrierung ist der Ausgangspunkt, nicht der Feind.
                    if guete > beste_gute + (0.0 if (dx, dy) == (0, 0) else 1e-9):
                        bestes, beste_gute = (dx, dy), guete
                # Nullversatz als Vergleichsmass
                null = float(np.mean([
                    self.digit_reader.read_digit(self._crop(f.image, box))[1]
                    for f in frames
                ])) if frames else 0.0
                if beste_gute < null + self.cfg.detection.digits.min_refine_gain:
                    bestes = (0, 0)
                versaetze.append(bestes)

            if any(v != (0, 0) for v in versaetze):
                log.info("Bahn %d: Ziffernrahmen '%s' feinausgerichtet: %s",
                         self.display_number, name, versaetze)
            self._digit_shifts[name] = versaetze

    @property
    def lamp_boxes(self) -> list[tuple[int, int, int, int]]:
        """Die neun Lampenrechtecke -- fuer die Auswahl des besten Frames."""
        return list(self._lamp_boxes)

    @property
    def board_before(self) -> str | None:
        """Die Tafel, bevor geworfen wurde (Base64-JPEG oder None)."""
        return self._board_before

    def lane_box(self) -> tuple[int, int, int, int] | None:
        """Umschliessendes Rechteck der Anzeigetafel im Frame.

        Fuer die Debug-Ausgabe: Statt eines 1920x1080-Vollframes genuegt dieser
        Ausschnitt -- er enthaelt alles Auswertbare bei einem Bruchteil der Groesse.
        """
        xs = [p[0] for p in self.lane.quad]
        ys = [p[1] for p in self.lane.quad]
        # Etwas Rand, damit die Tafelkanten sichtbar bleiben
        margin = 8
        x0 = max(0, int(min(xs)) - margin)
        y0 = max(0, int(min(ys)) - margin)
        x1 = int(max(xs)) + margin
        y1 = int(max(ys)) + margin
        if x1 <= x0 or y1 <= y0:
            return None
        return x0, y0, x1 - x0, y1 - y0

    def warped_board(self, image):
        """Die entzerrte Anzeigetafel dieser Bahn -- nur fuer Debug-Ausgaben.

        Die Analyse selbst entzerrt NICHT: Sie schneidet die ROIs direkt aus dem
        Originalframe, was pro Frame billiger ist. Fuer ein Belegbild lohnt die
        Entzerrung trotzdem, weil sie einmal je Wurf anfaellt und die Tafel erst
        dadurch gerade und vergleichbar aussieht.
        """
        if self._transform is None:
            return None
        return self._transform.warp(image)

    def roi_boxes(self) -> dict[str, tuple[int, int, int, int]]:
        """Alle ROI-Rechtecke dieser Bahn -- fuer die Debug-Ausschnitte."""
        boxes: dict[str, tuple[int, int, int, int]] = {}
        if self._green_box is not None:
            boxes["green_lamp"] = self._green_box
        # Bewusst `kegel_N` und nicht `pin_lamp_N`: Der ROI-Name zaehlt die
        # Lampen von oben, `_pin_numbers` zaehlt die Kegel von vorn. Beides
        # `pin_lamp_3` zu nennen hiesse, zwei verschiedene Lampen gleich zu
        # benennen -- der Debug-Ausschnitt traegt darum die Kegelnummer.
        for pin, box in zip(self._pin_numbers, self._lamp_boxes):
            boxes[f"kegel_{pin}"] = box
        # Ziffernfelder nur auf Wunsch: Sie verdreifachen die Dateizahl, sind
        # aber die einzige Moeglichkeit, eine Ziffernfrage nachtraeglich zu
        # klaeren (siehe `debug.save_digit_rois`).
        if self.cfg.debug.save_digit_rois:
            for feld, zellen in self._digit_cell_boxes.items():
                for i, box in enumerate(zellen):
                    boxes[f"ziffer_{feld}_{i}"] = box
        return boxes

    @property
    def result_pins(self) -> PinLampReading | None:
        """Lampenstand zum Zeitpunkt GREEN_OFF -- die Grundlage des Wurfergebnisses."""
        return self._result_pins

    @staticmethod
    def _crop(image: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
        """ROI-Ausschnitt als View, ohne Kopie.

        Eine leere Box liefert ein leeres Array -- der Detektor meldet dann
        UNKNOWN statt einen Messwert zu erfinden (siehe BUG-001).
        """
        x, y, w, h = box
        if w <= 0 or h <= 0:
            return np.empty((0, 0, 3), dtype=image.dtype)
        return image[y:y + h, x:x + w]

    # ---------------------------------------------------------------- Pro Frame

    def process(self, frame: Frame,
                buffer: FrameBuffer | None = None
                ) -> tuple[LaneObservation, LaneEvent | None, SampleEvent | None]:
        """Verarbeitet einen Frame. Das ist der Hot Path.

        Ausgewertet wird zunaechst nur die gruene Lampe. Die teurere
        Lampenauswertung laeuft erst, wenn ein Ereignis dazu Anlass gibt.

        Returns:
            (Beobachtung, Zustandsereignis, abgeschlossenes Sampling)
            Das Sampling ist nur gesetzt, wenn in diesem Frame ein Ereignis
            vollstaendig wurde -- dann liegen alle Frames zur Auswertung vor.
        """
        if not self._boxes_ready or self._green_box is None:
            return self._observation(LampReading.unknown("green_lamp")), None, None

        green = self.green_detector.detect(self._crop(frame.image, self._green_box))
        self._last_green = green

        # --- VERDECKTE TAFEL ---
        # Ein Score nahe null ist keine Lampenaussage, sondern gar keine: Selbst
        # die unbeleuchtete Lampe sitzt auf beigem Gehaeuse mit Gruenanteil, die
        # AUS-Grundlinie ist deshalb nie null. Null heisst, dass etwas anderes
        # davor ist -- im Bild nachgesehen: ein Spieler vor der Tafel.
        #
        # Als "aus" gelesen erzeugt das einen Wurf, den es nie gab. GEMESSEN:
        # Beide Phantomwuerfe des 52-Minuten-Videos fallen exakt in eine
        # Verdeckung (F3228 in F3229-3255, F43514 in F43512-43560), und einer
        # davon hat zusaetzlich die Grundlinie des naechsten echten Wurfs
        # vergiftet -- dessen neun Kegel wurden dadurch zu null.
        #
        # Eingefroren wird ALLES: kein Zustandswechsel, keine Lampenmessung,
        # keine Ziffern. Waehrend der Verdeckung ist keine Aussage moeglich,
        # und eine Luecke im Protokoll ist besser als ein erfundener Wurf.
        # ZWEI ZEUGEN. Der Gruen-Score erraet eine Verdeckung aus der
        # Helligkeit; die Personenmaske hat die Person gesehen.
        #
        # WARUM DER ZWEITE NOETIG WURDE: An der direkten Hallenkamera faellt
        # echtes Gruen-AUS selbst auf 0,0 (gemessen 2026-09-08, Bahn 2:
        # min 0,0, p25 1,3). Ein Schwellwert kann "aus" und "verdeckt" dort
        # nicht mehr trennen, und `occlusion_score` steht deshalb auf 0 --
        # die alte Bremse ist an dieser Kamera wirkungslos.
        #
        # Genau deshalb entstand am 2026-09-08 der Phantomwurf bei Frame 13224
        # auf Bahn 2: 0 Kegel, Ziffer unlesbar, und im Tafelbereich der
        # hoechste Vordergrundanteil des ganzen Laufs (0,197).
        # DREI ZEUGEN, und jeder sieht etwas, das die anderen nicht sehen:
        #
        #   Gruen-Score      ein Mensch VOR DER LAMPE -- der Score faellt auf 0
        #   Personenmaske    ein BEWEGTER Mensch irgendwo auf der Tafel
        #   Tafelwache       die Tafel sieht ueberhaupt nicht mehr aus wie sie
        #                    selbst -- auch wenn niemand sich bewegt und die
        #                    Lampe gar nicht mehr im Bild ist
        #
        # GEMESSEN 2026-09-13 am Streamende: Alles schwarz, kein bewegter
        # Vordergrund (Maske 0,000), und das gemessene AUS-Niveau selbst null
        # -- Gruen-Score und Personenmaske sind beide blind. Die Wache meldet
        # 61 bis 68 %. Ohne sie wurden dort drei Wuerfe gebucht.
        #   Personenmodell  ein MENSCH, als Mensch erkannt -- der einzige
        #                   Zeuge, der "Mensch davor" von "Kalibrierung
        #                   verrutscht" unterscheiden kann
        #
        # GEMESSEN 2026-09-13 an der Beweisstelle F42224 bis F42233: Das Modell
        # rahmt den Menschen in allen zehn Frames ein (Vertrauen 0,71 bis 0,86),
        # und auf 600 Frames ohne Menschen meldet es nichts.
        self._frage_das_modell(frame, green)
        # Haengt die Wache an einer Bildverschiebung fest? Dann loesen, BEVOR
        # sie in die Bremse geht -- sonst friert die Bahn dauerhaft ein.
        self._pruefe_festhaengende_wache(frame)
        if (green.score < self._verdeckungsschwelle() or self._extern_verdeckt
                or self._wache_bremst or self._modell_meldet_person):
            self._occlusion_frames += 1
        else:
            if self._occlusion_frames >= self.cfg.detection.green.occlusion_min_frames:
                log.info("Bahn %d: Tafel war %d Frames verdeckt, ab Frame %d "
                         "wieder sichtbar", self.display_number,
                         self._occlusion_frames, frame.index)
            self._occlusion_frames = 0

        if self._occlusion_frames >= self.cfg.detection.green.occlusion_min_frames:
            if self._occlusion_frames == self.cfg.detection.green.occlusion_min_frames:
                log.info("Bahn %d: Tafel ab Frame %d verdeckt (Gruen-Score "
                         "%.1f, Schwelle %.1f%s) -- Auswertung ausgesetzt",
                         self.display_number, frame.index, green.score,
                         self._verdeckungsschwelle(),
                         f", Personenmodell {100*self._modell_anteil:.0f} %"
                         if self._modell_meldet_person else "")
            # BUG-017: Merken, dass DIESES Fenster durch eine Verdeckung
            # gelaufen ist -- unabhaengig davon, ob das Fenster gerade jetzt
            # oder erst spaeter (beim naechsten GREEN_ON) schliesst.
            if self._window_open:
                self._occlusion_during_window = True
            # Regelmaessig erinnern. Ohne das bliebe eine dauerhaft
            # eingefrorene Bahn nach EINER Logzeile stumm -- und genau so
            # sieht es aus, wenn die Schwelle zum Material nicht passt: Die
            # Bahn meldet nie wieder einen Wurf, ohne dass etwas danach
            # aussieht. Die Schwelle ist an EINER Halle gemessen.
            takt = self.cfg.detection.green.occlusion_reminder_frames
            if takt > 0 and self._occlusion_frames % takt == 0:
                log.warning("Bahn %d: seit %d Frames (%.0f s) verdeckt, "
                            "Gruen-Score %.1f -- kommt hier nichts mehr, passt "
                            "womoeglich die Kalibrierung nicht zur Tafel",
                            self.display_number, self._occlusion_frames,
                            self._occlusion_frames / 25.0, green.score)
            return self._observation(green), None, None

        event = self.state_machine.update(green, frame.index, frame.timestamp)

        # --- Frame-Sampling (Auftrag Paragraph 7) ---
        completed: SampleEvent | None = None
        if event is not None and event.event is EventType.GREEN_OFF:
            self.sampler.start(frame)
            self._window_open = True
            self._green_off_frame = frame.index
            self._occlusion_during_window = False

        elif event is not None and event.event is EventType.GREEN_ON and buffer is not None:
            # Freigabe: GENAU DIESER FRAME ist das Bild, auf das geworfen
            # wird. Vom Nutzer so festgelegt (2026-09-07) -- und es raeumt zwei
            # gescheiterte Anlaeufe ab, die mit Nachlauf und Mitschreiben
            # gearbeitet hatten und beide ein Bild lieferten, auf dem das
            # Ergebnis schon stand.
            #
            # Sofort kodiert und weggelegt: Der naechste GREEN_OFF gehoert zu
            # dem Wurf, der auf DIESES Bild geworfen wird.
            self._green_on_frame = frame.index
            self._board_before = encode_board(
                frame.image, self.lane_box(),
                self.cfg.output.board_image_quality,
                self.fremdmaske(frame.image, frame.index))
            # Gruen wieder an -> das Fenster ist zu Ende. Ist der Wurf zu diesem
            # Zeitpunkt noch offen (Wartezeit 0 oder Gruen kam frueher zurueck
            # als die Wartezeit), wird er JETZT abgeschlossen.
            # Zu kurzes Fenster? Dann war es Flackern, kein Wurf.
            #
            # Die Sperre steht voreingestellt auf AUS: Sie kann echt und falsch
            # nicht trennen (siehe schema.py, `min_throw_frames`).
            offen = self.sampler.open_event
            mindest = self.cfg.state_machine.min_throw_frames
            if (offen is not None and mindest > 0
                    and frame.index - offen.trigger_frame < mindest):
                log.warning("Bahn %d: Fenster bei Frame %d war nur %d Frames lang "
                            "(mindestens %d) -- als Flackern verworfen",
                            self.display_number, offen.trigger_frame,
                            frame.index - offen.trigger_frame, mindest)
                self.sampler.abort("Fenster zu kurz -- Flackern")
                completed = None
            else:
                completed = self.sampler.finish(frame, buffer)
            if completed is not None:
                # Spaete Meldung: Der Wurf wird JETZT ausgewertet, und der
                # Nullzustand lag in seinem eigenen Fenster -- er gilt also erst
                # dem naechsten. Zwei Schritte.
                self._reset_weiterreichen()
            else:
                # Fruehe Meldung: Der Wurf ist laengst gemeldet, die Pause ist
                # erst jetzt zu Ende. Was in ihr gesehen wurde, gilt direkt dem
                # naechsten gemeldeten Wurf. Ein Schritt.
                self._reset_pending = self._reset_seen
                self._reset_seen = False
            self._window_open = False
            self._green_off_frame = None
            # Die Gruenphase des naechsten Wurfs beginnt -- was die Lampen ab
            # jetzt zeigen, gehoert zu IHM.
            self._green_phase_samples = []
            # ... und zugleich beginnt der naechste Wurf: Der jetzige Lampenstand
            # ist dessen Grundlinie (Raeumen). `_baseline_pins` bleibt dabei
            # unberuehrt -- es traegt noch die Grundlinie des Wurfs, der in
            # genau diesem Aufruf ausgewertet wird.
            # Grundlinie NACH GREEN_ON sammeln, nicht davor: Vor GREEN_ON
            # steht noch das Ergebnis des vorherigen Wurfs auf der Tafel.
            self._baseline_start = frame.index
            self._baseline_samples = []
            # Was die Pause zuletzt zeigte, bevor die Anlage freigab. Die
            # Vereinigung ist hier unbedenklich: In der Pause steht der Stand
            # still, sie faengt nur das Blinken ab.
            self._before_pins = (aggregate_pin_readings(list(self._pause_samples))
                                 if self.cfg.sampling.baseline_before_green
                                 else None)
            self._pause_samples.clear()
        elif event is not None and event.event is EventType.TIMEOUT:
            completed = self.sampler.abort("Timeout")
        else:
            self.sampler.offer(frame)

            # --- Frueher melden statt bis zum naechsten Gruen-AN zu warten ---
            # GEMESSEN: Ab 40 Frames nach GREEN_OFF ist nichts mehr zu gewinnen
            # (471 von 474 richtig, blinkende Wuerfe 100 %). Gewartet wurde
            # vorher im Mittel 15 Sekunden, beim Spielwechsel bis zu einer
            # Minute -- und der letzte Wurf einer Aufnahme ging ganz verloren.
            #
            # Das SAMMELFENSTER bleibt offen: Die Summe traegt die Anlage erst
            # kurz vor dem naechsten Gruen-AN ein (BUG-010), und der
            # Nullzustand des Spielwechsels steht ebenfalls erst spaeter da.
            # Beides wird weiter mitgelesen, nur haengt das Wurfergebnis nicht
            # mehr daran.
            wartezeit = self.cfg.sampling.report_after_green_off
            if (wartezeit > 0 and self._window_open and buffer is not None
                    and self._green_off_frame is not None
                    and frame.index - self._green_off_frame >= wartezeit
                    and self.sampler.open_event is not None):
                completed = self.sampler.finish(frame, buffer)
                # Hier wird das Spielwechsel-Zeichen NICHT weitergereicht: Der
                # Nullzustand steht erst spaeter in der Pause (gemessen 306
                # Frames nach Gruen-AUS). Das erledigt der Gruen-AN-Zweig.

        # --- Die Wurfnummer, JEDEN Frame, solange Gruen an ist ---
        #
        # WARUM JEDEN FRAME (gemessen 2026-09-28, jeder Frame gelesen): Die
        # Tafel zaehlt hoch, wenn die Kugel die halbe Bahn passiert -- der
        # Nutzer: *„Da ist noch weit kein Kegel in der Nähe."* Ueber 18 Zyklen
        # aller vier Bahnen springt die Nummer AUSNAHMSLOS zuerst, im Median
        # 6 Frames (0,30 s) vor der ersten Lampenaenderung.
        #
        # SECHS FRAMES. Mit dem Lesetakt von fuenf war der Sprung damit bis zu
        # fuenf Frames zu spaet erkannt und landete hinter der ersten Lampe --
        # die Grundlinie griff in den laufenden Wurf. Auf Bahn 5 wurde aus
        # einem Neuner eine Drei. Eine fruehere Messung schien zu zeigen, dass
        # die Nummer manchmal SPAETER springt; das war nur die Aufloesung, der
        # gemessene Abstand betrug genau ein Abtastintervall.
        #
        # KOSTEN: 1,99 ms fuer alle vier Bahnen (nur dieses eine Ziffernfeld;
        # der volle Satz kostet 14,70 ms). Budget je Frame sind 40 ms. Nur
        # waehrend der Gruenphase -- in der Pause springt keine Wurfnummer.
        if (self.cfg.sampling.breakpoint_from_throw_number
                and not self._window_open
                and self._green_on_frame is not None):
            self._nummer_mitschreiben(frame)

        # --- Grundlinie des laufenden Wurfs ---
        # Die Kegel fallen, waehrend die gruene Lampe an ist (Nutzerhinweis,
        # gemessen bestaetigt). Kurz NACH GREEN_ON ist die Anlage neu
        # aufgestellt und der Ball noch unterwegs -- dort steht, welche Kegel
        # bereits lagen.
        if self._baseline_start is not None:
            versatz = frame.index - self._baseline_start
            if versatz in self.cfg.sampling.baseline_offsets:
                messung = self._read_pin_lamps(frame, anlass="grundlinie")
                if messung is not None:
                    self._baseline_samples.append(messung)
            if versatz >= max(self.cfg.sampling.baseline_offsets):
                nachher = aggregate_pin_readings(self._baseline_samples)
                # Beide Messungen koennen zu HOCH liegen, keine zu niedrig --
                # darum die Schnittmenge. Siehe `baseline_aus_zwei`.
                self._pending_baseline = baseline_aus_zwei(
                    self._before_pins, nachher)
                if (self._before_pins is not None and nachher is not None
                        and self._before_pins.pins != nachher.pins):
                    log.info("Bahn %d: Grundlinie vor Gruen %s, danach %s -- "
                             "es gilt %s", self.display_number,
                             list(self._before_pins.pins), list(nachher.pins),
                             list(self._pending_baseline.pins))
                self._before_pins = None
                self._baseline_start = None

        # --- Mitlesen WAEHREND der Gruenphase ---
        # Vom Nutzer vorgeschlagen: Die Kegel fallen ja gerade jetzt, also steigt
        # die Zahl waehrend der Gruenphase an. Wer erst danach misst, verlaesst
        # sich darauf, dass das Ergebnis stehen bleibt -- und verliert es, wenn
        # die Pause kurz ist. GEMESSEN: Auf Bahn 4 rettet die Gruenphase drei
        # Wuerfe, bei denen das Fenster danach zu kurz war.
        #
        # Erst NACH dem Grundlinienfenster: Davor steht dort, was bereits lag.
        raster = self.cfg.sampling.green_phase_interval
        if (raster > 0 and not self._window_open
                and self._baseline_start is None
                and self._pending_baseline is not None
                and frame.index % raster == 0):
            messung = self._read_pin_lamps(frame, anlass="gruenphase")
            if messung is not None:
                self._green_phase_samples.append((frame.index, messung))

        # Zwei getrennte Zwecke, bewusst unterschieden:
        #
        # 1. WURFERGEBNIS -- nur bei GREEN_OFF. Der Auftrag (Paragraph 5A) verlangt,
        #    dass die Lampen erst als Ergebnis gelten, wenn die gruene Lampe aus ist.
        #    Dieser Wert fliesst spaeter in den ThrowResult.
        if event is not None and event.event is EventType.GREEN_OFF:
            self._result_pins = self._read_pin_lamps(frame, is_result=True)
            self._display_pins = self._result_pins
            # Das Ergebnis gilt, nicht der geglaettete Verlauf davor.
            self._display_history.clear()
            # Die Grundlinie dieses Wurfs wird jetzt festgeschrieben.
            #
            # ZWEI QUELLEN, und die laufende Spur hat Vorrang (BUG-031): Das
            # Fenster nach dem Gruen-AN misst EINEN Augenblick, und wenn die
            # Gruenerkennung spaet kommt, die Gruenphase ungewoehnlich lang ist
            # oder die Bahn gerade verdeckt war, ist es nicht der Augenblick
            # des Wurfs. Die Spur enthaelt alle Messungen seit dem vorigen
            # Wurf; ihr kleinster mehrfach bestaetigter Stand IST die
            # Grundlinie. Schweigt sie, gilt weiter das Fenster.
            self._baseline_pins = self._pending_baseline

            # ZUERST DIE PFLICHT, DANN DIE KUER.
            #
            # Alles, was den naechsten Wurf sauber beginnen laesst, steht VOR
            # jeder abgeleiteten Rechnung. Am 2026-09-19 stand es andersherum:
            # Die Grundlinie aus der Spur wurde zuerst berechnet, warf einen
            # TypeError -- und weil P8 die Ausnahme auffaengt, lief die Bahn
            # weiter, ohne dass die Ergebnisliste je zurueckgesetzt wurde. Jeder
            # Wurf erbte danach das Raeumbild des Vorgaengers mit allen neun
            # Lampen. Ueber einen ganzen Spieltag war jeder zweite Wurf zu hoch.
            #
            # Eine aufgefangene Ausnahme heisst nicht, dass der Zustand heil
            # ist. Reihenfolge ist deshalb kein Stil, sondern Schutz.
            bruch = self._breakpoint()
            self._result_samples = [m for fr, m in self._green_phase_samples
                                    if bruch is None or fr >= bruch]
            if self._result_pins is not None:
                self._result_samples.append(self._result_pins)
            # Neues Fenster: Die Mitlesungen des vorigen Wurfs sind verbraucht.
            # Ohne dieses Zuruecksetzen truege der naechste Wurf die Summe des
            # vorletzten -- genau der Versatz, der behoben werden soll.
            self._late_samples = {}
            self._nach_samples = []
            # MIT BREAKPOINT beginnt die Grundlinienspur beim GRUEN-AN, nicht
            # beim vorigen Gruen-AUS. Die Pause dazwischen gehoert dem vorigen
            # Wurf -- dort steht sein Ergebnis, dort wird der Satz gestellt,
            # und dort leuchtet ein Fehlercode nach.
            beginn = self._green_on_frame if bruch is not None else None
            # MIT FRAMENUMMER aufgehoben, bevor die Spur geleert wird: Der
            # Anker aus dem Vorstand braucht die Reihenfolge, nicht nur die
            # Staende (siehe `_anker_vorstand`).
            spur_roh = list(self._grundlinien_spur)
            spur = [m for fr, m in self._grundlinien_spur
                    if (bruch is None or fr < bruch)
                    and (beginn is None or fr >= beginn)]
            # Der naechste Wurf beginnt mit einer leeren Spur -- sonst truege
            # er die Staende dieses Wurfs noch mit sich.
            self._grundlinien_spur.clear()
            self._nummer_spur.clear()

            # ERST JETZT das Abgeleitete: die Grundlinie aus der laufenden Spur
            # (BUG-031). Das Fenster nach dem Gruen-AN misst EINEN Augenblick,
            # und wenn die Gruenerkennung spaet kommt, die Gruenphase
            # ungewoehnlich lang ist oder die Bahn gerade verdeckt war, ist es
            # nicht der Augenblick des Wurfs. Die Spur enthaelt alle Messungen
            # seit dem vorigen Wurf; ihr kleinster Stand ueber eine Blinkperiode
            # IST die Grundlinie. Schweigt sie, gilt weiter das Fenster.
            if self.cfg.sampling.baseline_from_trace:
                # Die Gruppengroesse ergibt sich aus dem Lesetakt: Sie muss
                # mehr als eine Blinkperiode abdecken, und der Takt steht erst
                # zur Laufzeit fest.
                takt = max(1, self._live_interval)
                gruppe = max(
                    2,
                    -(-self.cfg.sampling.baseline_trace_window_frames // takt))
                if bruch is not None and len(spur) >= gruppe:
                    # MIT BREAKPOINT: der Stand UNMITTELBAR VOR dem Sprung.
                    #
                    # Nutzer, 2026-09-25: *„Bei der Grundlinie müssen so späte
                    # Frames wie möglich genommen werden."* Ohne Breakpoint
                    # war das gefaehrlich -- niemand wusste, wo "spaet" endet
                    # und der Wurf beginnt. Der Sprung der Wurfnummer sagt es.
                    #
                    # WARUM NICHT WEITER DER KLEINSTE STAND: Der kleinste ueber
                    # die ganze Spur war der Griff an BUG-031 vorbei, als die
                    # Spur noch beim vorigen Gruen-AUS begann. Er greift aber
                    # auch nach einem Fehlercode. GEMESSEN an Bahn 4, Wurf 23:
                    # Die richtige Grundlinie [1,2,3,6,7,8,9] steht in 91 von
                    # 98 Messungen vor dem Sprung und in allen letzten sechs --
                    # der kleinste Stand war [6,7,9], der dauerleuchtende Teil
                    # des Fehlercodes. Ergebnis: 8 Kegel statt 1.
                    #
                    # Vereinigt wird ueber eine Blinkperiode, damit eine Lampe
                    # in ihrer Dunkelphase nicht fehlt.
                    aus_spur = aggregate_pin_readings(spur[-gruppe:])
                else:
                    aus_spur = grundlinie_aus_spur(spur, gruppe)
                if aus_spur is not None:
                    if (self._pending_baseline is not None
                            and set(aus_spur.pins)
                            != set(self._pending_baseline.pins)):
                        log.info(
                            "Bahn %d: Grundlinie aus dem Fenster %s, aus der "
                            "laufenden Spur %s -- es gilt die Spur",
                            self.display_number,
                            list(self._pending_baseline.pins),
                            list(aus_spur.pins))
                    self._baseline_pins = aus_spur

            # --- DIE GRUNDLINIE IST NICHT FREI (Nutzeridee 2026-09-29) ---
            #
            # Kegel stehen nicht wieder auf. Es gibt genau zwei erlaubte
            # Grundlinien: leer (die Anlage hat neu aufgestellt) oder den
            # Stand des vorigen Wurfs. Welche gilt, zeigt die Tafel selbst --
            # und der Augenblick, in dem sie einen der beiden zeigt, ist
            # zugleich der Beginn DIESES Wurfs. Alles davor ist Nachleuchten:
            # Jubelblinken oder ein Fehlercode.
            #
            # Damit wird an EINER Stelle geschnitten. Das ist der Unterschied
            # zu allem, was vorher versucht wurde: Eine reparierte Grundlinie
            # allein genuegt nicht, weil derselbe Fehlercode auch im Ergebnis
            # steht. Gemessen an Bahn 4 Spiel 4 Wurf 23 -- nur Grundlinie: 2
            # Kegel, Grundlinie und Beginn: 1 Kegel, Tafel sagt 1.
            if self.cfg.sampling.baseline_from_previous_state:
                anker = self._anker_vorstand(spur_roh)
                if anker is not None:
                    ab_frame, grundlinie = anker
                    if (self._baseline_pins is not None
                            and set(grundlinie.pins)
                            != set(self._baseline_pins.pins)):
                        log.info(
                            "Bahn %d: Grundlinie gemessen %s -- erlaubt ist "
                            "nur leer oder %s, es gilt %s ab Frame %d",
                            self.display_number,
                            list(self._baseline_pins.pins),
                            list(self._vorstand.pins) if self._vorstand
                            else [],
                            list(grundlinie.pins), ab_frame)
                    self._baseline_pins = grundlinie
                    self._result_samples = [
                        m for fr, m in self._green_phase_samples
                        if fr >= ab_frame]
                    if self._result_pins is not None:
                        self._result_samples.append(self._result_pins)

        # 2. ANZEIGE -- regelmaessig, damit in der Oberflaeche sichtbar ist, was
        #    die Tafel gerade zeigt. Ohne das bliebe die Kegelraute waehrend des
        #    ganzen Videos grau, und Fehlkalibrierungen fielen erst beim ersten
        #    Wurf auf. Kostet rund 1 ms bei einem Budget von 40 ms.
        elif (self._live_interval > 0
              and frame.index % self._live_interval == 0):
            self._display_pins = self._read_pin_lamps(frame)
            if self._display_pins is not None:
                self._display_history.append(self._display_pins)
                # ... und in die Grundlinienspur (BUG-031). Dieselbe Messung,
                # kein zusaetzlicher Aufwand -- nur wird sie jetzt auch
                # aufgehoben, statt nach der Anzeige vergessen zu werden.
                self._grundlinien_spur.append((frame.index, self._display_pins))
            # Laeuft gerade ein Ereignis, zaehlt diese Messung zum Wurfergebnis.
            # Das kostet nichts zusaetzlich: Der Wert wurde soeben ohnehin fuer
            # die Anzeige gelesen.
            #
            # ABER NUR, WENN DIE ZAEHLUNG NOCH LAEUFT. Nutzer, 2026-09-28:
            # *„sobald Grünaus geht, müssen wir fertig sein mit unserer
            # Zählung."* Das Ereignisfenster bleibt nach Gruen-AUS offen, um
            # die spaet nachziehenden ZIFFERN mitzulesen -- die Lampen sind da
            # laengst fertig. Was danach noch auf der Tafel passiert, gehoert
            # nicht mehr zum Wurf: Genau dort beginnt der Fehlercode (BUG-036),
            # und die Vereinigung nahm dessen Lampen mit ins Ergebnis.
            if (self.sampler.open_event is not None
                    and self._display_pins is not None
                    and not self.cfg.sampling.count_closes_at_green_off):
                # GEPUFFERT, nicht direkt angehaengt. Nach Gruen-AUS blinkt
                # entweder der Jubel-Effekt (dann brauchen wir diese Frames:
                # ohne sie wird aus einem Neuner eine Eins) oder ein
                # Fehlercode (dann verderben sie das Ergebnis). Welches von
                # beidem, steht erst am Ende des Fensters fest.
                self._nach_samples.append(self._display_pins)
            # ... und zugleich die Pause mitschreiben: `_window_open` ist genau
            # zwischen GREEN_OFF und GREEN_ON wahr. Kostet nichts, die Messung
            # ist soeben ohnehin entstanden.
            if self._window_open and self._display_pins is not None:
                self._pause_samples.append(self._display_pins)

        # Die spaet aktualisierten Felder waehrend des Fensters mitlesen.
        # Bewusst NICHT ueber den Ringpuffer geloest: Um 60 Frames zurueckgreifen
        # zu koennen, muesste er auf ueber 500 MB wachsen (1920x1080x3 je Frame).
        # Das Mitlesen kostet vier kleine Ausschnitte alle acht Frames.
        #
        # Gebunden an `_window_open`, NICHT an den Sampler: Der Wurf wird
        # inzwischen frueher gemeldet, die Summe traegt die Anlage aber erst
        # kurz vor dem naechsten Gruen-AN ein (BUG-010), und der Nullzustand des
        # Spielwechsels steht ebenfalls erst spaeter da. Beides braucht das
        # ganze Fenster, das Wurfergebnis nicht mehr.
        if (self._window_open
                and self._late_interval > 0
                and frame.index % self._late_interval == 0):
            self._read_late_fields(frame)

        # Der Nullzustand ebenfalls IMMER, aus demselben Grund: Ob er in eine
        # Gruenpause faellt, entscheidet die Anlage -- nicht wir.
        nulltakt = self.cfg.scoring.game_reset_check_interval
        if (self.cfg.scoring.game_reset_by_zero_display and nulltakt > 0
                and frame.index % nulltakt == 0):
            self._pruefe_nullzustand(frame)

        # DIE WACHE MITFUEHREN. Sie braucht eine Referenz der leeren Tafel,
        # und die entsteht nur, wenn sie regelmaessig hinsieht. Getaktet, weil
        # die Referenz sich langsam aendert -- Licht, nicht Inhalt.
        if self._wache_takt > 0 and frame.index % self._wache_takt == 0:
            box = self.lane_box()
            if box is not None:
                aus = self._crop(frame.image, box)
                if aus is not None and aus.size:
                    abweichung = self.wache.beobachte(aus)
                    # ZWEI SCHWELLEN, ZWEI FRAGEN (BUG-030).
                    #
                    # `_wache_meldet_fremdes` ist die Frage "soll dieses Bild
                    # geschwaerzt werden" -- niedrige Schwelle, denn ein Bild
                    # zu viel zu schwaerzen kostet nichts. Daran haengt auch
                    # die Erholung der festhaengenden Referenz.
                    #
                    # `_wache_bremst` ist die Frage "soll die Auswertung
                    # anhalten" -- und die verlangt viel mehr. Mit einer
                    # Schwelle fuer beides hielt eine festhaengende Referenz
                    # eine Bahn 1089 Frames an, waehrend zwei andere Zeugen
                    # klar widersprachen. Die Messwerte stehen bei
                    # `detection.person_mask.wache_bremse_schwelle`.
                    self._wache_meldet_fremdes = (
                        self.wache.bereit and abweichung >= self.wache.schwelle)
                    self._wache_bremst = (
                        self.wache.bereit
                        and abweichung >= self._wache_bremse_schwelle)

        # Die Anzeige der gelesenen Ziffern -- nur fuers Auge, kein Einfluss
        # auf irgendeine Zaehlung.
        #
        # VERSETZT JE BAHN, und das ist kein Schoenheitsfehler: GEMESSEN kostet
        # eine Lesung 4,25 ms je Bahn. Laesen alle vier im selben Frame, kaeme
        # dieser eine Frame auf 17 ms zusaetzlich -- zusammen mit den 29 ms des
        # letzten Laufs waere das Budget von 40 ms gerissen, und ein Frame, der
        # zu lange braucht, geht im Livestream verloren. Versetzt traegt jeder
        # betroffene Frame nur eine Bahn.
        if (self._live_digit_interval > 0
                and (frame.index - self.lane_id) % self._live_digit_interval == 0):
            self._lies_anzeige_live(frame)

        # Der Fehlwurfzaehler dagegen IMMER -- ein Wurf ohne Kegel faellt,
        # waehrend die gruene Lampe an ist, also ausserhalb jedes Fensters.
        takt = self.cfg.detection.digits.foul_read_interval
        if (self.cfg.scoring.detect_zero_throws and takt > 0
                and frame.index % takt == 0):
            self._pruefe_fehlwurfzaehler(frame)

        return self._observation(green), event, completed

    def _verdeckungsschwelle(self) -> float:
        """Ab welchem Gruen-Score die Tafel als VERDECKT gilt.

        RELATIV ZUM UNTEREN RAND DER GEMESSENEN AUS-WOLKE, nicht als feste
        Zahl. Der Grund ist derselbe wie bei BUG-011: Ein absoluter Wert kann
        nicht zwei Aufstellungen bedienen.

        WARUM DER RAND UND NICHT DER GIPFEL (2026-09-14). Bis dahin bezog sich
        der Anteil auf das AUS-NIVEAU, also den Gipfel der Wolke. Der sagt, wo
        AUS ueblicherweise liegt -- aber nichts darueber, wie weit die Wolke
        nach unten reicht, und genau dort entscheidet es sich.

        GEMESSEN an der Hallenkamera, echte AUS-Wolke (Frames, in denen
        Tafelwache UND Personenmodell schweigen):

            Bahn   Wolke        Gipfel   Rand   Schwelle alt   bremste alt
              2    0,0 .. 0,7      0,7    0,0           0,90       28,4 %
              3    1,4 .. 3,5      3,5    1,0           1,50        0,2 %
              4    7,1 .. 11,7    11,7    7,0           3,30        0,0 %

        Gleiche Halle, gleiches Licht, gleicher Frame -- drei voellig
        verschiedene Lampen. Bahn 2 bremste in 28 % ALLER Frames auf voellig
        freier Tafel, weil ihr echtes AUS selbst 0,0 liest. Am Rand gemessen
        bekommt sie 0,0: Dort kann der Gruen-Score nichts trennen, und die
        Bremse schweigt statt zu raten.

        Im Livestream wirkt dieselbe Regel umgekehrt -- die Wolken liegen bei
        14 bis 31, der Rand bei 20 bis 30, und die Schwelle steigt von rund 8
        auf 10 bis 15. Schaerfer also, bei praktisch gleicher Bremsrate.

        Solange keine zwei Wolken gemessen sind (Anlauf), gilt der feste Wert
        aus der Konfiguration.
        """
        fest = self.cfg.detection.green.occlusion_score
        anteil = self.cfg.detection.green.occlusion_edge_fraction
        if anteil <= 0:
            return fest
        rand = self.green_detector.aus_rand
        if rand is None or rand <= 0:
            # Rand 0 heisst: Die AUS-Wolke reicht selbst bis null. Dort kann
            # der Gruen-Score ein AUS nicht von einer Verdeckung trennen --
            # dann schweigt er, statt zu raten. Die drei anderen Zeugen
            # bleiben davon unberuehrt.
            return fest
        return max(fest, anteil * rand)

    def _nummer_mitschreiben(self, frame: Frame) -> None:
        """Liest die Wurfnummer und haengt sie an die Spur.

        Nur dieses eine Feld (1,99 ms fuer alle vier Bahnen), nicht der volle
        Satz. Unlesbares wird weggelassen statt als Luecke gefuehrt -- fuer den
        Sprung zaehlt nur, dass zwei aufeinanderfolgende LESBARE Werte sich um
        eins unterscheiden.
        """
        lesung = self.read_digits(frame, felder=("throw_number",)).get(
            "throw_number")
        if lesung is None or not lesung.text or not lesung.text.isdigit():
            return
        if lesung.confidence < self.cfg.sampling.breakpoint_min_confidence:
            return
        self._nummer_spur.append((frame.index, int(lesung.text)))

    def _breakpoint(self) -> int | None:
        """Der Frame, an dem die Tafel auf diesen Wurf hochgezaehlt hat.

        Gesucht wird der LETZTE Anstieg um genau eins innerhalb der laufenden
        Gruenphase. Der letzte, nicht der erste: Steckt mehr als ein Wurf in
        einer Gruenphase -- ein Fehlwurf schaltet Gruen nicht aus (BUG-035) --,
        gehoert das Ergebnis zum spaeteren.

        `None` heisst: kein Sprung gesehen. Dann gilt das bisherige Verfahren.
        Gemessen tritt das in 4 bis 12 % der Zyklen ein.
        """
        if not self.cfg.sampling.breakpoint_from_throw_number:
            return None
        ab = self._green_on_frame
        werte = [(fr, n) for fr, n in self._nummer_spur
                 if ab is None or fr >= ab]
        bruch = None
        for (f1, n1), (f2, n2) in zip(werte, werte[1:]):
            if n2 == n1 + 1:
                bruch = f2
        if bruch is None:
            log.debug("Bahn %d: kein Wurfnummernsprung in der Gruenphase "
                      "(%d Lesungen) -- es gilt das Fenster",
                      self.display_number, len(werte))
        else:
            log.debug("Bahn %d: Breakpoint bei Frame %d "
                      "(%d Lesungen in der Gruenphase)",
                      self.display_number, bruch, len(werte))
        return bruch

    def _read_pin_lamps(self, frame: Frame,
                        is_result: bool = False,
                        anlass: str = "live") -> PinLampReading | None:
        """Liest die neun Kegellampen.

        Args:
            is_result: True, wenn dies die Messung fuer das Wurfergebnis ist.
                Nur dann ist eine unlesbare Lampe eine Warnung wert -- bei der
                Live-Vorschau (alle paar Frames, vier Bahnen) entstuenden sonst
                hunderte identischer Meldungen, in denen die eine echte Warnung
                untergeht.
        """
        if not self._lamp_boxes:
            return None
        patches = [self._crop(frame.image, box) for box in self._lamp_boxes]
        reading = self.lamp_detector.detect(patches, self._pin_numbers)
        # Die Spur haengt bewusst HIER und nicht an einem eigenen Takt: So
        # steht in ihr genau das, was der Detektor gesehen hat -- nicht eine
        # zweite, unabhaengig entstandene Messung.
        if self.lamp_trace is not None:
            self.lamp_trace.add(frame.index, frame.timestamp,
                                self.display_number, reading, self.lamp_detector,
                                anlass="ergebnis" if is_result else anlass)

        if not reading.is_complete:
            if is_result:
                log.warning("Bahn %d: nicht alle Kegellampen lesbar bei Frame %d "
                            "-- Wurfergebnis unsicher", self.display_number, frame.index)
            elif not self._preview_warned:
                # Nur EINMAL je Lauf melden. Frueher wurde das Flag nach jedem
                # gelungenen Frame zurueckgesetzt -- bei flackernden Lampen
                # entstand dadurch trotzdem Log-Spam. Die Ursache (meist eine
                # unpassende Kalibrierung) aendert sich waehrend eines Laufs
                # ohnehin nicht, eine Meldung genuegt also.
                log.warning("Bahn %d: Kegellampen zeitweise nicht lesbar "
                            "(erstmals Frame %d) -- passt die Kalibrierung zu "
                            "diesem Video?", self.display_number, frame.index)
                self._preview_warned = True
        return reading

    def _geglaettete_anzeige(self) -> PinLampReading | None:
        """Der Lampenstand fuer die LIVE-ANZEIGE -- blinkfest.

        NUR fuer die Anzeige. Die Wurfzaehlung benutzt diesen Wert nicht; sie
        fasst ihre eigenen Messungen ueber das ganze Ereignisfenster zusammen.

        WARUM -- gemessen 2026-09-08 an der Hallenkamera: Die neun Kegellampen
        blinken GEMEINSAM, Periode rund 15 Frames (1 Sekunde), etwa 40 Prozent
        davon dunkel. Die Anzeige liest EINEN Frame und meldete darum
        regelmaessig "aus", waehrend die Lampe sichtbar leuchtete.

        Zusammengefasst wird mit derselben Regel wie beim Wurfergebnis: AN,
        wenn in mindestens einer Messung an. Das ist keine Beschoenigung,
        sondern Physik -- Blinken kann eine leuchtende Lampe dunkel erscheinen
        lassen, aber keine dunkle zum Leuchten bringen.
        """
        if not self._display_history:
            return self._display_pins
        return aggregate_pin_readings(list(self._display_history))             or self._display_pins


    def _observation(self, green: LampReading) -> LaneObservation:
        return LaneObservation(
            lane_id=self.lane_id,
            display_number=self.display_number,
            state=self.state_machine.state,
            green=green,
            pins=self._geglaettete_anzeige(),
            throw_count=self.throw_count,
            running_total=self.running_total,
            sampling=self.sampler.open_event is not None,
            digits=dict(self._live_digits),
        )

    def reset(self) -> None:
        self.state_machine.reset()
        self.throw_count = 0
        self.running_total = 0
        self._result_pins = None
        self._display_pins = None
        self._display_history.clear()
        self._pending_baseline = None
        self._baseline_pins = None
        self._vorstand = None
        self._baseline_samples = []
        self._baseline_start = None
        self._grundlinien_spur.clear()
        self._nummer_spur.clear()
        self._result_samples = []
        self._nach_samples = []
        self._late_samples = {}
        self._green_phase_samples = []
        self._pause_samples.clear()
        self._before_pins = None
        self._window_open = False
        self._green_off_frame = None
        self._occlusion_during_window = False
        self._foul_value = None
        self._foul_candidate = None
        self._foul_repeats = 0
        self._foul_events = []
        self._occlusion_frames = 0
        self._reset_observations = 0
        self._reset_latch = False
        self._verlassen_observations = 0
        self._reset_seen = False
        self._reset_carry = False
        self._reset_pending = False
        self.sampler.reset()
        self._preview_warned = False
