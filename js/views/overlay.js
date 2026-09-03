// OBS-Livestream-Overlay: eine eigene, TRANSPARENTE Seite (1920×1080), die ein OBS als
// Browser-Quelle einbindet. Anordnung wie das Referenz-Layout: oben links/rechts die beiden
// Mannschaftstabellen (Spieler · W · Bahnen · Kegel · EWP) samt Logos in den Ecken, oben
// mittig die Namen + Spielpunkte, darunter mittig die Bahn-Übersicht (wer spielt gerade auf
// welcher Bahn). Der große untere Bereich bleibt FREI, damit die Kamera durchscheint.
//
// Datenzugriff read-only per ZUSCHAUER-Code (#/overlay?code=XXXX) über die anon-RPC
// wettkampf_overlay — es braucht KEIN angemeldetes Gerät, läuft also auch im (nicht
// angemeldeten) OBS-Browser auf einem anderen PC. Der Eingabe-Code wird weiterhin akzeptiert
// (alte OBS-URLs), aber die App verlinkt bewusst den Zuschauer-Code (keine Eingaben nötig).
// Aktualisiert per Polling (~2 s).
//
// Design an die App angelehnt (dunkle Flächen, Kegel-Gold, gerundete Karten). Die Schere-
// Wertung (Spielpunkte + EWP) kommt aus logic/wettkampf-wertung.js; bei Bahnarten ohne
// hinterlegte Wertung zeigt das Overlay den Kegel-Zwischenstand statt der Spielpunkte.

import { currentQuery, UNMOUNT_EVENT } from '../router.js';
import { computeWettkampfStats, durchgangStatusList } from '../logic/wettkampf.js';
import { computeWertung, assignEwp, fmtPunkte } from '../logic/wettkampf-wertung.js';
import { computeBahnState } from '../logic/bahnwechsel.js';
import { esc } from '../util.js';

const POLL_MS = 2000;
const STAGE_W = 1920;
const STAGE_H = 1080;

export function overlayView() {
  const root = document.createElement('div');
  root.className = 'ov-root';
  root.innerHTML = `<div class="ov-stage"><div class="ov-wait">Warte auf Wettkampf-Daten …</div></div>`;
  const stage = root.querySelector('.ov-stage');

  // Body UND Html transparent schalten (für die OBS-Browser-Quelle) und beim Verlassen wieder
  // zurücknehmen. WICHTIG: html trägt in der App `background: var(--bg)` (dunkel) — nur body
  // transparent zu machen reicht nicht, sonst fängt OBS den dunklen html-Hintergrund ab.
  document.documentElement.classList.add('overlay-mode');
  document.body.classList.add('overlay-mode');

  const code = (currentQuery().get('code') || '').trim();
  let timer = null;
  let alive = true;
  let sync = null;
  let lastJson = '';
  // Bahnansicht-Halten: nach dem Fertigwerden eines Durchgangs bleibt sein Stand HOLD_MS in der
  // Bahnansicht stehen, danach schaltet sie auf den Vorbereitungs-Durchgang (chooseLaneDurchgangNr).
  const HOLD_MS = 60000;
  const laneHold = { fertigNr: null, fertigSeit: 0 };

  // Stage auf die Viewport-Größe skalieren (in OBS bei 1920×1080 = Faktor 1; in der
  // Vorschau passend verkleinert), zentriert, Seitenverhältnis erhalten.
  function fit() {
    const s = Math.min(window.innerWidth / STAGE_W, window.innerHeight / STAGE_H);
    stage.style.transform = `translate(-50%, -50%) scale(${s})`;
  }

  async function tick() {
    if (!alive) return;
    try {
      if (!sync) sync = await import('../backend/sync.js');
      const data = code ? await sync.fetchOverlay(code) : null;
      if (data) paint(data);
      else if (!lastJson) stage.innerHTML = `<div class="ov-wait">${code ? 'Wettkampf nicht gefunden — Code prüfen.' : 'Kein Code in der URL (#/overlay?code=…).'}</div>`;
    } catch (e) {
      if (!lastJson) stage.innerHTML = `<div class="ov-wait">Keine Verbindung — erneuter Versuch …</div>`;
    }
    if (alive) timer = setTimeout(tick, POLL_MS);
  }

  function paint(data) {
    // Welchen Durchgang die Bahnansicht zeigt (inkl. 1-Minuten-Halten nach „Fertig") lokal
    // je Tick entscheiden — hängt an der Uhrzeit, kann daher nicht aus dem Datenschnappschuss
    // allein kommen. Fällt bei Problemen auf den Standard (laufender Durchgang) zurück.
    let laneNr;
    try {
      const { wettkampf, games } = data || {};
      if (wettkampf) {
        const stats = computeWettkampfStats(wettkampf, games || []);
        laneNr = chooseLaneDurchgangNr(wettkampf, games || [], stats, laneHold, Date.now(), HOLD_MS);
      }
    } catch (e) { /* Standard greift in buildOverlayHtml */ }
    const html = buildOverlayHtml(data, { laneNr });
    if (html === lastJson) return; // nichts geändert → DOM nicht anfassen (kein Flackern)
    lastJson = html;
    stage.innerHTML = html;
    fit();
  }

  function teardown() {
    alive = false;
    clearTimeout(timer);
    document.documentElement.classList.remove('overlay-mode');
    document.body.classList.remove('overlay-mode');
    window.removeEventListener('resize', fit);
    window.removeEventListener(UNMOUNT_EVENT, teardown);
  }

  window.addEventListener('resize', fit);
  window.addEventListener(UNMOUNT_EVENT, teardown);
  fit();
  tick();
  return root;
}

// Spieler einer Mannschaft aus der Einzel-Auswertung in Aufstellungsreihenfolge (teamPos).
function playersOfTeam(stats, teamId) {
  return stats.einzel
    .filter((p) => p.mannschaftId === teamId)
    .sort((a, b) => (a.teamPos || 99) - (b.teamPos || 99) || (a.durchgangNr || 0) - (b.durchgangNr || 0));
}

function teamTotal(players) {
  return players.reduce((s, p) => s + (p.gesamt || 0), 0);
}

// Holz eines Spielers auf einer bestimmten Bahn (Satz, der auf dieser Bahn gespielt wurde).
function laneHolz(p, n) {
  const s = (p.saetze || []).find((x) => x.bahn === n && x.holz);
  return s ? s.holz : '';
}

// Eine Team-Tabelle mit Spieler · je Bahn Holz · Kegel-Summe · EWP. Die Bahn-Spalten (Holz je
// bespielter Bahn) sind wieder da (User-Wunsch) — die Tabelle darf dadurch bis über den PiP
// reichen. side = 'l' (Heim, links) | 'r' (Gast, rechts). Die Tabelle ist gespiegelt (Name
// außen, EWP/Kegel innen), die BAHN-Nummern laufen aber auf BEIDEN Seiten 2→5 (User-Wunsch).
// withEwp: EWP-Spalte (nur bei Wertung).
function teamTable(team, players, side, withEwp, lanes) {
  // Bahn-Reihenfolge auf beiden Seiten aufsteigend (2,3,4,5) — nicht gespiegelt.
  const laneOrder = lanes;

  const rows = players.map((p) => {
    const nameCell = `<td class="ov-name">${esc(p.name || '')}</td>`;
    const laneCells = laneOrder.map((n) => `<td class="ov-c ov-lane">${laneHolz(p, n)}</td>`).join('');
    const kCell = `<td class="ov-c ov-kegel">${p.gesamt || ''}</td>`;
    const eCell = withEwp ? `<td class="ov-c ov-ewp">${p.ewp != null ? p.ewp : ''}</td>` : '';
    const cells = side === 'l' ? nameCell + laneCells + kCell + eCell : eCell + kCell + laneCells + nameCell;
    return `<tr class="ov-row${(p.status === 'laufend') ? ' is-live' : ''}">${cells}</tr>`;
  }).join('');

  const ewpHead = withEwp ? '<th class="ov-ewp-h">EWP</th>' : '';
  const laneHead = laneOrder.map((n) => `<th class="ov-lane-h">${n}</th>`).join('');
  const head = side === 'l'
    ? `<th class="ov-name-h">Spieler</th>${laneHead}<th>Kegel</th>${ewpHead}`
    : `${ewpHead}<th>Kegel</th>${laneHead}<th class="ov-name-h">Spieler</th>`;

  // Gesamt-Zeile: KEIN Gesamtholz je Bahn mehr (User-Wunsch) — nur Kegel- und EWP-Summe.
  // Die Bahn-Spalten bleiben leer, damit die Spaltenbreiten mit Kopf/Körper übereinstimmen.
  const total = teamTotal(players);
  const laneTotCells = laneOrder.map(() => '<td class="ov-c ov-lane"></td>').join('');
  const ewpTot = withEwp ? players.reduce((s, p) => s + (p.ewp || 0), 0) : 0;
  const totEwpCell = withEwp ? `<td class="ov-c ov-ewp ov-total-val">${ewpTot}</td>` : '';
  const totalRow = side === 'l'
    ? `<td class="ov-name ov-total-lbl">Gesamt</td>${laneTotCells}<td class="ov-c ov-kegel ov-total-val">${total}</td>${totEwpCell}`
    : `${totEwpCell}<td class="ov-c ov-kegel ov-total-val">${total}</td>${laneTotCells}<td class="ov-name ov-total-lbl">Gesamt</td>`;

  return `
    <table class="ov-table ov-${side}">
      <thead><tr>${head}</tr></thead>
      <tbody>${rows}</tbody>
      <tfoot><tr class="ov-total">${totalRow}</tr></tfoot>
    </table>`;
}

function logoBox(team, side) {
  const src = team && team.logo;
  // Logo-Hintergrund pro Mannschaft wählbar: hell oder dunkel (Default dunkel).
  const bg = team && team.logoBg === 'light' ? ' is-light' : '';
  return `<div class="ov-logo ov-logo-${side}${bg}">${src ? `<img src="${esc(src)}" alt="">` : ''}</div>`;
}

// Akzentfarbe einer Mannschaft (für die Akzentschriften/Ränder im Overlay). Kommt aus der
// Team-Config und wird streng validiert (#rrggbb), damit sie sicher in ein inline `style`
// darf; sonst der bisherige Kegel-Gold-Ton.
const OV_ACCENT_DEFAULT = '#f5a623';
function teamAccent(team) {
  const c = team && team.accent;
  return /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : OV_ACCENT_DEFAULT;
}

// Kopfzeile über einer Team-Tabelle (außen): Teamname + Spielstand. Mit hinterlegter Wertung
// (Schere) sind das die Spielpunkte, sonst der Kegel-Zwischenstand des Teams. teamKey =
// 'home' | 'away' (für die Wertung), side = 'l' | 'r' (Ausrichtung/Reihenfolge).
function teamHeader(team, players, wertung, teamKey, side) {
  const hasW = !!wertung;
  const val = hasW ? fmtPunkte(wertung[teamKey].spielpunkte) : teamTotal(players);
  const lbl = hasW ? 'Punkte' : 'Kegel';
  const name = `<span class="ov-th-name">${esc(team.name || '')}</span>`;
  const score = `<span class="ov-th-score"><span class="ov-th-pts">${val}</span><span class="ov-th-lbl">${lbl}</span></span>`;
  const inner = side === 'l' ? name + score : score + name;
  return `<div class="ov-team-head ov-team-head-${side}">${inner}</div>`;
}

// Aktuellen (laufenden) Durchgang wählen: der zuletzt begonnene Durchgang mit Würfen; sonst
// der erste vorhandene. So zeigt die Bahn-Übersicht die gerade aktive Paarung.
function liveDurchgangNr(stats) {
  const nrs = [...new Set(stats.einzel.map((p) => p.durchgangNr).filter((n) => n != null))];
  if (!nrs.length) return null;
  const active = nrs.filter((n) => stats.einzel.some((p) => p.durchgangNr === n && (p.wurfCount || 0) > 0));
  return (active.length ? Math.max(...active) : Math.min(...nrs));
}

// Physische Bahn-Belegung EINES Durchgang-Spiels — exakt wie in der Wurferfassung
// (spiel-laufend.js): jeder Spieler steht auf der Bahn seines aktuell gespielten Satzes und
// rückt erst vor, wenn sein Satz fertig ist UND die nächste Bahn frei ist (Bahnwechsel-Gating).
// Wartende Spieler bleiben also auf ihrer alten Bahn. Rückgabe: Array je Spieler-Index
// { pos, lane, waiting, fertig } oder null (Spiel ohne Config).
function bahnStateOfGame(game) {
  const c = game && game.config;
  if (!c || !Array.isArray(c.spielerListe)) return null;
  const bloecke = (game.erfassung && game.erfassung.bloecke) || [];
  const laneOf = (sp, st) => c.bahnplan?.[sp]?.[st] ?? (c.ersteBahn + st);
  const doneMatrix = c.spielerListe.map((_, sp) =>
    Array.from({ length: c.saetze }, (_, st) => !!(bloecke[sp] && bloecke[sp][st] && bloecke[sp][st].done)));
  return computeBahnState({ n: c.spielerListe.length, saetze: c.saetze, doneMatrix, laneOf });
}

// Bespielte Bahnnummern eines Spiels (frei gewählte Liste oder fortlaufender Bereich) —
// wie gameLanes() in der Wurferfassung.
function lanesOfGame(c) {
  return Array.isArray(c.bahnListe) && c.bahnListe.length
    ? c.bahnListe.slice().sort((a, b) => a - b)
    : Array.from({ length: c.bahnen }, (_, i) => c.ersteBahn + i);
}

// Bahn-Übersicht (Mitte, über dem PiP): je Bahn EINE Kachel mit dem Spieler, der dort gerade
// steht — mit DERSELBEN Rotation wie die Spieleingabe (physische Bahn aus computeBahnState,
// inkl. Warten auf den Bahnwechsel). Team-Zugehörigkeit als farbiger Rand, freie Bahnen ohne
// Kachel. Zeigt den laufenden Durchgang.
function lanePanels(nr, stats, homeId, awayId, games, homeAccent, awayAccent) {
  if (nr == null) return '';
  const inDg = stats.einzel.filter((p) => p.durchgangNr === nr);
  if (!inDg.length) return '';
  const game = (games || []).find((g) => g.id === inDg[0].gameId);
  const bs = game ? bahnStateOfGame(game) : null;
  if (!bs || !game.config) return '';

  // Spieler-Index -> Auswertungs-Eintrag (Name, Gesamt, Team) des Durchgangs.
  const byIndex = {};
  inDg.forEach((p) => { if (p.index != null) byIndex[p.index] = p; });
  // Physische Belegung: Bahn -> Spieler-Index (genau wie belegung[s.lane] = sp in der Eingabe).
  const belegung = {};
  bs.forEach((s, sp) => { belegung[s.lane] = sp; });

  const cards = lanesOfGame(game.config).map((n) => {
    const sp = belegung[n];
    if (sp == null) return '';                 // freie Bahn -> keine Kachel
    const p = byIndex[sp];
    if (!p) return '';
    const teamCls = p.mannschaftId === homeId ? 'is-home' : 'is-away';
    const accent = p.mannschaftId === homeId ? homeAccent : awayAccent;
    const waitCls = bs[sp].waiting ? ' is-waiting' : '';
    return `
      <div class="ov-lane-card ${teamCls}${waitCls}" style="--ov-accent:${accent}">
        <span class="ov-lane-no">Bahn ${n}</span>
        <span class="ov-lane-row">
          <span class="ov-lane-nm">${esc(p.name || '')}</span>
          <span class="ov-lane-pins">${p.gesamt || ''}</span>
        </span>
      </div>`;
  }).join('');
  if (!cards.trim()) return '';
  return `<div class="ov-lanes">${cards}</div>`;
}

// Welchen Durchgang die Bahnansicht (ov-lanes) zeigt. Normalfall: der laufende Durchgang
// (liveDurchgangNr). Ist dieser fertig, bleibt sein Stand noch `holdMs` (Standard 60 s) stehen
// und schaltet danach auf den Vorbereitungs-Durchgang (den nächsten, der startet) — so sieht der
// Stream nach dem Durchgang kurz das Endergebnis und dann die kommende Paarung auf den Bahnen.
// `state` ({ fertigNr, fertigSeit }) hält den Fertig-Beginn über die Poll-Ticks und wird hier
// aktualisiert. Startet der nächste Durchgang von selbst (Würfe), greift wieder liveDurchgangNr.
export function chooseLaneDurchgangNr(wettkampf, games, stats, state, now, holdMs = 60000) {
  const liveNr = liveDurchgangNr(stats);
  const statusList = durchgangStatusList(wettkampf, games || []);
  const statusByNr = {};
  statusList.forEach((d) => { statusByNr[d.nr] = d.status; });
  const vorb = statusList.find((d) => d.status === 'vorbereitung');
  const vorbereitungNr = vorb ? vorb.nr : null;

  const liveFertig = liveNr != null && statusByNr[liveNr] === 'fertig';
  if (liveFertig) {
    if (state.fertigNr !== liveNr) { state.fertigNr = liveNr; state.fertigSeit = now; }
    if (vorbereitungNr != null && (now - state.fertigSeit) >= holdMs) return vorbereitungNr;
    return liveNr;
  }
  state.fertigNr = null;
  state.fertigSeit = 0;
  return liveNr != null ? liveNr : vorbereitungNr;
}

// Reine Render-Funktion: aus { wettkampf, games } (wie fetchOverlay sie liefert) den
// Overlay-HTML-String bauen. Exportiert, damit sie ohne Netz/DOM getestet/vorschaubar ist.
// `opts.laneNr` erzwingt den in der Bahnansicht gezeigten Durchgang (siehe chooseLaneDurchgangNr);
// ohne Angabe wird der laufende Durchgang gezeigt.
export function buildOverlayHtml(data, opts) {
  const { wettkampf, games } = data || {};
  if (!wettkampf) return `<div class="ov-wait">Warte auf Wettkampf-Daten …</div>`;
  const stats = computeWettkampfStats(wettkampf, games || []);
  const wertung = computeWertung(wettkampf, stats, games || []); // setzt EWP auf stats.einzel (Schere)
  // Für die Anzeige die EWP auf die volle Feldgröße skalieren (bester = Spieler je Mannschaft ×
  // Anzahl Mannschaften, von oben heruntergezählt) — wie im Wettkampf-Hub. Die in `wertung`
  // gespeicherten Spielpunkte bleiben unberührt (dort wurde bereits gerechnet).
  if (wertung) {
    const feldGroesse = (wettkampf.spielerJeMannschaft || 0) * (wettkampf.mannschaften || []).length;
    assignEwp(stats.einzel, (wettkampf.mannschaften || [])[0]?.id,
      wettkampf.wertung?.ewp?.minHolz ?? 1, feldGroesse);
  }
  const laneNr = opts && opts.laneNr !== undefined ? opts.laneNr : liveDurchgangNr(stats);
  return template(wettkampf, stats, wertung, games || [], laneNr);
}

function template(wettkampf, stats, wertung, games, laneNr) {
  const teams = wettkampf.mannschaften || [];
  if (teams.length < 2) {
    return `<div class="ov-wait">Wettkampf braucht zwei Mannschaften für das Overlay.</div>`;
  }
  const home = teams[0];
  const away = teams[1];
  const pHome = playersOfTeam(stats, home.id);
  const pAway = playersOfTeam(stats, away.id);
  const withEwp = !!wertung;
  const lanes = (wettkampf.playedLanes || []).slice().sort((a, b) => a - b);
  const homeAccent = teamAccent(home);
  const awayAccent = teamAccent(away);

  // Anordnung wie die Referenz: AUSSEN je Mannschaftstabelle mit Kopfzeile (Teamname +
  // Spielstand) darüber und Logo darunter; die MITTE zeigt nur die gerade laufende Bahn-
  // Paarung. Alles bleibt ein schmales oberes Band, damit die Nahansicht der Bahnen frei bleibt.
  return `
    <div class="ov-bar">
      <div class="ov-side ov-side-l" style="--ov-accent:${homeAccent}">
        ${teamHeader(home, pHome, wertung, 'home', 'l')}
        ${teamTable(home, pHome, 'l', withEwp, lanes)}
        ${logoBox(home, 'l')}
      </div>
      <div class="ov-center">
        ${lanePanels(laneNr, stats, home.id, away.id, games, homeAccent, awayAccent)}
      </div>
      <div class="ov-side ov-side-r" style="--ov-accent:${awayAccent}">
        ${teamHeader(away, pAway, wertung, 'away', 'r')}
        ${teamTable(away, pAway, 'r', withEwp, lanes)}
        ${logoBox(away, 'r')}
      </div>
    </div>`;
}
