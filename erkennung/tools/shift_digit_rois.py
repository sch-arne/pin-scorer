"""Verschiebt die ROIs eines Ziffernfeldes waagerecht -- als neue Datei.

WOZU -- gemessen am 2026-08-31 mit `tools/fit_digit_offsets.py`: Die fuehrende
Stelle eines mehrstelligen Feldes ist auf dieser Tafel immer null (Wurfnummern
001-030, Summen 0-270, Fehlwurfzaehler 00-0x). Der Anteil der Lesungen, bei
denen sie NICHT null ist, sagt damit ohne jeden Sollwert, ob die ROI sitzt:

    Bahn 2  total_b   heute 21 % falsch  ->  bei +0,006 noch 0 %
    Bahn 4  total_b   heute 10 % falsch  ->  bei +0,002 noch 0 %

Alle uebrigen zehn Kombinationen aus Bahn und Feld liegen heute schon bei 0 %.
Dort waere jede Verschiebung geraten, und sie unterbleibt.

URSACHE: Eine "0" ist abcdef. Fing die Box links den Auslaeufer der
Nachbarziffer mit, schob dieser Fremdanteil die eigentliche Ziffer beim
Normieren auf die 24x40-Zelle nach rechts -- die Segmentflaechen fuer e und f
sammelten dann Zwischenraum ein. Uebrig blieb abcd, naechstliegend "3"; fehlte
zusaetzlich d, blieb abc, also "7". Beide beobachteten Fehlwerte sind dieselbe
abgeschnittene Null.

Das Werkzeug schreibt IMMER eine neue Datei. Die Kalibrierung ist Handarbeit
des Nutzers; sie wird nicht ueberschrieben, solange ein Lauf die Aenderung
nicht bestaetigt hat.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DIGIT_PREFIX = "digit_"


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--shift", action="append", required=True, metavar="BAHN:FELD:WERT",
                   help="z.B. 4:total_b:0.002 -- mehrfach angebbar. Positiv "
                        "verschiebt nach rechts.")
    a = p.parse_args()

    d = json.loads(a.calibration.read_text(encoding="utf-8"))
    aenderungen = []
    for eintrag in a.shift:
        teile = eintrag.split(":")
        if len(teile) != 3:
            raise SystemExit(f"Unlesbar: {eintrag} (erwartet BAHN:FELD:WERT)")
        bahn, feld, wert = int(teile[0]), teile[1], float(teile[2])
        aenderungen.append((bahn, feld, wert))

    for bahn, feld, wert in aenderungen:
        lanes = [l for l in d["lanes"] if l.get("real_lane_number") == bahn]
        if not lanes:
            raise SystemExit(f"Bahn {bahn} nicht in der Kalibrierung")
        praefix = f"{DIGIT_PREFIX}{feld}_"
        getroffen = 0
        for lane in lanes:
            for roi in lane["rois"]:
                if not roi["name"].startswith(praefix):
                    continue
                x, y, w, h = roi["rect"]
                roi["rect"] = [x + wert, y, w, h]
                getroffen += 1
        if not getroffen:
            raise SystemExit(f"Bahn {bahn}: kein Feld '{feld}' stellenweise "
                             f"kalibriert -- nichts zu verschieben")
        print(f"  Bahn {bahn}  {feld:<14} {wert:+.3f}  ({getroffen} Stellen)")

    teile = [f"B{b} {f} {w:+.3f}" for b, f, w in aenderungen]
    d["name"] = f"{d.get('name', '')} [{', '.join(teile)}]".strip()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(d, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    print(f"\nGeschrieben: {a.out}  (Original unveraendert)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
