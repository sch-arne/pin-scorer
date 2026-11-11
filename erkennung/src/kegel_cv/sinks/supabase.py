"""Versendet Wurfergebnisse an eine Supabase-Tabelle (PostgREST).

Warum ohne zusaetzliche Bibliothek: Ein Einfuegen ist ein HTTP-POST mit zwei
Kopfzeilen. Dafuer `supabase-py` samt Abhaengigkeiten einzuziehen, waere ein
schlechter Tausch -- `urllib` aus der Standardbibliothek genuegt und haelt die
Installation schlank.

**Der Schluessel steht NICHT in der Konfiguration**, sondern in einer
Umgebungsvariablen. Konfigurationsdateien landen in der Versionsverwaltung,
Zugangsdaten duerfen das nie.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any

from ..models.throw import ThrowResult
from .base import ResultSink
from .payload import throw_to_row

log = logging.getLogger(__name__)


class SupabaseError(RuntimeError):
    """Der Versand ist fehlgeschlagen -- vom Aufrufer zu behandeln."""


class SupabaseSink(ResultSink):
    """Schreibt je Wurf eine Zeile per PostgREST.

    Diese Klasse sendet SYNCHRON und wirft bei Fehlern. Sie ist deshalb nicht
    dafuer gedacht, direkt in der Analyse zu haengen -- dafuer gibt es
    `QueuedSink`, der sie in einen Hintergrund-Thread stellt und Ausfaelle
    abfaengt. Die Trennung haelt diese Klasse einfach und pruefbar: Sie tut
    genau eine Sache und sagt ehrlich, wenn sie misslingt.
    """

    def __init__(self, url: str, table: str, api_key: str,
                 timeout_s: float = 5.0, video_id: str = "",
                 game_name: str = "",
                 game_name_column: str = "game_name") -> None:
        if not url or not table:
            raise ValueError("Supabase braucht URL und Tabellenname")
        if not api_key:
            raise ValueError(
                "Kein API-Schluessel. Er gehoert in eine Umgebungsvariable, "
                "nicht in die Konfigurationsdatei."
            )
        self.endpoint = f"{url.rstrip('/')}/rest/v1/{table}"
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.video_id = video_id
        self.game_name = game_name
        self.game_name_column = game_name_column
        # Die Meldung ueber eine fehlende Spalte darf nur EINMAL kommen --
        # sonst steht sie bei 1700 Wuerfen 1700 mal im Log.
        self._spalte_gemeldet = False

    def send(self, throw: ThrowResult) -> None:
        self.send_rows([throw_to_row(
            throw, video_id=self.video_id, game_name=self.game_name,
            game_name_column=self.game_name_column)])

    def send_rows(self, rows: list[dict[str, Any]]) -> None:
        """Schickt mehrere Zeilen in EINEM Aufruf.

        Gebraucht beim Nachliefern zwischengespeicherter Wuerfe: Nach einer
        Netzunterbrechung waeren sonst dutzende Einzelanfragen faellig.
        """
        if not rows:
            return

        koerper = json.dumps(rows).encode("utf-8")
        anfrage = urllib.request.Request(
            self.endpoint, data=koerper, method="POST",
            headers={
                "apikey": self.api_key,
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                # Ohne diesen Kopf antwortet PostgREST mit der eingefuegten
                # Zeile -- Datenverkehr, den niemand braucht.
                "Prefer": "return=minimal",
            },
        )
        try:
            with urllib.request.urlopen(anfrage, timeout=self.timeout_s) as antwort:
                if antwort.status >= 300:
                    raise SupabaseError(f"HTTP {antwort.status}")
        except urllib.error.HTTPError as exc:
            # Den Antwortkoerper mitgeben: PostgREST erklaert darin, WARUM es
            # abgelehnt hat (fehlende Spalte, Rechte, Format). Ohne diesen Text
            # bleibt nur eine nackte Zahl.
            text = exc.read().decode("utf-8", errors="replace")[:300]
            # DIE FEHLENDE SPALTE IM KLARTEXT. Sie ist der wahrscheinlichste
            # Grund, wenn zum ersten Mal mit einem Spielnamen gesendet wird,
            # und aus "HTTP 400: PGRST204" liest das niemand heraus.
            if (self.game_name and self.game_name_column
                    and self.game_name_column in text
                    and not self._spalte_gemeldet):
                self._spalte_gemeldet = True
                log.error(
                    "Die Tabelle kennt die Spalte '%s' nicht -- der Spielname "
                    "kann nicht gespeichert werden und die ganze Zeile wird "
                    "abgelehnt. In Supabase einmal anlegen: "
                    "alter table %s add column %s text; -- "
                    "bis dahin hilft ein Lauf ohne Spielnamen.",
                    self.game_name_column,
                    self.endpoint.rsplit("/", 1)[-1], self.game_name_column)
            raise SupabaseError(f"HTTP {exc.code}: {text}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise SupabaseError(f"nicht erreichbar: {exc}") from exc
