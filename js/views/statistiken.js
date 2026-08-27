// Statistiken: lokale Spiel-Historie (funktioniert offline, ohne Account) plus –
// wenn angemeldet – ein geräteübergreifender Konto-Überblick aus spiel_ergebnis sowie
// die beendeten Spiele des Accounts von ANDEREN Geräten. Jede beendete Spielkarte lässt
// sich antippen, um das Spiel (Auswertung/Wurfprotokoll) wieder aufzurufen.

import { getGames, getGame, saveGame, setActiveGame, setActiveWettkampf } from '../store.js';
import { navigate } from '../router.js';
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

// „Meine Ergebnisse aus fremd erfassten Spielen" (per LizenzID gefunden). Jede Zeile ist
// anklickbar und öffnet das Spiel (Auswertung/Wurfprotokoll) — die RLS gibt ein Spiel, in dem
// die eigene LizenzID als Spieler geführt wird, zum Lesen frei. Leer -> nichts anzeigen.
function fremdSection(rows) {
  if (!rows || !rows.length) return '';
  const fmtDay = (iso) => { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleDateString('de-DE'); };
  const items = rows.map((r) => `
    <div class="stat-fremd-row is-openable" role="button" tabindex="0" data-open-remote="${esc(r.spiel_id)}">
      <span class="stat-fremd-date">${fmtDay(r.erstellt_am)}</span>
      <span class="stat-fremd-meta">${r.rang ? `${r.rang}. · ` : ''}Ø ${r.schnitt_satz != null ? Math.round(r.schnitt_satz) : '–'} · bester ${r.bester_satz ?? '–'}</span>
      <strong class="stat-fremd-total">${r.gesamt ?? '–'}</strong>
      <span class="stat-fremd-open" aria-hidden="true">›</span>
    </div>`).join('');
  return `
    <div class="stat-fremd-box">
      <div class="stat-fremd-head">🏅 Meine Ergebnisse (per LizenzID) <span class="stat-fremd-hint">aus fremd erfassten Spielen · antippen zum Öffnen</span></div>
      ${items}
    </div>`;
}

// Ein per LizenzID gefundenes Spiel öffnen: vollständig aus der DB laden (RLS erlaubt es,
// weil die eigene LizenzID darin als Spieler geführt wird), lokal übernehmen und öffnen.
// Read-only, da dieses Gerät keinen Spieler des Spiels besitzt.
async function openRemoteGame(spielId) {
  try {
    const localId = 'r-' + spielId;
    let g = getGame(localId);
    if (!g) {
      const sync = await import('../backend/sync.js');
      g = await sync.pullGame(spielId);
      saveGame(g);
    }
    setActiveGame(g.id);
    navigate('/spiel-laufend');
  } catch (e) {
    window.alert('Das Spiel konnte nicht geladen werden — bist du online?');
  }
}

// Eine Spielkarte. `remote` markiert Spiele, die (noch) nur in der DB liegen (von einem
// anderen Gerät) — sie bekommen einen Hinweis, werden aber beim Antippen lokal übernommen.
function gameCard(g, { remote = false } = {}) {
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
  const openable = g.status === 'beendet';
  return `
    <div class="stat-card${openable ? ' is-openable' : ''}"${openable ? ` role="button" tabindex="0" data-open="${esc(g.id)}"` : ''}>
      <div class="stat-card-head">
        <span class="stat-date">${fmtDate(g.updatedAt || g.createdAt)}${remote ? ' · ☁ anderes Gerät' : ''}</span>
        <span class="status-badge is-${g.status || 'setup'}">${STATUS_LBL[g.status] || 'Setup'}</span>
      </div>
      ${rows}
      ${openable ? '<div class="stat-open-hint">Antippen, um wieder aufzurufen ›</div>' : ''}
    </div>`;
}

export function statistikenView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  const localGames = getGames()
    .filter((g) => g.erfassung && Array.isArray(g.erfassung.bloecke))
    .sort((a, b) => (b.updatedAt || b.createdAt || '').localeCompare(a.updatedAt || a.createdAt || ''));

  const list = localGames.length
    ? `<div class="stat-list">${localGames.map((g) => gameCard(g)).join('')}</div>`
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
    <div id="stat-list-wrap">${list}</div>`;

  // Bereits vorhandene (lokale) beendete Spiele anklickbar machen; die geräteübergreifenden
  // kommen asynchron dazu (loadAccount) und werden dort ebenfalls verdrahtet.
  const listWrap = root.querySelector('#stat-list-wrap');
  wireOpen(listWrap, {});
  loadAccount(root.querySelector('#stat-account'), listWrap);
  return root;
}

// Ein beendetes Spiel wieder aufrufen (Auswertung/Wurfprotokoll). Bei rein remote geladenen
// Spielen wird das mitgegebene Objekt zuvor lokal gespeichert, damit die Erfassungs-View es
// über getActiveGame findet (und es künftig auch offline verfügbar ist).
function openGame(id, remoteById) {
  let g = getGame(id) || (remoteById && remoteById[id]);
  if (!g) return;
  if (!getGame(id)) saveGame(g); // remote geladenes Spiel lokal übernehmen
  if (g.wettkampfId) setActiveWettkampf(g.wettkampfId); // damit „Zurück" in den Hub führt
  setActiveGame(id);
  navigate('/spiel-laufend');
}

// Alle Karten mit data-open im Container mit Klick/Tastatur (Enter/Space) verdrahten.
function wireOpen(container, remoteById) {
  if (!container) return;
  container.querySelectorAll('[data-open]').forEach((card) => {
    if (card.dataset.wired) return;
    card.dataset.wired = '1';
    const go = () => openGame(card.dataset.open, remoteById);
    card.addEventListener('click', go);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
  });
}

// Geräteübergreifender Überblick (nur wenn angemeldet + online). Best-effort:
//  1) Aggregat-Box (Ø/bester Satz) aus spiel_ergebnis.
//  2) Beendete Spiele des Accounts von ANDEREN Geräten in die Liste einmischen.
async function loadAccount(el, listWrap) {
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
    // Eigene LizenzID (profil.passnummer) — matcht Ergebnisse aus fremd erfassten Spielen
    // (z.B. Vereins-PC), die man selbst nie erfasst hat. Best-effort; null = kein Profil/keine ID.
    let myPass = null;
    try { myPass = (await auth.getProfil())?.passnummer || null; } catch (e) { /* egal */ }

    const cols = 'id,spiel_id,gesamt,schnitt_satz,bester_satz,rang,erstellt_am,profil_id';
    const [own, byPass] = await Promise.all([
      sb.from('spiel_ergebnis').select(cols).eq('profil_id', user.id),
      myPass ? sb.from('spiel_ergebnis').select(cols).eq('passnummer', myPass) : Promise.resolve({ data: [] }),
    ]);
    // Zusammenführen + deduplizieren (dieselbe Ergebniszeile kann über beide Wege kommen).
    const byId = new Map();
    (own.data || []).forEach((r) => byId.set(r.id, r));
    (byPass.data || []).forEach((r) => { if (!byId.has(r.id)) byId.set(r.id, r); });
    const data = [...byId.values()];
    // Fremd erfasst = per LizenzID gefunden, aber nicht auf dem eigenen Account erfasst.
    const fremd = data
      .filter((r) => r.profil_id !== user.id)
      .sort((a, b) => (b.erstellt_am || '').localeCompare(a.erstellt_am || ''));

    const metric = (v, l) => `<div class="stats-metric"><span class="stats-metric-val">${v}</span><span class="stats-metric-lbl">${l}</span></div>`;
    if (!data.length) {
      el.innerHTML = `<p class="stat-acc-empty">👤 ${esc(user.email)} — noch keine gespeicherten Ergebnisse.</p>`;
    } else {
      const n = data.length;
      const avg = Math.round(data.reduce((s, r) => s + (r.gesamt || 0), 0) / n);
      const best = Math.max(...data.map((r) => r.bester_satz || 0));
      el.innerHTML = `
        <div class="stat-acc-box">
          <div class="stat-acc-head">👤 ${esc(user.email)}</div>
          <div class="stats-metrics">${metric(n, 'Spiele')}${metric(avg, 'Ø Gesamt')}${metric(best, 'bester Satz')}</div>
        </div>
        ${fremdSection(fremd)}`;
    }
    // Per LizenzID gefundene Ergebniszeilen anklickbar machen -> Spiel öffnen.
    el.querySelectorAll('[data-open-remote]').forEach((row) => {
      const go = () => openRemoteGame(row.dataset.openRemote);
      row.addEventListener('click', go);
      row.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
      });
    });
  } catch (e) { /* offline -> nur lokale Historie zeigen */ }

  // Beendete Spiele des Accounts von anderen Geräten laden und die einmischen, die lokal
  // noch nicht vorliegen (Dedupe über die lokale, aus der remote-id abgeleitete id 'r-'+id).
  try {
    const sync = await import('../backend/sync.js');
    const remoteGames = await sync.pullAccountFinishedGames();
    const localIds = new Set(getGames().map((g) => g.id));
    const neu = remoteGames.filter((g) => !localIds.has(g.id));
    if (!neu.length || !listWrap) return;

    const remoteById = {};
    neu.forEach((g) => { remoteById[g.id] = g; });
    const cardsHtml = neu.map((g) => gameCard(g, { remote: true })).join('');
    if (!cardsHtml) return;

    let listEl = listWrap.querySelector('.stat-list');
    if (!listEl) {
      // Es gab bisher nur den Platzhalter (keine lokalen Spiele) -> echte Liste anlegen.
      listWrap.innerHTML = '<div class="stat-list"></div>';
      listEl = listWrap.querySelector('.stat-list');
    }
    listEl.insertAdjacentHTML('beforeend', cardsHtml);
    wireOpen(listWrap, remoteById);
  } catch (e) { /* offline / keine Berechtigung -> nur lokale Historie zeigen */ }
}
