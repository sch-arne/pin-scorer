import { test } from 'node:test';
import assert from 'node:assert/strict';
import { teilsatzStats, satzHolz, satzStatus } from '../js/logic/holz.js';
import { teilsatzRanges } from '../js/logic/teilsaetze.js';

const ranges = teilsatzRanges({ teilsaetze: [{ modus: 'volle', wuerfe: 3 }, { modus: 'abraeumen', wuerfe: 3 }] });

function blk(wuerfe, overrides = [null, null], done = false) {
  return { wuerfe, kegel: wuerfe.map(() => null), koenig: wuerfe.map(() => false), overrides, done };
}

test('satzHolz = Summe der Teilsatz-Würfe', () => {
  assert.equal(satzHolz(blk([9, 8, 7, 6, 5, 4]), ranges), 39);
  assert.equal(satzHolz(blk([]), ranges), 0);
});

test('satzHolz nutzt Override statt Würfe-Summe', () => {
  // Teilsatz 0 override 20 (statt 9+8+7=24), Teilsatz 1 aus Würfen (6+5+4=15) -> 35
  assert.equal(satzHolz(blk([9, 8, 7, 6, 5, 4], [20, null]), ranges), 35);
});

test('teilsatzStats.val: manuell vs. aus Würfen', () => {
  const withThrows = teilsatzStats(blk([9, 8, 7]), ranges, 0, false);
  assert.equal(withThrows.val, 24);
  assert.equal(withThrows.manual, false);

  const manual = teilsatzStats(blk([9, 8, 7], [20, null]), ranges, 0, false);
  assert.equal(manual.val, 20);
  assert.equal(manual.manual, true);
});

test('teilsatzStats.mark: Mismatch nur wenn "settled"', () => {
  // Zu wenige Würfe, aber Satz noch offen -> kein Mark
  assert.equal(teilsatzStats(blk([9, 8]), ranges, 0, false).mark, false);
  // Satz done -> settled -> Mark bei != Soll
  assert.equal(teilsatzStats(blk([9, 8], [null, null], true), ranges, 0, true).mark, true);
  // Genau Soll -> nie Mark (auch bei done)
  assert.equal(teilsatzStats(blk([9, 8, 7], [null, null], true), ranges, 0, true).mark, false);
  // Manuell gesetztes Ergebnis (Override) ist Absicht -> NIE Mismatch-Mark (auch bei != Soll Würfen)
  assert.equal(teilsatzStats(blk([9, 8], [50, null]), ranges, 0, false).mark, false);
  // Späterer Teilsatz hat Würfe -> Teilsatz 0 ist voll (Soll), also KEIN Mark (lückenlos gefüllt)
  assert.equal(teilsatzStats(blk([9, 8, 7, 6]), ranges, 0, false).mark, false);
});

test('teilsatzStats.count: manuell -> Soll, sonst erfasste Würfe', () => {
  // Ohne Override: tatsächliche Wurfzahl im Teilsatz-Bereich.
  assert.equal(teilsatzStats(blk([9, 8]), ranges, 0, false).count, 2);
  // Override gesetzt (auch ohne/mit zu wenig Würfen) -> Zähler springt auf Soll (3).
  assert.equal(teilsatzStats(blk([], [42, null]), ranges, 0, false).count, 3);
  assert.equal(teilsatzStats(blk([9, 8], [42, null]), ranges, 0, false).count, 3);
});

test('satzStatus: pending / live / done', () => {
  assert.equal(satzStatus(blk([])), 'pending');
  assert.equal(satzStatus(blk([9])), 'live');
  assert.equal(satzStatus(blk([], [5, null])), 'live'); // Override ohne Würfe = live
  assert.equal(satzStatus(blk([9], [null, null], true)), 'done');
});
