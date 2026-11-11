"""Prueft die Verbindung zu Supabase -- und sagt konkret, was noch fehlt.

Zweck: Wer den Versand einrichtet, soll nicht raten muessen. Dieses Werkzeug
geht die Einstellungen der Reihe nach durch, benennt jede Luecke mit dem
noetigen Handgriff und schickt am Ende eine deutlich markierte Testzeile.

Aufruf:
    .venv/Scripts/python.exe tools/test_supabase.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from kegel_cv.config import load_config
from kegel_cv.models.throw import ThrowResult, ThrowStatus
from kegel_cv.sinks.supabase import SupabaseError, SupabaseSink

TESTKENNUNG = "VERBINDUNGSTEST"

# Wichtig: VOR `load_config()` festhalten, was schon in der Umgebung stand.
# Der Loader schreibt die Werte aus `.env` nur dann hinein, wenn der Name dort
# noch fehlt (`config/loader.py`) -- danach ist nicht mehr zu unterscheiden,
# woher ein Wert kam.
_UMGEBUNG_VORHER = dict(os.environ)


def _herkunft(name: str, wert: str) -> str:
    """Sagt, WOHER der Schluessel kommt -- Umgebung oder `.env`.

    Das klingt nach Kleinkram, hat aber einen Nachmittag gekostet: In der
    Benutzerumgebung stand aus einem frueheren `setx` noch ein alter
    Schluessel. Der hat Vorrang vor `.env`, also blieb jede Aenderung an der
    Datei wirkungslos -- und das Werkzeug meldete brav "ok". Wer den Wert
    aendert und nichts passieren sieht, soll hier lesen koennen, warum.
    """
    aus_umgebung = _UMGEBUNG_VORHER.get(name, "")
    if not aus_umgebung:
        return "aus .env"

    datei = Path(__file__).resolve().parents[1] / ".env"
    aus_datei = ""
    if datei.is_file():
        for zeile in datei.read_text(encoding="utf-8").splitlines():
            if zeile.strip().startswith(f"{name}="):
                aus_datei = zeile.split("=", 1)[1].strip().strip('"').strip("'")

    if aus_datei and aus_datei != wert:
        return ("AUS DER UMGEBUNG -- und sie ueberstimmt einen ANDEREN Wert "
                "in .env")
    return "aus der Umgebung"


def pruefen(nur_pruefen: bool = False) -> int:
    cfg = load_config()
    supabase = cfg.output.supabase

    print("=" * 64)
    print("VERBINDUNGSTEST SUPABASE")
    print("=" * 64)

    fehlt: list[str] = []

    # --- 1. Ist der Versand eingeschaltet? ---
    if supabase.enabled:
        print("  [ok]     Versand ist eingeschaltet")
    else:
        print("  [FEHLT]  Versand ist ausgeschaltet")
        fehlt.append(
            "In config/default.yaml unter 'output: supabase:' setzen:\n"
            "             enabled: true"
        )

    # --- 2. Ist die Projekt-URL eingetragen? ---
    if supabase.url:
        print(f"  [ok]     URL: {supabase.url}")
        if not supabase.url.startswith("https://"):
            fehlt.append(f"Die URL sollte mit https:// beginnen: {supabase.url}")
    else:
        print("  [FEHLT]  Keine Projekt-URL")
        fehlt.append(
            "Im Supabase-Dashboard: Settings -> API -> 'Project URL'\n"
            "             (sieht aus wie https://abcdefgh.supabase.co)\n"
            "             In config/default.yaml eintragen unter url:"
        )

    # --- 3. Liegt der Schluessel in der Umgebungsvariablen? ---
    schluessel = os.environ.get(supabase.api_key_env, "")
    if schluessel:
        # Supabase hat die Schluessel umbenannt: Aus 'anon' wurde der
        # 'publishable key'. Beide Formen funktionieren identisch -- aber der
        # geheime Schluessel umgeht die RLS-Regeln und gehoert nicht hierher.
        if schluessel.startswith("sb_secret_"):
            art = "GEHEIMER Schluessel (sb_secret_)"
        elif schluessel.startswith("sb_publishable_"):
            art = "publishable key"
        elif schluessel.startswith("eyJ"):
            art = "anon/service_role (Legacy-Format)"
        else:
            art = "unbekanntes Format"
        herkunft = _herkunft(supabase.api_key_env, schluessel)
        print(f"  [ok]     Schluessel in {supabase.api_key_env} "
              f"({len(schluessel)} Zeichen, {art}, {herkunft})")
        if "ueberstimmt" in herkunft:
            print("           ACHTUNG: Die .env wird NICHT verwendet. Eine "
                  "Aenderung dort bleibt wirkungslos,")
            print("           solange diese Umgebungsvariable gesetzt ist. "
                  "Entfernen mit:")
            print("               [Environment]::SetEnvironmentVariable("
                  f"'{supabase.api_key_env}', $null, 'User')")
            print("           Danach ein NEUES Terminal oeffnen -- laufende "
                  "Prozesse behalten ihre Kopie.")
        if schluessel.startswith("sb_secret_"):
            # Seit dem 2026-09-07 ist das der RICHTIGE Schluessel fuer diese
            # Seite: `anon` darf auf der Tabelle nur noch lesen, schreiben kann
            # nur, wer RLS umgeht. Frueher stand hier eine Warnung -- die waere
            # jetzt falscher Rat.
            print("           Hinweis: Umgeht die RLS-Regeln -- fuer die "
                  "schreibende Seite ist das richtig so.")
            print("           Er gehoert NUR hierher (lokal). Niemals in den "
                  "Liveticker oder eine Webseite.")
    else:
        print(f"  [FEHLT]  Umgebungsvariable {supabase.api_key_env} ist leer")
        # Supabase hat die Oberflaeche umgestellt: Die alten Schluessel 'anon'
        # und 'service_role' unter Settings -> API heissen inzwischen anders.
        # Beide Wege werden genannt, weil je nach Projektalter mal der eine,
        # mal der andere zu sehen ist.
        fehlt.append(
            "Den Schluessel im Supabase-Dashboard holen. Je nach Version:\n"
            "               A) Seitenleiste 'API Keys' -> 'Publishable key'\n"
            "                  (beginnt mit sb_publishable_...)\n"
            "               B) Settings -> API -> 'Legacy API keys' -> 'anon'\n"
            "                  (beginnt mit eyJhbGciOi...)\n"
            "             NICHT den geheimen Schluessel nehmen -- der umgeht die\n"
            "             RLS-Regeln, die du gerade angelegt hast.\n"
            "             Dann setzen mit:\n"
            f"               setx {supabase.api_key_env} \"...\"\n"
            "             DANACH das Terminal neu oeffnen -- sonst wirkt es nicht."
        )

    print(f"  [info]   Tabelle: {supabase.table}")

    if fehlt:
        print("\n" + "-" * 64)
        print("NOCH ZU TUN:\n")
        for i, aufgabe in enumerate(fehlt, start=1):
            print(f"  {i}. {aufgabe}\n")
        print("Danach dieses Werkzeug erneut aufrufen.")
        return 1

    # --- 4. Wirklich senden ---
    print("\n" + "-" * 64)

    if nur_pruefen:
        # Fuer die Gegenprobe nach einer Rechteaenderung: Man will wissen, ob
        # die Einstellungen stimmen, ohne dafuer jedes Mal eine Zeile in der
        # Tabelle zu hinterlassen, die hinterher wieder wegmuss.
        print("Nur geprueft -- keine Testzeile gesendet.")
        print("(Ohne --nur-pruefen wird eine geschickt.)")
        return 0

    print("Sende eine Testzeile ...\n")

    probe = ThrowResult(
        lane=99, throw_number=999, throw_number_in_series=1,
        pins=(1, 2, 3), pins_count=3, displayed_pin_count=3,
        status=ThrowStatus.VALID, running_total=3, confidence=1.0,
    )
    sink = SupabaseSink(url=supabase.url, table=supabase.table,
                        api_key=schluessel, timeout_s=supabase.timeout_s,
                        video_id=TESTKENNUNG)
    try:
        sink.send(probe)
    except SupabaseError as exc:
        print(f"  FEHLGESCHLAGEN: {exc}\n")
        print("  Haeufige Ursachen:")
        print("    HTTP 401/403  -> falscher Schluessel, oder die RLS-Regel")
        print("                     'einfuegen erlaubt' fehlt")
        print("    HTTP 404      -> Tabellenname stimmt nicht, oder die URL")
        print("    HTTP 400      -> eine Spalte fehlt in der Tabelle; der Text")
        print("                     oben nennt sie beim Namen")
        print("    nicht erreichbar -> URL pruefen, Internetverbindung")
        return 1

    print("  ERFOLG -- die Zeile ist in der Tabelle.\n")
    print("  Nachsehen im Dashboard unter 'Table Editor' -> throws.")
    print(f"  Sie ist an video_id = '{TESTKENNUNG}' und lane = 99 erkennbar.\n")
    print("  Wieder loeschen mit diesem SQL:")
    print(f"      delete from {supabase.table} where video_id = '{TESTKENNUNG}';")
    print("\n  Der Versand ist eingerichtet. Ab jetzt geht jeder erkannte Wurf")
    print("  waehrend der Analyse automatisch raus.")
    return 0


if __name__ == "__main__":
    sys.exit(pruefen(nur_pruefen="--nur-pruefen" in sys.argv[1:]))
