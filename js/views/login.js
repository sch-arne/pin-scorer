// „Spieler": Account per Magic-Link (kein Passwort). Anonymes Gerät -> echter Account
// (uid bleibt). Nach dem Klick auf den E-Mail-Link landet der Nutzer wieder hier; der
// Supabase-Client verarbeitet den Callback beim Laden des Backends.
//
// Backend wird nur lazy geladen -> ohne Verbindung bleibt die App nutzbar (nur die
// Account-Funktionen brauchen Netz).

import { navigate } from '../router.js';
import { esc } from '../util.js';

export function spielerView() {
  const root = document.createElement('div');
  root.className = 'view view-page';
  root.innerHTML = `
    <header class="page-header">
      <a class="back-btn" href="#/menu" aria-label="Zurück">←</a>
      <h1 class="page-title">Spieler</h1>
    </header>
    <div class="join-body" id="spieler-body"><p class="join-msg">Lade …</p></div>`;

  const body = root.querySelector('#spieler-body');
  (async () => {
    let auth;
    try {
      auth = await import('../backend/auth.js');
    } catch (e) {
      body.innerHTML = '<p class="join-hint">Offline — Account-Funktionen brauchen eine Verbindung.</p>';
      return;
    }
    await renderState(auth, body);
  })();

  return root;
}

async function renderState(auth, body) {
  let user = null;
  try { user = await auth.currentUser(); } catch (e) { /* offline */ }

  if (!auth.isPermanent(user)) {
    body.innerHTML = `
      <p class="join-hint">Melde dich an, um deine Spiele und Statistiken geräteübergreifend zu speichern. Du bekommst einen Anmeldelink per E-Mail — kein Passwort nötig.</p>
      <input id="acc-email" class="join-input acc-text" type="email" inputmode="email" autocomplete="email" autocapitalize="off" spellcheck="false" placeholder="deine@email.de" aria-label="E-Mail" />
      <button type="button" id="acc-send" class="erf-btn done join-go">📧 Anmeldelink senden</button>
      <p id="acc-msg" class="join-msg" role="status"></p>`;
    const email = body.querySelector('#acc-email');
    const btn = body.querySelector('#acc-send');
    const msg = body.querySelector('#acc-msg');
    const send = async () => {
      const v = email.value.trim();
      if (!v || !v.includes('@')) { msg.textContent = 'Bitte eine gültige E-Mail eingeben.'; return; }
      btn.disabled = true; msg.textContent = 'Sende Link …';
      try {
        await auth.upgradeToAccount(v);
        msg.textContent = '✓ Link an ' + v + ' gesendet. Öffne die E-Mail auf DIESEM Gerät.';
      } catch (e) {
        const m = String((e && e.message) || e);
        if (/registered|already|exists|taken/i.test(m)) {
          try {
            await auth.loginExisting(v);
            msg.textContent = '✓ Anmeldelink gesendet (bestehender Account). E-Mail auf diesem Gerät öffnen.';
          } catch (e2) { msg.textContent = 'Fehlgeschlagen: ' + String((e2 && e2.message) || e2); btn.disabled = false; }
        } else { msg.textContent = 'Fehlgeschlagen: ' + m; btn.disabled = false; }
      }
    };
    btn.addEventListener('click', send);
    email.addEventListener('keydown', (e) => { if (e.key === 'Enter') send(); });
    return;
  }

  // Angemeldet: Anzeigename pflegen + abmelden.
  let profil = null;
  try { profil = await auth.getProfil(); } catch (e) { /* ignore */ }
  body.innerHTML = `
    <p class="join-hint">Angemeldet als <strong>${esc(user.email)}</strong>.</p>
    <label class="acc-label" for="acc-name">Anzeigename</label>
    <input id="acc-name" class="join-input acc-text" type="text" autocomplete="name" placeholder="Dein Name" value="${esc((profil && profil.anzeigename) || '')}" />
    <button type="button" id="acc-save" class="erf-btn done join-go">Speichern</button>
    <button type="button" id="acc-logout" class="erf-btn join-go acc-logout">Abmelden</button>
    <p id="acc-msg" class="join-msg" role="status"></p>`;
  const name = body.querySelector('#acc-name');
  const msg = body.querySelector('#acc-msg');
  body.querySelector('#acc-save').addEventListener('click', async () => {
    try { await auth.saveProfil(name.value); msg.textContent = '✓ Gespeichert.'; }
    catch (e) { msg.textContent = 'Speichern fehlgeschlagen.'; }
  });
  body.querySelector('#acc-logout').addEventListener('click', async () => {
    try { await auth.signOut(); } catch (e) { /* ignore */ }
    navigate('/menu');
  });
}
