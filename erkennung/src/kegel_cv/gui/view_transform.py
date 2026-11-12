"""Abbildung zwischen Widget- und Frame-Koordinaten mit Zoom und Verschiebung.

Bewusst als eigene Klasse ohne Qt-Abhaengigkeit: Diese Rechnung ist die
fehleranfaelligste Stelle der gesamten Oberflaeche. Sitzt sie falsch, landen alle
Kalibrierpunkte daneben -- und der Fehler faellt erst viel spaeter auf, weit weg
von seiner Ursache. Ohne Qt laesst sie sich vollstaendig testen.

    Frame (1920x1080)  ---- scale, offset ---->  Widget (Pixel auf dem Schirm)
                       <--- widget_to_frame ----

Der Zoom ist beim Kalibrieren keine Bequemlichkeit: Eine Anzeigetafel misst rund
160x155 px im Originalframe. Bei einer typischen Fensterbreite bleibt davon etwa
ein Zehntel der Bildbreite -- eine einzelne Kegellampe waere dann rund 5 Pixel
gross und nicht zielsicher anklickbar.
"""

from __future__ import annotations

from dataclasses import dataclass

MIN_ZOOM = 1.0
MAX_ZOOM = 40.0


@dataclass
class ViewTransform:
    """Zustand der Ansicht: Bildgroesse, Widgetgroesse, Zoom, Bildmittelpunkt."""

    frame_width: int = 0
    frame_height: int = 0
    widget_width: int = 1
    widget_height: int = 1
    zoom: float = 1.0
    # Welcher Frame-Punkt liegt in der Mitte des Widgets?
    center_x: float = 0.0
    center_y: float = 0.0

    def set_frame_size(self, width: int, height: int) -> None:
        """Neues Bildformat. Setzt die Ansicht zurueck, wenn sich die Groesse aendert."""
        if (width, height) != (self.frame_width, self.frame_height):
            self.frame_width, self.frame_height = width, height
            self.reset()

    def set_widget_size(self, width: int, height: int) -> None:
        self.widget_width = max(1, width)
        self.widget_height = max(1, height)

    def reset(self) -> None:
        """Ganzes Bild einpassen."""
        self.zoom = 1.0
        self.center_x = self.frame_width / 2
        self.center_y = self.frame_height / 2

    # ------------------------------------------------------------ Abbildung

    @property
    def base_scale(self) -> float:
        """Skalierung, bei der das ganze Bild ins Widget passt."""
        if self.frame_width <= 0 or self.frame_height <= 0:
            return 1.0
        return min(self.widget_width / self.frame_width,
                   self.widget_height / self.frame_height)

    @property
    def scale(self) -> float:
        return self.base_scale * self.zoom

    @property
    def offset_x(self) -> float:
        return self.widget_width / 2 - self.center_x * self.scale

    @property
    def offset_y(self) -> float:
        return self.widget_height / 2 - self.center_y * self.scale

    def frame_to_widget(self, x: float, y: float) -> tuple[float, float]:
        return x * self.scale + self.offset_x, y * self.scale + self.offset_y

    def widget_to_frame(self, x: float, y: float) -> tuple[float, float]:
        scale = self.scale
        if scale <= 0:
            return 0.0, 0.0
        return (x - self.offset_x) / scale, (y - self.offset_y) / scale

    def contains_frame_point(self, x: float, y: float) -> bool:
        return 0 <= x <= self.frame_width and 0 <= y <= self.frame_height

    # ---------------------------------------------------------------- Zoomen

    def zoom_at(self, widget_x: float, widget_y: float, factor: float) -> None:
        """Zoomt so, dass der Punkt unter dem Mauszeiger stehen bleibt.

        Ohne diese Verankerung wandert das Bild beim Zoomen unter der Maus weg --
        beim Anvisieren einer 5-px-Lampe ist das unbrauchbar.
        """
        anchor_x, anchor_y = self.widget_to_frame(widget_x, widget_y)

        new_zoom = _clamp(self.zoom * factor, MIN_ZOOM, MAX_ZOOM)
        if new_zoom == self.zoom:
            return
        self.zoom = new_zoom

        # Neuen Mittelpunkt so waehlen, dass der Ankerpunkt wieder unter der
        # Maus liegt: widget = frame * scale + (widget_mitte - center * scale)
        scale = self.scale
        self.center_x = anchor_x - (widget_x - self.widget_width / 2) / scale
        self.center_y = anchor_y - (widget_y - self.widget_height / 2) / scale
        self._clamp_center()

    def zoom_to_rect(self, x: float, y: float, width: float, height: float,
                     margin: float = 1.25) -> None:
        """Zoomt auf einen Bildbereich -- etwa auf eine frisch kalibrierte Tafel.

        `margin` laesst Rand stehen, damit die Tafelkanten sichtbar bleiben.
        """
        if width <= 0 or height <= 0 or self.base_scale <= 0:
            return

        needed = min(self.widget_width / (width * margin),
                     self.widget_height / (height * margin))
        self.zoom = _clamp(needed / self.base_scale, MIN_ZOOM, MAX_ZOOM)
        self.center_x = x + width / 2
        self.center_y = y + height / 2
        self._clamp_center()

    def set_zoom(self, zoom: float) -> None:
        """Setzt den Zoomfaktor und haelt den Ausschnitt am Bild."""
        self.zoom = _clamp(zoom, MIN_ZOOM, MAX_ZOOM)
        self._clamp_center()

    def pan_by_widget(self, dx: float, dy: float) -> None:
        """Verschiebt die Ansicht um eine Strecke in Widget-Pixeln."""
        scale = self.scale
        if scale <= 0:
            return
        self.center_x -= dx / scale
        self.center_y -= dy / scale
        self._clamp_center()

    def _clamp_center(self) -> None:
        """Haelt den Bildausschnitt am Bild.

        Ohne diese Begrenzung liesse sich das Bild aus dem Fenster schieben, bis
        nur noch Hintergrund zu sehen ist -- und der Nutzer weiss nicht, wohin er
        zuruecknavigieren soll.
        """
        if self.frame_width <= 0 or self.frame_height <= 0:
            return
        if self.zoom <= 1.0:
            self.center_x = self.frame_width / 2
            self.center_y = self.frame_height / 2
            return

        # Sichtbarer Ausschnitt in Frame-Koordinaten
        half_w = self.widget_width / (2 * self.scale)
        half_h = self.widget_height / (2 * self.scale)

        self.center_x = _clamp(self.center_x, min(half_w, self.frame_width / 2),
                               max(self.frame_width - half_w, self.frame_width / 2))
        self.center_y = _clamp(self.center_y, min(half_h, self.frame_height / 2),
                               max(self.frame_height - half_h, self.frame_height / 2))

    @property
    def visible_rect(self) -> tuple[float, float, float, float]:
        """Sichtbarer Bildausschnitt (x, y, w, h) in Frame-Koordinaten."""
        half_w = self.widget_width / (2 * self.scale)
        half_h = self.widget_height / (2 * self.scale)
        return (self.center_x - half_w, self.center_y - half_h, half_w * 2, half_h * 2)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))
