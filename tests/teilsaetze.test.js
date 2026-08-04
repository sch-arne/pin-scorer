import { test } from 'node:test';
import assert from 'node:assert/strict';
import { divisors, nearestDivisor, throwsPerPart, teilsatzRanges } from '../js/logic/teilsaetze.js';

test('divisors liefert alle Teiler', () => {
  assert.deepEqual(divisors(30), [1, 2, 3, 5, 6, 10, 15, 30]);
  assert.deepEqual(divisors(1), [1]);
  assert.deepEqual(divisors(7), [1, 7]);
});

test('nearestDivisor nimmt bei Gleichstand den kleineren', () => {
  assert.equal(nearestDivisor(30, 4), 3);   // 3 und 5 gleich weit -> 3
  assert.equal(nearestDivisor(30, 7), 6);
  assert.equal(nearestDivisor(12, 5), 4);   // |4-5|=1 und |6-5|=1 gleich weit -> kleinerer (4)
});

test('nearestDivisor exakt', () => {
  assert.equal(nearestDivisor(12, 4), 4);
  assert.equal(nearestDivisor(12, 3), 3);
});

test('throwsPerPart teilt gleichmaessig, Rest vorne', () => {
  assert.deepEqual(throwsPerPart(30, 2), [15, 15]);
  assert.deepEqual(throwsPerPart(30, 4), [8, 8, 7, 7]);
  assert.deepEqual(throwsPerPart(10, 3), [4, 3, 3]);
});

test('teilsatzRanges baut kumulative Bereiche', () => {
  const ranges = teilsatzRanges({ teilsaetze: [{ modus: 'volle', wuerfe: 15 }, { modus: 'abraeumen', wuerfe: 15 }] });
  assert.deepEqual(ranges, [
    { start: 0, end: 15, soll: 15, modus: 'volle' },
    { start: 15, end: 30, soll: 15, modus: 'abraeumen' },
  ]);
});
