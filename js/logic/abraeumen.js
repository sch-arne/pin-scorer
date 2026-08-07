// Reine Abräum-/Kranz-Logik der Wurferfassung.
//
// Beim Abräumen trifft jeder Wurf nur die zuvor stehengebliebenen Kegel; sind alle
// gefallen, wird wieder auf alle 9 gespielt. Kranz-Abräumen: der 5er (König) ist optional.
// Alle Funktionen hier sind rein (bekommen `blk`/`range`/State übergeben) und damit
// unabhängig vom View testbar.

export const ALL_PINS = [1, 2, 3, 4, 5, 6, 7, 8, 9];
export function fullPins() { return ALL_PINS.slice(); }
export function isAbraeumMode(modus) { return modus === 'abraeumen' || modus === 'kranz-abraeumen'; }
export function rangeOfThrow(ranges, idx) { return ranges.find((r) => idx >= r.start && idx < r.end) || null; }

// Standard-Kegelbelegung fuer eine Holzzahl: 0 -> keiner gefallen, 9 -> alle,
// dazwischen unbestimmt (null) -> der Nutzer waehlt in der Raute.
export function defaultKegel(pins) {
  if (pins <= 0) return [];
  if (pins >= 9) return [1, 2, 3, 4, 5, 6, 7, 8, 9];
  return null;
}

// Abräum-Lauf abgeräumt? Alle relevanten Kegel gefallen. Beim Kranz-Abräumen ist der
// 5er (König) optional: er MUSS nicht fallen. Abgeräumt also, wenn gar nichts mehr steht
// (count 0) oder — beim Kranz — nur noch der König (count 1 & König steht).
export function runCleared(state, modus) {
  if (state.count <= 0) return true;
  return modus === 'kranz-abraeumen' && state.koenig && state.count === 1;
}

// picked = wurden im aktuellen Lauf (seit dem letzten Reset) schon konkrete Kegel im
// Board ausgewählt? Solange nicht, gilt der König als stehend (Kranz-Langdruck möglich).
export function freshRun() { return { standing: fullPins(), count: 9, exact: true, koenig: true, picked: false }; }

// Ein Abräum-Wurf: aus dem Zustand VOR dem Wurf den Zustand danach ableiten und ein
// etwaiges Plausibilitätsproblem melden. Jeder Wurf fällt nur die zuvor stehenden Kegel;
// ist der Lauf abgeräumt (Kranz: bis auf den 5er), wird wieder auf alle 9 gespielt.
// `exact` ist false, sobald ein Teil-Abräumen ohne konkrete Kegel-Angabe die Restmenge
// unbekannt macht — dann stimmt nur noch `count`. `koenig` = steht der König (5) noch?
// `koenigFlag` (Kranz-Langdruck): der Wurf fällt nur Kranz-Kegel, König bleibt stehen.
// Fehler:  n > count            -> es fallen mehr Kegel als standen (unmöglich)
//          Kegel ∉ standing      -> ein gefallener Kegel stand gar nicht mehr (nur bei exact)
//          Langdruck n > Kranz   -> mehr Kegel als Kranz-Kegel standen
export function abraeumStep(state, n, fallen, koenigFlag, modus) {
  let { standing, count, exact, koenig, picked } = state;
  const kranz = modus === 'kranz-abraeumen';
  let error = null;
  if (n > count) error = `nur ${count} Kegel ${count === 1 ? 'stand' : 'standen'}`;

  if (Array.isArray(fallen)) {
    if (exact) {
      const bad = fallen.filter((p) => !standing.includes(p));
      if (bad.length && !error) error = `Kegel ${bad.join(', ')} ${bad.length === 1 ? 'stand' : 'standen'} nicht mehr`;
    }
    standing = standing.filter((p) => !fallen.includes(p));
    count = exact ? standing.length : Math.max(0, count - n);
    koenig = exact ? standing.includes(5) : (koenig && !fallen.includes(5));
    picked = true;                     // konkrete Kegel im Board gewählt
  } else if (kranz && koenigFlag) {    // Langdruck: n Kranz-Kegel gefallen, König bleibt stehen
    const kranzStand = count - (koenig ? 1 : 0);
    if (n > kranzStand && !error) error = `nur ${kranzStand} Kranz-Kegel ${kranzStand === 1 ? 'stand' : 'standen'}`;
    count = Math.max(1, count - n);    // König bleibt -> es steht immer mindestens 1
    koenig = true; exact = false;
  } else if (n >= count) {             // Anzahl unbekannt, aber alle Reststehenden gefallen
    standing = []; count = 0; koenig = false;
  } else {                             // Teil-Abräumen ohne Kegel-Angabe -> Menge unbekannt
    count -= n; exact = false;
    // Bei reiner Zahl-Eingabe ist unbekannt, WELCHER Kegel noch steht — nicht zwingend der
    // König (5). Deshalb konservativ: kein Kranz. Eine „8" aus dem vollen Bild bleibt damit
    // ein gewöhnlicher Wurf mit einem stehenden Restkegel; ein echter Kranz entsteht nur per
    // Langdruck (koenigFlag) oder über die konkrete Kegel-Auswahl im Brett (5 bleibt stehen).
    koenig = false;
  }

  const next = { standing, count, exact, koenig, picked };
  // Kranz: nur eine 8, die genau den König (5) als einzigen Kegel stehen lässt. Das reine
  // Wegräumen des letzten Nebenkegels (kleiner Wurf, König steht) ist kein Kranz.
  const istKranz = kranz && n === 8 && next.count === 1 && next.koenig;
  return { next: runCleared(next, modus) ? freshRun() : next, error, kranz: istKranz };
}

// Läuft den Abräum-Teilsatz durch. Rückgabe:
//   before[j]      = Zustand VOR (absolutem) Wurf-Index j (auch für den Index nach dem letzten Wurf)
//   error[j]       = Plausibilitätsproblem des Wurfs j (oder null)
//   koenigAfter[j] = steht der König NACH Wurf j? (nur Kranz relevant)
export function abraeumScan(blk, range) {
  const before = {}; const error = {}; const koenigAfter = {}; const kranzAt = {};
  let state = freshRun();
  const end = Math.min(range.end, blk.wuerfe.length);
  for (let j = range.start; j <= end; j++) {
    before[j] = state;
    if (j >= end) break;
    const koenigFlag = Array.isArray(blk.koenig) ? !!blk.koenig[j] : false;
    const r = abraeumStep(state, blk.wuerfe[j], blk.kegel[j], koenigFlag, range.modus);
    error[j] = r.error; koenigAfter[j] = r.next.koenig; kranzAt[j] = r.kranz; state = r.next;
  }
  return { before, error, koenigAfter, kranzAt, tail: state };
}

// Stehende Kegel VOR dem (absoluten) Wurf-Index k. Rückgabe {standing,count,exact,koenig}.
export function abraeumStateBefore(blk, range, k) {
  const { before, tail } = abraeumScan(blk, range);
  return before[k] !== undefined ? before[k] : tail;
}

// Kranz in der Volle: nur wenn eine 8 geworfen wurde UND im Kegelbrett genau der König (5)
// als einziger stehen bleibt (die 8 Nebenkegel gefallen). Ein bloß getippter Wert „8" ohne
// konkrete Kegel ist noch kein Kranz — erst die Kegel-Auswahl (5 steht) macht ihn dazu.
export function volleKranz(blk, k) {
  if (blk.wuerfe[k] !== 8) return false;
  const kg = blk.kegel[k];
  return Array.isArray(kg) && kg.length === 8 && !kg.includes(5);
}
