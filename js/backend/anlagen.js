// Anlagen (Kegel-Standorte) + Bahnen.
//
// Jeder eingeloggte Account darf eine Anlage anlegen (reale Daten sind im Formular
// Pflicht); alle dürfen Anlagen lesen und darauf spielen. Ändern/Löschen nur der
// Besitzer (RLS in policies.sql). `anlage.besitzer` = auth.uid() (die PERSON), NICHT
// die Geräte-ID — vgl. geraet.js. Erweiterte Funktionen (Kontrollzentrum, Sportwinner,
// Livestream/OBS) folgen späteren Etappen und nur für freigeschaltete Accounts.
//
// Wird nur lazy geladen (dynamic import), damit die local-first App ohne Verbindung
// unbeeinträchtigt bleibt.

import { supabase } from './supabase.js';
import { kontoId } from './geraet.js';

// Felder, die per Anlage gespeichert werden dürfen (Whitelist). Leere Strings -> NULL,
// außer name (Pflicht) und anzahl_bahnen (Zahl).
const ANLAGE_FELDER = ['name', 'strasse', 'plz', 'ort'];

function normFelder(f) {
  const row = {};
  for (const k of ANLAGE_FELDER) {
    if (k in f) row[k] = (f[k] ?? '').trim() || null;
  }
  if ('anzahl_bahnen' in f) {
    const n = parseInt(f.anzahl_bahnen, 10);
    row.anzahl_bahnen = Number.isFinite(n) && n > 0 ? n : 4;
  }
  return row;
}

// Alle Anlagen (für Auswahl + Verwaltung). `mein` markiert die eigenen (bearbeitbar).
export async function listAnlagen() {
  const uid = await kontoId();
  const { data, error } = await supabase
    .from('anlage')
    .select('id,name,ort,strasse,plz,anzahl_bahnen,besitzer,erstellt_am')
    .order('name', { ascending: true });
  if (error) throw error;
  return (data || []).map((a) => ({ ...a, mein: !!uid && a.besitzer === uid }));
}

// Weiche Duplikat-Prüfung vor dem Anlegen: gleiche Anlage (Name + PLZ) bereits vorhanden?
export async function findeDuplikate({ name, plz }) {
  const n = (name || '').trim();
  if (!n) return [];
  let q = supabase.from('anlage').select('id,name,ort,plz').ilike('name', n);
  const p = (plz || '').trim();
  if (p) q = q.eq('plz', p);
  const { data, error } = await q;
  if (error) return []; // Duplikat-Warnung ist optional — Fehler nicht blockierend
  return data || [];
}

// Neue Anlage anlegen. Besitzer = aktueller Account. Legt zugleich die Bahnen an
// (jede mit ihrer Bahnart — gemischte Bahnarten sind erlaubt). bahnen = [{nummer, bahnart}].
// Nicht transaktional (wie sync.js): scheitert ein Schritt nach dem Anlage-Insert, wird die
// (leere) Anlage wieder entfernt, damit keine Waise zurückbleibt.
export async function createAnlage(felder, bahnen) {
  const uid = await kontoId();
  if (!uid) throw new Error('nicht angemeldet');
  const clean = normBahnen(bahnen);
  const row = { ...normFelder(felder), besitzer: uid, anzahl_bahnen: clean.length || 4 };
  if (!row.name) throw new Error('Name ist Pflicht');

  const { data, error } = await supabase
    .from('anlage')
    .insert(row)
    .select('id,name,ort,strasse,plz,anzahl_bahnen,besitzer,erstellt_am')
    .single();
  if (error) throw error;

  if (clean.length) {
    const rows = clean.map((b) => ({ anlage_id: data.id, nummer: b.nummer, bahnart: b.bahnart }));
    const { error: e2 } = await supabase.from('bahn').insert(rows);
    if (e2) {
      try { await supabase.from('anlage').delete().eq('id', data.id); } catch (e) { /* best effort */ }
      throw e2;
    }
  }
  return { ...data, mein: true };
}

// Bahnen normalisieren: positive, eindeutige Nummern; Bahnart leer -> NULL.
function normBahnen(bahnen) {
  const out = [];
  const seen = new Set();
  for (const b of (bahnen || [])) {
    const nummer = parseInt(b.nummer, 10);
    if (!Number.isFinite(nummer) || nummer < 1 || seen.has(nummer)) continue;
    seen.add(nummer);
    out.push({ nummer, bahnart: (b.bahnart ?? '').trim() || null });
  }
  return out.sort((a, b) => a.nummer - b.nummer);
}

// Anlage-Stammdaten ändern (nur eigene — RLS erzwingt es).
export async function updateAnlage(id, felder) {
  const row = normFelder(felder);
  const { error } = await supabase.from('anlage').update(row).eq('id', id);
  if (error) throw error;
}

// Hinweis: Anlagen werden bewusst NICHT über die App gelöscht (kein deleteAnlage).
// Reale Anlagen bleiben erhalten; Korrekturen laufen über „Bearbeiten"/„Bahnen".
// (Der interne Orphan-Rollback in createAnlage ist kein Nutzer-Löschen.)

// Bahnen einer Anlage (aufsteigend nach Nummer).
export async function listBahnen(anlageId) {
  const { data, error } = await supabase
    .from('bahn')
    .select('id,nummer,bahnart')
    .eq('anlage_id', anlageId)
    .order('nummer', { ascending: true });
  if (error) throw error;
  return data || [];
}

// Bahnen speichern: übergebene (nummer/bahnart) upserten, nicht mehr enthaltene löschen.
// bahnen = [{ nummer, bahnart }]. Nur der Anlagen-Besitzer darf schreiben (RLS).
export async function saveBahnen(anlageId, bahnen) {
  const clean = (bahnen || [])
    .map((b) => ({
      anlage_id: anlageId,
      nummer: parseInt(b.nummer, 10),
      bahnart: (b.bahnart ?? '').trim() || null,
    }))
    .filter((b) => Number.isFinite(b.nummer) && b.nummer > 0);

  const nummern = clean.map((b) => b.nummer);
  // Entfernte Bahnen löschen.
  let del = supabase.from('bahn').delete().eq('anlage_id', anlageId);
  if (nummern.length) del = del.not('nummer', 'in', `(${nummern.join(',')})`);
  const { error: e1 } = await del;
  if (e1) throw e1;

  if (clean.length) {
    const { error: e2 } = await supabase.from('bahn').upsert(clean, { onConflict: 'anlage_id,nummer' });
    if (e2) throw e2;
  }
}

// Ist der aktuelle Account für die erweiterten Funktionen freigeschaltet?
export async function istFreigeschaltet() {
  const { data, error } = await supabase.rpc('pins_ist_freigeschaltet');
  if (error) return false;
  return !!data;
}
