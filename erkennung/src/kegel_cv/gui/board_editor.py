"""Eine einzelne Tafel gross zeigen und ihre Bereiche von Hand nachziehen.

WOFUER -- Wunsch des Nutzers am 2026-09-11:

    "ich brauche einen Button 'Nachkalibrieren' ... an dem ich jedes Board das
     ich aendern will anklicken kann, das wird mir gross gezeigt und ich kann
     die ROIs anpassen"

WARUM ENTZERRT UND NICHT IM VOLLBILD: Im Originalframe misst eine Tafel rund
250 Pixel, eine Kegellampe darin sechs. Ziehen laesst sich das dort nur im
starken Zoom -- und schraeg, weil die Tafel perspektivisch verzerrt im Bild
steht. Die entzerrte Tafel ist genau der Raum, in dem die ROIs DEFINIERT sind:
normierte Tafelkoordinaten 0..1. Was hier geschoben wird, wird ohne Umweg ueber
eine Homographie gespeichert.

IM WAHREN SEITENVERHAELTNIS, nicht im Rechenformat 440x530 -- dieselbe
Begruendung wie bei `roi_preview.tafelmontage`: Die Analyse rechnet in einem
gestreckten Format, das Auge soll die Tafel sehen.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from ..calibration.geometry import GeometryError, PerspectiveTransform, Quad
from ..calibration.model import DIGIT_PREFIX, Roi
from ..calibration.roi_preview import quadmasse, roi_farbe
from ..calibration.session import CalibrationSession
from .ziffern_lupe import ZiffernLupe

log = logging.getLogger(__name__)

# Trefferradius in WIDGET-Pixeln -- dieselbe Ueberlegung wie in `VideoView`:
# Was zielsicher greifbar ist, haengt am Bildschirm, nicht an der Tafelgroesse.
GREIFRADIUS = 9.0

# Wie oft das Bild unter den Rahmen erneuert wird. Im Livestream stehen dort
# wechselnde Ziffern; ein Standbild von vor einer Minute zeigt womoeglich eine
# Anzeige, die es gerade gar nicht gibt.
BILDTAKT_MS = 400


def _qfarbe(name: str) -> QColor:
    """Dieselben Farben wie in der Vorschau -- BGR dort, RGB hier."""
    b, g, r = roi_farbe(name)
    return QColor(r, g, b)


def entzerre(bild: np.ndarray, ecken) -> np.ndarray | None:
    """Schneidet eine Tafel im wahren Seitenverhaeltnis aus dem Frame.

    Gibt None zurueck, wenn das Viereck nichts hergibt -- waehrend des Ziehens
    an einer Tafelecke kann es kurzzeitig entartet sein (P8: kein Abbruch).
    """
    punkte = [(float(p[0]), float(p[1])) for p in ecken]
    breite, hoehe = quadmasse(punkte)
    if breite < 2 or hoehe < 2:
        return None
    try:
        transform = PerspectiveTransform(Quad.from_points(punkte),
                                         int(round(breite)), int(round(hoehe)))
    except GeometryError as exc:
        log.warning("Tafel laesst sich nicht entzerren: %s", exc)
        return None
    return transform.warp(bild)


class TafelLeinwand(QWidget):
    """Die entzerrte Tafel mit ihren Bereichen -- anfassbar.

    Die Leinwand rechnet ausschliesslich in normierten Tafelkoordinaten. Sie
    kennt weder Frame noch Homographie; was sie liefert, sind fertige `Roi`.
    """

    geaendert = Signal()
    zeiger = Signal(str)        # Name des Bereichs unter der Maus ("" = keiner)
    auswahl_geaendert = Signal(int)   # wie viele Bereiche gerade gewaehlt sind

    def __init__(self, rois: list[Roi], tafel_px: tuple[int, int],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 320)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setStyleSheet("background-color:#141414;")

        self.rois: list[Roi] = [r.model_copy(deep=True) for r in rois]
        # Nur fuer die Pfeiltasten: EIN Schritt ist EIN Pixel der Tafel im
        # Originalbild. Das ist die Einheit, in der der Fehler auftritt --
        # gemessen entscheidet ein Pixel ueber neun Prozentpunkte
        # Lesegenauigkeit bei den Ziffern.
        self._tafel_px = (max(1, tafel_px[0]), max(1, tafel_px[1]))
        self._pixmap: QPixmap | None = None
        self._namen = False
        # MEHRERE BEREICHE ZUGLEICH. Wunsch des Nutzers am 2026-09-11: "der
        # Nutzer braucht je Tafel die Moeglichkeit, ein Offset von x und y zu
        # setzen ... dafuer soll er die ROIs anklicken, die er gleichzeitig
        # verschieben moechte."
        #
        # Das ist mehr als Bequemlichkeit: Was zusammen danebenliegt, gehoert
        # zusammen verschoben. GEMESSEN wandert die untere Ziffernzeile als
        # GANZES um denselben Betrag -- sie einzeln nachzuziehen hiesse, den
        # gleichen Fehler achtmal zu schaetzen statt einmal.
        self._gewaehlt: set[str] = set()
        # Was gerade gezogen wird: Name, Kante, Startpunkt und die Rechtecke
        # der Auswahl zu Beginn des Ziehens.
        self._zieht: tuple[str, str] | None = None
        self._zieh_start: tuple[float, float] | None = None
        self._zieh_rechtecke: dict[str, tuple] = {}

    # ------------------------------------------------------------- Anzeige

    def set_bild(self, tafel: np.ndarray | None) -> None:
        if tafel is None:
            return
        hoehe, breite = tafel.shape[:2]
        rgb = np.ascontiguousarray(tafel[:, :, ::-1])
        bild = QImage(rgb.data, breite, hoehe, 3 * breite, QImage.Format_RGB888)
        self._pixmap = QPixmap.fromImage(bild.copy())
        self.update()

    def set_namen(self, an: bool) -> None:
        self._namen = bool(an)
        self.update()

    def setze_rois(self, rois: list[Roi]) -> None:
        self.rois = [r.model_copy(deep=True) for r in rois]
        self.update()
        self.geaendert.emit()

    # --------------------------------------------------------- Koordinaten

    def _flaeche(self) -> QRectF:
        """Wo die Tafel im Widget liegt -- eingepasst, Seitenverhaeltnis fest."""
        if self._pixmap is None or self._pixmap.isNull():
            return QRectF(0, 0, self.width(), self.height())
        pb, ph = self._pixmap.width(), self._pixmap.height()
        faktor = min(self.width() / pb, self.height() / ph)
        breite, hoehe = pb * faktor, ph * faktor
        return QRectF((self.width() - breite) / 2, (self.height() - hoehe) / 2,
                      breite, hoehe)

    def _nach_norm(self, pos: QPointF) -> tuple[float, float]:
        flaeche = self._flaeche()
        if flaeche.width() <= 0 or flaeche.height() <= 0:
            return 0.0, 0.0
        return ((pos.x() - flaeche.x()) / flaeche.width(),
                (pos.y() - flaeche.y()) / flaeche.height())

    def _kasten(self, roi: Roi) -> QRectF:
        x, y, w, h = roi.rect
        f = self._flaeche()
        return QRectF(f.x() + x * f.width(), f.y() + y * f.height(),
                      w * f.width(), h * f.height())

    # ------------------------------------------------------------- Zeichnen

    def paintEvent(self, event) -> None:      # noqa: N802  (Qt-Konvention)
        maler = QPainter(self)
        maler.setRenderHint(QPainter.Antialiasing)
        flaeche = self._flaeche()
        if self._pixmap is not None and not self._pixmap.isNull():
            maler.drawPixmap(flaeche, self._pixmap,
                             QRectF(self._pixmap.rect()))

        schrift = QFont()
        schrift.setPixelSize(10)
        maler.setFont(schrift)

        for roi in self.rois:
            if not roi.enabled:
                continue
            farbe = _qfarbe(roi.name)
            gewaehlt = roi.name in self._gewaehlt
            kasten = self._kasten(roi)
            maler.setPen(QPen(farbe, 2 if gewaehlt else 1))
            maler.drawRect(kasten)
            if gewaehlt:
                self._griffe(maler, kasten, farbe)
            # Der GEWAEHLTE Bereich zeigt seinen Namen immer -- man muss wissen,
            # was man gerade verschiebt, auch wenn alle anderen Namen aus sind.
            if self._namen or gewaehlt:
                maler.setPen(QPen(farbe))
                maler.drawText(kasten.topLeft() + QPointF(1, -2),
                               roi.name.replace("pin_lamp_", "L")
                               .replace("digit_", ""))
        maler.end()

    @staticmethod
    def _griffe(maler: QPainter, kasten: QRectF, farbe: QColor) -> None:
        """Ecken des gewaehlten Bereichs sichtbar machen.

        Ohne sie ist nicht zu erkennen, dass sich die GROESSE ziehen laesst --
        und eine Ziffernbox muss in der Groesse stimmen, nicht nur in der Lage.
        """
        maler.setBrush(farbe)
        for punkt in (kasten.topLeft(), kasten.topRight(),
                      kasten.bottomRight(), kasten.bottomLeft()):
            maler.drawRect(QRectF(punkt.x() - 2, punkt.y() - 2, 4, 4))
        maler.setBrush(Qt.NoBrush)

    # ---------------------------------------------------------------- Maus

    def _treffer(self, pos: QPointF) -> tuple[str, str] | None:
        """Was liegt unter dem Zeiger -- und an welchem Griff?

        Bei mehreren gewinnt der KLEINSTE Bereich: Eine Ziffernstelle liegt
        innerhalb ihres Gesamtfeldes, gemeint ist dann die Stelle.
        """
        kandidaten = []
        for roi in self.rois:
            if not roi.enabled:
                continue
            k = self._kasten(roi)
            if (k.x() - GREIFRADIUS <= pos.x() <= k.right() + GREIFRADIUS
                    and k.y() - GREIFRADIUS <= pos.y() <= k.bottom() + GREIFRADIUS):
                kandidaten.append((k.width() * k.height(), roi.name, k))
        if not kandidaten:
            return None
        _, name, kasten = min(kandidaten, key=lambda k: k[0])
        return name, self._kante(pos, kasten)

    @staticmethod
    def _kante(pos: QPointF, kasten: QRectF) -> str:
        """Nahe einem Rand wird VERZOGEN, in der Mitte VERSCHOBEN.

        Hoechstens ein Drittel der jeweiligen Seite -- bei einer 12 Pixel
        breiten Ziffer naehme ein fester Randstreifen die ganze Flaeche ein und
        das Verschieben waere unmoeglich.
        """
        rand_x = min(GREIFRADIUS, max(2.0, kasten.width() / 3))
        rand_y = min(GREIFRADIUS, max(2.0, kasten.height() / 3))
        senkrecht = ("t" if pos.y() <= kasten.y() + rand_y
                     else ("b" if pos.y() >= kasten.bottom() - rand_y else ""))
        waagerecht = ("l" if pos.x() <= kasten.x() + rand_x
                      else ("r" if pos.x() >= kasten.right() - rand_x else ""))
        return (senkrecht + waagerecht) or "move"

    def mousePressEvent(self, event) -> None:     # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        treffer = self._treffer(event.position())
        # Strg oder Umschalt sammelt ein, ein blosser Klick waehlt neu. Wer
        # daneben klickt, hebt die Auswahl auf -- sonst bleibt eine unsichtbare
        # Auswahl stehen und die naechste Pfeiltaste verschiebt Unerwartetes.
        dazu = bool(event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier))
        if treffer is None:
            if not dazu:
                self._gewaehlt.clear()
        elif dazu:
            self._gewaehlt.symmetric_difference_update({treffer[0]})
        elif treffer[0] not in self._gewaehlt:
            self._gewaehlt = {treffer[0]}

        self._zieht = treffer
        self._zieh_start = self._nach_norm(event.position())
        self._zieh_rechtecke = {r.name: r.rect for r in self.rois}
        self.auswahl_geaendert.emit(len(self._gewaehlt))
        self.setFocus()
        self.update()

    def mouseMoveEvent(self, event) -> None:      # noqa: N802
        if self._zieht is None:
            treffer = self._treffer(event.position())
            self.zeiger.emit(treffer[0] if treffer else "")
            self.setCursor(Qt.SizeAllCursor if treffer else Qt.ArrowCursor)
            return
        name, kante = self._zieht
        nx, ny = self._nach_norm(event.position())
        # AUCH BEIM ZIEHEN MELDEN. Frueher schwieg das Signal, solange die
        # Maus gedrueckt war -- also genau dann, wenn sich der Bereich
        # aendert. Fuer die Ziffernlupe ist das der einzige Moment, der
        # zaehlt: Sie soll zeigen, was das Verschieben BEWIRKT, nicht was
        # vorher war.
        self.zeiger.emit(name)
        if kante != "move":
            self._aendere(name, kante, nx, ny)
            return

        # RELATIV ziehen, nicht auf den Zeiger springen. Bei mehreren
        # ausgewaehlten Bereichen gaebe es keine gemeinsame Mitte -- und auch
        # bei einem einzelnen springt er sonst, wenn man ihn nicht genau
        # mittig angefasst hat.
        if self._zieh_start is None:
            return
        dx = nx - self._zieh_start[0]
        dy = ny - self._zieh_start[1]
        self._verschiebe_auswahl(dx, dy, name)

    def mouseReleaseEvent(self, event) -> None:   # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        self._zieht = None
        self._zieh_start = None
        # NEUE AUSGANGSLAGE. Der Versatz im Eingabefeld rechnet ab hier --
        # sonst naehme der naechste Dreh am Feld das Ziehen wieder zurueck.
        self._zieh_rechtecke = {r.name: r.rect for r in self.rois}
        self.auswahl_geaendert.emit(len(self._gewaehlt))

    def keyPressEvent(self, event) -> None:       # noqa: N802
        """Pfeiltasten schieben den gewaehlten Bereich um EINEN Tafelpixel.

        Mit der Maus ist ein einzelner Pixel nicht zu treffen -- und genau um
        einen einzelnen Pixel geht es bei den Ziffern.
        """
        schritte = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0),
                    Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if not self._gewaehlt or event.key() not in schritte:
            super().keyPressEvent(event)
            return
        dx, dy = schritte[event.key()]
        self._zieh_rechtecke = {r.name: r.rect for r in self.rois}
        self.versetze(dx, dy)

    # ------------------------------------------------------------- Aendern

    def _roi(self, name: str) -> Roi | None:
        return next((r for r in self.rois if r.name == name), None)

    @property
    def auswahl(self) -> set[str]:
        """Welche Bereiche gerade gewaehlt sind."""
        return set(self._gewaehlt)

    def waehle(self, namen) -> None:
        """Setzt die Auswahl von aussen -- fuer Knoepfe wie 'alle Ziffern'."""
        vorhanden = {r.name for r in self.rois}
        self._gewaehlt = {n for n in namen if n in vorhanden}
        self._zieh_rechtecke = {r.name: r.rect for r in self.rois}
        self.auswahl_geaendert.emit(len(self._gewaehlt))
        self.update()

    def versetze(self, dx_px: float, dy_px: float) -> None:
        """Verschiebt die ganze Auswahl um dx/dy TAFELPIXEL.

        WOFUER -- Wunsch des Nutzers am 2026-09-11: "je Tafel die Moeglichkeit,
        ein Offset von x und y zu setzen ... dafuer soll er die ROIs anklicken,
        die er gleichzeitig verschieben moechte."

        Gerechnet wird ab den Rechtecken, die beim Beginn der Verschiebung
        galten (`_zieh_rechtecke`). Sonst summierte sich jede Bewegung auf die
        vorige auf, und ein Drehen am Eingabefeld liefe davon.
        """
        self._verschiebe_auswahl(dx_px / self._tafel_px[0],
                                 dy_px / self._tafel_px[1])

    def _verschiebe_auswahl(self, dx: float, dy: float,
                            wenigstens: str | None = None) -> None:
        """Verschiebt die Auswahl um dx/dy in normierten Koordinaten."""
        namen = set(self._gewaehlt)
        if wenigstens:
            # Wer einen nicht gewaehlten Bereich anfasst, meint genau diesen.
            namen.add(wenigstens)
        if not namen:
            return
        for i, roi in enumerate(self.rois):
            if roi.name not in namen:
                continue
            ausgang = self._zieh_rechtecke.get(roi.name, roi.rect)
            x, y, w, h = ausgang
            neu_x = min(max(x + dx, 0.0), max(0.0, 1.0 - w))
            neu_y = min(max(y + dy, 0.0), max(0.0, 1.0 - h))
            self.rois[i] = roi.model_copy(
                update={"rect": (neu_x, neu_y, w, h), "enabled": True})
        self.update()
        self.geaendert.emit()

    def _aendere(self, name: str, kante: str, nx: float, ny: float) -> None:
        roi = self._roi(name)
        if roi is None:
            return
        neu = (self._verschoben(roi, nx, ny) if kante == "move"
               else self._verzogen(roi, kante, nx, ny))
        if neu is None:
            return
        self.rois[self.rois.index(roi)] = neu
        self.update()
        self.geaendert.emit()

    @staticmethod
    def _verschoben(roi: Roi, nx: float, ny: float) -> Roi:
        """Mittig auf den Punkt, aber nie ueber den Tafelrand hinaus.

        Geklemmt statt verworfen: Wer eine Lampe an den Rand zieht, will sie
        am Rand haben -- ein Bereich, der beim Ueberschreiten stehenbleibt,
        fuehlt sich an, als haenge die Oberflaeche.
        """
        _, _, w, h = roi.rect
        x = min(max(nx - w / 2, 0.0), max(0.0, 1.0 - w))
        y = min(max(ny - h / 2, 0.0), max(0.0, 1.0 - h))
        return roi.model_copy(update={"rect": (x, y, w, h), "enabled": True})

    @staticmethod
    def _verzogen(roi: Roi, kante: str, nx: float, ny: float) -> Roi:
        """Einen Rand oder eine Ecke ziehen -- Mindestkante wie in der Sitzung.

        Derselbe Grenzwert wie beim Ziehen im Video: Ein versehentlich auf
        null gezogener Bereich waere still kaputt statt sichtbar falsch.
        """
        klein = CalibrationSession.MINDESTKANTE
        nx = min(max(nx, 0.0), 1.0)
        ny = min(max(ny, 0.0), 1.0)
        x, y, w, h = roi.rect
        links, oben, rechts, unten = x, y, x + w, y + h
        if "l" in kante:
            links = min(nx, rechts - klein)
        if "r" in kante:
            rechts = max(nx, links + klein)
        if "t" in kante:
            oben = min(ny, unten - klein)
        if "b" in kante:
            unten = max(ny, oben + klein)
        return roi.model_copy(update={
            "rect": (links, oben, rechts - links, unten - oben),
            "enabled": True})


class TafelEditorDialog(QDialog):
    """Nachkalibrieren einer einzelnen Tafel.

    Der Dialog arbeitet auf KOPIEN der Bereiche. Erst "Uebernehmen" schreibt
    sie zurueck -- sonst waere ein versehentliches Verziehen nicht mehr
    ruecknehmbar, und genau deshalb kommt man hierher.
    """

    def __init__(self, lane, bild: np.ndarray, *, tafeln: int = 1,
                 bild_quelle=None, springer=None, rueckwaerts: bool = True,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Bahn {lane.display_number} nachkalibrieren")
        self._lane = lane
        self._bild_quelle = bild_quelle
        self._versatz_angewandt = (0, 0)
        self._ausgang = [r.model_copy(deep=True) for r in lane.rois]
        self.auf_alle = False

        tafel = entzerre(bild, lane.quad)
        px = (tafel.shape[1], tafel.shape[0]) if tafel is not None else (1, 1)

        spalte = QVBoxLayout(self)
        # UMBRECHEN, SONST SPRENGT DIESE ZEILE DEN DIALOG. Ein QLabel ohne
        # Umbruch setzt seine ganze Textbreite als Mindestbreite durch --
        # gemessen 2302 Pixel fuer eine Tafel, die 500 breit dargestellt wird.
        kopf = QLabel(
            f"<b>Bahn {lane.display_number}</b> -- Bereich anklicken und "
            "ziehen. Am Rand eines Bereichs wird seine <b>Groesse</b> "
            "gezogen, in der Mitte seine <b>Lage</b>. Die Pfeiltasten "
            "verschieben den gewaehlten Bereich um je einen Tafelpixel.")
        kopf.setWordWrap(True)
        spalte.addWidget(kopf)

        self.leinwand = TafelLeinwand(lane.rois, px)
        self.leinwand.set_bild(tafel)
        self.leinwand.zeiger.connect(self._zeige_bereich)
        spalte.addWidget(self.leinwand, 1)

        self.info = QLabel(f"{len(lane.rois)} Bereiche -- Tafel {px[0]}x{px[1]} px")
        self.info.setStyleSheet("color:#888;")
        self.info.setWordWrap(True)
        spalte.addWidget(self.info)

        # --- Ziffernlupe ---
        #
        # WOFUER (Nutzer, 2026-09-15): *"dass er wenn er eine Ziffer einrahmt
        # die Mittelpunkte der einzelnen Felder angezeigt bekommt"* -- und
        # nach der ersten Fassung: *"damit kann quasi niemand arbeiten, weil
        # das Bild die ganze Zeit seine Groesse aendert ... und dann faende
        # ich es sinnvoller wenn wir in der Grafik unten die Anpassungen
        # vornehmen und nicht oben."*
        #
        # Beides ist hier beantwortet: Das Feld hat eine feste Groesse, und
        # gezogen wird DORT, wo man die Messung sieht. Begruendung und die
        # Rechnung dahinter stehen in `gui/ziffern_lupe.py`.
        self._original = bild
        self._leser = None
        self._umrechnung = None
        self.lupe = ZiffernLupe()
        self.lupe.geaendert.connect(self._lupe_hat_geaendert)
        spalte.addWidget(self.lupe)

        # --- Standbild und Frame-Spruenge ---
        #
        # Der Takt lief bisher immer. Beim Ziehen eines Ziffernrahmens ist das
        # unbrauchbar: Das Bild wechselt unter der Hand, und man sieht nie, ob
        # die Aenderung etwas gebracht hat. Also Standbild als Vorgabe -- und
        # dafuer die Moeglichkeit, gezielt weiterzuspringen.
        bild_zeile = QHBoxLayout()
        self.standbild = QCheckBox("Standbild")
        self.standbild.setChecked(True)
        self.standbild.setToolTip(
            "Haelt das Bild an. Zum Pruefen einer Ziffernbox ist das noetig --"
            " sonst wechselt die Anzeige, waehrend man zieht.")
        self.standbild.toggled.connect(self._on_standbild)
        bild_zeile.addWidget(self.standbild)

        # RUECKWAERTS NUR BEI EINER DATEI. Ein Livestream kennt kein
        # vergangenes Frame -- der Nutzer dazu (2026-09-17): *"Das wird
        # spaeter im Livestream alles passieren muessen, wir koennen keine
        # 'Aufzeichnung' bemuehen.... Dann muessen wir halt sagen, dass
        # Frame, welches in dem Moment gueltig ist, wo der Nutzer auf
        # Nachkalibrieren klickt muss genommen werden."*
        #
        # Knoepfe anzubieten, die dann stumm nichts tun, waere schlechter als
        # sie wegzulassen. Beim Stream bleibt "frisches Bild" -- vorwaerts
        # geht immer.
        if rueckwaerts:
            for beschriftung, schritt in (("<<", -100), ("<", -10),
                                          ("|<", -1), (">|", 1),
                                          (">", 10), (">>", 100)):
                knopf = QPushButton(beschriftung)
                knopf.setMaximumWidth(44)
                knopf.setToolTip(f"{schritt:+d} Frames")
                knopf.clicked.connect(
                    lambda _=False, s=schritt: self._springe(s))
                bild_zeile.addWidget(knopf)
        else:
            frisch = QPushButton("frisches Bild")
            frisch.setToolTip(
                "Holt das aktuelle Bild aus dem laufenden Stream. "
                "Zurueck geht es nicht -- ein Stream kennt kein vergangenes "
                "Frame.")
            frisch.clicked.connect(lambda: self._springe(1))
            bild_zeile.addWidget(frisch)

        self.bild_info = QLabel("")
        self.bild_info.setStyleSheet("color:#888;")
        bild_zeile.addWidget(self.bild_info)
        bild_zeile.addStretch(1)
        spalte.addLayout(bild_zeile)

        # --- Auswahl und gemeinsamer Versatz ---
        #
        # WOFUER (Nutzer, 2026-09-11): "je Tafel die Moeglichkeit, ein Offset
        # von x und y zu setzen ... dafuer soll er die ROIs anklicken, die er
        # gleichzeitig verschieben moechte."
        wahl = QHBoxLayout()
        self.auswahl_info = QLabel("nichts gewaehlt")
        self.auswahl_info.setStyleSheet("color:#888;")
        self.auswahl_info.setMinimumWidth(120)
        wahl.addWidget(self.auswahl_info)

        # Die Gruppen, die erfahrungsgemaess GEMEINSAM danebenliegen -- die
        # Ziffernzeile wandert als Ganzes, die Lampenraute ebenso.
        for beschriftung, passt in (
                ("alle", lambda n: True),
                ("Lampen", lambda n: n.startswith(("pin_lamp", "green_lamp"))),
                ("Ziffern", lambda n: n.startswith(
                    ("digit_", "throw_number", "pin_count", "total_",
                     "left_display")))):
            knopf = QPushButton(beschriftung)
            knopf.setToolTip(f"{beschriftung} auswaehlen")
            knopf.setMaximumWidth(70)
            knopf.clicked.connect(
                lambda _=False, f=passt: self.leinwand.waehle(
                    [r.name for r in self.leinwand.rois if f(r.name)]))
            wahl.addWidget(knopf)

        wahl.addSpacing(12)
        wahl.addWidget(QLabel("Versatz:"))
        self.versatz_x = QSpinBox()
        self.versatz_x.setRange(-30, 30)
        self.versatz_x.setPrefix("x ")
        self.versatz_x.setSuffix(" px")
        self.versatz_x.setToolTip(
            "Verschiebt ALLE gewaehlten Bereiche um so viele Tafelpixel. "
            "Dasselbe tun die Pfeiltasten, je Druck um einen.")
        self.versatz_y = QSpinBox()
        self.versatz_y.setRange(-30, 30)
        self.versatz_y.setPrefix("y ")
        self.versatz_y.setSuffix(" px")
        self.versatz_y.setToolTip(self.versatz_x.toolTip())
        self.versatz_x.valueChanged.connect(self._on_versatz)
        self.versatz_y.valueChanged.connect(self._on_versatz)
        wahl.addWidget(self.versatz_x)
        wahl.addWidget(self.versatz_y)
        wahl.addStretch(1)
        spalte.addLayout(wahl)

        self.leinwand.auswahl_geaendert.connect(self._zeige_auswahl)

        zeile = QHBoxLayout()
        # NAMEN AUS: Bei 25 Bereichen -- neun Lampen und acht Ziffernstellen --
        # legen sich die Beschriftungen uebereinander und verdecken genau die
        # Anzeige, an der man beurteilen soll, ob der Rahmen sitzt. Wer wissen
        # will, was unter dem Zeiger liegt, liest es in der Zeile darueber.
        namen = QCheckBox("Namen einblenden")
        namen.setChecked(False)
        namen.toggled.connect(self.leinwand.set_namen)
        zeile.addWidget(namen)

        if tafeln > 1:
            self.alle = QCheckBox(f"auf alle {tafeln} Tafeln uebertragen")
            self.alle.setToolTip(
                "Die Bereiche liegen in normierten Tafelkoordinaten -- was "
                "hier sitzt, sitzt auf jeder Tafel derselben Bauart. Sinnvoll "
                "bei einem Fehler der Bauart, nicht bei einer einzelnen "
                "schief stehenden Tafel.")
            zeile.addWidget(self.alle)
        else:
            self.alle = None

        zurueck = QPushButton("Zuruecksetzen")
        zurueck.setToolTip("Alle Bereiche wieder so, wie sie beim Oeffnen waren")
        zurueck.clicked.connect(lambda: self.leinwand.setze_rois(self._ausgang))
        zeile.addWidget(zurueck)
        zeile.addStretch(1)
        spalte.addLayout(zeile)

        knoepfe = QDialogButtonBox()
        knoepfe.addButton("Uebernehmen", QDialogButtonBox.AcceptRole)
        knoepfe.addButton("Abbrechen", QDialogButtonBox.RejectRole)
        knoepfe.accepted.connect(self._uebernehmen)
        knoepfe.rejected.connect(self.reject)
        spalte.addWidget(knoepfe)

        self._passe_groesse_an(px)

        # FRUEHER LIEF DER TAKT IMMER, mit der Begruendung, im Livestream
        # wechselten die Ziffern und ein Standbild zeige zu wenig. Das stimmt
        # fuer die grobe Lage der Tafel -- und ist genau falsch fuer die
        # Ziffernrahmen: Dort aendert sich das Bild unter der Hand, waehrend
        # man zieht, und man sieht nie, ob die Aenderung etwas gebracht hat.
        #
        # Der Takt bleibt deshalb, aber das Standbild ist die Vorgabe. Wer
        # mehrere Anzeigen sehen will, schaltet es ab oder springt gezielt
        # weiter.
        self._takt = QTimer(self)
        self._takt.timeout.connect(self._bild_erneuern)
        self._springer = springer

    # ------------------------------------------------------------ Innereien

    def _passe_groesse_an(self, px: tuple[int, int]) -> None:
        """So gross wie moeglich, aber innerhalb des Bildschirms.

        Derselbe Fehler wie beim Bestaetigungsdialog soll sich nicht
        wiederholen: "kann man wegen der Fenstergroesse nicht bestaetigen"
        (Nutzer, 2026-09-10).
        """
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QApplication
        schirm = QApplication.primaryScreen()
        platz = schirm.availableGeometry() if schirm else QRect(0, 0, 1280, 800)
        hoehe = max(420, int(platz.height() * 0.86))
        # Breite aus dem Seitenverhaeltnis der Tafel plus Rand -- ein breites
        # Fenster um ein quadratisches Bild ist nur leere Flaeche.
        bild_hoehe = hoehe - 170
        breite = min(int(platz.width() * 0.9),
                     max(460, int(bild_hoehe * px[0] / max(1, px[1])) + 60))
        self.resize(breite, hoehe)
        self.setMaximumSize(platz.width(), platz.height())

    def _zeige_auswahl(self, anzahl: int) -> None:
        """Meldet, wie viele Bereiche gewaehlt sind, und setzt den Versatz zurueck.

        ZURUECKSETZEN IST WESENTLICH: Die Felder zeigen den Versatz DIESER
        Auswahl. Bliebe der alte Wert stehen, verschoebe die naechste Auswahl
        sich beim ersten Dreh um die Differenz zu einem Wert, der sie nie
        betraf.
        """
        self.auswahl_info.setText(
            "nichts gewaehlt" if not anzahl
            else f"{anzahl} Bereich{'e' if anzahl > 1 else ''} gewaehlt")
        for feld in (self.versatz_x, self.versatz_y):
            feld.blockSignals(True)
            feld.setValue(0)
            feld.blockSignals(False)
        self._versatz_angewandt = (0, 0)

    def _on_versatz(self) -> None:
        """Schiebt die Auswahl auf den eingestellten Gesamtversatz.

        Die Felder tragen den GESAMTversatz, verschoben wird die Differenz --
        dasselbe Muster wie bei den Ziffernrahmen im Hauptfenster. Wer von +2
        auf +3 dreht, verschiebt um einen Pixel, nicht um drei.
        """
        soll = (self.versatz_x.value(), self.versatz_y.value())
        if not self.leinwand.auswahl:
            self.auswahl_info.setText("erst Bereiche anklicken")
            for feld in (self.versatz_x, self.versatz_y):
                feld.blockSignals(True)
                feld.setValue(0)
                feld.blockSignals(False)
            return
        self.leinwand.versetze(soll[0], soll[1])
        self._versatz_angewandt = soll

    def _zeige_bereich(self, name: str) -> None:
        if not name:
            self.info.setText(f"{len(self.leinwand.rois)} Bereiche")
            return
        roi = self.leinwand._roi(name)
        if roi is None:
            return
        x, y, w, h = roi.rect
        self.info.setText(f"{name} -- Lage {x:.3f}/{y:.3f}, "
                          f"Groesse {w:.3f}x{h:.3f}")
        if name.startswith(DIGIT_PREFIX):
            self._zeige_lupe(roi)

    def _zeige_lupe(self, roi: Roi) -> None:
        """Legt diesen Ziffernrahmen in die Lupe.

        DER LESER UND DIE UMRECHNUNG WERDEN EINMAL GEBAUT und dann behalten:
        Das Bauen kostet, und die Lupe wird bei jeder Mausbewegung gefuellt.
        """
        if self._original is None:
            return
        try:
            if self._leser is None:
                from ..config import load_config
                from ..detection.digit_reader import CalibratedDigitReader
                cfg = load_config()
                self._leser = CalibratedDigitReader(cfg.detection.digits)
                self._umrechnung = self._lane.transform(
                    cfg.calibration.warped_width,
                    cfg.calibration.warped_height)
        except Exception as exc:  # noqa: BLE001
            # Die Lupe ist Hilfe, nicht Voraussetzung -- ein Fehler hier darf
            # das Nachkalibrieren nicht verhindern (P8).
            log.warning("Ziffernlupe nicht einsatzbereit: %s", exc)
            self.lupe.setze_hinweis(f"Lupe nicht verfuegbar: {exc}")
            return
        self.lupe.zeige(roi.name, roi.rect, self._original, self._leser,
                        self._umrechnung)

    def _lupe_hat_geaendert(self, name: str, rect: tuple) -> None:
        """Uebernimmt, was in der Lupe gezogen wurde.

        Die Lupe kennt die Bereichsliste nicht -- sie meldet nur, was aus dem
        Rechteck geworden ist. Geschrieben wird hier, damit es genau einen Ort
        gibt, an dem sich ein Bereich aendert.
        """
        for i, roi in enumerate(self.leinwand.rois):
            if roi.name == name:
                self.leinwand.rois[i] = roi.model_copy(update={"rect": rect})
                break
        self.leinwand.update()
        x, y, w, h = rect
        self.info.setText(f"{name} -- Lage {x:.4f}/{y:.4f}, "
                          f"Groesse {w:.4f}x{h:.4f}")

    def _on_standbild(self, an: bool) -> None:
        """Haelt das Bild an oder laesst es wieder laufen."""
        if an or self._bild_quelle is None:
            self._takt.stop()
        else:
            self._takt.start(BILDTAKT_MS)

    def _springe(self, schritt: int) -> None:
        """Holt ein Bild `schritt` Frames weiter und legt es unter die Rahmen.

        WOZU (Nutzer, 2026-09-15): *"nutze bitte ein Standbild und eventuell
        die Moeglichkeit mit Frames huepfen"*. Ob ein Ziffernrahmen sitzt,
        entscheidet sich an mehreren ANZEIGEN -- aber man will selbst
        bestimmen, wann gewechselt wird.
        """
        if self._springer is None:
            self.bild_info.setText("kein anderes Bild verfuegbar")
            return
        try:
            bild, nummer = self._springer(schritt)
        except Exception as exc:  # noqa: BLE001
            log.warning("Frame-Sprung fehlgeschlagen: %s", exc)
            self.bild_info.setText(f"Sprung fehlgeschlagen: {exc}")
            return
        if bild is None:
            self.bild_info.setText(
                "zurueck geht es im Stream nicht" if schritt < 0
                else "gerade kein neues Bild da")
            return
        self._original = bild
        self.leinwand.set_bild(entzerre(bild, self._lane.quad))
        self.bild_info.setText(f"Frame {nummer}" if nummer is not None
                               else "frisches Bild")
        # Die Lupe zeigt denselben Rahmen, nur auf dem neuen Bild.
        if self.lupe._name:
            roi = self.leinwand._roi(self.lupe._name)
            if roi is not None:
                self._zeige_lupe(roi)

    def _bild_erneuern(self) -> None:
        """Neues Bild unter die Rahmen legen -- die Rahmen bleiben stehen."""
        if self._bild_quelle is None:
            return
        bild = self._bild_quelle()
        if bild is None:
            return
        # AUCH DAS ORIGINAL NACHZIEHEN. Die Lupe liest daraus; bliebe es
        # stehen, zeigte sie ein Bild, das es so nicht mehr gibt.
        self._original = bild
        self.leinwand.set_bild(entzerre(bild, self._lane.quad))

    @property
    def rois(self) -> list[Roi]:
        return self.leinwand.rois

    def _uebernehmen(self) -> None:
        self.auf_alle = bool(self.alle is not None and self.alle.isChecked())
        self._takt.stop()
        self.accept()

    def reject(self) -> None:
        self._takt.stop()
        super().reject()
