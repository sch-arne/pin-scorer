"""Je Wurf ein Belegbild: die Tafel, wie sie gelesen wurde, mit dem Ergebnis.

WOZU -- vom Nutzer gewuenscht (2026-09-03): "koennte man theoretisch von jedem
Wurf immer ein Bild speichern, auf dem der Zeitpunkt des Bildes, die
vollstaendige Tafel sowie die gemessenen Werte angezeigt werden?"

Der Unterschied zu `FrameLogger`: Der speichert die abgetasteten Frames roh und
dient der Fehlersuche. Dieses Blatt ist der BELEG -- ein Bild je Wurf, auf dem
Ergebnis und Herkunft nebeneinander stehen. Wer eine Wurfzeile anzweifelt,
schaut hier nach und braucht weder Video noch Werkzeug.

WELCHER FRAME: der letzte des Wurffensters. Dort steht das Ergebnis vollstaendig
auf der Tafel -- frueher fehlen Lampen, die noch fallen, spaeter kann die
Anlage bereits geloescht haben.

SPEICHERBEDARF, gemessen an einem Spieltag mit 1695 Wuerfen:

    PNG, voller Faktor 3            1,6 MB je Bild   2,7 GB
    JPEG q85, Faktor 3              295 KB           0,51 GB
    JPEG q85, Faktor 2 (Standard)    93 KB           0,16 GB

Deshalb JPEG und Faktor 2 als Vorgabe. Wer den Beleg gross braucht, stellt
`debug.throw_sheet_scale` hoch -- und weiss dann, was es kostet.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

from ..models.throw import ThrowResult, ThrowStatus
from .board_render import mit_kopf_und_werten, zeichne_tafel

log = logging.getLogger(__name__)

# BGR. Gruen = beide Quellen einig, Gelb = nur eine Quelle, Rot = Widerspruch.
GRUEN, GELB, ROT, WEISS = (120, 255, 120), (0, 220, 255), (80, 80, 255), (230, 230, 230)


class ThrowSheet:
    """Schreibt je Wurf ein Belegbild in den Laufordner."""

    def __init__(self, ordner: Path, aktiv: bool = True, faktor: int = 2,
                 jpeg_qualitaet: int = 85, nur_auffaellige: bool = False) -> None:
        self.aktiv = aktiv
        self.ordner = ordner
        self.faktor = max(1, faktor)
        self.jpeg_qualitaet = jpeg_qualitaet
        self.nur_auffaellige = nur_auffaellige
        self._geschrieben = 0

    def _lohnt_sich(self, throw: ThrowResult) -> bool:
        if not self.nur_auffaellige:
            return True
        # Auffaellig ist, was die beiden Quellen uneins zeigt oder was kein
        # sauberes Ergebnis wurde. Genau diese Faelle sieht man sich spaeter an.
        if throw.status is not ThrowStatus.VALID:
            return True
        return (throw.displayed_pin_count is not None
                and throw.displayed_pin_count != throw.pins_count)

    def add(self, throw: ThrowResult, warped: np.ndarray, rois,
            frame_index: int, timestamp: float) -> Path | None:
        """Legt den Beleg ab und liefert den Pfad -- oder None, wenn abgeschaltet.

        `warped` ist die bereits entzerrte Tafel dieser Bahn, `rois` sind ihre
        kalibrierten Bereiche. Beides kommt aus der Pipeline, damit hier nichts
        erneut gerechnet wird.
        """
        if not self.aktiv or warped is None or warped.size == 0:
            return None
        if not self._lohnt_sich(throw):
            return None

        try:
            bild = self._male(throw, warped, rois, frame_index, timestamp)
            ziel = self._pfad(throw)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ok, puffer = cv2.imencode(
                ".jpg", bild, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_qualitaet])
            if not ok:
                log.warning("Bahn %d Wurf %d: Beleg liess sich nicht kodieren",
                            throw.lane, throw.throw_number)
                return None
            ziel.write_bytes(puffer.tobytes())
        except OSError as exc:
            # Ein fehlgeschlagener Beleg darf die Analyse nicht anhalten --
            # aber er darf auch nicht stillschweigend verschwinden.
            log.warning("Bahn %d Wurf %d: Beleg nicht gespeichert: %s",
                        throw.lane, throw.throw_number, exc)
            return None

        self._geschrieben += 1
        return ziel

    def _pfad(self, throw: ThrowResult) -> Path:
        """Sprechender Pfad -- sortiert sich von selbst und ist ohne Index lesbar."""
        return (self.ordner / f"bahn{throw.lane}" / "wurfbelege"
                / f"spiel{throw.game_number:02d}_wurf{throw.throw_number:03d}.jpg")

    def _male(self, throw: ThrowResult, warped: np.ndarray, rois,
              frame_index: int, timestamp: float) -> np.ndarray:
        tafel = zeichne_tafel(warped, rois, self.faktor)
        minuten, sekunden = divmod(timestamp, 60)
        kopf = (f"Bahn {throw.lane}  Spiel {throw.game_number}  "
                f"Wurf {throw.throw_number}   "
                f"t = {int(minuten):02d}:{sekunden:05.2f}   Frame {frame_index}")
        return mit_kopf_und_werten(tafel, kopf, self._werte(throw))

    def _werte(self, throw: ThrowResult) -> list[tuple[str, tuple[int, int, int]]]:
        """Die Messwerte als Textzeilen, eingefaerbt nach Verlaesslichkeit."""
        ziffer = throw.displayed_pin_count
        if ziffer is None:
            ton, sagt = GELB, "Tafel unlesbar"
        elif ziffer == throw.pins_count:
            ton, sagt = GRUEN, f"Tafel {ziffer} -- einig"
        else:
            ton, sagt = ROT, f"Tafel {ziffer} -- WIDERSPRUCH"

        gefallen = " ".join(str(p) for p in throw.pins) or "keine"
        zeilen = [
            (f"{throw.pins_count} Kegel  [{gefallen}]     {sagt}", ton),
            (f"Status {throw.status.value}   Confidence {throw.confidence:.2f}"
             f"   laufende Summe {throw.running_total}",
             WEISS if throw.status is ThrowStatus.VALID else GELB),
        ]
        # Die Pruefungen sind der eigentliche Grund fuer den Status -- ohne sie
        # zeigt der Beleg das Ergebnis, aber nicht das Warum.
        for pruefung in throw.evidence.checks:
            zeilen.append((
                f"  {pruefung.name}: erwartet {pruefung.expected}, "
                f"gelesen {pruefung.actual}",
                GRUEN if pruefung.passed else ROT))
        return zeilen

    def close(self) -> None:
        if self.aktiv and self._geschrieben:
            log.info("Wurfbelege geschrieben: %d Bilder in %s",
                     self._geschrieben, self.ordner)
