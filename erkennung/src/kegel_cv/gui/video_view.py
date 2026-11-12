"""Video-Anzeige mit Zoom, Overlays und Mausinteraktion.

Zwei Kernpunkte (siehe Skill `kegel-gui`):

1. Der Nutzer klickt auf ein SKALIERTES Bild, die Kalibrierung braucht
   ORIGINALPIXEL. Die Umrechnung liegt in `ViewTransform` -- ohne Qt und damit
   vollstaendig testbar.

2. **Zoom ist beim Kalibrieren Pflicht, nicht Komfort.** Eine Anzeigetafel misst
   rund 160x155 px im Originalframe; im eingepassten Video bleibt davon etwa ein
   Zehntel der Fensterbreite. Eine einzelne Kegellampe waere dann rund 5 Pixel
   gross -- nicht zielsicher anklickbar.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

from .view_transform import MAX_ZOOM, MIN_ZOOM, ViewTransform

log = logging.getLogger(__name__)

# Farben der vier Bahnen -- bewusst gut unterscheidbar, auch nebeneinander
LANE_COLORS = [
    QColor(255, 90, 90),    # Bahn 1 rot
    QColor(90, 200, 255),   # Bahn 2 blau
    QColor(120, 230, 120),  # Bahn 3 gruen
    QColor(255, 200, 80),   # Bahn 4 gelb
]


def lane_color(lane_id: int) -> QColor:
    return LANE_COLORS[(lane_id - 1) % len(LANE_COLORS)]


class VideoView(QWidget):
    """Zeigt Frames an, zeichnet Overlays und meldet Mausklicks in Frame-Koordinaten."""

    clicked = Signal(float, float)          # Frame-Koordinaten
    right_clicked = Signal(float, float)
    mouse_moved = Signal(float, float)
    dragged = Signal(float, float)          # bei gedrueckter linker Maustaste
    zoom_changed = Signal(float)

    # Gesetzte Punkte und Bereiche lassen sich ziehen. Ohne das muss man einen
    # danebengesetzten Eckpunkt ueber "Zurueck" abraeumen und die ganze Reihe
    # neu klicken -- bei vier Bahnen zu je vier Ecken und 17 Bereichen ist das
    # der Unterschied zwischen Nachjustieren und Neuanfangen.
    quad_corner_dragged = Signal(int, int, float, float)   # Bahn, Ecke, x, y
    roi_dragged = Signal(int, str, float, float)           # Bahn, Name, x, y
    # Einen RAND oder eine ECKE eines Bereichs verziehen statt ihn nur zu
    # verschieben. Eine Ziffernbox muss in der Groesse stimmen, nicht nur in
    # der Lage: Aus ihr ergeben sich die Segmentflaechen rein geometrisch.
    roi_resized = Signal(int, str, str, float, float)      # Bahn, Name, Kante, x, y
    drag_finished = Signal()

    # Griffe an einem Bereich. "move" ist die Flaeche, alles andere ein Rand
    # oder eine Ecke.
    KANTEN = ("tl", "t", "tr", "r", "br", "b", "bl", "l")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("background-color: #1e1e1e;")

        self._pixmap: QPixmap | None = None
        self._frame_size: tuple[int, int] = (0, 0)

        # Abbildung Widget <-> Frame inklusive Zoom (siehe view_transform.py)
        self.view = ViewTransform()
        self._panning = False
        self._pan_origin = QPointF()

        # Overlays
        self._quads: dict[int, list[tuple[float, float]]] = {}
        # Overlay-Position -> reale Bahnnummer. Ohne diese Zuordnung beschriftet
        # das Video "Bahn 1", waehrend dasselbe Ergebnis im Panel unter "Bahn 2"
        # steht -- eine Verwechslung mit Ansage.
        self._lane_labels: dict[int, str] = {}
        self._pending_points: list[tuple[float, float]] = []
        self._pending_lane: int | None = None
        self._rois: dict[int, list[tuple[str, list[tuple[float, float]]]]] = {}
        self._show_labels = True
        self._status_text = ""
        self._cursor_frame_pos: tuple[float, float] | None = None

        # Was gerade gezogen wird: ("quad", Bahn, Eckindex) oder ("roi", Bahn, Name)
        self._drag: tuple[str, int, object] | None = None
        # Ziehen ist nur erlaubt, wenn gerade NICHTS gesetzt wird.
        #
        # Sonst greift ein Klick den darunterliegenden Bereich, statt den Punkt
        # zu setzen -- und weil jede Ziffer INNERHALB ihres Gesamtfeldes liegt,
        # liesse sich keine einzige Ziffer mehr einrahmen. Genau das ist
        # passiert, als das Ziehen eingebaut wurde.
        self._drag_erlaubt = True
        # Trefferradius in WIDGET-Pixeln, nicht in Frame-Pixeln: Was zielsicher
        # greifbar ist, haengt am Bildschirm, nicht am Zoom. Bei achtfachem Zoom
        # waeren 10 Frame-Pixel eine handtellergrosse Flaeche.
        self._greifradius = 12.0

    # ---------------------------------------------------------------- Anzeige

    def set_frame(self, image: np.ndarray | None) -> None:
        """Zeigt einen BGR-Frame an (None loescht die Anzeige)."""
        if image is None:
            self._pixmap = None
            self._frame_size = (0, 0)
            self.update()
            return

        height, width = image.shape[:2]
        self._frame_size = (width, height)
        self.view.set_frame_size(width, height)

        rgb = np.ascontiguousarray(image[:, :, ::-1])   # BGR -> RGB
        # bytesPerLine explizit angeben, sonst zerreisst das Bild bei Breiten,
        # die nicht durch 4 teilbar sind. .copy() entkoppelt QImage vom
        # numpy-Puffer -- sonst zeigt Qt auf freigegebenen Speicher.
        qimage = QImage(rgb.data, width, height, 3 * width, QImage.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(qimage)
        self.update()

    def set_status_text(self, text: str) -> None:
        self._status_text = text
        self.update()

    def set_show_labels(self, show: bool) -> None:
        self._show_labels = show
        self.update()

    # --------------------------------------------------------------- Overlays

    def set_lane_quad(self, lane_id: int, points: list[tuple[float, float]] | None,
                      label: str | None = None) -> None:
        if points is None:
            self._quads.pop(lane_id, None)
            self._lane_labels.pop(lane_id, None)
        else:
            self._quads[lane_id] = list(points)
            self._lane_labels[lane_id] = label or f"Bahn {lane_id}"
        self.update()

    def set_pending_points(self, lane_id: int | None,
                           points: list[tuple[float, float]]) -> None:
        self._pending_lane = lane_id
        self._pending_points = list(points)
        self.update()

    def set_lane_rois(self, lane_id: int,
                      rois: list[tuple[str, list[tuple[float, float]]]]) -> None:
        self._rois[lane_id] = rois
        self.update()

    def clear_overlays(self) -> None:
        self._quads.clear()
        self._lane_labels.clear()
        self._rois.clear()
        self._pending_points.clear()
        self._pending_lane = None
        self.update()

    # ------------------------------------------------------------------ Zoom

    @property
    def zoom(self) -> float:
        return self.view.zoom

    def zoom_to_frame_rect(self, x: float, y: float, w: float, h: float) -> None:
        """Zoomt auf einen Bildbereich, etwa eine frisch kalibrierte Tafel."""
        self._update_transform()
        self.view.zoom_to_rect(x, y, w, h)
        self.zoom_changed.emit(self.view.zoom)
        self.update()

    def reset_zoom(self) -> None:
        self.view.reset()
        self.zoom_changed.emit(self.view.zoom)
        self.update()

    def set_zoom(self, zoom: float) -> None:
        self._update_transform()
        self.view.set_zoom(max(MIN_ZOOM, min(zoom, MAX_ZOOM)))
        self.zoom_changed.emit(self.view.zoom)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        """Mausrad zoomt am Zeiger -- der Punkt unter der Maus bleibt stehen.

        Ohne diese Verankerung wandert das Ziel beim Zoomen weg, und genau das
        macht das Anvisieren einer 5-px-Lampe unmoeglich.
        """
        if self._pixmap is None:
            return
        self._update_transform()
        steps = event.angleDelta().y() / 120.0
        if steps == 0:
            return
        position = event.position()
        self.view.zoom_at(position.x(), position.y(), 1.25 ** steps)
        self.zoom_changed.emit(self.view.zoom)
        self.update()
        event.accept()

    # ------------------------------------------------------- Koordinatenwechsel

    def widget_to_frame(self, pos: QPoint) -> tuple[float, float] | None:
        """Widget-Pixel -> Frame-Pixel. None, wenn ausserhalb des Bildes."""
        if self._pixmap is None:
            return None
        self._update_transform()
        x, y = self.view.widget_to_frame(pos.x(), pos.y())
        if not self.view.contains_frame_point(x, y):
            return None
        return x, y

    def frame_to_widget(self, x: float, y: float) -> QPoint:
        """Frame-Pixel -> Widget-Pixel.

        Die Abbildung wird HIER aktualisiert, nicht nur in `widget_to_frame`.
        Fehlte das, lieferte der erste Aufruf nach dem Anzeigen oder einer
        Groessenaenderung die Bildmitte -- die Widgetgroesse war der Abbildung
        noch unbekannt. Aufgefallen ist es, als ein Test das Fenster bediente,
        bevor Qt zum ersten Mal gezeichnet hatte: Der erste Klick landete
        reproduzierbar in der Mitte statt auf der angeklickten Ecke.
        """
        self._update_transform()
        wx, wy = self.view.frame_to_widget(x, y)
        return QPoint(int(wx), int(wy))

    def _update_transform(self) -> None:
        self.view.set_widget_size(self.width(), self.height())

    # ---------------------------------------------------------------- Zeichnen

    def paintEvent(self, event) -> None:  # noqa: N802  (Qt-Namenskonvention)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#1e1e1e"))

        if self._pixmap is None:
            painter.setPen(QColor("#888888"))
            painter.drawText(self.rect(), Qt.AlignCenter,
                             "Kein Video geladen\n\nDatei -> Video laden")
            return

        self._update_transform()

        frame_w, frame_h = self._frame_size
        left, top = self.view.frame_to_widget(0, 0)
        target = QRectF(left, top, frame_w * self.view.scale, frame_h * self.view.scale)

        # Beim Hineinzoomen bewusst KEINE Glaettung: Der Nutzer will die einzelnen
        # Pixel sehen, um die Lampenmitte zu treffen. Weichgezeichnet waere hier
        # schlechter als hart vergroessert.
        painter.setRenderHint(QPainter.SmoothPixmapTransform, self.view.zoom < 2.0)
        painter.drawPixmap(target, self._pixmap, QRectF(self._pixmap.rect()))

        painter.setRenderHint(QPainter.Antialiasing)
        self._draw_quads(painter)
        self._draw_rois(painter)
        self._draw_pending(painter)
        self._draw_crosshair(painter)
        self._draw_status(painter)

    def _draw_quads(self, painter: QPainter) -> None:
        for lane_id, points in self._quads.items():
            if len(points) != 4:
                continue
            color = lane_color(lane_id)
            painter.setPen(QPen(color, 2))
            widget_points = [self.frame_to_widget(x, y) for x, y in points]
            for i in range(4):
                painter.drawLine(widget_points[i], widget_points[(i + 1) % 4])

            if self._show_labels:
                painter.setFont(QFont("Segoe UI", 10, QFont.Bold))
                label_pos = widget_points[0] + QPoint(6, 18)
                text = self._lane_labels.get(lane_id, f"Bahn {lane_id}")
                painter.setPen(QPen(QColor(0, 0, 0), 3))
                painter.drawText(label_pos, text)
                painter.setPen(QPen(color, 1))
                painter.drawText(label_pos, text)

    def _draw_rois(self, painter: QPainter) -> None:
        for lane_id, rois in self._rois.items():
            color = lane_color(lane_id)
            for name, polygon in rois:
                if len(polygon) < 2:
                    continue
                painter.setPen(QPen(color, 1, Qt.DashLine))
                widget_points = [self.frame_to_widget(x, y) for x, y in polygon]
                for i in range(len(widget_points)):
                    painter.drawLine(widget_points[i],
                                     widget_points[(i + 1) % len(widget_points)])
                # Beschriftungen erst ab genug Zoom -- sonst ueberdecken 60 Labels
                # das Bild vollstaendig.
                if self._show_labels and self.view.zoom >= 2.0:
                    painter.setFont(QFont("Segoe UI", 7))
                    painter.setPen(QPen(color, 1))
                    painter.drawText(widget_points[0] + QPoint(2, -3), name)

    def _draw_pending(self, painter: QPainter) -> None:
        """Zeichnet die bereits gesetzten Kalibrierpunkte nummeriert ein.

        Die Nummerierung ist wichtig: Die Reihenfolge der vier Punkte bestimmt
        die Homographie, und ein Vertauscher faellt sonst erst sehr spaet auf.
        """
        if not self._pending_points:
            return

        color = lane_color(self._pending_lane or 1)
        painter.setFont(QFont("Segoe UI", 10, QFont.Bold))

        widget_points = [self.frame_to_widget(x, y) for x, y in self._pending_points]
        for i, point in enumerate(widget_points):
            painter.setPen(QPen(color, 2))
            painter.setBrush(color)
            painter.drawEllipse(point, 5, 5)
            painter.setPen(QPen(QColor(0, 0, 0), 3))
            painter.drawText(point + QPoint(9, 5), str(i + 1))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawText(point + QPoint(9, 5), str(i + 1))

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, 1, Qt.DotLine))
        for i in range(len(widget_points) - 1):
            painter.drawLine(widget_points[i], widget_points[i + 1])

    def _draw_crosshair(self, painter: QPainter) -> None:
        """Fadenkreuz im Zoom -- zeigt genau, welches Pixel getroffen wird."""
        if self.view.zoom < 3.0 or self._cursor_frame_pos is None:
            return
        point = self.frame_to_widget(*self._cursor_frame_pos)
        painter.setPen(QPen(QColor(255, 255, 255, 140), 1))
        painter.drawLine(point.x() - 14, point.y(), point.x() + 14, point.y())
        painter.drawLine(point.x(), point.y() - 14, point.x(), point.y() + 14)

    def _draw_status(self, painter: QPainter) -> None:
        text = self._status_text
        if self.view.zoom > 1.0:
            zoom_line = f"Zoom {self.view.zoom:.1f}x  (Mausrad zoomt, mittlere Taste schiebt)"
            text = f"{text}\n{zoom_line}" if text else zoom_line
        if not text:
            return

        painter.setFont(QFont("Consolas", 9))
        rect = self.rect().adjusted(8, 8, -8, 0)
        painter.setPen(QPen(QColor(0, 0, 0), 3))
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop, text)
        painter.setPen(QPen(QColor(240, 240, 240), 1))
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignTop, text)

    # ------------------------------------------------------------------- Maus

    def set_drag_enabled(self, erlaubt: bool) -> None:
        """Schaltet das Ziehen ab, solange etwas gesetzt wird.

        Waehrend `PICK_ROIS` oder `FRAME_DIGITS` bedeutet ein Klick immer
        "hier setzen". Bliebe das Ziehen aktiv, griffe er stattdessen den
        Bereich darunter -- und da jede Ziffer innerhalb ihres Gesamtfeldes
        liegt, waere keine einzige Ziffer mehr einrahmbar.
        """
        self._drag_erlaubt = erlaubt
        if not erlaubt:
            self._drag = None

    def _treffer(self, pos: QPointF) -> tuple[str, int, object] | None:
        """Was liegt unter dem Mauszeiger -- ein Eckpunkt oder ein Bereich?

        Eckpunkte haben Vorrang: Sie liegen auf den Ecken der Bereiche, und wer
        dort klickt, meint fast immer die Ecke der Tafel.
        """
        self._update_transform()

        def nah(fx: float, fy: float) -> bool:
            wx, wy = self.view.frame_to_widget(fx, fy)
            return (abs(wx - pos.x()) <= self._greifradius
                    and abs(wy - pos.y()) <= self._greifradius)

        for lane_id, quad in self._quads.items():
            for i, (fx, fy) in enumerate(quad):
                if nah(fx, fy):
                    return ("quad", lane_id, i)

        # Bereiche: getroffen ist, wer innerhalb liegt. Bei mehreren gewinnt der
        # KLEINSTE -- eine Ziffernstelle liegt innerhalb ihres Gesamtfeldes, und
        # gemeint ist dann die Stelle.
        kandidaten = []
        for lane_id, rois in self._rois.items():
            for name, polygon in rois:
                xs = [p[0] for p in polygon]
                ys = [p[1] for p in polygon]
                wx0, wy0 = self.view.frame_to_widget(min(xs), min(ys))
                wx1, wy1 = self.view.frame_to_widget(max(xs), max(ys))
                # Etwas Luft nach aussen: Die Raender selbst sind duenn, und
                # ein Rand, den man nur pixelgenau trifft, ist unbenutzbar.
                if (wx0 - self._greifradius <= pos.x() <= wx1 + self._greifradius
                        and wy0 - self._greifradius <= pos.y() <= wy1 + self._greifradius):
                    kandidaten.append(((wx1 - wx0) * (wy1 - wy0), lane_id, name,
                                       (wx0, wy0, wx1, wy1)))
        if kandidaten:
            _, lane_id, name, kasten = min(kandidaten, key=lambda k: k[0])
            return ("roi", lane_id, (name, self._kante(pos, kasten)))
        return None

    def _kante(self, pos: QPointF, kasten: tuple[float, float, float, float]) -> str:
        """Welcher Griff eines Bereichs liegt unter dem Zeiger?

        Nahe einem Rand wird VERZOGEN, in der Mitte VERSCHOBEN. Bei kleinen
        Bereichen -- eine Ziffer ist rund 12 px breit -- wuerde ein fester
        Randstreifen die ganze Flaeche einnehmen und das Verschieben unmoeglich
        machen. Deshalb hoechstens ein Drittel der jeweiligen Seite.
        """
        wx0, wy0, wx1, wy1 = kasten
        rand_x = min(self._greifradius, max(2.0, (wx1 - wx0) / 3))
        rand_y = min(self._greifradius, max(2.0, (wy1 - wy0) / 3))

        links = pos.x() <= wx0 + rand_x
        rechts = pos.x() >= wx1 - rand_x
        oben = pos.y() <= wy0 + rand_y
        unten = pos.y() >= wy1 - rand_y

        senkrecht = "t" if oben else ("b" if unten else "")
        waagerecht = "l" if links else ("r" if rechts else "")
        return (senkrecht + waagerecht) or "move"

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Mittlere Taste verschiebt die Ansicht -- die linke bleibt fuer das
        # Setzen von Punkten frei, sonst waere Kalibrieren im Zoom unmoeglich.
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_origin = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            return

        coords = self.widget_to_frame(event.position().toPoint())
        if coords is None:
            return
        if event.button() == Qt.LeftButton:
            # Liegt etwas Gesetztes unter dem Zeiger, wird es GEZOGEN statt
            # einen neuen Punkt zu setzen. Sonst legte jeder Korrekturversuch
            # einen weiteren Punkt an, statt den falschen zu bewegen.
            treffer = self._treffer(event.position()) if self._drag_erlaubt else None
            if treffer is not None:
                self._drag = treffer
                self.setCursor(Qt.SizeAllCursor)
                return
            self.clicked.emit(*coords)
        elif event.button() == Qt.RightButton:
            self.right_clicked.emit(*coords)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MiddleButton and self._panning:
            self._panning = False
            self.unsetCursor()
        elif event.button() == Qt.LeftButton and self._drag is not None:
            self._drag = None
            self.unsetCursor()
            # Erst beim Loslassen neu rechnen: Die Homographie bei jedem
            # Mausschritt neu aufzustellen wuerde das Ziehen zaeh machen.
            self.drag_finished.emit()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MiddleButton:
            self.reset_zoom()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._panning:
            delta = event.position() - self._pan_origin
            self._pan_origin = event.position()
            self._update_transform()
            self.view.pan_by_widget(delta.x(), delta.y())
            self.update()
            return

        coords = self.widget_to_frame(event.position().toPoint())
        self._cursor_frame_pos = coords
        if coords is None:
            return

        if self._drag is not None:
            art, lane_id, kennung = self._drag
            if art == "quad":
                self.quad_corner_dragged.emit(lane_id, int(kennung), *coords)
            else:
                name, kante = kennung
                if kante == "move":
                    self.roi_dragged.emit(lane_id, name, *coords)
                else:
                    self.roi_resized.emit(lane_id, name, kante, *coords)
            return

        self.mouse_moved.emit(*coords)
        if event.buttons() & Qt.LeftButton:
            self.dragged.emit(*coords)
        if self.view.zoom >= 3.0:
            self.update()   # Fadenkreuz nachziehen
