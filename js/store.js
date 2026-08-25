// Datenschicht-Abstraktion.
//
// Die Views reden ausschliesslich ueber dieses Modul mit dem Speicher — nie direkt
// mit localStorage. Dadurch kann spaeter eine Server-/Sync-Schicht hier andocken
// (Spieleraccounts, Anlagen-Verknuepfung), ohne die Views anzufassen.
//
// Aktuell: local-first ueber localStorage. Ein Spiel bleibt lokal, solange es mit
// keiner Anlage verknuepft ist.

import { DEFAULT_STANDARDBILDER } from './data/standardbilder-default.js';

const KEY_GAMES = 'pins-scorer:games';
const KEY_ACTIVE = 'pins-scorer:active-game';
const KEY_STANDARDBILDER = 'pins-scorer:standardbilder';
const KEY_SETTINGS = 'pins-scorer:settings';
const KEY_WETTKAEMPFE = 'pins-scorer:wettkaempfe';
const KEY_ACTIVE_WK = 'pins-scorer:active-wettkampf';

// App-Einstellungen: global, spieluebergreifend. Neue Optionen einfach hier als
// Default ergaenzen — getSettings mischt sie ueber gespeicherte Werte.
const DEFAULT_SETTINGS = {
  vorschlaege: true, // Schnellauswahl-Pop-up (Standard-Kegelbilder) nach Zahleneingabe zeigen?
};

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

// ── Wettkämpfe ──────────────────────────────────────────────────────────────
// Ein Wettkampf ist eine Klammer über mehrere Durchgänge (jeweils ein normales
// Spiel in KEY_GAMES, verknüpft über game.wettkampfId). Der Wettkampf selbst hält
// nur Stammdaten, Mannschaften, eine Setup-Vorlage und die Liste seiner Durchgänge.
export function getWettkaempfe() {
  return read(KEY_WETTKAEMPFE, []);
}

export function getWettkampf(id) {
  return getWettkaempfe().find((w) => w.id === id) || null;
}

// Durchgang-Spiele eines Wettkampfs (echte Spielobjekte aus KEY_GAMES).
export function getWettkampfGames(wettkampfId) {
  return getGames().filter((g) => g.wettkampfId === wettkampfId);
}

export function saveWettkampf(w) {
  w.updatedAt = new Date().toISOString();
  const list = getWettkaempfe();
  const idx = list.findIndex((x) => x.id === w.id);
  if (idx >= 0) list[idx] = w;
  else list.push(w);
  return write(KEY_WETTKAEMPFE, list) ? w : null;
}

// Wettkampf löschen — inklusive seiner Durchgang-Spiele (die nur im Wettkampf sinnvoll sind).
export function deleteWettkampf(id) {
  write(KEY_WETTKAEMPFE, getWettkaempfe().filter((w) => w.id !== id));
  write(KEY_GAMES, getGames().filter((g) => g.wettkampfId !== id));
  if (getActiveWettkampf() === id) write(KEY_ACTIVE_WK, null); // toten Zeiger nicht stehen lassen
}

// Fortsetzbare Wettkämpfe (Setup begonnen oder laufend), zuletzt bearbeitete zuerst.
export function getResumableWettkaempfe() {
  return getWettkaempfe()
    .filter((w) => w.status === 'setup' || w.status === 'laufend')
    .sort((a, b) => (b.updatedAt || b.createdAt || '').localeCompare(a.updatedAt || a.createdAt || ''));
}

export function setActiveWettkampf(id) {
  write(KEY_ACTIVE_WK, id);
}

export function getActiveWettkampf() {
  return read(KEY_ACTIVE_WK, null);
}

// Standard-Kegelbilder: globale, spielübergreifende Voreinstellung. Map von Holzzahl (1-8)
// auf eine Liste von Bildern; jedes Bild ist ein sortiertes Array der GEFALLENEN Kegel-Nummern
// (1-9). Wird beim Erfassen als Schnellauswahl-Pop-up nach dem Tippen einer Zahl angeboten
// und in den Einstellungen gepflegt. Absichtlich getrennt von den Spielen -> bleibt erhalten.
export function getStandardbilder() {
  // Erststart (Key wurde noch nie geschrieben): Werksvoreinstellung seeden und
  // persistieren. Ein absichtlich geleertes "{}" wurde geschrieben -> wird respektiert
  // und NICHT erneut geseedet.
  let present = true;
  try {
    present = localStorage.getItem(KEY_STANDARDBILDER) !== null;
  } catch {
    present = true; // kein Storage -> nicht seeden, nur Default in-memory liefern
  }
  if (!present) {
    write(KEY_STANDARDBILDER, DEFAULT_STANDARDBILDER);
    return DEFAULT_STANDARDBILDER;
  }
  const raw = read(KEY_STANDARDBILDER, {});
  return raw && typeof raw === 'object' ? raw : {};
}

export function saveStandardbilder(map) {
  return write(KEY_STANDARDBILDER, map);
}

// App-Einstellungen lesen (gespeicherte Werte ueber die Defaults gemischt, damit
// neu hinzugekommene Optionen automatisch ihren Default bekommen).
export function getSettings() {
  const raw = read(KEY_SETTINGS, {});
  return { ...DEFAULT_SETTINGS, ...(raw && typeof raw === 'object' ? raw : {}) };
}

// Einstellungen teilweise aktualisieren (Patch ueber den aktuellen Stand mergen).
export function saveSettings(patch) {
  return write(KEY_SETTINGS, { ...getSettings(), ...patch });
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

// Nur den Status eines Spiels setzen (z.B. 'beendet', sobald alle Spieler fertig sind, oder
// zurueck auf 'laufend', wenn ein Satz wieder geoeffnet wird). Liest das Spiel frisch aus dem
// Speicher (inkl. des zuletzt gespeicherten Erfassungsstands) -> ueberschreibt keine Wuerfe.
export function setGameStatus(gameId, status) {
  const game = getGame(gameId);
  if (!game) return null;
  game.status = status;
  return saveGame(game);
}
