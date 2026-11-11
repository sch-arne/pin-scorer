"""Live-Anzeige einer Bahn.

Zeigt waehrend der Analyse den aktuellen Zustand: gruene Lampe, Zustandsmaschine,
gefallene Kegel als Raute, und die Wurftabelle.

Die Aufbereitung der Daten passiert in `analysis/`, hier wird nur dargestellt --
deshalb enthaelt diese Datei keine Auswertungslogik (siehe Skill `kegel-gui` §8).
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..analysis.lane_processor import LaneObservation
from ..models.throw import ThrowResult, ThrowStatus
from ..detection.state_machine import LaneState
from ..models.readings import LampState
from .video_view import lane_color

log = logging.getLogger(__name__)

# Kegel-Raute: (Spalte, Zeile) je Kegelnummer 1..9.
#
# Zeile 0 ist HINTEN, Zeile 4 ist VORN -- so, wie die Kamera die Bahn sieht.
# Kegel 1 steht vorn, Kegel 9 hinten (siehe `calibration.pin_number_mapping`,
# vom Nutzer festgelegt am 2026-09-01):
#
#          9
#       7     8
#    4    5     6
#       2     3
#          1
#
# FRUEHER stand hier Kegel 1 oben. Das war dieselbe Raute, nur mit der alten
# Nummerierung -- mit der neuen stuende die Anzeige auf dem Kopf.
PIN_LAYOUT: dict[int, tuple[float, int]] = {
    9: (2.0, 0),
    7: (1.0, 1), 8: (3.0, 1),
    4: (0.0, 2), 5: (2.0, 2), 6: (4.0, 2),
    2: (1.0, 3), 3: (3.0, 3),
    1: (2.0, 4),
}


# Die Ziffernfelder in der Reihenfolge, in der sie auf der TAFEL stehen --
# oben die beiden Displays, darunter die Zeile aus Wurfnummer, Kegelzahl und
# Gesamtsumme. Kurze Namen, weil die Zeile in ein schmales Panel muss.
# `total_a` faehrt nicht mehr mit (Nutzer, 2026-09-14: "irgendwie Quatsch fuer
# uns") -- es hat als einziges Feld keine Ziffernzellen kalibriert und geht in
# keine Pruefung ein. Die vier verbliebenen sind genau die, die auch als
# nullbare Ablesungen an die Datenbank gehen.
# Die Reihenfolge folgt der Tafel: oben links der Fehlwurfzaehler, unten die
# Zeile Wurfnummer / Kegel / Summe. Wer vergleicht, schaut abwechselnd auf Bild
# und Zeile -- dann muss dieselbe Zahl an derselben Stelle stehen.
ANZEIGEFELDER: tuple[tuple[str, str], ...] = (
    ("left_display", "Fehl"),
    ("throw_number", "Wurf"),
    ("pin_count", "Kegel"),
    ("total_b", "SummeB"),
)
LEER_ANZEIGE = "<span style='color:#666;'>Ziffern: –</span>"
# Ab dieser Sicherheit gilt eine Lesung als belastbar. Darunter wird sie grau
# gezeigt statt verschwiegen: Eine unsichere Lesung ist die interessanteste
# Auskunft fuer den, der den Leser beurteilen will.
SICHER_AB = 0.60


def anzeige_zeile(lesungen: dict) -> str:
    """Baut die Zeile 'was steht gerade auf der Tafel' fuer ein Bahnpanel.

    Ohne Qt und ohne Zustand -- damit pruefbar, ohne ein Fenster zu oeffnen.
    """
    if not lesungen:
        return LEER_ANZEIGE
    teile = []
    for name, kurz in ANZEIGEFELDER:
        lesung = lesungen.get(name)
        if lesung is None:
            continue
        text = lesung.text or "?"
        sicher = lesung.is_readable and lesung.confidence >= SICHER_AB
        farbe = "#ddd" if sicher else "#888"
        teile.append(f"<span style='color:#666;'>{kurz}</span> "
                     f"<span style='color:{farbe};'>{text}</span>")
    return "  ".join(teile) if teile else LEER_ANZEIGE


class PinDiagram(QWidget):
    """Zeichnet die neun Kegel als Raute. Gefallene Kegel werden hervorgehoben.

    Ein Zahlenwert allein ("5 Kegel") laesst sich beim Zuschauen kaum mit dem
    Video abgleichen -- das Muster dagegen sofort.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(80, 92)
        self._fallen: set[int] = set()
        self._unknown = True

    def set_pins(self, fallen: set[int] | None) -> None:
        self._unknown = fallen is None
        self._fallen = fallen or set()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        radius = 8
        step_x = (self.width() - 2 * radius - 4) / 4
        step_y = (self.height() - 2 * radius - 4) / 4

        for pin, (col, row) in PIN_LAYOUT.items():
            cx = int(radius + 2 + col * step_x)
            cy = int(radius + 2 + row * step_y)

            if self._unknown:
                painter.setBrush(QColor(70, 70, 70))
                painter.setPen(QColor(100, 100, 100))
            elif pin in self._fallen:
                # Gefallen = leuchtet, wie auf der echten Tafel
                painter.setBrush(QColor(255, 170, 60))
                painter.setPen(QColor(255, 210, 130))
            else:
                painter.setBrush(QColor(225, 225, 225))
                painter.setPen(QColor(150, 150, 150))

            painter.drawEllipse(cx - radius, cy - radius, 2 * radius, 2 * radius)

            painter.setPen(QColor(40, 40, 40) if pin in self._fallen
                           else QColor(90, 90, 90))
            painter.setFont(QFont("Segoe UI", 7, QFont.Bold))
            painter.drawText(cx - radius, cy - radius, 2 * radius, 2 * radius,
                             Qt.AlignCenter, str(pin))


class LanePanel(QGroupBox):
    """Vollstaendige Live-Anzeige einer Bahn."""

    # Kurze Ueberschriften: Vier Panels teilen sich die Fensterbreite,
    # lange Titel erzwingen sonst horizontales Scrollen.
    HEADERS = ("Nr", "Zyk", "Kegel", "Summe", "Status")

    def __init__(self, lane_id: int, display_number: int,
                 parent: QWidget | None = None) -> None:
        # Beide Nummern im Titel: Der Nutzer sieht im Video die Tafelposition
        # (1-4 von links), die Ergebnisse tragen aber die reale Bahnnummer.
        # Nur eine von beiden anzuzeigen fuehrt zwangslaeufig zu Verwechslungen.
        titel = (f"Bahn {display_number}" if display_number == lane_id
                 else f"Bahn {display_number}  (Tafel {lane_id} von links)")
        super().__init__(titel, parent)
        self.lane_id = lane_id
        self.display_number = display_number

        color = lane_color(lane_id)
        self.setStyleSheet(
            f"QGroupBox {{ border-top: 3px solid {color.name()}; margin-top: 6px; "
            f"font-weight: bold; }}"
            f"QGroupBox::title {{ subcontrol-origin: margin; left: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # --- Statuszeile ---
        status_row = QHBoxLayout()

        self.green_label = QLabel("GRUEN ?")
        self.green_label.setAlignment(Qt.AlignCenter)
        self.green_label.setMinimumWidth(84)
        self._set_green(LampState.UNKNOWN)
        status_row.addWidget(self.green_label)

        self.state_label = QLabel(LaneState.READY.value)
        self.state_label.setFont(QFont("Consolas", 8))
        self.state_label.setStyleSheet("color:#aaa;")
        status_row.addWidget(self.state_label, 1)
        layout.addLayout(status_row)

        # --- Kegelbild + Kennzahlen ---
        middle = QHBoxLayout()
        self.pin_diagram = PinDiagram()
        middle.addWidget(self.pin_diagram)

        numbers = QVBoxLayout()
        self.count_label = QLabel("–")
        self.count_label.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self.count_label.setAlignment(Qt.AlignCenter)
        numbers.addWidget(self.count_label)

        self.total_label = QLabel("Gesamt 0")
        self.total_label.setAlignment(Qt.AlignCenter)
        self.total_label.setStyleSheet("color:#888; font-size:11px;")
        numbers.addWidget(self.total_label)

        self.throw_label = QLabel("Wurf –")
        self.throw_label.setAlignment(Qt.AlignCenter)
        self.throw_label.setStyleSheet("color:#888; font-size:11px;")
        numbers.addWidget(self.throw_label)
        middle.addLayout(numbers, 1)
        layout.addLayout(middle)

        # --- Was der Ziffernleser GERADE sieht ---
        #
        # WOFUER -- Wunsch des Nutzers am 2026-09-11: "ich haette gerne, dass
        # dort auch steht, was er gerade an Ziffern erkannt hat. Also welche
        # Werte angeblich wo stehen. Das wuerde mir helfen bei der Evaluierung,
        # ob wir die Ziffern bald wieder reinnehmen."
        #
        # In der Anordnung der TAFEL, nicht alphabetisch: Wer vergleicht,
        # schaut abwechselnd auf Bild und Zeile -- dann muss dieselbe Zahl an
        # derselben Stelle stehen.
        self.digit_label = QLabel(LEER_ANZEIGE)
        self.digit_label.setFont(QFont("Consolas", 9))
        self.digit_label.setTextFormat(Qt.RichText)
        self.digit_label.setToolTip(
            "Was der Ziffernleser in diesem Augenblick liest. Grau = unsicher "
            "oder unlesbar.\n\nDiese Werte gehen in KEINE Zaehlung -- sie "
            "stehen hier nur, um den Leser beurteilen zu koennen.")
        layout.addWidget(self.digit_label)

        # --- Wurftabelle ---
        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setFont(QFont("Consolas", 8))
        # Spalten fuellen die Breite -- sonst ist die Status-Spalte nur ueber
        # einen Scrollbalken erreichbar, und genau sie muss auffallen.
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setFont(QFont("Segoe UI", 8))
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout.addWidget(self.table, 1)

    # ------------------------------------------------------------ Aktualisieren

    def update_observation(self, observation: LaneObservation) -> None:
        """Uebernimmt eine Momentaufnahme. Wird pro Frame aufgerufen."""
        self._set_green(observation.green.state, observation.green.score)
        self.state_label.setText(observation.state.value)

        if observation.pins is not None:
            self.pin_diagram.set_pins(set(observation.pins.pins))
            self.count_label.setText(str(observation.pins.count))
        else:
            self.pin_diagram.set_pins(None)
            self.count_label.setText("–")

        self.total_label.setText(f"Gesamt {observation.running_total}")
        self.throw_label.setText(
            f"Wurf {observation.throw_count}" if observation.throw_count else "Wurf –"
        )
        self.digit_label.setText(anzeige_zeile(observation.digits))

    def _set_green(self, state: LampState, score: float = 0.0) -> None:
        text, background, foreground = {
            LampState.ON: ("GRUEN AN", "#1e7d32", "#ffffff"),
            LampState.OFF: ("GRUEN AUS", "#5a1e1e", "#ffcccc"),
        }.get(state, ("GRUEN ?", "#3a3a3a", "#999999"))

        if score:
            text = f"{text}  {score:.0f}"
        self.green_label.setText(text)
        self.green_label.setStyleSheet(
            f"background:{background}; color:{foreground}; padding:3px; "
            f"border-radius:3px; font-weight:bold; font-size:11px;"
        )

    #: Farben je Status -- ein ERROR muss auf einen Blick auffallen
    STATUS_COLORS = {
        ThrowStatus.VALID: QColor(40, 90, 40),
        ThrowStatus.EMPTY: QColor(70, 70, 40),
        ThrowStatus.INVALID: QColor(100, 60, 30),
        ThrowStatus.ERROR: QColor(110, 40, 40),
        ThrowStatus.UNKNOWN: QColor(60, 60, 60),
    }

    def add_throw(self, throw: ThrowResult) -> None:
        """Haengt eine Wurfzeile an -- nur bei neuem Wurf, nicht pro Frame.

        Zeilen anhaengen statt die Tabelle neu aufzubauen: Bei 25 fps waere ein
        Neuaufbau je Frame nicht darstellbar (siehe Skill `kegel-gui`).
        """
        row = self.table.rowCount()
        self.table.insertRow(row)

        values = (throw.throw_number, throw.throw_number_in_series,
                  throw.pins_count, throw.running_total, throw.status.value)
        color = self.STATUS_COLORS.get(throw.status, QColor(60, 60, 60))

        for column, value in enumerate(values):
            item = QTableWidgetItem(str(value))
            item.setTextAlignment(Qt.AlignCenter)
            if column == len(values) - 1:
                item.setBackground(color)
                item.setForeground(QColor(240, 240, 240))
            # Die vollstaendige Begruendung als Tooltip -- Nachvollziehbarkeit
            # ohne die Tabelle zu ueberladen (Auftrag Paragraph 27)
            item.setToolTip(throw.explain())
            self.table.setItem(row, column, item)

        # ENTFERNT (2026-08-30, auf Wunsch des Nutzers): die Zwischensumme-Zeile
        # "Zyklus N: SUMME" am Zyklusende. Sie stiftete mehr Verwirrung als
        # Nutzen, weil `cycle_number` NICHT der Lauf zwischen zwei `000 0000`
        # ist, sondern der rechnerische Satz aus der gelesenen Wurfnummer
        # (`throws_per_cycle`, derzeit 15). Zwei verschiedene Dinge hiessen
        # gleich, und die Anzeige zeigte das unauffaelligere von beiden.
        # Die Zwischensumme steht weiterhin in `wuerfe.csv`.

        self.table.scrollToBottom()

    def clear_results(self) -> None:
        self.table.setRowCount(0)
        self.pin_diagram.set_pins(None)
        self.count_label.setText("–")
        self.total_label.setText("Gesamt 0")
        self.throw_label.setText("Wurf –")
        self._set_green(LampState.UNKNOWN)
