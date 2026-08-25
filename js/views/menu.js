// Hauptmenue — Startbildschirm mit Kacheln. "Spieler" und "Anlagen" brauchen eine
// Verbindung/Account; die Views laden ihr Backend lazy und degradieren offline sauber.

const TILES = [
  { label: 'Neues Spiel', desc: 'Ein Spiel starten und Würfe erfassen', icon: '🎳', route: '/neues-spiel' },
  { label: 'Spiel beitreten', desc: 'Mit Code einem geteilten Spiel beitreten', icon: '🔗', route: '/beitreten' },
  { label: 'Statistiken', desc: 'Ergebnisse und Auswertungen', icon: '📊', route: '/statistiken' },
  { label: 'Spieler', desc: 'Account & Profil (geräteübergreifend)', icon: '👤', route: '/spieler' },
  { label: 'Anlagen', desc: 'Kegelanlagen anlegen & verwalten', icon: '📍', route: '/anlagen' },
];

export function menuView() {
  const root = document.createElement('div');
  root.className = 'view view-menu';

  const header = document.createElement('header');
  header.className = 'app-header';
  header.innerHTML = `
    <h1 class="brand">Pin-Scorer</h1>
    <p class="tagline">Deine Kegel-Würfe im Blick</p>
  `;
  root.appendChild(header);

  const grid = document.createElement('nav');
  grid.className = 'tile-grid';

  for (const t of TILES) {
    const tile = document.createElement(t.disabled ? 'div' : 'a');
    tile.className = 'tile' + (t.disabled ? ' is-disabled' : '');
    if (t.disabled) {
      tile.setAttribute('aria-disabled', 'true');
    } else {
      tile.href = '#' + t.route;
    }
    tile.innerHTML = `
      <span class="tile-icon" aria-hidden="true">${t.icon}</span>
      <span class="tile-label">${t.label}</span>
      <span class="tile-desc">${t.desc}</span>
    `;
    grid.appendChild(tile);
  }

  root.appendChild(grid);
  return root;
}
