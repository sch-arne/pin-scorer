import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computeWettkampfStats } from '../js/logic/wettkampf.js';
import {
  ALLE, leererFilter, filterOptionen, mannschaftAuswertung, filterAktiv,
} from '../js/logic/mannschaft-statistik.js';

const TEAMS = [{ id: 'mA', name: 'Team A' }, { id: 'mB', name: 'Team B' }];

// Ein Satz-Block mit 4 Würfen = 2 Teilsätze à 2 Würfe (Volle, Abräumen).
function blk(wuerfe, overrides = [null, null]) {
  return { wuerfe, kegel: wuerfe.map(() => null), koenig: wuerfe.map(() => false), overrides, done: true };
}

// Ein Durchgang: 2 Spieler (je einer pro Team), 2 Sätze, 2 Teilsätze (Volle/Abräumen) à 2 Würfe.
// `bahnplan` legt fest, welcher Spieler welchen Satz auf welcher Bahn spielt.
function durchgang(id, spielerListe, bloecke, bahnplan) {
  return {
    id,
    config: {
      spielerListe, saetze: 2, ersteBahn: 1, wuerfeProSatz: 4, bahnplan,
      teilsaetze: [{ modus: 'volle', wuerfe: 2 }, { modus: 'abraeumen', wuerfe: 2 }],
    },
    erfassung: { bloecke },
  };
}

// Zwei Durchgänge, gekreuzte Bahnen: Anna (A) spielt Satz 1 auf Bahn 1, Satz 2 auf Bahn 2,
// Ben (B) umgekehrt. Im 2. Durchgang dasselbe mit Cara (A) und Dirk (B).
function wettkampfFixture() {
  const g1 = durchgang('g1',
    [{ name: 'Anna', mannschaftId: 'mA', teamPos: 1 }, { name: 'Ben', mannschaftId: 'mB', teamPos: 1 }],
    [
      [blk([9, 8, 5, 4]), blk([7, 6, 3, 2])],   // Anna: Satz1 (B1) 17+9, Satz2 (B2) 13+5
      [blk([9, 9, 1, 1]), blk([0, 2, 4, 4])],   // Ben:  Satz1 (B2), Satz2 (B1)
    ],
    [[1, 2], [2, 1]]);
  const g2 = durchgang('g2',
    [{ name: 'Cara', mannschaftId: 'mA', teamPos: 2 }, { name: 'Dirk', mannschaftId: 'mB', teamPos: 2 }],
    [
      [blk([9, 9, 9, 9]), blk([1, 1, 1, 1])],
      [blk([2, 2, 2, 2]), blk([3, 3, 3, 3])],
    ],
    [[1, 2], [2, 1]]);
  const wettkampf = { mannschaften: TEAMS, durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }] };
  return computeWettkampfStats(wettkampf, [g1, g2]);
}

test('filterOptionen: alle vorkommenden Bahnen, Sätze und Teilsatz-Modi', () => {
  const { einzel } = wettkampfFixture();
  const opt = filterOptionen(einzel);
  assert.deepEqual(opt.bahnen, [1, 2]);
  assert.deepEqual(opt.saetze, [1, 2]);
  assert.deepEqual(opt.modi, ['volle', 'abraeumen']);
});

test('ohne Filter: Mannschafts-Holz = Summe der eigenen Spieler', () => {
  const { einzel, mannschaften } = wettkampfFixture();
  const a = mannschaftAuswertung(einzel, 'mA', leererFilter());
  const teamA = mannschaften.find((t) => t.mannschaftId === 'mA');
  assert.equal(a.holz, teamA.gesamt);
  // 2 Spieler (Starts) mit je 2 Sätzen.
  assert.equal(a.spieler, 2);
  assert.equal(a.saetze, 4);
  assert.equal(a.wurfCount, 16);
});

test('Bahn-Filter: nur die Sätze, die auf dieser Bahn gespielt wurden (spielerabhängig)', () => {
  const { einzel } = wettkampfFixture();
  // Team A spielt Satz 1 auf Bahn 1: Anna 9+8+5+4 = 26, Cara 9+9+9+9 = 36.
  const b1 = mannschaftAuswertung(einzel, 'mA', { ...leererFilter(), bahn: 1 });
  assert.equal(b1.holz, 26 + 36);
  assert.equal(b1.saetze, 2);
  // Team B spielt Satz 2 auf Bahn 1: Ben 0+2+4+4 = 10, Dirk 3+3+3+3 = 12.
  const b1B = mannschaftAuswertung(einzel, 'mB', { ...leererFilter(), bahn: 1 });
  assert.equal(b1B.holz, 10 + 12);
});

test('Satz- und Teilsatz-Filter sind mit dem Bahn-Filter kombinierbar', () => {
  const { einzel } = wettkampfFixture();
  // Satz 1 auf Bahn 1, nur Volle: Anna 9+8 = 17, Cara 9+9 = 18.
  const f = { bahn: 1, satz: 1, teil: 'volle' };
  const k = mannschaftAuswertung(einzel, 'mA', f);
  assert.equal(k.holz, 17 + 18);
  assert.equal(k.wurfCount, 4);
  assert.equal(k.erfasst, 4);
  // Satz 2 auf Bahn 1 gibt es für Team A nicht (dort liegt Satz 1) -> leer.
  const leer = mannschaftAuswertung(einzel, 'mA', { bahn: 1, satz: 2, teil: ALLE });
  assert.equal(leer.holz, 0);
  assert.equal(leer.saetze, 0);
});

test('Wurf-Verteilung zählt nur einzeln erfasste Würfe', () => {
  const { einzel } = wettkampfFixture();
  const k = mannschaftAuswertung(einzel, 'mA', { ...leererFilter(), teil: 'volle' });
  // Volle-Würfe Team A: Anna 9,8 (Satz 1) und 7,6 (Satz 2) — Cara 9,9 und 1,1
  assert.equal(k.verteilung[9], 3);
  assert.equal(k.verteilung[8], 1);
  assert.equal(k.verteilung[1], 2);
  assert.equal(k.erfasst, 8);
  assert.equal(k.neuner, 3);
});

test('nur als Summe eingetragene Teilsätze: Holz und Würfe zählen, Verteilung nicht', () => {
  const g = durchgang('g1',
    [{ name: 'Anna', mannschaftId: 'mA', teamPos: 1 }],
    [[blk([], [40, 20]), blk([9, 9, 9, 9])]],
    [[1, 2]]);
  const wettkampf = { mannschaften: TEAMS, durchgaenge: [{ nr: 1, gameId: 'g1' }] };
  const { einzel } = computeWettkampfStats(wettkampf, [g]);
  const k = mannschaftAuswertung(einzel, 'mA', { ...leererFilter(), bahn: 1 });
  assert.equal(k.holz, 60);        // aus den Overrides
  assert.equal(k.wurfCount, 4);    // manueller Teilsatz zählt als voller Teilsatz (Soll)
  assert.equal(k.erfasst, 0);      // aber keine Einzelwürfe
  assert.equal(k.verteilung.reduce((s, n) => s + n, 0), 0);
});

test('Bahn-Vergleich zeigt ALLE Bahnen und markiert die gefilterte', () => {
  const { einzel } = wettkampfFixture();
  const k = mannschaftAuswertung(einzel, 'mA', { ...leererFilter(), bahn: 2 });
  assert.deepEqual(k.bahnen.map((b) => b.wert), [1, 2]);
  assert.deepEqual(k.bahnen.map((b) => b.gewaehlt), [false, true]);
  // Bahn 1 bleibt mit ihren Zahlen sichtbar, obwohl Bahn 2 gefiltert ist.
  assert.equal(k.bahnen[0].holz, 26 + 36);
  assert.equal(k.bahnen[0].schnitt, (26 + 36) / 2);
  // Die Kennzahlen daneben folgen dagegen dem Filter (nur Bahn 2).
  assert.equal(k.holz, k.bahnen[1].holz);
});

test('Satz-Verlauf verhält sich analog und respektiert den Teilsatz-Filter', () => {
  const { einzel } = wettkampfFixture();
  const k = mannschaftAuswertung(einzel, 'mA', { bahn: ALLE, satz: 1, teil: 'volle' });
  assert.deepEqual(k.satzReihe.map((s) => s.wert), [1, 2]);
  // Satz 2 bleibt sichtbar, aber nur mit Volle-Holz: Anna 7+6 = 13, Cara 1+1 = 2.
  assert.equal(k.satzReihe[1].holz, 13 + 2);
});

test('filterAktiv erkennt jede gesetzte Dimension', () => {
  assert.equal(filterAktiv(leererFilter()), false);
  assert.equal(filterAktiv({ bahn: 2, satz: ALLE, teil: ALLE }), true);
  assert.equal(filterAktiv({ bahn: ALLE, satz: 1, teil: ALLE }), true);
  assert.equal(filterAktiv({ bahn: ALLE, satz: ALLE, teil: 'volle' }), true);
});
