// Wurferfassung fuer "Hausnummern".
//
// Anders als beim Sportkegeln zaehlt hier nicht die Holzsumme, sondern WO ein Wurf landet:
// jeder Wurf besetzt eine Stelle der Hausnummer. Die Oberflaeche ist deshalb bewusst klein —
// Ziffernkaestchen oben, Ziffernblock unten:
//   - Spieler-Tabs mit laufender Summe
//   - je Durchgang ein Kaestchen-Streifen (die entstehende Hausnummer)
//   - Ziffernblock 0-9 + Fehlwurf (zaehlt die schlechteste Ziffer) + Rueckgaengig
//   - bei den Ansage-Varianten wird die Stelle im Kaestchen-Streifen angetippt
//   - Reihum-Automatik: ist ein Durchgang voll, ist der naechste Spieler dran
//   - Stand/Ergebnis als eigener Bildschirm (Rangliste + Tabelle aller Durchgaenge)

import { getActiveGame, getGame, saveErfassung, setGameStatus } from '../store.js';
import { UNMOUNT_EVENT } from '../router.js';
import { esc } from '../util.js';
import {
  PLATZIERUNGEN, VARIANTEN, stellenOf, ziffer, fehlwurfZiffer,
  positionen, naechsteStelle, ziffernOf, durchgangFertig,
  hausnummerWert, hausnummerText, formatZahl, summe, spielFertig, rangliste,
} from '../logic/hausnummern.js';

const MEDAILLE = ['🥇', '🥈', '🥉'];
const medal = (rang) => MEDAILLE[rang - 1] || `${rang}.`;

// ── Modell-Helfer ─────────────────────────────────────────────────────────

// Frischer Erfassungsstand: je Spieler ein Array von Durchgaengen.
function initErfassung(c) {
  return {
    aktiverSpieler: 0,
    aktiverSatz: 0,
    bloecke: (c.spielerListe || []).map(() =>
      Array.from({ length: c.saetze || 1 }, () => ({
        wuerfe: [],      // Holz je Wurf (0-9)
        pos: [],         // Stelle der Hausnummer je Wurf (0..stellen-1)
        ungueltig: [],   // Fehlwurf-Flag je Wurf
        done: false,
      }))),
  };
}

// Bestehenden Stand an die Konfiguration angleichen (robust gegen geaenderte Regeln).
function normalizeErfassung(e, c) {
  const base = initErfassung(c);
  if (!e || !Array.isArray(e.bloecke)) return base;
  const stellen = stellenOf(c);
  base.aktiverSpieler = Math.min(e.aktiverSpieler || 0, base.bloecke.length - 1);
  base.aktiverSatz = Math.min(e.aktiverSatz || 0, (c.saetze || 1) - 1);
  base.bloecke = base.bloecke.map((satzArr, sp) => satzArr.map((blk, st) => {
    const old = e.bloecke[sp] && e.bloecke[sp][st];
    if (!old) return blk;
    const wuerfe = (Array.isArray(old.wuerfe) ? old.wuerfe : []).slice(0, stellen);
    return {
      wuerfe,
      pos: wuerfe.map((_, k) => (Array.isArray(old.pos) ? old.pos[k] : undefined)),
      ungueltig: wuerfe.map((_, k) => !!(Array.isArray(old.ungueltig) && old.ungueltig[k])),
      done: !!old.done,
    };
  }));
  return base;
}

// ── View ──────────────────────────────────────────────────────────────────

export function hausnummernSpielView() {
  const root = document.createElement('div');
  root.className = 'view view-page erf-screen hn-screen';

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
  const stellen = stellenOf(c);
  const runden = c.saetze || 1;
  const state = normalizeErfassung(game.erfassung, c);
  game.erfassung = state; // beide Sichten auf denselben Stand binden

  let editIdx = null;      // Korrektur: Index des Wurfs, der ueberschrieben wird
  let pendingPos = null;   // 'ansage-vor': angesagte Stelle, auf die der naechste Wurf geht
  let pendingZahl = null;  // 'wahl-nach': geworfene Ziffer, die noch eine Stelle sucht { wurf, ungueltig }
  let standOpen = game.status === 'beendet'; // Stand/Ergebnis-Bildschirm offen?
  let toastTimer = null;

  const blockOf = (sp, st) => state.bloecke[sp][st];
  // Gewertete Summe als Text — solange kein Durchgang fertig ist, ein Strich statt "0000".
  // Gerade beim Niedrig-Spiel sähe eine 0 sonst nach einem sensationellen Ergebnis aus.
  const summeText = (satzArr) => (satzArr.some((blk) => durchgangFertig(blk, c))
    ? formatZahl(summe(satzArr, c), c) : '–');
  const current = () => blockOf(state.aktiverSpieler, state.aktiverSatz);
  const playerName = (sp) => (c.spielerListe[sp] && c.spielerListe[sp].name) || ('Spieler ' + (sp + 1));
  const ansageModus = c.platzierung === 'ansage-vor';
  const wahlModus = c.platzierung === 'wahl-nach';
  const istNiedrig = c.variante === 'niedrig';
  // Hoch oder niedrig? Das entscheidet jeden einzelnen Wurf und steht deshalb dauerhaft als
  // Seitentitel über der Erfassung — nicht nur im Setup und im Ergebnis.
  const varianteLabel = (VARIANTEN.find((v) => v.key === c.variante) || VARIANTEN[0]).label;

  function persist() {
    if (saveErfassung(gameId, state) === null) toast('Speichern fehlgeschlagen — Speicher voll?');
  }

  // Spielreihenfolge: Durchgang fuer Durchgang, darin Spieler fuer Spieler.
  function zugOrdnung() {
    const out = [];
    for (let st = 0; st < runden; st += 1) {
      for (let sp = 0; sp < state.bloecke.length; sp += 1) out.push({ sp, st });
    }
    return out;
  }

  // Der naechste noch offene Zug ab (sp, st) — Grundlage der Reihum-Automatik.
  function naechsterOffenerZug(sp, st) {
    const ord = zugOrdnung();
    const idx = ord.findIndex((z) => z.sp === sp && z.st === st);
    for (let i = idx + 1; i < ord.length; i += 1) {
      if (!durchgangFertig(blockOf(ord[i].sp, ord[i].st), c)) return ord[i];
    }
    return ord.find((z) => !durchgangFertig(blockOf(z.sp, z.st), c)) || null;
  }

  // Der letzte Zug VOR (sp, st), der schon Wuerfe hat — fuer „Rückgängig" ueber die Grenze
  // eines Durchgangs hinweg.
  function vorherigerZugMitWurf(sp, st) {
    const ord = zugOrdnung();
    const idx = ord.findIndex((z) => z.sp === sp && z.st === st);
    for (let i = idx - 1; i >= 0; i -= 1) {
      if (blockOf(ord[i].sp, ord[i].st).wuerfe.length) return ord[i];
    }
    return null;
  }

  function selectZug(sp, st) {
    state.aktiverSpieler = sp;
    state.aktiverSatz = st;
    editIdx = null;
    pendingPos = null;
    pendingZahl = null;
    persist();
    render();
  }

  // ── Eingabe ──────────────────────────────────────────────────────────────

  // Die Stelle, auf die der naechste Wurf geht — oder null, wenn sie noch fehlt.
  function zielStelle() {
    if (editIdx !== null) return positionen(current(), c)[editIdx];
    if (ansageModus) return pendingPos;
    return naechsteStelle(current(), c);
  }

  // Eine Ziffer erfassen. `ungueltig` = Fehlwurf (zaehlt die schlechteste Ziffer).
  function eingabe(wurf, ungueltig = false) {
    const blk = current();
    if (editIdx !== null) {                 // Korrektur: nur den Wert tauschen, Stelle bleibt
      blk.wuerfe[editIdx] = wurf;
      blk.ungueltig[editIdx] = ungueltig;
      editIdx = null;
      nachEingabe(blk);
      return;
    }
    if (durchgangFertig(blk, c)) { toast('Durchgang ist voll.'); return; }
    if (wahlModus) {                        // erst werfen, dann die Stelle waehlen
      pendingZahl = { wurf, ungueltig };
      render();
      return;
    }
    const stelle = zielStelle();
    if (stelle == null) { toast('Erst die Stelle ansagen.'); return; }
    setzeWurf(blk, wurf, ungueltig, stelle);
  }

  function setzeWurf(blk, wurf, ungueltig, stelle) {
    blk.wuerfe.push(wurf);
    blk.ungueltig.push(ungueltig);
    blk.pos.push(stelle);
    pendingPos = null;
    pendingZahl = null;
    nachEingabe(blk);
  }

  // Nach jeder Eingabe: Durchgang ggf. schliessen, reihum weiterschalten, sichern.
  function nachEingabe(blk) {
    if (durchgangFertig(blk, c)) {
      blk.done = true;
      const naechster = naechsterOffenerZug(state.aktiverSpieler, state.aktiverSatz);
      if (naechster) {
        state.aktiverSpieler = naechster.sp;
        state.aktiverSatz = naechster.st;
      }
    }
    persist();
    if (spielFertig(c, state.bloecke)) {
      setGameStatus(gameId, 'beendet');
      game.status = 'beendet';
      standOpen = true;
    } else if (game.status === 'beendet') {
      setGameStatus(gameId, 'laufend');
      game.status = 'laufend';
    }
    render();
  }

  // Antippen eines Kaestchens: Stelle ansagen, Stelle waehlen oder einen Wurf korrigieren.
  function tapStelle(i) {
    const blk = current();
    const pos = positionen(blk, c);
    const wurfIdx = pos.indexOf(i);
    if (pendingZahl) {                          // 'wahl-nach': die geworfene Ziffer platzieren
      if (wurfIdx >= 0) { toast('Diese Stelle ist schon belegt.'); return; }
      setzeWurf(blk, pendingZahl.wurf, pendingZahl.ungueltig, i);
      return;
    }
    if (wurfIdx >= 0) {                         // belegte Stelle -> Wert korrigieren
      editIdx = editIdx === wurfIdx ? null : wurfIdx;
      render();
      return;
    }
    if (ansageModus) { pendingPos = pendingPos === i ? null : i; render(); return; }
    if (wahlModus) { toast('Erst werfen, dann die Stelle wählen.'); return; }
    const platz = PLATZIERUNGEN.find((p) => p.key === c.platzierung);
    toast(platz ? platz.desc + '.' : 'Die Stelle ergibt sich aus der Wurfnummer.');
  }

  function undo() {
    if (editIdx !== null || pendingZahl || pendingPos != null) {
      editIdx = null; pendingZahl = null; pendingPos = null;
      render();
      return;
    }
    let blk = current();
    if (!blk.wuerfe.length) {
      const zurueck = vorherigerZugMitWurf(state.aktiverSpieler, state.aktiverSatz);
      if (!zurueck) { toast('Nichts zurückzunehmen.'); return; }
      state.aktiverSpieler = zurueck.sp;
      state.aktiverSatz = zurueck.st;
      blk = current();
    }
    blk.wuerfe.pop();
    blk.pos.pop();
    blk.ungueltig.pop();
    blk.done = false;
    persist();
    if (game.status === 'beendet') { setGameStatus(gameId, 'laufend'); game.status = 'laufend'; }
    render();
  }

  function loescheWurf() {
    if (editIdx === null) return;
    const blk = current();
    blk.wuerfe.splice(editIdx, 1);
    blk.pos.splice(editIdx, 1);
    blk.ungueltig.splice(editIdx, 1);
    blk.done = false;
    editIdx = null;
    persist();
    if (game.status === 'beendet') { setGameStatus(gameId, 'laufend'); game.status = 'laufend'; }
    render();
  }

  // Spiel von Hand beenden (abbrechen) bzw. wieder oeffnen.
  function beenden() {
    setGameStatus(gameId, 'beendet');
    game.status = 'beendet';
    standOpen = true;
    render();
  }

  function weiterErfassen() {
    setGameStatus(gameId, 'laufend');
    game.status = 'laufend';
    standOpen = false;
    render();
  }

  // ── Anzeige ──────────────────────────────────────────────────────────────

  // Die Hausnummer eines Durchgangs als Text: fertig = die Zahl, angefangen = der Teilstand
  // mit Strichen, unberuehrt = ein Strich.
  function zellText(blk) {
    if (durchgangFertig(blk, c)) return formatZahl(hausnummerWert(blk, c), c);
    return blk.wuerfe.length ? hausnummerText(blk, c) : '–';
  }

  // Der LIVESTAND ueber der Erfassung: alle Spieler, alle Durchgaenge, die Summe — er waechst
  // mit jedem Wurf mit. Er ersetzt zugleich die Spieler-Tabs und die Durchgangs-Wahl: jede
  // Zelle springt zu genau diesem Spieler und Durchgang.
  //
  // Die Zeilen stehen in SPIELER-Reihenfolge, nicht nach Rang: eine Tabelle, die sich nach
  // jedem Wurf umsortiert, verliert man beim Eintippen aus den Augen. Wer vorn liegt, sagt
  // die Medaille am Namen (aus derselben Rangliste wie der Ergebnis-Bildschirm).
  function livestand() {
    const rang = {};
    rangliste(c, state.bloecke).forEach((r) => { rang[r.pos] = r.gespielt ? r.rang : null; });
    const kopf = Array.from({ length: runden }, (_, st) =>
      `<th class="${st === state.aktiverSatz ? 'is-aktiv' : ''}">${st + 1}</th>`).join('');
    const zeilen = state.bloecke.map((satzArr, sp) => {
      const zellen = satzArr.map((blk, st) => {
        const aktiv = sp === state.aktiverSpieler && st === state.aktiverSatz;
        const offen = !durchgangFertig(blk, c) && blk.wuerfe.length;
        const txt = zellText(blk);
        return `<td class="${aktiv ? 'is-aktiv' : ''}${offen ? ' is-offen' : ''}">
          <button type="button" class="hn-live-cell" data-zug="${sp}-${st}"
            aria-label="${esc(playerName(sp))}, Durchgang ${st + 1}: ${txt}"
            ${offen ? 'title="Angefangen — zählt erst, wenn der Durchgang voll ist"' : ''}>${txt}</button>
        </td>`;
      }).join('');
      return `<tr class="${sp === state.aktiverSpieler ? 'is-aktiv' : ''}">
        <th class="hn-live-name" scope="row">${rang[sp] ? `<span class="hn-live-rang">${medal(rang[sp])}</span>` : ''}${esc(playerName(sp))}</th>
        ${zellen}
        ${runden > 1 ? `<td class="hn-live-summe">${summeText(satzArr)}</td>` : ''}
      </tr>`;
    }).join('');
    return `<div class="hn-live">
      <table class="hn-live-table">
        <thead><tr><th class="hn-live-name">Spieler</th>${kopf}${runden > 1 ? '<th class="hn-live-summe">Summe</th>' : ''}</tr></thead>
        <tbody>${zeilen}</tbody>
      </table>
    </div>`;
  }

  function stellenStreifen() {
    const blk = current();
    const ziffern = ziffernOf(blk, c);
    const pos = positionen(blk, c);
    const ziel = zielStelle();
    const cells = ziffern.map((z, i) => {
      const wurfIdx = pos.indexOf(i);
      const klassen = ['hn-cell'];
      if (z == null) klassen.push('is-leer');
      if (editIdx !== null && wurfIdx === editIdx) klassen.push('is-edit');
      else if (pendingZahl && z == null) klassen.push('is-wahl');
      else if (ziel === i && editIdx === null) klassen.push('is-ziel');
      if (wurfIdx >= 0 && blk.ungueltig[wurfIdx]) klassen.push('is-fehl');
      return `<button type="button" class="${klassen.join(' ')}" data-stelle="${i}"
        aria-label="Stelle ${i + 1}${z == null ? ' — offen' : `: ${z}`}">
        <span class="hn-digit">${z == null ? '–' : z}</span>
        <span class="hn-pos">${i + 1}</span>
      </button>`;
    }).join('');
    return `<div class="hn-cells" style="--hn-stellen:${stellen}">${cells}</div>`;
  }

  // Was ist gerade zu tun? Eine Zeile, die den Zustand der Eingabe erklaert.
  function hinweis() {
    const blk = current();
    if (editIdx !== null) {
      return `Korrektur: Stelle <strong>${(positionen(blk, c)[editIdx] ?? 0) + 1}</strong> — neue Zahl tippen`;
    }
    if (pendingZahl) {
      const z = ziffer(pendingZahl.wurf, pendingZahl.ungueltig, c);
      return `<strong>${z}</strong> geworfen — jetzt die Stelle wählen`;
    }
    if (durchgangFertig(blk, c)) {
      return `Durchgang fertig: <strong>${hausnummerText(blk, c)}</strong>`;
    }
    if (ansageModus) {
      return pendingPos == null
        ? 'Stelle ansagen — dann werfen'
        : `Angesagt: Stelle <strong>${pendingPos + 1}</strong> — jetzt die Zahl tippen`;
    }
    const ziel = naechsteStelle(blk, c);
    const wurf = `Wurf <strong>${blk.wuerfe.length + 1}</strong> von ${stellen}`;
    if (ziel != null) return `${wurf} → Stelle <strong>${ziel + 1}</strong>`;
    return wahlModus ? `${wurf} — werfen, dann die Stelle wählen` : wurf;
  }

  function numpad() {
    const blk = current();
    const voll = durchgangFertig(blk, c) && editIdx === null;
    // Beim Warten auf die Stelle ('wahl-nach') sind die Zahlen gesperrt: erst platzieren.
    const gesperrt = voll || !!pendingZahl || (ansageModus && editIdx === null && pendingPos == null);
    // Die 0 ist beim Niedrig-Spiel die DURCHGELAUFENE Kugel — je nach Regel zählt sie 9 statt 0.
    // Weicht sie ab, steht das auf der Taste: sonst tippt man 0 und im Kästchen erscheint eine 9.
    const nullZiffer = ziffer(0, false, c);
    const btn = (n) => {
      const note = n === 0 && nullZiffer !== 0 ? `<small class="hn-num-note">zählt ${nullZiffer}</small>` : '';
      const titel = n === 0 && istNiedrig
        ? ` title="Kugel läuft durch (kein Holz) — zählt ${nullZiffer}"` : '';
      return `<button type="button" class="erf-num${note ? ' hn-num-2' : ''}" data-num="${n}"${titel}${gesperrt ? ' disabled' : ''}>${n}${note}</button>`;
    };
    const editing = editIdx !== null;
    const linksAkt = editing
      ? '<button type="button" class="erf-num erf-num-act danger" data-act="delete" aria-label="Wurf löschen">🗑</button>'
      : '<button type="button" class="erf-num erf-num-act" data-act="undo" aria-label="Letzten Wurf zurück">↩</button>';
    const rechtsAkt = editing
      ? '<button type="button" class="erf-num erf-num-act" data-act="cancel-edit" aria-label="Korrektur abbrechen">✕</button>'
      : `<button type="button" class="erf-num erf-num-act hn-fehl hn-num-2" data-act="fehl"${gesperrt ? ' disabled' : ''}
           aria-label="Ungültiger Wurf — zählt ${fehlwurfZiffer(c)}"
           title="Ungültiger Wurf (Fehlschritt, Kugel von der Bahn) — zählt ${fehlwurfZiffer(c)}"
           >✗<small class="hn-num-note">zählt ${fehlwurfZiffer(c)}</small></button>`;
    return `<div class="erf-numpad">
      ${[7, 8, 9, 4, 5, 6, 1, 2, 3].map(btn).join('')}
      ${linksAkt}
      ${btn(0)}
      ${rechtsAkt}
    </div>`;
  }

  // Tabelle aller Durchgaenge (Zeilen = Spieler in Rangfolge, Spalten = Durchgaenge + Summe).
  function standTabelle() {
    const rows = rangliste(c, state.bloecke);
    const kopf = Array.from({ length: runden }, (_, st) => `<th>${st + 1}</th>`).join('');
    const body = rows.map((r) => {
      const zellen = Array.from({ length: runden }, (_, st) => {
        const blk = blockOf(r.pos, st);
        return `<td class="${durchgangFertig(blk, c) ? '' : 'is-offen'}">${zellText(blk)}</td>`;
      }).join('');
      return `<tr${r.pos === state.aktiverSpieler ? ' class="is-aktiv"' : ''}>
        <th class="hn-th-name">${esc(medal(r.rang))} ${esc(r.name)}</th>
        ${zellen}
        <td class="hn-summe">${summeText(state.bloecke[r.pos])}</td>
      </tr>`;
    }).join('');
    return `<div class="hn-table-wrap">
      <table class="hn-table">
        <thead><tr><th class="hn-th-name">Spieler</th>${kopf}<th>Summe</th></tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>`;
  }

  function standScreen() {
    const fertig = spielFertig(c, state.bloecke);
    const rows = rangliste(c, state.bloecke);
    const sieger = rows.filter((r) => r.rang === 1 && r.gespielt);
    const variante = VARIANTEN.find((v) => v.key === c.variante) || VARIANTEN[0];
    const siegerZeile = sieger.length
      ? `<p class="hn-sieger">${fertig ? '🎉 ' : ''}${esc(sieger.map((r) => r.name).join(' & '))}
           <span>${formatZahl(sieger[0].summe, c)}</span></p>`
      : '<p class="hn-sieger"><span>Noch kein gewerteter Durchgang</span></p>';
    return `
      <div class="erf-stats-screen" role="dialog" aria-modal="true" aria-label="Stand">
        <header class="page-header">
          <button type="button" class="back-btn" data-act="stand-close" aria-label="Zurück zur Erfassung">←</button>
          <h1 class="page-title">${fertig ? 'Ergebnis' : 'Stand'}</h1>
        </header>
        <div class="hn-stand-body">
          <p class="hn-regel">${esc(variante.label)} · ${esc(regelText())}</p>
          ${siegerZeile}
          ${standTabelle()}
          <div class="erf-actions hn-actions">
            ${fertig
              ? '<button type="button" class="erf-btn" data-act="weiter">↩ Weiter erfassen</button>'
              : '<button type="button" class="erf-btn" data-act="stand-close">↩ Weiter erfassen</button>'}
            ${fertig ? '' : '<button type="button" class="erf-btn" data-act="beenden">Spiel beenden</button>'}
            <a class="erf-btn done" href="#/neues-spiel">Neues Spiel</a>
          </div>
        </div>
      </div>`;
  }

  // Kurzfassung der Regeln fuer die Kopf-/Standzeile.
  function regelText() {
    const platz = PLATZIERUNGEN.find((p) => p.key === c.platzierung);
    const teile = [`${stellen} Stellen`, runden > 1 ? `${runden} Durchgänge` : '1 Durchgang'];
    if (platz) teile.push(platz.label);
    if (istNiedrig) teile.push(`Durchläufer zählt ${ziffer(0, false, c)}`);
    return teile.join(' · ');
  }

  function template() {
    if (standOpen) return standScreen();
    const blk = current();
    return `
      <header class="page-header">
        <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
        <h1 class="page-title hn-title" title="${istNiedrig ? 'Die niedrigste Summe gewinnt' : 'Die höchste Summe gewinnt'}">
          <span class="hn-titel-pfeil" aria-hidden="true">${istNiedrig ? '↓' : '↑'}</span>${esc(varianteLabel)}</h1>
        <button type="button" class="erf-head-undo hn-stand-btn" data-act="stand-open" aria-label="Stand anzeigen">📊</button>
      </header>
      ${livestand()}
      <div class="erf-satz hn-board">
        <div class="hn-head">
          <span class="hn-head-name">${esc(playerName(state.aktiverSpieler))}</span>
          <span class="hn-head-round">${runden > 1 ? `Durchgang ${state.aktiverSatz + 1}/${runden}` : regelText()}</span>
        </div>
        ${stellenStreifen()}
        <p class="hn-hint">${hinweis()}</p>
        ${durchgangFertig(blk, c) || !blk.wuerfe.length ? ''
          : `<p class="hn-sum"><strong>${hausnummerText(blk, c)}</strong> <small>zählt erst, wenn der Durchgang voll ist</small></p>`}
        ${numpad()}
      </div>
      <div id="erf-toast" class="erf-toast"></div>`;
  }

  function render() {
    root.innerHTML = template();
    wire();
  }

  function wire() {
    root.querySelectorAll('[data-zug]').forEach((b) =>
      b.addEventListener('click', () => {
        const [sp, st] = b.dataset.zug.split('-').map((n) => parseInt(n, 10));
        selectZug(sp, st);
      }));
    root.querySelectorAll('[data-stelle]').forEach((b) =>
      b.addEventListener('click', () => tapStelle(parseInt(b.dataset.stelle, 10))));
    root.querySelectorAll('[data-num]').forEach((b) =>
      b.addEventListener('click', () => eingabe(parseInt(b.dataset.num, 10), false)));
    root.querySelectorAll('[data-act]').forEach((b) =>
      b.addEventListener('click', () => {
        const act = b.dataset.act;
        if (act === 'undo') undo();
        else if (act === 'fehl') eingabe(0, true);
        else if (act === 'delete') loescheWurf();
        else if (act === 'cancel-edit') { editIdx = null; render(); }
        else if (act === 'stand-open') { standOpen = true; render(); }
        else if (act === 'stand-close') { standOpen = false; render(); }
        else if (act === 'beenden') beenden();
        else if (act === 'weiter') weiterErfassen();
      }));
  }

  function toast(msg) {
    const el = root.querySelector('#erf-toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
  }

  // Tastatur am PC: Ziffern erfassen, Rücktaste nimmt zurück.
  function onKey(ev) {
    if (standOpen || ev.ctrlKey || ev.altKey || ev.metaKey) return;
    const t = ev.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
    if (ev.key >= '0' && ev.key <= '9') { eingabe(parseInt(ev.key, 10), false); ev.preventDefault(); }
    else if (ev.key === 'Backspace') { undo(); ev.preventDefault(); }
  }
  window.addEventListener('keydown', onKey);
  const onUnmount = () => {
    window.removeEventListener('keydown', onKey);
    window.removeEventListener(UNMOUNT_EVENT, onUnmount);
    clearTimeout(toastTimer);
  };
  window.addEventListener(UNMOUNT_EVENT, onUnmount);

  render();
  return root;
}
