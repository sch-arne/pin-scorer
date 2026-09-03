// E2E-Tests headless fahren — fuer CI und fuer "einmal alles durchlaufen lassen" ohne Klicken.
//
//     node tools/e2e-headless.mjs [--port 5173] [--only <Regex>] [--chrome <Pfad>]
//
// Exit-Code 0 = alles gruen, 1 = mindestens ein Test rot (oder der Lauf kam nicht zustande).
//
// BEWUSST OHNE npm-ABHAENGIGKEITEN. Das Projekt hat keinen Build-Step und keine node_modules;
// ein Playwright/Puppeteer nur fuer CI waere der erste Bruch damit. Stattdessen:
//   1) tools/devserver.py starten (liefert die App mit `no-store`),
//   2) ein installiertes Chrome/Edge headless mit --remote-debugging-port starten,
//   3) per CDP (WebSocket, in Node seit v22 eingebaut) die Runner-Seite oeffnen,
//      `window.__E2E_RUN__()` aufrufen und `window.__E2E__` auslesen.
//
// Auf GitHub Actions (ubuntu-latest) ist Chrome vorinstalliert; lokal wird es unten gesucht.

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

// ── Argumente ───────────────────────────────────────────────────────────────
function arg(name, fallback = null) {
  const i = process.argv.indexOf('--' + name);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const PORT = parseInt(arg('port', '5173'), 10);
const ONLY = arg('only', '');
const BASIS = `http://127.0.0.1:${PORT}`;
// Grosszuegig: ein voller Durchlauf braucht ~8 Minuten, ein langsamer CI-Runner mehr.
const GESAMT_TIMEOUT_MS = parseInt(arg('timeout', '1800000'), 10);

const log = (...a) => console.log('[e2e]', ...a);
const schlaf = (ms) => new Promise((r) => setTimeout(r, ms));

// ── Browser finden ──────────────────────────────────────────────────────────
function findeChrome() {
  const explizit = arg('chrome');
  if (explizit) return explizit;
  const kandidaten = [
    process.env.CHROME_PATH,
    // Linux / CI
    '/usr/bin/google-chrome', '/usr/bin/google-chrome-stable', '/usr/bin/chromium',
    '/usr/bin/chromium-browser', '/snap/bin/chromium',
    // macOS
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
    // Windows
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  ].filter(Boolean);
  return kandidaten.find((p) => existsSync(p)) || null;
}

// ── Warten, bis eine URL antwortet ──────────────────────────────────────────
async function warteAufUrl(url, ms = 20000) {
  const bis = Date.now() + ms;
  for (;;) {
    try {
      const r = await fetch(url);
      if (r.ok) return true;
    } catch { /* noch nicht da */ }
    if (Date.now() > bis) throw new Error('Nicht erreichbar: ' + url);
    await schlaf(200);
  }
}

// ── Minimaler CDP-Client ────────────────────────────────────────────────────
class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.offen = new Map();
    ws.addEventListener('message', (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      const p = msg.id != null && this.offen.get(msg.id);
      if (!p) return;
      this.offen.delete(msg.id);
      if (msg.error) p.reject(new Error(msg.error.message || 'CDP-Fehler'));
      else p.resolve(msg.result);
    });
  }

  static async verbinde(wsUrl) {
    const ws = new WebSocket(wsUrl);
    await new Promise((res, rej) => {
      ws.addEventListener('open', res, { once: true });
      ws.addEventListener('error', () => rej(new Error('WebSocket-Fehler: ' + wsUrl)), { once: true });
    });
    return new Cdp(ws);
  }

  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.offen.set(id, { resolve, reject }));
  }

  // Ausdruck in der Seite auswerten; Rueckgabe als JSON-taugliches Ergebnis.
  async evaluiere(ausdruck, { awaitPromise = true } = {}) {
    const r = await this.send('Runtime.evaluate', {
      expression: ausdruck, awaitPromise, returnByValue: true,
    });
    if (r.exceptionDetails) {
      const e = r.exceptionDetails;
      throw new Error('Seitenfehler: ' + (e.exception?.description || e.text));
    }
    return r.result?.value;
  }

  schliesse() { try { this.ws.close(); } catch { /* egal */ } }
}

// ── Hauptlauf ───────────────────────────────────────────────────────────────
let server = null;
let browser = null;
let profil = null;

async function aufraeumen() {
  if (browser) { try { browser.kill(); } catch { /* egal */ } }
  if (server) { try { server.kill(); } catch { /* egal */ } }
  if (profil) { await rm(profil, { recursive: true, force: true }).catch(() => {}); }
}

async function main() {
  const chrome = findeChrome();
  if (!chrome) {
    console.error('[e2e] Kein Chrome/Edge gefunden. Pfad mit --chrome <Pfad> angeben '
      + 'oder CHROME_PATH setzen.');
    return 1;
  }
  log('Browser:', chrome);

  // 1) Dev-Server
  const python = process.platform === 'win32' ? 'python' : 'python3';
  server = spawn(python, [join(ROOT, 'tools', 'devserver.py'), String(PORT)],
    { cwd: ROOT, stdio: 'ignore' });
  await warteAufUrl(BASIS + '/index.html');
  log('Dev-Server laeuft auf', BASIS);

  // 2) Headless-Browser mit Debug-Port
  const debugPort = PORT + 1000;
  profil = await mkdtemp(join(tmpdir(), 'pins-e2e-'));
  browser = spawn(chrome, [
    '--headless=new',
    '--disable-gpu',
    '--no-sandbox',                       // CI-Container laufen oft als root
    '--disable-dev-shm-usage',
    '--window-size=1400,1000',
    '--user-data-dir=' + profil,
    '--remote-debugging-port=' + debugPort,
    'about:blank',
  ], { stdio: 'ignore' });

  await warteAufUrl(`http://127.0.0.1:${debugPort}/json/version`);
  log('Browser bereit (CDP-Port ' + debugPort + ')');

  // 3) Neue Seite oeffnen und verbinden
  const ziel = await fetch(`http://127.0.0.1:${debugPort}/json/new?`
    + encodeURIComponent(BASIS + '/tests/e2e/'), { method: 'PUT' }).then((r) => r.json());
  const cdp = await Cdp.verbinde(ziel.webSocketDebuggerUrl);
  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');

  // Warten, bis der Runner geladen ist.
  const bereitBis = Date.now() + 30000;
  for (;;) {
    const da = await cdp.evaluiere("typeof window.__E2E_RUN__ === 'function'").catch(() => false);
    if (da) break;
    if (Date.now() > bereitBis) throw new Error('Runner-Seite lud nicht (tests/e2e/)');
    await schlaf(250);
  }
  log('Runner geladen — starte Tests' + (ONLY ? ` (Filter: ${ONLY})` : ''));

  // 4) Lauf starten (nicht awaiten — wir pollen den Fortschritt) und abwarten
  await cdp.evaluiere(`window.__E2E_RUN__(${JSON.stringify(ONLY)}); 0`, { awaitPromise: false });

  const bis = Date.now() + GESAMT_TIMEOUT_MS;
  let zuletzt = -1;
  for (;;) {
    const stand = await cdp.evaluiere(
      'JSON.stringify({done:__E2E__.done, pass:__E2E__.pass, fail:__E2E__.fail, n:__E2E__.tests.length})');
    const s = JSON.parse(stand);
    if (s.n !== zuletzt) { log(`${s.n} Tests · ${s.pass} ok · ${s.fail} rot`); zuletzt = s.n; }
    if (s.done) break;
    if (Date.now() > bis) throw new Error('Zeitlimit erreicht — Lauf haengt');
    await schlaf(3000);
  }

  const bericht = JSON.parse(await cdp.evaluiere('JSON.stringify(window.__E2E__)'));
  cdp.schliesse();

  console.log('');
  bericht.tests.forEach((t) => {
    if (!t.ok) console.log(`  ✕ ${t.suite} :: ${t.name}\n      ${t.error}`);
  });
  const dauer = Math.round((bericht.durationMs || 0) / 1000);
  console.log('');
  console.log(bericht.fail
    ? `[e2e] FEHLGESCHLAGEN — ${bericht.pass} ok, ${bericht.fail} rot (${dauer}s)`
    : `[e2e] alle ${bericht.pass} Tests ok (${dauer}s)`);
  return bericht.fail ? 1 : 0;
}

let code = 1;
try {
  code = await main();
} catch (e) {
  console.error('[e2e] Abbruch:', e && e.message ? e.message : e);
  code = 1;
} finally {
  await aufraeumen();
}
process.exit(code);
