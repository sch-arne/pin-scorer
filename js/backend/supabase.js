// Supabase-Client.
//
// WICHTIG: Dieses Modul wird ausschliesslich LAZY geladen (dynamic import aus
// sync.js / der View), nie statisch aus app.js. So bleibt die local-first App
// offline voll lauffaehig, auch wenn das CDN (esm.sh) nicht erreichbar ist —
// der Sync braucht ohnehin eine Verbindung.
//
// Der Client kommt per Runtime-Import von esm.sh. Ein sauberes, selbst-
// enthaltenes Bundle gibt es ohne Build-Step nicht (esm.sh/jsDelivr splitten in
// Sub-Pakete); der Service-Worker cacht die esm.sh-Antworten nach dem ersten
// Online-Laden fuer Folgestarts.

import { createClient } from 'https://esm.sh/@supabase/supabase-js@2.112';

export const SUPABASE_URL = 'https://oizupdfesgihpzdzwvcw.supabase.co';
// Oeffentlicher anon-Key: durch Row-Level-Security abgesichert, darf im Frontend liegen.
export const SUPABASE_ANON_KEY =
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9penVwZGZlc2dpaHB6ZHp3dmN3Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY0MzA3MDgsImV4cCI6MjEwMjAwNjcwOH0.Hl0L0_Xp9WJfVTigiW2vPPo9ZjNQuBk2337CRysPY30';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    storageKey: 'pins-scorer:auth',
    detectSessionInUrl: true, // fuer Magic-Link-, Bestaetigungs- und Reset-Callbacks
  },
  realtime: { params: { eventsPerSecond: 10 } },
});

// Passwort-Reset: Klickt der Nutzer den Reset-Link, verarbeitet der Client die URL
// beim Laden und feuert EINMAL das PASSWORD_RECOVERY-Event — moeglicherweise BEVOR die
// Login-View ihren eigenen Listener setzt. Deshalb hier ein synchron (bei Client-
// Erstellung) registrierter Listener, der ein Flag setzt; die View liest es beim Mount.
let _recoveryPending = false;
supabase.auth.onAuthStateChange((event) => {
  if (event === 'PASSWORD_RECOVERY') _recoveryPending = true;
});
export function isRecoveryPending() { return _recoveryPending; }
export function clearRecovery() { _recoveryPending = false; }
