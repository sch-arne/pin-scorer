// Mitgelieferte Standard-Kegelbilder (Werksvoreinstellung).
//
// Datenmodell — bewusst identisch zu dem, was `store.getStandardbilder()` liefert,
// damit die Seed-Daten ohne Umbau direkt übernommen werden können:
//
//   { "<Holzzahl 1-8>": [ { slot: 1-9, pins: [<gefallene Kegel 1-9>] }, ... ] }
//
//   - Schlüssel  = getippte Holzzahl (= Anzahl gefallener Kegel des Bildes)
//   - pins       = die GEFALLENEN Kegel (aufsteigend). Das App-Datenmodell speichert
//                  gefallene, nicht stehende Kegel — die Vorlage wurde entsprechend
//                  von "stehend" umgerechnet (gefallen = alle 9 minus stehend).
//   - slot       = Platz im Nummernblock-Popup (1-9, wie die Zifferntasten liegen).
//
// Kegel-Nummerierung (Raute wie in der App):
//            9
//         7     8
//      4     5     6      (5 = König)
//         2     3
//            1
//
// Beim ersten Start wird dies in `pins-scorer:standardbilder` gespeichert und ist
// danach in den Einstellungen frei änder-/löschbar. Leert der Nutzer die Liste
// absichtlich, wird NICHT erneut geseedet (siehe store.getStandardbilder()).

export const DEFAULT_STANDARDBILDER = {
  // 1 Holz — Inversion von "8 Holz" (fallender Kegel = dort stehender)
  '1': [
    { slot: 1, pins: [2] },
    { slot: 2, pins: [1] },
    { slot: 3, pins: [3] },
    { slot: 4, pins: [4] },
    { slot: 5, pins: [5] },
    { slot: 6, pins: [6] },
    { slot: 7, pins: [7] },
    { slot: 8, pins: [9] },
    { slot: 9, pins: [8] },
  ],

  // 2 Holz — Inversion von "7 Holz" (gefallene = dort stehende)
  '2': [
    { slot: 1, pins: [2, 4] },
    { slot: 3, pins: [3, 6] },
    { slot: 4, pins: [4, 5] },
    { slot: 6, pins: [5, 6] },
    { slot: 7, pins: [5, 7] },
    { slot: 8, pins: [5, 9] },
    { slot: 9, pins: [5, 8] },
  ],

  // 3 Holz — Inversion von "6 Holz", mit den drei Ausnahmen (Platz 1, 5, 8)
  '3': [
    { slot: 1, pins: [1, 7, 8] }, // Ausnahme
    { slot: 3, pins: [3, 5, 6] },
    { slot: 4, pins: [2, 4, 7] },
    { slot: 5, pins: [1, 5, 9] }, // Ausnahme (sonst leer)
    { slot: 6, pins: [3, 6, 8] },
    { slot: 7, pins: [4, 5, 7] },
    { slot: 9, pins: [5, 6, 8] },
    // Platz 8 bleibt bewusst leer (Ausnahme)
  ],

  // 4 Holz
  '4': [
    { slot: 1, pins: [1, 2, 4, 8] },
    { slot: 2, pins: [1, 5, 7, 9] },
    { slot: 3, pins: [1, 3, 6, 7] },
    { slot: 4, pins: [2, 4, 5, 7] },
    { slot: 5, pins: [1, 5, 8, 9] },
    { slot: 6, pins: [3, 5, 6, 8] },
    { slot: 7, pins: [2, 4, 5, 8] },
    { slot: 8, pins: [1, 5, 7, 8] },
    { slot: 9, pins: [3, 5, 6, 7] },
  ],

  // 5 Holz
  '5': [
    { slot: 1, pins: [3, 5, 6, 7, 9] },
    { slot: 3, pins: [2, 4, 5, 8, 9] },
    { slot: 4, pins: [1, 3, 6, 8, 9] },
    { slot: 6, pins: [1, 2, 4, 7, 9] },
    { slot: 7, pins: [1, 3, 6, 7, 9] },
    { slot: 8, pins: [1, 5, 7, 8, 9] },
    { slot: 9, pins: [1, 2, 4, 8, 9] },
  ],

  // 6 Holz (3 stehen)
  '6': [
    { slot: 1, pins: [1, 3, 6, 7, 8, 9] },
    { slot: 3, pins: [1, 2, 4, 7, 8, 9] },
    { slot: 4, pins: [1, 3, 5, 6, 8, 9] },
    { slot: 6, pins: [1, 2, 4, 5, 7, 9] },
    { slot: 7, pins: [1, 2, 3, 6, 8, 9] },
    { slot: 9, pins: [1, 2, 3, 4, 7, 9] },
  ],

  // 7 Holz (2 stehen)
  '7': [
    { slot: 1, pins: [1, 3, 5, 6, 7, 8, 9] },
    { slot: 3, pins: [1, 2, 4, 5, 7, 8, 9] },
    { slot: 4, pins: [1, 2, 3, 6, 7, 8, 9] },
    { slot: 6, pins: [1, 2, 3, 4, 7, 8, 9] },
    { slot: 7, pins: [1, 2, 3, 4, 6, 8, 9] },
    { slot: 8, pins: [1, 2, 3, 4, 6, 7, 8] },
    { slot: 9, pins: [1, 2, 3, 4, 6, 7, 9] },
  ],

  // 8 Holz (1 steht)
  '8': [
    { slot: 1, pins: [1, 3, 4, 5, 6, 7, 8, 9] },
    { slot: 2, pins: [2, 3, 4, 5, 6, 7, 8, 9] },
    { slot: 3, pins: [1, 2, 4, 5, 6, 7, 8, 9] },
    { slot: 4, pins: [1, 2, 3, 5, 6, 7, 8, 9] },
    { slot: 5, pins: [1, 2, 3, 4, 6, 7, 8, 9] },
    { slot: 6, pins: [1, 2, 3, 4, 5, 7, 8, 9] },
    { slot: 7, pins: [1, 2, 3, 4, 5, 6, 8, 9] },
    { slot: 8, pins: [1, 2, 3, 4, 5, 6, 7, 8] },
    { slot: 9, pins: [1, 2, 3, 4, 5, 6, 7, 9] },
  ],
};
