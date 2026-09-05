// Import eines GESPIELTEN Spiels aus dem öffentlichen Sportwinner-Ergebnisdienst.
//
// Der zweite Import-Weg neben der Brücke (views/import-sportwinner.js). Dort läuft der Import
// VOR dem Spiel auf dem Vereins-PC und die App erfasst danach jeden Wurf; hier wird ein längst
// gespieltes Spiel nachträglich aus dem Netz geholt — für Auswärtsspiele und überall dort, wo
// die Brücke nicht zur Verfügung steht.
//
// Zwei Dinge sind hier grundsätzlich anders als beim Brücken-Import:
//
//  1. DETAILGRAD. Der Ergebnisdienst kennt keine Einzelwürfe, nur Summen. Sie werden als
//     Teilsatz-Overrides eingetragen (logic/sw-web-import.js), damit Holz und Schnitt exakt
//     stimmen und 9er, Räumer und Wurfbild ehrlich leer bleiben statt erfunden zu werden.
//
//  2. DATENSCHUTZ. Die Namen der Mit- und Gegenspieler stammen aus einer öffentlichen Quelle,
//     aber diese Leute wissen von dieser App nichts. Deshalb bleiben sie ausschließlich LOKAL:
//     in die Datenbank wandert allein die eigene Ergebniszeile, und auch die ohne Namen
//     (sync.linkEigenesErgebnis). Aus demselben Grund lässt sich ein so importierter Wettkampf
//     nicht teilen — der Hub sperrt Beitritts-/Zuschauercode und Overlay.

import { esc } from '../util.js';
import {
  parseSpielListe, parseSpielerInfo, buildImportSpec, buildImportWettkampf,
} from '../logic/sw-web-import.js';
import { sektionToBahnart, parseBahnen } from '../logic/roster-import.js';
import { PRESETS, ART_LABEL } from '../logic/sportkegeln-presets.js';
import { saveGame, saveWettkampf, setActiveWettkampf, getWettkaempfe } from '../store.js';
import { bestAnlageMatch } from './import-sportwinner.js';
import * as swWeb from '../backend/sw-web.js';

const norm = (s) => (s || '').toLowerCase().replace(/\s+/g, ' ').trim();

export function importSwWebView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  const state = {
    phase: 'laden',        // laden | auswahl | anlegen | fertig | fehler
    fehler: '',
    msg: '',
    // Auswahlkette
    saisons: [], saison: '',
    sektion: 2,
    ligen: [], liga: '', ligenLaden: false,
    spieltage: [], spieltag: '',
    partien: [], partie: null, partienLaden: false,
    // Spielbericht + daraus abgeleitetes Spec
    spec: null, berichtLaden: false,
    anlagen: [], anlageId: '', anlageBahnen: [], playedLanes: [],
    ichKey: '',            // "<mannschaftId>|<teamPos>" — wer bin ich?
    warnungen: [],
  };

  // --- Laden ----------------------------------------------------------------

  async function ladeSaisons() {
    try {
      state.saisons = await swWeb.saisons();
      state.saison = state.saisons.length ? String(state.saisons[0].id) : '';
      state.phase = 'auswahl';
      render();
      if (state.saison) ladeLigen();
    } catch (e) {
      state.phase = 'fehler';
      state.fehler = e.message || 'Ergebnisdienst nicht erreichbar.';
      render();
    }
  }

  async function ladeLigen() {
    state.ligenLaden = true; state.ligen = []; state.liga = '';
    state.spieltage = []; state.spieltag = ''; state.partien = []; state.partie = null;
    state.spec = null;
    render();
    try {
      state.ligen = await swWeb.alleLigen(state.saison, state.sektion);
    } catch (e) {
      state.fehler = e.message || 'Ligen konnten nicht geladen werden.';
    }
    state.ligenLaden = false;
    render();
  }

  async function ladeSpieltageUndPartien() {
    state.partienLaden = true; state.partien = []; state.partie = null; state.spec = null;
    render();
    try {
      // Spieltage sind nur die Filterliste — die Partien kommen unabhängig davon.
      state.spieltage = await swWeb.spieltage(state.saison, state.sektion, state.liga);
    } catch (e) { state.spieltage = []; }
    try {
      const rows = await swWeb.spiele(state.saison, state.sektion, state.liga, state.spieltag);
      state.partien = parseSpielListe(rows).filter((p) => p.gespielt);
      if (!state.partien.length) state.fehler = 'Keine gespielte Partie in dieser Auswahl.';
      else state.fehler = '';
    } catch (e) {
      state.fehler = e.message || 'Partien konnten nicht geladen werden.';
    }
    state.partienLaden = false;
    render();
  }

  // Spielbericht der gewählten Partie holen und daraus das Import-Spec bauen.
  async function ladeBericht(partie) {
    state.partie = partie; state.spec = null; state.berichtLaden = true; state.fehler = '';
    state.ichKey = '';
    render();
    try {
      const preset = sektionToBahnart(state.sektion) || 'schere';
      const rows = await swWeb.spielbericht(
        state.saison, state.sektion, partie.idSpiel, partie.wertung,
      );
      const bericht = parseSpielerInfo(rows, { saetze: PRESETS[preset].saetze });
      const spec = buildImportSpec(partie, bericht);
      spec.preset = preset;
      state.spec = spec;
      state.warnungen = spec.warnungen;
      await ladeAnlage();
    } catch (e) {
      state.fehler = e.message || 'Spielbericht konnte nicht gelesen werden.';
    }
    state.berichtLaden = false;
    render();
  }

  // Anlage + bespielte Bahnen: die Bahnen kennt nur GetBahnanlage (je Heimmannschaft).
  async function ladeAnlage() {
    const spec = state.spec;
    const heim = spec.mannschaften[0].name;
    let ort = null;
    try {
      const anlagen = await swWeb.bahnanlagen(state.saison, state.sektion, state.liga);
      ort = anlagen.find((a) => norm(a.mannschaft) === norm(heim)) || null;
    } catch (e) { /* ohne Spielort weiter — Bahnen lassen sich von Hand setzen */ }

    state.playedLanes = parseBahnen(ort && ort.bahnen);
    if (!state.playedLanes.length) state.playedLanes = [1, 2, 3, 4];

    try {
      const mod = await import('../backend/anlagen.js');
      state.anlagen = (await mod.listAnlagen()) || [];
      const treffer = ort ? bestAnlageMatch(state.anlagen, {
        name: ort.anlage, plz: ort.plz, ort: ort.ort,
      }) : null;
      state.anlageId = treffer ? treffer.id : '';
      if (state.anlageId) state.anlageBahnen = (await mod.listBahnen(state.anlageId)) || [];
    } catch (e) { /* offline / kein Konto: Anlage bleibt leer, Import geht trotzdem */ }
  }

  // --- Anlegen --------------------------------------------------------------

  function ichPosition(game) {
    const liste = (game.config && game.config.spielerListe) || [];
    return liste.findIndex((sp) => `${sp.mannschaftId}|${sp.teamPos}` === state.ichKey);
  }

  async function anlegen() {
    const spec = state.spec;
    if (!spec || !state.ichKey) return;
    state.phase = 'anlegen'; state.msg = 'Baue Wettkampf …'; render();
    try {
      const anlage = state.anlagen.find((a) => a.id === state.anlageId) || null;
      const { wettkampf, games } = buildImportWettkampf(spec, {
        playedLanes: state.playedLanes,
        anlageId: state.anlageId || null,
        anlageName: anlage ? anlage.name : '',
        anlageBahnen: state.anlageBahnen,
      });
      // Herkunft vervollständigen: Duplikat-Erkennung und Teilen-Sperre hängen daran.
      Object.assign(wettkampf.swWeb, {
        saison: state.saison, sektion: state.sektion, liga: state.liga,
      });
      wettkampf.ichSlot = state.ichKey;

      games.forEach((g) => saveGame(g));
      saveWettkampf(wettkampf);
      setActiveWettkampf(wettkampf.id);

      // Nur die EIGENE Ergebniszeile in die Datenbank — Namen bleiben auf diesem Gerät.
      state.msg = 'Übertrage dein Ergebnis …'; render();
      const meineMannschaft = spec.mannschaften
        .find((m) => state.ichKey.startsWith(`${m.id}|`));
      const sync = await import('../backend/sync.js');
      let uebertragen = 0;
      for (const g of games) {
        const pos = ichPosition(g);
        if (pos < 0) continue;
        const { remoteId } = await sync.linkEigenesErgebnis(g, {
          position: pos,
          mannschaftName: meineMannschaft ? meineMannschaft.name : '',
        });
        g.linked = true;
        g.remoteId = remoteId;
        saveGame(g);
        uebertragen += 1;
      }
      state.msg = uebertragen
        ? `Importiert — ${uebertragen} Durchgang${uebertragen > 1 ? 'e' : ''} in deiner Statistik.`
        : 'Importiert — lokal gespeichert (keine eigene Position gefunden).';
      state.phase = 'fertig';
      render();
    } catch (e) {
      const m = (e && e.message) || '';
      state.phase = 'auswahl';
      state.fehler = /angemeldet|login|auth|jwt|permission|row-level/i.test(m)
        ? 'Konto nötig — bitte unter „Spieler" anmelden und erneut versuchen.'
        : (m || 'Import fehlgeschlagen.');
      render();
    }
  }

  // --- Darstellung ----------------------------------------------------------

  const opt = (v, label, sel) =>
    `<option value="${esc(String(v))}"${String(v) === String(sel) ? ' selected' : ''}>${esc(label)}</option>`;

  function auswahlSection() {
    const s = state;
    return `
      <section class="field">
        <label class="field-label" for="swb-saison">Saison</label>
        <select class="join-input select-full" id="swb-saison" data-field="saison">
          ${s.saisons.map((x) => opt(x.id, `${x.jahr}${x.aktiv ? ' (aktuell)' : ''}`, s.saison)).join('')}
        </select>
      </section>
      <section class="field">
        <label class="field-label" for="swb-sektion">Disziplin</label>
        <select class="join-input select-full" id="swb-sektion" data-field="sektion">
          ${swWeb.SEKTIONEN.map((x) => opt(x.id, x.label, s.sektion)).join('')}
        </select>
      </section>
      <section class="field">
        <label class="field-label" for="swb-liga">Liga</label>
        <select class="join-input select-full" id="swb-liga" data-field="liga" ${s.ligenLaden ? 'disabled' : ''}>
          <option value="">${s.ligenLaden ? 'Lade Ligen …' : 'Bitte wählen'}</option>
          ${s.ligen.map((x) => opt(x.id, x.name, s.liga)).join('')}
        </select>
      </section>
      ${s.liga ? `
      <section class="field">
        <label class="field-label" for="swb-spieltag">Spieltag</label>
        <select class="join-input select-full" id="swb-spieltag" data-field="spieltag">
          <option value="">Alle Spieltage</option>
          ${s.spieltage.map((x) => opt(x.id, x.name, s.spieltag)).join('')}
        </select>
      </section>` : ''}
      ${partienSection()}`;
  }

  function partienSection() {
    const s = state;
    if (!s.liga) return '';
    if (s.partienLaden) return '<p class="stats-sub">Lade Partien …</p>';
    if (!s.partien.length) return '';
    return `
      <section class="field">
        <label class="field-label">Partie</label>
        <div class="stat-list">
          ${s.partien.map((p) => `
            <button type="button" class="resume-main" data-partie="${esc(p.idSpiel)}"
              ${s.partie && s.partie.idSpiel === p.idSpiel ? 'aria-current="true"' : ''}>
              <span class="tile-label">${esc(p.heim)} – ${esc(p.gast)}</span>
              <span class="tile-desc">${esc(p.termin)} · ${esc(String(p.heimWert))}:${esc(String(p.gastWert))}</span>
            </button>`).join('')}
        </div>
      </section>`;
  }

  function berichtSection() {
    const s = state;
    if (s.berichtLaden) return '<p class="stats-sub">Lade Spielbericht …</p>';
    const spec = s.spec;
    if (!spec) return '';

    const ohneSaetze = Object.values(spec.ergebnisse).some((e) => !e.saetze);
    if (ohneSaetze) {
      return `<section class="field">
        <p class="field-hint">⚠ Der Ergebnisdienst liefert für diese Partie nur Gesamtsummen je
          Spieler, keine Satzergebnisse. Ein Import würde die Sätze erfinden — deshalb ist er
          hier gesperrt.</p>
      </section>`;
    }

    const dup = getWettkaempfe().find((w) => w.swWeb && w.swWeb.idSpiel === spec.idSpiel);
    const anlage = s.anlagen.find((a) => a.id === s.anlageId);
    const teams = spec.mannschaften.map((m) => `
      <div class="field">
        <span class="field-label">${esc(m.name)}</span>
        <div class="stat-list">
          ${m.spieler.map((p) => {
            const key = `${m.id}|${p.teamPos}`;
            const erg = spec.ergebnisse[key];
            const holz = erg && erg.saetze
              ? erg.saetze.reduce((n, x) => n + (x.holz || 0), 0) : 0;
            return `<button type="button" class="resume-main" data-ich="${esc(key)}"
                ${s.ichKey === key ? 'aria-current="true"' : ''}>
                <span class="tile-label">${s.ichKey === key ? '★ ' : ''}${esc(p.name)}</span>
                <span class="tile-desc">${holz} Holz</span>
              </button>`;
          }).join('')}
        </div>
      </div>`).join('');

    return `
      ${dup ? `<section class="field"><p class="field-hint">⚠ Diese Partie ist bereits
        importiert („${esc(dup.name || '—')}").</p></section>` : ''}
      <section class="field">
        <span class="field-label">Programm</span>
        <span class="readout">${esc(ART_LABEL[spec.preset] || spec.preset)}
          <small>· ${PRESETS[spec.preset].saetze}×${PRESETS[spec.preset].wuerfeProSatz}
          · Bahnen ${state.playedLanes.join(', ')}</small></span>
      </section>
      <section class="field">
        <label class="field-label" for="swb-anlage">Anlage</label>
        <select class="join-input select-full" id="swb-anlage" data-field="anlageId">
          <option value="">Ohne Anlage (nur lokal)</option>
          ${s.anlagen.map((a) => opt(a.id, a.name, s.anlageId)).join('')}
        </select>
        ${anlage ? '' : '<p class="field-hint">Ohne Anlage bleibt der Wettkampf rein lokal.</p>'}
      </section>
      <section class="field">
        <label class="field-label">Wer bist du? <small class="field-note">· Pflicht</small></label>
        ${teams}
        <p class="field-hint">${s.ichKey
          ? '★ Nur die Ergebnisse dieses Spielers gehen in deine Statistik.'
          : 'Wähle deinen Namen — der Ergebnisdienst liefert keine LizenzIDen, '
            + 'die Zuordnung geht deshalb nur von Hand.'}</p>
      </section>
      <section class="field">
        <p class="field-hint">📉 Der Ergebnisdienst kennt keine Einzelwürfe. Holz, Schnitt und
          bester Satz stimmen exakt; 9er, Räumer-Tempo, Fehlwürfe und Wurfbild bleiben bei
          importierten Spielen leer — sie lassen sich aus Summen nicht rekonstruieren.</p>
        ${spec.nurHolz ? `<p class="field-hint">➗ Für diese Partie nennt der Bericht nur das
          Satz-Holz, nicht die Trennung in Volle und Abräumen. Eingetragen wird deshalb allein
          das Satzergebnis — es stimmt exakt. Eine Aufteilung auf Volle und Abräumen wäre
          geraten und unterbleibt; nach Teilsätzen lässt sich dieses Spiel folglich nicht
          auswerten.</p>` : ''}
        <p class="field-hint">🔒 Datenschutz: Die Namen aller Spieler bleiben auf DIESEM Gerät.
          In die Datenbank geht ausschließlich deine eigene Ergebniszeile, und auch die ohne
          Namen. Ein so importierter Wettkampf lässt sich deshalb nicht teilen und nicht im
          Overlay zeigen.</p>
      </section>
      ${s.warnungen.length ? `<section class="field">${s.warnungen
        .map((w) => `<p class="field-hint">⚠ ${esc(w)}</p>`).join('')}</section>` : ''}`;
  }

  function render() {
    const s = state;
    if (s.phase === 'laden') {
      root.innerHTML = '<header class="app-header"><h1 class="brand">Aus dem Ergebnisdienst</h1>'
        + '</header><p class="stats-sub">Lade Saisons …</p>';
      return;
    }
    if (s.phase === 'fehler') {
      // Eine Sackgasse mit nur „Zurück" ist keine Auskunft: hier steht, WORAN es liegt, und
      // beide Wege weiter — noch einmal versuchen und (der haeufigste Grund) anmelden.
      root.innerHTML = `
        <header class="app-header"><h1 class="brand">Aus dem Ergebnisdienst</h1></header>
        <p class="field-hint">⚠ ${esc(s.fehler)}</p>
        <div class="field-row">
          <button type="button" class="btn-primary" data-action="erneut">Erneut versuchen</button>
          <a class="erf-btn" href="#/spieler">Zum Konto</a>
          <a class="erf-btn" href="#/menu">Zurück</a>
        </div>`;
      return;
    }
    if (s.phase === 'fertig') {
      root.innerHTML = `
        <header class="app-header"><h1 class="brand">Import fertig</h1></header>
        <p class="stats-sub">${esc(s.msg)}</p>
        <div class="field-row">
          <a class="btn-primary" href="#/wettkampf">Zum Wettkampf</a>
          <a class="erf-btn" href="#/statistiken">Zur Statistik</a>
        </div>`;
      return;
    }

    const kannAnlegen = !!(s.spec && s.ichKey && s.phase === 'auswahl'
      && !Object.values(s.spec.ergebnisse).some((e) => !e.saetze));
    root.innerHTML = `
      <header class="app-header">
        <h1 class="brand">Aus dem Ergebnisdienst</h1>
        <p class="tagline">Ein gespieltes Spiel per Webabfrage übernehmen</p>
      </header>
      ${s.fehler ? `<p class="field-hint">⚠ ${esc(s.fehler)}</p>` : ''}
      ${auswahlSection()}
      ${berichtSection()}
      <div class="field-row">
        <button type="button" class="btn-primary" data-action="anlegen"
          ${kannAnlegen ? '' : 'disabled'}>
          ${s.phase === 'anlegen' ? esc(s.msg || 'Importiere …') : 'Importieren'}
        </button>
        <a class="erf-btn" href="#/menu">Abbrechen</a>
      </div>`;
  }

  root.addEventListener('change', (ev) => {
    const feld = ev.target.dataset && ev.target.dataset.field;
    if (!feld) return;
    state[feld] = feld === 'sektion' ? Number(ev.target.value) : ev.target.value;
    if (feld === 'saison' || feld === 'sektion') ladeLigen();
    else if (feld === 'liga') { state.spieltag = ''; ladeSpieltageUndPartien(); }
    else if (feld === 'spieltag') ladeSpieltageUndPartien();
    else render();
  });

  root.addEventListener('click', (ev) => {
    const partie = ev.target.closest('[data-partie]');
    if (partie) {
      const p = state.partien.find((x) => x.idSpiel === partie.dataset.partie);
      if (p) ladeBericht(p);
      return;
    }
    const ich = ev.target.closest('[data-ich]');
    if (ich) { state.ichKey = ich.dataset.ich; render(); return; }
    if (ev.target.closest('[data-action="erneut"]')) {
      state.phase = 'laden'; state.fehler = '';
      render();
      ladeSaisons();
      return;
    }
    const btn = ev.target.closest('[data-action="anlegen"]');
    if (btn) anlegen();
  });

  render();
  ladeSaisons();
  return root;
}
