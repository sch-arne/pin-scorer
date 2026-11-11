"""Hauptfenster.

Phase 1 (Videoplayer) und Phase 2/3 (Kalibrierung, ROI-Konfiguration).
Die Ergebnistabellen sind als Platzhalter angelegt und werden in Phase 10 gefuellt.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QInputDialog,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..calibration import Calibration, list_calibrations
from .boardtype_dialog import (TafeltypDialog, TrefferDialog,
                               zeichne_treffer)
from ..calibration.geometry import GeometryError
from ..calibration.session import (
    CalibrationSession,
    CalibrationStep,
    GuideStep,
    roi_label,
    single_roi_choices,
)
from ..analysis.calibration_check import CheckVerdict, check_calibration
from ..analysis.pipeline import FrameResult
from ..config.schema import AppConfig
from ..detection.state_machine import EventType
from ..models.quellen import ohne_zugangsdaten
from ..video import (Frame, VideoInfo, is_stream, ist_youtube,
                     list_videos, open_source)
from ..video.file_source import FileVideoSource
from ..video.source import VideoSourceError
from .analysis_worker import SPRUNG_LAEUFT, AnalysisWorker
from .lane_panel import LanePanel
from .player import VideoPlayer
from .video_view import VideoView

log = logging.getLogger(__name__)


class StatusLogHandler(logging.Handler):
    """Zeigt Warnungen und Fehler in der Statusleiste.

    WARUM ES DAS GIBT: Mit dem Reiter "Debug / Events" ist am 2026-09-03 das
    einzige Fenster verschwunden, in dem der Nutzer Log-Meldungen sehen konnte.
    Eine Warnung, die nur in der Konsole steht, existiert fuer ihn nicht -- und
    gerade die Kalibrierungswarnungen ("passt die Kalibrierung zu diesem
    Video?") sind die, auf die es ankommt.

    Nur WARNING und darueber. Info-Meldungen kommen im Sekundentakt und wuerden
    die Leiste zum Flackern bringen, ohne dass jemand sie liest.

    Qt-Widgets duerfen nur im GUI-Thread beruehrt werden. Log-Aufrufe kommen
    aber aus Worker-Threads, daher wird die Ausgabe ueber QTimer.singleShot in
    den GUI-Thread verlagert statt direkt geschrieben.
    """

    def __init__(self, fenster: QMainWindow) -> None:
        super().__init__(level=logging.WARNING)
        self._fenster = fenster
        self.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
        except Exception:  # noqa: BLE001 -- Logging darf die Anwendung nie stoppen
            return
        QTimer.singleShot(
            0, lambda: self._fenster.statusBar().showMessage(message, 8000))


def als_uhrzeit(sekunden: float) -> str:
    """Sekunden als HH:MM:SS.

    WOFUER -- Nutzer am 2026-09-10: "5621 Sekunden ist fuer mich nicht so
    eingaengig". Bei einem Spieltag von drei Stunden ist die Sekundenzahl
    fuenfstellig; die Stelle im Video findet man damit nicht wieder.

    Die Sekunden bleiben trotzdem stehen: Frame-Nummer geteilt durch Bildrate
    ergibt sie, und in Logs und Debug-Ordnern steht sie so.
    """
    if sekunden < 0 or sekunden != sekunden:      # negativ oder NaN
        return "--:--:--"
    ganze = int(sekunden)
    return f"{ganze // 3600:02d}:{ganze % 3600 // 60:02d}:{ganze % 60:02d}"


class MainWindow(QMainWindow):
    def __init__(self, cfg: AppConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.player = VideoPlayer(cfg.video.max_consecutive_read_failures, self)
        self.session = CalibrationSession(
            warped_width=cfg.calibration.warped_width,
            warped_height=cfg.calibration.warped_height,
            # Sonst traegt jede frisch kalibrierte Bahn `real_lane_number: null`
            # und wird als 1..4 gemeldet -- auch im Versand.
            lane_number_mapping=cfg.calibration.lane_number_mapping,
        )
        self._current_frame: Frame | None = None
        self._calibration_path: Path | None = None
        self._worker: AnalysisWorker | None = None
        self._last_result: FrameResult | None = None
        self._throw_count = 0
        # Darf der Positionsschieber ueberhaupt bedient werden? Bei einem
        # Stream nicht -- dort gibt es nichts zu spulen. Der Merker haelt
        # das fest, damit `_update_controls` nach der Analyse nicht blind
        # wieder einschaltet, was vorher gesperrt war.
        self._slider_erlaubt = False
        # Laeuft gerade eine Analyse? Bewusst ein eigenes Kennzeichen und
        # nicht `self._worker is not None`: Der Worker wird nach dem Lauf
        # nicht zurueckgesetzt, die Wiedergabe bliebe sonst fuer immer
        # gesperrt. `isRunning()` waere kurz nach `start()` noch falsch.
        self._analyse_aktiv = False
        # Das zuletzt vom Worker gelieferte Bild -- die EINZIGE frische Quelle,
        # solange eine Analyse laeuft. Der Player ist dann geschlossen, und
        # sein `current_frame` steht auf dem Stand von vorher.
        self._analyse_bild = None
        self._analyse_bild_index: int | None = None
        # Pfad der Vorschau, solange sie fuer die Analyse geschlossen ist.
        self._vorschau_pfad: str | None = None
        # Videodaten fuer die Dauer der Analyse. Bei einem
        # Livestream ist der Player dann geschlossen.
        self._analyse_info: VideoInfo | None = None
        # Im Bauart-Fenster gewaehlte Feinkorrektur -- wird nach der Suche
        # auf die frische Kalibrierung gelegt.
        self._gewaehlte_korrektur = None
        # Wartet die Oberflaeche gerade auf den Klick in eine Tafel, die
        # nachgezogen werden soll? Solange das laeuft, bedeutet ein Klick
        # "diese Tafel" und nichts anderes.
        self._nachkal_auswahl = False

        self.setWindowTitle("Kegel_CV - Automatische Kegelerfassung")
        self._apply_window_size()

        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._refresh_video_list()
        self._refresh_calibration_list()
        self._update_controls()

        log.info("Anwendung gestartet")

    def _apply_window_size(self) -> None:
        """Passt das Fenster an den tatsaechlich verfuegbaren Bildschirm an.

        Eine feste Groesse aus der Konfiguration ist unbrauchbar, sobald der
        Bildschirm kleiner ist oder Windows mit 125/150 % skaliert: Das Fenster
        raegt dann ueber den Rand und Bedienelemente sind nicht erreichbar.
        `availableGeometry` beruecksichtigt bereits Taskleiste und Skalierung.
        """
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(self.cfg.gui.window_width, self.cfg.gui.window_height)
            return

        available = screen.availableGeometry()
        width = min(self.cfg.gui.window_width, int(available.width() * 0.95))
        height = min(self.cfg.gui.window_height, int(available.height() * 0.95))
        self.resize(width, height)

        # Mittig setzen, damit das Fenster nicht halb ausserhalb startet
        self.move(available.center().x() - width // 2,
                  available.center().y() - height // 2)

        if (self.cfg.gui.window_width > available.width()
                or self.cfg.gui.window_height > available.height()):
            log.info("Fenster auf %dx%d begrenzt (Bildschirm: %dx%d)",
                     width, height, available.width(), available.height())

    # ------------------------------------------------------------------- Aufbau

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)

        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter, 1)

        # --- oben: Video + Seitenleiste ---
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)

        self.video_view = VideoView()
        top_layout.addWidget(self.video_view, 1)

        # Seitenleiste scrollbar: Reicht die Fensterhoehe nicht, staucht Qt die
        # Widgets sonst bis zur Unkenntlichkeit -- im Extremfall auf Hoehe null,
        # sodass ganze Bedienbloecke unsichtbar werden.
        sidebar_scroll = QScrollArea()
        sidebar_scroll.setWidget(self._build_sidebar())
        sidebar_scroll.setWidgetResizable(True)
        sidebar_scroll.setFixedWidth(300)
        sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sidebar_scroll.setFrameShape(QScrollArea.NoFrame)
        top_layout.addWidget(sidebar_scroll)
        splitter.addWidget(top)

        # --- Mitte: Transport ---
        root_transport = self._build_transport()

        # --- unten: Ergebnisse je Bahn ---
        #
        # Frueher lagen hier zwei Reiter, "Ergebnisse" und "Debug / Events".
        # Mit dem Wegfall des Debug-Reiters bleibt nur einer uebrig -- und ein
        # Reiter, der nie wechselt, ist ein Rahmen ohne Inhalt. Warnungen
        # zeigt jetzt die Statusleiste (`StatusLogHandler`).
        splitter.addWidget(self._build_lane_tables())
        splitter.setSizes([int(self.height() * 0.62), int(self.height() * 0.38)])

        root.addWidget(root_transport)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Bereit - bitte ein Video laden")

        # Erst JETZT anhaengen: Der Handler schreibt in die Statusleiste, die
        # es vor dieser Zeile noch nicht gibt.
        logging.getLogger().addHandler(StatusLogHandler(self))

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(270)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(8)

        # Video-Auswahl
        video_box = QGroupBox("Video")
        video_layout = QVBoxLayout(video_box)
        self.video_combo = QComboBox()
        video_layout.addWidget(self.video_combo)
        btn_load = QPushButton("Laden")
        btn_load.clicked.connect(self._on_load_selected_video)
        video_layout.addWidget(btn_load)

        # Livestream statt Datei. Fuer die Analyse ist das derselbe Weg -- die
        # Videoquelle wird in `video.factory` anhand des Schemas gewaehlt.
        self.stream_edit = QLineEdit()
        self.stream_edit.setPlaceholderText("oder Stream-URL (https://..., rtsp://...)")
        self.stream_edit.setToolTip(
            "Adresse eines laufenden Streams. Kalibrieren funktioniert genauso: "
            "Wiedergabe anhalten, Ecken anklicken, Analyse starten. "
            "Im Stream laesst sich nicht spulen -- ausgewertet wird ab jetzt."
        )
        self.stream_edit.returnPressed.connect(self._on_load_stream)
        video_layout.addWidget(self.stream_edit)
        btn_stream = QPushButton("Stream verbinden")
        btn_stream.clicked.connect(self._on_load_stream)
        video_layout.addWidget(btn_stream)
        self.video_info_label = QLabel("kein Video geladen")
        self.video_info_label.setWordWrap(True)
        self.video_info_label.setStyleSheet("color: #666; font-size: 11px;")
        video_layout.addWidget(self.video_info_label)

        # Die Aufloesung als eigene, farbige Zeile -- siehe `_on_video_opened`.
        # Einem Stream sieht man an der Adresse nicht an, welche Fassung
        # dahinterliegt; die Kalibrierung gilt aber nur fuer eine.
        self.resolution_label = QLabel()
        self.resolution_label.setWordWrap(True)
        self.resolution_label.setVisible(False)
        video_layout.addWidget(self.resolution_label)
        layout.addWidget(video_box)

        # Kalibrierung
        cal_box = QGroupBox("Kalibrierung")
        cal_layout = QVBoxLayout(cal_box)

        # Aktive Bahn waehlen, OHNE die Eckpunkte neu zu setzen.
        # Ohne diese Auswahl waere nach dem Laden einer Kalibrierung keine Bahn
        # aktiv -- und alle folgenden Schritte (Bereiche, Ziffern) waeren
        # unerreichbar, ohne die Ecken erneut zu klicken.
        lane_row = QHBoxLayout()
        lane_row.addWidget(QLabel("aktive Bahn:"))
        self.active_lane_combo = QComboBox()
        self.active_lane_combo.currentIndexChanged.connect(self._on_select_active_lane)
        lane_row.addWidget(self.active_lane_combo, 1)
        cal_layout.addLayout(lane_row)

        # UNTER WELCHER BAHNNUMMER DIESE TAFEL GEMELDET WIRD.
        #
        # Die Tafeln im Bild sind von links durchnummeriert, die Ergebnisse
        # tragen aber die Bahnnummer der Halle. In der Stammhalle sind das die
        # Bahnen 2 bis 5; auswaerts kann dieselbe Anordnung 1 bis 4 heissen.
        # Bisher stand die Zuordnung nur in der Konfigurationsdatei -- also
        # nicht dort, wo man vor Ort steht.
        nummer_row = QHBoxLayout()
        nummer_row.addWidget(QLabel("meldet als Bahn:"))
        self.lane_number_spin = QSpinBox()
        self.lane_number_spin.setRange(1, 99)
        self.lane_number_spin.setToolTip(
            "Diese Zahl steht als Bahnnummer in der Datenbank und im "
            "Liveticker. Sie gilt fuer die oben gewaehlte Tafel und wird mit "
            "der Kalibrierung gespeichert."
        )
        self.lane_number_spin.valueChanged.connect(self._on_lane_number_changed)
        nummer_row.addWidget(self.lane_number_spin, 1)
        cal_layout.addLayout(nummer_row)

        # Die frueheren Knoepfe "Bahn N kalibrieren" sind entfallen: Sie
        # starteten denselben Vorgang wie die gefuehrte Kalibrierung, nur ohne
        # Fuehrung und je Bahn einzeln. Zwei Wege zum selben Ziel, von denen
        # einer schlechter ist, sind eine Falle -- nicht eine Auswahl.

        self.calibration_hint = QLabel("Video laden, dann gefuehrt kalibrieren")
        self.calibration_hint.setWordWrap(True)
        self.calibration_hint.setMinimumHeight(46)
        self.calibration_hint.setStyleSheet(
            "background:#2d2d2d; color:#eee; padding:6px; border-radius:3px;"
        )
        cal_layout.addWidget(self.calibration_hint)

        row = QHBoxLayout()
        btn_undo = QPushButton("Punkt zurueck")
        btn_undo.clicked.connect(self._on_undo_point)
        row.addWidget(btn_undo)
        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setToolTip("Aktuellen Schritt abbrechen (Esc)")
        btn_cancel.clicked.connect(self._on_cancel_calibration)
        row.addWidget(btn_cancel)
        cal_layout.addLayout(row)

        self.btn_guide = QPushButton("Gefuehrt kalibrieren")
        self.btn_guide.setToolTip(
            "Fuehrt durch alle vier Bahnen: Bahn 1 vollstaendig, danach werden "
            "ihre Felder auf die uebrigen uebernommen -- nur die Tafelecken "
            "sind dort noch zu setzen. Am Ende laesst sich jedes Feld einzeln "
            "nachziehen."
        )
        self.btn_guide.setStyleSheet("font-weight:bold; padding:6px;")
        self.btn_guide.clicked.connect(self._on_start_guide)
        cal_layout.addWidget(self.btn_guide)

        # OHNE EINEN EINZIGEN KLICK IN DIE TAFEL. Kennt das Werkzeug die
        # Bauart, folgt die ganze Kalibrierung aus dem Musterbild -- Ecken,
        # Lampen und Ziffern zusammen.
        self.btn_auto_kalibrieren = QPushButton("Automatisch kalibrieren")
        self.btn_auto_kalibrieren.setToolTip(
            "Zeigt die bekannten Kegelboard-Bauarten zur Auswahl. Die "
            "gewaehlte wird im Bild gesucht, samt aller weiteren Tafeln "
            "desselben Typs. Danach nur noch die Bahnnummern angeben."
        )
        self.btn_auto_kalibrieren.setStyleSheet(
            "font-weight:bold; padding:6px;")
        self.btn_auto_kalibrieren.clicked.connect(self._on_auto_kalibrieren)
        cal_layout.addWidget(self.btn_auto_kalibrieren)

        # EINE TAFEL GENUEGT. Ist eine Bahn vermessen, findet der Rechner die
        # uebrigen desselben Bautyps -- die ROIs liegen in normierten
        # Tafelkoordinaten, also folgen Lampen und Ziffern aus den vier Ecken.
        self.btn_find_lanes = QPushButton("Weitere Bahnen finden")
        self.btn_find_lanes.setToolTip(
            "Nimmt die aktive Bahn als Muster und sucht alle Tafeln desselben "
            "Bautyps im aktuellen Bild. Danach werden die Bahnnummern "
            "abgefragt. Am besten mit einer moeglichst frontal gesehenen "
            "Tafel als Muster."
        )
        self.btn_find_lanes.setStyleSheet("padding:6px;")
        self.btn_find_lanes.clicked.connect(self._on_find_lanes)
        cal_layout.addWidget(self.btn_find_lanes)

        # DIE EINE TAFEL, DIE NICHT SITZT. Die automatische Kalibrierung
        # trifft im Mittel auf 0,76 px genau -- aber wenn eine von vier
        # danebenliegt, muss genau diese eine nachziehbar sein, und zwar
        # gross: Im Vollbild misst eine Lampen-ROI sechs Pixel.
        self.btn_nachkalibrieren = QPushButton("Nachkalibrieren")
        self.btn_nachkalibrieren.setToolTip(
            "Danach die Tafel im Bild anklicken, die nicht sitzt. Sie wird "
            "entzerrt und gross gezeigt; dort lassen sich Lampen und "
            "Ziffernfelder einzeln ziehen und in der Groesse aendern.")
        self.btn_nachkalibrieren.setStyleSheet("padding:6px;")
        self.btn_nachkalibrieren.clicked.connect(self._on_nachkalibrieren)
        cal_layout.addWidget(self.btn_nachkalibrieren)

        # WAS EINMAL NACHGEZOGEN WURDE, SOLL NICHT ZWEIMAL NACHGEZOGEN WERDEN.
        # Gemerkt wird der Unterschied zur Bauart, nicht die Kalibrierung: Die
        # Tafelecken haengen an Kamera und Blickwinkel, die Versaetze auf der
        # Tafel beschreiben die Anlage.
        self.btn_korrektur_merken = QPushButton("Feinkorrektur merken")
        self.btn_korrektur_merken.setToolTip(
            "Merkt, wie weit die Bereiche hier von der Bauart abweichen -- je "
            "Tafel. Beim naechsten 'Automatisch kalibrieren' steht diese "
            "Korrektur unter der Bauart zur Auswahl.")
        self.btn_korrektur_merken.setStyleSheet("padding:6px;")
        self.btn_korrektur_merken.clicked.connect(self._on_korrektur_merken)
        cal_layout.addWidget(self.btn_korrektur_merken)

        # DER LETZTE PIXEL. Eine automatisch gefundene Tafel sitzt auf ein bis
        # drei Pixel genau. Fuer die Lampen genuegt das, fuer die Ziffern
        # nicht: GEMESSEN entscheidet EIN Pixel ueber neun Prozentpunkte
        # Lesegenauigkeit (54 -> 60 von 66 richtigen Stellen).
        ziffern_row = QHBoxLayout()
        ziffern_row.addWidget(QLabel("Ziffern verschieben:"))
        self.digit_dx = QSpinBox()
        self.digit_dx.setRange(-8, 8)
        self.digit_dx.setPrefix("x ")
        self.digit_dx.setToolTip(
            "Verschiebt NUR die Ziffernrahmen, in Pixeln. Ein Pixel zu weit "
            "rechts, und der Balken der 1 rutscht zur Zellmitte -- dann lesen "
            "die waagerechten Segmente mit, und aus 1 wird 3.")
        self.digit_dy = QSpinBox()
        self.digit_dy.setRange(-8, 8)
        self.digit_dy.setPrefix("y ")
        self.digit_dy.setToolTip(self.digit_dx.toolTip())
        self.digit_dx.valueChanged.connect(self._on_digit_shift)
        self.digit_dy.valueChanged.connect(self._on_digit_shift)
        ziffern_row.addWidget(self.digit_dx)
        ziffern_row.addWidget(self.digit_dy)
        cal_layout.addLayout(ziffern_row)
        # Was bereits angewandt ist -- die Felder zeigen den GESAMTversatz,
        # verschoben wird aber jeweils nur die Differenz.
        self._digit_shift_angewandt = (0, 0)

        # ENTFALLEN mit dem Umbau vom 2026-09-03: "Bereiche anklicken (14)",
        # "nur Raute" und "Ziffern einzeln einrahmen (8)" samt Feldauswahl.
        #
        # Alle drei setzten Rahmen NEU -- und das ist seit der gefuehrten
        # Kalibrierung ueberfluessig: Sie legt jeden Rahmen an eine gemessene
        # Stelle, und jeder Rahmen laesst sich danach mit der Maus ziehen. Ein
        # zweiter, umstaendlicherer Weg zum selben Ergebnis kostet den Nutzer
        # nur die Entscheidung, welchen er nehmen soll.
        #
        # `ueberspringen` bleibt: Es gehoert zum ABLAUF der Fuehrung, nicht zum
        # Neusetzen -- damit laesst sich ein Bereich unveraendert lassen.
        row_roi = QHBoxLayout()
        btn_skip = QPushButton("ueberspringen")
        btn_skip.setToolTip("Diesen Bereich unveraendert lassen")
        btn_skip.clicked.connect(self._on_skip_roi)
        row_roi.addWidget(btn_skip)
        cal_layout.addLayout(row_roi)

        self.roi_combo = QComboBox()
        self.roi_combo.setToolTip(
            "Einzelnen Bereich gezielt neu setzen. Ziffernstellen sind einzeln "
            "dabei -- sie werden ueber ZWEI Ecken gesetzt (oben links, unten "
            "rechts), alles andere ueber einen Klick in die Mitte."
        )
        self.roi_combo.addItem("-- einzelnen Bereich neu setzen --", None)
        for name in single_roi_choices():
            self.roi_combo.addItem(roi_label(name), name)
        self.roi_combo.currentIndexChanged.connect(self._on_select_single_roi)
        cal_layout.addWidget(self.roi_combo)

        # Stand HIER frueher nicht, sondern unter "Live-Analyse". Dort war er
        # fehl am Platz: Der Knopf misst die gruenen Lampen ueber mehrere
        # Frames und meldet, welche Bahn nachjustiert werden muss -- das ist
        # eine Aussage ueber die Kalibrierung, nicht ueber die Analyse.
        self.btn_check = QPushButton("Kalibrierung pruefen")
        self.btn_check.setMinimumHeight(28)
        self.btn_check.setToolTip(
            "Misst die gruenen Lampen ueber mehrere Frames und meldet, welche "
            "Bahn nachjustiert werden muss"
        )
        self.btn_check.clicked.connect(self._on_check_calibration)
        cal_layout.addWidget(self.btn_check)

        self.calibration_combo = QComboBox()
        cal_layout.addWidget(self.calibration_combo)
        row2 = QHBoxLayout()
        btn_save = QPushButton("Speichern")
        btn_save.clicked.connect(self._on_save_calibration)
        row2.addWidget(btn_save)
        btn_load_cal = QPushButton("Laden")
        btn_load_cal.clicked.connect(self._on_load_calibration)
        row2.addWidget(btn_load_cal)
        cal_layout.addLayout(row2)

        layout.addWidget(cal_box)

        # --- Ansicht / Zoom ---
        zoom_box = QGroupBox("Ansicht")
        zoom_layout = QVBoxLayout(zoom_box)
        self.zoom_label = QLabel("Zoom 1.0x")
        self.zoom_label.setStyleSheet("color:#888; font-size:11px;")
        zoom_layout.addWidget(self.zoom_label)

        zoom_row = QHBoxLayout()
        for text, factor in (("−", 1 / 1.6), ("+", 1.6)):
            btn = QPushButton(text)
            btn.setFixedSize(32, 26)
            btn.clicked.connect(lambda _=False, f=factor: self._on_zoom_step(f))
            zoom_row.addWidget(btn)
        btn_fit = QPushButton("ganzes Bild")
        btn_fit.setMinimumHeight(26)
        btn_fit.clicked.connect(self.video_view.reset_zoom)
        zoom_row.addWidget(btn_fit, 1)
        zoom_layout.addLayout(zoom_row)

        lane_zoom_row = QHBoxLayout()
        lane_zoom_row.addWidget(QLabel("auf Tafel:"))
        for lane_id in range(1, self.cfg.calibration.lane_count + 1):
            btn = QPushButton(str(lane_id))
            btn.setFixedSize(30, 26)
            btn.setToolTip(f"Auf die Anzeigetafel von Bahn {lane_id} zoomen")
            btn.clicked.connect(lambda _=False, n=lane_id: self._zoom_to_lane(n))
            lane_zoom_row.addWidget(btn)
        zoom_layout.addLayout(lane_zoom_row)

        hint = QLabel("Mausrad = Zoom, mittlere Taste = schieben")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#777; font-size:10px;")
        zoom_layout.addWidget(hint)
        layout.addWidget(zoom_box)

        # --- Live-Analyse ---
        analysis_box = QGroupBox("Live-Analyse")
        analysis_layout = QVBoxLayout(analysis_box)

        self.btn_analyze = QPushButton("Analyse starten")
        self.btn_analyze.setStyleSheet(
            "font-weight:bold; padding:6px; background:#1e7d32; color:white;"
        )
        self.btn_analyze.setMinimumHeight(34)
        self.btn_analyze.setToolTip(
            "Wertet das Video durchgehend aus und zeigt die Ergebnisse live an"
        )
        self.btn_analyze.clicked.connect(self._on_toggle_analysis)
        analysis_layout.addWidget(self.btn_analyze)

        # DER NAME DER PARTIE. Geht als `game_name` mit in die Datenbank und
        # benennt den Debug-Ordner. Im Multisensor-Aufbau -- Stream fuer zwei
        # Bahnen, Telefon fuer die anderen -- muss auf ALLEN Geraeten derselbe
        # Name stehen; daran finden die Wuerfe wieder zusammen.
        spiel_zeile = QHBoxLayout()
        spiel_zeile.addWidget(QLabel("Spiel:"))
        self.txt_spielname = QLineEdit()
        self.txt_spielname.setPlaceholderText("z. B. 2. Spieltag Herren")
        self.txt_spielname.setToolTip(
            "Name dieser Partie. Wird als `game_name` gespeichert und benennt "
            "den Debug-Ordner. Bei mehreren Geraeten (Stream + Handy) auf "
            "allen DENSELBEN Namen setzen -- daran finden die Wuerfe wieder "
            "zusammen. Die Herkunft bleibt trotzdem unterscheidbar."
        )
        spiel_zeile.addWidget(self.txt_spielname, 1)
        analysis_layout.addLayout(spiel_zeile)

        # WELCHE BAHNEN DIESES GERAET UEBERNIMMT. Leer angekreuzt = alle.
        # Die Kaestchen werden erst gefuellt, wenn eine Kalibrierung geladen
        # ist -- vorher weiss niemand, welche Bahnen es gibt.
        self.bahn_zeile = QHBoxLayout()
        self.bahn_zeile.addWidget(QLabel("Bahnen:"))
        self.chk_bahnen: dict[int, QCheckBox] = {}
        self.bahn_zeile.addStretch(1)
        analysis_layout.addLayout(self.bahn_zeile)

        # Ab der aktuellen Stelle auswerten. Vor einem Spiel wird warmgespielt,
        # und diese Wuerfe gehoeren nicht in die Auswertung.
        self.chk_ab_hier = QCheckBox("ab aktueller Stelle starten")
        self.chk_ab_hier.setToolTip(
            "Wertet erst ab dem gerade angezeigten Frame aus -- zum "
            "Ueberspringen des Warmspielens. Bei einem Livestream ohne "
            "Wirkung: dort gibt es keinen Anfang."
        )
        analysis_layout.addWidget(self.chk_ab_hier)

        # Versand getrennt schaltbar -- auch WAEHREND die Analyse laeuft.
        # Beim Warmspielen soll nichts in die Datenbank, sichtbar sein soll es
        # trotzdem.
        self.chk_senden = QCheckBox("an Datenbank senden")
        self.chk_senden.setChecked(True)
        self.chk_senden.setToolTip(
            "Aus: Es wird weiterhin ausgewertet, angezeigt und protokolliert "
            "-- nur nicht gesendet. Laesst sich jederzeit umschalten, auch "
            "mitten in der Analyse."
        )
        self.chk_senden.toggled.connect(self._on_toggle_senden)
        analysis_layout.addWidget(self.chk_senden)

        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Tempo:"))
        self.speed_combo = QComboBox()
        # Echtzeit ist beim Zuschauen oft nützlicher als Vollgas -- man will
        # erkennen, was passiert, nicht nur dass es passiert.
        self.speed_combo.addItem("Echtzeit (25 fps)", 25.0)
        self.speed_combo.addItem("halbes Tempo", 12.5)
        self.speed_combo.addItem("so schnell wie moeglich", 0.0)
        self.speed_combo.currentIndexChanged.connect(self._on_speed_changed)
        speed_row.addWidget(self.speed_combo, 1)
        analysis_layout.addLayout(speed_row)

        self.analysis_status = QLabel("nicht gestartet")
        self.analysis_status.setWordWrap(True)
        self.analysis_status.setStyleSheet("color:#888; font-size:11px;")
        analysis_layout.addWidget(self.analysis_status)
        layout.addWidget(analysis_box)

        # Der Kasten "Debug" mit "Frame speichern" und "Entzerrte Tafeln
        # speichern" ist am 2026-09-03 entfallen. Beides sind Werkzeuge fuer
        # die Fehlersuche, nicht fuer den taeglichen Gebrauch -- und beides
        # leistet `tools/export_roi_frames.py` gruendlicher, weil es die
        # Rahmen und die gelesenen Werte gleich mit einzeichnet.

        layout.addStretch(1)
        return panel

    def _build_transport(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.btn_prev = QPushButton("<<")
        self.btn_prev.setFixedWidth(48)
        self.btn_prev.setToolTip("Ein Frame zurueck (Pfeil links)")
        self.btn_play = QPushButton("Play")
        self.btn_play.setFixedWidth(70)
        self.btn_play.setToolTip("Wiedergabe (Leertaste)")
        self.btn_next = QPushButton(">>")
        self.btn_next.setFixedWidth(48)
        self.btn_next.setToolTip("Ein Frame vor (Pfeil rechts)")

        for btn in (self.btn_prev, self.btn_play, self.btn_next):
            layout.addWidget(btn)

        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setEnabled(False)
        layout.addWidget(self.position_slider, 1)

        self.position_label = QLabel("Frame 0    00:00:00  (0 s)")
        self.position_label.setFont(QFont("Consolas", 10))
        self.position_label.setMinimumWidth(320)
        layout.addWidget(self.position_label)

        return widget

    def _build_lane_tables(self) -> QWidget:
        """Live-Anzeige je Bahn. Wird beim Laden einer Kalibrierung neu aufgebaut,
        weil erst dann feststeht, welche Bahnen es gibt."""
        self.lane_container = QWidget()
        self.lane_layout = QHBoxLayout(self.lane_container)
        self.lane_layout.setSpacing(6)
        self.lane_panels: dict[int, LanePanel] = {}
        self._rebuild_lane_panels()
        return self.lane_container

    def _on_digit_shift(self) -> None:
        """Verschiebt die Ziffernrahmen um die Differenz zum bisherigen Stand.

        Die Felder zeigen den GESAMTversatz. Angewandt wird nur, was seit dem
        letzten Mal dazugekommen ist -- sonst summierte sich jeder Klick auf
        den vorigen und der angezeigte Wert loege.
        """
        from ..calibration.digit_shift import verschiebe_ziffern

        if not self.session.calibration.lanes:
            return
        soll = (self.digit_dx.value(), self.digit_dy.value())
        alt_x, alt_y = self._digit_shift_angewandt
        dx, dy = soll[0] - alt_x, soll[1] - alt_y
        if dx == 0 and dy == 0:
            return
        anzahl = verschiebe_ziffern(self.session.calibration, dx, dy)
        self._digit_shift_angewandt = soll
        self.statusBar().showMessage(
            f"{anzahl} Ziffernrahmen verschoben, Gesamtversatz "
            f"x {soll[0]:+d} / y {soll[1]:+d} px. Nicht vergessen: speichern.",
            6000)
        log.info("Ziffernrahmen um %+d/%+d px verschoben (gesamt %+d/%+d)",
                 dx, dy, soll[0], soll[1])
        self._redraw_overlays()
        self._reiche_kalibrierung_weiter()

    def _on_find_lanes(self) -> None:
        """Sucht alle Tafeln desselben Bautyps anhand der aktiven Bahn.

        WOFUER: In einer fremden Halle genuegt es, EINE Tafel von Hand zu
        vermessen. Die uebrigen findet der Merkmalsabgleich -- an einem
        Trainingsmitschnitt auf ein bis drei Pixel genau, und die daraus
        erzeugte Kalibrierung schnitt in der Analyse besser ab als die von
        Hand gesetzte.

        Welche Bahnnummer welche Tafel traegt, kann der Rechner nicht wissen
        -- das steht an der Wand. Deshalb die Rueckfrage am Ende.
        """
        from ..calibration.board_finder import (BoardFinder, entzerre,
                                                quad_groesse)

        frame = self.player.current_frame
        if frame is None or not self.session.calibration.lanes:
            QMessageBox.information(
                self, "Noch nichts zu suchen",
                "Erst ein Video laden und mindestens eine Tafel kalibrieren "
                "-- sie dient als Muster fuer die uebrigen.")
            return

        aktiv = self.session.active_lane
        muster = next((l for l in self.session.calibration.lanes
                       if l.lane_id == aktiv), self.session.calibration.lanes[0])

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            groesse = quad_groesse(muster.quad)
            vorlage = entzerre(frame.image, muster.quad, groesse)
            finder = BoardFinder()
            treffer = finder.finde_alle(frame.image, [vorlage])
            # Zweiter Durchgang mit dem besten Treffer als Muster: gleiche
            # Kamera, gleiches Licht. GEMESSEN: 92 -> 176 tragende Merkmale.
            if treffer:
                bester = max(treffer, key=lambda t: t.inlier)
                eigene = entzerre(frame.image, bester.quad,
                                  quad_groesse(bester.quad))
                zweite = BoardFinder().finde_alle(frame.image, [eigene])
                if (len(zweite) >= len(treffer)
                        and sum(t.inlier for t in zweite)
                        > sum(t.inlier for t in treffer)):
                    treffer = zweite
        finally:
            QApplication.restoreOverrideCursor()

        if not treffer:
            QMessageBox.warning(
                self, "Keine Tafel gefunden",
                "In diesem Bild liess sich keine weitere Tafel zuordnen.\n\n"
                "Moegliche Gruende: anderer Bautyp, sehr anderer Blickwinkel, "
                "oder das Bild taugt nicht (jemand davor, Bewegungsunschaerfe). "
                "Ein anderes Standbild waehlen und erneut versuchen.")
            return

        vorschlag = " ".join(str(i) for i in range(1, len(treffer) + 1))
        bestehende = [l.display_number for l in self.session.calibration.lanes]
        if len(bestehende) == len(treffer):
            vorschlag = " ".join(str(n) for n in bestehende)

        text, ok = QInputDialog.getText(
            self, "Bahnnummern",
            f"{len(treffer)} Tafeln gefunden, von links nach rechts.\n"
            f"Welche Bahnnummern tragen sie?",
            text=vorschlag)
        if not ok:
            return
        teile = text.replace(",", " ").split()
        if len(teile) != len(treffer) or not all(t.isdigit() for t in teile):
            QMessageBox.warning(
                self, "Eingabe passt nicht",
                f"{len(treffer)} Zahlen erwartet, {len(teile)} bekommen.")
            return

        neu = []
        for i, (t, nummer) in enumerate(zip(treffer, teile), start=1):
            bahn = muster.model_copy(deep=True)
            bahn.lane_id = i
            bahn.real_lane_number = int(nummer)
            bahn.quad = t.quad
            neu.append(bahn)
        self.session.calibration.lanes = neu
        self.session.active_lane = 1

        self._refresh_active_lane_combo()
        self._rebuild_lane_panels()
        self._update_calibration_hint()
        traeger = ", ".join(f"{t.inlier}" for t in treffer)
        self.statusBar().showMessage(
            f"{len(treffer)} Bahnen uebernommen (tragende Merkmale: "
            f"{traeger}). Rahmen pruefen, dann speichern.", 10000)
        log.info("Automatisch gefunden: %d Tafeln, Bahnnummern %s",
                 len(treffer), teile)

    def _refresh_lane_number_spin(self) -> None:
        """Zeigt die Bahnnummer der gerade gewaehlten Tafel an.

        `blockSignals`, damit das Nachfuehren nicht als Nutzereingabe gilt --
        sonst schriebe die Anzeige den Wert zurueck, den sie gerade erst
        gelesen hat.
        """
        if not hasattr(self, "lane_number_spin"):
            return
        aktiv = self.session.active_lane
        bahn = next((l for l in self.session.calibration.lanes
                     if l.lane_id == aktiv), None)
        self.lane_number_spin.blockSignals(True)
        self.lane_number_spin.setEnabled(bahn is not None)
        if bahn is not None:
            self.lane_number_spin.setValue(bahn.display_number)
        self.lane_number_spin.blockSignals(False)

    def _on_lane_number_changed(self, wert: int) -> None:
        aktiv = self.session.active_lane
        if aktiv is None:
            return
        # NUR AUF EINE KALIBRIERTE BAHN. `active_lane` steht auf 1, sobald das
        # Fenster offen ist -- kalibriert ist deshalb noch lange nichts.
        # GEMESSEN am 2026-09-10 im Livelauf: Ein Dreh am Bahnnummernfeld vor
        # der Kalibrierung warf `KeyError: Bahn 1 ist nicht kalibriert` mitten
        # aus dem Qt-Signal heraus.
        if not any(l.lane_id == aktiv for l in self.session.calibration.lanes):
            self.statusBar().showMessage(
                "Bahnnummern lassen sich erst vergeben, wenn die Tafeln "
                "kalibriert sind.", 6000)
            return
        warnung = self.session.set_real_lane_number(aktiv, wert)
        # Die Beschriftungen tragen die Bahnnummer -- sie muessen mit.
        self._refresh_active_lane_combo()
        self._rebuild_lane_panels()
        if warnung:
            self.statusBar().showMessage(warnung, 8000)
            log.warning("%s", warnung)
        else:
            self.statusBar().showMessage(
                f"Tafel {aktiv} von links meldet als Bahn {wert}. "
                f"Nicht vergessen: Kalibrierung speichern.", 5000)

    def _refresh_active_lane_combo(self) -> None:
        """Fuellt die Bahnauswahl passend zur aktuellen Kalibrierung."""
        if not hasattr(self, "active_lane_combo"):
            return
        self.active_lane_combo.blockSignals(True)
        self.active_lane_combo.clear()
        for lane in self.session.calibration.lanes:
            label = (f"Bahn {lane.display_number}" if lane.display_number == lane.lane_id
                     else f"Bahn {lane.display_number} (Tafel {lane.lane_id})")
            self.active_lane_combo.addItem(label, lane.lane_id)
        if not self.session.calibration.lanes:
            self.active_lane_combo.addItem("(noch nicht kalibriert)", None)
        self.active_lane_combo.blockSignals(False)
        self._refresh_lane_number_spin()

        # Erste Bahn automatisch aktiv setzen
        first = self.active_lane_combo.itemData(0)
        if first is not None and self.session.active_lane is None:
            self.session.active_lane = first
            self.session.step = CalibrationStep.EDIT_ROIS
            self._update_calibration_hint()

    def _on_select_active_lane(self, index: int) -> None:
        """Waehlt die Bahn, auf die sich die naechsten Schritte beziehen."""
        lane_id = self.active_lane_combo.itemData(index)
        if lane_id is None:
            return
        self.session.active_lane = lane_id
        self.session.pending_points.clear()
        self.session.roi_queue.clear()
        self.session.active_roi = None
        self.session.step = CalibrationStep.EDIT_ROIS
        self._zoom_to_lane(lane_id)
        # Die Bahnnummer gehoert zur Tafel, nicht zur Sitzung -- beim Wechsel
        # muss die Anzeige mit.
        self._refresh_lane_number_spin()
        self._update_calibration_hint()

    def _rebuild_lane_panels(self) -> None:
        """Erzeugt die Bahn-Panels passend zur aktuellen Kalibrierung."""
        while self.lane_layout.count():
            item = self.lane_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.lane_panels.clear()

        lanes = self.session.calibration.lanes
        if lanes:
            entries = [(l.lane_id, l.display_number) for l in lanes]
        else:
            # Noch keine Kalibrierung: Platzhalter mit der konfigurierten Zuordnung
            mapping = self.cfg.calibration.lane_number_mapping
            entries = [
                (i, mapping[i - 1] if mapping and i <= len(mapping) else i)
                for i in range(1, self.cfg.calibration.lane_count + 1)
            ]

        for lane_id, display_number in entries:
            panel = LanePanel(lane_id, display_number)
            self.lane_panels[lane_id] = panel
            self.lane_layout.addWidget(panel)

        self._bahn_kaestchen_aufbauen([d for _, d in entries])

    def _bahn_kaestchen_aufbauen(self, bahnnummern: list[int]) -> None:
        """Ein Kaestchen je Bahn -- welche uebernimmt dieses Geraet?

        WOZU (Nutzer, 2026-09-24): Im Multisensor-Aufbau nimmt der Stream die
        Bahnen 2 und 3, ein Telefon die anderen. Ohne diese Auswahl schriebe
        jedes Geraet alles, was es lesen kann, und die Tabelle haette jeden
        Wurf doppelt.

        Alle angehakt ist die Vorgabe. Eine leere Vorauswahl waere "nichts
        erfassen" -- das faellt erst nach einem ganzen Spieltag auf.
        """
        vorher = {nr: box.isChecked() for nr, box in self.chk_bahnen.items()}
        # ALLES HINTER DER BESCHRIFTUNG RAEUMEN -- auch den Dehnungsplatz am
        # Ende; er wird unten neu gesetzt.
        #
        # WARUM NICHT MIT `insertWidget(count() - 1)` VOR DEN DEHNUNGSPLATZ
        # (Nutzer, 2026-09-25: *"Warum gibt es hier Bahn 2 2x?"*): Diese
        # Schleife nimmt den Dehnungsplatz mit weg. Danach setzte
        # `count() - 1` die Kaestchen VOR die Beschriftung, die Reihe wurde zu
        # `[2, 3, 4, 5, Bahnen:]`. Beim naechsten Aufbau stand an Index 0 dann
        # kein Label mehr, sondern das Kaestchen der ersten Bahn -- es
        # ueberlebte das Raeumen, fiel aus `chk_bahnen` heraus und blieb als
        # fuenftes, totes Kaestchen stehen.
        while self.bahn_zeile.count() > 1:
            item = self.bahn_zeile.takeAt(1)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.chk_bahnen.clear()
        for nummer in sorted(set(bahnnummern)):
            box = QCheckBox(str(nummer))
            box.setChecked(vorher.get(nummer, True))
            box.setToolTip(
                f"Bahn {nummer} von diesem Geraet erfassen und senden. "
                "Abgewaehlt: Die Bahn wird gar nicht ausgewertet -- sie kostet "
                "dann auch keine Rechenzeit. Auf einem zweiten Geraet die "
                "jeweils anderen Bahnen anhaken, dann kommt kein Wurf doppelt "
                "in der Datenbank an."
            )
            self.chk_bahnen[nummer] = box
            self.bahn_zeile.addWidget(box)
        # Der Dehnungsplatz zuletzt -- so drueckt er die Kaestchen nach links,
        # ohne dass irgendwo mit Indizes gerechnet werden muss.
        self.bahn_zeile.addStretch(1)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Datei")

        act_open = QAction("Video oeffnen...", self)
        act_open.setShortcut(QKeySequence.Open)
        act_open.triggered.connect(self._on_open_video_dialog)
        file_menu.addAction(act_open)
        file_menu.addSeparator()

        act_quit = QAction("Beenden", self)
        act_quit.setShortcut(QKeySequence.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        view_menu = self.menuBar().addMenu("&Ansicht")
        self.act_labels = QAction("ROI-Beschriftungen", self, checkable=True)
        self.act_labels.setChecked(self.cfg.gui.show_roi_labels)
        self.act_labels.toggled.connect(self.video_view.set_show_labels)
        view_menu.addAction(self.act_labels)

        self.act_overlay = QAction("Debug-Overlay", self, checkable=True)
        self.act_overlay.setChecked(self.cfg.gui.show_debug_overlay)
        self.act_overlay.toggled.connect(lambda _: self._update_overlay_text())
        view_menu.addAction(self.act_overlay)

    def _connect_signals(self) -> None:
        self.player.frame_ready.connect(self._on_frame)
        self.player.opened.connect(self._on_video_opened)
        self.player.error.connect(self._on_player_error)
        self.player.state_changed.connect(
            lambda playing: self.btn_play.setText("Pause" if playing else "Play")
        )
        self.player.finished.connect(
            lambda: self.statusBar().showMessage("Videoende erreicht", 4000)
        )

        self.btn_play.clicked.connect(self.player.toggle)
        self.btn_next.clicked.connect(self.player.step_forward)
        self.btn_prev.clicked.connect(self.player.step_backward)
        self.position_slider.sliderMoved.connect(self.player.seek)

        self.video_view.clicked.connect(self._on_video_clicked)
        self.video_view.quad_corner_dragged.connect(self._on_drag_corner)
        self.video_view.roi_dragged.connect(self._on_drag_roi)
        self.video_view.roi_resized.connect(self._on_resize_roi)
        self.video_view.drag_finished.connect(self._on_drag_finished)
        self.video_view.zoom_changed.connect(
            lambda z: self.zoom_label.setText(f"Zoom {z:.1f}x")
        )

    # -------------------------------------------------------------- Videoliste

    def _refresh_video_list(self) -> None:
        directory = self.cfg.resolve(self.cfg.video.directory)
        self.video_combo.clear()
        videos = list_videos(directory)
        for video in videos:
            size_mb = video.stat().st_size / 1e6
            self.video_combo.addItem(f"{video.name}  ({size_mb:.0f} MB)", str(video))
        if not videos:
            self.video_combo.addItem("(keine Videos gefunden)", None)
        log.info("%d Videos gefunden in %s", len(videos), directory)

    def _refresh_calibration_list(self) -> None:
        directory = self.cfg.resolve(self.cfg.calibration.directory)
        self.calibration_combo.clear()
        files = list_calibrations(directory)
        for path in files:
            self.calibration_combo.addItem(path.stem, str(path))
        if not files:
            self.calibration_combo.addItem("(keine Kalibrierung)", None)

    # ------------------------------------------------------------------ Video

    def _on_load_selected_video(self) -> None:
        path = self.video_combo.currentData()
        if path:
            self._load_video(Path(path))

    def _on_open_video_dialog(self) -> None:
        directory = str(self.cfg.resolve(self.cfg.video.directory))
        path, _ = QFileDialog.getOpenFileName(
            self, "Video oeffnen", directory, "Videos (*.mp4 *.mkv *.mov *.avi)"
        )
        if path:
            self._load_video(Path(path))

    def _load_video(self, path: Path) -> None:
        if self.player.load(path, self.cfg.video.playback_fps):
            self.statusBar().showMessage(f"Geladen: {path.name}", 4000)

    def _on_load_stream(self) -> None:
        """Verbindet mit einem Livestream statt einer Datei."""
        url = self.stream_edit.text().strip()
        if not url:
            return
        if not is_stream(url):
            QMessageBox.information(
                self, "Keine Stream-Adresse",
                "Das sieht nicht nach einer Stream-Adresse aus. Erwartet wird "
                "etwas wie https://... oder rtsp://... "
                "Fuer eine Datei den Weg darueber benutzen."
            )
            return

        # Eine YouTube-Adresse muss erst uebersetzt werden, und das dauert
        # spuerbar (gemessen 2026-09-10: 1,7 s). Der Player liest im
        # GUI-Faden, die Oberflaeche steht so lange -- ohne Hinweis sieht das
        # nach einem Absturz aus.
        if ist_youtube(url):
            self.statusBar().showMessage(
                "YouTube-Adresse wird uebersetzt -- das dauert einen Moment ...")
            QApplication.processEvents()
        else:
            self.statusBar().showMessage(f"Verbinde mit {url} ...")
        if self.player.load(url, self.cfg.video.playback_fps):
            self.statusBar().showMessage(f"Stream verbunden: {url}", 6000)
            # Im Stream gibt es nichts zu spulen -- der Schieber wuerde nur
            # Erwartungen wecken, die die Quelle nicht erfuellen kann.
            self._slider_erlaubt = False
            self._update_controls()
        else:
            self.statusBar().showMessage("Stream nicht erreichbar", 8000)

    def _on_video_opened(self, info: VideoInfo) -> None:
        duration = info.duration_s or 0

        # Kalibrierung gegen die Videomasse pruefen -- eine unpassende
        # Kalibrierung liefert sonst STILL falsche ROIs.
        warnungen = self.session.calibration.check_against_video(
            info.width, info.height)
        for warning in warnungen:
            log.warning(warning)

        # DIE AUFLOESUNG GEHOERT INS AUGE, nicht ins Log. Bei einem Stream sieht
        # man der Adresse nicht an, welche Fassung dahinter liegt -- eine
        # falsche Wahl faellt sonst erst auf, wenn die Analyse Unsinn liefert.
        # Deshalb: gross, und farblich beantwortet, ob sie zur Kalibrierung passt.
        hint = self.session.calibration.source_hint
        passt = not (hint.width and hint.width != info.width
                     or hint.height and hint.height != info.height)
        if not hint.width:
            farbe, urteil = "#bbb", "keine Kalibrierung geladen"
        elif passt:
            farbe, urteil = "#5cb85c", f"passt zur Kalibrierung ({hint.width}x{hint.height})"
        else:
            farbe, urteil = "#d9534f", (f"PASST NICHT -- Kalibrierung ist fuer "
                                        f"{hint.width}x{hint.height}")
        self.video_info_label.setText(
            f"{info.source_id}\n"
            f"<b>{info.width} x {info.height}</b>, {info.fps:.2f} fps\n"
            f"{info.frame_count or '?'} Frames, {duration:.1f} s"
        )
        self.resolution_label.setText(
            f"{info.width} x {info.height} -- {urteil}")
        self.resolution_label.setStyleSheet(
            f"background:{farbe}; color:#111; padding:4px; border-radius:3px;"
            "font-weight:bold;"
        )
        self.resolution_label.setVisible(True)

        self._slider_erlaubt = True
        self.position_slider.setRange(0, max(0, (info.frame_count or 1) - 1))
        self._update_controls()
        if not self.session.calibration.lanes:
            self.statusBar().showMessage(
                "Noch nicht kalibriert -- 'Automatisch kalibrieren' waehlt die "
                "Bauart aus und misst den Rest selbst.", 10000)

    # ------------------------------------------------- Automatisch kalibrieren

    def _tafeltypen(self) -> list:
        from ..calibration.board_library import lade_bibliothek
        return lade_bibliothek(
            self.cfg.resolve(self.cfg.calibration.boardtype_directory))

    def _on_auto_kalibrieren(self) -> None:
        """Bauart waehlen lassen und daraus die ganze Kalibrierung bauen.

        WOFUER -- Wunsch des Nutzers am 2026-09-10:

            "Automatisches Kalibrieren (klick) dann kommt ein Fenster 'Waehle
             dein Kegelboardtyp aus' ... oder man klickt auf eins und dann wird
             das gesucht"

        Der Rechner kann alles ausser einem: Er weiss nicht, welche Bahnnummer
        an der Wand steht. Genau danach -- und nur danach -- wird gefragt.
        """
        if self.player.current_frame is None:
            QMessageBox.information(
                self, "Kein Bild",
                "Erst ein Video oder einen Stream laden.")
            return

        typen = self._tafeltypen()
        dialog = TafeltypDialog(typen, self.cfg.calibration.lane_count,
                                self._korrekturen(typen), self)
        if dialog.exec() != QDialog.Accepted or dialog.ergebnis is None:
            return
        if dialog.ergebnis == "neu":
            self._on_board_aufnehmen()
            return
        gesucht = typen if dialog.ergebnis == "alle" else [dialog.ergebnis]
        ziel = dialog.anzahl.value()
        self._gewaehlte_korrektur = dialog.korrektur

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            suche, letztes = self._suche_tafeln(gesucht, ziel)
        finally:
            QApplication.restoreOverrideCursor()

        treffer = suche.ergebnis()
        if treffer is None:
            QMessageBox.warning(
                self, "Nichts gefunden",
                f"In {suche.bilder_gesehen} Bildern liess sich keine Tafel "
                f"dieser Bauart zuordnen.\n\n"
                "Moegliche Gruende: eine andere Bauart, ein sehr anderer "
                "Blickwinkel, oder die Stelle taugt nicht (jemand davor, "
                "Wiederholung eingeblendet).\n\n"
                "An eine andere Stelle springen und noch einmal versuchen -- "
                "oder die Tafel von Hand kalibrieren und als neue Bauart "
                "aufnehmen.")
            return

        if not self._bestaetige_treffer(treffer, letztes, ziel,
                                        suche.bilder_gesehen):
            return
        self._uebernimm_erkennung(treffer, letztes)

    def _suche_tafeln(self, typen: list, ziel: int):
        """Fuettert die laufende Suche, bis sie fertig ist oder die Zeit um ist.

        EIN STREAM HAT KEINE VERGANGENHEIT -- der Einwand des Nutzers am
        2026-09-10:

            "da kann er ja nicht einfach hin und herspringen ... eigentlich
             waere es besser, wenn er in den ersten 5-10 Sekunden das
             glattzieht ... und wenn es nach 20 Sekunden immer noch nicht alle
             Boards gefunden hat"

        Also nimmt die Suche entgegen, was kommt. GEMESSEN an acht Stellen der
        Aufzeichnung, ein Bild je 0,8 Sekunden Streamzeit: sechsmal alle vier
        Tafeln nach 2,4 bis 14,4 Sekunden (im Mittel 4,8), zweimal nur zwei
        beziehungsweise drei bis zur Zeitgrenze.

        Bei einer DATEI wird stattdessen gesprungen -- da gibt es eine
        Vergangenheit, und Springen ist schneller als Warten.
        """
        from ..calibration.board_library import LaufendeSuche

        kal = self.cfg.calibration
        suche = LaufendeSuche(typen, ziel_anzahl=ziel,
                              min_inlier=kal.boardtype_min_inlier,
                              anker_inlier=kal.boardtype_anchor_inlier,
                              min_frames=kal.boardtype_min_frames,
                              nachlauf=kal.boardtype_nachlauf_bilder,
                              min_guete=kal.boardmatch_min_guete)
        # WAS HIER PASSIERT, GEHOERT INS PROTOKOLL. Am 2026-09-11 scheiterte
        # die Suche im Livestream zweimal, und im Protokoll stand dazu nichts
        # -- 38 stumme Sekunden zwischen zwei Zeilen. Eine Handlung, die eine
        # halbe Minute dauert, muss eine Spur hinterlassen.
        log.info("Tafelsuche gestartet: %d Bauart(en), %d Tafeln erwartet, "
                 "Quelle %s, Zeitgrenze %.0f s", len(typen), ziel,
                 "Livestream" if self.player.is_live else "Datei",
                 kal.boardtype_live_timeout_s)
        beginn_gesamt = time.monotonic()
        # Das erste Bild kostet gemessen 4,3 s. Ohne diese Zeile steht die
        # Oberflaeche so lange stumm da, und stumm sieht aus wie haengt.
        self.statusBar().showMessage(
            f"Suche {ziel} Tafeln im Bild -- das erste Bild dauert ein paar "
            f"Sekunden ...")
        QApplication.processEvents()

        letztes = self.player.current_frame.image
        if not self.player.is_live:
            for bild in self._bilder_fuer_suche():
                letztes = bild
                suche.fuettere(bild)
                self._melde_suchstand(suche, ziel)
                if suche.genug:
                    break
            log.info("Tafelsuche beendet: %d von %d Tafeln aus %d Bildern "
                     "in %.1f s", suche.gefunden, ziel, suche.bilder_gesehen,
                     time.monotonic() - beginn_gesamt)
            return suche, letztes

        beginn = time.monotonic()
        while not suche.genug:
            verbraucht = time.monotonic() - beginn
            if verbraucht > kal.boardtype_live_timeout_s:
                log.warning("Tafelsuche: Zeitgrenze von %.0f s erreicht "
                            "(%d Bilder, %d von %d Tafeln)",
                            kal.boardtype_live_timeout_s, suche.bilder_gesehen,
                            suche.gefunden, ziel)
                break
            frame = self.player.current_frame
            if frame is not None:
                letztes = frame.image
                gestartet = time.monotonic()
                suche.fuettere(frame.image)
                # Je Bild mitschreiben: Am 2026-09-11 kostete das erste Bild
                # 20,5 s und das zweite 1,3 s -- ohne diese Zeile war das nicht
                # zu sehen, und die Zeitgrenze traf den Falschen.
                log.debug("Tafelsuche: Bild %d in %.1f s, %d Tafeln",
                          suche.bilder_gesehen, time.monotonic() - gestartet,
                          suche.gefunden)
                self._melde_suchstand(suche, ziel, verbraucht)
            ende = time.monotonic() + kal.boardtype_sample_wait_s
            while time.monotonic() < ende:
                QApplication.processEvents()
                time.sleep(0.02)
            self.player.step_forward()
        log.info("Tafelsuche beendet: %d von %d Tafeln aus %d Bildern in "
                 "%.1f s", suche.gefunden, ziel, suche.bilder_gesehen,
                 time.monotonic() - beginn_gesamt)
        return suche, letztes

    def _melde_suchstand(self, suche, ziel: int, sekunden: float = 0.0) -> None:
        """Haelt den Nutzer auf dem Laufenden -- eine Suche darf nicht stumm
        zwanzig Sekunden dauern.

        Nach dem vollstaendigen Fund sagt sie ausdruecklich, dass sie noch
        WEITERSAMMELT. Sonst sieht es aus, als haenge sie: Alle Tafeln stehen
        da, und trotzdem passiert nichts.
        """
        zeit = f", {sekunden:.0f} s" if sekunden else ""
        stand = ("alle gefunden, sammle fuer die Genauigkeit weiter"
                 if suche.fertig else f"{suche.gefunden} von {ziel}")
        self.statusBar().showMessage(
            f"Suche Tafeln: {stand} ({suche.bilder_gesehen} Bilder{zeit})")
        QApplication.processEvents()

    def _bestaetige_treffer(self, treffer, bild, ziel: int,
                            bilder: int) -> bool:
        """Zeigt die entzerrten Tafeln MIT ROIs und fragt, ob sie sitzen.

        WARUM MIT ROIs -- Einwand des Nutzers am 2026-09-10 nach dem ersten
        Livelauf:

            "ich brauche schon das die ROIs eingeblendet werden ... sonst
             kann ich ja nicht entscheiden, ob es sitzt oder nicht"

        Ein Rahmen um die Tafel beweist nur, dass sie gefunden wurde. Ob die
        Gruenlampe auf der Gruenlampe liegt, zeigt sich erst in der entzerrten
        Tafel: Im Vollbild misst eine Tafel rund 160 Pixel, eine Lampen-ROI
        darin sechs.
        """
        from ..calibration.board_library import uebernimm
        from ..calibration.roi_preview import tafelmontage

        anzahl = len(treffer.treffer)
        if anzahl < ziel:
            kopf = (f"<b>Nur {anzahl} von {ziel} Tafeln gefunden</b> "
                    f"(Bauart {treffer.typ.name}, {bilder} Bilder).<br>"
                    f"Uebernehmen und den Rest von Hand ergaenzen -- oder "
                    f"verwerfen und an anderer Stelle noch einmal suchen.")
        else:
            kopf = (f"<b>{anzahl} Tafeln gefunden</b> "
                    f"(Bauart {treffer.typ.name}, {bilder} Bilder, "
                    f"{treffer.merkmale} tragende Merkmale).")
        # Vorschau mit vorlaeufigen Bahnnummern 1..n -- die echten werden
        # erst nach der Bestaetigung abgefragt, und fuer das Bild sind sie
        # ohne Belang. MIT Feinschliff, denn beurteilt werden soll das, was
        # danach auch gemessen wird.
        kal_cfg = self.cfg.calibration
        vorschau = uebernimm(
            treffer, list(range(1, anzahl + 1)), bild,
            feinschliff=kal_cfg.roi_feinschliff,
            feinschliff_weite=kal_cfg.roi_feinschliff_weite,
            feinschliff_min_pixel=kal_cfg.roi_feinschliff_min_pixel,
            feinschliff_max_versatz=kal_cfg.roi_feinschliff_max_versatz)
        return TrefferDialog(zeichne_treffer(bild, treffer.treffer),
                             tafelmontage(bild, vorschau.lanes),
                             kopf, self).exec() == QDialog.Accepted

    def _bilder_fuer_suche(self) -> list[np.ndarray]:
        """Sammelt mehrere Standbilder fuer die Suche.

        WARUM MEHRERE -- gemessen 2026-09-10 ueber 16 Stichproben eines
        Spiels: Ein einzelnes Bild lieferte nur einmal alle vier Tafeln,
        fuenfmal gar keine. Brennende Kegellampen und wechselnde Ziffern
        veraendern genau die Merkmale, an denen der Abgleich haengt. Die LAGE
        der Tafeln aendert sich dagegen nicht -- deshalb ueber mehrere Bilder.

        Bei einer Datei wird gesprungen und hinterher an die alte Stelle
        zurueck. Bei einem Stream gibt es nichts zu springen: Da wird
        gewartet, bis der Leser neue Bilder geliefert hat. Eine ZWEITE
        Verbindung wird bewusst nicht geoeffnet -- die hat schon einmal die
        laufende Uebertragung zerlegt.
        """
        kal = self.cfg.calibration
        bilder: list[np.ndarray] = []
        if self.player.is_live:
            for _ in range(kal.boardtype_sample_frames):
                frame = self.player.current_frame
                if frame is not None:
                    bilder.append(frame.image.copy())
                ende = time.monotonic() + kal.boardtype_sample_wait_s
                while time.monotonic() < ende:
                    QApplication.processEvents()
                    time.sleep(0.02)
                self.player.step_forward()
            return bilder

        start = self.player.position
        info = self.player.info
        gesamt = (info.frame_count or 0) if info else 0
        for k in range(kal.boardtype_sample_frames):
            ziel = start + k * kal.boardtype_sample_step
            if gesamt and ziel >= gesamt:
                ziel = max(0, start - (ziel - gesamt) - 1)
            if k == 0 or self.player.seek(ziel):
                frame = self.player.current_frame
                if frame is not None:
                    bilder.append(frame.image.copy())
        self.player.seek(start)
        return bilder

    def _uebernimm_erkennung(self, treffer, bild=None) -> None:
        """Fragt die Bahnnummern ab und setzt die Kalibrierung."""
        from ..calibration.board_library import uebernimm

        anzahl = len(treffer.treffer)
        einzeln = ", ".join(str(t.inlier) for t in treffer.treffer)
        vorschlag = " ".join(str(i) for i in range(1, anzahl + 1))
        text, ok = QInputDialog.getText(
            self, "Bahnnummern",
            f"Bauart {treffer.typ.name}: {anzahl} Tafeln gefunden "
            f"({einzeln} tragende Merkmale), von links nach rechts.\n\n"
            f"Welche Bahnnummern tragen sie?", text=vorschlag)
        if not ok:
            return
        teile = text.replace(",", " ").split()
        if len(teile) != anzahl or not all(t.isdigit() for t in teile):
            QMessageBox.warning(self, "Eingabe passt nicht",
                                f"{anzahl} Zahlen erwartet, durch Leerzeichen "
                                f"getrennt.")
            return

        kal = self.cfg.calibration
        self.session.calibration = uebernimm(
            treffer, [int(t) for t in teile], bild,
            quelle=ohne_zugangsdaten(self.player.source_id or ""),
            feinschliff=kal.roi_feinschliff,
            feinschliff_weite=kal.roi_feinschliff_weite,
            feinschliff_min_pixel=kal.roi_feinschliff_min_pixel,
            feinschliff_max_versatz=kal.roi_feinschliff_max_versatz)
        # GEMERKTE FEINKORREKTUR, falls im Bauart-Fenster gewaehlt. Sie liegt
        # AUF dem Ergebnis der Suche -- der Feinschliff hat da schon getan, was
        # sich messen laesst; hier kommt dazu, was ein Mensch gesehen hat.
        korrigiert = 0
        if self._gewaehlte_korrektur is not None:
            from ..calibration.korrekturen import wende_an
            korrigiert = wende_an(self.session.calibration,
                                  self._gewaehlte_korrektur)
        nullen = self._richte_an_nullen_aus(bild)
        self.session.active_lane = 1
        self._digit_shift_angewandt = (0, 0)
        self.digit_dx.setValue(0)
        self.digit_dy.setValue(0)
        self._refresh_active_lane_combo()
        self._refresh_lane_number_spin()
        self._rebuild_lane_panels()
        self._update_calibration_hint()
        # DIE ROIS MUESSEN SICHTBAR SEIN, sonst laesst sich nichts nachziehen.
        # Sie standen nach der automatischen Kalibrierung zwar in der Sitzung,
        # wurden aber nie ins Bild gezeichnet: "ich brauche die ROIs in der
        # Livepreview um sie dort noch hin und her zu schieben" (Nutzer,
        # 2026-09-10).
        self._redraw_overlays()
        zusatz = (f" {nullen} Ziffernfelder an den Nullen ausgerichtet."
                  if nullen else "")
        if korrigiert:
            zusatz += (f" Feinkorrektur '{self._gewaehlte_korrektur.name}' "
                       f"auf {korrigiert} Bereiche gelegt.")
        self.statusBar().showMessage(
            f"Bauart {treffer.typ.name} uebernommen, {anzahl} Bahnen.{zusatz} "
            f"Rahmen pruefen -- notfalls 'Ziffern verschieben'.", 12000)

    def _korrekturen(self, typen: list) -> dict:
        """Die gemerkten Feinkorrekturen zu allen bekannten Bauarten."""
        from ..calibration.korrekturen import lade
        ordner = self.cfg.resolve(self.cfg.calibration.boardtype_directory)
        return {typ.name: lade(ordner, typ.name) for typ in typen}

    def _on_korrektur_merken(self) -> None:
        """Merkt, was an dieser Anlage von Hand nachgezogen wurde.

        WOFUER -- Wunsch des Nutzers am 2026-09-11:

            "Am besten waere es, wenn sich der Code das merkt, und wenn das
             naechste Mal der Tafeltyp ausgewaehlt wird, dann schlaegt er
             automatisch vielleicht verschiedene Kalibrierungen vor."

        GEMERKT WIRD DER UNTERSCHIED ZUR BAUART, nicht die Kalibrierung. Die
        Tafelecken haengen an Kamera, Zoom und Blickwinkel und sind in der
        naechsten Halle wertlos; die Versaetze auf der Tafel beschreiben
        dagegen die ANLAGE und gelten wieder.
        """
        from ..calibration.korrekturen import (aus_vergleich, lade, speichere)

        if not self.session.calibration.lanes:
            QMessageBox.information(
                self, "Nichts zu merken",
                "Es ist noch keine Bahn kalibriert.")
            return
        typen = self._tafeltypen()
        if not typen:
            QMessageBox.information(
                self, "Keine Bauart",
                "Zum Merken wird die Bauart gebraucht, gegen die verglichen "
                "wird -- die Bibliothek ist leer.")
            return

        namen = [t.name for t in typen]
        gewaehlt, ok = QInputDialog.getItem(
            self, "Zu welcher Bauart?",
            "Verglichen wird gegen die Bereiche dieser Bauart:", namen, 0,
            False)
        if not ok:
            return
        typ = next(t for t in typen if t.name == gewaehlt)

        vorschlag = datetime.now().strftime("Anlage %d.%m. %H:%M")
        name, ok = QInputDialog.getText(
            self, "Feinkorrektur merken",
            "Name -- am besten die Halle oder die Anlage:", text=vorschlag)
        if not ok or not name.strip():
            return

        korrektur = aus_vergleich(typ.bahn.rois, self.session.calibration,
                                  name.strip())
        if not korrektur.tafeln:
            QMessageBox.information(
                self, "Kein Unterschied",
                f"Die Bereiche sitzen genau wie in der Bauart "
                f"{typ.name} -- es gibt nichts zu merken.")
            return

        ordner = self.cfg.resolve(self.cfg.calibration.boardtype_directory)
        vorhanden = [k for k in lade(ordner, typ.name)
                     if k.name != korrektur.name]
        speichere(ordner, typ.name, vorhanden + [korrektur])
        QMessageBox.information(
            self, "Gemerkt",
            f"<b>{korrektur.name}</b> steht jetzt bei der Bauart "
            f"{typ.name}.<br><br>"
            f"{korrektur.bereiche} Versaetze auf {len(korrektur.tafeln)} "
            f"Tafeln.<br><br>"
            f"Beim naechsten <b>Automatisch kalibrieren</b> steht sie unter "
            f"dieser Bauart zur Auswahl.")
        self.statusBar().showMessage(
            f"Feinkorrektur '{korrektur.name}' gemerkt "
            f"({korrektur.bereiche} Bereiche)", 8000)

    def _richte_an_nullen_aus(self, bild) -> int:
        """Verschiebt die Ziffernrahmen, bis die Nullen sicher gelesen werden.

        WOFUER -- Vorschlag des Nutzers am 2026-09-10:

            "wie waere es, wenn er Anfangs die Ziffern ganz unten verschiebt,
             bis er die 0en halbwegs sicher sieht?"

        Zu Spielbeginn steht auf der Tafel `000`, `0`, `0000` -- ein BEKANNTER
        Sollwert, kein geratener. Deshalb ist das keine Optimierung auf das
        eigene Ergebnis: Verschoben wird auf einen Inhalt, der unabhaengig
        feststeht.

        GEMESSEN 2026-09-10 am Hallenstream: angepasst an einem Bild, gemessen
        an acht spaeteren -- unlesbare Ziffernstellen 21,6 % -> 17,5 %.

        Zeigt die Tafel gerade keine Nullen, geschieht nichts. Das ist der
        Normalfall mitten im Spiel und kein Fehler.
        """
        if bild is None or not self.cfg.calibration.digit_zero_fit:
            return 0
        from ..calibration.digit_zero_fit import passe_an_nullen_an
        from ..calibration.geometry import PerspectiveTransform, Quad
        from ..detection.digit_reader import CalibratedDigitReader

        tafeln = {}
        for bahn in self.session.calibration.lanes:
            ecken = [(float(p[0]), float(p[1])) for p in bahn.quad]
            tafeln[bahn.lane_id] = PerspectiveTransform(
                Quad.from_points(ecken), self.cfg.calibration.warped_width,
                self.cfg.calibration.warped_height).warp(bild)
        bericht = passe_an_nullen_an(
            self.session.calibration, tafeln,
            CalibratedDigitReader(self.cfg.detection.digits))
        return sum(len(f) for f in bericht.values())

    def _on_board_aufnehmen(self) -> None:
        """Nimmt die aktive Bahn als neue Bauart in die Bibliothek auf.

        EINE BAUART IST KEINE HALLE. Dieselbe Anlage steht in vielen Vereinen;
        der Name soll deshalb die Anlage benennen, nicht den Ort.
        """
        from ..calibration.board_library import speichere_typ

        frame = self.player.current_frame
        if frame is None or not self.session.calibration.lanes:
            QMessageBox.information(
                self, "Erst eine Tafel vermessen",
                "Fuer eine neue Bauart wird ein Muster gebraucht.\n\n"
                "Mit <b>Kalibrierung starten</b> eine einzige Tafel "
                "vermessen -- Ecken, Lampen und Ziffern -- und danach hier "
                "wieder aufnehmen. Alle weiteren Tafeln dieser Bauart findet "
                "das Werkzeug dann ueberall selbst.")
            return

        name, ok = QInputDialog.getText(
            self, "Neue Bauart aufnehmen",
            "Name der BAUART (nicht der Halle), z. B. FUNK_klassisch:")
        name = name.strip().replace(" ", "_") if ok else ""
        if not name:
            return

        ordner = self.cfg.resolve(self.cfg.calibration.boardtype_directory)
        try:
            ziel = speichere_typ(ordner, name, frame.image,
                                 self.session.calibration,
                                 self.session.active_lane)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Nicht gespeichert", str(exc))
            return
        QMessageBox.information(
            self, "Bauart gemerkt",
            f"<b>{name}</b> steht jetzt in der Bibliothek "
            f"({ziel.name}).<br><br>"
            f"Beim naechsten <b>Automatisch kalibrieren</b> ist sie zur "
            f"Auswahl dabei -- auch in einer anderen Halle.")
        self.statusBar().showMessage(f"Bauart {name} aufgenommen", 8000)

    # ----------------------------------------------------- Nachkalibrieren

    def _on_nachkalibrieren(self) -> None:
        """Wartet auf den Klick in die Tafel, die nachgezogen werden soll.

        WOFUER -- Wunsch des Nutzers am 2026-09-11:

            "ich brauche einen Button 'Nachkalibrieren' ... an dem ich jedes
             Board das ich aendern will anklicken kann, das wird mir gross
             gezeigt und ich kann die ROIs anpassen"

        WARUM NICHT EINE AUSWAHLLISTE: Welche Tafel schief sitzt, sieht man im
        Bild -- ihre Nummer kennt man deshalb noch lange nicht. Die Liste
        zwaenge zu einer Uebersetzung, die das Auge gar nicht leistet.
        """
        bahnen = self.session.calibration.lanes
        if not bahnen:
            QMessageBox.information(
                self, "Nichts zu ziehen",
                "Es ist noch keine Bahn kalibriert -- erst "
                "'Automatisch kalibrieren'.")
            return
        if self._bild_zum_nachziehen() is None:
            QMessageBox.information(
                self, "Kein Bild",
                "Erst ein Video oder einen Stream laden.")
            return

        if len(bahnen) == 1:
            self._oeffne_tafel_editor(bahnen[0])
            return

        # ZIEHEN AUS. Waehrend der Auswahl bedeutet ein Klick "diese Tafel" --
        # bliebe das Ziehen an, griffe er den Bereich darunter und verschoebe
        # ihn, statt die Tafel zu oeffnen.
        self._nachkal_auswahl = True
        self.video_view.set_drag_enabled(False)
        hinweis = ("Tafel anklicken, die nachgezogen werden soll "
                   "(Esc bricht ab)")
        self.calibration_hint.setText(hinweis)
        self.video_view.set_status_text(hinweis)
        self.statusBar().showMessage(hinweis)

    def _beende_nachkal_auswahl(self) -> None:
        if not self._nachkal_auswahl:
            return
        self._nachkal_auswahl = False
        self.video_view.set_status_text("")
        self._update_calibration_hint()

    def _bild_zum_nachziehen(self) -> np.ndarray | None:
        """Das aktuellste Bild -- aus der Wiedergabe oder aus der Analyse.

        Waehrend der Analyse ist der Player geschlossen; das Bild kommt dann
        aus dem Worker (`_current_frame`). Nachziehen soll auch dann gehen:
        Genau im Lauf faellt auf, dass eine Tafel nicht sitzt.
        """
        # REIHENFOLGE NACH FRISCHE, nicht nach Bequemlichkeit.
        #
        # Waehrend einer Analyse ist der Player geschlossen -- sein
        # `current_frame` haelt aber das Bild von VOR dem Start und ist damit
        # beliebig alt. Wer es zuerst fragt, bekommt fuer immer dasselbe.
        if self._analyse_aktiv and self._analyse_bild is not None:
            return self._analyse_bild
        if self.player.is_loaded and self.player.current_frame is not None:
            return self.player.current_frame.image
        if self._current_frame is not None:
            return self._current_frame.image
        return None

    def _springe_frames(self, schritt: int):
        """Holt ein anderes Bild fuer den Tafeleditor.

        DER STREAM IST DER ERNSTFALL, nicht die Datei. Der Nutzer dazu
        (2026-09-17): *"Das wird spaeter im Livestream alles passieren
        muessen, wir koennen keine 'Aufzeichnung' bemuehen.... Dann muessen
        wir halt sagen, dass Frame, welches in dem Moment gueltig ist, wo der
        Nutzer auf Nachkalibrieren klickt muss genommen werden."*

        Daraus folgen zwei verschiedene Faehigkeiten:

            Datei   vor UND zurueck, gezielt um `schritt` Frames
            Stream  nur VORWAERTS -- "gib mir das neueste Bild". Zu einem
                    vergangenen Frame gibt es keinen Weg zurueck, und so zu
                    tun, als gaebe es ihn, waere schlimmer als die Einschraenkung.

        Eingefroren ist in beiden Faellen das Bild vom Moment des Oeffnens;
        gewechselt wird nur auf Wunsch.

        Returns:
            (Bild, Frame-Nummer) -- die Nummer ist None, wenn die Quelle
            keine kennt. (None, None), wenn kein Bild zu holen war.
        """
        if self._analyse_aktiv:
            # Waehrend eines Laufs liefert der Worker das jeweils neueste Bild
            # -- vorwaerts, wie beim Stream. Die Framenummer kennt er, also
            # geht sie mit: Sie ist der Beleg, dass sich wirklich etwas
            # geaendert hat.
            bild = self._bild_zum_nachziehen()
            if bild is None:
                return None, None
            return bild, self._analyse_bild_index

        if not self.player.is_loaded:
            bild = self._bild_zum_nachziehen()
            return (bild, None) if bild is not None else (None, None)

        if self.player.is_live:
            # Nur vorwaerts. Ein Rueckwaertsschritt wird nicht heimlich zu
            # einem Vorwaertsschritt -- der Aufrufer soll es sagen koennen.
            if schritt < 0:
                return None, None
            bild = self._bild_zum_nachziehen()
            return (bild, None) if bild is not None else (None, None)

        ziel = max(0, self.player.position + schritt)
        if not self.player.seek(ziel):
            return None, None
        frame = self.player.current_frame
        if frame is None:
            return None, None
        return frame.image, self.player.position

    def _tafel_unter(self, x: float, y: float):
        """Welche Tafel liegt unter dem Klick? None, wenn keine."""
        import cv2
        for lane in self.session.calibration.lanes:
            ecken = np.asarray(lane.quad, dtype=np.float32)
            if cv2.pointPolygonTest(ecken, (float(x), float(y)), False) >= 0:
                return lane
        return None

    def _oeffne_tafel_editor(self, lane) -> None:
        """Zeigt eine Tafel entzerrt und gross, mit ziehbaren Bereichen."""
        from .board_editor import TafelEditorDialog

        bild = self._bild_zum_nachziehen()
        if bild is None:
            return
        # BEI EINEM STREAM NICHT ANHALTEN. Der Player holt neue Bilder nur,
        # solange seine Wiedergabe laeuft -- angehalten stuende im Dialog
        # dieselbe Anzeige wie vor fuenf Minuten, und ob eine Ziffernbox sitzt,
        # entscheidet sich an wechselnden Ziffern. Bei einer Datei ist das
        # Anhalten dagegen richtig: Dort laeuft sonst das Spiel weiter, waehrend
        # man zieht.
        if not self.player.is_live:
            self.player.pause()
        dialog = TafelEditorDialog(
            lane, bild,
            tafeln=len(self.session.calibration.lanes),
            bild_quelle=self._bild_zum_nachziehen,
            springer=self._springe_frames,
            # Rueckwaerts nur, wenn es eine Datei ist. Beim Stream gibt es
            # kein vergangenes Frame (siehe `_springe_frames`).
            rueckwaerts=(not self._analyse_aktiv
                         and self.player.is_loaded
                         and not self.player.is_live),
            parent=self)
        if dialog.exec() != QDialog.Accepted:
            self.statusBar().showMessage("Nachkalibrieren abgebrochen", 3000)
            return

        ziele = (self.session.calibration.lanes if dialog.auf_alle else [lane])
        for ziel in ziele:
            for roi in dialog.rois:
                ziel.set_roi(roi.model_copy(deep=True))
        self._redraw_overlays()
        self._update_calibration_hint()
        self._reiche_kalibrierung_weiter()
        wohin = (f"alle {len(ziele)} Tafeln" if dialog.auf_alle
                 else f"Bahn {lane.display_number}")
        log.info("Nachkalibriert: %d Bereiche auf %s", len(dialog.rois), wohin)
        self.statusBar().showMessage(
            f"{len(dialog.rois)} Bereiche auf {wohin} uebernommen -- "
            "noch nicht gespeichert", 8000)

    def _setze_position(self, index: int, gesamt: int,
                        sekunden: float) -> None:
        """Die eine Stelle, an der die Positionsanzeige geschrieben wird.

        Vorher stand sie an zwei Stellen -- eine fuer die Wiedergabe, eine fuer
        die Analyse -- und die zweite rechnete die Sekunden aus einem Player,
        den die Analyse gerade geschlossen hatte.
        """
        rest = f" / {gesamt}" if gesamt else ""
        self.position_label.setText(
            f"Frame {index}{rest}    {als_uhrzeit(sekunden)}  "
            f"({sekunden:.0f} s)")
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(index)
        self._update_overlay_text()

    def _on_player_error(self, message: str) -> None:
        QMessageBox.critical(self, "Videofehler", message)
        self.statusBar().showMessage(f"Fehler: {message}", 8000)

    def _on_frame(self, frame: Frame) -> None:
        # Waehrend der Analyse gehoert die Anzeige der Analyse. Die gesperrten
        # Bedienelemente allein genuegen als Schutz nicht: Der Player kann auch
        # von anderer Stelle einen Frame liefern, und ein einziger davon
        # reisst das Bild an eine voellig andere Stelle der Aufnahme.
        if self._analyse_aktiv:
            return
        self._current_frame = frame
        self.video_view.set_frame(frame.image)

        info = self.player.info
        total = (info.frame_count or 0) if info else 0
        self._setze_position(frame.index, total, frame.timestamp)

    # ------------------------------------------------------------ Kalibrierung


    def _on_zoom_step(self, factor: float) -> None:
        """Zoomt um einen festen Faktor, verankert in der Bildmitte."""
        self.video_view.set_zoom(self.video_view.zoom * factor)

    def _zoom_to_lane(self, lane_id: int) -> None:
        """Zoomt auf die Anzeigetafel einer Bahn.

        Ohne das waere das Setzen der ROIs kaum moeglich: Eine Tafel misst rund
        160x155 px im Originalframe, eine einzelne Kegellampe darin etwa 12 px --
        im eingepassten Video sind das wenige Bildschirmpixel.
        """
        lane = self.session.calibration.get_lane(lane_id)
        if lane is None:
            return
        xs = [p[0] for p in lane.quad]
        ys = [p[1] for p in lane.quad]
        self.video_view.zoom_to_frame_rect(
            min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
        )


    def _on_start_guide(self) -> None:
        """Startet die gefuehrte Kalibrierung bei Bahn 1."""
        if self._current_frame is None:
            QMessageBox.information(
                self, "Kein Bild",
                "Bitte zuerst ein Video oder einen Stream laden.")
            return
        self.player.pause()
        self.session.start_guide(self.cfg.calibration.lane_count)
        self._update_calibration_hint()
        self._redraw_overlays()

    def _guide_pruefen(self) -> None:
        """Rueckt die Fuehrung vor, sobald ein Schritt fertig ist.

        Der laufende Schritt meldet sich ueber `session.step`: Steht er wieder
        auf EDIT_ROIS, ist er abgeschlossen.
        """
        if not self.session.guide_active:
            return
        if self.session.step is not CalibrationStep.EDIT_ROIS:
            return
        self.session.guide_advance()
        if self.session.guide_lane:
            self._zoom_to_lane(self.session.guide_lane)
        self._update_calibration_hint()
        self._redraw_overlays()


    def _on_skip_roi(self) -> None:
        if self.session.step is CalibrationStep.PICK_ROIS:
            self.session.skip_roi()
            self._update_calibration_hint()

    def _on_select_single_roi(self, index: int) -> None:
        name = self.roi_combo.itemData(index)
        if not name or self.session.active_lane is None:
            return
        self.player.pause()
        if self.session.select_roi(name):
            self._update_calibration_hint()
        # Auswahl zuruecksetzen, damit dieselbe ROI erneut waehlbar bleibt
        self.roi_combo.blockSignals(True)
        self.roi_combo.setCurrentIndex(0)
        self.roi_combo.blockSignals(False)

    def _on_drag_corner(self, lane_id: int, index: int,
                        x: float, y: float) -> None:
        """Eine Tafelecke ziehen. Die ROIs wandern mit -- sie sind normiert."""
        if self.session.move_quad_corner(lane_id, index, x, y):
            self._redraw_overlays()

    def _on_drag_roi(self, lane_id: int, name: str, x: float, y: float) -> None:
        if self.session.move_roi(lane_id, name, x, y):
            self._redraw_overlays()

    def _on_resize_roi(self, lane_id: int, name: str, kante: str,
                       x: float, y: float) -> None:
        """Einen Rand oder eine Ecke eines Bereichs verziehen."""
        if self.session.resize_roi(lane_id, name, kante, x, y):
            self._redraw_overlays()

    def _on_drag_finished(self) -> None:
        """Nach dem Loslassen pruefen -- waehrend des Ziehens waere jede
        Zwischenlage kurzzeitig ungueltig."""
        for lane in self.session.calibration.lanes:
            ok, meldung = self.session.validate_quad(lane.lane_id)
            if not ok:
                self.statusBar().showMessage(
                    f"Bahn {lane.display_number}: {meldung}", 6000)
                return
        self._redraw_overlays()
        self.statusBar().showMessage("Kalibrierung angepasst", 2000)
        self._reiche_kalibrierung_weiter()

    def _reiche_kalibrierung_weiter(self) -> None:
        """Gibt nachgezogene Bereiche an eine LAUFENDE Analyse weiter.

        WOFUER -- Befund des Nutzers am 2026-09-11:

            "wenn man die ROIs im Livestream verschiebt, aendert sich ja gar
             nichts... es lief einfach weiter, als haette ich nichts geaendert"

        Und niemand konnte das sehen. Deshalb geht die Aenderung jetzt in den
        Lauf hinein UND in die Statuszeile -- eine Aenderung, die nichts
        bewirkt, muss das wenigstens sagen.
        """
        if not (self._analyse_aktiv and self._worker is not None):
            return
        self._worker.uebernimm_kalibrierung(self.session.calibration)
        self.statusBar().showMessage(
            "Aenderung an die laufende Analyse uebergeben -- die mitlaufenden "
            "Schwellen der betroffenen Bahn beginnen von vorn (rund eine "
            "Minute).", 8000)

    def _on_video_clicked(self, x: float, y: float) -> None:
        # VOR ALLEM ANDEREN: Wurde 'Nachkalibrieren' gedrueckt, waehlt dieser
        # Klick die Tafel aus -- er setzt keinen Punkt und schiebt nichts.
        if self._nachkal_auswahl:
            lane = self._tafel_unter(x, y)
            if lane is None:
                self.statusBar().showMessage(
                    "Daneben -- bitte in eine der eingerahmten Tafeln "
                    "klicken (Esc bricht ab)", 4000)
                return
            self._beende_nachkal_auswahl()
            self._oeffne_tafel_editor(lane)
            return

        if self.session.step is CalibrationStep.FRAME_DIGITS:
            done = self.session.frame_digit(x, y)
            self.video_view.set_pending_points(
                self.session.active_lane, self.session.pending_points
            )
            self._redraw_overlays()
            if done:
                self.statusBar().showMessage(
                    f"Bahn {self.session.active_lane}: alle Ziffern eingerahmt", 5000
                )
                self._guide_pruefen()
            self._update_calibration_hint()
            return

        if self.session.step is CalibrationStep.PICK_ROIS:
            done = self.session.place_roi(x, y)
            self._redraw_overlays()
            if done:
                self.statusBar().showMessage(
                    f"Bahn {self.session.active_lane}: alle Bereiche gesetzt", 4000
                )
                self._guide_pruefen()
            self._update_calibration_hint()
            return

        if self.session.step is not CalibrationStep.PICK_CORNERS:
            return

        complete = self.session.add_point(x, y)
        self.video_view.set_pending_points(self.session.active_lane,
                                           self.session.pending_points)

        if complete:
            ok, message = self.session.try_commit()
            if ok:
                info = self.player.info
                if info:
                    self.session.set_source_hint(info.width, info.height, info.source_id)
                self.statusBar().showMessage(
                    message + " -- jetzt 'Bereiche anklicken' fuer die Raute", 6000
                )
                # Panels an die neue Kalibrierung anpassen -- sonst zeigen sie
                # noch die Platzhalter-Nummern, und erkannte Wuerfe faenden kein
                # Ziel.
                self._rebuild_lane_panels()
                self._refresh_active_lane_combo()
                # Direkt auf die frisch kalibrierte Tafel zoomen
                if self.session.active_lane is not None:
                    self._zoom_to_lane(self.session.active_lane)
                self._guide_pruefen()
            else:
                QMessageBox.warning(self, "Kalibrierung fehlgeschlagen", message)
                # Punkte behalten, damit der Nutzer einzeln korrigieren kann
                self.session.step = CalibrationStep.PICK_CORNERS
            self.video_view.set_pending_points(None, self.session.pending_points)
            self._redraw_overlays()

        self._update_calibration_hint()

    def _on_undo_point(self) -> None:
        if self.session.undo_point():
            self.video_view.set_pending_points(self.session.active_lane,
                                               self.session.pending_points)
            self._update_calibration_hint()

    def _on_cancel_calibration(self) -> None:
        # Esc muss auch aus der Tafelauswahl herausfuehren -- sonst bleibt die
        # Oberflaeche stumm im Wartezustand, in dem kein Klick mehr das tut,
        # was er sonst tut.
        self._beende_nachkal_auswahl()
        self.session.cancel()
        self.video_view.set_pending_points(None, [])
        self._update_calibration_hint()

    def _update_calibration_hint(self) -> None:
        label = self.session.next_corner_label
        roi_hint = self.session.current_roi_label

        # Die Tafelauswahl hat Vorrang: Sie schaltet das Ziehen ab, und jeder
        # andere Zweig dieser Methode schaltet es wieder ein. Ohne diese
        # Abfrage genuegte ein beliebiges Ereignis, um den Klick wieder zum
        # Ziehen zu machen -- die Auswahl waere zufaellig kaputt.
        if self._nachkal_auswahl:
            self.video_view.set_drag_enabled(False)
            return

        # Waehrend der Fuehrung sagt sie, was zu tun ist -- ein Satz statt
        # dreier Bedienelemente, zwischen denen man selbst waehlen muss.
        if self.session.guide_step is not GuideStep.AUS:
            self.calibration_hint.setText(self.session.guide_hint)
            self.video_view.set_status_text(self.session.guide_hint)
            self.video_view.set_drag_enabled(
                self.session.step in (CalibrationStep.IDLE,
                                      CalibrationStep.EDIT_ROIS))
            return

        # Ziehen und Setzen schliessen sich aus. Solange etwas gesetzt wird,
        # bedeutet ein Klick "hier hin" -- bliebe das Ziehen aktiv, griffe er
        # stattdessen den Bereich darunter, und da jede Ziffer innerhalb ihres
        # Gesamtfeldes liegt, waere keine Ziffer mehr einrahmbar.
        self.video_view.set_drag_enabled(
            self.session.step in (CalibrationStep.IDLE, CalibrationStep.EDIT_ROIS)
        )

        if label:
            self.calibration_hint.setText(
                f"Bahn {self.session.active_lane}:\n"
                f"Punkt {len(self.session.pending_points) + 1} von 4 -- "
                f"{label} anklicken"
            )
        elif self.session.step is CalibrationStep.FRAME_DIGITS and roi_hint:
            done, total = self.session.roi_progress
            ecke = self.session.digit_corner_label or ""
            self.calibration_hint.setText(
                f"Bahn {self.session.active_lane} — Ziffer {done + 1} von {total}\n"
                f"{roi_hint}\n"
                f"Ecke {ecke} anklicken"
            )
        elif roi_hint:
            done, total = self.session.roi_progress
            self.calibration_hint.setText(
                f"Bahn {self.session.active_lane} -- Bereich {done + 1} von {total}:\n"
                f"MITTE von \"{roi_hint}\" anklicken"
            )
        elif self.session.step is CalibrationStep.EDIT_ROIS:
            lane = self.session.calibration.get_lane(self.session.active_lane or 0)
            missing = len(lane.missing_rois()) if lane else 0
            self.calibration_hint.setText(
                f"Bahn {self.session.active_lane} kalibriert.\n"
                f"{len(lane.rois) if lane else 0} ROIs gesetzt"
                + (f", {missing} fehlen noch" if missing else "")
            )
        else:
            done = len(self.session.calibration.lanes)
            self.calibration_hint.setText(
                f"Bahn waehlen, dann 4 Ecken anklicken\n"
                f"({done} von {self.cfg.calibration.lane_count} Bahnen kalibriert)"
            )

    def _redraw_overlays(self) -> None:
        self.video_view.clear_overlays()
        cal_cfg = self.cfg.calibration

        for lane in self.session.calibration.lanes:
            # Dieselbe Beschriftung wie im Panel darunter
            label = (f"Bahn {lane.display_number}" if lane.display_number == lane.lane_id
                     else f"Bahn {lane.display_number} (Tafel {lane.lane_id})")
            self.video_view.set_lane_quad(
                lane.lane_id, [(p[0], p[1]) for p in lane.quad], label
            )

            try:
                transform = lane.transform(cal_cfg.warped_width, cal_cfg.warped_height)
            except GeometryError as exc:
                log.warning("Bahn %d: Transformation ungueltig: %s", lane.lane_id, exc)
                continue

            polygons: list[tuple[str, list[tuple[float, float]]]] = []
            for roi in lane.rois:
                if not roi.enabled:
                    continue
                x, y, w, h = roi.rect
                corners = np.array(
                    [[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float32
                )
                pts = transform.norm_to_frame(corners)
                polygons.append((roi.name, [(float(p[0]), float(p[1])) for p in pts]))
            self.video_view.set_lane_rois(lane.lane_id, polygons)

        self.video_view.set_pending_points(self.session.active_lane,
                                           self.session.pending_points)

    def _on_save_calibration(self) -> None:
        if not self.session.calibration.lanes:
            QMessageBox.information(self, "Nichts zu speichern",
                                    "Es wurde noch keine Bahn kalibriert.")
            return

        directory = self.cfg.resolve(self.cfg.calibration.directory)
        directory.mkdir(parents=True, exist_ok=True)
        default = self._calibration_path or (
            directory / f"kalibrierung_{datetime.now():%Y-%m-%d_%H%M}.json"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Kalibrierung speichern", str(default), "JSON (*.json)"
        )
        if not path:
            return

        self.session.calibration.name = Path(path).stem
        self.session.calibration.save(path)
        self._calibration_path = Path(path)
        self._refresh_calibration_list()
        self.statusBar().showMessage(f"Kalibrierung gespeichert: {Path(path).name}", 4000)

    def _on_load_calibration(self) -> None:
        path = self.calibration_combo.currentData()
        if not path:
            return
        try:
            self.session.calibration = Calibration.load(path)
        except (FileNotFoundError, ValueError) as exc:
            QMessageBox.critical(self, "Kalibrierung fehlerhaft", str(exc))
            return

        self._calibration_path = Path(path)
        self.session.cancel()
        self._refresh_active_lane_combo()

        info = self.player.info
        if info:
            for warning in self.session.calibration.check_against_video(
                info.width, info.height
            ):
                log.warning(warning)

        self._rebuild_lane_panels()
        self._redraw_overlays()
        self._update_calibration_hint()
        self.statusBar().showMessage(
            f"Kalibrierung geladen: {Path(path).name} "
            f"({len(self.session.calibration.lanes)} Bahnen)", 4000
        )

    # ------------------------------------------------------------------ Debug



    # --------------------------------------------------------- Live-Analyse

    def _on_toggle_analysis(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._stop_analysis()
        else:
            self._start_analysis()

    def _on_analysis_seeking(self, erreicht: int, ziel: int) -> None:
        """Zeigt das Vorspulen an.

        Ohne diese Rueckmeldung wirkt die Anwendung haengen: Bei einer Quelle,
        die nicht springen kann, dauert das Vorspulen auf eine spaete Stelle
        ueber eine Minute -- gemessen 77 Sekunden fuer Frame 11344.

        Beim SPRUNG gibt es keinen Zwischenstand: `seek` kehrt erst zurueck,
        wenn es fertig ist. Dann eine Prozentzahl zu zeigen waere gelogen --
        sie stand frueher die ganze Zeit auf 0 % und sah nach einem Absturz aus
        (gemeldet am 2026-09-07 an einem Stream ueber Netz).
        """
        if erreicht == SPRUNG_LAEUFT:
            text = f"springt zu Frame {ziel} ..."
        else:
            anteil = 100 * erreicht / max(1, ziel)
            text = f"spult vor ... {erreicht}/{ziel} ({anteil:.0f} %)"
        self.analysis_status.setText(text)
        self.statusBar().showMessage(
            f"Suche die Startposition -- {text}. Zum Abbrechen auf "
            f"'Analyse stoppen' klicken.")

    def _on_toggle_senden(self, aktiv: bool) -> None:
        """Schaltet den Versand um -- ohne die laufende Analyse zu stoeren."""
        if self._worker is not None:
            self._worker.set_sending(aktiv)
        self.statusBar().showMessage(
            "Versand an die Datenbank aktiv" if aktiv
            else "Versand pausiert -- es wird weiter ausgewertet und angezeigt",
            5000)

    def _start_analysis(self) -> None:
        if not self.player.is_loaded:
            QMessageBox.information(self, "Kein Video",
                                    "Bitte zuerst ein Video laden.")
            return

        calibration = self.session.calibration
        if not calibration.lanes:
            QMessageBox.information(
                self, "Keine Kalibrierung",
                "Bitte zuerst mindestens eine Bahn kalibrieren oder eine "
                "gespeicherte Kalibrierung laden."
            )
            return

        # VOR ALLEM ANDEREN merken. Bei einem Livestream wird der Player
        # gleich geschlossen, und danach ist `player.info` None -- die
        # Positionsanzeige haette dann keine Bildrate mehr und die Sekunden
        # stuenden still, waehrend die Frames weiterlaufen.
        self._analyse_info = self.player.info

        missing = [f"Bahn {l.lane_id}" for l in calibration.lanes
                   if l.get_roi("green_lamp") is None]
        if missing:
            QMessageBox.warning(
                self, "Gruene Lampe fehlt",
                "Ohne die gruene Lampe kann kein Wurf erkannt werden.\n\n"
                "Betroffen: " + ", ".join(missing)
            )
            return

        # WAS HIER PASSIEREN MUSS -- und warum nicht nur ein `pause()`:
        #
        # Der Worker liest seine EIGENE Videoquelle, und die Vorschau kommt ab
        # jetzt aus der Analyse (`_on_preview`). Die Frames des Players werden
        # waehrend der Analyse verworfen (`_on_frame` kehrt sofort zurueck).
        #
        # Bei einem Stream haelt `pause()` aber nur die ANZEIGE an -- der
        # Lesefaden holt absichtlich weiter Frames, damit die Verbindung nicht
        # weglaeuft. Bei einer Datei ist das harmlos. Bei einer Kamera nicht:
        # Dann laufen ZWEI volle Dekodierungen desselben Bildes, und beide
        # Verbindungen ringen um dieselbe Kamera.
        #
        # GEMESSEN 2026-09-08 an der Hallenkamera (2304x1296, h264): Ab dem
        # Moment, in dem die Analyse ihre Verbindung oeffnete, standen BEIDE
        # OpenCV-Faeden -- im Protokoll als `WARN:0` und `WARN:1`, beide alle
        # fuenf Sekunden mit "Stream timeout triggered". Die Analyse kam nicht
        # in Gang, die Vorschau blieb stehen.
        #
        # Deshalb wird die Verbindung des Players bei einem Stream GESCHLOSSEN,
        # nicht angehalten. Zu verlieren ist dabei nichts: An eine Stelle im
        # Livestream kann man ohnehin nicht zurueck. Nach der Analyse wird sie
        # in `_reset_analysis_button` wieder aufgebaut.
        video_path = self.player.source_id or ""
        war_live = self.player.is_live
        if war_live:
            log.info("Vorschauverbindung wird fuer die Dauer der Analyse "
                     "geschlossen -- zwei Verbindungen zur selben Kamera "
                     "blockieren sich gegenseitig.")
            self._vorschau_pfad = video_path
            self.player.close()
        else:
            self.player.pause()
        for panel in self.lane_panels.values():
            panel.clear_results()
        self._throw_count = 0

        # Ab der aktuellen Stelle, falls gewuenscht.
        #
        # BEI EINEM LIVESTREAM NICHT. Der Kommentar hier behauptete frueher,
        # das sei "wirkungslos" -- das war falsch, und es hat am 2026-09-08
        # einen Trainingsabend gekostet:
        #
        #     Sprung auf Frame 6081 nicht moeglich (Quelle steht bei 0)
        #     Kein Sprung moeglich -- es wird bis Frame 6081 vorgespult
        #
        # Der Zaehler des Players lief seit dem Laden mit. Bei 15 fps sind
        # 6081 Frames knapp sieben Minuten -- und in einem Livestream gibt es
        # diese Frames noch gar nicht. Der Worker haette sie in Echtzeit
        # abwarten muessen, waehrend im Saal gespielt wird.
        #
        # In einer Aufzeichnung ist das Vorspulen sinnvoll (Warmspielen
        # ueberspringen). In einer Live-Uebertragung ist "hier" immer jetzt.
        start_frame = 0
        if (self.chk_ab_hier.isChecked() and not war_live
                and self.player.current_frame is not None):
            start_frame = self.player.current_frame.index
        elif self.chk_ab_hier.isChecked() and war_live:
            log.info("Livestream: 'ab hier' wird uebergangen -- in einer "
                     "Live-Uebertragung ist der aktuelle Frame der Anfang.")

        # WELCHE BAHNEN DIESES GERAET UEBERNIMMT. Abgehakte Kaestchen werden
        # erfasst; nicht erfasst heisst auch: nicht gesendet, denn was nicht
        # gemessen wurde, kann nicht abgegeben werden. Alle angehakt = alle,
        # dann bleibt die Einstellung leer und alles verhaelt sich wie bisher.
        gewaehlt = [nr for nr, box in self.chk_bahnen.items() if box.isChecked()]
        alle = sorted(self.chk_bahnen)
        self.cfg.processing.lanes = [] if gewaehlt == alle else gewaehlt
        if self.cfg.processing.lanes:
            log.info("Dieses Geraet erfasst die Bahnen %s",
                     self.cfg.processing.lanes)

        self._worker = AnalysisWorker(video_path, calibration, self.cfg,
                                      start_frame=start_frame,
                                      sending_enabled=self.chk_senden.isChecked(),
                                      spielname=self.txt_spielname.text(),
                                      parent=self)
        self._worker.frame_processed.connect(self._on_frame_processed)
        self._worker.preview_ready.connect(self._on_preview)
        self._worker.progress.connect(self._on_analysis_progress)
        self._worker.seeking.connect(self._on_analysis_seeking)
        self._worker.finished_analysis.connect(self._on_analysis_finished)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.set_throttle_fps(self.speed_combo.currentData())
        self._worker.start()
        self._analyse_aktiv = True
        self._update_controls()

        self.btn_analyze.setText("Analyse stoppen")
        self.btn_analyze.setStyleSheet(
            "font-weight:bold; padding:6px; background:#8a2020; color:white;"
        )
        self.analysis_status.setText("laeuft...")
        log.info("Live-Analyse gestartet: %s", Path(video_path).name)

    def _stop_analysis(self) -> None:
        if self._worker is None:
            return
        self._worker.request_stop()
        # Begrenzt warten: Ein haengender Worker darf die Oberflaeche nicht
        # dauerhaft blockieren.
        if not self._worker.wait(3000):
            log.warning("Analyse-Thread reagiert nicht -- wird verworfen")
        self._reset_analysis_button()

    def _reset_analysis_button(self) -> None:
        # Hier endet die Analyse fuer die Oberflaeche -- ab jetzt darf die
        # Wiedergabe wieder ans Bild.
        self._analyse_aktiv = False
        # Ab jetzt liefert der Player wieder eigene Frames -- der Merker aus
        # der Analyse hat ausgedient.
        self._analyse_info = None
        self._vorschau_wieder_aufbauen()
        self._update_controls()

    def _vorschau_wieder_aufbauen(self) -> None:
        """Holt die Vorschau zurueck, die fuer die Analyse geschlossen wurde.

        Scheitert der Aufbau, bleibt die Oberflaeche ohne Bild -- aber sie
        bleibt bedienbar, und der Grund steht im Protokoll. Ein Fehler hier
        darf den gerade beendeten Lauf nicht nachtraeglich als Absturz
        erscheinen lassen.
        """
        if self._vorschau_pfad is None:
            return
        pfad, self._vorschau_pfad = self._vorschau_pfad, None
        log.info("Vorschauverbindung wird wieder aufgebaut: %s", pfad)
        if not self.player.load(pfad, self.cfg.video.playback_fps):
            log.warning("Vorschau konnte nicht wieder geoeffnet werden. "
                        "Die Quelle laesst sich ueber 'Laden' erneut oeffnen.")
        self.btn_analyze.setText("Analyse starten")
        self.btn_analyze.setStyleSheet(
            "font-weight:bold; padding:6px; background:#1e7d32; color:white;"
        )

    def _on_speed_changed(self, index: int) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.set_throttle_fps(self.speed_combo.itemData(index))

    def _on_check_calibration(self) -> None:
        """Prueft die Gruenlampen-ROIs und meldet Problembahnen konkret."""
        if not self.player.is_loaded or not self.session.calibration.lanes:
            QMessageBox.information(
                self, "Nicht moeglich",
                "Es muss ein Video geladen und mindestens eine Bahn kalibriert sein."
            )
            return

        self.player.pause()
        source = open_source(self.player.source_id or "", self.cfg)
        try:
            source.open()
            report = check_calibration(source, self.session.calibration, self.cfg)
        except VideoSourceError as exc:
            QMessageBox.critical(self, "Videofehler", str(exc))
            return
        finally:
            source.close()

        text = report.summary()
        self.analysis_status.setText(
            "Kalibrierung geprueft -- "
            + ("Probleme gefunden" if report.has_problems else "in Ordnung")
        )

        if report.has_problems:
            QMessageBox.warning(self, "Kalibrierung pruefen", text)
        else:
            QMessageBox.information(self, "Kalibrierung pruefen", text)

    def _panel_for_display_number(self, display_number: int):
        """Findet das Panel zu einer realen Bahnnummer.

        Die Wurfergebnisse tragen die REALE Bahnnummer (2-5), die Panels sind
        nach der Overlay-Position (1-4) abgelegt -- die Zuordnung darf nicht
        verwechselt werden.
        """
        for panel in self.lane_panels.values():
            if panel.display_number == display_number:
                return panel
        return None

    def _on_frame_processed(self, result: FrameResult) -> None:
        """Laeuft im GUI-Thread (Signal aus dem Worker)."""
        for observation in result.observations:
            panel = self.lane_panels.get(observation.lane_id)
            if panel is not None:
                panel.update_observation(observation)

        for event in result.events:
            if event.event in (EventType.GREEN_ON, EventType.GREEN_OFF,
                               EventType.THROW_CONFIRMED):
                log.info("%s", event.describe())

        # Erkannte Wuerfe in die Tabellen eintragen
        for throw in result.throws:
            panel = self._panel_for_display_number(throw.lane)
            if panel is None:
                # Darf nicht stillschweigend passieren: Der Wurf ist erkannt und
                # gebucht -- er wuerde sonst nur in der Oberflaeche fehlen, und
                # das saehe wie eine Erkennungsluecke aus.
                log.error("Bahn %d: kein Panel gefunden -- Wurf %d wird nicht "
                          "angezeigt. Panels: %s. Kalibrierung neu laden?",
                          throw.lane, throw.throw_number,
                          sorted(p.display_number for p in self.lane_panels.values()))
                self.statusBar().showMessage(
                    f"Wurf auf Bahn {throw.lane} erkannt, aber kein passendes "
                    f"Panel vorhanden", 8000)
            else:
                panel.add_throw(throw)
            self._throw_count += 1

        self._last_result = result

    def _on_preview(self, index: int, image) -> None:
        self.video_view.set_frame(image)
        # MERKEN, NICHT NUR ZEIGEN. Ohne das war das Nachkalibrieren waehrend
        # einer laufenden Analyse blind: `_current_frame` wird vom
        # Player-Handler bei `_analyse_aktiv` gar nicht mehr gesetzt, und
        # `player.current_frame` stand auf dem Bild von VOR dem Start. Der
        # Knopf "frisches Bild" lieferte deshalb immer dasselbe alte Bild
        # (Nutzerbefund 2026-09-17).
        self._analyse_bild = image
        self._analyse_bild_index = index
        # NICHT vom Player nehmen. Bei einem Livestream ist er fuer die Dauer
        # der Analyse GESCHLOSSEN -- `self.player.info` ist dann None, und die
        # Anzeige stand bei "Frame 12345 / 0    t = 0.00 s". Die Frames liefen,
        # die Sekunden nicht. Deshalb wird die Bildrate beim Start gemerkt.
        info = self._analyse_info or self.player.info
        total = (info.frame_count or 0) if info else 0
        fps = (info.fps if info and info.fps else 0.0)
        self._setze_position(index, total, index / fps if fps else 0.0)

    def _on_analysis_progress(self, current: int, total: int) -> None:
        percent = (current / total * 100.0) if total else 0.0
        fps_text = ""
        if self._last_result is not None and self._last_result.processing_ms > 0:
            fps_text = f" | {1000.0 / self._last_result.processing_ms:.0f} fps"
        self.analysis_status.setText(
            f"{percent:.0f} % ({current}/{total}){fps_text} | {self._throw_count} Wuerfe"
        )

    def _on_analysis_finished(self, summary: str) -> None:
        self._reset_analysis_button()
        self.analysis_status.setText(summary)
        self.statusBar().showMessage("Analyse abgeschlossen", 6000)
        log.info("Analyse abgeschlossen: %s", summary)

    def _on_analysis_error(self, message: str) -> None:
        self._reset_analysis_button()
        self.analysis_status.setText(f"Fehler: {message}")
        QMessageBox.critical(self, "Analysefehler", message)

    def _update_overlay_text(self) -> None:
        if not self.act_overlay.isChecked() or self._current_frame is None:
            self.video_view.set_status_text("")
            return
        frame = self._current_frame
        lanes = len(self.session.calibration.lanes)
        self.video_view.set_status_text(
            f"Frame {frame.index}   t={frame.timestamp:.2f}s\n"
            f"Bahnen kalibriert: {lanes}/{self.cfg.calibration.lane_count}"
        )

    def _update_controls(self) -> None:
        """Sperrt die Wiedergabe, solange die Analyse laeuft.

        WARUM: Waehrend der Analyse kommt das Bild aus dem Worker. Bleibt die
        Wiedergabe daneben bedienbar, malen ZWEI Quellen in dieselbe Anzeige --
        und weil beide an verschiedenen Stellen der Aufnahme stehen, springt
        das Bild zwischen ihnen hin und her.

        GEMESSEN am 2026-09-07 aus einer Bildschirmaufnahme des Nutzers: In der
        Statusleiste wechselten sich zwei Reihen ab, die BEIDE fortschritten --
        die Analyse (2880, 2895, 2900, ... 2949) und der Player rund 650 Frames
        dahinter (2230, 2234, 2282). Zugleich zeigte das Overlay durchgehend
        die Analyse. Ein Bild, zwei Schreiber.
        """
        laeuft = self._analyse_aktiv
        bedienbar = self.player.is_loaded and not laeuft
        for btn in (self.btn_play, self.btn_next, self.btn_prev):
            btn.setEnabled(bedienbar)
        # Der Schieber ist bei einem Stream ohnehin gesperrt -- deshalb wird
        # hier nicht blind wieder eingeschaltet, sondern nur, was vorher
        # erlaubt war.
        self.position_slider.setEnabled(self._slider_erlaubt and not laeuft)

    # -------------------------------------------------------------- Ereignisse

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        # Die Tastatur umgeht gesperrte Knoepfe. Ohne diese Abfrage liesse sich
        # die Wiedergabe mit der Leertaste mitten in der Analyse wieder
        # starten -- und genau das erzeugt die zwei Schreiber auf einem Bild.
        transport = (Qt.Key_Space, Qt.Key_Right, Qt.Key_Left)
        if key in transport and self._analyse_aktiv:
            self.statusBar().showMessage(
                "Die Wiedergabe ist waehrend der Analyse gesperrt -- das Bild "
                "kommt aus der Analyse.", 4000)
            return
        if key == Qt.Key_Space:
            self.player.toggle()
        elif key == Qt.Key_Right:
            self.player.step_forward()
        elif key == Qt.Key_Left:
            self.player.step_backward()
        elif key == Qt.Key_Escape:
            self._on_cancel_calibration()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        # Laufenden Analyse-Thread beenden, bevor das Fenster verschwindet --
        # sonst greift er auf geloeschte Widgets zu.
        if self._worker is not None and self._worker.isRunning():
            self._stop_analysis()
        # Datei-Handle freigeben -- unter Windows blockiert ein offenes
        # VideoCapture sonst das Verschieben oder Loeschen der Videodatei.
        self.player.close()
        log.info("Anwendung beendet")
        super().closeEvent(event)
