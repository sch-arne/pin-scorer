"""Prueft, ob eine Stream-Adresse taugt -- bevor man damit kalibriert.

Zweck: Eine Stream-URL ist entweder brauchbar oder nicht, und das soll man in
zehn Sekunden wissen statt nach zehn Minuten Kalibrierarbeit. Geprueft wird,
was fuer die Analyse zaehlt: Kommen Frames? Stimmt die Groesse? Laeuft es
schnell genug?

Aufruf:
    .venv/Scripts/python.exe tools/test_stream.py "https://stream.mux.com/XXXX.m3u8"
"""

from __future__ import annotations

import logging
import sys
import time

import cv2
import numpy as np

from kegel_cv.config import load_config
from kegel_cv.video import is_stream, open_source, source_label
from kegel_cv.video.source import VideoSourceError

FRAMES = 60          # rund zwei Sekunden -- genug fuer eine Aussage
VORSCHAU = "debug/stream_probe.png"


def pruefen(url: str) -> int:
    logging.basicConfig(level=logging.INFO, format="  %(message)s")
    cfg = load_config()

    print("=" * 66)
    print("STREAM-TEST")
    print("=" * 66)
    print(f"  Adresse: {url}")

    if not is_stream(url):
        print("\n  Das sieht nicht nach einer Stream-Adresse aus.")
        print("  Erwartet wird etwas wie https://... oder rtsp://...")
        return 1
    if "/chunk/" in url or url.endswith(".ts"):
        print("\n  Das ist ein SEGMENT, nicht die Playlist.")
        print("  Gesucht ist die Datei mit der Endung .m3u8 -- bei Mux liegt sie")
        print("  unter stream.mux.com, nicht unter edgemv.mux.com.")
        return 1

    quelle = open_source(url, cfg)
    try:
        quelle.open()
    except VideoSourceError as exc:
        print(f"\n  NICHT ERREICHBAR: {exc}")
        print("\n  Moegliche Ursachen:")
        print("    - Die Uebertragung laeuft gerade nicht")
        print("    - Die Adresse enthaelt ein Zugangstoken und ist abgelaufen")
        print("      (erkennbar an ?token= oder ?signature= am Ende)")
        print("    - Es ist eine Segment- statt einer Playlist-Adresse")
        return 1

    info = quelle.info
    print(f"\n  [ok] verbunden: {info.width}x{info.height}, {info.fps:.1f} fps")
    print(f"       Bezeichner fuer den Versand: {source_label(url)}")

    if (info.width, info.height) != (1920, 1080):
        print(f"\n  ACHTUNG: {info.width}x{info.height} statt 1920x1080.")
        print("  Die Kalibrierung rechnet in normierten Tafelkoordinaten und")
        print("  vertraegt andere Groessen -- aber kleinere Bilder heissen")
        print("  kleinere Ziffern, und die sind schon bei 1080p grenzwertig.")

    print(f"\n  Lese {FRAMES} Frames ...")
    begonnen = time.perf_counter()
    frames = []
    for _ in range(FRAMES):
        frame = quelle.read()
        if frame is None:
            break
        frames.append(frame)
    dauer = time.perf_counter() - begonnen
    quelle.close()

    if not frames:
        print("  KEINE FRAMES erhalten.")
        return 1

    tempo = len(frames) / dauer if dauer > 0 else 0
    print(f"  [ok] {len(frames)} Frames in {dauer:.1f} s  ({tempo:.1f} fps)")

    if tempo < info.fps * 0.9:
        print(f"\n  ACHTUNG: Der Stream liefert langsamer als seine {info.fps:.0f} fps.")
        print("  Bei einer LIVE-Uebertragung ist das normal -- man kann nicht")
        print("  schneller lesen, als gesendet wird. Bei einer Aufzeichnung")
        print("  deutet es auf eine langsame Verbindung hin.")

    # Ein Standbild ablegen: Daran sieht man sofort, ob das Overlay drin ist.
    letzter = frames[-1]
    cv2.imwrite(VORSCHAU, letzter.image)
    print(f"\n  Standbild abgelegt: {VORSCHAU}")
    print("  Darauf pruefen: Ist das Overlay mit den vier Tafeln zu sehen?")
    print("  Wenn ja, kann man damit kalibrieren.")

    statistik = getattr(quelle, "statistik", None)
    if statistik and statistik.get("reconnects"):
        print(f"\n  Hinweis: {statistik['reconnects']} Neuverbindung(en) noetig,")
        print(f"  geschaetzt {statistik['verlorene_frames_geschaetzt']} Frames verpasst.")
        print("  Bei einer laengeren Uebertragung fehlen dort Wuerfe.")

    print("\n  Die Adresse ist brauchbar. In der Oberflaeche eintragen unter")
    print("  'Video' -> Stream-URL, dann verbinden und kalibrieren.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(pruefen(sys.argv[1]))
