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

import { getActiveGame, getGame, saveGame, saveErfassung, setGameStatus, getStandardbilder, saveStandardbilder, getSettings, saveSettings } from '../store.js';
import { esc } from '../util.js';
import { teilsatzRanges } from '../logic/teilsaetze.js';
import { computeGameStats } from '../logic/statistik.js';
import {
  fullPins, isAbraeumMode, rangeOfThrow, defaultKegel,
  abraeumScan, abraeumStateBefore, volleKranz,
} from '../logic/abraeumen.js';
import { teilsatzStats, satzHolz, satzStatus } from '../logic/holz.js';
import { computeBahnState as computeBahnStatePure } from '../logic/bahnwechsel.js';

const MODUS_LABEL = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz-Abräumen' };
// Kurzform der Teilsatz-Beschreibung für die Wurfzeile (gleich lang -> gleiche Breite).
const MODUS_ABK = { volle: 'Vo', abraeumen: 'Ab', 'kranz-abraeumen': 'Kr' };
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

// Ziffernblock-Belegung des Pop-ups/Positions-Rasters (numpad-Reihenfolge, 12 Zellen).
// Die 9 Ziffern tragen die Bilder; 'manual' liegt auf der 0, die beiden unteren Ecken bleiben leer.
const PICK_CELLS = [7, 8, 9, 4, 5, 6, 1, 2, 3, 'undo', 'manual', 'settings'];
// Reihenfolge, in der freie Felder automatisch vergeben werden (oben-links zuerst).
const SB_SLOT_ORDER = [7, 8, 9, 4, 5, 6, 1, 2, 3];

// Für die Abräum-Schnellauswahl: Spalte (Raster-c) und Reihe (Raster-r) je Kegel aus der
// Rauten-Anordnung, plus die Pop-up-Felder spaltenweise (oben->unten). Damit lassen sich die
// automatisch erzeugten Bilder räumlich passend verteilen: rechts stehende Kegel -> rechts.
const PIN_COL = {}; const PIN_ROW = {};
KEGEL_LAYOUT.forEach((p) => { PIN_COL[p.n] = p.c; PIN_ROW[p.n] = p.r; });
// Pop-up-Felder je Spalte, oben -> unten (Numpad-Lage: 7/8/9 · 4/5/6 · 1/2/3).
const PICK_COL_SLOTS = [[7, 4, 1], [8, 5, 2], [9, 6, 3]];

// Automatisch erzeugte Abräum-Bilder auf die Pop-up-Felder legen, sortiert nach Kegel-Seite:
// Bilder mit Kegeln weiter rechts wandern nach rechts, weiter links nach links (innerhalb einer
// Spalte oben/unten nach vertikaler Lage). Läuft eine Spalte über, rutscht das Bild in die
// nächste freie Spalte (von innen nach außen).
function assignPickSlots(combos) {
  const items = combos.map((pins) => {
    const hx = pins.reduce((s, p) => s + PIN_COL[p], 0) / pins.length; // 1..5 (links..rechts)
    const vy = pins.reduce((s, p) => s + PIN_ROW[p], 0) / pins.length; // 1..5 (oben..unten)
    const col = hx < 2.5 ? 0 : hx > 3.5 ? 2 : 1;                       // 0=links,1=mitte,2=rechts
    return { pins, col, vy };
  });
  items.sort((a, b) => a.col - b.col || a.vy - b.vy);
  const free = PICK_COL_SLOTS.map((s) => s.slice());
  const out = [];
  items.forEach((it) => {
    let slot = null;
    for (const off of [0, -1, 1, -2, 2]) {          // Ziel-Spalte, dann nach außen ausweichen
      const c = it.col + off;
      if (c >= 0 && c <= 2 && free[c].length) { slot = free[c].shift(); break; }
    }
    out.push({ pins: it.pins, slot: slot == null ? SB_SLOT_ORDER[out.length] : slot });
  });
  return out;
}

// Standard-Bilder in die neue Form { pins:[…], slot:1-9 } bringen (und alte Form
// [[pins],…] migrieren, indem freie Slots vergeben werden). Je Zahl max. ein Bild pro Slot.
function normalizeStandardbilder(map) {
  const out = {};
  Object.keys(map || {}).forEach((k) => {
    const n = parseInt(k, 10);
    if (!(n >= 1 && n <= 8) || !Array.isArray(map[k])) return;
    const used = new Set();
    const items = [];
    map[k].forEach((e) => {
      const pins = Array.isArray(e) ? e : (e && Array.isArray(e.pins) ? e.pins : null);
      if (!pins) return;
      const clean = pins.filter((p) => p >= 1 && p <= 9);
      if (clean.length !== n) return;
      let slot = (!Array.isArray(e) && e.slot >= 1 && e.slot <= 9) ? e.slot : null;
      if (slot != null && used.has(slot)) slot = null;
      items.push({ pins: clean.slice().sort((a, b) => a - b), slot });
      if (slot != null) used.add(slot);
    });
    items.forEach((it) => {
      if (it.slot == null) {
        const free = SB_SLOT_ORDER.find((s) => !used.has(s));
        if (free != null) { it.slot = free; used.add(free); }
      }
    });
    const kept = items.filter((it) => it.slot != null);
    if (kept.length) out[n] = kept;
  });
  return out;
}

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
  root.className = 'view view-page erf-screen';

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
  let flashTs = 0; // Zeitstempel des zuletzt erfassten Wurfs: die aktuelle Wurfzahl blitzt danach kurz auf (Klick-Feedback, bei JEDEM Wert). Zeitfenster statt Render-Reset, damit ein Folge-Render (z. B. das Kegel-Popup) den Blitz nicht verschluckt.
  let pinMode = 'stehend'; // 'gefallen' | 'stehend' — welche Seite die Kegel-Raute erfasst (Default: Stehende)
  let lpSuppress = 0; // Zeitstempel: unterdrückt den Klick direkt nach einem Langdruck (König)
  let settingsOpen = false; // Einstellungsmenü (⚙) offen? — enthält u.a. die Spiel-Details
  let laneSettingsOpen = false; // Bahneinstellung (⚙ in der Satz-Kopfzeile) offen?
  let satzOverviewOpen = false; // Spieler-Übersicht (inline, statt Wurferfassung) offen?
  let ueberTab = 'uebersicht'; // aktiver Tab der Übersicht: 'uebersicht' (Bahnen editieren) | 'statistik' | 'verteilung' (Wurf-Häufigkeit)
  let overrideSt = null; // Satz-Index, dessen Ergebnis-Sheet offen ist (null = zu); bearbeitet wird aus der Übersicht
  let overrideTs = null; // Teilsatz-Index im Sheet (null = ganzes Satz-Ergebnis eingeben -> auf offenen Teilsatz verteilen)
  let overrideDraft = ''; // im Override-Sheet eingetippte Ziffern
  let standardbilder = normalizeStandardbilder(getStandardbilder()); // globale Schnellauswahl-Bilder (Zahl -> Liste { pins, slot })
  let pinPick = null; // offenes Schnellauswahl-Pop-up: { idx, n, combos } (null = zu)
  let sbEditN = 1; // in den Einstellungen gerade bearbeitete Holzzahl (1-8)
  let sbDraft = []; // im Einstellungs-Editor angetippte Kegel für das neue Bild
  let settings = getSettings(); // globale App-Einstellungen (u.a. ob Vorschläge gezeigt werden)
  let statsOpen = game.status === 'beendet'; // Statistik-Vollbild offen? (bei Reload eines beendeten Spiels direkt zeigen)
  let finishSeen = statsOpen; // Spielende schon einmal automatisch gemeldet -> nicht bei jedem Render neu aufpoppen

  function persist() {
    if (saveErfassung(gameId, state) === null) toast('Speichern fehlgeschlagen — Speicher voll?');
    pushDirty();
  }
  // Wie persist(), aber ohne Hochschreiben — für lokal übernommene Remote-Änderungen
  // (die dürfen nicht als eigener Push zurücklaufen).
  function persistLocalOnly() { saveErfassung(gameId, state); }

  // ── Mehrgeräte-Sync (nur bei einem mit der DB verknüpften Spiel) ─────────────
  // Local-first bleibt: ein unverknüpftes Spiel läuft rein lokal wie bisher. Bei einem
  // verknüpften Spiel schreibt DIESES Gerät nur die Würfe seiner EIGENEN Spieler hoch und
  // übernimmt fremde Änderungen live. Ein Spieler gehört immer genau einem Gerät.
  let linked = !!(game.linked && game.remoteId);
  let syncMod = null;                     // lazy geladenes backend/sync.js
  let meGeraet = null;                    // eigene Geräte-uid
  let owners = game.spielerOwners || {};  // position -> { id, besitzer, heartbeat }
  let unsub = null;                       // Realtime abmelden
  let hbTimer = null;                     // Heartbeat-Intervall
  const lastPushed = {};                  // "sp:st" -> JSON des zuletzt gepushten Blocks (Diff-Push)

  function ownerOf(sp) { return owners[sp] || null; }
  // Darf dieses Gerät den Spieler bearbeiten? Unverknüpft immer ja (lokal). Verknüpft nur,
  // wenn ich ihn besitze; freie/fremde Spieler sind gesperrt (erst „Übernehmen").
  function canEdit(sp) {
    if (!linked) return true;
    const o = ownerOf(sp);
    if (!o) return true;                  // Besitz noch nicht geladen -> nicht blockieren
    return o.besitzer === meGeraet;
  }
  function fremdAktiv(sp) {
    return linked && !!syncMod && syncMod.istFremdAktiv(ownerOf(sp), meGeraet);
  }
  // Sperr-Feedback für die mutierenden Aktionen. true = darf bearbeiten.
  function guardEdit() {
    if (canEdit(state.aktiverSpieler)) return true;
    const o = ownerOf(state.aktiverSpieler);
    toast(o && o.besitzer ? '🔒 Wird auf anderem Gerät erfasst' : 'Bahn frei — erst „Übernehmen"');
    return false;
  }

  // Geänderte Blöcke EIGENER Spieler in die DB schreiben (Diff gegen den letzten Push).
  function pushDirty() {
    if (!linked || !syncMod || !meGeraet) return;
    state.bloecke.forEach((satzArr, sp) => {
      if (!canEdit(sp)) return;
      const pid = owners[sp] && owners[sp].id;
      if (!pid) return;
      satzArr.forEach((blk, st) => {
        const key = sp + ':' + st;
        const snap = JSON.stringify(blk);
        if (lastPushed[key] === snap) return;
        lastPushed[key] = snap;
        syncMod.pushBlock(game.remoteId, pid, st, blk).catch(() => { delete lastPushed[key]; });
      });
    });
  }
  function seedPushed() {
    state.bloecke.forEach((satzArr, sp) => satzArr.forEach((blk, st) => {
      lastPushed[sp + ':' + st] = JSON.stringify(blk);
    }));
  }

  // Eingehende Realtime-Änderung eines FREMDEN Spielers in den lokalen Stand übernehmen.
  function onRemoteBlock(row) {
    if (!row || row.geraet === meGeraet) return;   // eigene Echos ignorieren
    let pos = null;
    for (const p in owners) if (owners[p].id === row.spieler_id) { pos = +p; break; }
    if (pos == null || !state.bloecke[pos] || state.bloecke[pos][row.satz] === undefined) return;
    state.bloecke[pos][row.satz] = row.block_json || state.bloecke[pos][row.satz];
    lastPushed[pos + ':' + row.satz] = JSON.stringify(state.bloecke[pos][row.satz]);
    persistLocalOnly();
    render();
  }
  function onRemoteSpieler(row) {
    if (!row || row.position == null) return;
    const prev = owners[row.position] || {};
    owners[row.position] = { id: row.id || prev.id, besitzer: row.besitzer_geraet, heartbeat: row.heartbeat_am };
    render();
  }

  function beat() {
    if (!root.isConnected) { teardownSync(); return; }
    if (syncMod && meGeraet) syncMod.heartbeat(game.remoteId).catch(() => {});
  }
  function teardownSync() {
    if (hbTimer) { clearInterval(hbTimer); hbTimer = null; }
    if (unsub) { try { unsub(); } catch (e) {} unsub = null; }
    window.removeEventListener('hashchange', teardownSync);
  }
  function startRealtime() {
    if (unsub) return;
    unsub = syncMod.subscribe(game.remoteId, { onBlock: onRemoteBlock, onSpieler: onRemoteSpieler });
    beat();
    hbTimer = setInterval(beat, 12000);
  }

  // Beim Öffnen eines bereits verknüpften Spiels: Besitz + fremde Blöcke frisch laden,
  // Realtime abonnieren, Heartbeat starten. Fällt still auf lokal zurück, wenn offline.
  async function initSync() {
    if (!linked) return;
    try {
      syncMod = await import('../backend/sync.js');
      meGeraet = await syncMod.ensureGeraet();
      const fresh = await syncMod.pullGame(game.remoteId);
      owners = fresh.spielerOwners || owners;
      if (fresh.erfassung && Array.isArray(fresh.erfassung.bloecke)) {
        fresh.erfassung.bloecke.forEach((satzArr, sp) => {
          if (canEdit(sp)) return;         // meine Spieler bleiben wie lokal
          satzArr.forEach((blk, st) => {
            if (state.bloecke[sp] && state.bloecke[sp][st] !== undefined) state.bloecke[sp][st] = blk;
          });
        });
      }
      seedPushed();
      startRealtime();
      render();
    } catch (e) { /* offline / CDN nicht erreichbar -> lokal weiterspielen */ }
  }
  window.addEventListener('hashchange', teardownSync);

  // Lokales Spiel teilen: in Supabase spiegeln, ab jetzt verknüpft + Realtime.
  async function shareGame() {
    try {
      if (!syncMod) syncMod = await import('../backend/sync.js');
      game.erfassung = state;
      const res = await syncMod.linkGame(game);
      meGeraet = await syncMod.ensureGeraet();
      game.linked = true; game.remoteId = res.remoteId; game.beitrittsCode = res.beitrittsCode;
      linked = true;
      owners = {};
      Object.keys(res.posToId).forEach((pos) => {
        owners[pos] = { id: res.posToId[pos], besitzer: meGeraet, heartbeat: new Date().toISOString() };
      });
      game.spielerOwners = owners;
      saveGame(game);
      seedPushed();
      startRealtime();
      toast('Spiel geteilt · Code ' + res.beitrittsCode);
      render();
    } catch (e) { toast('Teilen fehlgeschlagen — online?'); }
  }
  async function claimActive() {
    const sp = state.aktiverSpieler; const o = ownerOf(sp);
    if (!syncMod || !o || !o.id) return;
    try {
      const ok = await syncMod.claimPlayer(o.id);
      if (!ok) { toast('Noch aktiv auf anderem Gerät'); return; }
      owners[sp] = { ...o, besitzer: meGeraet, heartbeat: new Date().toISOString() };
      state.bloecke[sp].forEach((blk, st) => { lastPushed[sp + ':' + st] = JSON.stringify(blk); });
      toast('Bahn übernommen'); render();
    } catch (e) { toast('Übernehmen fehlgeschlagen'); }
  }
  async function releaseActive() {
    const sp = state.aktiverSpieler; const o = ownerOf(sp);
    if (!syncMod || !o || !o.id) return;
    try {
      await syncMod.releasePlayer(o.id);
      owners[sp] = { ...o, besitzer: null };
      laneSettingsOpen = false;
      toast('Bahn freigegeben'); render();
    } catch (e) { toast('Freigeben fehlgeschlagen'); }
  }
  // Bei Spielende einen Ergebnis-Snapshot je EIGENEM Spieler in die DB schreiben
  // (für die geräteübergreifende Statistik-Historie). Best-effort.
  function pushResults() {
    if (!linked || !syncMod || !meGeraet) return;
    try {
      const { players } = computeGameStats(c, state.bloecke, ranges);
      const rows = [];
      players.forEach((p, sp) => {
        if (!canEdit(sp)) return;
        const pid = owners[sp] && owners[sp].id;
        if (!pid) return;
        rows.push({
          spiel_id: game.remoteId, spieler_id: pid, profil_id: meGeraet,
          gesamt: p.gesamt, schnitt_satz: p.schnittSatz, schnitt_wurf: p.schnittWurf,
          bester_satz: p.bester, neuner: p.neuner, fehl: p.fehl, wurf_count: p.wurfCount, rang: p.rang,
        });
      });
      if (rows.length) syncMod.pushResults(rows).catch(() => {});
    } catch (e) { /* Snapshot ist best-effort */ }
  }
  function block(sp, st) { return state.bloecke[sp][st]; }
  function current() { return block(state.aktiverSpieler, state.aktiverSatz); }
  function laneOf(sp, st) { return c.bahnplan?.[sp]?.[st] ?? (c.ersteBahn + st); }
  function playerName(sp) { return c.spielerListe[sp].name || ('Spieler ' + (sp + 1)); }
  function playerTotal(sp) { return state.bloecke[sp].reduce((s, blk) => s + satzHolz(blk, ranges), 0); }

  // Effektive Wurfzahl eines Satz-Blocks fürs Anzeigen: ein manuell gesetzter Teilsatz zählt als
  // vollständig (Soll-Würfe), sonst die tatsächlich erfassten Würfe im Teilsatz-Bereich. Deckungs-
  // gleich mit der Statistik (computeGameStats.wurfCount) und dem Teilsatz-Zähler (teilsatzStats.count),
  // damit die Wurfzahl nach einer manuellen Eingabe überall gleich hochzählt (Bahn-Tabs, Kegelbrett).
  function wuerfeCount(blk) {
    return ranges.reduce((s, r, i) => {
      const manual = Array.isArray(blk.overrides) && blk.overrides[i] != null;
      const actual = blk.wuerfe.slice(r.start, r.end).length;
      return s + (manual ? r.soll : actual);
    }, 0);
  }

  // Teilsatz-Spaltenlabels (Vo, Ab, Kr …); kommt derselbe Modus mehrfach vor, durchnummerieren.
  function teilsatzLabels() {
    const modusN = {};
    ranges.forEach((r) => { modusN[r.modus] = (modusN[r.modus] || 0) + 1; });
    const seen = {};
    return ranges.map((r) => {
      const abk = MODUS_ABK[r.modus] || r.modus;
      if (modusN[r.modus] > 1) { seen[r.modus] = (seen[r.modus] || 0) + 1; return `${abk}${seen[r.modus]}`; }
      return abk;
    });
  }

  // Ein Teilsatz gilt als "offen" (noch kein Ergebnis), wenn er weder manuell gesetzt ist noch
  // seine Soll-Würfe vollständig erfasst sind. Rückgabe: Indizes der offenen Teilsätze.
  function openTeilsaetze(blk) {
    const done = satzStatus(blk) === 'done';
    const open = [];
    ranges.forEach((_, i) => {
      const t = teilsatzStats(blk, ranges, i, done);
      if (!(t.manual || t.count === t.soll)) open.push(i);
    });
    return open;
  }

  // Summe der bereits bekannten Teilsätze eines Satzes (ohne den ausgeschlossenen Index).
  function knownTeilsatzSum(blk, exclude) {
    const done = satzStatus(blk) === 'done';
    return ranges.reduce((s, _, i) =>
      (i === exclude ? s : s + teilsatzStats(blk, ranges, i, done).val), 0);
  }

  // Nach einer manuellen Ergebnis-Eingabe: haben ALLE Teilsätze ein Ergebnis (manuell oder volle
  // Würfe), wird der Satz automatisch abgeschlossen — genau wie ein vollständig geworfener Satz.
  // Bewusst OHNE Bahnwechsel-Gate (manuelle Endergebnisse dürfen jederzeit abschließen).
  // Rückgabe: true, wenn gerade abgeschlossen wurde (für die Rückmeldung).
  function autoCloseIfComplete(blk) {
    if (!blk.done && openTeilsaetze(blk).length === 0) { blk.done = true; return true; }
    return false;
  }

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
    overrideSt = null; overrideTs = null; overrideDraft = '';
    persist(); render();
  }
  function selectSatz(st) {
    state.aktiverSatz = st; editIdx = null;
    overrideSt = null; overrideTs = null; overrideDraft = '';
    persist(); render();
  }

  // koenigFlag (nur Kranz, per Langdruck): der Wurf fällt N Kranz-Kegel, der König (5)
  // bleibt stehen. Genaue Kranz-Kegel bleiben offen (kegel=null), gespeichert wird nur,
  // DASS der König danach noch steht (blk.koenig[idx]=true).
  function addWurf(pins, koenigFlag = false) {
    if (!guardEdit()) return false;
    const blk = current();
    if (!Array.isArray(blk.koenig)) blk.koenig = blk.wuerfe.map(() => false);
    if (editIdx !== null) {
      if (editIdx < blk.wuerfe.length) {
        const ctx = throwContext(blk, editIdx);
        const cap = koenigFlag ? ctx.maxPins - 1 : ctx.maxPins;
        if (ctx.abraeum && pins > cap) { toast(`Es stehen nur ${cap} ${koenigFlag ? 'Kranz-' : ''}Kegel`); return false; }
        blk.wuerfe[editIdx] = pins;
        blk.kegel[editIdx] = koenigFlag ? null : defaultKegelFor(blk, editIdx, pins);
        blk.koenig[editIdx] = koenigFlag;
      }
      const idx = editIdx;
      editIdx = null; flashTs = Date.now(); persist(); render();
      toast(koenigFlag ? `Wurf #${idx + 1} korrigiert · König steht` : `Wurf #${idx + 1} korrigiert`); return true;
    }
    if (blk.done) { toast('Satz ist fertig'); return false; }
    if (blk.wuerfe.length >= c.wuerfeProSatz) { toast('Satz voll — alle Würfe erfasst'); return false; }
    // In einen späteren Satz eintragen ist gesperrt, solange ein früherer noch offen ist.
    const front = frontSatz();
    if (state.aktiverSatz > front) { toast(`Erst Satz ${front + 1} abschließen`); return false; }
    // Ein Spieler kann maximal auf EINEN Bahnwechsel warten: steht der Wechsel nach einem
    // fertigen Satz noch aus (physisch noch auf der alten Bahn), darf der nächste Satz noch
    // nicht bespielt werden. Sonst würde man einen zweiten Bahnwechsel „vorziehen".
    if (state.aktiverSatz > computeBahnState()[state.aktiverSpieler].pos) {
      toast('Erst Bahnwechsel abwarten'); return false;
    }
    const idx = blk.wuerfe.length;
    const ctx = throwContext(blk, idx);
    const cap = koenigFlag ? ctx.maxPins - 1 : ctx.maxPins;
    if (ctx.abraeum && pins > cap) { toast(`Es stehen nur ${cap} ${koenigFlag ? 'Kranz-' : ''}Kegel`); return false; }
    blk.wuerfe.push(pins);
    blk.kegel.push(koenigFlag ? null : defaultKegelFor(blk, idx, pins));
    blk.koenig.push(koenigFlag);
    // Sind mit diesem Wurf alle Teilsätze voll (alle Soll-Würfe des Satzes erfasst), wird der
    // Satz automatisch beendet — kein manuelles Abschließen mehr nötig. Da die Würfe die
    // Teilsätze der Reihe nach füllen, ist das genau erreicht, wenn wuerfeProSatz voll ist.
    const autoDone = blk.wuerfe.length >= c.wuerfeProSatz;
    if (autoDone) blk.done = true;
    flashTs = Date.now(); persist(); render();
    if (autoDone) toast('Satz automatisch beendet');
    else if (koenigFlag) toast('König bleibt stehen');
    return true;
  }

  // Alle k-elementigen Teilmengen von `arr` (aufsteigend, lexikografisch) als Kegel-Listen.
  function subsets(arr, k) {
    const res = [];
    const pick = (start, acc) => {
      if (acc.length === k) { res.push(acc.slice()); return; }
      for (let i = start; i < arr.length; i++) { acc.push(arr[i]); pick(i + 1, acc); acc.pop(); }
    };
    pick(0, []);
    return res;
  }

  // Verfügbare Schnellauswahl-Bilder für Zahl n im Kontext des Ziel-Wurfs.
  //   Volle (oder Abräumen aufs VOLLE Bild, wenn wieder alle 9 stehen):
  //             die hinterlegten Standard-Bilder mit genau n gefallenen Kegeln.
  //   Abräumen auf Rest-Kegel: die Rest-Kegel stehen exakt fest -> die möglichen Bilder sind
  //             ALLE Arten, n der stehenden Kegel fallen zu lassen. Diese werden automatisch
  //             erzeugt (kein manuelles Hinterlegen nötig) und nach Kegel-Seite auf die 9
  //             Pop-up-Felder verteilt. Mehr als 9 Möglichkeiten passen nicht ins Raster ->
  //             kein Pop-up, dann wird die Raute wie gewohnt von Hand gewählt. Ist die
  //             Restmenge unbekannt (count-only), gibt es keine Vorschläge -> Wurf direkt.
  function combosFor(n, ctx) {
    // Volle oder Abräumen aufs volle Bild (alle 9 stehen) -> hinterlegte Standard-Bilder.
    if (!ctx.abraeum || (ctx.exact && ctx.universe.length >= 9)) {
      const list = standardbilder[n];
      if (!Array.isArray(list) || list.length === 0) return [];
      return list.filter((it) => Array.isArray(it.pins) && it.pins.length === n);
    }
    if (!ctx.exact) return [];
    const U = ctx.universe.slice().sort((a, b) => a - b);
    const subs = subsets(U, n);
    if (subs.length === 0 || subs.length > SB_SLOT_ORDER.length) return [];
    return assignPickSlots(subs);
  }

  // Zahl am Ziffernblock getippt: Wurf normal setzen. Gibt es für diese Zahl hinterlegte
  // Standard-Bilder (im aktuellen Kontext), danach das Schnellauswahl-Pop-up öffnen — sonst
  // bleibt es beim direkten Setzen wie bisher.
  function tapNumber(n) {
    const blk = current();
    const idx = editIdx !== null ? editIdx : blk.wuerfe.length;
    const ctx = throwContext(blk, idx);
    // Vorschläge in den Einstellungen deaktiviert -> nie ein Pop-up, Wurf wie gehabt direkt setzen.
    const combos = settings.vorschlaege ? combosFor(n, ctx) : [];
    if (!addWurf(n)) return;
    if (!combos.length) return;
    // Beim Abräumen auf REST-Kegel bleibt oft nur EIN mögliches Bild übrig — dann direkt setzen
    // statt ein Pop-up mit nur einer Option zu zeigen. Aufs volle Bild (alle 9 stehen) wird
    // dagegen wie in der Volle gearbeitet: Pop-up auch bei nur einem Standard-Bild.
    if (ctx.abraeum && ctx.universe.length < 9 && combos.length === 1) { applyPinImage(idx, combos[0]); return; }
    pinPick = { idx, n, combos };
    render();
  }

  // Ein Standard-Bild für den Ziel-Wurf übernehmen: dessen Kegel exakt setzen.
  function applyPinImage(idx, combo) {
    const blk = current();
    if (combo && idx < blk.wuerfe.length) {
      blk.kegel[idx] = combo.pins.slice();
      if (Array.isArray(blk.koenig)) blk.koenig[idx] = false;
    }
    persist(); render();
  }

  // Ein Standard-Bild aus dem Pop-up gewählt.
  function choosePinImage(ci) {
    const p = pinPick;
    pinPick = null;
    if (!p) return;
    applyPinImage(p.idx, p.combos[ci]);
  }

  function setPinMode(mode) {
    if (pinMode === mode) return;
    pinMode = mode;
    render();
  }

  // Vorschläge (Schnellauswahl-Pop-up) global an-/ausschalten; sofort persistieren.
  function toggleVorschlaege() {
    settings = { ...settings, vorschlaege: !settings.vorschlaege };
    saveSettings({ vorschlaege: settings.vorschlaege });
    toast(settings.vorschlaege ? 'Vorschläge an' : 'Vorschläge aus');
    render();
  }

  // Kegel p (1-9) fuer den Ziel-Wurf antippen. Der Ziffernblock gibt die Holzzahl N vor.
  // Gefallener Kegel LEUCHTET, stehender ist aus. F = gefallene (leuchtende) Kegel.
  //   "gefallen": Grundzustand alle aus, die N gefallenen einschalten.
  //   "stehend":  Grundzustand alle an (alle gefallen), die 9-N stehenden ausschalten.
  function tapPin(p) {
    if (!guardEdit()) return;
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
    if (!guardEdit()) return;
    const blk = current();
    if (blk.wuerfe.length === 0) { toast('Nichts rückgängig zu machen'); return; }
    blk.wuerfe.pop();
    blk.kegel.pop();
    if (Array.isArray(blk.koenig)) blk.koenig.pop();
    persist(); render();
  }

  function deleteEditing() {
    if (!guardEdit()) return;
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
    if (!guardEdit()) return;
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
    if (!guardEdit()) return;
    const bloecke = state.bloecke[state.aktiverSpieler];
    const allDone = bloecke.every((b) => b.done);
    bloecke.forEach((b) => { b.done = !allDone; });
    laneSettingsOpen = false;
    persist(); render();
    toast(allDone ? 'Spiel wieder geöffnet' : 'Spiel beendet – Bahn frei');
  }

  // Ein Spieler ist fertig, wenn alle seine Sätze beendet sind; das ganze Spiel ist beendet,
  // sobald das für JEDEN Spieler gilt.
  function allGamesDone() {
    return state.bloecke.every((arr) => arr.length > 0 && arr.every((b) => b.done));
  }

  // Übergang ins Spielende erkennen und einmalig die Statistik zeigen. Wird zu Beginn jedes
  // Renders geprüft (nachdem die Würfe/Done-Flags in `persist()` schon gespeichert sind):
  //   - alle fertig & noch nicht gemeldet -> Statistik automatisch öffnen + Status 'beendet'.
  //   - wieder ein Satz offen -> zurück auf 'laufend' (Statistik schließt sich).
  function maybeFinish() {
    const done = allGamesDone();
    if (done && !finishSeen) {
      finishSeen = true;
      statsOpen = true;
      setGameStatus(gameId, 'beendet');
      pushResults();
    } else if (!done && finishSeen) {
      finishSeen = false;
      statsOpen = false;
      setGameStatus(gameId, 'laufend');
    }
  }

  // ── Standard-Bilder verwalten (Einstellungen) ──
  function persistStandardbilder() {
    if (!saveStandardbilder(standardbilder)) toast('Speichern fehlgeschlagen — Speicher voll?');
  }
  function setSbEditN(n) { sbEditN = n; sbDraft = []; render(); }
  function toggleSbPin(p) {
    const i = sbDraft.indexOf(p);
    if (i >= 0) sbDraft.splice(i, 1);
    else if (sbDraft.length < sbEditN) { sbDraft.push(p); sbDraft.sort((a, b) => a - b); }
    else { toast(`Genau ${sbEditN} Kegel wählen`); return; }
    render();
  }
  // Das aktuelle Draft-Bild auf ein freies Feld (Slot = Ziffer 1-9) des Positions-Rasters legen.
  function placeSbImage(slot) {
    if (sbDraft.length !== sbEditN) { toast(`Erst ${sbEditN} Kegel wählen`); return; }
    const list = Array.isArray(standardbilder[sbEditN]) ? standardbilder[sbEditN].slice() : [];
    if (list.some((it) => it.slot === slot)) { toast('Feld ist belegt'); return; }
    if (list.some((it) => it.pins.join(',') === sbDraft.join(','))) { toast('Bild gibt es schon'); return; }
    list.push({ pins: sbDraft.slice(), slot });
    standardbilder[sbEditN] = list;
    sbDraft = [];
    persistStandardbilder(); render();
    toast(`Bild auf Feld ${slot} gelegt`);
  }
  function deleteSbImage(n, slot) {
    const list = standardbilder[n];
    if (!Array.isArray(list)) return;
    const i = list.findIndex((it) => it.slot === slot);
    if (i < 0) return;
    list.splice(i, 1);
    if (list.length === 0) delete standardbilder[n];
    persistStandardbilder(); render();
    toast('Bild gelöscht');
  }

  // ── Render ──
  function render() {
    maybeFinish();
    root.innerHTML = template();
    wire();
    keepThrowVisible();
    fitBoard();
    positionPinPick();
  }

  // Kegel-Raute so groß machen, wie der freie Platz in der Satz-Box zulässt — damit alles
  // (Raute + Chips + Ziffernblock) ohne Scrollen und ohne Überlappen auf einen Screen passt.
  // Die Raute ist der einzige flexible Block; Chips/Ziffernblock behalten ihre feste Höhe.
  // Deshalb genügt ein einziger Durchlauf: die Kegelgröße ändert die Box-Aufteilung nicht.
  function fitBoard() {
    const grid = root.querySelector('.erf-kegel-grid');
    const kegel = root.querySelector('.erf-kegel');
    if (!grid || !kegel) return;
    // Beim allerersten Render ist root noch nicht im DOM (der Router hängt es erst danach ein) —
    // dann sind Maße/Styles leer. Auf den nächsten Frame warten, bis das Layout steht.
    if (!root.isConnected || kegel.clientHeight === 0) {
      fitBoard._tries = (fitBoard._tries || 0) + 1;
      if (fitBoard._tries < 30) requestAnimationFrame(fitBoard);
      return;
    }
    fitBoard._tries = 0;
    const num = (v) => { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; };
    const head = kegel.querySelector('.erf-kegel-head');
    const foot = kegel.querySelector('.erf-kegel-foot');   // enthält jetzt Ecken-Stats + Wurfergebnis in einer Zeile
    const body = kegel.querySelector('.erf-kegel-body');
    const ks = getComputedStyle(kegel);
    const gs = getComputedStyle(grid);
    const padY = num(ks.paddingTop) + num(ks.paddingBottom);
    const padX = num(ks.paddingLeft) + num(ks.paddingRight);
    const kegelGap = num(ks.rowGap);                            // Abstand Kopf/Body/Fuß
    const headH = head ? head.getBoundingClientRect().height : 0;
    const footNat = foot ? foot.getBoundingClientRect().height : 0;  // volle (2-zeilige) Fußhöhe
    // Kegel-Box stapelt Kopf · Body · Fuß -> so viele Lücken wie sichtbare Kinder − 1.
    const gapsY = kegelGap * Math.max(0, [head, body, foot].filter(Boolean).length - 1);
    const rowGap = num(gs.rowGap);
    const colGap = num(gs.columnGap);
    // Kleiner seitlicher Sicherheitsabstand, damit die Raute nicht am Box-Rand klebt.
    // (Der Modus-Umschalter sitzt oben im Kopf, nicht neben der Raute -> keine Breiten-Reservierung.)
    const sideGap = 4;
    // Vom Fuß nur (Naturhöhe − LIFT_MAX) reservieren: die Raute darf um bis zu LIFT_MAX tiefer
    // reichen; die obere Ecken-Zeile wird per margin-top wieder in die Raute überlappt, während
    // Wurf + untere Ecken-Zahlen auf einer Ebene UNTER der Raute bleiben.
    const LIFT_MAX = 16;
    const footReserve = Math.max(0, footNat - LIFT_MAX);
    // Freie Höhe/Breite für das 5×5-Raster innerhalb der (flexibel zugeteilten) Kegel-Box.
    const availH = kegel.clientHeight - padY - headH - footReserve - gapsY;
    const availW = kegel.clientWidth - padX - 2 * sideGap;
    const byW = (availW - 4 * colGap) / 5;
    // Getrennt: Spaltenbreite (--pin-w) = Anordnung seitlich, Zeilenhöhe (--pin-h) = Anordnung
    // vertikal, Kegel-Durchmesser (--pin-d) = die runden Pins selbst. Die PINS werden NIE
    // gestaucht (immer Kreis mit Durchmesser d); reicht die Höhe nicht, rückt nur die
    // ANORDNUNG zusammen (kleineres --pin-h -> Zeilen näher), der Pin bleibt rund.
    // BREITE zuerst: die Spalten füllen den Platz seitlich aus (Deckel 80px), min 16px.
    const pinW = Math.max(16, Math.min(80, Math.floor(byW)));
    // Pin-Durchmesser d: durch die Breite begrenzt (d <= pinW) und durch die Höhe. In der
    // Raute liegen die engsten gleichspaltigen Nachbarn 2 Zeilen auseinander -> kein Überlapp
    // solange 2*pinH >= d, also pinH >= d/2. Bei minimalem pinH=d/2 ist die sichtbare
    // Rautenhöhe 4*(d/2)+4*rowGap+d = 3d+4*rowGap -> d <= (availH-4*rowGap)/3.
    const dByH = (availH - 4 * rowGap) / 3;
    const pinD = Math.max(16, Math.min(80, Math.floor(Math.min(pinW, dByH))));
    // Zeilenhöhe füllt die restliche Höhe, aber >= d/2 (kein Überlapp) und <= pinW (die
    // Anordnung wird nur gestaucht, nie vertikal gestreckt).
    const pinH = Math.max(Math.ceil(pinD / 2), Math.min(pinW, Math.floor((availH - 4 * rowGap - pinD) / 4)));
    if (Number.isFinite(pinW)) grid.style.setProperty('--pin-w', pinW + 'px');
    if (Number.isFinite(pinH)) grid.style.setProperty('--pin-h', pinH + 'px');
    if (Number.isFinite(pinD)) grid.style.setProperty('--pin-d', pinD + 'px');
    // Sichtbare Rautenhöhe: die runden Pins ragen über die (gestauchten) Zeilentracks hinaus,
    // von der Mitte des obersten bis zur Mitte des untersten Pins + ein Durchmesser.
    // Passt sie in availH -> voller Lift (obere Ecken-Zahlen tief in der Raute); überschießt
    // sie, Lift zurücknehmen, damit der Wurf Kegel 1 nicht überlappt.
    const diamondH = 4 * pinH + 4 * rowGap + pinD;
    const overshoot = Math.max(0, diamondH - availH);
    const lift = Math.max(0, Math.min(LIFT_MAX, LIFT_MAX - overshoot));
    kegel.style.setProperty('--foot-mt', (-lift) + 'px');
  }

  // Die Wurf-Chips scrollen horizontal, das Teilsatz-Ergebnis bleibt rechts fest daneben.
  // Ohne Nachführung landet ein neu erfasster Wurf außerhalb des sichtbaren Bereichs.
  // Wichtig: Die Zeile enthält NACH den erfassten Würfen noch leere Platzhalter-Chips für
  // die restlichen Würfe. Einfach „ganz nach rechts" zu scrollen zeigt daher diese leeren
  // Slots und schiebt den gerade eingetippten Wurf aus dem Bild (fällt nur am schmalen
  // Handy-Display auf). Stattdessen genau den aktiven Chip in die sichtbare Leiste holen —
  // und dabei ausschließlich die Leiste selbst horizontal scrollen, nie die Seite bewegen.
  function keepThrowVisible() {
    const blk = current();
    const cursor = editIdx !== null ? editIdx : blk.wuerfe.length - 1;
    if (cursor < 0) return;
    const r = rangeOfThrow(ranges, cursor);
    if (!r) return;
    const row = root.querySelector(`.erf-chip-row[data-ts="${ranges.indexOf(r)}"]`);
    if (!row) return;
    const chip = row.querySelector(`[data-chip="${cursor}"]`);
    if (!chip) return;
    const rowRect = row.getBoundingClientRect();
    const chipRect = chip.getBoundingClientRect();
    const pad = 8;
    // Abstand des Chips vom linken/rechten sichtbaren Rand der Leiste -> nur bei Bedarf scrollen.
    if (chipRect.left < rowRect.left + pad) {
      row.scrollLeft += (chipRect.left - rowRect.left) - pad;
    } else if (chipRect.right > rowRect.right - pad) {
      row.scrollLeft += (chipRect.right - rowRect.right) + pad;
    }
  }

  function template() {
    const blk = current();
    const status = satzStatus(blk);
    const bs = computeBahnState();

    return `
      <header class="page-header">
        <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
        <h1 class="page-title brand">Pin-Scorer</h1>
        ${allGamesDone() ? `<button type="button" class="icon-btn settings-btn" data-act="show-stats" aria-label="Statistik anzeigen">🏁</button>` : ''}
        <button type="button" class="icon-btn${allGamesDone() ? '' : ' settings-btn'}" data-act="settings" aria-label="Einstellungen">⚙</button>
      </header>

      ${bahnTabs(bs)}

      ${satzTabs()}

      ${satzOverviewOpen ? `
      <div class="erf-satz erf-satz-ueber">
        ${spielerUebersichtPanel()}
        ${ueberTab === 'uebersicht' ? overviewNumpad() : ''}
      </div>` : `
      <div class="erf-satz">
        ${linked && !canEdit(state.aktiverSpieler) ? lockBanner() : ''}
        ${kegelBoard(blk)}

        ${wurfChips(blk, status === 'done')}
        ${numpad(blk, status)}
      </div>`}

      <div id="erf-toast" class="erf-toast"></div>
      ${settingsOpen ? settingsPanel() : ''}
      ${laneSettingsOpen ? laneSettingsPanel() : ''}
      ${pinPick ? pinPickPanel() : ''}
      ${statsOpen ? statsPanel() : ''}`;
  }

  // Statistik-Vollbild nach Spielende: Platzierung (bei mehreren Spielern) + je Spieler eine
  // Karte mit Gesamt, Kennzahlen und Satz-für-Satz-Aufschlüsselung. Reine Auswertung kommt aus
  // logic/statistik.js. Über „Weiter bearbeiten" schließt sich das Overlay (Sätze lassen sich
  // aus der Bahneinstellung wieder öffnen), „Neues Spiel" führt zurück in die Spielauswahl.
  function statsPanel() {
    const { players, ranking } = computeGameStats(c, state.bloecke, ranges);
    const multi = players.length > 1;
    const hasKranz = ranges.some((r) => r.modus === 'kranz-abraeumen');
    const hasAbraeum = ranges.some((r) => r.modus === 'abraeumen' || r.modus === 'kranz-abraeumen');
    const medal = (r) => (r === 1 ? '🥇' : r === 2 ? '🥈' : r === 3 ? '🥉' : `${r}.`);

    const rankingBox = multi ? `
      <div class="stats-ranking">
        ${ranking.map((p) => `
          <div class="stats-rank-row${p.rang === 1 ? ' is-winner' : ''}">
            <span class="stats-rank-pos">${medal(p.rang)}</span>
            <span class="stats-rank-name">${esc(p.name)}</span>
            <span class="stats-rank-total">${p.gesamt}</span>
          </div>`).join('')}
      </div>` : '';

    const metric = (val, lbl) => `<div class="stats-metric"><span class="stats-metric-val">${val}</span><span class="stats-metric-lbl">${lbl}</span></div>`;
    // Gefallene Kegel je Einzelwurf (sofern einzeln erfasst), nach Teilsatz gruppiert; 9 = Alle Neune,
    // 0 = Fehlwurf werden hervorgehoben. Teilsätze, die nur als Summe eingetragen wurden, bleiben leer.
    const MODUS_LBL = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz' };
    const wuerfeRow = (s) => {
      const groups = s.teilsaetze.filter((t) => t.wuerfe.length);
      if (!groups.length) return '';
      const multi = groups.length > 1;
      const html = groups.map((t) => {
        const chips = t.wuerfe.map((w) => `<span class="stats-wurf${w === 9 ? ' is-neuner' : w === 0 ? ' is-fehl' : ''}">${w}</span>`).join('');
        const lbl = multi ? `<span class="stats-wurf-lbl">${MODUS_LBL[t.modus] || t.modus}</span>` : '';
        return `<span class="stats-wurf-group">${lbl}${chips}</span>`;
      }).join('');
      return `<div class="stats-wuerfe">${html}</div>`;
    };
    const cards = players.map((p) => {
      const satzRows = p.saetze.map((s) => `
        <div class="stats-satz">
          <div class="stats-satz-row"><span>Satz ${s.satz} · Bahn ${s.bahn}</span><strong>${s.holz}</strong></div>
          ${wuerfeRow(s)}
        </div>`).join('');
      return `
        <div class="stats-card">
          <div class="stats-card-head">
            <span class="stats-card-name">${multi ? `${medal(p.rang)} ` : ''}${esc(p.name)}</span>
            <span class="stats-card-total">${p.gesamt}</span>
          </div>
          <div class="stats-metrics">
            ${metric(p.schnittSatz.toFixed(1), 'Ø / Satz')}
            ${metric(p.bester, 'bester Satz')}
            ${metric(p.schnittWurf.toFixed(1), 'Ø / Wurf')}
            ${metric(p.neuner, 'Alle Neune ☆')}
            ${p.vollChance ? metric(Math.round(p.neunerQuote * 100) + ' %', '9er-Quote (volles Bild)') : ''}
            ${hasKranz ? metric(p.kranz, 'Kränze ♔') : ''}
            ${hasAbraeum && p.raeumer ? metric(p.raeumSchnitt.toFixed(1), 'Ø Würfe/Räumer') : ''}
            ${metric(p.fehl, 'Fehlwürfe')}
            ${metric(p.wurfCount, 'Würfe')}
          </div>
          <div class="stats-saetze">${satzRows}</div>
        </div>`;
    }).join('');

    return `
      <div class="erf-stats-screen" role="dialog" aria-modal="true" aria-label="Spiel-Statistik">
        <header class="page-header">
          <button type="button" class="back-btn" data-act="stats-close" aria-label="Zurück zur Erfassung">←</button>
          <h1 class="page-title">🏁 Spiel beendet</h1>
        </header>
        <div class="stats-body">
          <p class="stats-sub">Sportkegeln-Training${multi ? ` · ${players.length} Spieler` : ''}</p>
          ${rankingBox}
          ${cards}
          <div class="stats-actions">
            <button type="button" class="erf-btn" data-act="stats-close">↩ Weiter bearbeiten</button>
            <a class="erf-btn done" href="#/neues-spiel">Neues Spiel</a>
          </div>
        </div>
      </div>`;
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
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">Vorschläge</span>
                <span class="erf-setting-hint">Schnellauswahl der Standard-Kegelbilder nach dem Tippen einer Zahl</span>
              </div>
              <button type="button" class="erf-switch${settings.vorschlaege ? ' is-on' : ''}" role="switch" aria-checked="${settings.vorschlaege}" data-act="toggle-vorschlaege" aria-label="Vorschläge">
                <span class="erf-switch-knob"></span>
              </button>
            </div>
            <h3 class="erf-settings-sub">Mehrgeräte</h3>
            ${linked ? `
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">Beitritts-Code</span>
                <span class="erf-setting-hint">Anderes Gerät: im Menü „Spiel beitreten" wählen und diesen Code eingeben.</span>
              </div>
              <span class="erf-share-code">${esc(game.beitrittsCode || '—')}</span>
            </div>` : `
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">Spiel teilen</span>
                <span class="erf-setting-hint">Auf mehreren Geräten gleichzeitig erfassen — Konto nicht nötig.</span>
              </div>
              <button type="button" class="erf-btn done" data-act="share">🔗 Teilen</button>
            </div>`}
            <h3 class="erf-settings-sub">Standard-Kegelbilder</h3>
            ${standardbilderEditor()}
            <h3 class="erf-settings-sub" style="margin-top:20px;">Spiel-Details</h3>
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
              ${linked && canEdit(sp) ? `<button type="button" class="erf-btn" data-act="release">🔓 Bahn freigeben (anderes Gerät)</button>` : ''}
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
    return renderBahnTabs(bs);
  }

  // Banner über der Erfassung, wenn der aktive Spieler nicht diesem Gerät gehört.
  // „Übernehmen" nur, wenn die Bahn frei oder das andere Gerät inaktiv ist.
  function lockBanner() {
    const sp = state.aktiverSpieler;
    const o = ownerOf(sp);
    const belegt = !!(o && o.besitzer);
    const claimable = !belegt || !fremdAktiv(sp);
    const txt = belegt
      ? (fremdAktiv(sp) ? '🔒 Wird auf einem anderen Gerät erfasst' : '🔒 Anderes Gerät (inaktiv)')
      : 'Diese Bahn ist frei';
    return `<div class="erf-lock-banner">
      <span class="elb-text">${txt}</span>
      ${claimable ? `<button type="button" class="erf-btn done" data-act="claim">🔓 Übernehmen</button>` : ''}
    </div>`;
  }

  function renderBahnTabs(bs) {
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
          <span class="ept-top"><span class="ept-bahn">B${bahn}</span></span>
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
      const realN = blk.wuerfe.length;          // echte Würfe (für den zuletzt erfassten Wurf)
      const wurfN = wuerfeCount(blk);           // Anzeige: manuell gesetzte Teilsätze zählen als voll
      // FUNK-Stil-Kopf, 2-zeilig: Zeile 1 = B{Bahn} · Name · Gesamtergebnis (gold);
      // Zeile 2 = Wurf-Nr · aktueller Wurf · Gesamt Bahn.
      const lastThrow = realN ? blk.wuerfe[realN - 1] : '–';
      tabs.push(`<button type="button" role="tab" aria-selected="${sp === state.aktiverSpieler}" class="erf-ptab is-${status}${sp === state.aktiverSpieler ? ' is-active' : ''}" data-player="${sp}">
        <span class="ept-top">
          <span class="ept-bahn">B${bahn}</span>
          ${s.waiting ? `<span class="ept-warten" title="wartet auf Bahnwechsel">⏳</span>` : ''}
          ${fremdAktiv(sp) ? `<span class="ept-lock" title="wird auf anderem Gerät erfasst">🔒</span>` : ''}
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
    const tabs = state.bloecke[sp].map((blk, st) => {
      const s = satzStatus(blk);
      const h = satzHolz(blk, ranges);
      return `<button type="button" role="tab" aria-selected="${st === state.aktiverSatz}" class="erf-stab is-${s}${st === state.aktiverSatz ? ' is-active' : ''}" data-satz="${st}">
        <span class="est-label">Satz ${st + 1}</span>
        <span class="est-val">${s === 'pending' ? '–' : h}</span>
      </button>`;
    }).join('');
    // Übersicht-Button in der Satz-Zeile: schaltet zwischen Wurferfassung und Spieler-Übersicht
    // um (Tab-Leisten bleiben oben stehen). Aktiv gefärbt, solange die Übersicht offen ist.
    const overviewBtn = `<button type="button" class="erf-stab erf-stab-more${satzOverviewOpen ? ' is-active' : ''}" data-act="satz-overview" aria-pressed="${satzOverviewOpen}" aria-label="Spieler-Übersicht" title="Übersicht">▦</button>`;
    return `<div class="erf-stabs" role="tablist">${overviewBtn}${tabs}</div>`;
  }

  // Spieler-Übersicht (inline, ersetzt die Wurferfassung; die Bahn- und Satz-Leiste bleiben oben
  // stehen): alle spielerspezifischen Daten des AKTIVEN Spielers auf einen Blick —
  //   • Statistik-Kacheln (Gesamt, Ø/Satz, bester Satz, Ø/Wurf, Alle Neune, Fehlwürfe, Würfe)
  //   • alle Sätze NACH BAHN sortiert, je Satz die Teilsatz-Ergebnisse + deren Summe (Holz)
  //   • Fußzeile mit den Spalten-Summen (Teilsätze) und dem Gesamt-Holz
  // Ein Tipp auf eine Zeile wählt den Satz (die Satz-Leiste oben spiegelt das); der ▦-Button
  // schaltet zurück zur Erfassung.
  function spielerUebersichtPanel() {
    const sp = state.aktiverSpieler;
    const arr = state.bloecke[sp];
    const stats = computeGameStats(c, state.bloecke, ranges).players[sp];

    const tsLabels = teilsatzLabels();
    // Nur bei mehr als einem Teilsatz eigene Spalten zeigen — sonst wäre der Teilsatz = Satz-Holz.
    const showTs = ranges.length > 1;

    // Sätze nach Bahn sortieren (bei gleicher Bahn nach Satz-Nummer).
    const infos = arr.map((blk, st) => ({ st, blk, bahn: laneOf(sp, st), status: satzStatus(blk) }));
    const sorted = infos.slice().sort((a, b) => a.bahn - b.bahn || a.st - b.st);

    const tsHead = showTs
      ? tsLabels.map((l, i) => `<th class="ub-h-ts" title="${esc(MODUS_LABEL[ranges[i].modus] || '')}">${esc(l)}</th>`).join('')
      : '';

    const rows = sorted.map(({ st, blk, bahn, status }) => {
      const empty = status === 'pending';
      const active = st === state.aktiverSatz;
      const tsCells = showTs
        ? ranges.map((_, i) => {
          const t = teilsatzStats(blk, ranges, i, status === 'done');
          const touched = t.count > 0 || t.manual;
          // Wird diese Teilsatz-Zelle gerade per Ziffernblock bearbeitet? -> Entwurf live zeigen.
          const editing = overrideSt === st && overrideTs === i;
          const cell = editing ? (overrideDraft || '–') : (touched ? t.val : '·');
          return `<td class="ub-ts ub-edit${t.manual ? ' is-manual' : ''}${t.mark ? ' is-mark' : ''}${editing ? ' is-editing' : ''}" data-edit-ts="${st}:${i}" role="button" tabindex="0" aria-label="${esc(tsLabels[i])}, Satz ${st + 1} bearbeiten">${cell}${!editing && t.mark ? ' ⚠' : ''}</td>`;
        }).join('')
        : '';
      // Satz-Holz-Zelle: bearbeitet wird das ganze Satz-Ergebnis (overrideTs === null).
      const editingSatz = overrideSt === st && overrideTs === null;
      const holzCell = editingSatz ? (overrideDraft || '–') : (empty ? '–' : satzHolz(blk, ranges));
      return `<tr class="ub-row is-${status}${active ? ' is-active' : ''}" data-satz="${st}">
        <td class="ub-bahn">B${bahn}</td>
        <td class="ub-satz">Satz ${st + 1}</td>
        ${tsCells}
        <td class="ub-holz ub-edit${editingSatz ? ' is-editing' : ''}" data-edit-satz="${st}" role="button" tabindex="0" aria-label="Satz ${st + 1} Ergebnis bearbeiten">${holzCell}</td>
      </tr>`;
    }).join('');

    // Fußzeile: Summe je Teilsatz-Spalte über alle Sätze + Gesamt-Holz.
    const tsFoot = showTs
      ? ranges.map((_, i) =>
        `<td class="ub-ts">${arr.reduce((s, blk) => s + teilsatzStats(blk, ranges, i, satzStatus(blk) === 'done').val, 0)}</td>`).join('')
      : '';

    const metric = (val, lbl) => `<div class="stats-metric"><span class="stats-metric-val">${val}</span><span class="stats-metric-lbl">${lbl}</span></div>`;

    // Inhalt „Übersicht": die editierbare Bahnen-Tabelle (Teilsatz-/Satz-Ergebnisse antippbar).
    const uebersichtTab = `
      <p class="ueber-edithint">Tippe ein ${showTs ? 'Teilsatz- oder Satz-Ergebnis' : 'Satz-Ergebnis'} an und ändere es unten mit dem Ziffernblock.</p>
      <div class="ueber-tablewrap">
        <table class="ub-table">
          <thead>
            <tr>
              <th class="ub-h-bahn">Bahn</th>
              <th class="ub-h-satz">Satz</th>
              ${tsHead}
              <th class="ub-h-holz">Holz</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
          <tfoot>
            <tr>
              <td class="ub-bahn ub-foot-label">Σ</td>
              <td class="ub-satz"></td>
              ${tsFoot}
              <td class="ub-holz ub-grand">${playerTotal(sp)}</td>
            </tr>
          </tfoot>
        </table>
      </div>`;

    // Inhalt „Statistik": die Kennzahl-Kacheln. Kränze nur, wenn Kranz-Abräumen gespielt wird.
    const hasKranz = ranges.some((r) => r.modus === 'kranz-abraeumen');
    const hasAbraeum = ranges.some((r) => r.modus === 'abraeumen' || r.modus === 'kranz-abraeumen');
    const statistikTab = `
      <div class="stats-metrics">
        ${metric(stats.schnittSatz.toFixed(1), 'Ø / Satz')}
        ${metric(stats.bester, 'bester Satz')}
        ${metric(stats.schnittWurf.toFixed(1), 'Ø / Wurf')}
        ${metric(stats.neuner, 'Alle Neune ☆')}
        ${stats.vollChance ? metric(Math.round(stats.neunerQuote * 100) + ' %', '9er-Quote (volles Bild)') : ''}
        ${hasKranz ? metric(stats.kranz, 'Kränze ♔') : ''}
        ${hasAbraeum && stats.raeumer ? metric(stats.raeumSchnitt.toFixed(1), 'Ø Würfe/Räumer') : ''}
        ${metric(stats.fehl, 'Fehlwürfe')}
        ${metric(stats.wurfCount, 'Würfe')}
      </div>`;

    // Tab-Leiste + aktiver Inhalt.
    const tab = (id, label) =>
      `<button type="button" role="tab" aria-selected="${ueberTab === id}" class="ueber-tab${ueberTab === id ? ' is-active' : ''}" data-uebertab="${id}">${label}</button>`;
    const body =
      ueberTab === 'statistik' ? statistikTab :
      ueberTab === 'verteilung' ? wurfVerteilungTab(arr) :
      uebersichtTab;

    return `
      <div class="erf-ueber">
        <div class="ueber-scroll">
          <div class="ueber-head">
            <span class="ueber-name">${esc(playerName(sp))}</span>
            <span class="ueber-total">${stats.gesamt}</span>
          </div>
          <div class="ueber-tabs" role="tablist">
            ${tab('uebersicht', 'Übersicht')}
            ${tab('statistik', 'Statistik')}
            ${tab('verteilung', 'Wurf-Bild')}
          </div>
          ${body}
        </div>
      </div>`;
  }

  // Inhalt „Wurf-Bild": wie häufig welches Ergebnis (0–9 Holz) geworfen wurde. Zählt nur die
  // einzeln ERFASSTEN Würfe des aktiven Spielers (rein als Summe eingetragene Ergebnisse liefern
  // keine Einzelwürfe). Balken proportional zum häufigsten Wert; 9 (Alle Neune) und 0 (Fehl)
  // sind farblich hervorgehoben.
  function wurfVerteilungTab(arr) {
    const alle = arr.flatMap((b) => (Array.isArray(b.wuerfe) ? b.wuerfe : []));
    const dist = Array.from({ length: 10 }, () => 0);
    alle.forEach((w) => { if (w >= 0 && w <= 9) dist[w] += 1; });
    const total = alle.length;
    if (total === 0) {
      return `<p class="ueber-dist-empty">Noch keine Einzelwürfe erfasst.<br><span>Nur als Summe eingetragene Ergebnisse zählen hier nicht mit.</span></p>`;
    }
    const maxCount = Math.max(1, ...dist);
    const rows = [];
    for (let v = 9; v >= 0; v -= 1) {
      const count = dist[v];
      const pct = Math.round((count / total) * 100);
      const barW = (count / maxCount) * 100;
      const cls = v === 9 ? ' is-neuner' : v === 0 ? ' is-fehl' : '';
      const note = v === 9 ? '<span class="ud-note">☆</span>' : v === 0 ? '<span class="ud-note">Fehl</span>' : '';
      rows.push(`
        <div class="ud-row${cls}">
          <span class="ud-val">${v}${note}</span>
          <span class="ud-bar"><span class="ud-fill" style="width:${barW}%"></span></span>
          <span class="ud-count">${count}<span class="ud-pct">${pct}%</span></span>
        </div>`);
    }
    return `
      <p class="ueber-edithint">${total} Würfe erfasst · wie häufig welches Holz-Ergebnis fiel.</p>
      <div class="ueber-dist">${rows.join('')}</div>`;
  }

  // Kegel-Raute: welche Kegel im Ziel-Wurf gefallen/stehen (anklickbar).
  // Ziffernblock gibt N (Holz) vor -> Auswahl muss dazu passen.
  // Umschalter oben rechts: nur die Kegel-Silhouette (transparent, umfärbbar) — stehend = aufrecht,
  // gefallen = 90° nach rechts gedreht (liegend). Farbe je Zustand per CSS (gold/dunkel/weiß).
  function pinSvg(extra) {
    return `<svg class="ek-pin-svg${extra ? ' ' + extra : ''}" viewBox="0 0 100 120" aria-hidden="true">
      <circle cx="50" cy="26" r="17"/>
      <path d="M50 40 C40 40 36 48 35 58 C31 78 26 92 30 102 C34 114 44 118 50 118 C56 118 66 114 70 102 C74 92 69 78 65 58 C64 48 60 40 50 40 Z"/>
    </svg>`;
  }
  function pinModeToggle() {
    return `
      <div class="ek-modes" role="group" aria-label="Kegel erfassen als">
        <button type="button" aria-pressed="${pinMode === 'stehend'}" class="ek-mode${pinMode === 'stehend' ? ' is-active' : ''}" data-pinmode="stehend" aria-label="Stehende">${pinSvg()}</button>
        <button type="button" aria-pressed="${pinMode === 'gefallen'}" class="ek-mode${pinMode === 'gefallen' ? ' is-active' : ''}" data-pinmode="gefallen" aria-label="Gefallene">${pinSvg('is-fallen')}</button>
      </div>`;
  }

  // Kleine Kegel-Raute (Vorschau/Editor). `fallen` = Set/Array gefallener Kegel (leuchten gold).
  // editable -> die Kegel sind Buttons (data-sbpin) zum An-/Abwählen im Einstellungs-Editor.
  // `gone` = Kegel, die VOR diesem Wurf schon gefallen sind (Abräum-Vorschau): ausgegraut
  // wie im großen Kegelbrett, damit man sieht, worauf noch gespielt wird.
  function miniRaute(fallen, editable = false, gone = []) {
    const F = new Set(fallen);
    const G = new Set(gone);
    const cells = KEGEL_LAYOUT.map((p) => {
      const on = F.has(p.n);
      const isGone = !on && G.has(p.n);
      const tag = editable ? 'button' : 'span';
      const attr = editable ? ` type="button" data-sbpin="${p.n}"` : '';
      const cls = `mini-pin${on ? ' is-on' : ''}${isGone ? ' is-gone' : ''}`;
      return `<${tag} class="${cls}"${attr} style="grid-column:${p.c};grid-row:${p.r};">${p.n}</${tag}>`;
    }).join('');
    return `<div class="mini-raute${editable ? ' is-editable' : ''}">${cells}</div>`;
  }

  // Einstellungs-Editor für die Standard-Kegelbilder (global, spielübergreifend).
  // Positions-Raster im Numpad-Look: du bestimmst je Zahl, auf welchem Feld welches Bild sitzt.
  // 'Manuell' liegt fest auf der 0, die beiden unteren Ecken bleiben leer.
  function standardbilderEditor() {
    const nums = [1, 2, 3, 4, 5, 6, 7, 8]
      .map((n) => `<button type="button" class="sb-num${n === sbEditN ? ' is-active' : ''}" data-sbnum="${n}">${n}${Array.isArray(standardbilder[n]) && standardbilder[n].length ? `<span class="sb-num-badge">${standardbilder[n].length}</span>` : ''}</button>`)
      .join('');
    const list = Array.isArray(standardbilder[sbEditN]) ? standardbilder[sbEditN] : [];
    const bySlot = {};
    list.forEach((it) => { bySlot[it.slot] = it; });
    const ready = sbDraft.length === sbEditN;
    const cells = PICK_CELLS.map((cell) => {
      if (cell === 'manual') return `<div class="sb-cell sb-manual">Manuell</div>`;
      if (cell === 'undo' || cell === 'settings') return `<div class="sb-cell sb-void"></div>`;
      const it = bySlot[cell];
      if (it) return `<div class="sb-cell sb-filled">${miniRaute(it.pins)}<button type="button" class="sb-del" data-sbdel="${sbEditN}:${cell}" aria-label="Bild auf Feld ${cell} löschen">🗑</button></div>`;
      return `<button type="button" class="sb-cell sb-slot${ready ? ' is-ready' : ''}" data-sbplace="${cell}" aria-label="Bild auf Feld ${cell} legen"><span class="sb-slot-digit">${cell}</span></button>`;
    }).join('');
    return `
      <div class="sb-editor">
        <p class="erf-settings-sub" style="margin-bottom:6px;">Für wie viele gefallene Kegel?</p>
        <div class="sb-nums">${nums}</div>
        <p class="sb-hint">Bild bauen: die <strong>${sbEditN}</strong> gefallenen Kegel antippen (${sbDraft.length}/${sbEditN}), dann unten auf ein <strong>freies Feld</strong> tippen — dort erscheint es später im Pop-up.</p>
        <div class="sb-build">${miniRaute(sbDraft, true)}</div>
        <div class="sb-posgrid">${cells}</div>
      </div>`;
  }

  // Schnellauswahl-Pop-up: nach dem Tippen einer Zahl die hinterlegten Standard-Bilder zeigen.
  // Liegt GENAU über dem Ziffernblock (Position/Größe setzt positionPinPick() nach dem Render);
  // die Felder haben dasselbe 3-Spalten-Raster und dieselbe Zellengröße wie die Zahlentasten.
  // Ein Tipp setzt die Raute automatisch; „Manuell" schließt und lässt die Wahl offen (wie bisher).
  function pinPickPanel() {
    // Schon vorher gefallene Kegel (Abräumen): alles außerhalb der noch stehenden Restmenge —
    // in den Vorschau-Rauten ausgegraut wie im großen Kegelbrett.
    const ctx = throwContext(current(), pinPick.idx);
    const gone = (ctx.abraeum && ctx.exact) ? fullPins().filter((p) => !ctx.universe.includes(p)) : [];
    const bySlot = {};
    pinPick.combos.forEach((c, i) => { bySlot[c.slot] = { c, i }; });
    const cells = PICK_CELLS.map((cell) => {
      if (cell === 'manual') return `<button type="button" class="pk-cell pk-manual" data-act="pick-close" aria-label="Manuell wählen">Manuell</button>`;
      if (cell === 'undo' || cell === 'settings') return `<span class="pk-cell pk-void" aria-hidden="true"></span>`;
      const hit = bySlot[cell];
      if (hit) return `<button type="button" class="pk-cell" data-pick="${hit.i}" aria-label="Bild ${hit.c.pins.join(', ')}">${miniRaute(hit.c.pins, false, gone)}</button>`;
      return `<span class="pk-cell pk-void" aria-hidden="true"></span>`;
    }).join('');
    return `
      <div class="pk-overlay" data-act="pick-close">
        <div class="pk-pop" role="dialog" aria-modal="true" aria-label="${pinPick.n} Kegel — Bild wählen">
          <div class="pk-grid">${cells}</div>
        </div>
      </div>`;
  }

  // Das Pop-up exakt über den Ziffernblock legen und die Zellen auf Tastengröße bringen.
  function positionPinPick() {
    if (!pinPick) return;
    const pop = root.querySelector('.pk-pop');
    const pad = root.querySelector('.erf-numpad');
    if (!pop || !pad) return;
    const r = pad.getBoundingClientRect();
    if (r.height === 0) { requestAnimationFrame(positionPinPick); return; }
    const key = pad.querySelector('.erf-num');
    const kh = key ? key.getBoundingClientRect().height : 52;
    const grid = pop.querySelector('.pk-grid');
    pop.style.left = r.left + 'px';
    pop.style.top = r.top + 'px';
    pop.style.width = r.width + 'px';
    grid.style.gap = getComputedStyle(pad).rowGap || '6px';
    grid.style.setProperty('--pk-cell-h', kh + 'px');
    // Kegelgröße der Mini-Raute so, dass sie in eine Tastenzelle passt (Höhe minus kleine Gaps/Padding).
    grid.style.setProperty('--pk-mp', Math.max(6, Math.floor((kh - 12) / 5)) + 'px');
  }

  function kegelBoard(blk) {
    const sp = state.aktiverSpieler;
    const name = playerName(sp);
    const lane = laneOf(sp, state.aktiverSatz);              // Bahnnummer (oben links)
    const wurfN = wuerfeCount(blk);                          // manuell gesetzte Teilsätze zählen als voll
    const fehl = blk.wuerfe.filter((w) => w === 0).length;   // Fehlwürfe = kein Kegel getroffen (Wurf 0)
    const ergBahn = satzHolz(blk, ranges);                    // Ergebnis auf dieser Bahn (aktueller Satz)
    const ergGesamt = playerTotal(sp);                       // Ergebnis über alle Sätze
    const target = pinTarget();
    const has = target >= 0;

    let pins, curVal, curColor;
    if (!has) {
      pins = KEGEL_LAYOUT.map((p) =>
        `<span class="erf-kegel-pin is-off" style="grid-column:${p.c};grid-row:${p.r};">${p.n}</span>`).join('');
      curVal = '–'; curColor = 'is-gold';
    } else {
      const n = blk.wuerfe[target];
      const ctx = throwContext(blk, target);
      const U = ctx.universe;              // wählbare Kegel (Abräumen: nur stehende)
      const inU = (pin) => !ctx.abraeum || !ctx.exact || U.includes(pin);
      const unset = blk.kegel[target] == null;
      // König-Wurf (Langdruck): N Kranz-Kegel gefallen, König (5) steht — genaue Kegel offen.
      const koenigThrow = ctx.kranz && Array.isArray(blk.koenig) && blk.koenig[target] && unset;
      // F = gefallene (leuchtende) Kegel. Unbestimmt: gefallen-Modus keiner an, stehend-Modus alle wählbaren an.
      // Beim Kranz-Langdruck sind die genauen Kegel offen, aber es fielen alle STEHENDEN außer dem
      // König (5) -> so darstellen: die 8 Kranzkegel leuchten, der König steht ganz normal.
      const fallen = koenigThrow
        ? U.filter((pin) => pin !== 5)
        : (unset ? (pinMode === 'stehend' ? U.slice() : []) : blk.kegel[target]);
      const fallenN = fallen.length;
      const locked = blk.done;
      const match = fallenN === n;

      pins = KEGEL_LAYOUT.map((p) => {
        const gone = !inU(p.n);                          // vor diesem Wurf schon gefallen -> weg
        const isFallen = !gone && fallen.includes(p.n);
        // Gefallener Kegel leuchtet (Lampe an), stehender ist aus; schon gefallener ist "weg".
        const cls = gone ? 'is-gone' : (isFallen ? 'is-lamp-on' : '');
        const aria = gone ? 'schon gefallen' : (isFallen ? 'gefallen' : 'steht');
        const dis = locked || gone;
        return `<button type="button" class="erf-kegel-pin ${cls}" style="grid-column:${p.c};grid-row:${p.r};"
          data-pin="${p.n}"${dis ? ' disabled' : ''} aria-label="Kegel ${p.n}, ${aria}">${p.n}</button>`;
      }).join('');

      // Aktueller Wurf (mittig unter der Raute): Gold solange keine Pins gewählt (unbestimmt),
      // sonst Grün wenn die gewählte Anzahl zur Holzzahl passt, sonst Rot.
      curVal = n;
      curColor = unset ? 'is-gold' : (match ? 'is-green' : 'is-red');
    }

    return `
      <div class="erf-kegel">
        <div class="erf-kegel-head">
          <span class="ek-bahn">Bahn ${lane}</span>
          <span class="ek-name">${esc(name)}</span>
          ${pinModeToggle()}
        </div>
        <div class="erf-kegel-body">
          <div class="erf-kegel-grid">${pins}</div>
        </div>
        <div class="erf-kegel-foot">
          <div class="ek-stat ek-stat-left">
            <span class="ek-stat-a">${fehl}</span>
            <span class="ek-stat-b">${wurfN}/${c.wuerfeProSatz}</span>
          </div>
          <div class="erf-kegel-cur"><span class="ek-cur ${curColor}${Date.now() - flashTs < 500 ? ' is-flash' : ''}">${curVal}</span></div>
          <div class="ek-stat ek-stat-right">
            <span class="ek-stat-a">${ergGesamt}</span>
            <span class="ek-stat-b">${ergBahn}</span>
          </div>
        </div>
      </div>`;
  }

  function wurfChips(blk, satzDone) {
    if (c.wuerfeProSatz === 0) return '';
    const rows = ranges.map((r, i) => {
      const label = MODUS_LABEL[r.modus] || r.modus;
      const abk = MODUS_ABK[r.modus] || label;
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
      // Teilsatz-Ergebnis direkt in der Wurfzeile (rechts) — nur Anzeige. Das Anpassen der
      // Teilsatz-/Satz-Ergebnisse läuft jetzt ausschließlich über die Spieler-Übersicht (▦).
      const result = `<span class="erf-chip-result${t.mark ? ' mismatch' : ''}${t.manual ? ' manual' : ''}" aria-label="${label}-Ergebnis">
        <span class="ecr-val">${t.val}${t.mark ? ' ⚠' : ''}${t.manual ? ' ✎' : ''}</span>
        <span class="ecr-count">${t.count}/${t.soll}</span>
      </span>`;
      // Fehlerhinweis unter der Wurfzeile (auf dem Handy ohne Tooltip sichtbar).
      let errNote = '';
      if (errors) {
        const bad = [];
        for (let k = r.start; k < r.end; k++) if (errors[k]) bad.push(`Wurf ${k + 1}: ${errors[k]}`);
        if (bad.length) errNote = `<div class="erf-chip-err">⚠ ${esc(bad.join(' · '))}</div>`;
      }
      return `<div class="erf-chip-group">
        <div class="erf-chip-line">
          <span class="ecg-label" title="${label}">${abk}</span>
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
    const locked = !canEdit(state.aktiverSpieler) || (editIdx === null && (status === 'done' || full));
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
      return `<button type="button" class="erf-num${canK ? ' can-koenig' : ''}" data-num="${n}"${canK ? ' data-koenig="1"' : ''}${dis ? ' disabled' : ''}>${n}</button>`;
    };
    // Bodenreihe (3 Zellen wie die Zahlen): links Aktion · 0 · rechts Aktion.
    // Normal: ↩ Zurück · 0 · ⚙ Bahneinstellung. Beim Korrigieren: 🗑 Löschen · 0 · ✕ Abbrechen.
    const editing = editIdx !== null;
    const leftAct = editing
      ? `<button type="button" class="erf-num erf-num-act danger" data-act="delete" aria-label="Wurf löschen">🗑</button>`
      : `<button type="button" class="erf-num erf-num-act" data-act="undo" aria-label="Letzten Wurf zurück">↩</button>`;
    const rightAct = editing
      ? `<button type="button" class="erf-num erf-num-act" data-act="cancel-edit" aria-label="Korrektur abbrechen">✕</button>`
      : `<button type="button" class="erf-num erf-num-act" data-act="lane-settings" aria-label="Bahneinstellung">⚙</button>`;
    return `<div class="erf-numpad">
      ${[7, 8, 9, 4, 5, 6, 1, 2, 3].map(btn).join('')}
      ${leftAct}
      ${btn(0)}
      ${rightAct}
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
        tapNumber(n);
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
    // Übersicht: Teilsatz-/Satz-Ergebnis antippen -> Bearbeiten-Sheet. stopPropagation, damit der
    // Tipp nicht zusätzlich die (auf der Zeile liegende) Satz-Auswahl auslöst.
    root.querySelectorAll('[data-edit-ts]').forEach((el) =>
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const [st, i] = el.dataset.editTs.split(':').map((x) => parseInt(x, 10));
        openOverride(st, i);
      }));
    root.querySelectorAll('[data-edit-satz]').forEach((el) =>
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        openSatzOverride(parseInt(el.dataset.editSatz, 10));
      }));

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
    act('toggle-vorschlaege', toggleVorschlaege);
    act('show-stats', () => { statsOpen = true; render(); });
    act('share', shareGame);
    act('claim', claimActive);
    act('release', releaseActive);
    // Statistik schließen (Kopf-← und „Weiter bearbeiten" tragen beide diesen Hook).
    root.querySelectorAll('[data-act="stats-close"]').forEach((b) =>
      b.addEventListener('click', () => { statsOpen = false; render(); }));

    // Spieler-Übersicht (inline): der ▦-Button schaltet zwischen Erfassung und Übersicht um.
    // Die Übersichts-Zeilen tragen data-satz und werden über die Satz-Tab-Verdrahtung
    // (selectSatz) mitgenommen — ein Tipp wählt den Satz, die Übersicht bleibt offen.
    act('satz-overview', () => {
      satzOverviewOpen = !satzOverviewOpen;
      // Beim Verlassen der Übersicht eine ggf. angefangene Zellen-Bearbeitung verwerfen.
      overrideSt = null; overrideTs = null; overrideDraft = '';
      render();
    });

    // Tabs innerhalb der Übersicht (Übersicht / Statistik / Wurf-Bild) umschalten. Ein
    // Tab-Wechsel verwirft eine angefangene Zellen-Bearbeitung (Ziffernblock gibt es nur im
    // Übersicht-Tab).
    root.querySelectorAll('[data-uebertab]').forEach((b) =>
      b.addEventListener('click', () => {
        if (ueberTab === b.dataset.uebertab) return;
        ueberTab = b.dataset.uebertab;
        overrideSt = null; overrideTs = null; overrideDraft = '';
        render();
      }));

    // Standard-Bilder-Editor (in den Einstellungen)
    root.querySelectorAll('[data-sbnum]').forEach((b) =>
      b.addEventListener('click', () => setSbEditN(parseInt(b.dataset.sbnum, 10))));
    root.querySelectorAll('[data-sbpin]').forEach((b) =>
      b.addEventListener('click', () => toggleSbPin(parseInt(b.dataset.sbpin, 10))));
    root.querySelectorAll('[data-sbplace]').forEach((b) =>
      b.addEventListener('click', () => placeSbImage(parseInt(b.dataset.sbplace, 10))));
    root.querySelectorAll('[data-sbdel]').forEach((b) =>
      b.addEventListener('click', () => {
        const [n, slot] = b.dataset.sbdel.split(':').map((x) => parseInt(x, 10));
        deleteSbImage(n, slot);
      }));

    // Schnellauswahl-Pop-up (Standard-Bild nach Zahleneingabe)
    root.querySelectorAll('[data-pick]').forEach((b) =>
      b.addEventListener('click', () => choosePinImage(parseInt(b.dataset.pick, 10))));
    root.querySelectorAll('[data-act="pick-close"]').forEach((b) =>
      b.addEventListener('click', (e) => {
        if (b.classList.contains('pk-overlay') && e.target !== b) return;
        pinPick = null; render();
      }));
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
  }

  // Teilsatz-Ergebnis manuell setzen: Sheet für Satz `st`, Teilsatz `i` (aus der Übersicht).
  function openOverride(st, i) {
    const blk = state.bloecke[state.aktiverSpieler][st];
    overrideSt = st; overrideTs = i;
    const cur = blk.overrides[i];
    overrideDraft = cur != null ? String(cur) : '';
    render();
  }

  // Ganzes Satz-Ergebnis für Satz `st` eingeben: beim Übernehmen wird der Wert auf den einzigen
  // offenen Teilsatz ergänzt (bzw. direkt gesetzt, wenn es nur einen Teilsatz gibt).
  function openSatzOverride(st) {
    const blk = state.bloecke[state.aktiverSpieler][st];
    overrideSt = st; overrideTs = null;
    // Ein-Teilsatz-Satz = direktes Ergebnis: aktuellen Wert vorbelegen (nur anpassen). Bei mehreren
    // Teilsätzen wird verteilt → leer starten, damit die Gesamtsumme bewusst getippt wird und nicht
    // versehentlich der vorbelegte Teil-Stand einen offenen Teilsatz auf 0 setzt.
    overrideDraft = (ranges.length === 1 && satzStatus(blk) !== 'pending') ? String(satzHolz(blk, ranges)) : '';
    render();
  }

  // Overlay-Sheet mit eigenem Ziffernblock. Zwei Modi: einzelnen Teilsatz setzen (overrideTs=i)
  // oder das ganze Satz-Ergebnis eingeben (overrideTs=null -> auf den offenen Teilsatz verteilen).
  // Ziffernblock unter der Spieler-Übersicht: bearbeitet die in der Tabelle angetippte Zelle
  // (overrideSt/overrideTs). Ohne gewählte Zelle sind die Ziffern gesperrt und ein Hinweis steht
  // oben. Alle Data-Hooks (data-ovnum / override-apply / override-reset) sind bereits in wire()
  // verdrahtet und teilen sich die Logik mit dem alten Overlay.
  function overviewNumpad() {
    const active = overrideSt !== null;

    // Kontextzeile über dem Block: was wird bearbeitet + zulässiger Bereich + Entfernen.
    let bar;
    if (!active) {
      bar = `<div class="ueber-editbar is-idle">Ergebnis in der Tabelle antippen, um es zu ändern.</div>`;
    } else {
      const st = overrideSt;
      const blk = state.bloecke[state.aktiverSpieler][st];
      const bahn = laneOf(state.aktiverSpieler, st);
      let ctxText, resetBtn = '';
      if (overrideTs !== null) {
        const r = ranges[overrideTs];
        const label = MODUS_LABEL[r.modus] || r.modus;
        const throwsIn = blk.wuerfe.slice(r.start, r.end);
        ctxText = `Satz ${st + 1} · Bahn ${bahn} · ${esc(label)} · 0–${r.soll * 9}`;
        // Entfernen NUR über diesen klaren Knopf. Bei erfassten Würfen ist es ein Zurückfallen auf
        // die Würfe-Summe, sonst ein echtes Entfernen des Ergebnisses.
        const resetLabel = throwsIn.length > 0 ? '↺ Auf Würfe' : '↺ Entfernen';
        resetBtn = `<button type="button" class="ueber-editreset" data-act="override-reset">${resetLabel}</button>`;
      } else {
        const labels = teilsatzLabels();
        const open = openTeilsaetze(blk);
        if (ranges.length > 1) {
          if (open.length === 1) ctxText = `Satz ${st + 1} · Bahn ${bahn} · ergänzt ${esc(labels[open[0]])}`;
          else if (open.length === 0) ctxText = `Satz ${st + 1} · alle Teilsätze gesetzt — einzeln bearbeiten`;
          else ctxText = `Satz ${st + 1} · ${open.length} Teilsätze offen — einzeln eingeben`;
        } else {
          ctxText = `Satz ${st + 1} · Bahn ${bahn} · 0–${ranges[0].soll * 9}`;
        }
      }
      bar = `<div class="ueber-editbar"><span class="ueber-editctx">${ctxText}</span>${resetBtn}</div>`;
    }

    const btn = (n) => `<button type="button" class="erf-num${n === 0 ? ' zero' : ''}" data-ovnum="${n}"${active ? '' : ' disabled'}>${n}</button>`;
    return `
      ${bar}
      <div class="erf-numpad erf-ueber-numpad">
        ${[7, 8, 9, 4, 5, 6, 1, 2, 3].map(btn).join('')}
        <button type="button" class="erf-num erf-num-act" data-ovnum="back" aria-label="Letzte Ziffer löschen"${active ? '' : ' disabled'}>⌫</button>
        ${btn(0)}
        <button type="button" class="erf-num erf-num-act" data-act="override-apply" aria-label="Ergebnis übernehmen"${active ? '' : ' disabled'}>✓</button>
      </div>`;
  }

  // Ziffer/⌫ im Override-Sheet verarbeiten (max. 4 Stellen; führende Null verwerfen).
  function overrideKey(key) {
    if (key === 'back') overrideDraft = overrideDraft.slice(0, -1);
    else if (overrideDraft.length < 4) overrideDraft = (overrideDraft + key).replace(/^0+(?=\d)/, '');
    render();
  }

  function applyOverride() {
    if (!guardEdit()) return;
    const st = overrideSt;
    const blk = state.bloecke[state.aktiverSpieler][st];
    const labels = teilsatzLabels();

    // Modus A: einzelner Teilsatz.
    if (overrideTs !== null) {
      const i = overrideTs;
      // Leeres Feld ist KEINE Eingabe -> nichts löschen (Entfernen läuft nur über den ↺-Knopf).
      if (overrideDraft === '') { toast('Bitte einen Wert eingeben (oder ↺ zum Entfernen)'); return; }
      const v = parseInt(overrideDraft, 10);
      if (Number.isNaN(v) || v < 0) { toast('Ungültiger Wert'); return; }
      const maxV = ranges[i].soll * 9; // physikalisches Maximum: Soll-Würfe × 9 Kegel
      if (v > maxV) { toast(`${labels[i]}: höchstens ${maxV} möglich (${ranges[i].soll}×9)`); return; }
      blk.overrides[i] = v;
      const closed = autoCloseIfComplete(blk);
      overrideSt = null; overrideTs = null; persist(); render();
      toast(`${labels[i]} auf ${v} Holz gesetzt${closed ? ` · Satz ${st + 1} abgeschlossen` : ''}`); return;
    }

    // Modus B: ganzes Satz-Ergebnis -> auf den EINEN offenen Teilsatz verteilen.
    if (overrideDraft === '') { toast('Bitte ein Ergebnis eingeben'); return; }
    const T = parseInt(overrideDraft, 10);
    if (Number.isNaN(T) || T < 0) { toast('Ungültiger Wert'); return; }

    if (ranges.length === 1) { // nur ein Teilsatz -> Satz = Teilsatz
      const maxV = ranges[0].soll * 9;
      if (T > maxV) { toast(`Höchstens ${maxV} möglich (${ranges[0].soll}×9)`); return; }
      blk.overrides[0] = T;
      const closed = autoCloseIfComplete(blk);
      overrideSt = null; overrideTs = null; persist(); render();
      toast(`Satz ${st + 1} auf ${T} Holz gesetzt${closed ? ' · abgeschlossen' : ''}`); return;
    }

    const open = openTeilsaetze(blk);
    if (open.length === 0) { toast('Alle Teilsätze gesetzt — bitte einzeln bearbeiten'); return; }
    if (open.length > 1) { toast(`${open.length} Teilsätze offen — bitte einzeln eingeben`); return; }
    const i = open[0];
    const known = knownTeilsatzSum(blk, i);
    const diff = T - known;
    // Nicht plausibel -> nichts eintragen, Sheet bleibt offen (keine Daten verändert).
    if (diff < 0) { toast(`Ergebnis kleiner als erfasste Teilsätze (${known})`); return; }
    const maxOpen = ranges[i].soll * 9;
    if (diff > maxOpen) { toast(`${labels[i]} fasst höchstens ${maxOpen} — Rest wäre ${diff}`); return; }
    blk.overrides[i] = diff;
    const closed = autoCloseIfComplete(blk);
    overrideSt = null; overrideTs = null; persist(); render();
    toast(`${labels[i]} auf ${diff} Holz ergänzt${closed ? ` · Satz ${st + 1} abgeschlossen` : ''}`);
  }

  // Entfernen betrifft IMMER nur den einen bearbeiteten Teilsatz (gibt es nur im Teilsatz-Modus).
  // Der Satz-Modus verteilt nur eine Summe und bietet daher bewusst kein Massen-Löschen an —
  // so kann eine unplausible/versehentliche Aktion nie mehrere manuelle Ergebnisse auf einmal killen.
  function resetOverride() {
    if (!guardEdit()) return;
    const st = overrideSt;
    const blk = state.bloecke[state.aktiverSpieler][st];
    if (overrideTs === null) { overrideSt = null; render(); return; }
    const i = overrideTs;
    const labels = teilsatzLabels();
    const hadThrows = blk.wuerfe.slice(ranges[i].start, ranges[i].end).length > 0;
    blk.overrides[i] = null;
    // War der Satz (auto-)abgeschlossen und ist durch das Entfernen wieder unvollständig,
    // öffnet er sich wieder — kein "fertiger" Satz mit offenem Teilsatz.
    const reopened = blk.done && openTeilsaetze(blk).length > 0;
    if (reopened) blk.done = false;
    overrideSt = null; overrideTs = null; persist(); render();
    toast(`${labels[i]}: ${hadThrows ? 'zurück auf erfasste Würfe' : 'Ergebnis entfernt'}${reopened ? ` · Satz ${st + 1} wieder offen` : ''}`);
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

  // Bei Größen-/Ausrichtungswechsel die Kegel-Raute neu einpassen. Listener entfernt sich
  // selbst, sobald die View aus dem DOM ist (nach Navigation zu einer anderen Seite).
  const onResize = () => {
    if (!root.isConnected) { window.removeEventListener('resize', onResize); return; }
    fitBoard();
    positionPinPick();
  };
  window.addEventListener('resize', onResize);

  render();
  initSync();
  return root;
}
