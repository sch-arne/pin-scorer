"""Ziffernrahmen dort setzen, wo man die Messung sieht.

DIE KRITIK, DIE DAZU FUEHRTE (Nutzer, 2026-09-15): *"damit kann quasi niemand
arbeiten, weil das Bild die ganze Zeit seine Größe ändert, nutze bitte ein
Standbild und eventuell die Möglichkeit mit Frames hüpfen... und dann fände ich
es sinnvoller wenn wir in der Grafik unten die Anpassungen vornehmen und nicht
oben."*

Beides trifft zu. Die erste Fassung zeichnete nur und liess das Ziehen oben auf
der Tafel -- also dort, wo die Ziffer acht Pixel gross ist und man nicht sieht,
was man tut. Und sie wuchs und schrumpfte mit dem Ausschnitt, weil jeder
Ziffernrahmen anders gross ist.

DIESE FASSUNG

* hat eine FESTE Groesse. Der Vergroesserungsfaktor wird so gewaehlt, dass der
  Ausschnitt hineinpasst -- das Feld springt nicht mehr.
* zeigt den Rahmen IM ZUSAMMENHANG: ringsum ein Stueck der Nachbarschaft,
  damit man sieht, ob die Nachbarstelle hineinragt.
* laesst den Rahmen HIER ziehen und in der Groesse aendern. Die Pfeiltasten
  verschieben um je einen Bildpixel.
* legt die sieben Messflaechen auf die Ziffer, samt Mittelpunkten und
  Fuellgraden.

WARUM DIE FLAECHEN GENAU DORT LIEGEN, WO SIE LIEGEN

Der Leser misst nicht auf dem Ausschnitt, sondern auf der Rotmaske, die er
VERTIKAL auf den Ziffernumriss beschneidet und dann auf 24x40 staucht. Wer die
Flaechen einfach gleichmaessig ueber den Rahmen legte, zeigte etwas anderes als
die Messung. Dieses Feld rechnet den Beschnitt deshalb mit -- oben und unten
endet das Raster dort, wo die Maske endet.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..detection.digit_reader import (CELL_HEIGHT, CELL_WIDTH, SEGMENT_ORDER,
                                      segment_regions)

log = logging.getLogger(__name__)

# Wie viel Nachbarschaft ringsum gezeigt wird, als Vielfaches der Rahmengroesse.
# Eine halbe Rahmenbreite reicht, um die Nachbarstelle anzuschneiden -- und
# genau das ist die Frage, die man hier beantworten will.
RAND = 0.9
# Wie nah am Rand des Rahmens gegriffen wird, um seine GROESSE zu aendern.
KANTE_PX = 7
HOEHE = 260


class ZiffernLupe(QWidget):
    """Ein Ziffernrahmen, gross, mit seinen Messflaechen -- und ziehbar."""

    geaendert = Signal(str, tuple)      # ROI-Name, neues normiertes Rechteck

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(HOEHE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setStyleSheet("background:#111;")

        self._name: str | None = None
        self._rect: tuple[float, float, float, float] | None = None
        self._bild: np.ndarray | None = None
        self._leser = None
        self._umrechnung = None
        self._hinweis = ("Ziffernrahmen oben anklicken -- danach hier ziehen "
                         "und in der Groesse aendern")

        # Zustand der Darstellung, gefuellt beim Zeichnen
        self._zoom = 1.0
        self._ursprung = (0, 0)         # linke obere Ecke des Ausschnitts (Frame-px)
        self._kasten_px: tuple[int, int, int, int] | None = None
        self._zieht: str | None = None
        self._letzte_pos: QPoint | None = None

    # ------------------------------------------------------------- Fuellen

    def zeige(self, name: str | None, rect, bild, leser, umrechnung) -> None:
        """Legt fest, welcher Rahmen gezeigt wird. `name=None` leert das Feld."""
        self._name = name
        self._rect = tuple(rect) if rect is not None else None
        self._bild = bild
        self._leser = leser
        self._umrechnung = umrechnung
        self.update()

    def setze_hinweis(self, text: str) -> None:
        self._hinweis = text
        self.update()

    # ------------------------------------------------------------- Rechnen

    def _frame_kasten(self) -> tuple[int, int, int, int] | None:
        if self._rect is None or self._bild is None or self._umrechnung is None:
            return None
        from ..calibration.geometry import norm_rect_to_frame_bbox
        return norm_rect_to_frame_bbox(self._umrechnung, self._rect,
                                       self._bild.shape)

    def _norm_je_pixel(self) -> tuple[float, float]:
        """Wie viel normiertes Mass ein Frame-Pixel wert ist -- oertlich.

        Genau hier waere ein globaler Faktor falsch: Die Tafel steht schraeg
        im Bild, also ist der Massstab an jeder Stelle ein anderer. Genommen
        wird deshalb der Massstab DIESES Rahmens.
        """
        kasten = self._frame_kasten()
        if kasten is None or kasten[2] <= 0 or kasten[3] <= 0:
            return (0.0, 0.0)
        return (self._rect[2] / kasten[2], self._rect[3] / kasten[3])

    # ------------------------------------------------------------- Zeichnen

    def paintEvent(self, event) -> None:      # noqa: N802  (Qt-Konvention)
        maler = QPainter(self)
        maler.fillRect(self.rect(), QColor("#111"))
        kasten = self._frame_kasten()
        if kasten is None or kasten[2] <= 0 or kasten[3] <= 0:
            maler.setPen(QColor("#888"))
            maler.drawText(QRectF(8, 8, self.width() - 16, self.height() - 16),
                           Qt.AlignLeft | Qt.TextWordWrap, self._hinweis)
            return

        x, y, w, h = kasten
        rand_x, rand_y = int(w * RAND) + 2, int(h * RAND) + 2
        ax0 = max(0, x - rand_x)
        ay0 = max(0, y - rand_y)
        ax1 = min(self._bild.shape[1], x + w + rand_x)
        ay1 = min(self._bild.shape[0], y + h + rand_y)
        ausschnitt = self._bild[ay0:ay1, ax0:ax1]
        if ausschnitt.size == 0:
            return

        # FESTER PLATZ, PASSENDER ZOOM -- nicht umgekehrt. Genau daran ist die
        # erste Fassung gescheitert: Sie waehlte einen festen Zoom, und das
        # Feld sprang mit jeder Rahmengroesse.
        platz_h = self.height() - 16
        platz_b = self.width() - 250
        self._zoom = max(1.0, min(platz_b / ausschnitt.shape[1],
                                  platz_h / ausschnitt.shape[0]))
        gross = cv2.resize(
            ausschnitt,
            (int(ausschnitt.shape[1] * self._zoom),
             int(ausschnitt.shape[0] * self._zoom)),
            interpolation=cv2.INTER_NEAREST)
        self._ursprung = (ax0, ay0)

        bild = np.ascontiguousarray(gross)
        qimg = QImage(bild.data, bild.shape[1], bild.shape[0],
                      3 * bild.shape[1], QImage.Format_BGR888).copy()
        links = 8
        oben = 8
        maler.drawPixmap(links, oben, QPixmap.fromImage(qimg))

        def auf_schirm(fx: float, fy: float) -> tuple[float, float]:
            return (links + (fx - ax0) * self._zoom,
                    oben + (fy - ay0) * self._zoom)

        # Der Rahmen selbst
        rx, ry = auf_schirm(x, y)
        rb, rh = w * self._zoom, h * self._zoom
        self._kasten_px = (int(rx), int(ry), int(rb), int(rh))
        maler.setPen(QPen(QColor("#ffcc33"), 2))
        maler.drawRect(QRectF(rx, ry, rb, rh))

        self._zeichne_flaechen(maler, kasten, auf_schirm)
        self._zeichne_zahlen(maler, kasten)

    def _zeichne_flaechen(self, maler, kasten, auf_schirm) -> None:
        """Die sieben Messflaechen dorthin, wo der Leser sie wirklich misst."""
        if self._leser is None:
            return
        x, y, w, h = kasten
        patch = self._bild[y:y + h, x:x + w]
        fills = self._leser.segment_fills(patch)
        if fills is None:
            return
        schwelle = self._leser._threshold(fills)

        # DER VERTIKALE BESCHNITT MUSS MIT. Der Leser schneidet die Maske oben
        # und unten auf den Ziffernumriss, bevor er sie staucht -- wer das
        # weglaesst, zeigt die Flaechen an der falschen Stelle.
        maske = self._leser._preprocessor._red_mask(patch)
        zeilen = np.where(maske.max(axis=1) > 0)[0]
        oben_px = y + (int(zeilen[0]) if zeilen.size else 0)
        unten_px = y + (int(zeilen[-1]) + 1 if zeilen.size else h)
        hoehe_px = max(1, unten_px - oben_px)

        regionen = segment_regions(
            shear=self._leser.cfg.segment_shear,
            middle_inset=self._leser.cfg.segment_middle_inset)
        for i, name in enumerate(SEGMENT_ORDER):
            sx, sy, sw, sh = regionen[name]
            fx0 = x + sx / CELL_WIDTH * w
            fx1 = x + (sx + sw) / CELL_WIDTH * w
            fy0 = oben_px + sy / CELL_HEIGHT * hoehe_px
            fy1 = oben_px + (sy + sh) / CELL_HEIGHT * hoehe_px
            px0, py0 = auf_schirm(fx0, fy0)
            px1, py1 = auf_schirm(fx1, fy1)
            an = fills[i] >= schwelle
            farbe = QColor("#50e650") if an else QColor("#f06a46")
            maler.setPen(QPen(farbe, 1))
            maler.drawRect(QRectF(px0, py0, px1 - px0, py1 - py0))
            mx, my = (px0 + px1) / 2, (py0 + py1) / 2
            maler.drawLine(int(mx - 4), int(my), int(mx + 4), int(my))
            maler.drawLine(int(mx), int(my - 4), int(mx), int(my + 4))
            maler.drawText(QPoint(int(px0) + 2, int(py0) + 11), name)

    def _zeichne_zahlen(self, maler, kasten) -> None:
        """Fuellgrade und die wahrscheinlichsten Ziffern, rechts als Spalte."""
        if self._leser is None:
            return
        x, y, w, h = kasten
        patch = self._bild[y:y + h, x:x + w]
        fills = self._leser.segment_fills(patch)
        spalte = self.width() - 238
        if fills is None:
            maler.setPen(QColor("#f06a46"))
            maler.drawText(QPoint(spalte, 24), "nichts zu messen (zu dunkel)")
            return
        schwelle = self._leser._threshold(fills)
        zeichen, _, _, verteilung = self._leser.read_digit_verteilung(patch)

        maler.setPen(QColor("#eee"))
        maler.drawText(QPoint(spalte, 22), f"gelesen: {zeichen}")
        maler.setPen(QColor("#999"))
        maler.drawText(QPoint(spalte, 40), f"Schwelle {schwelle:.3f}")
        maler.drawText(QPoint(spalte, 58), f"Rahmen {w}x{h} px")
        for i, name in enumerate(SEGMENT_ORDER):
            an = fills[i] >= schwelle
            maler.setPen(QColor("#50e650") if an else QColor("#f06a46"))
            maler.drawText(QPoint(spalte, 80 + i * 16),
                           f"{name}  {fills[i]:.3f}")
        for j, (wert, p) in enumerate(verteilung[:3]):
            maler.setPen(QColor("#50e650") if j == 0 else QColor("#ffb020"))
            maler.drawText(QPoint(spalte + 110, 80 + j * 18),
                           f"{wert}: {100 * p:.1f}%")

    # -------------------------------------------------------------- Ziehen

    def _greift(self, pos: QPoint) -> str | None:
        """Was wird hier angefasst -- eine Kante oder die Mitte?"""
        if self._kasten_px is None:
            return None
        x, y, w, h = self._kasten_px
        if not (x - KANTE_PX <= pos.x() <= x + w + KANTE_PX
                and y - KANTE_PX <= pos.y() <= y + h + KANTE_PX):
            return None
        nah_links = abs(pos.x() - x) <= KANTE_PX
        nah_rechts = abs(pos.x() - (x + w)) <= KANTE_PX
        nah_oben = abs(pos.y() - y) <= KANTE_PX
        nah_unten = abs(pos.y() - (y + h)) <= KANTE_PX
        if nah_links:
            return "links"
        if nah_rechts:
            return "rechts"
        if nah_oben:
            return "oben"
        if nah_unten:
            return "unten"
        return "mitte"

    def mousePressEvent(self, event) -> None:     # noqa: N802
        if event.button() != Qt.LeftButton or self._rect is None:
            return
        self._zieht = self._greift(event.position().toPoint())
        self._letzte_pos = event.position().toPoint()
        self.setFocus()

    def mouseMoveEvent(self, event) -> None:      # noqa: N802
        pos = event.position().toPoint()
        if self._zieht is None:
            griff = self._greift(pos)
            self.setCursor({
                "links": Qt.SizeHorCursor, "rechts": Qt.SizeHorCursor,
                "oben": Qt.SizeVerCursor, "unten": Qt.SizeVerCursor,
                "mitte": Qt.SizeAllCursor,
            }.get(griff, Qt.ArrowCursor))
            return
        if self._letzte_pos is None:
            return
        dx = (pos.x() - self._letzte_pos.x()) / max(self._zoom, 1e-6)
        dy = (pos.y() - self._letzte_pos.y()) / max(self._zoom, 1e-6)
        self._letzte_pos = pos
        self._verschiebe(dx, dy, self._zieht)

    def mouseReleaseEvent(self, event) -> None:   # noqa: N802
        self._zieht = None
        self._letzte_pos = None

    def keyPressEvent(self, event) -> None:       # noqa: N802
        """Pfeiltasten verschieben um je einen BILDpixel.

        Ein Pixel ist hier die sinnvolle Einheit: Bei 12x20 px je Ziffer
        verschiebt ein Pixel die Messflaeche um rund eine halbe Segmentbreite.
        """
        schritte = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
                    Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if event.key() not in schritte:
            super().keyPressEvent(event)
            return
        dx, dy = schritte[event.key()]
        if event.modifiers() & Qt.ShiftModifier:
            # Mit Shift die GROESSE statt der Lage -- rechts und unten.
            self._verschiebe(dx, dy, "rechts" if dx else "unten")
        else:
            self._verschiebe(dx, dy, "mitte")

    def _verschiebe(self, dx_px: float, dy_px: float, art: str | None) -> None:
        """Rechnet eine Verschiebung in Bildpixeln auf das normierte Rechteck."""
        if art is None or self._rect is None or self._name is None:
            return
        sx, sy = self._norm_je_pixel()
        if sx <= 0 or sy <= 0:
            return
        x, y, w, h = self._rect
        ndx, ndy = dx_px * sx, dy_px * sy
        if art == "mitte":
            x, y = x + ndx, y + ndy
        elif art == "links":
            x, w = x + ndx, w - ndx
        elif art == "rechts":
            w = w + ndx
        elif art == "oben":
            y, h = y + ndy, h - ndy
        elif art == "unten":
            h = h + ndy
        # Ein Rahmen ohne Flaeche liesse sich nicht mehr greifen.
        w, h = max(sx, w), max(sy, h)
        self._rect = (x, y, w, h)
        self.geaendert.emit(self._name, self._rect)
        self.update()
