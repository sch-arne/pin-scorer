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

  assert.equal(ben.gesamt, 30);
  assert.equal(ben.bester, 27);
  assert.equal(ben.neuner, 3);           // drei 9er
  assert.equal(ben.fehl, 1);             // eine 0
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
