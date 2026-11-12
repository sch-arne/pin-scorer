# Plan: automatische Wurfbild-Erkennung an die App andocken

Stand: 12.11.2026 · Status: vollständig gebaut und gegen die Test-Datenbank gefahren; die Wurfnummer der Tafel bestimmt den Platz

> ## Was seit dem 01.09. daraus geworden ist
>
> Der Plan unten ist weiter gültig, mit drei Abweichungen — jede davon, weil sich die
> Annahme als falsch oder überholt erwiesen hat:
>
> **1. Die Erkennung ist nicht extern, sie liegt im Repo.** [Kegel_CV](https://github.com/ni5080/Kegel_CV)
> ist als `erkennung/` kopiert und schreibt in UNSERE Datenbank, Tabelle `erkannter_wurf`
> (Einrichtung: [`erkennung/docs/PINS_SCORER.md`](../erkennung/docs/PINS_SCORER.md),
> Herkunft: [`erkennung/HERKUNFT.md`](../erkennung/HERKUNFT.md)). Damit entfällt die
> Transportfrage aus Abschnitt 2: es ist Variante B, aber ohne fremdes Projekt — der
> Erkenner hat einen eigenen Login und darf ausschließlich Rohzeilen einfügen.
>
> **2. Der Kontrakt sieht anders aus als in Abschnitt 1.** Gesendet werden die GEFALLENEN
> Kegel, nicht die stehenden, und es gibt weder `bildVor` noch `seq` noch `konfidenz` —
> der Erkenner schickt Bahn, Anzahl, Kegelnummern, Zeit und vier nullbare Ablesungen der
> Tafel. Die Drift-Erkennung aus Abschnitt 4 kann sich deshalb nicht auf einen gemeldeten
> Vorzustand stützen; sie hängt allein an der Abräum-Kette. Die Anforderungen 2, 3, 5 und 6
> sind damit gegenstandslos. Anforderung 1 (Wurf-Trigger auch bei 0 Holz) ist erfüllt —
> gemessen, 0-Holz-Würfe stehen in den Daten.
>
> **3. Phasen 1 und 2 sind gebaut** — alles, was ohne Oberfläche geht:
>
> | Stück | Datei | Tests |
> |---|---|---|
> | Zuordnung eines Wurfs | [`js/logic/erkennung-zuordnung.js`](../js/logic/erkennung-zuordnung.js) | 25 |
> | Reihenfolge, Entdopplung, Puffer je Bahn, Betriebsmodus | [`js/logic/erkennung-strom.js`](../js/logic/erkennung-strom.js) | 19 |
> | Wurf an ein explizites Ziel schreiben (`addWurfAn`) | `js/views/spiel-laufend.js` | E2E |
>
> Darunter ein Durchlauf gegen eine echte Aufzeichnung (65 Würfe, 08.09.2026): 60 sauber
> zuordenbar, 5 angemahnt, und jeder Abräum-Wurf, der die Kette bricht, ist auch angemahnt
> worden.
>
> Beim Bauen des Stroms kam heraus, was Abschnitt 4 nicht bedacht hatte: **Der Puffer muss
> JE BAHN sperren.** Wartet ein Wurf, muss alles dahinter auf derselben Bahn ebenfalls
> warten — sonst nimmt der spätere Wurf den Platz des früheren, und aus 9-8-4 wird 9-4-8.
> Ebenso darf es nur EINEN offenen Vorschlag je Platz geben; weil der erste Wurf eines
> leeren Satzes immer nur vorgeschlagen wird (Einspielwürfe), stapelten sich sonst am
> Satzanfang beliebig viele Vorschläge für denselben Wurf.
>
> **4. Die Oberfläche ist anders ausgefallen als Abschnitt 3 sie plante: es gibt KEINE
> Vorschlagsliste.** Die Entscheidung fiel am 12.11.2026 — ein erkannter Wurf geht direkt
> in den Satz, korrigiert wird er wie jeder getippte. Damit trägt der Automatik-Betrieb
> auch das ein, was die Zuordnung nur „vorschlagen" wollte; der Grund wird zum HINWEIS an
> der Bahn statt zur Rückfrage. Nur ein Wurf, den die Erfassung selbst ablehnt („mehr
> Holz als Kegel standen"), bleibt draußen — und wird sofort aufgegeben, statt die Bahn
> 15 Minuten lang zu sperren: Eine Fehlerkennung darf nicht den Rest des Satzes stilllegen.
>
> Sichtbar wird die Erkennung an genau drei Stellen: ein Zeichen im Bahn-Tab (👁 läuft,
> ⚠ Hinweise), ein 👁 im Wurf-Chip (dieser Wurf kam von der Kamera, beim Bearbeiten mit
> Knopf zum Tafelbild), und der Abschnitt „Erkennung" in der Bahneinstellung (Schalter
> Aus/Automatik je Bahn, „erkannte Würfe dieses Satzes verwerfen", Hinweisliste).
>
> Gegen die Einspielwürfe — die für die Kamera aussehen wie Würfe — steht ein
> **Stichtag je Bahn**: Nur was NACH dem Einschalten aufgezeichnet wurde, zählt. Wer beim
> Anspiel einschaltet, hat das Problem nicht; das Verwerfen ist das Netz darunter.
>
> **5. Was der erste Durchlauf in der Oberfläche zutage förderte** — vier Dinge, die
> keine Unit- und keine E2E-Prüfung gefunden hätte:
>
> | Fund | Wo | Warum es niemandem auffiel |
> |---|---|---|
> | Die Policies prüften `status = 'laufend'` | `supabase/policies.sql` | Ein geteiltes Spiel steht in der Datenbank auf `setup` — der lokale Status springt beim ersten Wurf (store.js), der entfernte wird erst beim Beenden geschrieben. In der Test-DB: 47 Spiele auf `setup`, **kein einziges** auf `laufend`. |
> | `erkannt` überlebte kein Neuladen | `normalizeErfassung` | Die Funktion baut jeden Block aus FESTEN Feldern neu auf. In der Datenbank stand die Herkunft noch, lokal war sie weg. Gleiches galt für Schalterstellung, Stichtag und Hinweise. |
> | Das Teilen startete die Erkennung nicht | `shareGame` | `initErkennung` lief nur beim Öffnen des Spiels — wer während des Spiels teilte, bekam sie bis zum nächsten Öffnen nicht. |
> | Verworfene Würfe behielten ihren Verweis | `verwerfen` | Es schützt mit `satz_block_id is null` davor, Zugeordnetes zu überschreiben — beim Verwerfen ist aber genau das gewollt. Dafür gibt es jetzt `freigeben`. |
>
> Gefahren wurde der Durchlauf gegen die Test-Datenbank, mit echten Zeilen des Erkenners
> über HTTP: vier Würfe automatisch im Satz, Reihenfolge richtig, widersprüchliches
> Kegelbild verworfen, Verweise (`satz_block_id` + `wurf_index`) gesetzt, Tafelbild
> angezeigt, Schalter und Stichtag geprüft, danach restlos aufgeräumt.

Ausgangslage: Eine externe Erkennung (Kamera/Sensorik an der Bahn) liefert **nur erkannte
Wurfbilder plus die Bahn**. Sie kennt weder Spieler noch Satz, Teilsatz oder Teilsatzmodus.

## 0. Kernidee

Die App weiß alles, was der Erkenner nicht weiß. Aus der Bahn folgt der Rest deterministisch:

```
Bahn --(computeBahnState)--> Spieler --(.pos)--> physischer Satz
     --(blk.wuerfe.length)--> Wurfindex --(rangeOfThrow)--> Teilsatz + Modus
```

* `computeBahnState` (`js/logic/bahnwechsel.js`) belegt jede Bahn mit genau einem Spieler,
  inklusive Bahnwechsel-Gating und Duo-Tausch.
* `rangeOfThrow` (`js/logic/abraeumen.js`) liefert zum Wurfindex den Teilsatz und damit den Modus.

Der Erkenner darf Teilsatz/Modus/Spieler also **nicht** kennen — sonst gäbe es zwei Wahrheiten.

## 1. Kontrakt (Phase 0 — zuerst festzurren)

Ein Event je Wurf, je Bahn:

```json
{
  "eventId": "uuid",
  "anlage": "…", "bahn": 3,
  "seq": 147,
  "ts": "2026-09-01T18:22:31.402Z",
  "art": "wurf",
  "bildVor":  [1,2,3,4,5,6,7,8,9],
  "bildNach": [5,7],
  "konfidenz": 0.97
}
```

Sieben nicht verhandelbare Anforderungen an die Erkennungsseite:

1. **Wurf-Trigger auch bei 0 Holz.** Ein Fehlwurf ändert das Bild nicht. Ohne ein Signal
   „hier wurde geworfen" (Kugellauf, Bewegung, Lichtschranke) gehen Fehlwürfe verloren —
   dann stimmt die Wurfzahl im Teilsatz nicht mehr (Mismatch-Warnung in `teilsatzStats`).
   **Das ist der Knackpunkt: kann die Erkennung das nicht, ist realistisch nur der
   Vorschlagsmodus möglich, keine Automatik.** Vor Phase 1 klären.
2. **Absolute Standbilder statt Deltas.** `bildNach` = Menge der stehenden Kegel.
   Selbstkorrigierend: ein verpasstes Event wird beim nächsten Wurf sichtbar, statt
   fortgeschrieben zu werden.
3. **`bildVor` mitschicken**, obwohl die App es selbst berechnen kann — genau deshalb:
   erwarteter vs. gemeldeter Vorzustand = Drift-Erkennung (siehe 4.).
4. **Aufstellvorgang als eigenes Event** (`art: "aufstellung"`), nicht als Wurf mit 9 Stehenden.
5. **`seq` + `eventId`** für Idempotenz und Reihenfolge, plus Abruf „alles ab seq N" nach Reconnect.
6. **Konfidenz je Event** (idealerweise je Kegel) — unter Schwelle: Vorschlag statt Automatik.
7. **Kalibrierte Kegelnummerierung je Bahn**, identisch zur Raute in `KEGEL_LAYOUT`
   (`js/views/spiel-laufend.js`). Achtung Spiegelung von der Kameraseite; bei Bohle/Schere je
   Bahn prüfen. Ein Kalibrier-Screen je Bahn ist Pflicht — klassischer Feldfehler.

**Vor der ersten Zeile Code:** echte Aufzeichnung einer kompletten Serie (Volle + Abräumen,
mit Fehlwurf und Kranz) als JSON-Fixture. Ohne die baut man die Zuordnung gegen Vermutungen.

## 2. Transport

|                | A: lokale Brücke                 | B: Supabase `wurf_event`          |
| -------------- | -------------------------------- | --------------------------------- |
| Muster         | existiert: `js/backend/sw-bruecke.js` | existiert: Realtime in `js/backend/sync.js` |
| Aufwand        | klein, keine Migration           | Tabelle + RLS + Erkenner-Auth     |
| Reichweite     | nur Gerät am selben PC/LAN       | jedes Tablet an der Bahn          |

**A zuerst, B nachrüsten** — hinter einer gemeinsamen Schnittstelle in `js/backend/erkennung.js`:

```
subscribeErkennung({ bahnen, seitSeq, onEvent }) -> unsubscribe
```

Wichtig für B: Der Erkenner schreibt **nie** in `satz_block`, nur Rohevents. Die App übersetzt
sie. Damit bleibt die Single-Writer-Regel der RLS unangetastet (nur das Gerät mit
`besitzer_geraet` schreibt Würfe) — die Eigenschaft, die den Mehrgeräte-Sync trivial hält.

## 3. Neue Module

* **`js/logic/erkennung-zuordnung.js`** — reine Funktion, kein DOM/Netz:
  `ordneEvent(event, { config, ranges, bloecke, bahnState, besitz })`
  → `{ aktion: 'setzen'|'vorschlag'|'puffern'|'verwerfen', ziel:{sp,st,idx}, pins, kegel, koenigFlag, grund }`
  Unit-testbar mit `node --test` wie `tests/abraeumen.test.js`.
* **`js/logic/erkennung-strom.js`** — Dedupe nach `eventId`, Lücken über `seq`, Puffer je Bahn,
  Entprellung.
* **`js/backend/erkennung.js`** — Transport (siehe 2.).
* **Refactor in `js/views/spiel-laufend.js`:** `addWurf(pins, koenigFlag)` arbeitet implizit auf
  `state.aktiverSpieler/aktiverSatz` (UI-Zustand). Die Erkennung braucht ein explizites Ziel:
  `addWurfAn({ sp, st, pins, kegel, koenigFlag, quelle })`, `addWurf` ruft es mit dem aktiven
  Ziel auf. Alle bestehenden Guards (Satz voll, `blk.done`, `frontSatz`, Bahnwechsel-Gate,
  `guardEdit`) bleiben in Kraft — die Erkennung geht durch dieselbe Tür, nicht daran vorbei.

## 4. Zuordnungsregeln

**Satzwahl:** `bahnState[sp].pos`, **nicht** `state.aktiverSatz` (das ist reiner UI-Zustand).

**Modus-Übersetzung:**

* *Volle*: gefallen = `9 ohne bildNach`, Holz = Anzahl. Kranz ergibt sich über `volleKranz`.
* *Abräumen*: gefallen = `bildVor ohne bildNach`; erwarteter Vorzustand aus `abraeumStateBefore`.
  Bonus: wo die Handerfassung nur `count` kennt (`exact:false`), liefert die Kamera das exakte
  Bild — die Erkennung macht den Datenbestand besser, nicht nur schneller.
* *Kranz-Abräumen*: steht die 5 in `bildNach` und sind die Kegel bekannt, `kegel[idx]` exakt
  setzen, `koenig`-Flag bleibt false — Semantik von `koenigKegelFor`.
* *Neuaufstellung*: keine Sonderbehandlung nötig, `runCleared`/`freshRun` erledigen das im
  Modell. Das `aufstellung`-Event dient nur als Plausibilitätsanker.

**Drift-Erkennung (wichtigster Sicherheitsmechanismus):** Weicht `event.bildVor` vom erwarteten
Vorzustand ab, wurde ein Wurf verpasst oder falsch zugeordnet. Dann nicht setzen, sondern die
Bahn in den Vorschlagsmodus zwingen und ein Banner zeigen — Muster vorhanden in
`js/views/sportwinner-konflikt-panel.js` / `js/logic/sportwinner-konflikte.js`.

**Vier Fälle, die kein „Verwerfen" verdienen, sondern einen Puffer je Bahn:**

1. Spieler wartet auf Bahnwechsel (`waiting`), wirft physisch schon → puffern, nachziehen
   sobald `pos` vorrückt.
2. Satz voll / `blk.done` → puffern, als Korrekturvorschlag anbieten.
3. Spieler gehört einem anderen Gerät (`canEdit === false`) → hier ist Verwerfen richtig,
   sonst schreiben zwei Geräte.
4. Erster Wurf eines noch leeren Satzes → Vorschlag statt Automatik, sonst zählen
   Einspielwürfe mit („Satz auf Bahn 3 starten?" einmal bestätigen).

## 5. Betriebsmodi (Einstellung je Spiel)

* **Aus** (Default)
* **Vorschlag** — Erkennung füllt nur das Kegelbild-Popup vor, der Erfasser bestätigt.
  Einstieg im Feldtest.
* **Automatik** — setzt den Wurf; alles unter Konfidenzschwelle, mit Drift oder aus Puffer (4.)
  landet trotzdem als Vorschlag in der Warteschlange.

Erkannte Würfe optional als `blk.quelle[idx] = 'auto'|'hand'` markieren. Das Blockformat wandert
1:1 durch `satz_block.block_json`; ein zusätzliches Array ist unkritisch (`normalizeErfassung`
muss es tolerieren), CSV und Protokoll bleiben unberührt. Nutzen: Korrekturquote messbar — die
einzige harte Zahl zur Erkennungsqualität.

## 6. Phasen

| Phase | Inhalt | Ergebnis |
| ----- | ------ | -------- |
| 0 | Kontrakt + echte Fixture-Aufzeichnung | Grundlage |
| 1 | `erkennung-zuordnung.js` + Tests (Volle, Abräumen, Kranz, Fehlwurf, Drift, unbekannte Bahn, Satz voll, Warten) | Logik steht, ohne UI/Netz |
| 2 | `erkennung.js` (Variante A) + Abspiel-Skript für die Fixture | gegen Testspiel verifizierbar |
| 3 | UI: `addWurfAn`-Refactor, Statusbadge (wie `sw-dot`), Modus-Umschalter im ⚙, Vorschlags-Panel, Kennzeichnung erkannter Würfe | benutzbar an der Bahn |
| 4 | Variante B: `wurf_event` + RLS + Realtime | Tablets ohne PC-Nähe |
| 5 | Feldtest, Korrekturquote auswerten, Schwellen nachziehen | Automatik freischalten |

Phasen 0–2 sind unabhängig von der Erkennungssoftware testbar — dafür reicht die Aufzeichnung.

## 7. Selbst ausprobieren — ohne Kamera

Zum Üben braucht es weder Bahn-Rechner noch Kegel_CV: `tools/erkennung-wuerfe-senden.py`
meldet sich mit dem Erkenner-Login aus `erkennung/.env` an und schreibt über PostgREST in
`erkannter_wurf` — denselben Weg, den der Rechner an der Bahn nimmt. Jeder Lauf prüft damit
auch die Rechte mit, nicht nur die Oberfläche; ein SQL-Editor täte das nicht, dort sitzt man
als Eigentümer.

**Drei Dinge müssen stimmen, sonst passiert gar nichts** (`erkMoeglich` in
`js/views/spiel-laufend.js`):

1. Die App läuft gegen die Test-Datenbank — `js/backend/config.local.js`, `npm run dev`.
2. Das Spiel hat eine **Anlage**, und zwar die, an der der Erkenner hängt.
3. Das Spiel ist **geteilt**. Ohne geteiltes Spiel gibt es keinen Verweis zurück in die
   Datenbank, und ohne ihn stünde nach einem Neuladen jeder Wurf doppelt.

Dann:

```
npm run dev                                   # http://localhost:5173
# Spiel anlegen (Anlage wählen!), teilen, Erfassung öffnen
python tools/erkennung-wuerfe-senden.py . 1 9 8 7 --pause 2
```

Die Würfe erscheinen einzeln im Satz, jeder mit 👁 im Chip. `--pause` ist zum Zusehen da —
ohne sie kommen sie schneller, als Realtime sie ausliefert, und man sieht nur das Ergebnis.

Was sich damit vorführen lässt:

| Zu sehen | Aufruf |
| --- | --- |
| Kegelbild (welche Kegel fielen) | `… . 1 9:1,2,3,4,5,6,7,8,9` |
| Tafelbild am bearbeiteten Wurf (🖼) | `… . 1 7:bild` |
| Widerspruch Bild ⇄ Holz → Holz zählt, Bild fällt weg | erst `9:1,2,3,4,5,6,7,8,9`, dann `8:1,2` |
| Hinweis an der Bahn, Wurf bleibt draußen | mehr Holz schicken, als noch steht |
| Stichtag: Einspielwürfe bleiben draußen | Würfe schicken, **dann** erst in der Bahneinstellung einschalten |

Aufräumen: `python tools/erkennung-wuerfe-senden.py . --aufraeumen` (löschen darf nur der
Verwalter, nicht der Erkenner — das geht deshalb über `supabase/.db-test.env`). Was die App
schon übernommen hat, steht danach weiter im Satz; dafür gibt es in der Bahneinstellung
„erkannte Würfe dieses Satzes verwerfen".

## 8. Die Wurfnummer der Tafel bestimmt den Platz (12.11.2026)

**Das ist eine Kehrtwende gegenüber Abschnitt 0 und 4.** Dort stand, die von der Tafel
gelesene Wurfnummer werde bewusst NICHT benutzt — im Ursprungsprojekt der Erkennung hatte
sie 28 % der Würfe gelöscht. Der Grund dafür bleibt richtig; die Schlussfolgerung war zu
weit. Die Nummer darf jetzt mitreden, aber sie darf **nie einen Wurf kosten**:

| Lage | Was passiert |
| --- | --- |
| keine Nummer gelesen | nächster freier Platz — wie vorher |
| Nummer passt zum Platz | nichts Besonderes, kein Hinweis |
| Nummer liegt auf einem belegten Platz | der Wurf dort wird **ersetzt**, mit Hinweis |
| Nummer liegt weiter vorn (bis `MAX_LUECKE` = 5) | die Plätze dazwischen bleiben als **offene Würfe** stehen (`? ✎`, 0 Holz) |
| Nummer liegt weiter als 5 Plätze vorn | Nummer gilt als verlesen → ans Ende, mit Hinweis |
| Nummer außerhalb 1…Würfe-pro-Satz | dito |

**Wozu das gut ist:** Lehnt die Erfassung einen Wurf ab — und sie gibt ihn sofort auf,
siehe Abweichung 4 —, sitzt ohne die Nummer **jeder folgende Wurf einen Platz zu früh**,
bis zum Satzende. Gemessen am Mitschnitt vom 08.09.: Nach vier abgelehnten Würfen landete
der nächste auf Platz 19 statt auf 23. Mit der Nummer sitzt er auf 23, und die vier
offenen Plätze stehen sichtbar als `? ✎` da.

**Warum 0 Holz für einen offenen Platz:** Die Wurfliste ist ein dichtes Array; `null` darin
hätte 149 Fundstellen in 22 Dateien zu tragen gehabt (Summen, Statistik, CSV, Sportwinner,
Overlay). 0 Holz hält die Satzsumme richtig (0 addiert nichts) und heißt beim Abräumen
„nichts fiel" — die harmloseste Annahme. Das eigene Feld `blk.luecke` je Wurf unterscheidet
den offenen Platz vom gewollten Fehlwurf; ohne es wären beide dieselbe 0.

**Warum `MAX_LUECKE`:** Eine verlesene Ziffer ist der häufigste Fehler der Tafelerkennung —
aus „7" wird „17". Ohne Deckel stünden zehn erfundene Fehlwürfe im Satz, bei 30 Würfen je
Satz womöglich bis zum automatischen Satzende. Vier bis fünf verpasste Würfe am Stück sind
dagegen real: genau das ist beim Abspielen passiert.

**Was der Durchlauf hier fand:** Der Ablehnungsgrund in der Datenbank war falsch. In
`erkUebernehmen` setzte `melde` den Grund nur, wenn noch keiner dastand (`e.grund || txt`) —
stand dort schon der Hinweis zur Platzierung, landete DER als `verworfen_grund`. In der
Datenbank stand dann „Tafel zeigte Wurf 20, hier war erst Platz 19", obwohl die Erfassung
den Wurf wegen „8 Holz, aber es stand nur 1 Kegel" nicht annahm. Eine Ablehnung schlägt
jetzt jeden Hinweis.

Nachgewiesen gegen die Test-Datenbank mit dem Mitschnitt vom 08.09. (23 Würfe, jede 7.
Tafelnummer absichtlich weggelassen): **17 von 17 gelesenen Nummern sitzen auf ihrem
eigenen Platz**, die drei ohne Nummer am nächsten freien, vier von der Erfassung abgelehnt
(mit dem richtigen Grund), vier offene Plätze als `? ✎` — und sie überleben das Neuladen.
