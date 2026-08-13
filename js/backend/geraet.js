// Geraete-Identitaet — ENTKOPPELT vom Account.
//
// Frueher galt "Geraet = auth.uid()". Damit koennen aber nicht MEHRERE Geraete
// GLEICHZEITIG im selben Account erfassen: gleiche uid => der Spieler-Besitz-Lock
// (besitzer_geraet) kollabiert, beide schreiben dieselbe satz_block-Zeile.
//
// Deshalb hat jedes Geraet jetzt eine eigene, in localStorage gespeicherte UUID,
// unabhaengig davon, WER (welcher Account) gerade eingeloggt ist:
//   * auth.uid()  = Person / Account  -> Statistik (profil_id), spiel.besitzer, profil
//   * Geraete-ID  = dieses Geraet     -> Mitgliedschaft (spiel_geraet), Spieler-Lock
//
// Die Geraete-ID wird serverseitig in der Tabelle `geraet` an den aktuellen Account
// gebunden (konto = auth.uid()). Die RLS vertraut NUR dieser Bindung — eine allein
// vom Client gelieferte Geraete-ID zaehlt nicht.

import { supabase } from './supabase.js';

const LS_KEY = 'pins-scorer:geraet';

function uuid() {
  if (globalThis.crypto && crypto.randomUUID) return crypto.randomUUID();
  // Fallback fuer aeltere Browser.
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

// Stabile Geraete-ID (persistiert in localStorage). Synchron, unabhaengig vom Login.
// Wird beim ersten Aufruf erzeugt und bleibt fuer dieses Geraet gleich.
export function geraetId() {
  let id = null;
  try { id = localStorage.getItem(LS_KEY); } catch (e) { /* privater Modus o.ae. */ }
  if (!id) {
    id = uuid();
    try { localStorage.setItem(LS_KEY, id); } catch (e) { /* ignore */ }
  }
  return id;
}

let pending = null;
let registeredFor = null; // konto-uid, fuer die die Geraete-ID zuletzt registriert wurde

// Stellt sicher, dass eine (anonyme) Auth-Session existiert, und liefert deren uid.
async function ensureSession() {
  const { data: { session } } = await supabase.auth.getSession();
  if (session && session.user) return session.user.id;
  const { data, error } = await supabase.auth.signInAnonymously();
  if (error) throw error;
  return data.user.id;
}

// Stellt sicher, dass (a) eine Auth-Session existiert und (b) dieses Geraet in der
// `geraet`-Tabelle an den AKTUELLEN Account gebunden ist. Liefert die Geraete-ID.
// Idempotent: mehrfache Aufrufe teilen sich denselben In-Flight-Vorgang.
export function ensureGeraet() {
  if (!pending) {
    pending = (async () => {
      const konto = await ensureSession();
      const id = geraetId();
      if (registeredFor !== konto) {
        // (id, konto) ist der Primaerschluessel: dasselbe Geraet kann ueber die Zeit
        // an mehrere Accounts gebunden sein (z.B. anonym -> Account, oder Kontowechsel).
        const { error } = await supabase
          .from('geraet')
          .upsert({ id, konto, gesehen_am: new Date().toISOString() }, { onConflict: 'id,konto' });
        if (error) throw error;
        registeredFor = konto;
      }
      return id;
    })().catch((e) => { pending = null; throw e; }); // Fehlschlag -> naechster Versuch neu
  }
  return pending;
}

// Aktueller Account (auth.uid()) — die PERSON hinter der Statistik. Kann sich vom
// Geraet unterscheiden. Null, wenn (noch) keine Session existiert.
export async function kontoId() {
  const { data: { session } } = await supabase.auth.getSession();
  return (session && session.user && session.user.id) || null;
}

// Kontowechsel (Login/Logout): das Geraet beim naechsten ensureGeraet() neu binden.
let lastKonto;
supabase.auth.onAuthStateChange((_event, session) => {
  const konto = (session && session.user && session.user.id) || null;
  if (konto !== lastKonto) {
    lastKonto = konto;
    registeredFor = null;
    pending = null;
  }
});
