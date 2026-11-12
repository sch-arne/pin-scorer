"""Versand der erkannten Wuerfe in die Datenbank des PIN SCORERS.

Das ist der Grund, warum dieser Ordner eine Kopie ist und kein Submodul: Der
Erkenner schreibt hier nicht mehr in das Supabase-Projekt des Urhebers, sondern
in unsere eigene Tabelle `erkannter_wurf` -- und er meldet sich dafuer anders an.

UNTERSCHIED ZUM UPSTREAM-VERSAND (`supabase.py`)
------------------------------------------------

1. **Anmeldung als BENUTZER, nicht mit einem Schluessel.**
   Upstream schickt denselben Schluessel als `apikey` und als `Bearer` -- und
   `.env.example` empfiehlt dafuer inzwischen den geheimen Schluessel. Der
   umgeht jede Zeilen-Sicherheit (RLS): wer ihn hat, liest und schreibt die
   ganze Datenbank, auch Klarnamen und fremde Spiele. Auf einem Rechner, der
   offen an der Bahn steht, ist das ein Generalschluessel im Schuhkasten.

   Hier sind es deshalb zwei verschiedene Werte: `apikey` ist der oeffentliche
   Schluessel des Projekts, `Bearer` das Zugangstoken eines EIGENEN Benutzers,
   der laut `supabase/policies.sql` genau eines darf -- Wuerfe fuer seine eigene
   `erkenner_id` einfuegen. Nicht lesen, nicht aendern, nicht loeschen. Der
   schlimmste Fall eines gestohlenen Zugangs ist damit "jemand schleust falsche
   Wuerfe ein", und das Gegenmittel ist ein neues Passwort.

2. **Jede Zeile traegt die `erkenner_id`.**
   Sie sagt, WELCHES Geraet geliefert hat, und darueber findet die App Anlage
   und Bahn. Sie kommt aus der Umgebung, nicht aus der Oberflaeche: Sie gehoert
   zur Installation, nicht zum Lauf.

3. **Was der Erkenner NICHT schreibt**, schreibt die App: Spiel, Spieler, Satz,
   Teilsatz, Wurfindex. Der Erkenner kennt nur Bahn und gefallene Kegel -- so
   wie er es auch upstream tut (siehe `payload.py`). Die Spalten `spiel_id`,
   `satz_block_id` und `wurf_index` darf er nicht einmal fuellen; die
   Einfuege-Regel verlangt, dass sie leer sind.

Der Rest bleibt wie gebaut: `QueuedSink` haelt die Analyse frei, puffert bei
Netzausfall und liefert beim naechsten Start nach. Diese Klasse ist nur der
innere, synchrone Versand -- sie darf werfen, und sie soll es.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from .supabase import SupabaseError, SupabaseSink

log = logging.getLogger(__name__)

# --- Umgebungsvariablen ------------------------------------------------------
# Eigene Namen, absichtlich nicht die SUPABASE_*-Namen des Urhebers: dort steht
# laut dessen `.env.example` der GEHEIME Schreibschluessel. Wer beides in einer
# Datei haette, koennte den einen Wert fuer den anderen halten -- und ein
# geheimer Schluessel, der versehentlich als `PINS_SCORER_KEY` landet, wird hier
# abgewiesen (siehe `aus_umgebung`).
ENV_EIN = "PINS_SCORER"                   # "1"/"true" schaltet diesen Weg ein
ENV_URL = "PINS_SCORER_URL"               # https://<projekt>.supabase.co
ENV_KEY = "PINS_SCORER_KEY"               # oeffentlicher Schluessel (publishable/anon)
ENV_ERKENNER = "PINS_SCORER_ERKENNER"     # uuid aus der Tabelle `erkenner`
ENV_EMAIL = "PINS_SCORER_EMAIL"           # Login des Erkenners
ENV_PASSWORT = "PINS_SCORER_PASSWORT"
ENV_TABELLE = "PINS_SCORER_TABELLE"       # Vorgabe: erkannter_wurf

TABELLE_VORGABE = "erkannter_wurf"

# Spalten, die es in UNSERER Tabelle nicht gibt. `game_name` ist der
# Partiename, den der Nutzer in der Oberflaeche vergibt; bei uns gehoert die
# Partie zum `spiel` in der Datenbank, nicht in eine Textspalte. Wir bauen ihn
# deshalb nicht ein -- aber eine Zeile aus einem ALTEN Versandpuffer kann ihn
# noch tragen, und PostgREST lehnt dann die ganze Zeile ab. Also hier raus,
# still: ein Wurf darf nicht an einem Etikett scheitern.
UNBEKANNTE_SPALTEN = ("game_name",)

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

# So lange vor dem Ablauf wird das Token erneuert. Ein Zugangstoken gilt bei
# Supabase eine Stunde; zwei Minuten Vorlauf reichen fuer einen Versuch samt
# Wiederholung und sind kurz genug, dass pro Spieltag nur eine Handvoll
# Erneuerungen anfallen.
VORLAUF_S = 120.0


class Anmeldung:
    """Haelt das Zugangstoken eines Supabase-Benutzers aktuell.

    Ohne Fremdbibliothek, wie der ganze Versand: Anmelden ist ein POST, und
    `urllib` liegt schon da (siehe Kopf von `supabase.py`).

    Angemeldet wird SPAET -- beim ersten Wurf, nicht beim Start. Gruende:
    Erstens darf ein toter Zugang die Analyse nicht verhindern (P8); zweitens
    wuerde ein Fehlschlag beim Start den Versand dauerhaft stilllegen, obwohl
    das Netz eine Minute spaeter wieder da ist. So landet der Wurf im Puffer und
    geht beim naechsten Versuch raus.
    """

    def __init__(self, url: str, apikey: str, email: str, passwort: str,
                 timeout_s: float = 5.0) -> None:
        self.basis = f"{url.rstrip('/')}/auth/v1/token"
        self.apikey = apikey
        self.email = email
        self.passwort = passwort
        self.timeout_s = timeout_s
        self._token = ""
        self._erneuerungstoken = ""
        self._gueltig_bis = 0.0
        # `QueuedSink` sendet aus einem Hintergrund-Thread, liefert aber beim
        # Start aus dem Haupt-Thread nach. Ohne Schloss koennten beide
        # gleichzeitig anmelden und sich die Tokens ueberschreiben.
        self._schloss = threading.Lock()

    def token(self) -> str:
        """Das gueltige Zugangstoken. Meldet an oder erneuert, wenn noetig."""
        with self._schloss:
            if self._token and time.time() < self._gueltig_bis - VORLAUF_S:
                return self._token
            if self._erneuerungstoken:
                try:
                    return self._holen("refresh_token",
                                       {"refresh_token": self._erneuerungstoken})
                except SupabaseError as exc:
                    # Ein abgelaufenes oder zurueckgezogenes Erneuerungstoken
                    # ist kein Grund aufzugeben -- Passwort haben wir noch.
                    log.warning("Erneuern fehlgeschlagen (%s) -- melde neu an", exc)
                    self._erneuerungstoken = ""
            return self._holen("password",
                               {"email": self.email, "password": self.passwort})

    def verwerfen(self) -> None:
        """Vergisst das Token -- nach einem 401 holt `token()` ein neues."""
        with self._schloss:
            self._token = ""
            self._gueltig_bis = 0.0

    def _holen(self, art: str, koerper: dict[str, str]) -> str:
        anfrage = urllib.request.Request(
            f"{self.basis}?grant_type={art}",
            data=json.dumps(koerper).encode("utf-8"), method="POST",
            headers={"apikey": self.apikey, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(anfrage, timeout=self.timeout_s) as antwort:
                daten = json.loads(antwort.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")[:300]
            # DAS PASSWORT NIE MITLOGGEN. Der Benutzername hilft beim Suchen,
            # das Passwort stuende sonst in jeder Protokolldatei.
            raise SupabaseError(
                f"Anmeldung als {self.email} fehlgeschlagen: HTTP {exc.code}: {text}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise SupabaseError(f"Anmeldung nicht erreichbar: {exc}") from exc

        token = daten.get("access_token") or ""
        if not token:
            raise SupabaseError("Anmeldung ohne access_token")
        self._token = token
        self._erneuerungstoken = daten.get("refresh_token") or ""
        # `expires_in` ist die verlaessliche Angabe: `expires_at` ist eine
        # absolute Zeit vom SERVER und waere auf einem Rechner mit falsch
        # gestellter Uhr sofort "abgelaufen". Das ist kein erfundener Fall --
        # ein Rechner an der Bahn haengt nicht zwingend an einem Zeitserver.
        self._gueltig_bis = time.time() + float(daten.get("expires_in") or 3600)
        log.info("Am Pin Scorer angemeldet als %s (%s)", self.email,
                 "erneuert" if art == "refresh_token" else "neu")
        return token


class PinsScorerSink(SupabaseSink):
    """Schreibt die erkannten Wuerfe in `erkannter_wurf` des Pin Scorers."""

    def __init__(self, url: str, table: str, apikey: str, erkenner_id: str,
                 email: str, passwort: str, timeout_s: float = 5.0,
                 video_id: str = "") -> None:
        # `api_key` der Basisklasse ist hier der OEFFENTLICHE Schluessel: er
        # bleibt der `apikey`-Kopf, waehrend `Authorization` aus der Anmeldung
        # kommt (siehe `_kopfzeilen`).
        super().__init__(url=url, table=table, api_key=apikey,
                         timeout_s=timeout_s, video_id=video_id,
                         game_name="", game_name_column="")
        if not _UUID.match(erkenner_id or ""):
            raise ValueError(
                f"{ENV_ERKENNER} ist keine UUID: {erkenner_id!r}. Erwartet wird "
                "die id aus der Tabelle `erkenner`."
            )
        self.erkenner_id = erkenner_id
        self.anmeldung = Anmeldung(url, apikey, email, passwort, timeout_s)

    def _kopfzeilen(self) -> dict[str, str]:
        kopf = super()._kopfzeilen()
        kopf["Authorization"] = f"Bearer {self.anmeldung.token()}"
        return kopf

    def send_rows(self, rows: list[dict[str, Any]]) -> None:
        """Ergaenzt die `erkenner_id` und schickt die Zeilen.

        Der Einschub sitzt hier und nicht in `payload.py`, weil hier BEIDE Wege
        durchkommen: der laufende Versand und das Nachliefern aus dem Puffer.
        Zeilen, die vor der Umstellung gepuffert wurden, bekommen ihre
        `erkenner_id` damit noch nachtraeglich.
        """
        if not rows:
            return
        fertig = [self._zeile(zeile) for zeile in rows]
        try:
            super().send_rows(fertig)
        except SupabaseError as exc:
            # Ein 401 heisst fast immer: das Token ist weg oder zurueckgezogen.
            # Einmal neu anmelden und noch einmal versuchen -- danach gilt der
            # Fehler, und `QueuedSink` puffert.
            if "HTTP 401" not in str(exc):
                raise
            log.warning("Zugang abgelehnt (401) -- melde neu an und wiederhole")
            self.anmeldung.verwerfen()
            super().send_rows(fertig)

    def _zeile(self, zeile: dict[str, Any]) -> dict[str, Any]:
        fertig = {k: v for k, v in zeile.items() if k not in UNBEKANNTE_SPALTEN}
        fertig["erkenner_id"] = self.erkenner_id
        return fertig


def eingeschaltet() -> bool:
    """Steht `PINS_SCORER` in der Umgebung auf wahr?"""
    return os.environ.get(ENV_EIN, "").strip().lower() in ("1", "true", "ja", "yes", "on")


def aus_umgebung(video_id: str = "") -> PinsScorerSink | None:
    """Baut den Versand aus der `.env` -- oder `None`, wenn etwas fehlt.

    `None` heisst immer "nicht eingerichtet", nie "kaputt": Der Aufrufer faellt
    dann auf den Upstream-Weg bzw. auf `NullSink` zurueck, und die Analyse laeuft
    weiter (P8). Was fehlt, steht als Warnung im Protokoll -- stumm nichts zu
    senden ist der eine Fehler, der einen ganzen Spieltag kostet.
    """
    if not eingeschaltet():
        return None

    url = os.environ.get(ENV_URL, "").strip()
    key = os.environ.get(ENV_KEY, "").strip()
    erkenner = os.environ.get(ENV_ERKENNER, "").strip()
    email = os.environ.get(ENV_EMAIL, "").strip()
    passwort = os.environ.get(ENV_PASSWORT, "")
    tabelle = os.environ.get(ENV_TABELLE, "").strip() or TABELLE_VORGABE

    fehlt = [name for name, wert in (
        (ENV_URL, url), (ENV_KEY, key), (ENV_ERKENNER, erkenner),
        (ENV_EMAIL, email), (ENV_PASSWORT, passwort),
    ) if not wert]
    if fehlt:
        log.warning(
            "%s ist eingeschaltet, aber %s fehlt -- es wird nichts an den Pin "
            "Scorer gesendet. Vorlage: .env.example", ENV_EIN, ", ".join(fehlt))
        return None

    # EIN GEHEIMER SCHLUESSEL GEHOERT HIER NICHT HIN, und zwar unbedingt nicht:
    # Er umgeht die Zeilen-Sicherheit und machte den Rechner an der Bahn zum
    # Generalschluessel. Derselbe Schutz wie upstream im Liveticker -- nur dass
    # es dort ums Lesen geht und hier ums Schreiben.
    if key.startswith("sb_secret_") or "service_role" in key:
        log.error(
            "%s sieht nach einem GEHEIMEN Schluessel aus. Hier gehoert der "
            "oeffentliche hin (sb_publishable_... bzw. anon); angemeldet wird "
            "ueber %s/%s. Es wird nichts gesendet.",
            ENV_KEY, ENV_EMAIL, ENV_PASSWORT)
        return None

    try:
        sink = PinsScorerSink(url=url, table=tabelle, apikey=key,
                              erkenner_id=erkenner, email=email,
                              passwort=passwort, video_id=video_id)
    except ValueError as exc:
        log.error("Versand an den Pin Scorer nicht moeglich: %s", exc)
        return None

    log.info("Erkannte Wuerfe gehen an %s/rest/v1/%s als Erkenner %s",
             url.rstrip("/"), tabelle, erkenner)
    return sink
