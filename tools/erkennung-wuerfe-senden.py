# -*- coding: utf-8 -*-
"""Wuerfe als ERKENNER in die Datenbank schicken -- zum Ausprobieren der Oberflaeche.

Ohne Kamera, ohne Bahn-Rechner. Den Weg des Betriebs (Anmeldung, Einfuegen, Aufraeumen)
stellt `erkennung_versand.py` daneben bereit; hier stehen nur die Wuerfe von Hand. Wer
eine ECHTE Aufzeichnung abspielen will, nimmt `erkennung-aufzeichnung-abspielen.py`.

    # erst das Spiel im Browser teilen (ohne Teilen keine Erkennung!), dann:
    python tools/erkennung-wuerfe-senden.py . 1 9 8 7 --pause 2

    # Wurf mit Kegelbild (welche Kegel fielen) und mit Tafelbild:
    python tools/erkennung-wuerfe-senden.py . 1 9:1,2,3,4,5,6,7,8,9 8:bild

    # hinterher die eigenen Zeilen wieder entfernen:
    python tools/erkennung-wuerfe-senden.py . --aufraeumen

Ein Wurf ist `HOLZ`, `HOLZ:kegel,kegel,...` oder `HOLZ:bild`. Die Kegel sind die
GEFALLENEN. Die Bahnnummer ist die, die der Erkenner meldet -- bei einem Erkenner ohne
feste Bahn und ohne `bahn_zuordnung` ist das die Bahnnummer selbst (siehe `bahnFuerLane`
in js/logic/erkennung-zuordnung.js).
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from erkennung_versand import Versand, aufraeumen  # noqa: E402


def zeile_aus(teil: str, versand: Versand, bahn: int) -> dict:
    holz, _, rest = teil.partition(":")
    if not holz.isdigit() or not 0 <= int(holz) <= 9:
        raise SystemExit(f"'{teil}': Holz muss 0 bis 9 sein.")
    if rest == "bild":
        return versand.zeile(bahn, int(holz), mit_bild=True)
    if rest:
        try:
            kegel = [int(x) for x in rest.split(",")]
        except ValueError:
            raise SystemExit(f"'{teil}': Kegel sind Zahlen 1 bis 9, durch Komma getrennt.")
        return versand.zeile(bahn, int(holz), kegel=kegel)
    return versand.zeile(bahn, int(holz))


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wurzel", help="Projektverzeichnis (meist .)")
    p.add_argument("bahn", nargs="?", type=int, help="Bahnnummer, die der Erkenner meldet")
    p.add_argument("wuerfe", nargs="*", help="HOLZ | HOLZ:kegel,kegel,... | HOLZ:bild")
    p.add_argument("--pause", type=float, default=0.0,
                   help="Sekunden zwischen den Wuerfen, zum Zusehen (z. B. 2)")
    p.add_argument("--aufraeumen", action="store_true",
                   help="alle Zeilen dieses Werkzeugs wieder loeschen")
    a = p.parse_args()

    wurzel = Path(a.wurzel).resolve()
    if a.aufraeumen:
        aufraeumen(wurzel)
        return 0

    if a.bahn is None or not a.wuerfe:
        p.error("Ohne --aufraeumen braucht es eine Bahn und mindestens einen Wurf.")

    versand = Versand(wurzel)
    print(f"Als Erkenner angemeldet an {versand.projekt}")
    zeilen = [zeile_aus(t, versand, a.bahn) for t in a.wuerfe]
    for nr, reihe in enumerate(zeilen, 1):
        versand.schicke(reihe)
        text = f"{reihe['pins_count']} Holz"
        if reihe.get("pins"):
            text += ", Kegel " + ",".join(str(k) for k in reihe["pins"])
        if reihe.get("board_jpeg"):
            text += " + Tafelbild"
        print(f"  Wurf {nr}: Bahn {reihe['lane']}, {text}")
        if a.pause and nr < len(zeilen):
            time.sleep(a.pause)
    print(f"{len(zeilen)} Wuerfe auf Bahn {a.bahn} abgeschickt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
