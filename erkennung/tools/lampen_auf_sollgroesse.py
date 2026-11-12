"""Setzt alle Lampen-ROIs einer Kalibrierung auf die GEMESSENE Sollgroesse.

WOZU: Die Groesse der Lampen-ROIs entscheidet ueber die Trennschaerfe zwischen
AN und AUS. GEMESSEN am 2026-09-02 (`tools/measure_roi_shrink.py`): Der enge
Rahmen hebt die Trennung auf Bahn 4 von 33,7 auf 44,8 Punkte und senkt die
unentschiedenen Messungen von 6,73 % auf 0,50 %.

Kommt eine Kalibrierung aus einer aelteren Fassung oder wurde eine ROI von
Hand aufgezogen, kann sie zu weit sein. Dieses Werkzeug zieht sie auf die
Sollgroesse zusammen, OHNE die Mitte zu verschieben -- die muehsame Arbeit
des Positionierens bleibt also erhalten.

KEINE eigene Zahl: Die Sollgroesse kommt aus `default_roi_size()`, derselben
Quelle, aus der auch die Oberflaeche sie nimmt. Zwei Stellen mit derselben
Zahl waeren zwei Wahrheiten.

AUFRUF:

    .venv/Scripts/python.exe tools/lampen_auf_sollgroesse.py \
        --calibration data/calibrations/Spieltag2.json --inplace

    (ohne --inplace wird nur berichtet, nichts geaendert)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kegel_cv.calibration.session import default_roi_size  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--out", type=Path, default=None,
                   help="Zieldatei (Standard: neben der Quelle mit _sollgroesse)")
    p.add_argument("--inplace", action="store_true",
                   help="die Quelldatei selbst ueberschreiben")
    p.add_argument("--auch-gruen", action="store_true",
                   help="die Gruenlampe mitziehen (Standard: nur Kegellampen)")
    a = p.parse_args()

    daten = json.loads(a.calibration.read_text(encoding="utf-8"))
    namen = {f"pin_lamp_{i}" for i in range(1, 10)}
    if a.auch_gruen:
        namen.add("green_lamp")

    geaendert = 0
    print(f"{'Bahn':>5} {'ROI':>12} {'vorher':>17} {'nachher':>17}")
    print("-" * 56)
    for lane in daten.get("lanes", []):
        bahn = lane.get("real_lane_number", lane.get("lane_id"))
        for roi in lane.get("rois", []):
            if roi["name"] not in namen:
                continue
            x, y, w, h = roi["rect"]
            soll_w, soll_h = default_roi_size(roi["name"])
            if abs(w - soll_w) < 1e-6 and abs(h - soll_h) < 1e-6:
                continue
            # Mitte halten -- die Position ist Handarbeit und bleibt.
            cx, cy = x + w / 2, y + h / 2
            roi["rect"] = [cx - soll_w / 2, cy - soll_h / 2, soll_w, soll_h]
            geaendert += 1
            print(f"{bahn:>5} {roi['name']:>12} "
                  f"{w:.4f} x {h:.4f}".rjust(17)
                  + f"   {soll_w:.4f} x {soll_h:.4f}".rjust(17))

    if not geaendert:
        print("Alle Lampen-ROIs haben bereits die Sollgroesse -- nichts zu tun.")
        return 0

    ziel = a.calibration if a.inplace else (
        a.out or a.calibration.with_name(a.calibration.stem + "_sollgroesse.json"))
    if not a.inplace and not a.out and ziel.exists():
        print(f"\n{ziel} existiert bereits -- bitte --out angeben.")
        return 1
    ziel.write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"\n{geaendert} ROIs angepasst -> {ziel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
