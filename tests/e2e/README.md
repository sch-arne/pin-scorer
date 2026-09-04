# End-to-End-Tests

Die E2E-Tests fahren die **echte App** in einem `<iframe>` und bedienen sie über das DOM —
Klicks auf die tatsächlichen Knöpfe, Tippen in die tatsächlichen Felder. Geprüft wird, was
danach auf dem Bildschirm steht **und** was im `localStorage` landet.

Sie ergänzen die reinen Logik-Tests (`node --test`, Ordner `tests/`): dort steckt die
Rechnerei (Holz, Bahnwechsel, Wertung, CSV), hier der Weg durch die Oberfläche.

## Starten

**Headless (der Normalfall — dauert gut eine Minute):**

```bash
npm run test:e2e
```

Startet den Dev-Server, ein installiertes Chrome/Edge headless und fährt alles durch;
Exit-Code 0 = grün. Nur einen Ausschnitt: `node tools/e2e-headless.mjs --only Wettkampf`.
Beides zusammen (Logik + E2E) läuft mit `npm run test:all` — dasselbe tut die CI
(`.github/workflows/tests.yml`) bei jedem Push.

**Im Browser** (zum Zuschauen und Nacharbeiten):

```bash
npm run dev
```

Dann <http://localhost:5173/tests/e2e/> öffnen und **„Alle Tests laufen lassen"** drücken.
Ausschnitt: `?only=Wettkampf` an die URL hängen.

> `npm run dev` ist `python -m http.server` plus `Cache-Control: no-store` (siehe
> `tools/devserver.py`). Der Header ist hier nicht Kosmetik: ohne ihn cacht der Browser die
> ES-Module heuristisch, und ein Testlauf fährt dann teils gegen alten Code — der Fehler
> sieht aus wie ein echter.

Im Browser dauert ein voller Lauf rund acht Minuten statt einer: dort drosselt der Browser
`requestAnimationFrame` der Runner-Seite. Für „einmal alles" ist der headless-Weg gedacht.

Maschinenlesbar liegt das Ergebnis nach dem Lauf in `window.__E2E__`
(`{ done, pass, fail, tests[], failures[] }`); `window.__E2E_RUN__(filter)` startet einen Lauf.

## Wichtig: eigene Daten

Der Runner läuft auf demselben Origin wie die App und teilt sich deshalb den
`localStorage`. Er **sichert alle `pins-scorer:*`-Einträge vor dem Lauf und stellt sie
danach wieder her**. Beim Abbrechen mitten im Lauf (Tab schließen) bleibt allerdings der
Testzustand stehen — dann einfach die App einmal aufräumen.

## Aufbau

| Datei | Inhalt |
| --- | --- |
| `index.html` | Runner-Oberfläche (Ergebnisliste + App-Fenster) |
| `runner.js` | lädt die Specs, fährt sie der Reihe nach, schreibt das Ergebnis |
| `harness.js` | Mini-Testframework (`suite`/`test`/Assertions) + App-Treiber (`App`) |
| `fixtures.js` | fertige Spiel-/Wettkampf-Objekte zum Seeden, gebaut mit den echten Logik-Modulen |
| `specs/00-router.js` | Routen montieren, Navigation, Abräum-Signal, Overlay-Aufräumen |
| `specs/10-setup.js` | Setup „Sportkegeln-Training" (Presets, Stepper, Startbahnen, Spielstart) |
| `specs/20-erfassung.js` | Wurferfassung: Würfe, Kegelbild, Korrektur, Abräumen, Spielende, Einstellungen |
| `specs/30-uebersicht-statistik.js` | Spieler-Übersicht, Ergebnis-Eingabe, Statistik, Wurf-Bild, Kontrollzentrum |
| `specs/40-export.js` | CSV-Download und Wurfprotokoll-Druck |
| `specs/50-wettkampf.js` | Wettkampf-Setup (mit und ohne Anlage), Hub, Aufstellung, Wertung, Auswertung, Mannschafts-Export |
| `specs/60-backend-views.js` | Statistiken sowie Account/Anlagen/Beitreten/Import/Overlay ohne Anmeldung |
| `specs/70-offline.js` | die local-first-Zusage: ohne Verbindung geht alles Lokale weiter, nichts geht verloren |
| `specs/80-loeschen.js` | Löschen: rein lokal = endgültig weg, in der Datenbank = verbergen, über die LizenzID = gar nicht |
| `specs/90-hausnummern.js` | Hausnummern: Regeln im Setup, die vier Platzierungs-Varianten, Fehlwurf, Ergebnis |
| `../../tools/e2e-headless.mjs` | headless-Runner (Chrome per CDP, ohne npm-Abhängigkeiten) |

## Was der Treiber abfängt

Damit ein Testlauf nichts nach außen tut:

* `window.confirm` / `alert` / `prompt` — Antwort über `app.confirmAnswer` steuerbar,
  gestellte Fragen stehen in `app.confirms` / `app.alerts`.
* **Downloads** (CSV): der Klick auf den `<a download>` wird abgefangen, der Inhalt sofort
  gelesen — `await app.downloadText()`.
* **Druck** (Wurfprotokoll): das versteckte Druck-`iframe` bekommt ein gefälschtes `print()`,
  das HTML landet in `app.prints`.
* **Unbehandelte Fehler** im App-Fenster werden gesammelt; `app.assertClean()` lässt einen
  Test daran scheitern. Jeder Test sollte damit enden.

## Offline testen

`app.boot({ offline: true })` setzt den localStorage-Schlüssel `pins-scorer:e2e-offline`.
`js/backend/supabase.js` bricht daraufhin **auf Entwicklungs-Hosts** absichtlich ab; jeder
Aufrufer lädt das Modul ohnehin nur lazy und fängt den Fehlschlag ab. Die App verhält sich
damit exakt wie ohne Verbindung — nur eben unabhängig davon, ob der Rechner gerade Netz hat.
In Produktion (GitHub Pages) greift der Schalter nie.

## Grenzen

* **Kein echter Server.** Der Sync gegen Supabase (Mehrgeräte-Erfassung, Beitritts- und
  Zuschauer-Codes, Overlay-Daten, Account, Anlagen) wird von zwei Seiten eingekreist, aber
  nicht durchgespielt: ohne Anmeldung müssen die Views sauber montieren (`60-…`), ohne
  Verbindung muss alles Lokale weiterlaufen und nichts verloren gehen (`70-…`). Der
  Erfolgsfall gehört weiterhin in einen manuellen Zwei-Geräte-Test gegen die Test-DB.
* **Keine Sportwinner-Brücke.** Der Import und das Rückschreiben brauchen die 32-Bit-DLL auf
  dem Vereins-PC.
* Die App wird über das Menü angesteuert statt direkt auf der Zielseite geladen: im iframe
  steht die Layout-Breite während des allerersten Dokument-Ladens noch nicht fest, sodass
  Views, die beim Bauen `matchMedia('(min-width: 900px)')` lesen, sonst fälschlich das
  Handy-Layout wählen. `app.boot({ direct: true })` erzwingt den direkten Kaltstart (dafür
  ohne verlässliches Desktop-Layout).
