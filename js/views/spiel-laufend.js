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

import { getActiveGame, getGame, saveGame, saveErfassung, setGameStatus, getStandardbilder, saveStandardbilder, getSettings, saveSettings, getWettkampf, getWettkampfGames, saveWettkampf } from '../store.js';
import { esc, fehlerText } from '../util.js';
import { revealCodeHtml, wireRevealCodes } from '../reveal-code.js';
import { teilsatzRanges } from '../logic/teilsaetze.js';
import { computeGameStats } from '../logic/statistik.js';
import { buildProtokollHTML, printProtokollHTML } from '../logic/wurfprotokoll.js';
import { computeWettkampfStats, wettkampfBaseStatus } from '../logic/wettkampf.js';
import { computeWertung, assignEwp } from '../logic/wettkampf-wertung.js';
import { teamUebersichtSection } from './wettkampf-teams.js';
import { buildSportwinnerPush } from '../logic/sportwinner-ergebnis.js';
import { buildKonflikte } from '../logic/sportwinner-konflikte.js';
import {
  getBruecke, pushErgebnis, holeStatus, holeSportwinnerLive, brueckeStatusInfo, brueckePushText,
} from '../backend/sw-bruecke.js';
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
  // Zuschauer-Modus: das Spiel wurde per Zuschauer-Code geöffnet (sync.zuschauerGame). Alles wird
  // live angezeigt, aber KEINE Eingabe ist möglich — keine Würfe, kein Übernehmen, kein Teilen,
  // kein Beenden. Server-seitig ist das ohnehin nicht schreibbar (kein Geräte-Beitritt); hier
  // werden zusätzlich alle Eingabe-Bedienelemente ausgeblendet. Aktualisiert per Polling.
  const zuschauer = !!game.zuschauer;
  // Gehört das Spiel zu einem Wettkampf, führt „Zurück" in dessen Hub statt in die Spielauswahl.
  const backHref = game.wettkampfId ? '#/wettkampf' : '#/neues-spiel';
  const backLabel = game.wettkampfId ? 'Zum Wettkampf' : 'Neues Spiel';
  const ranges = teilsatzRanges(c);
  const state = normalizeErfassung(game.erfassung, c);
  // state ist eine NORMALISIERTE Kopie — game.erfassung sofort daran binden, damit beide nicht
  // auseinanderlaufen. Sonst schreibt initSync() frisch geladene (fremde/geräteübergreifende)
  // Würfe nur in state, während das Wurfprotokoll (buildProtokollHTML(game, …)) noch die alte,
  // leere game.erfassung druckt — auf einem anderen Gerät fehlen dann die Würfe im Protokoll.
  game.erfassung = state;
  let editIdx = null; // lokaler Korrektur-Index (nicht persistiert)
  let flashTs = 0; // Zeitstempel des zuletzt erfassten Wurfs: die aktuelle Wurfzahl blitzt danach kurz auf (Klick-Feedback, bei JEDEM Wert). Zeitfenster statt Render-Reset, damit ein Folge-Render (z. B. das Kegel-Popup) den Blitz nicht verschluckt.
  let pinMode = 'stehend'; // 'gefallen' | 'stehend' — welche Seite die Kegel-Raute erfasst (Default: Stehende)
  let lpSuppress = 0; // Zeitstempel: unterdrückt den Klick direkt nach einem Langdruck (König)
  let settingsOpen = false; // Einstellungsmenü (⚙) offen? — enthält u.a. die Spiel-Details
  let laneSettingsOpen = false; // Bahneinstellung (⚙ in der Satz-Kopfzeile) offen?
  let satzOverviewOpen = true; // Spieler-Übersicht (inline, statt Wurferfassung) offen? — beim Öffnen eines Spiels direkt die Übersicht zeigen (nicht die Wurferfassung des 1. Satzes)
  let ueberTab = 'uebersicht'; // aktiver Tab der Übersicht: 'uebersicht' (Bahnen editieren) | 'statistik' | 'verteilung' (Wurf-Häufigkeit)
  // Filter der Wurfübersicht (Wurf-Bild). Zwei Dimensionen, frei kombinierbar:
  //   wbSatzFilter — 'alle' oder ein Satz-Index als String ('0','1',…): nur diesen Satz zählen.
  //   wbTeilFilter — 'alle' oder ein Teilsatz-Modus ('volle'/'abraeumen'/'kranz-abraeumen'):
  //                  nur die Würfe der Teilsätze dieses Modus zählen.
  let wbSatzFilter = 'alle';
  let wbTeilFilter = 'alle';
  // Sortierung der Übersichts-Zeilen (klickbare Kopfzellen Bahn/Satz). Standard: nach Satz aufsteigend.
  // Ein Klick auf eine Spalte sortiert danach absteigend; erneuter Klick auf dieselbe Spalte toggelt.
  let ueberSortKey = 'satz'; // 'satz' | 'bahn'
  let ueberSortDir = 'asc';  // 'asc' | 'desc'
  let overrideSt = null; // Satz-Index, dessen Ergebnis-Sheet offen ist (null = zu); bearbeitet wird aus der Übersicht
  let overrideTs = null; // Teilsatz-Index im Sheet (null = ganzes Satz-Ergebnis eingeben -> auf offenen Teilsatz verteilen)
  let overrideDraft = ''; // im Override-Sheet eingetippte Ziffern
  // Zell-Cursor der Mehr-Spieler-Übersicht (nur Kontrollzentrum): { sp, r, ci } — Spieler,
  // sichtbare Zeile (nach Bahn sortiert) und Spalte (Teilsatz-Index 0.. oder letzte = Holz).
  // Pfeiltasten bewegen ihn, Enter öffnet die markierte Zelle zum Bearbeiten. null = kein Cursor.
  let cursor = null;

  // Desktop-PC (breiter Bildschirm) → Kontrollzentrum-Erfassung (Bahn-Monitor, Mehr-Spieler-
  // Übersicht, breitere Eingabe). Automatisch per Bildschirmbreite, live bei Größenänderung
  // (Listener am Ende, Aufräumen in teardownSync). Passt zum CSS-Breakpoint 900px.
  const kzMedia = window.matchMedia('(min-width: 900px)');
  const istDesktop = () => kzMedia.matches;
  // Übersicht ist beim Öffnen offen -> auf dem Desktop (Kontrollzentrum) gleich den Zell-Cursor setzen (wie beim manuellen Umschalten).
  if (satzOverviewOpen && istDesktop()) cursor = { sp: state.aktiverSpieler || 0, r: 0, ci: 0 };
  let standardbilder = normalizeStandardbilder(getStandardbilder()); // globale Schnellauswahl-Bilder (Zahl -> Liste { pins, slot })
  let pinPick = null; // offenes Schnellauswahl-Pop-up: { idx, n, combos } (null = zu)
  let sbEditN = 1; // in den Einstellungen gerade bearbeitete Holzzahl (1-8)
  let sbDraft = []; // im Einstellungs-Editor angetippte Kegel für das neue Bild
  let settings = getSettings(); // globale App-Einstellungen (u.a. ob Vorschläge gezeigt werden)
  let overNumpadOpen = !!settings.overNumpad; // Desktop-Satzübersicht: einschiebbarer Ziffernblock (Tablet) ausgefahren?
  let statsOpen = game.status === 'beendet'; // Statistik-Vollbild offen? (bei Reload eines beendeten Spiels direkt zeigen)
  let printSel = null; // Wurfprotokoll-Auswahl im Statistik-Screen: Set der Spieler-Indizes (null = noch nicht initialisiert -> alle)
  let finishSeen = statsOpen; // Spielende schon einmal automatisch gemeldet -> nicht bei jedem Render neu aufpoppen

  function persist() {
    if (saveErfassung(gameId, state) === null) toast('Speichern fehlgeschlagen — Speicher voll?');
    pushDirty();
    pushToBruecke();
  }
  // Wie persist(), aber ohne Hochschreiben — für lokal übernommene Remote-Änderungen
  // (die dürfen nicht als eigener Push zurücklaufen).
  function persistLocalOnly() { saveErfassung(gameId, state); pushToBruecke(); }

  // ── Sportwinner-Rückschreiben (nur Vereins-PC) ───────────────────────────────
  // Gehört das Spiel zu einem aus Sportwinner importierten Wettkampf UND wurde die App von der
  // Brücke mit `?push=…` geöffnet, schickt DIESES Gerät die Ergebnisse (Volle/Abräumen/Fehler je
  // Slot/Bahn) bei jeder Änderung direkt an die lokale Brücke — unabhängig davon, ob der
  // Wettkampf-Hub gerade offen ist. So wird sofort bei der Eingabe geschrieben, nicht erst beim
  // nächsten Hub-Render. Andere Geräte kennen den Push-Endpoint nicht und schreiben nichts.
  let bpushTimer = null;
  let bpushLast = '';
  let bstatusTimer = null; // pollt den echten Schnittstellen-Status der Brücke
  // Zuletzt bekannter Brücken-Status — als View-State gehalten, damit ein Re-Render (jeder Wurf
  // baut das Template neu) die Statuszeile NICHT zurücksetzt und eine Push-Bestätigung stehen bleibt.
  let swBadge = { state: 'checking', label: 'Prüfe …' };
  let swMsg = 'Status wird geprüft …';

  // Ist das Rückschreiben in DIESER Ansicht überhaupt möglich? (Sportwinner-Import + von der
  // Brücke geöffnet = Vereins-PC). Steuert Statuszeile UND Push.
  function swActive() {
    if (!game.wettkampfId || !getBruecke()) return false;
    const w = getWettkampf(game.wettkampfId);
    return !!(w && w.sportwinner);
  }

  // Status-Punkt in der Kopfzeile aus dem View-State färben (nach jedem Render aufgerufen).
  // Farbe = Zustand, Tooltip/aria = Klartext (per Tippen als Toast, siehe wire()).
  function paintSw() {
    const dot = root.querySelector('[data-bruecke-status]');
    if (dot) { dot.className = 'sw-dot is-' + swBadge.state; dot.title = swMsg; dot.setAttribute('aria-label', 'Sportwinner: ' + swMsg); }
  }

  // Live-Status der Brücke abfragen. Badge immer aktualisieren; die Hinweis-Zeile nur, wenn
  // gerade keine frische Push-Bestätigung stehen soll (msgToo=false direkt nach einem Push).
  async function pollBrueckeStatus({ msgToo = true } = {}) {
    if (!getBruecke()) return;
    const info = brueckeStatusInfo(await holeStatus());
    swBadge = { state: info.state, label: info.label };
    if (msgToo) swMsg = info.hint;
    paintSw();
  }

  // ── Sportwinner-Konflikte (Erkennung + Freeze; Entscheidung im Wettkampf-Hub) ─────────────
  // Diese Ansicht erkennt Abweichungen (Ergebnisse/Aufstellung) und friert die betroffenen
  // Ergebnis-Zellen im Rückschreiben ein, damit die Brücke einen direkten Sportwinner-Eintrag
  // nicht überschreibt. Gelöst werden die Konflikte im Wettkampf-Hub (voller Entscheidungs-Dialog);
  // hier führt ein Banner dorthin.
  let swKonfliktTimer = null;
  let swKonfliktKeys = new Set(); // eingefrorene Ergebnis-Zellen (ergKey)
  let swKonfliktN = 0;            // Anzahl offener Abweichungen (Ergebnis + Aufstellung)

  async function pollKonflikte() {
    if (!swActive()) return;
    const live = await holeSportwinnerLive();
    if (!live) return;
    const w = getWettkampf(game.wettkampfId);
    // Aktuellen Erfassungsstand (state) für DIESES Spiel einsetzen, sonst vergliche man den
    // zuletzt gespeicherten Stand statt der Live-Eingabe.
    const games = getWettkampfGames(w.id).map((g) => (g.id === gameId ? { ...g, erfassung: state } : g));
    const all = buildKonflikte(w, games, live);
    swKonfliktKeys = new Set(all.ergebnis.map((k) => k.key));
    swKonfliktN = all.ergebnis.length + all.aufstellung.length;
    paintKonfliktBanner();
  }

  function paintKonfliktBanner() {
    const box = root.querySelector('[data-sw-konflikt-banner]');
    if (!box) return;
    box.innerHTML = swKonfliktN
      ? `<a class="swk-banner" href="#/wettkampf">⚠ ${swKonfliktN} Sportwinner-${swKonfliktN === 1 ? 'Abweichung' : 'Abweichungen'} — im Wettkampf lösen →</a>`
      : '';
  }

  function pushToBruecke() {
    if (!swActive()) return;
    const w = getWettkampf(game.wettkampfId);
    // Offene Konflikt-Zellen einfrieren (nicht überschreiben, bis im Hub entschieden).
    const payload = buildSportwinnerPush(w, getWettkampfGames(w.id), { excludeKeys: swKonfliktKeys });
    if (!payload || !payload.updates.length) return;
    const json = JSON.stringify(payload);
    if (json === bpushLast) return;
    clearTimeout(bpushTimer);
    bpushTimer = setTimeout(async () => {
      bpushLast = json;
      const res = await pushErgebnis(payload);
      swMsg = res ? brueckePushText(res) : 'Brücke nicht erreichbar — läuft die Brücke auf diesem PC?';
      paintSw();
      pollBrueckeStatus({ msgToo: false }); // Badge frisch ziehen, Bestätigung stehen lassen
    }, 350);
  }

  // ── Mehrgeräte-Sync (nur bei einem mit der DB verknüpften Spiel) ─────────────
  // Local-first bleibt: ein unverknüpftes Spiel läuft rein lokal wie bisher. Bei einem
  // verknüpften Spiel schreibt DIESES Gerät nur die Würfe seiner EIGENEN Spieler hoch und
  // übernimmt fremde Änderungen live. Ein Spieler gehört immer genau einem Gerät.
  let linked = !!(game.linked && game.remoteId);
  let syncMod = null;                     // lazy geladenes backend/sync.js
  let meGeraet = null;                    // eigene Geräte-ID (entkoppelt vom Account)
  let meKonto = null;                     // eigener Account (auth.uid()) — die Person
  let owners = game.spielerOwners || {};  // position -> { id, besitzer, heartbeat }
  let unsub = null;                       // Realtime abmelden
  let hbTimer = null;                     // Heartbeat-Intervall
  let zpollTimer = null;                  // Zuschauer-Polling-Intervall (nur-lesen)
  const lastPushed = {};                  // "sp:st" -> JSON des zuletzt gepushten Blocks (Diff-Push)

  function ownerOf(sp) { return owners[sp] || null; }
  // Darf dieses Gerät den Spieler bearbeiten? Unverknüpft immer ja (lokal). Verknüpft nur,
  // wenn ich ihn besitze; freie/fremde Spieler sind gesperrt (erst „Übernehmen").
  function canEdit(sp) {
    if (zuschauer) return false;         // Zuschauer-Modus: niemals bearbeitbar
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
    if (zpollTimer) { clearInterval(zpollTimer); zpollTimer = null; }
    if (unsub) { try { unsub(); } catch (e) {} unsub = null; }
    clearTimeout(bpushTimer);
    clearInterval(bstatusTimer);
    clearInterval(swKonfliktTimer);
    window.removeEventListener('keydown', onKey);
    kzMedia.removeEventListener('change', render);
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
      meKonto = await syncMod.kontoId();
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

  // Zuschauer-Modus: statt Realtime (braucht Mitgliedschaft) den anonymen Snapshot pollen und
  // Würfe + Status live übernehmen. Nur neu rendern, wenn sich etwas geändert hat (kein Flackern,
  // kein ständiger Scroll-Reset). UI-Zustände (aktiver Spieler/Satz) bleiben erhalten.
  async function initZuschauerPoll() {
    if (!zuschauer || !game.zuschauerCode) return;
    let last = '';
    const poll = async () => {
      if (!root.isConnected) { teardownSync(); return; }
      try {
        if (!syncMod) syncMod = await import('../backend/sync.js');
        const fresh = await syncMod.zuschauerGame(game.zuschauerCode);
        const fb = (fresh.erfassung && fresh.erfassung.bloecke) || [];
        const sig = JSON.stringify(fb) + '|' + (fresh.status || '');
        if (sig === last) return;
        last = sig;
        fb.forEach((satzArr, sp) => satzArr.forEach((blk, st) => {
          if (state.bloecke[sp] && state.bloecke[sp][st] !== undefined) state.bloecke[sp][st] = blk;
        }));
        game.status = fresh.status;
        persistLocalOnly();
        render();
      } catch (e) { /* offline -> letzten Stand stehen lassen */ }
    };
    await poll();
    zpollTimer = setInterval(poll, 2500);
  }
  window.addEventListener('hashchange', teardownSync);

  // Lokales Spiel teilen: in Supabase spiegeln, ab jetzt verknüpft + Realtime.
  async function shareGame() {
    try {
      if (!syncMod) syncMod = await import('../backend/sync.js');
      game.erfassung = state;
      // LizenzIDen der Aufstellung + die eigene Spieler-Position mitgeben: die Paesse landen
      // an spiel_spieler.passnummer (hinter der RLS), profil_id NUR bei meinem eigenen Slot.
      const ident = await syncMod.spielerIdentitaet(
        game, game.wettkampfId ? getWettkampf(game.wettkampfId) : null,
      );
      const res = await syncMod.linkGame(game, ident);
      meGeraet = await syncMod.ensureGeraet();
      meKonto = await syncMod.kontoId();
      game.linked = true; game.remoteId = res.remoteId; game.beitrittsCode = res.beitrittsCode;
      game.zuschauerCode = res.zuschauerCode;
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
    } catch (e) {
      // Die echte Ursache zeigen. "online?" hat frueher JEDEN Grund verdeckt — fehlende
      // Anmeldung, RLS-Ablehnung und eine nicht eingespielte SQL-Migration sahen gleich aus.
      console.error('[teilen] Spiel teilen fehlgeschlagen', e);
      toast('Teilen fehlgeschlagen: ' + fehlerText(e, 'online?'));
    }
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
  //
  // WICHTIG für die accountbasierte Statistik: `profil_id` bedeutet „das bin ICH als SPIELER"
  // und wird deshalb nur auf genau EINER Zeile gesetzt — der eigenen Position (spielerIdentitaet:
  // eigene LizenzID in der Aufstellung, sonst die manuelle „Das bin ich"-Markierung). Wer die
  // Zeile ERFASST hat, steht getrennt in `erfasst_von`. Früher stand hier durchgängig das eigene
  // Konto, wodurch auf einem Vereins-PC alle 12 Spieler in der eigenen Statistik landeten.
  //
  // `passnummer` bleibt dagegen für ALLE Positionen gesetzt: darüber findet jeder Mitspieler
  // seine eigenen Ergebnisse in fremd erfassten Spielen wieder (pins_lizenz_im_spiel).
  async function pushResults() {
    if (!linked || !syncMod || !meGeraet) return;
    try {
      const wk = game.wettkampfId ? getWettkampf(game.wettkampfId) : null;
      const { passByPos, ichIndex } = await syncMod.spielerIdentitaet(game, wk);
      const { players } = computeGameStats(c, state.bloecke, ranges);
      const rows = [];
      players.forEach((p, sp) => {
        if (!canEdit(sp)) return;
        const pid = owners[sp] && owners[sp].id;
        if (!pid) return;
        const row = {
          spiel_id: game.remoteId, spieler_id: pid,
          profil_id: (ichIndex != null && sp === ichIndex) ? meKonto : null,
          erfasst_von: meKonto,
          gesamt: p.gesamt, schnitt_satz: p.schnittSatz, schnitt_wurf: p.schnittWurf,
          bester_satz: p.bester, neuner: p.neuner, fehl: p.fehl, wurf_count: p.wurfCount, rang: p.rang,
        };
        // passnummer nur setzen, wenn vorhanden — so bleibt das Rückschreiben auch auf einer
        // DB ohne die (neue) Spalte lauffähig (PostgREST würde eine unbekannte Spalte melden).
        if (passByPos[sp]) row.passnummer = passByPos[sp];
        rows.push(row);
      });
      if (rows.length) await syncMod.pushResults(rows);
    } catch (e) {
      // Best-effort: das Spiel bleibt lokal vollstaendig. Aber lautlos verschwinden darf der
      // Fehler nicht — sonst fehlt der Ergebnis-Snapshot spaeter unerklaerlich in der Statistik.
      console.error('[sync] Ergebnis-Snapshot fehlgeschlagen', e);
    }
  }
  function block(sp, st) { return state.bloecke[sp][st]; }
  function current() { return block(state.aktiverSpieler, state.aktiverSatz); }
  function laneOf(sp, st) { return c.bahnplan?.[sp]?.[st] ?? (c.ersteBahn + st); }
  // Reale Bahn (aus der gewählten Anlage) zu einer Bahnnummer — { id, bahnart } oder null.
  function bahnInfo(nummer) { return c.bahnZuordnung?.[nummer] || null; }
  const ART_LABEL = { classic: 'Classic', bohle: 'Bohle', schere: 'Schere' };
  // Bespielte Bahnnummern des Spiels: die frei gewählte Liste (Anlage) oder der fortlaufende
  // Bereich ersteBahn … ersteBahn+bahnen-1. Für die Bahn-Tabs/Übersicht (auch nicht fortlaufend).
  function gameLanes() {
    return Array.isArray(c.bahnListe) && c.bahnListe.length
      ? c.bahnListe.slice().sort((a, b) => a - b)
      : Array.from({ length: c.bahnen }, (_, i) => c.ersteBahn + i);
  }
  function playerName(sp) { return c.spielerListe[sp].name || ('Spieler ' + (sp + 1)); }
  // Mannschaftsname eines Spielers — nur im Wettkampf gesetzt, sonst ''. Wird in den Bahn-Tabs
  // unter dem Spielernamen gezeigt. Die Zuordnung id -> Name wird beim ersten Aufruf gecacht.
  let teamNameById = null;
  function teamNameOf(sp) {
    if (!game.wettkampfId) return '';
    if (teamNameById === null) {
      teamNameById = {};
      const w = getWettkampf(game.wettkampfId);
      ((w && w.mannschaften) || []).forEach((m) => { teamNameById[m.id] = m.name; });
    }
    const mid = c.spielerListe[sp] && c.spielerListe[sp].mannschaftId;
    return (mid != null && teamNameById[mid]) || '';
  }
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
  function selectSatz(st, closeOverview = false) {
    state.aktiverSatz = st; editIdx = null;
    overrideSt = null; overrideTs = null; overrideDraft = '';
    // Klick auf einen Satz-Tab (oben) führt direkt in die Wurfeingabe des Satzes; die
    // Übersichts-Zeilen (ohne closeOverview) lassen die Übersicht offen (Inline-Bearbeitung).
    if (closeOverview) { satzOverviewOpen = false; cursor = null; }
    persist(); render();
  }

  // Tastatur (Desktop): zur vorigen/nächsten BESETZTEN Bahn wechseln (in Bahn-Reihenfolge).
  function stepLane(dir) {
    const bs = computeBahnState();
    const belegung = {};
    bs.forEach((s, sp) => { belegung[s.lane] = sp; });
    const occupied = gameLanes().map((l) => belegung[l]).filter((sp) => sp != null);
    if (!occupied.length) return;
    const cur = occupied.indexOf(state.aktiverSpieler);
    const next = cur < 0 ? 0 : (cur + dir + occupied.length) % occupied.length;
    if (occupied[next] !== state.aktiverSpieler) selectPlayer(occupied[next]);
  }
  // Tastatur (Desktop): Satz hoch/runter (in Grenzen des Spielers).
  function stepSatz(dir) {
    const n = state.bloecke[state.aktiverSpieler].length;
    const next = state.aktiverSatz + dir;
    if (next >= 0 && next < n) selectSatz(next);
  }

  // ── Zell-Cursor der Mehr-Spieler-Übersicht (Kontrollzentrum) ─────────────────
  function ensureCursor() { if (!cursor) cursor = { sp: state.aktiverSpieler || 0, r: 0, ci: 0 }; }
  // Flache Spaltenliste über alle Spieler × editierbare Spalten (für ←/→ über Spieler hinweg).
  function cursorColumns() {
    const cols = overviewCols();
    const list = [];
    state.bloecke.forEach((_, sp) => cols.forEach((_, ci) => list.push({ sp, ci })));
    return list;
  }
  // Aktiven Spieler + Satz an die Cursor-Zelle koppeln (Ziffernblock/Statuszeile/Markierung folgen).
  function syncCursorSelection() {
    state.aktiverSpieler = cursor.sp;
    const sorted = sortedRows(cursor.sp);
    const row = sorted[Math.min(cursor.r, sorted.length - 1)];
    if (row) state.aktiverSatz = row.st;
  }
  function moveCursor(dx, dy) {
    ensureCursor();
    if (dy !== 0) cursor.r = Math.min(c.saetze - 1, Math.max(0, cursor.r + dy));
    if (dx !== 0) {
      const list = cursorColumns();
      const idx = list.findIndex((e) => e.sp === cursor.sp && e.ci === cursor.ci);
      const next = Math.min(list.length - 1, Math.max(0, (idx < 0 ? 0 : idx) + dx));
      cursor.sp = list[next].sp; cursor.ci = list[next].ci;
    }
    syncCursorSelection();
    render();
  }
  // Cursor an eine per Klick gewählte Zelle setzen (col = Teilsatz-Index oder 'holz').
  function setCursorTo(sp, st, col) {
    const r = sortedRows(sp).findIndex((x) => x.st === st);
    const ci = overviewCols().indexOf(col);
    cursor = { sp, r: r < 0 ? 0 : r, ci: ci < 0 ? 0 : ci };
  }
  // Enter auf der markierten Zelle: das passende Override-Sheet öffnen (dann Ziffern + Enter).
  function editCursorCell() {
    ensureCursor();
    const sorted = sortedRows(cursor.sp);
    const row = sorted[Math.min(cursor.r, sorted.length - 1)];
    if (!row) return;
    state.aktiverSpieler = cursor.sp;
    const col = overviewCols()[cursor.ci];
    if (col === 'holz') openSatzOverride(row.st); else openOverride(row.st, col);
  }

  // koenigFlag (nur Kranz, per Langdruck): der Wurf fällt ALLE stehenden Kranz-Kegel, der
  // König (5) bleibt stehen. Ist der Reststand exakt bekannt (ctx.exact), sind das genau
  // universe\{5} -> die konkreten Kegel werden gespeichert (Kegelbild eindeutig bestimmbar,
  // erscheint auch im Wurfprotokoll). Nur bei unbekanntem Reststand bleiben die Kegel offen
  // (kegel=null) und es wird lediglich das König-Flag gesetzt (blk.koenig[idx]=true).
  // Liefert für den Kranz-Langdruck die konkreten gefallenen Kegel oder null (unbestimmbar).
  function koenigKegelFor(ctx) {
    return ctx.exact && ctx.universe.includes(5) ? ctx.universe.filter((p) => p !== 5) : null;
  }
  function addWurf(pins, koenigFlag = false) {
    if (!guardEdit()) return false;
    const blk = current();
    if (!Array.isArray(blk.koenig)) blk.koenig = blk.wuerfe.map(() => false);
    if (editIdx !== null) {
      if (editIdx < blk.wuerfe.length) {
        const ctx = throwContext(blk, editIdx);
        const cap = koenigFlag ? ctx.maxPins - 1 : ctx.maxPins;
        if (ctx.abraeum && pins > cap) { toast(`Es stehen nur ${cap} ${koenigFlag ? 'Kranz-' : ''}Kegel`); return false; }
        const kk = koenigFlag ? koenigKegelFor(ctx) : null;
        blk.wuerfe[editIdx] = pins;
        blk.kegel[editIdx] = koenigFlag ? kk : defaultKegelFor(blk, editIdx, pins);
        blk.koenig[editIdx] = koenigFlag && kk == null;   // Flag nur, wenn Kegel offen bleiben
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
    const kk = koenigFlag ? koenigKegelFor(ctx) : null;
    blk.wuerfe.push(pins);
    blk.kegel.push(koenigFlag ? kk : defaultKegelFor(blk, idx, pins));
    blk.koenig.push(koenigFlag && kk == null);   // Flag nur, wenn Kegel offen bleiben
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

  // Hebel der Spieler-Übersicht: Spalten fest (Spieler-Reihenfolge) oder der aktuellen Bahn
  // folgend (wandern beim Bahnwechsel mit). Global gespeichert, wie die Vorschläge-Einstellung.
  function toggleBahnfolge() {
    settings = { ...settings, uebersichtBahnFolge: !settings.uebersichtBahnFolge };
    saveSettings({ uebersichtBahnFolge: settings.uebersichtBahnFolge });
    toast(settings.uebersichtBahnFolge ? 'Übersicht folgt der Bahn' : 'Übersicht in fester Reihenfolge');
    render();
  }

  // Desktop-Erfassung: Ziffernblock rechts oder links neben Kegelbrett/Bahnansicht legen.
  // Global gespeichert (wie die übrigen Einstellungen); wirkt nur im Kontrollzentrum (breiter Bildschirm).
  function setNumpadSeite(seite) {
    if (settings.numpadSeite === seite) return;
    settings = { ...settings, numpadSeite: seite };
    saveSettings({ numpadSeite: seite });
    toast(seite === 'links' ? 'Ziffernblock links' : 'Ziffernblock rechts');
    render();
  }

  // Desktop-Satzübersicht: den einschiebbaren Ziffernblock (Tablet-Eingabe ohne Tastatur)
  // aus-/einfahren. Zustand global gespeichert, damit ein Tablet ihn ausgefahren behält.
  function toggleOverNumpad() {
    overNumpadOpen = !overNumpadOpen;
    settings = { ...settings, overNumpad: overNumpadOpen };
    saveSettings({ overNumpad: overNumpadOpen });
    render();
  }

  // Steht das Kegelbild von Wurf k schon? Fertig ist es, wenn genau so viele Kegel gewählt
  // sind wie Holz geworfen wurde — dieselbe Bedingung, die die Zahl unter der Raute grün
  // färbt. Der Kranz-Langdruck (König steht, Kegel bewusst offen) gilt ebenfalls als fertig.
  function bildOffen(blk, k) {
    if (k < 0 || k >= blk.wuerfe.length) return false;
    const bild = blk.kegel[k];
    if (Array.isArray(bild) && bild.length === blk.wuerfe[k]) return false;
    return !(bild == null && Array.isArray(blk.koenig) && blk.koenig[k]);
  }

  // Ein beendeter Satz ist gesperrt — mit einer Ausnahme: das Kegelbild des LETZTEN Wurfs darf
  // noch nachgetragen werden. Genau dieser Wurf schließt den Satz ja automatisch, oft bevor die
  // Raute überhaupt angetippt werden konnte.
  //
  // Das gilt NUR für den voll durchgeworfenen Satz. Ein Satz, der über ein manuell gesetztes
  // Ergebnis oder über „Satz beenden“/„Bahn frei“ geschlossen wurde, ist bewusst ohne
  // vollständige Wurferfassung fertig — dort wartet niemand auf eine Raute. Ebenso, wenn der
  // Teilsatz DIESES Wurfs ein manuelles Ergebnis trägt: dann zählen die Kegel gar nicht mit.
  function bildNachtragbar(blk, k) {
    if (blk.wuerfe.length < c.wuerfeProSatz) return false;   // nicht voll geworfen
    if (k !== blk.wuerfe.length - 1) return false;
    const ti = ranges.findIndex((r) => k >= r.start && k < r.end);
    if (ti >= 0 && Array.isArray(blk.overrides) && blk.overrides[ti] != null) return false;
    return bildOffen(blk, k);
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
    if (blk.done && !bildNachtragbar(blk, k)) { toast('Satz ist fertig'); return; }
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

  // Ein beendeter Satz darf per ↩ direkt wieder geöffnet werden, solange er der ZULETZT
  // bespielte ist (kein späterer Satz angefangen oder beendet). Ältere Sätze bleiben gesperrt
  // — die öffnet man bewusst über die Bahneinstellung („Satz öffnen“).
  function undoReopenAllowed(sp, st) {
    const arr = state.bloecke[sp];
    for (let i = st + 1; i < arr.length; i++) if (satzStatus(arr[i]) !== 'pending') return false;
    return true;
  }

  // Ist die ↩-Taste gerade bedienbar? Steuert das Ausgrauen im Ziffernblock.
  function canUndo() {
    const blk = current();
    if (blk.wuerfe.length === 0) return false;
    return !blk.done || undoReopenAllowed(state.aktiverSpieler, state.aktiverSatz);
  }

  function undo() {
    if (!guardEdit()) return;
    const blk = current();
    if (blk.done && !undoReopenAllowed(state.aktiverSpieler, state.aktiverSatz)) {
      toast('Älterer Satz — erst über ⚙ wieder öffnen'); return;
    }
    if (blk.wuerfe.length === 0) { toast('Nichts rückgängig zu machen'); return; }
    // Ein Satz, der mit dem letzten Wurf automatisch beendet wurde, wird durch das Zurücknehmen
    // wieder geöffnet — sonst stünde er mit fehlendem Wurf weiter als „fertig“ da.
    const reopened = blk.done;
    blk.done = false;
    blk.wuerfe.pop();
    blk.kegel.pop();
    if (Array.isArray(blk.koenig)) blk.koenig.pop();
    persist(); render();
    if (reopened) toast(`Satz ${state.aktiverSatz + 1} wieder geöffnet`);
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

  // Wartet der zuletzt erfasste Wurf noch auf sein Kegelbild? Der letzte Wurf eines Satzes
  // schließt den Satz automatisch — ohne diese Bremse spränge der „Spiel beendet“-Screen auf,
  // während die Raute (bzw. das Vorschlags-Pop-up) noch offen ist. Geprüft wird nur für
  // Spieler, die DIESES Gerät erfasst — fremde Bahnen dürfen das Spielende nicht blockieren.
  function kegelbildOffen() {
    return state.bloecke.some((arr, sp) => {
      if (!canEdit(sp)) return false;
      const blk = arr[arr.length - 1];
      if (!blk) return false;
      return bildNachtragbar(blk, blk.wuerfe.length - 1);
    });
  }

  // Spielende festschreiben: Statistik zeigen, Status 'beendet', Ergebnisse spiegeln.
  function markFinished() {
    finishSeen = true;
    statsOpen = true;
    setGameStatus(gameId, 'beendet');
    finishRemote();
    reconcileWettkampfStatus();
  }

  // Übergang ins Spielende erkennen und einmalig die Statistik zeigen. Wird zu Beginn jedes
  // Renders geprüft (nachdem die Würfe/Done-Flags in `persist()` schon gespeichert sind):
  //   - alle fertig & noch nicht gemeldet -> Statistik automatisch öffnen + Status 'beendet'
  //     (aber erst, wenn auch das Kegelbild des letzten Wurfs gewählt ist).
  //   - wieder ein Satz offen -> zurück auf 'laufend' (Statistik schließt sich).
  function maybeFinish() {
    const done = allGamesDone();
    if (done && !finishSeen) {
      if (kegelbildOffen()) return;   // letzter Wurf wartet noch auf sein Kegelbild
      markFinished();
    } else if (!done && finishSeen) {
      finishSeen = false;
      statsOpen = false;
      setGameStatus(gameId, 'laufend');
      pushRemoteStatus('laufend');
      reconcileWettkampfStatus();
    }
  }

  // Spielende zum Server spiegeln. Die REIHENFOLGE ist wichtig:
  //   1) Ergebnis-Snapshots schreiben (tragen u.a. die LizenzID je Spieler),
  //   2) DANN spiel.status auf 'beendet' setzen — das löst serverseitig die Anonymisierung
  //      der Namen aus (Trigger trg_spiel_anonymisieren), die die LizenzID braucht, um das
  //      passende Profil und dessen öffentlichen Anzeigenamen zu finden.
  // Beides best-effort: ohne Verbindung bleibt der lokale Stand maßgeblich und wird beim
  // nächsten Beenden nachgezogen.
  async function finishRemote() {
    try {
      await pushResults();
      await pushRemoteStatus('beendet');
    } catch (e) { /* offline / keine Berechtigung */ }
  }

  // spiel.status spiegeln (laut RLS nur der Ersteller; auf anderen Geräten still no-op).
  async function pushRemoteStatus(status) {
    if (!linked || !syncMod || !game.remoteId) return;
    try { await syncMod.pushStatus(game.remoteId, status); } catch (e) { /* still */ }
  }

  // Ist dieser Durchgang Teil eines Wettkampfs: dessen Status an die Durchgänge angleichen.
  // Sind ALLE Durchgänge beendet, ist auch der Wettkampf beendet; wird ein Durchgang wieder
  // geöffnet, geht der Wettkampf zurück auf 'laufend'. Lokal speichern und — falls geteilt —
  // zum Server spiegeln (pushWettkampfStatus ist laut RLS Ersteller-only; sonst still no-op).
  function reconcileWettkampfStatus() {
    if (!game.wettkampfId) return;
    const w = getWettkampf(game.wettkampfId);
    if (!w || w.zuschauer) return;
    const alleFertig = wettkampfBaseStatus(w, getWettkampfGames(w.id)) === 'beendet';
    let next = null;
    if (alleFertig && w.status !== 'beendet') next = 'beendet';
    else if (!alleFertig && w.status === 'beendet') next = 'laufend';
    if (!next) return;
    w.status = next;
    saveWettkampf(w);
    if (w.linked && w.remoteId && syncMod) syncMod.pushWettkampfStatus(w.remoteId, next).catch(() => {});
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
    // Desktop-PC → Kontrollzentrum: die Erfassung verbreitert sich und zeigt oben den Live-Monitor
    // aller Bahnen (siehe CSS .erf-kz). Automatisch per Bildschirmbreite; Handy bleibt mobil-first.
    root.classList.toggle('erf-kz', istDesktop());
    // Einschiebbarer Ziffernblock der Satzübersicht: Root-Klassen steuern, wie stark der
    // Arbeitsbereich (Bahnkarten + Übersicht) zur Seite geschoben wird. „has-overpad-…" reserviert
    // den Griff, „overpad-open" zusätzlich die volle Blockbreite (siehe CSS). Nur Desktop + Übersicht.
    const padPresent = satzOverviewOpen && istDesktop();
    root.classList.toggle('has-overpad-right', padPresent && settings.numpadSeite !== 'links');
    root.classList.toggle('has-overpad-left', padPresent && settings.numpadSeite === 'links');
    root.classList.toggle('overpad-open', padPresent && overNumpadOpen);
    root.innerHTML = template();
    wire();
    wireRevealCodes(root); // Eingabe-Code verdeckt, per Klick 10 s lesbar
    keepThrowVisible();
    fitBoard();
    positionPinPick();
    paintKonfliktBanner();
    anchorOverpad();
  }

  // Oberkante des einschiebbaren Ziffernblocks auf die Bahnkarten-Oberkante setzen, damit die
  // Seitenspalte NICHT bis in die Mannschaftsübersicht darüber reicht (Wettkampf-Spiele). Ohne
  // Team-Übersicht sitzen die Bahnkarten direkt unter dem Kopf — dann beginnt der Block dort.
  function anchorOverpad() {
    const pad = root.querySelector('.erf-overpad');
    if (!pad) return;
    if (!root.isConnected) { requestAnimationFrame(anchorOverpad); return; } // erster Render: Layout steht noch nicht
    const anchor = root.querySelector('.erf-ptabs') || root.querySelector('.erf-stabs');
    const top = anchor ? Math.max(0, Math.round(anchor.getBoundingClientRect().top)) : 0;
    pad.style.top = top + 'px';
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

  // Live-Mannschaftsübersicht des Wettkampfs (nur wenn das Spiel zu einem Wettkampf gehört) —
  // dieselbe Tafel wie im Wettkampf-Hub, aber schreibgeschützt und mit dem AKTUELLEN Erfassungsstand
  // DIESES Durchgangs (state statt zuletzt gespeichert), damit sie live mit jeder Eingabe mitläuft.
  function wettkampfTeamSection() {
    if (!game.wettkampfId) return '';
    const w = getWettkampf(game.wettkampfId);
    if (!w || !(w.mannschaften || []).length) return '';
    const wkGames = getWettkampfGames(w.id).map((g) => (g.id === gameId ? { ...g, erfassung: state } : g));
    const stats = computeWettkampfStats(w, wkGames);
    const wertung = computeWertung(w, stats, wkGames);
    // EWP für die Anzeige bereitstellen (wie im Hub) — der Beste skaliert auf die volle Feldgröße.
    const feldGroesse = (w.spielerJeMannschaft || 0) * (w.mannschaften || []).length;
    assignEwp(stats.einzel, (w.mannschaften || [])[0]?.id, w.wertung?.ewp?.minHolz ?? 1, feldGroesse);
    return teamUebersichtSection(w, wkGames, stats, wertung, true, { editable: false });
  }

  function template() {
    const blk = current();
    const status = satzStatus(blk);
    const bs = computeBahnState();

    return `
      <header class="page-header">
        <a class="back-btn" href="${backHref}" aria-label="Zurück">←</a>
        <h1 class="page-title brand">Pin-Scorer</h1>
        ${swActive() ? `<span class="sw-dot is-${swBadge.state}" data-bruecke-status data-act="sw-info" role="img" aria-label="Sportwinner-Status" title="${esc(swMsg)}"></span>` : ''}
        ${allGamesDone() ? `<button type="button" class="icon-btn settings-btn" data-act="show-stats" aria-label="Statistik anzeigen">🏁</button>` : ''}
        <button type="button" class="icon-btn${allGamesDone() ? '' : ' settings-btn'}" data-act="settings" aria-label="Einstellungen">⚙</button>
      </header>

      <div data-sw-konflikt-banner></div>
      ${istDesktop() ? wettkampfTeamSection() : ''}
      ${bahnTabs(bs)}

      ${satzTabs()}

      ${satzOverviewOpen ? `
      <div class="erf-satz erf-satz-ueber">
        ${istDesktop() ? allPlayersOverview() : spielerUebersichtPanel()}
        ${(!istDesktop() && ueberTab === 'uebersicht') ? overviewNumpad() : ''}
        ${(istDesktop() && ueberTab === 'uebersicht') ? overSlideNumpad() : ''}
      </div>` : `
      <div class="erf-satz erf-pad-${settings.numpadSeite === 'links' ? 'left' : 'right'}">
        <div class="erf-play-main">
          ${zuschauer ? zuschauerBanner() : (linked && !canEdit(state.aktiverSpieler) ? lockBanner() : '')}
          ${kegelBoard(blk)}
          ${wurfChips(blk, status === 'done')}
        </div>
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
  // ── Wurfprotokoll (PDF-Druck) ────────────────────────────────────────────────
  // Kopf-Angaben fürs Blatt: Spielname + Unterzeile, im Wettkampf zusätzlich die
  // Mannschafts-Namen (für die Zeile je Spieler). Datum nur als Tag (ohne Uhrzeit).
  function protokollDatum(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
  }
  function protokollMeta() {
    const istWk = !!game.wettkampfId;
    const parts = [];
    let titel;
    let teamNameById = null;
    if (istWk) {
      const w = getWettkampf(game.wettkampfId);
      titel = (w && w.name) || 'Wettkampf';
      if (game.durchgangNr) parts.push('Durchgang ' + game.durchgangNr);
      const dat = protokollDatum((w && w.datum) || game.createdAt);
      if (dat) parts.push(dat);
      teamNameById = {};
      ((w && w.mannschaften) || []).forEach((m) => { teamNameById[m.id] = m.name; });
    } else {
      titel = 'Sportkegeln-Training';
      const dat = protokollDatum(game.createdAt);
      if (dat) parts.push(dat);
    }
    if (c.anlageName) parts.push(c.anlageName);
    if (c.preset) parts.push(c.preset);
    return { titel, sub: parts.join(' · '), istWettkampf: istWk, teamNameById };
  }
  // Protokoll für die gegebenen Spieler-Indizes bauen und drucken (leere Auswahl -> Hinweis).
  function printProtokoll(indices) {
    if (!indices || !indices.length) { toast('Keine Spieler ausgewählt'); return; }
    try {
      const html = buildProtokollHTML(game, ranges, indices, protokollMeta());
      printProtokollHTML(html);
    } catch (e) { toast('Protokoll konnte nicht erstellt werden'); }
  }

  // Export-Box im Statistik-Screen: bei mehreren Spielern je ein Häkchen (Standard: alle),
  // sonst nur der Druck-Knopf. Ein Spieler pro A4-Seite.
  function protokollExportBox(players, multi) {
    if (!printSel) printSel = new Set(players.map((p) => p.index));
    const list = multi ? `
      <div class="wp-export-players">
        ${players.map((p) => `
          <label class="wp-export-player">
            <input type="checkbox" data-wp-player="${p.index}" ${printSel.has(p.index) ? 'checked' : ''}>
            <span>${esc(p.name)}</span>
          </label>`).join('')}
      </div>` : '';
    return `
      <div class="wp-export">
        <div class="wp-export-head">🖨 Wurfprotokoll (PDF)</div>
        ${list}
        <button type="button" class="erf-btn done" data-act="print-protokoll">Drucken / Als PDF speichern</button>
      </div>`;
  }

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
          ${protokollExportBox(players, multi)}
          <div class="stats-actions">
            <button type="button" class="erf-btn" data-act="stats-close">↩ Weiter bearbeiten</button>
            <a class="erf-btn done" href="${backHref}">${esc(backLabel)}</a>
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
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">Ziffernblock (Desktop)</span>
                <span class="erf-setting-hint">Auf breiten Bildschirmen: Seite des Ziffernblocks neben Kegelbrett & Bahnansicht — und Seite, von der er in der Satzübersicht einfährt</span>
              </div>
              <div class="erf-seg" role="group" aria-label="Ziffernblock-Seite">
                <button type="button" class="erf-seg-btn${settings.numpadSeite === 'links' ? ' is-on' : ''}" data-act="numpad-links" aria-pressed="${settings.numpadSeite === 'links'}">Links</button>
                <button type="button" class="erf-seg-btn${settings.numpadSeite !== 'links' ? ' is-on' : ''}" data-act="numpad-rechts" aria-pressed="${settings.numpadSeite !== 'links'}">Rechts</button>
              </div>
            </div>
            <h3 class="erf-settings-sub">Mehrgeräte</h3>
            ${zuschauer ? `
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">👁 Zuschauer-Modus</span>
                <span class="erf-setting-hint">Du bist über einen Zuschauer-Code verbunden und siehst den Stand live. Eingaben sind nicht möglich.</span>
              </div>
            </div>` : linked ? `
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">Eingabe-Code</span>
                <span class="erf-setting-hint">Zum Mit-Erfassen: anderes Gerät → „Spiel beitreten" → diesen Code eingeben. Verdeckt — zum Ablesen antippen.</span>
              </div>
              ${revealCodeHtml(game.beitrittsCode)}
            </div>
            ${game.zuschauerCode ? `
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">👁 Zuschauer-Code</span>
                <span class="erf-setting-hint">Nur ansehen (keine Eingabe): diesen Code an Zuschauer geben.</span>
              </div>
              <span class="erf-share-code">${esc(game.zuschauerCode)}</span>
            </div>` : ''}` : `
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">Spiel teilen</span>
                <span class="erf-setting-hint">Auf mehreren Geräten gleichzeitig erfassen — Konto nicht nötig.</span>
              </div>
              <button type="button" class="erf-btn done" data-act="share">🔗 Teilen</button>
            </div>`}
            <h3 class="erf-settings-sub">Wurfprotokoll</h3>
            <div class="erf-setting-row">
              <div class="erf-setting-text">
                <span class="erf-setting-label">Als PDF drucken</span>
                <span class="erf-setting-hint">Blatt für <strong>${esc(playerName(state.aktiverSpieler))}</strong> — satzweise mit Kegelbild je Wurf. In der Endansicht (🏁) sind alle Spieler wählbar.</span>
              </div>
              <button type="button" class="erf-btn done" data-act="print-protokoll-current">🖨 Drucken</button>
            </div>
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
            <p class="erf-lane-sub">Bahn ${laneOf(sp, st)}${(() => { const bi = bahnInfo(laneOf(sp, st)); return bi && bi.bahnart ? ` (${esc(ART_LABEL[bi.bahnart] || bi.bahnart)})` : ''; })()} · ${esc(playerName(sp))} · Satz ${st + 1}</p>
            <div class="erf-lane-actions">
              ${zuschauer ? '<p class="erf-lane-sub">👁 Zuschauer-Modus — keine Eingabe möglich.</p>' : `
              <button type="button" class="erf-btn ${satzDone ? 'is-on' : 'done'}" data-act="end-satz">${satzDone ? '↺ Satz wieder öffnen' : '✓ Satz beenden'}</button>
              <button type="button" class="erf-btn ${allDone ? 'is-on' : 'danger'}" data-act="end-game">${allDone ? '↺ Spiel wieder öffnen' : '⏹ Spiel beenden (nur dieser Spieler)'}</button>
              ${linked && canEdit(sp) ? `<button type="button" class="erf-btn" data-act="release">🔓 Bahn freigeben (anderes Gerät)</button>` : ''}`}
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
        ${c.anlageName ? `<div class="sum-row"><span>Anlage</span><strong>${esc(c.anlageName)}</strong></div>` : ''}
        <div class="sum-row"><span>Bahnart</span><strong>${c.preset ? c.preset : '—'}</strong></div>
        <div class="sum-row"><span>Spieler</span><strong>${c.spieler}</strong></div>
        <div class="sum-row"><span>Bahnen</span><strong>${c.bahnListe && c.bahnListe.length
          ? `${c.bahnListe.length} <small>(Bahn ${gameLanes().join(', ')})</small>`
          : `${c.bahnen}${c.ersteBahn ? ` <small>(Bahn ${c.ersteBahn}–${c.ersteBahn + c.bahnen - 1})</small>` : ''}`}</strong></div>
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
  // Banner im Zuschauer-Modus: macht deutlich, dass nur zugesehen wird (keine Eingabe).
  function zuschauerBanner() {
    return `<div class="erf-lock-banner erf-zuschauer-banner">
      <span class="elb-text">👁 Zuschauer-Modus — live ansehen, keine Eingabe</span>
    </div>`;
  }

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
    const lanes = gameLanes();
    const belegung = {};
    bs.forEach((s, sp) => { belegung[s.lane] = sp; });

    const tabs = [];
    for (let i = 0; i < lanes.length; i++) {
      const bahn = lanes[i];
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
        ${teamNameOf(sp) ? `<span class="ept-team">${esc(teamNameOf(sp))}</span>` : ''}
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
    // um (Tab-Leisten bleiben oben stehen). Auf dem Desktop ist er der „Übersicht"-Tab und nur
    // dann aktiv gefärbt; auf dem Handy gilt jede offene Übersicht als aktiv.
    const uebersichtAktiv = satzOverviewOpen && (!istDesktop() || ueberTab === 'uebersicht');
    const overviewBtn = `<button type="button" class="erf-stab erf-stab-more${uebersichtAktiv ? ' is-active' : ''}" data-act="satz-overview" aria-pressed="${uebersichtAktiv}" aria-label="Spieler-Übersicht" title="Übersicht">▦</button>`;

    // Desktop: Statistik + Wurf-Bild als eigene Tabs links neben dem mittig gesetzten ▦-Button.
    // Sie öffnen die Übersicht auf dem jeweiligen Tab (bzw. schließen sie beim erneuten Tipp).
    if (istDesktop()) {
      const sideBtn = (id, label, title) => {
        const on = satzOverviewOpen && ueberTab === id;
        return `<button type="button" class="erf-stab erf-stab-tab${on ? ' is-active' : ''}" data-uebertab="${id}" aria-pressed="${on}" title="${title}">${label}</button>`;
      };
      const side = `<div class="erf-stabs-side">${sideBtn('statistik', 'Statistik', 'Statistik')}${sideBtn('verteilung', 'Wurfübersicht', 'Wurf-Bild')}</div>`;
      return `<div class="erf-stabs erf-stabs-desk" role="tablist">${side}${overviewBtn}<div class="erf-stabs-satze">${tabs}</div></div>`;
    }
    return `<div class="erf-stabs" role="tablist">${overviewBtn}${tabs}</div>`;
  }

  // Sätze eines Spielers, nach der aktiven Sortierung (Satz oder Bahn, auf-/absteigend) — die
  // Zeilen-Reihenfolge der Übersicht. Zweitschlüssel ist immer die Satz-Nr (stabile Reihenfolge).
  function sortedRows(sp) {
    const rows = state.bloecke[sp]
      .map((blk, st) => ({ st, blk, bahn: laneOf(sp, st), status: satzStatus(blk) }));
    const primary = ueberSortKey === 'bahn' ? 'bahn' : 'st';
    const sign = ueberSortDir === 'desc' ? -1 : 1;
    return rows.sort((a, b) => sign * (a[primary] - b[primary]) || (a.st - b.st));
  }
  // Sortierschlüssel setzen: gleiche Spalte -> Richtung umkehren; neue Spalte -> absteigend beginnen.
  function setUeberSort(key) {
    if (ueberSortKey === key) ueberSortDir = ueberSortDir === 'asc' ? 'desc' : 'asc';
    else { ueberSortKey = key; ueberSortDir = 'desc'; }
    render();
  }
  // Editierbare Spalten der Übersicht: Teilsatz-Indizes (nur bei >1 Teilsatz) + 'holz' ganz rechts.
  function overviewCols() {
    return ranges.length > 1 ? [...ranges.map((_, i) => i), 'holz'] : ['holz'];
  }

  // Editierbare Satz-Tabelle EINES Spielers (Bahn/Satz/Teilsätze/Holz, Zellen antippbar).
  // `multi` = Teil der Mehr-Spieler-Übersicht (Kontrollzentrum): dann trägt jede Zelle die
  // Spieler-Nr (data-edit-…="sp:…") und die per Pfeiltasten markierte Cursor-Zelle wird
  // hervorgehoben. Die is-editing-Markierung gilt nur beim aktiven Spieler.
  function overviewTableFor(sp, { multi = false } = {}) {
    const arr = state.bloecke[sp];
    const tsLabels = teilsatzLabels();
    const showTs = ranges.length > 1;
    const cols = overviewCols();
    const sorted = sortedRows(sp);
    const activeSp = sp === state.aktiverSpieler;
    const onCursor = (r, colVal) => !!(cursor && cursor.sp === sp && cursor.r === r && cols[cursor.ci] === colVal);

    const tsHead = showTs
      ? tsLabels.map((l, i) => `<th class="ub-h-ts" title="${esc(MODUS_LABEL[ranges[i].modus] || '')}">${esc(l)}</th>`).join('')
      : '';

    const rows = sorted.map(({ st, blk, bahn, status }, r) => {
      const empty = status === 'pending';
      const active = st === state.aktiverSatz && activeSp;
      const tsCells = showTs
        ? ranges.map((_, i) => {
          const t = teilsatzStats(blk, ranges, i, status === 'done');
          const touched = t.count > 0 || t.manual;
          // Wird diese Teilsatz-Zelle gerade per Ziffernblock bearbeitet? -> Entwurf live zeigen.
          const editing = activeSp && overrideSt === st && overrideTs === i;
          const cell = editing ? (overrideDraft || '–') : (touched ? t.val : '·');
          return `<td class="ub-ts ub-edit${t.manual ? ' is-manual' : ''}${t.mark ? ' is-mark' : ''}${editing ? ' is-editing' : ''}${onCursor(r, i) ? ' is-cursor' : ''}" data-edit-ts="${sp}:${st}:${i}" role="button" tabindex="0" aria-label="${esc(tsLabels[i])}, Satz ${st + 1} bearbeiten">${cell}${!editing && t.mark ? ' ⚠' : ''}</td>`;
        }).join('')
        : '';
      // Satz-Holz-Zelle: bearbeitet wird das ganze Satz-Ergebnis (overrideTs === null).
      const editingSatz = activeSp && overrideSt === st && overrideTs === null;
      const holzCell = editingSatz ? (overrideDraft || '–') : (empty ? '–' : satzHolz(blk, ranges));
      return `<tr class="ub-row is-${status}${active ? ' is-active' : ''}"${multi ? '' : ` data-satz="${st}"`}>
        <td class="ub-bahn">B${bahn}</td>
        <td class="ub-satz">Satz ${st + 1}</td>
        ${tsCells}
        <td class="ub-holz ub-edit${editingSatz ? ' is-editing' : ''}${onCursor(r, 'holz') ? ' is-cursor' : ''}" data-edit-satz="${sp}:${st}" role="button" tabindex="0" aria-label="Satz ${st + 1} Ergebnis bearbeiten">${holzCell}</td>
      </tr>`;
    }).join('');

    // Fußzeile: Summe je Teilsatz-Spalte über alle Sätze + Gesamt-Holz.
    const tsFoot = showTs
      ? ranges.map((_, i) =>
        `<td class="ub-ts">${arr.reduce((s, blk) => s + teilsatzStats(blk, ranges, i, satzStatus(blk) === 'done').val, 0)}</td>`).join('')
      : '';

    // Klickbare Kopfzellen Bahn/Satz mit Sortier-Pfeil (▴ auf / ▾ ab) an der aktiven Spalte.
    const sortH = (key, cls, label) => {
      const active = ueberSortKey === key;
      const ar = active ? `<span class="ub-sort-ar">${ueberSortDir === 'desc' ? '▾' : '▴'}</span>` : '';
      return `<th class="${cls} ub-h-sort${active ? ' is-sorted' : ''}" data-sort="${key}" role="button" tabindex="0" aria-label="Nach ${label} sortieren" aria-sort="${active ? (ueberSortDir === 'desc' ? 'descending' : 'ascending') : 'none'}">${label}${ar}</th>`;
    };

    return `
      <div class="ueber-tablewrap">
        <table class="ub-table">
          <thead>
            <tr>
              ${sortH('bahn', 'ub-h-bahn', 'Bahn')}
              ${sortH('satz', 'ub-h-satz', 'Satz')}
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
  }

  // Mehr-Spieler-Übersicht (nur Kontrollzentrum): die Satztabelle ALLER Spieler nebeneinander,
  // volle Bildschirmbreite. Ein Zell-Cursor (Pfeiltasten) läuft über alle Spalten/Spieler; Enter
  // öffnet die markierte Zelle zum Bearbeiten (unten mit dem Ziffernblock / per Tastatur).
  function allPlayersOverview() {
    // Spalten-Reihenfolge: fest (Spieler-Index) ODER der aktuellen Bahn folgend (Hebel). Bei
    // „nach Bahn" stehen die Spalten so wie die Bahnkarten darüber und wandern beim Bahnwechsel mit.
    const bahnFolge = !!settings.uebersichtBahnFolge;
    const order = state.bloecke.map((_, sp) => sp);
    if (bahnFolge) {
      const bs = computeBahnState();
      order.sort((a, b) => bs[a].lane - bs[b].lane);
    }
    const players = computeGameStats(c, state.bloecke, ranges).players;
    // Spalten-Inhalt je aktivem Tab: editierbare Satztabelle (Standard), Statistik-Kacheln
    // oder das Wurf-Bild — jeweils für alle Spieler nebeneinander.
    const colBody = (sp) =>
      ueberTab === 'statistik' ? statMetricsFor(sp) :
      ueberTab === 'verteilung' ? wurfVerteilungTab(state.bloecke[sp]) :
      overviewTableFor(sp, { multi: true });
    const cols = order.map((sp) => `
        <div class="eum-col${sp === state.aktiverSpieler ? ' is-active' : ''}">
          <div class="ueber-head">
            <span class="ueber-name">${esc(playerName(sp))}</span>
            <span class="ueber-total">${players[sp].gesamt}</span>
          </div>
          ${colBody(sp)}
        </div>`).join('');
    const hint =
      ueberTab === 'statistik' ? 'Kennzahlen je Spieler.' :
      ueberTab === 'verteilung' ? 'Wie häufig welches Holz-Ergebnis fiel — je Spieler.' :
      'Pfeiltasten bewegen die Markierung · Enter öffnet die Zelle · Ziffern + Enter übernehmen.';
    return `
      <div class="erf-ueber erf-ueber-multi">
        <div class="eum-toolbar">
          <p class="ueber-edithint">${hint}</p>
          <label class="eum-sync">
            <span class="eum-sync-lbl">Nach Bahn ordnen</span>
            <button type="button" class="erf-switch${bahnFolge ? ' is-on' : ''}" role="switch" aria-checked="${bahnFolge}" data-act="toggle-bahnfolge" aria-label="Übersicht nach aktueller Bahn ordnen"><span class="erf-switch-knob"></span></button>
          </label>
        </div>
        ${ueberTab === 'verteilung' ? wurfFilterBar() : ''}
        <div class="eum-grid" style="grid-template-columns: repeat(${order.length}, minmax(0, 1fr));">${cols}</div>
      </div>`;
  }

  // Kennzahl-Kacheln EINES Spielers (geteilt: mobile Übersicht + Desktop-Statistik-Spalten).
  // Kränze nur, wenn Kranz-Abräumen gespielt wird; Räumer-Schnitt nur beim Abräumen.
  function statMetricsFor(sp) {
    const stats = computeGameStats(c, state.bloecke, ranges).players[sp];
    const metric = (val, lbl) => `<div class="stats-metric"><span class="stats-metric-val">${val}</span><span class="stats-metric-lbl">${lbl}</span></div>`;
    const hasKranz = ranges.some((r) => r.modus === 'kranz-abraeumen');
    const hasAbraeum = ranges.some((r) => r.modus === 'abraeumen' || r.modus === 'kranz-abraeumen');
    return `
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
  }

  // Spieler-Übersicht (inline, ein Spieler; Bahn-/Satz-Leiste bleibt oben): Satztabelle +
  // Statistik-Kacheln + Wurf-Bild in Tabs. Der ▦-Button schaltet zurück zur Erfassung.
  function spielerUebersichtPanel() {
    const sp = state.aktiverSpieler;
    const arr = state.bloecke[sp];
    const stats = computeGameStats(c, state.bloecke, ranges).players[sp];
    const showTs = ranges.length > 1;

    // Inhalt „Übersicht": die editierbare Bahnen-Tabelle (Teilsatz-/Satz-Ergebnisse antippbar).
    const uebersichtTab = `
      <p class="ueber-edithint">Tippe ein ${showTs ? 'Teilsatz- oder Satz-Ergebnis' : 'Satz-Ergebnis'} an und ändere es unten mit dem Ziffernblock.</p>
      ${overviewTableFor(sp, { multi: false })}`;

    // Inhalt „Statistik": die Kennzahl-Kacheln (geteilte Helfer-Funktion).
    const statistikTab = statMetricsFor(sp);

    // Tab-Leiste + aktiver Inhalt.
    const tab = (id, label) =>
      `<button type="button" role="tab" aria-selected="${ueberTab === id}" class="ueber-tab${ueberTab === id ? ' is-active' : ''}" data-uebertab="${id}">${label}</button>`;
    const body =
      ueberTab === 'statistik' ? statistikTab :
      ueberTab === 'verteilung' ? wurfFilterBar() + wurfVerteilungTab(arr) :
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

  // Die im Wurf-Bild aktuell aktiven Filter greifen? (für Hinweise/Leer-Text).
  function wbFilterAktiv() { return wbSatzFilter !== 'alle' || wbTeilFilter !== 'alle'; }

  // Einzelwürfe eines Spielers nach den aktiven Wurf-Bild-Filtern einsammeln:
  //  - Satz-Filter: nur den gewählten Satz-Block (Index als String).
  //  - Teilsatz-Filter: nur die Würfe der Teilsätze mit dem gewählten Modus (per ranges-Bereich).
  // Beide sind frei kombinierbar (z. B. „Satz 2 · Volle").
  function gefilterteWuerfe(arr) {
    const out = [];
    arr.forEach((b, st) => {
      if (wbSatzFilter !== 'alle' && String(st) !== wbSatzFilter) return;
      const w = Array.isArray(b.wuerfe) ? b.wuerfe : [];
      if (wbTeilFilter === 'alle') { out.push(...w); return; }
      ranges.forEach((r) => { if (r.modus === wbTeilFilter) out.push(...w.slice(r.start, r.end)); });
    });
    return out;
  }

  // Filter-Leiste über dem Wurf-Bild: Chips für den Satz (Alle + je Satz) und — sofern das Spiel
  // mehrere Teilsatz-Modi kennt — für den Teilsatz (Alle + Volle/Abräumen/…). Beide kombinierbar.
  function wurfFilterBar() {
    const chip = (attr, val, cur, label) => {
      const on = cur === val;
      return `<button type="button" class="wb-chip${on ? ' is-on' : ''}" ${attr}="${esc(val)}" aria-pressed="${on}">${esc(label)}</button>`;
    };
    const satzChips = [chip('data-wb-satz', 'alle', wbSatzFilter, 'Alle Sätze')]
      .concat(Array.from({ length: c.saetze }, (_, st) => chip('data-wb-satz', String(st), wbSatzFilter, `Satz ${st + 1}`)))
      .join('');
    const modi = [...new Set(ranges.map((r) => r.modus))];
    let modusRow = '';
    if (modi.length > 1) {
      const modChips = [chip('data-wb-teil', 'alle', wbTeilFilter, 'Alle')]
        .concat(modi.map((m) => chip('data-wb-teil', m, wbTeilFilter, MODUS_LABEL[m] || m)))
        .join('');
      modusRow = `<div class="wb-row"><span class="wb-row-lbl">Teilsatz</span><div class="wb-chips">${modChips}</div></div>`;
    }
    return `
      <div class="wb-filter">
        <div class="wb-row"><span class="wb-row-lbl">Satz</span><div class="wb-chips">${satzChips}</div></div>
        ${modusRow}
      </div>`;
  }

  // Inhalt „Wurf-Bild": wie häufig welches Ergebnis (0–9 Holz) geworfen wurde. Zählt nur die
  // einzeln ERFASSTEN Würfe des aktiven Spielers (rein als Summe eingetragene Ergebnisse liefern
  // keine Einzelwürfe), gefiltert nach Satz und Teilsatz. Balken proportional zum häufigsten Wert;
  // 9 (Alle Neune) und 0 (Fehl) sind farblich hervorgehoben.
  function wurfVerteilungTab(arr) {
    // Zwei Häufigkeiten je Holz-Wert: GESAMT (alle Einzelwürfe) und GEFILTERT (aktueller Filter).
    // Der Balken bildet immer die Gesamt-Häufigkeit ab (stabile Länge, an der häufigsten Zahl
    // skaliert); der Filter füllt darin nur den relativen Anteil ein.
    const distGes = Array.from({ length: 10 }, () => 0);
    const distFil = Array.from({ length: 10 }, () => 0);
    arr.forEach((b) => { (Array.isArray(b.wuerfe) ? b.wuerfe : []).forEach((w) => { if (w >= 0 && w <= 9) distGes[w] += 1; }); });
    gefilterteWuerfe(arr).forEach((w) => { if (w >= 0 && w <= 9) distFil[w] += 1; });
    const gesamt = distGes.reduce((s, n) => s + n, 0);
    const total = distFil.reduce((s, n) => s + n, 0);
    if (gesamt === 0) {
      return `<p class="ueber-dist-empty">Noch keine Einzelwürfe erfasst.<br><span>Nur als Summe eingetragene Ergebnisse zählen hier nicht mit.</span></p>`;
    }
    const maxCount = Math.max(1, ...distGes); // Skala fest an der Gesamt-Häufigkeit — filterunabhängig.
    const rows = [];
    for (let v = 9; v >= 0; v -= 1) {
      const ges = distGes[v];
      const fil = distFil[v];
      const barW = (ges / maxCount) * 100;        // äußerer Balken = Gesamt-Anteil dieses Werts.
      const fillW = ges > 0 ? (fil / ges) * 100 : 0; // Füllung innerhalb = relativer Filter-Anteil.
      const pct = total > 0 ? Math.round((fil / total) * 100) : 0;
      const cls = v === 9 ? ' is-neuner' : v === 0 ? ' is-fehl' : '';
      const note = v === 9 ? '<span class="ud-note">☆</span>' : v === 0 ? '<span class="ud-note">Fehl</span>' : '';
      // Zähler: bei aktivem Filter „gefiltert/gesamt" je Wert, sonst nur die Gesamtzahl.
      const zahl = wbFilterAktiv() ? `${fil}<span class="ud-of">/${ges}</span>` : `${ges}`;
      rows.push(`
        <div class="ud-row${cls}">
          <span class="ud-val">${v}${note}</span>
          <span class="ud-bar"><span class="ud-total" style="width:${barW}%"><span class="ud-fill" style="width:${fillW}%"></span></span></span>
          <span class="ud-count">${zahl}<span class="ud-pct">${pct}%</span></span>
        </div>`);
    }
    // Kopfzeile: bei aktivem Filter „X von Gesamt", sonst nur die Gesamtzahl.
    const kopf = wbFilterAktiv()
      ? `<strong>${total}</strong> von ${gesamt} Würfen · Balken = Gesamt, gefüllt = Filter.`
      : `${gesamt} Würfe erfasst · wie häufig welches Holz-Ergebnis fiel.`;
    return `
      <p class="ueber-edithint">${kopf}</p>
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
      const locked = blk.done && !bildNachtragbar(blk, target);
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
    // ↩ ist ausgegraut, wenn es nichts zurückzunehmen gibt — und bei einem älteren, bereits
    // beendeten Satz: den öffnet man bewusst über die Bahneinstellung („Satz öffnen“).
    const undoDis = !canUndo();
    // Im Zuschauer-Modus keine Aktionstasten (Zurück/Löschen/⚙) — reine Anzeige.
    const leftAct = zuschauer ? '' : (editing
      ? `<button type="button" class="erf-num erf-num-act danger" data-act="delete" aria-label="Wurf löschen">🗑</button>`
      : `<button type="button" class="erf-num erf-num-act" data-act="undo"${undoDis ? ' disabled' : ''} aria-label="Letzten Wurf zurück">↩</button>`);
    const rightAct = zuschauer ? '' : (editing
      ? `<button type="button" class="erf-num erf-num-act" data-act="cancel-edit" aria-label="Korrektur abbrechen">✕</button>`
      : `<button type="button" class="erf-num erf-num-act" data-act="lane-settings" aria-label="Bahneinstellung">⚙</button>`);
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
      b.addEventListener('click', () => selectSatz(parseInt(b.dataset.satz, 10), b.classList.contains('erf-stab'))));
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
        const [sp, st, i] = el.dataset.editTs.split(':').map((x) => parseInt(x, 10));
        state.aktiverSpieler = sp;
        setCursorTo(sp, st, i);
        openOverride(st, i);
      }));
    root.querySelectorAll('[data-edit-satz]').forEach((el) =>
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const [sp, st] = el.dataset.editSatz.split(':').map((x) => parseInt(x, 10));
        state.aktiverSpieler = sp;
        setCursorTo(sp, st, 'holz');
        openSatzOverride(st);
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
    act('sw-info', () => toast(swMsg)); // Status-Punkt antippen -> Klartext als Toast
    act('end-satz', toggleDone);
    act('end-game', endPlayerGame);
    act('toggle-vorschlaege', toggleVorschlaege);
    act('toggle-bahnfolge', toggleBahnfolge);
    act('numpad-links', () => setNumpadSeite('links'));
    act('numpad-rechts', () => setNumpadSeite('rechts'));
    act('toggle-overpad', toggleOverNumpad);
    // 🏁 im Kopf: Statistik von Hand öffnen. Hängt das Spielende nur noch am offenen
    // Kegelbild, ist dieser Griff die bewusste Ansage „fertig“ — dann wird es festgeschrieben.
    act('show-stats', () => { if (allGamesDone() && !finishSeen) markFinished(); else statsOpen = true; render(); });
    // Wurfprotokoll: im Statistik-Screen die angehakten Spieler, im ⚙-Menü der aktive Spieler.
    act('print-protokoll', () => {
      const sel = [];
      root.querySelectorAll('[data-wp-player]').forEach((cb) => { if (cb.checked) sel.push(parseInt(cb.dataset.wpPlayer, 10)); });
      // Ohne Häkchen-Liste (Einzelspieler-Screen) alle Spieler drucken.
      printProtokoll(root.querySelector('[data-wp-player]') ? sel : state.bloecke.map((_, i) => i));
    });
    act('print-protokoll-current', () => { settingsOpen = false; render(); printProtokoll([state.aktiverSpieler]); });
    root.querySelectorAll('[data-wp-player]').forEach((cb) =>
      cb.addEventListener('change', () => {
        const i = parseInt(cb.dataset.wpPlayer, 10);
        if (cb.checked) printSel.add(i); else printSel.delete(i);
      }));
    act('share', shareGame);
    act('claim', claimActive);
    act('release', releaseActive);
    // Statistik schließen (Kopf-← und „Weiter bearbeiten" tragen beide diesen Hook).
    root.querySelectorAll('[data-act="stats-close"]').forEach((b) =>
      b.addEventListener('click', () => { statsOpen = false; render(); }));

    // Spieler-Übersicht (inline): der ▦-Button schaltet zwischen Erfassung und Übersicht um.
    // Die Übersichts-Zeilen tragen data-satz und werden über die Satz-Tab-Verdrahtung
    // (selectSatz) mitgenommen — ein Tipp auf eine Zeile wählt den Satz, die Übersicht bleibt
    // offen (Inline-Bearbeitung). Ein Tipp auf einen Satz-Tab oben (.erf-stab) schließt dagegen
    // die Übersicht und führt direkt in die Wurfeingabe des Satzes.
    act('satz-overview', () => {
      // Beim Verlassen/Umschalten eine ggf. angefangene Zellen-Bearbeitung verwerfen.
      overrideSt = null; overrideTs = null; overrideDraft = '';
      // Desktop: liegt die offene Übersicht auf Statistik/Wurf-Bild, wechselt der ▦-Button
      // zurück auf die (editierbare) Satztabelle, statt die Übersicht zu schließen.
      if (istDesktop() && satzOverviewOpen && ueberTab !== 'uebersicht') {
        ueberTab = 'uebersicht';
        cursor = { sp: state.aktiverSpieler || 0, r: 0, ci: 0 };
        render();
        return;
      }
      satzOverviewOpen = !satzOverviewOpen;
      if (satzOverviewOpen && istDesktop()) ueberTab = 'uebersicht';
      // Im Kontrollzentrum den Zell-Cursor initialisieren (Pfeiltasten-Navigation), sonst löschen.
      cursor = (satzOverviewOpen && istDesktop()) ? { sp: state.aktiverSpieler || 0, r: 0, ci: 0 } : null;
      render();
    });

    // Tabs innerhalb der Übersicht (Übersicht / Statistik / Wurf-Bild) umschalten. Ein
    // Tab-Wechsel verwirft eine angefangene Zellen-Bearbeitung (Ziffernblock gibt es nur im
    // Übersicht-Tab).
    root.querySelectorAll('[data-uebertab]').forEach((b) =>
      b.addEventListener('click', () => {
        const tab = b.dataset.uebertab;
        overrideSt = null; overrideTs = null; overrideDraft = '';
        // Desktop-Tabs in der Satz-Zeile öffnen die (ggf. geschlossene) Übersicht auf ihrem Tab;
        // ein erneuter Tipp auf den aktiven Tab schließt die Übersicht wieder.
        const inStabRow = b.classList.contains('erf-stab');
        if (inStabRow && satzOverviewOpen && ueberTab === tab) {
          satzOverviewOpen = false; cursor = null; render(); return;
        }
        if (ueberTab === tab && satzOverviewOpen) return;
        ueberTab = tab;
        if (inStabRow && !satzOverviewOpen) {
          satzOverviewOpen = true;
          cursor = istDesktop() ? { sp: state.aktiverSpieler || 0, r: 0, ci: 0 } : null;
        }
        render();
      }));

    // Wurf-Bild-Filter (Satz-Chips + Teilsatz-Modus-Chips) umschalten. Beide Dimensionen sind
    // unabhängig und kombinierbar; ein Tipp setzt nur die jeweilige Dimension neu.
    root.querySelectorAll('[data-wb-satz]').forEach((b) =>
      b.addEventListener('click', () => { wbSatzFilter = b.dataset.wbSatz; render(); }));
    root.querySelectorAll('[data-wb-teil]').forEach((b) =>
      b.addEventListener('click', () => { wbTeilFilter = b.dataset.wbTeil; render(); }));

    // Klickbare Sortier-Kopfzellen der Übersicht (Bahn/Satz). Enter/Leertaste ebenso (role=button).
    root.querySelectorAll('[data-sort]').forEach((th) => {
      th.addEventListener('click', () => setUeberSort(th.dataset.sort));
      th.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setUeberSort(th.dataset.sort); }
      });
    });

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

  // Desktop-Satzübersicht: einschiebbarer Ziffernblock für die Tablet-Eingabe (kein Hardware-
  // Keyboard nötig). Fährt von der in den Einstellungen gewählten Seite (settings.numpadSeite)
  // ein; der Griff bleibt immer sichtbar. Inhalt ist derselbe wie der mobile Übersichts-
  // Ziffernblock (overviewNumpad) und teilt dessen Verdrahtung (data-ovnum / override-apply …):
  // eine in der Tabelle angetippte Zelle wird hier per Touch eingegeben.
  function overSlideNumpad() {
    const seite = settings.numpadSeite === 'links' ? 'left' : 'right';
    const open = !!overNumpadOpen;
    // Griff-Symbol: zeigt beim Ausfahren zur Wand hin (schließen), beim Einfahren die Tastatur.
    const handleIcon = open ? (seite === 'left' ? '‹' : '›') : '⌨';
    return `
      <div class="erf-overpad erf-overpad-${seite}${open ? ' is-open' : ''}">
        <button type="button" class="erf-overpad-handle" data-act="toggle-overpad" aria-expanded="${open}" aria-label="Ziffernblock ${open ? 'einklappen' : 'ausklappen'}">${handleIcon}</button>
        <div class="erf-overpad-body">${overviewNumpad()}</div>
      </div>`;
  }

  // Ziffer/⌫ im Override-Sheet verarbeiten (max. 4 Stellen; führende Null verwerfen).
  // 'back' = letzte Ziffer löschen (⌫-Taste), 'clear' = ganzes Feld leeren (Entf/Backspace auf der
  // echten Tastatur — schnelles „auf null setzen"/zurücksetzen, danach wird frisch neu getippt).
  function overrideKey(key) {
    if (key === 'back') overrideDraft = overrideDraft.slice(0, -1);
    else if (key === 'clear') overrideDraft = '';
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
      // Leeres Feld beim Bestätigen = Ergebnis entfernen (wie der ↺-Knopf / die Entf-Taste).
      if (overrideDraft === '') { resetOverride(); return; }
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
    // Leeres Feld beim Bestätigen = Ergebnis entfernen (Ein-Teilsatz-Satz) bzw. schließen (Verteil-Modus).
    if (overrideDraft === '') { resetOverride(); return; }
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

  // Entfernen betrifft genau EINEN Teilsatz: im Teilsatz-Modus den bearbeiteten, im Satz-Modus
  // eines Ein-Teilsatz-Spiels dessen einzigen Teilsatz. Nur beim VERTEILEN einer Satz-Summe (mehrere
  // Teilsätze) gibt es kein einzelnes Ziel — dort wird bewusst nichts gelöscht, nur geschlossen, damit
  // eine versehentliche Aktion nie mehrere manuelle Ergebnisse auf einmal killt.
  function resetOverride() {
    if (!guardEdit()) return;
    const st = overrideSt;
    const blk = state.bloecke[state.aktiverSpieler][st];
    const i = overrideTs !== null ? overrideTs : (ranges.length === 1 ? 0 : null);
    if (i === null) { overrideSt = null; overrideTs = null; render(); return; }
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

  // ── Tastatureingabe am Desktop-PC ────────────────────────────────────────────
  // 0–9 = Wurf für die aktive/fokussierte Bahn · Backspace = letzter Wurf zurück ·
  // ←/→ = Bahn wechseln · ↑/↓ = Satz wechseln · Enter = manuelles Ergebnis übernehmen ·
  // Esc = offenes Pop-up/Sheet schließen bzw. Korrektur abbrechen. Auf Touch-Geräten ohne
  // Tastatur feuert das nie — daher überall aktiv (kein eigenes Gating nötig).
  function onKey(e) {
    if (!root.isConnected) { window.removeEventListener('keydown', onKey); return; }
    if (zuschauer) return; // Zuschauer-Modus: keine Tastatureingabe
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;

    const key = e.key;
    const digit = /^[0-9]$/.test(key) ? parseInt(key, 10) : null;

    // Vollbild-Statistik: nur Schließen per Esc.
    if (statsOpen) { if (key === 'Escape') { statsOpen = false; render(); e.preventDefault(); } return; }
    // Einstellungs-Sheets: nur Schließen per Esc.
    if (settingsOpen) { if (key === 'Escape') { settingsOpen = false; render(); e.preventDefault(); } return; }
    if (laneSettingsOpen) { if (key === 'Escape') { laneSettingsOpen = false; render(); e.preventDefault(); } return; }
    // Schnellauswahl-Pop-up: Ziffer = Bild an dieser Position wählen, Enter/Esc = schließen.
    if (pinPick) {
      if (key === 'Escape' || key === 'Enter') { pinPick = null; render(); e.preventDefault(); return; }
      if (digit != null) { const ci = pinPick.combos.findIndex((cb) => cb.slot === digit); if (ci >= 0) { choosePinImage(ci); e.preventDefault(); } return; }
      return;
    }
    // Manuelles Ergebnis (Übersicht): Ziffern/⌫/Enter/Esc bedienen den Entwurf.
    if (overrideSt !== null) {
      if (digit != null) { overrideKey(String(digit)); e.preventDefault(); return; }
      // Entf UND Backspace leeren das eingegebene Ergebnis komplett (schnelles Zurücksetzen).
      // Einzelne Ziffern löscht weiterhin der ⌫-Knopf im Sheet.
      if (key === 'Backspace' || key === 'Delete') { overrideKey('clear'); e.preventDefault(); return; }
      if (key === 'Enter') { applyOverride(); e.preventDefault(); return; }
      if (key === 'Escape') { overrideSt = null; overrideTs = null; overrideDraft = ''; render(); e.preventDefault(); return; }
      return;
    }
    // Mehr-Spieler-Übersicht (Kontrollzentrum): Zell-Cursor per Pfeiltasten, Enter öffnet die Zelle.
    // Cursor/Ziffern nur auf dem editierbaren Übersicht-Tab; Statistik/Wurf-Bild sind reine Anzeige.
    if (satzOverviewOpen && istDesktop()) {
      if (key === 'Escape') { satzOverviewOpen = false; cursor = null; render(); e.preventDefault(); return; }
      if (ueberTab === 'uebersicht') {
        if (key === 'ArrowLeft') { moveCursor(-1, 0); e.preventDefault(); return; }
        if (key === 'ArrowRight') { moveCursor(1, 0); e.preventDefault(); return; }
        if (key === 'ArrowUp') { moveCursor(0, -1); e.preventDefault(); return; }
        if (key === 'ArrowDown') { moveCursor(0, 1); e.preventDefault(); return; }
        if (key === 'Enter') { editCursorCell(); e.preventDefault(); return; }
        if (digit != null || key === 'Backspace') { e.preventDefault(); return; } // keine Würfe in der Übersicht
      }
      return;
    }
    // Normale Wurferfassung.
    if (digit != null) { tapNumber(digit); e.preventDefault(); return; }
    if (key === 'Backspace') { undo(); e.preventDefault(); return; }
    if (key === 'ArrowLeft') { stepLane(-1); e.preventDefault(); return; }
    if (key === 'ArrowRight') { stepLane(1); e.preventDefault(); return; }
    if (key === 'ArrowUp') { stepSatz(-1); e.preventDefault(); return; }
    if (key === 'ArrowDown') { stepSatz(1); e.preventDefault(); return; }
    if (key === 'Escape' && editIdx !== null) { editIdx = null; render(); e.preventDefault(); }
  }
  window.addEventListener('keydown', onKey);
  kzMedia.addEventListener('change', render); // Desktop⇄Handy live umschalten

  render();
  initSync();
  initZuschauerPoll();
  if (!zuschauer && swActive()) {
    pollBrueckeStatus();
    bstatusTimer = setInterval(pollBrueckeStatus, 3000);
    pollKonflikte();
    swKonfliktTimer = setInterval(pollKonflikte, 3000);
  }
  return root;
}
