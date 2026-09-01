// Statistiken — zwei klar getrennte Sichten:
//
//   1) MEINE Spiele (accountbasiert). Quelle sind die Ergebnis-Snapshots, in denen ICH der
//      Spieler bin: entweder ausdrücklich zugeordnet (spiel_ergebnis.profil_id = mein Konto)
//      oder über die eigene LizenzID gefunden (passnummer = profil.passnummer) — Letzteres
//      auch in Spielen, die jemand anderes erfasst hat (z.B. der Vereins-PC). Wettkampf-
//      Durchgänge sind ausdrücklich dabei; sie tragen als einzige die LizenzID.
//   2) Von diesem Konto ERFASST. Die lokale Historie plus die beendeten Einzelspiele des
//      Accounts von anderen Geräten. Auf einem Vereins-PC sind das überwiegend Spiele
//      ANDERER Personen — sie gehören deshalb nicht in die eigene Auswertung.
//
// Die Trennung ist der Kern der Korrektur: früher wurde `profil_id` beim Spielende für JEDEN
// mit erfassten Spieler auf das eigene Konto gesetzt, wodurch Gegner und Mannschaftskameraden
// in „Ø Gesamt" und „bester Satz" des eigenen Accounts landeten.
//
// Alles Netzabhängige ist best-effort: ohne Verbindung bleibt die lokale Historie sichtbar.

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
const medal = (r) => (r === 1 ? '🥇' : r === 2 ? '🥈' : r === 3 ? '🥉' : `${r}.`);

// Eine Spielkarte. `ichPos` hebt die eigene Zeile hervor; `hinweis` ist ein kleiner Zusatz
// in der Kopfzeile (z.B. „☁ anderes Gerät" oder „👤 fremd erfasst").
function gameCard(g, { ichPos = null, hinweis = '', zuordnung = '' } = {}) {
  const c = g.config;
  const ranges = teilsatzRanges(c);
  let players = [];
  try { players = computeGameStats(c, g.erfassung.bloecke, ranges).players; } catch (e) { return ''; }
  const multi = players.length > 1;
  const rows = players.map((p, i) => `
    <div class="stat-prow${i === ichPos ? ' is-ich' : ''}">
      <span class="stat-pname">${multi ? `${medal(p.rang)} ` : ''}${esc(p.name)}${i === ichPos ? ' <small class="rank-team">★ du</small>' : ''}</span>
      <strong class="stat-ptotal">${p.gesamt}</strong>
    </div>`).join('');
  const openable = g.status === 'beendet';
  return `
    <div class="stat-card${openable ? ' is-openable' : ''}"${openable ? ` role="button" tabindex="0" data-open="${esc(g.id)}"` : ''}>
      <div class="stat-card-head">
        <span class="stat-date">${fmtDate(g.updatedAt || g.createdAt)}${hinweis ? ` · ${esc(hinweis)}` : ''}</span>
        <span class="status-badge is-${g.status || 'setup'}">${STATUS_LBL[g.status] || 'Setup'}</span>
      </div>
      ${rows}
      ${zuordnung}
      ${openable ? '<div class="stat-open-hint">Antippen, um wieder aufzurufen ›</div>' : ''}
    </div>`;
}

// Die lokale (Offline-)Historie rendern. Wird beim Aufbau UND bei jedem Neuladen des
// Konto-Teils aufgerufen, damit die remote ergänzten Karten nicht doppelt angehängt werden.
function renderLokal(listWrap) {
  const localGames = getGames()
    .filter((g) => g.erfassung && Array.isArray(g.erfassung.bloecke))
    .sort((a, b) => (b.updatedAt || b.createdAt || '').localeCompare(a.updatedAt || a.createdAt || ''));
  listWrap.innerHTML = localGames.length
    ? `<div class="stat-list">${localGames.map((g) => gameCard(g)).join('')}</div>`
    : `<div class="placeholder">
         <p class="placeholder-icon" aria-hidden="true">📊</p>
         <p class="placeholder-text">Noch keine Daten.</p>
         <p class="placeholder-sub">Sobald du Spiele erfasst hast, erscheinen hier deine Statistiken.</p>
       </div>`;
  wireOpen(listWrap, {});
}

export function statistikenView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  root.innerHTML = `
    <header class="page-header">
      <a class="back-btn" href="#/menu" aria-label="Zurück zum Menü">←</a>
      <h1 class="page-title">Statistiken</h1>
    </header>
    <div id="stat-account"></div>
    <div id="stat-meine"></div>
    <h2 class="section-label" id="stat-lokal-head">Auf diesem Gerät erfasst</h2>
    <div id="stat-list-wrap"></div>`;

  const listWrap = root.querySelector('#stat-list-wrap');
  renderLokal(listWrap);
  loadAccount(root, listWrap);
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
// Klicks aus dem Zuordnungs-Bereich (select/button) dürfen die Karte NICHT öffnen.
function wireOpen(container, remoteById) {
  if (!container) return;
  container.querySelectorAll('[data-open]').forEach((card) => {
    if (card.dataset.wired) return;
    card.dataset.wired = '1';
    const go = (e) => {
      if (e && e.target && e.target.closest('.stat-zuordnung')) return;
      openGame(card.dataset.open, remoteById);
    };
    card.addEventListener('click', go);
    card.addEventListener('keydown', (e) => {
      if (e.target && e.target.closest('.stat-zuordnung')) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
  });
}

const metric = (v, l) => `<div class="stats-metric"><span class="stats-metric-val">${v}</span><span class="stats-metric-lbl">${l}</span></div>`;

// Kennzahlen über die EIGENEN Ergebniszeilen. Bewusst nur Werte, die je Spiel/Satz sinnvoll
// aggregierbar sind: Anzahl Spiele, Ø Gesamt je Spiel, bester Einzelsatz.
function accountBox(user, rows, hatLizenz) {
  if (!rows.length) {
    return `<div class="stat-acc-box">
        <div class="stat-acc-head">👤 ${esc(user.email)}</div>
        <p class="stat-acc-empty">Noch keine Ergebnisse, die dir zugeordnet sind.</p>
        <p class="field-hint">${hatLizenz
          ? 'Deine LizenzID ist hinterlegt — Ergebnisse erscheinen hier, sobald ein Spiel mit dir in der Aufstellung beendet wurde.'
          : '💡 Hinterlege deine LizenzID unter „Spieler": dann werden dir deine Ergebnisse auch in fremd erfassten Spielen automatisch zugeordnet.'}</p>
      </div>`;
  }
  const n = rows.length;
  const avg = Math.round(rows.reduce((s, r) => s + (r.gesamt || 0), 0) / n);
  const best = Math.max(...rows.map((r) => r.bester_satz || 0));
  return `
    <div class="stat-acc-box">
      <div class="stat-acc-head">👤 ${esc(user.email)}</div>
      <div class="stats-metrics">${metric(n, 'Spiele')}${metric(avg, 'Ø Gesamt')}${metric(best, 'bester Satz')}</div>
      <p class="field-hint">Nur Ergebnisse, in denen <strong>du selbst</strong> gespielt hast — mit erfasste
        Mitspieler und Gegner zählen nicht mit.</p>
    </div>`;
}

// Auswahl „welcher Spieler warst du?" für ein selbst erfasstes, beendetes Spiel, dem noch
// keine eigene Ergebniszeile zugeordnet ist. Nur Positionen, deren Ergebniszeile noch FREI
// ist (profil_id null) — eine fremde Zuordnung lässt die RPC ohnehin nicht überschreiben.
function zuordnungBlock(g, ergebnisse) {
  const owners = g.spielerOwners || {};
  const byId = {};
  ergebnisse.forEach((r) => { byId[r.spieler_id] = r; });
  const opts = (g.config.spielerListe || []).map((sp, i) => {
    const o = owners[i];
    const r = o && byId[o.id];
    if (!r || r.profil_id) return '';
    return `<option value="${esc(r.id)}">${esc(sp.name || 'Spieler ' + (i + 1))}</option>`;
  }).filter(Boolean).join('');
  if (!opts) return '';
  return `
    <div class="stat-zuordnung">
      <label class="field-hint" for="zu-${esc(g.id)}">★ Warst du dabei? Ordne dein Ergebnis zu:</label>
      <div class="field-row">
        <select class="join-input" id="zu-${esc(g.id)}" data-zuordnen-select="${esc(g.id)}">
          <option value="">— auswählen —</option>${opts}
        </select>
        <button type="button" class="btn-mini" data-zuordnen="${esc(g.id)}">Das war ich</button>
      </div>
    </div>`;
}

// Geräteübergreifender Überblick (nur wenn angemeldet + online).
async function loadAccount(root, listWrap) {
  const el = root.querySelector('#stat-account');
  const meineEl = root.querySelector('#stat-meine');
  if (!el) return;

  // Beim Neuladen (nach einer Zuordnung) die lokale Liste frisch aufbauen — sonst würden
  // die remote ergänzten Karten unten ein zweites Mal angehängt.
  if (listWrap) renderLokal(listWrap);
  if (meineEl) meineEl.innerHTML = '';

  let auth;
  try { auth = await import('../backend/auth.js'); } catch (e) { return; }
  let user = null;
  try { user = await auth.currentUser(); } catch (e) { return; }

  if (!auth.isPermanent(user)) {
    el.innerHTML = '<a href="#/spieler" class="stat-login-hint">👤 Anmelden für geräteübergreifende Statistik →</a>';
    return;
  }

  let sync;
  try { sync = await import('../backend/sync.js'); } catch (e) { return; }

  // --- 0) Selbst markierte Ergebnisse abholen ---------------------------------
  // Hat man sich im Wettkampf-Hub als „das bin ich" markiert, aber ein ANDERER hat erfasst
  // (Vereins-PC), steht die eigene profil_id noch nicht an der Ergebniszeile: die RLS erlaubt
  // dem Erfasser bewusst nicht, eine fremde profil_id zu schreiben. Also holt man sie sich hier
  // selbst ab — schreibt ausschließlich das eigene Konto auf noch freie Zeilen.
  try { await sync.meineErgebnisseBeanspruchen(); } catch (e) { /* offline / alte DB */ }

  // --- 1) Meine eigenen Ergebnisse + die zugehörigen Spiele -------------------
  let meine = [];
  try { meine = await sync.pullMeineErgebnisse(); } catch (e) { /* offline */ }
  let hatLizenz = false;
  try { hatLizenz = !!(await sync.meinePassnummer()); } catch (e) { /* egal */ }
  el.innerHTML = accountBox(user, meine, hatLizenz);

  if (meine.length && meineEl) {
    try {
      const spiele = await sync.pullSpieleZuErgebnissen(meine);
      // Ergebniszeile je Spiel -> Position der eigenen Zeile für die Hervorhebung.
      const meineBySpiel = {};
      meine.forEach((r) => { meineBySpiel[r.spiel_id] = r; });
      const remoteById = {};
      const cards = spiele.map((g) => {
        remoteById[g.id] = g;
        const r = meineBySpiel[g.remoteId];
        const owners = g.spielerOwners || {};
        const ichPos = Object.keys(owners).map(Number)
          .find((pos) => owners[pos] && r && owners[pos].id === r.spieler_id);
        const fremd = r && r.erfasst_von && r.erfasst_von !== user.id;
        return gameCard(g, {
          ichPos: ichPos == null ? null : ichPos,
          hinweis: fremd ? '👤 fremd erfasst' : '☁ Konto',
        });
      }).filter(Boolean).join('');
      if (cards) {
        meineEl.innerHTML = `<h2 class="section-label">Meine Spiele</h2><div class="stat-list">${cards}</div>`;
        wireOpen(meineEl, remoteById);
      }
    } catch (e) { /* offline / kein Zugriff */ }
  }

  // --- 2) Von diesem Konto erfasste beendete Einzelspiele --------------------
  try {
    const remoteGames = await sync.pullAccountFinishedGames();
    const localIds = new Set(getGames().map((g) => g.id));
    const neu = remoteGames.filter((g) => !localIds.has(g.id));

    // Für die nachträgliche Zuordnung: alle Ergebniszeilen der gezeigten Spiele. Spiele,
    // in denen mir bereits eine Zeile gehört, brauchen keine Auswahl mehr.
    const schonMeins = new Set(meine.map((r) => r.spiel_id));
    const kandidaten = neu.filter((g) => g.status === 'beendet' && !schonMeins.has(g.remoteId));
    let alleErgebnisse = [];
    try {
      alleErgebnisse = await sync.pullErgebnisseFuerSpiele(kandidaten.map((g) => g.remoteId));
    } catch (e) { /* ohne Zuordnungs-Auswahl weiter */ }
    const ergBySpiel = {};
    alleErgebnisse.forEach((r) => {
      (ergBySpiel[r.spiel_id] = ergBySpiel[r.spiel_id] || []).push(r);
    });

    if (!neu.length || !listWrap) return;
    const remoteById = {};
    neu.forEach((g) => { remoteById[g.id] = g; });
    const cardsHtml = neu.map((g) => gameCard(g, {
      hinweis: '☁ anderes Gerät',
      zuordnung: schonMeins.has(g.remoteId) ? '' : zuordnungBlock(g, ergBySpiel[g.remoteId] || []),
    })).join('');
    if (!cardsHtml) return;

    let listEl = listWrap.querySelector('.stat-list');
    if (!listEl) {
      // Es gab bisher nur den Platzhalter (keine lokalen Spiele) -> echte Liste anlegen.
      listWrap.innerHTML = '<div class="stat-list"></div>';
      listEl = listWrap.querySelector('.stat-list');
    }
    listEl.insertAdjacentHTML('beforeend', cardsHtml);
    wireOpen(listWrap, remoteById);
    wireZuordnen(listWrap, sync, root);
  } catch (e) { /* offline / keine Berechtigung -> nur lokale Historie zeigen */ }
}

// „Das war ich" verdrahten: setzt spiel_ergebnis.profil_id per RPC auf den eigenen Account
// und lädt die Ansicht neu, damit das Spiel in „Meine Spiele" auftaucht.
function wireZuordnen(container, sync, root) {
  container.querySelectorAll('[data-zuordnen]').forEach((btn) => {
    if (btn.dataset.wired) return;
    btn.dataset.wired = '1';
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const gameId = btn.dataset.zuordnen;
      const sel = container.querySelector(`[data-zuordnen-select="${CSS.escape(gameId)}"]`);
      const ergebnisId = sel && sel.value;
      if (!ergebnisId) return;
      btn.disabled = true;
      try {
        const ok = await sync.ergebnisMirZuordnen(ergebnisId);
        if (!ok) { window.alert('Zuordnung nicht möglich — das Ergebnis gehört bereits einem Konto.'); return; }
        const wrap = root.querySelector('#stat-list-wrap');
        loadAccount(root, wrap);
      } catch (err) {
        window.alert('Zuordnung fehlgeschlagen — bist du online?');
      } finally { btn.disabled = false; }
    });
  });
}
