"""Der Tafelausschnitt eines Wurfs -- klein genug, um ihn mitzuschicken.

WOZU: Ein Ergebnis, das sich selbst erklaert (P1), erklaert sich am besten mit
dem Bild, aus dem es stammt. Wer im Liveticker einen Wurf korrigiert, soll
sehen, worueber er entscheidet, statt der Zahl glauben zu muessen.

WAS DRAUF IST: **Nur die Anzeigetafel** -- genau das Rechteck, das beim
Kalibrieren eingemessen wurde (`LaneProcessor.lane_box`). Kein Hallenbild, keine
Spieler. Das ist keine Sparmassnahme, sondern eine Festlegung des Nutzers
(2026-09-07): Was nicht zur Auswertung gehoert, wird auch nicht uebertragen.

GROESSE: Der Ausschnitt misst rund 152x154 Pixel. GEMESSEN an einem echten
Wurf (Bahn 2, Frame 26984):

    JPEG  40 ->  4,8 KB      JPEG  70 ->  6,7 KB
    JPEG  55 ->  5,5 KB      PNG      -> 46,4 KB

Bei rund 2000 Wuerfen je Spieltag sind das mit Qualitaet 40 etwa 9 MB -- als
Base64 in der Datenbankzeile, ohne eigenen Speicher-Dienst und ohne zweiten
Uebertragungsweg, der bei wackeligem Netz eigene Fehler machen koennte.
"""

from __future__ import annotations

import base64
import logging

import cv2
import numpy as np

log = logging.getLogger(__name__)


def crop_board(image: np.ndarray | None,
               box: tuple[int, int, int, int] | None) -> np.ndarray | None:
    """Schneidet die Tafel aus dem Frame. `None`, wenn nichts Brauchbares bleibt."""
    if image is None or box is None:
        return None
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return None
    # Am Bildrand darf der Ausschnitt nicht ueber die Kante hinauslaufen --
    # numpy schneidet still ab und liefert sonst ein leeres Feld.
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(image.shape[1], x + w), min(image.shape[0], y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    ausschnitt = image[y0:y1, x0:x1]
    return ausschnitt if ausschnitt.size else None


def lamp_brightness(image: np.ndarray | None,
                    lamp_boxes: list[tuple[int, int, int, int]] | None) -> float:
    """Wie hell die neun Kegellampen in diesem Bild zusammen sind.

    NUR eine Rangfolge, KEINE Entscheidung. Es wird nichts als "an" oder "aus"
    eingestuft und kein Schwellwert gebraucht -- verglichen werden Frames
    untereinander, um den auszusuchen, der am meisten zeigt.

    Der Detektor wird dafuer bewusst NICHT aufgerufen: Er fuehrt ein
    mitlaufendes Gedaechtnis (Grundlinie, AN-Niveau) und wuerde durch
    zusaetzliche Aufrufe verfaelscht. Das Wurfergebnis bleibt allein seine
    Sache; hier geht es um die Wahl eines Fotos.
    """
    if image is None or not lamp_boxes:
        return 0.0
    summe = 0.0
    for box in lamp_boxes:
        ausschnitt = crop_board(image, box)
        if ausschnitt is not None and ausschnitt.size:
            summe += float(ausschnitt.mean())
    return summe


def pick_board_frame(frames: list, lamp_boxes: list[tuple[int, int, int, int]] | None,
                     bild_von=lambda f: f):
    """Sucht aus den Frames eines Ereignisses den aussagekraeftigsten aus.

    WARUM ES DAS BRAUCHT -- GEMESSEN am 2026-09-07 an einem Neuner (Bahn 1,
    Ereignis 7, Wurf 20): Von zehn gesampelten Frames waren FUENF dunkel. Die
    Anlage laesst die Kegellampen nach einem hohen Ergebnis blinken, waehrend
    das untere Display durchgehend `020 9 0129` zeigt. Wer stur den
    Ausloeser-Frame nimmt, erwischt mit rund halber Wahrscheinlichkeit ein
    Bild ohne eine einzige leuchtende Lampe -- vom Nutzer gemeldet.

    Genommen wird deshalb der Frame mit den insgesamt hellsten Lampen. Das ist
    ein ECHTES Bild, keine Montage: Es zeigt einen Augenblick, den es so gab.

    Bei Gleichstand -- etwa bei einem Wurf ohne Kegel, wo alle Frames gleich
    dunkel sind -- bleibt es beim ersten, also beim Ausloeser.
    """
    if not frames:
        return None
    if not lamp_boxes:
        return frames[0]
    return max(frames, key=lambda f: lamp_brightness(bild_von(f), lamp_boxes))


def encode_crop(ausschnitt: np.ndarray | None, quality: int = 40) -> str | None:
    """Kodiert einen FERTIGEN Ausschnitt -- ohne noch einmal zu schneiden."""
    if ausschnitt is None or not getattr(ausschnitt, "size", 0):
        return None
    try:
        ok, puffer = cv2.imencode(
            ".jpg", ausschnitt,
            [cv2.IMWRITE_JPEG_QUALITY, int(max(1, min(100, quality)))])
    except cv2.error as fehler:
        log.warning("Tafelbild nicht kodierbar: %s", fehler)
        return None
    return base64.b64encode(puffer.tobytes()).decode("ascii") if ok else None


def schwaerze_fremdes(ausschnitt: np.ndarray,
                      fremd: np.ndarray | None) -> np.ndarray:
    """Schwaerzt im Tafelausschnitt, was nicht dazugehoert -- nur fuers Bild.

    WOFUER -- Befund des Nutzers am 2026-09-13: *"im Liveticker sieht man sehr
    haeufig noch Gesichter -> immer dann, wenn sie Phantomwuerfe erzeugen."*

    Die Personenmaske nimmt die Tafelbereiche vom Schwaerzen aus, weil dort das
    Signal steht -- und genau dieses Rechteck wird als `board_jpeg` verschickt.
    Wer davorsteht, war im ganzen Bild geschwaerzt, nur nicht in dem Ausschnitt,
    den alle sehen.

    `fremd` kommt aus `TafelWache` und liegt bereits in den Koordinaten des
    Ausschnitts. Geschwaerzt wird eine KOPIE: Die Messung hat den
    unveraenderten Ausschnitt laengst gelesen.
    """
    if fremd is None or fremd.size == 0 or not fremd.any():
        return ausschnitt
    if fremd.shape[:2] != ausschnitt.shape[:2]:
        fremd = cv2.resize(fremd, (ausschnitt.shape[1], ausschnitt.shape[0]),
                           interpolation=cv2.INTER_NEAREST)
    aus = ausschnitt.copy()
    aus[fremd > 0] = 0
    return aus


def encode_board(image: np.ndarray | None,
                 box: tuple[int, int, int, int] | None,
                 quality: int = 40,
                 fremd: np.ndarray | None = None) -> str | None:
    """Tafelausschnitt als Base64-JPEG -- ohne `data:`-Praefix.

    Gibt `None` zurueck, wenn kein Bild entsteht. Ein fehlendes Bild ist kein
    Fehler: Der Wurf ist gemessen, ob sein Bild ankommt oder nicht (P8). Diese
    Funktion wirft deshalb nie -- sie meldet und liefert `None`.

    `fremd` ist die Maske aus `TafelWache` (siehe `schwaerze_fremdes`). Ohne
    sie geht der Ausschnitt unveraendert hinaus -- so, wie es bis zum
    2026-09-13 immer war.
    """
    ausschnitt = crop_board(image, box)
    if ausschnitt is None:
        return None
    ausschnitt = schwaerze_fremdes(ausschnitt, fremd)
    try:
        ok, puffer = cv2.imencode(
            ".jpg", ausschnitt,
            [cv2.IMWRITE_JPEG_QUALITY, int(max(1, min(100, quality)))])
    except cv2.error as fehler:
        log.warning("Tafelbild nicht kodierbar: %s", fehler)
        return None
    if not ok:
        log.warning("Tafelbild nicht kodierbar -- imencode meldete Fehlschlag")
        return None
    return base64.b64encode(puffer.tobytes()).decode("ascii")
