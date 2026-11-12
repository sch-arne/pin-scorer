"""Der Versand in die Datenbank des Pin Scorers.

Schwerpunkt ist die ZUGANGSFRAGE, nicht das Format: Der Rechner steht offen an
der Bahn. Geprueft wird deshalb vor allem, dass dort kein Generalschluessel
liegen kann -- `apikey` und `Authorization` muessen zwei verschiedene Werte
sein, ein geheimer Schluessel wird abgewiesen, und das Passwort darf in keiner
Meldung auftauchen.

Dazu die Eigenschaft, die die Zuordnung in der App ueberhaupt erst moeglich
macht: Jede Zeile traegt ihre `erkenner_id`, und KEINE traegt eine Zuordnung --
die setzt die App, nicht die Bilderkennung.
"""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from kegel_cv.config.schema import AppConfig
from kegel_cv.models.throw import ThrowResult, ThrowStatus
from kegel_cv.sinks import pins_scorer as ps
from kegel_cv.sinks.factory import build_sink
from kegel_cv.sinks.payload import throw_to_row
from kegel_cv.sinks.queued import QueuedSink
from kegel_cv.sinks.supabase import SupabaseError

ERKENNER = "7a1f9c3e-5b2d-4e8a-9f10-2c3d4e5f6a7b"
URL = "https://testprojekt.supabase.co"
KEY = "sb_publishable_testwert"

UMGEBUNG = {
    ps.ENV_EIN: "1",
    ps.ENV_URL: URL,
    ps.ENV_KEY: KEY,
    ps.ENV_ERKENNER: ERKENNER,
    ps.ENV_EMAIL: "erkennung-bahn2@example.org",
    ps.ENV_PASSWORT: "streng-geheim-nie-im-log",
}


def wurf(bahn: int = 2, kegel: int = 6) -> ThrowResult:
    return ThrowResult(
        lane=bahn, throw_number=1, throw_number_in_series=1,
        pins=tuple(range(1, kegel + 1)), pins_count=kegel,
        displayed_pin_count=kegel, status=ThrowStatus.VALID,
        running_total=kegel, confidence=0.95,
    )


@pytest.fixture
def umgebung(monkeypatch):
    """Setzt die `.env`-Werte -- und nur diese."""
    for name, wert in UMGEBUNG.items():
        monkeypatch.setenv(name, wert)
    return UMGEBUNG


class Antwort:
    """Minimale Antwort, wie `urlopen` sie als Kontext liefert."""

    def __init__(self, status: int = 201, koerper: bytes = b"") -> None:
        self.status = status
        self._koerper = koerper

    def read(self) -> bytes:
        return self._koerper

    def __enter__(self) -> "Antwort":
        return self

    def __exit__(self, *_: object) -> None:
        return None


class Netz:
    """Faengt alle Anfragen ab und spielt Anmeldung und Einfuegen nach.

    Haelt jede Anfrage fest -- Adresse, Kopfzeilen und Koerper. Erst damit
    laesst sich pruefen, was tatsaechlich auf die Leitung gegangen waere; eine
    Zusicherung ueber das Innenleben des Sinks waere wertlos.
    """

    def __init__(self, token: str = "token-1", gueltig_s: int = 3600) -> None:
        self.anfragen: list[urllib.request.Request] = []
        self.token = token
        self.gueltig_s = gueltig_s
        self.anmeldungen: list[dict] = []
        self.einfuegungen: list[list[dict]] = []
        self.weist_ab = 0          # so viele Einfuege-Versuche mit 401 ablehnen
        self.anmeldung_scheitert = False

    def __call__(self, anfrage, timeout=None):  # noqa: ANN001
        self.anfragen.append(anfrage)
        koerper = json.loads(anfrage.data.decode("utf-8"))
        if "/auth/v1/token" in anfrage.full_url:
            if self.anmeldung_scheitert:
                raise urllib.error.HTTPError(
                    anfrage.full_url, 400, "Bad Request", {},
                    io.BytesIO(b'{"error":"invalid_grant"}'))
            self.anmeldungen.append(koerper)
            nummer = len(self.anmeldungen)
            return Antwort(200, json.dumps({
                "access_token": f"{self.token}-{nummer}",
                "refresh_token": f"erneuern-{nummer}",
                "expires_in": self.gueltig_s,
            }).encode("utf-8"))

        if self.weist_ab > 0:
            self.weist_ab -= 1
            raise urllib.error.HTTPError(
                anfrage.full_url, 401, "Unauthorized", {},
                io.BytesIO(b'{"message":"JWT expired"}'))
        self.einfuegungen.append(koerper)
        return Antwort(201)

    # --- Auskunft ---------------------------------------------------------
    @property
    def letzte_zeilen(self) -> list[dict]:
        return self.einfuegungen[-1]

    def kopf(self, index: int = -1) -> dict[str, str]:
        # urllib normalisiert Kopfzeilen auf Kleinschreibung mit grossem
        # Anfangsbuchstaben ("Apikey"), deshalb hier vereinheitlichen.
        return {k.lower(): v for k, v in self.anfragen[index].header_items()}


@pytest.fixture
def netz(monkeypatch):
    netz = Netz()
    monkeypatch.setattr(urllib.request, "urlopen", netz)
    return netz


class TestEinrichtung:
    """Fehlt etwas, wird NICHT gesendet -- aber die Analyse laeuft weiter."""

    def test_ohne_schalter_kein_versand(self, monkeypatch):
        monkeypatch.delenv(ps.ENV_EIN, raising=False)
        assert ps.aus_umgebung() is None

    @pytest.mark.parametrize("fehlt", [
        ps.ENV_URL, ps.ENV_KEY, ps.ENV_ERKENNER, ps.ENV_EMAIL, ps.ENV_PASSWORT,
    ])
    def test_fehlender_wert_meldet_und_sendet_nicht(self, umgebung, monkeypatch,
                                                    caplog, fehlt):
        monkeypatch.setenv(fehlt, "")
        with caplog.at_level("WARNING"):
            assert ps.aus_umgebung() is None
        assert fehlt in caplog.text, "Was fehlt, muss im Protokoll stehen"

    @pytest.mark.parametrize("schluessel", [
        "sb_secret_abc123", "eyJhbGciOiJ.service_role.xyz",
    ])
    def test_geheimer_schluessel_wird_abgewiesen(self, umgebung, monkeypatch,
                                                 caplog, schluessel):
        """Der eigentliche Punkt dieses Moduls.

        Ein geheimer Schluessel umgeht die Zeilen-Sicherheit vollstaendig: wer
        ihn hat, liest und schreibt die ganze Datenbank -- auch Klarnamen und
        fremde Spiele. Auf einem Rechner, der offen an der Bahn steht, darf er
        nicht einmal versehentlich landen.
        """
        monkeypatch.setenv(ps.ENV_KEY, schluessel)
        with caplog.at_level("ERROR"):
            assert ps.aus_umgebung() is None
        assert "GEHEIM" in caplog.text.upper()

    def test_erkenner_muss_eine_uuid_sein(self, umgebung, monkeypatch, caplog):
        """Ein Tippfehler hier wuerde JEDE Zeile des Spieltags ablehnen --
        und zwar erst auf der Leitung, also im Versandpuffer."""
        monkeypatch.setenv(ps.ENV_ERKENNER, "bahn2")
        with caplog.at_level("ERROR"):
            assert ps.aus_umgebung() is None
        assert ps.ENV_ERKENNER in caplog.text

    def test_tabelle_hat_eine_vorgabe(self, umgebung, monkeypatch):
        monkeypatch.delenv(ps.ENV_TABELLE, raising=False)
        sink = ps.aus_umgebung()
        assert sink.endpoint.endswith("/rest/v1/erkannter_wurf")

    def test_beim_bauen_wird_noch_nicht_angemeldet(self, umgebung, netz):
        """Spaet anmelden, nicht beim Start.

        Sonst legte ein kurzer Netzausfall beim Hochfahren den Versand fuer den
        ganzen Lauf still -- obwohl die Verbindung eine Minute spaeter wieder
        da ist. So landet der erste Wurf im Puffer und geht danach raus.
        """
        ps.aus_umgebung()
        assert netz.anfragen == []


class TestZugang:
    def test_apikey_und_bearer_sind_verschieden(self, umgebung, netz):
        """Der Unterschied zum Upstream-Versand in einem Satz.

        Dort ist beides derselbe Schluessel. Hier ist `apikey` der oeffentliche
        Schluessel des Projekts und `Authorization` das Token eines Benutzers,
        der laut policies.sql nur einfuegen darf.
        """
        sink = ps.aus_umgebung()
        sink.send(wurf())

        kopf = netz.kopf()
        assert kopf["apikey"] == KEY
        assert kopf["authorization"] == "Bearer token-1-1"
        assert kopf["authorization"] != f"Bearer {KEY}"

    def test_token_wird_wiederverwendet(self, umgebung, netz):
        sink = ps.aus_umgebung()
        for _ in range(5):
            sink.send(wurf())

        assert len(netz.anmeldungen) == 1, "einmal anmelden, nicht je Wurf"
        assert len(netz.einfuegungen) == 5

    def test_kurz_vor_ablauf_wird_erneuert(self, umgebung, monkeypatch):
        """Erneuert wird mit dem `refresh_token`, nicht mit dem Passwort."""
        netz = Netz(gueltig_s=int(ps.VORLAUF_S) - 1)   # sofort "fast abgelaufen"
        monkeypatch.setattr(urllib.request, "urlopen", netz)

        sink = ps.aus_umgebung()
        sink.send(wurf())
        sink.send(wurf())

        assert len(netz.anmeldungen) == 2
        assert "password" in netz.anmeldungen[0]
        assert netz.anmeldungen[1] == {"refresh_token": "erneuern-1"}

    def test_nach_401_einmal_neu_anmelden_und_wiederholen(self, umgebung, netz):
        """Ein zurueckgezogenes Token darf keinen Wurf kosten."""
        sink = ps.aus_umgebung()
        netz.weist_ab = 1

        sink.send(wurf())

        assert len(netz.einfuegungen) == 1, "der Wurf ist durchgekommen"
        assert len(netz.anmeldungen) == 2, "dazwischen neu angemeldet"

    def test_gescheiterte_anmeldung_wirft_ohne_passwort(self, umgebung, netz):
        """Werfen ist richtig: `QueuedSink` wiederholt und puffert dann.

        Wichtiger ist der zweite Teil -- in der Meldung steht der Benutzername
        (damit man sie suchen kann), aber NIEMALS das Passwort. Sonst stuende es
        in jeder Protokolldatei des Spieltags.
        """
        netz.anmeldung_scheitert = True
        sink = ps.aus_umgebung()

        with pytest.raises(SupabaseError) as fehler:
            sink.send(wurf())

        assert UMGEBUNG[ps.ENV_EMAIL] in str(fehler.value)
        assert UMGEBUNG[ps.ENV_PASSWORT] not in str(fehler.value)


class TestZeile:
    def test_jede_zeile_traegt_den_erkenner(self, umgebung, netz):
        sink = ps.aus_umgebung()
        sink.send(wurf())

        assert netz.letzte_zeilen[0]["erkenner_id"] == ERKENNER

    def test_auch_nachgelieferte_zeilen(self, umgebung, netz):
        """Der Einschub sitzt im Versand, nicht im Zeilenbau -- deshalb
        bekommen auch Zeilen aus dem Puffer ihre `erkenner_id`, selbst wenn sie
        vor der Umstellung geschrieben wurden."""
        sink = ps.aus_umgebung()
        alt = throw_to_row(wurf(), video_id="gestern.mp4")
        assert "erkenner_id" not in alt, "der Zeilenbau kennt ihn nicht"

        sink.send_rows([alt])

        assert netz.letzte_zeilen[0]["erkenner_id"] == ERKENNER

    def test_keine_zuordnung_vom_erkenner(self, umgebung, netz):
        """Der Kern der Arbeitsteilung: Der Erkenner kennt Bahn und Kegel,
        nicht Spiel, Spieler, Satz oder Wurfindex. Setzte er sie, gaebe es zwei
        Wahrheiten -- und die Einfuege-Regel in policies.sql lehnt es ohnehin
        ab, weil sie verlangt, dass diese Spalten leer sind.
        """
        sink = ps.aus_umgebung()
        sink.send(wurf())

        for spalte in ("spiel_id", "satz_block_id", "wurf_index",
                       "uebernommen_am", "verworfen_grund"):
            assert spalte not in netz.letzte_zeilen[0]

    def test_partiename_geht_nicht_mit(self, umgebung, netz):
        """`game_name` gibt es in unserer Tabelle nicht: die Partie ist bei uns
        ein `spiel` in der Datenbank. Eine Zeile aus einem alten Puffer darf
        daran aber nicht haengenbleiben -- PostgREST lehnt sonst die GANZE
        Zeile ab, und der Wurf kreist fuer immer im Puffer."""
        sink = ps.aus_umgebung()
        alt = throw_to_row(wurf(), game_name="VOK 1 - Greste 1")

        sink.send_rows([alt])

        assert "game_name" not in netz.letzte_zeilen[0]
        assert netz.letzte_zeilen[0]["pins_count"] == 6, "der Wurf bleibt heil"

    def test_das_gemessene_bleibt_vollstaendig(self, umgebung, netz):
        sink = ps.aus_umgebung()
        sink.send(wurf(bahn=4, kegel=9))

        zeile = netz.letzte_zeilen[0]
        assert zeile["lane"] == 4
        assert zeile["pins_count"] == 9
        assert zeile["pins"] == list(range(1, 10))
        assert "recorded_at" in zeile and "video_time_s" in zeile


class TestFactory:
    def test_umgebung_schlaegt_die_konfiguration(self, umgebung, netz):
        """Eingeschaltet wird ueber die Umgebung -- auch wenn in der
        Konfiguration `output.supabase.enabled` aus steht. Welche Datenbank und
        welcher Erkenner gehoert zur INSTALLATION, nicht in eine Datei, die in
        der Versionsverwaltung liegt."""
        cfg = AppConfig()
        assert cfg.output.supabase.enabled is False

        sink = build_sink(cfg, video_id="bahn2.mp4")

        assert isinstance(sink, QueuedSink)
        assert isinstance(sink.inner, ps.PinsScorerSink)
        sink.close()

    def test_ohne_umgebung_bleibt_alles_wie_upstream(self, monkeypatch):
        monkeypatch.delenv(ps.ENV_EIN, raising=False)
        from kegel_cv.sinks.base import NullSink

        sink = build_sink(AppConfig())

        assert isinstance(sink, NullSink)

    def test_bahnfilter_gilt_auch_hier(self, umgebung, netz):
        """Mehrere Erkenner an einer Halle sind vorgesehen (ein Stream fuer
        zwei Bahnen, ein Telefon fuer die anderen). Der Filter des Urhebers
        muss deshalb auch um unseren Versand liegen, sonst schriebe jedes
        Geraet jede Bahn, die es zufaellig lesen kann."""
        from kegel_cv.sinks.base import BahnFilterSink

        cfg = AppConfig()
        cfg.output.lanes = [2, 3]

        sink = build_sink(cfg)

        assert isinstance(sink, BahnFilterSink)
        sink.close()


class TestGegenDasSchema:
    """Jede gesendete Spalte muss es in `erkannter_wurf` wirklich geben.

    PostgREST lehnt eine Zeile mit einer unbekannten Spalte KOMPLETT ab -- und
    zwar erst auf der Leitung. Ein umbenanntes Feld auf einer der beiden Seiten
    wuerde also nicht auffallen, bis ein ganzer Spieltag im Versandpuffer liegt.
    Deshalb liest dieser Test das Schema des Pin Scorers mit.

    Die Gegenrichtung (fehlende Spalten in der Zeile) prueft der Test nicht:
    Alles in `erkannter_wurf` ausser `lane` und `pins_count` ist nullbar, weil
    "nicht gelesen" eine gueltige Aussage ist.
    """

    # tests/unit/ -> tests -> erkennung -> pins-scorer
    SCHEMA = Path(__file__).resolve().parents[3] / "supabase" / "schema.sql"

    def spalten(self) -> set[str]:
        if not self.SCHEMA.is_file():
            pytest.skip(f"{self.SCHEMA} nicht gefunden (Kopie ohne den Pin Scorer?)")
        text = self.SCHEMA.read_text(encoding="utf-8")
        anfang = text.index("create table if not exists erkannter_wurf")
        namen = set()
        # Zeilenweise bis zur schliessenden Klammer, und ZUERST den Kommentar
        # abschneiden: In einem Kommentar darf jedes Zeichen stehen, "(1..9);"
        # zum Beispiel -- eine Suche nach ");" im ganzen Text endet sonst
        # mitten in der Tabelle, und der Test waere still unvollstaendig.
        for zeile in text[anfang:].splitlines()[1:]:
            zeile = zeile.split("--")[0].strip()
            if zeile.startswith(")"):
                break
            if not zeile:
                continue
            namen.add(zeile.split()[0].strip(","))
        return namen

    def test_gesendete_spalten_gibt_es(self, umgebung, netz):
        sink = ps.aus_umgebung()
        voll = throw_to_row(wurf(), video_id="bahn2.mp4", mit_bild=True,
                            mit_vorher=True)
        voll["board_jpeg"] = "x"          # throw_to_row laesst sie weg, wenn
        voll["board_before_jpeg"] = "x"   # der Wurf kein Tafelbild traegt

        sink.send_rows([voll])

        unbekannt = set(netz.letzte_zeilen[0]) - self.spalten()
        assert not unbekannt, (
            f"Diese Spalten sendet der Erkenner, aber erkannter_wurf hat sie "
            f"nicht: {sorted(unbekannt)}"
        )

    def test_die_zuordnung_steht_im_schema(self):
        """Umgekehrte Absicherung: Die Spalten, die die APP fuellt, muessen da
        sein -- sonst hat der Erkenner eine Tabelle, in der seine Wuerfe nie
        einem Wurf im Satz zugeordnet werden koennen."""
        assert {"erkenner_id", "spiel_id", "satz_block_id",
                "wurf_index"} <= self.spalten()
