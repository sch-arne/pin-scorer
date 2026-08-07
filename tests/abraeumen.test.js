import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  abraeumStep, abraeumScan, freshRun, volleKranz, defaultKegel, isAbraeumMode,
} from '../js/logic/abraeumen.js';

// Ein Block, wie ihn die Erfassung hält.
function blk(wuerfe, kegel = null, koenig = null) {
  return {
    wuerfe,
    kegel: kegel || wuerfe.map(() => null),
    koenig: koenig || wuerfe.map(() => false),
  };
}
const ABR = { start: 0, end: 30, soll: 30, modus: 'abraeumen' };
const KRANZ = { start: 0, end: 30, soll: 30, modus: 'kranz-abraeumen' };

test('isAbraeumMode / defaultKegel Grundlagen', () => {
  assert.equal(isAbraeumMode('abraeumen'), true);
  assert.equal(isAbraeumMode('kranz-abraeumen'), true);
  assert.equal(isAbraeumMode('volle'), false);
  assert.deepEqual(defaultKegel(0), []);
  assert.deepEqual(defaultKegel(9), [1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.equal(defaultKegel(5), null); // unbestimmt
});

test('abraeumStep count-only: 6 gefallen -> 3 stehen (Menge unbekannt)', () => {
  const r = abraeumStep(freshRun(), 6, null, false, 'abraeumen');
  assert.equal(r.next.count, 3);
  assert.equal(r.next.exact, false);
  assert.equal(r.error, null);
});

test('abraeumStep exakt: konkrete Kegel -> Restmenge bekannt', () => {
  const r = abraeumStep(freshRun(), 6, [1, 2, 3, 4, 6, 7], false, 'abraeumen');
  assert.deepEqual(r.next.standing, [5, 8, 9]);
  assert.equal(r.next.count, 3);
  assert.equal(r.next.exact, true);
  assert.equal(r.error, null);
});

test('Leerräumen setzt zurück auf alle 9', () => {
  // 6 fallen (count 3), dann 3 fallen -> abgeräumt -> freshRun
  let s = abraeumStep(freshRun(), 6, null, false, 'abraeumen').next;
  const r = abraeumStep(s, 3, null, false, 'abraeumen');
  assert.equal(r.next.count, 9);
  assert.equal(r.next.exact, true);
});

test('Plausibilität: n > count meldet Fehler', () => {
  // exakt auf 3 stehende, dann 4 werfen
  const s = abraeumStep(freshRun(), 6, [1, 2, 3, 4, 6, 7], false, 'abraeumen').next;
  const r = abraeumStep(s, 4, null, false, 'abraeumen');
  assert.match(r.error, /nur 3 Kegel standen/);
});

test('Plausibilität: gefallener Kegel stand nicht mehr (exact)', () => {
  // Scan: Wurf1 fällt exakt [1,2,3,5,8,9] -> stehen [4,6,7]; Wurf2 [5,8] standen nicht mehr
  const b = blk([6, 2], [[1, 2, 3, 5, 8, 9], [5, 8]], [false, false]);
  const scan = abraeumScan(b, ABR);
  assert.equal(scan.error[0], null);
  assert.match(scan.error[1], /Kegel 5, 8 standen nicht mehr/);
});

test('Kranz: eine reine 8 (ohne Kegel-Angabe) ist KEIN Kranz, kein Reset', () => {
  // count-only 8 -> genau 1 Restkegel, welcher ist unbekannt (nicht zwingend der König)
  // -> kein Kranz-Zeichen, kein Reset auf 9.
  const b = blk([8, 1], [null, null], [false, false]);
  const scan = abraeumScan(b, KRANZ);
  assert.equal(scan.kranzAt[0], false);
  assert.equal(scan.koenigAfter[0], false);
  assert.equal(scan.before[1].count, 1); // nur 1 Kegel steht noch, KEIN frischer 9er-Lauf
  // Genau 1 Kegel steht -> eine 1 räumt ihn plausibel ab
  assert.equal(scan.error[1], null);
});

test('Kranz: reine 8 dann 9 ist unmöglich (nur 1 Kegel stand)', () => {
  // Ohne Kranz-Reset stehen nach der 8 nur noch 1 Kegel -> eine 9 ist unmöglich.
  const b = blk([8, 9], [null, null], [false, false]);
  const scan = abraeumScan(b, KRANZ);
  assert.match(scan.error[1], /nur 1 Kegel stand/);
});

test('Kranz-Langdruck: eine 8 per Langdruck IST ein Kranz (Reset auf 9)', () => {
  // koenigFlag=true -> König bleibt stehen, 8 Kranz-Kegel fallen -> Kranz, danach frischer Lauf.
  const b = blk([8, 9], [null, null], [true, false]);
  const scan = abraeumScan(b, KRANZ);
  assert.equal(scan.kranzAt[0], true);
  assert.equal(scan.error[1], null); // nach Reset stehen wieder alle 9 -> 9 ist plausibel
});

test('Kranz-Langdruck: König bleibt stehen (koenig-Flag)', () => {
  const r = abraeumStep(freshRun(), 3, null, true, 'kranz-abraeumen');
  assert.equal(r.next.koenig, true);
  assert.equal(r.next.count, 6); // 9 - 3, König in den 6 enthalten
  assert.equal(r.next.exact, false);
});

test('Kranz: 7er (statt König) bleibt stehen -> KEIN Reset', () => {
  // Alle außer der 7 fallen exakt (inkl. König 5) -> es steht die 7, nicht der König.
  const r = abraeumStep(freshRun(), 8, [1, 2, 3, 4, 5, 6, 8, 9], false, 'kranz-abraeumen');
  assert.deepEqual(r.next.standing, [7]);
  assert.equal(r.next.koenig, false);
  assert.equal(r.next.count, 1); // nicht zurückgesetzt auf 9
});

test('volleKranz: 8 mit König stehend', () => {
  assert.equal(volleKranz(blk([8], [[1, 2, 3, 4, 6, 7, 8, 9]]), 0), true);  // 8 Nebenkegel, 5 steht
  assert.equal(volleKranz(blk([8], [[1, 2, 3, 4, 5, 6, 7, 8]]), 0), false); // König gefallen -> kein Kranz
  assert.equal(volleKranz(blk([9], [[1, 2, 3, 4, 5, 6, 7, 8, 9]]), 0), false); // 9 ist kein Kranz
});
