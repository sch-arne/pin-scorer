"""Prueft die RLS der Wurferkennung mit echten Rollen -- und raeumt restlos auf.

    python tools/rls-erkennung-pruefen.py .

Braucht `psycopg2` (nicht im Projekt, bewusst: dieses Skript laeuft von Hand, nicht in
der App) und den Zugang zur TEST-Datenbank in `supabase/.db-test.env`:

    python -m venv %TEMP%/pgvenv
    %TEMP%/pgvenv/Scripts/python.exe -m pip install psycopg2-binary
    %TEMP%/pgvenv/Scripts/python.exe tools/rls-erkennung-pruefen.py .

Nach jeder Aenderung an den Policies der Erkennung wiederholen. Die Pruefung ist das
Gegenstueck zu den Unit-Tests: Dass `ordneEvent` richtig entscheidet, sagt nichts darueber,
ob die Datenbank einem fremden Geraet wirklich den Zugriff verweigert.

Alles laeuft in EINER Transaktion, die am Ende zurueckgerollt wird: Die Testdaten
(Konten, Anlage, Erkenner, zwei gleichzeitig laufende Spiele) existieren nur waehrend
des Laufs. Danach ist die Datenbank Zeile fuer Zeile wie vorher.

Geprueft wird als die ECHTEN Rollen: `set local role authenticated` plus
`request.jwt.claims`, denn genau daraus liest `auth.uid()` (nachgesehen in dieser
Datenbank). Als Eigentuemer der Tabellen (postgres) waere RLS wirkungslos -- eine
Pruefung ohne Rollenwechsel wuerde alles durchlassen und nichts beweisen.

ACHTUNG, hier gestolpert: Ein `insert ... RETURNING` verlangt zusaetzlich die
LESE-Erlaubnis fuer die neue Zeile. Der Erkenner darf nicht lesen, also scheitert sein
Insert mit RETURNING -- mit einer Meldung, die auf die falsche Ursache zeigt
("new row violates row-level security policy"). Der Versand schickt deshalb
`Prefer: return=minimal`; das ist keine Sparsamkeit, sondern Voraussetzung.
"""
from pathlib import Path
import sys

import psycopg2

WURZEL = Path(sys.argv[1])
url = next(z.split("=", 1)[1].strip()
           for z in (WURZEL / "supabase" / ".db-test.env").read_text(encoding="utf-8").splitlines()
           if z.startswith("PGURL="))
assert "oizupdfesgihpzdzwvcw" in url, "nur die Test-Datenbank"

conn = psycopg2.connect(url, sslmode="require", connect_timeout=15)
conn.autocommit = False
cur = conn.cursor()

ergebnisse = []


def pruefe(titel, bedingung, info=""):
    ergebnisse.append((bool(bedingung), titel, info))
    print(f"{'ok  ' if bedingung else 'ROT '} {titel}" + (f"   [{info}]" if info else ""))


def erwarte_abweisung(titel, sql, args=None):
    cur.execute("savepoint s")
    try:
        cur.execute(sql, args)
        getroffen = cur.rowcount
        cur.execute("rollback to savepoint s")
        # 0 getroffene Zeilen ist bei update/delete die normale Form der Abweisung:
        # die Lese-Policy versteckt die Zeile, es gibt also nichts zu aendern.
        if getroffen == 0 and sql.strip().lower().startswith(("update", "delete")):
            pruefe(titel, True, "keine Zeile sichtbar")
        else:
            pruefe(titel, False, f"wurde ERLAUBT ({getroffen} Zeilen)")
    except psycopg2.Error as exc:
        cur.execute("rollback to savepoint s")
        pruefe(titel, True, f"abgewiesen, {exc.pgcode}")


def als(konto):
    cur.execute("reset role")
    cur.execute("select set_config('request.jwt.claims', %s, true)",
                ['{"sub":"%s","role":"authenticated"}' % konto])
    cur.execute("set local role authenticated")


def als_eigentuemer():
    cur.execute("reset role")


# ── Testdaten ───────────────────────────────────────────────────────────────
cur.execute("""
  insert into auth.users (id, email) values
    (gen_random_uuid(), 'rls-a@test.invalid'),
    (gen_random_uuid(), 'rls-b@test.invalid'),
    (gen_random_uuid(), 'rls-erkenner@test.invalid')
  returning id, email
""")
konten = {e.split('@')[0].replace('rls-', ''): i for i, e in cur.fetchall()}
A, B, E = konten['a'], konten['b'], konten['erkenner']

cur.execute("insert into anlage (name, besitzer, anzahl_bahnen) values ('RLS-Testanlage', %s, 4) returning id", [A])
anlage = cur.fetchone()[0]
cur.execute("insert into bahn (anlage_id, nummer) select %s, g from generate_series(2,5) g", [anlage])
cur.execute("insert into erkenner (name, anlage_id, konto, besitzer) values ('Testerkenner', %s, %s, %s) returning id",
            [anlage, E, A])
erkenner = cur.fetchone()[0]
cur.execute("insert into erkenner (name, anlage_id, konto, besitzer) values ('Fremder', %s, %s, %s) returning id",
            [anlage, A, A])
fremder = cur.fetchone()[0]


def spiel_anlegen(besitzer, bahnliste):
    cur.execute("""
      insert into spiel (besitzer, status, anlage_id, config_json)
      values (%s, 'laufend', %s, %s::jsonb) returning id
    """, [besitzer, anlage,
          '{"ersteBahn": %d, "bahnen": %d, "bahnListe": %s}'
          % (bahnliste[0], len(bahnliste), bahnliste)])
    sid = cur.fetchone()[0]
    cur.execute("insert into geraet (id, konto) values (gen_random_uuid(), %s) returning id", [besitzer])
    ger = cur.fetchone()[0]
    cur.execute("insert into spiel_geraet (spiel_id, geraet, konto) values (%s, %s, %s)", [sid, ger, besitzer])
    return sid


spiel_a = spiel_anlegen(A, [2, 3])
spiel_b = spiel_anlegen(B, [4, 5])
print(f"Zwei Spiele auf EINER Anlage: A auf Bahn 2+3, B auf Bahn 4+5\n")

cur.execute("select pins_spiel_bahnen(%s), pins_spiel_bahnen(%s)", [spiel_a, spiel_b])
bahnen_a, bahnen_b = cur.fetchone()
pruefe("pins_spiel_bahnen trennt die beiden Spiele", bahnen_a == [2, 3] and bahnen_b == [4, 5],
       f"A={bahnen_a} B={bahnen_b}")

# ── Der Erkenner-Login ──────────────────────────────────────────────────────
print("\n--- als Erkenner-Login ---")
als(E)

cur.execute("insert into erkannter_wurf (erkenner_id, lane, pins_count, pins) "
            "values (%s, 2, 9, '{1,2,3,4,5,6,7,8,9}')", [erkenner])
pruefe("darf einen Wurf fuer seinen eigenen Erkenner einfuegen", cur.rowcount == 1)
cur.execute("insert into erkannter_wurf (erkenner_id, lane, pins_count, pins) "
            "values (%s, 4, 7, '{1,2,3,4,5,6,7}')", [erkenner])

erwarte_abweisung("insert MIT returning scheitert (darf die Zeile nicht lesen)",
                  "insert into erkannter_wurf (erkenner_id, lane, pins_count) "
                  "values (%s, 2, 5) returning id", [erkenner])
erwarte_abweisung("darf NICHT fuer einen fremden Erkenner einfuegen",
                  "insert into erkannter_wurf (erkenner_id, lane, pins_count) values (%s, 2, 5)",
                  [fremder])
erwarte_abweisung("darf NICHT gleich eine Zuordnung mitschreiben",
                  "insert into erkannter_wurf (erkenner_id, lane, pins_count, spiel_id) "
                  "values (%s, 2, 5, %s)", [erkenner, spiel_a])
erwarte_abweisung("darf uebernommen_am nicht setzen",
                  "insert into erkannter_wurf (erkenner_id, lane, pins_count, uebernommen_am) "
                  "values (%s, 2, 5, now())", [erkenner])
erwarte_abweisung("darf verworfen_grund nicht setzen",
                  "insert into erkannter_wurf (erkenner_id, lane, pins_count, verworfen_grund) "
                  "values (%s, 2, 5, 'egal')", [erkenner])

cur.execute("select count(*) from erkannter_wurf")
pruefe("darf NICHTS lesen", cur.fetchone()[0] == 0, "select liefert 0 Zeilen")
cur.execute("select count(*) from spiel")
pruefe("sieht keine Spiele", cur.fetchone()[0] == 0)
cur.execute("select count(*) from profil")
pruefe("sieht keine Profile", cur.fetchone()[0] == 0)
cur.execute("select count(*) from spiel_spieler")
pruefe("sieht keine Spielernamen", cur.fetchone()[0] == 0)
erwarte_abweisung("darf keinen Wurf loeschen", "delete from erkannter_wurf")

als_eigentuemer()
cur.execute("update erkenner set aktiv = false where id = %s", [erkenner])
als(E)
erwarte_abweisung("aktiv = false sperrt das Einfuegen",
                  "insert into erkannter_wurf (erkenner_id, lane, pins_count) values (%s, 2, 5)",
                  [erkenner])
als_eigentuemer()
cur.execute("update erkenner set aktiv = true where id = %s", [erkenner])
cur.execute("select id, lane from erkannter_wurf order by lane")
ids = dict((lane, i) for i, lane in cur.fetchall())
wurf2, wurf4 = ids[2], ids[4]

# ── Das Geraet von Spiel A ──────────────────────────────────────────────────
print("\n--- als Geraet von Spiel A (Bahn 2+3; A besitzt auch die Anlage) ---")
als(A)
cur.execute("select lane from erkannter_wurf order by lane")
sichtbar = [z[0] for z in cur.fetchall()]
pruefe("sieht die Wuerfe (als Anlagen-Besitzer alle seiner Anlage)", sichtbar == [2, 4],
       f"sichtbar: {sichtbar}")
cur.execute("update erkannter_wurf set spiel_id = %s, uebernommen_am = now() where id = %s",
            [spiel_a, wurf2])
pruefe("darf einen Wurf seiner Bahn zuordnen", cur.rowcount == 1)

# ── Das Geraet von Spiel B ──────────────────────────────────────────────────
print("\n--- als Geraet von Spiel B (Bahn 4+5), ohne Anlagenbesitz ---")
als(B)
cur.execute("select lane from erkannter_wurf order by lane")
sichtbar_b = [z[0] for z in cur.fetchall()]
pruefe("sieht NUR die Wuerfe seiner Bahnen", sichtbar_b == [4],
       f"sichtbar: {sichtbar_b} — Bahn 2 gehoert Spiel A")
erwarte_abweisung("darf den Wurf von Bahn 2 nicht auf sein Spiel umschreiben",
                  "update erkannter_wurf set spiel_id = %s where id = %s", [spiel_b, wurf2])
erwarte_abweisung("darf nichts loeschen (nicht Verwalter)",
                  "delete from erkannter_wurf where id = %s", [wurf4])
cur.execute("update erkannter_wurf set spiel_id = %s where id = %s", [spiel_b, wurf4])
pruefe("darf seinen eigenen Wurf zuordnen", cur.rowcount == 1)

# ── Bahnuebersetzung ────────────────────────────────────────────────────────
print("\n--- Tafelposition statt Bahnnummer ---")
als_eigentuemer()
cur.execute("update erkenner set bahn_zuordnung = '{\"1\":2,\"2\":3,\"3\":4,\"4\":5}' where id = %s", [erkenner])
cur.execute("select pins_erkenner_bahn(%s, 1), pins_erkenner_bahn(%s, 3)", [erkenner, erkenner])
pruefe("pins_erkenner_bahn uebersetzt Tafelposition -> Bahn", cur.fetchone() == (2, 4))
als(E)
cur.execute("insert into erkannter_wurf (erkenner_id, lane, pins_count) values (%s, 3, 6)", [erkenner])
als_eigentuemer()
cur.execute("select id from erkannter_wurf where lane = 3")
pos3 = cur.fetchone()[0]
als(B)
cur.execute("select count(*) from erkannter_wurf where id = %s", [pos3])
pruefe("Tafelposition 3 ist fuer Spiel B die Bahn 4 und damit sichtbar", cur.fetchone()[0] == 1)
als(A)
cur.execute("select count(*) from erkannter_wurf where id = %s", [pos3])
pruefe("… und fuer A nur, weil er die Anlage besitzt", cur.fetchone()[0] == 1)

# ── Kein laufendes Spiel mehr ───────────────────────────────────────────────
print("\n--- wenn kein Spiel mehr laeuft ---")
als_eigentuemer()
cur.execute("insert into erkannter_wurf (erkenner_id, lane, pins_count) values (%s, 5, 3)", [erkenner])
cur.execute("update spiel set status = 'beendet' where id = %s", [spiel_b])
als(B)
cur.execute("select count(*) from erkannter_wurf where spiel_id is null")
pruefe("nach Spielende keine unzugeordneten Wuerfe mehr sichtbar", cur.fetchone()[0] == 0)
cur.execute("select count(*) from erkannter_wurf where spiel_id = %s", [spiel_b])
pruefe("der bereits zugeordnete Wurf bleibt lesbar (Beleg im Wurfprotokoll)",
       cur.fetchone()[0] == 1)

# ── Aufraeumen ──────────────────────────────────────────────────────────────
als_eigentuemer()
conn.rollback()
for frage, titel in [
    ("select count(*) from erkannter_wurf", "erkannter_wurf"),
    ("select count(*) from erkenner", "erkenner"),
    ("select count(*) from anlage where name = 'RLS-Testanlage'", "Testanlage"),
    ("select count(*) from auth.users where email like 'rls-%@test.invalid'", "Testkonten"),
    ("select count(*) from spiel where status = 'laufend'", "laufende Spiele"),
]:
    cur.execute(frage)
    print(f"nach dem Zuruecknehmen — {titel}: {cur.fetchone()[0]}")
conn.rollback()
conn.close()

rot = [t for ok, t, _ in ergebnisse if not ok]
print(f"\n=== {len(ergebnisse) - len(rot)} von {len(ergebnisse)} Pruefungen gruen ===")
for t in rot:
    print(f"ROT: {t}")
raise SystemExit(1 if rot else 0)
