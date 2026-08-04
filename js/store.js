// Datenschicht-Abstraktion.
//
// Die Views reden ausschliesslich ueber dieses Modul mit dem Speicher — nie direkt
// mit localStorage. Dadurch kann spaeter eine Server-/Sync-Schicht hier andocken
// (Spieleraccounts, Anlagen-Verknuepfung), ohne die Views anzufassen.
//
// Aktuell: local-first ueber localStorage. Ein Spiel bleibt lokal, solange es mit
// keiner Anlage verknuepft ist.

const KEY_GAMES = 'pins-scorer:games';
const KEY_ACTIVE = 'pins-scorer:active-game';

function read(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function write(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function getGames() {
  return read(KEY_GAMES, []);
}

export function getGame(id) {
  return getGames().find((g) => g.id === id) || null;
}

// Speichert ein Spiel und stempelt `updatedAt` (fuer "zuletzt gespielt"-Sortierung).
// Rueckgabe: das Spiel bei Erfolg, sonst `null` (z.B. localStorage voll) — damit der
// Aufrufer einen Fehlschlag bemerken und melden kann (statt stillem Datenverlust).
export function saveGame(game) {
  game.updatedAt = new Date().toISOString();
  const games = getGames();
  const idx = games.findIndex((g) => g.id === game.id);
  if (idx >= 0) games[idx] = game;
  else games.push(game);
  return write(KEY_GAMES, games) ? game : null;
}

export function deleteGame(id) {
  write(KEY_GAMES, getGames().filter((g) => g.id !== id));
  if (getActiveGame() === id) write(KEY_ACTIVE, null); // toten Zeiger nicht stehen lassen
}

// Fortsetzbare Spiele (Setup begonnen oder laufend), zuletzt gespielte zuerst.
export function getResumableGames() {
  return getGames()
    .filter((g) => g.status === 'setup' || g.status === 'laufend')
    .sort((a, b) => (b.updatedAt || b.createdAt || '').localeCompare(a.updatedAt || a.createdAt || ''));
}

// Zeiger auf das aktuell offene Spiel (bis Param-Routing existiert).
export function setActiveGame(id) {
  write(KEY_ACTIVE, id);
}

export function getActiveGame() {
  return read(KEY_ACTIVE, null);
}

// Erfassungsstand (Wuerfe) eines Spiels ersetzen. Muss die ganze Struktur
// speichern, damit ein Reload den Stand wiederherstellt.
export function saveErfassung(gameId, erfassung) {
  const game = getGame(gameId);
  if (!game) return null;
  game.erfassung = erfassung;
  if (game.status === 'setup') game.status = 'laufend';
  return saveGame(game);
}
