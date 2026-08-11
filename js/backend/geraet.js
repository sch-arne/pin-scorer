// Geraete-Identitaet.
//
// Ein Geraet identifiziert sich als anonymer Supabase-Auth-Nutzer (Anonymous
// Sign-In). Die anon-uid ist die stabile `geraet`-Kennung fuer den Spielbetrieb.
// Beim spaeteren Account-Schritt wird derselbe Nutzer per Magic-Link zu einem
// echten Account aufgewertet — die uid bleibt gleich, deshalb ist auth.uid()
// zugleich Geraet (Spielbetrieb) und Person (Statistik-Historie).

import { supabase } from './supabase.js';

let cached = null;
let pending = null;

// Stellt sicher, dass eine (anonyme) Session existiert und liefert die geraet-uid.
// Idempotent: mehrfache Aufrufe teilen sich denselben In-Flight-Login.
export function ensureGeraet() {
  if (cached) return Promise.resolve(cached);
  if (!pending) {
    pending = (async () => {
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.user) return session.user.id;
      const { data, error } = await supabase.auth.signInAnonymously();
      if (error) throw error;
      return data.user.id;
    })()
      .then((id) => { cached = id; return id; })
      .catch((e) => { pending = null; throw e; }); // Fehlschlag -> naechster Versuch neu
  }
  return pending;
}

// Synchron: die bereits ermittelte uid (oder null, falls noch nicht angemeldet).
export function geraetId() {
  return cached;
}
