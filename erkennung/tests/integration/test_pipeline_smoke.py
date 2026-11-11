"""Ein vollstaendiger Durchlauf der Pipeline mit synthetischen Frames.

WARUM ES DIESEN TEST GIBT: Beim Umbau der Raeum-Grundlinie wurden versehentlich
drei Methoden mit entfernt (`_read_late_fields`, `late_samples`). Die gesamte
Unit-Suite blieb gruen -- sie prueft die Bausteine einzeln, nie ihr
Zusammenspiel. Aufgefallen ist es erst im 13-Minuten-Lauf ueber das echte Video.

Dieser Test durchlaeuft denselben Pfad in Sekunden: gruen an, Kegel fallen,
gruen aus, naechster Wurf. Er prueft nicht die Erkennungsguete -- dafuer sind
die Unit-Tests und die Messungen am Material da -- sondern nur, dass der Weg
vom Frame zum Wurfergebnis durchgaengig begehbar ist.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.analysis.pipeline import AnalysisPipeline
from kegel_cv.calibration.model import Calibration, LaneCalibration, Roi
from kegel_cv.config import AppConfig
from kegel_cv.video.source import Frame

BREITE, HOEHE = 320, 240


def kalibrierung() -> Calibration:
    """Eine Bahn mit gruener Lampe, neun Kegellampen und Ziffernfeldern."""
    rois = [Roi(name="green_lamp", rect=(0.45, 0.80, 0.10, 0.08))]
    for i in range(1, 10):
        spalte, zeile = (i - 1) % 3, (i - 1) // 3
        rois.append(Roi(name=f"pin_lamp_{i}", pin_number=i,
                        rect=(0.20 + spalte * 0.25, 0.20 + zeile * 0.15, 0.08, 0.08)))
    for name, stellen, y in (("throw_number", 3, 0.90),
                             ("pin_count", 1, 0.90),
                             ("total_b", 4, 0.95)):
        for k in range(1, stellen + 1):
            rois.append(Roi(name=f"digit_{name}_{k}",
                            rect=(0.05 + k * 0.08, y, 0.06, 0.04)))

    cal = Calibration()
    cal.set_lane(LaneCalibration(
        lane_id=1, real_lane_number=2,
        quad=[[10, 10], [310, 10], [310, 230], [10, 230]],
        rois=rois,
    ))
    return cal


def frame(index: int, gruen: bool, gefallen: int = 0) -> Frame:
    """Baut ein Bild mit gesetzter gruener Lampe und N leuchtenden Kegellampen."""
    bild = np.full((HOEHE, BREITE, 3), 40, dtype=np.uint8)

    # Die gruene Lampe. WICHTIG: "aus" ist NICHT "nichts" -- das beige
    # Tafelgehaeuse hat selbst Gruenanteil, am Material gemessen liegt der
    # AUS-Score bei 17 bis 24, der AN-Score bei 60 bis 74. Ein Score nahe null
    # bedeutet, dass die Tafel VERDECKT ist (jemand steht davor), und wird
    # inzwischen als solche behandelt. Ohne Grundhelligkeit hier waere jeder
    # "gruen aus"-Abschnitt dieser Probe eine Verdeckung.
    if gruen:
        bild[190:210, 140:175] = (40, 230, 40)      # kraeftig und gesaettigt
    else:
        # Rund ein Fuenftel der Flaeche gruen -- entspricht dem gemessenen
        # AUS-Niveau des Gehaeuses.
        bild[190:210, 140:175] = (40, 60, 40)
        bild[190:194, 140:175] = (40, 230, 40)

    for i in range(gefallen):
        spalte, zeile = i % 3, i // 3
        x = 10 + int((0.20 + spalte * 0.25) * 300)
        y = 10 + int((0.20 + zeile * 0.15) * 220)
        # BGR. Die Lampe muss nicht nur HELL, sondern auch WARM sein: Der
        # Detektor verlangt Farbwaerme als Schutz gegen helle, aber farblose
        # Reflexe (`detection.lamps.warmth_min`). Vorher stand hier ein
        # kaltweisses (250, 252, 255) -- Helligkeit 255, Waerme knapp null.
        # Saemtliche Lampen wurden dadurch UNKNOWN, und diese Probe hat den
        # Weg vom Frame zur KEGELZAHL nie geprueft, sondern nur bis zum Wurf.
        bild[y:y + 18, x:x + 24] = (60, 190, 255)
    return Frame(index, index / 25.0, bild)


@pytest.fixture
def pipeline() -> AnalysisPipeline:
    pipe = AnalysisPipeline(kalibrierung(), AppConfig(), video_id="smoke")
    pipe.cfg.debug.save_frames = False
    pipe.prepare((HOEHE, BREITE, 3))
    return pipe


class TestDurchlauf:
    def test_ein_wurf_laeuft_vollstaendig_durch(self, pipeline):
        """Gruen an -> Kegel fallen -> gruen aus -> gruen an: ein Wurfergebnis."""
        wuerfe = []
        index = 0

        def lauf(anzahl: int, gruen: bool, gefallen: int = 0) -> None:
            nonlocal index
            for _ in range(anzahl):
                wuerfe.extend(pipeline.process(frame(index, gruen, gefallen)).throws)
                index += 1

        # Die Dauern entsprechen dem gemessenen Material: Ein Wurffenster
        # (GREEN_OFF bis zum naechsten GREEN_ON) dauert im Mittel 251 Frames.
        lauf(40, gruen=True)                      # Bahn frei, Kegel stehen
        lauf(60, gruen=True, gefallen=6)          # Kegel fallen waehrend gruen
        lauf(200, gruen=False, gefallen=6)        # gruen aus: Ergebnis steht
        lauf(40, gruen=True)                      # naechster Wurf beginnt

        assert wuerfe, "der Wurf muss die Pipeline durchlaufen haben"
        assert wuerfe[0].pins_count == 6, (
            "sechs Lampen leuchteten -- der Weg vom Frame bis zur KEGELZAHL "
            "muss durchgaengig sein, nicht nur bis zum Wurf"
        )
        assert wuerfe[0].lane == 2, "die angezeigte Bahnnummer muss durchgereicht werden"
        assert wuerfe[0].throw_number == 1
        assert wuerfe[0].evidence.frames, "die Beweiskette darf nicht leer sein"

    def test_kein_ereignis_ohne_gruenwechsel(self, pipeline):
        """Ohne Flanke darf nichts gebucht werden -- sonst zaehlte Stillstand."""
        wuerfe = []
        for i in range(120):
            wuerfe.extend(pipeline.process(frame(i, gruen=True)).throws)

        assert wuerfe == []

    def test_alle_vom_prozessor_erwarteten_methoden_existieren(self, pipeline):
        """Billige Absicherung gegen versehentlich entfernte Methoden.

        Genau daran ist der Umbau der Raeum-Grundlinie gescheitert: Die Pipeline
        rief `late_samples` und `_read_late_fields`, beide waren geloescht, und
        keine Unit hat es bemerkt.
        """
        prozessor = pipeline.processors[0]
        for name in ("process", "prepare", "read_digits", "read_pin_lamps_at",
                     "late_samples", "result_samples", "baseline_pins",
                     "lane_box", "refine_digit_boxes"):
            assert hasattr(prozessor, name), f"LaneProcessor.{name} fehlt"


class TestFruehesMelden:
    """Der Wurf wird kurz nach Gruen-AUS gemeldet, nicht erst beim naechsten
    Gruen-AN.

    Vom Nutzer verlangt (2026-08-28): "generell, dass der Wurf frueher erfasst
    ausgegeben wird". GEMESSEN gegen das Wurfprotokoll
    (tools/measure_report_delay.py, 474 Wuerfe):

        ein Frame bei Gruen-AUS          82,7 %
        Maximum ueber die Gruenphase     98,9 %
        ganzes Fenster danach (frueher)  98,5 %
        Gruenphase + 40 Frames           99,4 %

    Gewartet wurde vorher im Mittel 15 Sekunden, beim Spielwechsel bis zu einer
    Minute -- und der letzte Wurf einer Aufnahme ging ganz verloren.
    """

    def _bis_wurf(self, pipeline, gruen_aus_dauer: int = 300) -> tuple[int, int]:
        """Laeuft einen Wurf und liefert (Frame des Gruen-AUS, Frame der Meldung)."""
        index = 0
        gruen_aus = None
        gemeldet = None

        def phase(anzahl: int, gruen: bool, gefallen: int = 0) -> None:
            nonlocal index, gruen_aus, gemeldet
            for _ in range(anzahl):
                ergebnis = pipeline.process(frame(index, gruen, gefallen))
                if gruen_aus is None and not gruen and index > 50:
                    from kegel_cv.detection.state_machine import EventType
                    if any(e.event is EventType.GREEN_OFF for e in ergebnis.events):
                        gruen_aus = index
                if ergebnis.throws and gemeldet is None:
                    gemeldet = index
                index += 1

        phase(40, gruen=True)
        phase(60, gruen=True, gefallen=6)
        phase(gruen_aus_dauer, gruen=False, gefallen=6)
        phase(40, gruen=True)
        return gruen_aus, gemeldet

    def test_meldung_kommt_kurz_nach_gruen_aus(self, pipeline):
        gruen_aus, gemeldet = self._bis_wurf(pipeline)

        assert gruen_aus is not None, "Gruen-AUS muss erkannt werden"
        assert gemeldet is not None, "der Wurf muss gemeldet werden"
        verzug = gemeldet - gruen_aus
        wartezeit = pipeline.cfg.sampling.report_after_green_off
        assert verzug < wartezeit + 20, (
            f"gemeldet {verzug} Frames nach Gruen-AUS -- erwartet rund "
            f"{wartezeit}, nicht erst beim naechsten Gruen-AN (300)"
        )

    def test_altes_verhalten_bleibt_einstellbar(self, pipeline):
        """0 stellt die Meldung beim naechsten Gruen-AN wieder her."""
        pipeline.cfg.sampling.report_after_green_off = 0
        for prozessor in pipeline.processors:
            prozessor.cfg = pipeline.cfg

        gruen_aus, gemeldet = self._bis_wurf(pipeline, gruen_aus_dauer=300)

        assert gemeldet - gruen_aus >= 295, (
            "ohne Wartezeit wird erst beim naechsten Gruen-AN gemeldet"
        )

    def test_gruenphase_traegt_zum_ergebnis_bei(self, pipeline):
        """Kegel, die WAEHREND der Gruenphase leuchten, zaehlen mit.

        Das ist der Kern des Nutzervorschlags: Die Kegel fallen ja gerade dann.
        Hier gehen die Lampen nach Gruen-AUS wieder aus -- wer nur danach misst,
        sieht null.
        """
        index = 0
        wuerfe = []

        def phase(anzahl: int, gruen: bool, gefallen: int = 0) -> None:
            nonlocal index
            for _ in range(anzahl):
                wuerfe.extend(pipeline.process(frame(index, gruen, gefallen)).throws)
                index += 1

        phase(40, gruen=True)
        phase(80, gruen=True, gefallen=7)    # Kegel fallen bei gruener Lampe
        phase(300, gruen=False, gefallen=0)  # danach ist die Anzeige dunkel
        phase(40, gruen=True)

        assert wuerfe, "der Wurf muss gemeldet werden"
        assert wuerfe[0].pins_count == 7, (
            f"7 Kegel leuchteten waehrend der Gruenphase, gemeldet wurden "
            f"{wuerfe[0].pins_count} -- die Gruenphase wird nicht mitgelesen"
        )


class TestVerdeckteTafel:
    """Steht jemand vor der Tafel, darf kein Wurf entstehen.

    GEMESSEN am 52-Minuten-Video: Der Gruen-Score faellt dabei auf exakt null.
    Das ist keine Lampenaussage -- die unbeleuchtete Lampe sitzt auf beigem
    Gehaeuse mit Gruenanteil und liegt bei 17 bis 24. Null heisst, dass die
    Lampe gar nicht im Bild ist.

    Verteilung der niedrigen Scores ueber 52 Minuten:

        Score 0-1   Bahn 2 1044 Frames, Bahn 3 169, Bahn 4 und 5 keine
        Score 2-3   Bahn 2    5 Frames, Bahn 3   8

    Die 1213 Frames liegen in acht Abschnitten von 1 bis 18 Sekunden. Beide
    Phantomwuerfe des Videos fallen exakt in einen davon.
    """

    def _frame_verdeckt(self, index: int, gefallen: int = 0):
        """Wie `frame`, aber die Tafel ist schwarz uebermalt."""
        bild = frame(index, gruen=True, gefallen=gefallen).image.copy()
        bild[:, :] = 8          # jemand steht davor
        return Frame(index, index / 25.0, bild)

    def test_verdeckung_erzeugt_keinen_wurf(self, pipeline):
        """Der beobachtete Fehler: Der Score faellt auf null, die
        Zustandsmaschine liest 'aus' und meldet einen Wurf, den es nie gab."""
        wuerfe = []
        index = 0

        def phase(anzahl: int, bauer) -> None:
            nonlocal index
            for _ in range(anzahl):
                wuerfe.extend(pipeline.process(bauer(index)).throws)
                index += 1

        phase(60, lambda i: frame(i, gruen=True))
        phase(60, lambda i: frame(i, gruen=True, gefallen=5))
        phase(40, self._frame_verdeckt)                 # 1,6 s verdeckt
        phase(120, lambda i: frame(i, gruen=True, gefallen=5))

        assert wuerfe == [], (
            "eine Verdeckung ist kein Gruen-AUS und darf keinen Wurf ergeben"
        )

    def test_nach_der_verdeckung_geht_es_normal_weiter(self, pipeline):
        """Das Einfrieren darf die Bahn nicht dauerhaft lahmlegen."""
        wuerfe = []
        index = 0

        def phase(anzahl: int, bauer) -> None:
            nonlocal index
            for _ in range(anzahl):
                wuerfe.extend(pipeline.process(bauer(index)).throws)
                index += 1

        phase(40, lambda i: frame(i, gruen=True))
        phase(40, self._frame_verdeckt)
        phase(60, lambda i: frame(i, gruen=True, gefallen=6))
        phase(200, lambda i: frame(i, gruen=False, gefallen=6))
        phase(40, lambda i: frame(i, gruen=True))

        assert wuerfe, "nach der Verdeckung muss ein echter Wurf wieder ankommen"
        assert wuerfe[0].pins_count == 6


class TestKurzeFensterZaehlenTrotzdem:
    """Die Fensterlaenge darf NICHT ueber echt oder Flackern entscheiden.

    Diese Klasse haelt eine Korrektur fest. Zuerst stand hier das Gegenteil:
    Fenster unter 100 Frames galten als Flackern, begruendet mit "kuerzestes
    echtes Fenster 158 Frames, unter 100 nur Fehlausloeser".

    Diese Messung war ZIRKULAER. Als "echtes Fenster" galt, was das Werkzeug
    selbst zu einem Wurf gemacht hatte -- die kurzen hatte es bereits verworfen
    und wurden deshalb als Fehlausloeser gezaehlt.

    Das handgefuehrte Wurfprotokoll (2026-08-28) widerlegt es. Auf Bahn 4 im
    vierten Satz verwarf die Sperre drei Fenster von 51, 46 und 44 Frames --
    im Protokoll stehen dort die Wuerfe 22, 24 und 27 mit 2, 2 und 7 Kegeln.

    Damit ueberlappen die Bereiche: echt ab 44 Frames, der Fehlausloeser aus
    BUG-013 war 64 Frames lang. Gegen BUG-013 wirkt
    `detection.green.adaptive_min_span`, nicht die Fensterlaenge.
    """

    def _lauf(self, pipeline, gruen_aus_dauer: int) -> list:
        wuerfe = []
        index = 0

        def phase(anzahl: int, gruen: bool, gefallen: int = 0) -> None:
            nonlocal index
            for _ in range(anzahl):
                wuerfe.extend(pipeline.process(frame(index, gruen, gefallen)).throws)
                index += 1

        phase(40, gruen=True)
        phase(40, gruen=True, gefallen=6)
        phase(gruen_aus_dauer, gruen=False, gefallen=6)
        phase(40, gruen=True)
        return wuerfe

    def test_kurzes_fenster_ergibt_trotzdem_einen_wurf(self, pipeline):
        """44 Frames -- die kuerzeste im Protokoll belegte Pause."""
        assert self._lauf(pipeline, gruen_aus_dauer=44), (
            "ein 44-Frame-Fenster gehoert zu einem echten Wurf (Bahn 4, Satz 4, "
            "Wurf 27 mit 7 Kegeln) -- es darf nicht verworfen werden"
        )

    def test_normales_fenster_ergibt_einen_wurf(self, pipeline):
        assert self._lauf(pipeline, gruen_aus_dauer=200), (
            "ein 200-Frame-Fenster ist ein normaler Wurf"
        )

    def test_sperre_wirkt_nur_bei_spaeter_meldung(self, pipeline):
        """Die Sperre setzt voraus, dass die Pausenlaenge bekannt ist.

        Bei frueher Meldung (`report_after_green_off > 0`) ist der Wurf bereits
        heraus, bevor feststeht, wie lang die Pause war -- die Sperre kann dann
        grundsaetzlich nicht mehr greifen. Sie gehoert deshalb zum alten
        Meldeverhalten und wird nur zusammen mit ihm gesetzt.
        """
        pipeline.cfg.state_machine.min_throw_frames = 100
        pipeline.cfg.sampling.report_after_green_off = 0
        for prozessor in pipeline.processors:
            prozessor.cfg = pipeline.cfg

        assert self._lauf(pipeline, gruen_aus_dauer=44) == []


class TestBug016GrundlinieVorGruen:
    """Faellt ein Kegel WAEHREND der Grundlinienmessung, ging der Wurf verloren.

    Am Material (Spieltag 2026-08-22, Bahn 2, F180615): Der Gruenscore kroch
    langsam durch die Totzone, GREEN_ON wurde 69 Frames zu spaet gemeldet, und
    das Grundlinienfenster rutschte in die Zeit, in der der geraeumte Kegel
    fiel. Grundlinie neun, Ergebnis neun, nichts neu gefallen -- verworfen.

    Fuenf Wuerfe des Spieltags gingen so verloren. Der Nutzer wies auf die
    zweite Quelle hin: Beim Raeumen bleiben die Ergebnislampen an, bis der
    naechste Wurf abgeschlossen ist -- der Stand VOR dem Gruen-AN haengt an
    keiner Erkennung.
    """

    def _raeumwurf(self, pipeline) -> list:
        """Acht Kegel liegen, der neunte faellt sofort nach dem Gruen-AN."""
        wuerfe = []
        index = 0

        def lauf(anzahl: int, gruen: bool, gefallen: int = 0) -> None:
            nonlocal index
            for _ in range(anzahl):
                wuerfe.extend(pipeline.process(frame(index, gruen, gefallen)).throws)
                index += 1

        lauf(40, gruen=True)                    # Bahn frei
        lauf(60, gruen=True, gefallen=8)        # erster Wurf: acht Kegel
        lauf(200, gruen=False, gefallen=8)      # Pause -- hier steht die Acht
        lauf(8, gruen=True, gefallen=8)         # gruen an, noch acht
        lauf(60, gruen=True, gefallen=9)        # der neunte faellt SOFORT,
                                                # mitten ins Grundlinienfenster
        lauf(200, gruen=False, gefallen=9)      # Ergebnis: neun
        lauf(40, gruen=True)
        return wuerfe

    def test_der_raeumwurf_geht_nicht_verloren(self, pipeline):
        wuerfe = self._raeumwurf(pipeline)

        assert len(wuerfe) == 2, (
            "beide Wuerfe muessen gebucht sein -- der zweite ging verloren, "
            "weil die Grundlinie den gerade gefallenen Kegel mitzaehlte"
        )
        assert wuerfe[0].pins_count == 8
        assert wuerfe[1].pins_count == 1, (
            "acht lagen vorher, neun liegen nachher -- also ein neuer Kegel"
        )

    def test_ohne_die_zweite_quelle_geht_er_verloren(self, pipeline):
        """Der Bug selbst, festgehalten: ohne den Stand vor Gruen fehlt er.

        Nicht als Mahnmal, sondern als Beleg, dass dieser Test den Fehler
        wirklich trifft. Faellt er eines Tages um, prueft der Test oben etwas
        anderes als gedacht.
        """
        pipeline.cfg.sampling.baseline_before_green = False
        wuerfe = self._raeumwurf(pipeline)

        assert len(wuerfe) == 1, (
            "ohne die zweite Quelle wird der Raeumwurf als 'nichts veraendert' "
            "verworfen -- genau das ist BUG-016"
        )

    def test_das_aufstellen_bleibt_unberuehrt(self, pipeline):
        """Nach dem Aufstellen loescht die Anlage die Lampen -- vor dem Gruen-AN.

        Der Stand aus der Pause darf dann NICHT in die Grundlinie geraten,
        sonst zaehlte der naechste Wurf zu wenige Kegel. Die Schnittmenge
        erledigt das von selbst: Was nachher nicht liegt, liegt nicht.
        """
        wuerfe = []
        index = 0

        def lauf(anzahl: int, gruen: bool, gefallen: int = 0) -> None:
            nonlocal index
            for _ in range(anzahl):
                wuerfe.extend(pipeline.process(frame(index, gruen, gefallen)).throws)
                index += 1

        lauf(40, gruen=True)
        lauf(60, gruen=True, gefallen=8)        # erster Wurf: acht
        lauf(150, gruen=False, gefallen=8)      # Pause mit acht Lampen
        lauf(50, gruen=False, gefallen=0)       # aufgestellt: Lampen geloescht
        lauf(30, gruen=True, gefallen=0)        # gruen an, der Ball rollt noch
        lauf(60, gruen=True, gefallen=6)        # dann fallen sechs
        lauf(200, gruen=False, gefallen=6)
        lauf(40, gruen=True)

        assert len(wuerfe) == 2
        assert wuerfe[1].pins_count == 6, (
            "nach dem Aufstellen ist die Grundlinie leer -- alle sechs Kegel "
            "gehoeren zu diesem Wurf"
        )
