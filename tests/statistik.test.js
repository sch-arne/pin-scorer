import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computeGameStats } from '../js/logic/statistik.js';
import { teilsatzRanges } from '../js/logic/teilsaetze.js';

// Ein Satz-Block mit gegebenen Würfen (ein Teilsatz "volle", 3 Würfe pro Satz).
function blk(wuerfe, overrides = [null], done = true) {
  return { wuerfe, kegel: wuerfe.map(() => null), koenig: wuerfe.map(() => false), overrides, done };
}

// Config: 2 Spieler A/B, 2 Sätze, ein Teilsatz Volle à 3 Würfe.
const config = {
  spielerListe: [{ name: 'Anna' }, { name: 'Ben' }],
  saetze: 2,
  ersteBahn: 1,
  wuerfeProSatz: 3,
  teilsaetze: [{ modus: 'volle', wuerfe: 3 }],
};
const ranges = teilsatzRanges(config);

test('Gesamt, Bester, Schnitte je Spieler', () => {
  const bloecke = [
    [blk([9, 8, 7]), blk([6, 5, 4])], // Anna: 24 + 15 = 39
    [blk([9, 9, 9]), blk([0, 1, 2])], // Ben:  27 + 3  = 30
  ];
  const { players } = computeGameStats(config, bloecke, ranges);
  const [anna, ben] = players;

  assert.equal(anna.gesamt, 39);
  assert.equal(anna.bester, 24);
  assert.equal(anna.schnittSatz, 19.5); // 39 / 2
  assert.equal(anna.schnittWurf, 6.5);  // 39 / 6
  assert.equal(anna.wurfCount, 6);
  assert.equal(anna.neuner, 1);          // eine 9
  assert.equal(anna.fehl, 0);
  assert.equal(anna.kranz, 0);           // ohne Kranz-Abräumen keine Kränze

  assert.equal(ben.gesamt, 30);
  assert.equal(ben.bester, 27);
  assert.equal(ben.neuner, 3);           // drei 9er
  assert.equal(ben.fehl, 1);             // eine 0

  // Volle: jeder Wurf kommt aus vollem Bild -> vollChance = wurfCount, kein Abräumen.
  assert.equal(anna.vollChance, 6);
  assert.equal(anna.raeumer, 0);
  assert.equal(anna.neunerQuote, 1 / 6); // eine 9 von 6 Würfen aus vollem Bild
  assert.equal(ben.neunerQuote, 3 / 6);  // drei 9er von 6
});

test('Abräum-Tempo & Neuner-Quote am vollen Bild', () => {
  // Ein Teilsatz Abräumen à 3 Würfe, 1 Satz. Zwei Läufe:
  //   Lauf 1: 9 -> in 1 Wurf abgeräumt (9er-Räumer, aus vollem Bild)
  //   Lauf 2: 6 (Rest 3 stehen), dann 3 -> in 2 Würfen abgeräumt; der 6er kam aus vollem Bild
  const cfg = {
    spielerListe: [{ name: 'R' }], saetze: 1, ersteBahn: 1, wuerfeProSatz: 3,
    teilsaetze: [{ modus: 'abraeumen', wuerfe: 3 }],
  };
  const r = teilsatzRanges(cfg);
  const bloecke = [[
    {
      wuerfe: [9, 6, 3],
      kegel: [[1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 6, 7, 8], [4, 5, 9]],
      koenig: [false, false, false], overrides: [null], done: true,
    },
  ]];
  const p = computeGameStats(cfg, bloecke, r).players[0];
  assert.equal(p.raeumer, 2);            // zwei vollständige Räumer
  assert.equal(p.raeumSchnitt, 1.5);     // (1 + 2) Würfe / 2 Räumer
  // Aus vollem Bild geworfen: der 9er (Lauf 1) und der 6er (Beginn Lauf 2). Die 3 und die 0
  // kamen aus Restbildern -> keine Gelegenheit.
  assert.equal(p.vollChance, 2);
  assert.equal(p.neunerQuote, 0.5);      // ein 9er von zwei Würfen aus vollem Bild
});

test('wurfCount: manuelles Ergebnis (Override) zählt als voller Teilsatz', () => {
  // 2 Teilsätze à 2 Würfe; Satz 1 komplett geworfen, Satz 2 nur als Summen (Overrides) eingetragen.
  const cfg = { ...config, wuerfeProSatz: 4, teilsaetze: [{ modus: 'volle', wuerfe: 2 }, { modus: 'abraeumen', wuerfe: 2 }] };
  const r = teilsatzRanges(cfg);
  const bloecke = [[
    { wuerfe: [9, 8, 7, 6], kegel: [], koenig: [], overrides: [null, null], done: true }, // 4 echte Würfe
    { wuerfe: [], kegel: [], koenig: [], overrides: [15, 12], done: true },                // 0 echte, 2 Overrides
  ]];
  const { players } = computeGameStats({ ...cfg, spielerListe: [{ name: 'A' }], saetze: 2 }, bloecke, r);
  // Satz 1: 4 Würfe; Satz 2: 2 Teilsätze à Soll 2 = 4 -> gesamt 8.
  assert.equal(players[0].wurfCount, 8);
  assert.equal(players[0].gesamt, 30 + 27); // (9+8+7+6) + (15+12)
});

test('Kränze: Kranz-Abräumen (nur König 5 bleibt) und Volle-Kranz (8 lässt König)', () => {
  // Kranz-Abräumen: eine 8, die genau die 8 Nebenkegel fällt (König 5 steht) = Kranz.
  // Nach einem Kranz wird wieder aufs volle Bild gespielt -> zweiter Wurf gleich = zweiter Kranz.
  const kranzKegel = [1, 2, 3, 4, 6, 7, 8, 9];
  const cfgK = {
    spielerListe: [{ name: 'K' }], saetze: 1, ersteBahn: 1, wuerfeProSatz: 2,
    teilsaetze: [{ modus: 'kranz-abraeumen', wuerfe: 2 }],
  };
  const rK = teilsatzRanges(cfgK);
  const bloeckeK = [[
    { wuerfe: [8, 8], kegel: [kranzKegel, kranzKegel], koenig: [false, false], overrides: [null], done: true },
  ]];
  assert.equal(computeGameStats(cfgK, bloeckeK, rK).players[0].kranz, 2);

  // Volle: eine 8, deren Kegelbild genau den König (5) übrig lässt, zählt ebenfalls als Kranz;
  // eine 8 ohne passendes Kegelbild (null) dagegen nicht.
  const cfgV = { ...config, spielerListe: [{ name: 'V' }], saetze: 1, wuerfeProSatz: 3 };
  const bloeckeV = [[
    { wuerfe: [8, 8, 9], kegel: [kranzKegel, null, null], koenig: [false, false, false], overrides: [null], done: true },
  ]];
  assert.equal(computeGameStats(cfgV, bloeckeV, ranges).players[0].kranz, 1);
});

test('Platzierung nach Gesamt absteigend', () => {
  const bloecke = [
    [blk([1, 1, 1]), blk([1, 1, 1])], // Anna: 6
    [blk([9, 9, 9]), blk([9, 9, 9])], // Ben:  54
  ];
  const { ranking, players } = computeGameStats(config, bloecke, ranges);
  assert.equal(ranking[0].name, 'Ben');
  assert.equal(ranking[0].rang, 1);
  assert.equal(ranking[1].name, 'Anna');
  assert.equal(ranking[1].rang, 2);
  // players teilt dieselben Objekte -> rang ist dort gesetzt.
  assert.equal(players.find((p) => p.name === 'Ben').rang, 1);
});

test('Gleichstand -> gleicher Rang, nächster übersprungen', () => {
  const cfg3 = { ...config, spielerListe: [{ name: 'A' }, { name: 'B' }, { name: 'C' }] };
  const bloecke = [
    [blk([9, 9, 9]), blk([9, 9, 9])], // 54
    [blk([9, 9, 9]), blk([9, 9, 9])], // 54 (Gleichstand mit A)
    [blk([1, 1, 1]), blk([1, 1, 1])], // 6
  ];
  const { ranking } = computeGameStats(cfg3, bloecke, ranges);
  assert.equal(ranking[0].rang, 1);
  assert.equal(ranking[1].rang, 1); // Gleichstand -> ebenfalls Platz 1
  assert.equal(ranking[2].rang, 3); // Platz 2 wird übersprungen
});

test('Bahn kommt aus dem bahnplan (Fallback ersteBahn + satz)', () => {
  const cfg = { ...config, bahnplan: [[3, 4]], spielerListe: [{ name: 'A' }] };
  const bloecke = [[blk([5, 5, 5]), blk([5, 5, 5])]];
  const { players } = computeGameStats(cfg, bloecke, ranges);
  assert.deepEqual(players[0].saetze.map((s) => s.bahn), [3, 4]);

  // Ohne bahnplan: ersteBahn (1) + Satz-Index.
  const bloecke2 = [[blk([5, 5, 5]), blk([5, 5, 5])]];
  const { players: p2 } = computeGameStats({ ...config, spielerListe: [{ name: 'A' }] }, bloecke2, ranges);
  assert.deepEqual(p2[0].saetze.map((s) => s.bahn), [1, 2]);
});

test('leerer Name -> "Spieler N"', () => {
  const cfg = { ...config, spielerListe: [{ name: '' }] };
  const { players } = computeGameStats(cfg, [[blk([1, 1, 1]), blk([1, 1, 1])]], ranges);
  assert.equal(players[0].name, 'Spieler 1');
});

test('Räumer-Verteilung: wie oft brauchte ein Lauf wie viele Würfe?', () => {
  // Ein Teilsatz Abräumen à 6 Würfe, 1 Satz. Drei Läufe mit 1, 2 und 3 Würfen:
  //   Lauf 1: 9                 -> in 1 Wurf abgeräumt
  //   Lauf 2: 6, 3              -> in 2 Würfen
  //   Lauf 3: 5, 2, 2           -> in 3 Würfen
  const cfg = {
    spielerListe: [{ name: 'R' }], saetze: 1, ersteBahn: 1, wuerfeProSatz: 6,
    teilsaetze: [{ modus: 'abraeumen', wuerfe: 6 }],
  };
  const r = teilsatzRanges(cfg);
  const bloecke = [[
    {
      wuerfe: [9, 6, 3, 5, 2, 2],
      kegel: [[1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 5, 6], [7, 8, 9], [1, 2, 3, 4, 5], [6, 7], [8, 9]],
      koenig: [false, false, false, false, false, false], overrides: [null], done: true,
    },
  ]];
  const p = computeGameStats(cfg, bloecke, r).players[0];
  assert.equal(p.raeumer, 3);
  assert.equal(p.raeumSchnitt, 2);                 // (1 + 2 + 3) / 3
  // Index = Würfe je Räumer, Wert = Häufigkeit. Index 0 bleibt leer.
  assert.deepEqual(p.raeumVert, [0, 1, 1, 1]);

  // Würfe auf das volle Bild: der jeweils erste Wurf eines Laufs (9, 6, 5).
  const ts = p.saetze[0].teilsaetze[0];
  assert.deepEqual(ts.wuerfeVoll, [true, true, false, true, false, false]);
  assert.equal(p.vollChance, 3);
});

test('Räumer-Verteilung: über Sätze und Teilsätze aufsummiert', () => {
  // 2 Sätze mit je einem Abräum-Teilsatz à 2 Würfe. Satz 1: ein Räumer in 1 Wurf (9) und einer
  // in 1 Wurf (9). Satz 2: ein Räumer in 2 Würfen (7, 2). -> zweimal „1 Wurf", einmal „2 Würfe".
  const cfg = {
    spielerListe: [{ name: 'R' }], saetze: 2, ersteBahn: 1, wuerfeProSatz: 2,
    teilsaetze: [{ modus: 'abraeumen', wuerfe: 2 }],
  };
  const r = teilsatzRanges(cfg);
  const alle = [1, 2, 3, 4, 5, 6, 7, 8, 9];
  const bloecke = [[
    { wuerfe: [9, 9], kegel: [alle, alle], koenig: [false, false], overrides: [null], done: true },
    { wuerfe: [7, 2], kegel: [[1, 2, 3, 4, 5, 6, 7], [8, 9]], koenig: [false, false], overrides: [null], done: true },
  ]];
  const p = computeGameStats(cfg, bloecke, r).players[0];
  assert.equal(p.raeumer, 3);
  assert.deepEqual(p.raeumVert, [0, 2, 1]);
});

test('Räumer-Verteilung: ohne Abräumen leer', () => {
  const bloecke = [[blk([9, 8, 7]), blk([6, 5, 4])], [blk([1, 1, 1]), blk([1, 1, 1])]];
  const { players } = computeGameStats(config, bloecke, ranges);
  assert.deepEqual(players[0].raeumVert, []);
  // In der Volle kam jeder Wurf aus dem vollen Bild.
  assert.deepEqual(players[0].saetze[0].teilsaetze[0].wuerfeVoll, [true, true, true]);
});
