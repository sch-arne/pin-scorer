# -*- coding: utf-8 -*-
"""Gemeinsamer Unterbau: als ERKENNER anmelden und Wuerfe einfuegen.

Benutzt von `erkennung-wuerfe-senden.py` (Wuerfe von Hand) und
`erkennung-aufzeichnung-abspielen.py` (eine echte Aufzeichnung). Der Weg ist in beiden
Faellen der des Betriebs: GoTrue-Anmeldung mit dem Login aus `erkennung/.env`, Einfuegen
per PostgREST. Damit prueft jeder Lauf die Rechte mit und nicht nur die App -- im
SQL-Editor saesse man als Eigentuemer und merkte einen Rechtefehler erst an der Bahn.

Der Dateiname hat ABSICHTLICH einen Unterstrich statt eines Bindestrichs: Nur so laesst
er sich importieren. Die beiden Werkzeuge daneben werden aufgerufen, nicht importiert,
und heissen deshalb weiter mit Bindestrich wie der Rest von tools/.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
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

# Daran erkennen die Werkzeuge ihre eigenen Zeilen wieder. Nicht aendern, sonst findet
# das Aufraeumen die Wuerfe aelterer Laeufe nicht mehr.
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


class Versand:
    """Eine angemeldete Verbindung, die Wuerfe einzeln einfuegt."""

    def __init__(self, wurzel: Path):
        env = lies_env(wurzel)
        self.projekt = env["PINS_SCORER_URL"].strip()
        self.erkenner = env["PINS_SCORER_ERKENNER"].strip()
        self.anon = lies_anon(wurzel)
        self.token = self._anmelden(env["PINS_SCORER_EMAIL"].strip(),
                                    env["PINS_SCORER_PASSWORT"].strip())

    def _anmelden(self, email: str, passwort: str) -> str:
        anfrage = urllib.request.Request(
            f"{self.projekt}/auth/v1/token?grant_type=password",
            data=json.dumps({"email": email, "password": passwort}).encode(),
            method="POST",
            headers={"apikey": self.anon, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(anfrage, timeout=20) as a:
                return json.loads(a.read())["access_token"]
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")[:300]
            raise SystemExit(
                f"Anmeldung als Erkenner fehlgeschlagen (HTTP {exc.code}): {text}")

    def zeile(self, bahn: int, holz: int, kegel=None, mit_bild: bool = False,
              nummer=None) -> dict:
        """Eine Zeile bauen.

        `kegel` sind die GEFALLENEN Kegel. `nummer` ist die Wurfnummer von der Tafel --
        seit dem 12.11.2026 bestimmt sie in der App den Platz im Satz. None heisst
        "nichts gelesen"; der Wurf geht dann an den naechsten freien Platz.
        """
        reihe = {"erkenner_id": self.erkenner, "lane": int(bahn),
                 "pins_count": int(holz), "video_id": MARKE}
        if kegel:
            reihe["pins"] = sorted({int(k) for k in kegel})
        if nummer is not None:
            reihe["displayed_throw_number"] = int(nummer)
        if mit_bild:
            reihe["board_jpeg"] = MINI_JPEG
            reihe["board_before_jpeg"] = MINI_JPEG
            reihe["displayed_pin_count"] = int(holz)
            reihe["displayed_throw_number"] = 99
        return reihe

    def schicke(self, reihe: dict) -> None:
        """Eine Zeile je Anfrage.

        NICHT als Stapel: PostgREST verlangt in einem Stapel bei JEDER Zeile dieselben
        Schluessel. Ein Wurf mit Kegelbild neben einem ohne ergibt dann HTTP 400 -- und
        einzeln ist es ohnehin naeher am Betrieb, wo jeder Wurf fuer sich ankommt.
        """
        anfrage = urllib.request.Request(
            f"{self.projekt}/rest/v1/erkannter_wurf", data=json.dumps(reihe).encode(),
            method="POST",
            headers={"apikey": self.anon, "Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"})
        try:
            with urllib.request.urlopen(anfrage, timeout=20):
                pass
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")[:400]
            raise SystemExit(f"Wurf abgelehnt (HTTP {exc.code}): {text}")


def aufraeumen(wurzel: Path) -> None:
    """Die eigenen Testzeilen loeschen -- ueber die Datenbank, NICHT als Erkenner.

    Absicht der Policies: `erkannter_wurf_delete` verlangt den Verwalter des Erkenners.
    Ein Geraet an der Bahn soll Wuerfe zuordnen oder als verworfen markieren, aber keine
    Belege wegraeumen -- sonst koennte ein fehlerhafter Rechner das Wurfprotokoll eines
    Spiels still loeschen. Der Erkenner-Login darf hier also richtigerweise nicht.

    ACHTUNG, falls jemand den Weg zurueckbaut: Ein DELETE, das die Rechte wegfiltern,
    kommt als HTTP 200 mit LEERER Liste zurueck -- erfolgreich aussehend, aber
    wirkungslos. Deshalb wird hier nicht der Antwort geglaubt, sondern nachgezaehlt.
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
