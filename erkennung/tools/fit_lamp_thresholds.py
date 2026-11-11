"""Bestimmt den Schwellensatz der Kegellampen aus gemessenen Ausschnitten.

WOZU: Ein anderer ROI-Zuschnitt verschiebt ALLE Niveaus. Die vier Werte
`brightness_on_threshold`, `brightness_off_threshold`, `baseline_on_fraction`
und `baseline_off_fraction` gelten dann nicht mehr, und sie zu schaetzen waere
gegen Prinzip P7. Dieses Werkzeug rechnet sie aus den Messungen.

WIE DER DETEKTOR RECHNET (`WarmthLampDetector._thresholds`):

    niveau      = 15. Perzentil der letzten AUS-Messungen dieser Lampe
    niveau      = min(max(niveau, off_threshold - off_margin),
                      off_threshold - off_margin + max_drift)
    spielraum   = 255 - niveau
    AN-Schwelle = niveau + spielraum * on_fraction
    AUS-Schwelle= niveau + spielraum * off_fraction

Die Anteile sind also relativ zum Abstand zwischen Ruheniveau und Saettigung.
Das ist bewusst so: Eine leuchtende Lampe ist im Bild gesaettigt, ihr Wert
wandert nicht mit dem Ruheniveau mit. Ein fester Abstand haette bei hohem
Niveau eine unerreichbare AN-Schwelle ergeben (siehe Kommentar dort).

WAS HIER GESUCHT WIRD: die Anteile, bei denen ueber ALLE Bahnen und ALLE
Messstrecken

    die AUS-Schwelle oberhalb des 95. Perzentils der AUS-Messungen liegt
    (sonst rutschen dunkle Lampen in die Totzone), und
    die AN-Schwelle unterhalb des 5. Perzentils der AN-Messungen
    (sonst rutschen leuchtende Lampen in die Totzone).

Beide Bedingungen zugleich sind nur erfuellbar, wenn die Wolken sich nicht
beruehren. Wo sie es tun, nennt das Werkzeug den Konflikt, statt ihn durch
eine Mittelung zu verstecken.

AUFRUF:

    .venv/Scripts/python.exe tools/fit_lamp_thresholds.py \
        debug/roi_proben/neu_frueh.pkl debug/roi_proben/neu_spaet.pkl \
        --core-percentile 0
"""

from __future__ import annotations

import argparse
import pickle
import statistics as st
from collections import defaultdict
from pathlib import Path

import numpy as np

SAETTIGUNG = 255.0

# Einordnung AN/AUS anhand des ROHEN Messwerts, unabhaengig von jeder
# Schwelle -- sonst benotete sich der Vorschlag selbst. Die Grenzen sind weit
# gesetzt; was dazwischen liegt, bleibt aussen vor.
AN_AB, AUS_BIS = 235.0, 210.0


def messwert(patch: np.ndarray, core_percentile: float) -> float:
    value = patch.max(axis=2).astype(np.float32)
    if core_percentile <= 0.0:
        return float(value.mean())
    kern = value >= np.percentile(value, core_percentile)
    if not kern.any():
        kern = np.ones_like(value, dtype=bool)
    return float(value[kern].mean())


def perzentil(werte: list[float], q: float) -> float:
    werte = sorted(werte)
    return werte[min(len(werte) - 1, int(len(werte) * q / 100))]


def anteil_fuer(schwelle: float, niveau: float) -> float:
    """Welcher Anteil ergaebe diese Schwelle bei diesem Niveau?"""
    spielraum = max(1.0, SAETTIGUNG - niveau)
    return (schwelle - niveau) / spielraum


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("dateien", nargs="+", type=Path)
    parser.add_argument("--core-percentile", type=float, default=0.0)
    parser.add_argument("--baseline-percentile", type=float, default=15.0,
                        help="wie `lamp_detection.pin.baseline_percentile`")
    args = parser.parse_args()

    # --- messen ------------------------------------------------------------
    je_fall = defaultdict(lambda: defaultdict(list))   # (Datei, Bahn) -> Zustand
    for pfad in args.dateien:
        if not pfad.is_file():
            print(f"fehlt: {pfad}")
            return 1
        with pfad.open("rb") as datei:
            for _, bahn, _, patch in pickle.load(datei):
                wert = messwert(patch, args.core_percentile)
                if wert >= AN_AB:
                    je_fall[(pfad.name, bahn)]["AN"].append(wert)
                elif wert <= AUS_BIS:
                    je_fall[(pfad.name, bahn)]["AUS"].append(wert)

    if not je_fall:
        print("Keine verwertbaren Messungen.")
        return 1

    # --- je Fall: Niveau, Wolkenraender, noetige Anteile -------------------
    print(f"Kernfilter: core_percentile {args.core_percentile:.0f}\n")
    print(f"{'Strecke':>16} {'Bahn':>4} {'Niveau':>7} {'AUS p95':>8} "
          f"{'AN p5':>7} {'Luecke':>7} {'off_frac >':>11} {'on_frac <':>10}")
    noetig_off, erlaubt_on = [], []
    for (name, bahn) in sorted(je_fall):
        aus = je_fall[(name, bahn)]["AUS"]
        an = je_fall[(name, bahn)]["AN"]
        if len(aus) < 20 or len(an) < 20:
            continue
        niveau = perzentil(aus, args.baseline_percentile)
        aus_p95, an_p5 = perzentil(aus, 95), perzentil(an, 5)
        f_off = anteil_fuer(aus_p95, niveau)
        f_on = anteil_fuer(an_p5, niveau)
        noetig_off.append((f_off, name, bahn))
        erlaubt_on.append((f_on, name, bahn))
        print(f"{name[:16]:>16} {bahn:>4} {niveau:>7.1f} {aus_p95:>8.1f} "
              f"{an_p5:>7.1f} {an_p5 - aus_p95:>7.1f} "
              f"{f_off:>11.3f} {f_on:>10.3f}")

    if not noetig_off:
        print("\nZu wenige Messungen je Bahn.")
        return 1

    schlimmster_off = max(noetig_off)
    knappstes_on = min(erlaubt_on)
    print(f"\nGroesster noetiger off_fraction: {schlimmster_off[0]:.3f} "
          f"({schlimmster_off[1][:20]}, Bahn {schlimmster_off[2]})")
    print(f"Kleinster erlaubter on_fraction: {knappstes_on[0]:.3f} "
          f"({knappstes_on[1][:20]}, Bahn {knappstes_on[2]})")

    if schlimmster_off[0] >= knappstes_on[0]:
        print("\nKONFLIKT: Die AUS-Wolke der einen Bahn reicht ueber die "
              "AN-Wolke einer anderen. Kein Anteilspaar erfuellt beide "
              "Bedingungen -- der Zuschnitt taugt so nicht.")
        return 1

    # Mittig zwischen die Anforderungen legen, damit beide Seiten gleich viel
    # Reserve bekommen. Eine Seite zu bevorzugen waere ohne Messgrund.
    luft = knappstes_on[0] - schlimmster_off[0]
    off_neu = schlimmster_off[0] + luft * 0.25
    on_neu = knappstes_on[0] - luft * 0.25

    print(f"\n=== Vorschlag ===")
    print(f"  baseline_off_fraction: {off_neu:.2f}")
    print(f"  baseline_on_fraction:  {on_neu:.2f}")
    print(f"  (Luft dazwischen: {luft:.3f} Anteilspunkte)")

    # --- absolute Startwerte ----------------------------------------------
    # Sie gelten, solange das Gedaechtnis einer Lampe zu duenn ist. Sinnvoll
    # ist, was die Anteile beim TYPISCHEN Niveau ergeben.
    niveaus = [perzentil(je_fall[k]["AUS"], args.baseline_percentile)
               for k in je_fall if len(je_fall[k]["AUS"]) >= 20]
    niveau_typisch = st.median(niveaus)
    spielraum = SAETTIGUNG - niveau_typisch
    print(f"\n  Typisches Ruheniveau: {niveau_typisch:.1f}")
    print(f"  brightness_off_threshold: {niveau_typisch + spielraum * off_neu:.0f}")
    print(f"  brightness_on_threshold:  {niveau_typisch + spielraum * on_neu:.0f}")

    hoechstes, niedrigstes = max(niveaus), min(niveaus)
    print(f"\n  Niveaus reichen von {niedrigstes:.1f} bis {hoechstes:.1f}.")
    print(f"  Die Deckelung (`off_threshold - off_margin` bis "
          f"`+ max_drift`) muss diesen Bereich umfassen, sonst wird das")
    print(f"  gemessene Niveau beschnitten und die Schwellen verrutschen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
