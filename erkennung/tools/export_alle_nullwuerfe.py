"""Findet ALLE Nullwuerfe eines Laufs und exportiert sie als Clips + GIFs.

WOZU: Nach jeder Aenderung an den Nullwurf-Filtern (`discard_zero_*`) soll sich
jeder verbleibende Nullwurf einzeln ansehen lassen -- ohne zu raten, ob er echt
ist (Fehlwurfzaehler-Beleg) oder ein Artefakt (Spielwechsel, Verdeckung,
Aggregationsluecke).

AUFRUF:

    .venv/Scripts/python.exe tools/export_alle_nullwuerfe.py \
        --run debug/<...>/lauf_XXX \
        --source <Stream-URL oder Datei> \
        --calibration data/calibrations/1Spieltag_enge_lampen.json \
        --out debug/nullwuerfe_belege

Legt an:
    <out>/nullwuerfe.csv         Bahn;Frame;Was;Soll;Ist (fuer --aus-csv)
    <out>/clips/*.mp4            Videoclips (export_problem_clips.py)
    <out>/clips/gif/*.gif        GIFs (clips_zu_gif.py)
"""

from __future__ import annotations

import argparse
import csv
import io
import subprocess
import sys
from pathlib import Path


def nullwuerfe_lesen(run: Path) -> list[dict]:
    pfad = run / "wuerfe.csv"
    zeilen = []
    with io.open(pfad, encoding="utf-8-sig", newline="") as datei:
        for z in csv.DictReader(datei, delimiter=";"):
            if int(z["Kegel"]) == 0:
                zeilen.append(z)
    return zeilen


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--source", required=True)
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--out", type=Path, default=Path("debug/nullwuerfe_belege"))
    p.add_argument("--vor", type=float, default=4.0)
    p.add_argument("--nach", type=float, default=4.0)
    a = p.parse_args()

    nullwuerfe = nullwuerfe_lesen(a.run)
    if not nullwuerfe:
        print(f"Keine Nullwuerfe in {a.run}/wuerfe.csv -- nichts zu tun.")
        return 0

    a.out.mkdir(parents=True, exist_ok=True)
    fallliste = a.out / "nullwuerfe.csv"
    with io.open(fallliste, "w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.DictWriter(
            datei, ["Bahn", "Frame", "Was", "Soll", "Ist"], delimiter=";")
        schreiber.writeheader()
        for w in nullwuerfe:
            schreiber.writerow({
                "Bahn": w["Bahn"], "Frame": w["Frame"],
                "Was": f"Nullwurf, Wurfnr {w['Wurfnummer']}, Spiel {w['Spiel']}",
                "Soll": "?",
                "Ist": (f"Ziffer={w['Ziffer'] or '-'}  "
                       f"Herkunft={w['Herkunft']}  Status={w['Status']}"),
            })
    print(f"{len(nullwuerfe)} Nullwuerfe -> {fallliste}")
    for w in nullwuerfe:
        print(f"  Bahn {w['Bahn']} F{w['Frame']:>7} Spiel {w['Spiel']} "
              f"Wurf {w['Wurfnummer']:>2}  Ziffer={w['Ziffer'] or '-':<3} "
              f"Herkunft={w['Herkunft']}")

    clips = a.out / "clips"
    print(f"\n=== Clips exportieren ({len(nullwuerfe)} Faelle) ===")
    subprocess.run([
        sys.executable, "tools/export_problem_clips.py",
        "--source", a.source, "--calibration", str(a.calibration),
        "--aus-csv", str(fallliste),
        "--vor", str(a.vor), "--nach", str(a.nach),
        "--out", str(clips),
    ], check=True)

    print(f"\n=== GIFs erzeugen ===")
    subprocess.run([
        sys.executable, "tools/clips_zu_gif.py", str(clips),
        "--breite", "620", "--jeder", "3", "--fps", "8", "--farben", "64",
        "--out", str(clips / "gif"),
    ], check=True)

    print(f"\nFertig. GIFs liegen in {clips / 'gif'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
