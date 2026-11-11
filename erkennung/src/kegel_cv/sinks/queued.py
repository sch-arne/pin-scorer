"""Entkoppelt den Versand von der Analyse.

Die Analyse hat ein Zeitbudget von 40 ms je Frame. Ein HTTP-Aufruf dauert
zwischen 30 ms und -- bei gestoertem Netz -- mehreren Sekunden. Beides im selben
Thread waere ein Fehler: Ein hakendes Netz wuerde die Auswertung zum Stehen
bringen, und Wuerfe gingen verloren, weil Frames nicht mehr rechtzeitig gelesen
werden.

Deshalb: Die Analyse legt den Wurf in eine Warteschlange und ist fertig. Ein
Hintergrund-Thread nimmt ihn heraus und versendet ihn.

**Nichts geht verloren.** Was nach mehreren Versuchen nicht rausgeht, landet in
einer Zwischendatei und wird beim naechsten Start erneut versucht. Die Kegel
sind gefallen -- das Ergebnis darf nicht daran scheitern, dass gerade ein Kabel
gezogen wurde.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Any

from ..models.throw import ThrowResult
from .base import ResultSink
from .payload import throw_to_row

log = logging.getLogger(__name__)

_ENDE = object()   # Signal an den Thread, sich zu beenden


class QueuedSink(ResultSink):
    """Versendet ueber einen Hintergrund-Thread, mit Wiederholung und Puffer."""

    def __init__(self, inner: ResultSink, spool_file: Path | None = None,
                 max_retries: int = 3, retry_delay_s: float = 2.0,
                 queue_size: int = 500, video_id: str = "",
                 mit_bild: bool = True, mit_vorher: bool = False,
                 game_name: str = "",
                 game_name_column: str = "game_name") -> None:
        self.inner = inner
        self.spool_file = Path(spool_file) if spool_file else None
        self.max_retries = max_retries
        self.retry_delay_s = retry_delay_s
        self.video_id = video_id
        self.game_name = game_name
        self.game_name_column = game_name_column
        # Tafelbild mitschicken? Aus der Konfiguration durchgereicht,
        # damit sich der Versand ohne Codeaenderung abspecken laesst.
        self.mit_bild = mit_bild
        self.mit_vorher = mit_vorher

        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._thread = threading.Thread(target=self._arbeiten, daemon=True,
                                        name="ResultSink")
        self._gesendet = 0
        self._gepuffert = 0
        self._thread.start()

    # ------------------------------------------------------------- Schnittstelle

    def send(self, throw: ThrowResult) -> None:
        """Legt den Wurf in die Warteschlange. Kehrt sofort zurueck."""
        try:
            self._queue.put_nowait(throw_to_row(
                throw, video_id=self.video_id, mit_bild=self.mit_bild,
                game_name=self.game_name,
                game_name_column=self.game_name_column,
                mit_vorher=self.mit_vorher))
        except queue.Full:
            # Lieber in die Datei als verlieren. Dass die Schlange volllaeuft,
            # bedeutet ohnehin, dass das Netz laenger weg ist.
            log.warning("Versand-Warteschlange voll -- Wurf der Bahn %d "
                        "(%d Kegel) wird zwischengespeichert",
                        throw.lane, throw.pins_count)
            self._puffern(throw_to_row(
                throw, video_id=self.video_id, mit_bild=self.mit_bild,
                game_name=self.game_name,
                game_name_column=self.game_name_column,
                mit_vorher=self.mit_vorher))

    def flush(self) -> None:
        """Wartet, bis die Warteschlange leer ist."""
        self._queue.join()

    def close(self) -> None:
        self._queue.put(_ENDE)
        self._thread.join(timeout=10.0)
        self.inner.close()
        log.info("Versand beendet: %d gesendet, %d zwischengespeichert",
                 self._gesendet, self._gepuffert)

    @property
    def statistik(self) -> dict[str, int]:
        return {"gesendet": self._gesendet, "gepuffert": self._gepuffert,
                "wartend": self._queue.qsize()}

    # ------------------------------------------------------------- intern

    def _arbeiten(self) -> None:
        while True:
            eintrag = self._queue.get()
            if eintrag is _ENDE:
                self._queue.task_done()
                return
            try:
                self._senden_mit_wiederholung(eintrag)
            except Exception as exc:  # noqa: BLE001
                # Der Thread darf unter KEINEN Umstaenden sterben -- sonst
                # sammeln sich alle folgenden Wuerfe stumm in der Schlange.
                log.error("Versand fehlgeschlagen: %s", exc)
                self._puffern(eintrag)
            finally:
                self._queue.task_done()

    def _senden_mit_wiederholung(self, zeile: dict[str, Any]) -> None:
        letzter_fehler: Exception | None = None
        for versuch in range(1, self.max_retries + 1):
            try:
                self.inner.send_rows([zeile])   # type: ignore[attr-defined]
                self._gesendet += 1
                return
            except Exception as exc:  # noqa: BLE001
                letzter_fehler = exc
                if versuch < self.max_retries:
                    log.warning("Versand-Versuch %d/%d fehlgeschlagen: %s",
                                versuch, self.max_retries, exc)
                    time.sleep(self.retry_delay_s * versuch)   # wachsender Abstand
        raise RuntimeError(f"nach {self.max_retries} Versuchen: {letzter_fehler}")

    def _puffern(self, zeile: dict[str, Any]) -> None:
        """Schreibt eine Zeile in die Zwischendatei (JSON Lines)."""
        if self.spool_file is None:
            # Die Zeile enthaelt keine Wurfnummer mehr (siehe payload.py) --
            # zur Wiedererkennung dienen Bahn und Zeitpunkt.
            log.error("Kein Zwischenspeicher eingerichtet -- Wurf geht verloren: "
                      "Bahn %s, %s Kegel, %s",
                      zeile.get("lane"), zeile.get("pins_count"),
                      zeile.get("recorded_at"))
            return
        try:
            self.spool_file.parent.mkdir(parents=True, exist_ok=True)
            with self.spool_file.open("a", encoding="utf-8") as datei:
                datei.write(json.dumps(zeile, ensure_ascii=False) + "\n")
            self._gepuffert += 1
        except OSError as exc:
            log.error("Zwischenspeichern fehlgeschlagen: %s", exc)

    # ------------------------------------------------------------- Nachliefern

    def resend_spooled(self, batch: int = 50) -> int:
        """Schickt zwischengespeicherte Wuerfe nach. Liefert die Anzahl.

        Wird beim Start aufgerufen. Erst wenn ALLE Zeilen durch sind, wird die
        Datei geleert -- bricht es in der Mitte ab, bleibt der Rest erhalten und
        wird beim naechsten Mal erneut versucht.
        """
        if self.spool_file is None or not self.spool_file.exists():
            return 0

        zeilen = [json.loads(z) for z in
                  self.spool_file.read_text(encoding="utf-8").splitlines() if z.strip()]
        if not zeilen:
            return 0

        log.info("%d zwischengespeicherte Wuerfe werden nachgeliefert", len(zeilen))
        offen = list(zeilen)
        try:
            while offen:
                teil, offen = offen[:batch], offen[batch:]
                self.inner.send_rows(teil)   # type: ignore[attr-defined]
                self._gesendet += len(teil)
        except Exception as exc:  # noqa: BLE001
            log.warning("Nachliefern abgebrochen, %d Wuerfe bleiben gepuffert: %s",
                        len(offen), exc)
            self.spool_file.write_text(
                "\n".join(json.dumps(z, ensure_ascii=False) for z in offen) + "\n",
                encoding="utf-8")
            return len(zeilen) - len(offen)

        self.spool_file.unlink()
        return len(zeilen)
