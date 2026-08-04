// "Neues Spiel" — laufende Spiele fortsetzen und einen neuen Spiel-Typ starten.
// Aktuell ein Typ: Sportkegeln-Training. Weitere Spiele lassen sich hier ergaenzen.

import { navigate } from '../router.js';
import { getResumableGames, setActiveGame, deleteGame } from '../store.js';
import { esc } from '../util.js';

const GAMES = [
  {
    key: 'sportkegler-wk',
    label: 'Sportkegeln-Training',
    desc: 'Wettkampf — Bohle · Schere · Classic',
    icon: '🎳',
    route: '/setup/sportkegler-wk',
  },
];

// Anzeigename je Spiel-Typ (fuer die Fortsetzen-Liste).
const SPIEL_LABEL = { 'sportkegler-wk': 'Sportkegeln-Training' };

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
    const resumable = getResumableGames();

    const resumeSection = resumable.length ? `
      <section class="resume">
        <h2 class="section-label">Fortsetzen</h2>
        <div class="game-list">
          ${resumable.map((g) => {
            const label = SPIEL_LABEL[g.spiel] || g.spiel;
            const statusLabel = g.status === 'laufend' ? 'Läuft' : 'Setup';
            const spieler = g.config?.spielerListe?.length || g.config?.spieler || 0;
            const meta = [formatDate(g.updatedAt || g.createdAt), spieler ? `${spieler} Spieler` : '']
              .filter(Boolean).join(' · ');
            return `
              <div class="game-card resume-card">
                <button type="button" class="resume-main" data-resume="${esc(g.id)}">
                  <span class="game-icon" aria-hidden="true">🎳</span>
                  <span class="game-text">
                    <span class="game-label">${esc(label)}</span>
                    <span class="game-desc">${esc(meta)}</span>
                  </span>
                  <span class="status-badge is-${g.status}">${statusLabel}</span>
                </button>
                <button type="button" class="resume-del" data-del="${esc(g.id)}" aria-label="Spiel löschen">🗑</button>
              </div>`;
          }).join('')}
        </div>
      </section>` : '';

    const startSection = `
      <section class="start-new">
        ${resumable.length ? '<h2 class="section-label">Neu starten</h2>' : ''}
        <div class="game-list">
          ${GAMES.map((g) => `
            <a class="game-card" href="#${g.route}">
              <span class="game-icon" aria-hidden="true">${g.icon}</span>
              <span class="game-text">
                <span class="game-label">${g.label}</span>
                <span class="game-desc">${g.desc}</span>
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
    root.querySelectorAll('[data-del]').forEach((b) =>
      b.addEventListener('click', () => {
        if (!window.confirm('Dieses Spiel wirklich löschen?')) return;
        deleteGame(b.dataset.del);
        render();
      }));
  }

  render();
  return root;
}
