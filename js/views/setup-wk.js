// Setup fuer "Sportkegeln-Training" — drei Tabs (Modus / Optionen / Spieler).
//
// Tab "Modus":     Bahnart (oben), Anzahl Bahnen + 1. Bahn, Anzahl Spieler, Bahnwechsel (unten).
// Tab "Optionen":  Anzahl Saetze, Wuerfe/Satz, Gesamtwurfzahl, Anzahl Teilsaetze (nur Teiler),
//                  Modus je Teilsatz (Volle / Abraeumen / Kranz-Abraeumen).
// Tab "Spieler":   Name + Startbahn je Spieler (+ Zufällig), Vorschau Bahnbelegung.
//
// Unten-Button fuehrt zum naechsten Tab; auf dem letzten Tab startet er das Spiel
// (Zusammenfassung erscheint dann auf der Folgeseite).

import { navigate } from '../router.js';
import { saveGame, setActiveGame } from '../store.js';
import { esc } from '../util.js';
import { divisors, nearestDivisor, throwsPerPart } from '../logic/teilsaetze.js';
import { lanePlan } from '../logic/bahnwechsel.js';

const TAB_ORDER = ['modus', 'optionen', 'spieler'];

// Format-Version des gespeicherten Spiels — Ankerpunkt für spätere Migrationen (Server-Sync).
const SCHEMA_VERSION = 1;

const MODI = [
  { key: 'volle', label: 'Volle' },
  { key: 'abraeumen', label: 'Abräumen' },
  { key: 'kranz-abraeumen', label: 'Kranz-Abräumen' },
];

const BAHNEN_OPTS = [1, 2, 4, 6, 8, 10, 12];

const BAHNWECHSEL = [
  { key: 'plus1', label: 'Reihum (+1)' },
  { key: 'minus1', label: 'Reihum (−1)' },
  { key: 'classic', label: 'Classic-Duo' },
  { key: 'bohle', label: 'Bohle-Duo' },
  { key: 'fest', label: 'Feste Bahn' },
];

// Bahnart-Presets (inkl. Standard-Bahnwechsel je Disziplin)
const PRESETS = {
  bohle: { label: 'Bohle', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'volle'], bahnen: 4, bahnwechsel: 'bohle' },
  schere: { label: 'Schere', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'kranz-abraeumen'], bahnen: 4, bahnwechsel: 'plus1' },
  classic: { label: 'Classic', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'abraeumen'], bahnen: 4, bahnwechsel: 'classic' },
};

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// Tatsaechliche Bahnnummern (ab erster Bahn), z.B. erste Bahn 2 / 4 Bahnen -> [2,3,4,5].
function laneNumbers(s) {
  return Array.from({ length: s.bahnen }, (_, i) => s.ersteBahn + i);
}

// Haelt spielerData konsistent zu Anzahl Spieler/Bahnen; jede Startbahn hoechstens EINMAL.
function ensurePlayers(s) {
  const nums = laneNumbers(s);
  const numSet = new Set(nums);
  const arr = s.spielerData;
  while (arr.length < s.spieler) arr.push({ name: '', startBahn: null });
  arr.length = s.spieler;
  const used = new Set();
  arr.forEach((pl) => {
    let lane = pl.startBahn;
    if (lane == null || !numSet.has(lane) || used.has(lane)) {
      lane = nums.find((n) => !used.has(n));
    }
    pl.startBahn = lane;
    used.add(lane);
  });
}

function shuffleStartLanes(s) {
  const nums = laneNumbers(s);
  for (let i = nums.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [nums[i], nums[j]] = [nums[j], nums[i]];
  }
  s.spielerData.forEach((pl, i) => { pl.startBahn = nums[i]; }); // spieler <= bahnen
}

function defaultState() {
  const p = PRESETS.bohle;
  return {
    tab: 'modus',
    preset: 'bohle',
    spieler: 1,
    spielerData: [{ name: '', startBahn: 1 }],
    bahnen: p.bahnen,
    ersteBahn: 1,
    saetze: p.saetze,
    wuerfeProSatz: p.wuerfeProSatz,
    teilsaetze: [...p.teilsaetze],
    bahnwechsel: p.bahnwechsel,
  };
}

export function setupWkView() {
  const root = document.createElement('div');
  root.className = 'view view-page';
  const state = defaultState();

  function applyPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    state.preset = key; // Bahnart bleibt gewählt, auch bei Abweichungen
    state.saetze = p.saetze;
    state.wuerfeProSatz = p.wuerfeProSatz;
    state.teilsaetze = [...p.teilsaetze];
    state.bahnen = p.bahnen;
    state.bahnwechsel = p.bahnwechsel;
    if (state.spieler > state.bahnen) state.spieler = state.bahnen;
    update();
  }

  // Teilsatz-Anzahl aendern (n teilt wuerfeProSatz gleichmaessig). Ohne Re-Render.
  function resizeTeilsaetze(n) {
    n = clamp(n, 1, 99);
    const next = [];
    for (let i = 0; i < n; i++) next.push(state.teilsaetze[i] || 'volle');
    state.teilsaetze = next;
  }

  function setField(field, val) {
    if (Number.isNaN(val)) { update(); return; }
    if (field === 'spieler') { state.spieler = clamp(val, 1, state.bahnen); update(); return; }
    if (field === 'ersteBahn') {
      const v = clamp(val, 1, 999);
      const delta = v - state.ersteBahn;
      state.ersteBahn = v;
      state.spielerData.forEach((pl) => { if (pl.startBahn != null) pl.startBahn += delta; }); // relative Position halten
      update();
      return;
    }
    if (field === 'saetze') state.saetze = clamp(val, 1, 99);
    else if (field === 'wuerfeProSatz') {
      state.wuerfeProSatz = clamp(val, 1, 999);
      const cnt = state.teilsaetze.length;
      if (state.wuerfeProSatz % cnt !== 0) resizeTeilsaetze(nearestDivisor(state.wuerfeProSatz, cnt)); // gleichmaessig halten
    }
    update();
  }

  function currentOf(field) {
    if (field === 'ersteBahn') return state.ersteBahn;
    if (field === 'spieler') return state.spieler;
    if (field === 'saetze') return state.saetze;
    if (field === 'wuerfeProSatz') return state.wuerfeProSatz;
    return 0;
  }

  function goNext() {
    const idx = TAB_ORDER.indexOf(state.tab);
    state.tab = TAB_ORDER[Math.min(idx + 1, TAB_ORDER.length - 1)];
    update();
  }

  function start() {
    const tpp = throwsPerPart(state.wuerfeProSatz, state.teilsaetze.length);
    const game = {
      id: 'g' + Date.now(),
      schemaVersion: SCHEMA_VERSION,
      createdAt: new Date().toISOString(),
      spiel: 'sportkegler-wk',
      status: 'setup',
      config: {
        preset: state.preset,
        spieler: state.spieler,
        spielerListe: state.spielerData.map((p, i) => ({ name: p.name.trim() || ('Spieler ' + (i + 1)), startBahn: p.startBahn })),
        bahnen: state.bahnen,
        ersteBahn: state.ersteBahn,
        saetze: state.saetze,
        wuerfeProSatz: state.wuerfeProSatz,
        gesamtwuerfe: state.saetze * state.wuerfeProSatz,
        teilsaetze: state.teilsaetze.map((modus, i) => ({ modus, wuerfe: tpp[i] })),
        bahnwechsel: state.bahnwechsel,
        bahnplan: lanePlan(state),
      },
    };
    saveGame(game);
    setActiveGame(game.id);
    navigate('/spiel-laufend');
  }

  function update() {
    ensurePlayers(state);
    root.innerHTML = template(state);
    wire();
  }

  function wire() {
    root.querySelectorAll('[data-tab]').forEach((b) =>
      b.addEventListener('click', () => { state.tab = b.dataset.tab; update(); }));

    root.querySelectorAll('[data-preset]').forEach((b) =>
      b.addEventListener('click', () => applyPreset(b.dataset.preset)));

    root.querySelectorAll('[data-step]').forEach((b) =>
      b.addEventListener('click', () => {
        const dir = b.dataset.step === 'inc' ? 1 : -1;
        setField(b.dataset.field, currentOf(b.dataset.field) + dir);
      }));

    root.querySelectorAll('[data-input]').forEach((inp) =>
      inp.addEventListener('change', () => setField(inp.dataset.input, parseInt(inp.value, 10))));

    root.querySelectorAll('[data-teilsatz]').forEach((b) =>
      b.addEventListener('click', () => { resizeTeilsaetze(parseInt(b.dataset.teilsatz, 10)); update(); }));

    root.querySelectorAll('.part-modus').forEach((sel) =>
      sel.addEventListener('change', () => { state.teilsaetze[parseInt(sel.dataset.part, 10)] = sel.value; update(); }));

    root.querySelectorAll('[data-bahnen]').forEach((b) =>
      b.addEventListener('click', () => {
        state.bahnen = parseInt(b.dataset.bahnen, 10);
        if (state.spieler > state.bahnen) state.spieler = state.bahnen; // mehr Spieler als Bahnen nicht erlaubt
        update();
      }));

    const bw = root.querySelector('[data-field="bahnwechsel"]');
    if (bw) bw.addEventListener('change', () => { state.bahnwechsel = bw.value; update(); });

    // Spieler-Tab
    root.querySelectorAll('.player-name').forEach((inp) =>
      inp.addEventListener('input', () => { state.spielerData[parseInt(inp.dataset.player, 10)].name = inp.value; }));
    root.querySelectorAll('.player-lane').forEach((sel) =>
      sel.addEventListener('change', () => {
        const i = parseInt(sel.dataset.player, 10);
        const newLane = parseInt(sel.value, 10);
        const prev = state.spielerData[i].startBahn;
        const other = state.spielerData.findIndex((p, idx) => idx !== i && p.startBahn === newLane);
        if (other >= 0) state.spielerData[other].startBahn = prev; // tauschen, keine Doppelbelegung
        state.spielerData[i].startBahn = newLane;
        update();
      }));
    const shuffle = root.querySelector('[data-action="shuffle"]');
    if (shuffle) shuffle.addEventListener('click', () => { shuffleStartLanes(state); update(); });

    const primary = root.querySelector('.btn-primary');
    if (primary) primary.addEventListener('click', () => {
      if (primary.dataset.action === 'start') start();
      else goNext();
    });
  }

  update();
  return root;
}

function stepper(field, value, min) {
  return `
    <div class="stepper">
      <button type="button" class="step-btn" data-step="dec" data-field="${field}" aria-label="weniger">−</button>
      <input class="step-val" type="number" inputmode="numeric" min="${min}" value="${value}" data-input="${field}" />
      <button type="button" class="step-btn" data-step="inc" data-field="${field}" aria-label="mehr">+</button>
    </div>`;
}

function tabModus(s) {
  return `
    <section class="field">
      <label class="field-label">Bahnart</label>
      <div class="segmented" role="group">
        ${Object.entries(PRESETS).map(([k, p]) => `<button type="button" class="seg-btn${s.preset === k ? ' is-active' : ''}" data-preset="${k}">${p.label}</button>`).join('')}
      </div>
    </section>

    <section class="field">
      <label class="field-label">Anzahl Bahnen</label>
      <div class="chips bahnen-row">
        ${BAHNEN_OPTS.map((n) => `<button type="button" class="chip${s.bahnen === n ? ' is-active' : ''}" data-bahnen="${n}">${n}</button>`).join('')}
        <div class="inline-num">
          <span class="inline-num-label">1. Bahn</span>
          <div class="inline-stepper">
            <button type="button" class="step-btn sm" data-step="dec" data-field="ersteBahn" aria-label="erste Bahn weniger">−</button>
            <input class="step-val sm" type="number" inputmode="numeric" min="1" value="${s.ersteBahn}" data-input="ersteBahn" />
            <button type="button" class="step-btn sm" data-step="inc" data-field="ersteBahn" aria-label="erste Bahn mehr">+</button>
          </div>
        </div>
      </div>
      <p class="field-hint">Bahn ${s.ersteBahn}–${s.ersteBahn + s.bahnen - 1}</p>
    </section>

    <section class="field">
      <label class="field-label">Anzahl Spieler</label>
      ${stepper('spieler', s.spieler, 1)}
      <p class="field-hint">Höchstens so viele wie Bahnen (${s.bahnen}).</p>
    </section>

    <section class="field">
      <label class="field-label">Bahnwechsel</label>
      <select class="select-full" data-field="bahnwechsel">
        ${BAHNWECHSEL.map((o) => `<option value="${o.key}"${o.key === s.bahnwechsel ? ' selected' : ''}>${o.label}</option>`).join('')}
      </select>
    </section>`;
}

function tabOptionen(s) {
  const tpp = throwsPerPart(s.wuerfeProSatz, s.teilsaetze.length);
  const divs = divisors(s.wuerfeProSatz);
  return `
    <section class="field">
      <label class="field-label">Anzahl Sätze</label>
      ${stepper('saetze', s.saetze, 1)}
    </section>

    <section class="field">
      <label class="field-label">Würfe pro Satz</label>
      ${stepper('wuerfeProSatz', s.wuerfeProSatz, 1)}
    </section>

    <section class="field field-readout">
      <span class="field-label">Gesamtwurfzahl</span>
      <span class="readout">${s.saetze * s.wuerfeProSatz} <small>(${s.saetze} × ${s.wuerfeProSatz})</small></span>
    </section>

    <section class="field">
      <label class="field-label">Anzahl Teilsätze</label>
      <div class="chips">
        ${divs.map((n) => `<button type="button" class="chip${s.teilsaetze.length === n ? ' is-active' : ''}" data-teilsatz="${n}">${n}</button>`).join('')}
      </div>
      <p class="field-hint">Nur gleichmäßige Aufteilung (Teiler von ${s.wuerfeProSatz}).</p>
    </section>

    <section class="field">
      <label class="field-label">Modus je Teilsatz</label>
      <div class="parts">
        ${s.teilsaetze.map((m, i) => `
          <div class="part-row">
            <span class="part-name">Teilsatz ${i + 1}</span>
            <span class="part-throws">${tpp[i]} Wurf</span>
            <select class="part-modus" data-part="${i}">
              ${MODI.map((o) => `<option value="${o.key}"${o.key === m ? ' selected' : ''}>${o.label}</option>`).join('')}
            </select>
          </div>`).join('')}
      </div>
    </section>`;
}

function tabSpieler(s) {
  const nums = laneNumbers(s);
  const rows = s.spielerData.map((pl, i) => `
    <div class="player-row">
      <span class="player-idx">${i + 1}</span>
      <input class="player-name" data-player="${i}" type="text" placeholder="Spieler ${i + 1}" value="${esc(pl.name)}" />
      <select class="player-lane" data-player="${i}">
        ${nums.map((n) => `<option value="${n}"${pl.startBahn === n ? ' selected' : ''}>Bahn ${n}</option>`).join('')}
      </select>
    </div>`).join('');
  return `
    <section class="field">
      <div class="field-row">
        <label class="field-label">Spieler & Startbahn</label>
        <button type="button" class="btn-mini" data-action="shuffle">🎲 Zufällig</button>
      </div>
      <div class="players">${rows}</div>
      <p class="field-hint">Anzahl Spieler änderst du im Tab „Modus". Keine Bahn doppelt – bei Konflikt wird getauscht.</p>
    </section>

    <section class="field">
      <label class="field-label">Vorschau — Bahnbelegung</label>
      ${previewTable(s)}
      <p class="field-hint">Zahl = Spieler-Nr., leere Zelle = freie Bahn.</p>
    </section>`;
}

function previewTable(s) {
  const plan = lanePlan(s); // plan[spieler][satz] = Bahnnummer
  const nums = laneNumbers(s);
  const names = s.spielerData.map((p, i) => esc(p.name.trim() || ('Spieler ' + (i + 1))));
  // Spalten = Bahnen, Zeilen = Sätze, Zelle = Spieler-Nr. (leer = freie Bahn)
  const head = ['<th>Satz</th>', ...nums.map((n) => `<th>Bahn ${n}</th>`)].join('');
  const rows = Array.from({ length: s.saetze }, (_, set) => {
    const cells = nums.map((laneNum) => {
      const pills = [];
      plan.forEach((lanes, p) => {
        if (lanes[set] === laneNum) pills.push(`<span class="lane-pill" title="${names[p]}">${p + 1}</span>`);
      });
      return `<td>${pills.length ? pills.join(' ') : '<span class="lane-empty">–</span>'}</td>`;
    }).join('');
    return `<tr><th>Satz ${set + 1}</th>${cells}</tr>`;
  }).join('');
  return `<div class="preview-wrap"><table class="preview"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>`;
}

function template(s) {
  const body = s.tab === 'modus' ? tabModus(s)
    : s.tab === 'optionen' ? tabOptionen(s)
    : tabSpieler(s);
  const isLast = s.tab === 'spieler';
  return `
    <header class="page-header">
      <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
      <h1 class="page-title">Sportkegeln-Training</h1>
    </header>

    <div class="tabs" role="tablist">
      <button type="button" role="tab" aria-selected="${s.tab === 'modus'}" class="tab${s.tab === 'modus' ? ' is-active' : ''}" data-tab="modus">Modus</button>
      <button type="button" role="tab" aria-selected="${s.tab === 'optionen'}" class="tab${s.tab === 'optionen' ? ' is-active' : ''}" data-tab="optionen">Optionen</button>
      <button type="button" role="tab" aria-selected="${s.tab === 'spieler'}" class="tab${s.tab === 'spieler' ? ' is-active' : ''}" data-tab="spieler">Spieler</button>
    </div>

    <div class="setup">
      ${body}
      <button type="button" class="btn-primary" data-action="${isLast ? 'start' : 'next'}">${isLast ? 'Spiel starten' : 'Weiter'}</button>
    </div>`;
}
