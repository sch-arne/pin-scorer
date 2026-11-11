"""YouTube-Adressen in eine Adresse uebersetzen, die FFmpeg oeffnen kann.

WARUM ES DIESES MODUL BRAUCHT

Eine YouTube-Adresse ist keine Videoadresse, sondern eine Webseite. Wer sie
direkt an OpenCV gibt, bekommt eine leere Quelle -- ohne Fehlermeldung, die
das erklaeren wuerde.

GEMESSEN 2026-09-10 mit https://www.youtube.com/watch?v=SO7ShGGQpHM
(Verbandsliga KVN, 3:08 h):

    direkt an OpenCV        geoeffnet=False, kein Frame          2,2 s
    ueber yt-dlp aufgeloest 1920x1080 @30 fps, erstes Frame da   1,4 s

yt-dlp liest die Seite und nennt die tatsaechliche Medienadresse.

DIESE ADRESSE VERFAELLT. Sie traegt eine Gueltigkeitsdauer von wenigen Stunden
und ist an die abrufende Sitzung gebunden. Deshalb wird sie hier nirgends
gespeichert: `open_source` uebergibt diese Funktion selbst an die Stromquelle,
die sie bei JEDEM Verbindungsaufbau neu aufruft. Ein Lauf ueber einen ganzen
Spieltag ueberlebt so den Ablauf der Adresse.

WAS DER NUTZER SIEHT, BLEIBT SEIN LINK. Die aufgeloeste Adresse ist ueber 900
Zeichen lang und in keiner Meldung lesbar; Fehlertexte und `source_id` nennen
weiter die Adresse, die eingegeben wurde.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .source import VideoSourceError

log = logging.getLogger(__name__)

# Alle Schreibweisen, unter denen dasselbe Video erreichbar ist.
HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
         "music.youtube.com", "youtu.be", "www.youtu.be"}

# Pfade, hinter denen eine Video-Kennung im Pfad statt in der Abfrage steht.
PFAD_FORMEN = ("/live/", "/embed/", "/shorts/", "/v/")


def ist_youtube(quelle: str | Path) -> bool:
    """Zeigt diese Adresse auf YouTube?"""
    return urlparse(str(quelle).strip()).netloc.lower() in HOSTS


def video_kennung(quelle: str | Path) -> str | None:
    """Die elfstellige Kennung des Videos -- oder None, wenn keine drinsteht.

    Sie ist das einzig Stabile an einer YouTube-Adresse: Der Rest der URL
    unterscheidet sich je nach Schreibweise, und die aufgeloeste Medienadresse
    wechselt bei jedem Abruf. Debug-Ordner und `video_id` haengen daran.
    """
    teile = urlparse(str(quelle).strip())
    if teile.netloc.lower() not in HOSTS:
        return None
    if teile.netloc.lower().endswith("youtu.be"):
        return Path(teile.path).name or None
    kennung = parse_qs(teile.query).get("v", [None])[0]
    if kennung:
        return kennung
    for form in PFAD_FORMEN:
        if teile.path.startswith(form):
            return teile.path[len(form):].split("/")[0] or None
    return None


def loese_auf(quelle: str | Path, max_hoehe: int = 1080) -> str:
    """Nennt die Medienadresse hinter einer YouTube-Seite.

    Gewaehlt wird eine reine BILDSPUR: Ton braucht die Analyse nicht, und ohne
    ihn entfaellt das Zusammensetzen zweier Stroeme. Faellt keine passende an,
    wird die beste vollstaendige Fassung genommen.

    `max_hoehe` deckelt die Aufloesung. Mehr Pixel heisst mehr Decodierarbeit
    je Frame, und die Tafeln sind schon bei 1080p gross genug: Im Overlay-Video
    misst eine Tafel rund 190 Pixel, und darauf sass die Kalibrierung.
    """
    adresse = str(quelle).strip()
    try:
        import yt_dlp
    except ImportError as exc:
        raise VideoSourceError(
            "Fuer YouTube-Adressen wird yt-dlp gebraucht.\n"
            "Nachinstallieren:  .venv/Scripts/pip.exe install yt-dlp\n"
            "Oder das Video vorher herunterladen und die Datei oeffnen."
        ) from exc

    auswahl = (f"bestvideo[height<={max_hoehe}][protocol^=http]"
               f"/best[height<={max_hoehe}][protocol^=http]"
               f"/best[protocol^=http]")
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                               "skip_download": True,
                               "format": auswahl}) as ydl:
            info = ydl.extract_info(adresse, download=False)
    except Exception as exc:  # noqa: BLE001 -- yt-dlp wirft eigene Klassen
        raise VideoSourceError(
            f"YouTube-Adresse liess sich nicht aufloesen: {adresse}\n"
            f"{exc}\n"
            f"Pruefen: Ist das Video oeffentlich? Besteht eine Verbindung?"
        ) from exc

    medien = info.get("url")
    if not medien:
        raise VideoSourceError(
            f"YouTube nennt keine abspielbare Fassung fuer: {adresse}")

    log.info("YouTube aufgeloest: %r -- %sx%s @%s fps, Format %s%s",
             str(info.get("title", ""))[:60], info.get("width"),
             info.get("height"), info.get("fps"), info.get("format_id"),
             " (Live)" if info.get("is_live") else "")
    return medien
