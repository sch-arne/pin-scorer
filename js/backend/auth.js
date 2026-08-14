// Accounts (E-Mail + Passwort, mit E-Mail-Bestaetigung).
//
// REGISTRIEREN legt per signUp einen echten Account an (E-Mail + Passwort in einem
// Schritt) und sendet eine Bestaetigungs-Mail. Hinweis: Supabase erlaubt es NICHT,
// einem anonymen Nutzer E-Mail und Passwort zusammen zu geben ("Updating password of
// an anonymous user without an email is not allowed") — deshalb signUp statt Anon-
// Aufwertung. Der Account bekommt dadurch eine EIGENE uid; die Geraete-Identitaet ist
// davon entkoppelt (geraet.js), sodass Mitgliedschaften in geteilten Spielen erhalten
// bleiben und mehrere Geraete gleichzeitig denselben Account nutzen koennen.
//
// Wird nur lazy geladen (dynamic import), damit die local-first App ohne Verbindung
// unbeeintraechtigt bleibt.

import { supabase, isRecoveryPending, clearRecovery } from './supabase.js';

export { isRecoveryPending, clearRecovery };

// Zurueck auf die Spieler-Seite; dort verarbeitet der Client Bestaetigungs-/Reset-Links.
function redirectUrl() {
  return location.origin + location.pathname + '#/spieler';
}

export async function currentUser() {
  const { data: { user } } = await supabase.auth.getUser();
  return user || null;
}

// Echter Account (nicht mehr anonym, hat eine bestaetigte E-Mail)?
export function isPermanent(user) {
  return !!(user && !user.is_anonymous && user.email && user.email_confirmed_at);
}

// Registrierung angestossen, aber E-Mail noch nicht bestaetigt? Dann kennt Supabase die
// Adresse als ausstehend (new_email) oder als noch unbestaetigtes email.
export function pendingEmail(user) {
  if (!user) return null;
  if (user.new_email) return user.new_email;
  if (user.email && !user.email_confirmed_at) return user.email;
  return null;
}

// REGISTRIEREN: echten Account mit E-Mail + Passwort anlegen. Sendet eine Bestaetigungs-
// Mail; erst nach dem Klick auf den Link gilt der Account als vollwertig (isPermanent)
// und man kann sich damit anmelden. Die anonyme Session bleibt bis dahin aktiv, die App
// also weiter nutzbar. Gibt bei bereits vergebener E-Mail einen Fehler zurueck.
export async function register(email, password) {
  const { data, error } = await supabase.auth.signUp({
    email: (email || '').trim(),
    password,
    options: { emailRedirectTo: redirectUrl() },
  });
  if (error) throw error;
  // Supabase verschleiert bereits vergebene, bestaetigte E-Mails (kein Fehler, aber ein
  // Nutzer ohne neue Identitaet und ohne gesendete Mail). Das der View signalisieren.
  const identities = data && data.user && data.user.identities;
  if (Array.isArray(identities) && identities.length === 0) {
    const e = new Error('E-Mail ist bereits registriert');
    e.code = 'email_exists';
    throw e;
  }
}

// ANMELDEN in einen BESTEHENDEN Account (z.B. auf einem weiteren Geraet). Ersetzt die
// (anonyme) Session — auth.uid() wechselt dann auf die des Accounts. Erfordert eine
// bereits bestaetigte E-Mail.
export async function login(email, password) {
  const { error } = await supabase.auth.signInWithPassword({
    email: (email || '').trim(), password,
  });
  if (error) throw error;
}

// Passwort-Reset anfordern (Mail mit Link zurueck auf die Spieler-Seite).
export async function requestPasswordReset(email) {
  const { error } = await supabase.auth.resetPasswordForEmail((email || '').trim(), {
    redirectTo: redirectUrl(),
  });
  if (error) throw error;
}

// Neues Passwort im Reset-Zustand setzen (nach Klick auf den Reset-Link).
export async function setNewPassword(password) {
  const { error } = await supabase.auth.updateUser({ password });
  if (error) throw error;
  clearRecovery();
}

// Auf das PASSWORD_RECOVERY-Event lauschen (falls es erst nach dem Mount feuert).
// Rueckgabe: unsubscribe().
export function onPasswordRecovery(cb) {
  const { data } = supabase.auth.onAuthStateChange((event) => {
    if (event === 'PASSWORD_RECOVERY') cb();
  });
  return () => { try { data.subscription.unsubscribe(); } catch (e) { /* ignore */ } };
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
