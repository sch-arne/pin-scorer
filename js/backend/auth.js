// Accounts (Magic-Link, kein Passwort).
//
// Ein Gerät ist zunächst ein ANONYMER Supabase-Nutzer (siehe geraet.js). Meldet sich
// der Nutzer mit einer E-Mail an, wird dieser anonyme Nutzer zu einem echten Account
// AUFGEWERTET — die uid bleibt gleich. Dadurch bleibt die Geräte-Identität (laufende
// Spiele) erhalten UND die Statistik-Historie hängt fortan an der Person.
//
// Wird nur lazy geladen (dynamic import), damit die local-first App ohne Verbindung
// unbeeinträchtigt bleibt.

import { supabase } from './supabase.js';
import { ensureGeraet } from './geraet.js';

// Zurück auf die Spieler-Seite; dort verarbeitet der Client den Magic-Link-Callback.
function redirectUrl() {
  return location.origin + location.pathname + '#/spieler';
}

export async function currentUser() {
  const { data: { user } } = await supabase.auth.getUser();
  return user || null;
}

// Echter Account (nicht mehr anonym, hat eine bestätigte E-Mail)?
export function isPermanent(user) {
  return !!(user && !user.is_anonymous && user.email);
}

// Anonymen Nutzer per E-Mail zu einem Account aufwerten (uid bleibt gleich).
// Sendet einen Bestätigungs-Magic-Link an die Adresse.
export async function upgradeToAccount(email) {
  await ensureGeraet(); // sicherstellen, dass eine (anonyme) Session existiert
  const { error } = await supabase.auth.updateUser(
    { email: (email || '').trim() },
    { emailRedirectTo: redirectUrl() },
  );
  if (error) throw error;
}

// In einen BESTEHENDEN Account einloggen (z.B. auf einem weiteren Gerät). Ersetzt die
// Session — die uid wechselt dann auf die des Accounts.
export async function loginExisting(email) {
  const { error } = await supabase.auth.signInWithOtp({
    email: (email || '').trim(),
    options: { emailRedirectTo: redirectUrl(), shouldCreateUser: false },
  });
  if (error) throw error;
}

// Profil (Anzeigename) lesen / speichern.
export async function getProfil() {
  const uid = (await currentUser())?.id;
  if (!uid) return null;
  const { data } = await supabase.from('profil').select('*').eq('id', uid).maybeSingle();
  return data || null;
}
export async function saveProfil(anzeigename) {
  const uid = (await currentUser())?.id;
  if (!uid) throw new Error('nicht angemeldet');
  const { error } = await supabase
    .from('profil')
    .upsert({ id: uid, anzeigename: (anzeigename || '').trim() }, { onConflict: 'id' });
  if (error) throw error;
}

export async function signOut() {
  await supabase.auth.signOut();
}
