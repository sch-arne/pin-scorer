// „Wurfdaten einlesen": die CSV-Dateien der Bahnanlage in ein BESTEHENDES Spiel übernehmen.
//
// Hintergrund: die Anlage schreibt je Spieler eine Datei mit einem Spalten-Tripel pro Bahn
// (Holz, Wurfbild, Zeit) — siehe logic/wurf-csv-import.js. Sie kennt Bahn und Wurfnummer,
// aber weder Satz noch Teilsatz noch Aufstellung. Diese Ansicht legt beides zusammen: sie
// ordnet jede Datei über den Namen einem Slot der Aufstellung und jede Bahn-Spalte über den
// BAHNPLAN des Spiels einem Satz zu — und zeigt VOR dem Schreiben, was sie gefunden hat.
//
// Warum eine eigene Ansicht und kein stiller Import: eingelesene Würfe überschreiben
// Erfassungsstand. Jede Datei bekommt daher eine Zeile mit Zuordnung, Satz/Bahn/Holz und
// allen Plausibilitäts-Befunden, und erst ein Knopf schreibt. Unvollständige Dateien (ein
// abgebrochener Export) sind dabei VORAUSGEWÄHLT AUS — der häufigste Fall ist, dass noch
// gespielt wurde, als exportiert wurde, und dann will man sie meist nicht.
//
// Mehrgeräte: in einem geteilten Spiel darf nur das Gerät schreiben, das den Spieler hält.
// Vor dem Schreiben werden die betroffenen Spieler deshalb übernommen (sync.claimPlayer) —
// genau wie beim Tippen auf „Übernehmen" in der Erfassung. Verweigert die Datenbank das
// (anderes Gerät erfasst gerade), bleibt diese Datei ungeschrieben und wird genannt.

import { currentQuery } from '../router.js';
import { getActiveGame, getGame, saveErfassung, setGameStatus } from '../store.js';
import { esc, fehlerText } from '../util.js';
import { gameBaseStatus } from '../logic/wettkampf.js';
import { teilsatzRanges } from '../logic/teilsaetze.js';
import {
  baueImportPlan, istImportierbar, importierbareSaetze, schwere,
} from '../logic/wurf-csv-import.js';

const MODUS_LBL = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz-Abräumen' };
const ART_ICON = { fehler: '⛔', warnung: '⚠️', hinweis: 'ℹ️' };

// Vollständig = alle Sätze des Spiels da und jeder davon voll. Nur solche Dateien sind
// vorausgewählt (siehe Kopf).
function istVollstaendig(eintrag, config) {
  if (!eintrag || eintrag.spielerIndex < 0) return false;
  if (eintrag.saetze.length !== (config.saetze || 0)) return false;
  return eintrag.saetze.every((s) => s.block.done);
}

export function importWurfdatenView() {
  const gameId = currentQuery().get('game') || getActiveGame();
  const game = gameId ? getGame(gameId) : null;

  const root = document.createElement('div');
  root.className = 'view view-page';

  if (!game || !game.config) {
    root.innerHTML = `
      <header class="page-header">
        <a class="back-btn" href="#/menu" aria-label="Zurück">←</a>
        <h1 class="page-title">Wurfdaten einlesen</h1>
      </header>
      <p class="field-hint">Kein offenes Spiel gefunden. Öffne zuerst das Spiel, in das die Würfe sollen.</p>`;
    return root;
  }

  const config = game.config;
  const ranges = teilsatzRanges(config);
  const zurueck = '#/spiel-laufend';

  // ── Zustand dieser Ansicht ────────────────────────────────────────────────
  let dateien = [];            // [{ dateiname, text }] — die gelesenen Rohdateien
  let zuordnung = {};          // dateiname -> Spieler-Index (Hand-Zuordnung schlägt Automatik)
  let gewaehlt = {};           // dateiname -> bool (importieren?)
  let plan = [];               // baueImportPlan(...)
  let msg = '';
  let msgArt = '';             // '' | 'ok' | 'warn' | 'err'
  let laeuft = false;

  function neuRechnen({ auswahlZuruecksetzen = false } = {}) {
    plan = baueImportPlan(dateien, game, zuordnung);
    plan.forEach((e) => {
      if (auswahlZuruecksetzen || !(e.dateiname in gewaehlt)) {
        gewaehlt[e.dateiname] = istImportierbar(e) && istVollstaendig(e, config);
      }
      if (!istImportierbar(e)) gewaehlt[e.dateiname] = false;
    });
  }

  // ── Bausteine der Anzeige ────────────────────────────────────────────────
  const programm = () => `${config.saetze} Sätze × ${config.wuerfeProSatz} Würfe · `
    + ranges.map((r) => `${r.soll}× ${MODUS_LBL[r.modus] || r.modus}`).join(' + ');

  function befundListe(befunde) {
    if (!befunde || !befunde.length) return '';
    return `<ul class="wdi-befunde">${befunde.map((b) =>
      `<li class="wdi-b-${esc(b.art)}">${ART_ICON[b.art] || ''} ${esc(b.text)}</li>`).join('')}</ul>`;
  }

  function spielerWahl(eintrag) {
    const liste = config.spielerListe || [];
    const opts = liste.map((p, i) =>
      `<option value="${i}"${i === eintrag.spielerIndex ? ' selected' : ''}>${esc(p.name)} (Pos. ${i + 1})</option>`).join('');
    return `
      <label class="wdi-zuordnung">
        <span class="acc-label">Spieler</span>
        <select class="select-full sm" data-zuordnung="${esc(eintrag.dateiname)}">
          <option value="-1"${eintrag.spielerIndex < 0 ? ' selected' : ''}>— nicht einlesen —</option>
          ${opts}
        </select>
      </label>`;
  }

  function satzZeilen(eintrag) {
    if (!eintrag.saetze.length) return '';
    return `
      <table class="wdi-saetze">
        <thead><tr><th>Satz</th><th>Bahn</th><th>Würfe</th><th>Holz</th><th></th></tr></thead>
        <tbody>
          ${eintrag.saetze.map((s) => `
            <tr class="wdi-s-${esc(schwere(s.befunde))}">
              <td>${s.satz + 1}</td>
              <td>${s.bahn == null ? '–' : s.bahn}</td>
              <td>${s.wuerfe}${config.wuerfeProSatz ? `<span class="wdi-soll">/${config.wuerfeProSatz}</span>` : ''}</td>
              <td><b>${s.holz}</b></td>
              <td class="wdi-s-befund">${befundListe(s.befunde)}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  }

  function dateiKarte(eintrag) {
    const ok = istImportierbar(eintrag);
    const saetze = importierbareSaetze(eintrag);
    const holz = saetze.reduce((a, s) => a + s.holz, 0);
    const wuerfe = saetze.reduce((a, s) => a + s.wuerfe, 0);
    const voll = istVollstaendig(eintrag, config);
    return `
      <section class="wdi-karte wdi-k-${esc(schwere(eintrag.befunde.concat(...eintrag.saetze.map((s) => s.befunde))))}">
        <header class="wdi-k-head">
          <label class="wdi-k-pick">
            <input type="checkbox" data-pick="${esc(eintrag.dateiname)}"${gewaehlt[eintrag.dateiname] ? ' checked' : ''}${ok ? '' : ' disabled'}>
            <span class="wdi-k-name">${esc(eintrag.spielerName || eintrag.dateiname)}</span>
          </label>
          <span class="wdi-k-summe">${wuerfe} Würfe · <b>${holz}</b> Holz${voll ? '' : ' · <em>unvollständig</em>'}</span>
        </header>
        <p class="wdi-k-datei">${esc(eintrag.dateiname)}${eintrag.warm ? ` · ${eintrag.warm} Einspielwurf${eintrag.warm === 1 ? '' : 'e'} übersprungen` : ''}</p>
        ${spielerWahl(eintrag)}
        ${befundListe(eintrag.befunde)}
        ${eintrag.fehler && eintrag.fehler.length ? befundListe(eintrag.fehler.map((t) => ({ art: 'fehler', text: t }))) : ''}
        ${satzZeilen(eintrag)}
      </section>`;
  }

  function zusammenfassung() {
    const aktiv = plan.filter((e) => gewaehlt[e.dateiname]);
    const saetze = aktiv.reduce((a, e) => a + importierbareSaetze(e).length, 0);
    const wuerfe = aktiv.reduce((a, e) => a + importierbareSaetze(e).reduce((x, s) => x + s.wuerfe, 0), 0);
    return { aktiv, saetze, wuerfe };
  }

  function render() {
    const { aktiv, saetze, wuerfe } = zusammenfassung();
    root.innerHTML = `
      <header class="page-header">
        <a class="back-btn" href="${zurueck}" aria-label="Zurück">←</a>
        <h1 class="page-title">Wurfdaten einlesen</h1>
      </header>
      <div class="wdi-body">
        <p class="wdi-intro">Die CSV-Dateien der Bahnanlage — <b>eine Datei je Spieler</b>, darin je Bahn die Spalten
          Holz, Wurfbild und Zeit. Zugeordnet wird über den <b>Dateinamen</b> (Spieler) und den <b>Bahnplan</b> des
          Spiels (Satz). Das <b>Warmwerfen wird nie eingelesen</b>.</p>
        <p class="wdi-spiel">Ziel: <b>${esc(config.anlageName || 'Spiel')}</b> · ${esc(programm())} ·
          ${(config.spielerListe || []).length} Spieler${game.linked ? ' · geteilt' : ' · nur lokal'}</p>

        <label class="btn-mini wdi-pick-btn">📄 CSV-Dateien wählen
          <input type="file" accept=".csv,text/csv" multiple hidden id="wdi-files">
        </label>
        ${dateien.length ? `<button type="button" class="link-btn" data-act="leeren">Auswahl verwerfen</button>` : ''}

        ${plan.length ? `
          <div class="wdi-bulk">
            <button type="button" class="btn-mini" data-act="alle">Alle auswählen</button>
            <button type="button" class="btn-mini" data-act="keine">Keine</button>
          </div>
          <div class="wdi-liste">${plan.map(dateiKarte).join('')}</div>
          <div class="wdi-foot">
            <p class="wdi-summe">${aktiv.length} Datei${aktiv.length === 1 ? '' : 'en'} · ${saetze} Sätze · ${wuerfe} Würfe werden übernommen</p>
            <button type="button" class="erf-btn done wdi-go" data-act="go"${aktiv.length && !laeuft ? '' : ' disabled'}>
              ${laeuft ? 'Schreibe …' : '⤒ Würfe übernehmen'}</button>
          </div>` : '<p class="field-hint">Noch keine Dateien gewählt.</p>'}

        <p class="wdi-msg is-${esc(msgArt || 'none')}" role="status">${esc(msg)}</p>
      </div>`;
    binde();
  }

  // ── Ereignisse ───────────────────────────────────────────────────────────
  function binde() {
    const inp = root.querySelector('#wdi-files');
    if (inp) {
      inp.addEventListener('change', async () => {
        const liste = Array.from(inp.files || []);
        if (!liste.length) return;
        msg = 'Lese Dateien …'; msgArt = ''; render();
        try {
          const neu = await Promise.all(liste.map(async (f) => ({ dateiname: f.name, text: await f.text() })));
          // Dieselbe Datei nicht zweimal: ein zweites Wählen ERSETZT den gleichnamigen Stand.
          const namen = neu.map((d) => d.dateiname);
          dateien = dateien.filter((d) => !namen.includes(d.dateiname)).concat(neu);
          neuRechnen();
          msg = `${dateien.length} Datei${dateien.length === 1 ? '' : 'en'} gelesen.`;
          msgArt = 'ok';
        } catch (e) {
          msg = 'Dateien konnten nicht gelesen werden: ' + fehlerText(e);
          msgArt = 'err';
        }
        render();
      });
    }

    root.querySelectorAll('[data-pick]').forEach((cb) =>
      cb.addEventListener('change', () => {
        gewaehlt[cb.dataset.pick] = cb.checked;
        render();
      }));

    root.querySelectorAll('[data-zuordnung]').forEach((sel) =>
      sel.addEventListener('change', () => {
        zuordnung[sel.dataset.zuordnung] = parseInt(sel.value, 10);
        // Eine geänderte Zuordnung verschiebt Sätze und Befunde — Auswahl neu bestimmen.
        delete gewaehlt[sel.dataset.zuordnung];
        neuRechnen();
        render();
      }));

    root.querySelectorAll('[data-act]').forEach((b) =>
      b.addEventListener('click', () => {
        const act = b.dataset.act;
        if (act === 'leeren') {
          dateien = []; zuordnung = {}; gewaehlt = {}; plan = []; msg = ''; msgArt = '';
          render();
        } else if (act === 'alle') {
          plan.forEach((e) => { gewaehlt[e.dateiname] = istImportierbar(e); });
          render();
        } else if (act === 'keine') {
          plan.forEach((e) => { gewaehlt[e.dateiname] = false; });
          render();
        } else if (act === 'go') {
          uebernehmen();
        }
      }));
  }

  // ── Schreiben ────────────────────────────────────────────────────────────
  async function uebernehmen() {
    const { aktiv } = zusammenfassung();
    if (!aktiv.length || laeuft) return;
    laeuft = true; msg = 'Schreibe …'; msgArt = ''; render();

    // Erfassungsstand frisch aus dem Speicher holen: zwischen Dateiwahl und Knopfdruck kann
    // auf einem anderen Gerät (oder in einem zweiten Tab) etwas dazugekommen sein.
    const frisch = getGame(game.id) || game;
    const state = frisch.erfassung && Array.isArray(frisch.erfassung.bloecke)
      ? frisch.erfassung
      : { aktiverSpieler: 0, aktiverSatz: 0, bloecke: [] };

    // Mehrgeräte: Spieler übernehmen, bevor geschrieben wird (siehe Kopf).
    let sync = null;
    let meGeraet = null;
    const gesperrt = [];
    if (frisch.linked && frisch.remoteId) {
      try {
        sync = await import('../backend/sync.js');
        meGeraet = await sync.ensureGeraet();
      } catch (e) {
        sync = null;
        msg = 'Ohne Verbindung: die Würfe werden nur lokal gespeichert und beim nächsten '
          + 'Öffnen des Spiels hochgeschrieben.';
        msgArt = 'warn';
      }
    }

    const owners = frisch.spielerOwners || {};
    const geschrieben = [];
    for (const e of aktiv) {
      const sp = e.spielerIndex;
      if (sync) {
        const pid = owners[sp] && owners[sp].id;
        if (!pid) { gesperrt.push(`${e.spielerName} (nicht in der geteilten Aufstellung)`); continue; }
        if (owners[sp].besitzer !== meGeraet) {
          let ok = false;
          try { ok = await sync.claimPlayer(pid); } catch (_) { ok = false; }
          if (!ok) { gesperrt.push(`${e.spielerName} (wird auf einem anderen Gerät erfasst)`); continue; }
          owners[sp] = { ...owners[sp], besitzer: meGeraet, heartbeat: new Date().toISOString() };
        }
      }
      if (!Array.isArray(state.bloecke[sp])) state.bloecke[sp] = [];
      importierbareSaetze(e).forEach((s) => {
        state.bloecke[sp][s.satz] = s.block;
        geschrieben.push({ sp, satz: s.satz, block: s.block, pid: owners[sp] && owners[sp].id });
      });
    }

    if (!geschrieben.length) {
      laeuft = false;
      msg = 'Nichts geschrieben: ' + (gesperrt.join(', ') || 'keine übernehmbaren Sätze.');
      msgArt = 'err';
      render();
      return;
    }

    // Lücken im Blöcke-Raster füllen — ein Satz, der nie erfasst wurde, darf nicht `undefined`
    // bleiben, sonst stolpert die Erfassung beim Öffnen darüber.
    const leer = () => ({
      wuerfe: [], kegel: [], koenig: [],
      overrides: (config.teilsaetze || []).map(() => null), done: false,
    });
    for (let sp = 0; sp < (config.spielerListe || []).length; sp += 1) {
      if (!Array.isArray(state.bloecke[sp])) state.bloecke[sp] = [];
      for (let st = 0; st < (config.saetze || 0); st += 1) {
        if (!state.bloecke[sp][st]) state.bloecke[sp][st] = leer();
      }
    }

    if (saveErfassung(frisch.id, state) === null) {
      laeuft = false;
      msg = 'Speichern fehlgeschlagen — Speicher voll?';
      msgArt = 'err';
      render();
      return;
    }
    // Status neu ableiten: ein eingelesener offener Satz macht aus einem „beendeten" Spiel
    // wieder ein laufendes, ein vollständiger Import kann es beenden.
    const nachher = getGame(frisch.id);
    const status = gameBaseStatus(nachher);
    if (nachher && nachher.status !== status) setGameStatus(frisch.id, status);

    // Hochschreiben. Jeder Block einzeln — ein Fehlschlag soll die anderen nicht mitnehmen.
    let gepusht = 0;
    const fehlgeschlagen = [];
    if (sync) {
      for (const g of geschrieben) {
        if (!g.pid) continue;
        try { await sync.pushBlock(frisch.remoteId, g.pid, g.satz, g.block); gepusht += 1; } catch (err) {
          fehlgeschlagen.push(`Pos. ${g.sp + 1} Satz ${g.satz + 1}`);
        }
      }
    }

    laeuft = false;
    const teile = [`${geschrieben.length} Sätze übernommen`];
    if (sync) teile.push(gepusht === geschrieben.length ? 'alle hochgeschrieben' : `${gepusht} hochgeschrieben`);
    if (fehlgeschlagen.length) teile.push(`nicht hochgeschrieben: ${fehlgeschlagen.join(', ')}`);
    if (gesperrt.length) teile.push(`übersprungen: ${gesperrt.join(', ')}`);
    msg = teile.join(' · ') + '.';
    msgArt = fehlgeschlagen.length || gesperrt.length ? 'warn' : 'ok';
    // Importierte Dateien aus der Liste nehmen, damit ein zweiter Klick nicht erneut schreibt.
    const fertig = aktiv.map((e) => e.dateiname);
    dateien = dateien.filter((d) => !fertig.includes(d.dateiname));
    fertig.forEach((n) => { delete gewaehlt[n]; delete zuordnung[n]; });
    neuRechnen();
    render();
  }

  render();
  return root;
}
