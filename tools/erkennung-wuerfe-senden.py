# -*- coding: utf-8 -*-
"""Wuerfe als ERKENNER in die Datenbank schicken -- zum Ausprobieren der Oberflaeche.

Ohne Kamera, ohne Bahn-Rechner: Dieses Werkzeug nimmt genau den Weg des Betriebs. Es
meldet sich per GoTrue mit dem Erkenner-Login aus `erkennung/.env` an und fuegt per
PostgREST in `erkannter_wurf` ein -- also mit denselben Rechten wie der Rechner an der
Bahn. Damit prueft jeder Lauf die Policies mit und nicht nur die App.

    # erst das Spiel im Browser teilen (ohne Teilen keine Erkennung!), dann:
    python tools/erkennung-wuerfe-senden.py . 1 9 8 7 --pause 2

    # Wurf mit Kegelbild (welche Kegel fielen) und mit Tafelbild:
    python tools/erkennung-wuerfe-senden.py . 1 9:1,2,3,4,5,6,7,8,9 8:bild

    # hinterher die eigenen Zeilen wieder entfernen:
    python tools/erkennung-wuerfe-senden.py . --aufraeumen

Ein Wurf ist `HOLZ`, `HOLZ:kegel,kegel,...` oder `HOLZ:bild`. Die Bahnnummer ist die, die
der Erkenner meldet -- bei einem Erkenner ohne feste Bahn und ohne `bahn_zuordnung` ist
das die Bahnnummer selbst (siehe `bahnFuerLane` in js/logic/erkennung-zuordnung.js).

WARUM EIN EIGENES WERKZEUG UND KEIN SQL: Eine Zeile von Hand im SQL-Editor umgeht die
Rechte (dort sitzt man als Eigentuemer) und damit genau den Teil, der am Spieltag bricht.
Hier faellt ein Rechtefehler als HTTP 401/403 auf, so wie er auch an der Bahn auffiele.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.request

# Ein winziges, gueltiges 1x1-JPEG. Es geht nur um den WEG des Bildes (Base64 OHNE
# data:-Praefix, siehe encode_board in erkennung/), nicht um seinen Inhalt.
MINI_JPEG = (
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
    "HBwcJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPDc0NP/bAEMBCQkJDAsMGA0NGDIhHCEyMjIyMjIy"
    "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEB"
    "AxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAA"
    "AAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwA/8A=="
)

# Daran erkennt das Werkzeug spaeter seine eigenen Zeilen wieder. Nicht aendern, sonst
# findet --aufraeumen die Wuerfe aelterer Laeufe nicht mehr.
MARKE = "ui-probe"


def lies_env(wurzel: Path) -> dict:
    pfad = wurzel / "erkennung" / ".env"
    if not pfad.is_file():
        raise SystemExit(f"{pfad} fehlt -- dort steht der Erkenner-Login.")
    return dict(z.split("=", 1)
                for z in pfad.read_text(encoding="utf-8").splitlines()
                if "=" in z and not z.lstrip().startswith("#"))


def lies_anon(wurzel: Path) -> str:
    """Den oeffentlichen Schluessel aus der Konfiguration der App ziehen.

    Bewusst aus derselben Datei wie die App: Wer lokal gegen die Test-Datenbank
    arbeitet, soll nicht versehentlich Wuerfe in die Produktion schicken.
    """
    for name in ("config.local.js", "config.js"):
        pfad = wurzel / "js" / "backend" / name
        if not pfad.is_file():
            continue
        treffer = re.search(r"['\"`](eyJ[\w.-]+|sb_publishable_[\w-]+)['\"`]",
                            pfad.read_text(encoding="utf-8"))
        if treffer:
            return treffer.group(1)
    raise SystemExit("Keinen anon-Key in js/backend/config*.js gefunden.")


def anmelden(projekt: str, anon: str, email: str, passwort: str) -> str:
    anfrage = urllib.request.Request(
        f"{projekt}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": email, "password": passwort}).encode(),
        method="POST", headers={"apikey": anon, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(anfrage, timeout=20) as a:
            return json.loads(a.read())["access_token"]
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")[:300]
        raise SystemExit(f"Anmeldung als Erkenner fehlgeschlagen (HTTP {exc.code}): {text}")


def zeile_aus(teil: str, erkenner: str, bahn: int) -> dict:
    holz, _, rest = teil.partition(":")
    if not holz.isdigit() or not 0 <= int(holz) <= 9:
        raise SystemExit(f"'{teil}': Holz muss 0 bis 9 sein.")
    reihe = {"erkenner_id": erkenner, "lane": bahn, "pins_count": int(holz),
             "video_id": MARKE}
    if rest == "bild":
        reihe["board_jpeg"] = MINI_JPEG
        reihe["board_before_jpeg"] = MINI_JPEG
        reihe["displayed_pin_count"] = int(holz)
        reihe["displayed_throw_number"] = 99
    elif rest:
        try:
            reihe["pins"] = sorted({int(x) for x in rest.split(",")})
        except ValueError:
            raise SystemExit(f"'{teil}': Kegel sind Zahlen 1 bis 9, durch Komma getrennt.")
    return reihe


def senden(projekt: str, anon: str, token: str, zeilen: list, pause: float) -> None:
    """Eine Zeile je Anfrage.

    NICHT als Stapel: PostgREST verlangt in einem Stapel bei JEDER Zeile dieselben
    Schluessel. Ein Wurf mit Kegelbild neben einem ohne ergibt dann HTTP 400 -- und
    einzeln ist es ohnehin naeher am Betrieb, wo jeder Wurf fuer sich ankommt.
    """
    for nr, reihe in enumerate(zeilen, 1):
        anfrage = urllib.request.Request(
            f"{projekt}/rest/v1/erkannter_wurf", data=json.dumps(reihe).encode(),
            method="POST",
            headers={"apikey": anon, "Authorization": f"Bearer {token}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"})
        try:
            with urllib.request.urlopen(anfrage, timeout=20):
                pass
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")[:400]
            raise SystemExit(f"Wurf {nr} abgelehnt (HTTP {exc.code}): {text}")
        beschreibung = f"{reihe['pins_count']} Holz"
        if reihe.get("pins"):
            beschreibung += ", Kegel " + ",".join(str(k) for k in reihe["pins"])
        if reihe.get("board_jpeg"):
            beschreibung += " + Tafelbild"
        print(f"  Wurf {nr}: Bahn {reihe['lane']}, {beschreibung}")
        if pause and nr < len(zeilen):
            time.sleep(pause)


def aufraeumen(wurzel: Path) -> None:
    """Die eigenen Testzeilen loeschen -- ueber die Datenbank, NICHT als Erkenner.

    Absicht der Policies: `erkannter_wurf_delete` verlangt den Verwalter des Erkenners.
    Ein Geraet an der Bahn soll Wuerfe zuordnen oder als verworfen markieren, aber keine
    Belege wegraeumen -- sonst koennte ein fehlerhafter Rechner das Wurfprotokoll eines
    Spiels still loeschen. Der Erkenner-Login darf hier also richtigerweise nicht.

    ACHTUNG, falls jemand den Weg zurueckbaut: Ein DELETE, das die Rechte wegfiltern,
    kommt als HTTP 200 mit LEERER Liste zurueck -- erfolgreich aussehend, aber wirkungslos.
    Deshalb wird hier nicht die Antwort geglaubt, sondern nachgezaehlt.
    """
    try:
        import psycopg2
    except ImportError:
        raise SystemExit("Zum Aufraeumen braucht es psycopg2:  pip install psycopg2-binary")

    pfad = wurzel / "supabase" / ".db-test.env"
    if not pfad.is_file():
        raise SystemExit(f"{pfad} fehlt -- dort gehoert PGURL=postgresql://... hinein.")
    url = next((z.split("=", 1)[1].strip()
                for z in pfad.read_text(encoding="utf-8").splitlines()
                if z.startswith("PGURL=")), None)
    if not url:
        raise SystemExit(f"Kein PGURL in {pfad}")

    verbindung = psycopg2.connect(url, sslmode="require", connect_timeout=15)
    with verbindung, verbindung.cursor() as cur:
        cur.execute("delete from erkannter_wurf where video_id = %s", [MARKE])
        weg = cur.rowcount
        cur.execute("select count(*) from erkannter_wurf where video_id = %s", [MARKE])
        rest = cur.fetchone()[0]
    verbindung.close()
    print(f"{weg} Testzeilen entfernt, {rest} uebrig.")
    print("Hinweis: Was die App schon uebernommen hat, steht trotzdem noch im Satz -- dort"
          " raeumt 'erkannte Wuerfe dieses Satzes verwerfen' in der Bahneinstellung auf.")


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

    env = lies_env(wurzel)
    projekt = env["PINS_SCORER_URL"].strip()
    anon = lies_anon(wurzel)
    token = anmelden(projekt, anon, env["PINS_SCORER_EMAIL"].strip(),
                     env["PINS_SCORER_PASSWORT"].strip())
    print(f"Als Erkenner angemeldet an {projekt}")

    if a.bahn is None or not a.wuerfe:
        p.error("Ohne --aufraeumen braucht es eine Bahn und mindestens einen Wurf.")
    zeilen = [zeile_aus(t, env["PINS_SCORER_ERKENNER"].strip(), a.bahn) for t in a.wuerfe]
    senden(projekt, anon, token, zeilen, a.pause)
    print(f"{len(zeilen)} Wuerfe auf Bahn {a.bahn} abgeschickt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
