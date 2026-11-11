"""Der Ergebnisversand.

Schwerpunkt: Der Versand darf die Analyse unter keinen Umstaenden aufhalten oder
abbrechen -- und nichts verlieren. Die Kegel sind gefallen, ob die Datenbank
erreichbar ist oder nicht.
"""

from __future__ import annotations

import json
import time

from kegel_cv.config.schema import AppConfig
from kegel_cv.models.throw import ThrowResult, ThrowStatus
from kegel_cv.sinks.base import NullSink, ResultSink
from kegel_cv.sinks.factory import build_sink
from kegel_cv.sinks.payload import throw_to_row
from kegel_cv.sinks.queued import QueuedSink


def wurf(nummer: int = 1, bahn: int = 2, kegel: int = 6) -> ThrowResult:
    return ThrowResult(
        lane=bahn, throw_number=nummer, throw_number_in_series=nummer,
        pins=tuple(range(1, kegel + 1)), pins_count=kegel,
        displayed_pin_count=kegel, status=ThrowStatus.VALID,
        running_total=kegel * nummer, confidence=0.95,
    )


class SammelSink(ResultSink):
    """Merkt sich alles -- und faellt auf Wunsch die ersten N Male aus."""

    def __init__(self, faellt_aus: int = 0) -> None:
        self.zeilen: list[dict] = []
        self.faellt_aus = faellt_aus
        self.versuche = 0

    def send(self, throw: ThrowResult) -> None:
        self.send_rows([throw_to_row(throw)])

    def send_rows(self, rows: list[dict]) -> None:
        self.versuche += 1
        if self.versuche <= self.faellt_aus:
            raise RuntimeError("Netz weg")
        self.zeilen.extend(rows)


class TestZeile:
    """Uebertragen wird nur, was GEMESSEN ist -- nicht, was abgeleitet wurde.

    Vom Nutzer so festgelegt (2026-08-26). Der Grund ist die Erfahrung aus
    diesem Projekt: Die abgeleiteten Groessen sind schiefgegangen -- die
    Wurfnummer loeschte 28 % der Wuerfe, die Spielerkennung traf den
    Bahnwechsel nicht, die laufende Summe driftete ab. Die auswertende
    Anwendung kennt die Regeln besser als die Bilderkennung.
    """

    def test_enthaelt_das_gemessene(self):
        zeile = throw_to_row(wurf(), video_id="test.mp4")

        for schluessel in ("lane", "pins_count", "pins",
                           "video_id", "recorded_at", "video_time_s"):
            assert schluessel in zeile

    def test_enthaelt_nichts_abgeleitetes(self):
        """Der Kern der Entscheidung: Was die Bilderkennung nicht misst,
        sondern HERLEITET, gehoert nicht in die Uebertragung.

        Die Grenze verlaeuft zwischen abgeleitet und abgelesen, nicht zwischen
        wichtig und unwichtig. `throw_number` ist eine Zaehlung ueber viele
        Wuerfe hinweg und faellt heraus; `displayed_throw_number` ist das, was
        auf der Tafel STAND, und darf mit."""
        zeile = throw_to_row(wurf())

        for schluessel in ("throw_number", "running_total", "series_total",
                           "game", "cycle", "status"):
            assert schluessel not in zeile, (
                f"'{schluessel}' ist abgeleitet und darf nicht gesendet werden"
            )

    def test_enthaelt_die_ablesungen_der_tafel(self):
        """ERGAENZUNG 2026-09-14 (Nutzer): *"nullable mitsenden, dann kann
        jeder selbst entscheiden, was er macht."* Vier Ablesungen -- kein
        Regelwissen, keine Rechnung, kein Zustand ueber Wuerfe hinweg."""
        zeile = throw_to_row(wurf())

        for schluessel in ("displayed_throw_number", "displayed_pin_count",
                           "displayed_foul_count", "displayed_total"):
            assert schluessel in zeile

    def test_die_ablesungen_duerfen_leer_sein(self):
        """`None` heisst "nicht sicher gelesen" und ist eine Aussage. Die
        Spalte muss trotzdem da sein -- eine fehlende und eine leere Spalte
        sind fuer die lesende Anwendung zweierlei."""
        zeile = throw_to_row(wurf())
        assert zeile["displayed_foul_count"] is None
        json.dumps(zeile)

    def test_summenfeld_a_faehrt_nicht_mit(self):
        """Nutzer 2026-09-14: "summe_a ist irgendwie Quatsch fuer uns." Es hat
        als einziges Feld keine Ziffernzellen kalibriert und geht in keine
        Pruefung ein."""
        zeile = throw_to_row(wurf())
        assert not any("total_a" in s for s in zeile)

    def test_ist_flach_und_json_faehig(self):
        """Der Spielleiter schaut auf eine Tabelle, nicht auf ein Dokument."""
        zeile = throw_to_row(wurf())

        json.dumps(zeile)   # darf nicht werfen
        assert not any(isinstance(w, dict) for w in zeile.values())


class TestQueuedSink:
    def test_wuerfe_kommen_an(self):
        innen = SammelSink()
        with QueuedSink(innen, max_retries=1) as sink:
            for i in range(1, 6):
                sink.send(wurf(i))
            sink.flush()

        assert len(innen.zeilen) == 5

    def test_send_blockiert_die_analyse_nicht(self):
        """Der entscheidende Punkt: `send` kehrt sofort zurueck, auch wenn der
        Versand haengt. Sonst braechte ein hakendes Netz die Auswertung zum
        Stehen -- bei 40 ms Budget je Frame.
        """
        class LahmerSink(SammelSink):
            def send_rows(self, rows):
                time.sleep(0.4)
                super().send_rows(rows)

        sink = QueuedSink(LahmerSink(), max_retries=1)
        begonnen = time.perf_counter()
        for i in range(1, 6):
            sink.send(wurf(i))
        gebraucht = time.perf_counter() - begonnen
        sink.close()

        assert gebraucht < 0.2, "send darf nicht auf den Versand warten"

    def test_wiederholt_bei_ausfall(self):
        innen = SammelSink(faellt_aus=2)
        with QueuedSink(innen, max_retries=3, retry_delay_s=0.01) as sink:
            sink.send(wurf())
            sink.flush()

        assert len(innen.zeilen) == 1, "der dritte Versuch muss durchkommen"

    def test_verlorenes_wird_zwischengespeichert(self, tmp_path):
        puffer = tmp_path / "puffer.jsonl"
        innen = SammelSink(faellt_aus=99)
        with QueuedSink(innen, spool_file=puffer, max_retries=2,
                        retry_delay_s=0.01) as sink:
            sink.send(wurf(7))
            sink.flush()

        assert puffer.exists(), "nichts darf verlorengehen"
        zeilen = [json.loads(z) for z in puffer.read_text(encoding="utf-8").splitlines()]
        assert zeilen[0]["pins_count"] == 6 and zeilen[0]["lane"] == 2

    def test_zwischengespeichertes_wird_nachgeliefert(self, tmp_path):
        puffer = tmp_path / "puffer.jsonl"
        puffer.write_text(json.dumps(throw_to_row(wurf(3))) + "\n", encoding="utf-8")

        innen = SammelSink()
        sink = QueuedSink(innen, spool_file=puffer, max_retries=1)
        anzahl = sink.resend_spooled()
        sink.close()

        assert anzahl == 1
        assert not puffer.exists(), "nach dem Nachliefern ist der Puffer leer"

    def test_ein_fehler_toetet_den_thread_nicht(self):
        """Stirbt der Thread, sammeln sich alle folgenden Wuerfe stumm an."""
        innen = SammelSink(faellt_aus=2)
        with QueuedSink(innen, max_retries=1, retry_delay_s=0.01) as sink:
            sink.send(wurf(1))       # scheitert
            sink.flush()
            sink.send(wurf(2))       # scheitert
            sink.flush()
            sink.send(wurf(3))       # muss durchkommen
            sink.flush()

        assert len(innen.zeilen) == 1, "nur der dritte Wurf kommt durch"


class TestFactory:
    def test_ohne_einstellung_wird_nichts_versendet(self):
        assert isinstance(build_sink(AppConfig()), NullSink)

    def test_ohne_schluessel_kein_versand(self, monkeypatch):
        """Eine unvollstaendige Einstellung darf die Analyse nicht verhindern."""
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        cfg = AppConfig()
        cfg.output.supabase.enabled = True
        cfg.output.supabase.url = "https://beispiel.supabase.co"

        assert isinstance(build_sink(cfg), NullSink)

    def test_nullsink_schluckt_alles(self):
        NullSink().send(wurf())     # darf nicht werfen


class TestWeiterhinBerechnet:
    """Nicht gesendet heisst NICHT: nicht gerechnet.

    Der Nutzer braucht die abgeleiteten Groessen weiterhin in der Oberflaeche,
    um die Erkennung beurteilen zu koennen -- sie sollen nur nicht uebertragen
    werden.
    """

    def test_wurfergebnis_traegt_weiterhin_alles(self):
        w = wurf()

        assert w.throw_number == 1
        assert w.running_total > 0
        assert w.game_number == 1
        assert w.status is ThrowStatus.VALID


class TestAdresseAusDerUmgebung:
    """Die Projekt-URL kommt aus `SUPABASE_URL`, die Konfiguration ist nur
    Rueckfall -- sie benennt die Datenbank eines bestimmten Vereins und hat in
    einer geteilten Datei nichts verloren (2026-09-11)."""

    def _cfg(self, url: str = ""):
        # ZUERST laden: `load_config` liest die `.env` in die Umgebung. Wer
        # danach setzt oder loescht, gewinnt -- andersherum holt die Datei den
        # geloeschten Wert still zurueck.
        from kegel_cv.config import load_config
        cfg = load_config()
        cfg.output.supabase.enabled = True
        cfg.output.supabase.url = url
        return cfg

    def test_die_umgebung_gewinnt(self, monkeypatch):
        from kegel_cv.sinks.factory import build_sink
        cfg = self._cfg("https://ausderdatei.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "sb_secret_test")
        monkeypatch.setenv("SUPABASE_URL", "https://ausderumgebung.supabase.co")
        sink = build_sink(cfg)
        assert "ausderumgebung" in sink.inner.endpoint

    def test_ohne_umgebung_zaehlt_die_datei(self, monkeypatch):
        from kegel_cv.sinks.factory import build_sink
        cfg = self._cfg("https://ausderdatei.supabase.co")
        monkeypatch.setenv("SUPABASE_KEY", "sb_secret_test")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        sink = build_sink(cfg)
        assert "ausderdatei" in sink.inner.endpoint

    def test_ohne_adresse_wird_nichts_versendet(self, monkeypatch, caplog):
        """P8: Eine fehlende Adresse darf die Analyse nicht verhindern --
        der Nutzer will seine Wuerfe sehen, auch ohne Datenbank."""
        import logging
        from kegel_cv.sinks.base import NullSink
        from kegel_cv.sinks.factory import build_sink
        cfg = self._cfg("")
        monkeypatch.setenv("SUPABASE_KEY", "sb_secret_test")
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        with caplog.at_level(logging.WARNING):
            sink = build_sink(cfg)
        assert isinstance(sink, NullSink)
        assert any("Adresse" in s for s in caplog.messages), caplog.messages
