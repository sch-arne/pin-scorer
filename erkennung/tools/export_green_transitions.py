"""Belegt die Lampenzaehlung an jedem Gruenwechsel -- als Bildstreifen.

Zweck: Die Lampen sind die Hauptquelle. Ob sie stimmen, laesst sich bisher nur
gegen die Ziffernfelder pruefen -- und die sind selbst fehleranfaellig. Wer die
Ziffern als Wahrheit nimmt, misst am Ende die Ziffern.

Deshalb hier BILDER: Je Gruenwechsel die ersten Frames als Ausschnitt der
Anzeigetafel, darueber die Zahl, die der Detektor daraus gemacht hat. Kein
Ziffernwert, keine Wertung -- nur "das war das Bild, das habe ich gezaehlt".
Damit ist die Zaehlung mit blossem Auge pruefbar.

Aufruf:
    .venv/Scripts/python.exe tools/export_green_transitions.py [VIDEO] [KALIBRIERUNG]

Ergebnis:
    debug/gruenwechsel/bahn{N}/{frame}_{AN|AUS}.png   je Wechsel ein Streifen
    debug/gruenwechsel/uebersicht_bahn{N}_{k}.png     Sammelblaetter zum Blaettern
    debug/gruenwechsel/wechsel.csv                    dieselben Zahlen als Tabelle
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

import cv2
import numpy as np

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.detection.state_machine import EventType
from kegel_cv.video import FileVideoSource, FrameBuffer

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = "data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json"
AUSGABE = Path("debug/gruenwechsel")

FRAMES_JE_WECHSEL = 5     # vom Nutzer so gewuenscht
SKALIERUNG = 2.2          # Ausschnitte sind klein -- vergroessern hilft dem Auge
PRO_BLATT = 12            # Wechsel je Sammelblatt


def zeit(frame: int, fps: float = 25.0) -> str:
    s = frame / fps
    return f"{int(s // 60)}:{int(s % 60):02d}"


def streifen(bilder: list[np.ndarray], zahlen: list[int | None],
             indizes: list[int], kopf: str) -> np.ndarray:
    """Baut aus mehreren Frames einen beschrifteten Streifen."""
    teile = []
    for bild, zahl, index in zip(bilder, zahlen, indizes):
        b = cv2.resize(bild, None, fx=SKALIERUNG, fy=SKALIERUNG,
                       interpolation=cv2.INTER_LANCZOS4)
        b = cv2.copyMakeBorder(b, 34, 6, 4, 4, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        cv2.putText(b, f"F{index}", (6, 13), cv2.FONT_HERSHEY_SIMPLEX,
                    0.38, (170, 170, 170), 1)
        text = "?" if zahl is None else str(zahl)
        # Die gezaehlte Lampenzahl gross und allein -- sie ist der Pruefgegenstand
        cv2.putText(b, f"{text} Lampen", (6, 28), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 255, 255), 1)
        teile.append(b)

    hoehe = max(t.shape[0] for t in teile)
    teile = [cv2.copyMakeBorder(t, 0, hoehe - t.shape[0], 0, 0,
                                cv2.BORDER_CONSTANT, value=(0, 0, 0)) for t in teile]
    streifen_bild = np.hstack(teile)
    streifen_bild = cv2.copyMakeBorder(streifen_bild, 26, 4, 4, 4,
                                       cv2.BORDER_CONSTANT, value=(0, 0, 0))
    cv2.putText(streifen_bild, kopf, (8, 18), cv2.FONT_HERSHEY_SIMPLEX,
                0.52, (255, 255, 255), 1)
    return streifen_bild


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    video = argumente[0] if argumente else VIDEO
    kalibrierung = argumente[1] if len(argumente) > 1 else KALIBRIERUNG

    cfg = load_config()
    cal = Calibration.load(kalibrierung)
    src = FileVideoSource(video)
    src.open()
    info = src.info
    print(f"Video: {info.source_id}  ({info.frame_count} Frames)")

    first = src.read()
    prozessoren = {}
    for lane in cal.lanes:
        p = LaneProcessor(lane, cfg)
        if p.prepare(first.image.shape):
            prozessoren[lane.display_number] = p
    print(f"Bahnen: {sorted(prozessoren)}\n")

    AUSGABE.mkdir(parents=True, exist_ok=True)
    for dn in prozessoren:
        (AUSGABE / f"bahn{dn}").mkdir(exist_ok=True)

    # Je Bahn die offenen Wechsel: noch fehlende Frames einsammeln
    offen: dict[int, list[dict]] = {dn: [] for dn in prozessoren}
    fertige: dict[int, list[tuple[int, str, np.ndarray, list]]] = {
        dn: [] for dn in prozessoren}
    buffer = FrameBuffer(cfg.processing.frame_buffer_size)

    frame = first
    n = 0
    while frame is not None:
        buffer.append(frame)
        for dn, p in prozessoren.items():
            _, ereignis, _ = p.process(frame, buffer)

            # Laufende Wechsel bedienen -- BEVOR ein neuer beginnt
            for eintrag in list(offen[dn]):
                messung = p.read_pin_lamps_at(frame)
                # lane_box() liefert (x, y, Breite, Hoehe) -- nicht zwei Ecken.
                x, y, w, h = p.lane_box()
                eintrag["bilder"].append(frame.image[y:y + h, x:x + w].copy())
                eintrag["zahlen"].append(messung.count if messung else None)
                eintrag["indizes"].append(frame.index)
                if len(eintrag["bilder"]) >= FRAMES_JE_WECHSEL:
                    offen[dn].remove(eintrag)
                    fertige[dn].append((eintrag["start"], eintrag["art"],
                                        streifen(eintrag["bilder"], eintrag["zahlen"],
                                                 eintrag["indizes"], eintrag["kopf"]),
                                        eintrag["zahlen"]))

            if ereignis is not None and ereignis.event in (EventType.GREEN_ON,
                                                           EventType.GREEN_OFF):
                art = "AN" if ereignis.event is EventType.GREEN_ON else "AUS"
                offen[dn].append({
                    "start": frame.index, "art": art,
                    "kopf": f"Bahn {dn} | gruen {art} | {zeit(frame.index, info.fps)}"
                            f" | Frame {frame.index}",
                    "bilder": [], "zahlen": [], "indizes": [],
                })

        frame = src.read()
        n += 1
        if n % 10000 == 0:
            gesamt = sum(len(v) for v in fertige.values())
            print(f"   {100 * n / max(1, info.frame_count):5.1f} %  "
                  f"({gesamt} Wechsel erfasst)")
    src.close()

    # --- Schreiben ---
    zeilen = []
    gesamt = 0
    for dn, eintraege in fertige.items():
        eintraege.sort(key=lambda e: e[0])
        for start, art, bild, zahlen in eintraege:
            cv2.imwrite(str(AUSGABE / f"bahn{dn}" / f"{start:06d}_{art}.png"), bild)
            zeilen.append({"Bahn": dn, "Zeit": zeit(start, info.fps), "Frame": start,
                           "Wechsel": art,
                           **{f"Lampen_{i+1}": (z if z is not None else "")
                              for i, z in enumerate(zahlen)}})
            gesamt += 1

        # Sammelblaetter: zum Durchblaettern statt hunderte Einzeldateien
        for k in range(0, len(eintraege), PRO_BLATT):
            teil = [e[2] for e in eintraege[k:k + PRO_BLATT]]
            breite = max(t.shape[1] for t in teil)
            teil = [cv2.copyMakeBorder(t, 0, 8, 0, breite - t.shape[1],
                                       cv2.BORDER_CONSTANT, value=(40, 40, 40))
                    for t in teil]
            cv2.imwrite(str(AUSGABE / f"uebersicht_bahn{dn}_{k // PRO_BLATT + 1}.png"),
                        np.vstack(teil))

    with (AUSGABE / "wechsel.csv").open("w", encoding="utf-8-sig", newline="") as f:
        if zeilen:
            schreiber = csv.DictWriter(f, fieldnames=list(zeilen[0]), delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(zeilen)

    print(f"\n{gesamt} Gruenwechsel geschrieben nach {AUSGABE}")
    for dn, eintraege in sorted(fertige.items()):
        an = sum(1 for e in eintraege if e[1] == "AN")
        aus = sum(1 for e in eintraege if e[1] == "AUS")
        print(f"   Bahn {dn}: {an}x gruen AN, {aus}x gruen AUS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
