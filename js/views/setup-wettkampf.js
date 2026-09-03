// Setup für "Sportkegeln-Wettkampf". Zwei Tabs:
//   „Programm":     Name/Datum, Anlage (optional) + bespielte Bahnen, Bahnart, Bahnwechsel,
//                   Sätze, Würfe/Satz, Teilsätze.
//   „Mannschaften": Anzahl Mannschaften (+ Namen), je Mannschaft die Startbahn(en) aus den
//                   bespielten Bahnen, Spieler je Mannschaft.
// „Wettkampf erstellen" erzeugt DARAUS die Durchgänge (Paarkreuz): jede Mannschaft sitzt pro
// Durchgang auf ihren Bahnen; Spieler werden auf die Team-Bahnen verteilt. Namen füllt man
// danach im Hub; dort ist die Startbahn eines Spielers auf die Bahnen seiner Mannschaft begrenzt.

import { navigate } from '../router.js';
import { saveWettkampf, setActiveWettkampf, saveGame } from '../store.js';
import { esc } from '../util.js';
import { divisors, nearestDivisor, throwsPerPart } from '../logic/teilsaetze.js';
import { planDurchgaenge } from '../logic/wettkampf.js';
import { buildWettkampf } from '../logic/wettkampf-build.js';
import { MODI, BAHNWECHSEL, PRESETS, ART_LABEL } from '../logic/sportkegeln-presets.js';

const TAB_ORDER = ['programm', 'mannschaften', 'wertung'];

// Erstellbar? Die bespielten Bahnen stehen fest (mit oder ohne Anlage) und jede Mannschaft hat
// mindestens eine Startbahn. Eine Anlage ist NICHT nötig — ohne sie bleibt der Wettkampf lokal;
// das Teilen verlangt sie dann im Hub nach (views/wettkampf-hub.js).
// Absichtlich eine Funktion für BEIDE Stellen: die Prüfung stand früher doppelt (create() und
// das Ausgrauen im template) und lief beim Ändern auseinander.
function istErstellbar(s) {
  return !!(s.playedLanes.length
    && s.mannschaften.every((m) => m.lanes.length >= 1)
    && s.spielerJeMannschaft >= 1);
}
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const uid = (p) => p + Math.random().toString(36).slice(2, 8);
const sortNum = (arr) => arr.slice().sort((a, b) => a - b);

function defaultState() {
  const p = PRESETS.bohle;
  return {
    tab: 'programm',
    name: '',
    datum: new Date().toISOString().slice(0, 10),
    // Programm:
    preset: 'bohle',
    saetze: p.saetze,
    wuerfeProSatz: p.wuerfeProSatz,
    teilsaetze: [...p.teilsaetze],
    bahnwechsel: p.bahnwechsel,
    // Anlage (optional). MIT Anlage sind die bespielten Bahnen deren echte Bahnen; OHNE Anlage
    // wählt man frei Anzahl + erste Bahn (wie im Training-Setup). Ein Wettkampf ohne Anlage
    // bleibt LOKAL — geteilt (Mehrgeräte/OBS-Overlay) werden kann er erst, wenn ihm im Hub
    // eine Anlage zugewiesen wurde. Grund: die Anlage ist der gemeinsame Bezugspunkt, über den
    // andere Geräte und das Overlay die Bahnen derselben Halle zuordnen.
    anlagen: [],
    anlageId: null,
    anlageBahnen: [],       // [{ id, nummer, bahnart }] der gewählten Anlage, nach Nummer sortiert
    anlageLoading: false,
    anlageError: '',
    playedLanes: [],        // bespielte Bahnnummern (mit Anlage: Teilmenge davon), Standard: alle
    // Nur ohne Anlage: frei gewählter, fortlaufender Bahnbereich.
    freiBahnen: 4,
    freiErsteBahn: 1,
    // Mannschaften:
    mannschaften: [{ id: uid('m'), name: 'Mannschaft 1', lanes: [] }, { id: uid('m'), name: 'Mannschaft 2', lanes: [] }],
    spielerJeMannschaft: 6,
    // Wertung (Kriterien der Punktvergabe):
    wertung: defaultWertung('bohle', 6),
    schwelleTouched: false,     // EWP-Schwelle vom Nutzer angefasst? (dann kein Preset-Default mehr)
    kriterium2Touched: false,   // Kriterium 2 (EWP/Satzpunkte) vom Nutzer angefasst?
  };
}

// Standard-Wertung nach Bahnart: Kriterium 1 Gesamtholz (2 Pkt), Kriterium 2 EWP (1 Pkt);
// Classic nutzt Satzpunkte. EWP-Verteilung: Bester = Anzahl aller Spieler, Schlechtester = 1
// (min. 1 Holz gespielt). Die EWP-Schwelle entscheidet im Duell, ab welcher Team-EWP-Summe
// der Gast den EWP-Punkt bekommt.
function defaultWertung(preset, spieler) {
  return {
    modus: 'duell',            // 'duell' (2 Mannschaften) | 'rangliste' (mehr als 2)
    gesamtholzPunkte: 2,       // Kriterium 1: Gesamtholz der Mannschaft
    kriterium2: preset === 'classic' ? 'satzpunkte' : 'ewp',
    kriterium2Punkte: 1,       // Punkte für Kriterium 2
    ewp: { beste: 'anzahlSpieler', schlechteste: 1, minHolz: 1 },
    ewpSchwelle: defaultEwpSchwelle(preset, spieler),
  };
}

// Empfohlener Modus nach Mannschaftszahl: genau 2 → Duell, sonst Rangliste.
const empfohlenerModus = (teams) => (teams === 2 ? 'duell' : 'rangliste');

// Möglicher Team-EWP-Bereich im Duell: EWP werden über ALLE Spieler (2×spieler) von N bis 1
// vergeben. Eine Mannschaft (spieler Spieler) hat min. die untersten, max. die obersten Werte.
//   min = 1+…+spieler ;  max = (N−spieler+1)+…+N   mit N = 2×spieler.
function teamEwpBereich(spieler) {
  const s = Math.max(1, spieler | 0);
  const N = 2 * s;
  const min = (s * (s + 1)) / 2;
  const max = s * N - (s * (s - 1)) / 2;
  return { min, max };
}

// Standard-EWP-Schwelle (ab wann der Gast den EWP-Punkt bekommt) nach Bahnart + Mannschaftsgröße.
// Vorgabewerte des Vereins; für unbekannte Größen die neutrale Mitte des Bereichs.
function defaultEwpSchwelle(preset, spieler) {
  const tabelle = { schere: { 6: 31, 4: 15 }, bohle: { 6: 32, 4: 15 } };
  const v = tabelle[preset] && tabelle[preset][spieler];
  if (v != null) return v;
  const { min, max } = teamEwpBereich(spieler);
  return Math.round((min + max) / 2);
}

export function setupWettkampfView() {
  const root = document.createElement('div');
  root.className = 'view view-page';
  const state = defaultState();

  // ── Anlage ────────────────────────────────────────────────────────────────────
  async function loadAnlagen() {
    try {
      const mod = await import('../backend/anlagen.js');
      state.anlagen = (await mod.listAnlagen()) || [];
    } catch (e) { state.anlagen = []; }
    update();
  }

  async function selectAnlage(id) {
    if (!id) {
      // Zurück auf „ohne Anlage": der frei gewählte Bahnbereich greift wieder (update -> syncFreieBahnen).
      state.anlageId = null; state.anlageBahnen = []; state.playedLanes = []; state.anlageError = '';
      update(); return;
    }
    state.anlageId = id;
    state.anlageBahnen = [];
    state.playedLanes = [];
    state.anlageError = '';
    state.anlageLoading = true;
    update();
    try {
      const mod = await import('../backend/anlagen.js');
      const bahnen = (await mod.listBahnen(id)) || [];
      state.anlageBahnen = bahnen.slice().sort((a, b) => a.nummer - b.nummer);
      state.playedLanes = state.anlageBahnen.map((b) => b.nummer); // Standard: alle Bahnen bespielen
      assignDefaultLanes(state);                                    // Standard-Aufteilung auf die Teams
    } catch (e) {
      state.anlageError = 'Bahnen der Anlage konnten nicht geladen werden.';
      state.anlageBahnen = [];
      state.playedLanes = [];
    }
    state.anlageLoading = false;
    update();
  }

  // Ohne Anlage: die bespielten Bahnen sind der frei gewählte, fortlaufende Bereich. Wird vor
  // jedem Render angeglichen, damit Anzahl/erste Bahn und playedLanes nie auseinanderlaufen.
  function syncFreieBahnen(s) {
    if (s.anlageId) return;
    const lanes = Array.from({ length: s.freiBahnen }, (_, i) => s.freiErsteBahn + i);
    if (lanes.join(',') === s.playedLanes.join(',')) return;
    s.playedLanes = lanes;
    assignDefaultLanes(s);   // Bahnbereich geändert -> Team-Aufteilung neu
  }

  // Bespielte Bahn an-/abwählen. Abgewählte Bahnen fallen auch aus den Team-Zuordnungen.
  function togglePlayedLane(n) {
    const i = state.playedLanes.indexOf(n);
    if (i >= 0) {
      state.playedLanes.splice(i, 1);
      state.mannschaften.forEach((m) => { m.lanes = m.lanes.filter((l) => l !== n); });
    } else {
      state.playedLanes.push(n);
    }
    update();
  }

  // ── Mannschaften & Team-Bahnen ─────────────────────────────────────────────────
  // Bespielte Bahnen gleichmäßig (fortlaufend) auf die Mannschaften aufteilen.
  function assignDefaultLanes(s) {
    const lanes = sortNum(s.playedLanes);
    const M = s.mannschaften.length;
    const n = lanes.length;
    s.mannschaften.forEach((m, i) => {
      const start = Math.floor((i * n) / M);
      const end = Math.floor(((i + 1) * n) / M);
      m.lanes = lanes.slice(start, end);
    });
  }

  function setAnzahlMannschaften(n) {
    n = clamp(n, 1, 20);
    const cur = state.mannschaften;
    while (cur.length < n) cur.push({ id: uid('m'), name: 'Mannschaft ' + (cur.length + 1), lanes: [] });
    cur.length = n;
    assignDefaultLanes(state);                        // Struktur geändert -> Bahnen neu aufteilen
    state.wertung.modus = empfohlenerModus(n);        // Duell/Rangliste an Mannschaftszahl anpassen
    update();
  }

  // Eine bespielte Bahn einer Mannschaft zuordnen (exklusiv: gehört immer nur einem Team).
  function toggleTeamLane(teamId, n) {
    const team = state.mannschaften.find((m) => m.id === teamId);
    if (!team) return;
    const had = team.lanes.includes(n);
    state.mannschaften.forEach((m) => { m.lanes = m.lanes.filter((l) => l !== n); });
    if (!had) team.lanes.push(n);
    team.lanes = sortNum(team.lanes);
    update();
  }

  // ── Programm-Handler ────────────────────────────────────────────────────────────
  function applyPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    state.preset = key;
    state.saetze = p.saetze;
    state.wuerfeProSatz = p.wuerfeProSatz;
    state.teilsaetze = [...p.teilsaetze];
    state.bahnwechsel = p.bahnwechsel;
    // Wertungs-Defaults der Bahnart folgen lassen, solange nicht selbst angepasst.
    if (!state.kriterium2Touched) state.wertung.kriterium2 = key === 'classic' ? 'satzpunkte' : 'ewp';
    if (!state.schwelleTouched) state.wertung.ewpSchwelle = defaultEwpSchwelle(key, state.spielerJeMannschaft);
    update();
  }

  function resizeTeilsaetze(n) {
    n = clamp(n, 1, 99);
    const next = [];
    for (let i = 0; i < n; i += 1) next.push(state.teilsaetze[i] || 'volle');
    state.teilsaetze = next;
  }

  function setField(field, val) {
    if (Number.isNaN(val)) { update(); return; }
    if (field === 'mannschaftenCount') { setAnzahlMannschaften(val); return; }
    if (field === 'freiBahnen') state.freiBahnen = clamp(val, 1, 24);
    else if (field === 'freiErsteBahn') state.freiErsteBahn = clamp(val, 1, 999);
    else if (field === 'saetze') state.saetze = clamp(val, 1, 99);
    else if (field === 'gesamtholzPunkte') state.wertung.gesamtholzPunkte = clamp(val, 0, 99);
    else if (field === 'kriterium2Punkte') state.wertung.kriterium2Punkte = clamp(val, 0, 99);
    else if (field === 'spielerJeMannschaft') {
      state.spielerJeMannschaft = clamp(val, 1, 99);
      // Team-EWP-Bereich hängt an der Spielerzahl: Standard neu setzen (bzw. in Grenzen halten).
      if (!state.schwelleTouched) state.wertung.ewpSchwelle = defaultEwpSchwelle(state.preset, state.spielerJeMannschaft);
      else { const { min, max } = teamEwpBereich(state.spielerJeMannschaft); state.wertung.ewpSchwelle = clamp(state.wertung.ewpSchwelle, min, max); }
    }
    else if (field === 'wuerfeProSatz') {
      state.wuerfeProSatz = clamp(val, 1, 999);
      const cnt = state.teilsaetze.length;
      if (state.wuerfeProSatz % cnt !== 0) resizeTeilsaetze(nearestDivisor(state.wuerfeProSatz, cnt));
    }
    update();
  }

  function currentOf(field) {
    if (field === 'freiBahnen') return state.freiBahnen;
    if (field === 'freiErsteBahn') return state.freiErsteBahn;
    if (field === 'saetze') return state.saetze;
    if (field === 'wuerfeProSatz') return state.wuerfeProSatz;
    if (field === 'gesamtholzPunkte') return state.wertung.gesamtholzPunkte;
    if (field === 'kriterium2Punkte') return state.wertung.kriterium2Punkte;
    if (field === 'spielerJeMannschaft') return state.spielerJeMannschaft;
    if (field === 'mannschaftenCount') return state.mannschaften.length;
    return 0;
  }

  function goNext() {
    const idx = TAB_ORDER.indexOf(state.tab);
    state.tab = TAB_ORDER[Math.min(idx + 1, TAB_ORDER.length - 1)];
    update();
  }

  function create() {
    if (!istErstellbar(state)) { update(); return; }
    const anlage = state.anlagen.find((a) => a.id === state.anlageId);
    const { wettkampf, games } = buildWettkampf({
      name: state.name,
      datum: state.datum,
      preset: state.preset,
      saetze: state.saetze,
      wuerfeProSatz: state.wuerfeProSatz,
      teilsaetze: state.teilsaetze,
      bahnwechsel: state.bahnwechsel,
      anlageId: state.anlageId,
      anlageName: anlage ? anlage.name : '',
      anlageBahnen: state.anlageBahnen,
      playedLanes: state.playedLanes,
      mannschaften: state.mannschaften,
      spielerJeMannschaft: state.spielerJeMannschaft,
      wertung: state.wertung,
    });

    games.forEach((g) => saveGame(g));
    saveWettkampf(wettkampf);
    setActiveWettkampf(wettkampf.id);
    navigate('/wettkampf');
  }

  function update() {
    syncFreieBahnen(state);
    root.innerHTML = template(state);
    wire();
  }

  function wire() {
    root.querySelectorAll('[data-tab]').forEach((b) =>
      b.addEventListener('click', () => { state.tab = b.dataset.tab; update(); }));

    const name = root.querySelector('[data-field="name"]');
    if (name) name.addEventListener('input', () => { state.name = name.value; });
    const datum = root.querySelector('[data-field="datum"]');
    if (datum) datum.addEventListener('change', () => { state.datum = datum.value; });

    const anl = root.querySelector('[data-field="anlage"]');
    if (anl) anl.addEventListener('change', () => selectAnlage(anl.value || null));
    root.querySelectorAll('[data-playedlane]').forEach((b) =>
      b.addEventListener('click', () => togglePlayedLane(parseInt(b.dataset.playedlane, 10))));

    root.querySelectorAll('[data-preset]').forEach((b) =>
      b.addEventListener('click', () => applyPreset(b.dataset.preset)));
    root.querySelectorAll('[data-step]').forEach((b) =>
      b.addEventListener('click', () => {
        const dir = b.dataset.step === 'inc' ? 1 : -1;
        setField(b.dataset.field, currentOf(b.dataset.field) + dir);
      }));
    root.querySelectorAll('[data-input]').forEach((inp) =>
      inp.addEventListener('change', () => setField(inp.dataset.input, parseInt(inp.value, 10))));
    const bw = root.querySelector('[data-field="bahnwechsel"]');
    if (bw) bw.addEventListener('change', () => { state.bahnwechsel = bw.value; update(); });
    root.querySelectorAll('[data-teilsatz]').forEach((b) =>
      b.addEventListener('click', () => { resizeTeilsaetze(parseInt(b.dataset.teilsatz, 10)); update(); }));
    root.querySelectorAll('.part-modus').forEach((sel) =>
      sel.addEventListener('change', () => { state.teilsaetze[parseInt(sel.dataset.part, 10)] = sel.value; update(); }));

    // Mannschaften
    root.querySelectorAll('.team-name').forEach((inp) =>
      inp.addEventListener('input', () => {
        const m = state.mannschaften.find((x) => x.id === inp.dataset.team);
        if (m) m.name = inp.value;
      }));
    root.querySelectorAll('[data-teamlane]').forEach((b) =>
      b.addEventListener('click', () => toggleTeamLane(b.dataset.teamlane, parseInt(b.dataset.lane, 10))));
    const reassign = root.querySelector('[data-action="reassign-lanes"]');
    if (reassign) reassign.addEventListener('click', () => { assignDefaultLanes(state); update(); });

    // Wertung
    root.querySelectorAll('[data-wmodus]').forEach((b) =>
      b.addEventListener('click', () => { state.wertung.modus = b.dataset.wmodus; update(); }));
    root.querySelectorAll('[data-krit2]').forEach((b) =>
      b.addEventListener('click', () => { state.wertung.kriterium2 = b.dataset.krit2; state.kriterium2Touched = true; update(); }));
    const schwelle = root.querySelector('[data-schwelle]');
    if (schwelle) schwelle.addEventListener('input', () => {
      const { min, max } = teamEwpBereich(state.spielerJeMannschaft);
      state.wertung.ewpSchwelle = clamp(parseInt(schwelle.value, 10) || min, min, max);
      state.schwelleTouched = true;
      // Nur die Live-Anzeige aktualisieren, nicht neu rendern (sonst bricht der Drag ab).
      const out = root.querySelector('[data-schwelle-out]');
      if (out) out.textContent = String(state.wertung.ewpSchwelle);
    });

    const primary = root.querySelector('.btn-primary');
    if (primary && !primary.disabled) primary.addEventListener('click', () => {
      if (primary.dataset.action === 'create') create();
      else goNext();
    });
  }

  update();
  loadAnlagen();
  return root;
}

// ── Render ───────────────────────────────────────────────────────────────────
function stepper(field, value, min) {
  return `
    <div class="stepper">
      <button type="button" class="step-btn" data-step="dec" data-field="${field}" aria-label="weniger">−</button>
      <input class="step-val" type="number" inputmode="numeric" min="${min}" value="${value}" data-input="${field}" />
      <button type="button" class="step-btn" data-step="inc" data-field="${field}" aria-label="mehr">+</button>
    </div>`;
}

function anlageOptionsHtml(s) {
  return `<option value="">— Ohne Anlage (bleibt auf diesem Gerät) —</option>`
    + s.anlagen.map((a) => `<option value="${esc(a.id)}"${s.anlageId === a.id ? ' selected' : ''}>${esc(a.name)}${a.ort ? ` (${esc(a.ort)})` : ''}</option>`).join('');
}

const artOfLane = (s, n) => { const b = s.anlageBahnen.find((x) => x.nummer === n); return b && b.bahnart ? b.bahnart : null; };

function anlageSection(s) {
  const anlageActive = !!(s.anlageId && s.anlageBahnen.length);
  const bahnenChips = anlageActive ? `
    <section class="field">
      <label class="field-label">Bespielte Bahnen <small class="field-note">· antippen</small></label>
      <div class="chips">
        ${s.anlageBahnen.map((b) => {
          const a = b.bahnart ? (ART_LABEL[b.bahnart] || b.bahnart) : '';
          const on = s.playedLanes.includes(b.nummer);
          return `<button type="button" class="chip${on ? ' is-active' : ''}" data-playedlane="${b.nummer}">${b.nummer}${a ? ` <small>${esc(a)}</small>` : ''}</button>`;
        }).join('')}
      </div>
      <p class="field-hint">Gewählt: ${s.playedLanes.length} von ${s.anlageBahnen.length}</p>
    </section>` : '';
  // Ohne Anlage: freier, fortlaufender Bahnbereich (wie im Training-Setup).
  const freieBahnen = s.anlageId ? '' : `
    <section class="field">
      <label class="field-label">Bespielte Bahnen</label>
      <div class="chips bahnen-row">
        ${stepper('freiBahnen', s.freiBahnen, 1)}
        <div class="inline-num">
          <span class="inline-num-label">1. Bahn</span>
          <div class="inline-stepper">
            <button type="button" class="step-btn sm" data-step="dec" data-field="freiErsteBahn" aria-label="erste Bahn weniger">−</button>
            <input class="step-val sm" type="number" inputmode="numeric" min="1" value="${s.freiErsteBahn}" data-input="freiErsteBahn" />
            <button type="button" class="step-btn sm" data-step="inc" data-field="freiErsteBahn" aria-label="erste Bahn mehr">+</button>
          </div>
        </div>
      </div>
      <p class="field-hint">Bahn ${s.freiErsteBahn}–${s.freiErsteBahn + s.freiBahnen - 1}</p>
    </section>`;
  return `
    <section class="field">
      <label class="field-label" for="wk-anlage">Anlage <small class="field-note">· optional</small></label>
      <select class="select-full" data-field="anlage" id="wk-anlage">
        ${anlageOptionsHtml(s)}
      </select>
      ${s.anlageLoading ? '<p class="field-hint">Lade Bahnen …</p>' : ''}
      ${s.anlageError ? `<p class="field-hint">${esc(s.anlageError)}</p>` : ''}
      ${s.anlageId ? '' : '<p class="field-hint">Ohne Anlage bleibt der Wettkampf auf <strong>diesem Gerät</strong>. Zum Teilen (Mehrgeräte-Erfassung, OBS-Overlay) braucht er eine Anlage — die lässt sich später im Wettkampf nachtragen.</p>'}
      ${!s.anlagen.length && !s.anlageLoading ? '<p class="field-hint">Keine Anlagen verfügbar — unter <a href="#/anlagen">Anlagen</a> eine anlegen (Konto nötig).</p>' : ''}
      ${s.anlageId && !anlageActive && !s.anlageLoading ? '<p class="field-hint">Diese Anlage hat keine Bahnen.</p>' : ''}
    </section>
    ${freieBahnen}
    ${bahnenChips}`;
}

function tabProgramm(s) {
  const tpp = throwsPerPart(s.wuerfeProSatz, s.teilsaetze.length);
  const divs = divisors(s.wuerfeProSatz);
  return `
    <section class="field">
      <label class="field-label" for="wk-name">Name des Wettkampfs</label>
      <input class="join-input select-full" id="wk-name" data-field="name" type="text" placeholder="z. B. Vereinspokal 2026" value="${esc(s.name)}" />
    </section>

    <section class="field">
      <label class="field-label" for="wk-datum">Datum</label>
      <input class="join-input select-full" id="wk-datum" data-field="datum" type="date" value="${esc(s.datum)}" />
    </section>

    ${anlageSection(s)}

    <section class="field">
      <label class="field-label">Bahnart</label>
      <div class="segmented" role="group">
        ${Object.entries(PRESETS).map(([k, p]) => `<button type="button" class="seg-btn${s.preset === k ? ' is-active' : ''}" data-preset="${k}">${p.label}</button>`).join('')}
      </div>
    </section>

    <section class="field">
      <label class="field-label">Bahnwechsel</label>
      <select class="select-full" data-field="bahnwechsel">
        ${BAHNWECHSEL.map((o) => `<option value="${o.key}"${o.key === s.bahnwechsel ? ' selected' : ''}>${o.label}</option>`).join('')}
      </select>
    </section>

    <section class="field">
      <label class="field-label">Anzahl Sätze</label>
      ${stepper('saetze', s.saetze, 1)}
    </section>

    <section class="field">
      <label class="field-label">Würfe pro Satz</label>
      ${stepper('wuerfeProSatz', s.wuerfeProSatz, 1)}
    </section>

    <section class="field field-readout">
      <span class="field-label">Gesamtwurfzahl</span>
      <span class="readout">${s.saetze * s.wuerfeProSatz} <small>(${s.saetze} × ${s.wuerfeProSatz})</small></span>
    </section>

    <section class="field">
      <label class="field-label">Anzahl Teilsätze</label>
      <div class="chips">
        ${divs.map((n) => `<button type="button" class="chip${s.teilsaetze.length === n ? ' is-active' : ''}" data-teilsatz="${n}">${n}</button>`).join('')}
      </div>
      <p class="field-hint">Nur gleichmäßige Aufteilung (Teiler von ${s.wuerfeProSatz}).</p>
    </section>

    <section class="field">
      <label class="field-label">Modus je Teilsatz</label>
      <div class="parts">
        ${s.teilsaetze.map((m, i) => `
          <div class="part-row">
            <span class="part-name">Teilsatz ${i + 1}</span>
            <span class="part-throws">${tpp[i]} Wurf</span>
            <select class="part-modus" data-part="${i}">
              ${MODI.map((o) => `<option value="${o.key}"${o.key === m ? ' selected' : ''}>${o.label}</option>`).join('')}
            </select>
          </div>`).join('')}
      </div>
    </section>`;
}

function tabMannschaften(s) {
  const played = sortNum(s.playedLanes);
  if (!played.length) {
    return '<p class="field-hint">Bitte zuerst im Tab „Programm" die bespielten Bahnen festlegen.</p>';
  }
  const laneChips = (team) => played.map((n) => {
    const a = artOfLane(s, n);
    const on = team.lanes.includes(n);
    return `<button type="button" class="chip sm${on ? ' is-active' : ''}" data-teamlane="${esc(team.id)}" data-lane="${n}">${n}${a ? ` <small>${esc(ART_LABEL[a] || a)}</small>` : ''}</button>`;
  }).join('');
  const teams = s.mannschaften.map((m, i) => `
    <div class="team-block">
      <div class="player-row">
        <span class="player-idx">${i + 1}</span>
        <input class="player-name team-name" data-team="${esc(m.id)}" type="text" placeholder="Mannschaft ${i + 1}" value="${esc(m.name)}" />
      </div>
      <div class="chips team-lanes">${laneChips(m)}</div>
      <p class="field-hint">Startbahn(en): ${m.lanes.length ? m.lanes.join(', ') : '— keine —'}</p>
    </div>`).join('');

  // Vorschau der Durchgänge.
  const teamLanes = {};
  s.mannschaften.forEach((m) => { teamLanes[m.id] = m.lanes; });
  const plan = planDurchgaenge({ mannschaften: s.mannschaften.map((m) => ({ id: m.id, name: m.name })), spielerJeMannschaft: s.spielerJeMannschaft, teamLanes });
  const unassigned = played.filter((n) => !s.mannschaften.some((m) => m.lanes.includes(n)));

  return `
    <section class="field">
      <label class="field-label">Anzahl Mannschaften</label>
      ${stepper('mannschaftenCount', s.mannschaften.length, 1)}
    </section>

    <section class="field">
      <div class="field-row">
        <label class="field-label">Mannschaften & Startbahnen</label>
        <button type="button" class="btn-mini" data-action="reassign-lanes">↻ Standard-Aufteilung</button>
      </div>
      <div class="players">${teams}</div>
      ${unassigned.length ? `<p class="field-hint">Nicht zugeordnete Bahnen: ${unassigned.join(', ')} — jede bespielte Bahn sollte einem Team gehören.</p>` : ''}
    </section>

    <section class="field">
      <label class="field-label">Spieler je Mannschaft</label>
      ${stepper('spielerJeMannschaft', s.spielerJeMannschaft, 1)}
    </section>

    <section class="field field-readout">
      <span class="field-label">Ergibt</span>
      <span class="readout">${plan.length} Durchgänge <small>(${s.mannschaften.length} Teams · ${s.spielerJeMannschaft} Spieler)</small></span>
    </section>
    <p class="field-hint">Jede Mannschaft sitzt pro Durchgang auf ihren Startbahnen. Namen füllst du danach im Wettkampf.</p>`;
}

// Tab „Wertung": Kriterien der Punktvergabe. Zuerst Duell/Rangliste, dann die
// beiden Kriterien (Gesamtholz-Punkte, dann EWP oder Satzpunkte). Für EWP wird die
// Verteilung Bester = Anzahl Spieler … Schlechtester = 1 erläutert; Satzpunkte folgt.
function tabWertung(s) {
  const w = s.wertung;
  const teams = s.mannschaften.length;
  const empf = empfohlenerModus(teams);
  const N = teams * s.spielerJeMannschaft;   // EWP über ALLE Spieler des Wettkampfs
  const ewpAktiv = w.kriterium2 === 'ewp';
  const { min: ewpMin, max: ewpMax } = teamEwpBereich(s.spielerJeMannschaft);
  const schwelle = clamp(w.ewpSchwelle, ewpMin, ewpMax);

  return `
    <section class="field">
      <label class="field-label">Punktevergabe</label>
      <div class="segmented" role="group">
        <button type="button" class="seg-btn${w.modus === 'duell' ? ' is-active' : ''}" data-wmodus="duell">Duell</button>
        <button type="button" class="seg-btn${w.modus === 'rangliste' ? ' is-active' : ''}" data-wmodus="rangliste">Rangliste</button>
      </div>
      <p class="field-hint">Duell bei 2 Mannschaften, Rangliste bei mehr als 2. Aktuell ${teams} Mannschaft${teams === 1 ? '' : 'en'} → empfohlen: <strong>${empf === 'duell' ? 'Duell' : 'Rangliste'}</strong>.</p>
    </section>

    <section class="field">
      <label class="field-label">Kriterium 1 · Gesamtholz Mannschaft</label>
      ${stepper('gesamtholzPunkte', w.gesamtholzPunkte, 0)}
      <p class="field-hint">Punkte für die Mannschaft mit dem höheren Gesamtholz. Bei Gleichstand geteilt.</p>
    </section>

    <section class="field">
      <label class="field-label">Kriterium 2</label>
      <div class="segmented" role="group">
        <button type="button" class="seg-btn${w.kriterium2 === 'ewp' ? ' is-active' : ''}" data-krit2="ewp">EWP</button>
        <button type="button" class="seg-btn${w.kriterium2 === 'satzpunkte' ? ' is-active' : ''}" data-krit2="satzpunkte">Satzpunkte</button>
      </div>
    </section>

    <section class="field">
      <label class="field-label">Punkte für Kriterium 2</label>
      ${stepper('kriterium2Punkte', w.kriterium2Punkte, 0)}
    </section>

    ${ewpAktiv ? `
    <section class="field">
      <label class="field-label">EWP-Verteilung</label>
      <div class="parts">
        <div class="part-row"><span class="part-name">Bester Spieler</span><span class="part-throws">${N} EWP <small>(= alle Spieler: ${teams} × ${s.spielerJeMannschaft})</small></span></div>
        <div class="part-row"><span class="part-name">Schlechtester Spieler</span><span class="part-throws">1 EWP</span></div>
      </div>
      <p class="field-hint">Alle Spieler des Wettkampfs in eine gemeinsame Rangliste; lückenlos von ${N} bis 1. Nur Spieler mit mindestens 1 gespielten Holz.</p>
      <p class="field-hint">Gleichstand bei der EWP-Vergabe: höhere EWP geht an den Gast; bei Rangliste und innerhalb einer Mannschaft entscheidet die höhere Abräumzahl.</p>
    </section>

    ${w.modus === 'duell' ? `
    <section class="field">
      <label class="field-label">EWP-Punkt · Schwelle für den Gast</label>
      <input type="range" class="slider-full" min="${ewpMin}" max="${ewpMax}" step="1" value="${schwelle}" data-schwelle aria-label="EWP-Schwelle für den Gast" />
      <div class="slider-scale"><span>${ewpMin}</span><span>${ewpMax}</span></div>
      <p class="field-hint">Der Gast bekommt den EWP-Punkt (${w.kriterium2Punkte} Pkt) ab einer Team-EWP-Summe von <strong data-schwelle-out>${schwelle}</strong> (möglich: ${ewpMin}–${ewpMax}). Darunter geht der Punkt ans Heim-Team.</p>
    </section>` : `
    <section class="field">
      <p class="field-hint">Rangliste: Der EWP-Punkt wird über die Team-EWP-Rangfolge vergeben — keine Gast-Schwelle.</p>
    </section>`}` : `
    <section class="field">
      <p class="field-hint">Satzpunkte-Wertung folgt (ToDo).</p>
    </section>`}`;
}

function template(s) {
  const body = s.tab === 'programm' ? tabProgramm(s)
    : s.tab === 'mannschaften' ? tabMannschaften(s)
    : tabWertung(s);
  const isLast = s.tab === 'wertung';
  const disabled = isLast && !istErstellbar(s);
  return `
    <header class="page-header">
      <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
      <h1 class="page-title">Sportkegeln-Wettkampf</h1>
    </header>

    <div class="tabs" role="tablist">
      <button type="button" role="tab" aria-selected="${s.tab === 'programm'}" class="tab${s.tab === 'programm' ? ' is-active' : ''}" data-tab="programm">Programm</button>
      <button type="button" role="tab" aria-selected="${s.tab === 'mannschaften'}" class="tab${s.tab === 'mannschaften' ? ' is-active' : ''}" data-tab="mannschaften">Mannschaften</button>
      <button type="button" role="tab" aria-selected="${s.tab === 'wertung'}" class="tab${s.tab === 'wertung' ? ' is-active' : ''}" data-tab="wertung">Wertung</button>
    </div>

    <div class="setup">
      ${body}
      <button type="button" class="btn-primary" data-action="${isLast ? 'create' : 'next'}"${disabled ? ' disabled' : ''}>${isLast ? 'Wettkampf erstellen' : 'Weiter'}</button>
    </div>`;
}
