// Wurferfassung fuer "Sportkegeln-Training".
//
// Uebernommen aus dem alten VOK-Scoreboard (public/wuerfe.js), angepasst auf das
// neue Modell Saetze -> Teilsaetze (statt fix "4 Bahnen a 30 Wuerfe, Volle/Abraeumen"):
//   - Pin-Numpad 0-9 je Wurf
//   - Einzelwurf-Chips, antippen -> Korrektur (ueberschreiben / loeschen)
//   - Rueckgaengig (letzter Wurf)
//   - Untersummen je TEILSATZ mit Modus-Label + Wurfzaehler (X/Soll)
//   - Teilsatz-Summe manuell setzen (Override statt Einzelwuerfe)
//   - Mismatch-Warnung (Teilsatz gilt als fertig, hat aber != Soll-Wuerfe)
//   - Holz je Satz = Summe Teilsaetze; Spieler-Gesamt ueber alle Saetze
//   - Satz-Status pending/live/done, Bahn je Satz aus bahnplan

import { getActiveGame, getGame, saveErfassung } from '../store.js';
import { esc } from '../util.js';
import { teilsatzRanges } from '../logic/teilsaetze.js';
import {
  fullPins, isAbraeumMode, rangeOfThrow, defaultKegel,
  abraeumScan, abraeumStateBefore, volleKranz,
} from '../logic/abraeumen.js';
import { teilsatzStats, satzHolz, satzStatus } from '../logic/holz.js';
import { computeBahnState as computeBahnStatePure } from '../logic/bahnwechsel.js';

const MODUS_LABEL = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz-Abräumen' };
const BW_LABEL = { plus1: 'Reihum (+1)', minus1: 'Reihum (−1)', classic: 'Classic-Duo', bohle: 'Bohle-Duo', fest: 'Feste Bahn' };

// Kegel-Anordnung als Raute (Nummerierung wie auf der Bahn), Position im 5x5-Raster.
//        9
//     7     8
//  4     5     6
//     2     3
//        1
const KEGEL_LAYOUT = [
  { n: 9, r: 1, c: 3 },
  { n: 7, r: 2, c: 2 }, { n: 8, r: 2, c: 4 },
  { n: 4, r: 3, c: 1 }, { n: 5, r: 3, c: 3 }, { n: 6, r: 3, c: 5 },
  { n: 2, r: 4, c: 2 }, { n: 3, r: 4, c: 4 },
  { n: 1, r: 5, c: 3 },
];

// ── Modell-Helfer ─────────────────────────────────────────────────────────

// Frischer Erfassungsstand: je Spieler ein Array von Saetzen, je Satz ein Block.
function initErfassung(c) {
  return {
    aktiverSpieler: 0,
    aktiverSatz: 0,
    bloecke: c.spielerListe.map(() =>
      Array.from({ length: c.saetze }, () => ({
        wuerfe: [],
        kegel: [], // je Wurf ein Array der gefallenen Kegel-Nummern (1-9)
        koenig: [], // je Wurf: König (5) steht danach noch? (nur Kranz-Abräumen, per Langdruck)
        overrides: c.teilsaetze.map(() => null),
        done: false,
      }))),
  };
}

// Bestehenden Stand an die aktuelle Konfiguration angleichen (robust gegen Aenderungen).
function normalizeErfassung(e, c) {
  const base = initErfassung(c);
  if (!e || !Array.isArray(e.bloecke)) return base;
  base.aktiverSpieler = Math.min(e.aktiverSpieler || 0, c.spielerListe.length - 1);
  base.aktiverSatz = Math.min(e.aktiverSatz || 0, c.saetze - 1);
  base.bloecke = base.bloecke.map((satzArr, sp) => satzArr.map((blk, st) => {
    const old = e.bloecke[sp] && e.bloecke[sp][st];
    if (!old) return blk;
    const wuerfe = Array.isArray(old.wuerfe) ? old.wuerfe.slice(0, c.wuerfeProSatz) : [];
    const oldKegel = Array.isArray(old.kegel) ? old.kegel : [];
    const oldKoenig = Array.isArray(old.koenig) ? old.koenig : [];
    return {
      wuerfe,
      kegel: wuerfe.map((w, k) => {
        const ok = oldKegel[k];
        if (Array.isArray(ok)) return ok.slice();
        if (ok === null) return null;        // "unbestimmt" bewahren
        return defaultKegel(w);              // fehlend -> aus Holzzahl ableiten
      }),
      koenig: wuerfe.map((_, k) => !!oldKoenig[k]),
      overrides: c.teilsaetze.map((_, i) => (old.overrides && old.overrides[i] != null ? old.overrides[i] : null)),
      done: !!old.done,
    };
  }));
  return base;
}

// ── View ──────────────────────────────────────────────────────────────────

export function spielLaufendView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  const gameId = getActiveGame();
  const game = getGame(gameId);
  if (!game) {
    root.innerHTML = `
      <header class="page-header">
        <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
        <h1 class="page-title">Kein Spiel</h1>
      </header>
      <div class="placeholder"><p class="placeholder-text">Kein aktives Spiel gefunden.</p></div>`;
    return root;
  }

  const c = game.config;
  const ranges = teilsatzRanges(c);
  const state = normalizeErfassung(game.erfassung, c);
  let editIdx = null; // lokaler Korrektur-Index (nicht persistiert)
  let pinMode = 'gefallen'; // 'gefallen' | 'stehend' — welche Seite die Kegel-Raute erfasst
  let lpSuppress = 0; // Zeitstempel: unterdrückt den Klick direkt nach einem Langdruck (König)
  let settingsOpen = false; // Einstellungsmenü (⚙) offen? — enthält u.a. die Spiel-Details
  let laneSettingsOpen = false; // Bahneinstellung (⚙ in der Satz-Kopfzeile) offen?
  let overrideTs = null; // Teilsatz-Index, dessen Summe-Sheet offen ist (null = zu)
  let overrideDraft = ''; // im Override-Sheet eingetippte Ziffern

  function persist() {
    if (saveErfassung(gameId, state) === null) toast('Speichern fehlgeschlagen — Speicher voll?');
  }
  function block(sp, st) { return state.bloecke[sp][st]; }
  function current() { return block(state.aktiverSpieler, state.aktiverSatz); }
  function laneOf(sp, st) { return c.bahnplan?.[sp]?.[st] ?? (c.ersteBahn + st); }
  function playerName(sp) { return c.spielerListe[sp].name || ('Spieler ' + (sp + 1)); }
  function playerTotal(sp) { return state.bloecke[sp].reduce((s, blk) => s + satzHolz(blk, ranges), 0); }

  // Kontext eines (geplanten oder bestehenden) Wurfs an absolutem Index `idx`:
  // Beim Abräumen/Kranz-Abräumen nur die stehenden Kegel wählbar, Numpad auf deren
  // Anzahl gedeckelt. Bei Volle: alle 9, keine Deckelung.
  function throwContext(blk, idx) {
    const r = rangeOfThrow(ranges, idx);
    if (!r || !isAbraeumMode(r.modus)) {
      return { abraeum: false, kranz: false, modus: r ? r.modus : null, universe: fullPins(), exact: true, maxPins: 9, koenig: false, picked: false };
    }
    const st = abraeumStateBefore(blk, r, idx);
    return {
      abraeum: true,
      kranz: r.modus === 'kranz-abraeumen',
      modus: r.modus,
      universe: st.exact ? st.standing : fullPins(), // unbekannt -> alle erlauben (nur count deckelt)
      exact: st.exact,
      maxPins: st.count,                             // zuverlässig, auch wenn Menge unbekannt
      koenig: st.koenig,                             // steht der König vor diesem Wurf noch?
      picked: st.picked,                             // schon konkrete Kegel im Board gewählt?
    };
  }

  // Standard-Kegelbelegung fuer einen Wurf, kontextabhaengig: beim Abräumen ist
  // "alle" = alle STEHENDEN Kegel (nicht zwingend 9).
  function defaultKegelFor(blk, idx, pins) {
    const ctx = throwContext(blk, idx);
    if (!ctx.abraeum) return defaultKegel(pins);
    if (pins <= 0) return [];
    if (pins >= ctx.universe.length) return ctx.universe.slice();
    return null;
  }

  // Bahn-Belegung mit Bahnwechsel-Gating — dünner Wrapper um die reine Logik in
  // logic/bahnwechsel.js. Übergibt die done-Matrix und die Bahn-Zuordnung; alles Weitere
  // (Warten, Duo-Tausch, Fixpunkt) steckt dort und ist per Unit-Test abgesichert.
  function computeBahnState() {
    return computeBahnStatePure({
      n: c.spielerListe.length,
      saetze: c.saetze,
      doneMatrix: state.bloecke.map((arr) => arr.map((b) => b.done)),
      laneOf,
    });
  }

  // Der aktuell "laufende" Satz des aktiven Spielers = erster noch nicht fertiger Satz.
  // Würfe gehören immer nur in diesen einen Satz; erfasst man in einem NEUEREN Satz, ist
  // ein früherer noch offen — dann fragt der Satz-Wechsel-Dialog nach.
  function frontSatz() {
    const arr = state.bloecke[state.aktiverSpieler];
    const i = arr.findIndex((b) => !b.done);
    return i < 0 ? arr.length - 1 : i;
  }

  // Bei Spielerwechsel ersten offenen Satz waehlen (wie im alten Projekt).
  function firstOpenSatz(sp) {
    const arr = state.bloecke[sp];
    const live = arr.findIndex((b) => satzStatus(b) === 'live');
    if (live >= 0) return live;
    const open = arr.findIndex((b) => satzStatus(b) === 'pending');
    return open >= 0 ? open : 0;
  }

  function selectPlayer(sp) {
    state.aktiverSpieler = sp;
    state.aktiverSatz = firstOpenSatz(sp);
    editIdx = null;
    persist(); render();
  }
  function selectSatz(st) { state.aktiverSatz = st; editIdx = null; persist(); render(); }

  // koenigFlag (nur Kranz, per Langdruck): der Wurf fällt N Kranz-Kegel, der König (5)
  // bleibt stehen. Genaue Kranz-Kegel bleiben offen (kegel=null), gespeichert wird nur,
  // DASS der König danach noch steht (blk.koenig[idx]=true).
  function addWurf(pins, koenigFlag = false) {
    const blk = current();
    if (!Array.isArray(blk.koenig)) blk.koenig = blk.wuerfe.map(() => false);
    if (editIdx !== null) {
      if (editIdx < blk.wuerfe.length) {
        const ctx = throwContext(blk, editIdx);
        const cap = koenigFlag ? ctx.maxPins - 1 : ctx.maxPins;
        if (ctx.abraeum && pins > cap) { toast(`Es stehen nur ${cap} ${koenigFlag ? 'Kranz-' : ''}Kegel`); return; }
        blk.wuerfe[editIdx] = pins;
        blk.kegel[editIdx] = koenigFlag ? null : defaultKegelFor(blk, editIdx, pins);
        blk.koenig[editIdx] = koenigFlag;
      }
      const idx = editIdx;
      editIdx = null; persist(); render();
      toast(koenigFlag ? `Wurf #${idx + 1} korrigiert · König steht` : `Wurf #${idx + 1} korrigiert`); return;
    }
    if (blk.done) { toast('Satz ist fertig'); return; }
    if (blk.wuerfe.length >= c.wuerfeProSatz) { toast('Satz voll — alle Würfe erfasst'); return; }
    // In einen späteren Satz eintragen ist gesperrt, solange ein früherer noch offen ist.
    const front = frontSatz();
    if (state.aktiverSatz > front) { toast(`Erst Satz ${front + 1} abschließen`); return; }
    // Ein Spieler kann maximal auf EINEN Bahnwechsel warten: steht der Wechsel nach einem
    // fertigen Satz noch aus (physisch noch auf der alten Bahn), darf der nächste Satz noch
    // nicht bespielt werden. Sonst würde man einen zweiten Bahnwechsel „vorziehen".
    if (state.aktiverSatz > computeBahnState()[state.aktiverSpieler].pos) {
      toast('Erst Bahnwechsel abwarten'); return;
    }
    const idx = blk.wuerfe.length;
    const ctx = throwContext(blk, idx);
    const cap = koenigFlag ? ctx.maxPins - 1 : ctx.maxPins;
    if (ctx.abraeum && pins > cap) { toast(`Es stehen nur ${cap} ${koenigFlag ? 'Kranz-' : ''}Kegel`); return; }
    blk.wuerfe.push(pins);
    blk.kegel.push(koenigFlag ? null : defaultKegelFor(blk, idx, pins));
    blk.koenig.push(koenigFlag);
    persist(); render();
    if (koenigFlag) toast('König bleibt stehen');
  }

  function setPinMode(mode) {
    if (pinMode === mode) return;
    pinMode = mode;
    render();
  }

  // Kegel p (1-9) fuer den Ziel-Wurf antippen. Der Ziffernblock gibt die Holzzahl N vor.
  // Gefallener Kegel LEUCHTET, stehender ist aus. F = gefallene (leuchtende) Kegel.
  //   "gefallen": Grundzustand alle aus, die N gefallenen einschalten.
  //   "stehend":  Grundzustand alle an (alle gefallen), die 9-N stehenden ausschalten.
  function tapPin(p) {
    const blk = current();
    const k = pinTarget();
    if (k < 0) { toast('Erst einen Wurf eintragen'); return; }
    if (blk.done) { toast('Satz ist fertig'); return; }
    const n = blk.wuerfe[k];
    const ctx = throwContext(blk, k);
    const U = ctx.universe;         // wählbare Kegel (beim Abräumen nur die stehenden)
    const Usize = U.length;
    // Beim Abräumen: schon zuvor gefallene Kegel sind nicht mehr wählbar.
    if (ctx.abraeum && ctx.exact && !U.includes(p)) { toast(`Kegel ${p} stand nicht mehr`); return; }
    // Unbestimmt -> je nach Modus materialisieren (gefallen: keiner an; stehend: alle wählbaren an).
    if (blk.kegel[k] == null) {
      blk.kegel[k] = pinMode === 'stehend' ? U.slice() : [];
    }
    // Exakte Kegel-Angabe übernimmt: der „König-count-only"-Marker (Langdruck) entfällt.
    if (Array.isArray(blk.koenig)) blk.koenig[k] = false;
    const F = blk.kegel[k];
    const pos = F.indexOf(p);

    if (pinMode === 'gefallen') {
      if (pos >= 0) F.splice(pos, 1);                                   // aus
      else if (F.length >= n) { toast(`Nur ${n} Kegel gefallen — schon alle gewählt`); return; }
      else { F.push(p); F.sort((a, b) => a - b); }                      // an (gefallen)
    } else { // stehend: getippten Kegel ausschalten (= steht), Rest leuchtet weiter
      if (pos >= 0) {                                                   // leuchtet -> ausschalten (steht)
        if (F.length <= n) { toast(`Nur ${Usize - n} Kegel stehen — schon alle gewählt`); return; }
        F.splice(pos, 1);
      } else { F.push(p); F.sort((a, b) => a - b); }                    // wieder an (doch gefallen)
    }
    persist(); render();
  }

  // Ziel-Wurf fuer die Kegel-Erfassung: der in Korrektur gewaehlte, sonst der letzte Wurf.
  function pinTarget() {
    const blk = current();
    if (editIdx !== null && editIdx < blk.wuerfe.length) return editIdx;
    return blk.wuerfe.length - 1;
  }

  function undo() {
    const blk = current();
    if (blk.wuerfe.length === 0) { toast('Nichts rückgängig zu machen'); return; }
    blk.wuerfe.pop();
    blk.kegel.pop();
    if (Array.isArray(blk.koenig)) blk.koenig.pop();
    persist(); render();
  }

  function deleteEditing() {
    const blk = current();
    if (editIdx === null || editIdx >= blk.wuerfe.length) return;
    blk.wuerfe.splice(editIdx, 1);
    blk.kegel.splice(editIdx, 1);
    if (Array.isArray(blk.koenig)) blk.koenig.splice(editIdx, 1);
    editIdx = null; persist(); render();
    toast('Wurf gelöscht');
  }

  // Aktuellen Satz beenden / wieder öffnen (aus der Bahneinstellung).
  function toggleDone() {
    const blk = current();
    // Beenden eines Satzes, den man physisch noch nicht bespielt (Bahnwechsel steht
    // aus), würde einen zweiten Bahnwechsel vorziehen — gesperrt. Wieder-Öffnen bleibt erlaubt.
    if (!blk.done && state.aktiverSatz > computeBahnState()[state.aktiverSpieler].pos) {
      toast('Erst Bahnwechsel abwarten'); return;
    }
    blk.done = !blk.done;
    laneSettingsOpen = false;
    persist(); render();
    toast(blk.done ? 'Satz beendet' : 'Satz wieder geöffnet');
  }

  // Ganzes Spiel für DIESEN Spieler beenden: alle offenen Sätze auf fertig setzen (Bahn
  // wird frei für den Bahnwechsel). Sind bereits alle fertig, öffnet die Aktion sie wieder.
  function endPlayerGame() {
    const bloecke = state.bloecke[state.aktiverSpieler];
    const allDone = bloecke.every((b) => b.done);
    bloecke.forEach((b) => { b.done = !allDone; });
    laneSettingsOpen = false;
    persist(); render();
    toast(allDone ? 'Spiel wieder geöffnet' : 'Spiel beendet – Bahn frei');
  }

  function setOverride(i, val) {
    current().overrides[i] = val;
    persist(); render();
  }

  // ── Render ──
  function render() {
    root.innerHTML = template();
    wire();
    keepThrowVisible();
  }

  // Die Wurf-Chips scrollen horizontal, das Teilsatz-Ergebnis bleibt rechts fest daneben.
  // Ohne Nachführung landet ein neu erfasster Wurf am rechten Rand außerhalb des sichtbaren
  // Bereichs — also „hinter" dem Ergebnis. Deshalb den aktiven Teilsatz ans Ende scrollen,
  // sodass der neueste (bzw. gerade korrigierte) Wurf immer sichtbar bleibt.
  function keepThrowVisible() {
    const blk = current();
    const cursor = editIdx !== null ? editIdx : blk.wuerfe.length - 1;
    if (cursor < 0) return;
    const r = rangeOfThrow(ranges, cursor);
    if (!r) return;
    const row = root.querySelector(`.erf-chip-row[data-ts="${ranges.indexOf(r)}"]`);
    if (!row) return;
    if (editIdx !== null) {
      const chip = row.querySelector(`[data-chip="${editIdx}"]`);
      if (chip) { chip.scrollIntoView({ inline: 'nearest', block: 'nearest' }); return; }
    }
    row.scrollLeft = row.scrollWidth; // neuester Wurf ans sichtbare Ende
  }

  function template() {
    const sp = state.aktiverSpieler;
    const st = state.aktiverSatz;
    const blk = current();
    const status = satzStatus(blk);
    const wurfN = blk.wuerfe.length;
    const bs = computeBahnState();

    return `
      <header class="page-header">
        <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
        <h1 class="page-title brand">Pin-Scorer</h1>
        <button type="button" class="icon-btn settings-btn" data-act="settings" aria-label="Einstellungen">⚙</button>
      </header>

      ${bahnTabs(bs)}

      <div class="erf-player">
        <span class="erf-player-name">${esc(playerName(sp))}</span>
        ${bs[sp].waiting ? `<span class="erf-player-warten">⏳ wartet auf Bahnwechsel</span>` : ''}
        <span class="erf-player-total">${playerTotal(sp)}</span>
      </div>

      ${satzTabs()}

      <div class="erf-satz">
        <div class="erf-satz-head">
          <span class="erf-bahn-badge">Bahn ${laneOf(sp, st)}</span>
          <span class="erf-wurf-count">${wurfN}/${c.wuerfeProSatz}</span>
          <button type="button" class="erf-lane-btn" data-act="lane-settings" aria-label="Bahneinstellung">⚙ Einstellung</button>
        </div>

        ${kegelBoard(blk)}

        ${wurfChips(blk, status === 'done')}
        ${numpad(blk, status)}

        <div class="erf-actions">
          ${editIdx !== null
            ? `<button type="button" class="erf-btn danger" data-act="delete">🗑 Löschen</button>
               <button type="button" class="erf-btn" data-act="cancel-edit">✕ Abbrechen</button>`
            : `<button type="button" class="erf-btn" data-act="undo">↩ Zurück</button>`}
        </div>
      </div>

      <div id="erf-toast" class="erf-toast"></div>
      ${settingsOpen ? settingsPanel() : ''}
      ${laneSettingsOpen ? laneSettingsPanel() : ''}
      ${overrideTs !== null ? overridePanel() : ''}`;
  }

  // Einstellungsmenü (⚙): als Overlay-Sheet. Enthält aktuell die Spiel-Details
  // zum Abrufen; hier lassen sich später weitere Einstellungen andocken.
  function settingsPanel() {
    return `
      <div class="erf-settings-backdrop" data-act="settings-close">
        <div class="erf-settings-sheet" role="dialog" aria-modal="true" aria-label="Einstellungen">
          <div class="erf-settings-head">
            <h2 class="erf-settings-title">Einstellungen</h2>
            <button type="button" class="icon-btn" data-act="settings-close" aria-label="Schließen">✕</button>
          </div>
          <div class="erf-settings-body">
            <h3 class="erf-settings-sub">Spiel-Details</h3>
            ${spielDetails()}
          </div>
        </div>
      </div>`;
  }

  // Bahneinstellung (⚙ in der Satz-Kopfzeile): Satz beenden oder das ganze Spiel
  // dieses Spielers beenden. Beide Aktionen sind umkehrbar (öffnen wieder).
  function laneSettingsPanel() {
    const sp = state.aktiverSpieler;
    const st = state.aktiverSatz;
    const satzDone = current().done;
    const allDone = state.bloecke[sp].every((b) => b.done);
    return `
      <div class="erf-settings-backdrop" data-act="lane-settings-close">
        <div class="erf-settings-sheet" role="dialog" aria-modal="true" aria-label="Bahneinstellung">
          <div class="erf-settings-head">
            <h2 class="erf-settings-title">Bahneinstellung</h2>
            <button type="button" class="icon-btn" data-act="lane-settings-close" aria-label="Schließen">✕</button>
          </div>
          <div class="erf-settings-body">
            <p class="erf-lane-sub">Bahn ${laneOf(sp, st)} · ${esc(playerName(sp))} · Satz ${st + 1}</p>
            <div class="erf-lane-actions">
              <button type="button" class="erf-btn ${satzDone ? 'is-on' : 'done'}" data-act="end-satz">${satzDone ? '↺ Satz wieder öffnen' : '✓ Satz beenden'}</button>
              <button type="button" class="erf-btn ${allDone ? 'is-on' : 'danger'}" data-act="end-game">${allDone ? '↺ Spiel wieder öffnen' : '⏹ Spiel beenden (nur dieser Spieler)'}</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  function spielDetails() {
    const teile = c.teilsaetze.map((t, i) =>
      `<li>Teilsatz ${i + 1}: <strong>${MODUS_LABEL[t.modus] || t.modus}</strong> · ${t.wuerfe} Wurf</li>`).join('');
    return `
      <div class="summary">
        <div class="sum-row"><span>Spielart</span><strong>Sportkegeln-Training</strong></div>
        <div class="sum-row"><span>Bahnart</span><strong>${c.preset ? c.preset : '—'}</strong></div>
        <div class="sum-row"><span>Spieler</span><strong>${c.spieler}</strong></div>
        <div class="sum-row"><span>Bahnen</span><strong>${c.bahnen}${c.ersteBahn ? ` <small>(Bahn ${c.ersteBahn}–${c.ersteBahn + c.bahnen - 1})</small>` : ''}</strong></div>
        <div class="sum-row"><span>Sätze</span><strong>${c.saetze}</strong></div>
        <div class="sum-row"><span>Würfe pro Satz</span><strong>${c.wuerfeProSatz}</strong></div>
        <div class="sum-row"><span>Gesamtwürfe</span><strong>${c.gesamtwuerfe}</strong></div>
        <div class="sum-row sum-block"><span>Modus je Teilsatz</span><ul class="sum-list">${teile}</ul></div>
        <div class="sum-row"><span>Bahnwechsel</span><strong>${BW_LABEL[c.bahnwechsel] || c.bahnwechsel}</strong></div>
      </div>`;
  }

  // Bahn-Tabs: IMMER alle Bahnen des Spiels (max. 4), so wie sie nebeneinander
  // stehen. Zeigt die AKTUELLE (physische) Bahn jedes Spielers aus `computeBahnState`,
  // NICHT den unten angesehenen Satz. Wechselt man unten den Satz, bleibt oben gleich.
  // Wartende Spieler (fertig, naechste Bahn noch besetzt) bleiben auf ihrer Bahn mit
  // Status "wartet auf Bahnwechsel". Bahnen ohne Spieler -> "frei".
  function bahnTabs(bs) {
    // Alle Bahnen des Spiels zeigen; bis zu 4 füllen die Breite komplett,
    // ab der 5. entsteht horizontaler Scroll (CSS .erf-ptab min-width).
    const anzahl = c.bahnen;
    const belegung = {};
    bs.forEach((s, sp) => { belegung[s.lane] = sp; });

    const tabs = [];
    for (let i = 0; i < anzahl; i++) {
      const bahn = c.ersteBahn + i;
      const sp = belegung[bahn];
      if (sp == null) {
        tabs.push(`<div class="erf-ptab is-frei" aria-label="Bahn ${bahn}, frei">
          <span class="ept-top"><span class="ept-bahn">Bahn ${bahn}</span></span>
          <span class="ept-name ept-frei">frei</span>
        </div>`);
        continue;
      }
      const s = bs[sp];
      const st = s.pos;
      const blk = block(sp, st);
      const status = s.waiting ? 'wartet' : satzStatus(blk);
      const total = playerTotal(sp);
      const satzH = satzHolz(blk, ranges);
      const wurfN = blk.wuerfe.length;
      // FUNK-Stil-Kopf: WW = Wurf-Nr · aktueller Wurf · GS = Gesamt Bahn; G = Gesamtergebnis.
      const lastThrow = wurfN ? blk.wuerfe[wurfN - 1] : '–';
      tabs.push(`<button type="button" role="tab" aria-selected="${sp === state.aktiverSpieler}" class="erf-ptab is-${status}${sp === state.aktiverSpieler ? ' is-active' : ''}" data-player="${sp}">
        <span class="ept-top">
          <span class="ept-bahn">Bahn ${bahn}</span>
          ${s.waiting ? `<span class="ept-warten" title="wartet auf Bahnwechsel">⏳</span>` : ''}
          <span class="ept-total" title="Gesamtergebnis">${total}</span>
        </span>
        <span class="ept-name">${esc(playerName(sp))}</span>
        <span class="ept-bot">
          <span class="ept-wurf" title="Wurf-Nr.">${wurfN}</span>
          <span class="ept-cur" title="Aktueller Wurf">${lastThrow}</span>
          <span class="ept-satzholz" title="Gesamt Bahn">${status === 'pending' ? '–' : satzH}</span>
        </span>
      </button>`);
    }
    return `<div class="erf-ptabs" role="tablist">${tabs.join('')}</div>`;
  }

  function satzTabs() {
    const sp = state.aktiverSpieler;
    return `<div class="erf-stabs" role="tablist">${state.bloecke[sp].map((blk, st) => {
      const s = satzStatus(blk);
      const h = satzHolz(blk, ranges);
      return `<button type="button" role="tab" aria-selected="${st === state.aktiverSatz}" class="erf-stab is-${s}${st === state.aktiverSatz ? ' is-active' : ''}" data-satz="${st}">
        <span class="est-label">Satz ${st + 1}</span>
        <span class="est-bahn">Bahn ${laneOf(sp, st)}</span>
        <span class="est-val">${s === 'pending' ? '–' : h}</span>
      </button>`;
    }).join('')}</div>`;
  }

  // Kegel-Raute: welche Kegel im Ziel-Wurf gefallen/stehen (anklickbar).
  // Ziffernblock gibt N (Holz) vor -> Auswahl muss dazu passen.
  function kegelBoard(blk) {
    const target = pinTarget();
    const has = target >= 0;

    if (!has) {
      const pins = KEGEL_LAYOUT.map((p) =>
        `<span class="erf-kegel-pin is-off" style="grid-column:${p.c};grid-row:${p.r};">${p.n}</span>`).join('');
      return `
        <div class="erf-kegel">
          <div class="erf-kegel-head"><span class="ek-title">Kegel</span><span class="ek-target">kein Wurf</span></div>
          <div class="erf-kegel-grid">${pins}</div>
          <div class="erf-kegel-foot"></div>
        </div>`;
    }

    const n = blk.wuerfe[target];
    const ctx = throwContext(blk, target);
    const U = ctx.universe;              // wählbare Kegel (Abräumen: nur stehende)
    const Usize = U.length;
    const inU = (pin) => !ctx.abraeum || !ctx.exact || U.includes(pin);
    const unset = blk.kegel[target] == null;
    // König-Wurf (Langdruck): N Kranz-Kegel gefallen, König (5) steht — genaue Kegel offen.
    const koenigThrow = ctx.kranz && Array.isArray(blk.koenig) && blk.koenig[target] && unset;
    // F = gefallene (leuchtende) Kegel. Unbestimmt: gefallen-Modus keiner an, stehend-Modus alle wählbaren an.
    // Beim Kranz-Langdruck sind die genauen Kegel offen, aber es fielen alle STEHENDEN außer dem
    // König (5) -> so darstellen: die 8 Kranzkegel leuchten, der König steht ganz normal (keine Sonder-Umrandung).
    const fallen = koenigThrow
      ? U.filter((pin) => pin !== 5)
      : (unset ? (pinMode === 'stehend' ? U.slice() : []) : blk.kegel[target]);
    const fallenN = fallen.length;
    const stehendN = Usize - fallenN;
    const locked = blk.done;
    const match = fallenN === n;

    const pins = KEGEL_LAYOUT.map((p) => {
      const gone = !inU(p.n);                          // vor diesem Wurf schon gefallen -> weg
      const isFallen = !gone && fallen.includes(p.n);
      // Gefallener Kegel leuchtet (Lampe an), stehender ist aus; schon gefallener ist "weg".
      // Der König (5) steht beim Kranz wie jeder andere stehende Kegel — keine Sonder-Umrandung.
      const cls = gone ? 'is-gone' : (isFallen ? 'is-lamp-on' : '');
      const aria = gone ? 'schon gefallen' : (isFallen ? 'gefallen' : 'steht');
      const dis = locked || gone;
      return `<button type="button" class="erf-kegel-pin ${cls}" style="grid-column:${p.c};grid-row:${p.r};"
        data-pin="${p.n}"${dis ? ' disabled' : ''} aria-label="Kegel ${p.n}, ${aria}">${p.n}</button>`;
    }).join('');

    const counter = pinMode === 'gefallen' ? `${fallenN}/${n}` : `${stehendN}/${Usize - n}`;
    let foot;
    foot = '';

    return `
      <div class="erf-kegel">
        <div class="erf-kegel-head">
          <div class="ek-modes" role="group" aria-label="Kegel erfassen als">
            <button type="button" aria-pressed="${pinMode === 'gefallen'}" class="ek-mode${pinMode === 'gefallen' ? ' is-active' : ''}" data-pinmode="gefallen">Gefallene</button>
            <button type="button" aria-pressed="${pinMode === 'stehend'}" class="ek-mode${pinMode === 'stehend' ? ' is-active' : ''}" data-pinmode="stehend">Stehende</button>
          </div>
          <span class="ek-target">${counter}</span>
        </div>
        <div class="erf-kegel-grid">${pins}</div>
        <div class="erf-kegel-foot">${foot}</div>
      </div>`;
  }

  function wurfChips(blk, satzDone) {
    if (c.wuerfeProSatz === 0) return '';
    const rows = ranges.map((r, i) => {
      const label = MODUS_LABEL[r.modus] || r.modus;
      const t = teilsatzStats(blk, ranges, i, satzDone);
      // Abräumen/Kranz: Lauf einmal durchscannen (Plausibilität + Kranz-Treffer pro Wurf).
      const scan = isAbraeumMode(r.modus) ? abraeumScan(blk, r) : null;
      const errors = scan ? scan.error : null;
      const chips = [];
      for (let k = r.start; k < r.end; k++) {
        if (k < blk.wuerfe.length) {
          const err = errors && errors[k];
          // Kranz: nur der König (5) steht noch. Abräumen -> aus dem Lauf-Scan, Volle -> aus dem Wurf.
          const kranzHit = scan ? !!scan.kranzAt[k] : (r.modus === 'volle' && volleKranz(blk, k));
          // Neuner = Maximalwurf im Bild (alle 9 auf einmal): dauerhaftes ⭐-Abzeichen am Chip.
          const neuner = blk.wuerfe[k] === 9;
          chips.push(`<button type="button" class="erf-chip${editIdx === k ? ' is-edit' : ''}${err ? ' is-error' : ''}${kranzHit ? ' is-koenig' : ''}${neuner ? ' is-neuner' : ''}" data-chip="${k}"${err ? ` title="${esc(err)}"` : kranzHit ? ' title="Kranz — nur der König (5) steht"' : neuner ? ' title="Alle Neune!"' : ''}>
            <span class="ec-nr">${k + 1}${kranzHit ? ' ♔' : neuner ? ' ☆' : ''}</span><span class="ec-pins">${blk.wuerfe[k]}${err ? '⚠' : ''}</span></button>`);
        } else {
          chips.push(`<span class="erf-chip is-empty" data-slot="${k}"><span class="ec-nr">${k + 1}</span><span class="ec-pins">·</span></span>`);
        }
      }
      // Teilsatz-Ergebnis direkt in der Wurfzeile (rechts), antippen -> Override.
      const result = `<button type="button" class="erf-chip-result${t.mark ? ' mismatch' : ''}${t.manual ? ' manual' : ''}" data-override="${i}" aria-label="${label}-Ergebnis setzen">
        <span class="ecr-val">${t.val}${t.mark ? ' ⚠' : ''}${t.manual ? ' ✎' : ''}</span>
        <span class="ecr-count">${t.count}/${t.soll}</span>
      </button>`;
      // Fehlerhinweis unter der Wurfzeile (auf dem Handy ohne Tooltip sichtbar).
      let errNote = '';
      if (errors) {
        const bad = [];
        for (let k = r.start; k < r.end; k++) if (errors[k]) bad.push(`Wurf ${k + 1}: ${errors[k]}`);
        if (bad.length) errNote = `<div class="erf-chip-err">⚠ ${esc(bad.join(' · '))}</div>`;
      }
      return `<div class="erf-chip-group">
        <span class="ecg-label">${label}</span>
        <div class="erf-chip-line">
          <div class="erf-chip-row" data-ts="${i}">${chips.join('')}</div>
          ${result}
        </div>
        ${errNote}
      </div>`;
    }).join('');
    return `<div class="erf-chips">${rows}</div>`;
  }

  function numpad(blk, status) {
    const full = blk.wuerfe.length >= c.wuerfeProSatz;
    const locked = editIdx === null && (status === 'done' || full);
    // Ziel-Wurf: beim Korrigieren der editIdx-Wurf, sonst der nächste neue.
    const idx = editIdx !== null ? editIdx : blk.wuerfe.length;
    const ctx = throwContext(blk, idx);
    // Kranz-Abräumen: per LANGDRUCK GENAU die Zahl erfassen, die den ganzen Kranz abräumt
    // und nur den König stehen lässt — also maxPins-1 (im vollen Bild die 8). Danach steht
    // nur noch der König -> Reset auf alle 9. Voraussetzung: der König steht noch — entweder
    // weil im Bild noch KEINE konkreten Kegel gewählt wurden (dann gilt er als stehend), oder
    // weil die gewählten Kegel den König (5) stehen lassen. Nie auf einer 0 (dann stünde kein
    // Kranz mehr, der fallen könnte).
    const koenigDigit = ctx.maxPins - 1;
    const koenigLong = ctx.kranz && (!ctx.picked || ctx.koenig) && !locked && koenigDigit >= 1;
    // Beim Abräumen können nur so viele Kegel fallen wie stehen -> höhere Zahlen sperren.
    const btn = (n) => {
      const dis = locked || (ctx.abraeum && n > ctx.maxPins);
      const canK = koenigLong && !dis && n === koenigDigit;
      return `<button type="button" class="erf-num${n === 0 ? ' zero' : ''}${canK ? ' can-koenig' : ''}" data-num="${n}"${canK ? ' data-koenig="1"' : ''}${dis ? ' disabled' : ''}>${n}</button>`;
    };
    return `<div class="erf-numpad">
      ${[7, 8, 9, 4, 5, 6, 1, 2, 3].map(btn).join('')}
      ${btn(0)}
    </div>`;
  }

  function wire() {
    root.querySelectorAll('[data-player]').forEach((b) =>
      b.addEventListener('click', () => selectPlayer(parseInt(b.dataset.player, 10))));
    root.querySelectorAll('[data-satz]').forEach((b) =>
      b.addEventListener('click', () => selectSatz(parseInt(b.dataset.satz, 10))));
    root.querySelectorAll('[data-num]').forEach((b) => {
      const n = parseInt(b.dataset.num, 10);
      const canK = b.dataset.koenig === '1';
      // Kurzer Tipp = normaler Wurf. Auf König-Tasten zusätzlich Langdruck (~450 ms) =
      // Wurf, nach dem der König stehen bleibt. lpSuppress verhindert, dass der Klick nach
      // dem Langdruck (auch nach dem Re-Render) noch einen zweiten Wurf auslöst.
      b.addEventListener('click', () => {
        if (Date.now() - lpSuppress < 500) return;
        addWurf(n);
      });
      if (!canK) return;
      let timer = null;
      b.addEventListener('pointerdown', () => {
        clearTimeout(timer);
        timer = setTimeout(() => { timer = null; lpSuppress = Date.now(); addWurf(n, true); }, 450);
      });
      const clear = () => { clearTimeout(timer); timer = null; };
      b.addEventListener('pointerup', clear);
      b.addEventListener('pointerleave', clear);
      b.addEventListener('pointercancel', clear);
    });
    root.querySelectorAll('[data-pin]').forEach((b) =>
      b.addEventListener('click', () => tapPin(parseInt(b.dataset.pin, 10))));
    root.querySelectorAll('[data-pinmode]').forEach((b) =>
      b.addEventListener('click', () => setPinMode(b.dataset.pinmode)));
    root.querySelectorAll('[data-chip]').forEach((b) =>
      b.addEventListener('click', () => {
        const idx = parseInt(b.dataset.chip, 10);
        editIdx = editIdx === idx ? null : idx;
        render();
      }));
    root.querySelectorAll('[data-override]').forEach((b) =>
      b.addEventListener('click', () => openOverride(parseInt(b.dataset.override, 10))));

    const act = (name, fn) => {
      const el = root.querySelector(`[data-act="${name}"]`);
      if (el) el.addEventListener('click', fn);
    };
    act('undo', undo);
    act('delete', deleteEditing);
    act('cancel-edit', () => { editIdx = null; render(); });
    act('settings', () => { settingsOpen = true; render(); });
    act('lane-settings', () => { laneSettingsOpen = true; render(); });
    act('end-satz', toggleDone);
    act('end-game', endPlayerGame);
    // Schließen: ✕-Button oder Klick auf den Backdrop (aber nicht ins Sheet hinein).
    root.querySelectorAll('[data-act="settings-close"]').forEach((b) =>
      b.addEventListener('click', (e) => {
        if (b.classList.contains('erf-settings-backdrop') && e.target !== b) return;
        settingsOpen = false; render();
      }));
    root.querySelectorAll('[data-act="lane-settings-close"]').forEach((b) =>
      b.addEventListener('click', (e) => {
        if (b.classList.contains('erf-settings-backdrop') && e.target !== b) return;
        laneSettingsOpen = false; render();
      }));

    // Override-Sheet (Teilsatz-Summe)
    root.querySelectorAll('[data-ovnum]').forEach((b) =>
      b.addEventListener('click', () => overrideKey(b.dataset.ovnum)));
    act('override-apply', applyOverride);
    act('override-reset', resetOverride);
    root.querySelectorAll('[data-act="override-close"]').forEach((b) =>
      b.addEventListener('click', (e) => {
        if (b.classList.contains('erf-settings-backdrop') && e.target !== b) return;
        overrideTs = null; render();
      }));
  }

  // Teilsatz-Summe manuell setzen (Override): öffnet das Sheet mit Ziffernblock.
  function openOverride(i) {
    const cur = current().overrides[i];
    overrideTs = i;
    overrideDraft = cur != null ? String(cur) : '';
    render();
  }

  // Overlay-Sheet mit eigenem Ziffernblock — ersetzt den früheren window.prompt.
  function overridePanel() {
    const i = overrideTs;
    const blk = current();
    const r = ranges[i];
    const label = MODUS_LABEL[r.modus] || r.modus;
    const stats = teilsatzStats(blk, ranges, i, satzStatus(blk) === 'done');
    const wSum = blk.wuerfe.slice(r.start, r.end).reduce((a, w) => a + w, 0);
    const draft = overrideDraft === '' ? '—' : overrideDraft;
    const numBtn = (n) => `<button type="button" class="erf-num${n === 0 ? ' zero' : ''}" data-ovnum="${n}">${n}</button>`;
    return `
      <div class="erf-settings-backdrop" data-act="override-close">
        <div class="erf-settings-sheet" role="dialog" aria-modal="true" aria-label="Teilsatz-Summe">
          <div class="erf-settings-head">
            <h2 class="erf-settings-title">Teilsatz-Summe</h2>
            <button type="button" class="icon-btn" data-act="override-close" aria-label="Schließen">✕</button>
          </div>
          <div class="erf-settings-body">
            <p class="erf-lane-sub">${esc(label)} · aus Würfen: ${stats.count} Wurf, ${wSum} Holz</p>
            <div class="erf-ov-value" aria-live="polite">${draft}</div>
            <div class="erf-numpad erf-ov-numpad">
              ${[7, 8, 9, 4, 5, 6, 1, 2, 3].map(numBtn).join('')}
              <button type="button" class="erf-num" data-ovnum="back" aria-label="Letzte Ziffer löschen">⌫</button>
              ${numBtn(0)}
            </div>
            <div class="erf-lane-actions">
              <button type="button" class="erf-btn done" data-act="override-apply">✓ Übernehmen</button>
              <button type="button" class="erf-btn danger" data-act="override-reset">↺ Zurücksetzen</button>
            </div>
          </div>
        </div>
      </div>`;
  }

  // Ziffer/⌫ im Override-Sheet verarbeiten (max. 4 Stellen; führende Null verwerfen).
  function overrideKey(key) {
    if (key === 'back') overrideDraft = overrideDraft.slice(0, -1);
    else if (overrideDraft.length < 4) overrideDraft = (overrideDraft + key).replace(/^0+(?=\d)/, '');
    render();
  }

  function applyOverride() {
    const i = overrideTs;
    const label = MODUS_LABEL[ranges[i].modus] || ranges[i].modus;
    if (overrideDraft !== '') {
      const v = parseInt(overrideDraft, 10);
      if (Number.isNaN(v) || v < 0) { toast('Ungültiger Wert'); return; }
      overrideTs = null;
      setOverride(i, v); // persist + render (Sheet ist dann zu)
      toast(`${label} auf ${v} Holz gesetzt`);
      return;
    }
    // leer = wie Zurücksetzen
    overrideTs = null;
    setOverride(i, null);
    toast(`${label}: Override entfernt`);
  }

  function resetOverride() {
    const i = overrideTs;
    const label = MODUS_LABEL[ranges[i].modus] || ranges[i].modus;
    overrideTs = null;
    setOverride(i, null);
    toast(`${label}: Override entfernt`);
  }

  let toastTimer;
  function toast(msg) {
    const el = root.querySelector('#erf-toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
  }

  render();
  return root;
}
