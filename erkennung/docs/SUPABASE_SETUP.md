# Ergebnisse live an Supabase schicken

Jeder erkannte Wurf geht sofort als eine Zeile raus. Eine andere Anwendung — die
des Spielleiters — kann die Tabelle per Realtime abonnieren und bekommt den Wurf,
während noch gespielt wird.

## 1. Tabelle anlegen

Im Supabase-Dashboard unter **SQL Editor** ausführen:

```sql
create table if not exists throws (
    id            bigint generated always as identity primary key,

    video_id      text,                 -- welche Aufnahme / Übertragung
    lane          int  not null,        -- Bahnnummer laut Anzeigetafel
    pins_count    int  not null,        -- gefallene Kegel in diesem Wurf
    pins          int[],                -- welche Kegel (Nummern 1..9)
    video_time_s  real,                 -- Zeitpunkt im Video
    recorded_at   timestamptz not null default now()
);

create index if not exists throws_lane_time on throws (lane, recorded_at desc);

-- Realtime einschalten, damit Abonnenten sofort benachrichtigt werden
alter publication supabase_realtime add table throws;
```

### Das Tafelbild je Wurf (seit 2026-09-07)

Jeder Wurf kann den Ausschnitt der Anzeigetafel mitbringen, aus dem sein
Ergebnis stammt — der Beleg zum Wert. Dafür braucht die Tabelle eine Spalte:

```sql
alter table throws add column if not exists board_jpeg text;
alter table throws add column if not exists board_before_jpeg text;
```

Zwei Bilder je Wurf: `board_before_jpeg` zeigt die Tafel, **bevor**
geworfen wurde (beim Abräumen die Aufstellung, in die geworfen wird),
`board_jpeg` die Tafel danach.

Ohne die Spalte lehnt PostgREST den Insert ab; der Versand landet dann im
Puffer. **Erst die Spalte anlegen, dann den nächsten Lauf starten.**

Gespeichert wird ein Base64-JPEG des kalibrierten Tafelrechtecks — 152 × 154
Pixel, bei Qualität 40 rund 4,8 KB. Bei etwa 2000 Würfen je Spieltag sind das
9 MB. Kein eigener Speicher-Dienst: So gilt für das Bild dieselbe
Warteschlange und dieselbe Nachlieferung wie für den Wurf selbst.

Abschalten in `config/default.yaml` unter `output: send_board_image: false`.

**Nicht** in die Liveabfrage aufnehmen — der Ticker holt die Spalte nur für den
Wurf, den jemand anklickt:

```sql
select id, lane, pins, pins_count, recorded_at from throws;   -- Liste
select board_jpeg from throws where id = 4711;                -- ein Beleg
```

### Tabelle leeren

Vor einem Testtag, damit alte Läufe die neuen nicht überlagern. Im **SQL
Editor** ausführen:

```sql
truncate table throws restart identity;
```

`restart identity` setzt auch die `id` wieder auf 1. Ohne den Zusatz bleiben
die Zeilen gelöscht, die Nummerierung läuft aber weiter.

**Gezielter — nur eine bestimmte Aufnahme:**

```sql
delete from throws where video_id = 'name-der-aufnahme';
```

Welche `video_id` überhaupt vorkommen:

```sql
select video_id, count(*), min(recorded_at), max(recorded_at)
from throws group by video_id order by 3;
```

**Nur die Läufe von heute:**

```sql
delete from throws where recorded_at >= current_date;
```

> `truncate` und `delete` sind nicht rückgängig zu machen. Wenn die Daten noch
> gebraucht werden könnten, vorher sichern:
> `create table throws_sicherung as select * from throws;`

### Warum so wenige Spalten

**Übertragen wird nur, was gemessen ist.** Laufende Summe, Wurfnummer, Zyklus,
Spielnummer und Zwischensummen entstehen zwar weiterhin in der Auswertung und
stehen in der Oberfläche — gesendet werden sie nicht.

Der Grund ist Erfahrung aus diesem Projekt: Genau diese abgeleiteten Größen sind
schiefgegangen. Die aus der Anzeige gelesene Wurfnummer löschte 28 % der Würfe
(BUG-008). Die Spielerkennung nach 30 Würfen traf den Bahnwechsel nicht. Die
laufende Summe driftete von der Tafel ab, sobald ein Wurf fehlte.

Alle drei setzen **Regelwissen** voraus, das die auswertende Anwendung besser
kennt als eine Bilderkennung: wann ein Bahnwechsel ansteht, wann ein Spiel endet,
wie gewertet wird. Was hier gemessen wird, ist allein: *Auf dieser Bahn sind zu
diesem Zeitpunkt diese Kegel gefallen.*

### Wenn die Tabelle schon existiert

Die frühere Fassung hatte mehr Spalten, davon zwei mit `not null`, die jetzt
nicht mehr gefüllt werden. Ohne diese Anpassung wird **jeder Insert abgelehnt**:

```
HTTP 400: null value in column "throw_number" violates not-null constraint
```

Zum Beheben genügt:

```sql
alter table throws alter column throw_number drop not null;
alter table throws alter column status       drop not null;
```

Die alten Spalten bleiben erhalten und bleiben künftig leer — bestehende Zeilen
gehen dabei nicht verloren.

## 2. Schlüssel setzen

Der Schlüssel steht **nicht** in `config/default.yaml` — diese Datei liegt in der
Versionsverwaltung. Stattdessen in einer Datei `.env` in der Projektwurzel:

```
SUPABASE_KEY=sb_publishable_...
```

Sie wird beim Start automatisch gelesen (`config/loader.py`) und ist über
`.gitignore` ausgeschlossen.

Warum eine Datei und nicht `setx`: Der übliche Windows-Weg schreibt den Wert
dauerhaft in die Registrierung des Benutzers und wirkt erst in neu geöffneten
Terminals — beides überrascht regelmäßig. Eine Datei im Projekt ist sichtbar,
sofort wirksam und jederzeit löschbar. Eine bereits gesetzte Umgebungsvariable
hat trotzdem Vorrang: Wer den Wert bewusst im System hinterlegt hat, behält ihn.

### Welcher Schlüssel

Supabase hat die Benennung umgestellt. Je nach Alter des Projekts:

| Wo | Name | Format |
|---|---|---|
| Seitenleiste → **API Keys** | *Publishable key* | `sb_publishable_...` |
| Settings → API → **Legacy API keys** | *anon* | `eyJhbGciOi...` |

Beide funktionieren identisch. **Nicht** den geheimen Schlüssel (`sb_secret_`
bzw. `service_role`) nehmen — der umgeht die RLS-Regeln.

## 3. Einschalten

In `config/default.yaml`:

```yaml
output:
  supabase:
    enabled: true
    url: "https://abcdefgh.supabase.co"
    table: "throws"
```

Beim nächsten Analyselauf steht im Log:

```
Wurfergebnisse gehen an https://abcdefgh.supabase.co/rest/v1/throws
```

## Was passiert, wenn das Netz weg ist

Nichts geht verloren, und die Analyse hält nie an:

| Situation | Verhalten |
|---|---|
| Versand langsam | Die Analyse merkt nichts — `send` legt den Wurf nur in eine Warteschlange |
| Einzelner Fehler | Bis zu drei Versuche mit wachsendem Abstand |
| Netz länger weg | Der Wurf landet in `debug/versand_puffer.jsonl` |
| Nächster Start | Gepufferte Würfe werden zuerst nachgeliefert |
| Schlüssel fehlt | Warnung im Log, Analyse läuft normal weiter |

Der Grund für diesen Aufwand: **Die Kegel sind gefallen, ob die Datenbank
erreichbar ist oder nicht.** Ein Ergebnis darf nicht daran scheitern, dass gerade
jemand ein Kabel gezogen hat.

## Live mitlesen

Die Anwendung des Spielleiters abonniert die Tabelle:

```js
const kanal = supabase
  .channel('wuerfe')
  .on('postgres_changes',
      { event: 'INSERT', schema: 'public', table: 'throws' },
      ({ new: wurf }) => {
          console.log(`Bahn ${wurf.lane}: ${wurf.pins_count} Kegel `
                    + `(${wurf.pins.join(", ")})`);
      })
  .subscribe();
```

Summen, Wurfnummern und Spielstände entstehen **auf dieser Seite** — die
Anwendung kennt die Regeln (Bahnwechsel, Spielende, Wertung), die Bilderkennung
nicht.

## Kein Videostream — noch nicht

Der Versand ist fertig, die **Stream-Quelle noch nicht**. `VideoSource` ist
bewusst abstrakt und `FileVideoSource` nur eine Implementierung; eine
`StreamVideoSource` tritt an dieselbe Stelle, ohne dass Analyse oder Erkennung
etwas merken. Dass `cv2.VideoCapture` in `analysis/` und `detection/` nicht
vorkommen darf, prüft `tests/unit/test_architecture.py` — genau dafür.

Offen ist dabei vor allem, was bei einem Aussetzer der Verbindung geschehen
soll: Bei einer Datei kann man zurückspringen, bei einem Stream nicht. Das
gehört gemessen, bevor es gebaut wird.
