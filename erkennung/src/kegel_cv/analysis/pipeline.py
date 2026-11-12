"""Analyse-Pipeline: orchestriert alle Bahnen.

Kennt keine GUI und keine Videoquelle -- sie bekommt Frames und liefert
Beobachtungen. Dadurch laesst sie sich ohne Qt und ohne Video testen, und
spaeter unveraendert mit einem Livestream betreiben.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass, field, replace

from .gegenprobe import MELDENSWERT, Gegenprobe
from ..calibration.anlage import wende_an
from ..calibration.model import Calibration
from ..config.schema import AppConfig
from ..debug.frame_logger import FrameLogger
from ..debug.green_trace import GreenTrace
from ..debug.lamp_trace import LampTrace
from ..debug.cycle_sheet import CycleSheet
from ..debug.throw_log import ThrowLog
from ..debug.throw_sheet import ThrowSheet
from ..detection.person_maske import PersonMaske
from ..detection.personen_modell import PersonenModell
from ..detection.state_machine import LaneEvent
from ..video.source import Frame, FrameBuffer
from ..models.readings import (LampReading, LampState, PinLampReading,
                              aggregate_pin_readings, ist_fehlercode)
from ..models.throw import FrameRole, ThrowResult
from .frame_sampler import SampleEvent
from .board_image import encode_board, pick_board_frame
from .lamp_watchdog import LampWatchdog
from .lane_processor import LaneObservation, LaneProcessor
from .temporal_aggregator import FieldAggregator, TemporalAggregator
from .throw_analyzer import ThrowAnalyzer

log = logging.getLogger(__name__)


@dataclass
class FrameResult:
    """Ergebnis der Verarbeitung eines Frames ueber alle Bahnen."""

    frame_index: int
    timestamp: float
    observations: list[LaneObservation] = field(default_factory=list)
    events: list[LaneEvent] = field(default_factory=list)
    samples: list[SampleEvent] = field(default_factory=list)
    throws: list[ThrowResult] = field(default_factory=list)
    processing_ms: float = 0.0


@dataclass
class PerformanceMonitor:
    """Laufende Leistungsmessung (Auftrag Paragraph 20).

    Nicht optimieren ohne Messwert -- deshalb laeuft das von Anfang an mit.
    """

    window: int = 100
    _times: list[float] = field(default_factory=list)
    frames: int = 0
    _started: float = field(default_factory=time.perf_counter)

    def record(self, elapsed_ms: float) -> None:
        self.frames += 1
        self._times.append(elapsed_ms)
        if len(self._times) > self.window:
            self._times.pop(0)

    @property
    def average_ms(self) -> float:
        return sum(self._times) / len(self._times) if self._times else 0.0

    @property
    def processing_fps(self) -> float:
        avg = self.average_ms
        return 1000.0 / avg if avg > 0 else 0.0

    def summary(self, video_fps: float) -> str:
        return (f"Video FPS: {video_fps:.1f} | Processing FPS: {self.processing_fps:.1f} "
                f"| {self.average_ms:.1f} ms/Frame | {self.frames} Frames")


class AnalysisPipeline:
    """Verarbeitet Frames und fuehrt alle Bahnen unabhaengig voneinander."""

    def __init__(self, calibration: Calibration, cfg: AppConfig,
                 video_id: str = "unbenannt", game_name: str = "") -> None:
        # DAS ANLAGENPROFIL ZUERST. Was die Kalibrierung ueber ihre Anlage
        # weiss -- Lampenfarbe, Kegelzahl, Zyklus -- gilt fuer diesen Lauf und
        # nichts anderes. Ohne Profil bleibt `cfg` unveraendert; eine
        # Kalibrierung aus der Zeit davor verhaelt sich damit genau wie bisher.
        cfg = wende_an(cfg, calibration.anlage)
        self.cfg = cfg
        self.calibration = calibration
        # WELCHE BAHNEN DIESES GERAET ERFASST (`processing.lanes`).
        #
        # Gefiltert wird ueber die Bahnnummer der ANLAGE, nicht ueber den
        # Index: Der Nutzer denkt in "Bahn 2 und 3", und genau das soll er
        # eintragen. Leer heisst alle -- sonst waere die Vorgabe "nichts
        # auswerten".
        #
        # Eine nicht erfasste Bahn bekommt gar keinen Prozessor. Das ist der
        # Punkt: Auf einem Telefon, das nur zwei Bahnen sieht, soll es auch nur
        # zwei Bahnen kosten.
        gewaehlt = set(cfg.processing.lanes or ())
        bahnen = [l for l in calibration.lanes
                  if not gewaehlt or l.real_lane_number in gewaehlt]
        if gewaehlt:
            log.info("Erfasst werden nur die Bahnen %s -- %d von %d "
                     "kalibrierten Bahnen", sorted(gewaehlt), len(bahnen),
                     len(calibration.lanes))
            fehlt = gewaehlt - {l.real_lane_number for l in calibration.lanes}
            if fehlt:
                log.warning("Bahn(en) %s sollen erfasst werden, stehen aber "
                            "nicht in der Kalibrierung", sorted(fehlt))
        self.processors: list[LaneProcessor] = [
            LaneProcessor(lane, cfg) for lane in bahnen
        ]

        # PERSONENMASKE. Schwaerzt bewegte Menschen, bevor irgendetwas
        # ausgewertet wird, und meldet dabei, welche Tafel verdeckt ist.
        #
        # Zustandsbehaftet (Hintergrundmodell) -- genau EIN Aufruf je Frame.
        m = cfg.detection.person_mask
        self.person_maske = PersonMaske(
            history=m.history, var_threshold=m.var_threshold, scale=m.scale,
            min_blob_px=m.min_blob_px, dilate_px=m.dilate_px,
            occlusion_fraction=m.occlusion_fraction,
            warmup_frames=m.warmup_frames, enabled=m.enabled)
        self._verdeckt_gemeldet: set[int] = set()

        # DAS PERSONENMODELL. Es gehoert der Pipeline und nicht den Bahnen,
        # weil alle vier sich EINEN Netzdurchlauf je Frame teilen: Gesucht wird
        # in einem Band ueber alle Tafeln, nicht viermal einzeln. Auf dem
        # einzelnen Tafelausschnitt findet das Netz gemessen NICHTS -- siehe
        # `detection/personen_modell.py`.
        pm = cfg.detection.person_model
        self.personen_modell = PersonenModell(
            (cfg.project_root / pm.model_path) if pm.model_path else None,
            eingang=pm.input_size, vertrauen=pm.confidence, nms=pm.nms,
            luft_unten=pm.band_below, luft_seitlich=pm.band_sides,
            gedaechtnis=cfg.processing.frame_buffer_size, aktiv=pm.enabled)
        for processor in self.processors:
            processor.setze_personenmodell(self.personen_modell)
        self.buffer = FrameBuffer(cfg.processing.frame_buffer_size)
        self.performance = PerformanceMonitor()
        # Der Debug-Ordner traegt den SPIELNAMEN, wenn es einen gibt --
        # `manifest-oci-us-ashburn-1-vop1.edgemv.mux.com_rendition.m3u8`
        # findet niemand wieder, "2. Spieltag Herren" schon.
        self.frame_logger = FrameLogger(cfg.debug, cfg.project_root,
                                        game_name or video_id)
        # Spur der gruenen Lampe -- landet im Ordner DIESES Laufs, damit sie
        # sich den Bildern eindeutig zuordnen laesst.
        self.green_trace = GreenTrace(self.frame_logger.root / "gruenspur.csv",
                                      aktiv=cfg.debug.green_trace)
        self.lamp_trace = LampTrace(self.frame_logger.root / "lampenspur.csv",
                                    aktiv=cfg.debug.lamp_trace,
                                    takt=cfg.debug.lamp_trace_interval)
        for processor in self.processors:
            processor.lamp_trace = self.lamp_trace
        # Jeder erkannte Wurf sofort als CSV-Zeile. Ohne sie gibt es die
        # Ergebnisse eines Laufs nur ueber einen ZWEITEN Durchlauf mit den
        # Werkzeugen -- an einem Spieltag laeuft die Analyse aber genau einmal.
        # ZWEI MESSSYSTEME, die einander befragen -- beobachtend, nicht
        # korrigierend. Siehe `gegenprobe.py`.
        self.gegenprobe = (Gegenprobe(pin_count=cfg.scoring.pin_count)
                           if cfg.debug.gegenprobe else None)
        # Die Summe des zuletzt ausgewerteten Wurfs je Bahn -- als Lesung MIT
        # Kandidaten je Stelle, nicht als Zahl. Nur so kann die Gegenprobe
        # gefuehrt lesen (`gefuehrtes_lesen`): Sie muss wissen, worueber die
        # Frames uneinig waren, nicht nur, wer gewonnen hat.
        self._summenlesung: dict[int, object] = {}
        self.throw_log = ThrowLog(self.frame_logger.root / "wuerfe.csv",
                                  aktiv=cfg.debug.throw_log)
        self.throw_sheet = ThrowSheet(
            self.frame_logger.root,
            aktiv=cfg.debug.throw_sheet,
            faktor=cfg.debug.throw_sheet_scale,
            jpeg_qualitaet=cfg.debug.throw_sheet_quality,
            nur_auffaellige=cfg.debug.throw_sheet_only_flagged,
        )
        # Je Bahn ein Blatt: Wuerfe in den Zeilen, Laeufe in den Spalten.
        # Wird erst beim Schliessen geschrieben -- vorher steht die Spaltenzahl
        # nicht fest.
        self.cycle_sheet = CycleSheet(self.frame_logger.root,
                                      aktiv=cfg.debug.cycle_sheets)
        self.analyzers: dict[int, ThrowAnalyzer] = {
            lane.lane_id: ThrowAnalyzer(lane.lane_id, cfg, lane.display_number)
            for lane in calibration.lanes
        }
        # Wacht darueber, dass die Lampen ueberhaupt noch etwas melden.
        # Ein Lauf, bei dem sie stumm bleiben, waehrend die Tafel Kegel
        # zeigt, ist kein Spielverlauf -- siehe lamp_watchdog.py.
        self.lamp_watchdog = LampWatchdog(
            threshold=cfg.detection.lamps.silent_failure_after)
        self._prepared = False

    @property
    def lane_count(self) -> int:
        return len(self.processors)

    def prepare(self, frame_shape: tuple[int, ...]) -> list[int]:
        """Bereitet alle Bahnen vor. Liefert die IDs der nutzbaren Bahnen.

        Eine unbrauchbar kalibrierte Bahn wird uebersprungen, statt die gesamte
        Analyse zu verhindern -- die anderen drei sollen trotzdem laufen (P8).
        """
        usable: list[int] = []
        for processor in self.processors:
            if processor.prepare(frame_shape):
                usable.append(processor.lane_id)
        self.processors = [p for p in self.processors if p.lane_id in usable]
        self._prepared = bool(self.processors)

        if not self._prepared:
            log.error("Keine einzige Bahn ist nutzbar -- Analyse nicht moeglich")

        # Die Tafelbereiche sind Schutzzonen: Dort wird gemessen, aber NIE
        # geschwaerzt. Ziffern und Lampen aendern sich staendig und sind damit
        # selbst bewegter Vordergrund -- wer sie schwaerzt, loescht das Signal.
        self.person_maske.set_tafeln(
            {p.display_number: p.lane_box() for p in self.processors})
        for processor in self.processors:
            processor.setze_personenmodell(self.personen_modell)
        self.personen_modell.setze_tafeln(
            {p.display_number: p.lane_box() for p in self.processors},
            frame_shape)
        if self.person_maske.enabled:
            log.info("Personenmaske aktiv: %d Tafeln geschuetzt, Verdeckung ab "
                     "Vordergrundanteil %.2f", len(self.processors),
                     self.person_maske.occlusion_fraction)
        else:
            log.warning("Personenmaske ist ABGESCHALTET -- Menschen werden "
                        "nicht geschwaerzt, und eine verdeckte Tafel kann "
                        "einen Wurf erfinden.")
        return usable

    def uebernimm_kalibrierung(self, neue: Calibration,
                               frame_shape: tuple[int, ...]) -> list[int]:
        """Nimmt im LAUFENDEN Betrieb nachgezogene Bereiche entgegen.

        Die Bahnen behalten ihren Zustand -- getauscht werden nur die Bereiche
        und die daraus gerechneten Rechtecke. Siehe
        `LaneProcessor.uebernimm_kalibrierung`.

        Bahnen, die in der neuen Kalibrierung fehlen, bleiben unveraendert
        stehen: Eine laufende Analyse darf an einer Nachjustierung nicht
        stillschweigend Bahnen verlieren (P8).
        """
        # Ein ANDERES Anlagenprofil wird NICHT uebernommen. Die Schwellen der
        # Lampenerkennung sind zur Laufzeit eingelernt; sie mitten im Spiel zu
        # tauschen hiesse, mit halb gelernten Wolken weiterzumessen. Wer die
        # Anlage wechselt, startet die Analyse neu.
        if neue.anlage.gesetzt != self.calibration.anlage.gesetzt:
            log.warning("Die neue Kalibrierung bringt ein anderes "
                        "Anlagenprofil mit (%s) -- es gilt weiter das alte. "
                        "Fuer einen Wechsel die Analyse neu starten.",
                        neue.anlage.gesetzt)
        neue_bahnen = {bahn.lane_id: bahn for bahn in neue.lanes}
        betroffen: list[int] = []
        for processor in self.processors:
            bahn = neue_bahnen.get(processor.lane_id)
            if bahn is None:
                continue
            if processor.uebernimm_kalibrierung(bahn, frame_shape):
                betroffen.append(processor.lane_id)
        self.calibration = neue
        # Die Schutzzonen der Personenmaske haengen an den Tafelecken und
        # muessen mitwandern -- sonst schwaerzt sie in die Tafel hinein.
        self.person_maske.set_tafeln(
            {p.display_number: p.lane_box() for p in self.processors})
        # Das Suchband haengt genauso an den Tafelecken wie die Schutzzonen.
        self.personen_modell.setze_tafeln(
            {p.display_number: p.lane_box() for p in self.processors},
            frame_shape)
        return betroffen

    def process(self, frame: Frame) -> FrameResult:
        """Verarbeitet einen Frame ueber alle Bahnen."""
        started = time.perf_counter()
        result = FrameResult(frame_index=frame.index, timestamp=frame.timestamp)

        # ZUERST MASKIEREN, DANN AUSWERTEN. Was danach kommt -- Gruenlampe,
        # Ziffern, Tafelbilder, Ringpuffer -- sieht nur noch das geschwaerzte
        # Bild. So kann kein Gesicht in ein Debugbild oder in die Datenbank
        # geraten, und keine durchlaufende Person einen Wurf erfinden.
        # Das UNGESCHWAERZTE Bild fuer das Personenmodell festhalten, BEVOR
        # maskiert wird. Die Maske schwaerzt alles ausserhalb der Tafeln --
        # also genau den Rumpf, an dem das Netz einen Menschen erkennt.
        roh = frame.image
        self.personen_modell.merke(roh, frame.index)
        for processor in self.processors:
            processor.setze_rohbild(roh)

        maskiert = self.person_maske.verarbeite(frame.image)
        if maskiert.bild is not frame.image:
            frame = replace(frame, image=maskiert.bild)

        for processor in self.processors:
            verdeckt = processor.display_number in maskiert.verdeckte_bahnen
            processor.setze_verdeckung(verdeckt)
            # Einmal melden, nicht in jedem Frame -- sonst ist das Log voll.
            if verdeckt and processor.display_number not in self._verdeckt_gemeldet:
                self._verdeckt_gemeldet.add(processor.display_number)
                log.info("Bahn %d: Personenmaske sieht die Tafel verdeckt "
                         "(Frame %d, Vordergrund %.2f) -- Auswertung ausgesetzt",
                         processor.display_number, frame.index,
                         maskiert.verdeckung.get(processor.display_number, 0.0))
            elif not verdeckt:
                self._verdeckt_gemeldet.discard(processor.display_number)

        self.buffer.append(frame)

        for processor in self.processors:
            try:
                observation, event, sample = processor.process(frame, self.buffer)
                # Jeden Messwert festhalten: Ohne die Frames VOR einem Ereignis
                # laesst sich nicht klaeren, warum es ausgeloest hat.
                self.green_trace.add(frame.index, frame.timestamp,
                                     processor.display_number, observation.green)
            except Exception as exc:  # noqa: BLE001
                # Ein Fehler auf einer Bahn darf die anderen drei nicht stoppen
                # (Prinzip P6/P8). Bewusst breit gefangen: Welche Ausnahme ein
                # Detektor kuenftig wirft, ist nicht vorhersehbar -- die Analyse
                # eines mehrstuendigen Videos darf daran nicht scheitern.
                log.exception("Bahn %d: Fehler bei Frame %d: %s",
                              processor.display_number, frame.index, exc)
                continue

            result.observations.append(observation)
            if event is not None:
                result.events.append(event)

            # Wuerfe ohne Kegel kommen NICHT aus dem Gruenzyklus -- bei ihnen
            # schaltet die Anlage die gruene Lampe gar nicht aus (Q10). Sie
            # werden vom Fehlwurfzaehler gemeldet und hier eingereiht, damit
            # sie denselben Weg gehen wie jeder andere Wurf: Tabelle, Versand,
            # Protokoll.
            for frame_index, timestamp, wurfnummer, tafelbild in                     processor.take_zero_throws():
                # Nach lane_id, nicht nach display_number -- so ist das
                # Verzeichnis angelegt (siehe __init__).
                analyzer = self.analyzers.get(processor.lane_id)
                if analyzer is None:
                    continue
                try:
                    leerwurf = analyzer.analyze_zero_throw(
                        frame_index, timestamp, wurfnummer)
                except Exception as exc:  # noqa: BLE001
                    log.exception("Bahn %d: Nullwurf nicht buchbar: %s",
                                  processor.display_number, exc)
                    continue
                leerwurf = replace(leerwurf, board_image=tafelbild)
                result.throws.append(leerwurf)
                self.throw_log.add(leerwurf)
                self.cycle_sheet.add(leerwurf)
                processor.throw_count = leerwurf.throw_number
                processor.running_total = leerwurf.running_total
                observation.throw_count = leerwurf.throw_number
                observation.running_total = leerwurf.running_total
            if sample is not None:
                result.samples.append(sample)
                throw = self._evaluate_sample(processor, sample)
                if throw is not None:
                    throw = replace(
                        throw,
                        board_image=self._tafelbild(processor, sample),
                        board_image_before=processor.board_before)
                    result.throws.append(throw)
                    self.throw_log.add(throw)
                    if self.gegenprobe is not None:
                        befund = self.gegenprobe.nimm(
                            throw,
                            self._summenlesung.get(processor.display_number))
                        if befund is not None and befund.urteil in MELDENSWERT:
                            # Nur die Faelle melden, die etwas ueber das
                            # ERGEBNIS sagen. "Ziffer falsch" ist haeufig und
                            # folgenlos -- im Protokoll waere es Rauschen.
                            log.warning("Bahn %d Wurf %d: %s (%s)",
                                        befund.bahn, befund.wurf,
                                        befund.urteil, befund.bemerkung)
                    self.cycle_sheet.add(throw)
                    self.lamp_watchdog.observe_and_log(throw)
                    # Anzeigewerte des Prozessors nachziehen -- gebucht wird
                    # allein im Analyzer, angezeigt wird ueber die Observation.
                    processor.throw_count = throw.throw_number
                    processor.running_total = throw.running_total
                    observation.throw_count = throw.throw_number
                    observation.running_total = throw.running_total
                self._save_sample(processor, sample, throw)

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        result.processing_ms = elapsed_ms
        self.performance.record(elapsed_ms)
        return result

    def _tafelbild(self, processor: LaneProcessor,
                   sample: SampleEvent) -> str | None:
        """Die Anzeigetafel im Ausloeser-Frame des Wurfs.

        Genommen wird der GREEN_OFF-Frame -- derselbe, aus dem das Ergebnis
        stammt. Ein spaeterer Frame zeigte womoeglich schon die naechste
        Aufstellung.
        """
        if not sample.frames:
            return None
        # NICHT stur den Ausloeser: Die Anlage laesst die Kegellampen nach
        # einem hohen Ergebnis blinken. GEMESSEN am 2026-09-07 (Bahn 1,
        # Ereignis 7, Wurf 20, neun Kegel): fuenf von zehn Frames voellig
        # dunkel. Genommen wird der Frame mit den hellsten Lampen -- ein
        # echtes Bild, keine Montage.
        ausloeser = next(
            (f for f in sample.frames if f.role is FrameRole.GREEN_OFF),
            sample.frames[0])
        kandidaten = [ausloeser] + [f for f in sample.frames if f is not ausloeser]
        bester = pick_board_frame(kandidaten, processor.lamp_boxes,
                                  bild_von=lambda f: f.frame.image)
        gewaehlt = (bester or ausloeser).frame
        # MENSCHEN AUCH IM TAFELAUSSCHNITT SCHWAERZEN. Der Ausschnitt ist der
        # einzige Teil des Bildes, den die Personenmaske ausspart -- und genau
        # er geht an die Datenbank und in den Liveticker (Befund des Nutzers,
        # 2026-09-13).
        return encode_board(gewaehlt.image, processor.lane_box(),
                            self.cfg.output.board_image_quality,
                            processor.fremdmaske(gewaehlt.image, gewaehlt.index))

    def _aggregate_pins(self, processor: LaneProcessor,
                        sample: SampleEvent) -> PinLampReading | None:
        """Fasst die Kegellampen ueber ALLE Frames des Ereignisses zusammen.

        GEMESSEN und ueberraschend: **Die Kegellampen der Anlage blinken.**
        Ueber 100 Frames eines Wurfs sprang die Anzeige mehrfach zwischen
        8 Lampen und 0 Lampen, waehrend die Ziffer konstant "8" zeigte:

            Frame 5800: 8 Lampen    Frame 5840: 0 Lampen
            Frame 5824: 8 Lampen    Frame 5844: 0 Lampen   <- hier wurde gemessen
            Frame 5852: 8 Lampen    Frame 5868: 0 Lampen

        Ein einzelner Messzeitpunkt ist damit reiner Zufall. Deshalb gilt eine
        Lampe als gefallen, wenn sie in **mindestens einem** Frame des
        Ereignisses geleuchtet hat: Eine Lampe kann waehrend des Blinkens
        faelschlich dunkel erscheinen, aber nicht faelschlich leuchten.
        """
        frames = sample.sorted_frames()
        if not frames:
            return processor.result_pins

        # BEI GRUEN-AUS IST DIE ZAEHLUNG FERTIG. Nutzer, 2026-09-28: *„sobald
        # Grünaus geht, müssen wir fertig sein mit unserer Zählung."*
        #
        # Die Abtastframes beginnen beim Gruen-AUS und reichen rund 40 Frames
        # darueber hinaus. Sie sind fuer die ZIFFERN da, die spaet nachziehen.
        # Die Lampen sind da laengst fertig -- und genau dort beginnt ein
        # Fehlercode der Tafel (BUG-036, gemessen sieben Frames nach Gruen-AUS).
        # Die Vereinigung nahm dessen Lampen mit ins Ergebnis: Auf Bahn 4
        # wurden daraus zweimal alle neun Kegel, wo die Tafel 7 zaehlte.
        ausloeser = next((f for f in frames
                          if f.role is FrameRole.GREEN_OFF), None)
        grenze = ausloeser.frame.index if ausloeser else sample.trigger_frame

        # Die Frames des Samplings decken nur rund 10 Frames ab -- zu wenig
        # gegen eine Dunkelphase von bis zu 15. Deshalb kommen die ueber das
        # ganze Ereignisfenster gesammelten Messungen des Prozessors hinzu.
        messungen: list[PinLampReading] = list(processor.result_samples)
        # Die Messungen nach Gruen-AUS aus BEIDEN Quellen in EINE Folge --
        # sonst entscheidet jede fuer sich, und die Lampen der einen landen
        # im Ergebnis, waehrend die andere den Fehlercode meldet.
        nach: list[PinLampReading] = list(processor.nach_samples)
        for sampled in frames:
            reading = processor.read_pin_lamps_at(sampled.frame)
            if reading is None:
                continue
            if sampled.frame.index > grenze:
                nach.append(reading)
            else:
                messungen.append(reading)

        # WAS NACH GRUEN-AUS KOMMT, IST ZWEIERLEI. Entweder der Jubel-Effekt
        # (alle Neune, 8er Kranz) -- dann sind diese Frames noetig, weil eine
        # Lampe sonst in ihrer Dunkelphase fehlt; ohne sie fiel die
        # Trefferquote ueber 42 Minuten von 97,8 auf 94,1 Prozent, und zwar
        # jedes Mal ZU NIEDRIG. Oder ein FEHLERCODE der Tafel, und dann
        # leuchten dort Lampen, die keinen gefallenen Kegel meinen (BUG-036).
        #
        # Beide beginnen nach Gruen-AUS und sind nur an ihrer FORM zu
        # trennen: Beim Jubel blinkt alles, was leuchtet; beim Fehlercode
        # leuchtet ein Teil fest, waehrend der andere blinkt.
        blinkende = self.cfg.sampling.error_code_min_blinking_lamps
        if nach and not ist_fehlercode(nach, mindest_blinkende=blinkende):
            messungen += nach
        elif nach:
            log.info("Bahn %d: Fehlercode nach Gruen-AUS bei Frame %d -- "
                     "diese %d Messungen zaehlen nicht zum Wurf",
                     processor.display_number, grenze, len(nach))
        ergebnis = aggregate_pin_readings(messungen) or processor.result_pins
        # DER ENDSTAND IST DIE GRUNDLINIE DES NAECHSTEN WURFS. Erst hier steht
        # er vollstaendig fest: Bei blinkender Anzeige fehlt in jeder
        # einzelnen Messung etwas, erst die Vereinigung ist der Stand.
        processor.uebernimm_vorstand(ergebnis)
        return ergebnis

    def finalize(self, last_frame: Frame | None) -> list[ThrowResult]:
        """Wertet Wurffenster aus, die beim Ende der Quelle noch offen waren.

        Ein Wurf wird normalerweise erst beim NAECHSTEN Gruen-AN gemeldet: Erst
        dann steht fest, dass das Fenster zu Ende ist. Endet das Video vorher,
        geht dieser Wurf ersatzlos verloren.

        GEMESSEN gegen das handgefuehrte Wurfprotokoll: Genau vier Wuerfe
        fehlten, einer je Bahn -- und zwar jedes Mal der DREISSIGSTE und damit
        letzte des Videos (Bahn 2: 6 Kegel, Bahn 3: 2, Bahn 4: 7, Bahn 5: 7).
        Die Satzergebnisse stimmten sonst auf allen vier Bahnen exakt; die
        gesamte verbliebene Abweichung des vierten Satzes bestand aus diesen
        vier Wuerfen.

        Bei einem Livestream faellt das nicht ins Gewicht -- dort kommt das
        naechste Gruen-AN. Bei der Auswertung einer Datei ist es der Unterschied
        zwischen einem vollstaendigen und einem abgeschnittenen Spiel.

        Sicher ist das, weil das ERGEBNIS bereits bei Gruen-AUS gemessen wurde:
        Ein offenes Fenster bedeutet, dass die gruene Lampe aus ist und die
        Kegel liegen. Laeuft die gruene Lampe beim Ende noch, ist gar kein
        Fenster offen und es gibt nichts abzuschliessen.
        """
        if last_frame is None:
            return []
        nachzuegler: list[ThrowResult] = []
        for processor in self.processors:
            offen = processor.sampler.open_event
            if offen is None:
                continue
            # Dieselbe Flackersperre wie im laufenden Betrieb: Ein Fenster, das
            # kurz vor Schluss aufging, ist kein belegter Wurf.
            mindest = self.cfg.state_machine.min_throw_frames
            if mindest > 0 and last_frame.index - offen.trigger_frame < mindest:
                log.info("Bahn %d: offenes Fenster bei Frame %d war nur %d Frames "
                         "lang -- nicht als Wurf gewertet",
                         processor.display_number, offen.trigger_frame,
                         last_frame.index - offen.trigger_frame)
                processor.sampler.abort("Quelle endet, Fenster zu kurz")
                continue
            sample = processor.sampler.finish(last_frame, self.buffer)
            if sample is None:
                continue
            # Kein Weiterreichen des Spielwechsel-Zeichens: Die Quelle ist zu
            # Ende, ein naechster Wurf kommt nicht mehr.
            throw = self._evaluate_sample(processor, sample)
            if throw is not None:
                log.info("Bahn %d: letzter Wurf beim Ende der Quelle "
                         "nachgetragen -- %d Kegel", processor.display_number,
                         throw.pins_count)
                nachzuegler.append(throw)
                self.throw_log.add(throw)
                self.cycle_sheet.add(throw)
            self._save_sample(processor, sample, throw)
        return nachzuegler

    def close(self) -> None:
        """Schliesst offene Debug-Ausgaben. Mehrfachaufruf ist harmlos."""
        self.throw_sheet.close()
        self.green_trace.close()
        self.lamp_trace.close()
        self.throw_log.close()
        self.cycle_sheet.close()
        self._schreibe_gegenprobe()

    def _schreibe_gegenprobe(self) -> None:
        """Legt die Gegenprobe als Tabelle ab und meldet die Bilanz.

        Ins PROTOKOLL kommt die Zusammenfassung, nicht jede Zeile: Die
        interessante Zahl ist, wie oft zwei unabhaengige Quellen gemeinsam
        einem gebuchten Ergebnis widersprochen haben.
        """
        if self.gegenprobe is None or not self.gegenprobe.befunde:
            return
        import csv

        ziel = self.frame_logger.root / "gegenprobe.csv"
        try:
            zeilen = [b.als_zeile() for b in self.gegenprobe.befunde]
            with ziel.open("w", newline="", encoding="utf-8") as datei:
                schreiber = csv.DictWriter(datei, fieldnames=list(zeilen[0]),
                                           delimiter=";")
                schreiber.writeheader()
                schreiber.writerows(zeilen)
        except OSError as exc:
            # Eine nicht schreibbare Debug-Datei darf einen fertigen Lauf
            # nicht nachtraeglich zum Fehlschlag machen (P8).
            log.warning("Gegenprobe nicht geschrieben: %s", exc)
        else:
            log.info("Gegenprobe: %s", ziel)
        for zeile in self.gegenprobe.bericht().splitlines():
            log.info("%s", zeile)

    def _plausible_digits(self, haeufigkeit: "Counter[int]",
                          frames: int) -> tuple[int, ...]:
        """Welche Kegelzahlen hielt der Ziffernleser ueber das Ereignis fuer moeglich?

        Ein Wert zaehlt, wenn er in einem nennenswerten Teil der Frames unter den
        Kandidaten stand. Ein einzelner Ausreisser soll die Menge nicht aufblaehen
        -- sonst waere am Ende jeder Lampenwert "plausibel" und die Gegenprobe
        wertlos.
        """
        if frames <= 0:
            return ()
        mindestens = max(1, int(frames * self.cfg.detection.digits.min_digit_agreement))
        return tuple(sorted(wert for wert, n in haeufigkeit.items()
                            if n >= mindestens))

    def _evaluate_sample(self, processor: LaneProcessor,
                         sample: SampleEvent) -> ThrowResult | None:
        """Wertet ein abgeschlossenes Ereignis zu einem Wurfergebnis aus.

        Die Ziffernfelder werden ueber ALLE Frames des Ereignisses aggregiert --
        ein einzelnes Leseergebnis wird nie uebernommen (Auftrag Paragraph 8).
        """
        analyzer = self.analyzers.get(processor.lane_id)
        if analyzer is None:
            return None

        # STELLENWEISE abstimmen, nicht ueber den Gesamtwert.
        #
        # GEMESSEN an einer 40 Frames lang unveraenderten Anzeige ("0040"): Drei
        # Stellen waren vollkommen eindeutig, eine schwankte zwischen '4' und '9'
        # (auf dieser Anlage nur EIN Segment Unterschied, BUG-009). Ueber den
        # Gesamtwert abgestimmt riss diese eine Stelle die ganze Summe mit --
        # deshalb blieb die Summe bei vielen Wuerfen unlesbar, und damit fehlte
        # die einzige von den Lampen unabhaengige Gegenprobe.
        # Beim ersten Ereignis dieser Bahn die Ziffernrahmen einmalig
        # feinausrichten -- danach ist es ein reiner Lesevorgang.
        try:
            processor.refine_digit_boxes([s.frame for s in sample.sorted_frames()])
        except Exception as exc:  # noqa: BLE001
            log.warning("Bahn %d: Feinausrichtung der Ziffern fehlgeschlagen: %s",
                        processor.display_number, exc)

        felder: dict[str, FieldAggregator] = {}
        # Kandidaten der Kegelzahl: Wo die Ziffer zwischen zwei Werten schwankt,
        # kann die Lampenzaehlung sie aufloesen -- ohne dass die Gegenprobe
        # dadurch wertlos wird (siehe throw_analyzer).
        # Gezaehlt wird JEDER Wert, den der Leser in einem Frame fuer moeglich
        # hielt -- nicht nur die Faelle, in denen er sich nicht entscheiden
        # konnte. GEMESSEN: Bei fuenf von vierzehn Widerspruechen stand der
        # Lampenwert in den Frame-Kandidaten, waehrend die Mehrheitsabstimmung
        # auf einen anderen Wert fiel. Die Information zum Aufloesen war also
        # vorhanden und ging beim Zusammenfassen verloren.
        kandidaten_zaehler: Counter[int] = Counter()
        kandidaten_frames = 0
        for sampled in sample.sorted_frames():
            try:
                readings = processor.read_digits(sampled.frame)
            except Exception as exc:  # noqa: BLE001
                # Ziffern sind Gegenprobe, kein Muss -- ein Fehler hier darf den
                # Wurf nicht verhindern, der aus den Lampen bereits feststeht.
                log.warning("Bahn %d: Ziffern in Frame %d nicht lesbar: %s",
                            processor.display_number, sampled.index, exc)
                continue
            pin = readings.get("pin_count")
            if pin is not None and pin.candidates and pin.candidates[0]:
                kandidaten_frames += 1
                for wert in pin.candidates[0]:
                    kandidaten_zaehler[wert] += 1

            for name, reading in readings.items():
                if not reading.digits:
                    continue
                # Spaet aktualisierte Felder kommen NICHT aus den Sample-Frames:
                # Dort steht die Summe noch auf dem alten Wert.
                if name in self.cfg.detection.digits.late_fields:
                    continue
                felder.setdefault(name, FieldAggregator(
                    digits=len(reading.digits),
                    min_confidence=self.cfg.detection.digits.min_confidence,
                    min_agreement=self.cfg.detection.digits.min_digit_agreement,
                )).add(reading.digits, reading.scores, sampled.index)

        # Die spaet aktualisierten Felder aus den Mitlesungen des Fensters
        for name, messungen in processor.late_samples.items():
            for reading in messungen:
                if not reading.digits:
                    continue
                felder.setdefault(name, FieldAggregator(
                    digits=len(reading.digits),
                    min_confidence=self.cfg.detection.digits.min_confidence,
                    min_agreement=self.cfg.detection.digits.min_digit_agreement,
                )).add(reading.digits, reading.scores)

        def value_of(name: str) -> int | None:
            aggregator = felder.get(name)
            return aggregator.result()[0] if aggregator else None

        def confidence_of(name: str) -> float:
            """Wie SICHER die Ziffernerkennung des Feldes war.

            ACHTUNG (BUG-020): Das ist NICHT die zeitliche Einigkeit, auch
            wenn der Name das nahelegt -- es ist die Bildguete der
            schwaechsten Stelle. Fuer die Einigkeit gibt es `mehrheit_von`.
            """
            aggregator = felder.get(name)
            return aggregator.result()[1] if aggregator else 0.0

        def mehrheit_von(name: str, ignoriere_fuehrende: int = 0):
            """(Mehrheitswert, zeitliche Einigkeit) -- ohne Confidence-Schwelle."""
            aggregator = felder.get(name)
            if aggregator is None:
                return None, 0.0
            return aggregator.mehrheit(ignoriere_fuehrende)

        if self.gegenprobe is not None:
            summenfeld = felder.get("total_b")
            self._summenlesung[processor.display_number] = (
                summenfeld.als_lesung() if summenfeld is not None else None)

        try:
            return analyzer.analyze(
                sample,
                pins=self._aggregate_pins(processor, sample),
                baseline=processor.baseline_pins,
                displayed_count=value_of("pin_count"),
                displayed_candidates=self._plausible_digits(
                    kandidaten_zaehler, kandidaten_frames),
                throw_number=value_of("throw_number"),
                throw_number_confidence=confidence_of("throw_number"),
                displayed_total=value_of("total_b"),
                foul_count=value_of("left_display"),
                display_reset=processor.reset_pending,
                window_was_occluded=processor.window_was_occluded,
                throw_number_majority=mehrheit_von(
                    "throw_number",
                    self.cfg.scoring.throw_number_ignore_leading),
                # OHNE `ignoriere_fuehrende`: Bei der Summe sind fuehrende
                # Nullen bedeutungstragend. Wuerde man sie weglassen, waere
                # eine Summe von 100 ("0100") an den hinteren Stellen von
                # einer echten Null nicht mehr zu unterscheiden.
                total_majority=mehrheit_von("total_b"),
            )
        except ValueError as exc:
            # Etwa: Wurfnummer nicht groesser als die zuletzt gebuchte
            log.warning("Bahn %d: Wurf nicht buchbar: %s", processor.display_number, exc)
            return None

    def _save_sample(self, processor: LaneProcessor, sample: SampleEvent,
                     throw: ThrowResult | None = None) -> None:
        """Legt die Frames eines abgeschlossenen Ereignisses im Debug-Ordner ab.

        Ein Fehler beim Speichern darf die Analyse nicht stoppen -- Debug-Ausgabe
        ist wichtig, aber nicht wichtiger als der Analyselauf selbst.
        """
        try:
            pins = processor.result_pins
            self.frame_logger.save_event(
                sample,
                roi_boxes=processor.roi_boxes(),
                lane_box=processor.lane_box(),
                metadata={
                    "display_number": processor.display_number,
                    "pins": pins.to_dict() if pins is not None else None,
                    "throw": throw.to_dict() if throw is not None else None,
                },
                failed=(throw is None),
            )
            if throw is not None and sample.frames:
                self._save_throw_sheet(processor, sample, throw)
        except OSError as exc:
            log.warning("Bahn %d: Debug-Ereignis konnte nicht gespeichert werden: %s",
                        processor.display_number, exc)

    def _save_throw_sheet(self, processor: LaneProcessor, sample: SampleEvent,
                          throw: ThrowResult) -> None:
        """Legt das Belegbild zu einem Wurf ab.

        DER LETZTE Frame des Fensters: Dort steht das Ergebnis vollstaendig auf
        der Tafel. Frueher fehlen Lampen, die noch fallen; spaeter kann die
        Anlage schon geloescht haben.
        """
        letzter = sample.frames[-1]
        warped = processor.warped_board(letzter.frame.image)
        if warped is None:
            return
        self.throw_sheet.add(throw, warped, processor.lane.rois,
                             letzter.index, letzter.timestamp)

    def reset(self) -> None:
        for processor in self.processors:
            processor.reset()
        for analyzer in self.analyzers.values():
            analyzer.reset()
        self.buffer.clear()
        self.performance = PerformanceMonitor()
