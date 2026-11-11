"""Baut den Ergebnis-Abnehmer aus der Konfiguration.

Eine Stelle, an der entschieden wird, wohin die Ergebnisse gehen -- damit die
Analyse davon nichts wissen muss.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ..config.schema import AppConfig
from .base import BahnFilterSink, NullSink, ResultSink
from .pins_scorer import ENV_EIN, aus_umgebung
from .queued import QueuedSink
from .supabase import SupabaseSink

log = logging.getLogger(__name__)


def build_sink(cfg: AppConfig, video_id: str = "",
               game_name: str = "") -> ResultSink:
    """Baut den Abnehmer und legt den Bahnfilter darum.

    Der Filter liegt GANZ AUSSEN und gilt auch dann, wenn gar nicht gesendet
    wird: Im Probelauf soll im Log stehen, dass die Auswahl verstanden wurde --
    sonst faellt eine vertippte Bahnnummer erst am Spieltag auf.
    """
    innen = _baue_abnehmer(cfg, video_id, game_name)
    if cfg.output.lanes:
        log.info("Gesendet werden nur die Bahnen %s", sorted(cfg.output.lanes))
        return BahnFilterSink(innen, cfg.output.lanes)
    return innen


def _baue_abnehmer(cfg: AppConfig, video_id: str,
                   game_name: str) -> ResultSink:
    """Liefert den konfigurierten Abnehmer -- oder einen, der nichts tut.

    Faellt IMMER auf `NullSink` zurueck, wenn etwas fehlt. Eine unvollstaendige
    Versandeinstellung darf die Analyse nicht verhindern: Der Nutzer will seine
    Wuerfe sehen, auch wenn die Datenbank noch nicht eingerichtet ist.
    """
    # DER PIN SCORER ZUERST (siehe sinks/pins_scorer.py). Er wird ueber die
    # Umgebung eingeschaltet, nicht ueber die Konfiguration: Welche Datenbank
    # und welcher Erkenner -- das gehoert zur INSTALLATION, und die Zugangsdaten
    # duerfen ohnehin nie in eine Datei, die in der Versionsverwaltung liegt.
    # Steht in der Umgebung nichts, bleibt alles beim Upstream-Weg darunter.
    eigener = aus_umgebung(video_id)
    if eigener is not None:
        return QueuedSink(
            eigener,
            spool_file=Path(cfg.output.supabase.spool_file)
            if cfg.output.supabase.spool_file else None,
            max_retries=cfg.output.supabase.max_retries,
            retry_delay_s=cfg.output.supabase.retry_delay_s,
            queue_size=cfg.output.supabase.queue_size,
            video_id=video_id,
            mit_bild=cfg.output.send_board_image,
            mit_vorher=cfg.output.send_board_before_image,
            # KEIN Spielname: Bei uns gehoert die Partie zum `spiel` in der
            # Datenbank, die Zuordnung macht die App. Eine Textspalte daneben
            # waere eine zweite, konkurrierende Wahrheit.
            game_name="",
            game_name_column="",
        )

    supabase = cfg.output.supabase
    if not supabase.enabled:
        if ENV_EIN in os.environ:
            # Hier steht der Schalter, aber `aus_umgebung` hat abgelehnt -- der
            # Grund steht eine Zeile vorher im Protokoll. Diese Meldung sagt,
            # was daraus folgt, damit nicht jemand eine halbe Stunde nach dem
            # Versand sucht, der nie eingerichtet war.
            log.warning("Es wird NICHTS versendet (siehe Meldung oben).")
        return NullSink()

    schluessel = os.environ.get(supabase.api_key_env, "")
    if not schluessel:
        log.warning(
            "Supabase ist eingeschaltet, aber die Umgebungsvariable '%s' ist "
            "leer -- es wird nichts versendet.", supabase.api_key_env,
        )
        return NullSink()

    # DIE ADRESSE KOMMT AUS DER UMGEBUNG, die Konfiguration ist nur Rueckfall.
    # Sie benennt die Datenbank eines bestimmten Vereins und hat in einer
    # Datei, die alle teilen, nichts verloren -- fuer jeden anderen Nutzer ist
    # sie ausserdem falsch.
    adresse = os.environ.get(supabase.url_env, "") or supabase.url
    if not adresse:
        log.warning(
            "Supabase ist eingeschaltet, aber es ist keine Adresse gesetzt "
            "(Umgebungsvariable '%s' oder 'output.supabase.url') -- es wird "
            "nichts versendet.", supabase.url_env,
        )
        return NullSink()

    try:
        innerer = SupabaseSink(
            url=adresse, table=supabase.table, api_key=schluessel,
            timeout_s=supabase.timeout_s, video_id=video_id,
            game_name=game_name, game_name_column=supabase.game_name_column,
        )
    except ValueError as exc:
        log.error("Supabase-Versand nicht moeglich: %s", exc)
        return NullSink()

    sink = QueuedSink(
        innerer,
        spool_file=Path(supabase.spool_file) if supabase.spool_file else None,
        max_retries=supabase.max_retries,
        retry_delay_s=supabase.retry_delay_s,
        queue_size=supabase.queue_size,
        video_id=video_id,
        mit_bild=cfg.output.send_board_image,
        mit_vorher=cfg.output.send_board_before_image,
        game_name=game_name,
        game_name_column=supabase.game_name_column,
    )

    # Was beim letzten Lauf liegengeblieben ist, zuerst nachliefern.
    try:
        nachgeliefert = sink.resend_spooled()
        if nachgeliefert:
            log.info("%d zwischengespeicherte Wuerfe nachgeliefert", nachgeliefert)
    except Exception as exc:  # noqa: BLE001
        log.warning("Nachliefern fehlgeschlagen: %s", exc)

    log.info("Wurfergebnisse gehen an %s/rest/v1/%s%s", supabase.url,
             supabase.table,
             f" als Spiel '{game_name}'" if game_name else "")
    return sink
