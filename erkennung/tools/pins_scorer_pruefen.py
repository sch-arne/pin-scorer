"""Prueft die Anbindung an den Pin Scorer -- ohne Video, ohne Oberflaeche.

WOZU: Am Spieltag soll nicht die Erkennung die erste Stelle sein, an der
auffaellt, dass ein Passwort falsch ist oder die Tabelle fehlt. Dieses Skript
geht denselben Weg wie der echte Versand (dieselbe `.env`, dieselbe Anmeldung,
dieselbe Tabelle) und sagt im Klartext, woran es haengt.

    python tools/pins_scorer_pruefen.py           # nur anmelden
    python tools/pins_scorer_pruefen.py --wurf    # und einen Probewurf einfuegen

Der Probewurf steht auf Bahn 0 und traegt `video_id = 'pruefung'` -- eine Bahn,
die es nicht gibt, damit die App ihn nie einem Spiel zuordnen kann. Wieder weg
ist er mit:

    delete from erkannter_wurf where video_id = 'pruefung';
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "src"))

from kegel_cv.config.loader import load_env_file          # noqa: E402
from kegel_cv.sinks import pins_scorer as ps              # noqa: E402
from kegel_cv.sinks.supabase import SupabaseError         # noqa: E402

log = logging.getLogger("pruefung")


def main() -> int:
    zerleger = argparse.ArgumentParser(description=__doc__)
    zerleger.add_argument("--wurf", action="store_true",
                          help="zusaetzlich einen Probewurf einfuegen")
    args = zerleger.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    uebernommen = load_env_file(WURZEL / ".env")
    print(f"{uebernommen} Werte aus .env uebernommen")

    if not ps.eingeschaltet():
        print(f"FEHLT: {ps.ENV_EIN} steht nicht auf 1 -- es wuerde nichts "
              f"gesendet. Vorlage: .env.example")
        return 1

    sink = ps.aus_umgebung(video_id="pruefung")
    if sink is None:
        print("NICHT EINGERICHTET -- der Grund steht in der Meldung darueber.")
        return 1

    print(f"Ziel:     {sink.endpoint}")
    print(f"Erkenner: {sink.erkenner_id}")

    try:
        token = sink.anmeldung.token()
    except SupabaseError as exc:
        print(f"ANMELDUNG FEHLGESCHLAGEN: {exc}")
        return 1
    print(f"Anmeldung ok (Token {token[:12]}…)")

    if not args.wurf:
        print("Kein Probewurf gesendet (--wurf fuegt einen ein).")
        return 0

    # Bewusst eine flache Zeile und nicht `send(ThrowResult)`: Dieses Skript
    # soll den VERSANDWEG pruefen, nicht die Erkennung -- also ohne Frames,
    # ohne Kalibrierung, ohne Tafelbild.
    try:
        sink.send_rows([{
            "lane": 0,
            "pins_count": 0,
            "pins": [],
            "video_id": "pruefung",
        }])
    except SupabaseError as exc:
        print(f"EINFUEGEN ABGELEHNT: {exc}")
        print("Haeufige Gruende: schema.sql/policies.sql noch nicht eingespielt, "
              "erkenner-Zeile fehlt oder steht auf aktiv = false, oder "
              f"{ps.ENV_ERKENNER} gehoert nicht zu diesem Login.")
        return 1

    print("Probewurf eingefuegt. Wieder entfernen mit:")
    print("  delete from erkannter_wurf where video_id = 'pruefung';")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
