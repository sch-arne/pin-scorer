// Gemeinsame Konstanten für die Sportkegeln-Programme (Training-Setup und
// Wettkampf-Setup teilen sie, damit Bahnart-Presets & Co. nicht auseinanderlaufen).

// Modi je Teilsatz.
export const MODI = [
  { key: 'volle', label: 'Volle' },
  { key: 'abraeumen', label: 'Abräumen' },
  { key: 'kranz-abraeumen', label: 'Kranz-Abräumen' },
];

// Ein ganzer Satz als EIN Teilsatz, dessen Aufteilung unbekannt ist.
//
// Nur für den Web-Import (logic/sw-web-import.js): der Ergebnisdienst nennt bei Schere und
// Classic ausschließlich das Satz-Holz, nie die Trennung in Volle und Abräumen. Statt sie zu
// schätzen, bekommt so ein Satz genau einen Teilsatz über alle Würfe — das Satzergebnis stimmt
// exakt, und eine Auswertung nach Volle/Abräumen gibt es für dieses Spiel schlicht nicht.
// Bewusst NICHT in MODI: von Hand soll niemand ein solches Programm anlegen können.
export const MODUS_GESAMT = 'gesamt';

// Vorgeschlagene Bahnzahlen (Schnellauswahl-Chips).
export const BAHNEN_OPTS = [1, 2, 4, 6, 8, 10, 12];

// Bahnwechsel-Modi (Reihum / Duo / fest).
export const BAHNWECHSEL = [
  { key: 'plus1', label: 'Reihum (+1)' },
  { key: 'minus1', label: 'Reihum (−1)' },
  { key: 'classic', label: 'Classic-Duo' },
  { key: 'bohle', label: 'Bohle-Duo' },
  { key: 'fest', label: 'Feste Bahn' },
];

// Bahnart-Presets (inkl. Standard-Bahnwechsel je Disziplin).
export const PRESETS = {
  bohle: { label: 'Bohle', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'volle'], bahnen: 4, bahnwechsel: 'bohle' },
  schere: { label: 'Schere', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'kranz-abraeumen'], bahnen: 4, bahnwechsel: 'plus1' },
  classic: { label: 'Classic', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'abraeumen'], bahnen: 4, bahnwechsel: 'classic' },
};

// Bahnart-Kürzel für Anzeige (physische Bahnart einer Anlage).
export const ART_LABEL = { classic: 'Classic', bohle: 'Bohle', schere: 'Schere' };
