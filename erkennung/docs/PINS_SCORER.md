# Anbindung an den Pin Scorer

Diese Kopie von Kegel_CV schreibt die erkannten Würfe in die Datenbank des
**Pin Scorers** (`../supabase/schema.sql`), nicht in das Supabase-Projekt des
Urhebers. Diese Datei sagt, was dafür anders ist, wie man es einrichtet und wo
die Grenze zwischen Erkenner und App verläuft. Zur Herkunft des Ordners:
[../HERKUNFT.md](../HERKUNFT.md).

## Die Arbeitsteilung — eine Wahrheit, nicht zwei

| | kennt | schreibt |
|---|---|---|
| **Erkenner** (dieser Ordner) | Bahn, gefallene Kegel, Zeit | die *gemessenen* Spalten von `erkannter_wurf` |
| **App** (Pin Scorer) | Bahnplan, Bahnwechsel, Duo-Tausch, Sätze, Teilsätze, Wertung | die *zugeordneten* Spalten: `spiel_id`, `satz_block_id`, `wurf_index` |

Der Erkenner erfährt **nicht**, welches Spiel läuft, wer wirft oder in welchem
Satz. Das ist keine Sparsamkeit, sondern der Kern: Beide Seiten könnten Spieler
und Satz herleiten, und sobald sie es beide tun, laufen die Ergebnisse
auseinander. Upstream ist aus genau diesem Grund schon so gebaut — die gelesene
Wurfnummer löschte dort einmal 28 % der Würfe (BUG-008), die Spielerkennung nach
30 Würfen traf den Bahnwechsel nicht, die laufende Summe driftete ab. Die
Begründung steht ausführlich in `src/kegel_cv/sinks/payload.py`.

Wie die App zuordnet (`erkenner_id` → Bahn → Anlage → laufendes Spiel →
`computeBahnState`), steht in `../docs/wurferkennung-plan.md`. Diese Seite ist
noch nicht gebaut; der Erkenner schreibt bereits.

## Mehrere Spiele gleichzeitig auf einer Anlage

Vorgesehen und ohne Zusatzaufwand: Ein Erkenner, der alle vier Tafeln sieht,
schreibt die Würfe aller vier Bahnen in dieselbe Tabelle. Läuft auf Bahn 2+3 ein
Spiel und auf 4+5 ein zweites, holt sich jedes Erfassungsgerät nur die Zeilen
*seiner* Bahnen — `erkannter_wurf.spiel_id` steht je Zeile, nicht je Anlage.

Die Datenbank setzt das durch, nicht die App: `pins_wurf_lesbar(erkenner_id,
lane)` in `supabase/policies.sql` gibt eine Zeile nur frei, wenn die Bahn zu
einem laufenden Spiel gehört, in dem ich Mitglied bin. Das Gerät von Spiel A
sieht die Würfe von Spiel B also nicht und kann sie auch nicht als übernommen
markieren.

Welche Bahn eine gemeldete `lane` meint, sagt `pins_erkenner_bahn(erkenner_id,
lane)`: die gekoppelte `bahn_id`, sonst `erkenner.bahn_zuordnung`, sonst die
gemeldete Zahl selbst. Die App muss dieselbe Übersetzung anwenden, bevor sie
eine Zeile einem Satz zuordnet.

## Einrichten

### 1. Tabellen anlegen

`supabase/schema.sql` und danach `supabase/policies.sql` im SQL-Editor
einspielen — wie bei jeder Schemaänderung des Pin Scorers, **erst Test-DB,
dann Prod**. Beide Dateien sind idempotent; die neuen Teile stehen am Ende unter
„Wurferkennung".

Angelegt werden `erkenner` (die registrierten Geräte) und `erkannter_wurf` (ein
Wurf je Zeile, mit Realtime). Eine nummerierte Migration braucht es nicht: hier
wird kein Altbestand umgebaut.

### 2. Login für den Erkenner anlegen

Dashboard → **Authentication → Users → Add user**: E-Mail und Passwort, *Auto
Confirm* an. Das ist ein Zugang für ein **Gerät**, kein Mensch — also eine
eigene Adresse (z. B. `erkennung-bahn@…`), nicht die eigene.

Was dieser Zugang darf, steht in `supabase/policies.sql`: Würfe für seine eigene
`erkenner_id` einfügen. Nicht lesen, nicht ändern, nicht löschen, kein Blick in
Spiele, Profile oder Namen. Der schlimmste Fall eines gestohlenen Zugangs ist
„jemand schleust falsche Würfe ein"; das Gegenmittel ist ein neues Passwort.

> **Kein geheimer Schlüssel auf dem Rechner an der Bahn.** `sb_secret_` /
> `service_role` umgeht die Zeilen-Sicherheit vollständig — wer ihn hat, liest
> und schreibt die ganze Datenbank, auch Klarnamen und fremde Spiele. Der
> Versand weist einen solchen Schlüssel deshalb aktiv ab.

### 3. Erkenner eintragen

Im SQL-Editor (der läuft als `postgres`, also ohne `auth.uid()` — die beiden
Konten stehen deshalb ausgeschrieben):

```sql
-- Die ids heraussuchen:
select id, email from auth.users where email in ('erkennung-bahn@example.org', 'ich@example.org');
select id, name  from anlage;

insert into erkenner (name, anlage_id, bahn_id, konto, besitzer)
values (
  'Bahn-Rechner',
  '<anlage.id>',      -- NULL bei einem mobilen Erkenner ohne feste Anlage
  null,               -- oder eine bahn.id, wenn er genau EINE Bahn liest
  '<auth.users.id des Erkenner-Logins>',
  '<auth.users.id von mir>'
)
returning id;         -- das ist die PINS_SCORER_ERKENNER
```

Liest der Erkenner mehrere Bahnen (der Normalfall: eine Kamera sieht alle vier
Tafeln), bleibt `bahn_id` leer — die Bahn steht dann in jeder Zeile. Zählt
Kegel_CV die Tafeln nur von links, weil auf ihnen keine Bahnnummern kalibriert
sind, übersetzt `erkenner.bahn_zuordnung` das:

```sql
update erkenner set bahn_zuordnung = '{"1":2,"2":3,"3":4,"4":5}' where id = '<erkenner.id>';
```

### 4. `.env` auf dem Erkenner-Rechner

Nach `.env` im Wurzelverzeichnis dieses Ordners (die Datei ist von der
Versionsverwaltung ausgeschlossen, Vorlage: [`../.env.example`](../.env.example)):

```
PINS_SCORER=1
PINS_SCORER_URL=https://<projekt>.supabase.co
PINS_SCORER_KEY=sb_publishable_…
PINS_SCORER_ERKENNER=<erkenner.id aus Schritt 3>
PINS_SCORER_EMAIL=erkennung-bahn@example.org
PINS_SCORER_PASSWORT=…
```

`PINS_SCORER_TABELLE` ist optional (Vorgabe `erkannter_wurf`). Beim nächsten
Analyselauf steht im Protokoll:

```
Erkannte Wuerfe gehen an https://<projekt>.supabase.co/rest/v1/erkannter_wurf als Erkenner …
Am Pin Scorer angemeldet als erkennung-bahn@example.org (neu)
```

Fehlt ein Wert, wird **nicht** gesendet, die Analyse läuft weiter, und im
Protokoll steht, welcher Wert fehlt. Stumm nichts zu senden ist der eine Fehler,
der einen ganzen Spieltag kostet.

Prüfen, ohne auf ein Spiel zu warten:

```
python tools/pins_scorer_pruefen.py          # nur anmelden
python tools/pins_scorer_pruefen.py --wurf   # und einen Probewurf einfügen
```

## Was am Upstream-Code geändert wurde

Drei Stellen — alles andere steht in eigenen Dateien, damit der nächste Abgleich
mit <https://github.com/ni5080/Kegel_CV> klein bleibt:

| Datei | Änderung |
|---|---|
| `src/kegel_cv/sinks/pins_scorer.py` | **neu** — Anmeldung als Benutzer, `erkenner_id` je Zeile |
| `src/kegel_cv/sinks/supabase.py` | Kopfzeilen des POST in `_kopfzeilen()` ausgelagert, damit ein anderer Anmeldeweg sie ersetzen kann (20 Zeilen) |
| `src/kegel_cv/sinks/factory.py` | Weiche: steht der Pin Scorer in der Umgebung, geht es dorthin (sonst unverändert) |
| `tests/unit/test_pins_scorer.py` | **neu** — 24 Tests, Schwerpunkt Zugang |
| `tools/pins_scorer_pruefen.py` | **neu** — Anmeldung und Versand prüfen, ohne Video |

Eingeschaltet wird über die **Umgebung**, nicht über `config/default.yaml`:
Welche Datenbank und welcher Erkenner — das gehört zur Installation, nicht in
eine Datei, die in der Versionsverwaltung liegt. `output.supabase.*` bleibt
unberührt und schreibt weiter dorthin, wohin es upstream schreibt.

Mitbenutzt, nicht nachgebaut: `QueuedSink` (die Analyse hängt nie am Versand,
Netzausfälle landen in `debug/versand_puffer.jsonl` und gehen beim nächsten
Start raus) und `BahnFilterSink` (welche Bahnen dieses Gerät sendet — nötig,
sobald zwei Erkenner dieselbe Halle sehen).

## Tafelbilder

Jeder Wurf bringt den Ausschnitt der Anzeigetafel als Base64-JPEG mit
(`board_jpeg`, davor `board_before_jpeg`) — der Beleg zum Wert, wenn ein
Ergebnis angezweifelt wird. Rund 4,8 KB je Wurf, also etwa 9 MB je Spieltag.

Zwei Dinge dazu:

* **In Listen nie mitladen.** `select id, lane, pins, pins_count, recorded_at
  from erkannter_wurf …` — das Bild nur für den einen Wurf, den jemand ansieht.
* **Es ist ein Foto aus der Halle.** Im Ausschnitt der Tafel können Menschen
  auftauchen (upstream BUG-025). Abschaltbar in `config/default.yaml` unter
  `output: send_board_image: false`; gelöscht werden die Bilder über die
  `erkannter_wurf`-Zeilen, die beim Löschen des Spiels mitgehen
  (`on delete cascade`).
