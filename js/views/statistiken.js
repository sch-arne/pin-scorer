// Statistiken: lokale Spiel-Historie (funktioniert offline, ohne Account) plus –
// wenn angemeldet – ein geräteübergreifender Konto-Überblick aus spiel_ergebnis.

import { getGames } from '../store.js';
import { esc } from '../util.js';
import { teilsatzRanges } from '../logic/teilsaetze.js';
import { computeGameStats } from '../logic/statistik.js';

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const STATUS_LBL = { beendet: 'Beendet', laufend: 'Läuft', setup: 'Setup' };

function gameCard(g) {
  const c = g.config;
  const ranges = teilsatzRanges(c);
  let players = [];
  try { players = computeGameStats(c, g.erfassung.bloecke, ranges).players; } catch (e) { return ''; }
  const multi = players.length > 1;
  const medal = (r) => (r === 1 ? '🥇' : r === 2 ? '🥈' : r === 3 ? '🥉' : `${r}.`);
  const rows = players.map((p) => `
    <div class="stat-prow">
      <span class="stat-pname">${multi ? `${medal(p.rang)} ` : ''}${esc(p.name)}</span>
      <strong class="stat-ptotal">${p.gesamt}</strong>
    </div>`).join('');
  return `
    <div class="stat-card">
      <div class="stat-card-head">
        <span class="stat-date">${fmtDate(g.updatedAt || g.createdAt)}</span>
        <span class="status-badge is-${g.status || 'setup'}">${STATUS_LBL[g.status] || 'Setup'}</span>
      </div>
      ${rows}
    </div>`;
}

export function statistikenView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  const games = getGames()
    .filter((g) => g.erfassung && Array.isArray(g.erfassung.bloecke))
    .sort((a, b) => (b.updatedAt || b.createdAt || '').localeCompare(a.updatedAt || a.createdAt || ''));

  const list = games.length
    ? `<div class="stat-list">${games.map(gameCard).join('')}</div>`
    : `<div class="placeholder">
         <p class="placeholder-icon" aria-hidden="true">📊</p>
         <p class="placeholder-text">Noch keine Daten.</p>
         <p class="placeholder-sub">Sobald du Spiele erfasst hast, erscheinen hier deine Statistiken.</p>
       </div>`;

  root.innerHTML = `
    <header class="page-header">
      <a class="back-btn" href="#/menu" aria-label="Zurück zum Menü">←</a>
      <h1 class="page-title">Statistiken</h1>
    </header>
    <div id="stat-account"></div>
    ${list}`;

  loadAccount(root.querySelector('#stat-account'));
  return root;
}

// Geräteübergreifender Überblick (nur wenn angemeldet + online). Best-effort.
async function loadAccount(el) {
  if (!el) return;
  let auth;
  try { auth = await import('../backend/auth.js'); } catch (e) { return; }
  let user = null;
  try { user = await auth.currentUser(); } catch (e) { return; }

  if (!auth.isPermanent(user)) {
    el.innerHTML = `<a href="#/spieler" class="stat-login-hint">👤 Anmelden für geräteübergreifende Statistik →</a>`;
    return;
  }
  try {
    const sb = (await import('../backend/supabase.js')).supabase;
    const { data } = await sb.from('spiel_ergebnis').select('gesamt,bester_satz').eq('profil_id', user.id);
    const metric = (v, l) => `<div class="stats-metric"><span class="stats-metric-val">${v}</span><span class="stats-metric-lbl">${l}</span></div>`;
    if (!data || !data.length) {
      el.innerHTML = `<p class="stat-acc-empty">👤 ${esc(user.email)} — noch keine gespeicherten Ergebnisse.</p>`;
      return;
    }
    const n = data.length;
    const avg = Math.round(data.reduce((s, r) => s + (r.gesamt || 0), 0) / n);
    const best = Math.max(...data.map((r) => r.bester_satz || 0));
    el.innerHTML = `
      <div class="stat-acc-box">
        <div class="stat-acc-head">👤 ${esc(user.email)}</div>
        <div class="stats-metrics">${metric(n, 'Spiele')}${metric(avg, 'Ø Gesamt')}${metric(best, 'bester Satz')}</div>
      </div>`;
  } catch (e) { /* offline -> nur lokale Historie zeigen */ }
}
