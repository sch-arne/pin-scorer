// Platzhalter "Statistiken".
// Vorerst leer — zeigt erfasste Spiele/Auswertungen, sobald Spiele gespeichert werden.

import { getGames } from '../store.js';

export function statistikenView() {
  const root = document.createElement('div');
  root.className = 'view view-page';

  const hasGames = getGames().length > 0;

  root.innerHTML = `
    <header class="page-header">
      <a class="back-btn" href="#/menu" aria-label="Zurück zum Menü">←</a>
      <h1 class="page-title">Statistiken</h1>
    </header>
    <div class="placeholder">
      <p class="placeholder-icon" aria-hidden="true">📊</p>
      <p class="placeholder-text">${hasGames ? 'Auswertung folgt.' : 'Noch keine Daten.'}</p>
      <p class="placeholder-sub">Sobald du Spiele erfasst hast, erscheinen hier deine Statistiken.</p>
    </div>
  `;
  return root;
}
