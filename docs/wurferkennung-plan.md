# Plan: automatische Wurfbild-Erkennung an die App andocken

Stand: 01.09.2026 · Status: Konzept, noch keine Zeile Code

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
