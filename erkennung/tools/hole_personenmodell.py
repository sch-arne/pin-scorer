"""Holt das Personenmodell und legt es unter `models/` ab.

    .venv/Scripts/python.exe tools/hole_personenmodell.py

Ein reiner Download, rund 20 MB, keine weitere Abhaengigkeit. Adresse und
Pruefsumme stehen in `config/default.yaml` unter `detection.person_model`.

WARUM DIE DATEI NICHT IM REPO LIEGT

Nicht aus Lizenzgruenden -- YOLOX steht unter Apache-2.0 und duerfte
mitgeliefert werden. Sondern weil 20 MB Binaerdaten, die sich nie aendern,
nichts in einer Versionsverwaltung verloren haben: Jeder Klon zoege sie mit,
und jede Aenderung daran waere in einem Diff unsichtbar.

WARUM DIE PRUEFSUMME

Ein stillschweigend ausgetauschtes Modell aendert das Verhalten einer
SCHUTZFUNKTION -- Menschen werden nicht mehr geschwaerzt, Phantomwuerfe nicht
mehr aufgehalten -- ohne dass irgendein Test rot wird. Passt die Summe nicht,
bricht dieses Werkzeug ab und laesst nichts liegen.

ANDERE MODELLE. Gemessen wurden vier (Belege in `docs/VIDEO_ANALYSIS.md`):

    YOLOX-Tiny 416   Apache-2.0    28 ms   20,2 MB   <- Voreinstellung
    YOLOX-Nano 416   Apache-2.0    13 ms    3,7 MB   geringerer Abstand
    YOLOX-S    640   Apache-2.0   100 ms   35,9 MB
    YOLOv8n    640   AGPL-3.0      62 ms   12,8 MB   passt nicht zu MIT

Ein anderes Modell nimmt man ueber `--url`, `--sha256` und `--ziel` -- und
traegt dieselben Werte samt `input_size` in die Konfiguration ein, sonst passt
das Ankergitter nicht zum Netz.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

WURZEL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WURZEL / "src"))

from kegel_cv.config import load_config  # noqa: E402

BLOCK = 1 << 16


def hole(url: str, ziel: Path) -> None:
    """Laedt mit Fortschrittsanzeige in eine Datei daneben."""
    vorlaeufig = ziel.with_suffix(ziel.suffix + ".teil")
    anfrage = urllib.request.Request(url, headers={"User-Agent": "Kegel_CV"})
    with urllib.request.urlopen(anfrage, timeout=60) as antwort:
        gesamt = int(antwort.headers.get("Content-Length") or 0)
        geladen = 0
        with vorlaeufig.open("wb") as datei:
            while True:
                stueck = antwort.read(BLOCK)
                if not stueck:
                    break
                datei.write(stueck)
                geladen += len(stueck)
                if gesamt:
                    print(f"\r  {geladen/1e6:5.1f} von {gesamt/1e6:.1f} MB "
                          f"({100*geladen/gesamt:3.0f} %)", end="", flush=True)
    print()
    vorlaeufig.replace(ziel)


def summe(pfad: Path) -> str:
    h = hashlib.sha256()
    with pfad.open("rb") as datei:
        for block in iter(lambda: datei.read(BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    cfg = load_config()
    pm = cfg.detection.person_model
    p = argparse.ArgumentParser(
        description="Holt das Personenmodell nach models/.")
    p.add_argument("--url", default=pm.model_url)
    p.add_argument("--sha256", default=pm.model_sha256)
    p.add_argument("--ziel", default=pm.model_path)
    p.add_argument("--neu", action="store_true",
                   help="auch dann holen, wenn die Datei schon da ist")
    a = p.parse_args()

    ziel = WURZEL / a.ziel
    if ziel.is_file() and not a.neu:
        vorhanden = summe(ziel)
        if not a.sha256 or vorhanden == a.sha256:
            print(f"{ziel} liegt schon da ({ziel.stat().st_size/1e6:.1f} MB), "
                  f"Pruefsumme stimmt.")
            return 0
        print(f"{ziel} liegt da, aber die Pruefsumme passt nicht:\n"
              f"  erwartet {a.sha256}\n  gefunden {vorhanden}\n"
              f"Wird neu geholt.")

    ziel.parent.mkdir(parents=True, exist_ok=True)
    print(f"Hole {a.url}")
    try:
        hole(a.url, ziel)
    except (urllib.error.URLError, OSError) as exc:
        print(f"Download fehlgeschlagen: {exc}")
        return 1

    if a.sha256:
        gefunden = summe(ziel)
        if gefunden != a.sha256:
            ziel.unlink(missing_ok=True)
            print(f"PRUEFSUMME PASST NICHT -- Datei geloescht.\n"
                  f"  erwartet {a.sha256}\n  gefunden {gefunden}")
            return 1

    print(f"fertig: {ziel}  ({ziel.stat().st_size/1e6:.1f} MB)")
    print("Die Anwendung findet es beim naechsten Start von selbst.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
