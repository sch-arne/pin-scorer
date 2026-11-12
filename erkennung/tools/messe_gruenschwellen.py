"""Zeigt die Gruenlampen-Niveaus je Bahn -- Diagnose beim Kalibrieren.

WOZU (Nutzer, 2026-10-02): *„wenn ich dich richtig verstanden habe, ist ja das
Problem, dass anfangs alle Bahnen immer fuer ein paar Minuten nur Gruen AN
haben... oder?"* -- genau so ist es.

Der Detektor lernt seine Schwellen im Betrieb: zuerst aus dem gleitenden
Histogramm, hilfsweise aus Perzentilen. Beides setzt voraus, dass BEIDE
Zustaende im Fenster vorkommen. Zu Beginn einer Aufzeichnung ist die Anlage
aber freigegeben und die Lampe durchgehend an. Gemessen am 2. Spieltag:

    erstes AUS   Bahn 2: Frame 7558   Bahn 3: 10400
                 Bahn 4: Frame 10480  Bahn 5:  5607

Auf Bahn 4 traegt also achteinhalb Minuten lang allein die FESTE Schwelle --
und die ist global (45/35). Zu den vier gemessenen AUS-Niveaus (25,5 / 22,9 /
31,4 / 25,7) passt sie eher zufaellig. Eine nach Trennschaerfe bessere
Gruenlampen-ROI hob das AUS-Niveau auf Bahn 4 auf 50,3, also ueber die feste
Schwelle -- und die ersten drei Wuerfe des Spieltags gingen verloren.

Dieses Werkzeug nimmt der festen Schwelle das Raten: Es liest die Gruenspur
eines fertigen Laufs, trennt die beiden Wolken und legt die Schwellen
anteilig dazwischen -- dieselbe Rechnung, die der Detektor im Betrieb macht,
nur ueber den ganzen Lauf statt ueber ein Fenster.

    AUS-Niveau   Perzentil `adaptive_off_percentile` der Messungen
    AN-Niveau    Perzentil `adaptive_on_percentile`
    Schwellen    AUS + `adaptive_on_fraction` bzw. `_off_fraction` der Spanne

GEPRUEFT WIRD, dass die Wolken ueberhaupt getrennt sind: Liegt die Spanne
unter `adaptive_min_span`, sagt der Lauf nichts ueber diese Bahn und es wird
nichts eingetragen.

WAS DARAUS WURDE: Ein erster Anlauf trug diese Schwellen je Bahn in die
Kalibrierung ein. Das behebt das Symptom und schafft eine neue Groesse, die
bei jeder ROI-Aenderung mitgepflegt werden muss -- Nutzer dazu: *„Ich halte
2 Schwellen fuer schwierig... das ist ja sehr Kalibrierungsabhaengig."* Der
Detektor ueberbrueckt den Anlauf jetzt ueber eine AENDERUNG
(`detection.green.warmup_min_change`), die ohne absoluten Bezug auskommt.

Geblieben ist dieses Werkzeug als DIAGNOSE: Die Warnung „AUS-Niveau ueber
der globalen Schwelle" hat den Bahn-4-Fall von selbst gemeldet, und das ist
beim Kalibrieren wertvoll.

Aufruf:

    .venv/Scripts/python.exe tools/messe_gruenschwellen.py \
        --lauf debug/Vorstand-Grundlinie/lauf_2026-09-29_13-52-42 \
        --kalibrierung data/calibrations/2Spieltag_neu.json
"""

from __future__ import annotations

import argparse
import collections
import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration.model import Calibration     # noqa: E402
from kegel_cv.config import load_config                # noqa: E402


def niveaus(werte: np.ndarray, cfg) -> tuple[float, float, float]:
    """(AUS-Niveau, AN-Niveau, Spanne) -- wie `HsvGreenDetector._thresholds`."""
    aus = float(np.percentile(werte, cfg.adaptive_off_percentile))
    an = float(np.percentile(werte, cfg.adaptive_on_percentile))
    return aus, an, an - aus


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--bahnen", default="",
                   help="nur diese Bahnen eintragen, z.B. 5 oder 2,3,4. "
                        "NOETIG, wenn die ROIs seit dem Lauf veraendert "
                        "wurden: Eine Schwelle gilt immer fuer die ROI, an "
                        "der sie gemessen wurde.")
    a = p.parse_args()

    cfg = load_config().detection.green
    kal = Calibration.load(str(a.kalibrierung))
    nur = ({int(x) for x in a.bahnen.split(",") if x.strip()}
           if a.bahnen else None)

    spuren: dict[str, list[float]] = collections.defaultdict(list)
    with (a.lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            spuren[r["Bahn"]].append(float(r["Score"]))

    print(f"Konfiguration: fest {cfg.on_threshold}/{cfg.off_threshold}, "
          f"Mindestspanne {cfg.adaptive_min_span}\n")
    print(f"{'Bahn':>4} {'Messungen':>10} {'AUS':>7} {'AN':>7} {'Spanne':>7} "
          f"{'-> AN':>7} {'-> AUS':>7}  Urteil")
    neu: dict[int, tuple[float, float]] = {}
    for lane in sorted(kal.lanes, key=lambda l: l.display_number):
        bahn = lane.display_number
        werte = np.asarray(spuren.get(str(bahn), []), dtype=np.float64)
        if werte.size < 1000:
            print(f"{bahn:>4} {werte.size:>10}  zu wenige Messungen")
            continue
        aus_n, an_n, spanne = niveaus(werte, cfg)
        if spanne < cfg.adaptive_min_span:
            print(f"{bahn:>4} {werte.size:>10} {aus_n:>7.1f} {an_n:>7.1f} "
                  f"{spanne:>7.1f} {'':>7} {'':>7}  Wolken zu dicht -- "
                  f"nichts eingetragen")
            continue
        an_s = aus_n + cfg.adaptive_on_fraction * spanne
        aus_s = aus_n + cfg.adaptive_off_fraction * spanne
        warnung = ""
        if aus_n > cfg.off_threshold:
            warnung = ("  AUS-Niveau UEBER der festen Schwelle -- im Anlauf "
                       "traegt allein die Aenderungsregel")
        print(f"{bahn:>4} {werte.size:>10} {aus_n:>7.1f} {an_n:>7.1f} "
              f"{spanne:>7.1f} {an_s:>7.1f} {aus_s:>7.1f}{warnung}")

    print("\nDiese Werte gehen NICHT in die Analyse. Der Detektor ueberbrueckt"
          "\nden Anlauf ueber `detection.green.warmup_min_change` -- eine AENDERUNG,"
          "\nkeinen absoluten Wert -- und lernt danach selbst. Die Tabelle dient"
          "\ndem Blick auf die Kalibrierung, vor allem der Warnung oben: Eine ROI,"
          "\ndie das AUS-Niveau zu hoch legt, kostet im Anlauf Wuerfe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
