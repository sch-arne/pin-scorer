// Abruf des öffentlichen Sportwinner-Ergebnisdienstes über das Relay.
//
// Gegenstück zu backend/sw-bruecke.js: dort spricht die App die lokale Brücke auf dem
// Vereins-PC an, hier den Verbands-Ergebnisdienst im Netz. Der Umweg über die Edge Function
// `sportwinner-proxy` ist nicht Bequemlichkeit, sondern Notwendigkeit — service.php antwortet
// nur auf Anfragen mit seinem eigenen Referer/Origin, und die darf ein Browser nicht setzen.
// Die Begründung und die Datenschutzregeln stehen im Kopf von
// supabase/functions/sportwinner-proxy/index.ts.
//
// Wie überall im Backend wird der Supabase-Client LAZY geladen, damit die App ohne Netz
// vollständig lauffähig bleibt.

// Verband = erstes Host-Label des Ergebnisdienstes (kvn.sportwinner.de -> "kvn"), genau wie
// in sw_ergebnisdienst.py. Voreinstellung ist der Kegelverband Niedersachsen.
export const VERBAND_STANDARD = 'kvn';

// Sportwinner-Sektionen (Disziplinen). 1 = Classic, 2 = Schere — dieselbe Zuordnung, die
// sektionToBahnart() in logic/roster-import.js verwendet.
export const SEKTIONEN = [
  { id: 2, label: 'Schere' },
  { id: 1, label: 'Classic' },
];

// Liga-Arten von GetLigaArray: Bundes- und Landesligen hängen an id_bezirk 0,
// Bezirksligen an einem echten Bezirk.
export const LIGA_ARTEN = [
  { art: 0, bezirk: 0, label: 'Bundesligen' },
  { art: 1, bezirk: 0, label: 'Landesligen' },
];

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

// Keine einzige Teilabfrage kam durch. Eigene Meldung, weil der Nutzer hier nichts falsch
// gemacht hat und ein zweiter Versuch meist hilft (die Ausfälle kommen in Wellen).
export const NICHTS_GELADEN = 'Der Ergebnisdienst hat keine Liga geliefert — '
  + 'die Verbindung zu ihm fällt derzeit phasenweise aus. Bitte gleich noch einmal versuchen.';

function klartext(error, body) {
  if (body) return body;                                   // Meldung der Function selbst
  const roh = (error && error.message) || '';
  if (/failed to send a request|failed to fetch|networkerror/i.test(roh)) {
    return NICHT_BEREITGESTELLT;
  }
  if (/jwt|unauthor|401/i.test(roh)) return 'Konto nötig — bitte unter „Spieler" anmelden.';
  return roh || 'Ergebnisdienst nicht erreichbar.';
}

async function relay(command, params, { verband = VERBAND_STANDARD } = {}) {
  const { supabase } = await import('./supabase.js');
  const { data, error } = await supabase.functions.invoke('sportwinner-proxy', {
    body: { verband, command, params: params || {} },
  });
  if (error) {
    // Die Function schickt ihre Meldung im Body — supabase-js legt sie nicht in error.message.
    let text = '';
    try { text = (await error.context?.json())?.error || ''; } catch { /* kein JSON-Body */ }
    throw new Error(klartext(error, text));
  }
  return (data && data.daten) || [];
}

export function saisons(opt) {
  // [[id_saison, jahr, aktiv]] -> die aktive zuerst, sonst absteigend nach Jahr.
  return relay('GetSaisonArray', {}, opt).then((rows) => rows
    .map((r) => ({ id: r[0], jahr: r[1], aktiv: String(r[2]) === '1' }))
    .sort((a, b) => (b.aktiv - a.aktiv) || String(b.jahr).localeCompare(String(a.jahr))));
}

export function bezirke(idSaison, sektion, opt) {
  return relay('GetBezirkArray', { id_saison: idSaison, id_sektion: sektion }, opt)
    .then((rows) => rows.map((r) => ({ id: r[0], name: r[1] })));
}

export function ligen(idSaison, sektion, idBezirk, art, opt) {
  return relay('GetLigaArray', {
    id_saison: idSaison, id_sektion: sektion, id_bezirk: idBezirk, favorit: '', art,
  }, opt).then((rows) => rows.map((r) => ({ id: r[0], name: r.length > 2 ? r[2] : '' })));
}

// Alle Ligen einer Saison: Bundes- und Landesligen plus die Bezirksligen jedes Bezirks.
// Bewusst sequenziell — der Ergebnisdienst soll nicht in Serie durchgeblättert werden
// (siehe Rate-Limit im Relay).
//
// Das sind ein halbes Dutzend Abfragen, und die Verbindung zum Ergebnisdienst fällt phasenweise
// aus (siehe supabase/functions/sportwinner-proxy: aus dem Rechenzentnum bleibt zeitweise jede
// Anfrage stumm). Früher riss EINE ausgefallene davon die ganze Liste mit: die Funktion warf,
// und die Auswahl blieb leer — obwohl die Bundes- und Landesligen längst da waren. Genau die
// braucht aber, wer ein Bundesliga-Spiel importieren will.
//
// Deshalb zählt jetzt, was ANKOMMT. Jede Teilabfrage darf einzeln scheitern; geworfen wird nur,
// wenn ÜBERHAUPT nichts zusammenkam. `unvollstaendig` sagt der Ansicht, dass sie zum Nachladen
// auffordern soll — eine kurze Liste ohne Hinweis wäre schlimmer als ein Fehler, weil die
// fehlende Liga dann wie „gibt es nicht" aussieht.
export async function alleLigen(idSaison, sektion, opt = {}) {
  const { nurBezirke = false } = opt;
  const out = [];
  let fehlend = 0;
  const merke = (liste) => liste.forEach((l) => {
    if (!out.some((x) => x.id === l.id)) out.push(l);
  });
  const versuche = async (fn) => {
    try { merke(await fn()); } catch { fehlend += 1; }
  };
  if (!nurBezirke) {
    for (const a of LIGA_ARTEN) await versuche(() => ligen(idSaison, sektion, a.bezirk, a.art, opt));
  }
  let bezirksliste = [];
  try {
    bezirksliste = await bezirke(idSaison, sektion, opt);
  } catch (e) {
    fehlend += 1;
    if (!out.length) throw e;            // nichts da UND die Bezirke fehlen -> echter Fehler
  }
  for (const bz of bezirksliste) {
    await versuche(() => ligen(idSaison, sektion, bz.id, 2, opt));
  }
  if (!out.length) throw new Error(NICHTS_GELADEN);
  out.unvollstaendig = fehlend > 0;
  return out;
}

// [id_spieltag, Nummer, "N. Spieltag", id_sektion]
export function spieltage(idSaison, sektion, idLiga, opt) {
  return relay('GetSpieltagArray', {
    id_saison: idSaison, id_sektion: sektion, id_liga: idLiga,
  }, opt).then((rows) => rows.map((r) => ({
    id: r[0], nr: r.length > 1 ? r[1] : null, name: (r.length > 2 && r[2]) || `Spieltag ${r[1]}`,
  })));
}

// Die Partien einer Liga. Rohzeilen — parseSpielListe() in logic/sw-web-import.js formt sie.
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
  return relay('GetBahnanlage', { id_saison: idSaison, id_sektion: sektion, id_liga: idLiga }, opt)
    .then((rows) => rows.map((r) => ({
      mannschaft: r[0], wochentag: r[1], uhrzeit: r[2], bahnen: r[3],
      anlage: r[4], plz: r[5], ort: r[6], strasse: r[7],
    })));
}
