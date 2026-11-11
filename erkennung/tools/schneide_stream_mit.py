"""Schneidet einen Livestream in eine Datei mit.

WOZU (Nutzer, 2026-09-17): *"Hältst du es nicht für sinnvoller, jetzt mal die
Aufzeichnung des Livestreams zu nehmen, alle 4 Tafeln zu Kalibrieren, die
Ziffern nachzuschärfen und dann den durchlaufen zu lassen?"*

WARUM NICHT DIREKT AUF DEM STREAM. Zwei Gründe, beide am selben Tag gelernt:

1. Was sich nicht wiederholen lässt, lässt sich nicht beurteilen. Eine
   Kalibrierung gegen einen Stream ist morgen nicht mehr nachmessbar -- der
   Link läuft ab, und die Zahlen von vorher und nachher stehen dann nebeneinander,
   ohne dass jemand sagen kann, woran der Unterschied lag.
2. Die Ziffernlupe kann in einem Stream nicht durch Frames springen. Ob ein
   Rahmen sitzt, entscheidet sich aber an mehreren ANZEIGEN -- auf einer `1`
   sieht fast jeder Rahmen gut aus.

Aufruf:

    .venv/Scripts/python.exe tools/schneide_stream_mit.py \\
        --url "https://.../rendition.m3u8?..." --minuten 45

Abbrechen mit Strg-C ist jederzeit gefahrlos: Die Datei wird geschlossen und
bleibt brauchbar.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True, help="Stream-URL (m3u8)")
    p.add_argument("--minuten", type=float, default=45.0)
    p.add_argument("--ziel", type=Path, default=None,
                   help="Zieldatei; sonst kegelVideos/stream_<Zeit>.mp4")
    a = p.parse_args()

    quelle = cv2.VideoCapture(a.url)
    if not quelle.isOpened():
        print("Stream nicht zu oeffnen -- Link abgelaufen?", file=sys.stderr)
        return 1

    ok, erstes = quelle.read()
    if not ok:
        print("Kein Bild vom Stream", file=sys.stderr)
        return 1
    hoehe, breite = erstes.shape[:2]

    # DIE BILDRATE DES STREAMS IST NICHT IMMER GLAUBWUERDIG. Steht dort Unsinn,
    # wird 25 genommen -- eine falsche Rate in der Datei verschiebt spaeter
    # jede Zeitangabe, und die Wurferkennung rechnet in Frames.
    fps = quelle.get(cv2.CAP_PROP_FPS)
    if not (1.0 < fps < 121.0):
        fps = 25.0

    ziel = a.ziel or Path("kegelVideos") / (
        f"stream_{datetime.now():%Y-%m-%d_%H-%M-%S}.mp4")
    ziel.parent.mkdir(parents=True, exist_ok=True)
    schreiber = cv2.VideoWriter(str(ziel), cv2.VideoWriter_fourcc(*"mp4v"),
                                fps, (breite, hoehe))
    if not schreiber.isOpened():
        print(f"Kann {ziel} nicht schreiben", file=sys.stderr)
        return 1

    print(f"Mitschnitt: {ziel}")
    print(f"            {breite}x{hoehe}, {fps:g} fps, geplant "
          f"{a.minuten:g} Minuten")

    schreiber.write(erstes)
    geschrieben = 1
    ausfaelle = 0
    beginn = time.time()
    ende = beginn + a.minuten * 60
    naechste_meldung = beginn + 30

    try:
        while time.time() < ende:
            ok, bild = quelle.read()
            if not ok:
                # EIN AUSSETZER BEENDET DEN MITSCHNITT NICHT (P8). Ein Stream
                # stolpert; erst wenn er dauerhaft schweigt, ist Schluss.
                ausfaelle += 1
                if ausfaelle > 250:
                    print("Stream liefert dauerhaft nichts mehr -- Schluss")
                    break
                time.sleep(0.2)
                continue
            ausfaelle = 0
            schreiber.write(bild)
            geschrieben += 1
            if time.time() >= naechste_meldung:
                lief = time.time() - beginn
                print(f"  {lief/60:5.1f} min | {geschrieben:7d} Frames | "
                      f"{geschrieben/max(lief,1):.1f} Frames/s | "
                      f"{ziel.stat().st_size/2**20:.0f} MB", flush=True)
                naechste_meldung += 30
    except KeyboardInterrupt:
        print("\nAbgebrochen -- die Datei bleibt brauchbar.")
    finally:
        schreiber.release()
        quelle.release()

    lief = time.time() - beginn
    print(f"\nFertig: {geschrieben} Frames in {lief/60:.1f} min "
          f"({ziel.stat().st_size/2**20:.0f} MB)")
    print(f"Datei:  {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
