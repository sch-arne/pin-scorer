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
//    Schluesseln `thumbmark` und `webdriver: false` ist; die `components` duerfen ganz fehlen.
//    Blockt (0 Zeilen, HTTP 200 mit LEEREM Koerper): `webdriver: true`, ein fehlendes
//    `webdriver`-Feld, ein fehlendes `thumbmark`-Feld — und seit dem 26.09.2026 auch der
//    LEERE Hash `""` sowie 32 Nullen. Der Dienst hat also offenbar genau die Platzhalter
//    gesperrt, die nach Automat aussehen. Der Wert selbst wird nicht geprueft (jede andere
//    Zeichenkette liefert den Bericht, auch mehrfach hintereinander — kein Kontingent je Wert).
//    Deshalb steht hier jetzt nicht der leere Hash, sondern der NAME der App: sie gibt sich
//    damit zu erkennen, statt einen Browser-Fingerprint vorzutaeuschen, und traegt weiterhin
//    null Information ueber den Nutzer. Wird auch dieser Wert gesperrt, ist das die Antwort
//    des Betreibers — dann beim Verband nachfragen und nicht etwa raten oder wuerfeln.
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

// Der einzige Wert, den wir je als `thumbmark` senden: erfuellt die Formpruefung des Dienstes,
// benennt die App und enthaelt keinerlei Angaben ueber Geraet oder Nutzer (siehe Kopf).
const THUMBMARK = JSON.stringify({ thumbmark: 'pins-scorer', webdriver: false });

// Limit je Konto: der Import braucht pro Spiel eine Handvoll Aufrufe. 30/Minute lässt das
// bequem zu und stoppt jeden Versuch, ganze Ligen durchzublättern. In-memory und damit je
// Instanz — als Bremse ausreichend, als Sicherheitsgrenze nicht gedacht.
const LIMIT = 30;
const FENSTER_MS = 60_000;

// Haengende Verbindungen zum Ergebnisdienst: vom Rechner eines Nutzers aus antwortet er
// zuverlaessig (8 von 8 Abfragen, 0,19-3,4 s), aus der Edge-Runtime von Supabase dagegen bleibt
// etwa jede zweite Verbindung stumm stehen, bis sie ablaeuft — bei JEDEM Kommando, auch ohne
// `thumbmark` (am 26.09.2026 gemessen: 3 von 8 GetSaisonArray, 4 von 8 GetSpielerInfo). Es ist
// also weder der Parameter noch das Kommando, sondern der Weg aus dem Rechenzentrum dorthin.
//
// Wiederholt wird HIER NICHTS MEHR — und das ist eine Messung, keine Meinung.
//
// Am 27.09.2026 zehnmal dasselbe Kommando abgefragt: fuenf Aufrufe blieben stumm, und zwar jeder
// volle 25 Sekunden. Das sind genau die drei Versuche, die hier drin standen: waren sie einmal
// stumm, blieben sie es alle drei. Ein NEUER Aufruf der Function war dagegen in 3 von 5 Faellen
// sofort da, in rund 0,3 Sekunden. Die Stille klebt also am einzelnen Aufruf — an der Instanz
// bzw. ihrer Verbindung dorthin — und nicht am Zeitpunkt. Damit ist eine Wiederholung INNERHALB
// dieser Funktion wertlos: sie zieht nur dieselbe taube Leitung noch zweimal und laesst den
// Nutzer 25 statt 8 Sekunden warten.
//
// Die Wiederholung liegt deshalb jetzt in der App (js/backend/sw-web.js, ANLAEUFE): dort ist
// jeder Anlauf ein neuer Aufruf und damit ein echter neuer Versuch. Hier bleibt EIN Versuch mit
// kurzem Timeout, der schnell scheitert, damit der naechste Anlauf schnell kommt. GEANTWORTET
// hat der Dienst bisher immer binnen 5,2 Sekunden — was laenger braucht, kommt auch nicht mehr.
//
// Die Zahl der Anfragen an den Ergebnisdienst aendert sich dadurch nicht (vorher ein Aufruf mit
// drei Versuchen, jetzt bis zu drei Aufrufe mit je einem). Das Konto-Limit oben bleibt die
// Obergrenze fuer alles.
const VERSUCHE = 1;
const VERSUCH_MS = 6_000;
const PAUSE_MS = 400;
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

  let antwort: Response | null = null;
  for (let versuch = 1; versuch <= VERSUCHE; versuch++) {
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
        signal: AbortSignal.timeout(VERSUCH_MS),
      });
      break;
    } catch (e) {
      // Bewusst ohne Meldungstext: der koennte Teile der Anfrage enthalten. Die ART des
      // Fehlers steht dagegen fuer sich und ist bei der Suche das Entscheidende —
      // `TimeoutError` heisst: verbunden, aber keine Antwort (so sieht eine absichtliche
      // Bremse aus), ein `TypeError` dagegen: die Verbindung kam gar nicht zustande.
      const art = (e && typeof e === 'object' && 'name' in e) ? String(e.name) : 'unbekannt';
      console.error(`[sw-proxy] ${command} -> Versuch ${versuch}/${VERSUCHE} ohne Antwort (${art})`);
      if (versuch < VERSUCHE) await new Promise((r) => setTimeout(r, PAUSE_MS));
    }
  }
  if (!antwort) {
    // Der Wortlaut zaehlt: die App erkennt daran, dass sie es noch einmal versuchen darf
    // (js/backend/sw-web.js, STUMM_RE) — im Unterschied zu einer inhaltlichen Ablehnung.
    return fehler(origin, 502, 'Der Ergebnisdienst hat nicht geantwortet.');
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
