"""Wertet das Ergebnis von `run_full_analysis.py` aus.

Getrennt vom Lauf selbst, damit die Auswertung wiederholt und veraendert werden
kann, ohne die 52 Minuten erneut zu rechnen.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

QUELLE = Path("debug/vollauswertung.json")


def main() -> int:
    pfad = Path(sys.argv[1]) if len(sys.argv) > 1 else QUELLE
    if not pfad.exists():
        print(f"Keine Auswertung unter {pfad}")
        return 1
    daten = json.loads(pfad.read_text(encoding="utf-8"))
    wuerfe = daten["wuerfe"]
    zyklen = daten["gruenzyklen"]

    print("=" * 62)
    print(f"VOLLAUSWERTUNG  {daten['video']}")
    print("=" * 62)
    print(f"{daten['frames']} Frames in {daten['dauer_s'] / 60:.1f} min "
          f"({daten['ms_pro_frame']} ms/Frame)\n")

    gz = sum(zyklen.values())
    print(f"Gruenzyklen {gz} | gemeldete Wuerfe {len(wuerfe)} "
          f"-> Erfassung {100 * len(wuerfe) / max(1, gz):.1f} %")
    print(f"Status: {dict(Counter(w['status'] for w in wuerfe))}\n")

    print("Je Bahn:")
    print(f"   {'Bahn':<6}{'Zyklen':>8}{'Wuerfe':>8}{'verloren':>10}"
          f"{'Ziffer':>9}{'stimmig':>9}")
    for bahn in sorted({w["lane"] for w in wuerfe}):
        r = [w for w in wuerfe if w["lane"] == bahn]
        z = zyklen.get(str(bahn), zyklen.get(bahn, 0))
        mit = [w for w in r if w["displayed_pin_count"] is not None]
        ok = [w for w in mit if w["displayed_pin_count"] == w["pins_count"]]
        quote = f"{100 * len(ok) / len(mit):.0f} %" if mit else "-"
        print(f"   {bahn:<6}{z:>8}{len(r):>8}{z - len(r):>10}"
              f"{len(mit):>9}{quote:>9}")

    # --- Gegenprobe 1: Kegelziffer ---
    mit = [w for w in wuerfe if w["displayed_pin_count"] is not None]
    abw = [w for w in mit if w["displayed_pin_count"] != w["pins_count"]]
    print(f"\nGEGENPROBE Kegelziffer: lesbar {len(mit)}/{len(wuerfe)}, "
          f"stimmig {len(mit) - len(abw)} "
          f"-> {100 * (len(mit) - len(abw)) / max(1, len(mit)):.1f} %")

    # --- Ruecksetzungen der Anzeige finden ---
    # Vom Nutzer angekuendigt: Die Ergebniszeile wird nach einer bestimmten
    # Wurfzahl zurueckgesetzt -- ein Zeichen, dass ein Spiel zu Ende ist.
    print("\nRUECKSETZUNGEN der angezeigten Summe:")
    gefunden = 0
    for bahn in sorted({w["lane"] for w in wuerfe}):
        r = [w for w in wuerfe if w["lane"] == bahn]
        vor = None
        for w in r:
            s = (w.get("evidence") or {}).get("raw", {}).get("displayed_total")
            if s is not None and vor is not None and s < vor - 20:
                print(f"   Bahn {bahn}: Summe {vor} -> {s} "
                      f"bei Wurf {w['throw_number']} (Frame {w['source_frame']})")
                gefunden += 1
            if s is not None:
                vor = s
    if not gefunden:
        print("   keine gefunden")

    # --- Gegenprobe 2: Summenkette ---
    treffer = fehl = 0
    for bahn in sorted({w["lane"] for w in wuerfe}):
        vor = None
        for w in [x for x in wuerfe if x["lane"] == bahn]:
            s = (w.get("evidence") or {}).get("raw", {}).get("displayed_total")
            if s is None:
                vor = None
                continue
            if vor is not None:
                if s - vor == w["pins_count"]:
                    treffer += 1
                elif s >= vor:          # Ruecksetzungen nicht als Fehler zaehlen
                    fehl += 1
            vor = s
    print(f"\nGEGENPROBE Summenkette: pruefbar {treffer + fehl}, "
          f"stimmig {treffer} -> {100 * treffer / max(1, treffer + fehl):.1f} %")

    # --- Spiele: der Endstand vor jeder Ruecksetzung ist das Spielergebnis ---
    print("")
    print("SPIELE (je 30 Wuerfe, Endstand aus der internen Zaehlung):")
    for bahn in sorted({w["lane"] for w in wuerfe}):
        r = [w for w in wuerfe if w["lane"] == bahn]
        spiele: list[tuple[int, int]] = []
        vor_total, vor_nummer = 0, 0
        for w in r:
            if w["throw_number"] <= vor_nummer:      # Ruecksetzung
                spiele.append((vor_nummer, vor_total))
            vor_nummer, vor_total = w["throw_number"], w["running_total"]
        spiele.append((vor_nummer, vor_total))
        text = "  ".join(f"{t} ({n} W.)" for n, t in spiele)
        gesamt = sum(t for _, t in spiele)
        print(f"   Bahn {bahn}: {text}   | zusammen {gesamt} Kegel")

    raeum = [w for w in wuerfe if (w.get("evidence") or {}).get("raw", {}).get("clearing")]
    print(f"\nRaeumwuerfe erkannt: {len(raeum)}")
    print(f"Kegel gesamt: {sum(w['pins_count'] for w in wuerfe)}")
    return 0


def vergleich(a: Path, b: Path) -> int:
    """Stellt zwei Auswertungen gegenueber -- fuer A/B-Vergleiche."""
    da = json.loads(a.read_text(encoding="utf-8"))
    db = json.loads(b.read_text(encoding="utf-8"))

    def kennzahlen(d: dict) -> dict:
        w = d["wuerfe"]
        mit = [x for x in w if x["displayed_pin_count"] is not None]
        ok = [x for x in mit if x["displayed_pin_count"] == x["pins_count"]]
        treffer = fehl = 0
        for bahn in sorted({x["lane"] for x in w}):
            vor = None
            for x in [y for y in w if y["lane"] == bahn]:
                s = (x.get("evidence") or {}).get("raw", {}).get("displayed_total")
                if s is None:
                    vor = None
                    continue
                if vor is not None:
                    if s - vor == x["pins_count"]:
                        treffer += 1
                    elif s >= vor:
                        fehl += 1
                vor = s
        return {
            "Wuerfe": len(w),
            "VALID": sum(1 for x in w if x["status"] == "VALID"),
            "ERROR": sum(1 for x in w if x["status"] == "ERROR"),
            "Ziffer lesbar": len(mit),
            "Ziffer stimmig %": round(100 * len(ok) / max(1, len(mit)), 1),
            "Summenkette %": round(100 * treffer / max(1, treffer + fehl), 1),
            "Kegel gesamt": sum(x["pins_count"] for x in w),
        }

    ka, kb = kennzahlen(da), kennzahlen(db)
    print(f"{'Kennzahl':<20}{a.stem[:16]:>18}{b.stem[:16]:>18}")
    for schluessel in ka:
        print(f"{schluessel:<20}{ka[schluessel]:>18}{kb[schluessel]:>18}")

    print("")
    print("Je Bahn -- Anteil stimmiger Ziffern:")
    for bahn in sorted({x["lane"] for x in da["wuerfe"]}):
        zeile = []
        for d in (da, db):
            r = [x for x in d["wuerfe"] if x["lane"] == bahn
                 and x["displayed_pin_count"] is not None]
            ok = [x for x in r if x["displayed_pin_count"] == x["pins_count"]]
            zeile.append(f"{len(ok)}/{len(r)}" if r else "-")
        print(f"   Bahn {bahn}: {zeile[0]:>10}  ->  {zeile[1]:>10}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and Path(sys.argv[1]).exists() and Path(sys.argv[2]).exists():
        raise SystemExit(vergleich(Path(sys.argv[1]), Path(sys.argv[2])))
    raise SystemExit(main())
