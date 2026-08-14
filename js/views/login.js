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

// --- Angemeldet: Profil + Geräte + Abmelden + Konto löschen -------------------

async function renderLoggedIn(auth, body, user) {
  let profil = null;
  try { profil = await auth.getProfil(); } catch (e) { /* ignore */ }
  const v = (k) => esc((profil && profil[k]) || '');
  body.innerHTML = `
    <p class="join-hint">Angemeldet als <strong>${esc(user.email)}</strong>.</p>

    <h2 class="acc-section">Profil</h2>
    <label class="acc-label" for="acc-name">Anzeigename</label>
    <input id="acc-name" class="join-input acc-text" type="text" autocomplete="name" placeholder="Dein Name" value="${v('anzeigename')}" />
    <p class="acc-hint">Dein Anzeigename kann im öffentlichen Livestream sichtbar sein.</p>

    <label class="acc-label" for="acc-vorname">Vorname</label>
    <input id="acc-vorname" class="join-input acc-text" type="text" autocomplete="given-name" placeholder="optional" value="${v('vorname')}" />
    <label class="acc-label" for="acc-nachname">Nachname</label>
    <input id="acc-nachname" class="join-input acc-text" type="text" autocomplete="family-name" placeholder="optional" value="${v('nachname')}" />
    <label class="acc-label" for="acc-verein">Verein</label>
    <input id="acc-verein" class="join-input acc-text" type="text" placeholder="optional" value="${v('verein')}" />
    <label class="acc-label" for="acc-passnummer">SpielerID / Passnummer</label>
    <input id="acc-passnummer" class="join-input acc-text" type="text" inputmode="numeric" autocapitalize="off" spellcheck="false" placeholder="optional" value="${v('passnummer')}" />
    <p class="acc-hint">Privat. Wird nur zum Abgleich mit Sportwinner genutzt.</p>

    <button type="button" id="acc-save" class="erf-btn done join-go">Speichern</button>

    <h2 class="acc-section">Geräte</h2>
    <div id="acc-devices"><p class="join-msg">Lade Geräte …</p></div>

    <button type="button" id="acc-logout" class="erf-btn join-go acc-logout">Abmelden</button>

    <div id="acc-danger" class="acc-danger"></div>
    <p id="acc-msg" class="join-msg" role="status"></p>`;

  const msg = body.querySelector('#acc-msg');

  body.querySelector('#acc-save').addEventListener('click', async () => {
    const felder = {
      anzeigename: body.querySelector('#acc-name').value,
      vorname:     body.querySelector('#acc-vorname').value,
      nachname:    body.querySelector('#acc-nachname').value,
      verein:      body.querySelector('#acc-verein').value,
      passnummer:  body.querySelector('#acc-passnummer').value,
    };
    try { await auth.saveProfil(felder); msg.textContent = '✓ Gespeichert.'; }
    catch (e) { msg.textContent = 'Speichern fehlgeschlagen.'; }
  });

  body.querySelector('#acc-logout').addEventListener('click', async () => {
    try { await auth.signOut(); } catch (e) { /* ignore */ }
    navigate('/menu');
  });

  // Geräte-Liste und Danger-Zone brauchen jeweils eigene Backend-Module — separat laden,
  // damit ein Fehler (offline) die eingeloggte Ansicht nicht als Ganzes blockiert.
  renderDevices(body.querySelector('#acc-devices'));
  renderDanger(auth, body.querySelector('#acc-danger'), msg);
}

// --- Geräte-Verwaltung -------------------------------------------------------

async function renderDevices(host) {
  let geraetMod;
  try { geraetMod = await import('../backend/geraet.js'); } catch (e) {
    host.innerHTML = '<p class="join-hint">Offline — Geräte nicht abrufbar.</p>';
    return;
  }
  let liste;
  try { liste = await geraetMod.listGeraete(); } catch (e) {
    host.innerHTML = '<p class="join-hint">Geräte konnten nicht geladen werden.</p>';
    return;
  }
  const meins = geraetMod.geraetId();
  if (!liste.length) { host.innerHTML = '<p class="join-hint">Noch keine Geräte registriert.</p>'; return; }

  host.innerHTML = '<ul class="acc-devices"></ul>';
  const ul = host.querySelector('ul');
  for (const g of liste) {
    const li = document.createElement('li');
    li.className = 'acc-device';
    const aktuell = g.id === meins;
    li.innerHTML = `
      <div class="acc-device-info">
        <span class="acc-device-name">${esc(g.name || 'Unbenannt')}</span>
        ${aktuell ? '<span class="acc-badge">dieses Gerät</span>' : ''}
        <span class="acc-device-seen">zuletzt aktiv ${relZeit(g.gesehen_am)}</span>
      </div>
      <div class="acc-device-actions">
        <button type="button" class="acc-link" data-act="rename">Umbenennen</button>
        <button type="button" class="acc-link acc-link-danger" data-act="remove">Entfernen</button>
      </div>`;

    li.querySelector('[data-act="rename"]').addEventListener('click', () => {
      const info = li.querySelector('.acc-device-info');
      info.innerHTML = `
        <input class="join-input acc-text acc-rename" type="text" value="${esc(g.name || '')}" placeholder="Gerätename" />
        <button type="button" class="acc-link" data-act="save">Speichern</button>
        <button type="button" class="acc-link" data-act="cancel">Abbrechen</button>`;
      const input = info.querySelector('.acc-rename');
      input.focus();
      info.querySelector('[data-act="cancel"]').addEventListener('click', () => renderDevices(host));
      const save = async () => {
        try { await geraetMod.renameGeraet(g.id, input.value); } catch (e) { /* ignore */ }
        renderDevices(host);
      };
      info.querySelector('[data-act="save"]').addEventListener('click', save);
      input.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') save(); });
    });

    li.querySelector('[data-act="remove"]').addEventListener('click', async () => {
      const frage = aktuell
        ? 'Dieses Gerät entfernen? Es wird beim nächsten Synchronisieren automatisch neu registriert.'
        : 'Dieses Gerät entfernen?';
      if (!confirm(frage)) return;
      try { await geraetMod.removeGeraet(g.id); } catch (e) { /* ignore */ }
      renderDevices(host);
    });

    ul.appendChild(li);
  }
}

// --- Konto löschen (Danger-Zone, Zwei-Schritt-Bestätigung) -------------------

function renderDanger(auth, host, msg) {
  host.innerHTML = '<button type="button" id="acc-delete" class="acc-link acc-link-danger">Konto löschen</button>';
  host.querySelector('#acc-delete').addEventListener('click', () => {
    host.innerHTML = `
      <p class="acc-hint acc-warn">⚠️ Dein Konto wird <strong>unwiderruflich</strong> gelöscht — inklusive aller
        deiner Spiele, Statistiken und Geräte. Tippe zum Bestätigen <strong>LÖSCHEN</strong> ein.</p>
      <input id="acc-del-confirm" class="join-input acc-text" type="text" autocapitalize="characters" placeholder="LÖSCHEN" />
      <button type="button" id="acc-del-go" class="erf-btn join-go acc-logout" disabled>Konto endgültig löschen</button>
      <button type="button" id="acc-del-cancel" class="acc-link">Abbrechen</button>`;
    const confirmInput = host.querySelector('#acc-del-confirm');
    const go = host.querySelector('#acc-del-go');
    confirmInput.focus();
    confirmInput.addEventListener('input', () => {
      go.disabled = confirmInput.value.trim().toUpperCase() !== 'LÖSCHEN';
    });
    host.querySelector('#acc-del-cancel').addEventListener('click', () => renderDanger(auth, host, msg));
    go.addEventListener('click', async () => {
      go.disabled = true;
      msg.textContent = 'Lösche Konto …';
      try {
        await auth.deleteAccount();
        navigate('/menu');
      } catch (e) {
        msg.textContent = 'Löschen fehlgeschlagen: ' + errText(e);
        renderDanger(auth, host, msg);
      }
    });
  });
}

// Grobe relative Zeitangabe für „zuletzt aktiv".
function relZeit(iso) {
  const t = Date.parse(iso);
  if (!t) return '–';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return 'gerade eben';
  const min = Math.floor(s / 60);
  if (min < 60) return `vor ${min} Min`;
  const std = Math.floor(min / 60);
  if (std < 24) return `vor ${std} Std`;
  const tage = Math.floor(std / 24);
  if (tage < 30) return `vor ${tage} Tag${tage === 1 ? '' : 'en'}`;
  return new Date(t).toLocaleDateString('de-DE');
}

function errText(e) { return String((e && e.message) || e); }
