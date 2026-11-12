"""Traegt einen Erkenner in die Tabelle `erkenner` ein -- und sagt, was in die .env gehoert.

    python tools/erkenner-eintragen.py . --email erkennung@example.org
    python tools/erkenner-eintragen.py . --email … --name "Telefon Bahn 5" --bahn 5

Braucht `psycopg2` und den Zugang in `supabase/.db-test.env` (siehe
tools/rls-erkennung-pruefen.py). Fuer Prod denselben Weg mit der Prod-Verbindung --
deshalb ist die Datenbank hier ein Parameter und nicht fest eingebaut.

WARUM UEBERHAUPT EIN WERKZEUG: Die Zeile von Hand im SQL-Editor zusammenzusetzen heisst,
drei uuids richtig abzuschreiben (Login, Anlage, eigenes Konto). Genau dabei entsteht der
Fehler, der am Spieltag nicht zu finden ist: Ein Erkenner, dessen `konto` nicht zum Login in
der .env gehoert, darf nichts einfuegen -- und die Meldung sagt nur "row-level security".

Was es NICHT tut: den Login anlegen. Der entsteht im Dashboard unter
Authentication -> Add user (mit "Auto Confirm"), damit das Passwort bei dir bleibt; es
gehoert direkt in erkennung/.env als PINS_SCORER_PASSWORT.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import psycopg2


def pgurl(wurzel: Path, datei: str) -> str:
    pfad = wurzel / "supabase" / datei
    if not pfad.is_file():
        raise SystemExit(f"{pfad} fehlt -- dort gehoert PGURL=postgresql://… hinein.")
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        if zeile.startswith("PGURL="):
            return zeile.split("=", 1)[1].strip()
    raise SystemExit(f"Kein PGURL in {pfad}")


def main() -> int:
    z = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    z.add_argument("wurzel", help="Projektverzeichnis (meist .)")
    z.add_argument("--email", required=True, help="Login des Erkenners (muss schon existieren)")
    z.add_argument("--name", default="Bahn-Rechner", help="Anzeigename des Erkenners")
    z.add_argument("--anlage", default=None,
                   help="Name oder id der Anlage; weglassen, wenn es nur eine gibt")
    z.add_argument("--bahn", type=int, default=None,
                   help="Nummer der EINEN Bahn, die dieser Erkenner liest "
                        "(weglassen, wenn er mehrere Tafeln sieht)")
    z.add_argument("--db", default=".db-test.env", help="Zugangsdatei unter supabase/")
    a = z.parse_args()

    wurzel = Path(a.wurzel).resolve()
    conn = psycopg2.connect(pgurl(wurzel, a.db), sslmode="require", connect_timeout=15)
    conn.autocommit = False
    cur = conn.cursor()

    # --- Login ---------------------------------------------------------------
    cur.execute("select id, email_confirmed_at is not null from auth.users where email = %s",
                [a.email])
    treffer = cur.fetchone()
    if not treffer:
        print(f"ABBRUCH: Kein Login {a.email} in DIESER Datenbank.")
        print("  Anlegen: Dashboard -> Authentication -> Add user, mit 'Auto Confirm'.")
        print("  Haeufige Verwechslung: im Prod-Projekt angelegt statt im Test-Projekt.")
        return 1
    konto, bestaetigt = treffer
    if not bestaetigt:
        print(f"WARNUNG: {a.email} ist nicht bestaetigt -- die Anmeldung wird scheitern.")
        print("  Im Dashboard den Benutzer bestaetigen ('Confirm email').")

    # --- Anlage --------------------------------------------------------------
    if a.anlage:
        cur.execute("select id, name, besitzer from anlage where id::text = %s or name ilike %s",
                    [a.anlage, f"%{a.anlage}%"])
    else:
        cur.execute("select id, name, besitzer from anlage")
    anlagen = cur.fetchall()
    if len(anlagen) != 1:
        print(f"ABBRUCH: {len(anlagen)} Anlagen passen -- bitte mit --anlage eingrenzen:")
        for x in anlagen:
            print(f"  {x[0]}  {x[1]}")
        return 1
    anlage_id, anlage_name, anlage_besitzer = anlagen[0]
    if anlage_besitzer is None:
        print(f"ABBRUCH: Die Anlage {anlage_name} hat keinen Besitzer -- dann gibt es "
              "niemanden, der den Erkenner verwalten darf.")
        return 1

    # --- Bahn (optional) -----------------------------------------------------
    bahn_id = None
    if a.bahn is not None:
        cur.execute("select id from bahn where anlage_id = %s and nummer = %s",
                    [anlage_id, a.bahn])
        b = cur.fetchone()
        if not b:
            print(f"ABBRUCH: Bahn {a.bahn} gibt es auf {anlage_name} nicht.")
            return 1
        bahn_id = b[0]

    # --- Schon da? -----------------------------------------------------------
    cur.execute("select id, name from erkenner where konto = %s and anlage_id = %s",
                [konto, anlage_id])
    vorhanden = cur.fetchall()
    if vorhanden:
        print("Fuer diesen Login gibt es auf dieser Anlage schon Erkenner:")
        for x in vorhanden:
            print(f"  {x[0]}  {x[1]}")
        print("Mit --name einen weiteren anlegen, oder einen davon in die .env uebernehmen.")
        return 1

    cur.execute("""
      insert into erkenner (name, anlage_id, bahn_id, konto, besitzer)
      values (%s, %s, %s, %s, %s) returning id
    """, [a.name, anlage_id, bahn_id, konto, anlage_besitzer])
    erkenner_id = cur.fetchone()[0]
    conn.commit()

    print(f"Eingetragen: {a.name} auf {anlage_name}"
          + (f", Bahn {a.bahn}" if a.bahn is not None else ", alle Bahnen"))
    print("\nDas gehoert in erkennung/.env (das Passwort kennst nur du):\n")
    print("PINS_SCORER=1")
    print("PINS_SCORER_URL=https://<projekt>.supabase.co")
    print("PINS_SCORER_KEY=<publishable key>")
    print(f"PINS_SCORER_ERKENNER={erkenner_id}")
    print(f"PINS_SCORER_EMAIL={a.email}")
    print(f"PINS_SCORER_PASSWORT=<das Passwort aus dem Dashboard>")
    print("\nDanach pruefen: python erkennung/tools/pins_scorer_pruefen.py --wurf")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
