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
import { ensureGeraet, geraetId } from './geraet.js';

export { ensureGeraet, geraetId };

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
export async function linkGame(game) {
  const geraet = await ensureGeraet();
  const now = new Date().toISOString();
  const config = game.config || {};

  const { data: sp, error: e1 } = await supabase
    .from('spiel')
    .insert({
      besitzer: geraet,
      spielart: game.spiel || 'sportkegler-wk',
      status: game.status || 'setup',
      config_json: config,
    })
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

// Einem Spiel per Beitritts-Code beitreten (RPC), dann vollstaendig laden.
export async function joinGame(code) {
  await ensureGeraet();
  const { data: remoteId, error } = await supabase.rpc('spiel_beitreten', { p_code: (code || '').trim() });
  if (error) throw error;
  return pullGame(remoteId);
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
