"""Entscheidet, welche Videoquelle zu einer Angabe gehoert.

Eine Stelle, an der zwischen Datei und Stream unterschieden wird -- damit
Oberflaeche und Analyse beide nur noch "oeffne das hier" sagen muessen und die
Frage nicht an zwei Orten verschieden beantwortet wird.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

from ..config.schema import AppConfig
from .file_source import FileVideoSource
from .source import VideoSource
from ..models.quellen import ohne_zugangsdaten
from .stream_source import StreamVideoSource
from .youtube import ist_youtube, loese_auf, video_kennung

log = logging.getLogger(__name__)

# Schemata, die auf einen Stream hindeuten. `file://` fehlt bewusst: Das ist
# eine Datei mit URL-Schreibweise und gehoert zur Dateiquelle.
STREAM_SCHEMES = {"http", "https", "rtsp", "rtmp", "udp", "srt"}


def is_stream(quelle: str | Path) -> bool:
    """Ist die Angabe ein Stream (statt einer Datei)?"""
    text = str(quelle).strip()
    if len(text) > 1 and text[1] == ":":
        # Windows-Laufwerksbuchstabe -- urlparse liest daraus sonst ein Schema
        return False
    return urlparse(text).scheme.lower() in STREAM_SCHEMES


def open_source(quelle: str | Path, cfg: AppConfig | None = None) -> VideoSource:
    """Baut die passende Videoquelle. Geoeffnet wird sie NICHT.

    Der Aufrufer ruft `open()` selbst -- so kann er Fehler dort behandeln, wo er
    weiss, was er dem Nutzer sagen will.
    """
    if is_stream(quelle):
        log.info("Quelle als Stream erkannt: %s", quelle)
        # Eine YouTube-Adresse ist eine WEBSEITE, kein Video. FFmpeg oeffnet
        # sie nicht (gemessen 2026-09-10: geoeffnet=False, kein Frame). Die
        # Uebersetzung wird nicht hier ausgefuehrt, sondern als Auftrag
        # weitergereicht: Die genannte Medienadresse verfaellt, und die
        # Stromquelle erfragt sie deshalb bei jedem Verbindungsaufbau neu.
        aufloesung = None
        if ist_youtube(quelle):
            hoehe = cfg.video.youtube_max_height if cfg else 1080
            aufloesung = lambda: loese_auf(str(quelle), hoehe)  # noqa: E731

        if cfg is None:
            return StreamVideoSource(str(quelle), url_aufloesung=aufloesung)
        return StreamVideoSource(
            str(quelle),
            url_aufloesung=aufloesung,
            reconnect_attempts=cfg.video.stream_reconnect_attempts,
            reconnect_delay_s=cfg.video.stream_reconnect_delay_s,
            read_failures_before_reconnect=cfg.video.stream_read_failures,
            open_timeout_ms=cfg.video.stream_open_timeout_ms,
            read_timeout_ms=cfg.video.stream_read_timeout_ms,
            rtsp_transport=cfg.video.stream_rtsp_transport,
            restart_check=cfg.video.stream_restart_check,
            restart_probe_frames=cfg.video.stream_restart_probe_frames,
            restart_matches=cfg.video.stream_restart_matches,
            resume_tolerance_frames=cfg.video.stream_resume_tolerance_frames,
            end_tolerance_frames=cfg.video.stream_end_tolerance_frames,
        )

    fehler = cfg.video.max_consecutive_read_failures if cfg else 10
    return FileVideoSource(Path(quelle), max_read_failures=fehler)


def source_label(quelle: str | Path) -> str:
    """Kurzer, dateisystemtauglicher Name der Quelle.

    Wird fuer Debug-Ordner und als `video_id` beim Ergebnisversand gebraucht.
    Bei einer Datei ist das der Dateiname; bei einem Stream Rechnername und
    letzter Pfadteil, damit sich zwei Uebertragungen desselben Anbieters
    unterscheiden lassen.
    """
    if not is_stream(quelle):
        return Path(quelle).name

    # Bei YouTube taugt der Adressaufbau nicht als Name: JEDES Video liegt
    # unter `www.youtube.com/watch`, zwei Laeufe landeten also im selben
    # Debug-Ordner und truegen dieselbe `video_id`. Die Kennung unterscheidet.
    kennung = video_kennung(quelle)
    if kennung:
        return f"youtube_{kennung}"

    # OHNE ZUGANGSDATEN. `netloc` enthaelt bei einer Kamera Benutzer und
    # Passwort im Klartext -- und dieser Name wird zum Debug-Ordner und zur
    # `video_id` in der Datenbank. Am 2026-09-09 stand das Kamerapasswort
    # dadurch in jedem Ordnernamen unter debug/.
    teile = urlparse(ohne_zugangsdaten(str(quelle)) or str(quelle))
    letzter = Path(teile.path).name or "live"
    name = f"{teile.netloc}_{letzter}"
    # Alles, was in einem Dateinamen Aerger macht, ersetzen
    return "".join(z if (z.isalnum() or z in "._-") else "_" for z in name)[:80]
