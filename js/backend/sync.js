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
//   config.spielerListe[i] -> spiel_spieler { position:i, name, start_bahn }
//   erfassung.bloecke[i][s]-> satz_block { spieler_id(pos i), satz:s, block_json }
//
// aktiverSpieler/aktiverSatz sind reine Geraete-UI-Zustaende und werden NICHT
// synchronisiert.

import { supabase } from './supabase.js';
import { ensureGeraet, geraetId, kontoId } from './geraet.js';

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
function assembleLocalGame(sp, spieler, blocks) {
  const config = sp.config_json || {};
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
    linked: true,
    beitrittsCode: sp.beitritts_code,
    createdAt: sp.erstellt_am,
    spiel: sp.spielart,
    status: sp.status,
    config,
    erfassung: { aktiverSpieler: 0, aktiverSatz: 0, bloecke },
    // Besitz-Landkarte fuer die UI-Sperren (position -> {id, besitzer, heartbeat}).
    spielerOwners: ownersMap(spieler),
    updatedAt: sp.aktualisiert_am,
  };
}

function ownersMap(spieler) {
  const m = {};
  spieler.forEach((s) => {
    m[s.position] = { id: s.id, besitzer: s.besitzer_geraet, heartbeat: s.heartbeat_am };
  });
  return m;
}

// Ist ein Spieler von einem FREMDEN, aktiven Geraet gehalten? (fuer UI/Politeness)
export function istFremdAktiv(owner, meineUid) {
  if (!owner || !owner.besitzer) return false;
  if (owner.besitzer === meineUid) return false;
  if (!owner.heartbeat) return false;
  return Date.now() - new Date(owner.heartbeat).getTime() < STALE_MS;
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
export async function linkGame(game, opts = {}) {
  const { wettkampfRemoteId = null } = opts;
  const geraet = await ensureGeraet();
  // Besitzer des Spiels ist der ACCOUNT (auth.uid()), NICHT das Geraet: die RLS
  // (spiel_insert/update/delete/select) prueft `besitzer = auth.uid()`. Die Geraete-ID
  // wird darunter fuer Mitgliedschaft (spiel_geraet) und Besitz-Lock (besitzer_geraet)
  // genutzt. ensureGeraet() hat die Session bereits sichergestellt, kontoId() ist gesetzt.
  const konto = await kontoId();
  if (!konto) throw new Error('nicht angemeldet');
  const now = new Date().toISOString();
  const config = game.config || {};

  const insertRow = {
    besitzer: konto,
    spielart: game.spiel || 'sportkegler-wk',
    status: game.status || 'setup',
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
    .select('id, beitritts_code, erstellt_am, aktualisiert_am, spielart, status, config_json')
    .single();
  if (e1) throw e1;
  const remoteId = sp.id;

  const { error: e2 } = await supabase.from('spiel_geraet').insert({ spiel_id: remoteId, geraet });
  if (e2) throw e2;

  // Aufstellung anlegen — laut RLS startet sie UNBESETZT (besitzer_geraet null).
  const rows = (config.spielerListe || []).map((p, i) => ({
    spiel_id: remoteId, position: i, name: p.name, start_bahn: p.startBahn,
  }));
  const { data: spieler, error: e3 } = await supabase
    .from('spiel_spieler').insert(rows).select('id, position');
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

  return { remoteId, beitrittsCode: sp.beitritts_code, posToId, geraet };
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

// Beendete EINZELSPIELE des angemeldeten Accounts geraeteuebergreifend laden.
// Grundlage ist die RLS: der Ersteller (spiel.besitzer = auth.uid()) darf seine eigenen
// Spiele auf JEDEM Geraet vollstaendig lesen (pins_ist_spiel_besitzer). So erscheinen
// beendete Spiele in den Statistiken auch auf einem Geraet, das dem Spiel nie beigetreten
// ist, und lassen sich von dort wieder aufrufen. Wettkampf-Durchgaenge (wettkampf_id gesetzt)
// bleiben aussen vor — sie gehoeren in den Wettkampf-Hub, nicht in die Einzelspiel-Historie.
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
  const games = [];
  for (const row of rows || []) {
    try { games.push(await pullGame(row.id)); } catch { /* ein defektes Spiel ueberspringt die Liste nicht */ }
  }
  return games;
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

// --- Wettkampf: Klammer über mehrere Durchgang-Spiele -----------------------
//
// Ein Wettkampf ist eine dünne Klammer: die `wettkampf`-Zeile hält Stammdaten +
// die gesamte lokale Struktur (Mannschaften, Programm, spielerJeMannschaft) in
// config_json; die Durchgänge sind normale `spiel`-Zeilen mit wettkampf_id. Ein
// zweites Gerät tritt EINMAL dem Wettkampf bei (wettkampf_beitreten) und sieht/
// beschreibt darüber automatisch alle Durchgänge (auch später ergänzte).

// Lokalen Wettkampf + seine Durchgänge in Supabase spiegeln.
// games = die lokalen Durchgang-Spiele (aus getWettkampfGames). Gibt
// {remoteId, beitrittsCode} zurück; die Durchgänge werden per linkGame gespiegelt.
export async function linkWettkampf(wettkampf, games) {
  const geraet = await ensureGeraet();
  const konto = await kontoId();
  if (!konto) throw new Error('nicht angemeldet');

  // config_json = die lokale Wettkampf-Struktur OHNE Remote-/Laufzeit-Felder und ohne
  // die (geräte-lokalen) Durchgang-IDs — die Durchgänge werden relational rekonstruiert.
  const { remoteId, beitrittsCode, linked, updatedAt, durchgaenge, id, ...rest } = wettkampf;
  const config = { ...rest };

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
    .select('id, beitritts_code')
    .single();
  if (e1) throw e1;
  const remoteWkId = w.id;

  const { error: e2 } = await supabase
    .from('wettkampf_geraet').insert({ wettkampf_id: remoteWkId, geraet });
  if (e2) throw e2;

  // Jeden Durchgang als normales Spiel spiegeln (mit wettkampf_id + durchgang_nr).
  const links = [];
  for (const g of games) {
    const res = await linkGame(g, { wettkampfRemoteId: remoteWkId });
    links.push({ gameId: g.id, remoteId: res.remoteId, beitrittsCode: res.beitrittsCode });
  }

  return { remoteId: remoteWkId, beitrittsCode: w.beitritts_code, links };
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
    linked: true,
    beitrittsCode: w.beitritts_code,
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

// Einem Wettkampf per Beitritts-Code beitreten (RPC), dann vollständig laden.
export async function joinWettkampf(code) {
  const geraet = await ensureGeraet();
  const { data: remoteId, error } = await supabase.rpc('wettkampf_beitreten', {
    p_code: (code || '').trim(), p_geraet: geraet,
  });
  if (error) throw error;
  return pullWettkampf(remoteId);
}

// Wettkampf-Status setzen (nur der Ersteller darf das laut RLS).
export async function pushWettkampfStatus(remoteId, status) {
  const { error } = await supabase.from('wettkampf').update({ status }).eq('id', remoteId);
  if (error) throw error;
}

// Wettkampf-Config (Stammdaten-Struktur: Mannschaften inkl. Logos, Programm …) aktualisieren.
// Laut RLS darf das NUR der Ersteller (wettkampf.besitzer); auf anderen Geräten schlägt es
// still fehl (lokale Anzeige bleibt), analog zu pushConfig für Durchgänge.
export async function pushWettkampfConfig(remoteId, config) {
  const { error } = await supabase.from('wettkampf').update({ config_json: config }).eq('id', remoteId);
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
  const { error } = await supabase
    .from('spiel_ergebnis')
    .upsert(rows, { onConflict: 'spiel_id,spieler_id' });
  if (error) throw error;
}

// --- Verbindung kappen (ohne zu löschen) ------------------------------------

// Die Verbindung eines Spiels lösen: Beitritts-Code entwerten + alle Geräte-Mitgliedschaften
// entfernen. Danach ist das Spiel weder beitretbar noch (über den Code) sichtbar, und schon
// verbundene Geräte verlieren den Zugriff — das Spiel selbst und alle Wurf-/Ergebnisdaten
// bleiben aber in der DB erhalten. Nur der Ersteller darf (die security-definer RPC prüft das).
export async function cutGameLink(remoteId) {
  const { error } = await supabase.rpc('spiel_verbindung_kappen', { p_spiel: remoteId });
  if (error) throw error;
}

// Wie cutGameLink, aber für einen Wettkampf inkl. all seiner Durchgänge (schaltet auch das
// OBS-Overlay ab, das am Wettkampf-Code hängt).
export async function cutWettkampfLink(remoteId) {
  const { error } = await supabase.rpc('wettkampf_verbindung_kappen', { p_wettkampf: remoteId });
  if (error) throw error;
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
