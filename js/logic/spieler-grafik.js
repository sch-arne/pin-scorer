// Spieler-Grafik: das MODELL hinter der Ergebnisansicht EINES Spielers
// (logic/spieler-zeichnen.js zeichnet es, views/grafik-panel.js bedient es im Reiter
// „Spieler"). Reine Logik — Browser + Node ladbar, per Unit-Test abgesichert, kein DOM.
//
// Das Bild ist das Wurfprotokoll (logic/wurfprotokoll.js) als teilbare Grafik: jeder
// Einzelwurf, je Teilsatz eine Zeile mit ihrer Summe, je Satz das Satz-Ergebnis, unten die
// Kennzahlen. Anders als das A4-Blatt ist es EIN Spieler auf EINEM Bild mit transparentem
// Hintergrund — gedacht für Stream, Chat und soziale Netzwerke.
//
// Die Eingangsdaten sind dieselben ROHEN Daten wie bei der Ergebnis-Grafik
// (`{ wettkampf, games }` / `{ game }`), damit das Panel beide Reiter aus einer Quelle
// speist und die Rechenkette hier (und nicht im View) liegt.

import { computeGameStats } from './statistik.js';
import { teilsatzRanges } from './teilsaetze.js';
import { satzStatus } from './holz.js';
import { isAbraeumMode, abraeumScan, volleKranz } from './abraeumen.js';
import { GRAFIK_FORMATE, GRAFIK_SCHRIFTEN, GRAFIK_ACCENT_DEFAULT } from './ergebnis-grafik.js';
import { dateiSicher, datumTeil } from './wurf-csv.js';

// Beschriftung der Teilsätze — lang für die Fußzeile, kurz für die Wurfzeile (die Spalte
// ist schmal, damit möglichst viel Platz für die Würfe bleibt).
export const MODUS_LANG = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz-Abräumen' };
export const MODUS_KURZ = { volle: 'Volle', abraeumen: 'Abräum.', 'kranz-abraeumen': 'Kranz' };

const TEXTFARBEN = ['hell', 'dunkel'];
const FLAECHEN = ['aus', 'dezent', 'kraeftig'];
const POSITIONEN = ['oben', 'mitte', 'unten'];
// Reihenfolge der Blöcke im Bild. 'saetze' ist die Spielreihenfolge, 'bahnen' sortiert nach
// der Bahnnummer — dieselbe Wahl wie die Spalten der Beamer-Tafel (views/beamer.js). Wer auf
// Bahn 3 anfängt, sieht damit wahlweise 1…4 (Sätze) oder 1…4 (Bahnen, also Satz 3,4,1,2).
export const REIHENFOLGEN = ['saetze', 'bahnen'];

// Standard-Einstellungen der Spieler-Grafik (gespeichert unter `settings.spielerGrafik`).
// Format/Schrift/Textfarbe/Flächen/Position/Kontur bedeuten dasselbe wie bei der
// Ergebnis-Grafik; sie werden bewusst GETRENNT gemerkt: eine Wurftabelle braucht oft ein
// anderes Format als die Rangliste.
export const SPIELER_GRAFIK_DEFAULT = {
  format: 'hoch',
  schrift: 'system',
  textfarbe: 'hell',
  kontur: true,
  flaechen: 'dezent',
  position: 'mitte',
  reihenfolge: 'saetze',  // Blöcke nach Satz-Nummer ('saetze') oder Bahnnummer ('bahnen')
  logo: true,          // Logo der Mannschaft neben dem Namen (nur wenn eines hinterlegt ist)
  kegelbilder: true,   // Kegelbild über jedem Wurf (● gefallen · ○ stehend)
  wurfnummern: false,  // kleine Wurfnummer unter jedem Wurf (je Satz gezählt)
  kennzahlen: true,    // Fußzeile mit Teilsatz-Summen, 9ern, Kränzen und Fehlern
};

// Gespeicherte Einstellungen -> vollständige Optionen. Wie grafikOptionen() in
// ergebnis-grafik.js ein eigener Merge, weil store.js flach mischt und ein später
// ergänzter Standard Bestandsnutzer sonst nicht erreicht.
export function spielerGrafikOptionen(settings) {
  const roh = settings && settings.spielerGrafik;
  return { ...SPIELER_GRAFIK_DEFAULT, ...(roh && typeof roh === 'object' ? roh : {}) };
}

// Optionen gegen das Modell gültig machen: unbekannte Werte zurück auf den Standard und
// alles abschalten, wofür die Daten fehlen (Kegelbilder ohne erfasste Kegel). Das Panel
// sperrt dieselben Schalter sichtbar.
export function normalisiereSpielerOptionen(opts, modell) {
  const o = { ...SPIELER_GRAFIK_DEFAULT, ...(opts && typeof opts === 'object' ? opts : {}) };
  if (!GRAFIK_FORMATE.includes(o.format)) o.format = SPIELER_GRAFIK_DEFAULT.format;
  if (!GRAFIK_SCHRIFTEN.includes(o.schrift)) o.schrift = SPIELER_GRAFIK_DEFAULT.schrift;
  if (!TEXTFARBEN.includes(o.textfarbe)) o.textfarbe = SPIELER_GRAFIK_DEFAULT.textfarbe;
  if (!FLAECHEN.includes(o.flaechen)) o.flaechen = SPIELER_GRAFIK_DEFAULT.flaechen;
  if (!POSITIONEN.includes(o.position)) o.position = SPIELER_GRAFIK_DEFAULT.position;
  if (!REIHENFOLGEN.includes(o.reihenfolge)) o.reihenfolge = SPIELER_GRAFIK_DEFAULT.reihenfolge;
  o.kontur = !!o.kontur;
  o.logo = !!o.logo;
  o.kegelbilder = !!o.kegelbilder;
  o.wurfnummern = !!o.wurfnummern;
  o.kennzahlen = !!o.kennzahlen;
  if (!(modell && modell.hatLogo)) o.logo = false;
  if (!(modell && modell.hatKegel)) o.kegelbilder = false;
  if (!(modell && modell.hatWuerfe)) o.wurfnummern = false;
  return o;
}

// ── Spieler-Auswahl ──────────────────────────────────────────────────────────

// Schlüssel eines Spielers: Spiel + Platz in dessen Aufstellung. Stabil über ein
// Neu-Laden der Daten hinweg (↻ im Panel) und eindeutig auch über mehrere Durchgänge.
export function spielerKey(gameId, index) {
  return String(gameId || '') + '#' + index;
}

function quelleAus(game, index, extra) {
  const sp = (game.config.spielerListe || [])[index] || {};
  return {
    key: spielerKey(game.id, index),
    gameId: game.id || '',
    index,
    name: sp.name || ('Spieler ' + (index + 1)),
    hatName: !!String(sp.name || '').trim(),
    mannschaft: null,
    teamPos: sp.teamPos || null,
    startBahn: sp.startBahn == null ? null : sp.startBahn,
    ...extra,
  };
}

// Alle wählbaren Spieler der Rohdaten — im Wettkampf nach Mannschaft und Aufstellung
// sortiert (wie das Overlay sie zeigt), im Einzelspiel in Aufstellungsreihenfolge.
// Spieler ohne Namen bleiben drin: sie tragen trotzdem Ergebnisse.
export function spielerQuellen(roh) {
  const q = roh || {};
  if (q.wettkampf) {
    const teams = q.wettkampf.mannschaften || [];
    const reihenfolge = {};
    const teamById = {};
    teams.forEach((m, i) => { reihenfolge[m.id] = i; teamById[m.id] = m; });
    const byId = {};
    (q.games || []).forEach((g) => { if (g && g.id) byId[g.id] = g; });
    const liste = [];
    (q.wettkampf.durchgaenge || []).slice()
      .sort((a, b) => (a.nr || 0) - (b.nr || 0))
      .forEach((d) => {
        const game = byId[d.gameId];
        if (!game || !game.config || !Array.isArray(game.config.spielerListe)) return;
        game.config.spielerListe.forEach((sp, i) => {
          const team = sp.mannschaftId ? teamById[sp.mannschaftId] : null;
          liste.push(quelleAus(game, i, {
            mannschaft: (team && team.name) || null,
            mannschaftId: sp.mannschaftId || null,
            // Logo und Akzentfarbe der Mannschaft — dieselbe Quelle wie in der
            // Ergebnis-Grafik und im Overlay (am Wettkampf, nicht am Spiel).
            logo: (team && team.logo) || null,
            logoBg: team && team.logoBg === 'light' ? 'light' : 'dark',
            accent: accentOf(team),
            durchgangNr: d.nr || null,
          }));
        });
      });
    const rang = (id) => (id != null && reihenfolge[id] != null ? reihenfolge[id] : 99);
    liste.sort((a, b) => rang(a.mannschaftId) - rang(b.mannschaftId)
      || (a.teamPos || 99) - (b.teamPos || 99)
      || (a.durchgangNr || 0) - (b.durchgangNr || 0));
    return liste;
  }
  const g = q.game;
  if (!g || !g.config || !Array.isArray(g.config.spielerListe)) return [];
  return g.config.spielerListe.map((sp, i) => quelleAus(g, i, { durchgangNr: null }));
}

// Akzentfarbe einer Mannschaft, streng validiert (#rrggbb) — sie landet direkt als
// Canvas-Farbe. Gleiche Regel wie in ergebnis-grafik.js.
function accentOf(team) {
  const c = team && team.accent;
  return /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : GRAFIK_ACCENT_DEFAULT;
}

// Den gewählten Spieler auflösen — unbekannter/leerer Schlüssel nimmt den ersten.
function findeQuelle(quellen, key) {
  return quellen.find((x) => x.key === key) || quellen[0] || null;
}

function spielAus(roh, gameId) {
  const q = roh || {};
  if (q.wettkampf) return (q.games || []).find((g) => g && g.id === gameId) || null;
  return q.game || null;
}

function datumText(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('de-DE');
}

// ── Würfe eines Satzes ───────────────────────────────────────────────────────

// Die Einzelwürfe EINES Teilsatzes mit allem, was das Bild braucht: Wert, Kegelbild,
// Kranz-Zeichen und die Wurfnummer innerhalb des Satzes.
//
// Kegelbild und Kranz kommen direkt aus dem Satz-Block (nicht aus computeGameStats, das
// nur Zahlen liefert) — genau wie im Wurfprotokoll, inklusive des Rückfalls für ALTDATEN,
// bei denen der Kranz-Langdruck kein Kegelbild abgelegt hat.
function wuerfeDesTeilsatzes(blk, r) {
  const alle = Array.isArray(blk.wuerfe) ? blk.wuerfe : [];
  const kegelArr = Array.isArray(blk.kegel) ? blk.kegel : [];
  const scan = isAbraeumMode(r.modus) ? abraeumScan(blk, r) : null;
  const ende = Math.min(r.end, alle.length);
  const out = [];
  for (let k = r.start; k < ende; k += 1) {
    const wert = alle[k];
    const koenig = Array.isArray(blk.koenig) ? !!blk.koenig[k] : false;
    // Echter Kranz (fürs ♔) wie in der Erfassung: aus dem Abräum-Scan bzw. volleKranz.
    // NICHT das koenig-Flag — eine 2 per Langdruck lässt den König stehen, ist aber kein Kranz.
    const kranz = scan ? !!scan.kranzAt[k] : (r.modus === 'volle' && volleKranz(blk, k));
    let kegel = kegelArr[k] != null ? kegelArr[k] : null;
    if (kegel == null && koenig && scan) {
      const st = scan.before[k];
      if (st && st.exact) {
        const fallen = st.standing.filter((p) => p !== 5);
        if (fallen.length === wert) kegel = fallen;
      }
    }
    out.push({
      nr: k + 1,                                  // Wurfnummer innerhalb des Satzes
      wert,
      kegel: Array.isArray(kegel) ? kegel : null, // null = Bild unbekannt
      kranz,
      neuner: wert === 9,
      fehl: wert === 0,
    });
  }
  return out;
}

// ── Modell ───────────────────────────────────────────────────────────────────

function leeresModell() {
  return {
    key: '', gameId: '', index: -1,
    name: '', mannschaft: null, mannschaftId: null, bahn: null, durchgangNr: null,
    logo: null, logoBg: 'dark', accent: GRAFIK_ACCENT_DEFAULT, hatLogo: false,
    ueberschrift: '', titel: 'Spieler', eigenerTitel: '', untertitel: '', datumIso: null,
    saetze: [], summen: [],
    gesamt: 0, neuner: 0, kranz: 0, fehl: 0, wurfCount: 0, schnitt: 0,
    hatWuerfe: false, hatKegel: false, leer: true,
  };
}

// Schlüssel, unter dem die eigene Überschrift dieses Spielers gemerkt wird. Eigener
// Präfix, weil sich der Topf (settings.grafikTexte) die Einträge mit der Ergebnis-Grafik
// teilt — deren Schlüssel sind 'wk:'/'sp:'.
export function spielerTextId(key) {
  return key ? 'spieler:' + key : '';
}

// Rohdaten + Spieler-Schlüssel -> Modell für die Spieler-Grafik.
//   roh   — { wettkampf, games } oder { game } (wie bei grafikModell)
//   key   — spielerKey(); unbekannt/leer nimmt den ersten Spieler
//   kopf  — { ueberschrift, titel, untertitel }: die freie Überschrift ÜBER dem Namen (leer
//           -> keine Zeile), der Name selbst (leer -> der Name aus der Aufstellung) und die
//           Kontextzeile darunter (leer -> Wettkampfname und Datum)
export function spielerGrafikModell(roh, key, kopf = {}) {
  const quellen = spielerQuellen(roh);
  const quelle = findeQuelle(quellen, key);
  if (!quelle) return leeresModell();
  const game = spielAus(roh, quelle.gameId);
  const c = game && game.config;
  if (!c || !Array.isArray(c.spielerListe)) return leeresModell();

  const ranges = teilsatzRanges(c);
  const bloecke = (game.erfassung && game.erfassung.bloecke) || [];
  const { players } = computeGameStats(c, bloecke, ranges);
  const p = players[quelle.index];
  if (!p) return leeresModell();
  const arr = Array.isArray(bloecke[quelle.index]) ? bloecke[quelle.index] : [];

  let hatWuerfe = false;
  let hatKegel = false;
  const saetze = p.saetze.map((s, st) => {
    const blk = arr[st] || { wuerfe: [], overrides: [], kegel: [] };
    const status = satzStatus(blk);
    const teilsaetze = s.teilsaetze.map((ts, ti) => {
      const wuerfe = wuerfeDesTeilsatzes(blk, ranges[ti]);
      if (wuerfe.length) hatWuerfe = true;
      if (wuerfe.some((w) => w.kegel)) hatKegel = true;
      return {
        modus: ts.modus,
        label: MODUS_LANG[ts.modus] || ts.modus,
        kurz: MODUS_KURZ[ts.modus] || ts.modus,
        soll: ts.soll,
        holz: ts.holz,
        // Nur als Summe eingetragen (Übersicht, Import) -> es gibt keine Einzelwürfe.
        manual: !!ts.manual,
        // Der Satz trägt sein Holz selbst (Web-Import) -> die Teilsätze sind unbekannt.
        ohneTeilsatz: !!s.nurSatz,
        wuerfe,
      };
    });
    return {
      nr: s.satz,
      bahn: s.bahn,
      holz: s.holz,
      // Ein noch gar nicht gespielter Satz zeigt „–" statt einer 0.
      gespielt: status !== 'pending',
      nurSatz: !!s.nurSatz,
      teilsaetze,
    };
  });

  // Teilsatz-Summen je Modus über alle Sätze (Volle/Abräumen/Kranz) — wie im Fuß des
  // Wurfprotokolls. Ein Satz ohne Teilsatz-Aufteilung trägt hier nichts bei.
  const summen = [];
  const topf = {};
  saetze.forEach((s) => s.teilsaetze.forEach((ts) => {
    if (!(ts.label in topf)) { topf[ts.label] = 0; summen.push({ label: ts.label, val: 0 }); }
    topf[ts.label] += ts.ohneTeilsatz ? 0 : ts.holz;
  }));
  summen.forEach((e) => { e.val = topf[e.label]; });

  const wkName = (roh && roh.wettkampf && roh.wettkampf.name) || '';
  const datumIso = (roh && roh.wettkampf && roh.wettkampf.datum) || (game && game.createdAt) || null;
  const eigen = kopf && typeof kopf.untertitel === 'string' ? kopf.untertitel.trim() : '';
  const kontext = eigen || [wkName, datumText(datumIso)].filter(Boolean).join(' · ');
  // Der Name ist frei überschreibbar; ohne Eingabe steht der aus der Aufstellung da.
  const eigenerTitel = kopf && typeof kopf.titel === 'string' ? kopf.titel.trim() : '';
  // Die Überschrift ist eine ZUSÄTZLICHE Zeile über dem Namen — ohne Eingabe gibt es sie nicht.
  const ueberschrift = kopf && typeof kopf.ueberschrift === 'string' ? kopf.ueberschrift.trim() : '';

  // Die Mannschaft steht vor der Kontextzeile — aber nicht doppelt: im Punktspiel heißt der
  // Wettkampf oft „Heim – Gast", und „VOK 1 · VOK 1 – KV Sontra 1" liest sich wie ein Fehler.
  const mannschaft = quelle.mannschaft || '';
  const mannschaftZeigen = mannschaft && !kontext.includes(mannschaft);

  return {
    key: quelle.key,
    gameId: quelle.gameId,
    index: quelle.index,
    name: p.name,
    mannschaft: quelle.mannschaft || null,
    mannschaftId: quelle.mannschaftId || null,
    logo: quelle.logo || null,
    logoBg: quelle.logoBg === 'light' ? 'light' : 'dark',
    accent: quelle.accent || GRAFIK_ACCENT_DEFAULT,
    hatLogo: !!quelle.logo,
    bahn: quelle.startBahn == null ? (saetze[0] ? saetze[0].bahn : null) : quelle.startBahn,
    durchgangNr: quelle.durchgangNr || null,
    ueberschrift,
    titel: eigenerTitel || p.name,
    eigenerTitel,
    untertitel: [mannschaftZeigen ? mannschaft : '', kontext].filter(Boolean).join(' · '),
    datumIso,
    saetze,
    summen,
    gesamt: p.gesamt,
    neuner: p.neuner,
    kranz: p.kranz,
    fehl: p.fehl,
    wurfCount: p.wurfCount,
    schnitt: p.schnittWurf,
    hatWuerfe,
    hatKegel,
    leer: false,
  };
}

// Dateiname der PNG: Wurfbild_<Überschrift>_<Datum>.png (Helfer wie beim CSV-Export).
// Ohne eigene Überschrift ist das der Spielername.
export function spielerGrafikDateiname(modell) {
  const m = modell || {};
  const wer = dateiSicher(m.titel) || dateiSicher(m.name) || 'Spieler';
  return ['Wurfbild', wer, datumTeil(m.datumIso)].join('_') + '.png';
}
