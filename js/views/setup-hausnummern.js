// Setup für "Hausnummern" — zwei Tabs (Regeln / Spieler).
//
// Tab "Regeln":  Variante (hoch/niedrig), Platzierung der Würfe, Anzahl Stellen,
//                Anzahl Durchgänge und — nur beim Niedrig-Spiel — wie 0 Holz zählt.
// Tab "Spieler": Anzahl Spieler, Namen, „Das bin ich".
//
// Bewusst schlank: Hausnummern ist ein Spiel für zwischendurch, es braucht weder Bahnwechsel
// noch Teilsätze. Das gespeicherte Spiel hat trotzdem die übliche Form (saetze/wuerfeProSatz/
// teilsaetze), damit die generischen Helfer der App damit umgehen können.

import { navigate } from '../router.js';
import { saveGame, setActiveGame } from '../store.js';
import { esc } from '../util.js';
import {
  VARIANTEN, PLATZIERUNGEN, NULL_REGELN, STELLEN_MIN, STELLEN_MAX, STELLEN_DEFAULT,
  besteHausnummer, schlechtesteHausnummer, formatZahl,
} from '../logic/hausnummern.js';

const TAB_ORDER = ['regeln', 'spieler'];

// Format-Version des gespeicherten Spiels — Ankerpunkt für spätere Migrationen.
const SCHEMA_VERSION = 1;

const MAX_SPIELER = 12;
const MAX_DURCHGAENGE = 20;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

function defaultState() {
  return {
    tab: 'regeln',
    variante: 'hoch',
    platzierung: 'vorn',
    stellen: STELLEN_DEFAULT,
    nullRegel: 'neun',
    durchgaenge: 1,
    spieler: 2,
    spielerData: [{ name: '' }, { name: '' }],
    // "Das bin ich": Index des Spielers, der der angemeldete Account SELBST ist (oder null).
    ichIndex: null,
  };
}

// Hält spielerData konsistent zur Anzahl Spieler.
function ensurePlayers(s) {
  const arr = s.spielerData;
  while (arr.length < s.spieler) arr.push({ name: '' });
  arr.length = s.spieler;
  if (s.ichIndex != null && s.ichIndex >= s.spieler) s.ichIndex = null; // Markierung fiel weg
}

// Die Regeln als Config-Ausschnitt — auch für die Vorschau im Setup (beste/schlechteste Zahl).
function regelnOf(s) {
  return { variante: s.variante, platzierung: s.platzierung, stellen: s.stellen, nullRegel: s.nullRegel };
}

export function setupHausnummernView() {
  const root = document.createElement('div');
  root.className = 'view view-page';
  const state = defaultState();

  function setField(field, val) {
    if (Number.isNaN(val)) { update(); return; }
    if (field === 'spieler') state.spieler = clamp(val, 1, MAX_SPIELER);
    else if (field === 'durchgaenge') state.durchgaenge = clamp(val, 1, MAX_DURCHGAENGE);
    update();
  }

  function currentOf(field) {
    if (field === 'spieler') return state.spieler;
    if (field === 'durchgaenge') return state.durchgaenge;
    return 0;
  }

  function goNext() {
    const idx = TAB_ORDER.indexOf(state.tab);
    state.tab = TAB_ORDER[Math.min(idx + 1, TAB_ORDER.length - 1)];
    update();
  }

  function start() {
    const game = {
      id: 'g' + Date.now(),
      schemaVersion: SCHEMA_VERSION,
      createdAt: new Date().toISOString(),
      spiel: 'hausnummern',
      status: 'setup',
      // Bleibt (wie beim Sportkegeln) am Spiel-Objekt und nicht in config.
      ichIndex: state.ichIndex,
      config: {
        ...regelnOf(state),
        spieler: state.spieler,
        spielerListe: state.spielerData.map((p, i) => ({
          name: p.name.trim() || ('Spieler ' + (i + 1)),
          startBahn: null,
        })),
        // Kompatibilitäts-Felder: ein Durchgang IST ein Satz, seine Würfe sind ein Teilsatz
        // "Volle". So bleiben generische Helfer (teilsatzRanges, Sync-Gerüst) lauffähig.
        saetze: state.durchgaenge,
        wuerfeProSatz: state.stellen,
        gesamtwuerfe: state.durchgaenge * state.stellen,
        teilsaetze: [{ modus: 'volle', wuerfe: state.stellen }],
      },
    };
    saveGame(game);
    setActiveGame(game.id);
    navigate('/hausnummern');
  }

  function update() {
    ensurePlayers(state);
    root.innerHTML = template(state);
    wire();
  }

  function wire() {
    root.querySelectorAll('[data-tab]').forEach((b) =>
      b.addEventListener('click', () => { state.tab = b.dataset.tab; update(); }));

    root.querySelectorAll('[data-variante]').forEach((b) =>
      b.addEventListener('click', () => { state.variante = b.dataset.variante; update(); }));

    root.querySelectorAll('[data-nullregel]').forEach((b) =>
      b.addEventListener('click', () => { state.nullRegel = b.dataset.nullregel; update(); }));

    root.querySelectorAll('[data-stellen]').forEach((b) =>
      b.addEventListener('click', () => { state.stellen = parseInt(b.dataset.stellen, 10); update(); }));

    const pl = root.querySelector('[data-field="platzierung"]');
    if (pl) pl.addEventListener('change', () => { state.platzierung = pl.value; update(); });

    root.querySelectorAll('[data-step]').forEach((b) =>
      b.addEventListener('click', () => {
        const dir = b.dataset.step === 'inc' ? 1 : -1;
        setField(b.dataset.field, currentOf(b.dataset.field) + dir);
      }));
    root.querySelectorAll('[data-input]').forEach((inp) =>
      inp.addEventListener('change', () => setField(inp.dataset.input, parseInt(inp.value, 10))));

    root.querySelectorAll('.player-name').forEach((inp) =>
      inp.addEventListener('input', () => { state.spielerData[parseInt(inp.dataset.player, 10)].name = inp.value; }));
    root.querySelectorAll('[data-ich]').forEach((rb) =>
      rb.addEventListener('change', () => { state.ichIndex = parseInt(rb.dataset.ich, 10); update(); }));
    const ichClear = root.querySelector('[data-action="ich-clear"]');
    if (ichClear) ichClear.addEventListener('click', () => { state.ichIndex = null; update(); });

    const primary = root.querySelector('.btn-primary');
    if (primary) primary.addEventListener('click', () => {
      if (primary.dataset.action === 'start') start();
      else goNext();
    });
  }

  update();
  return root;
}

function stepper(field, value, min, max) {
  return `
    <div class="stepper">
      <button type="button" class="step-btn" data-step="dec" data-field="${field}" aria-label="weniger">−</button>
      <input class="step-val" type="number" inputmode="numeric" min="${min}" max="${max}" value="${value}" data-input="${field}" />
      <button type="button" class="step-btn" data-step="inc" data-field="${field}" aria-label="mehr">+</button>
    </div>`;
}

function tabRegeln(s) {
  const c = regelnOf(s);
  const platz = PLATZIERUNGEN.find((p) => p.key === s.platzierung) || PLATZIERUNGEN[0];
  const stellenOpts = [];
  for (let n = STELLEN_MIN; n <= STELLEN_MAX; n += 1) stellenOpts.push(n);
  const nullRegelSection = s.variante === 'niedrig' ? `
    <section class="field">
      <label class="field-label">Kugel läuft durch <small class="field-note">· kein Holz gefallen</small></label>
      <div class="segmented" role="group">
        ${NULL_REGELN.map((o) => `<button type="button" class="seg-btn${s.nullRegel === o.key ? ' is-active' : ''}" data-nullregel="${o.key}">${esc(o.label)}</button>`).join('')}
      </div>
      <p class="field-hint">${esc((NULL_REGELN.find((o) => o.key === s.nullRegel) || NULL_REGELN[0]).desc)} — vorher ausmachen.</p>
      <p class="field-hint">Ein <strong>ungültiger</strong> Wurf (Fehlwurf) zählt immer 9 — sonst setzte man ihn
        absichtlich, statt sauber durch die Gasse zu spielen.</p>
    </section>` : '';

  return `
    <section class="field">
      <label class="field-label">Variante</label>
      <div class="segmented" role="group">
        ${VARIANTEN.map((o) => `<button type="button" class="seg-btn${s.variante === o.key ? ' is-active' : ''}" data-variante="${o.key}">${esc(o.label)}</button>`).join('')}
      </div>
      <p class="field-hint">${esc((VARIANTEN.find((o) => o.key === s.variante) || VARIANTEN[0]).desc)} — gewertet wird die Summe über alle Durchgänge.</p>
    </section>

    ${nullRegelSection}

    <section class="field">
      <label class="field-label" for="platzierung-select">Wohin zählt der Wurf?</label>
      <select class="select-full" data-field="platzierung" id="platzierung-select">
        ${PLATZIERUNGEN.map((o) => `<option value="${o.key}"${o.key === s.platzierung ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}
      </select>
      <p class="field-hint">${esc(platz.desc)}.</p>
    </section>

    <section class="field">
      <label class="field-label">Stellen <small class="field-note">· Würfe je Durchgang</small></label>
      <div class="chips">
        ${stellenOpts.map((n) => `<button type="button" class="chip${s.stellen === n ? ' is-active' : ''}" data-stellen="${n}">${n}</button>`).join('')}
      </div>
    </section>

    <section class="field field-readout">
      <span class="field-label">Beste Hausnummer</span>
      <span class="readout">${formatZahl(besteHausnummer(c), c)} <small>schlechteste ${formatZahl(schlechtesteHausnummer(c), c)}</small></span>
    </section>

    <section class="field">
      <label class="field-label">Anzahl Durchgänge</label>
      ${stepper('durchgaenge', s.durchgaenge, 1, MAX_DURCHGAENGE)}
      <p class="field-hint">${s.durchgaenge > 1
        ? `${s.durchgaenge} Hausnummern je Spieler — die Summe entscheidet.`
        : 'Mehrere Durchgänge machen es spannender: die Hausnummern werden addiert.'}</p>
    </section>`;
}

function tabSpieler(s) {
  const rows = s.spielerData.map((pl, i) => `
    <div class="player-row">
      <span class="player-idx">${i + 1}</span>
      <input class="player-name" data-player="${i}" type="text" placeholder="Spieler ${i + 1}" value="${esc(pl.name)}" />
      <label class="player-ich" title="Das bin ich — nur dieser Spieler zählt in meine Statistik">
        <input type="radio" name="ich" data-ich="${i}"${s.ichIndex === i ? ' checked' : ''} />
        <span aria-hidden="true">★</span><span class="sr-only">Das bin ich: Spieler ${i + 1}</span>
      </label>
    </div>`).join('');
  return `
    <section class="field">
      <label class="field-label">Anzahl Spieler</label>
      ${stepper('spieler', s.spieler, 1, MAX_SPIELER)}
      <p class="field-hint">Es wird reihum gekegelt — jeder wirft seinen Durchgang am Stück.</p>
    </section>

    <section class="field">
      <label class="field-label">Namen</label>
      <div class="players">${rows}</div>
      <p class="field-hint">★ markiert, wer <strong>du selbst</strong> bist.
        ${s.ichIndex == null ? '<button type="button" class="btn-mini" data-action="ich-clear" hidden></button>' : '<button type="button" class="btn-mini" data-action="ich-clear">★ Markierung entfernen</button>'}</p>
    </section>`;
}

function template(s) {
  const body = s.tab === 'regeln' ? tabRegeln(s) : tabSpieler(s);
  const isLast = s.tab === 'spieler';
  return `
    <header class="page-header">
      <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
      <h1 class="page-title">Hausnummern</h1>
    </header>

    <div class="tabs" role="tablist">
      <button type="button" role="tab" aria-selected="${s.tab === 'regeln'}" class="tab${s.tab === 'regeln' ? ' is-active' : ''}" data-tab="regeln">Regeln</button>
      <button type="button" role="tab" aria-selected="${s.tab === 'spieler'}" class="tab${s.tab === 'spieler' ? ' is-active' : ''}" data-tab="spieler">Spieler</button>
    </div>

    <div class="setup">
      ${body}
      <button type="button" class="btn-primary" data-action="${isLast ? 'start' : 'next'}">${isLast ? 'Spiel starten' : 'Weiter'}</button>
    </div>`;
}
