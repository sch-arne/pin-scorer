// Mini-Testframework + App-Treiber fuer die End-to-End-Tests.
//
// Die E2E-Tests fahren die ECHTE App in einem <iframe> auf demselben Origin
// (http://localhost:5173) und bedienen sie ueber das DOM — genau wie ein Mensch:
// Klicks auf Buttons, Tippen in Felder, Hash-Navigation. Geprueft wird, was
// danach im DOM steht und was im localStorage landet.
//
// Warum ein iframe und kein Headless-Runner? Das Projekt hat bewusst keinen
// Build-Step und keine npm-Abhaengigkeiten (kein Playwright/jsdom). Ein iframe
// auf gleichem Origin reicht: localStorage ist geteilt (Seeden + Nachpruefen),
// die Breite des iframes steuert matchMedia (Desktop-/Handy-Layout), und
// window.confirm/alert/print/Downloads lassen sich sauber abfangen.
//
// WICHTIG: Der Runner sichert alle "pins-scorer:*"-Keys vor dem Lauf und stellt
// sie danach wieder her — lokale Entwicklungsdaten gehen nicht verloren.

// ── Registry ────────────────────────────────────────────────────────────────

export const suites = [];
let currentSuite = null;

export function suite(name, fn) {
  currentSuite = { name, tests: [] };
  suites.push(currentSuite);
  fn();
  currentSuite = null;
}

export function test(name, fn) {
  if (!currentSuite) throw new Error('test() ausserhalb von suite()');
  currentSuite.tests.push({ name, fn });
}

// ── Assertions ──────────────────────────────────────────────────────────────

export class AssertionError extends Error {}

function fail(msg) { throw new AssertionError(msg); }

export function ok(cond, msg = 'Bedingung nicht erfuellt') {
  if (!cond) fail(msg);
}

export function eq(actual, expected, msg = '') {
  if (!Object.is(actual, expected)) {
    fail(`${msg ? msg + ': ' : ''}erwartet ${JSON.stringify(expected)}, war ${JSON.stringify(actual)}`);
  }
}

export function deepEq(actual, expected, msg = '') {
  const a = JSON.stringify(actual); const b = JSON.stringify(expected);
  if (a !== b) fail(`${msg ? msg + ': ' : ''}erwartet ${b}, war ${a}`);
}

export function includes(haystack, needle, msg = '') {
  const s = String(haystack);
  if (!s.includes(needle)) fail(`${msg ? msg + ': ' : ''}"${needle}" nicht gefunden in "${s.slice(0, 400)}"`);
}

export function notIncludes(haystack, needle, msg = '') {
  const s = String(haystack);
  if (s.includes(needle)) fail(`${msg ? msg + ': ' : ''}"${needle}" haette nicht vorkommen duerfen`);
}

// ── Storage-Sicherung ───────────────────────────────────────────────────────

const APP_PREFIX = 'pins-scorer';

export function snapshotStorage() {
  const out = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(APP_PREFIX)) out[k] = localStorage.getItem(k);
  }
  return out;
}

export function clearAppStorage() {
  const keys = [];
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    if (k && k.startsWith(APP_PREFIX)) keys.push(k);
  }
  keys.forEach((k) => localStorage.removeItem(k));
}

export function restoreStorage(snap) {
  clearAppStorage();
  Object.entries(snap).forEach(([k, v]) => localStorage.setItem(k, v));
}

// ── App-Treiber ─────────────────────────────────────────────────────────────

const tick = (ms = 0) => new Promise((r) => setTimeout(r, ms));

// Ein Frame IM APP-FENSTER abwarten. Bewusst nicht das requestAnimationFrame des
// Runner-Fensters: das wird vom Browser gedrosselt, sobald die Runner-Seite nicht
// aktiv gemalt wird — die Tests liefen dann minutenlang. Zusaetzlich ein Timeout
// als Sicherheitsnetz, falls auch das App-Fenster gedrosselt wird.
function frame(win) {
  return new Promise((res) => {
    let fertig = false;
    const done = () => { if (!fertig) { fertig = true; res(); } };
    try { win.requestAnimationFrame(done); } catch { /* Fenster weg */ }
    setTimeout(done, 50);
  });
}

export class App {
  constructor(host) {
    this.host = host;
    this.frame = null;
    this.win = null;
    this.doc = null;
    this.errors = [];
    this.consoleErrors = [];
    this.alerts = [];
    this.confirms = [];
    this.prints = [];
    this.downloads = [];
    this.confirmAnswer = true;
  }

  // Frisches App-Fenster. `storage` seedet localStorage-Keys (ohne Prefix),
  // `width` steuert das Layout (>=900 => Desktop-Kontrollzentrum).
  // `direct: true` laedt den Ziel-Hash gleich mit dem Dokument (echter Kaltstart auf
  // dieser Seite). Standard ist der Weg ueber das Menue — im iframe ist die Layout-Breite
  // waehrend des ERSTEN Dokument-Ladens noch nicht endgueltig, sodass eine View, die beim
  // Bauen `matchMedia('(min-width: 900px)')` liest, faelschlich das Handy-Layout waehlt.
  // In einem echten Fenster tritt das nicht auf (die Fenstergroesse steht vor dem Parsen).
  // `offline: true` setzt den Test-Schalter, an dem js/backend/supabase.js auf einem
  // Entwicklungs-Host absichtlich scheitert. Damit nimmt die App deterministisch ihren
  // Offline-Pfad — sonst haenge das Ergebnis daran, ob gerade Netz da ist.
  async boot({ hash = '/menu', width = 1200, height = 900, storage = null, keepStorage = false, direct = false, offline = false } = {}) {
    if (!keepStorage) clearAppStorage();
    if (offline) localStorage.setItem(`${APP_PREFIX}:e2e-offline`, '1');
    if (storage) {
      Object.entries(storage).forEach(([k, v]) => {
        localStorage.setItem(`${APP_PREFIX}:${k}`, JSON.stringify(v));
      });
    }
    this.errors = []; this.consoleErrors = []; this.alerts = [];
    this.confirms = []; this.prints = []; this.downloads = [];
    this.confirmAnswer = true;

    if (this.frame) this.frame.remove();
    const f = document.createElement('iframe');
    f.className = 'app-frame';
    f.style.width = width + 'px';
    f.style.height = height + 'px';
    const ziel = hash.replace(/^#/, '');
    f.src = '/index.html#' + (direct ? ziel : '/menu');
    this.host.innerHTML = '';
    this.host.appendChild(f);
    await new Promise((res, rej) => {
      f.addEventListener('load', res, { once: true });
      f.addEventListener('error', () => rej(new Error('iframe-Ladefehler')), { once: true });
      setTimeout(() => rej(new Error('iframe lud nicht (Timeout)')), 15000);
    });
    this.frame = f;
    this.win = f.contentWindow;
    this.doc = f.contentDocument;
    this._instrument();
    await this.waitFor(() => this.$('#app') && this.$('#app').children.length > 0, 'App montierte nicht');
    if (!direct && ziel.split('?')[0] !== '/menu') await this.go(ziel);
    return this;
  }

  _instrument() {
    const self = this;
    const win = this.win;

    win.addEventListener('error', (e) => {
      self.errors.push(String((e.error && e.error.stack) || e.message || e));
    });
    win.addEventListener('unhandledrejection', (e) => {
      const r = e.reason;
      self.errors.push('unhandledrejection: ' + String((r && r.stack) || r));
    });

    const origErr = win.console.error.bind(win.console);
    win.console.error = (...args) => { self.consoleErrors.push(args.map(String).join(' ')); origErr(...args); };

    win.alert = (m) => { self.alerts.push(String(m)); };
    win.confirm = (m) => { self.confirms.push(String(m)); return self.confirmAnswer; };
    win.prompt = (m) => { self.confirms.push(String(m)); return null; };
    win.print = () => { self.prints.push('window.print'); };

    // Downloads (CSV-Export) abfangen statt wirklich herunterzuladen.
    const A = win.HTMLAnchorElement.prototype;
    const origClick = A.click;
    A.click = function patchedClick() {
      if (this.hasAttribute && this.hasAttribute('download')) {
        // Inhalt SOFORT lesen: die App gibt die Blob-URL nach einer Sekunde wieder frei.
        const eintrag = { name: this.getAttribute('download'), href: this.href, text: null };
        eintrag.text = win.fetch(this.href).then((r) => r.text()).catch((e) => 'FEHLER: ' + e);
        self.downloads.push(eintrag);
        return undefined;
      }
      return origClick.call(this);
    };

    // Druck-Vorschau (Wurfprotokoll) laeuft ueber ein verstecktes iframe, dessen
    // contentWindow.print() gerufen wird. Das fangen wir ab und merken uns das HTML.
    const mo = new win.MutationObserver((muts) => {
      muts.forEach((m) => {
        m.addedNodes.forEach((n) => {
          if (n.tagName !== 'IFRAME') return;
          try {
            const cw = n.contentWindow;
            cw.print = () => {
              self.prints.push(cw.document.documentElement.outerHTML);
              try { n.remove(); } catch { /* egal */ }
            };
          } catch { /* fremdes Origin – ignorieren */ }
        });
      });
    });
    mo.observe(this.doc.body, { childList: true, subtree: true });
  }

  // ── Warten / Navigation ───────────────────────────────────────────────────

  async settle(rounds = 2) {
    for (let i = 0; i < rounds; i++) { await frame(this.win); await tick(0); }
  }

  async waitFor(fn, msg = 'Bedingung trat nicht ein', timeout = 4000) {
    const t0 = Date.now();
    for (;;) {
      let v = false;
      try { v = fn(); } catch { v = false; }
      if (v) return v;
      if (Date.now() - t0 > timeout) fail(`${msg} (Timeout ${timeout}ms)`);
      await tick(16);
    }
  }

  async go(path) {
    this.win.location.hash = '#' + path;
    await this.settle();
    await this.waitFor(() => this.route() === path.split('?')[0], `Route ${path} nicht erreicht`);
    return this;
  }

  route() {
    const raw = String(this.win.location.hash).replace(/^#/, '').split('?')[0];
    return raw || '/menu';
  }

  async reload() {
    const hash = String(this.win.location.hash).replace(/^#/, '') || '/menu';
    await this.boot({
      hash,
      width: parseInt(this.frame.style.width, 10),
      height: parseInt(this.frame.style.height, 10),
      keepStorage: true,
      direct: true,   // echter Neustart auf genau dieser Seite
    });
    return this;
  }

  // ── DOM ───────────────────────────────────────────────────────────────────

  $(sel) { return this.doc.querySelector(sel); }
  $$(sel) { return Array.from(this.doc.querySelectorAll(sel)); }

  need(sel) {
    const el = this.$(sel);
    if (!el) fail(`Element nicht gefunden: ${sel}`);
    return el;
  }

  txt(sel = '#app') {
    const el = this.$(sel);
    return el ? el.textContent.replace(/\s+/g, ' ').trim() : '';
  }

  html(sel = '#app') {
    const el = this.$(sel);
    return el ? el.innerHTML : '';
  }

  // Sichtbarer Text der ganzen App-Seite (fuer grobe Inhalts-Checks).
  page() { return this.txt('#app'); }

  async click(sel) {
    const el = this.need(sel);
    if (el.disabled) fail(`Element ist disabled: ${sel}`);
    el.click();
    await this.settle();
    return this;
  }

  // Klickt das erste Element, dessen Text `label` enthaelt.
  async clickText(sel, label) {
    const el = this.$$(sel).find((e) => e.textContent.replace(/\s+/g, ' ').includes(label));
    if (!el) fail(`Kein "${sel}" mit Text "${label}"`);
    el.click();
    await this.settle();
    return this;
  }

  async setInput(sel, value) {
    const el = this.need(sel);
    el.value = String(value);
    el.dispatchEvent(new this.win.Event('input', { bubbles: true }));
    el.dispatchEvent(new this.win.Event('change', { bubbles: true }));
    await this.settle();
    return this;
  }

  async setSelect(sel, value) {
    const el = this.need(sel);
    el.value = String(value);
    el.dispatchEvent(new this.win.Event('change', { bubbles: true }));
    await this.settle();
    return this;
  }

  async check(sel, on = true) {
    const el = this.need(sel);
    if (el.checked !== on) {
      el.checked = on;
      el.dispatchEvent(new this.win.Event('change', { bubbles: true }));
    }
    await this.settle();
    return this;
  }

  async key(key, opts = {}) {
    this.doc.dispatchEvent(new this.win.KeyboardEvent('keydown', { key, bubbles: true, ...opts }));
    await this.settle();
    return this;
  }

  // ── Speicher ──────────────────────────────────────────────────────────────

  store(key) {
    const raw = localStorage.getItem(`${APP_PREFIX}:${key}`);
    return raw ? JSON.parse(raw) : null;
  }

  games() { return this.store('games') || []; }
  game(id) { return this.games().find((g) => g.id === id) || null; }
  activeGame() { return this.game(this.store('active-game')); }
  wettkaempfe() { return this.store('wettkaempfe') || []; }
  activeWettkampf() {
    const id = this.store('active-wettkampf');
    return this.wettkaempfe().find((w) => w.id === id) || null;
  }

  async downloadText(i = 0) {
    const d = this.downloads[i];
    if (!d) fail('Kein Download aufgezeichnet');
    // Die BOM (Excel-Kennung) gehoert zum Download, nicht zum Inhalt.
    return (await d.text).replace(/^﻿/, '');
  }

  // Keine unbehandelten Fehler waehrend des Tests?
  assertClean(msg = '') {
    if (this.errors.length) {
      fail(`${msg ? msg + ': ' : ''}unbehandelte Fehler in der App:\n- ${this.errors.join('\n- ')}`);
    }
  }
}
