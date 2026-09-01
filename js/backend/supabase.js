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

// Lokaler Config-Override fuer die Entwicklung: Auf einem ENTWICKLUNGS-Host wird versucht,
// eine git-ignorierte ./config.local.js zu laden (die Werte der separaten Test-Datenbank).
// In Produktion (GitHub Pages) existiert die Datei nicht — der Import scheitert still und
// die Produktionswerte unten greifen.
//
// Als Entwicklungs-Host zaehlt NICHT nur localhost, sondern auch eine private LAN-Adresse.
// Grund: der Zwei-Geraete-Test laeuft ueber die LAN-IP des Dev-Rechners (das Handy erreicht
// kein localhost). Mit der alten localhost-Pruefung sprach genau dieser Test unbemerkt gegen
// die PRODUKTIONS-Datenbank — inklusive aller Schreibvorgaenge und mit Fehlern, sobald der
// Code eine Spalte nutzt, die dort noch nicht migriert ist.
// WICHTIG: Das Top-Level-await funktioniert nur, weil dieses Modul ausschliesslich
// LAZY (per dynamischem import()) geladen wird — siehe Kopf-Kommentar.
function istEntwicklungsHost(host) {
  if (['localhost', '127.0.0.1', '::1', '[::1]'].includes(host)) return true;
  if (/\.local$/i.test(host)) return true;                       // mDNS (macbook.local)
  if (/^10\./.test(host)) return true;                           // 10.0.0.0/8
  if (/^192\.168\./.test(host)) return true;                     // 192.168.0.0/16
  return /^172\.(1[6-9]|2\d|3[01])\./.test(host);                // 172.16.0.0/12
}

let _override = {};
if (istEntwicklungsHost(location.hostname)) {
  try {
    _override = await import('./config.local.js');
  } catch {
    /* keine lokale Config vorhanden -> Produktionswerte */
  }
}

export const SUPABASE_URL = _override.SUPABASE_URL ?? 'https://bajiihfyvupvsdsxwdkj.supabase.co';
// Oeffentlicher anon-Key: durch Row-Level-Security abgesichert, darf im Frontend liegen.
export const SUPABASE_ANON_KEY =
  _override.SUPABASE_ANON_KEY ??
  'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJhamlpaGZ5dnVwdnNkc3h3ZGtqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY2OTQ4ODYsImV4cCI6MjEwMjI3MDg4Nn0.4xf05tBTBmkR-L7UFXUVmKT2-GbSi5DpQMM0EqKjo7U';

if (_override.SUPABASE_URL) {
  console.info('[supabase] Lokale Config aktiv (Test-DB):', _override.SUPABASE_URL);
} else if (istEntwicklungsHost(location.hostname)) {
  // Dev-Host ohne config.local.js: alles laeuft gegen die PRODUKTIONS-DB. Das ist beim
  // Testen fast nie gewollt und war bisher nicht zu erkennen.
  console.warn('[supabase] Entwicklungs-Host OHNE config.local.js — es wird die '
    + 'PRODUKTIONS-Datenbank benutzt:', SUPABASE_URL);
}

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
