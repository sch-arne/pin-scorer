"""Misst die Pause zwischen erkanntem Spielwechsel und dem ersten echten Wurf.

WOZU -- Nutzerfrage (2026-09-03): Im Normalbetrieb unterbricht der Spielleiter
das Spiel kurz, wenn die Anzeige auf `000/0000` steht, und gibt die Bahn erst
danach wieder frei. Diese Pause sollte messbar laenger sein als der Abstand
zwischen zwei gewoehnlichen Wuerfen -- und liesse sich als Kriterium nutzen,
das (anders als ein reiner Zeitabstand zwischen Wuerfen) nicht mit einem
schnellen Raeumwurf verwechselt werden kann: Es misst ab einem STRUKTURELLEN
Ereignis (dem Spielwechsel), nicht ab dem letzten Wurf.

GEMESSEN wird: Zeitstempel des ersten geloggten "Anzeige steht ... auf
000/0000" je Bahn und Spielwechsel, bis zum ersten Wurf des naechsten Spiels
mit mindestens einem gefallenen Kegel ODER lesbarer Ziffer (die "leeren"
Uebergangs-Nullwuerfe zaehlen nicht als Ende der Pause).

AUFRUF:

    .venv/Scripts/python.exe tools/measure_reset_pause.py <lauf_log> <wuerfe.csv>
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import statistics as st
from pathlib import Path


def resets_lesen(log_pfad: Path) -> list[tuple[int, int, float]]:
    """(Bahn, Frame, Zeit_s) je geloggtem Spielwechsel, in Reihenfolge."""
    muster = re.compile(
        r"(\d{2}):(\d{2}):(\d{2}),\d+ INFO\s+kegel_cv\.analysis\.lane_processor "
        r"Bahn (\d+): Anzeige steht bei Frame (\d+) auf 000/0000")
    treffer = []
    basis = None
    for zeile in io.open(log_pfad, encoding="utf-8", errors="replace"):
        m = muster.search(zeile)
        if not m:
            continue
        h, mi, s, bahn, frame = m.groups()
        t = int(h) * 3600 + int(mi) * 60 + int(s)
        if basis is None:
            basis = t
        treffer.append((int(bahn), int(frame), t - basis))
    return treffer


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("log", type=Path)
    p.add_argument("wuerfe", type=Path)
    a = p.parse_args()

    resets = resets_lesen(a.log)
    if not resets:
        print("Keine Spielwechsel-Meldungen im Log gefunden.")
        return 1

    wuerfe = list(csv.DictReader(
        io.open(a.wuerfe, encoding="utf-8-sig", newline=""), delimiter=";"))
    je_bahn = {}
    for w in wuerfe:
        je_bahn.setdefault(int(w["Bahn"]), []).append(w)
    for bahn in je_bahn:
        je_bahn[bahn].sort(key=lambda w: int(w["Frame"]))

    print(f"{len(resets)} Spielwechsel-Meldungen im Log\n")
    print(f"{'Bahn':>4} {'Reset-Frame':>11} {'erster echter Wurf':>19} "
          f"{'Frames':>7} {'Sekunden':>9}")

    pausen = []
    for bahn, reset_frame, _ in resets:
        folge = je_bahn.get(bahn, [])
        for w in folge:
            wf = int(w["Frame"])
            if wf <= reset_frame:
                continue
            # "echt" = mindestens ein Kegel ODER eine lesbare Ziffer.
            # Die leeren Uebergangs-Nullwuerfe (0 Kegel, keine Ziffer) sind
            # genau die Faelle aus dieser Untersuchung -- sie zaehlen NICHT
            # als Ende der Pause, sonst mässe man die Pause gegen sich selbst.
            if int(w["Kegel"]) > 0 or w["Ziffer"]:
                dauer = wf - reset_frame
                pausen.append(dauer)
                print(f"{bahn:>4} {reset_frame:>11} {wf:>19} "
                      f"{dauer:>7} {dauer/25.0:>8.1f}s")
                break
        else:
            print(f"{bahn:>4} {reset_frame:>11} {'kein weiterer Wurf':>19}")

    if not pausen:
        return 0

    pausen_s = [p / 25.0 for p in pausen]
    print(f"\n=== Verteilung der Pause (Spielwechsel -> erster echter Wurf) ===")
    print(f"  n = {len(pausen_s)}")
    print(f"  Minimum : {min(pausen_s):.1f} s")
    print(f"  5. Perz.: {sorted(pausen_s)[max(0, len(pausen_s)*5//100)]:.1f} s")
    print(f"  Median  : {st.median(pausen_s):.1f} s")
    print(f"  95. Perz: {sorted(pausen_s)[min(len(pausen_s)-1, len(pausen_s)*95//100)]:.1f} s")
    print(f"  Maximum : {max(pausen_s):.1f} s")

    print(f"\n=== Zum Vergleich: Abstand zwischen gewoehnlichen Wuerfen ===")
    normal = []
    for bahn, folge in je_bahn.items():
        for x, y in zip(folge, folge[1:]):
            dx = float(y["Zeitstempel_s"]) - float(x["Zeitstempel_s"])
            if 0 < dx < 120:
                normal.append(dx)
    if normal:
        print(f"  n = {len(normal)}")
        print(f"  5. Perz.: {sorted(normal)[len(normal)*5//100]:.1f} s")
        print(f"  Median  : {st.median(normal):.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
