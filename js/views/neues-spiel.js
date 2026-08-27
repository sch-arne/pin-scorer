// "Neues Spiel" — laufende Spiele/Wettkämpfe fortsetzen und einen neuen Spiel-Typ starten.
// Die Spiel-Typen kommen aus der zentralen Registry (logic/spielarten.js).

import { navigate } from '../router.js';
import {
  getResumableGames, setActiveGame, deleteGame,
  getResumableWettkaempfe, setActiveWettkampf, deleteWettkampf,
} from '../store.js';
import { SPIELARTEN, labelOf, iconOf } from '../logic/spielarten.js';
import { vergissWettkampf } from '../backend/sw-bruecke.js';
import { esc } from '../util.js';

function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
}

export function neuesSpielView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  function render() {
    // Durchgänge eines Wettkampfs erscheinen NICHT als einzelne Spiele — sie werden über
    // den Wettkampf-Hub fortgesetzt. Stattdessen listen wir die Wettkämpfe selbst.
    const resumableGames = getResumableGames().filter((g) => !g.wettkampfId);
    const resumableWk = getResumableWettkaempfe();
    const resumable = [
      ...resumableWk.map((w) => ({ kind: 'wettkampf', obj: w })),
      ...resumableGames.map((g) => ({ kind: 'game', obj: g })),
    ].sort((a, b) => {
      const ta = a.obj.updatedAt || a.obj.createdAt || '';
      const tb = b.obj.updatedAt || b.obj.createdAt || '';
      return tb.localeCompare(ta);
    });

    const gameCard = (g) => {
      const statusLabel = g.status === 'laufend' ? 'Läuft' : 'Setup';
      const spieler = g.config?.spielerListe?.length || g.config?.spieler || 0;
      const meta = [formatDate(g.updatedAt || g.createdAt), spieler ? `${spieler} Spieler` : '']
        .filter(Boolean).join(' · ');
      return `
        <div class="game-card resume-card">
          <button type="button" class="resume-main" data-resume="${esc(g.id)}">
            <span class="game-icon" aria-hidden="true">${iconOf(g.spiel)}</span>
            <span class="game-text">
              <span class="game-label">${esc(labelOf(g.spiel))}</span>
              <span class="game-desc">${esc(meta)}</span>
            </span>
            <span class="status-badge is-${g.status}">${statusLabel}</span>
          </button>
          <button type="button" class="resume-del" data-del="${esc(g.id)}" aria-label="Spiel löschen">🗑</button>
        </div>`;
    };

    const wettkampfCard = (w) => {
      const statusLabel = w.status === 'laufend' ? 'Läuft' : 'Setup';
      const durchgaenge = w.durchgaenge?.length || 0;
      const meta = [formatDate(w.updatedAt || w.createdAt), esc(w.name || 'Wettkampf'),
        durchgaenge ? `${durchgaenge} Durchg.` : ''].filter(Boolean).join(' · ');
      return `
        <div class="game-card resume-card">
          <button type="button" class="resume-main" data-resume-wk="${esc(w.id)}">
            <span class="game-icon" aria-hidden="true">${iconOf('sportkegler-wettkampf')}</span>
            <span class="game-text">
              <span class="game-label">${esc(w.name || 'Sportkegeln-Wettkampf')}</span>
              <span class="game-desc">${meta}</span>
            </span>
            <span class="status-badge is-${w.status}">${statusLabel}</span>
          </button>
          <button type="button" class="resume-del" data-del-wk="${esc(w.id)}" aria-label="Wettkampf löschen">🗑</button>
        </div>`;
    };

    const resumeSection = resumable.length ? `
      <section class="resume">
        <h2 class="section-label">Fortsetzen</h2>
        <div class="game-list">
          ${resumable.map((r) => (r.kind === 'wettkampf' ? wettkampfCard(r.obj) : gameCard(r.obj))).join('')}
        </div>
      </section>` : '';

    const startSection = `
      <section class="start-new">
        ${resumable.length ? '<h2 class="section-label">Neu starten</h2>' : ''}
        <div class="game-list">
          ${SPIELARTEN.map((g) => `
            <a class="game-card" href="#${g.route}">
              <span class="game-icon" aria-hidden="true">${g.icon}</span>
              <span class="game-text">
                <span class="game-label">${esc(g.label)}</span>
                <span class="game-desc">${esc(g.desc)}</span>
              </span>
              <span class="game-chevron" aria-hidden="true">›</span>
            </a>`).join('')}
        </div>
      </section>`;

    root.innerHTML = `
      <header class="page-header">
        <a class="back-btn" href="#/menu" aria-label="Zurück zum Menü">←</a>
        <h1 class="page-title">Neues Spiel</h1>
      </header>
      ${resumeSection}
      ${startSection}`;

    wire();
  }

  function wire() {
    root.querySelectorAll('[data-resume]').forEach((b) =>
      b.addEventListener('click', () => {
        setActiveGame(b.dataset.resume);
        navigate('/spiel-laufend');
      }));
    root.querySelectorAll('[data-resume-wk]').forEach((b) =>
      b.addEventListener('click', () => {
        setActiveWettkampf(b.dataset.resumeWk);
        navigate('/wettkampf');
      }));
    root.querySelectorAll('[data-del]').forEach((b) =>
      b.addEventListener('click', async () => {
        const g = getResumableGames().find((x) => x.id === b.dataset.del);
        const linked = !!(g && g.linked && g.remoteId);
        const frage = linked
          ? 'Dieses Spiel hier entfernen und den Freigabe-Link deaktivieren? Die aufgezeichneten '
            + 'Daten bleiben erhalten, aber Beitreten ist danach nicht mehr möglich.'
          : 'Dieses Spiel wirklich löschen?';
        if (!window.confirm(frage)) return;
        if (linked && !(await cutRemote('cutGameLink', g.remoteId))) return;
        deleteGame(b.dataset.del);
        render();
      }));
    root.querySelectorAll('[data-del-wk]').forEach((b) =>
      b.addEventListener('click', async () => {
        const w = getResumableWettkaempfe().find((x) => x.id === b.dataset.delWk);
        const linked = !!(w && w.linked && w.remoteId);
        const frage = linked
          ? 'Diesen Wettkampf hier entfernen und den Freigabe-Link (inkl. OBS-Overlay) '
            + 'deaktivieren? Die aufgezeichneten Daten bleiben erhalten, aber Beitreten und '
            + 'Overlay funktionieren danach nicht mehr.'
          : 'Diesen Wettkampf mit allen Durchgängen wirklich löschen?';
        if (!window.confirm(frage)) return;
        if (linked && !(await cutRemote('cutWettkampfLink', w.remoteId))) return;
        // Kam der Wettkampf aus Sportwinner, die Brücke dieses Match vergessen lassen, damit sie
        // beim nächsten Öffnen nicht den (nun toten) Code wiederfindet. Nur wirksam, wenn die
        // Brücke in dieser Session bekannt ist (Vereins-PC); sonst still no-op.
        const swNr = w && w.sportwinner && w.sportwinner.spielNr;
        if (swNr != null || (w && w.beitrittsCode)) {
          vergissWettkampf({ code: w.beitrittsCode || '', spielNr: swNr ?? null,
            heim: w.mannschaften?.[0]?.name, gast: w.mannschaften?.[1]?.name });
        }
        deleteWettkampf(b.dataset.delWk);
        render();
      }));
  }

  // Remote-Link eines verknüpften Objekts kappen (Code entwerten + Mitgliedschaften lösen).
  // Gibt true bei Erfolg zurück; bei Fehler (z.B. offline) false + Hinweis, damit der Aufrufer
  // das lokale Objekt NICHT entfernt und es später erneut versucht werden kann.
  async function cutRemote(fn, remoteId) {
    try {
      const sync = await import('../backend/sync.js');
      await sync[fn](remoteId);
      return true;
    } catch (e) {
      window.alert('Der Freigabe-Link konnte nicht deaktiviert werden (keine Verbindung?). '
        + 'Bitte online erneut versuchen — es wurde nichts entfernt.');
      return false;
    }
  }

  render();
  return root;
}
