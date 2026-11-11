"""Laedt Dateien in Supabase Storage -- fuer die Wurfbelege.

WARUM STORAGE UND NICHT `bytea` IN DER TABELLE: Postgres kann Bilder als
Binaerspalte halten, aber dafuer ist es das falsche Werkzeug. Ein Spieltag
bringt rund 1700 Belege; als Spalte waechst die Datenbank um Hunderte
Megabyte, jedes Backup zieht sie mit, und eine Abfrage, die die Spalte
versehentlich mitliest, uebertraegt sie vollstaendig. Storage liegt daneben,
liefert ueber CDN aus und laesst sich einzeln aufraeumen.

In der Wurftabelle steht deshalb nur der PFAD -- eine Textspalte. Wer das Bild
sehen will, holt es ueber eine signierte URL.

WARUM OHNE ZUSATZBIBLIOTHEK: wie beim `SupabaseSink` -- ein Upload ist ein
HTTP-POST mit zwei Kopfzeilen. `urllib` aus der Standardbibliothek genuegt.

**Der Schluessel steht NICHT in der Konfiguration**, sondern in einer
Umgebungsvariablen. Konfigurationsdateien landen in der Versionsverwaltung.
"""

from __future__ import annotations

import logging
import mimetypes
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)


class StorageError(RuntimeError):
    """Der Upload ist fehlgeschlagen -- vom Aufrufer zu behandeln."""


class SupabaseStorage:
    """Legt Dateien in einem Storage-Bucket ab.

    Sendet SYNCHRON und wirft bei Fehlern. Absichtlich nicht dafuer gedacht, in
    der laufenden Analyse zu haengen: Die Belege entstehen zuerst auf der
    Platte, hochgeladen wird danach (`tools/upload_throw_sheets.py`). Bricht
    die Uebertragung ab, sind die Bilder trotzdem da.
    """

    def __init__(self, url: str, bucket: str, api_key: str,
                 timeout_s: float = 15.0) -> None:
        if not url or not bucket:
            raise ValueError("Storage braucht URL und Bucket-Namen")
        if not api_key:
            raise ValueError(
                "Kein API-Schluessel. Er gehoert in eine Umgebungsvariable, "
                "nicht in die Konfigurationsdatei."
            )
        self.basis = f"{url.rstrip('/')}/storage/v1/object"
        self.bucket = bucket
        self.api_key = api_key
        self.timeout_s = timeout_s

    def upload(self, datei: Path, ziel_pfad: str,
               ueberschreiben: bool = False) -> str:
        """Laedt eine Datei hoch und liefert ihren Pfad im Bucket.

        `ziel_pfad` ist der Pfad INNERHALB des Buckets, etwa
        `2026-08-22/bahn4/spiel03_wurf017.jpg`.
        """
        if not datei.is_file():
            raise StorageError(f"Datei fehlt: {datei}")

        rohdaten = datei.read_bytes()
        typ = mimetypes.guess_type(datei.name)[0] or "application/octet-stream"
        ziel = f"{self.basis}/{self.bucket}/{ziel_pfad.lstrip('/')}"

        request = urllib.request.Request(
            ziel, data=rohdaten, method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "apikey": self.api_key,
                "Content-Type": typ,
                # Ohne das antwortet Storage auf eine bereits vorhandene Datei
                # mit 409 statt sie zu ersetzen.
                "x-upsert": "true" if ueberschreiben else "false",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as antwort:
                if antwort.status not in (200, 201):
                    raise StorageError(
                        f"Storage antwortete mit {antwort.status} fuer {ziel_pfad}")
        except urllib.error.HTTPError as exc:
            # Der Antworttext nennt den Grund -- ohne ihn raet man.
            text = exc.read().decode("utf-8", "replace")[:300]
            raise StorageError(
                f"Upload von {ziel_pfad} fehlgeschlagen ({exc.code}): {text}"
            ) from exc
        except urllib.error.URLError as exc:
            raise StorageError(
                f"Storage nicht erreichbar: {exc.reason}") from exc

        return ziel_pfad

    def oeffentliche_url(self, ziel_pfad: str) -> str:
        """Die oeffentliche URL -- traegt nur bei einem oeffentlichen Bucket.

        Fuer einen privaten Bucket braucht es eine signierte URL, die der
        Client selbst anfordert. Diese Methode ist deshalb bewusst nur ein
        Bequemlichkeitshelfer und keine Zusicherung.
        """
        return f"{self.basis}/public/{self.bucket}/{ziel_pfad.lstrip('/')}"
