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
  },
  {
    key: 'sportkegler-wettkampf',
    label: 'Sportkegeln-Wettkampf',
    desc: 'Mehrere Durchgänge · Einzel- & Mannschafts-Rangliste',
    icon: '🏆',
    route: '/setup/wettkampf',
  },
];

const BY_KEY = Object.fromEntries(SPIELARTEN.map((s) => [s.key, s]));

export function spielart(key) { return BY_KEY[key] || null; }
export function labelOf(key) { return (BY_KEY[key] && BY_KEY[key].label) || key; }
export function iconOf(key) { return (BY_KEY[key] && BY_KEY[key].icon) || '🎳'; }
