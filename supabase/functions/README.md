# Edge Functions

## `sportwinner-proxy`

Relay zum öffentlichen Sportwinner-Ergebnisdienst. Ohne diese Funktion bleibt der Web-Import
(`#/import/sportwinner-web`) leer — die App kann `service.php` nicht direkt aufrufen, weil der
Endpunkt `Referer`/`Origin` des Ergebnisdienstes verlangt und beides ein Browser nicht setzen
darf. Details und die Datenschutzregeln stehen im Kopf von `sportwinner-proxy/index.ts`.

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

Gegenprobe, dass die Allowlist greift — muss mit `400 Kommando nicht erlaubt` antworten:

```bash
curl -s -X POST "https://<PROJECT_REF>.supabase.co/functions/v1/sportwinner-proxy" -H "Authorization: Bearer <ANON_KEY>" -H "Content-Type: application/json" -d '{"verband":"kvn","command":"DropTable","params":{}}'
```

Und in den Function-Logs darf **kein** Antwortinhalt stehen — geloggt werden nur Kommandoname
und Statuscode, weil die Antworten Klarnamen von Spielern tragen.
