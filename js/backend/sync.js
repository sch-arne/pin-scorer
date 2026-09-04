// Sync-Kern: verbindet ein lokales Spiel mit Supabase und haelt es mehrgeraetig
// synchron. Wird nur LAZY geladen (dynamic import), damit die local-first App
// ohne Verbindung unbeeintraechtigt bleibt.
//
// Leitidee: Ein Spieler gehoert zu jeder Zeit genau EINEM Geraet. Alle Daten
// eines Spielers (satz_block-Zeilen) schreibt nur dessen Besitzer-Geraet — die
// DB (RLS) setzt das durch. Deshalb ist kein wurf-genaues Merge noetig: Merge
// laeuft pro (spieler, satz) und ist wegen Single-Writer trivial.
//
// Mapping local <-> remote:
//   game.config            -> spiel.config_json
//   game.spiel             -> spiel.spielart
//   game.status            -> spiel.status
//   config.spielerListe[i] -> spiel_spieler { position:i, name, start_bahn, passnummer, profil_id }
//   erfassung.bloecke[i][s]-> satz_block { spieler_id(pos i), satz:s, block_json }
//
// aktiverSpieler/aktiverSatz sind reine Geraete-UI-Zustaende und werden NICHT
// synchronisiert.

import { supabase } from './supabase.js';
import { ensureGeraet, geraetId, kontoId } from './geraet.js';
import { getGame, getWettkampf } from '../store.js';
import {
  mergeSpielerNamen, passByPosition, resolveIchIndex, istLizenzWettkampf,
} from '../logic/spieler-identitaet.js';

export { istLizenzWettkampf };
import { sportwinnerOhnePersonendaten } from '../logic/wettkampf-build.js';
import { ohneVerborgene } from '../logic/loeschen.js';
import { computeGameStats } from '../logic/statistik.js';
import { teilsatzRanges } from '../logic/teilsaetze.js';
import { ergebnisZeilen } from '../logic/ergebnis-snapshot.js';
import { schreibeVertraeglich as dbSchreibeVertraeglich } from '../logic/db-spalten.js';

export { ensureGeraet, geraetId, kontoId };

const STALE_MS = 30_000; // Besitz gilt als "inaktiv", wenn Heartbeat aelter (siehe RLS)

// --- Hilfen -----------------------------------------------------------------

// Frischer, leerer Satz-Block (Struktur wie initErfassung in spiel-laufend.js).
function emptyBlock(config) {
  return {
    wuerfe: [],
    kegel: [],
    koenig: [],
    overrides: (config.teilsaetze || []).map(() => null),
    done: false,
  };
}

// Remote-Zeilen -> lokales Spiel-Objekt (in der App-Struktur).
//
// Namen: ist das Spiel serverseitig anonymisiert (spiel.anonymisiert_am, gesetzt beim Uebergang
// auf `beendet`), behaelt eine bereits vorhandene LOKALE Kopie ihre Klarnamen. Wer waehrend des
// Spiels verbunden war, soll sie weiter sehen; nur wer erst danach beitritt/pullt, bekommt die
// anonymisierte Fassung (Anzeigename bzw. neutraler Platzhalter). Bei nicht anonymisierten
// Spielen gewinnt weiterhin der Server, damit Umbenennungen im Kontrollzentrum ankommen.
function assembleLocalGame(sp, spieler, blocks) {
  let config = sp.config_json || {};
  if (sp.anonymisiert_am) {
    const lokal = getGame('r-' + sp.id);
    const lokaleListe = lokal && lokal.config && lokal.config.spielerListe;
    if (lokaleListe) {
      config = { ...config, spielerListe: mergeSpielerNamen(config.spielerListe, lokaleListe) };
    }
  }
  const nSaetze = config.saetze || 0;
  const posOf = {};
  spieler.forEach((s) => { posOf[s.id] = s.position; });

  const bloecke = (config.spielerListe || []).map(() =>
    Array.from({ length: nSaetze }, () => emptyBlock(config)));
  blocks.forEach((b) => {
    const pos = posOf[b.spieler_id];
    if (pos != null && bloecke[pos] && bloecke[pos][b.satz] !== undefined) {
      bloecke[pos][b.satz] = b.block_json || emptyBlock(config);
    }
  });

  return {
    id: 'r-' + sp.id,          // stabile lokale id aus der remote-id abgeleitet
    remoteId: sp.id,
    // Wem gehoert das Spiel? Entscheidet, ob es sich ueberhaupt loeschen/verbergen laesst
    // (logic/loeschen.js) — ueber die eigene LizenzID gefundene FREMDE Spiele nicht.
    besitzer: sp.besitzer || null,
    // Gehoert das Spiel zu einem Wettkampf? Bewusst die REMOTE-id (nicht `wettkampfId`, das
    // auf einen LOKALEN Wettkampf zeigen wuerde, den es hier evtl. gar nicht gibt): so kann
    // die Statistik die Durchgaenge eines Wettkampfs zu EINEM Eintrag buendeln und ihn bei
    // Bedarf per pullWettkampf nachladen. pullWettkampf setzt `wettkampfId` zusaetzlich.
    wettkampfRemoteId: sp.wettkampf_id || null,
    durchgangNr: sp.durchgang_nr ?? null,
    linked: true,
    beitrittsCode: sp.beitritts_code,
    zuschauerCode: sp.zuschauer_code,
    createdAt: sp.erstellt_am,
    spiel: sp.spielart,
    status: sp.status,
    anonymisiertAm: sp.anonymisiert_am || null,
    // Rein lokale "Das bin ich"-Markierung eines Einzelspiels: sie reist nicht ueber die DB
    // (serverseitig steckt sie in spiel_spieler.profil_id) und wuerde beim Pull sonst
    // verloren gehen. Aus der vorhandenen lokalen Kopie uebernehmen.
    ichIndex: (getGame('r-' + sp.id) || {}).ichIndex ?? null,
    config,
    erfassung: { aktiverSpieler: 0, aktiverSatz: 0, bloecke },
    // Besitz-Landkarte fuer die UI-Sperren (position -> {id, besitzer, heartbeat}).
    spielerOwners: ownersMap(spieler),
    updatedAt: sp.aktualisiert_am,
  };
}

// position -> { id, besitzer, heartbeat, profil }
//   besitzer/heartbeat = ERFASSUNGS-Lock (welches Geraet schreibt gerade die Wuerfe)
//   profil             = "das bin ich"-Markierung (welcher ACCOUNT ist dieser Spieler)
// Bewusst getrennt: der Lock wandert zwischen Geraeten, die Person bleibt dieselbe.
function ownersMap(spieler) {
  const m = {};
  spieler.forEach((s) => {
    m[s.position] = {
      id: s.id, besitzer: s.besitzer_geraet, heartbeat: s.heartbeat_am, profil: s.profil_id || null,
    };
  });
  return m;
}

// Eigene LizenzID (profil.passnummer) — best effort, null bei fehlendem Profil/ohne ID.
// Gecacht je Konto, weil sie beim Verknuepfen eines Wettkampfs sonst pro Durchgang neu
// abgefragt wuerde. Die LizenzID ist per DB-Trigger ohnehin nur EINMAL setzbar.
let passCache = null; // { konto, pass }
export async function meinePassnummer() {
  const konto = await kontoId();
  if (!konto) return null;
  if (passCache && passCache.konto === konto) return passCache.pass;
  try {
    const { data } = await supabase.from('profil').select('passnummer').eq('id', konto).maybeSingle();
    passCache = { konto, pass: (data && data.passnummer) || null };
    return passCache.pass;
  } catch (e) {
    return null; // offline -> keine Auto-Zuordnung, die manuelle Markierung greift weiter
  }
}

// Nach dem erstmaligen Setzen der LizenzID im Profil den Cache verwerfen.
export function resetPassCache() { passCache = null; }

// Wer ist wer in DIESEM Spiel? -> { passByPos, ichIndex } fuer linkGame/pushResults.
//   passByPos: Positionen mit LizenzID
//   ichIndex:  die Position, die der angemeldete Account selbst spielt (oder null)
// `wettkampf` ist optional (Einzelspiele haben keinen) und liefert die Sportwinner-Zuordnung
// sowie die manuelle Wettkampf-Markierung (ichSlot).
//
// Zwei Quellen fuer die LizenzIDen, in dieser Reihenfolge:
//   1) der LOKALE Sportwinner-Roster — nur das importierende Geraet (Vereins-PC) hat ihn,
//   2) die Aufstellung in der DB (spiel_spieler.passnummer), sobald das Spiel geteilt ist.
// Quelle 2 ist entscheidend fuer BEIGETRETENE Geraete: seit die Paesse nicht mehr ueber
// wettkampf.config_json mitreisen (Datenschutz), waere dort sonst keine LizenzID bekannt —
// weder fuers Wiederfinden fremder Ergebnisse noch fuer die eigene Zuordnung.
export async function spielerIdentitaet(game, wettkampf = null) {
  const config = (game && game.config) || {};
  const passByPos = passByPosition(config, wettkampf && wettkampf.sportwinner);
  const konto = await kontoId();

  let dbProfilPos = null; // Position, die in der DB bereits meinem Konto zugeordnet ist
  if (game && game.remoteId) {
    try {
      const { data } = await supabase.from('spiel_spieler')
        .select('position, passnummer, profil_id').eq('spiel_id', game.remoteId);
      (data || []).forEach((r) => {
        if (r.passnummer && !passByPos[r.position]) passByPos[r.position] = r.passnummer;
        if (konto && r.profil_id === konto) dbProfilPos = r.position;
      });
    } catch (e) { /* alte DB ohne die Spalte / offline -> lokaler Roster genuegt */ }
  }

  // Sportwinner-Wettkampf: die amtliche Aufstellung nennt die LizenzID jedes Spielers, damit
  // steht die Zuordnung fest. Manuelle Markierungen werden dort BEWUSST ignoriert — sie duerften
  // die amtliche Zuordnung nicht ueberstimmen (siehe istLizenzWettkampf).
  const ichIndex = resolveIchIndex(config, {
    nurLizenz: istLizenzWettkampf(wettkampf),
    ichSlot: (wettkampf && wettkampf.ichSlot) || null,
    ichIndex: Number.isInteger(game && game.ichIndex) ? game.ichIndex
      : (dbProfilPos != null ? dbProfilPos : null),
    passByPos,
    meinePass: await meinePassnummer(),
  });
  return { passByPos, ichIndex };
}

// Ist ein Spieler von einem FREMDEN, aktiven Geraet gehalten? (fuer UI/Politeness)
export function istFremdAktiv(owner, meineUid) {
  if (!owner || !owner.besitzer) return false;
  if (owner.besitzer === meineUid) return false;
  if (!owner.heartbeat) return false;
  return Date.now() - new Date(owner.heartbeat).getTime() < STALE_MS;
}

// --- Vertraeglich schreiben: neue Spalten, alte DB ---------------------------
// Warum das noetig ist, steht in js/logic/db-spalten.js. Kurz: die SQL-Skripte werden von
// Hand eingespielt, deshalb kann die DB eine neue Spalte noch nicht kennen — und dann darf
// nicht der ganze Vorgang (Teilen!) scheitern, sondern nur das Zusatzfeld ausfallen.
function schreibeVertraeglich(table, rows, optionale, run) {
  return dbSchreibeVertraeglich(table, rows, optionale, run, {
    onFallback: (t, opt, error) => console.warn(
      `[sync] ${t}: Spalte(n) ${opt.join(', ')} fehlen in dieser Datenbank — SQL-Migration `
      + '(supabase/schema.sql) noch nicht eingespielt. Schreibe ohne sie.',
      error.message || error),
  });
}

// --- Verknuepfen / Beitreten ------------------------------------------------

// Lokales Spiel in Supabase spiegeln. Gibt {remoteId, beitrittsCode, posToId} zurueck.
// Das erstellende Geraet uebernimmt zunaechst alle Spieler (es hat sie lokal bereits
// bespielt); Freigeben/Uebernehmen fuer weitere Geraete laeuft ueber die UI.
//
// opts.wettkampfRemoteId: wenn gesetzt, wird das Spiel als DURCHGANG eines Wettkampfs
// verknuepft (spiel.wettkampf_id + durchgang_nr). Bei Einzelspielen bleiben diese Spalten
// ungenannt — so bleibt das Einzelspiel-Sharing auch auf einer DB ohne die Wettkampf-
// Migration lauffaehig (PostgREST wuerde sonst eine unbekannte Spalte melden).
//
// opts.passByPos: { position -> LizenzID } aus der Sportwinner-Aufstellung. Landet an
//   spiel_spieler.passnummer (hinter der RLS, NICHT im config_json) und ist die Grundlage
//   fuer die Anonymisierung bei Spielende und fuers Wiederfinden eigener Ergebnisse.
// opts.ichIndex: die Position, die der angemeldete Account SELBST spielt (oder null).
//   Nur diese Zeile bekommt profil_id — mit erfasste Mitspieler/Gegner bleiben NULL und
//   tauchen dadurch nicht in der Account-Statistik des Erfassers auf.
export async function linkGame(game, opts = {}) {
  const { wettkampfRemoteId = null, passByPos = null, ichIndex = null } = opts;
  const geraet = await ensureGeraet();
  // Besitzer des Spiels ist der ACCOUNT (auth.uid()), NICHT das Geraet: die RLS
  // (spiel_insert/update/delete/select) prueft `besitzer = auth.uid()`. Die Geraete-ID
  // wird darunter fuer Mitgliedschaft (spiel_geraet) und Besitz-Lock (besitzer_geraet)
  // genutzt. ensureGeraet() hat die Session bereits sichergestellt, kontoId() ist gesetzt.
  const konto = await kontoId();
  if (!konto) throw new Error('nicht angemeldet');
  const now = new Date().toISOString();
  const config = game.config || {};

  // Ein bereits FERTIGES Spiel wird bewusst NICHT als 'beendet' eingefuegt: die
  // Anonymisierung der Namen haengt an einem UPDATE auf 'beendet' (Trigger
  // trg_spiel_anonymisieren) und wuerde einen INSERT nie sehen — die Klarnamen blieben
  // dauerhaft in der DB stehen. Deshalb 'laufend' einfuegen und den Status ganz unten,
  // wenn Aufstellung und Ergebnis-Snapshots stehen, per UPDATE nachziehen.
  const fertig = (game.status || '') === 'beendet';

  const insertRow = {
    besitzer: konto,
    spielart: game.spiel || 'sportkegler-wk',
    status: fertig ? 'laufend' : (game.status || 'setup'),
    config_json: config,
    anlage_id: config.anlageId || null,
  };
  if (wettkampfRemoteId) {
    insertRow.wettkampf_id = wettkampfRemoteId;
    insertRow.durchgang_nr = game.durchgangNr ?? null;
  }

  const { data: sp, error: e1 } = await supabase
    .from('spiel')
    .insert(insertRow)
    .select('id, beitritts_code, zuschauer_code, erstellt_am, aktualisiert_am, spielart, status, config_json')
    .single();
  if (e1) throw e1;
  const remoteId = sp.id;

  const { error: e2 } = await supabase.from('spiel_geraet').insert({ spiel_id: remoteId, geraet });
  if (e2) throw e2;

  // Aufstellung anlegen — laut RLS startet sie UNBESETZT (besitzer_geraet null).
  // passnummer/profil_id werden nur gesetzt, wenn vorhanden. Kennt die DB die (neue) Spalte
  // passnummer noch gar nicht, schreibt schreibeVertraeglich die Aufstellung ohne sie —
  // sonst wuerde ein fehlendes SQL-Update das Teilen komplett verhindern.
  const rows = (config.spielerListe || []).map((p, i) => {
    const row = { spiel_id: remoteId, position: i, name: p.name, start_bahn: p.startBahn };
    if (passByPos && passByPos[i]) row.passnummer = passByPos[i];
    if (ichIndex != null && i === ichIndex) row.profil_id = konto;
    return row;
  });
  const { data: spieler, error: e3 } = await schreibeVertraeglich(
    'spiel_spieler', rows, ['passnummer'],
    (rs) => supabase.from('spiel_spieler').insert(rs).select('id, position'),
  );
  if (e3) throw e3;
  const posToId = {};
  spieler.forEach((s) => { posToId[s.position] = s.id; });

  // Das erstellende Geraet uebernimmt zunaechst alle Spieler (es hat sie lokal
  // bereits bespielt). Freigeben/Uebernehmen fuer weitere Geraete laeuft ueber die UI.
  const { error: e3b } = await supabase
    .from('spiel_spieler')
    .update({ besitzer_geraet: geraet, besitzer_seit: now, heartbeat_am: now })
    .eq('spiel_id', remoteId);
  if (e3b) throw e3b;

  const e = game.erfassung;
  if (e && Array.isArray(e.bloecke)) {
    const blocks = [];
    e.bloecke.forEach((satzArr, pos) => satzArr.forEach((blk, satz) => {
      if (posToId[pos] == null) return;
      blocks.push({ spiel_id: remoteId, spieler_id: posToId[pos], satz, geraet, block_json: blk });
    }));
    if (blocks.length) {
      const { error: e4 } = await supabase.from('satz_block')
        .upsert(blocks, { onConflict: 'spieler_id,satz' });
      if (e4) throw e4;
    }
  }

  // War das Spiel beim Teilen SCHON fertig, gaebe es sonst nie Ergebnis-Snapshots: geschrieben
  // werden die ausschliesslich beim Spielende in der Erfassung (spiel-laufend.js/finishRemote),
  // und da laeuft ein importierter oder nachtraeglich geteilter Durchgang nicht mehr durch.
  // Ohne diese Zeilen liegen Wuerfe und Aufstellung in der DB, aber die Konto-Statistik findet
  // nichts — sie fragt genau spiel_ergebnis ab. Deshalb hier nachtragen, wo jeder Weg ins
  // Teilen vorbeikommt (Einzelspiel, Wettkampf, Sportwinner-Import, nachgereichter Durchgang).
  // Reihenfolge wie bei finishRemote (spiel-laufend.js): erst die Snapshots (sie tragen die
  // LizenzID je Spieler), DANN der Statuswechsel — der Trigger braucht die LizenzID, um das
  // passende Profil und dessen oeffentlichen Anzeigenamen zu finden.
  if (fertig) {
    await ergebnisSnapshot(game, { remoteId, posToId, konto, passByPos, ichIndex });
    await pushStatus(remoteId, 'beendet');
  }

  return { remoteId, beitrittsCode: sp.beitritts_code, zuschauerCode: sp.zuschauer_code, posToId, geraet };
}

// Ergebnis-Snapshots eines fertigen Spiels schreiben — dieselben Zeilen wie beim Spielende
// (logic/ergebnis-snapshot.js). Best effort: die Aufzeichnung selbst (Wuerfe, Aufstellung) ist
// schon geschrieben und darf an einem fehlgeschlagenen Snapshot nicht scheitern — aber lautlos
// verschwinden darf er auch nicht.
async function ergebnisSnapshot(game, { remoteId, posToId, konto, passByPos, ichIndex }) {
  try {
    const config = game.config || {};
    const bloecke = (game.erfassung && game.erfassung.bloecke) || [];
    const { players } = computeGameStats(config, bloecke, teilsatzRanges(config));
    await pushResults(ergebnisZeilen(players, {
      spielId: remoteId, spielerIdFuer: (pos) => posToId[pos], konto, passByPos, ichIndex,
    }));
  } catch (e) {
    console.error('[sync] Ergebnis-Snapshot beim Teilen fehlgeschlagen', e);
  }
}

// Vollstaendiges Remote-Spiel laden und als lokales Spiel-Objekt zusammenbauen.
export async function pullGame(remoteId) {
  const [{ data: sp, error: e1 }, { data: spieler, error: e2 }, { data: blocks, error: e3 }] =
    await Promise.all([
      supabase.from('spiel').select('*').eq('id', remoteId).single(),
      supabase.from('spiel_spieler').select('*').eq('spiel_id', remoteId).order('position'),
      supabase.from('satz_block').select('*').eq('spiel_id', remoteId),
    ]);
  if (e1) throw e1;
  if (e2) throw e2;
  if (e3) throw e3;
  return assembleLocalGame(sp, spieler || [], blocks || []);
}

// Beendete EINZELSPIELE, die dieser Account ERFASST hat, geraeteuebergreifend laden.
// Grundlage ist die RLS: der Ersteller (spiel.besitzer = auth.uid()) darf seine eigenen
// Spiele auf JEDEM Geraet vollstaendig lesen (pins_ist_spiel_besitzer). So erscheinen
// beendete Spiele in den Statistiken auch auf einem Geraet, das dem Spiel nie beigetreten
// ist, und lassen sich von dort wieder aufrufen. Wettkampf-Durchgaenge (wettkampf_id gesetzt)
// bleiben aussen vor — sie gehoeren in den Wettkampf-Hub, nicht in die Einzelspiel-Historie.
//
// ACHTUNG (Bedeutung): das ist die „von diesem Geraet/Account ERFASST"-Liste, nicht die
// eigene Spieler-Historie. Wer selbst gespielt hat, steht in pullMeineSpiele() — auf einem
// Vereins-PC sind das voellig verschiedene Mengen.
// Gibt vollstaendige lokale Spiel-Objekte zurueck (id 'r-'+remoteId), zuletzt gespielt zuerst.
export async function pullAccountFinishedGames() {
  const konto = await kontoId();
  if (!konto) return [];
  const { data: rows, error } = await supabase
    .from('spiel')
    .select('id, aktualisiert_am')
    .eq('besitzer', konto)
    .eq('status', 'beendet')
    .is('wettkampf_id', null)
    .order('aktualisiert_am', { ascending: false });
  if (error) throw error;
  const versteckt = (await verborgeneIds()).spiele;   // was ich bei mir entfernt habe
  const games = [];
  for (const row of (rows || []).filter((r) => !versteckt.has(r.id))) {
    try { games.push(await pullGame(row.id)); } catch { /* ein defektes Spiel ueberspringt die Liste nicht */ }
  }
  return games;
}

// Beendete WETTKAEMPFE dieses Accounts (geraeteuebergreifend) — das Gegenstueck zu
// pullAccountFinishedGames eine Ebene hoeher. Die RLS gibt sie ueber `besitzer = auth.uid()`
// frei (wettkampf_select). Jeder Wettkampf wird vollstaendig geladen (Durchgaenge + Bloecke),
// damit die Statistik-Karte die Rangliste zeigen und der Hub ihn direkt oeffnen kann —
// deshalb ist die Zahl bewusst gedeckelt.
// Rueckgabe: [{ wettkampf, games }], zuletzt bearbeitete zuerst.
export async function pullAccountFinishedWettkaempfe({ limit = 8 } = {}) {
  const konto = await kontoId();
  if (!konto) return [];
  const { data: rows, error } = await supabase
    .from('wettkampf')
    .select('id, aktualisiert_am')
    .eq('besitzer', konto)
    .eq('status', 'beendet')
    .order('aktualisiert_am', { ascending: false })
    .limit(limit);
  if (error) throw error;
  const versteckt = (await verborgeneIds()).wettkaempfe;
  const out = [];
  for (const row of (rows || []).filter((r) => !versteckt.has(r.id))) {
    try { out.push(await pullWettkampf(row.id)); } catch { /* ein defekter WK kippt die Liste nicht */ }
  }
  return out;
}

// Nur die Koepfe (Name/Datum/Status) zu einer Menge von Wettkampf-IDs — eine Abfrage, ohne
// die Durchgaenge zu laden. Fuer die Statistik-Karten, die die Durchgaenge ohnehin schon
// haben und bloss den Namen des Wettkampfs brauchen. Ohne Leserecht (man kennt nur sein
// eigenes Ergebnis, ist dem Wettkampf aber nie beigetreten) kommt die Zeile schlicht nicht
// zurueck — die Karte faellt dann auf „Wettkampf" zurueck.
export async function pullWettkampfKoepfe(ids) {
  const list = [...new Set((ids || []).filter(Boolean))];
  if (!list.length) return {};
  const { data, error } = await supabase
    .from('wettkampf').select('id, name, datum, status, anlage_id, besitzer, aktualisiert_am').in('id', list);
  if (error) throw error;
  const byId = {};
  (data || []).forEach((w) => { byId[w.id] = w; });
  return byId;
}

// --- Eigene Spieler-Historie (accountbasierte Statistik) --------------------
//
// DIE Quelle fuer „meine Statistik": die Ergebnis-Snapshots, in denen ICH der Spieler bin.
// Zwei Wege, per RLS beide erlaubt (spiel_ergebnis_select):
//   1) profil_id = auth.uid()          -> selbst markiert oder beim Erfassen zugeordnet
//   2) passnummer = meine LizenzID     -> auch in FREMD erfassten Spielen (z.B. Vereins-PC)
// Dedupliziert ueber die Zeilen-id (dieselbe Zeile kann ueber beide Wege kommen).
// Wettkampf-Durchgaenge sind ausdruecklich MIT dabei — sie tragen als einzige die LizenzID.
export const ERGEBNIS_COLS =
  'id,spiel_id,spieler_id,gesamt,schnitt_satz,schnitt_wurf,bester_satz,neuner,fehl,'
  + 'wurf_count,rang,erstellt_am,profil_id,passnummer,erfasst_von';

export async function pullMeineErgebnisse() {
  const konto = await kontoId();
  if (!konto) return [];
  const meinPass = await meinePassnummer();
  const [own, byPass] = await Promise.all([
    supabase.from('spiel_ergebnis').select(ERGEBNIS_COLS).eq('profil_id', konto),
    meinPass
      ? supabase.from('spiel_ergebnis').select(ERGEBNIS_COLS).eq('passnummer', meinPass)
      : Promise.resolve({ data: [] }),
  ]);
  const byId = new Map();
  (own.data || []).forEach((r) => byId.set(r.id, r));
  (byPass.data || []).forEach((r) => { if (!byId.has(r.id)) byId.set(r.id, r); });
  // Ein bei mir entferntes Spiel darf auch meine Statistik nicht mehr faerben — sonst waere es
  // zwar aus der Historie verschwunden, wuerde aber weiter Schnitt und Bestwert bestimmen.
  // Es ist MEINE Notiz: die Statistik der Mitspieler bleibt unveraendert.
  const versteckt = (await verborgeneIds()).spiele;
  return ohneVerborgene([...byId.values()], versteckt)
    .sort((a, b) => (b.erstellt_am || '').localeCompare(a.erstellt_am || ''));
}

// Die Spiele zu einer Ergebnisliste laden (fuer die Spielkarten in den Statistiken).
// Fehlgeschlagene einzelne Spiele werden uebersprungen — ein defektes Spiel darf die
// gesamte Historie nicht kippen. `limit` deckelt die Zahl der Einzelabfragen.
export async function pullSpieleZuErgebnissen(ergebnisse, { limit = 40 } = {}) {
  const ids = [...new Set((ergebnisse || []).map((r) => r.spiel_id).filter(Boolean))].slice(0, limit);
  const games = [];
  for (const id of ids) {
    try { games.push(await pullGame(id)); } catch (e) { /* kein Zugriff / geloescht */ }
  }
  return games;
}

// ALLE Ergebniszeilen zu einer Menge von Spielen (nicht nur die eigenen) — Grundlage fuer
// die nachtraegliche Zuordnung „welcher Spieler war ich?". Die RLS gibt sie frei, wenn man
// Mitglied/Ersteller des Spiels ist (spiel_ergebnis_select).
export async function pullErgebnisseFuerSpiele(spielIds) {
  const ids = [...new Set((spielIds || []).filter(Boolean))];
  if (!ids.length) return [];
  const { data, error } = await supabase
    .from('spiel_ergebnis').select(ERGEBNIS_COLS).in('spiel_id', ids);
  if (error) throw error;
  return data || [];
}

// --- "Das bin ich" an der Aufstellung ---------------------------------------
//
// Markiert eine Spieler-Position als den eigenen Account (spiel_spieler.profil_id). Laeuft
// ueber eine security-definer-RPC, weil die normale spiel_spieler-Policy an den ERFASSUNGS-
// Lock gebunden ist: solange ein anderes Geraet (z.B. der Vereins-PC) den Spieler aktiv
// bespielt, duerfte ein Mitspieler die Zeile sonst gar nicht anfassen. Geschrieben wird
// ausschliesslich das eigene Konto. Rueckgabe false = Position gehoert schon jemand anderem.
export async function spielerBinIch(spielerId) {
  const { data, error } = await supabase.rpc('spieler_bin_ich', { p_spieler: spielerId });
  if (error) throw error;
  return !!data;
}

export async function spielerBinIchLoesen(spielerId) {
  const { error } = await supabase.rpc('spieler_bin_ich_loesen', { p_spieler: spielerId });
  if (error) throw error;
}

// Alle noch freien Ergebniszeilen einsammeln, deren Aufstellungs-Zeile ich selbst markiert
// habe. Noetig, weil die Ergebniszeilen der ERFASSER schreibt und laut RLS keine fremde
// profil_id eintragen darf — der Spieler holt sich die Zuordnung selbst ab. Rueckgabe: Anzahl.
export async function meineErgebnisseBeanspruchen() {
  const { data, error } = await supabase.rpc('meine_ergebnisse_beanspruchen');
  if (error) throw error;
  return data || 0;
}

// Ein Ergebnis nachtraeglich dem eigenen Account zuordnen („das war ich") bzw. die
// Zuordnung wieder loesen. Beide laufen ueber security-definer-RPCs, weil die normale
// spiel_ergebnis-Policy den Geraete-Besitz des Spielers verlangt — den hat ein anderes
// Geraet womoeglich laengst abgegeben. Rueckgabe von zuordnen: true = Zeile wurde gesetzt.
export async function ergebnisMirZuordnen(ergebnisId) {
  const { data, error } = await supabase.rpc('ergebnis_mir_zuordnen', { p_ergebnis: ergebnisId });
  if (error) throw error;
  return !!data;
}

export async function ergebnisZuordnungLoesen(ergebnisId) {
  const { error } = await supabase.rpc('ergebnis_zuordnung_loesen', { p_ergebnis: ergebnisId });
  if (error) throw error;
}

// Einem Spiel per Beitritts-Code beitreten (RPC), dann vollstaendig laden.
// p_geraet = eigene Geraete-ID (RLS prueft, dass sie zu meinem Account gehoert).
export async function joinGame(code) {
  const geraet = await ensureGeraet();
  const { data: remoteId, error } = await supabase.rpc('spiel_beitreten', {
    p_code: (code || '').trim(), p_geraet: geraet,
  });
  if (error) throw error;
  return pullGame(remoteId);
}

// Einem Spiel als ZUSCHAUER per Zuschauer-Code beitreten: nur lesend, KEIN Geräte-Beitritt.
// Holt einen anonymen Snapshot (RPC spiel_zuschauer) und baut daraus ein lokales, NUR-LESEN
// markiertes Spiel-Objekt (zuschauer:true, linked:false). Aktualisiert wird per Polling in der
// Ansicht (nicht Realtime, da ohne Mitgliedschaft kein RLS-Lesezugriff besteht). Wirft
// 'Ungültiger Beitritts-Code' bei unbekanntem Code (gleiche Semantik wie joinGame).
export async function zuschauerGame(code) {
  const c = (code || '').trim();
  const { data, error } = await supabase.rpc('spiel_zuschauer', { p_code: c });
  if (error) throw error;
  if (!data || !data.spiel) throw new Error('Ungültiger Beitritts-Code');
  const g = assembleLocalGame(data.spiel, data.spieler || [], data.bloecke || []);
  g.linked = false;
  g.zuschauer = true;
  g.zuschauerCode = c.toUpperCase();
  g.spielerOwners = {}; // im Zuschauer-Modus irrelevant (keine Locks anzeigen)
  return g;
}

// --- Wettkampf: Klammer über mehrere Durchgang-Spiele -----------------------
//
// Ein Wettkampf ist eine dünne Klammer: die `wettkampf`-Zeile hält Stammdaten +
// die gesamte lokale Struktur (Mannschaften, Programm, spielerJeMannschaft) in
// config_json; die Durchgänge sind normale `spiel`-Zeilen mit wettkampf_id. Ein
// zweites Gerät tritt EINMAL dem Wettkampf bei (wettkampf_beitreten) und sieht/
// beschreibt darüber automatisch alle Durchgänge (auch später ergänzte).

// Die lokale Wettkampf-Struktur in die Form bringen, die in wettkampf.config_json darf.
// Entfernt werden:
//   * Remote-/Laufzeit-Felder (remoteId, beitrittsCode, linked, updatedAt, durchgaenge, id) —
//     die Durchgänge werden relational über spiel.wettkampf_id rekonstruiert,
//   * `ichSlot` — die rein lokale „Das bin ich"-Markierung; sie gehört niemandem sonst und
//     reist serverseitig ohnehin als spiel_spieler.profil_id mit,
//   * die Personendaten im `sportwinner`-Block (pass/extId, siehe sportwinnerOhnePersonendaten):
//     config_json wird über die Zuschauer-/Overlay-RPCs an `anon` ausgeliefert.
function wettkampfConfigFuerDb(wettkampf) {
  const {
    remoteId, beitrittsCode, zuschauerCode, linked, updatedAt, durchgaenge, id, ichSlot,
    ...rest
  } = wettkampf;
  const config = { ...rest };
  if (config.sportwinner) config.sportwinner = sportwinnerOhnePersonendaten(config.sportwinner);
  return config;
}

// Lokalen Wettkampf + seine Durchgänge in Supabase spiegeln.
// games = die lokalen Durchgang-Spiele (aus getWettkampfGames). Gibt
// {remoteId, beitrittsCode} zurück; die Durchgänge werden per linkGame gespiegelt.
export async function linkWettkampf(wettkampf, games) {
  const geraet = await ensureGeraet();
  const konto = await kontoId();
  if (!konto) throw new Error('nicht angemeldet');

  // config_json = die lokale Wettkampf-Struktur OHNE Remote-/Laufzeit-Felder und ohne
  // die (geräte-lokalen) Durchgang-IDs — die Durchgänge werden relational rekonstruiert.
  const config = wettkampfConfigFuerDb(wettkampf);

  const { data: w, error: e1 } = await supabase
    .from('wettkampf')
    .insert({
      besitzer: konto,
      name: wettkampf.name || null,
      datum: wettkampf.datum || null,
      anlage_id: wettkampf.anlageId || null,
      status: wettkampf.status || 'setup',
      config_json: config,
    })
    .select('id, beitritts_code, zuschauer_code')
    .single();
  if (e1) throw e1;
  const remoteWkId = w.id;

  const { error: e2 } = await supabase
    .from('wettkampf_geraet').insert({ wettkampf_id: remoteWkId, geraet });
  if (e2) throw e2;

  // Jeden Durchgang als normales Spiel spiegeln (mit wettkampf_id + durchgang_nr).
  // Die LizenzIDen der Aufstellung und die eigene Spieler-Position reisen dabei je Durchgang
  // an spiel_spieler mit — NICHT ueber config_json (siehe wettkampfConfigFuerDb).
  const links = [];
  for (const g of games) {
    const ident = await spielerIdentitaet(g, wettkampf);
    const res = await linkGame(g, { wettkampfRemoteId: remoteWkId, ...ident });
    links.push({ gameId: g.id, remoteId: res.remoteId, beitrittsCode: res.beitrittsCode });
  }

  return { remoteId: remoteWkId, beitrittsCode: w.beitritts_code, zuschauerCode: w.zuschauer_code, links };
}

// Vollständigen Remote-Wettkampf laden und als { wettkampf, games } (App-Struktur)
// zusammenbauen. Die Durchgänge werden über spiel.wettkampf_id gefunden und einzeln
// als lokale Spiele geladen (pullGame). Lokale IDs werden stabil aus den Remote-IDs
// abgeleitet (wettkampf: 'rw-'+id, Spiele: 'r-'+id), sodass mehrfaches Pullen idempotent
// dieselben lokalen Objekte trifft.
export async function pullWettkampf(remoteId) {
  const [{ data: w, error: e1 }, { data: spiele, error: e2 }] = await Promise.all([
    supabase.from('wettkampf').select('*').eq('id', remoteId).single(),
    supabase.from('spiel').select('id, durchgang_nr, status').eq('wettkampf_id', remoteId),
  ]);
  if (e1) throw e1;
  if (e2) throw e2;

  const localWkId = 'rw-' + w.id;
  const rows = (spiele || []).slice().sort((a, b) => (a.durchgang_nr || 0) - (b.durchgang_nr || 0));
  const games = [];
  const durchgaenge = [];
  for (const row of rows) {
    const g = await pullGame(row.id);   // assembliertes lokales Spiel (id 'r-'+row.id)
    g.wettkampfId = localWkId;
    g.durchgangNr = row.durchgang_nr;
    games.push(g);
    durchgaenge.push({ nr: row.durchgang_nr, gameId: g.id, status: row.status || g.status });
  }

  const base = w.config_json || {};
  const wettkampf = {
    ...base,
    id: localWkId,
    remoteId: w.id,
    besitzer: w.besitzer || null,
    linked: true,
    beitrittsCode: w.beitritts_code,
    zuschauerCode: w.zuschauer_code,
    typ: 'sportkegler-wettkampf',
    status: w.status,
    name: w.name != null ? w.name : base.name,
    datum: w.datum || base.datum,
    anlageId: w.anlage_id || base.anlageId,
    durchgaenge,
    // Rein lokale "Das bin ich"-Markierung (<mannschaftId>|<teamPos>): sie wird bewusst NICHT
    // in config_json gespiegelt (siehe wettkampfConfigFuerDb) und muss deshalb aus der
    // vorhandenen lokalen Kopie uebernommen werden — sonst waere sie nach jedem reload weg.
    ichSlot: (getWettkampf(localWkId) || {}).ichSlot || null,
    createdAt: base.createdAt || w.erstellt_am,
    updatedAt: w.aktualisiert_am,
  };
  return { wettkampf, games };
}

// Einem Wettkampf per Beitritts-Code beitreten (RPC), dann vollständig laden.
export async function joinWettkampf(code) {
  const geraet = await ensureGeraet();
  const { data: remoteId, error } = await supabase.rpc('wettkampf_beitreten', {
    p_code: (code || '').trim(), p_geraet: geraet,
  });
  if (error) throw error;
  return pullWettkampf(remoteId);
}

// Einem Wettkampf als ZUSCHAUER per Zuschauer-Code folgen: nur lesend, KEIN Geräte-Beitritt.
// Anonymer Snapshot (RPC wettkampf_zuschauer) inkl. aller Durchgänge; baut { wettkampf, games }
// in derselben App-Struktur wie pullWettkampf, aber NUR-LESEN markiert (zuschauer:true). Jeder
// Durchgang trägt seinen eigenen Zuschauer-Code, damit er in der Erfassungs-Ansicht live pollen
// kann. Wirft 'Ungültiger Beitritts-Code' bei unbekanntem Code.
export async function zuschauerWettkampf(code) {
  const c = (code || '').trim();
  const { data, error } = await supabase.rpc('wettkampf_zuschauer', { p_code: c });
  if (error) throw error;
  if (!data || !data.wettkampf) throw new Error('Ungültiger Beitritts-Code');
  const w = data.wettkampf;
  const localWkId = 'rw-' + w.id;
  const spiele = (data.spiele || []).slice()
    .sort((a, b) => (a.durchgang_nr || 0) - (b.durchgang_nr || 0));
  const games = [];
  const durchgaenge = [];
  for (const s of spiele) {
    const g = assembleLocalGame(s, s.spieler || [], s.bloecke || []);
    g.linked = false;
    g.zuschauer = true;
    g.zuschauerCode = s.zuschauer_code || '';
    g.spielerOwners = {};
    g.wettkampfId = localWkId;
    g.durchgangNr = s.durchgang_nr;
    games.push(g);
    durchgaenge.push({ nr: s.durchgang_nr, gameId: g.id, status: s.status || g.status });
  }
  const base = w.config_json || {};
  const wettkampf = {
    ...base,
    id: localWkId,
    remoteId: w.id,
    linked: false,
    zuschauer: true,
    typ: 'sportkegler-wettkampf',
    status: w.status,
    name: w.name != null ? w.name : base.name,
    datum: w.datum || base.datum,
    anlageId: w.anlage_id || base.anlageId,
    durchgaenge,
    createdAt: base.createdAt || w.erstellt_am,
    updatedAt: w.aktualisiert_am,
  };
  return { wettkampf, games };
}

// Wettkampf-Status setzen (nur der Ersteller darf das laut RLS).
export async function pushWettkampfStatus(remoteId, status) {
  const { error } = await supabase.from('wettkampf').update({ status }).eq('id', remoteId);
  if (error) throw error;
}

// Wettkampf-Config (Stammdaten-Struktur: Mannschaften inkl. Logos, Programm …) aktualisieren.
// Laut RLS darf das NUR der Ersteller (wettkampf.besitzer); auf anderen Geräten schlägt es
// still fehl (lokale Anzeige bleibt), analog zu pushConfig für Durchgänge.
//
// `config` ist die LOKALE Wettkampf-Struktur; sie wird hier durch dieselbe Bereinigung
// geschickt wie beim Verknüpfen (wettkampfConfigFuerDb), damit LizenzIDen/extIds auch bei
// jedem späteren Push draußen bleiben.
export async function pushWettkampfConfig(remoteId, config) {
  const { error } = await supabase.from('wettkampf')
    .update({ config_json: wettkampfConfigFuerDb(config || {}) }).eq('id', remoteId);
  if (error) throw error;
}

// Read-only Schnappschuss eines geteilten Wettkampfs per Beitritts-Code (RPC) — für das
// OBS-Overlay. Braucht KEIN angemeldetes Gerät (die RPC ist an anon ge-grantet). Baut das
// Ergebnis in die App-Struktur { wettkampf, games } um, wie sie computeWettkampfStats erwartet.
// Gibt null zurück, wenn der Code unbekannt ist.
export async function fetchOverlay(code) {
  const { data, error } = await supabase.rpc('wettkampf_overlay', { p_code: (code || '').trim() });
  if (error) throw error;
  if (!data) return null;

  const base = (data.wettkampf && data.wettkampf.config) || {};
  const wettkampf = {
    ...base,
    name: (data.wettkampf && data.wettkampf.name) != null ? data.wettkampf.name : base.name,
    status: data.wettkampf && data.wettkampf.status,
    durchgaenge: [],
  };
  const games = [];
  (data.spiele || []).forEach((s, i) => {
    const config = s.config || {};
    const nSaetze = config.saetze || 0;
    const nSp = (config.spielerListe || []).length;
    const bloecke = Array.from({ length: nSp }, () =>
      Array.from({ length: nSaetze }, () => emptyBlock(config)));
    (s.bloecke || []).forEach((b) => {
      if (bloecke[b.position] && b.satz != null && bloecke[b.position][b.satz] !== undefined) {
        bloecke[b.position][b.satz] = b.block || emptyBlock(config);
      }
    });
    const id = 'ov-' + (s.durchgang_nr ?? i);
    games.push({ id, spiel: 'sportkegler-wk', status: s.status, config, erfassung: { bloecke } });
    wettkampf.durchgaenge.push({ nr: s.durchgang_nr ?? i + 1, gameId: id });
  });
  return { wettkampf, games };
}

// Auf Änderungen eines Wettkampfs lauschen: die wettkampf-Zeile selbst (Status/Config),
// neue/entfernte Durchgänge (spiel mit wettkampf_id) und die Würfe der bekannten
// Durchgänge (satz_block je spiel_id). onChange(art) wird bei jeder Änderung gerufen
// ('wettkampf' | 'durchgang' | 'block'); der Aufrufer entprellt und lädt neu.
// durchgangIds = aktuell bekannte Durchgang-Remote-IDs (für die satz_block-Filter).
export function subscribeWettkampf(remoteId, durchgangIds = [], { onChange } = {}) {
  const ch = supabase.channel('wk:' + remoteId + ':' + Math.random().toString(36).slice(2, 7));
  ch.on('postgres_changes',
    { event: '*', schema: 'public', table: 'wettkampf', filter: `id=eq.${remoteId}` },
    () => onChange && onChange('wettkampf'));
  ch.on('postgres_changes',
    { event: '*', schema: 'public', table: 'spiel', filter: `wettkampf_id=eq.${remoteId}` },
    () => onChange && onChange('durchgang'));
  (durchgangIds || []).forEach((id) => {
    ch.on('postgres_changes',
      { event: '*', schema: 'public', table: 'satz_block', filter: `spiel_id=eq.${id}` },
      () => onChange && onChange('block'));
  });
  ch.subscribe();
  return () => { supabase.removeChannel(ch); };
}

// --- Besitz-Lock ------------------------------------------------------------

// Spieler uebernehmen. Rueckgabe false = von der DB verweigert (fremd + aktiv).
export async function claimPlayer(spielerId) {
  const geraet = await ensureGeraet();
  const now = new Date().toISOString();
  const { data, error } = await supabase
    .from('spiel_spieler')
    .update({ besitzer_geraet: geraet, besitzer_seit: now, heartbeat_am: now })
    .eq('id', spielerId)
    .select('id');
  if (error) throw error;
  return Array.isArray(data) && data.length > 0;
}

// Eigenen Spieler wieder freigeben.
export async function releasePlayer(spielerId) {
  const geraet = await ensureGeraet();
  const { error } = await supabase
    .from('spiel_spieler')
    .update({ besitzer_geraet: null, besitzer_seit: null })
    .eq('id', spielerId)
    .eq('besitzer_geraet', geraet);
  if (error) throw error;
}

// Heartbeat fuer alle vom eigenen Geraet gehaltenen Spieler eines Spiels.
export async function heartbeat(remoteId) {
  const geraet = await ensureGeraet();
  const { error } = await supabase
    .from('spiel_spieler')
    .update({ heartbeat_am: new Date().toISOString() })
    .eq('spiel_id', remoteId)
    .eq('besitzer_geraet', geraet);
  if (error) throw error;
}

// --- Wuerfe schreiben -------------------------------------------------------

// Einen Satz-Block hochschreiben (upsert auf (spieler_id, satz)).
export async function pushBlock(remoteId, spielerId, satz, block) {
  const geraet = await ensureGeraet();
  const { error } = await supabase
    .from('satz_block')
    .upsert(
      { spiel_id: remoteId, spieler_id: spielerId, satz, geraet, block_json: block },
      { onConflict: 'spieler_id,satz' },
    );
  if (error) throw error;
}

// Status des Spiels setzen (nur der Ersteller darf das laut RLS).
export async function pushStatus(remoteId, status) {
  const { error } = await supabase.from('spiel').update({ status }).eq('id', remoteId);
  if (error) throw error;
}

// Setup/Config eines Spiels aktualisieren (z.B. Spielernamen + Startbahnen der Aufstellung
// im Wettkampf-Hub). Laut RLS darf das NUR der Ersteller (spiel.besitzer) — bei anderen
// Geraeten schlaegt es fehl; der Aufrufer faengt das ab (lokale Anzeige, kein harter Fehler).
export async function pushConfig(remoteId, config) {
  const { error } = await supabase.from('spiel').update({ config_json: config }).eq('id', remoteId);
  if (error) throw error;
}

// Ergebnis-Snapshots bei Spielende schreiben (für die Statistik-Historie).
// rows = [{ spiel_id, spieler_id, profil_id, gesamt, schnitt_satz, ... }].
export async function pushResults(rows) {
  if (!rows || !rows.length) return;
  const { error } = await schreibeVertraeglich(
    'spiel_ergebnis', rows, ['erfasst_von'],
    (rs) => supabase.from('spiel_ergebnis').upsert(rs, { onConflict: 'spiel_id,spieler_id' }),
  );
  if (error) throw error;
}

// --- Entfernen, ohne zu löschen ---------------------------------------------
//
// „Geloescht" heisst fuer alles, was schon in der Datenbank liegt: VERBORGEN — und zwar NUR
// FUER MICH. Geschrieben wird eine Zeile in `verborgen` (Konto + Objekt), sonst nichts: das
// Spiel, sein Beitritts- und Zuschauer-Code, das OBS-Overlay und alle anderen Geraete bleiben
// unberuehrt. Wer etwas bei sich entfernt, fliegt selbst raus — niemand sonst merkt davon
// etwas. Ausgeblendet wird es dann in pullAccountFinishedGames/-Wettkaempfe (die eigenen
// Listen) und in pullMeineErgebnisse (die eigene Statistik).
//
// Rein LOKALE Spiele kennt die Datenbank gar nicht; die verschwinden ganz (store.deleteGame).

async function merkeVerborgen(zeilen) {
  if (!zeilen.length) return;
  // upsert statt insert: zweimal Verbergen ist kein Fehler, sondern dasselbe Ergebnis.
  const { error } = await supabase.from('verborgen')
    .upsert(zeilen, { onConflict: 'konto,art,objekt_id' });
  if (error) throw error;
}

export async function verbergeSpiel(remoteId) {
  const konto = await kontoId();
  if (!konto) throw new Error('Nicht angemeldet');
  await merkeVerborgen([{ konto, art: 'spiel', objekt_id: remoteId }]);
  await loeseZuordnung([remoteId]);
}

// Die eigene „das war ich"-Zuordnung an diesen Spielen zuruecknehmen. Best effort und bewusst
// NACH dem Verbergen: das Verbergen ist die Zusage an den Nutzer, das Loesen der Zuordnung nur
// das Aufraeumen dahinter — scheitert es, ist das Spiel trotzdem weg (die Anzeige filtert
// ohnehin ueber `verborgen`). Andersherum haette man eine geloeste Zuordnung an einem Spiel,
// das weiter sichtbar ist.
async function loeseZuordnung(spielIds) {
  const ids = (spielIds || []).filter(Boolean);
  if (!ids.length) return;
  try {
    await supabase.rpc('zuordnung_loesen_fuer_spiele', { p_spiele: ids });
  } catch (e) { /* Anzeige stimmt auch ohne */ }
}

// Ein Wettkampf verschwindet nur dann wirklich, wenn auch seine Durchgaenge mitgehen: sonst
// blieben die eigenen Ergebnisse aus ihnen in der Statistik stehen (pullMeineErgebnisse findet
// sie ueber die LizenzID). Die Durchgang-IDs kommen aus der DB, weil lokal nicht jeder
// Durchgang liegen muss (fremde Mannschaft erfasst ihre selbst).
export async function verbergeWettkampf(remoteId) {
  const konto = await kontoId();
  if (!konto) throw new Error('Nicht angemeldet');
  const { data, error } = await supabase.from('spiel').select('id').eq('wettkampf_id', remoteId);
  if (error) throw error;
  const durchgaenge = (data || []).map((r) => r.id);
  await merkeVerborgen([
    { konto, art: 'wettkampf', objekt_id: remoteId },
    ...durchgaenge.map((id) => ({ konto, art: 'spiel', objekt_id: id })),
  ]);
  await loeseZuordnung(durchgaenge);
}

// Was habe ICH bei mir entfernt? -> { spiele: Set, wettkaempfe: Set }. Die RLS gibt nur die
// eigenen Zeilen frei, deshalb braucht die Abfrage keinen Filter. Best effort: faellt sie aus
// (offline, Migration noch nicht eingespielt), bleiben die Listen vollstaendig stehen, statt
// ganz zu verschwinden.
export async function verborgeneIds() {
  const leer = { spiele: new Set(), wettkaempfe: new Set() };
  try {
    const { data, error } = await supabase.from('verborgen').select('art, objekt_id');
    if (error) throw error;
    const out = { spiele: new Set(), wettkaempfe: new Set() };
    (data || []).forEach((r) => {
      (r.art === 'wettkampf' ? out.wettkaempfe : out.spiele).add(r.objekt_id);
    });
    return out;
  } catch (e) {
    return leer;
  }
}

// --- Realtime ---------------------------------------------------------------

// Auf Aenderungen an satz_block + spiel_spieler eines Spiels lauschen.
// onBlock(row) und onSpieler(row) bekommen die geaenderte Zeile. Rueckgabe: unsubscribe().
export function subscribe(remoteId, { onBlock, onSpieler } = {}) {
  const ch = supabase
    .channel('spiel:' + remoteId)
    .on('postgres_changes',
      { event: '*', schema: 'public', table: 'satz_block', filter: `spiel_id=eq.${remoteId}` },
      (p) => onBlock && onBlock(p.new && p.new.id ? p.new : p.old))
    .on('postgres_changes',
      { event: '*', schema: 'public', table: 'spiel_spieler', filter: `spiel_id=eq.${remoteId}` },
      (p) => onSpieler && onSpieler(p.new && p.new.id ? p.new : p.old))
    .subscribe();
  return () => { supabase.removeChannel(ch); };
}
