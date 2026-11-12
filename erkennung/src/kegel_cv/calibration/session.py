"""Ablaufsteuerung der Kalibrierung -- ohne Qt, damit vollstaendig testbar.

Die GUI ist nur Darstellung; die Frage "welcher Klick bedeutet was" gehoert in
eine Klasse ohne Qt-Abhaengigkeit (siehe Skill `kegel-gui`, Abschnitt 8).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from ..config import load_config
from ..models.quellen import ohne_zugangsdaten
from .geometry import GeometryError, Quad
from .model import (
    DIGIT_FIELDS,
    DIGIT_PREFIX,
    PIN_LAMP_PREFIX,
    Calibration,
    LaneCalibration,
    Roi,
    SourceHint,
    digit_roi_name,
    pin_lamp_name,
)

log = logging.getLogger(__name__)

CORNER_LABELS = ("oben links", "oben rechts", "unten rechts", "unten links")


class CalibrationStep(str, Enum):
    """Aktueller Schritt im Kalibrierungsablauf."""

    IDLE = "IDLE"                 # keine Bahn ausgewaehlt
    PICK_CORNERS = "PICK_CORNERS" # vier Eckpunkte setzen
    EDIT_ROIS = "EDIT_ROIS"       # ROIs innerhalb der Tafel anpassen
    PICK_ROIS = "PICK_ROIS"       # ROIs nacheinander anklicken
    FRAME_DIGITS = "FRAME_DIGITS" # Ziffern einzeln einrahmen (zwei Ecken je Stelle)


# Beschriftungen fuer das gefuehrte Setzen der ROIs.
ROI_LABELS: dict[str, str] = {
    "green_lamp": "gruene Lampe",
    "pin_count": "Feld Kegelanzahl (einstellig)",
    "throw_number": "Feld Wurfnummer (dreistellig)",
    "total_a": "Summenfeld A (oben rechts)",
    "total_b": "Summenfeld B (untere Zeile)",
    "left_display": "linkes zweistelliges Display",
}


def roi_label(name: str) -> str:
    """Menschenlesbare Beschriftung einer ROI."""
    if name.startswith(PIN_LAMP_PREFIX):
        return f"Kegellampe {name.removeprefix(PIN_LAMP_PREFIX)}"
    if name.startswith(DIGIT_PREFIX):
        rest = name.removeprefix(DIGIT_PREFIX)
        field, _, position = rest.rpartition("_")
        feld = ROI_LABELS.get(field, field)
        return f"{feld} — Ziffer {position}"
    return ROI_LABELS.get(name, name)


def digit_pick_order(fields: list[str] | None = None) -> list[str]:
    """Reihenfolge fuer das stellenweise Einrahmen der Ziffern.

    Standard sind die Felder, die fuer die Wurfauswertung zaehlen. `total_a`
    bleibt aussen vor, solange seine Bedeutung nicht geklaert ist (Q3) -- es
    laesst sich einzeln nachtragen.

    `left_display` ist seit 2026-08-28 dabei. Es zaehlt die FEHLWUERFE und ist
    damit die einzige Quelle fuer Wuerfe ohne Kegel: Faellt nichts, schaltet die
    Anlage die gruene Lampe gar nicht aus, und der Wurf ist fuer den Trigger
    unsichtbar (Q10). Vorher stand es hier mit der Begruendung "Bedeutung nicht
    geklaert" aussen vor -- geklaert ist sie inzwischen, und ohne die Rahmen
    fehlen die Nullwuerfe ersatzlos.
    """
    order = fields if fields is not None else ["throw_number", "pin_count",
                                               "total_b", "left_display"]
    return [digit_roi_name(field, i)
            for field in order
            for i in range(1, DIGIT_FIELDS.get(field, 1) + 1)]


def default_pick_order(pin_count: int = 9) -> list[str]:
    """Reihenfolge, in der die ROIs abgefragt werden.

    Erst die Raute von oben nach unten (so, wie der Blick sie ohnehin abgeht),
    dann die gruene Lampe, dann die Displays.
    """
    return (
        [pin_lamp_name(i) for i in range(1, pin_count + 1)]
        + ["green_lamp", "pin_count", "throw_number", "total_a", "total_b",
           "left_display"]
    )


def single_roi_choices(pin_count: int = 9) -> list[str]:
    """Alles, was sich EINZELN nachsetzen laesst -- inklusive jeder Ziffer.

    Sitzt eine einzelne Stelle daneben, muss man nur sie neu setzen koennen.
    Vorher liess sich nur das GESAMTFELD waehlen; wer eine Ziffer korrigieren
    wollte, musste das ganze Feld noch einmal durchlaufen -- und bekam dabei
    fuer jede Stelle wieder eine Standardbox statt zweier Ecken.
    """
    return default_pick_order(pin_count) + [
        digit_roi_name(feld, i)
        for feld in ("throw_number", "pin_count", "total_b", "total_a",
                     "left_display")
        for i in range(1, DIGIT_FIELDS.get(feld, 1) + 1)
    ]


class GuideStep(str, Enum):
    """Schritte der gefuehrten Kalibrierung."""

    AUS = "AUS"
    ECKEN = "ECKEN"           # vier Tafelecken dieser Bahn
    BEREICHE = "BEREICHE"     # Lampen und Felder (nur erste Bahn)
    ZIFFERN = "ZIFFERN"       # Ziffernstellen (nur erste Bahn)
    FERTIG = "FERTIG"         # alle Bahnen stehen, freies Nachbessern


@dataclass
class CalibrationSession:
    """Zustand einer laufenden Kalibrierung."""

    calibration: Calibration = field(default_factory=Calibration)
    # Groesse des entzerrten Tafelbilds -- wird gebraucht, um Frame-Klicks in
    # normierte Tafelkoordinaten umzurechnen.
    warped_width: int = 440
    warped_height: int = 530
    active_lane: int | None = None
    step: CalibrationStep = CalibrationStep.IDLE
    pending_points: list[tuple[float, float]] = field(default_factory=list)
    roi_queue: list[str] = field(default_factory=list)
    active_roi: str | None = None
    # Rand, der beim Einrahmen einer Ziffer zugegeben wird (normiert).
    # 0.004 entspricht bei einer 157 px breiten Tafel rund 0,6 px je Seite.
    digit_padding: float = 0.004
    # Overlay-Position -> reale Bahnnummer, aus der Konfiguration
    # (`calibration.lane_number_mapping`). Die Tafel ganz links im Overlay ist
    # nicht zwangslaeufig Bahn 1 -- in der bisherigen Halle zeigt es die
    # Bahnen 2 bis 5.
    #
    # WICHTIG: Diese Nummer geht in den Versand. Ohne sie meldet eine frische
    # Kalibrierung die Bahnen als 1..4, waehrend der Spielleiter 2..5 erwartet.
    # Genau das ist passiert: Alle vier Bahnen einer neu angelegten Kalibrierung
    # trugen `real_lane_number: null`, weil die Zuordnung nur fuer die
    # Platzhalter-Anzeige benutzt wurde und nie beim Anlegen einer Bahn.
    lane_number_mapping: list[int] | None = None

    # GEFUEHRTE KALIBRIERUNG. Vom Nutzer so beschrieben: erst Bahn 1
    # vollstaendig, dann Bahn 2 -- dort wird Bahn 1 uebernommen -- dann 3 und 4,
    # danach freies Nachbessern.
    #
    # Der Ablauf steht hier und nicht in der Oberflaeche, damit er ohne Qt
    # pruefbar ist. Die Oberflaeche fragt nur "was jetzt?" und zeigt es an.
    guide_step: GuideStep = GuideStep.AUS
    guide_lane: int = 0
    guide_lanes: int = 4

    # ------------------------------------------------------- Gefuehrter Ablauf

    def start_guide(self, lanes: int = 4) -> None:
        """Beginnt die gefuehrte Kalibrierung bei Bahn 1."""
        self.guide_lanes = lanes
        self.guide_lane = 1
        self.guide_step = GuideStep.ECKEN
        self.start_lane(1)

    def cancel_guide(self) -> None:
        self.guide_step = GuideStep.AUS
        self.guide_lane = 0

    @property
    def guide_active(self) -> bool:
        return self.guide_step not in (GuideStep.AUS, GuideStep.FERTIG)

    @property
    def guide_hint(self) -> str:
        """Was als Naechstes zu tun ist -- in einem Satz."""
        if self.guide_step is GuideStep.AUS:
            return ""
        if self.guide_step is GuideStep.FERTIG:
            return ("Alle Bahnen stehen. Jetzt einzelne Felder nachbessern: "
                    "anfassen und ziehen, Raender zum Verziehen.")
        bahn = self.guide_lane
        if self.guide_step is GuideStep.ECKEN:
            ecke = self.next_corner_label or "oben links"
            wie_viele = len(self.pending_points) + 1
            zusatz = ("" if bahn == 1 else
                      "  (die Felder von Bahn 1 werden uebernommen)")
            return (f"Bahn {bahn} von {self.guide_lanes} -- Tafelecke "
                    f"{wie_viele} von 4: {ecke} anklicken{zusatz}")
        if self.guide_step is GuideStep.BEREICHE:
            fertig, gesamt = self.roi_progress
            was = self.current_roi_label or ""
            return (f"Bahn {bahn} -- Bereich {fertig + 1} von {gesamt}: "
                    f"{was} anklicken")
        fertig, gesamt = self.roi_progress
        return (f"Bahn {bahn} -- Ziffer {fertig + 1} von {gesamt}: "
                f"{self.current_roi_label or ''}, "
                f"{self.digit_corner_label or 'oben links'}")

    def guide_advance(self) -> None:
        """Rueckt zum naechsten Schritt vor. Von der Oberflaeche gerufen,
        wenn der laufende Schritt fertig gemeldet hat.

        Nur die ERSTE Bahn durchlaeuft Bereiche und Ziffern. Bei den uebrigen
        werden sie beim Umranden uebernommen (siehe `_roi_muster`) -- die ROIs
        stehen in normierten Tafelkoordinaten und gelten fuer jede Tafel gleich.
        """
        if not self.guide_active:
            return

        if self.guide_step is GuideStep.ECKEN:
            if self.guide_lane == 1:
                self.guide_step = GuideStep.BEREICHE
                self.start_roi_picking()
            else:
                self._guide_naechste_bahn()
            return

        if self.guide_step is GuideStep.BEREICHE:
            self.guide_step = GuideStep.ZIFFERN
            self.start_digit_framing()
            return

        if self.guide_step is GuideStep.ZIFFERN:
            self._guide_naechste_bahn()

    def _guide_naechste_bahn(self) -> None:
        if self.guide_lane >= self.guide_lanes:
            self.guide_step = GuideStep.FERTIG
            self.step = CalibrationStep.EDIT_ROIS
            log.info("Gefuehrte Kalibrierung abgeschlossen -- %d Bahnen",
                     self.guide_lanes)
            return
        self.guide_lane += 1
        self.guide_step = GuideStep.ECKEN
        self.start_lane(self.guide_lane)

    # ------------------------------------------------------------ Bahnauswahl

    def start_lane(self, lane_id: int) -> None:
        """Beginnt die Kalibrierung einer Bahn. Bestehende Punkte gehen verloren."""
        self.active_lane = lane_id
        self.pending_points.clear()
        self.step = CalibrationStep.PICK_CORNERS
        log.info("Kalibrierung Bahn %d gestartet -- bitte %s anklicken",
                 lane_id, CORNER_LABELS[0])

    def cancel(self) -> None:
        self.active_lane = None
        self.pending_points.clear()
        self.roi_queue.clear()
        self.active_roi = None
        self.step = CalibrationStep.IDLE

    # -------------------------------------------------------------- Eckpunkte

    @property
    def next_corner_label(self) -> str | None:
        """Beschriftung des naechsten zu setzenden Eckpunkts."""
        if self.step is not CalibrationStep.PICK_CORNERS:
            return None
        if len(self.pending_points) >= 4:
            return None
        return CORNER_LABELS[len(self.pending_points)]

    def add_point(self, x: float, y: float) -> bool:
        """Fuegt einen Eckpunkt hinzu.

        Returns:
            True, wenn damit alle vier Punkte gesetzt sind (Viereck fertig).
        """
        if self.step is not CalibrationStep.PICK_CORNERS or self.active_lane is None:
            log.debug("Klick ignoriert -- keine Bahn im Kalibriermodus")
            return False
        if len(self.pending_points) >= 4:
            return True

        self.pending_points.append((x, y))
        log.debug("Bahn %d: Punkt %d gesetzt bei (%.1f, %.1f)",
                  self.active_lane, len(self.pending_points), x, y)
        return len(self.pending_points) == 4

    def undo_point(self) -> bool:
        """Nimmt den zuletzt gesetzten Punkt zurueck."""
        if not self.pending_points:
            return False
        removed = self.pending_points.pop()
        log.debug("Punkt zurueckgenommen: (%.1f, %.1f)", *removed)
        return True

    def commit_quad(self, default_rois: bool = True) -> LaneCalibration:
        """Uebernimmt die vier Punkte als Tafel-Viereck der aktiven Bahn.

        Raises:
            GeometryError: Viereck ist entartet oder Punkte in falscher Reihenfolge.
            RuntimeError: Es sind noch nicht vier Punkte gesetzt.
        """
        if self.active_lane is None:
            raise RuntimeError("Keine Bahn ausgewaehlt")
        if len(self.pending_points) != 4:
            raise RuntimeError(
                f"Es sind erst {len(self.pending_points)} von 4 Punkten gesetzt"
            )

        quad = Quad.from_points(self.pending_points)
        # Bewusst hier pruefen: Ein verdrehtes Viereck erzeugt ein gespiegeltes
        # Tafelbild, das oft noch plausibel aussieht -- der Fehler faellt sonst
        # erst bei der Erkennung auf, weit weg von seiner Ursache.
        quad.validate()

        existing = self.calibration.get_lane(self.active_lane)
        lane = LaneCalibration(
            lane_id=self.active_lane,
            quad=quad.as_list(),
            rois=existing.rois if existing else [],
            real_lane_number=(existing.real_lane_number if existing
                              else self.mapped_lane_number(self.active_lane)),
        )

        if default_rois and not lane.rois:
            # Von einer bereits kalibrierten Bahn UEBERNEHMEN statt die
            # allgemeine Vorlage zu benutzen.
            #
            # Die ROIs stehen in normierten TAFELkoordinaten -- bezogen auf das
            # entzerrte Viereck, nicht auf das Bild. Vier baugleiche Tafeln
            # haben damit dieselben Werte, gleichgueltig wie schraeg sie im
            # Overlay stehen. Wer eine Bahn sauber eingestellt hat, bekommt die
            # Arbeit fuer die uebrigen drei geschenkt und muss nur noch
            # nachjustieren.
            #
            # Die allgemeine Vorlage bleibt fuer die ERSTE Bahn; sie stammt aus
            # einer Nutzerkalibrierung einer anderen Halle und passt dort, wo
            # die Anlage anders steht, naturgemaess schlecht.
            muster = self._roi_muster()
            lane.rois = muster if muster else default_roi_layout()

        self.calibration.set_lane(lane)
        self.pending_points.clear()
        self.step = CalibrationStep.EDIT_ROIS
        log.info("Bahn %d kalibriert (Flaeche %.0f px^2, %d ROIs)",
                 self.active_lane, quad.area, len(lane.rois))
        return lane

    def move_quad_corner(self, lane_id: int, index: int,
                         frame_x: float, frame_y: float) -> bool:
        """Verschiebt eine Ecke einer bereits kalibrierten Bahn.

        Die ROIs bleiben unveraendert -- sie stehen in normierten
        Tafelkoordinaten und wandern mit dem Viereck automatisch mit. Genau
        dafuer sind sie normiert.

        Das Viereck wird NICHT geprueft: Waehrend des Ziehens laeuft eine Ecke
        zwangslaeufig durch ungueltige Lagen. Geprueft wird beim Loslassen
        (`validate_quad`).
        """
        lane = self.calibration.get_lane(lane_id)
        if lane is None or not (0 <= index < len(lane.quad)):
            return False
        lane.quad[index] = [float(frame_x), float(frame_y)]
        return True

    def validate_quad(self, lane_id: int) -> tuple[bool, str]:
        """Prueft das Viereck nach dem Ziehen. Meldet Fehler als Text."""
        lane = self.calibration.get_lane(lane_id)
        if lane is None:
            return False, "Bahn nicht kalibriert"
        try:
            Quad.from_points([(p[0], p[1]) for p in lane.quad]).validate()
        except GeometryError as exc:
            return False, str(exc)
        return True, ""

    def move_roi(self, lane_id: int, name: str,
                 frame_x: float, frame_y: float) -> bool:
        """Schiebt einen Bereich mittig auf den Punkt -- Groesse bleibt."""
        lane = self.calibration.get_lane(lane_id)
        if lane is None:
            return False
        roi = lane.get_roi(name)
        if roi is None:
            return False
        try:
            transform = lane.transform(self.warped_width, self.warped_height)
        except GeometryError:
            return False
        norm = transform.frame_to_norm(
            np.array([[frame_x, frame_y]], dtype=np.float32))[0]
        cx, cy = float(norm[0]), float(norm[1])
        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
            return False
        lane.set_roi(roi.moved_to(cx, cy).model_copy(update={"enabled": True}))
        return True

    # Kleinste zulaessige Kantenlaenge eines Bereichs, normiert. Bei einer
    # 157 px breiten Tafel sind 0,02 rund 3 Pixel -- darunter ist nichts mehr
    # messbar, und ein versehentlich auf null gezogener Bereich waere still
    # kaputt statt sichtbar falsch.
    MINDESTKANTE = 0.02

    def resize_roi(self, lane_id: int, name: str, kante: str,
                   frame_x: float, frame_y: float) -> bool:
        """Zieht einen RAND oder eine ECKE eines Bereichs auf den Punkt.

        Verschieben allein genuegt nicht: Eine Ziffernbox muss in der GROESSE
        stimmen, nicht nur in der Lage -- aus ihr ergeben sich die
        Segmentflaechen rein geometrisch. Wer nur schieben kann, muss bei einer
        zu grossen Box neu einrahmen.

        `kante` ist eine Kombination aus t/b und l/r ("t", "bl", "r", ...).
        """
        lane = self.calibration.get_lane(lane_id)
        if lane is None:
            return False
        roi = lane.get_roi(name)
        if roi is None:
            return False
        try:
            transform = lane.transform(self.warped_width, self.warped_height)
        except GeometryError:
            return False

        norm = transform.frame_to_norm(
            np.array([[frame_x, frame_y]], dtype=np.float32))[0]
        nx, ny = float(norm[0]), float(norm[1])
        if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
            return False

        x, y, w, h = roi.rect
        links, oben, rechts, unten = x, y, x + w, y + h

        if "l" in kante:
            links = min(nx, rechts - self.MINDESTKANTE)
        if "r" in kante:
            rechts = max(nx, links + self.MINDESTKANTE)
        if "t" in kante:
            oben = min(ny, unten - self.MINDESTKANTE)
        if "b" in kante:
            unten = max(ny, oben + self.MINDESTKANTE)

        lane.set_roi(roi.model_copy(update={
            "rect": (links, oben, rechts - links, unten - oben),
            "enabled": True,
        }))
        return True

    def _roi_muster(self) -> list[Roi]:
        """ROIs einer bereits kalibrierten Bahn, als Vorlage fuer die naechste.

        Genommen wird die Bahn mit den MEISTEN ROIs -- an ihr wurde am meisten
        gearbeitet, insbesondere die stellenweise eingerahmten Ziffern. Kopiert
        wird, damit spaetere Aenderungen die Vorlage nicht mitverschieben.
        """
        kandidaten = [lane for lane in self.calibration.lanes
                      if lane.lane_id != self.active_lane and lane.rois]
        if not kandidaten:
            return []
        beste = max(kandidaten, key=lambda lane: len(lane.rois))
        log.info("Bahn %s: ROIs von Bahn %d uebernommen (%d Bereiche) -- "
                 "normierte Tafelkoordinaten gelten fuer jede Tafel gleich",
                 self.active_lane, beste.lane_id, len(beste.rois))
        return [roi.model_copy(deep=True) for roi in beste.rois]

    def mapped_lane_number(self, lane_id: int) -> int | None:
        """Reale Bahnnummer zu einer Overlay-Position, laut Konfiguration."""
        mapping = self.lane_number_mapping
        if not mapping or not (1 <= lane_id <= len(mapping)):
            return None
        return mapping[lane_id - 1]

    def try_commit(self, default_rois: bool = True) -> tuple[bool, str]:
        """Wie commit_quad, meldet Fehler aber als Text statt als Exception.

        Fuer die GUI gedacht: Ein Bedienfehler soll eine verstaendliche Meldung
        erzeugen, keinen Stacktrace.
        """
        try:
            self.commit_quad(default_rois=default_rois)
            return True, f"Bahn {self.active_lane} kalibriert"
        except (GeometryError, RuntimeError) as exc:
            log.warning("Kalibrierung Bahn %s fehlgeschlagen: %s", self.active_lane, exc)
            return False, str(exc)

    # ------------------------------------------------------- ROIs per Klick

    def start_roi_picking(self, names: list[str] | None = None) -> bool:
        """Startet das gefuehrte Setzen der ROIs fuer die aktive Bahn.

        Args:
            names: ROI-Namen in Abfragereihenfolge. None = Standardreihenfolge
                (erst die neun Kegellampen, dann gruene Lampe, dann Displays).

        Returns:
            False, wenn die Bahn noch keine Eckpunkte hat -- ohne Viereck gibt es
            keine Tafelkoordinaten, in die sich ein Klick umrechnen liesse.
        """
        if self.active_lane is None or self.calibration.get_lane(self.active_lane) is None:
            log.warning("ROI-Auswahl nicht moeglich: Bahn %s ist nicht kalibriert",
                        self.active_lane)
            return False

        self.roi_queue = list(names) if names is not None else default_pick_order()
        self.active_roi = self.roi_queue[0] if self.roi_queue else None
        self.step = CalibrationStep.PICK_ROIS
        log.info("Bahn %d: ROI-Auswahl gestartet (%d Bereiche) -- bitte %s anklicken",
                 self.active_lane, len(self.roi_queue), roi_label(self.active_roi or ""))
        return True

    @staticmethod
    def _ist_lampe(roi_name: str | None) -> bool:
        """Kegellampe oder gruene Lampe? Nur fuer sie gilt die Sollgroesse."""
        return bool(roi_name) and (roi_name.startswith(PIN_LAMP_PREFIX)
                                    or roi_name == "green_lamp")

    @property
    def current_roi_label(self) -> str | None:
        """Beschriftung der ROI, die gerade gesetzt werden soll."""
        if self.active_roi is None:
            return None
        if self.step not in (CalibrationStep.PICK_ROIS, CalibrationStep.FRAME_DIGITS):
            return None
        return roi_label(self.active_roi)

    @property
    def roi_progress(self) -> tuple[int, int]:
        """(bereits gesetzt, insgesamt) im laufenden ROI-Durchgang."""
        total = len(self.roi_queue)
        remaining = len(self.roi_queue) - self.roi_queue.index(self.active_roi) \
            if self.active_roi in self.roi_queue else 0
        return total - remaining, total

    def place_roi(self, frame_x: float, frame_y: float) -> bool:
        """Setzt die aktuelle ROI mittig auf den angeklickten Punkt.

        Der Klick kommt in Frame-Pixeln und wird ueber die Homographie der Bahn
        in normierte Tafelkoordinaten umgerechnet -- nur so bleibt die ROI auch
        bei anderer Aufloesung oder Perspektive gueltig.

        Returns:
            True, wenn damit alle ROIs der Warteschlange gesetzt sind.
        """
        if self.step is not CalibrationStep.PICK_ROIS or self.active_roi is None:
            return False

        lane = self.calibration.get_lane(self.active_lane or 0)
        if lane is None:
            return False

        try:
            transform = lane.transform(self.warped_width, self.warped_height)
        except GeometryError as exc:
            log.error("Bahn %s: Transformation ungueltig, ROI nicht setzbar: %s",
                      self.active_lane, exc)
            return False

        point = np.array([[frame_x, frame_y]], dtype=np.float32)
        norm = transform.frame_to_norm(point)[0]
        cx, cy = float(norm[0]), float(norm[1])

        if not (0.0 <= cx <= 1.0 and 0.0 <= cy <= 1.0):
            # Bewusst nicht klemmen: Ein Klick neben die Tafel ist fast immer ein
            # Vertipper. Eine an den Rand geschobene ROI saehe gesetzt aus,
            # waere aber falsch -- und der Fehler fiele erst bei der Erkennung auf.
            log.warning("Klick liegt ausserhalb der Tafel (%.2f, %.2f) -- ignoriert",
                        cx, cy)
            return False

        existing = lane.get_roi(self.active_roi)
        # LAMPEN BEKOMMEN IMMER DIE SOLLGROESSE (gemeldet 2026-09-04).
        #
        # `moved_to` verschiebt nur und laesst die Groesse, wie sie war. Beim
        # GEFUEHRTEN Setzen existieren die ROIs aber immer schon -- sie kommen
        # aus der Vorlage (`_roi_muster`) oder der Raute
        # (`default_roi_layout`). Damit griff `default_roi_size` nie, und eine
        # Vorlage mit WEITEN Lampen vererbte ihre Groesse an jede neu
        # geklickte Bahn: Der Nutzer legte eine neue Kalibrierung an und
        # bekam die alten, zu grossen Rahmen zurueck, ohne dass es eine
        # Moeglichkeit gab, das im gefuehrten Ablauf zu korrigieren.
        #
        # WARUM NUR LAMPEN: Ihre Groesse ist gemessen und entscheidet ueber
        # die Trennschaerfe zwischen AN und AUS (Bahn 4: 33,7 -> 44,8 Punkte,
        # unentschiedene Messungen 6,73 % -> 0,50 %). Bei den Ziffernfeldern
        # kann eine von Hand angepasste Groesse dagegen gewollt sein -- und
        # die stellenweise eingerahmten Ziffern kennt `default_roi_size` gar
        # nicht; sie wuerden auf einen Ersatzwert gesetzt und waeren zerstoert.
        if existing is not None and self._ist_lampe(self.active_roi):
            soll_w, soll_h = default_roi_size(self.active_roi)
            if (abs(existing.rect[2] - soll_w) > 1e-6
                    or abs(existing.rect[3] - soll_h) > 1e-6):
                log.info("Bahn %s: %s auf Sollgroesse gesetzt "
                         "(%.4f x %.4f statt %.4f x %.4f)",
                         self.active_lane, self.active_roi, soll_w, soll_h,
                         existing.rect[2], existing.rect[3])
            lane.set_roi(existing.model_copy(update={
                "rect": (_clamp01(cx - soll_w / 2, soll_w),
                         _clamp01(cy - soll_h / 2, soll_h), soll_w, soll_h),
                "enabled": True,
            }))
        elif existing is not None:
            # `enabled=True` ist Absicht, nicht Beiwerk: Wer einen Bereich von
            # Hand setzt, will ihn benutzt haben.
            #
            # BEOBACHTET: Der Fehlwurfzaehler wird aus der Vorlage abgeschaltet
            # angelegt. Wurde er dann gesetzt, verschob `moved_to` nur das
            # Rechteck und liess den Schalter aus -- die Oberflaeche zeichnete
            # keinen Rahmen (sie ueberspringt abgeschaltete Bereiche), und
            # gelesen wurde das Feld auch nicht. Es sah aus, als liesse es sich
            # nicht kalibrieren.
            lane.set_roi(existing.moved_to(cx, cy).model_copy(
                update={"enabled": True}))
        else:
            width, height = default_roi_size(self.active_roi)
            lane.set_roi(Roi(
                name=self.active_roi,
                rect=(_clamp01(cx - width / 2, width),
                      _clamp01(cy - height / 2, height), width, height),
                pin_number=_pin_number_of(self.active_roi),
            ))

        log.debug("Bahn %s: %s gesetzt bei (%.3f, %.3f)",
                  self.active_lane, self.active_roi, cx, cy)
        return self._advance_roi()

    def skip_roi(self) -> bool:
        """Ueberspringt die aktuelle ROI (behaelt ihre bisherige Position)."""
        if self.step is not CalibrationStep.PICK_ROIS:
            return False
        log.debug("ROI uebersprungen: %s", self.active_roi)
        return self._advance_roi()

    def select_roi(self, name: str) -> bool:
        """Waehlt gezielt eine einzelne ROI zum Neusetzen aus.

        EINE Ziffernstelle wird ueber ZWEI Ecken gesetzt, nicht ueber einen
        Klick in die Mitte. Der Unterschied ist nicht kosmetisch: Aus der Box
        ergeben sich die Segmentflaechen rein geometrisch, und eine
        Standardgroesse um den Klickpunkt trifft keine Ziffer.

        Vorher landete jede einzeln gewaehlte Ziffernstelle in `PICK_ROIS` und
        bekam damit eine Standardbox verpasst -- sie "hing sonst wo". Aufgefallen
        ist das erst, als der Fehlwurfzaehler einzeln nachgesetzt werden musste.
        """
        lane = self.calibration.get_lane(self.active_lane or 0)
        if lane is None:
            return False
        self.roi_queue = [name]
        self.active_roi = name
        self.pending_points.clear()
        if name.startswith(DIGIT_PREFIX):
            self.step = CalibrationStep.FRAME_DIGITS
            log.info("Bahn %s: %s einrahmen -- zwei Ecken (oben links, "
                     "unten rechts)", self.active_lane, roi_label(name))
        else:
            self.step = CalibrationStep.PICK_ROIS
            log.info("Bahn %s: %s neu setzen", self.active_lane, roi_label(name))
        return True

    def _advance_roi(self) -> bool:
        """Rueckt zur naechsten ROI vor. True, wenn die Warteschlange leer ist."""
        if self.active_roi in self.roi_queue:
            index = self.roi_queue.index(self.active_roi)
            if index + 1 < len(self.roi_queue):
                self.active_roi = self.roi_queue[index + 1]
                return False

        self.active_roi = None
        self.roi_queue.clear()
        self.pending_points.clear()
        self.step = CalibrationStep.EDIT_ROIS
        log.info("Bahn %s: alle Bereiche gesetzt", self.active_lane)
        return True

    # ---------------------------------------------- Ziffern einzeln einrahmen

    def start_digit_framing(self, names: list[str] | None = None) -> bool:
        """Startet das stellenweise Einrahmen der Ziffern.

        Je Ziffer werden ZWEI Ecken geklickt (oben links, unten rechts). Das ist
        aufwendiger als ein Klick auf die Mitte, aber notwendig: Aus der exakten
        Box ergeben sich die Segmentflaechen rein geometrisch. Jedes Verfahren,
        das die Ziffernbreite schaetzt, ist am Material gescheitert.
        """
        if self.active_lane is None or self.calibration.get_lane(self.active_lane) is None:
            log.warning("Ziffern einrahmen nicht moeglich: Bahn %s nicht kalibriert",
                        self.active_lane)
            return False

        self.roi_queue = list(names) if names is not None else digit_pick_order()
        self.active_roi = self.roi_queue[0] if self.roi_queue else None
        self.pending_points.clear()
        self.step = CalibrationStep.FRAME_DIGITS
        log.info("Bahn %d: %d Ziffern einrahmen -- je zwei Ecken. Zuerst %s",
                 self.active_lane, len(self.roi_queue), roi_label(self.active_roi or ""))
        return True

    @property
    def digit_corner_label(self) -> str | None:
        """Welche Ecke der aktuellen Ziffer als naechstes gesetzt wird."""
        if self.step is not CalibrationStep.FRAME_DIGITS or self.active_roi is None:
            return None
        return "oben links" if not self.pending_points else "unten rechts"

    def frame_digit(self, frame_x: float, frame_y: float) -> bool:
        """Nimmt eine Ecke der aktuellen Ziffer entgegen.

        Returns:
            True, wenn damit ALLE Ziffern eingerahmt sind.
        """
        if self.step is not CalibrationStep.FRAME_DIGITS or self.active_roi is None:
            return False

        lane = self.calibration.get_lane(self.active_lane or 0)
        if lane is None:
            return False

        try:
            transform = lane.transform(self.warped_width, self.warped_height)
        except GeometryError as exc:
            log.error("Bahn %s: Transformation ungueltig: %s", self.active_lane, exc)
            return False

        point = np.array([[frame_x, frame_y]], dtype=np.float32)
        norm = transform.frame_to_norm(point)[0]
        nx, ny = float(norm[0]), float(norm[1])

        if not (0.0 <= nx <= 1.0 and 0.0 <= ny <= 1.0):
            log.warning("Klick ausserhalb der Tafel (%.2f, %.2f) -- ignoriert", nx, ny)
            return False

        if not self.pending_points:
            self.pending_points.append((frame_x, frame_y))
            return False

        # Zweite Ecke: Box bilden
        first = transform.frame_to_norm(
            np.array([list(self.pending_points[0])], dtype=np.float32))[0]
        x0, x1 = sorted((float(first[0]), nx))
        y0, y1 = sorted((float(first[1]), ny))
        self.pending_points.clear()

        # Rand zugeben: Der Nutzer trifft beim Einrahmen naturgemaess nicht
        # pixelgenau, und ein zu enger Rahmen schneidet die aeusseren Segmente
        # an. Lieber etwas Gehaeuse mitnehmen -- die Binarisierung verwirft es.
        pad = self.digit_padding
        x0, y0 = max(0.0, x0 - pad), max(0.0, y0 - pad)
        x1, y1 = min(1.0, x1 + pad), min(1.0, y1 + pad)

        if x1 - x0 < 0.005 or y1 - y0 < 0.005:
            log.warning("Ziffernrahmen zu klein (%.3f x %.3f) -- bitte erneut",
                        x1 - x0, y1 - y0)
            return False

        lane.set_roi(Roi(name=self.active_roi, rect=(x0, y0, x1 - x0, y1 - y0)))
        log.debug("Bahn %s: %s eingerahmt (%.3f, %.3f, %.3f, %.3f)",
                  self.active_lane, self.active_roi, x0, y0, x1 - x0, y1 - y0)
        return self._advance_roi()

    # ------------------------------------------------------- Reale Bahnnummer

    def set_real_lane_number(self, lane_id: int, nummer: int | None) -> str | None:
        """Legt fest, unter welcher Bahnnummer diese Tafel gemeldet wird.

        WARUM DAS EINSTELLBAR SEIN MUSS

        Die Tafeln im Bild sind von links durchnummeriert (`lane_id` 1..4), die
        Ergebnisse tragen aber die BAHNNUMMER der Halle. In der Stammhalle sind
        das die Bahnen 2 bis 5; auswaerts kann dieselbe Anordnung 1 bis 4 oder
        6 bis 9 heissen. Bisher kam die Zuordnung allein aus
        `calibration.lane_number_mapping` und liess sich nur in der Datei
        aendern -- also nicht dort, wo man vor Ort steht.

        Diese Zahl ist es, die als `lane` in der Datenbank landet
        (`ThrowAnalyzer(lane.lane_id, cfg, lane.display_number)`).

        Rueckgabe: None, wenn alles in Ordnung ist -- sonst ein Warntext.
        Doppelte Nummern werden NICHT verhindert, aber gemeldet: Sie sind fast
        immer ein Versehen, und in der Datenbank verschmelzen dann zwei Bahnen
        zu einer, ohne dass es auffiele. Es gibt aber keinen Grund, dem Nutzer
        einen Zwischenzustand zu verbieten, waehrend er die Nummern umsortiert.
        """
        bahn = next((l for l in self.calibration.lanes if l.lane_id == lane_id),
                    None)
        if bahn is None:
            raise KeyError(f"Bahn {lane_id} ist nicht kalibriert")

        bahn.real_lane_number = nummer
        log.info("Bahn (Tafel %d von links) meldet ab jetzt als Bahn %s",
                 lane_id, bahn.display_number)

        doppelt = [l.lane_id for l in self.calibration.lanes
                   if l.lane_id != lane_id
                   and l.display_number == bahn.display_number]
        if doppelt:
            andere = ", ".join(f"Tafel {i}" for i in sorted(doppelt))
            return (f"Bahnnummer {bahn.display_number} ist jetzt doppelt "
                    f"vergeben ({andere}). In der Datenbank verschmelzen "
                    f"diese Tafeln zu einer Bahn.")
        return None

    # --------------------------------------------------------------- Speichern

    def set_source_hint(self, width: int, height: int, video: str | None) -> None:
        """Merkt sich, aus welcher Quelle diese Kalibrierung stammt.

        Zugangsdaten werden HIER entfernt, nicht beim Aufrufer: Die
        Kalibrierungsdatei gehoert ins Repository -- sie ist die Vermessung
        einer Bahn und soll geteilt werden koennen. Ein Passwort darin waere
        auch nach dem Loeschen noch in der Historie (2026-09-09).
        """
        self.calibration.source_hint = SourceHint(
            width=width, height=height, video=ohne_zugangsdaten(video))


def _clamp01(value: float, size: float) -> float:
    """Haelt eine ROI-Position so im Bereich 0..1, dass sie samt Groesse hineinpasst."""
    return max(0.0, min(value, 1.0 - size))


def _pin_number_of(roi_name: str,
                   zuordnung: list[int] | None = None) -> int | None:
    """Kegelnummer einer Lampen-ROI.

    Der ROI-NAME zaehlt die Lampen so, wie sie auf der Tafel von oben nach
    unten liegen. Die KEGELNUMMER zaehlt von vorn. Beides faellt nur zusammen,
    wenn die Zuordnung die Identitaet ist -- am Material ist sie es nicht
    (siehe `calibration.pin_number_mapping`).
    """
    if not roi_name.startswith(PIN_LAMP_PREFIX):
        return None
    index = int(roi_name.removeprefix(PIN_LAMP_PREFIX))
    if zuordnung is None:
        zuordnung = load_config().calibration.pin_number_mapping
    if 1 <= index <= len(zuordnung):
        return zuordnung[index - 1]
    return index


def default_roi_size(roi_name: str) -> tuple[float, float]:
    """Startgroesse einer neu gesetzten ROI, gemessen am realen Material.

    GEMESSEN an der entzerrten Tafel: Die 7-Segment-Ziffern sind normiert rund
    **0,099 hoch**. Ein ROI von 0,093 waere also kleiner als die Ziffer selbst --
    die oberen und unteren Segmente fielen heraus, und die Segment-Dekodierung
    haette keine Chance.

    Die Felder haben deshalb **0,13 Hoehe**: die Ziffernhoehe plus rund 30 %
    Rand. Der Rand ist kein Luxus -- er faengt die Klickungenauigkeit des
    Nutzers ab (gemessen: 0,6-1,9 px Streuung) und den leichten Versatz
    zwischen den vier perspektivisch unterschiedlichen Tafeln.

    Die Breiten richten sich nach der Stelligkeit, ebenfalls mit Rand:
        1-stellig (Kegelanzahl)   Ziffernbreite ~0,068  ->  0,11
        2-stellig (Fehlwuerfe)    ~0,222                ->  0,26
        3-stellig (Wurfnummer)    ~0,199                ->  0,24
        4-stellig (Summen)        ~0,19 bzw. ~0,30      ->  0,24 / 0,33
    """
    if roi_name.startswith(PIN_LAMP_PREFIX):
        # Eng, nur die Leuchtflaeche -- siehe die Begruendung bei der
        # Rautenvorlage in `_default_rois`. Gehoert zu
        # `lamp_detection.pin.core_percentile: 0`.
        return 0.040, 0.0375
    return {
        "green_lamp": (0.065, 0.052),   # Lampe, keine Ziffer -- bleibt eng
        "pin_count": (0.110, 0.130),
        "throw_number": (0.240, 0.130),
        "total_a": (0.240, 0.130),
        "total_b": (0.330, 0.130),
        "left_display": (0.260, 0.130),
    }.get(roi_name, (0.12, 0.10))


def default_roi_layout(pin_count: int = 9,
                       zuordnung: list[int] | None = None) -> list[Roi]:
    """Startpositionen der ROIs in normierten Tafelkoordinaten.

    GEMESSEN an der entzerrten FUNK-Tafel (Bahn 3, Video 2026-08-22, Frame 90),
    nicht geschaetzt -- siehe docs/VIDEO_ANALYSIS.md und tools/verify_rois.py.
    Bezugsrahmen ist das beige Tafelgehaeuse: die Ecken, die der Nutzer anklickt.

    Es bleiben Startwerte -- der Nutzer justiert sie in der GUI nach. Ohne
    Startwerte muesste er 15 ROIs von Hand aufziehen, was die Kalibrierung
    unbenutzbar machen wuerde.

    Kegel-Raute (Lampenindex 1..9, oben nach unten):

              1
           2     3
        4     5     6
           7     8
              9
    """
    rois: list[Roi] = []

    # Kegellampen: Raute mit Zeilen zu 1, 2, 3, 2, 1 Lampen.
    #
    # NACHGEMESSEN am 2026-09-03 an der Leuchtfläche selbst: Die frueheren
    # Werte stammten aus einer Nutzerkalibrierung von Hand und lagen
    # systematisch zu hoch -- bis zu 0,011 in y. Beim alten, weiten Rahmen
    # (0,080 x 0,075) fiel das nicht auf; beim halbierten waeren 0,011 fast ein
    # Drittel der Hoehe.
    #
    # Grundlage sind die gemessenen Lampenmitten aus `1Spieltag_enge_lampen`,
    # gemittelt ueber alle vier Bahnen (Streuung zwischen den Bahnen 0,006 bis
    # 0,012). Die Raute ist dabei sauber symmetrisch: Der Mittelpunkt der
    # aeusseren wie der mittleren Lampen liegt auf 0,501.
    center_x = 0.501
    middle_dx, outer_dx = 0.161, 0.322
    row_pitch = 0.0753
    first_row_y = 0.353
    rows: list[tuple[float, list[float]]] = [
        (first_row_y + 0 * row_pitch, [center_x]),
        (first_row_y + 1 * row_pitch, [center_x - middle_dx, center_x + middle_dx]),
        (first_row_y + 2 * row_pitch, [center_x - outer_dx, center_x,
                                       center_x + outer_dx]),
        (first_row_y + 3 * row_pitch, [center_x - middle_dx, center_x + middle_dx]),
        (first_row_y + 4 * row_pitch, [center_x]),
    ]
    # ENG, nicht weit: Der Rahmen fasst nur die Leuchtflaeche, nicht das
    # Gehaeuse daneben. Gemessen am 2026-09-02 (tools/measure_roi_shrink.py)
    # hebt das die Trennung zwischen AN und AUS auf Bahn 4 von 33,7 auf 44,8
    # Punkte und die unentschiedenen Messungen von 6,73 % auf 0,50 %.
    #
    # DAZU GEHOERT `lamp_detection.pin.core_percentile: 0`. Der Kernfilter war
    # ein Notbehelf fuer den weiten Rahmen; bei diesem hier schadet er, weil er
    # einer ohnehin kleinen Pixelmenge nochmals 70 % nimmt.
    lamp_w, lamp_h = 0.040, 0.0375
    index = 1
    for cy, xs in rows:
        for cx in xs:
            rois.append(Roi(
                name=pin_lamp_name(index),
                rect=(cx - lamp_w / 2, cy - lamp_h / 2, lamp_w, lamp_h),
                # Der Lampenindex zaehlt von oben, die Kegelnummer von
                # vorn -- die Zuordnung steht in der Konfiguration (Q5).
                pin_number=_pin_number_of(pin_lamp_name(index), zuordnung),
            ))
            index += 1
            if index > pin_count:
                break
        if index > pin_count:
            break

    # Displays: Mittelpunkte aus derselben Nutzerkalibrierung, Groessen nach
    # der gemessenen Ziffernhoehe (siehe default_roi_size).
    def centered(name: str, cx: float, cy: float, enabled: bool = True) -> Roi:
        w, h = default_roi_size(name)
        return Roi(name=name, rect=(cx - w / 2, cy - h / 2, w, h), enabled=enabled)

    # Gruene Lampe: mittig unter dem Kegelbild, zwischen den beiden Displays
    rois.append(centered("green_lamp", 0.504, 0.771))
    # Linkes zweistelliges Display: Fehlwurfzaehler (Q2). Wird in Phase 7
    # aktiviert, sobald die Ziffernerkennung steht.
    # Der Fehlwurfzaehler. Stand bis 2026-08-28 auf `enabled=False`, weil seine
    # Bedeutung als ungeklaert galt (Q2). Sie ist geklaert: Er zaehlt die
    # Wuerfe ohne Kegel und ist die EINZIGE Quelle dafuer -- faellt nichts,
    # schaltet die Anlage die gruene Lampe gar nicht aus, und der Wurf ist
    # sonst unsichtbar (Q10). Abgeschaltet fehlten solche Wuerfe ersatzlos.
    rois.append(centered("left_display", 0.182, 0.698))
    # Summe A: oben rechts, 4-stellig
    rois.append(centered("total_a", 0.780, 0.700))
    # Untere Displayzeile: Wurfnummer (3-stellig), Kegelanzahl (1), Summe B (4)
    rois.append(centered("throw_number", 0.232, 0.888))
    rois.append(centered("pin_count", 0.450, 0.888))
    rois.append(centered("total_b", 0.715, 0.888))

    return rois
