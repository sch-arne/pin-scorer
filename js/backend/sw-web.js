// Abruf des öffentlichen Sportwinner-Ergebnisdienstes über das Relay.
//
// Gegenstück zu backend/sw-bruecke.js: dort spricht die App die lokale Brücke auf dem
// Vereins-PC an, hier den Verbands-Ergebnisdienst im Netz. Der Umweg über die Edge Function
// `sportwinner-proxy` ist nicht Bequemlichkeit, sondern Notwendigkeit — service.php antwortet
// nur auf Anfragen mit seinem eigenen Referer/Origin, und die darf ein Browser nicht setzen.
// Die Begründung und die Datenschutzregeln stehen im Kopf von
// supabase/functions/sportwinner-proxy/index.ts.
//
// WIE DIE ABFRAGEN AUSSEHEN MÜSSEN — und warum das über Zuverlässigkeit entscheidet
// ---------------------------------------------------------------------------------
// Alles hier ist am eigenen Client des Dienstes abgelesen (kvn.sportwinner.de/script/kvn/
// sportwinner.js) und am echten Dienst nachgemessen. Der entscheidende Punkt: DIE SEITE FRAGT
// NIE ALLE LIGEN AUF EINMAL. Sie hat ein Bereichs-Dropdown (Landesebene oder ein Bezirk) und
// ruft `GetLigaArray` genau einmal — für den gewählten Bereich. Genau so macht es die App jetzt
// auch. Früher lief sie den ganzen Baum ab: Bundesligen, Landesligen, Bezirksliste und dann je
// Bezirk noch eine Abfrage, zusammen rund ein Dutzend. Jede einzelne davon konnte in eine
// Ausfallwelle geraten (siehe unten), und eine ausgefallene riss entweder die Liste mit oder
// ließ Ligen fehlen. Zwei Abfragen statt zwölf sind deshalb kein Feinschliff, sondern der
// Unterschied zwischen „geht meistens" und „geht".
//
// Die zweite Hälfte davon ist der Zwischenspeicher weiter unten: was einmal da war, wird nicht
// erneut geholt. Saison-, Bereichs-, Liga- und Spieltagslisten ändern sich über eine Saison
// hinweg praktisch nicht — ein zweiter Import am selben Tag kommt damit ganz ohne Netz bis zur
// Partie-Auswahl. Und fällt eine Abfrage aus, darf die alte Antwort einspringen, statt den
// Nutzer vor eine leere Liste zu stellen.
//
// DAS AUSFALLBILD
// ---------------
// Vom Rechner eines Nutzers antwortet der Dienst zuverlässig, aus der Edge-Runtime bleibt
// zeitweise jede zweite Verbindung stumm stehen (Messung im Kopf des Relays). Dazu passt, was
// der Betreiber im Impressum seiner Seite schreibt: erlaubt sind „einzelne Abfragen … im
// normalen Maß einer menschlichen Nutzung", untersagt ist systematisches oder automatisiertes
// Auslesen, und er behält sich ausdrücklich die Sperrung von IP-Adressen vor. Die Konsequenz
// daraus steht in dieser Datei als Bauweise: so wenige Abfragen wie möglich, nur auf eine
// Nutzeraktion hin, mit Zwischenspeicher — und keine Verschleierung. Wird der Weg dauerhaft
// zugemacht, ist das die Antwort des Betreibers; dann fragt man beim Verband nach.
//
// Wie überall im Backend wird der Supabase-Client LAZY geladen, damit die App ohne Netz
// vollständig lauffähig bleibt.

// Verband = erstes Host-Label des Ergebnisdienstes (kvn.sportwinner.de -> "kvn"), genau wie
// in sw_ergebnisdienst.py. Voreinstellung ist der Kegelverband Niedersachsen.
export const VERBAND_STANDARD = 'kvn';

// Die Ergebnisdienste, die es gibt — am 27.09.2026 über DNS und einen Abruf der Startseite
// geprüft. Alle drei liegen auf demselben Server, führen aber verschiedene Bestände.
// `kvs`, `wkbv` und `dkb` lösen ebenfalls auf, antworten aber mit 403: dort läuft kein
// Ergebnisdienst.
//
// Die Liste ist eine Bequemlichkeit, keine Schranke: über VERBAND_FREI lässt sich jedes andere
// `<name>.sportwinner.de` eintippen, ohne dass die App dafür geändert werden muss (das Relay
// erlaubt jeden Host unter dieser Domain). Kommt ein Verband dazu, tippt man ihn ein.
export const VERBAENDE = [
  { id: 'kvn', label: 'Niedersachsen (KVN)', hinweis: 'Schere — Bezirks-, Landes- und Bundesligen' },
  { id: 'dskb', label: 'Bundesebene Schere (DSKB)', hinweis: 'nur die Schere-Bundesligen' },
  { id: 'dkbc', label: 'Bundesebene Classic (DKBC)', hinweis: 'Classic-Bundesligen und DKBC-Pokal' },
];

// Kennung eines selbst eingetippten Dienstes im Auswahlfeld.
export const VERBAND_FREI = '__frei__';

// Ein Verbandskürzel ist genau das erste Label eines Hostnamens — mehr darf es nicht sein,
// sonst zeigt die Anfrage irgendwohin. Dieselbe Prüfung macht das Relay noch einmal.
export function verbandGueltig(v) {
  return /^[a-z0-9][a-z0-9-]{0,29}$/.test(String(v || '').trim().toLowerCase());
}

// Sportwinner-Sektionen (Disziplinen). 1 = Classic, 2 = Schere — dieselbe Zuordnung, die
// sektionToBahnart() in logic/roster-import.js verwendet.
export const SEKTIONEN = [
  { id: 2, label: 'Schere' },
  { id: 1, label: 'Classic' },
];

// `art` von GetLigaArray, aus `Globals.Art` des Dienst-Clients übernommen:
//   0 Bund · 1 Land · 2 Bezirk · 3 Klub · 4 Favorit
// Bundes- und Landesligen hängen an id_bezirk 0, Bezirksligen an einem echten Bezirk.
export const ART_BUND = 0;
export const ART_LAND = 1;
export const ART_BEZIRK = 2;

// Meldung von supabase-js -> Klartext, mit dem der Nutzer etwas anfangen kann.
//
// supabase-js wirft „Failed to send a request to the Edge Function", sobald die Function gar
// nicht antwortet — und das heisst in der Praxis fast immer: sie ist noch nicht bereitgestellt
// (dann scheitert schon der CORS-Preflight). Diese Meldung unuebersetzt anzuzeigen laesst den
// Nutzer im Regen stehen; sie ist kein Bedienfehler und kein Netzproblem, sondern eine offene
// Aufgabe am Projekt.
export const NICHT_BEREITGESTELLT = 'Die Serverfunktion „sportwinner-proxy" antwortet nicht. '
  + 'Sie muss einmalig bereitgestellt werden (supabase/functions/README.md) — erst danach kann '
  + 'die App den Ergebnisdienst abfragen.';

function klartext(error, body) {
  if (body) return body;                                   // Meldung der Function selbst
  const roh = (error && error.message) || '';
  if (/failed to send a request|failed to fetch|networkerror/i.test(roh)) {
    return NICHT_BEREITGESTELLT;
  }
  if (/jwt|unauthor|401/i.test(roh)) return 'Konto nötig — bitte unter „Spieler" anmelden.';
  return roh || 'Ergebnisdienst nicht erreichbar.';
}

// Eine stumm gebliebene Abfrage — und nur die wird wiederholt. Eine inhaltliche Ablehnung
// (kein Konto, Limit, unbekanntes Kommando) ist eine Antwort und bleibt stehen.
const STUMM = 'Der Ergebnisdienst hat nicht geantwortet.';
const STUMM_RE = /nicht geantwortet|antwortete mit 5\d\d/i;

// Auch der letzte Anlauf blieb stumm. Eigene Meldung, weil der Nutzer hier nichts falsch gemacht
// hat und der naechste Versuch nach aller Erfahrung durchgeht. Bewusst ohne Anzahl: wie viele
// Anlaeufe in die Frist gepasst haben, ist fuer ihn ohne Belang.
export const ALLES_STUMM = 'Der Ergebnisdienst hat nicht geantwortet — die Verbindung zu ihm '
  + 'fällt derzeit phasenweise aus. Das liegt nicht an dieser App; '
  + 'bitte gleich noch einmal versuchen.';

// MEHRERE ANLAEUFE, JEDER MIT EIGENER UHR — das ist der Kern der Zuverlaessigkeit.
//
// Gemessen am 27.09.2026, 10 gleiche Abfragen: 5 blieben stumm, und zwar jede volle 25 Sekunden.
// Das waren die drei Wiederholungen INNERHALB des Relays, die alle zusammen erfolglos blieben.
// Ein NEUER Aufruf von hier aus war dagegen in 3 von 5 Faellen sofort da, in rund 0,3 Sekunden.
// Die Stille klebt also am einzelnen Aufruf — an der Instanz und ihrer Verbindung dorthin — und
// nicht am Zeitpunkt. Daraus folgt beides:
//
//   * Die Wiederholung gehoert HIERHER, nicht ins Relay. Dort ist sie dieselbe taube Leitung,
//     hier ist sie ein neuer Wurf. (Im Relay steht sie deshalb auf einem Versuch.)
//   * Gewartet wird nach UNSERER Uhr, nicht nach der des Relays. Antwortet der Ergebnisdienst,
//     dann binnen 5,2 Sekunden (so gemessen, meist in unter einer halben); was laenger braucht,
//     kommt nicht mehr. Nach ANLAUF_MS brechen wir also ab und werfen den naechsten — auch wenn
//     eine aeltere, noch nicht ersetzte Fassung der Function selbst 25 Sekunden warten wuerde.
//     So haengt die Wartezeit des Nutzers nicht daran, welche Fassung gerade bereitgestellt ist.
//
// Die Zahl der Anfragen an den Ergebnisdienst bleibt in der Rechnung dieselbe wie vorher (ein
// Aufruf mit drei Versuchen -> drei Aufrufe mit je einem). Das zaehlt, weil der Betreiber
// ausdruecklich nur Abfragen „im normalen Maß einer menschlichen Nutzung" gestattet. Solange
// eine aeltere Fassung der Function laeuft, die selbst noch wiederholt, kann ein abgebrochener
// Anlauf dort im Hintergrund weiterlaufen — ein Grund mehr, sie bereitzustellen.
const ANLAEUFE = 3;
const ANLAUF_MS = 7_000;
const ANLAUF_PAUSE_MS = 300;
const ANLAUF_FRIST_MS = 25_000;

async function relay(command, params, opt = {}) {
  const start = Date.now();
  for (let i = 1; i <= ANLAEUFE; i++) {
    try {
      return await einAnlauf(command, params, opt);
    } catch (e) {
      if (!STUMM_RE.test((e && e.message) || '')) throw e;
      if (i >= ANLAEUFE || Date.now() - start > ANLAUF_FRIST_MS) break;
      await new Promise((r) => setTimeout(r, ANLAUF_PAUSE_MS));
    }
  }
  throw new Error(ALLES_STUMM);
}

async function einAnlauf(command, params, { verband = VERBAND_STANDARD } = {}) {
  const { supabase } = await import('./supabase.js');
  const abbruch = new AbortController();
  const uhr = setTimeout(() => abbruch.abort(), ANLAUF_MS);
  let data;
  let error;
  try {
    ({ data, error } = await supabase.functions.invoke('sportwinner-proxy', {
      body: { verband, command, params: params || {} },
      signal: abbruch.signal,
    }));
  } finally {
    clearTimeout(uhr);
  }
  // Unsere eigene Uhr war es, nicht die Function: supabase-js meldet einen Abbruch als
  // „Failed to send a request", und das wuerde klartext() zu „Function nicht bereitgestellt"
  // machen — eine falsche Fehlersuche. Deshalb wird der Abbruch vorher abgefangen.
  if (abbruch.signal.aborted) throw new Error(STUMM);
  if (error) {
    // Die Function schickt ihre Meldung im Body — supabase-js legt sie nicht in error.message.
    let text = '';
    try { text = (await error.context?.json())?.error || ''; } catch { /* kein JSON-Body */ }
    throw new Error(klartext(error, text));
  }
  // „Nichts da" meldet der Dienst als `-1` (das Relay macht daraus []), bei einem Kommando ohne
  // Bestand auch schon mal als nackte Zahl. Alles, was keine Zeilenliste ist, ist deshalb eine
  // LEERE Liste — kein Fehler, und erst recht kein `.map` auf einer Zahl.
  const daten = data && data.daten;
  return Array.isArray(daten) ? daten : [];
}

// --- Zwischenspeicher --------------------------------------------------------
//
// Nur die reduzierten Listen landen hier, nie eine Antwort im Rohzustand: GetLigaArray liefert
// Name, Telefonnummer und E-Mail des Spielleiters mit, und die haben in einem Cache nichts zu
// suchen. Gespeichert wird, was die Auswahlfelder brauchen — Id und Bezeichnung.
// Spielberichte werden NIE zwischengespeichert: sie enthalten die Klarnamen aller Spieler.
const CACHE_PRAEFIX = 'sw-web-liste:';
const STUNDE = 60 * 60 * 1000;

function cacheLies(name) {
  try {
    const roh = localStorage.getItem(CACHE_PRAEFIX + name);
    if (!roh) return null;
    const e = JSON.parse(roh);
    return e && typeof e.t === 'number' && Array.isArray(e.v) ? e : null;
  } catch { return null; }
}

function cacheSchreib(name, wert) {
  try {
    localStorage.setItem(CACHE_PRAEFIX + name, JSON.stringify({ t: Date.now(), v: wert }));
  } catch { /* voll oder abgeschaltet: der Cache beschleunigt, er ist keine Bedingung */ }
}

// Alles vergessen, was zu einem Dienst gespeichert ist — für den Fall, dass der Ergebnisdienst
// etwas nachträgt und der Nutzer es sehen will, bevor die Frist abgelaufen ist.
export function cacheLeeren(verband) {
  const praefix = CACHE_PRAEFIX + (verband ? `${verband}:` : '');
  try {
    Object.keys(localStorage)
      .filter((k) => k.startsWith(praefix))
      .forEach((k) => localStorage.removeItem(k));
  } catch { /* kein localStorage: dann gab es auch nichts zu leeren */ }
}

// Holt `fn()`, aber nur wenn nötig — und behält die Antwort.
//
// Fällt die Abfrage aus und liegt eine ältere Antwort vor, gewinnt die alte mit dem Vermerk
// `ausCache`. Eine Liga-Liste von heute Morgen ist für die Auswahl so gut wie eine von jetzt;
// eine Fehlermeldung statt der Liste wäre dagegen das Ende des Imports.
async function gecached(name, frist, fn) {
  const alt = cacheLies(name);
  if (alt && Date.now() - alt.t < frist) return alt.v;
  try {
    const neu = await fn();
    cacheSchreib(name, neu);
    return neu;
  } catch (e) {
    if (!alt) throw e;
    const wert = alt.v.slice();
    wert.ausCache = alt.t;
    return wert;
  }
}

const cacheName = (opt, ...teile) => [(opt && opt.verband) || VERBAND_STANDARD, ...teile].join(':');

// --- Abfragen ----------------------------------------------------------------

// [[id_saison, jahr, flag]] -> nach Jahr absteigend, die neueste zuerst.
//
// Das dritte Feld ist NICHT „ist die aktuelle Saison": kvn liefert für 2026 eine „0", dskb für
// 2025 und 2024 eine „1". Der Client des Dienstes liest es überhaupt nicht — er nimmt eine fest
// eingebaute Saison-Id als Vorauswahl, und das ist die neueste. Genau das macht die Sortierung.
// (Vorher stand „(aktuell)" an den ALTEN Saisons — das kam von diesem Feld.)
export function saisons(opt) {
  return gecached(cacheName(opt, 'saisons'), 12 * STUNDE, () => relay('GetSaisonArray', {}, opt)
    .then((rows) => rows
      .map((r) => ({ id: r[0], jahr: r[1] }))
      .sort((a, b) => String(b.jahr).localeCompare(String(a.jahr)))));
}

export function bezirke(idSaison, sektion, opt) {
  return relay('GetBezirkArray', { id_saison: idSaison, id_sektion: sektion }, opt)
    .then((rows) => rows.map((r) => ({ id: r[0], name: r[1] })));
}

// Die Bereiche einer Saison — genau das Dropdown, das der Ergebnisdienst selbst anbietet.
//
// EINE Abfrage (die Bezirksliste), und der Rest steht fest. Danach holt ligen() die Ligen des
// gewählten Bereichs mit einer zweiten.
//
// Fällt die Bezirksliste aus, wird hier nichts geworfen: die Bundes- und Landesebene sind dann
// trotzdem erreichbar, und die will hier fast immer jemand. Aber das Ergebnis wird dann auch
// NICHT gespeichert und trägt `unvollstaendig` — sonst stünde zwölf Stunden lang „es gibt keine
// Bezirke" im Zwischenspeicher, obwohl bloß eine Abfrage stumm geblieben ist. Genau das ist
// beim ersten Live-Durchlauf passiert.
//
// Ein Dienst OHNE Bezirke ist davon zu unterscheiden: dskb und dkbc antworten auf
// GetBezirkArray mit „-1", daraus wird eine leere Liste — eine Antwort, kein Ausfall. Die beiden
// festen Einträge sind dort das vollständige Ergebnis und dürfen gespeichert werden.
export async function bereiche(idSaison, sektion, opt = {}) {
  const fest = [
    { id: `${ART_BUND}:0`, name: 'Bundesligen', art: ART_BUND, bezirk: 0 },
    { id: `${ART_LAND}:0`, name: 'Landesligen', art: ART_LAND, bezirk: 0 },
  ];
  const name = cacheName(opt, 'bereiche', idSaison, sektion);
  const alt = cacheLies(name);
  if (alt && Date.now() - alt.t < 12 * STUNDE) return alt.v;
  try {
    const liste = await bezirke(idSaison, sektion, opt);
    const out = fest.concat(liste.map((bz) => ({
      id: `${ART_BEZIRK}:${bz.id}`, name: bz.name, art: ART_BEZIRK, bezirk: bz.id,
    })));
    cacheSchreib(name, out);
    return out;
  } catch (e) {
    if (alt) {
      const wert = alt.v.slice();
      wert.ausCache = alt.t;
      return wert;
    }
    const wert = fest.slice();
    wert.unvollstaendig = true;
    return wert;
  }
}

// Der Liga-Name steht NICHT bei allen Diensten in derselben Spalte: `kvn` und `dkbc` liefern
// [id, wertung, Name, art, …], `dskb` dagegen [id, Name, art, …] — dort fehlt die Wertung ganz.
// Mit einer festen Spalte hiess die Liga auf dskb schlicht "0". Deshalb die erste Zelle nach der
// id, die ueberhaupt Buchstaben traegt — Ligennamen haben immer welche ("Herren - 2. Bundesliga
// Nord"), die Zaehlspalten nie.
export function ligenName(r) {
  for (let i = 1; i < r.length; i++) {
    const z = r[i] == null ? '' : String(r[i]).trim();
    if (/\p{L}/u.test(z)) return z;
  }
  return '';
}

// Die Wertung der Liga: 0 = Kegel/Holz, 1 = Punkte (Globals.Art.Kegel/Punkte).
// Sie steht — wenn überhaupt — in der Zelle direkt nach der id, also VOR dem Namen.
// Sie zählt, weil GetSpielerInfo sie als Parameter erwartet und das Layout des Berichts daran
// hängt. Die Partie-Zeile führt sie zwar auch, aber nicht bei jedem Dienst (dskb nicht) —
// deshalb wird sie hier mitgenommen und dient dort als Rückfall.
export function ligenWertung(r) {
  const z = r[1] == null ? '' : String(r[1]).trim();
  return /^\d+$/.test(z) ? Number(z) : null;
}

export function ligen(idSaison, sektion, idBezirk, art, opt) {
  return gecached(cacheName(opt, 'ligen', idSaison, sektion, art, idBezirk), 12 * STUNDE,
    () => relay('GetLigaArray', {
      id_saison: idSaison, id_sektion: sektion, id_bezirk: idBezirk, favorit: '', art,
    }, opt).then((rows) => rows.map((r) => ({
      id: r[0], name: ligenName(r), wertung: ligenWertung(r),
    }))));
}

// Die Spieltage einer Liga: [id_spieltag, Nummer, "N. Spieltag", Status].
//
// Status „1" heisst beendet — der Dienst setzt dafür in seiner eigenen Liste ein Häkchen. Das
// ist hier keine Zierde: nur ein gespielter Spieltag hat Berichte, und wer die Liste sieht,
// erkennt daran sofort, wo etwas zu holen ist. Gefiltert wird NICHT — auch an einem noch
// laufenden Spieltag kann die eigene Partie längst fertig sein.
//
// `id_sektion` schickt der Dienst-Client hier nicht mit; wir tun es trotzdem, weil die Antwort
// mit und ohne nachgemessen identisch ist und der Parameter die Anfrage eindeutiger macht.
export function spieltage(idSaison, sektion, idLiga, opt) {
  return gecached(cacheName(opt, 'spieltage', idSaison, sektion, idLiga), 6 * STUNDE,
    () => relay('GetSpieltagArray', {
      id_saison: idSaison, id_sektion: sektion, id_liga: idLiga,
    }, opt).then((rows) => rows.map((r) => ({
      id: r[0],
      nr: r.length > 1 ? r[1] : null,
      name: (r.length > 2 && r[2]) || `Spieltag ${r[1]}`,
      beendet: r.length > 3 && String(r[3]) === '1',
    }))));
}

// Die Partien einer Liga. Rohzeilen — parseSpielListe() in logic/sw-web-import.js formt sie.
// Bewusst OHNE Zwischenspeicher: hier ändern sich Stände, und ein alter Stand wäre schlimmer
// als eine Wartezeit.
//
// `art_spieltag` steuert, WELCHE Partien kommen, und die Werte sind nicht offensichtlich
// (am echten Dienst ausprobiert):
//   0/1 mit id_spieltag=0  -> nur der AKTUELLE Spieltag
//   2   mit echter id      -> genau dieser Spieltag
// Ohne die 2 liefert eine Abfrage mit id_spieltag schlicht eine leere Liste — auch fuer
// laengst gespielte Spieltage, und genau die will der Import.
export function spiele(idSaison, sektion, idLiga, idSpieltag, opt) {
  return relay('GetSpiel', {
    id_saison: idSaison,
    id_sektion: sektion,
    id_klub: 0,
    id_bezirk: 0,
    id_liga: idLiga,
    id_spieltag: idSpieltag || 0,
    favorit: '',
    art_bezirk: 0,
    art_liga: 0,
    art_spieltag: idSpieltag ? 2 : 0,
  }, opt);
}

// Der Spielbericht einer Partie. Rohzeilen — parseSpielerInfo() formt sie.
// Den `thumbmark`-Parameter setzt ausschliesslich das Relay (siehe dort) — er wird hier
// bewusst nicht mitgegeben, damit aus dem Browser des Nutzers nie ein Fingerprint abgeht.
// Kein Zwischenspeicher: der Bericht nennt die Klarnamen aller Spieler.
export function spielbericht(idSaison, sektion, idSpiel, wertung, opt) {
  return relay('GetSpielerInfo', {
    id_saison: idSaison,
    id_sektion: sektion,
    id_spiel: idSpiel,
    wertung: wertung == null ? 0 : wertung,
  }, opt);
}

// Die Bahnanlagen einer Liga — liefert je Mannschaft Anlage, Bahnen und Adresse und ist die
// einzige Quelle, aus der der Web-Weg die BESPIELTEN BAHNEN einer Partie erfährt.
export function bahnanlagen(idSaison, sektion, idLiga, opt) {
  return gecached(cacheName(opt, 'anlagen', idSaison, sektion, idLiga), 12 * STUNDE,
    () => relay('GetBahnanlage', { id_saison: idSaison, id_sektion: sektion, id_liga: idLiga }, opt)
      .then((rows) => rows.map((r) => ({
        mannschaft: r[0], wochentag: r[1], uhrzeit: r[2], bahnen: r[3],
        anlage: r[4], plz: r[5], ort: r[6], strasse: r[7],
      }))));
}
