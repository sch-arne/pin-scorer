// Gemeinsames Sportwinner-Konflikt-Panel für Wettkampf-Hub UND laufendes Spiel.
// Der Controller hält die offenen (noch nicht entschiedenen) Konflikte, zeichnet das Panel in
// seinen Container und ruft für jede Entscheidung die vom View gelieferten Hooks (Persistenz/Push).
//
// Der View treibt das Polling: er holt den Sportwinner-Live-Stand (holeSportwinnerLive) und ruft
// `update(swLive)`. Für das Rückschreiben liefert `activeKeys()` die Zellen, die eingefroren
// bleiben, bis der Nutzer entschieden hat (an buildSportwinnerPush({ excludeKeys }) übergeben).

import { buildKonflikte, adoptErgebnisBlock } from '../logic/sportwinner-konflikte.js';
import { esc } from '../util.js';

const swSig = (v) => `${v.volle}/${v.abr}/${v.fehler}`;
const sigOf = (k, isErg) => (isErg ? swSig(k.sw) : String(k.sw.pass));

// hooks:
//   getData()                     -> { wettkampf, games }  (frisch aus dem Store)
//   onAdoptErgebnis(konflikt, block)  App-Satz auf die SW-Summen setzen + persistieren
//   onKeepErgebnis(konflikt)          App behalten -> nach Sportwinner schreiben (View pusht)
//   onAdoptAufstellung(konflikt)      Name/Pass aus Sportwinner übernehmen + persistieren
//   onKeepAufstellung?(konflikt)      App behalten (Aufstellung) -> nur bestätigen (optional)
export function createKonfliktPanel(container, hooks) {
  // container darf ein Element ODER eine Funktion sein, die es liefert (der View rendert neu
  // und tauscht dabei den Container aus — dann muss er bei jedem paint() frisch geholt werden).
  const getBox = typeof container === 'function' ? container : () => container;
  let konflikte = { ergebnis: [], aufstellung: [] };
  const resolvedSig = new Map(); // key -> Signatur des SW-Werts, für den entschieden wurde

  function activeKeys() {
    return new Set(konflikte.ergebnis.map((k) => k.key));
  }
  function anzahl() {
    return konflikte.ergebnis.length + konflikte.aufstellung.length;
  }

  function update(swLive) {
    const { wettkampf, games } = hooks.getData() || {};
    if (!wettkampf || !wettkampf.sportwinner || !swLive) {
      konflikte = { ergebnis: [], aufstellung: [] };
      paint();
      return;
    }
    const all = buildKonflikte(wettkampf, games, swLive);
    konflikte = {
      ergebnis: all.ergebnis.filter((k) => resolvedSig.get(k.key) !== sigOf(k, true)),
      aufstellung: all.aufstellung.filter((k) => resolvedSig.get(k.key) !== sigOf(k, false)),
    };
    paint();
  }

  function resolveErg(key, decision) {
    const k = konflikte.ergebnis.find((x) => x.key === key);
    if (!k) return;
    resolvedSig.set(k.key, sigOf(k, true));
    // Zuerst aus der Liste nehmen: dann friert activeKeys() diese Zelle NICHT mehr ein, sodass
    // „App behalten" sie beim anschliessenden Push tatsächlich nach Sportwinner schreibt.
    konflikte.ergebnis = konflikte.ergebnis.filter((x) => x.key !== key);
    if (decision === 'sw') {
      const { games } = hooks.getData() || {};
      const g = (games || []).find((x) => x.id === k.gameId);
      if (g) hooks.onAdoptErgebnis(k, adoptErgebnisBlock(g.config, k.sw));
    } else if (hooks.onKeepErgebnis) {
      hooks.onKeepErgebnis(k);
    }
    paint();
  }

  function resolveAuf(key, decision) {
    const k = konflikte.aufstellung.find((x) => x.key === key);
    if (!k) return;
    resolvedSig.set(k.key, sigOf(k, false));
    konflikte.aufstellung = konflikte.aufstellung.filter((x) => x.key !== key);
    if (decision === 'sw') hooks.onAdoptAufstellung(k);
    else if (hooks.onKeepAufstellung) hooks.onKeepAufstellung(k);
    paint();
  }

  function resolveAlle(decision) {
    konflikte.ergebnis.slice().forEach((k) => resolveErg(k.key, decision));
    konflikte.aufstellung.slice().forEach((k) => resolveAuf(k.key, decision));
  }

  function paint() {
    const container = getBox();
    if (!container) return;
    if (!anzahl()) { container.innerHTML = ''; return; }
    const ergZeile = (k) => `
      <div class="swk-row">
        <div class="swk-info">
          <span class="swk-name">${esc(k.spielerName || 'Spieler')}</span>
          <span class="swk-detail">Bahn ${k.bahnNummer != null ? k.bahnNummer : k.bahn + 1} · Satz ${k.satz + 1}</span>
          <span class="swk-vs"><b>App</b> ${k.app.volle}+${k.app.abr}${k.app.fehler ? ` (${k.app.fehler}F)` : ''}
            ↔ <b>Sportwinner</b> ${k.sw.volle}+${k.sw.abr}${k.sw.fehler ? ` (${k.sw.fehler}F)` : ''}</span>
        </div>
        <div class="swk-actions">
          <button type="button" class="swk-btn" data-erg-app="${esc(k.key)}">App behalten</button>
          <button type="button" class="swk-btn is-sw" data-erg-sw="${esc(k.key)}">Sportwinner übernehmen</button>
        </div>
      </div>`;
    const aufZeile = (k) => `
      <div class="swk-row">
        <div class="swk-info">
          <span class="swk-name">Slot ${k.slot + 1} · Aufstellung</span>
          <span class="swk-vs"><b>App</b> ${esc(k.app.name || '—')} (${esc(k.app.pass || '—')})
            ↔ <b>Sportwinner</b> ${esc(k.sw.name || '—')} (${esc(k.sw.pass || '—')})</span>
        </div>
        <div class="swk-actions">
          <button type="button" class="swk-btn" data-auf-app="${esc(k.key)}">App behalten</button>
          <button type="button" class="swk-btn is-sw" data-auf-sw="${esc(k.key)}">Sportwinner übernehmen</button>
        </div>
      </div>`;
    container.innerHTML = `
      <div class="swk-panel">
        <div class="swk-head">
          <span class="swk-title">⚠ ${anzahl()} Sportwinner-${anzahl() === 1 ? 'Abweichung' : 'Abweichungen'}</span>
          <span class="swk-bulk">
            <button type="button" class="swk-btn" data-all-app>Alle: App</button>
            <button type="button" class="swk-btn is-sw" data-all-sw>Alle: Sportwinner</button>
          </span>
        </div>
        ${konflikte.ergebnis.map(ergZeile).join('')}
        ${konflikte.aufstellung.map(aufZeile).join('')}
      </div>`;
    container.querySelectorAll('[data-erg-app]').forEach((b) => b.addEventListener('click', () => resolveErg(b.dataset.ergApp, 'app')));
    container.querySelectorAll('[data-erg-sw]').forEach((b) => b.addEventListener('click', () => resolveErg(b.dataset.ergSw, 'sw')));
    container.querySelectorAll('[data-auf-app]').forEach((b) => b.addEventListener('click', () => resolveAuf(b.dataset.aufApp, 'app')));
    container.querySelectorAll('[data-auf-sw]').forEach((b) => b.addEventListener('click', () => resolveAuf(b.dataset.aufSw, 'sw')));
    const allApp = container.querySelector('[data-all-app]');
    if (allApp) allApp.addEventListener('click', () => resolveAlle('app'));
    const allSw = container.querySelector('[data-all-sw]');
    if (allSw) allSw.addEventListener('click', () => resolveAlle('sw'));
  }

  return { update, activeKeys, anzahl, paint };
}
