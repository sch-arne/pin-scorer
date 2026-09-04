// E2E-Runner: laedt die Spec-Dateien, faehrt sie der Reihe nach und schreibt das
// Ergebnis in die Seite UND nach `window.__E2E__` (maschinenlesbar).

import { suites, App, snapshotStorage, restoreStorage, clearAppStorage } from './harness.js';

import './specs/00-router.js';
import './specs/10-setup.js';
import './specs/20-erfassung.js';
import './specs/30-uebersicht-statistik.js';
import './specs/40-export.js';
import './specs/50-wettkampf.js';
import './specs/60-backend-views.js';
import './specs/70-offline.js';
import './specs/80-loeschen.js';
import './specs/90-hausnummern.js';

const resultsEl = document.getElementById('results');
const summaryEl = document.getElementById('summary');
const runBtn = document.getElementById('run');
const host = document.getElementById('host');

// Die App laeuft in voller Breite; im Runner wird sie nur verkleinert ANGEZEIGT.
function fitFrame(app) {
  if (!app.frame) return;
  const w = parseInt(app.frame.style.width, 10) || 1200;
  app.frame.style.transform = `scale(${Math.min(1, 620 / w)})`;
}

function esc(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}

// `filter` (Regex-Text) laeuft gegen "Suite :: Testname" — praktisch beim Nacharbeiten
// einzelner Faelle, ohne den ganzen Durchlauf abzuwarten.
async function run(filter = '') {
  const re = filter ? new RegExp(filter, 'i') : null;
  runBtn.disabled = true;
  resultsEl.innerHTML = '';
  const backup = snapshotStorage();
  const report = { started: new Date().toISOString(), pass: 0, fail: 0, failures: [], tests: [] };
  window.__E2E__ = { done: false, ...report };

  const app = new App(host);
  const t0 = performance.now();

  try {
    for (const s of suites) {
      if (re && !s.tests.some((t) => re.test(`${s.name} :: ${t.name}`))) continue;
      const head = document.createElement('div');
      head.className = 'suite';
      head.textContent = s.name;
      resultsEl.appendChild(head);

      for (const t of s.tests) {
        if (re && !re.test(`${s.name} :: ${t.name}`)) continue;
        const row = document.createElement('div');
        row.className = 't';
        row.innerHTML = `<span>…</span><span>${esc(t.name)}</span><span class="ms"></span>`;
        resultsEl.appendChild(row);

        const tt = performance.now();
        let error = null;
        try {
          await t.fn(app);
          fitFrame(app);
        } catch (e) {
          error = e;
        }
        const ms = Math.round(performance.now() - tt);
        row.children[2].textContent = ms + ' ms';

        const entry = { suite: s.name, name: t.name, ms, ok: !error };
        if (error) {
          report.fail++;
          entry.error = String(error && error.message ? error.message : error);
          entry.stack = String((error && error.stack) || '');
          report.failures.push(entry);
          row.classList.add('fail');
          row.children[0].textContent = '✕';
          const pre = document.createElement('pre');
          pre.className = 'err';
          pre.textContent = entry.error;
          resultsEl.appendChild(pre);
        } else {
          report.pass++;
          row.children[0].textContent = '✓';
        }
        report.tests.push(entry);
        window.__E2E__ = { done: false, ...report };
        summaryEl.className = report.fail ? 's-fail' : 's-run';
        summaryEl.textContent = `${report.pass} ok · ${report.fail} fehlgeschlagen …`;
      }
    }
  } finally {
    if (app.frame) app.frame.remove();
    clearAppStorage();
    restoreStorage(backup);
    runBtn.disabled = false;
  }

  report.durationMs = Math.round(performance.now() - t0);
  summaryEl.className = report.fail ? 's-fail' : 's-pass';
  summaryEl.textContent = report.fail
    ? `${report.pass} ok · ${report.fail} FEHLGESCHLAGEN (${report.durationMs} ms)`
    : `alle ${report.pass} Tests ok (${report.durationMs} ms)`;
  window.__E2E__ = { done: true, ...report };
  return report;
}

runBtn.addEventListener('click', () => run(new URLSearchParams(location.search).get('only') || ''));
window.__E2E_RUN__ = run;

// Automatisch starten, wenn "#auto" in der URL steht (fuer den Aufruf aus Werkzeugen).
if (location.hash.includes('auto')) run();
