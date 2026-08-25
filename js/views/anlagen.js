// „Anlagen": Kegel-Standorte anlegen, verwalten und (später) bespielen. Jeder Account
// mit Konto darf eine Anlage mit realen Daten anlegen; alle sehen alle Anlagen. Bahnen
// können gemischte Bahnarten haben; Bahngruppen bündeln Bahnen, die zusammen bespielt
// werden. Erweiterte Funktionen (Kontrollzentrum, Sportwinner, Livestream/OBS) folgen
// später und nur für freigeschaltete Accounts — hier vorerst als gesperrte Platzhalter.
//
// Backend wird nur lazy geladen -> ohne Verbindung bleibt die App nutzbar (nur die
// Anlagen-Funktionen brauchen Netz).

import { esc } from '../util.js';

const BAHNARTEN = [
  ['', '— Bahnart wählen —'],
  ['classic', 'Classic'],
  ['bohle', 'Bohle'],
  ['schere', 'Schere'],
];

// Erweiterte Funktionen (spätere Etappen) — als gesperrte Platzhalter dargestellt.
const FEATURES = [
  ['🎛️', 'Kontrollzentrum', 'Bahnen-Übersicht & Belegung vor Ort'],
  ['🔌', 'Sportwinner', 'Ergebnisse direkt übernehmen'],
  ['📺', 'Livestream / OBS', 'Ansicht zur Einbindung in OBS'],
];

export function anlagenView() {
  const root = document.createElement('div');
  root.className = 'view view-page';
  root.innerHTML = `
    <header class="page-header">
      <a class="back-btn" href="#/menu" aria-label="Zurück">←</a>
      <h1 class="page-title">Anlagen</h1>
    </header>
    <div class="join-body" id="anl-body"><p class="join-msg">Lade …</p></div>`;

  const body = root.querySelector('#anl-body');
  (async () => {
    let mod;
    try {
      mod = await import('../backend/anlagen.js');
    } catch (e) {
      body.innerHTML = '<p class="join-hint">Offline — Anlagen brauchen eine Verbindung.</p>';
      return;
    }
    let auth = null;
    try { auth = await import('../backend/auth.js'); } catch (e) { /* Konto-Check entfällt offline */ }
    renderList({ body, mod, auth });
  })();

  return root;
}

// --- Übersicht ---------------------------------------------------------------

async function renderList(ctx) {
  const { body, mod, auth } = ctx;
  body.innerHTML = `
    <div id="anl-frei"></div>
    <div class="anl-list-head">
      <h2 class="acc-section">Anlagen</h2>
      <button type="button" id="anl-new" class="acc-link anl-new">＋ Neue Anlage</button>
    </div>
    <div id="anl-list"><p class="join-msg">Lade Anlagen …</p></div>
    <p id="anl-msg" class="join-msg" role="status"></p>`;

  renderFreiStatus(body.querySelector('#anl-frei'), mod);

  // "Neue Anlage" braucht ein permanentes Konto (reale Daten, Nachvollziehbarkeit).
  const neuBtn = body.querySelector('#anl-new');
  let user = null;
  if (auth) { try { user = await auth.currentUser(); } catch (e) { /* ignore */ } }
  const darfAnlegen = !!(auth && auth.isPermanent(user));
  neuBtn.addEventListener('click', () => {
    if (darfAnlegen) { renderCreate(ctx); return; }
    const msg = body.querySelector('#anl-msg');
    msg.innerHTML = 'Zum Anlegen einer Anlage brauchst du ein Konto. '
      + '<a class="anl-inline-link" href="#/spieler">Jetzt anmelden →</a>';
  });

  const host = body.querySelector('#anl-list');
  let liste;
  try { liste = await mod.listAnlagen(); } catch (e) {
    host.innerHTML = '<p class="join-hint">Anlagen konnten nicht geladen werden.</p>';
    return;
  }
  if (!liste.length) {
    host.innerHTML = '<p class="join-hint">Noch keine Anlage angelegt.</p>';
    return;
  }

  // Suchfeld nur, wenn sich Filtern lohnt. Filtert die Karten live nach Name/Ort/Straße/PLZ.
  const searchHtml = liste.length > 3
    ? `<div class="anl-search">
         <input type="search" id="anl-search" class="join-input acc-text" placeholder="Anlage suchen …" aria-label="Anlagen durchsuchen" autocomplete="off" />
       </div>`
    : '';
  host.innerHTML = `${searchHtml}<ul class="anl-list"></ul><p class="anl-search-empty join-hint" hidden>Keine Anlage gefunden.</p>`;
  const ul = host.querySelector('ul');
  for (const a of liste) {
    const li = document.createElement('li');
    li.className = 'anl-card';
    const ortLine = [a.strasse, [a.plz, a.ort].filter(Boolean).join(' ')].filter(Boolean).join(', ');
    li.dataset.search = [a.name, a.strasse, a.plz, a.ort].filter(Boolean).join(' ').toLowerCase();
    li.innerHTML = `
      <div class="anl-card-main">
        <span class="anl-name">${esc(a.name)}</span>
        ${ortLine ? `<span class="anl-meta">${esc(ortLine)}</span>` : ''}
        <span class="anl-meta">${a.anzahl_bahnen} Bahn${a.anzahl_bahnen === 1 ? '' : 'en'}</span>
      </div>
      ${a.mein ? `
      <div class="anl-actions">
        <button type="button" class="acc-link" data-act="edit">Bearbeiten</button>
        <button type="button" class="acc-link" data-act="bahnen">Bahnen</button>
      </div>` : '<span class="anl-badge">fremd</span>'}`;

    if (a.mein) {
      li.querySelector('[data-act="edit"]').addEventListener('click', () => renderEditStamm(ctx, a));
      li.querySelector('[data-act="bahnen"]').addEventListener('click', () => renderBahnen(ctx, a));
    }
    ul.appendChild(li);
  }

  const search = host.querySelector('#anl-search');
  if (search) {
    const empty = host.querySelector('.anl-search-empty');
    search.addEventListener('input', () => {
      const q = search.value.trim().toLowerCase();
      let treffer = 0;
      ul.querySelectorAll('.anl-card').forEach((li) => {
        const match = !q || (li.dataset.search || '').includes(q);
        li.hidden = !match;
        if (match) treffer++;
      });
      empty.hidden = treffer > 0;
    });
  }
}

async function renderFreiStatus(host, mod) {
  let frei = false;
  try { frei = await mod.istFreigeschaltet(); } catch (e) { /* ignore */ }
  const feat = FEATURES.map(([icon, name, desc]) => `
    <div class="anl-feature ${frei ? 'is-on' : 'is-locked'}">
      <span class="anl-feature-icon">${icon}</span>
      <span class="anl-feature-text"><strong>${name}</strong><span>${desc}</span></span>
      <span class="anl-feature-state">${frei ? '✓' : '🔒'}</span>
    </div>`).join('');
  host.innerHTML = `
    <div class="anl-frei ${frei ? 'is-on' : ''}">
      <p class="anl-frei-head">${frei
        ? '🔓 Erweiterte Funktionen freigeschaltet'
        : '🔒 Erweiterte Funktionen — Freischaltung erforderlich'}</p>
      <div class="anl-features">${feat}</div>
      ${frei ? '' : '<p class="acc-hint">Diese Funktionen folgen in Kürze und werden für freigeschaltete Accounts aktiviert.</p>'}
    </div>`;
}

// --- Gemeinsame Stammdaten-Felder --------------------------------------------

function stammFelderHtml(anlage) {
  const v = (k) => esc((anlage && anlage[k]) || '');
  return `
    <label class="acc-label" for="anl-f-name">Name der Anlage</label>
    <input id="anl-f-name" class="join-input acc-text" type="text" placeholder="z. B. Kegelzentrum Osnabrück" value="${v('name')}" />
    <label class="acc-label" for="anl-f-strasse">Straße & Hausnummer</label>
    <input id="anl-f-strasse" class="join-input acc-text" type="text" autocomplete="street-address" placeholder="z. B. Musterweg 12" value="${v('strasse')}" />
    <label class="acc-label" for="anl-f-plz">PLZ</label>
    <input id="anl-f-plz" class="join-input acc-text" type="text" inputmode="numeric" autocomplete="postal-code" maxlength="5" placeholder="z. B. 49080" value="${v('plz')}" />
    <label class="acc-label" for="anl-f-ort">Ort</label>
    <input id="anl-f-ort" class="join-input acc-text" type="text" autocomplete="address-level2" placeholder="z. B. Osnabrück" value="${v('ort')}" />`;
}

// Stammdaten aus dem Formular lesen + validieren. Gibt das Feld-Objekt oder null (Fehler).
function leseStamm(body, msg) {
  const get = (id) => body.querySelector(id).value.trim();
  const felder = {
    name: get('#anl-f-name'),
    strasse: get('#anl-f-strasse'),
    plz: get('#anl-f-plz'),
    ort: get('#anl-f-ort'),
  };
  if (!felder.name) { msg.textContent = 'Bitte den Namen der Anlage eingeben.'; return null; }
  if (!felder.strasse) { msg.textContent = 'Bitte Straße & Hausnummer eingeben.'; return null; }
  if (!/^\d{5}$/.test(felder.plz)) { msg.textContent = 'Bitte eine gültige PLZ (5 Ziffern) eingeben.'; return null; }
  if (!felder.ort) { msg.textContent = 'Bitte den Ort eingeben.'; return null; }
  return felder;
}

// --- Anlegen (Stammdaten + Bahnen mit Bahnart) -------------------------------

function renderCreate(ctx) {
  const { body, mod } = ctx;
  const bahnen = Array.from({ length: 4 }, (_, i) => ({ nummer: i + 1, bahnart: '' }));

  body.innerHTML = `
    <h2 class="acc-section">Neue Anlage</h2>
    <p class="join-hint">Bitte echte Daten der Anlage eintragen — alle Stammdaten sind Pflicht.</p>
    ${stammFelderHtml(null)}

    <h2 class="acc-section">Bahnen</h2>
    <p class="acc-hint">Nummer und Bahnart je Bahn festlegen — Bahnart ist Pflicht, gemischte Bahnarten sind erlaubt.</p>
    <ul class="anl-bahn-list" id="anl-bahnen"></ul>
    <button type="button" id="anl-bahn-add" class="acc-link">＋ Bahn hinzufügen</button>

    <button type="button" id="anl-f-save" class="erf-btn done join-go">Anlage anlegen</button>
    <button type="button" id="anl-f-cancel" class="acc-link">Abbrechen</button>
    <p id="anl-msg" class="join-msg" role="status"></p>`;

  const msg = body.querySelector('#anl-msg');
  const ul = body.querySelector('#anl-bahnen');
  const redraw = () => drawBahnRows(ul, bahnen, redraw);
  redraw();

  body.querySelector('#anl-bahn-add').addEventListener('click', () => {
    const maxNr = bahnen.reduce((m, b) => Math.max(m, parseInt(b.nummer, 10) || 0), 0);
    bahnen.push({ nummer: maxNr + 1, bahnart: '' });
    redraw();
  });
  body.querySelector('#anl-f-cancel').addEventListener('click', () => renderList(ctx));

  body.querySelector('#anl-f-save').addEventListener('click', async () => {
    const felder = leseStamm(body, msg);
    if (!felder) return;
    const fehler = bahnenFehler(bahnen);
    if (fehler) { msg.textContent = fehler; return; }

    const btn = body.querySelector('#anl-f-save');
    btn.disabled = true;
    msg.textContent = 'Lege an …';
    try {
      let dupe = [];
      try { dupe = await mod.findeDuplikate({ name: felder.name, plz: felder.plz }); } catch (e) { /* ignore */ }
      if (dupe.length && !confirm(`Es gibt bereits eine Anlage „${felder.name}" in ${felder.plz}. Trotzdem anlegen?`)) {
        btn.disabled = false; msg.textContent = '';
        return;
      }
      await mod.createAnlage(felder, bahnen);
      renderList(ctx);
    } catch (e) {
      btn.disabled = false;
      msg.textContent = 'Anlegen fehlgeschlagen: ' + String((e && e.message) || e);
    }
  });
}

// --- Stammdaten bearbeiten ---------------------------------------------------

function renderEditStamm(ctx, anlage) {
  const { body, mod } = ctx;
  body.innerHTML = `
    <h2 class="acc-section">Anlage bearbeiten</h2>
    ${stammFelderHtml(anlage)}
    <p class="acc-hint">Bahnen werden über die Aktion „Bahnen" verwaltet.</p>
    <button type="button" id="anl-f-save" class="erf-btn done join-go">Speichern</button>
    <button type="button" id="anl-f-cancel" class="acc-link">Abbrechen</button>
    <p id="anl-msg" class="join-msg" role="status"></p>`;

  const msg = body.querySelector('#anl-msg');
  body.querySelector('#anl-f-cancel').addEventListener('click', () => renderList(ctx));
  body.querySelector('#anl-f-save').addEventListener('click', async () => {
    const felder = leseStamm(body, msg);
    if (!felder) return;
    const btn = body.querySelector('#anl-f-save');
    btn.disabled = true;
    msg.textContent = 'Speichere …';
    try { await mod.updateAnlage(anlage.id, felder); renderList(ctx); }
    catch (e) { btn.disabled = false; msg.textContent = 'Speichern fehlgeschlagen: ' + String((e && e.message) || e); }
  });
}

// --- Bahnen verwalten (bestehende Anlage) ------------------------------------

async function renderBahnen(ctx, anlage) {
  const { body, mod } = ctx;
  body.innerHTML = `
    <h2 class="acc-section">Bahnen — ${esc(anlage.name)}</h2>
    <p class="acc-hint">Nummer und Bahnart je Bahn festlegen — Bahnart ist Pflicht, gemischte Bahnarten sind erlaubt.</p>
    <ul class="anl-bahn-list" id="anl-bahnen"><li><p class="join-msg">Lade Bahnen …</p></li></ul>
    <button type="button" id="anl-bahn-add" class="acc-link">＋ Bahn hinzufügen</button>
    <button type="button" id="anl-bahn-save" class="erf-btn done join-go">Bahnen speichern</button>
    <button type="button" id="anl-bahn-back" class="acc-link">Zurück</button>
    <p id="anl-msg" class="join-msg" role="status"></p>`;

  const ul = body.querySelector('#anl-bahnen');
  const msg = body.querySelector('#anl-msg');
  body.querySelector('#anl-bahn-back').addEventListener('click', () => renderList(ctx));

  let bahnen;
  try { bahnen = await mod.listBahnen(anlage.id); } catch (e) {
    ul.innerHTML = '<li><p class="join-hint">Bahnen konnten nicht geladen werden.</p></li>';
    return;
  }
  const redraw = () => drawBahnRows(ul, bahnen, redraw);
  redraw();

  body.querySelector('#anl-bahn-add').addEventListener('click', () => {
    const maxNr = bahnen.reduce((m, b) => Math.max(m, parseInt(b.nummer, 10) || 0), 0);
    bahnen.push({ nummer: maxNr + 1, bahnart: '' });
    redraw();
  });

  body.querySelector('#anl-bahn-save').addEventListener('click', async () => {
    const fehler = bahnenFehler(bahnen);
    if (fehler) { msg.textContent = fehler; return; }
    const btn = body.querySelector('#anl-bahn-save');
    btn.disabled = true;
    msg.textContent = 'Speichere …';
    try {
      await mod.saveBahnen(anlage.id, bahnen);
      try { await mod.updateAnlage(anlage.id, { anzahl_bahnen: bahnen.length }); } catch (e) { /* nachrangig */ }
      renderList(ctx);
    } catch (e) {
      btn.disabled = false;
      msg.textContent = 'Speichern fehlgeschlagen: ' + String((e && e.message) || e);
    }
  });
}

// Gemeinsamer Bahn-Zeilen-Editor (Nummer + Bahnart). Mutiert `bahnen` in place.
function drawBahnRows(ul, bahnen, redraw) {
  ul.innerHTML = '';
  bahnen.forEach((b, i) => {
    const li = document.createElement('li');
    li.className = 'anl-bahn-row';
    const opts = BAHNARTEN.map(([val, label]) =>
      `<option value="${val}" ${(b.bahnart || '') === val ? 'selected' : ''}>${label}</option>`).join('');
    li.innerHTML = `
      <input class="join-input acc-text anl-bahn-nr" type="number" min="1" max="99" step="1" value="${esc(b.nummer)}" aria-label="Bahn-Nummer" />
      <select class="join-input acc-text anl-bahn-art" aria-label="Bahnart">${opts}</select>
      <button type="button" class="acc-link acc-link-danger anl-bahn-del" aria-label="Bahn entfernen">✕</button>`;
    li.querySelector('.anl-bahn-nr').addEventListener('input', (e) => { b.nummer = e.target.value; });
    li.querySelector('.anl-bahn-art').addEventListener('change', (e) => { b.bahnart = e.target.value; });
    li.querySelector('.anl-bahn-del').addEventListener('click', () => { bahnen.splice(i, 1); redraw(); });
    ul.appendChild(li);
  });
}

// Bahnen-Validierung: mind. 1, positive und eindeutige Nummern, Bahnart je Bahn gesetzt.
function bahnenFehler(bahnen) {
  if (!bahnen.length) return 'Bitte mindestens eine Bahn anlegen.';
  const nrs = bahnen.map((b) => parseInt(b.nummer, 10));
  if (nrs.some((n) => !Number.isFinite(n) || n < 1)) return 'Bahn-Nummern müssen positive Zahlen sein.';
  if (new Set(nrs).size !== nrs.length) return 'Bahn-Nummern müssen eindeutig sein.';
  if (bahnen.some((b) => !(b.bahnart || '').trim())) return 'Bitte für jede Bahn eine Bahnart wählen.';
  return null;
}
