"""Schneidet strittige Stellen als Videoclips heraus -- zum gemeinsamen Ansehen.

WOZU: Wo Protokoll und Bilderkennung auseinandergehen, entscheidet keine
Kennzahl, sondern der Blick auf die Stelle. Ein Standbild reicht dafuer nicht --
ob ein Kegel noch faellt, ob die Lampen blinken, ob jemand durchs Bild laeuft,
zeigt erst die Bewegung.

Jeder Clip zeigt das ganze Bild (das Tor der Halle steht nicht auf der Tafel)
und die betroffene Tafel vergroessert eingeblendet, dazu je Frame die Zahl, die
der Detektor gerade daraus macht. Der Zaehlframe ist orange umrandet.

AUFRUF:

    .venv/Scripts/python.exe tools/export_problem_clips.py         --source <Datei oder Stream-URL>         --calibration data/calibrations/1Spieltag_enge_lampen.json         --fall 4:289308 --vor 4 --nach 4 --out debug/streitfaelle

`--fall` ist BAHN:FRAME[:BESCHREIBUNG] und mehrfach angebbar. `--vor` und
`--nach` sind SEKUNDEN um den genannten Frame.

Alternativ `--aus-csv <datei>`: liest Faelle aus einer CSV mit den Spalten
Bahn und Frame (weitere Spalten werden als Beschreibung mitgenommen).
"""

from __future__ import annotations

import argparse
import csv
import logging
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.video import open_source

BREITE = 1280          # Ausgabebreite; das Original ist 1920 und zu gross
TAFEL_ZOOM = 2.6


def faelle_lesen(argumente: list[str], csv_pfad: Path | None,
                 vor_s: float, nach_s: float, fps: float) -> list[dict]:
    """Baut die Fallliste aus `--fall` und/oder einer CSV.

    Die Sekundenangaben werden hier EINMAL in Frames umgerechnet -- der Nutzer
    denkt in Sekunden, das Video zaehlt in Frames.
    """
    vor, nach = int(round(vor_s * fps)), int(round(nach_s * fps))
    faelle: list[dict] = []

    for eintrag in argumente or []:
        teile = eintrag.split(":", 2)
        if len(teile) < 2 or not teile[0].isdigit() or not teile[1].isdigit():
            raise SystemExit(f"--fall braucht BAHN:FRAME[:TEXT], nicht '{eintrag}'")
        faelle.append({"bahn": int(teile[0]), "frame": int(teile[1]),
                       "vor": vor, "nach": nach,
                       "was": teile[2] if len(teile) > 2 else "",
                       "soll": "", "ist": ""})

    if csv_pfad:
        with csv_pfad.open(encoding="utf-8-sig", newline="") as datei:
            for zeile in csv.DictReader(datei, delimiter=";"):
                if not zeile.get("Bahn") or not zeile.get("Frame"):
                    continue
                rest = {k: v for k, v in zeile.items()
                        if k not in ("Bahn", "Frame") and v}
                faelle.append({
                    "bahn": int(zeile["Bahn"]), "frame": int(zeile["Frame"]),
                    "vor": vor, "nach": nach,
                    "was": zeile.get("Was", ""),
                    "soll": zeile.get("Soll", ""),
                    "ist": zeile.get("Ist", "")
                            or "  ".join(f"{k}={v}" for k, v in rest.items()),
                })
    return faelle


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--fall", action="append", metavar="BAHN:FRAME[:TEXT]")
    p.add_argument("--aus-csv", dest="aus_csv", type=Path, default=None)
    p.add_argument("--vor", type=float, default=4.0, help="Sekunden davor")
    p.add_argument("--nach", type=float, default=4.0, help="Sekunden danach")
    p.add_argument("--out", type=Path, default=Path("debug/streitfaelle"))
    a = p.parse_args()

    if not a.fall and not a.aus_csv:
        raise SystemExit("Mindestens ein --fall oder --aus-csv angeben.")

    cfg = load_config()
    cal = Calibration.load(a.calibration)

    def neue_quelle():
        """Frisch geoeffnete Quelle -- siehe Begruendung unten."""
        quelle = open_source(a.source, cfg)
        quelle.open()
        return quelle

    src = neue_quelle()
    info = src.info
    erster = src.read()

    prozessoren = {}
    for lane in cal.lanes:
        prozessor = LaneProcessor(lane, cfg)
        if prozessor.prepare(erster.image.shape):
            prozessoren[lane.display_number] = prozessor

    AUSGABE = a.out
    AUSGABE.mkdir(parents=True, exist_ok=True)
    faelle = faelle_lesen(a.fall, a.aus_csv, a.vor, a.nach, info.fps)

    # FUER JEDEN FALL EINE FRISCHE QUELLE OEFFNEN.
    #
    # GEMESSEN am 2026-09-03: Sortieren nach Zaehlframe reicht nicht. Liegen
    # zwei Faelle naeher beieinander als das Vorlauf-Fenster (hier: 196 Frames
    # Abstand bei 200 Frames Vorlauf), liegt der SPRUNGZIEL des zweiten VOR dem
    # Ende des ersten Clips -- ein Ruecksprung trotz steigender Frame-Zahlen.
    # Eine durchgehende Sitzung mit mehreren Spruengen lieferte danach fuer
    # zwei von vier Faellen nur noch 0 bis 2 Frames.
    #
    # Eine neue Quelle je Fall kostet Verbindungsaufbau, ist bei einer
    # Handvoll Streitfaellen aber vernachlaessigbar -- und robust gegen jede
    # Reihenfolge und jeden Abstand.
    print(f"{len(faelle)} Faelle, je {a.vor:.0f} s davor und {a.nach:.0f} s "
          f"danach (eigene Quelle je Fall)\n")

    for fall in faelle:
        proz = prozessoren.get(fall["bahn"])
        if proz is None:
            print(f"Bahn {fall['bahn']} nicht kalibriert")
            continue

        if fall is not faelle[0]:
            src.close()
            src = neue_quelle()

        von = max(0, fall["frame"] - fall["vor"])
        bis = fall["frame"] + fall["nach"]
        sek = fall["frame"] / info.fps
        name = (AUSGABE / f"bahn{fall['bahn']}_{int(sek // 60):02d}-"
                f"{int(sek % 60):02d}_F{fall['frame']}.mp4")

        hoehe = int(BREITE * info.height / info.width)
        schreiber = cv2.VideoWriter(str(name), cv2.VideoWriter_fourcc(*"mp4v"),
                                    info.fps, (BREITE, hoehe))
        if not schreiber.isOpened():
            print(f"Konnte {name} nicht anlegen")
            continue

        src.seek(von)
        frame = src.read()
        lx, ly, lw, lh = proz.lane_box()
        n = 0
        while frame is not None and frame.index <= bis:
            messung = proz.read_pin_lamps_at(frame)
            gruen = proz.green_detector.detect(
                proz._crop(frame.image, proz._green_box))

            bild = cv2.resize(frame.image, (BREITE, hoehe))

            # Die betroffene Tafel gross oben links einblenden
            tafel = frame.image[ly:ly + lh, lx:lx + lw]
            if tafel.size:
                tafel = cv2.resize(tafel, None, fx=TAFEL_ZOOM, fy=TAFEL_ZOOM,
                                   interpolation=cv2.INTER_LANCZOS4)
                th, tw = tafel.shape[:2]
                if th < hoehe - 90 and tw < BREITE - 20:
                    bild[80:80 + th, 10:10 + tw] = tafel
                    cv2.rectangle(bild, (10, 80), (10 + tw, 80 + th),
                                  (0, 200, 255), 2)

            # Kopfzeile: worum es geht
            cv2.rectangle(bild, (0, 0), (BREITE, 76), (0, 0, 0), -1)
            versatz = frame.index - fall["frame"]
            cv2.putText(bild, f"Bahn {fall['bahn']} | {fall['was']}",
                        (12, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65,
                        (255, 255, 255), 2)
            cv2.putText(bild, f"{fall['soll']}   |   {fall['ist']}",
                        (12, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (170, 220, 255), 1)
            cv2.putText(bild,
                        f"Frame {frame.index}  ({versatz:+d} zum Zaehlframe)   "
                        f"Lampen: {messung.count if messung else '?'}   "
                        f"gruen: {'AN' if gruen.is_on else 'aus'} "
                        f"(Score {gruen.score:.0f})",
                        (12, 68), cv2.FONT_HERSHEY_SIMPLEX, 0.48,
                        (120, 255, 120) if gruen.is_on else (200, 200, 200), 1)
            if versatz == 0:
                cv2.rectangle(bild, (2, 2), (BREITE - 3, hoehe - 3),
                              (0, 140, 255), 6)

            schreiber.write(bild)
            frame = src.read()
            n += 1
        schreiber.release()
        # Ein leerer Clip ist ein Fehler, kein Ergebnis. Ohne diese Meldung
        # entsteht eine unbrauchbare Datei, ohne dass irgendetwas fehlschlaegt.
        if n < 5:
            print(f"  ACHTUNG: nur {n} Frames gelesen -- die Quelle hat den "
                  f"Sprung auf {von} nicht mitgemacht.")
        print(f"{name}   {n} Frames ({n / info.fps:.1f} s), "
              f"Frame {von}-{bis}")

    src.close()
    print(f"\nAlle Clips in {AUSGABE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
