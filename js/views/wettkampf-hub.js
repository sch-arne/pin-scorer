// Wettkampf-Hub — Übersicht eines Wettkampfs: die (aus dem Setup erzeugten) Durchgänge
// erfassen, die Aufstellung (Spielernamen je Mannschaft) füllen und die zusammengeführte
// Rangliste (Einzel + Mannschaft) sehen.

import { navigate } from '../router.js';
import {
  getActiveWettkampf, getWettkampf, getWettkampfGames, saveWettkampf,
  getGame, saveGame, saveErfassung, setActiveGame, deleteGame, setActiveWettkampf, deleteWettkampf,
} from '../store.js';
import { computeWettkampfStats, durchgangStatusList } from '../logic/wettkampf.js';
import { computeWertung, assignEwp, fmtPunkte } from '../logic/wettkampf-wertung.js';
import { buildSportwinnerPush } from '../logic/sportwinner-ergebnis.js';
import { adoptAufstellung } from '../logic/sportwinner-konflikte.js';
import { createKonfliktPanel } from './sportwinner-konflikt-panel.js';
import {
  getBruecke, pushErgebnis, holeStatus, holeSportwinnerLive, brueckeStatusInfo, brueckePushText,
} from '../backend/sw-bruecke.js';
import { lanePlan } from '../logic/bahnwechsel.js';
import { esc } from '../util.js';

const STATUS_LBL = { vorbereitung: 'Vorbereitung', laufend: 'Läuft', offen: 'Offen', fertig: 'Fertig' };
const STATUS_CTA = { fertig: 'Ansehen', laufend: 'Fortsetzen', vorbereitung: 'Erfassen', offen: 'Erfassen' };

export function wettkampfHubView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  // Desktop-PC (breiter Bildschirm) → Kontrollzentrum-Layout automatisch. Passt sich bei
  // Größenänderung live an (Listener unten, Aufräumen in teardown()). Passt zum CSS-Breakpoint.
  const kzMedia = window.matchMedia('(min-width: 900px)');
  const istDesktop = () => kzMedia.matches;

  // ── Mehrgeräte-Sync ──────────────────────────────────────────────────────────
  let syncMod = null;      // lazy geladenes backend/sync.js
  let unsub = null;        // Realtime abmelden
  let reloadTimer = null;  // entprellt das Neuladen bei Remote-Änderungen
  let subscribedIds = '';  // Signatur der aktuell abonnierten Durchgang-Remote-IDs
  let syncMsg = '';        // Statuszeile der Mehrgeräte-Sektion

  // ── Sportwinner-Rückschreiben (nur Vereins-PC) ───────────────────────────────
  // Ist der Wettkampf aus Sportwinner importiert UND wurde die App von der Brücke mit
  // `?push=…` geöffnet, rechnet der Hub die Ergebnisse (Volle/Abräumen/Fehler je Slot/Bahn)
  // und schickt sie an die lokale Brücke, die sie per DLL nach Sportwinner schreibt.
  let pushTimer = null;
  let lastPushJson = '';   // zuletzt gesendeter Auftrag — verhindert redundante Übertragungen
  let statusTimer = null;  // pollt den echten Schnittstellen-Status der Brücke
  // Zuletzt bekannter Brücken-Status als View-State — ein Re-Render (z. B. Realtime-Update)
  // behält so den Status und überschreibt eine frische Push-Bestätigung nicht mit „Prüfe …".
  let swBadge = { state: 'checking', label: 'Prüfe …' };
  let swMsg = 'Status wird geprüft …';

  // ── Sportwinner-Konflikte (Sportwinner ⇄ App) ────────────────────────────────
  // Die App pollt den Sportwinner-Live-Stand; der gemeinsame Controller zeigt Abweichungen
  // (Ergebnisse/Aufstellung) und wickelt die Entscheidungen ab. Offene Ergebnis-Konflikte
  // frieren ihre Zelle im Rückschreiben ein (activeKeys -> excludeKeys), damit die Brücke den
  // Sportwinner-Eintrag nicht überschreibt, bevor der Nutzer entschieden hat.
  let swLiveTimer = null;
  const konfliktPanel = createKonfliktPanel(() => root.querySelector('[data-sw-konflikte]'), {
    getData: () => {
      const w = getWettkampf(getActiveWettkampf());
      return { wettkampf: w, games: w ? getWettkampfGames(w.id) : [] };
    },
    onAdoptErgebnis: (k, block) => {
      const game = getGame(k.gameId);
      if (!game) return;
      const erfassung = game.erfassung && Array.isArray(game.erfassung.bloecke)
        ? game.erfassung : { bloecke: (game.config.spielerListe || []).map(() => []) };
      if (!Array.isArray(erfassung.bloecke[k.spielerIdx])) erfassung.bloecke[k.spielerIdx] = [];
      erfassung.bloecke[k.spielerIdx][k.satz] = block;
      saveErfassung(k.gameId, erfassung);
      // Auf andere Geräte spiegeln (best effort; der Vereins-PC ist ohnehin die Quelle für SW).
      const sid = game.spielerOwners && game.spielerOwners[k.spielerIdx] && game.spielerOwners[k.spielerIdx].id;
      if (game.remoteId && syncMod && sid) syncMod.pushBlock(game.remoteId, sid, k.satz, block).catch(() => {});
    },
    onKeepErgebnis: () => {
      // App behalten -> Zelle ist nicht mehr gefroren -> Push schreibt sie nach Sportwinner.
      const w = getWettkampf(getActiveWettkampf());
      if (w) pushToBruecke(w, getWettkampfGames(w.id));
    },
    onAdoptAufstellung: (k) => {
      const w = getWettkampf(getActiveWettkampf());
      const game = getGame(k.gameId);
      if (!w || !game) return;
      const { wettkampf: w2, game: g2 } = adoptAufstellung(w, game, k);
      saveWettkampf(w2);
      saveGame(g2);
      if (g2.remoteId && syncMod) syncMod.pushConfig(g2.remoteId, g2.config).catch(() => {});
      render();
    },
    onKeepAufstellung: () => { render(); },
  });

  async function pollKonflikte() {
    if (!getBruecke()) return;
    const w = getWettkampf(getActiveWettkampf());
    if (!w || !w.sportwinner) return;
    const live = await holeSportwinnerLive();
    if (live) konfliktPanel.update(live);
  }

  // Status-Badge + Hinweis-Zeile aus dem View-State ins DOM malen (nach jedem Render).
  function paintSw() {
    const badge = root.querySelector('[data-bruecke-status]');
    if (badge) { badge.textContent = swBadge.label; badge.className = 'sw-status is-' + swBadge.state; }
    const msg = root.querySelector('[data-bruecke-msg]');
    if (msg) msg.textContent = swMsg;
  }

  // Live-Status der Brücke abfragen. So sieht man in der App, ob die Sportwinner-Schnittstelle
  // wirklich offen ist (SpielCount>0) — statt pauschal „aktiv". Badge immer aktualisieren; die
  // Hinweis-Zeile nur, wenn gerade keine frische Push-Bestätigung stehen soll.
  async function pollBrueckeStatus({ msgToo = true } = {}) {
    if (!getBruecke()) return;
    const info = brueckeStatusInfo(await holeStatus());
    swBadge = { state: info.state, label: info.label };
    if (msgToo) swMsg = info.hint;
    paintSw();
  }

  function setSyncMsg(m) {
    syncMsg = m || '';
    const el = root.querySelector('[data-sync-msg]');
    if (el) el.textContent = syncMsg;
  }

  function pushToBruecke(wettkampf, games) {
    if (!wettkampf || !wettkampf.sportwinner || !getBruecke()) return;
    // Offene Ergebnis-Konflikte einfrieren: diese Zellen NICHT nach Sportwinner schreiben,
    // bis der Nutzer entschieden hat (sonst überschriebe die Brücke den Sportwinner-Eintrag).
    const payload = buildSportwinnerPush(wettkampf, games, { excludeKeys: konfliktPanel.activeKeys() });
    if (!payload || !payload.updates.length) return;
    const json = JSON.stringify(payload);
    if (json === lastPushJson) return; // nichts Neues
    clearTimeout(pushTimer);
    pushTimer = setTimeout(async () => {
      const res = await pushErgebnis(payload);
      if (res) lastPushJson = json;
      swMsg = res ? brueckePushText(res) : 'Brücke nicht erreichbar — läuft die Brücke auf diesem PC?';
      paintSw();
      pollBrueckeStatus({ msgToo: false }); // Badge frisch ziehen, Bestätigung stehen lassen
    }, 600);
  }

  function render() {
    const wettkampf = getWettkampf(getActiveWettkampf());
    if (!wettkampf) {
      root.innerHTML = `
        <header class="page-header">
          <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
          <h1 class="page-title">Kein Wettkampf</h1>
        </header>
        <div class="placeholder"><p class="placeholder-text">Kein aktiver Wettkampf gefunden.</p></div>`;
      return;
    }
    const games = getWettkampfGames(wettkampf.id);
    const stats = computeWettkampfStats(wettkampf, games);
    const wertung = computeWertung(wettkampf, stats, games); // Spielpunkte (Duell/EWP) oder null
    // Einzelwertungspunkte für die Aufstellung immer bereitstellen — computeWertung vergibt sie
    // nur bei aktiver Duell/EWP-Wertung, hier zeigen wir sie unabhängig von der Punktvergabe.
    // Für die Anzeige skaliert der Beste auf die volle Feldgröße (Spieler je Mannschaft × Anzahl
    // Mannschaften), nicht nur auf die Zahl der aktuell Spielenden.
    const feldGroesse = (wettkampf.spielerJeMannschaft || 0) * (wettkampf.mannschaften || []).length;
    assignEwp(stats.einzel, (wettkampf.mannschaften || [])[0]?.id,
      wettkampf.wertung?.ewp?.minHolz ?? 1, feldGroesse);
    // Desktop-PC → Kontrollzentrum: breites, mehrspaltiges Layout. Auf schmalen Schirmen
    // (Handy/Tablet hochkant) bleibt der Hub mobil-first — automatisch per Bildschirmbreite.
    const kz = istDesktop();
    root.classList.toggle('view-kontrollzentrum', kz);
    root.innerHTML = template(wettkampf, games, stats, wertung, syncMsg, kz);
    wire(wettkampf, games);
    paintSw(); // gehaltenen Brücken-Status ins frisch gerenderte DOM malen
    konfliktPanel.paint(); // offene Konflikte ins frisch gerenderte DOM malen
    pushToBruecke(wettkampf, games);
  }

  // Spielernamen der Aufstellung (Mannschaft + Position) im richtigen Durchgang-Spiel setzen.
  function editName(games, teamId, teamPos, value) {
    for (const g of games) {
      const idx = (g.config?.spielerListe || []).findIndex((p) => p.mannschaftId === teamId && p.teamPos === teamPos);
      if (idx >= 0) {
        const game = getGame(g.id);
        if (game) { game.config.spielerListe[idx].name = value; saveGame(game); }
        return;
      }
    }
  }

  // Startbahn eines Spielers ändern — nur innerhalb der Team-Bahnen. Belegt ein anderer Spieler
  // desselben Durchgangs die Zielbahn, tauschen die beiden (bleibt in den Team-Bahnen). Danach
  // den Bahnplan des Durchgangs neu berechnen.
  function editLane(games, teamId, teamPos, newLane) {
    for (const g of games) {
      const list = g.config?.spielerListe || [];
      const idx = list.findIndex((p) => p.mannschaftId === teamId && p.teamPos === teamPos);
      if (idx < 0) continue;
      const game = getGame(g.id);
      if (!game) return;
      const spl = game.config.spielerListe;
      const old = spl[idx].startBahn;
      const other = spl.findIndex((p, j) => j !== idx && p.startBahn === newLane);
      if (other >= 0) spl[other].startBahn = old;
      spl[idx].startBahn = newLane;
      game.config.bahnplan = lanePlan({
        bahnListe: game.config.bahnListe, saetze: game.config.saetze,
        bahnwechsel: game.config.bahnwechsel, spielerData: spl,
      });
      saveGame(game);
      pushConfig(game);
      return;
    }
  }

  // Config eines (verknüpften) Durchgang-Spiels zum Server spiegeln. Nur der Ersteller
  // darf das laut RLS — bei anderen Geräten schlägt es still fehl (lokale Anzeige bleibt).
  function pushConfig(game) {
    if (game && game.remoteId && syncMod) syncMod.pushConfig(game.remoteId, game.config).catch(() => {});
  }

  // Das Durchgang-Spiel finden, in dem (Mannschaft, Position) sitzt, und dessen Config pushen.
  function pushConfigOfTeamPos(games, teamId, teamPos) {
    for (const g of games) {
      const idx = (g.config?.spielerListe || []).findIndex((p) => p.mannschaftId === teamId && p.teamPos === teamPos);
      if (idx >= 0) { pushConfig(getGame(g.id)); return; }
    }
  }

  function removeDurchgang(wettkampf, gameId, nr) {
    if (!window.confirm(`Durchgang ${nr} wirklich löschen?`)) return;
    deleteGame(gameId);
    wettkampf.durchgaenge = (wettkampf.durchgaenge || []).filter((x) => x.gameId !== gameId);
    saveWettkampf(wettkampf);
    render();
  }

  // Frischen Remote-Stand ziehen und lokal spiegeln (Durchgang-Spiele + Wettkampf).
  // IDs sind stabil aus den Remote-IDs abgeleitet -> saveGame überschreibt vorhandene;
  // remote gelöschte Durchgänge werden lokal entfernt.
  async function reload() {
    const w = getWettkampf(getActiveWettkampf());
    if (!w || !w.remoteId || !syncMod) return;
    const { wettkampf: fresh, games } = await syncMod.pullWettkampf(w.remoteId);
    const keep = new Set(games.map((g) => g.id));
    getWettkampfGames(fresh.id).forEach((g) => { if (!keep.has(g.id)) deleteGame(g.id); });
    games.forEach((g) => saveGame(g));
    saveWettkampf(fresh);
    render();
  }

  // Manuell (lokal) ergänzte Durchgänge eines bereits verknüpften Wettkampfs nachträglich
  // hochladen. Die lokale Temp-Kopie wird danach entfernt (reload holt die 'r-'-Version).
  async function reconcileUnlinked(w) {
    const locals = getWettkampfGames(w.id).filter((g) => !g.remoteId);
    for (const g of locals) {
      await syncMod.linkGame(g, { wettkampfRemoteId: w.remoteId });
      deleteGame(g.id);
    }
  }

  function subscribeNow() {
    if (unsub) { try { unsub(); } catch (e) {} unsub = null; }
    const w = getWettkampf(getActiveWettkampf());
    if (!w || !w.remoteId || !syncMod) return;
    const ids = getWettkampfGames(w.id).map((g) => g.remoteId).filter(Boolean);
    subscribedIds = ids.join(',');
    unsub = syncMod.subscribeWettkampf(w.remoteId, ids, { onChange: onRemoteChange });
  }

  function onRemoteChange() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(async () => {
      if (!root.isConnected) { teardown(); return; }
      try { await reload(); } catch (e) { return; }
      // Durchgang-Menge könnte sich geändert haben -> Subscription auffrischen.
      const w = getWettkampf(getActiveWettkampf());
      const ids = w ? getWettkampfGames(w.id).map((g) => g.remoteId).filter(Boolean).join(',') : '';
      if (ids !== subscribedIds) subscribeNow();
    }, 400);
  }

  // Beim Öffnen eines bereits verknüpften Wettkampfs: frisch laden + Realtime abonnieren.
  // Fällt still auf lokal zurück, wenn offline.
  async function initSync() {
    const w = getWettkampf(getActiveWettkampf());
    if (!w || !w.linked || !w.remoteId) return;
    try {
      syncMod = await import('../backend/sync.js');
      await reconcileUnlinked(w);
      await reload();
      subscribeNow();
    } catch (e) { /* offline -> lokal weiterarbeiten */ }
  }

  // Wettkampf teilen: in Supabase spiegeln, lokale (unverknüpfte) Kopie durch die
  // remote-gespiegelte ersetzen, ab jetzt verknüpft + Realtime.
  async function shareWettkampf() {
    const w = getWettkampf(getActiveWettkampf());
    if (!w || w.linked) return;
    setSyncMsg('Teile Wettkampf …');
    try {
      if (!syncMod) syncMod = await import('../backend/sync.js');
      const games = getWettkampfGames(w.id);
      const { remoteId } = await syncMod.linkWettkampf(w, games);
      const { wettkampf: fresh, games: freshGames } = await syncMod.pullWettkampf(remoteId);
      deleteWettkampf(w.id);            // alten (lokalen) WK + alte 'g'-Durchgänge entfernen
      freshGames.forEach((g) => saveGame(g));
      saveWettkampf(fresh);
      setActiveWettkampf(fresh.id);
      render();
      subscribeNow();
      setSyncMsg('Geteilt · Code ' + (fresh.beitrittsCode || ''));
    } catch (e) {
      const m = (e && e.message) || '';
      setSyncMsg(/angemeldet|login|auth/i.test(m)
        ? 'Zum Teilen anmelden (Menü → Spieler).'
        : 'Teilen fehlgeschlagen — online sein und erneut versuchen.');
    }
  }

  function teardown() {
    clearTimeout(reloadTimer);
    clearTimeout(pushTimer);
    clearInterval(statusTimer);
    clearInterval(swLiveTimer);
    if (unsub) { try { unsub(); } catch (e) {} unsub = null; }
    kzMedia.removeEventListener('change', render);
    window.removeEventListener('hashchange', teardown);
  }

  function wire(wettkampf, games) {
    const add = root.querySelector('[data-action="add-durchgang"]');
    if (add) add.addEventListener('click', () => navigate('/setup/wettkampf-durchgang'));
    root.querySelectorAll('[data-open]').forEach((b) =>
      b.addEventListener('click', () => { setActiveGame(b.dataset.open); navigate('/spiel-laufend'); }));
    root.querySelectorAll('[data-del-durchgang]').forEach((b) =>
      b.addEventListener('click', () => removeDurchgang(wettkampf, b.dataset.delDurchgang, b.dataset.nr)));

    // Aufstellung: Namen live in die jeweiligen Durchgang-Spiele schreiben. Während des Tippens
    // nur speichern (Fokus halten); beim Verlassen des Feldes neu rendern (Rangliste-Namen).
    root.querySelectorAll('.roster-name').forEach((inp) => {
      inp.addEventListener('input', () => editName(games, inp.dataset.team, parseInt(inp.dataset.pos, 10), inp.value));
      inp.addEventListener('change', () => {
        pushConfigOfTeamPos(games, inp.dataset.team, parseInt(inp.dataset.pos, 10));
        render();
      });
    });
    // Startbahn eines Spielers (nur Team-Bahnen).
    root.querySelectorAll('.roster-lane').forEach((sel) =>
      sel.addEventListener('change', () => {
        editLane(games, sel.dataset.team, parseInt(sel.dataset.pos, 10), parseInt(sel.value, 10));
        render();
      }));

    const share = root.querySelector('[data-action="share"]');
    if (share) share.addEventListener('click', shareWettkampf);

    // Team-Logos: Datei wählen → verkleinern → in die Mannschaft schreiben (lokal + Server).
    root.querySelectorAll('input[data-logo]').forEach((inp) =>
      inp.addEventListener('change', async () => {
        const file = inp.files && inp.files[0];
        if (!file) return;
        try {
          const logo = await fileToLogo(file);
          setTeamLogo(wettkampf, inp.dataset.logo, logo);
        } catch (e) { setOverlayMsg('Logo konnte nicht geladen werden.'); }
      }));
    root.querySelectorAll('[data-logo-del]').forEach((b) =>
      b.addEventListener('click', () => setTeamLogo(wettkampf, b.dataset.logoDel, null)));

    // Akzentfarbe (change = wenn der Farbwähler schließt, nicht bei jedem Zwischenwert)
    // und Logo-Hintergrund (hell/dunkel) pro Mannschaft.
    root.querySelectorAll('input[data-accent]').forEach((inp) =>
      inp.addEventListener('change', () => setTeamAccent(wettkampf, inp.dataset.accent, inp.value)));
    root.querySelectorAll('select[data-logobg]').forEach((sel) =>
      sel.addEventListener('change', () => setTeamLogoBg(wettkampf, sel.dataset.logobg, sel.value)));

    // Overlay-URL kopieren.
    const copy = root.querySelector('[data-action="copy-overlay"]');
    if (copy) copy.addEventListener('click', async () => {
      const url = overlayUrl(wettkampf);
      try { await navigator.clipboard.writeText(url); setOverlayMsg('URL kopiert.'); }
      catch (e) {
        const inp = root.querySelector('[data-overlay-url]');
        if (inp) { inp.focus(); inp.select(); }
        setOverlayMsg('Bitte manuell kopieren (Strg+C).');
      }
    });
  }

  function setOverlayMsg(m) {
    const el = root.querySelector('[data-overlay-msg]');
    if (el) el.textContent = m || '';
  }

  // Logo einer Mannschaft setzen/entfernen: lokal speichern, neu rendern und (falls geteilt)
  // die Wettkampf-Config zum Server spiegeln, damit das Overlay das Logo sieht.
  function setTeamLogo(wettkampf, teamId, logo) {
    const m = (wettkampf.mannschaften || []).find((x) => x.id === teamId);
    if (!m) return;
    if (logo) m.logo = logo; else delete m.logo;
    saveWettkampf(wettkampf);
    render();
    pushWettkampfConfigNow(wettkampf);
  }

  // Akzentfarbe einer Mannschaft setzen (Default Gold → Feld weglassen). Wie bei den Logos:
  // lokal speichern, neu rendern und zum Server spiegeln, damit das Overlay die Farbe sieht.
  function setTeamAccent(wettkampf, teamId, color) {
    const m = (wettkampf.mannschaften || []).find((x) => x.id === teamId);
    if (!m || !/^#[0-9a-fA-F]{6}$/.test(color || '')) return;
    if (color.toLowerCase() === '#f5a623') delete m.accent; else m.accent = color;
    saveWettkampf(wettkampf);
    render();
    pushWettkampfConfigNow(wettkampf);
  }

  // Logo-Hintergrund (hell/dunkel) einer Mannschaft setzen. Dunkel = Default → Feld weglassen.
  function setTeamLogoBg(wettkampf, teamId, mode) {
    const m = (wettkampf.mannschaften || []).find((x) => x.id === teamId);
    if (!m) return;
    if (mode === 'light') m.logoBg = 'light'; else delete m.logoBg;
    saveWettkampf(wettkampf);
    render();
    pushWettkampfConfigNow(wettkampf);
  }

  // Wettkampf-Config (Mannschaften/Logos …) zum Server spiegeln — dieselbe Form wie
  // linkWettkampf (ohne Remote-/Laufzeit-Felder). Nur der Ersteller darf das laut RLS;
  // sonst still fehlschlagen (lokale Anzeige bleibt).
  function pushWettkampfConfigNow(wettkampf) {
    if (!wettkampf.remoteId || !syncMod) return;
    const { remoteId, beitrittsCode, linked, updatedAt, durchgaenge, id, ...rest } = wettkampf;
    syncMod.pushWettkampfConfig(remoteId, { ...rest }).catch(() => {});
  }

  render();
  window.addEventListener('hashchange', teardown);
  kzMedia.addEventListener('change', render); // Desktop⇄Handy live umschalten
  initSync();
  if (getBruecke()) {
    pollBrueckeStatus();
    statusTimer = setInterval(pollBrueckeStatus, 3000);
    pollKonflikte();
    swLiveTimer = setInterval(pollKonflikte, 3000);
  }
  return root;
}

// Führende Mannschaft ermitteln: bei aktiver Duell-Wertung die mit den höheren Spielpunkten,
// sonst die (eindeutig) auf Gesamtholz-Rang 1 stehende. Gleichstand -> keine Führung markiert.
function leadTeamId(stats, wertung) {
  if (wertung && wertung.home && wertung.away && wertung.home.spielpunkte !== wertung.away.spielpunkte) {
    return wertung.home.spielpunkte > wertung.away.spielpunkte ? wertung.homeId : wertung.awayId;
  }
  const played = (stats.mannschaften || []).filter((t) => (t.gesamt || 0) > 0);
  const firsts = played.filter((t) => t.rang === 1);
  return firsts.length === 1 ? firsts[0].mannschaftId : null;
}

// Mannschafts-Übersicht (linke Spalte): je Mannschaft eine Tafel mit integrierter Aufstellung.
// Oben Kopf (Name, Spielpunkte bei aktiver Duell/EWP-Wertung, Führungs-Markierung) und die
// Team-Summen (Gesamtholz, EWP, Aufschlüsselung). Darunter die Spieler:
//   • solange die Mannschaft noch keine Ergebnisse hat: Aufstellung (Name + Startbahn wählbar),
//   • sobald Ergebnisse vorliegen: eine bahnweise Ergebnistabelle je Spieler (Ergebnis pro Bahn)
//     mit Ges. Volle, Ges. Abräumen, Gesamtholz und EWP, plus einer Mannschafts-Summenzeile.
function teamUebersichtSection(wettkampf, games, stats, wertung, kz) {
  const teams = wettkampf.mannschaften || [];
  if (!teams.length) return '';
  const lead = leadTeamId(stats, wertung);
  // Namen/Startbahnen der Aufstellung aus den Durchgang-Spielen (für die Bearbeitung im Setup).
  const nameOf = {}; const laneOf = {};
  (games || []).forEach((g) => (g.config?.spielerListe || []).forEach((p) => {
    if (p.mannschaftId && p.teamPos) {
      nameOf[`${p.mannschaftId}|${p.teamPos}`] = p.name || '';
      laneOf[`${p.mannschaftId}|${p.teamPos}`] = p.startBahn;
    }
  }));
  const anyResults = (stats.mannschaften || []).some((t) => (t.gesamt || 0) > 0);
  // Gegenüberstellung (Scoreboard): bei genau zwei Mannschaften auf breitem Schirm stehen sie
  // nebeneinander, die zweite gespiegelt — die Zahlen beider Teams zeigen so zur Mitte.
  const facing = !!kz && teams.length === 2;
  const cards = teams.map((m, ti) =>
    teamCard(wettkampf, m, stats, wertung, lead, nameOf, laneOf, anyResults, facing && ti === 1)).join('');
  return `
    <section class="field kz-team-uebersicht${facing ? ' is-facing' : ''}">
      <label class="field-label">Mannschafts-Übersicht</label>
      <div class="wk-teams">${cards}</div>
      <p class="field-hint">Namen und Startbahn (nur Team-Bahnen) werden direkt in die Durchgänge übernommen; die Startbahn bleibt änderbar, solange ein Spieler noch kein Ergebnis hat. Sobald Ergebnisse vorliegen, erscheinen die Bahn-Ergebnisse sowie Volle/Abräumen je Spieler.</p>
    </section>`;
}

// Gesamtholz eines Spielers auf einer bestimmten Bahn (summiert, falls die Bahn mehrfach
// gespielt wurde); null, wenn der Spieler auf dieser Bahn (noch) kein Ergebnis hat.
function holzAufBahn(p, bahn) {
  let sum = null;
  ((p && p.saetze) || []).forEach((s) => { if (s.bahn === bahn) sum = (sum || 0) + (s.holz || 0); });
  return sum;
}

// Startbahn-Steuerung eines (noch ergebnislosen) Spielers: Auswahl innerhalb der Team-Bahnen,
// bei nur einer Bahn die feste Anzeige. Änderungen laufen über die roster-lane-Verdrahtung.
function startbahnCtrl(m, pos, teamLanes, laneOf) {
  const cur = laneOf[`${m.id}|${pos}`];
  return teamLanes.length > 1
    ? `<select class="wk-lane roster-lane" data-team="${esc(m.id)}" data-pos="${pos}" aria-label="Startbahn">
         ${teamLanes.map((n) => `<option value="${n}"${cur === n ? ' selected' : ''}>Bahn ${n}</option>`).join('')}
       </select>`
    : `<span class="wk-lane-fix">Bahn ${cur ?? (teamLanes[0] ?? '–')}</span>`;
}

function teamCard(wettkampf, m, stats, wertung, lead, nameOf, laneOf, anyResults, mirror) {
  const P = wettkampf.spielerJeMannschaft || 0;
  const teamLanes = (m.lanes || []).slice().sort((a, b) => a - b);
  const st = (stats.mannschaften || []).find((t) => t.mannschaftId === m.id)
    || { gesamt: 0, spieler: 0, schnitt: 0 };
  const w = wertung && wertung.teams && wertung.teams[m.id];
  const isLead = lead === m.id;

  // Spieler dieses Teams nach Position (1 … P), jeweils mit ihrem Ergebnis-Objekt (falls vorhanden).
  const byPos = {};
  (stats.einzel || []).forEach((p) => { if (p.mannschaftId === m.id && p.teamPos) byPos[p.teamPos] = p; });
  const rows = Array.from({ length: P }, (_, k) => ({ pos: k + 1, p: byPos[k + 1] || null }));
  const teamHasResults = rows.some((r) => r.p && (r.p.gesamt || 0) > 0);
  const ewpSum = rows.reduce((s, r) => s + (r.p ? (r.p.ewp || 0) : 0), 0);

  // Kopfzeile mit Spielpunkten (nur bei aktiver Duell/EWP-Wertung UND sobald überhaupt Ergebnisse
  // vorliegen — im reinen Setup ist der Punktestand aus 0-Holz-Gleichstand nicht aussagekräftig).
  const spBox = w && anyResults
    ? `<span class="wk-team-sp" title="Spielpunkte">${fmtPunkte(w.spielpunkte)}<small>Punkte</small></span>`
    : '';
  const head = `
    <div class="wk-team-head">
      <span class="wk-team-rank">${isLead ? '🥇' : ''}</span>
      <span class="wk-team-name">${esc(m.name)}</span>
      <small class="wk-team-lanes">Bahn ${teamLanes.join(', ') || '—'}</small>
      ${spBox}
    </div>`;

  // Team-Summen nur zeigen, sobald Ergebnisse vorliegen (im reinen Setup irrelevant/0).
  const drittStat = w
    ? `<span class="wk-team-stat"><b>${fmtPunkte(w.mannschaftspunkte)}<span class="wk-plus">+</span>${fmtPunkte(w.ewpPunkt)}</b><small>Holz + EWP</small></span>`
    : `<span class="wk-team-stat"><b>${st.schnitt.toFixed(0)}</b><small>Ø / Spieler</small></span>`;
  const stats3 = teamHasResults ? `
    <div class="wk-team-stats">
      <span class="wk-team-stat"><b>${st.gesamt}</b><small>Gesamtholz</small></span>
      <span class="wk-team-stat"><b>${ewpSum}</b><small>EWP</small></span>
      ${drittStat}
    </div>` : '';

  const body = teamHasResults
    ? ergebnisTabelle(m, rows, st, ewpSum, teamLanes, laneOf, mirror)
    : aufstellungListe(m, rows, teamLanes, nameOf, laneOf, mirror);

  return `
    <div class="wk-team-card${isLead ? ' is-lead' : ''}${mirror ? ' is-mirror' : ''}">
      ${head}
      ${stats3}
      ${body}
    </div>`;
}

// Nullen unterdrücken: 0/null/undefined werden leer dargestellt (bessere Lesbarkeit der Tabelle).
function nz(v) { return v ? v : ''; }

// Bahnweise Ergebnistabelle: Pos, Name, Wurf (Startbahn — bei noch ergebnislosen Spielern wählbar),
// je eine Spalte pro gespielter Bahn, dann Volle/Abräumen/Gesamt/EWP. Je Spieler eine Zeile (Name
// editierbar). Mannschaft als Fußzeile: je Bahn der Mannschafts-Durchschnitt, rechts die Summen.
// Bei `mirror` (gegenüberstehendes Team) werden die Spalten-Blöcke gespiegelt (Zahlen zur Mitte) —
// der Bahn-Block bleibt dabei ein zusammenhängender Segment und damit auf beiden Seiten aufsteigend.
function ergebnisTabelle(m, rows, st, ewpSum, teamLanes, laneOf, mirror) {
  // Bahn-Spalten = sortierte Vereinigung aller im Team gespielten Bahnen.
  const bahnSet = new Set();
  rows.forEach((r) => ((r.p && r.p.saetze) || []).forEach((s) => { if (s.bahn != null) bahnSet.add(s.bahn); }));
  const bahnen = [...bahnSet].sort((a, b) => a - b);
  // Die Bahn-Zellen als EIN Segment führen → beim Spiegeln bleibt ihre Reihenfolge aufsteigend.
  const ord = (cells) => (mirror ? cells.slice().reverse() : cells).join('');
  const bahnBlock = (mk) => bahnen.map(mk).join('');

  // Drei gleich breite Blöcke: (Nr + Name) | (W + Bahnen) | (Volle … EWP). Spaltenbreiten fix
  // über den Kopf (table-layout: fixed); reisen beim Spiegeln mit der jeweiligen Spalte mit.
  const T = 100 / 3;
  const nB = Math.max(1, bahnen.length);
  const wPos = 6;
  const wName = (T - wPos).toFixed(2);
  const wWurf = 12;
  const wBahn = ((T - wWurf) / nB).toFixed(2);
  const wNum = (T / 4).toFixed(2);

  const headCells = [
    `<th class="wk-c-pos" style="width:${wPos}%"></th>`,
    `<th class="wk-c-name" style="width:${wName}%"></th>`,
    `<th class="wk-c-wurf" style="width:${wWurf}%">W</th>`,
    bahnBlock((b) => `<th class="wk-c-bahn" style="width:${wBahn}%" title="Bahn ${b}">${b}</th>`),
    `<th class="wk-c-num" style="width:${wNum}%">Volle</th>`,
    `<th class="wk-c-num" style="width:${wNum}%">Abr.</th>`,
    `<th class="wk-c-num wk-c-ges" style="width:${wNum}%">Ges.</th>`,
    `<th class="wk-c-num wk-c-ewp" style="width:${wNum}%">EWP</th>`,
  ];

  const volleSum = rows.reduce((s, r) => s + (r.p ? (r.p.gesamt || 0) - (r.p.abraeum || 0) : 0), 0);
  const abrSum = rows.reduce((s, r) => s + (r.p ? (r.p.abraeum || 0) : 0), 0);

  const bodyRows = rows.map((r) => {
    const p = r.p;
    const played = !!(p && (p.gesamt || 0) > 0);
    const nameCell = `<td class="wk-c-name"><input class="wk-name roster-name" data-team="${esc(m.id)}" data-pos="${r.pos}" type="text" placeholder="${esc(m.name)} ${r.pos}" value="${esc((p && p.name) || '')}" /></td>`;
    // W-Spalte: hat der Spieler begonnen → seine bisherige Wurfanzahl; sonst die (noch änderbare)
    // Startbahn zur Auswahl.
    const wurfCell = played
      ? `<td class="wk-c-wurf">${nz(p.wurfCount)}</td>`
      : `<td class="wk-c-wurf">${startbahnCtrl(m, r.pos, teamLanes, laneOf)}</td>`;
    const bahnCells = bahnBlock((b) => `<td class="wk-c-bahn">${played ? nz(holzAufBahn(p, b)) : ''}</td>`);
    const volle = played ? (p.gesamt || 0) - (p.abraeum || 0) : null;
    const cells = [
      `<td class="wk-c-pos">${r.pos}</td>`,
      nameCell,
      wurfCell,
      bahnCells,
      `<td class="wk-c-num">${nz(volle)}</td>`,
      `<td class="wk-c-num">${played ? nz(p.abraeum) : ''}</td>`,
      `<td class="wk-c-num wk-c-ges">${played ? nz(p.gesamt) : ''}</td>`,
      `<td class="wk-c-num wk-c-ewp">${played ? nz(p.ewp) : ''}</td>`,
    ];
    return `<tr>${ord(cells)}</tr>`;
  });

  const footCells = [
    '<td class="wk-c-pos"></td>',
    '<td class="wk-c-name">Ø Mannschaft</td>',
    '<td class="wk-c-wurf"></td>',
    // Je Bahn der Durchschnitt der Mannschaft — nur über die tatsächlich gespielten Ergebnisse
    // (Holz > 0); noch nicht gespielte Bahnen zählen nicht in den Nenner.
    bahnBlock((b) => {
      let sum = 0; let cnt = 0;
      rows.forEach((r) => { const h = holzAufBahn(r.p, b); if (h) { sum += h; cnt += 1; } });
      return `<td class="wk-c-bahn">${cnt ? nz(Math.round(sum / cnt)) : ''}</td>`;
    }),
    `<td class="wk-c-num">${nz(volleSum)}</td>`,
    `<td class="wk-c-num">${nz(abrSum)}</td>`,
    `<td class="wk-c-num wk-c-ges">${nz(st.gesamt)}</td>`,
    `<td class="wk-c-num wk-c-ewp">${nz(ewpSum)}</td>`,
  ];

  return `
    <div class="wk-tbl-wrap">
      <table class="wk-tbl${mirror ? ' wk-mirror' : ''}">
        <thead><tr>${ord(headCells)}</tr></thead>
        <tbody>${bodyRows.join('')}</tbody>
        <tfoot><tr class="wk-tbl-sum">${ord(footCells)}</tr></tfoot>
      </table>
    </div>`;
}

// Aufstellung (reines Setup, noch keine Ergebnisse im Team): je Position ein Namensfeld und –
// innerhalb der Team-Bahnen – die Startbahn. Bei `mirror` liegen die Namen außen (Zahlen/Bahn
// zur Mitte). Namen und Startbahn werden direkt in die Durchgang-Spiele geschrieben (siehe wire()).
function aufstellungListe(m, rows, teamLanes, nameOf, laneOf, mirror) {
  const lis = rows.map((r) => {
    const val = nameOf[`${m.id}|${r.pos}`] || '';
    return `
      <div class="wk-lu-row${mirror ? ' is-mirror' : ''}">
        <span class="wk-c-pos">${r.pos}</span>
        <input class="wk-name roster-name" data-team="${esc(m.id)}" data-pos="${r.pos}" type="text" placeholder="${esc(m.name)} ${r.pos}" value="${esc(val)}" />
        ${startbahnCtrl(m, r.pos, teamLanes, laneOf)}
      </div>`;
  }).join('');
  return `<div class="wk-lineup">${lis}</div>`;
}

// Overlay-URL des Wettkampfs (Hash-Route + Beitritts-Code) — von einer OBS-Browser-Quelle
// eingebunden. Braucht einen geteilten Wettkampf (Code), da das Overlay read-only per Code liest.
function overlayUrl(wettkampf) {
  const base = location.origin + location.pathname;
  return `${base}#/overlay?code=${encodeURIComponent(wettkampf.beitrittsCode || '')}`;
}

// Bilddatei → verkleinerte Data-URL (PNG, längste Kante ≤ MAX). Klein genug, um im
// Wettkampf-config_json mitzureisen (kein Storage-Bucket nötig).
function fileToLogo(file, MAX = 256) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, MAX / Math.max(img.width, img.height));
      const w = Math.round(img.width * scale);
      const h = Math.round(img.height * scale);
      const cv = document.createElement('canvas');
      cv.width = w; cv.height = h;
      cv.getContext('2d').drawImage(img, 0, 0, w, h);
      resolve(cv.toDataURL('image/png'));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Bild konnte nicht geladen werden')); };
    img.src = url;
  });
}

// Overlay-Sektion: Team-Logos hochladen + Overlay-URL für OBS (nur wenn geteilt).
function overlaySection(wettkampf) {
  const teams = (wettkampf.mannschaften || []).slice(0, 2);
  const accentOf = (m) => (/^#[0-9a-fA-F]{6}$/.test(m.accent || '') ? m.accent : '#f5a623');
  const logos = teams.map((m) => `
    <div class="ov-logo-field">
      <div class="ov-logo-prev${m.logoBg === 'light' ? ' is-light' : ''}">${m.logo ? `<img src="${esc(m.logo)}" alt="">` : '<span>🎳</span>'}</div>
      <div class="ov-logo-meta">
        <span class="erf-setting-label">${esc(m.name)}</span>
        <label class="btn-mini ov-logo-btn">${m.logo ? 'Logo ändern' : 'Logo wählen'}
          <input type="file" accept="image/*" hidden data-logo="${esc(m.id)}">
        </label>
        ${m.logo ? `<button type="button" class="link-btn" data-logo-del="${esc(m.id)}">entfernen</button>` : ''}
        <label class="ov-opt">Akzentfarbe
          <input type="color" class="ov-accent-input" value="${accentOf(m)}" data-accent="${esc(m.id)}">
        </label>
        <label class="ov-opt">Logo-Hintergrund
          <select class="ov-logobg-input" data-logobg="${esc(m.id)}">
            <option value="dark"${m.logoBg === 'light' ? '' : ' selected'}>Dunkel</option>
            <option value="light"${m.logoBg === 'light' ? ' selected' : ''}>Hell</option>
          </select>
        </label>
      </div>
    </div>`).join('');

  const linked = !!(wettkampf.linked && wettkampf.beitrittsCode);
  const urlBox = linked
    ? `<div class="ov-url-row">
         <input class="ov-url-input" type="text" readonly value="${esc(overlayUrl(wettkampf))}" data-overlay-url aria-label="Overlay-URL">
         <button type="button" class="btn-mini" data-action="copy-overlay">Kopieren</button>
         <a class="btn-mini" href="${esc(overlayUrl(wettkampf))}" target="_blank" rel="noopener">Öffnen</a>
       </div>
       <p class="field-hint">In OBS als <b>Browser-Quelle</b> (1920×1080) mit dieser URL einbinden — transparenter Hintergrund, zeigt die Ergebnisse live.</p>`
    : `<p class="field-hint">Zuerst oben <b>Wettkampf teilen</b> — dann erscheint hier die Overlay-URL für OBS.</p>`;

  return `
    <section class="field kz-overlay">
      <label class="field-label">OBS-Livestream-Overlay</label>
      <div class="ov-logo-fields">${logos || '<p class="field-hint">Keine Mannschaften.</p>'}</div>
      ${urlBox}
      <p class="join-msg" data-overlay-msg role="status"></p>
    </section>`;
}

function mehrgeraeteSection(wettkampf, syncMsg) {
  const linked = !!(wettkampf.linked && wettkampf.remoteId);
  const code = wettkampf.beitrittsCode || '';
  const body = linked
    ? `<div class="field-row">
         <span class="erf-setting-label">Beitritts-Code</span>
         <span class="erf-share-code">${esc(code || '—')}</span>
       </div>
       <p class="field-hint">Andere Geräte treten unter „Spiel beitreten" mit diesem Code bei. Durchgänge werden parallel erfasst, die Rangliste läuft live zusammen.</p>`
    : `<button type="button" class="erf-btn done" data-action="share">🔗 Wettkampf teilen</button>
       <p class="field-hint">Teilt den Wettkampf geräteübergreifend — andere erfassen Durchgänge parallel mit. Konto nötig.</p>`;
  return `
    <section class="field">
      <label class="field-label">Mehrgeräte</label>
      ${body}
      <p class="join-msg" data-sync-msg role="status">${esc(syncMsg || '')}</p>
      ${brueckeRow(wettkampf)}
      <div data-sw-konflikte></div>
    </section>`;
}

// Zeile für das Sportwinner-Rückschreiben — nur bei aus Sportwinner importierten Wettkämpfen.
// Auf dem Vereins-PC (App per Brücke mit `?push=…` geöffnet) ist das Rückschreiben aktiv;
// auf anderen Geräten wird nur der Hinweis gezeigt, dass es der Vereins-PC übernimmt.
function brueckeRow(wettkampf) {
  if (!wettkampf.sportwinner) return '';
  const aktiv = !!getBruecke();
  return `
    <div class="field-row field-row--wrap">
      <span class="erf-setting-label">🎳 Sportwinner-Rückschreiben</span>
      ${aktiv
        ? '<span class="sw-status is-checking" data-bruecke-status>Prüfe …</span>'
        : '<span class="erf-share-code">auf dem Vereins-PC</span>'}
    </div>
    <p class="field-hint" data-bruecke-msg role="status">${aktiv
      ? 'Status wird geprüft …'
      : 'Die Übertragung nach Sportwinner läuft über den Vereins-PC, der die Brücke ausführt.'}</p>`;
}

function template(wettkampf, games, stats, wertung, syncMsg, kz) {
  const metaLine = [
    wettkampf.datum ? new Date(wettkampf.datum).toLocaleDateString('de-DE') : '',
    wettkampf.anlageName || '',
    `${(wettkampf.mannschaften || []).length} Mannschaften`,
  ].filter(Boolean).join(' · ');

  // Durchgänge als Statuskarten: Nummer, abgeleiteter Status (Vorbereitung/Läuft/Offen/Fertig)
  // und die passende Aktion — die Spielernamen stehen in der Aufstellung.
  const durchgaenge = durchgangStatusList(wettkampf, games).map((d) => {
    const status = d.status;
    const cta = STATUS_CTA[status] || 'Erfassen';
    return `
      <div class="wk-dg is-${status}">
        <button type="button" class="wk-dg-main" data-open="${esc(d.gameId)}">
          <span class="wk-dg-top">
            <span class="wk-dg-nr" aria-hidden="true">${d.nr}</span>
            <span class="wk-dg-label">Durchgang ${d.nr}</span>
          </span>
          <span class="wk-dg-bot">
            <span class="status-badge is-${status}">${STATUS_LBL[status] || status}</span>
            <span class="wk-dg-cta">${cta}</span>
          </span>
        </button>
        <button type="button" class="wk-dg-del" data-del-durchgang="${esc(d.gameId)}" data-nr="${d.nr}" aria-label="Durchgang löschen">🗑</button>
      </div>`;
  }).join('');

  const durchgaengeSection = durchgaenge || '<p class="field-hint">Noch keine Durchgänge.</p>';

  const meta = `<p class="stats-sub">${esc(metaLine)}</p>`;
  const secMehr = mehrgeraeteSection(wettkampf, syncMsg);
  const secDurch = `
      <section class="field kz-durchgaenge">
        <div class="field-row">
          <label class="field-label">Durchgänge</label>
          <button type="button" class="btn-mini" data-action="add-durchgang">+ Durchgang</button>
        </div>
        <div class="wk-dg-list">${durchgaengeSection}</div>
      </section>`;
  const secTeam = teamUebersichtSection(wettkampf, games, stats, wertung, kz);

  // Kontrollzentrum (Vereins-PC): oben über die ganze Breite die Mannschafts-Übersicht — bei zwei
  // Mannschaften stehen sie sich gegenüber (Zahlen zur Mitte). Darunter der Arbeitsbereich: links
  // die kompakten Durchgänge, rechts Mehrgeräte/Sportwinner und das OBS-Overlay. Die Spalten-Wrapper
  // lösen sich auf schmalen Schirmen per CSS (display:contents) auf. Das OBS-Overlay ist eine
  // Desktop-/Vereins-PC-Funktion (Livestream läuft dort) — daher nur im Kontrollzentrum-Layout.
  const secOverlay = kz ? overlaySection(wettkampf) : '';
  const inner = kz
    ? `${meta}
       ${secTeam}
       <div class="kz-main">${secDurch}</div>
       <div class="kz-side">${secMehr}${secOverlay}</div>`
    : `${meta}${secTeam}${secDurch}${secMehr}`;

  return `
    <header class="page-header">
      <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
      <h1 class="page-title">${esc(wettkampf.name || 'Wettkampf')}</h1>
    </header>

    <div class="setup">
      ${inner}
    </div>`;
}
