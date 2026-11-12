"""Legt die strittigen Stellen Frame fuer Frame offen -- MESSUNG.

Vier Faelle bleiben nach dem Vergleich mit dem Wurfprotokoll offen. Der Nutzer
hat zu allen vieren eine Deutung geliefert; diese Datei prueft sie am Signal
statt am Eindruck.

    Bahn 2  F 4032   Tor hinten geoeffnet/geschlossen -> Wurf erfunden
    Bahn 2  F43514   dasselbe
    Bahn 2  F44352   Lampen blinken -> 0 statt 9 gezaehlt
    Bahn 4  F77497   letzter Kegel faellt unmittelbar vor Gruen-AUS

Ausgegeben wird je Frame: Gruen-Score und Zustand, die Zahl der leuchtenden
Kegellampen und WELCHE leuchten. Erst daran laesst sich sagen, ob eine Lampe
kurz dunkel war (Blinken), ob alle zugleich verschwanden (Anlage), oder ob die
gruene Lampe eine Flanke geschlagen hat, die kein Wurf war.

Aufruf:
    .venv/Scripts/python.exe tools/trace_problem_spots.py [FALL ...]

Ergebnis:
    debug/problemspuren/bahn{N}_{frame}.csv
"""

from __future__ import annotations

import csv
import logging
import sys
from pathlib import Path

from kegel_cv.analysis.lane_processor import LaneProcessor
from kegel_cv.calibration import Calibration
from kegel_cv.config import load_config
from kegel_cv.video import FileVideoSource

VIDEO = "kegelVideos/2026-08-22 09-24-46.mp4"
KALIBRIERUNG = ("data/calibrations/"
                "kalibrierung_2026-08-25_0950_allDigits_neu_2_leftdisplay.json")
AUSGABE = Path("debug/problemspuren")

FAELLE = [
    {"bahn": 2, "frame": 4032, "vor": 500, "nach": 300, "was": "Tor 2:41"},
    {"bahn": 2, "frame": 43514, "vor": 500, "nach": 300, "was": "Tor 29:00"},
    {"bahn": 2, "frame": 44352, "vor": 500, "nach": 400, "was": "Blinken 29:34"},
    {"bahn": 4, "frame": 77497, "vor": 500, "nach": 280, "was": "letzter Kegel 51:39"},
]


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    gewaehlt = [int(a) for a in sys.argv[1:] if a.isdigit()]

    cfg = load_config()
    cal = Calibration.load(KALIBRIERUNG)
    src = FileVideoSource(VIDEO)
    src.open()
    info = src.info
    erster = src.read()

    prozessoren = {}
    for lane in cal.lanes:
        p = LaneProcessor(lane, cfg)
        if p.prepare(erster.image.shape):
            prozessoren[lane.display_number] = p

    AUSGABE.mkdir(parents=True, exist_ok=True)
    faelle = [f for i, f in enumerate(FAELLE) if not gewaehlt or i in gewaehlt]

    for fall in faelle:
        p = prozessoren.get(fall["bahn"])
        if p is None:
            continue
        von = max(0, fall["frame"] - fall["vor"])
        bis = fall["frame"] + fall["nach"]

        print("=" * 78)
        print(f"{fall['was']}  --  Bahn {fall['bahn']}, Frame {von}-{bis}")
        print("=" * 78)

        src.seek(von)
        frame = src.read()
        zeilen = []
        while frame is not None and frame.index <= bis:
            gruen = p.green_detector.detect(p._crop(frame.image, p._green_box))
            messung = p.read_pin_lamps_at(frame)
            leuchtend = list(messung.pins) if messung else []
            unbekannt = ([l.name.removeprefix("pin_lamp_")
                          for l in messung.lamps if l.state.value == "UNKNOWN"]
                         if messung else [])
            zeilen.append({
                "Frame": frame.index,
                "Versatz": frame.index - fall["frame"],
                "Zeit": f"{frame.timestamp:.2f}",
                "GruenScore": round(gruen.score, 1),
                "Gruen": "AN" if gruen.is_on else "aus",
                "Lampen": len(leuchtend),
                "Kegel": " ".join(map(str, leuchtend)),
                "Unlesbar": " ".join(unbekannt),
            })
            frame = src.read()

        ziel = AUSGABE / f"bahn{fall['bahn']}_{fall['frame']}.csv"
        with ziel.open("w", encoding="utf-8-sig", newline="") as datei:
            schreiber = csv.DictWriter(datei, fieldnames=list(zeilen[0]),
                                       delimiter=";")
            schreiber.writeheader()
            schreiber.writerows(zeilen)

        # Zusammenfassung: nur die Stellen, an denen sich etwas AENDERT
        print(f"{'Versatz':>9}{'Frame':>8}{'Score':>8}{'gruen':>7}"
              f"{'Lampen':>8}   Kegel")
        letzte = None
        for z in zeilen:
            kennung = (z["Gruen"], z["Lampen"], z["Kegel"])
            if kennung != letzte:
                print(f"{z['Versatz']:>+9}{z['Frame']:>8}{z['GruenScore']:>8}"
                      f"{z['Gruen']:>7}{z['Lampen']:>8}   {z['Kegel'] or '-'}"
                      + (f"   unlesbar: {z['Unlesbar']}" if z["Unlesbar"] else ""))
                letzte = kennung
        print(f"\n   -> {ziel}\n")

    src.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
