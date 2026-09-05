// Relay zum öffentlichen Sportwinner-Ergebnisdienst.
//
// WARUM ES DIESE FUNKTION ÜBERHAUPT GIBT
// --------------------------------------
// Die App kann `https://<verband>.sportwinner.de/php/<verband>/service.php` nicht direkt aus
// dem Browser aufrufen. Der Endpunkt antwortet nur auf Anfragen, die `Referer` und `Origin`
// des Ergebnisdienstes tragen (sonst 404) — beides sind "forbidden headers", die ein Browser
// nicht setzen darf; CORS-Header schickt der Endpunkt ohnehin keine. Der Aufruf muss also
// serverseitig passieren. Diese Funktion ist genau das und sonst nichts.
//
// DATENSCHUTZ — die Regeln, an die sie sich hält
// ----------------------------------------------
//  • Reine Durchleitung: KEIN Logging von Anfrage- oder Antwortkörpern, kein Cache, keine
//    Persistenz. Die Antworten enthalten Klarnamen von Spielern; die sollen nirgends liegen
//    bleiben. Geloggt wird nur, WAS schiefging (Kommandoname, Statuscode) — nie Inhalte.
//  • Der Ergebnisdienst erwartet an `GetSpielerInfo` einen Browser-Fingerprint (thumbmarkjs).
//    Den geben wir nicht weiter — statt dessen setzt das Relay den Konstantwert THUMBMARK.
//    Am echten Dienst ausprobiert: geprueft wird nur, dass das Feld ein JSON-Objekt mit den
//    Schluesseln `thumbmark` und `webdriver: false` ist. Der Hash selbst ist beliebig (auch
//    leer), die `components` duerfen ganz fehlen — `webdriver: true` blockt (Bot-Erkennung).
//    Der Konstantwert erfuellt die Pruefung und traegt null Information ueber den Nutzer.
//    Wird das Feld weggelassen oder auf einen blossen String gesetzt, kommen 0 Zeilen zurueck.
//  • Die IP des Nutzers erreicht Sportwinner nicht — nur die des Relays.
//  • Kein offener Proxy: nur angemeldete Konten, nur Hosts *.sportwinner.de, nur die
//    Kommandos aus KOMMANDOS, und ein Limit je Konto gegen massenhaftes Abziehen
//    (Datenbankherstellerrecht, § 87b UrhG — Einzelabruf auf Nutzeraktion ist gewollt,
//    systematisches Auslesen nicht).

const KOMMANDOS = new Set([
  'GetSaisonArray',
  'GetBezirkArray',
  'GetLigaArray',
  'GetSpieltagArray',
  'GetSpiel',
  'GetSpielerInfo',
  'GetBahnanlage',
]);

const HOST_RE = /^[a-z0-9-]+\.sportwinner\.de$/;
const KONTAKT = 'pins-scorer (Verein Osnabrücker Kegler e.V.)';

// Der einzige Wert, den wir je als `thumbmark` senden: erfuellt die Formpruefung des Dienstes
// und enthaelt keinerlei Angaben ueber Geraet oder Nutzer (siehe Kopf).
const THUMBMARK = JSON.stringify({ thumbmark: '', webdriver: false });

// Limit je Konto: der Import braucht pro Spiel eine Handvoll Aufrufe. 30/Minute lässt das
// bequem zu und stoppt jeden Versuch, ganze Ligen durchzublättern. In-memory und damit je
// Instanz — als Bremse ausreichend, als Sicherheitsgrenze nicht gedacht.
const LIMIT = 30;
const FENSTER_MS = 60_000;
const zaehler = new Map<string, { n: number; bis: number }>();

function limitUeberschritten(konto: string): boolean {
  const jetzt = Date.now();
  const e = zaehler.get(konto);
  if (!e || e.bis < jetzt) {
    zaehler.set(konto, { n: 1, bis: jetzt + FENSTER_MS });
    return false;
  }
  e.n += 1;
  return e.n > LIMIT;
}

const cors = (origin: string | null) => ({
  'Access-Control-Allow-Origin': origin || '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
  Vary: 'Origin',
});

const fehler = (origin: string | null, status: number, meldung: string) =>
  new Response(JSON.stringify({ error: meldung }), {
    status,
    headers: { ...cors(origin), 'Content-Type': 'application/json' },
  });

// Konto-Kennung aus dem JWT — nur für das Rate-Limit. Die Signaturprüfung macht die Plattform
// (verify_jwt), hier wird lediglich die Subject-Claim gelesen.
function kontoAus(auth: string | null): string | null {
  const t = (auth || '').replace(/^Bearer\s+/i, '');
  const teil = t.split('.')[1];
  if (!teil) return null;
  try {
    const json = atob(teil.replace(/-/g, '+').replace(/_/g, '/'));
    const sub = JSON.parse(json)?.sub;
    return typeof sub === 'string' && sub ? sub : null;
  } catch {
    return null;
  }
}

Deno.serve(async (req: Request) => {
  const origin = req.headers.get('origin');
  if (req.method === 'OPTIONS') return new Response('ok', { headers: cors(origin) });
  if (req.method !== 'POST') return fehler(origin, 405, 'Nur POST.');

  const konto = kontoAus(req.headers.get('authorization'));
  if (!konto) return fehler(origin, 401, 'Anmeldung nötig.');
  if (limitUeberschritten(konto)) {
    return fehler(origin, 429, 'Zu viele Abfragen — bitte kurz warten.');
  }

  let anfrage: { verband?: string; command?: string; params?: Record<string, unknown> };
  try {
    anfrage = await req.json();
  } catch {
    return fehler(origin, 400, 'Ungültige Anfrage.');
  }

  const verband = String(anfrage.verband || '').trim().toLowerCase();
  const command = String(anfrage.command || '').trim();
  if (!verband || !HOST_RE.test(`${verband}.sportwinner.de`)) {
    return fehler(origin, 400, 'Unbekannter Verband.');
  }
  if (!KOMMANDOS.has(command)) return fehler(origin, 400, `Kommando nicht erlaubt: ${command}`);

  const basis = `https://${verband}.sportwinner.de`;
  const body = new URLSearchParams({ command });
  for (const [k, v] of Object.entries(anfrage.params || {})) {
    if (v == null || k === 'thumbmark') continue;   // Fingerprint des Clients wird verworfen
    body.set(k, String(v));
  }
  if (command === 'GetSpielerInfo') body.set('thumbmark', THUMBMARK);

  let antwort: Response;
  try {
    antwort = await fetch(`${basis}/php/${verband}/service.php`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-Requested-With': 'XMLHttpRequest',
        Referer: `${basis}/`,
        Origin: basis,
        Accept: '*/*',
        'User-Agent': `Mozilla/5.0 ${KONTAKT}`,
      },
      body,
      signal: AbortSignal.timeout(20_000),
    });
  } catch {
    // Bewusst ohne Details: die Fehlermeldung könnte Teile der Anfrage enthalten.
    return fehler(origin, 502, 'Ergebnisdienst nicht erreichbar.');
  }

  if (!antwort.ok) {
    console.error(`[sw-proxy] ${command} -> HTTP ${antwort.status}`); // nur Status, nie Inhalt
    return fehler(origin, 502, `Ergebnisdienst antwortete mit ${antwort.status}.`);
  }

  const text = (await antwort.text()).trim();
  // Der Dienst signalisiert "leer" mit -1 oder einem leeren Körper.
  let daten: unknown = [];
  if (text !== '' && text !== '-1') {
    try {
      daten = JSON.parse(text);
    } catch {
      // Kein JSON heisst in aller Regel: die Schnittstelle hat sich geaendert. Der Text koennte
      // Personendaten enthalten und wird deshalb nicht mitgeloggt und nicht zurueckgegeben.
      console.error(`[sw-proxy] ${command} -> Antwort war kein JSON (${text.length} Zeichen)`);
      return fehler(origin, 502, 'Ergebnisdienst lieferte kein verwertbares JSON.');
    }
  }

  return new Response(JSON.stringify({ daten }), {
    headers: { ...cors(origin), 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });
});
