"""Laedt die Wurfbelege eines Laufs nach Supabase Storage.

WOZU: `debug.throw_sheet` legt je Wurf ein Belegbild ab. Damit es von aussen
erreichbar ist -- etwa aus einer Auswertung heraus -- muss es in den Storage.

WARUM NACH DEM LAUF UND NICHT WAEHREND: Ein Upload haengt am Netz. Waehrend der
Analyse wuerde jede Stoerung sie ausbremsen oder anhalten. Die Belege liegen
zuerst auf der Platte; sie gehen nicht verloren, wenn die Uebertragung
scheitert, und ein zweiter Aufruf holt das Fehlende nach.

WAS IN DIE DATENBANK GEHOERT: nur der Pfad, nicht das Bild. Warum, steht in
`src/kegel_cv/sinks/storage.py`.

VORAUSSETZUNGEN:

    SUPABASE_URL   und   SUPABASE_KEY   als Umgebungsvariablen
    ein Bucket, der bereits existiert (dieses Werkzeug legt keinen an)

AUFRUF -- erst schauen, dann senden:

    .venv/Scripts/python.exe tools/upload_throw_sheets.py <laufordner> \
        --bucket wurfbelege --probelauf

    .venv/Scripts/python.exe tools/upload_throw_sheets.py <laufordner> \
        --bucket wurfbelege

`--probelauf` zeigt, was hochgeladen wuerde, und ruehrt nichts an. Das ist die
Vorgabe fuer den ersten Versuch: Ein Upload ist von aussen sichtbar und laesst
sich nicht zurueckholen.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.sinks.storage import StorageError, SupabaseStorage  # noqa: E402


def belege_finden(lauf: Path) -> list[Path]:
    """Alle Belegbilder eines Laufordners, in stabiler Reihenfolge."""
    return sorted(lauf.glob("bahn*/wurfbelege/*.jpg"))


def ziel_pfad(lauf: Path, beleg: Path, praefix: str) -> str:
    """Pfad im Bucket: <praefix>/<lauf>/<bahn>/<datei>.

    Der Laufordner bleibt im Pfad, sonst ueberschreiben zwei Auswertungen
    desselben Videos ihre Belege gegenseitig -- und man koennte sie nicht mehr
    vergleichen.
    """
    bahn = beleg.parent.parent.name
    teile = [t for t in (praefix.strip("/"), lauf.name, bahn, beleg.name) if t]
    return "/".join(teile)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("lauf", type=Path, help="Ordner eines Analysedurchlaufs")
    p.add_argument("--bucket", required=True)
    p.add_argument("--praefix", default="",
                   help="Unterordner im Bucket, z.B. ein Spieltagsdatum")
    p.add_argument("--probelauf", action="store_true",
                   help="nur zeigen, was geschehen wuerde")
    p.add_argument("--ueberschreiben", action="store_true",
                   help="vorhandene Dateien ersetzen statt sie zu ueberspringen")
    p.add_argument("--grenze", type=int, default=0,
                   help="hoechstens so viele Dateien senden (0 = alle)")
    a = p.parse_args()

    if not a.lauf.is_dir():
        print(f"Kein Ordner: {a.lauf}")
        return 1

    belege = belege_finden(a.lauf)
    if not belege:
        print(f"Keine Belege in {a.lauf}. Stand `debug.throw_sheet` auf true?")
        return 1

    gesamt_mb = sum(b.stat().st_size for b in belege) / 1e6
    print(f"{len(belege)} Belege, zusammen {gesamt_mb:.1f} MB")
    if a.grenze:
        belege = belege[:a.grenze]
        print(f"  auf {len(belege)} begrenzt (--grenze)")

    if a.probelauf:
        print("\nPROBELAUF -- es wird nichts gesendet. Die ersten Ziele:")
        for beleg in belege[:5]:
            print(f"  {beleg.name}  ->  {ziel_pfad(a.lauf, beleg, a.praefix)}")
        if len(belege) > 5:
            print(f"  ... und {len(belege) - 5} weitere")
        return 0

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("SUPABASE_URL und SUPABASE_KEY muessen gesetzt sein. Der "
              "Schluessel gehoert in die Umgebung, nicht in eine Datei.")
        return 1

    storage = SupabaseStorage(url, a.bucket, key)
    gesendet = fehler = 0
    for i, beleg in enumerate(belege, 1):
        pfad = ziel_pfad(a.lauf, beleg, a.praefix)
        try:
            storage.upload(beleg, pfad, ueberschreiben=a.ueberschreiben)
            gesendet += 1
        except StorageError as exc:
            # Ein einzelner Fehlschlag beendet den Lauf nicht -- sonst muesste
            # man nach jeder Stoerung von vorn beginnen.
            fehler += 1
            print(f"  FEHLER bei {beleg.name}: {exc}")
        if i % 50 == 0:
            print(f"  {i} von {len(belege)} ...", flush=True)

    print(f"\nFertig: {gesendet} gesendet, {fehler} fehlgeschlagen")
    return 1 if fehler and not gesendet else 0


if __name__ == "__main__":
    raise SystemExit(main())
