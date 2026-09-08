import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  teilsatzStats, satzHolz, satzStatus, satzWurfCount, satzOverrideAktiv, blockHatInhalt,
} from '../js/logic/holz.js';
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

// --- Satz-Ergebnis ohne Teilsatz-Aufteilung (`satzOverride`) ------------------
// Entsteht beim Web-Import: der Sportwinner-Ergebnisdienst nennt bei Schere und Classic mit
// Punktwertung nur das Satz-Holz. Der Satz traegt es dann selbst, die Teilsaetze bleiben leer.

const satzBlk = (holz, overrides = [null, null], wuerfe = []) => ({
  ...blk(wuerfe, overrides), satzOverride: holz,
});

test('satzOverride gilt als Satz-Holz, solange ein Teilsatz offen ist', () => {
  const b = satzBlk(151);
  assert.equal(satzOverrideAktiv(b, ranges), true);
  assert.equal(satzHolz(b, ranges), 151);
  // Ohne diese Wurfzahl waere der Schnitt/Wurf eines importierten Spiels 0.
  assert.equal(satzWurfCount(b, ranges), 6);
  assert.equal(satzStatus(b), 'live');
  assert.equal(blockHatInhalt(b), true);
});

test('satzOverride bleibt stehen, bis JEDER Teilsatz einen Wert hat', () => {
  // Wer die Volle nachtraegt, soll das exakte Satzergebnis nicht dabei verlieren.
  const halb = satzBlk(151, [90, null]);
  assert.equal(satzHolz(halb, ranges), 151, 'ein Teilsatz allein ersetzt den Satz noch nicht');

  const ganz = satzBlk(151, [90, 61]);
  assert.equal(satzOverrideAktiv(ganz, ranges), false);
  assert.equal(satzHolz(ganz, ranges), 151, 'jetzt zaehlen die Teilsaetze');
  assert.equal(satzWurfCount(ganz, ranges), 6);

  // Auch erfasste Wuerfe zaehlen als "Teilsatz hat einen Wert".
  const mitWuerfen = satzBlk(151, [90, null], [0, 0, 0, 5, 5, 5]);
  assert.equal(satzOverrideAktiv(mitWuerfen, ranges), false);
  assert.equal(satzHolz(mitWuerfen, ranges), 105);
});

test('ohne satzOverride bleibt alles wie bisher', () => {
  const b = blk([9, 8, 7, 6, 5, 4]);
  assert.equal(satzOverrideAktiv(b, ranges), false);
  assert.equal(satzHolz(b, ranges), 39);
  assert.equal(satzWurfCount(b, ranges), 6);
  assert.equal(blockHatInhalt(blk([])), false);
  assert.equal(blockHatInhalt(blk([], [12, null])), true);
});

test('satzOverride: leere Teilsaetze sind kein Erfassungsfehler', () => {
  // Ohne diese Ausnahme wuerde jeder Teilsatz eines importierten Satzes ein ⚠ tragen ("falsche
  // Wurfzahl") — dabei ist genau das die Aussage: die Quelle kennt die Aufteilung nicht.
  const b = { ...satzBlk(151), done: true };
  assert.equal(teilsatzStats(b, ranges, 0, true).mark, false);
  // Ein erfasster Satz mit zu wenig Wuerfen wird weiterhin markiert.
  assert.equal(teilsatzStats(blk([9, 8], [null, null], true), ranges, 0, true).mark, true);
});
