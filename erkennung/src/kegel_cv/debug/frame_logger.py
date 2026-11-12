"""Speichern der Debug-Frames je Ereignis (Auftrag Paragraph 14).

Ziel ist die Frage aus Paragraph 27:

    "Welche Frames wurden fuer Bahn 2 bei Wurf 17 verwendet, und warum kam
     dieses Ergebnis zustande?"

Sie muss beantwortbar sein, ohne das Video erneut zu laden. Deshalb liegen
Bilder und Ergebnis im selben Verzeichnis -- nicht in getrennten Baeumen.

    debug/<video>/lane_2/event_017/
        t_00184.230_frame_04580_GREEN_OFF.png
        t_00184.350_frame_04583_SAMPLE.png
        t_00184.790_frame_04594_GREEN_ON.png
        event.json
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ..config.schema import DebugConfig

log = logging.getLogger(__name__)

_UNSAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def safe_name(text: str) -> str:
    """Macht einen Dateinamen aus beliebigem Text.

    Videodateien heissen hier etwa "2026-08-22 09-15-50.mp4" -- Leerzeichen und
    Doppelpunkte sind in Pfaden unpraktisch bis unzulaessig.
    """
    return _UNSAFE.sub("_", text).strip("_") or "unbenannt"


@dataclass
class SavedEvent:
    """Wohin ein Ereignis geschrieben wurde."""

    directory: Path
    images: list[Path]
    metadata: Path | None


class FrameLogger:
    """Schreibt Debug-Frames und Ereignis-Metadaten.

    Der Logger entscheidet nicht, was wichtig ist -- er speichert, was ihm
    gegeben wird. Die Auswahl trifft der FrameSampler.
    """

    def __init__(self, cfg: DebugConfig, project_root: Path,
                 video_id: str = "unbenannt") -> None:
        self.cfg = cfg
        # JE LAUF ein eigener Ordner.
        #
        # Ohne ihn schreiben mehrere Laeufe in dieselben `event_XXX`-Ordner:
        # Die Bilder mischen sich, und `event.json` wird ueberschrieben.
        # Beim Untersuchen eines Fehlers hat mich das fast in die Irre
        # gefuehrt -- in einem Ordner lagen Bilder aus zwei verschiedenen
        # Videos, und die Zeitreihe daraus war frei erfunden.
        #
        # Auffindbar ist der Lauf ueber Datum und Uhrzeit; die Ordner sortieren
        # sich dadurch von selbst chronologisch.
        self.run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.root = (project_root / cfg.directory / safe_name(video_id)
                     / f"lauf_{self.run_id}")
        self._saved_per_lane: dict[int, int] = {}
        log.info("Debug-Ausgabe dieses Laufs: %s", self.root)

    def event_directory(self, lane_id: int, event_id: int) -> Path:
        return self.root / f"lane_{lane_id}" / f"event_{event_id:03d}"

    def _limit_reached(self, lane_id: int) -> bool:
        if self.cfg.max_events_per_lane <= 0:
            return False
        return self._saved_per_lane.get(lane_id, 0) >= self.cfg.max_events_per_lane

    def save_event(self, event, roi_boxes: dict[str, tuple[int, int, int, int]] | None = None,
                   metadata: dict | None = None, failed: bool = False,
                   lane_box: tuple[int, int, int, int] | None = None) -> SavedEvent | None:
        """Speichert alle Frames eines Sampling-Ereignisses.

        Args:
            event: `SampleEvent` aus dem FrameSampler.
            roi_boxes: Optionale ROI-Rechtecke; dann werden zusaetzlich die
                einzelnen Ausschnitte gespeichert, die der Detektor gesehen hat.
            metadata: Wird als event.json abgelegt.
            failed: Kennzeichnet einen Fehlerfall. Diese werden auch dann
                gespeichert, wenn `save_frames` aus ist -- Fehlerfaelle sind
                die wertvollsten Testdaten.
            lane_box: Rechteck der Anzeigetafel. Ist es gesetzt, wird nur dieser
                Ausschnitt gespeichert statt des Vollframes -- das ist der
                Unterschied zwischen wenigen Kilobyte und 2,8 MB je Bild.

        Returns:
            None, wenn nichts gespeichert wurde.
        """
        if not self.cfg.save_frames and not (failed and self.cfg.save_failed_frames):
            return None

        if self._limit_reached(event.lane_id) and not failed:
            log.debug("Bahn %d: Speichergrenze von %d Ereignissen erreicht",
                      event.lane_id, self.cfg.max_events_per_lane)
            return None

        directory = self.event_directory(event.lane_id, event.event_id)
        directory.mkdir(parents=True, exist_ok=True)

        images: list[Path] = []
        for sample in event.sorted_frames():
            # Zeit voran im Namen -> alphabetische Sortierung ist chronologisch
            stem = (f"t_{sample.timestamp:09.3f}_frame_{sample.index:06d}"
                    f"_{sample.role.value}")

            # Standardfall: nur der Tafelausschnitt. Ein 1920x1080-PNG belegt
            # rund 2,8 MB; bei vier Frames je Ereignis und mehreren hundert
            # Wuerfen pro Video sind das mehrere Gigabyte. Der Ausschnitt der
            # Anzeigetafel enthaelt alles Auswertbare und ist winzig dagegen.
            if lane_box is not None:
                x, y, w, h = lane_box
                crop = sample.frame.image[y:y + h, x:x + w]
                if crop.size and _write_image(directory / f"{stem}_tafel.png", crop):
                    images.append(directory / f"{stem}_tafel.png")

            if self.cfg.save_full_frames or lane_box is None:
                # Vollframes als JPEG -- verlustbehaftet, aber ein Vierzehntel
                # der Groesse. Fuer den Gesamtkontext genuegt das.
                path = directory / f"{stem}.jpg"
                if _write_image(path, sample.frame.image,
                                [cv2.IMWRITE_JPEG_QUALITY, self.cfg.jpeg_quality]):
                    images.append(path)

            if self.cfg.save_roi_crops and roi_boxes:
                images.extend(self._save_crops(directory, sample, roi_boxes))

        metadata_path: Path | None = None
        if metadata is not None or True:
            metadata_path = directory / "event.json"
            payload = {
                "lane_id": event.lane_id,
                "event_id": event.event_id,
                "trigger_frame": event.trigger_frame,
                "trigger_timestamp": round(event.trigger_timestamp, 3),
                "close_reason": event.close_reason,
                "frames": [
                    {"index": s.index, "timestamp": round(s.timestamp, 3),
                     "offset": s.offset, "role": s.role.value}
                    for s in event.sorted_frames()
                ],
            }
            if metadata:
                payload.update(metadata)
            metadata_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        self._saved_per_lane[event.lane_id] = self._saved_per_lane.get(event.lane_id, 0) + 1
        log.info("Bahn %d: Ereignis %d gespeichert (%d Bilder) -> %s",
                 event.lane_id, event.event_id, len(images), directory)
        return SavedEvent(directory=directory, images=images, metadata=metadata_path)

    def _save_crops(self, directory: Path, sample,
                    roi_boxes: dict[str, tuple[int, int, int, int]]) -> list[Path]:
        """Speichert die ROI-Ausschnitte -- klein, und genau das, was der
        Detektor tatsaechlich gesehen hat."""
        crop_dir = directory / f"rois_frame_{sample.index:06d}"
        crop_dir.mkdir(parents=True, exist_ok=True)

        saved: list[Path] = []
        for name, (x, y, w, h) in roi_boxes.items():
            if w <= 0 or h <= 0:
                continue
            patch = sample.frame.image[y:y + h, x:x + w]
            if patch.size == 0:
                continue
            path = crop_dir / f"{safe_name(name)}.png"
            if _write_image(path, patch):
                saved.append(path)
        return saved


def _write_image(path: Path, image: np.ndarray,
                 params: list[int] | None = None) -> bool:
    """Schreibt ein Bild und meldet Fehler, ohne die Analyse zu stoppen."""
    try:
        if not cv2.imwrite(str(path), image, params or []):
            log.warning("Bild konnte nicht geschrieben werden: %s", path)
            return False
        return True
    except (cv2.error, OSError) as exc:
        # Debug-Ausgabe darf die Analyse eines langen Videos nie abbrechen
        log.warning("Fehler beim Schreiben von %s: %s", path, exc)
        return False
