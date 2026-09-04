// Zentrale Spielart-Registry. Eine Quelle für die Spiel-Auswahl (neues-spiel.js),
// die Fortsetzen-Liste (Label + Icon) und spätere Erweiterungen. Neue Spiel-Typen
// hier ergänzen und ihre Route in app.js registrieren.

export const SPIELARTEN = [
  {
    key: 'sportkegler-wk',
    label: 'Sportkegeln-Training',
    desc: 'Einzel-Durchgang — Bohle · Schere · Classic',
    icon: '🎳',
    route: '/setup/sportkegler-wk',
    spielRoute: '/spiel-laufend',
  },
  {
    key: 'sportkegler-wettkampf',
    label: 'Sportkegeln-Wettkampf',
    desc: 'Mehrere Durchgänge · Einzel- & Mannschafts-Rangliste',
    icon: '🏆',
    route: '/setup/wettkampf',
    spielRoute: '/spiel-laufend',
  },
  {
    key: 'hausnummern',
    label: 'Hausnummern',
    desc: 'Vier Würfe ergeben eine Zahl — hoch oder niedrig',
    icon: '🏠',
    route: '/setup/hausnummern',
    spielRoute: '/hausnummern',
  },
];

const BY_KEY = Object.fromEntries(SPIELARTEN.map((s) => [s.key, s]));

export function spielart(key) { return BY_KEY[key] || null; }
export function labelOf(key) { return (BY_KEY[key] && BY_KEY[key].label) || key; }
export function iconOf(key) { return (BY_KEY[key] && BY_KEY[key].icon) || '🎳'; }

// Die Erfassungs-Route eines SPIELS (nicht der Setup-Weg): jede Spielart hat ihre eigene
// Oberfläche. Überall dort verwenden, wo ein beliebiges gespeichertes Spiel geöffnet wird
// (Fortsetzen-Liste, Statistik-Historie) — sonst landet ein Hausnummern-Spiel in der
// Sportkegeln-Erfassung. Unbekannte Spielarten fallen auf die Sportkegeln-Ansicht zurück.
export function spielRoute(game) {
  const key = typeof game === 'string' ? game : (game && game.spiel);
  return (BY_KEY[key] && BY_KEY[key].spielRoute) || '/spiel-laufend';
}
