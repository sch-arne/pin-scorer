// "Neues Spiel" — laufende Spiele/Wettkämpfe fortsetzen und einen neuen Spiel-Typ starten.
// Die Spiel-Typen kommen aus der zentralen Registry (logic/spielarten.js).

import { navigate } from '../router.js';
import {
  getResumableGames, setActiveGame,
  getResumableWettkaempfe, setActiveWettkampf,
} from '../store.js';
import { SPIELARTEN, labelOf, iconOf } from '../logic/spielarten.js';
import { spielLoeschen, wettkampfLoeschen } from './loeschen.js';
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
    // Nur NOCH NICHT fertige Wettkämpfe: „Fortsetzen" ist die Arbeitsliste. Ist der letzte
    // Durchgang durchgeworfen, wandert der Wettkampf in die Historie (Statistiken) und
    // verschwindet hier — genau wie ein beendetes Einzelspiel. Der Status wird dabei aus den
    // Durchgängen abgeleitet (store.wettkampfStatus), nicht aus einem evtl. veralteten Feld.
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
        if (await spielLoeschen(b.dataset.del)) render();
      }));
    root.querySelectorAll('[data-del-wk]').forEach((b) =>
      b.addEventListener('click', async () => {
        if (await wettkampfLoeschen(b.dataset.delWk)) render();
      }));
  }

  render();
  return root;
}
