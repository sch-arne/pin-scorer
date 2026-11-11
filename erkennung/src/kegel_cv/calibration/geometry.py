"""Geometrie: Vierecke, Homographie, Koordinatentransformation.

Zwei Koordinatensysteme (siehe Skill `kegel-kalibrierung`):

    FRAME-KOORDINATEN            TAFEL-KOORDINATEN
    Pixel im Originalvideo  <->  normiert 0..1 je Anzeigetafel

ROIs werden ausschliesslich in Tafelkoordinaten gespeichert. Nur so bleiben sie
gueltig, wenn sich Kamera, Zoom oder Aufloesung aendern -- und genau das tut die
Overlay-Position zwischen den Aufnahme-Sessions nachweislich.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)

Point = tuple[float, float]


class GeometryError(ValueError):
    """Ungueltige Geometrie (degeneriertes Viereck, nicht invertierbare Matrix)."""


@dataclass(frozen=True)
class Quad:
    """Viereck aus vier Frame-Punkten.

    Reihenfolge ist verbindlich (Auftrag Paragraph 4):

        1 o-----------o 2      1 = oben links
          |           |        2 = oben rechts
          |  TAFEL    |        3 = unten rechts
        4 o-----------o 3      4 = unten links

    cv2.getPerspectiveTransform sortiert die Punkte NICHT selbst. Vertauschte
    Punkte liefern ein gespiegeltes Bild, das oft noch plausibel aussieht --
    deshalb wird die Reihenfolge hier geprueft statt vorausgesetzt.
    """

    top_left: Point
    top_right: Point
    bottom_right: Point
    bottom_left: Point

    @classmethod
    def from_points(cls, points: list[Point] | tuple[Point, ...]) -> Quad:
        if len(points) != 4:
            raise GeometryError(f"Ein Viereck braucht genau 4 Punkte, erhalten: {len(points)}")
        return cls(tuple(points[0]), tuple(points[1]), tuple(points[2]), tuple(points[3]))  # type: ignore[arg-type]

    def as_array(self) -> np.ndarray:
        return np.array(
            [self.top_left, self.top_right, self.bottom_right, self.bottom_left],
            dtype=np.float32,
        )

    def as_list(self) -> list[list[float]]:
        return [list(p) for p in
                (self.top_left, self.top_right, self.bottom_right, self.bottom_left)]

    @property
    def area(self) -> float:
        """Flaeche nach der Gauss'schen Trapezformel (immer positiv)."""
        pts = self.as_array()
        x, y = pts[:, 0], pts[:, 1]
        return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

    def is_convex(self) -> bool:
        """Prueft, ob alle Kreuzprodukte aufeinanderfolgender Kanten dasselbe
        Vorzeichen haben. Ein nicht-konvexes Viereck ergibt eine unbrauchbare
        Homographie.

        Das 2D-Kreuzprodukt wird von Hand gerechnet: np.cross ist fuer
        2D-Vektoren seit NumPy 2.0 veraltet.
        """
        pts = self.as_array()
        signs = []
        for i in range(4):
            a, b, c = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
            u, v = b - a, c - b
            signs.append(np.sign(u[0] * v[1] - u[1] * v[0]))
        signs = [s for s in signs if s != 0]
        return len(signs) > 0 and (all(s > 0 for s in signs) or all(s < 0 for s in signs))

    def validate(self, min_area: float = 100.0) -> None:
        """Wirft GeometryError, wenn das Viereck unbrauchbar ist.

        Lieber hier ein klarer Fehler als spaeter ein verdrehtes Tafelbild,
        dessen Ursache schwer zu finden ist.

        Reihenfolge der Pruefungen: Konvexitaet VOR Flaeche. Ein sanduhrfoermiges
        Viereck (Punkte 3 und 4 vertauscht) hat nach der Gauss'schen Trapezformel
        die Flaeche null, weil sich die beiden Dreiecke aufheben. Wuerde zuerst
        die Flaeche geprueft, meldete die Anwendung "zu klein" -- und der Nutzer
        suchte den Fehler an der falschen Stelle, obwohl er nur zwei Punkte
        vertauscht hat.
        """
        pts = self.as_array()
        if len({(round(p[0], 3), round(p[1], 3)) for p in pts}) < 4:
            raise GeometryError("Viereck enthaelt doppelte Punkte")
        if not self.is_convex():
            raise GeometryError(
                "Viereck ist nicht konvex -- vermutlich wurden die Eckpunkte in "
                "falscher Reihenfolge gesetzt (erwartet: oben links, oben rechts, "
                "unten rechts, unten links)"
            )
        if self.area < min_area:
            raise GeometryError(
                f"Viereck ist zu klein oder entartet (Flaeche {self.area:.1f} < {min_area})"
            )


class PerspectiveTransform:
    """Homographie zwischen Frame- und Tafelkoordinaten."""

    def __init__(self, quad: Quad, width: int, height: int, validate: bool = True) -> None:
        if width < 1 or height < 1:
            raise GeometryError(f"Zielgroesse muss positiv sein: {width}x{height}")
        if validate:
            quad.validate()

        self._quad = quad
        self._width = width
        self._height = height

        dst = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float32)
        self._matrix = cv2.getPerspectiveTransform(quad.as_array(), dst)

        try:
            self._inverse = np.linalg.inv(self._matrix)
        except np.linalg.LinAlgError as exc:
            raise GeometryError(f"Homographie ist nicht invertierbar: {exc}") from exc

    @property
    def quad(self) -> Quad:
        return self._quad

    @property
    def size(self) -> tuple[int, int]:
        return self._width, self._height

    @property
    def matrix(self) -> np.ndarray:
        return self._matrix

    def warp(self, frame: np.ndarray) -> np.ndarray:
        """Entzerrt die Tafel in ein normiertes Rechteck.

        Nur fuer GUI-Anzeige und ROI-Bearbeitung. Im Hot Path der Analyse
        stattdessen `norm_to_frame` verwenden -- das Warpen ganzer Tafeln kostet
        pro Frame und Bahn etwa eine Millisekunde und ist dort unnoetig.
        """
        return cv2.warpPerspective(frame, self._matrix, (self._width, self._height))

    def frame_to_warped(self, points: np.ndarray) -> np.ndarray:
        """Frame-Pixel -> Pixel im entzerrten Tafelbild."""
        return self._apply(self._matrix, points)

    def warped_to_frame(self, points: np.ndarray) -> np.ndarray:
        """Pixel im entzerrten Tafelbild -> Frame-Pixel."""
        return self._apply(self._inverse, points)

    def norm_to_frame(self, points: np.ndarray) -> np.ndarray:
        """Normierte Tafelkoordinaten (0..1) -> Frame-Pixel.

        Der schnelle Weg fuer die Analyse: nur die ROI-Eckpunkte werden
        transformiert, nicht das gesamte Bild.
        """
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
        scaled = pts * np.array([self._width, self._height], dtype=np.float32)
        return self._apply(self._inverse, scaled)

    def frame_to_norm(self, points: np.ndarray) -> np.ndarray:
        """Frame-Pixel -> normierte Tafelkoordinaten (0..1)."""
        warped = self._apply(self._matrix, points)
        return warped / np.array([self._width, self._height], dtype=np.float32)

    @staticmethod
    def _apply(matrix: np.ndarray, points: np.ndarray) -> np.ndarray:
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, matrix).reshape(-1, 2)


def norm_rect_to_frame_bbox(
    transform: PerspectiveTransform,
    rect: tuple[float, float, float, float],
    frame_shape: tuple[int, ...] | None = None,
) -> tuple[int, int, int, int]:
    """Normiertes ROI-Rechteck (x, y, w, h) -> achsparalleles Frame-Rechteck.

    Fuer kleine ROIs (die Gruenlampe misst etwa 6x8 px) ist die perspektivische
    Entzerrung bedeutungslos -- das Bounding-Rechteck der zurueckgerechneten Ecken
    genuegt und ist um Groessenordnungen billiger.

    Returns:
        (x, y, w, h) in Frame-Pixeln, bei Bedarf auf das Bild begrenzt.
        Liegt die ROI vollstaendig ausserhalb, ist w oder h gleich 0 -- und die
        Position liegt dann garantiert trotzdem innerhalb des Bildes.
    """
    x, y, w, h = rect
    corners = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float32)
    frame_pts = transform.norm_to_frame(corners)

    x0 = int(np.floor(frame_pts[:, 0].min()))
    y0 = int(np.floor(frame_pts[:, 1].min()))
    x1 = int(np.ceil(frame_pts[:, 0].max()))
    y1 = int(np.ceil(frame_pts[:, 1].max()))

    if frame_shape is not None:
        height, width = frame_shape[0], frame_shape[1]
        # BEIDE Grenzen beidseitig klemmen. Nur `max(0, x0)` genuegt nicht:
        # Liegt die ROI komplett rechts des Bildes, bliebe x0 > width stehen und
        # der Aufrufer erhielte eine Position ausserhalb des Bildes.
        # Siehe BUG-001.
        x0 = min(max(0, x0), width)
        x1 = min(max(0, x1), width)
        y0 = min(max(0, y0), height)
        y1 = min(max(0, y1), height)

    return x0, y0, max(0, x1 - x0), max(0, y1 - y0)
