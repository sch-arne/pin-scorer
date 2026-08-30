// Wettkampf-Hub — Übersicht eines Wettkampfs: die (aus dem Setup erzeugten) Durchgänge
// erfassen, die Aufstellung (Spielernamen je Mannschaft) füllen und die zusammengeführte
// Rangliste (Einzel + Mannschaft) sehen.

import { navigate } from '../router.js';
import {
  getActiveWettkampf, getWettkampf, getWettkampfGames, saveWettkampf,
  getGame, saveGame, saveErfassung, setActiveGame, deleteGame, setActiveWettkampf, deleteWettkampf,
} from '../store.js';
import { computeWettkampfStats, durchgangStatusList, wettkampfBaseStatus } from '../logic/wettkampf.js';
import { computeWertung, assignEwp } from '../logic/wettkampf-wertung.js';
import { buildSportwinnerPush } from '../logic/sportwinner-ergebnis.js';
import { adoptAufstellung } from '../logic/sportwinner-konflikte.js';
import { createKonfliktPanel } from './sportwinner-konflikt-panel.js';
import {
  getBruecke, pushErgebnis, holeStatus, holeSportwinnerLive, brueckeStatusInfo, brueckePushText,
} from '../backend/sw-bruecke.js';
import { lanePlan } from '../logic/bahnwechsel.js';
import { teamUebersichtSection } from './wettkampf-teams.js';
import { esc } from '../util.js';
import { revealCodeHtml, wireRevealCodes } from '../reveal-code.js';

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
  let zpollTimer = null;   // Zuschauer-Polling-Intervall (nur-lesen)
  let zpollSig = '';       // letzter Snapshot-Fingerabdruck (Flicker/Scroll-Reset vermeiden)

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
      // Die Übernahme ändert BEIDES: den Spielernamen im Durchgang (spiel.config) UND
      // Pass/extId in der Sportwinner-Zuordnung des Wettkampfs (wettkampf.config.sportwinner).
      // Beide müssen zum Server — sonst überschreibt der Realtime-Reload (pullWettkampf) die
      // Übernahme mit den alten Pässen aus config_json und die Abweichung taucht wieder auf.
      if (g2.remoteId && syncMod) syncMod.pushConfig(g2.remoteId, g2.config).catch(() => {});
      pushWettkampfConfigNow(w2);
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

  // Wettkampf-Status an die Durchgänge angleichen (Sicherheitsnetz, u. a. wenn ein beigetretenes
  // Gerät den letzten Durchgang beendet hat): sind alle Durchgänge beendet, gilt auch der
  // Wettkampf als beendet — sonst wieder 'laufend'. Lokal spiegeln und als Ersteller zum Server
  // pushen (pushWettkampfStatus ist laut RLS Ersteller-only; auf anderen Geräten still no-op,
  // der lokale Status stimmt dann trotzdem für die Anzeige).
  function reconcileWettkampfStatus(wettkampf, games) {
    const alleFertig = wettkampfBaseStatus(wettkampf, games) === 'beendet';
    let next = null;
    if (alleFertig && wettkampf.status !== 'beendet') next = 'beendet';
    else if (!alleFertig && wettkampf.status === 'beendet') next = 'laufend';
    if (!next) return;
    wettkampf.status = next;
    saveWettkampf(wettkampf);
    if (wettkampf.remoteId && syncMod) syncMod.pushWettkampfStatus(wettkampf.remoteId, next).catch(() => {});
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
    // Zuschauer-Modus: der Wettkampf wurde per Zuschauer-Code geöffnet (sync.zuschauerWettkampf).
    // Alles wird live gezeigt, aber keine Bearbeitung (kein Teilen, kein Durchgang +/−, keine
    // Aufstellungs-/Logo-Änderung); Durchgänge öffnen read-only. Aktualisiert per Polling.
    const zuschauer = !!wettkampf.zuschauer;
    if (!zuschauer) reconcileWettkampfStatus(wettkampf, games);
    root.classList.toggle('view-kontrollzentrum', kz);
    root.classList.toggle('is-zuschauer', zuschauer);
    root.innerHTML = template(wettkampf, games, stats, wertung, syncMsg, kz, zuschauer);
    wire(wettkampf, games, zuschauer);
    paintSw(); // gehaltenen Brücken-Status ins frisch gerenderte DOM malen
    konfliktPanel.paint(); // offene Konflikte ins frisch gerenderte DOM malen
    if (!zuschauer) pushToBruecke(wettkampf, games);
    scheduleFit(); // Zahlen in den Ergebnistabellen an ihre Spaltenbreite anpassen
  }

  // Zahlen in den Ergebnistabellen, die für ihre (fixe) Spaltenbreite zu breit sind, kleiner
  // setzen statt sie mit „…" abzuschneiden. Läuft nach jedem Render und bei Größenänderung —
  // gemessen wird erst im nächsten Frame, wenn die Tabelle im DOM hängt und ihre Breite kennt.
  let fitRaf = 0;
  function scheduleFit() {
    cancelAnimationFrame(fitRaf);
    fitRaf = requestAnimationFrame(fitTableNumbers);
  }
  function fitTableNumbers() {
    root.querySelectorAll('.wk-tbl td, .wk-tbl th').forEach((cell) => {
      cell.style.fontSize = ''; // erst zurücksetzen (Neu-Messung bei Resize)
      if (cell.querySelector('input, select')) return; // Eingabefelder nicht verkleinern
      const base = parseFloat(getComputedStyle(cell).fontSize);
      if (!base) return;
      let size = base;
      // Nur eine SANFTE Anpassung (bis 85 %) als Sicherheitsnetz für ungewöhnlich lange Werte —
      // die eigentliche Lesbarkeit sichert die Mindest-Spaltenbreite (min-width der Tabelle, siehe
      // ergebnisTabelle): reicht der Platz nicht, werden die Spalten breiter und die Tabelle scrollt,
      // statt die Zahlen klein zu schrumpfen.
      while (cell.scrollWidth > cell.clientWidth + 1 && size > base * 0.85) {
        size -= 0.5;
        cell.style.fontSize = `${size}px`;
      }
    });
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
    if (w && w.zuschauer) { initZuschauerPoll(); return; }
    if (!w || !w.linked || !w.remoteId) return;
    try {
      syncMod = await import('../backend/sync.js');
      await reconcileUnlinked(w);
      await reload();
      subscribeNow();
    } catch (e) { /* offline -> lokal weiterarbeiten */ }
  }

  // Zuschauer-Modus: statt Realtime (braucht Mitgliedschaft) den anonymen Wettkampf-Snapshot
  // pollen und lokal spiegeln. Nur neu rendern, wenn sich der Snapshot geändert hat — sonst
  // springt das Layout (Scroll) alle paar Sekunden.
  async function initZuschauerPoll() {
    const w0 = getWettkampf(getActiveWettkampf());
    if (!w0 || !w0.zuschauer || !w0.zuschauerCode) return;
    const code = w0.zuschauerCode;
    try { syncMod = await import('../backend/sync.js'); } catch (e) { return; }
    const poll = async () => {
      if (!root.isConnected) { teardown(); return; }
      try {
        const { wettkampf: fresh, games: freshGames } = await syncMod.zuschauerWettkampf(code);
        const sig = JSON.stringify({
          s: fresh.status,
          g: freshGames.map((g) => [g.id, g.status, g.erfassung && g.erfassung.bloecke]),
        });
        if (sig === zpollSig) return;
        zpollSig = sig;
        const keep = new Set(freshGames.map((g) => g.id));
        getWettkampfGames(fresh.id).forEach((g) => { if (!keep.has(g.id)) deleteGame(g.id); });
        freshGames.forEach((g) => saveGame(g));
        saveWettkampf(fresh);
        render();
      } catch (e) { /* offline -> letzten Stand stehen lassen */ }
    };
    await poll();
    zpollTimer = setInterval(poll, 2500);
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
    clearInterval(zpollTimer);
    clearTimeout(pushTimer);
    clearInterval(statusTimer);
    clearInterval(swLiveTimer);
    if (unsub) { try { unsub(); } catch (e) {} unsub = null; }
    cancelAnimationFrame(fitRaf);
    kzMedia.removeEventListener('change', render);
    window.removeEventListener('resize', scheduleFit);
    window.removeEventListener('hashchange', teardown);
  }

  function wire(wettkampf, games, zuschauer) {
    wireRevealCodes(root); // verdeckte Codes (Eingabe-Code) aufdeckbar machen
    // Durchgänge öffnen (read-only bei Zuschauer, da die geöffneten Spiele zuschauer:true tragen)
    // ist immer aktiv — auch im Zuschauer-Modus.
    root.querySelectorAll('[data-open]').forEach((b) =>
      b.addEventListener('click', () => { setActiveGame(b.dataset.open); navigate('/spiel-laufend'); }));
    // Zuschauer-Modus: keine Bearbeitungs-Handler binden; Aufstellungs-Felder sperren.
    if (zuschauer) {
      root.querySelectorAll('.roster-name, .roster-lane').forEach((el) => { el.disabled = true; });
      return;
    }
    const add = root.querySelector('[data-action="add-durchgang"]');
    if (add) add.addEventListener('click', () => navigate('/setup/wettkampf-durchgang'));
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
  window.addEventListener('resize', scheduleFit); // Zahlen bei Größenänderung neu einpassen
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

// Overlay-URL des Wettkampfs (Hash-Route + ZUSCHAUER-Code) — von einer OBS-Browser-Quelle
// eingebunden. Nutzt bewusst den read-only Zuschauer-Code (nicht den Eingabe-Code): das Overlay
// macht ohnehin keine Eingaben, und so gibt selbst eine geleakte OBS-URL kein Eingaberecht.
// Braucht einen geteilten Wettkampf (Code), da das Overlay read-only per Code liest.
function overlayUrl(wettkampf) {
  const base = location.origin + location.pathname;
  return `${base}#/overlay?code=${encodeURIComponent(wettkampf.zuschauerCode || '')}`;
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

  const linked = !!(wettkampf.linked && wettkampf.zuschauerCode);
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

// Ersetzt die Mehrgeräte-Sektion im Zuschauer-Modus: nur ein Hinweis, keine Codes/Teilen.
function zuschauerSection() {
  return `
    <section class="field">
      <label class="field-label">👁 Zuschauer-Modus</label>
      <p class="field-hint">Du verfolgst diesen Wettkampf über einen Zuschauer-Code und siehst den Stand live. Eingaben und Änderungen sind nicht möglich.</p>
    </section>`;
}

function mehrgeraeteSection(wettkampf, syncMsg) {
  const linked = !!(wettkampf.linked && wettkampf.remoteId);
  const code = wettkampf.beitrittsCode || '';
  const zcode = wettkampf.zuschauerCode || '';
  const body = linked
    ? `<div class="field-row">
         <span class="erf-setting-label">Eingabe-Code</span>
         ${revealCodeHtml(code)}
       </div>
       ${zcode ? `<div class="field-row">
         <span class="erf-setting-label">👁 Zuschauer-Code</span>
         <span class="erf-share-code">${esc(zcode)}</span>
       </div>` : ''}
       <p class="field-hint">Der <b>Eingabe-Code</b> ist zum Mit-Erfassen (Durchgänge parallel, Rangliste läuft live zusammen) — aus Schutz standardmäßig verdeckt, zum Ablesen antippen. Der <b>Zuschauer-Code</b> zeigt alles live, aber nur zum Ansehen. Beide unter „Spiel beitreten" eingeben.</p>`
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

function template(wettkampf, games, stats, wertung, syncMsg, kz, zuschauer) {
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
            <span class="wk-dg-cta">${zuschauer ? 'Ansehen' : cta}</span>
          </span>
        </button>
        ${zuschauer ? '' : `<button type="button" class="wk-dg-del" data-del-durchgang="${esc(d.gameId)}" data-nr="${d.nr}" aria-label="Durchgang löschen">🗑</button>`}
      </div>`;
  }).join('');

  const durchgaengeSection = durchgaenge || '<p class="field-hint">Noch keine Durchgänge.</p>';

  const secMehr = zuschauer ? zuschauerSection() : mehrgeraeteSection(wettkampf, syncMsg);
  const secDurch = `
      <section class="field kz-durchgaenge">
        <div class="field-row">
          <label class="field-label">Durchgänge</label>
          ${zuschauer ? '' : '<button type="button" class="btn-mini" data-action="add-durchgang">+ Durchgang</button>'}
        </div>
        <div class="wk-dg-list">${durchgaengeSection}</div>
      </section>`;
  const secTeam = teamUebersichtSection(wettkampf, games, stats, wertung, kz);

  // Kontrollzentrum (Vereins-PC): oben über die ganze Breite die Mannschafts-Übersicht — bei zwei
  // Mannschaften stehen sie sich gegenüber (Zahlen zur Mitte). Darunter der Arbeitsbereich: links
  // die kompakten Durchgänge, rechts Mehrgeräte/Sportwinner und das OBS-Overlay. Die Spalten-Wrapper
  // lösen sich auf schmalen Schirmen per CSS (display:contents) auf. Das OBS-Overlay ist eine
  // Desktop-/Vereins-PC-Funktion (Livestream läuft dort) — daher nur im Kontrollzentrum-Layout.
  const secOverlay = (kz && !zuschauer) ? overlaySection(wettkampf) : '';
  const inner = kz
    ? `${secTeam}
       <div class="kz-main">${secDurch}</div>
       <div class="kz-side">${secMehr}${secOverlay}</div>`
    : `${secTeam}${secDurch}${secMehr}`;

  return `
    <header class="page-header wk-hub-header">
      <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
      <div class="wk-hub-heading">
        <h1 class="page-title">${esc(wettkampf.name || 'Wettkampf')}</h1>
        ${metaLine ? `<p class="wk-hub-meta">${esc(metaLine)}</p>` : ''}
      </div>
    </header>

    <div class="setup">
      ${inner}
    </div>`;
}
