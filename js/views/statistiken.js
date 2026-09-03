// Statistiken — die Historie. Ein Eintrag ist ein SPIEL im Sinne der App:
//
//   • ein Einzelspiel (Sportkegeln-Training) oder
//   • ein ganzer Wettkampf — mit allen seinen Durchgängen zu EINER Karte gebündelt.
//
// Die einzelnen Durchgänge tauchen hier bewusst nicht mehr einzeln auf: sie sind Teile eines
// Wettkampfs, nicht eigene Spiele. Und ein Wettkampf ist fertig, sobald alle Durchgänge
// durchgeworfen sind — dann wandert er aus „Neues Spiel" (der Arbeitsliste) hierher in die
// Historie. Beide Listen fragen dafür dieselbe Quelle: store.wettkampfStatus leitet den
// Status aus den Erfassungsdaten ab, statt einem evtl. veralteten Statusfeld zu glauben.
//
// Darüber liegen zwei klar getrennte Konto-Sichten:
//
//   1) MEINE Spiele (accountbasiert). Quelle sind die Ergebnis-Snapshots, in denen ICH der
//      Spieler bin: entweder ausdrücklich zugeordnet (spiel_ergebnis.profil_id = mein Konto)
//      oder über die eigene LizenzID gefunden (passnummer = profil.passnummer) — Letzteres
//      auch in Spielen, die jemand anderes erfasst hat (z.B. der Vereins-PC). Beide Wege sind
//      gleichwertig; an jeder Karte steht, welcher gegriffen hat (logic/historie.js). Wettkampf-
//      Durchgänge sind ausdrücklich dabei; sie tragen als einzige die LizenzID und werden
//      je Wettkampf zu einer Karte gebündelt.
//   2) Von diesem Konto ERFASST. Die lokale Historie plus die beendeten Spiele UND
//      Wettkämpfe des Accounts von anderen Geräten. Auf einem Vereins-PC sind das
//      überwiegend Spiele ANDERER Personen — sie gehören nicht in die eigene Auswertung.
//
// Über allem liegt EIN Filter (Spielart + Anlage, logic/historie.js): er greift in beide
// Sichten, weil eine Frage wie „meine Trainings auf der Halle X" sonst zwei Antworten hätte.
// Gefiltert wird an den fertigen Karten (jede trägt ihre Merkmale als data-Attribut) — so
// gilt die Auswahl auch für Karten, die erst später aus dem Netz nachkommen.
//
// Die nachträgliche Zuordnung „das war ich" steckt in views/spiel-zuordnung.js und hängt
// hier an jeder Einzelspiel-Karte — auch an den lokalen Trainingsspielen.
//
// Alles Netzabhängige ist best-effort: ohne Verbindung bleibt die lokale Historie sichtbar.

import {
  getGames, getGame, saveGame, setActiveGame,
  getWettkaempfe, getWettkampf, getWettkaempfeMitErgebnis, getWettkampfGames,
  saveWettkampf, setActiveWettkampf, wettkampfStatus,
} from '../store.js';
import { navigate } from '../router.js';
import { esc } from '../util.js';
import { teilsatzRanges } from '../logic/teilsaetze.js';
import { computeGameStats } from '../logic/statistik.js';
import { computeWettkampfStats } from '../logic/wettkampf.js';
import {
  OHNE_ANLAGE, metaOfGame, metaOfWettkampf, filterOptionen, passtZuFilter, filterSinnvoll,
  ergebnisQuelle, QUELLE_LABEL, quellenZaehlen,
} from '../logic/historie.js';
import { zuordnungBlock, wireZuordnung, ichPosVon } from './spiel-zuordnung.js';
import { spielLoeschen, wettkampfLoeschen } from './loeschen.js';
import { loeschart, GESPERRT } from '../logic/loeschen.js';

function fmtDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const STATUS_LBL = { beendet: 'Beendet', laufend: 'Läuft', setup: 'Setup' };
const medal = (r) => (r === 1 ? '🥇' : r === 2 ? '🥈' : r === 3 ? '🥉' : `${r}.`);
const zeitOf = (o) => (o && (o.updatedAt || o.createdAt)) || '';

// Kopfzeile einer Karte: Datum · Anlage · Hinweis. Die Anlage steht bewusst an der Karte
// (nicht nur im Filter) — sonst wüsste man bei „Ohne Anlage" nicht, warum ein Spiel fehlt.
function kopfzeile(ts, meta, hinweis) {
  return [fmtDate(ts), meta && meta.anlageName ? `📍 ${esc(meta.anlageName)}` : '',
    hinweis ? esc(hinweis) : ''].filter(Boolean).join(' · ');
}

// Eine Ergebniszeile einer Karte. `name` ist bereits escapt (er wird zusammengesetzt).
function prow(name, wert, { ich = false, zusatz = '' } = {}) {
  const klein = [ich ? '★ du' : '', zusatz].filter(Boolean)
    .map((t) => ` <small class="rank-team">${esc(t)}</small>`).join('');
  return `
    <div class="stat-prow${ich ? ' is-ich' : ''}">
      <span class="stat-pname">${name}${klein}</span>
      <strong class="stat-ptotal">${wert}</strong>
    </div>`;
}

// Gemeinsames Karten-Gerüst. `open` = { attr, id } macht die Karte anklickbar; `meta` und
// `ts` hängen die Filter-/Sortiermerkmale an das Element, damit der Filter allein am DOM
// arbeiten kann (siehe applyFilter).
function karte({ kopf, status, titel = '', rows, hint = '', open = null, extra = '', meta = null, ts = '', del = null }) {
  const on = open ? ` role="button" tabindex="0" data-${open.attr}="${esc(open.id)}"` : '';
  const m = meta
    ? ` data-art="${esc(meta.art || '')}" data-anlage="${esc(meta.anlageId || '')}"`
      + ` data-anlage-name="${esc(meta.anlageName || '')}"`
    : '';
  const del1 = del
    ? `<button type="button" class="stat-del" data-${del.attr}="${esc(del.id)}"`
      + ` aria-label="${del.attr === 'del-wk' ? 'Wettkampf' : 'Spiel'} entfernen">🗑</button>`
    : '';
  return `
    <div class="stat-card${open ? ' is-openable' : ''}"${on}${m} data-ts="${esc(ts)}">
      <div class="stat-card-head">
        <span class="stat-date">${kopf}</span>
        <span class="status-badge is-${status || 'setup'}">${STATUS_LBL[status] || 'Setup'}</span>
        ${del1}
      </div>
      ${titel}
      ${rows}
      ${extra}
      ${hint ? `<div class="stat-open-hint">${esc(hint)} ›</div>` : ''}
    </div>`;
}

// Eine Einzelspiel-Karte. `ichPos` hebt die eigene Zeile hervor; `hinweis` ist ein kleiner
// Zusatz in der Kopfzeile (z.B. „☁ anderes Gerät" oder „👤 fremd erfasst").
function gameCard(g, { ichPos = null, hinweis = '', zuordnung = '', konto = null } = {}) {
  const c = g.config;
  let players = [];
  try { players = computeGameStats(c, g.erfassung.bloecke, teilsatzRanges(c)).players; } catch (e) { return ''; }
  const multi = players.length > 1;
  const rows = players.map((p, i) =>
    prow(`${multi ? `${medal(p.rang)} ` : ''}${esc(p.name)}`, p.gesamt, { ich: i === ichPos })).join('');
  const openable = g.status === 'beendet';
  const meta = metaOfGame(g);
  return karte({
    kopf: kopfzeile(zeitOf(g), meta, hinweis),
    status: g.status,
    rows,
    extra: zuordnung,
    meta,
    ts: zeitOf(g),
    open: openable ? { attr: 'open', id: g.id } : null,
    del: delKnopf(g, konto, 'del-spiel'),
    hint: openable ? 'Antippen, um wieder aufzurufen' : '',
  });
}

// Der 🗑-Knopf an einer Karte — aber nur dort, wo es etwas zu entfernen GIBT. Eine Karte, die
// nur über die eigene LizenzID aus einem fremd erfassten Spiel kommt, bekommt keinen Knopf,
// statt ihn anzubieten und die Bedienung dann abzuweisen. `lokal` entscheidet das mit: von
// einem fremden Spiel lässt sich immerhin die Kopie auf DIESEM Gerät entfernen.
function delKnopf(obj, konto, attr) {
  if (!obj) return null;
  const lokal = attr === 'del-wk' ? !!getWettkampf(obj.id) : !!getGame(obj.id);
  if (loeschart(obj, { konto, lokal }) === GESPERRT) return null;
  return { attr, id: obj.id };
}

// Eine WETTKAMPF-Karte: EIN Eintrag für den ganzen Wettkampf statt einer Karte je Durchgang.
// Gezeigt wird die Mannschafts-Rangliste (ab zwei Mannschaften mit Ergebnis), sonst die
// Einzel-Rangliste über alle Durchgänge. `ichSlot` ('<mannschaftId>|<teamPos>') markiert die
// eigene Zeile — dieselbe Markierung, die der Wettkampf-Hub setzt.
function wettkampfCard(w, games, { status = null, hinweis = '', ichSlot = null, openAttr = 'open-wk', zuordnungHint = false, konto = null } = {}) {
  let stats;
  try { stats = computeWettkampfStats(w, games); } catch (e) { return ''; }
  const st = status || wettkampfStatus(w);
  const teams = (stats.mannschaften || []).filter((t) => t.spieler > 0);
  const ich = ichSlot
    ? (stats.einzel || []).find((p) => `${p.mannschaftId}|${p.teamPos}` === ichSlot)
    : null;

  let rows;
  if (teams.length >= 2) {
    rows = teams.map((t) => prow(`${medal(t.rang)} ${esc(t.name)}`, t.gesamt,
      { zusatz: `${t.spieler} Spieler` })).join('');
    // Bei der Mannschafts-Sicht die eigene Zeile zusätzlich zeigen — sonst sähe man in der
    // eigenen Historie sein eigenes Ergebnis gar nicht.
    if (ich) rows += prow(esc(ich.name), ich.gesamt, { ich: true, zusatz: `Durchgang ${ich.durchgangNr}` });
  } else {
    rows = (stats.einzel || []).slice(0, 8).map((p) => prow(`${medal(p.rang)} ${esc(p.name)}`, p.gesamt,
      { ich: !!ich && p === ich, zusatz: p.durchgangNr ? `DG ${p.durchgangNr}` : '' })).join('');
  }

  // Im Wettkampf gilt die Zuordnung für ALLE Durchgänge zugleich (im Paarkreuz sitzt derselbe
  // Spieler jedes Mal auf einem anderen Index). Sie wird deshalb nicht hier, sondern in der
  // Aufstellung des Hubs gesetzt — die Karte sagt bloß, wo.
  const extra = zuordnungHint && !ich
    ? '<p class="field-hint stat-quelle">★ Noch niemandem zugeordnet — öffne den Wettkampf '
      + 'und markiere dich in der Aufstellung.</p>'
    : '';

  const n = (w.durchgaenge || []).length;
  const meta = metaOfWettkampf(w);
  const titel = `<div class="stat-titel">🏆 ${esc(w.name || 'Wettkampf')}`
    + ` <small class="rank-team">${n} ${n === 1 ? 'Durchgang' : 'Durchgänge'}</small></div>`;
  return karte({
    kopf: kopfzeile(zeitOf(w), meta, hinweis),
    status: st,
    titel,
    rows: rows || '<p class="field-hint">Noch keine Ergebnisse erfasst.</p>',
    extra,
    meta,
    ts: zeitOf(w),
    open: { attr: openAttr, id: openAttr === 'open-wkr' ? (w.remoteId || w.id) : w.id },
    del: delKnopf(w, konto, 'del-wk'),
    hint: 'Antippen, um den Wettkampf zu öffnen',
  });
}

// Die lokale (Offline-)Historie: Einzelspiele + Wettkämpfe, gemischt nach Datum. Wird beim
// Aufbau UND bei jedem Neuladen des Konto-Teils aufgerufen, damit die remote ergänzten
// Karten nicht doppelt angehängt werden.
//
// Jede Einzelspiel-Karte trägt die Zuordnung „das war ich" — genau das fehlte bisher fürs
// Sportkegeln-Training: der ★ ließ sich nur im Setup setzen, nie danach.
function renderLokal(listWrap, ctx) {
  const eintraege = [
    ...getGames()
      .filter((g) => !g.wettkampfId && g.erfassung && Array.isArray(g.erfassung.bloecke))
      .map((g) => ({
        ts: zeitOf(g),
        html: gameCard(g, {
          ichPos: ichPosVon(g, ctx.konto),
          konto: ctx.konto,
          zuordnung: zuordnungBlock(g, { konto: ctx.konto, meinPass: ctx.meinPass }),
        }),
      })),
    ...getWettkaempfeMitErgebnis()
      .map((w) => ({
        ts: zeitOf(w),
        html: wettkampfCard(w, getWettkampfGames(w.id), {
          ichSlot: w.ichSlot, zuordnungHint: true, konto: ctx.konto,
        }),
      })),
  ].filter((e) => e.html).sort((a, b) => b.ts.localeCompare(a.ts));

  listWrap.innerHTML = eintraege.length
    ? `<div class="stat-list">${eintraege.map((e) => e.html).join('')}</div>`
    : `<div class="placeholder">
         <p class="placeholder-icon" aria-hidden="true">📊</p>
         <p class="placeholder-text">Noch keine Daten.</p>
         <p class="placeholder-sub">Sobald du Spiele erfasst hast, erscheinen hier deine Statistiken.</p>
       </div>`;
  wireOpen(listWrap, {});
  wireZuordnung(listWrap, {
    gameById: (id) => getGame(id),
    konto: ctx.konto,
    onChanged: () => ctx.reload(),
  });
  wireDelete(listWrap, {
    gameById: (id) => getGame(id),
    wkById: (id) => getWettkampf(id),
    konto: ctx.konto,
    onDone: () => ctx.reload(),
  });
}

export function statistikenView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  // Gemeinsamer Zustand der Seite: wer bin ich (sobald bekannt) und was ist gerade gefiltert.
  const ctx = {
    konto: null,
    meinPass: null,
    filter: { art: '', anlage: '', sort: 'neu' },
    reload: () => {},
  };

  root.innerHTML = `
    <header class="page-header">
      <a class="back-btn" href="#/menu" aria-label="Zurück zum Menü">←</a>
      <h1 class="page-title">Statistiken</h1>
    </header>
    ${filterBar()}
    <div id="stat-account"></div>
    <div id="stat-meine"></div>
    <h2 class="section-label" id="stat-lokal-head">Auf diesem Gerät erfasst</h2>
    <div id="stat-list-wrap"></div>
    <p class="field-hint" id="stat-leer" hidden>Keine Spiele passen zu dieser Auswahl.</p>`;

  const listWrap = root.querySelector('#stat-list-wrap');
  ctx.reload = () => loadAccount(root, listWrap, ctx); // baut die lokale Liste mit auf
  wireFilter(root, ctx);
  renderLokal(listWrap, ctx);
  applyFilter(root, ctx);
  loadAccount(root, listWrap, ctx);
  return root;
}

// ── Filter (Spielart + Anlage) ───────────────────────────────────────────────
// Die Auswahl wird aus den vorhandenen Karten aufgebaut, nicht aus einer festen Liste: was
// nicht in der Historie steht, ist auch keine sinnvolle Auswahl. Sie greift über alle
// Abschnitte hinweg und wird nach jedem Nachladen erneut angewandt.

function filterBar() {
  return `
    <div class="stat-filter" id="stat-filter" hidden>
      <label class="sr-only" for="stat-f-art">Spielart</label>
      <select class="select-full sm" id="stat-f-art" data-filter="art"></select>
      <label class="sr-only" for="stat-f-anlage">Anlage</label>
      <select class="select-full sm" id="stat-f-anlage" data-filter="anlage"></select>
      <label class="sr-only" for="stat-f-sort">Reihenfolge</label>
      <select class="select-full sm" id="stat-f-sort" data-filter="sort">
        <option value="neu">Neueste zuerst</option>
        <option value="alt">Älteste zuerst</option>
      </select>
    </div>`;
}

function wireFilter(root, ctx) {
  root.querySelectorAll('[data-filter]').forEach((sel) => {
    sel.addEventListener('change', () => {
      ctx.filter = { ...ctx.filter, [sel.dataset.filter]: sel.value };
      applyFilter(root, ctx);
    });
  });
}

const metaOfCard = (el) => ({
  art: el.dataset.art || '',
  anlageId: el.dataset.anlage || '',
  anlageName: el.dataset.anlageName || '',
});

// Auswahllisten neu aufbauen und die aktuelle Wahl auf die sichtbaren Karten anwenden.
function applyFilter(root, ctx) {
  const karten = [...root.querySelectorAll('.stat-card')];
  const metas = karten.map(metaOfCard);
  const opt = filterOptionen(metas);

  fuelleSelect(root.querySelector('#stat-f-art'), ctx.filter.art,
    [{ value: '', text: 'Alle Spielarten' },
      ...opt.arten.map((a) => ({ value: a.key, text: `${a.label} (${a.n})` }))]);
  fuelleSelect(root.querySelector('#stat-f-anlage'), ctx.filter.anlage,
    [{ value: '', text: 'Alle Anlagen' },
      ...opt.anlagen.map((a) => ({ value: a.id, text: `${a.id === OHNE_ANLAGE ? '' : '📍 '}${a.name} (${a.n})` }))]);
  const bar = root.querySelector('#stat-filter');
  if (bar) bar.hidden = !filterSinnvoll(opt);

  karten.forEach((el, i) => { el.hidden = !passtZuFilter(metas[i], ctx.filter); });

  // Sortierung innerhalb jeder Liste (die Abschnitte selbst bleiben, wo sie sind).
  const rueckwaerts = ctx.filter.sort === 'alt';
  root.querySelectorAll('.stat-list').forEach((list) => {
    [...list.children]
      .sort((a, b) => {
        const ta = a.dataset.ts || ''; const tb = b.dataset.ts || '';
        return rueckwaerts ? ta.localeCompare(tb) : tb.localeCompare(ta);
      })
      .forEach((el) => list.appendChild(el));
  });

  // Leere Abschnitte ausblenden, damit keine Überschrift ohne Inhalt stehen bleibt.
  const sichtbar = (el) => !!el && [...el.querySelectorAll('.stat-card')].some((c) => !c.hidden);
  const meineEl = root.querySelector('#stat-meine');
  if (meineEl && meineEl.querySelector('.stat-card')) meineEl.hidden = !sichtbar(meineEl);
  const lokalHead = root.querySelector('#stat-lokal-head');
  const listWrap = root.querySelector('#stat-list-wrap');
  const lokalHatKarten = !!(listWrap && listWrap.querySelector('.stat-card'));
  if (lokalHead && lokalHatKarten) lokalHead.hidden = !sichtbar(listWrap);
  if (listWrap && lokalHatKarten) listWrap.hidden = !sichtbar(listWrap);

  const leer = root.querySelector('#stat-leer');
  if (leer) leer.hidden = !(karten.length && karten.every((c) => c.hidden));
}

function fuelleSelect(sel, wert, optionen) {
  if (!sel) return;
  const gibtEs = optionen.some((o) => o.value === wert);
  sel.innerHTML = optionen
    .map((o) => `<option value="${esc(o.value)}"${o.value === wert ? ' selected' : ''}>${esc(o.text)}</option>`)
    .join('');
  if (!gibtEs) sel.value = '';
}

// Ein beendetes Einzelspiel wieder aufrufen (Auswertung/Wurfprotokoll). Bei rein remote
// geladenen Spielen wird das mitgegebene Objekt zuvor lokal gespeichert, damit die
// Erfassungs-View es über getActiveGame findet (und es künftig auch offline da ist).
// Ein Wettkampf-Durchgang wird NICHT allein geöffnet: dafür wird der ganze Wettkampf
// nachgeladen, damit man im Hub landet, wo der Durchgang hingehört.
async function openGame(id, remoteById) {
  const g = getGame(id) || (remoteById && remoteById[id]);
  if (!g) return;
  if (g.wettkampfRemoteId && !g.wettkampfId && await openWettkampfRemote(g.wettkampfRemoteId)) return;
  if (!getGame(id)) saveGame(g); // remote geladenes Spiel lokal übernehmen
  if (g.wettkampfId) setActiveWettkampf(g.wettkampfId); // damit „Zurück" in den Hub führt
  setActiveGame(id);
  navigate('/spiel-laufend');
}

// Einen lokal vorhandenen Wettkampf öffnen (Hub: Rangliste, Durchgänge, Auswertung, Export).
function openWettkampf(id) {
  if (!getWettkampf(id)) return;
  setActiveWettkampf(id);
  navigate('/wettkampf');
}

// Einen nur remote bekannten Wettkampf öffnen: vollständig laden, lokal spiegeln (dieselben
// stabilen 'rw-'/'r-'-IDs wie beim Beitreten) und in den Hub springen. Rückgabe false, wenn
// das nicht geht (offline, kein Leserecht) — der Aufrufer fällt dann auf das Einzelspiel
// zurück, statt den Nutzer auf einer leeren Seite stehen zu lassen.
async function openWettkampfRemote(remoteId) {
  try {
    const sync = await import('../backend/sync.js');
    const { wettkampf, games } = await sync.pullWettkampf(remoteId);
    games.forEach((g) => saveGame(g));
    saveWettkampf(wettkampf);
    setActiveWettkampf(wettkampf.id);
    navigate('/wettkampf');
    return true;
  } catch (e) {
    return false;
  }
}

// Alle Karten im Container mit Klick/Tastatur (Enter/Space) verdrahten. Klicks aus dem
// Zuordnungs-Bereich (select/button) dürfen die Karte NICHT öffnen.
//   data-open      -> Einzelspiel (lokal oder aus `remoteById`)
//   data-open-wk   -> lokaler Wettkampf
//   data-open-wkr  -> nur remote bekannter Wettkampf (remote-id; wird beim Öffnen geladen)
function wireOpen(container, remoteById) {
  if (!container) return;
  container.querySelectorAll('[data-open], [data-open-wk], [data-open-wkr]').forEach((card) => {
    if (card.dataset.wired) return;
    card.dataset.wired = '1';
    const go = (e) => {
      if (e && e.target && e.target.closest('.stat-zuordnung, .stat-del')) return;
      const d = card.dataset;
      if (d.openWk) openWettkampf(d.openWk);
      else if (d.openWkr) openWettkampfRemote(d.openWkr);
      else openGame(d.open, remoteById);
    };
    card.addEventListener('click', go);
    card.addEventListener('keydown', (e) => {
      if (e.target && e.target.closest('.stat-zuordnung, .stat-del')) return;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); }
    });
  });
}

// Die 🗑-Knöpfe eines Containers verdrahten. `gameById`/`wkById` lösen die id am Knopf zu
// dem Objekt auf, das entfernt werden soll — lokal vorhandene zuerst, sonst aus der Karte
// des nur remote geladenen Eintrags. Was dann geschieht (löschen oder verbergen), entscheidet
// views/loeschen.js; hier wird nur neu geladen, wenn wirklich etwas verschwunden ist.
function wireDelete(container, { gameById, wkById, konto, onDone }) {
  if (!container) return;
  container.querySelectorAll('[data-del-spiel], [data-del-wk]').forEach((b) => {
    if (b.dataset.wired) return;
    b.dataset.wired = '1';
    b.addEventListener('click', async (e) => {
      e.stopPropagation();
      const wk = !!b.dataset.delWk;
      const id = wk ? b.dataset.delWk : b.dataset.delSpiel;
      const obj = wk ? (wkById && wkById(id)) : (gameById && gameById(id));
      if (!obj) return;
      const weg = wk
        ? await wettkampfLoeschen(obj, { konto })
        : await spielLoeschen(obj, { konto });
      if (weg) onDone();
    });
  });
}

const metric = (v, l) => `<div class="stats-metric"><span class="stats-metric-val">${v}</span><span class="stats-metric-lbl">${l}</span></div>`;

// Kennzahlen über die EIGENEN Ergebniszeilen. Bewusst nur Werte, die je Spiel/Satz sinnvoll
// aggregierbar sind: Anzahl Spiele, Ø Gesamt je Serie, bester Einzelsatz. Gezählt wird in
// SPIELEN (`spiele`: ein Wettkampf ist eins, egal über wie viele Durchgänge er ging);
// gemittelt wird dagegen je Ergebniszeile, denn das ist die tatsächlich gespielte Serie.
//
// Die Zeile darunter trennt die beiden Wege ins Profil: über die LizenzID gefundene Ergebnisse
// und ausdrücklich zugeordnete. Wer dort eine 0 sieht, weiß sofort, warum etwas fehlt.
function accountBox(user, rows, hatLizenz, spiele = null, meinPass = null) {
  if (!rows.length) {
    return `<div class="stat-acc-box">
        <div class="stat-acc-head">👤 ${esc(user.email)}</div>
        <p class="stat-acc-empty">Noch keine Ergebnisse, die dir zugeordnet sind.</p>
        <p class="field-hint">${hatLizenz
          ? 'Deine LizenzID ist hinterlegt — Ergebnisse erscheinen hier, sobald ein Spiel mit dir in der Aufstellung beendet wurde.'
          : '💡 Hinterlege deine LizenzID unter „Spieler": dann werden dir deine Ergebnisse auch in fremd erfassten Spielen automatisch zugeordnet.'}</p>
        <p class="field-hint">Ohne LizenzID geht es auch: markiere dich im Setup mit ★ oder ordne dir
          ein Ergebnis unten an der Karte nachträglich zu.</p>
      </div>`;
  }
  const n = rows.length;
  const avg = Math.round(rows.reduce((s, r) => s + (r.gesamt || 0), 0) / n);
  const best = Math.max(...rows.map((r) => r.bester_satz || 0));
  const q = quellenZaehlen(rows, meinPass);
  return `
    <div class="stat-acc-box">
      <div class="stat-acc-head">👤 ${esc(user.email)}</div>
      <div class="stats-metrics">${metric(spiele == null ? n : spiele, 'Spiele')}${metric(avg, 'Ø Gesamt')}${metric(best, 'bester Satz')}</div>
      <p class="field-hint">Nur Ergebnisse, in denen <strong>du selbst</strong> gespielt hast — mit erfasste
        Mitspieler und Gegner zählen nicht mit.</p>
      <p class="field-hint">Davon ${q.lizenz} über die LizenzID gefunden, ${q.zuordnung} ausdrücklich zugeordnet.</p>
    </div>`;
}

// Remote-Spiele in Historien-EINTRÄGE gruppieren: Wettkampf-Durchgänge (wettkampfRemoteId
// gesetzt) werden je Wettkampf zu einem Eintrag gebündelt, alles andere bleibt ein
// Einzelspiel. Rückgabe: [{ kind:'game'|'wettkampf', ts, game?, wkId?, games? }], neueste zuerst.
function gruppiere(spiele) {
  const wk = new Map();
  const eintraege = [];
  (spiele || []).forEach((g) => {
    if (!g.wettkampfRemoteId) { eintraege.push({ kind: 'game', ts: zeitOf(g), game: g }); return; }
    let e = wk.get(g.wettkampfRemoteId);
    if (!e) {
      e = { kind: 'wettkampf', ts: '', wkId: g.wettkampfRemoteId, games: [] };
      wk.set(g.wettkampfRemoteId, e);
      eintraege.push(e);
    }
    e.games.push(g);
    if (zeitOf(g) > e.ts) e.ts = zeitOf(g);
  });
  wk.forEach((e) => e.games.sort((a, b) => (a.durchgangNr || 0) - (b.durchgangNr || 0)));
  return eintraege.sort((a, b) => b.ts.localeCompare(a.ts));
}

// Karte für „meinen" Wettkampf: der Kopf ist der Wettkampf, die Zeilen sind MEINE Durchgänge.
// Bewusst nicht die volle Rangliste — geladen sind nur die Durchgänge, in denen ich ein
// Ergebnis habe. Der ganze Wettkampf wird erst beim Antippen nachgeladen.
function meinWettkampfCard(eintrag, kopf, meineBySpiel, meinPass, { konto = null, wkById = null } = {}) {
  const quellen = new Set();
  const rows = eintrag.games.map((g) => {
    let players = [];
    try { players = computeGameStats(g.config, g.erfassung.bloecke, teilsatzRanges(g.config)).players; }
    catch (e) { return ''; }
    const r = meineBySpiel[g.remoteId];
    const owners = g.spielerOwners || {};
    const pos = Object.keys(owners).map(Number)
      .find((p) => owners[p] && r && owners[p].id === r.spieler_id);
    const p = pos == null ? null : (players.find((x) => x.index === pos) || players[pos]);
    if (!p) return '';
    if (r) quellen.add(ergebnisQuelle(r, meinPass));
    return prow(`${medal(p.rang)} ${esc(p.name)}`, p.gesamt,
      { ich: true, zusatz: g.durchgangNr ? `Durchgang ${g.durchgangNr}` : '' });
  }).filter(Boolean).join('');
  if (!rows) return '';
  const n = eintrag.games.length;
  const meta = {
    art: 'sportkegler-wettkampf',
    anlageId: (kopf && kopf.anlage_id) || '',
    anlageName: '',
  };
  // Der Wettkampf selbst liegt hier nicht vor (nur meine Durchgänge) — für das Entfernen
  // genügt aber, WO er liegt und WEM er gehört. Ist er fremd erfasst, fällt der Knopf weg.
  const stellvertreter = {
    id: 'rw-' + eintrag.wkId, remoteId: eintrag.wkId, besitzer: (kopf && kopf.besitzer) || null,
    name: (kopf && kopf.name) || '',
  };
  if (wkById) wkById[stellvertreter.id] = stellvertreter;
  return karte({
    kopf: kopfzeile(eintrag.ts, meta, '☁ Wettkampf'),
    status: (kopf && kopf.status) || 'beendet',
    titel: `<div class="stat-titel">🏆 ${esc((kopf && kopf.name) || 'Wettkampf')}`
      + ` <small class="rank-team">mein Ergebnis aus ${n} ${n === 1 ? 'Durchgang' : 'Durchgängen'}</small></div>`,
    rows,
    extra: quellenZeile(quellen),
    meta,
    ts: eintrag.ts,
    open: { attr: 'open-wkr', id: eintrag.wkId },
    del: delKnopf(stellvertreter, konto, 'del-wk'),
    hint: 'Antippen, um den Wettkampf zu öffnen',
  });
}

// Woher kennt das Profil dieses Ergebnis? (LizenzID, ausdrückliche Zuordnung oder beides)
function quellenZeile(quellen) {
  const liste = [...quellen];
  if (!liste.length) return '';
  return `<div class="stat-quelle">${liste.map((q) => esc(QUELLE_LABEL[q])).join(' · ')}</div>`;
}

// Geräteübergreifender Überblick (nur wenn angemeldet + online).
async function loadAccount(root, listWrap, ctx) {
  const el = root.querySelector('#stat-account');
  const meineEl = root.querySelector('#stat-meine');
  if (!el) return;

  // Beim Neuladen (nach einer Zuordnung) die lokale Liste frisch aufbauen — sonst würden
  // die remote ergänzten Karten unten ein zweites Mal angehängt.
  if (listWrap) renderLokal(listWrap, ctx);
  if (meineEl) { meineEl.innerHTML = ''; meineEl.hidden = false; }
  applyFilter(root, ctx);

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

  // Wer bin ich? Beides fließt in die Karten: das Konto entscheidet, welche Position mir
  // gehört, die LizenzID, auf welchem Weg ein Ergebnis gefunden wurde.
  try { ctx.konto = await sync.kontoId(); } catch (e) { /* offline */ }
  try { ctx.meinPass = await sync.meinePassnummer(); } catch (e) { /* egal */ }
  const hatLizenz = !!ctx.meinPass;
  if (listWrap) renderLokal(listWrap, ctx); // jetzt mit Konto-Wissen (★-Markierungen)

  // --- 0) Selbst markierte Ergebnisse abholen ---------------------------------
  // Hat man sich im Wettkampf-Hub als „das bin ich" markiert, aber ein ANDERER hat erfasst
  // (Vereins-PC), steht die eigene profil_id noch nicht an der Ergebniszeile: die RLS erlaubt
  // dem Erfasser bewusst nicht, eine fremde profil_id zu schreiben. Also holt man sie sich hier
  // selbst ab — schreibt ausschließlich das eigene Konto auf noch freie Zeilen.
  try { await sync.meineErgebnisseBeanspruchen(); } catch (e) { /* offline / alte DB */ }

  // --- 1) Meine eigenen Ergebnisse + die zugehörigen Spiele -------------------
  let meine = [];
  try { meine = await sync.pullMeineErgebnisse(); } catch (e) { /* offline */ }
  el.innerHTML = accountBox(user, meine, hatLizenz, null, ctx.meinPass);

  if (meine.length && meineEl) {
    try {
      const spiele = await sync.pullSpieleZuErgebnissen(meine);
      // Ergebniszeile je Spiel -> Position der eigenen Zeile für die Hervorhebung.
      const meineBySpiel = {};
      meine.forEach((r) => { meineBySpiel[r.spiel_id] = r; });
      const eintraege = gruppiere(spiele);

      // Die Namen der Wettkämpfe in EINER Abfrage nachziehen (die Durchgänge sind schon da).
      let koepfe = {};
      const wkIds = eintraege.filter((e) => e.kind === 'wettkampf').map((e) => e.wkId);
      if (wkIds.length) {
        try { koepfe = await sync.pullWettkampfKoepfe(wkIds); } catch (e) { /* Name ist Beiwerk */ }
      }

      const remoteById = {};
      const remoteWkById = {};
      const ergById = {};
      const cards = eintraege.map((e) => {
        if (e.kind === 'wettkampf') {
          return meinWettkampfCard(e, koepfe[e.wkId], meineBySpiel, ctx.meinPass,
            { konto: ctx.konto, wkById: remoteWkById });
        }
        const g = e.game;
        remoteById[g.id] = g;
        const r = meineBySpiel[g.remoteId];
        if (r) ergById[g.id] = [r];
        const owners = g.spielerOwners || {};
        const ichPos = Object.keys(owners).map(Number)
          .find((pos) => owners[pos] && r && owners[pos].id === r.spieler_id);
        const fremd = r && r.erfasst_von && r.erfasst_von !== user.id;
        return gameCard(g, {
          ichPos: ichPos == null ? null : ichPos,
          hinweis: fremd ? '👤 fremd erfasst' : '☁ Konto',
          konto: ctx.konto,
          // Die eigene Position ist über die Ergebniszeile bekannt — auch wenn die Zuordnung
          // allein über die LizenzID läuft und an spiel_spieler gar nichts steht.
          zuordnung: zuordnungBlock(g, {
            konto: ctx.konto, meinPass: ctx.meinPass, ergebnisse: r ? [r] : [],
            ichPos: ichPos == null ? null : ichPos,
          }),
        });
      }).filter(Boolean).join('');
      if (cards) {
        meineEl.innerHTML = `<h2 class="section-label">Meine Spiele</h2><div class="stat-list">${cards}</div>`;
        wireOpen(meineEl, remoteById);
        wireZuordnung(meineEl, {
          gameById: (id) => getGame(id) || remoteById[id] || null,
          ergebnisseFor: (g) => ergById[g.id] || [],
          konto: ctx.konto,
          onChanged: () => ctx.reload(),
        });
        wireDelete(meineEl, {
          gameById: (id) => remoteById[id] || getGame(id),
          wkById: (id) => remoteWkById[id] || getWettkampf(id),
          konto: ctx.konto,
          onDone: () => ctx.reload(),
        });
      }
      // Die Kennzahl „Spiele" zählt jetzt Einträge, nicht Durchgänge.
      el.innerHTML = accountBox(user, meine, hatLizenz, eintraege.length, ctx.meinPass);
      applyFilter(root, ctx);
    } catch (e) { /* offline / kein Zugriff */ }
  }

  // --- 2) Von diesem Konto erfasste beendete Spiele UND Wettkämpfe -----------
  try {
    // Was lokal schon liegt, wird nicht doppelt gezeigt. Lokale Objekte behalten ihre eigene
    // id und tragen die remote-id daneben — deshalb über BEIDE vergleichen.
    const lokalGames = getGames();
    const bekannt = new Set([...lokalGames.map((g) => g.id), ...lokalGames.map((g) => g.remoteId)].filter(Boolean));
    const lokalWk = getWettkaempfe();
    const bekanntWk = new Set([...lokalWk.map((w) => w.id), ...lokalWk.map((w) => w.remoteId)].filter(Boolean));

    const [remoteGames, remoteWk] = await Promise.all([
      sync.pullAccountFinishedGames(),
      sync.pullAccountFinishedWettkaempfe().catch(() => []),
    ]);
    const neu = remoteGames.filter((g) => !bekannt.has(g.id) && !bekannt.has(g.remoteId));
    const neuWk = remoteWk.filter((x) => !bekanntWk.has(x.wettkampf.id) && !bekanntWk.has(x.wettkampf.remoteId));

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

    if ((!neu.length && !neuWk.length) || !listWrap) return;
    const remoteById = {};
    const remoteWkById = {};
    neu.forEach((g) => { remoteById[g.id] = g; });
    neuWk.forEach((x) => { remoteWkById[x.wettkampf.id] = x.wettkampf; });
    const eintraege = [
      ...neu.map((g) => ({
        ts: zeitOf(g),
        html: gameCard(g, {
          hinweis: '☁ anderes Gerät',
          konto: ctx.konto,
          ichPos: ichPosVon(g, ctx.konto),
          zuordnung: schonMeins.has(g.remoteId) ? '' : zuordnungBlock(g, {
            konto: ctx.konto, meinPass: ctx.meinPass, ergebnisse: ergBySpiel[g.remoteId] || [],
          }),
        }),
      })),
      ...neuWk.map((x) => ({
        ts: zeitOf(x.wettkampf),
        html: wettkampfCard(x.wettkampf, x.games, {
          status: 'beendet', hinweis: '☁ anderes Gerät',
          ichSlot: x.wettkampf.ichSlot, openAttr: 'open-wkr', konto: ctx.konto,
        }),
      })),
    ].filter((e) => e.html).sort((a, b) => b.ts.localeCompare(a.ts));
    const cardsHtml = eintraege.map((e) => e.html).join('');
    if (!cardsHtml) return;

    let listEl = listWrap.querySelector('.stat-list');
    if (!listEl) {
      // Es gab bisher nur den Platzhalter (keine lokalen Spiele) -> echte Liste anlegen.
      listWrap.innerHTML = '<div class="stat-list"></div>';
      listEl = listWrap.querySelector('.stat-list');
    }
    listEl.insertAdjacentHTML('beforeend', cardsHtml);
    wireOpen(listWrap, remoteById);
    wireZuordnung(listWrap, {
      gameById: (id) => getGame(id) || remoteById[id] || null,
      ergebnisseFor: (g) => ergBySpiel[g.remoteId] || [],
      konto: ctx.konto,
      onChanged: () => ctx.reload(),
    });
    wireDelete(listWrap, {
      gameById: (id) => getGame(id) || remoteById[id] || null,
      wkById: (id) => getWettkampf(id) || remoteWkById[id] || null,
      konto: ctx.konto,
      onDone: () => ctx.reload(),
    });
    applyFilter(root, ctx);
  } catch (e) { /* offline / keine Berechtigung -> nur lokale Historie zeigen */ }
}
