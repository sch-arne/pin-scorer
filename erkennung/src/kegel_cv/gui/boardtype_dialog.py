"""Auswahl der Kegelboard-Bauart -- mit Bildern statt Namen.

WOFUER -- Wunsch des Nutzers am 2026-09-10:

    "Automatisches Kalibrieren (klick) dann kommt ein Fenster 'Waehle dein
     Kegelboardtyp aus' (da sind dann ganz viele Bilder mit Kegelboards) und
     dort gibt es zusaetzlich 'neues Board aufnehmen' oder man klickt auf eins
     und dann wird das gesucht"

WARUM BILDER UND KEINE LISTE: Eine Bauart erkennt man am Aussehen, nicht am
Namen. `FUNK_klassisch` sagt niemandem etwas, der vor einer fremden Anlage
steht -- das Musterbild dagegen sofort. Deshalb ist das Bild die eigentliche
Schaltflaeche und der Name nur die Unterschrift.
"""

from __future__ import annotations

import logging

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..calibration.board_library import Tafeltyp
from ..calibration.korrekturen import Korrektur

log = logging.getLogger(__name__)

# Kantenlaenge der Vorschau. Gross genug, dass Lampenraute und Ziffernfelder
# zu erkennen sind -- daran unterscheidet der Nutzer zwei Bauarten.
VORSCHAU_PX = 190
SPALTEN = 3


def _als_pixmap(bild: np.ndarray, kante: int = VORSCHAU_PX) -> QPixmap:
    """Macht aus einem BGR-Musterbild eine Vorschau fuer die Oberflaeche."""
    hoehe, breite = bild.shape[:2]
    rgb = np.ascontiguousarray(bild[:, :, ::-1])
    qbild = QImage(rgb.data, breite, hoehe, 3 * breite, QImage.Format_RGB888)
    return QPixmap.fromImage(qbild).scaled(
        kante, kante, Qt.KeepAspectRatio, Qt.SmoothTransformation)


class TafeltypDialog(QDialog):
    """Zeigt die bekannten Bauarten als Bildkacheln zur Auswahl.

    Drei Ausgaenge, die der Aufrufer an `ergebnis` abliest:

        ein `Tafeltyp`   diese Bauart soll gesucht werden
        "alle"           jede bekannte Bauart durchprobieren
        "neu"            keine passt -- eine neue aufnehmen
    """

    def __init__(self, typen: list[Tafeltyp], vorgabe_anzahl: int = 4,
                 korrekturen: dict[str, list[Korrektur]] | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kegelboard-Bauart waehlen")
        self.ergebnis: Tafeltyp | str | None = None
        self._typen = typen
        # Gemerkte Feinkorrekturen je Bauart. Sie werden VORGESCHLAGEN, nicht
        # angewandt: Ob die Korrektur aus einer anderen Halle hier passt, weiss
        # der Mensch davor -- eine still uebernommene waere ein Fehler, den
        # niemand sucht, weil niemand von ihr weiss.
        self._korrekturen = korrekturen or {}
        self._auswahl: dict[str, object] = {}
        self.korrektur: Korrektur | None = None

        aussen = QVBoxLayout(self)
        aussen.addWidget(QLabel(
            "<b>Welche Bauart hat die Anlage im Bild?</b><br>"
            "Die gewaehlte Bauart wird im Bild gesucht; alle Tafeln desselben "
            "Typs werden dabei gefunden."))

        # WIE VIELE TAFELN ERWARTET WERDEN. Der Rechner kann das nicht wissen
        # -- aber wer davorsteht, sieht es. Und die Zahl ist das Abbruchkriterium
        # der Suche: Sind sie alle da, ist sie fertig; sonst laeuft sie bis zur
        # Zeitgrenze weiter, statt sich mit dem ersten Fund zufriedenzugeben.
        zeile = QHBoxLayout()
        zeile.addWidget(QLabel("Wie viele Tafeln sind im Bild?"))
        self.anzahl = QSpinBox()
        self.anzahl.setRange(1, 8)
        self.anzahl.setValue(max(1, min(8, vorgabe_anzahl)))
        self.anzahl.setToolTip(
            "Sobald so viele Tafeln gefunden sind, hoert die Suche auf. "
            "Werden es nicht alle, meldet sie nach Ablauf der Zeit, was sie "
            "hat.")
        zeile.addWidget(self.anzahl)
        zeile.addStretch(1)
        aussen.addLayout(zeile)

        if typen:
            aussen.addWidget(self._kacheln(typen))
        else:
            leer = QLabel(
                "Die Bibliothek ist noch leer.<br><br>"
                "Eine Bahn von Hand kalibrieren und dann "
                "<b>Neues Board aufnehmen</b> -- danach findet das Werkzeug "
                "diese Bauart ueberall wieder.")
            leer.setStyleSheet("padding:24px;")
            aussen.addWidget(leer)

        if len(typen) > 1:
            alle = QPushButton(f"Alle {len(typen)} Bauarten durchprobieren")
            alle.setToolTip("Dauert laenger, dafuer muss nichts gewusst werden.")
            alle.clicked.connect(lambda: self._waehle("alle"))
            aussen.addWidget(alle)

        neu = QPushButton("Neues Board aufnehmen ...")
        neu.setToolTip(
            "Fuer eine Bauart, die hier noch fehlt: eine Tafel von Hand "
            "vermessen, danach merkt sich das Werkzeug sie dauerhaft.")
        neu.setStyleSheet("padding:6px;")
        neu.clicked.connect(lambda: self._waehle("neu"))
        aussen.addWidget(neu)

        knoepfe = QDialogButtonBox(QDialogButtonBox.Cancel)
        knoepfe.rejected.connect(self.reject)
        aussen.addWidget(knoepfe)

    def _kacheln(self, typen: list[Tafeltyp]) -> QWidget:
        inhalt = QWidget()
        gitter = QGridLayout(inhalt)
        for i, typ in enumerate(typen):
            gitter.addWidget(self._kachel(typ), i // SPALTEN, i % SPALTEN)

        bereich = QScrollArea()
        bereich.setWidget(inhalt)
        bereich.setWidgetResizable(True)
        # Drei Kacheln nebeneinander, zwei Reihen sichtbar -- darueber
        # hinaus wird gerollt.
        bereich.setMinimumSize(SPALTEN * (VORSCHAU_PX + 30),
                               2 * (VORSCHAU_PX + 70))
        return bereich

    def _kachel(self, typ: Tafeltyp) -> QWidget:
        hoehe, breite = typ.muster.shape[:2]
        knopf = QPushButton()
        knopf.setIcon(_als_pixmap(typ.muster))
        # Das BILD ist die Schaltflaeche. Ohne gesetzte Icon-Groesse zeigt Qt
        # ein 16-Pixel-Briefmarkenbild, auf dem nichts zu erkennen ist.
        knopf.setIconSize(_als_pixmap(typ.muster).size())
        knopf.setToolTip(f"{typ.name}\n{breite}x{hoehe} px, "
                         f"{len(typ.bahn.rois)} Felder")
        knopf.clicked.connect(lambda _=False, t=typ: self._waehle(t))

        unterschrift = QLabel(f"<b>{typ.name}</b><br>"
                              f"<small>{len(typ.bahn.rois)} Felder</small>")
        unterschrift.setAlignment(Qt.AlignHCenter)

        kachel = QWidget()
        spalte = QVBoxLayout(kachel)
        spalte.setContentsMargins(4, 4, 4, 4)
        spalte.addWidget(knopf)
        spalte.addWidget(unterschrift)

        # GEMERKTE FEINKORREKTUREN dieser Bauart. Sie stehen unter der Kachel,
        # weil sie zu ihr gehoeren -- eine Korrektur ohne ihre Bauart ist
        # sinnlos. Ohne gemerkte Korrektur erscheint das Feld gar nicht: Ein
        # Auswahlfeld mit genau einem Eintrag ist nur Platz.
        gemerkte = self._korrekturen.get(typ.name, [])
        if gemerkte:
            wahl = QComboBox()
            wahl.addItem("ohne Feinkorrektur", None)
            for k in gemerkte:
                wahl.addItem(k.beschreibung(), k)
            wahl.setToolTip(
                "Von Hand nachgezogene Versaetze einer frueheren Kalibrierung "
                "derselben Bauart.\n\n"
                "Sie passen, wenn die Anlage dieselbe ist -- in einer anderen "
                "Halle koennen sie danebenliegen. Nach dem Uebernehmen laesst "
                "sich das im Bild pruefen.")
            self._auswahl[typ.name] = wahl
            spalte.addWidget(wahl)
        return kachel

    def _waehle(self, was: Tafeltyp | str) -> None:
        self.ergebnis = was
        if isinstance(was, Tafeltyp):
            feld = self._auswahl.get(was.name)
            self.korrektur = feld.currentData() if feld is not None else None
        self.accept()


def zeichne_treffer(bild: np.ndarray, treffer, ziel_breite: int = 900):
    """Malt die gefundenen Tafeln ins Bild -- zum Ansehen, nicht zum Rechnen.

    WOFUER: Der Nutzer will vor dem Uebernehmen sehen, ob die Rahmen sitzen
    ("meinetwegen mich auch noch fragt 'sitzt dieses Board?'"). Zahlen ueber
    tragende Merkmale beantworten das nicht -- ein Bild schon.
    """
    import cv2

    malbild = bild.copy()
    for i, t in enumerate(treffer, start=1):
        ecken = np.asarray(t.quad, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(malbild, [ecken], True, (0, 255, 0), 2, cv2.LINE_AA)
        x, y = ecken[0][0]
        cv2.putText(malbild, f"{i}", (int(x), max(18, int(y) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2, cv2.LINE_AA)
    hoehe, breite = malbild.shape[:2]
    if breite > ziel_breite:
        faktor = ziel_breite / breite
        malbild = cv2.resize(malbild, (ziel_breite, int(hoehe * faktor)))
    return malbild


class TrefferDialog(QDialog):
    """Zeigt die gefundenen Tafeln mit ihren ROIs und fragt, ob sie sitzen.

    ZWEI BILDER, weil sie zwei verschiedene Fragen beantworten:

    * die **Uebersicht** -- wurden die richtigen Tafeln gefunden, und wurde
      keine uebersehen?
    * die **entzerrten Tafeln mit ROIs** -- sitzen Lampen und Ziffern?

    Die zweite Frage laesst sich an der Uebersicht nicht beantworten: Dort
    misst eine Tafel rund 160 Pixel und eine Lampen-ROI sechs.
    """

    def __init__(self, uebersicht: np.ndarray, tafeln: np.ndarray,
                 kopfzeile: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sitzen die Tafeln?")

        # AUF DEN BILDSCHIRM PASSEN. Vorher wurde die Uebersicht auf ihre
        # eigene Kantenlaenge skaliert -- bei einem 1920er Bild also auf 1920
        # Pixel. Der Dialog wurde groesser als der Bildschirm, und die Knoepfe
        # rutschten hinaus: "kann man wegen der Fenstergroesse nicht
        # bestaetigen" (Nutzer, 2026-09-10).
        platz = self._verfuegbar()
        breite = max(480, int(platz.width() * 0.82))
        hoehe = max(360, int(platz.height() * 0.86))

        spalte = QVBoxLayout(self)
        kopf = QLabel(kopfzeile)
        kopf.setWordWrap(True)
        spalte.addWidget(kopf)

        spalte.addWidget(QLabel(
            "<b>Lampen und Ziffern</b> -- gelb Kegellampen, gruen die "
            "Gruenlampe, magenta die Wurfnummer, orange die Summen:"))
        spalte.addWidget(self._bildbereich(tafeln, breite - 60,
                                           int(hoehe * 0.46)), 3)

        spalte.addWidget(QLabel("<b>Wo sie im Bild sitzen:</b>"))
        spalte.addWidget(self._bildbereich(uebersicht, breite - 60,
                                           int(hoehe * 0.26)), 2)

        spalte.addWidget(QLabel(
            "<small>Die Nummern zaehlen von links nach rechts -- in dieser "
            "Reihenfolge werden gleich die Bahnnummern abgefragt.</small>"))

        self.resize(breite, hoehe)
        self.setMaximumSize(platz.width(), platz.height())

        knoepfe = QDialogButtonBox()
        knoepfe.addButton("Uebernehmen", QDialogButtonBox.AcceptRole)
        knoepfe.addButton("Verwerfen", QDialogButtonBox.RejectRole)
        knoepfe.accepted.connect(self.accept)
        knoepfe.rejected.connect(self.reject)
        spalte.addWidget(knoepfe)

    @staticmethod
    def _verfuegbar():
        """Der Bereich, den ein Fenster wirklich einnehmen darf.

        `availableGeometry` laesst die Taskleiste aus -- `geometry` nicht, und
        ein Dialog in voller Bildschirmhoehe schiebt seine Knoepfe darunter.
        """
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QApplication
        schirm = QApplication.primaryScreen()
        return schirm.availableGeometry() if schirm else QRect(0, 0, 1280, 800)

    @staticmethod
    def _bildbereich(bild: np.ndarray, breite: int, hoehe: int) -> QScrollArea:
        """Ein Bild, das sich einpasst statt den Dialog aufzublasen.

        Kleiner gerechnet wird nur, wenn noetig -- ein Bild kuenstlich
        aufzublasen bringt keine Erkenntnis, es macht nur die Pixel groesser.
        """
        h, b = bild.shape[:2]
        faktor = min(1.0, breite / b, hoehe / h) if b and h else 1.0
        marke = QLabel()
        marke.setPixmap(_als_pixmap(bild, kante=int(max(b, h) * faktor)))
        marke.setAlignment(Qt.AlignCenter)
        bereich = QScrollArea()
        bereich.setWidget(marke)
        bereich.setWidgetResizable(True)
        bereich.setMinimumHeight(min(hoehe, int(h * faktor) + 4))
        return bereich
