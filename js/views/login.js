// „Spieler": Account per E-Mail + Passwort (mit E-Mail-Bestaetigung). Anonymes Geraet
// -> echter Account beim Registrieren (uid bleibt). Nach dem Klick auf den Bestaetigungs-
// bzw. Reset-Link landet der Nutzer wieder hier; der Supabase-Client verarbeitet den
// Callback beim Laden des Backends.
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

    // Kam der Nutzer über einen Passwort-Reset-Link? (Flag wird in supabase.js gesetzt.)
    if (auth.isRecoveryPending && auth.isRecoveryPending()) {
      renderRecovery(auth, body);
      return;
    }
    // Falls das Event erst kurz nach dem Mount feuert: einmalig nachziehen.
    const off = auth.onPasswordRecovery(() => renderRecovery(auth, body));
    window.addEventListener('hashchange', function h() {
      off && off();
      window.removeEventListener('hashchange', h);
    }, { once: true });

    await renderState(auth, body);
  })();

  return root;
}

async function renderState(auth, body) {
  let user = null;
  try { user = await auth.currentUser(); } catch (e) { /* offline */ }

  if (auth.isPermanent(user)) { renderLoggedIn(auth, body, user); return; }

  const pending = auth.pendingEmail(user);
  if (pending) { renderPending(auth, body, pending); return; }

  renderAuthForm(auth, body, 'login');
}

// --- Anmelden / Registrieren -------------------------------------------------

function renderAuthForm(auth, body, mode) {
  const isReg = mode === 'register';
  body.innerHTML = `
    <div class="acc-tabs" role="tablist">
      <button type="button" class="acc-tab ${!isReg ? 'is-on' : ''}" data-mode="login" role="tab" aria-selected="${!isReg}">Anmelden</button>
      <button type="button" class="acc-tab ${isReg ? 'is-on' : ''}" data-mode="register" role="tab" aria-selected="${isReg}">Registrieren</button>
    </div>
    <p class="join-hint">${isReg
      ? 'Erstelle ein Konto, um deine Spiele und Statistiken geräteübergreifend zu speichern. Du bekommst eine Bestätigung per E-Mail.'
      : 'Melde dich an, um deine Spiele und Statistiken auf allen Geräten zu sehen.'}</p>
    <input id="acc-email" class="join-input acc-text" type="email" inputmode="email" autocomplete="email" autocapitalize="off" spellcheck="false" placeholder="deine@email.de" aria-label="E-Mail" />
    <div class="acc-field">
      <input id="acc-pw" class="join-input acc-text" type="password" autocomplete="${isReg ? 'new-password' : 'current-password'}" placeholder="Passwort" aria-label="Passwort" />
      <button type="button" class="acc-eye" id="acc-eye" aria-label="Passwort anzeigen">👁</button>
    </div>
    <button type="button" id="acc-go" class="erf-btn done join-go">${isReg ? 'Registrieren' : 'Anmelden'}</button>
    ${isReg ? '' : '<button type="button" id="acc-forgot" class="acc-link">Passwort vergessen?</button>'}
    <p id="acc-msg" class="join-msg" role="status"></p>`;

  const email = body.querySelector('#acc-email');
  const pw = body.querySelector('#acc-pw');
  const btn = body.querySelector('#acc-go');
  const msg = body.querySelector('#acc-msg');

  body.querySelectorAll('.acc-tab').forEach((t) => t.addEventListener('click', () => {
    if (t.dataset.mode !== mode) renderAuthForm(auth, body, t.dataset.mode);
  }));

  body.querySelector('#acc-eye').addEventListener('click', () => {
    pw.type = pw.type === 'password' ? 'text' : 'password';
  });

  const forgot = body.querySelector('#acc-forgot');
  if (forgot) forgot.addEventListener('click', async () => {
    const v = email.value.trim();
    if (!v || !v.includes('@')) { msg.textContent = 'Bitte zuerst deine E-Mail oben eingeben.'; return; }
    msg.textContent = 'Sende Link …';
    try {
      await auth.requestPasswordReset(v);
      msg.textContent = '✓ Falls ein Konto existiert, ist ein Link an ' + v + ' unterwegs.';
    } catch (e) { msg.textContent = 'Fehlgeschlagen: ' + errText(e); }
  });

  const submit = async () => {
    const e = email.value.trim();
    const p = pw.value;
    if (!e || !e.includes('@')) { msg.textContent = 'Bitte eine gültige E-Mail eingeben.'; return; }
    if (!p || (isReg && p.length < 8)) {
      msg.textContent = isReg ? 'Passwort: mindestens 8 Zeichen.' : 'Bitte Passwort eingeben.';
      return;
    }
    btn.disabled = true;
    msg.textContent = isReg ? 'Erstelle Konto …' : 'Melde an …';
    try {
      if (isReg) {
        await auth.register(e, p);
        renderPending(auth, body, e);
      } else {
        await auth.login(e, p);
        navigate('/menu');
      }
    } catch (err) {
      btn.disabled = false;
      const m = errText(err);
      if (isReg && (err.code === 'email_exists' || /registr|already|exists|taken/i.test(m))) {
        msg.textContent = 'Diese E-Mail hat schon ein Konto — wechsle zu „Anmelden".';
      } else if (/rate limit/i.test(m)) {
        msg.textContent = 'Zu viele E-Mails in kurzer Zeit. Bitte in ein paar Minuten erneut versuchen.';
      } else if (!isReg && /not confirmed|confirm/i.test(m)) {
        msg.textContent = 'E-Mail noch nicht bestätigt. Bitte zuerst den Link aus der Mail öffnen.';
      } else if (!isReg && /invalid login|credential/i.test(m)) {
        msg.textContent = 'E-Mail oder Passwort stimmt nicht.';
      } else {
        msg.textContent = 'Fehlgeschlagen: ' + m;
      }
    }
  };
  btn.addEventListener('click', submit);
  pw.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') submit(); });
  email.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') pw.focus(); });
}

// --- E-Mail-Bestaetigung ausstehend ------------------------------------------

function renderPending(auth, body, email) {
  body.innerHTML = `
    <p class="join-hint">📧 Wir haben eine Bestätigung an <strong>${esc(email)}</strong> geschickt.
      Öffne den Link <strong>auf diesem Gerät</strong>, um dein Konto zu aktivieren.</p>
    <button type="button" id="acc-recheck" class="erf-btn done join-go">Ich habe bestätigt</button>
    <button type="button" id="acc-back" class="acc-link">Zurück</button>
    <p id="acc-msg" class="join-msg" role="status"></p>`;
  const msg = body.querySelector('#acc-msg');
  body.querySelector('#acc-recheck').addEventListener('click', async () => {
    msg.textContent = 'Prüfe …';
    try {
      const user = await auth.currentUser();
      if (auth.isPermanent(user)) { renderLoggedIn(auth, body, user); return; }
      msg.textContent = 'Noch nicht bestätigt. Öffne den Link in der E-Mail.';
    } catch (e) { msg.textContent = 'Prüfen fehlgeschlagen — online?'; }
  });
  body.querySelector('#acc-back').addEventListener('click', () => renderAuthForm(auth, body, 'login'));
}

// --- Neues Passwort setzen (Reset-Flow) --------------------------------------

function renderRecovery(auth, body) {
  body.innerHTML = `
    <p class="join-hint">Setze ein neues Passwort für dein Konto.</p>
    <div class="acc-field">
      <input id="acc-pw" class="join-input acc-text" type="password" autocomplete="new-password" placeholder="Neues Passwort" aria-label="Neues Passwort" />
      <button type="button" class="acc-eye" id="acc-eye" aria-label="Passwort anzeigen">👁</button>
    </div>
    <button type="button" id="acc-set" class="erf-btn done join-go">Passwort speichern</button>
    <p id="acc-msg" class="join-msg" role="status"></p>`;
  const pw = body.querySelector('#acc-pw');
  const msg = body.querySelector('#acc-msg');
  body.querySelector('#acc-eye').addEventListener('click', () => {
    pw.type = pw.type === 'password' ? 'text' : 'password';
  });
  const set = async () => {
    if (!pw.value || pw.value.length < 8) { msg.textContent = 'Passwort: mindestens 8 Zeichen.'; return; }
    msg.textContent = 'Speichere …';
    try {
      await auth.setNewPassword(pw.value);
      const user = await auth.currentUser();
      renderLoggedIn(auth, body, user);
    } catch (e) { msg.textContent = 'Fehlgeschlagen: ' + errText(e); }
  };
  body.querySelector('#acc-set').addEventListener('click', set);
  pw.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') set(); });
}

// --- Angemeldet: Profil + Abmelden -------------------------------------------

async function renderLoggedIn(auth, body, user) {
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

function errText(e) { return String((e && e.message) || e); }
