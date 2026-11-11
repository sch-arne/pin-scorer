"""Wandelt die Streitfall-Clips in GIFs -- damit sie ueberall aufgehen.

WOZU: Die Clips entstehen als MP4 mit dem `mp4v`-Codec. Den spielt nicht jeder
Betrachter ab; ein GIF laeuft dagegen in jedem Bildbetrachter und inline im
Chat, ohne Codec-Frage.

WAS ES KOSTET: GIF kennt nur 256 Farben und komprimiert schlechter als H.264.
Damit die Dateien handhabbar bleiben, wird verkleinert und jeder n-te Frame
uebersprungen, das Bild auf Kopfzeile und Tafel zugeschnitten, entrauscht und
auf 64 Farben gebracht. Die Kopfzeile mit den Messwerten muss dabei lesbar
bleiben -- sie ist der eigentliche Inhalt, nicht die Bildqualitaet.

GEMESSEN an einem 8-Sekunden-Clip:

    volles Bild, 900 px, 256 Farben, jeder 2. Frame     21 MB
    zugeschnitten, 560 px, 256 Farben, jeder 2.         15 MB
    zugeschnitten, 500 px, 64 Farben, entrauscht, 3.     s.u.

AUFRUF:

    .venv/Scripts/python.exe tools/clips_zu_gif.py <ordner> [--breite 900]
        [--jeder 2] [--fps 12]

`--jeder 2` nimmt jeden zweiten Frame; bei 25 fps Quelle und `--fps 12` laeuft
das GIF dann in Echtzeit.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import cv2
from PIL import Image


def gif_schreiben(quelle: Path, ziel: Path, breite: int, jeder: int,
                  fps: int, zuschnitt: bool = True,
                  farben: int = 64) -> tuple[int, float]:
    """Ein GIF je Clip. `zuschnitt` behaelt nur Kopfzeile und Tafel.

    WARUM ZUSCHNEIDEN: Das volle Hallenbild als GIF wiegt 21 MB je Clip --
    gemessen bei 900 px Breite und jedem zweiten Frame. Der groesste Teil davon
    ist Hallenboden, auf dem nichts geschieht, waehrend GIF jede Flaeche gleich
    teuer bezahlt. Die Aussage steckt in der eingeblendeten Tafel und der
    Kopfzeile mit den Messwerten; beides zusammen ist ein Achtel der Flaeche.
    """
    cap = cv2.VideoCapture(str(quelle))
    if not cap.isOpened():
        raise SystemExit(f"Clip nicht lesbar: {quelle}")

    bilder: list[Image.Image] = []
    index = 0
    while True:
        ok, bild = cap.read()
        if not ok:
            break
        if index % jeder == 0:
            if zuschnitt:
                # Kopfzeile (76 px) plus die Tafel-Einblendung links oben.
                # Die Masse stammt aus `export_problem_clips.py`: Einblendung
                # ab (10, 80), Tafel rund 160x155 mal Zoom 2.6.
                #
                # DIE BREITE richtet sich nach der KOPFZEILE, nicht nach der
                # Tafel: Die laengste Zeile ("Frame ... Lampen: ... gruen: ...
                # (Score ...)") misst rund 700 px. Schneidet man auf die Tafel
                # zu (434 px), faellt der Gruenscore weg -- also genau die
                # Zahl, wegen der man hinsieht.
                hoch = min(bild.shape[0], 80 + int(155 * 2.6) + 12)
                weit = min(bild.shape[1], 700)
                bild = bild[0:hoch, 0:weit]
            hoehe = int(breite * bild.shape[0] / bild.shape[1])
            klein = cv2.resize(bild, (breite, hoehe),
                               interpolation=cv2.INTER_AREA)
            # ENTRAUSCHEN vor der Umwandlung. GIF speichert jeden Frame fast
            # eigenstaendig; Sensorrauschen macht dabei jedes Pixel in jedem
            # Bild anders und verhindert die Kompression. Ein leichter
            # Weichzeichner kostet kaum Schaerfe und halbiert die Datei.
            klein = cv2.bilateralFilter(klein, 5, 40, 40)
            bilder.append(Image.fromarray(
                cv2.cvtColor(klein, cv2.COLOR_BGR2RGB)))
        index += 1
    cap.release()

    if not bilder:
        raise SystemExit(f"Keine Frames in {quelle}")

    # ADAPTIVE Palette je Bild waere schoener, aber dann flackern die Farben
    # von Frame zu Frame. Eine gemeinsame Palette aus dem MITTLEREN Bild haelt
    # sie ruhig -- dort steht die Tafel im interessanten Zustand.
    #
    # WENIGER FARBEN sind hier kein Verlust: Das Bild zeigt eine Tafel mit
    # roten Ziffern, gelben Rahmen und beigem Gehaeuse -- keine 256 Toene.
    # Ohne Dithering, weil dessen Streumuster in jedem Frame anders faellt und
    # die Kompression genauso verdirbt wie das Rauschen.
    palette = bilder[len(bilder) // 2].convert(
        "P", palette=Image.ADAPTIVE, colors=farben)
    umgesetzt = [b.quantize(palette=palette, dither=Image.NONE)
                 for b in bilder]

    ziel.parent.mkdir(parents=True, exist_ok=True)
    umgesetzt[0].save(ziel, save_all=True, append_images=umgesetzt[1:],
                      duration=int(round(1000 / fps)), loop=0, optimize=True)
    return len(umgesetzt), ziel.stat().st_size / 1e6


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ordner", type=Path, help="Ordner mit den MP4-Clips")
    p.add_argument("--breite", type=int, default=900)
    p.add_argument("--jeder", type=int, default=2,
                   help="nur jeden n-ten Frame uebernehmen")
    p.add_argument("--fps", type=int, default=12)
    p.add_argument("--farben", type=int, default=64,
                   help="Palettengroesse (weniger = kleinere Datei)")
    p.add_argument("--ganzes-bild", action="store_true",
                   help="ohne Zuschnitt -- deutlich groessere Dateien")
    p.add_argument("--out", type=Path, default=None,
                   help="Zielordner (Vorgabe: derselbe)")
    a = p.parse_args()

    clips = sorted(a.ordner.glob("*.mp4"))
    if not clips:
        print(f"Keine MP4-Clips in {a.ordner}")
        return 1

    ziel_ordner = a.out or a.ordner
    gesamt = 0.0
    for clip in clips:
        ziel = ziel_ordner / (clip.stem + ".gif")
        n, mb = gif_schreiben(clip, ziel, a.breite, a.jeder, a.fps,
                              zuschnitt=not a.ganzes_bild,
                              farben=a.farben)
        gesamt += mb
        print(f"  {ziel.name:<36} {n:>4} Bilder  {mb:>5.1f} MB")
    print(f"\n{len(clips)} GIFs, zusammen {gesamt:.1f} MB in {ziel_ordner}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
