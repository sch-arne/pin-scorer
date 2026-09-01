// Import aus Sportwinner: die Brücke (interface.dll) exportiert die laufende Partie als
// roster.json und öffnet die App auf dieser Route (Deeplink `#/import/sportwinner?src=…`).
// Diese View lädt den Roster und zeigt ein VORBEFÜLLTES, editierbares Setup:
//   • Mannschaften + Spieler kommen aus Sportwinner (Vorschau, nicht editiert).
//   • Die Anlage wird ZUERST gegen bestehende Anlagen abgeglichen (Best-Treffer
//     vorausgewählt); alternativ eine neue aus den Sportwinner-Spielortdaten anlegen.
//   • Programm (Bahnart/Bahnwechsel/Sätze/Würfe/Teilsätze), Name, Datum und die
//     bespielten Bahnen sind frei einstellbar (Default: Bohle 4×30).
// „Erstellen" legt bei Bedarf die Anlage an, baut den Wettkampf (Paarkreuz-Durchgänge)
// und TEILT ihn — das erzeugt den Beitrittscode. Ein Konto ist nötig (Anlage/Teilen laut RLS).

import { navigate, currentQuery } from '../router.js';
import { esc } from '../util.js';
import { parseRoster, parseBahnen, teamLanesByBahnart } from '../logic/roster-import.js';
import { buildWettkampf } from '../logic/wettkampf-build.js';
import { ichSlotAusRoster } from '../logic/spieler-identitaet.js';
import { planDurchgaenge } from '../logic/wettkampf.js';
import { divisors, nearestDivisor, throwsPerPart } from '../logic/teilsaetze.js';
import { MODI, BAHNWECHSEL, PRESETS, ART_LABEL } from '../logic/sportkegeln-presets.js';
import {
  saveGame, saveWettkampf, setActiveWettkampf, deleteWettkampf, getWettkaempfe,
} from '../store.js';
import { setBruecke, getBruecke, meldeWettkampf } from '../backend/sw-bruecke.js';

const ROSTER_SS_KEY = 'pins-scorer:sw-roster'; // Fallback über einen Login-Umweg hinweg
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const sortNum = (arr) => arr.slice().sort((a, b) => a - b);
const norm = (s) => (s || '').toLowerCase().replace(/["'"'„".]/g, '').replace(/\s+/g, ' ').trim();

// Beste vorhandene Anlage zum Sportwinner-Spielort finden (Name+PLZ > Name > PLZ+Ort).
function bestAnlageMatch(anlagen, ziel) {
  const nName = norm(ziel.name);
  const nPlz = (ziel.plz || '').trim();
  const nOrt = norm(ziel.ort);
  if (nName && nPlz) {
    const m = anlagen.find((a) => norm(a.name) === nName && (a.plz || '').trim() === nPlz);
    if (m) return m;
  }
  if (nName) {
    const m = anlagen.find((a) => {
      const an = norm(a.name);
      return an && (an === nName || an.includes(nName) || nName.includes(an));
    });
    if (m) return m;
  }
  if (nPlz && nOrt) {
    const m = anlagen.find((a) => (a.plz || '').trim() === nPlz && norm(a.ort) === nOrt);
    if (m) return m;
  }
  return null;
}

export function importSportwinnerView() {
  const root = document.createElement('div');
  root.className = 'view view-page';
  const state = {
    phase: 'loading',    // loading | ready | creating | done | error
    spec: null,
    error: '',
    msg: '',
    darfAnlegen: false,
    authChecked: false,
    code: '',
    // editierbares Programm (Default: Bohle):
    name: '', datum: '',
    preset: 'bohle', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'volle'], bahnwechsel: 'bohle',
    spielerJeMannschaft: 1,      // Default aus der Aufstellung (Sportwinner nennt keine Soll-Anzahl)
    teamLanes: {},               // { [mannschaftId]: number[] } — Startbahnen je Mannschaft
    teamLanesTouched: false,     // hat der Nutzer die Startbahnen manuell verändert?
    duplikat: null,              // bereits vorhandener, nicht beendeter Wettkampf gleicher Spielnr.
    // Anlage:
    anlagen: [], anlagenLoaded: false, anlagenError: '',
    anlageChoice: 'new',   // 'new' | <anlageId>
    anlageBahnen: [],      // Bahnen der gewählten BESTEHENDEN Anlage [{id,nummer,bahnart}]
    anlageBahnenLoading: false,
    newAnlage: { name: '', strasse: '', plz: '', ort: '' },
    newBahnenText: '',     // Bahnen-Eingabe für die neue Anlage (z. B. "2-5")
    playedLanes: [],       // aktuell bespielte Bahnnummern
    autoMatched: false,    // Best-Treffer schon einmal automatisch gesetzt?
    ichSlot: null,         // "<mannschaftId>|<teamPos>" der eigenen LizenzID in dieser
                           // Aufstellung — rein lokale Markierung, siehe erkenneIch()
  };

  function setPhase(p) { state.phase = p; render(); }

  // --- Roster laden -----------------------------------------------------------
  async function fetchRosterText() {
    const src = currentQuery().get('src') || './roster.json';
    try {
      const res = await fetch(src, { cache: 'no-store' });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const text = await res.text();
      try { sessionStorage.setItem(ROSTER_SS_KEY, text); } catch (e) { /* privater Modus */ }
      return text;
    } catch (e) {
      try {
        const cached = sessionStorage.getItem(ROSTER_SS_KEY);
        if (cached) return cached;
      } catch (e2) { /* ignore */ }
      throw e;
    }
  }

  async function load() {
    // Brücke-Push-Endpoint aus dem Deeplink merken (nur auf dem Vereins-PC gesetzt): darüber
    // meldet die App den Beitrittscode zurück und schickt später die Ergebnisse.
    setBruecke(currentQuery().get('push'));
    try {
      const text = await fetchRosterText();
      const roster = JSON.parse(text);
      const spec = parseRoster(roster);
      state.spec = spec;
      // Editierbare Felder aus Roster + Bohle-Preset vorbelegen.
      state.name = spec.name;
      state.datum = spec.datum;
      // Bahnart aus der Sportwinner-Sektion vorwählen (classic/schere); sonst Bohle.
      // Der Preset bestimmt zugleich die Bahnart einer neu angelegten Anlage (siehe create()).
      applyPreset(spec.bahnart && PRESETS[spec.bahnart] ? spec.bahnart : 'bohle');
      state.newAnlage = {
        name: spec.anlage.name, strasse: spec.anlage.strasse, plz: spec.anlage.plz, ort: spec.anlage.ort,
      };
      state.newBahnenText = spec.anlage.bahnen.join(', ');
      state.playedLanes = spec.anlage.bahnen.slice();
      state.spielerJeMannschaft = Math.max(1, spec.spielerJeMannschaft || 1);
      recomputeTeamLanes();
      state.duplikat = findeDuplikat(spec);
      state.anlageChoice = 'new';
      state.phase = 'ready';
    } catch (e) {
      state.error = 'roster.json konnte nicht geladen/gelesen werden. '
        + 'Die Brücke muss den Roster bereitstellen (export-roster / open-app).';
      state.phase = 'error';
    }
    render();
    checkAuth();
    loadAnlagen();
  }

  async function checkAuth() {
    try {
      const auth = await import('../backend/auth.js');
      const user = await auth.currentUser();
      state.darfAnlegen = auth.isPermanent(user);
      if (state.darfAnlegen) await erkenneIch(auth);
    } catch (e) {
      state.darfAnlegen = false;
    }
    state.authChecked = true;
    render();
  }

  // „Das bin ich" automatisch bestimmen: steht die im Profil hinterlegte LizenzID in dieser
  // Aufstellung, wird der zugehörige Wettkampf-Slot vorgemerkt. Daraus leitet sich später je
  // Durchgang ab, WELCHE Ergebniszeile dem eigenen Account zugeordnet wird — alle übrigen
  // bleiben neutral und landen damit nicht in der eigenen Statistik. Rein lokal: ichSlot wird
  // nicht in die DB gespiegelt (siehe sync.js wettkampfConfigFuerDb).
  async function erkenneIch(auth) {
    if (!state.spec) return;
    try {
      const profil = await auth.getProfil();
      state.ichSlot = ichSlotAusRoster(state.spec.sportwinner, profil && profil.passnummer);
    } catch (e) { state.ichSlot = null; }
  }

  // Bestehende Anlagen laden und (einmalig) den Best-Treffer vorwählen.
  async function loadAnlagen() {
    if (!state.spec) return;
    try {
      const mod = await import('../backend/anlagen.js');
      state.anlagen = (await mod.listAnlagen()) || [];
      state.anlagenLoaded = true;
      state.anlagenError = '';
    } catch (e) {
      state.anlagen = [];
      state.anlagenLoaded = true;
      state.anlagenError = 'Bestehende Anlagen konnten nicht geladen werden (offline?).';
    }
    if (!state.autoMatched && state.anlageChoice === 'new') {
      const match = bestAnlageMatch(state.anlagen, state.spec.anlage);
      state.autoMatched = true;
      if (match) { await selectAnlage(match.id); return; }
    }
    render();
  }

  async function selectAnlage(choice) {
    state.anlageChoice = choice;
    state.anlageBahnen = [];
    state.teamLanesTouched = false; // andere Anlage = anderer Bahnsatz -> Startbahn-Default neu
    if (choice === 'new') {
      state.playedLanes = parseBahnen(state.newBahnenText);
      recomputeTeamLanes();
      render();
      return;
    }
    state.anlageBahnenLoading = true;
    render();
    try {
      const mod = await import('../backend/anlagen.js');
      const bahnen = (await mod.listBahnen(choice)) || [];
      state.anlageBahnen = bahnen.slice().sort((a, b) => a.nummer - b.nummer);
      const laneNums = state.anlageBahnen.map((b) => b.nummer);
      // Sportwinner-Bahnen mit der Anlage schneiden; sonst alle Bahnen der Anlage.
      const inter = state.spec.anlage.bahnen.filter((n) => laneNums.includes(n));
      state.playedLanes = inter.length ? inter : laneNums;
    } catch (e) {
      state.anlageBahnen = [];
      state.playedLanes = [];
    }
    recomputeTeamLanes();
    state.anlageBahnenLoading = false;
    render();
  }

  function togglePlayedLane(n) {
    const i = state.playedLanes.indexOf(n);
    if (i >= 0) state.playedLanes.splice(i, 1); else state.playedLanes.push(n);
    reconcileTeamLanes();
    render();
  }

  // Bereits vorhandener, NICHT beendeter Wettkampf derselben Sportwinner-Partie (Spielnummer)?
  // Fehlt die Spielnummer im Roster, ist keine verlässliche Zuordnung möglich -> kein Treffer.
  function findeDuplikat(spec) {
    const nr = spec && spec.sportwinner && spec.sportwinner.spielNr;
    if (nr == null) return null;
    return getWettkaempfe().find((w) => w.status !== 'beendet'
      && w.sportwinner && w.sportwinner.spielNr === nr) || null;
  }

  // Startbahnen je Mannschaft aus den bespielten Bahnen + Bahnart-Regel neu setzen (Default).
  function recomputeTeamLanes() {
    if (!state.spec) return;
    const played = sortNum(state.playedLanes);
    const teams = state.spec.mannschaften;
    const split = teamLanesByBahnart(state.preset, played, teams.length);
    const tl = {};
    teams.forEach((m, i) => { tl[m.id] = (split[i] || []).slice(); });
    state.teamLanes = tl;
  }

  // Nach Änderung der bespielten Bahnen: unberührt -> Default neu; manuell verändert -> nur
  // entfernte Bahnen aus den Teams streichen (neu hinzugekommene bleiben zunächst unzugeordnet).
  function reconcileTeamLanes() {
    if (!state.teamLanesTouched) { recomputeTeamLanes(); return; }
    const allowed = new Set(state.playedLanes);
    Object.keys(state.teamLanes).forEach((id) => {
      state.teamLanes[id] = (state.teamLanes[id] || []).filter((n) => allowed.has(n));
    });
  }

  // Manuelle, exklusive Zuordnung einer Bahn zu einer Mannschaft (jede Bahn gehört genau einem Team).
  function toggleTeamLane(teamId, n) {
    state.teamLanesTouched = true;
    const cur = state.teamLanes[teamId] || [];
    const has = cur.includes(n);
    Object.keys(state.teamLanes).forEach((id) => {
      state.teamLanes[id] = (state.teamLanes[id] || []).filter((x) => x !== n);
    });
    if (!has) state.teamLanes[teamId] = sortNum([...(state.teamLanes[teamId] || []), n]);
    render();
  }

  // --- Programm-Handler (wie setup-wettkampf) --------------------------------
  function applyPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    state.preset = key;
    state.saetze = p.saetze;
    state.wuerfeProSatz = p.wuerfeProSatz;
    state.teilsaetze = [...p.teilsaetze];
    state.bahnwechsel = p.bahnwechsel;
    if (!state.teamLanesTouched) recomputeTeamLanes(); // Startbahn-Default folgt der Bahnart
  }
  function resizeTeilsaetze(n) {
    n = clamp(n, 1, 99);
    const next = [];
    for (let i = 0; i < n; i += 1) next.push(state.teilsaetze[i] || 'volle');
    state.teilsaetze = next;
  }
  function setField(field, val) {
    if (Number.isNaN(val)) { render(); return; }
    if (field === 'saetze') state.saetze = clamp(val, 1, 99);
    else if (field === 'spielerJeMannschaft') state.spielerJeMannschaft = clamp(val, 1, 99);
    else if (field === 'wuerfeProSatz') {
      state.wuerfeProSatz = clamp(val, 1, 999);
      const cnt = state.teilsaetze.length;
      if (state.wuerfeProSatz % cnt !== 0) resizeTeilsaetze(nearestDivisor(state.wuerfeProSatz, cnt));
    }
    render();
  }
  const currentOf = (f) => {
    if (f === 'saetze') return state.saetze;
    if (f === 'spielerJeMannschaft') return state.spielerJeMannschaft;
    return state.wuerfeProSatz;
  };

  // Bahnen-Nummern, die aktuell für die Auswahl zur Verfügung stehen.
  function availableLanes() {
    if (state.anlageChoice === 'new') return parseBahnen(state.newBahnenText);
    return state.anlageBahnen.map((b) => b.nummer);
  }
  const artOfLane = (n) => {
    const b = state.anlageBahnen.find((x) => x.nummer === n);
    return b && b.bahnart ? b.bahnart : null;
  };

  function teamLanesComplete() {
    return !!(state.spec && state.spec.mannschaften.every((m) => (state.teamLanes[m.id] || []).length));
  }
  function canCreate() {
    return !!(state.playedLanes.length && state.spec && teamLanesComplete()
      && (state.anlageChoice !== 'new' || (state.newAnlage.name || '').trim()));
  }

  // --- Anlegen + Teilen -------------------------------------------------------
  async function create() {
    if (state.phase !== 'ready' || !canCreate()) { render(); return; }
    const spec = state.spec;
    state.msg = state.anlageChoice === 'new' ? 'Lege Anlage an …' : 'Bereite Wettkampf vor …';
    setPhase('creating');
    try {
      const anlagenMod = await import('../backend/anlagen.js');

      let anlageId = state.anlageChoice;
      let anlageBahnen = state.anlageBahnen;
      let anlageName = '';
      if (state.anlageChoice === 'new') {
        const bahnen = sortNum(state.playedLanes).map((n) => ({ nummer: n, bahnart: state.preset }));
        const created = await anlagenMod.createAnlage({
          name: state.newAnlage.name, strasse: state.newAnlage.strasse,
          plz: state.newAnlage.plz, ort: state.newAnlage.ort,
        }, bahnen);
        anlageId = created.id;
        anlageName = created.name;
        anlageBahnen = await anlagenMod.listBahnen(anlageId);
      } else {
        const chosen = state.anlagen.find((a) => a.id === anlageId);
        anlageName = chosen ? chosen.name : '';
        if (!anlageBahnen.length) anlageBahnen = await anlagenMod.listBahnen(anlageId);
      }

      const laneNums = anlageBahnen.map((b) => b.nummer);
      let played = sortNum(state.playedLanes.filter((n) => laneNums.includes(n)));
      if (!played.length) played = sortNum(laneNums);
      // Startbahnen je Team aus der (evtl. manuellen) Zuordnung, auf die echten Bahnen beschnitten.
      const playedSet = new Set(played);
      let mannschaften = spec.mannschaften.map((m) => ({
        id: m.id, name: m.name,
        lanes: sortNum((state.teamLanes[m.id] || []).filter((n) => playedSet.has(n))),
      }));
      // Sicherheitsnetz: hat ein Team keine gültige Startbahn, Bahnart-Default anwenden.
      if (mannschaften.some((m) => !m.lanes.length)) {
        const split = teamLanesByBahnart(state.preset, played, spec.mannschaften.length);
        mannschaften = spec.mannschaften.map((m, i) => ({ id: m.id, name: m.name, lanes: split[i] || [] }));
      }

      const { wettkampf, games } = buildWettkampf({
        name: state.name,
        datum: state.datum,
        preset: state.preset,
        saetze: state.saetze,
        wuerfeProSatz: state.wuerfeProSatz,
        teilsaetze: [...state.teilsaetze],
        bahnwechsel: state.bahnwechsel,
        anlageId,
        anlageName,
        anlageBahnen,
        playedLanes: played,
        mannschaften,
        spielerJeMannschaft: state.spielerJeMannschaft,
        namesByTeamPos: spec.namesByTeamPos,
        quelle: 'sportwinner',
        sportwinner: spec.sportwinner,
      });

      // „Das bin ich" (aus der eigenen LizenzID erkannt) an den Wettkampf hängen: darüber
      // bekommt beim Spielende genau EINE Ergebniszeile je Durchgang die eigene profil_id.
      if (state.ichSlot) wettkampf.ichSlot = state.ichSlot;

      games.forEach((g) => saveGame(g));
      saveWettkampf(wettkampf);
      setActiveWettkampf(wettkampf.id);

      state.msg = 'Teile Wettkampf …';
      render();
      const sync = await import('../backend/sync.js');
      const { remoteId } = await sync.linkWettkampf(wettkampf, games);
      const { wettkampf: fresh, games: freshGames } = await sync.pullWettkampf(remoteId);
      deleteWettkampf(wettkampf.id);
      // ichSlot reist bewusst NICHT über die DB (rein lokale Markierung) — nach dem Pull
      // wieder aufsetzen, sonst ginge sie beim Ersetzen der lokalen Kopie verloren.
      if (state.ichSlot) fresh.ichSlot = state.ichSlot;
      freshGames.forEach((g) => saveGame(g));
      saveWettkampf(fresh);
      setActiveWettkampf(fresh.id);

      state.code = fresh.beitrittsCode || '';
      // Der Brücke den Code + die Match-Identität melden, damit sie beim nächsten Start
      // genau dieses Match wiedererkennt und den Browser automatisch wieder beitreten lässt.
      const sw = spec.sportwinner || {};
      meldeWettkampf({
        code: state.code,
        spielNr: sw.spielNr ?? null,
        heim: spec.mannschaften[0] ? spec.mannschaften[0].name : '',
        gast: spec.mannschaften[1] ? spec.mannschaften[1].name : '',
        name: fresh.name || state.name || '',
      });
      try { sessionStorage.removeItem(ROSTER_SS_KEY); } catch (e) { /* ignore */ }
      // Vereins-PC (App per Brücke geöffnet): direkt ins Kontrollzentrum (Wettkampf-Hub,
      // Desktop-Übersicht) springen, statt den Beitrittscode-Zwischenschritt zu zeigen —
      // der Code steht dort weiter in der Mehrgeräte-Sektion.
      if (getBruecke()) { navigate('/wettkampf'); return; }
      setPhase('done');
    } catch (e) {
      const m = (e && e.message) || '';
      state.msg = /angemeldet|login|auth|jwt|permission|row-level/i.test(m)
        ? 'Konto nötig — bitte anmelden und erneut versuchen.'
        : 'Erstellen fehlgeschlagen — online sein und erneut versuchen.';
      setPhase('ready');
    }
  }

  // --- Render -----------------------------------------------------------------
  function render() {
    root.innerHTML = template(state);
    wire();
  }

  function wire() {
    // Name / Datum
    const name = root.querySelector('[data-field="name"]');
    if (name) name.addEventListener('input', () => { state.name = name.value; });
    const datum = root.querySelector('[data-field="datum"]');
    if (datum) datum.addEventListener('change', () => { state.datum = datum.value; });

    // Anlage
    const anl = root.querySelector('[data-field="anlagewahl"]');
    if (anl) anl.addEventListener('change', () => selectAnlage(anl.value));
    root.querySelectorAll('[data-newanlage]').forEach((inp) =>
      inp.addEventListener('input', () => { state.newAnlage[inp.dataset.newanlage] = inp.value; }));
    const bahnenInp = root.querySelector('[data-field="newbahnen"]');
    if (bahnenInp) bahnenInp.addEventListener('change', () => {
      state.newBahnenText = bahnenInp.value;
      state.playedLanes = parseBahnen(bahnenInp.value);
      reconcileTeamLanes();
      render();
    });
    root.querySelectorAll('[data-playedlane]').forEach((b) =>
      b.addEventListener('click', () => togglePlayedLane(parseInt(b.dataset.playedlane, 10))));

    // Programm
    root.querySelectorAll('[data-preset]').forEach((b) =>
      b.addEventListener('click', () => { applyPreset(b.dataset.preset); render(); }));
    const bw = root.querySelector('[data-field="bahnwechsel"]');
    if (bw) bw.addEventListener('change', () => { state.bahnwechsel = bw.value; render(); });
    root.querySelectorAll('[data-step]').forEach((b) =>
      b.addEventListener('click', () => {
        const dir = b.dataset.step === 'inc' ? 1 : -1;
        setField(b.dataset.field, currentOf(b.dataset.field) + dir);
      }));
    root.querySelectorAll('[data-input]').forEach((inp) =>
      inp.addEventListener('change', () => setField(inp.dataset.input, parseInt(inp.value, 10))));
    root.querySelectorAll('[data-teilsatz]').forEach((b) =>
      b.addEventListener('click', () => { resizeTeilsaetze(parseInt(b.dataset.teilsatz, 10)); render(); }));
    root.querySelectorAll('.part-modus').forEach((sel) =>
      sel.addEventListener('change', () => { state.teilsaetze[parseInt(sel.dataset.part, 10)] = sel.value; render(); }));

    // Startbahnen je Mannschaft
    root.querySelectorAll('[data-teamlane]').forEach((b) =>
      b.addEventListener('click', () => toggleTeamLane(b.dataset.teamlane, parseInt(b.dataset.lane, 10))));

    // Duplikat-Aktionen
    const dupOpen$ = root.querySelector('[data-action="dup-open"]');
    if (dupOpen$) dupOpen$.addEventListener('click', () => {
      setActiveWettkampf(state.duplikat.id);
      navigate('/wettkampf');
    });
    const dupDel$ = root.querySelector('[data-action="dup-del"]');
    if (dupDel$) dupDel$.addEventListener('click', () => {
      if (!window.confirm(`Vorhandenen Wettkampf „${state.duplikat.name || ''}" mit allen Durchgängen wirklich löschen?`)) return;
      deleteWettkampf(state.duplikat.id);
      state.duplikat = null;
      render();
    });
    const dupDismiss$ = root.querySelector('[data-action="dup-dismiss"]');
    if (dupDismiss$) dupDismiss$.addEventListener('click', () => { state.duplikat = null; render(); });

    // Aktionen
    const create$ = root.querySelector('[data-action="create"]');
    if (create$ && !create$.disabled) create$.addEventListener('click', create);
    const retry$ = root.querySelector('[data-action="retry"]');
    if (retry$) retry$.addEventListener('click', () => { state.phase = 'loading'; render(); load(); });
    const recheck$ = root.querySelector('[data-action="recheck"]');
    if (recheck$) recheck$.addEventListener('click', () => { checkAuth(); loadAnlagen(); });
    const goto$ = root.querySelector('[data-action="goto-wk"]');
    if (goto$) goto$.addEventListener('click', () => navigate('/wettkampf'));
  }

  render();
  load();
  return root;
}

// --- Templates ----------------------------------------------------------------

function stepper(field, value, min) {
  return `
    <div class="stepper">
      <button type="button" class="step-btn" data-step="dec" data-field="${field}" aria-label="weniger">−</button>
      <input class="step-val" type="number" inputmode="numeric" min="${min}" value="${value}" data-input="${field}" />
      <button type="button" class="step-btn" data-step="inc" data-field="${field}" aria-label="mehr">+</button>
    </div>`;
}

function teamBlock(m, ichSlot) {
  const rows = (m.spieler || []).map((p) => {
    const ich = !!ichSlot && ichSlot === `${m.id}|${p.teamPos}`;
    return `
    <div class="player-row${ich ? ' is-ich' : ''}">
      <span class="player-idx">${p.teamPos}</span>
      <span class="player-name">${esc(p.name || '—')}${ich ? ' <small class="rank-team">★ das bist du</small>' : ''}</span>
      ${p.pass ? `<small class="rank-team">Pass ${esc(p.pass)}</small>` : ''}
    </div>`;
  }).join('') || '<p class="field-hint">Keine Aufstellung.</p>';
  return `
    <div class="roster-team">
      <h3 class="section-label">${esc(m.name)}</h3>
      <div class="players">${rows}</div>
    </div>`;
}

function anlageSection(s) {
  const options = `<option value="new"${s.anlageChoice === 'new' ? ' selected' : ''}>➕ Neu anlegen aus Sportwinner</option>`
    + s.anlagen.map((a) => `<option value="${esc(a.id)}"${s.anlageChoice === a.id ? ' selected' : ''}>${esc(a.name)}${a.ort ? ` (${esc(a.ort)})` : ''}${a.mein ? ' · eigene' : ''}</option>`).join('');

  const matchHint = s.anlagenLoaded && s.anlageChoice !== 'new'
    ? '<p class="field-hint">Bestehende Anlage gewählt — ihre Bahnen werden genutzt.</p>'
    : (s.anlagenLoaded && s.anlageChoice === 'new' && s.anlagen.length
      ? '<p class="field-hint">Kein passender Treffer — es wird eine neue Anlage angelegt (oben auswählbar).</p>' : '');

  let details;
  if (s.anlageChoice === 'new') {
    details = `
      <div class="players">
        <input class="join-input select-full" data-newanlage="name" type="text" placeholder="Anlagenname" value="${esc(s.newAnlage.name)}" />
        <input class="join-input select-full" data-newanlage="strasse" type="text" placeholder="Straße" value="${esc(s.newAnlage.strasse)}" />
        <input class="join-input select-full" data-newanlage="plz" type="text" placeholder="PLZ" value="${esc(s.newAnlage.plz)}" />
        <input class="join-input select-full" data-newanlage="ort" type="text" placeholder="Ort" value="${esc(s.newAnlage.ort)}" />
        <input class="join-input select-full" data-field="newbahnen" type="text" placeholder="Bahnen, z. B. 2-5" value="${esc(s.newBahnenText)}" />
      </div>
      <p class="field-hint">Wird als neue Anlage (Bahnart „${esc(ART_LABEL[s.preset] || s.preset)}") angelegt.</p>`;
  } else if (s.anlageBahnenLoading) {
    details = '<p class="field-hint">Lade Bahnen …</p>';
  } else {
    const laneChips = s.anlageBahnen.map((b) => {
      const a = b.bahnart ? (ART_LABEL[b.bahnart] || b.bahnart) : '';
      const on = s.playedLanes.includes(b.nummer);
      return `<button type="button" class="chip${on ? ' is-active' : ''}" data-playedlane="${b.nummer}">${b.nummer}${a ? ` <small>${esc(a)}</small>` : ''}</button>`;
    }).join('') || '<p class="field-hint">Diese Anlage hat keine Bahnen.</p>';
    details = `
      <label class="field-label">Bespielte Bahnen <small class="field-note">· antippen</small></label>
      <div class="chips">${laneChips}</div>
      <p class="field-hint">Gewählt: ${s.playedLanes.length} von ${s.anlageBahnen.length}</p>`;
  }

  return `
    <section class="field">
      <label class="field-label" for="sw-anlage">Anlage <small class="field-note">· abgeglichen</small></label>
      <select class="select-full" data-field="anlagewahl" id="sw-anlage">${options}</select>
      ${s.anlagenError ? `<p class="field-hint">${esc(s.anlagenError)}</p>` : ''}
      ${matchHint}
      ${details}
    </section>`;
}

function programmSection(s) {
  const tpp = throwsPerPart(s.wuerfeProSatz, s.teilsaetze.length);
  const divs = divisors(s.wuerfeProSatz);
  return `
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

function previewBody(s) {
  const spec = s.spec;
  const p = spec.partie;
  const metaLine = [
    p && p.liga ? p.liga : '',
    p && p.uhrzeit ? p.uhrzeit + ' Uhr' : '',
  ].filter(Boolean).join(' · ');

  const plan = planDurchgaenge({
    mannschaften: spec.mannschaften.map((m) => ({ id: m.id, name: m.name })),
    spielerJeMannschaft: s.spielerJeMannschaft, teamLanes: s.teamLanes,
  });
  const warnungen = (spec.warnungen || []).map((w) => `<p class="field-hint">⚠ ${esc(w)}</p>`).join('');

  return `
    ${duplikatBanner(s)}
    ${metaLine ? `<p class="stats-sub">${esc(metaLine)}</p>` : ''}

    <section class="field">
      <label class="field-label" for="sw-name">Name des Wettkampfs</label>
      <input class="join-input select-full" id="sw-name" data-field="name" type="text" value="${esc(s.name)}" />
    </section>
    <section class="field">
      <label class="field-label" for="sw-datum">Datum</label>
      <input class="join-input select-full" id="sw-datum" data-field="datum" type="date" value="${esc(s.datum)}" />
    </section>

    ${anlageSection(s)}
    ${programmSection(s)}

    <section class="field">
      <label class="field-label">Spieler je Mannschaft</label>
      ${stepper('spielerJeMannschaft', s.spielerJeMannschaft, 1)}
      <p class="field-hint">Sportwinner liefert keine Soll-Anzahl — Vorgabe aus der Aufstellung.</p>
    </section>

    ${startbahnenSection(s)}

    <section class="field">
      <label class="field-label">Mannschaften & Aufstellung <small class="field-note">· aus Sportwinner</small></label>
      ${spec.mannschaften.map((m) => teamBlock(m, s.ichSlot)).join('')}
      <p class="field-hint">${s.ichSlot
        ? '★ Deine LizenzID wurde in der Aufstellung erkannt — nur diese Ergebnisse zählen in deine Statistik.'
        : 'ℹ Hinterlege deine LizenzID unter „Spieler", damit deine eigenen Ergebnisse automatisch in deiner Statistik landen.'}</p>
      <p class="field-hint">🔒 Datenschutz: Die Namen werden bis zum Spielende an die verbundenen
        Geräte und Zuschauer übertragen und danach automatisch anonymisiert — dann steht dort
        der öffentliche Anzeigename des jeweiligen Profils, sonst „Mannschaft + Position".
        LizenzIDen verlassen dieses Gerät nicht im Klartext.</p>
    </section>

    <section class="field field-readout">
      <span class="field-label">Ergibt</span>
      <span class="readout">${plan.length} Durchgänge <small>(${spec.mannschaften.length} Teams · ${s.spielerJeMannschaft} Spieler)</small></span>
    </section>
    ${warnungen}`;
}

// Bereits vorhandener, nicht beendeter Wettkampf gleicher Spielnummer -> Hinweis + Aktionen.
function duplikatBanner(s) {
  const d = s.duplikat;
  if (!d || s.phase !== 'ready') return '';
  const lbl = { setup: 'in Vorbereitung', laufend: 'läuft' }[d.status] || d.status;
  return `
    <section class="field sw-dup">
      <p class="field-hint">⚠ Für diese Partie (Spielnr. ${esc(String(s.spec.sportwinner.spielNr))})
        existiert bereits ein Wettkampf „${esc(d.name || '—')}" (${esc(lbl)}).</p>
      <div class="field-row">
        <button type="button" class="btn-primary" data-action="dup-open">Vorhandenen öffnen</button>
        <button type="button" class="erf-btn" data-action="dup-del">Alten löschen & neu anlegen</button>
        <button type="button" class="erf-btn" data-action="dup-dismiss">Trotzdem neu anlegen</button>
      </div>
    </section>`;
}

// Startbahnen je Mannschaft: Chips aller bespielten Bahnen, exklusiv einem Team zugeordnet.
function startbahnenSection(s) {
  const played = sortNum(s.playedLanes);
  if (!played.length) return '';
  const artOf = (n) => {
    const b = (s.anlageBahnen || []).find((x) => x.nummer === n);
    return b && b.bahnart ? (ART_LABEL[b.bahnart] || b.bahnart) : '';
  };
  const teams = s.spec.mannschaften.map((m) => {
    const chips = played.map((n) => {
      const on = (s.teamLanes[m.id] || []).includes(n);
      const a = artOf(n);
      return `<button type="button" class="chip sm${on ? ' is-active' : ''}" data-teamlane="${esc(m.id)}" data-lane="${n}">${n}${a ? ` <small>${esc(a)}</small>` : ''}</button>`;
    }).join('');
    const leer = !(s.teamLanes[m.id] || []).length;
    return `
      <div class="team-block">
        <span class="section-label">${esc(m.name)}</span>
        <div class="chips team-lanes">${chips}</div>
        ${leer ? '<p class="field-hint">⚠ Keine Startbahn zugeordnet.</p>' : ''}
      </div>`;
  }).join('');
  return `
    <section class="field">
      <label class="field-label">Startbahnen je Mannschaft <small class="field-note">· antippen</small></label>
      ${teams}
      <p class="field-hint">Standard je Bahnart (${esc(ART_LABEL[s.preset] || s.preset)}); jede Bahn gehört genau einem Team.</p>
    </section>`;
}

function actionArea(s) {
  if (s.phase === 'done') {
    return `
      <section class="field">
        <label class="field-label">Beitritts-Code</label>
        <div class="field-row"><span class="erf-share-code">${esc(s.code || '—')}</span></div>
        <p class="field-hint">Wettkampf erstellt und geteilt. Andere Geräte treten unter „Spiel beitreten" mit diesem Code bei.</p>
        <button type="button" class="btn-primary" data-action="goto-wk">Zum Wettkampf</button>
      </section>`;
  }
  if (!s.authChecked) return '<p class="join-msg" role="status">Prüfe Konto …</p>';
  if (!s.darfAnlegen) {
    return `
      <section class="field">
        <p class="field-hint">Zum Anlegen der Anlage und zum Teilen brauchst du ein Konto.
        <a class="anl-inline-link" href="#/spieler">Jetzt anmelden →</a></p>
        <button type="button" class="btn-primary" data-action="recheck">Erneut prüfen</button>
      </section>`;
  }
  const busy = s.phase === 'creating';
  const teamsOk = s.spec && s.spec.mannschaften.every((m) => (s.teamLanes[m.id] || []).length);
  const bereit = !!(s.playedLanes.length && teamsOk
    && (s.anlageChoice !== 'new' || (s.newAnlage.name || '').trim()));
  const disabled = busy || !bereit;
  return `
    <button type="button" class="btn-primary" data-action="create"${disabled ? ' disabled' : ''}>
      ${busy ? 'Erstelle …' : 'Wettkampf erstellen & Beitrittscode'}
    </button>
    ${!bereit && !busy ? `<p class="field-hint">${teamsOk ? 'Anlage/Bahnen wählen.' : 'Jeder Mannschaft mindestens eine Startbahn zuordnen.'}</p>` : ''}
    <p class="join-msg" data-sync-msg role="status">${esc(s.msg || '')}</p>`;
}

function template(s) {
  let body;
  if (s.phase === 'loading') {
    body = '<p class="join-msg" role="status">Lade Sportwinner-Daten …</p>';
  } else if (s.phase === 'error') {
    body = `
      <p class="field-hint">${esc(s.error)}</p>
      <button type="button" class="btn-primary" data-action="retry">Erneut versuchen</button>`;
  } else {
    body = previewBody(s) + actionArea(s);
  }
  return `
    <header class="page-header">
      <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
      <h1 class="page-title">Aus Sportwinner</h1>
    </header>
    <div class="setup">${body}</div>`;
}
