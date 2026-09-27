# Edge Functions

## `sportwinner-proxy`

Relay zum öffentlichen Sportwinner-Ergebnisdienst. Ohne diese Funktion bleibt der Web-Import
(`#/import/sportwinner-web`) leer — die App kann `service.php` nicht direkt aufrufen, weil der
Endpunkt `Referer`/`Origin` des Ergebnisdienstes verlangt und beides ein Browser nicht setzen
darf. Details und die Datenschutzregeln stehen im Kopf von `sportwinner-proxy/index.ts`.

### Welche Dienste es gibt

| Verband | Bestand | geprüft |
|---|---|---|
| `kvn` | Schere: Bezirks-, Landes- und Bundesligen | 27.09.2026 |
| `dskb` | nur die Schere-Bundesligen (keine Bezirke: `GetBezirkArray` → `-1`) | 27.09.2026 |
| `dkbc` | Classic-Bundesligen und DKBC-Pokal | 27.09.2026 |

Die Funktion lässt jeden Host `<name>.sportwinner.de` zu; die Liste in `js/backend/sw-web.js`
ist nur die Auswahl im Formular, und daneben steht ein Feld zum Eintippen. `kvs`, `wkbv` und
`dkb` lösen auf, antworten aber mit `403` — dort läuft kein Ergebnisdienst.

### Wie die Abfragen aussehen müssen

Abgelesen am Client des Dienstes selbst (`kvn.sportwinner.de/script/kvn/sportwinner.js`) und am
echten Dienst nachgemessen. Wer hier etwas ändert, prüft es dort — geraten wird nichts.

* **`GetLigaArray` immer nur für EINEN Bereich.** `art`: 0 Bund · 1 Land · 2 Bezirk · 3 Klub ·
  4 Favorit (`Globals.Art`), Bund und Land mit `id_bezirk=0`. Die Seite fragt nie alle Ligen auf
  einmal, sie hat ein Bereichs-Dropdown. Die App tat es früher doch und brauchte dafür rund ein
  Dutzend Abfragen — auf diesem Weg die Hauptursache der Ausfälle.
* **Spaltenlage ist nicht überall gleich.** `kvn`/`dkbc`: `[id, wertung, name, art, …]`,
  `dskb`: `[id, name, art, …]` — ohne `wertung`. Dasselbe bei `GetSpiel`: 14 Spalten mit
  `wertung` an `[11]`, bei `dskb` 13 ohne. Deshalb wird am Inhalt erkannt, nicht am Index.
* **`wertung` braucht `GetSpielerInfo`**, und das Layout des Berichts hängt daran. Fehlt sie in
  der Partie-Zeile, gilt die der Liga aus `GetLigaArray`.
* **`art_spieltag`**: `0` mit `id_spieltag=0` → nur der aktuelle Spieltag; `2` mit echter Id →
  genau dieser. Ohne die `2` kommt eine leere Liste.
* **`GetSpieltagArray`** liefert `[id, nr, name, status]`; `status="1"` heißt beendet.
  `id_sektion` ist dort entbehrlich (Antwort mit und ohne gemessen identisch).
* **`GetSaisonArray`**: das dritte Feld ist **nicht** „ist die aktuelle Saison" — `kvn` meldet
  für 2026 eine `0`, `dskb` für 2025 und 2024 eine `1`. Der Dienst-Client liest es nie und nimmt
  die neueste Saison. Die App sortiert deshalb nach Jahr.
* **`-1`** ist die Leer-Antwort des Dienstes. Die Funktion macht daraus `[]`, die App behandelt
  jede Antwort, die keine Zeilenliste ist, als leer.

### Was der Betreiber zur Nutzung sagt

Im Impressum der Seite (wörtlich im Client enthalten) steht unter *Gestattete Nutzung*: privat
und nicht-kommerziell, „Einzelne Abfragen sind zulässig, sofern sie das normale Maß einer
menschlichen Nutzung nicht überschreiten." Unter *Untersagte Nutzung (Scraping-Verbot)*:
systematische oder automatisierte Extraktion, Crawler, Scraper-Skripte, Headless-Browser,
systematisches Auslesen zur Speicherung, KI-Training. Er behält sich die Sperrung von
IP-Adressen vor; `robots.txt` sagt `Disallow: /` und `Crawl-delay: 10`.

Das ist der Rahmen, in dem dieser Import gebaut ist, und der Grund für seine Form: ein Abruf nur
auf Nutzeraktion, so wenige Abfragen wie möglich, Listen aus dem Zwischenspeicher statt erneut
geholt, ein Limit je Konto — und nichts, was Automatisierung verschleiert (kein wechselnder
User-Agent, kein vorgetäuschter Fingerprint). Wird der Weg dauerhaft zugemacht, ist das die
Antwort des Betreibers. Dann fragt man beim Verband oder bei `support@sportwinner.de` nach einer
Genehmigung — und baut sie nicht weg.


### Was mit einer Anfrage hinausgeht

Vollstaendig — mehr steht in keiner Anfrage an `sportwinner.de`:

| | Inhalt |
|---|---|
| `Referer` / `Origin` | der Ergebnisdienst selbst (verlangt er so, sonst 404) |
| `User-Agent` | `Mozilla/5.0 pins-scorer` — der Name der App, damit sie sich zu erkennen gibt |
| `thumbmark` | `{"thumbmark":"ohne-fingerprint","webdriver":false}`, fest und fuer alle gleich |
| Parameter | nur Ids aus der Auswahl des Nutzers (Saison, Sektion, Liga, Spieltag, Spiel) |

Kein Verein, kein Name, keine E-Mail, keine Geraetemerkmale, keine Konto-Kennung — und die
IP-Adresse des Nutzers erreicht den Dienst ohnehin nicht, nur die des Relays. Bis zum 27.09.2026
trug der `User-Agent` zusaetzlich den Verein des Nutzers und der `thumbmark` den App-Namen; beides
ist auf seinen Wunsch heraus. Wer hier etwas HINZUFUEGT, prueft vorher, ob es dort hingehoert.

### Wohin

| Umgebung | Project-Ref | steht in |
|---|---|---|
| Test-DB | `oizupdfesgihpzdzwvcw` | `js/backend/config.local.js` |
| Produktion | `bajiihfyvupvsdsxwdkj` | `js/backend/supabase.js` |

**Immer erst Test-DB, den Import gegen `localhost:5173` durchspielen, dann Produktion** — wie bei
den SQL-Migrationen.

### Weg A — Dashboard (ohne Werkzeuge auf dem Rechner)

1. `https://supabase.com/dashboard/project/oizupdfesgihpzdzwvcw/functions` öffnen
   (für Produktion dieselbe Adresse mit `bajiihfyvupvsdsxwdkj`).
2. **Deploy a new function** → **Via Editor**.
3. Als Namen exakt `sportwinner-proxy` eintragen. Der Name ist die Adresse: die App ruft
   `supabase.functions.invoke('sportwinner-proxy')` — ein Tippfehler und sie findet nichts.
4. Den Beispielcode im Editor **vollständig** löschen und dafür den ganzen Inhalt von
   `supabase/functions/sportwinner-proxy/index.ts` einfügen. Die Datei ist absichtlich
   eigenständig: keine Imports, keine npm-Pakete, nichts, was mitkopiert werden müsste.
5. Falls eine Option zur JWT-Prüfung angeboten wird: **an lassen**. Ohne sie wäre das Relay ein
   offener Proxy.
6. **Deploy function** — dauert etwa 10 bis 30 Sekunden.

Das Dashboard kennt keine Versionierung: die Datei im Repo bleibt die Quelle. Ändert sie sich,
muss der Inhalt erneut eingefügt werden.

### Weg B — CLI

```bash
npx supabase@latest login
npx supabase@latest functions deploy sportwinner-proxy --project-ref oizupdfesgihpzdzwvcw
```

Aus dem **Projekt-Wurzelverzeichnis** starten, nicht aus `supabase/functions/`. Die CLI erwartet
ein Projektverzeichnis, also `supabase/config.toml` — die Datei liegt dafür im Repo (minimal,
ohne lokalen Docker-Stack); ohne sie meldet sie „Cannot find project".

Scheitert `npx` in der PowerShell mit *„npx.ps1 cannot be loaded because running scripts is
disabled on this system"*, ist die Ausführungsrichtlinie schuld und nicht Node. `npx.cmd` statt
`npx` schreiben — auf `.cmd` greift die Richtlinie nicht, und es muss nichts umgestellt werden.

Geht npm gar nicht (z. B. gesperrte Registry), gibt es die CLI auch als fertige `supabase.exe`:
`supabase_<version>_windows_amd64.zip` unter `https://github.com/supabase/cli/releases`,
entpacken, aus dem Projektverzeichnis `.\supabase.exe functions deploy …` aufrufen.

Die Funktion braucht **keine** Secrets. `verify_jwt` bleibt auf dem Standard (an) — sie ist
bewusst kein offener Proxy.

### Prüfen

Nach dem Deploy in der App `#/import/sportwinner-web` öffnen (bei der Test-DB:
`localhost:5173`) und **neu laden**. Die Saison-Auswahl muss sich füllen. Was die Ansicht sonst
meldet, ist bereits die Diagnose:

| Meldung | Bedeutung |
|---|---|
| „Die Serverfunktion … antwortet nicht" | nicht deployt, oder der Name weicht ab |
| „Konto nötig — bitte unter Spieler anmelden" | Funktion läuft, es fehlt die Anmeldung |
| „Zu viele Abfragen" | Rate-Limit der Funktion (30/Minute) |
| „Der Ergebnisdienst hat nicht geantwortet" | Die Verbindung aus der Edge-Runtime zu `sportwinner.de` bleibt haengen, bis sie ablaeuft. Am 27.09.2026 an 10 Abfragen desselben Kommandos gemessen: 5 blieben stumm, jede volle 25 s — das waren die damals drei Versuche IM Relay, die zusammen stumm blieben. Ein NEUER Aufruf der Function war dagegen in 3 von 5 Faellen sofort da (~0,3 s). Die Stille klebt also am einzelnen Aufruf, nicht am Zeitpunkt. Daraus folgte die Aufteilung: Relay = 1 Versuch / 6 s, App = bis zu 3 Anlaeufe (`ANLAEUFE`) — gleich viele Anfragen, aber jede ein echter neuer Versuch. Vom Rechner eines Nutzers gehen dieselben Abfragen 8 von 8 Mal durch; es ist der Weg aus dem Rechenzentrum, nicht die App. Haeuft es sich, beim Verband nachfragen. |
| „Der Ergebnisdienst hat zu dieser Partie keine Zeile geliefert" | Liga, Spieltag und Partien kommen an, nur `GetSpielerInfo` bleibt leer. Heisst: der Dienst lehnt den `thumbmark` ab. Am 26.09.2026 sperrte er den bis dahin gesendeten LEEREN Hash. In `THUMBMARK` steht seither ein fester, neutraler Wert (`ohne-fingerprint`) — das Feld muss mitgehen, sein Inhalt wird nicht geprueft (am 27.09.2026 gemessen: mit Wert 781 Zeichen Bericht, ohne das Feld 0). Wird auch dieser Wert gesperrt, beim Verband nachfragen — nicht einen neuen raten und schon gar nicht je Anfrage wuerfeln. |
| „Die Listen stehen hier aus dem Zwischenspeicher" | Eine Listen-Abfrage fiel aus, und die App hat die letzte gute Antwort genommen (siehe `js/backend/sw-web.js`). Der Import läuft damit weiter; nur ein gerade nachgetragener Spieltag kann fehlen — spätestens nach Ablauf der Frist (6–12 h) wird die Liste wieder frisch geholt. |

Zum Nachprüfen, ob es am `thumbmark` liegt, braucht es die Function gar nicht: der Ergebnisdienst
antwortet auf diese Anfrage direkt (leerer Körper = abgelehnt, sonst der Spielbericht).

```bash
curl -s -X POST "https://kvn.sportwinner.de/php/kvn/service.php" -H "Content-Type: application/x-www-form-urlencoded" -H "Referer: https://kvn.sportwinner.de/" -H "Origin: https://kvn.sportwinner.de" --data-urlencode "command=GetSpielerInfo" --data-urlencode "id_saison=12" --data-urlencode "id_sektion=2" --data-urlencode "id_spiel=347918" --data-urlencode "wertung=0" --data-urlencode 'thumbmark={"thumbmark":"ohne-fingerprint","webdriver":false}'
```

Gegenprobe, dass die Allowlist greift — muss mit `400 Kommando nicht erlaubt` antworten:

```bash
curl -s -X POST "https://<PROJECT_REF>.supabase.co/functions/v1/sportwinner-proxy" -H "Authorization: Bearer <ANON_KEY>" -H "Content-Type: application/json" -d '{"verband":"kvn","command":"DropTable","params":{}}'
```

Und in den Function-Logs darf **kein** Antwortinhalt stehen — geloggt werden nur Kommandoname
und Statuscode, weil die Antworten Klarnamen von Spielern tragen.
