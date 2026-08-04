import { test } from 'node:test';
import assert from 'node:assert/strict';
import { lanePlan, computeBahnState } from '../js/logic/bahnwechsel.js';

function setup(mode, startLanes, { bahnen = 4, saetze = 4, ersteBahn = 1 } = {}) {
  return {
    bahnen, saetze, ersteBahn, bahnwechsel: mode,
    spielerData: startLanes.map((startBahn) => ({ startBahn })),
  };
}

// ── lanePlan (statischer Bahnplan) ──────────────────────────────────────────

test('lanePlan bohle (4 Bahnen, 4 Sätze)', () => {
  const plan = lanePlan(setup('bohle', [1, 2, 3, 4]));
  assert.deepEqual(plan, [
    [1, 2, 3, 4],
    [2, 1, 4, 3],
    [3, 4, 1, 2],
    [4, 3, 2, 1],
  ]);
});

test('lanePlan classic (4 Bahnen, 4 Sätze)', () => {
  const plan = lanePlan(setup('classic', [1, 2, 3, 4]));
  assert.deepEqual(plan, [
    [1, 2, 4, 3],
    [2, 1, 3, 4],
    [3, 4, 2, 1],
    [4, 3, 1, 2],
  ]);
});

test('lanePlan plus1 / minus1 / fest', () => {
  assert.deepEqual(lanePlan(setup('plus1', [1, 2])), [[1, 2, 3, 4], [2, 3, 4, 1]]);
  assert.deepEqual(lanePlan(setup('minus1', [1])), [[1, 4, 3, 2]]);
  assert.deepEqual(lanePlan(setup('fest', [2])), [[2, 2, 2, 2]]);
});

test('lanePlan: 1 Bahn -> immer fest, auch bei Duo-Modus', () => {
  assert.deepEqual(lanePlan(setup('classic', [1], { bahnen: 1 })), [[1, 1, 1, 1]]);
});

// ── computeBahnState (dynamische Belegung mit Gating) ────────────────────────

// Bahn-Zuordnung aus einem statischen Plan (wie im View: laneOf via bahnplan).
function laneOfFrom(plan) {
  return (sp, st) => plan[sp][st];
}

test('A fertig, B nicht -> A wartet auf besetzte Bahn', () => {
  const plan = lanePlan(setup('bohle', [1, 2], { saetze: 4 }));
  const bs = computeBahnState({
    n: 2, saetze: 4,
    doneMatrix: [[true, false, false, false], [false, false, false, false]],
    laneOf: laneOfFrom(plan),
  });
  assert.equal(bs[0].waiting, true);   // A will auf Bahn 2, dort steht B
  assert.equal(bs[0].lane, 1);         // bleibt sichtbar auf alter Bahn
  assert.equal(bs[1].waiting, false);
  assert.equal(bs[1].lane, 2);
});

test('beide fertig -> Duo-Tausch löst sich', () => {
  const plan = lanePlan(setup('bohle', [1, 2], { saetze: 4 }));
  const bs = computeBahnState({
    n: 2, saetze: 4,
    doneMatrix: [[true, false, false, false], [true, false, false, false]],
    laneOf: laneOfFrom(plan),
  });
  assert.equal(bs[0].waiting, false);
  assert.equal(bs[1].waiting, false);
  assert.equal(bs[0].lane, 2); // A auf Satz-2-Bahn
  assert.equal(bs[1].lane, 1); // B getauscht
  assert.equal(bs[0].pos, 1);
  assert.equal(bs[1].pos, 1);
});

test('4 Spieler alle Satz 1 fertig -> zwei parallele Duo-Swaps, kein Deadlock', () => {
  const plan = lanePlan(setup('bohle', [1, 2, 3, 4], { saetze: 4 }));
  const done1 = [true, false, false, false];
  const bs = computeBahnState({
    n: 4, saetze: 4,
    doneMatrix: [done1, done1.slice(), done1.slice(), done1.slice()],
    laneOf: laneOfFrom(plan),
  });
  assert.deepEqual(bs.map((s) => s.lane), [2, 1, 4, 3]); // zwei Tausche (1↔2, 3↔4)
  assert.equal(bs.every((s) => !s.waiting), true);
  // keine Doppelbelegung
  assert.equal(new Set(bs.map((s) => s.lane)).size, 4);
});

test('Startzustand: niemand fertig -> alle auf Startbahn, keiner wartet', () => {
  const plan = lanePlan(setup('bohle', [1, 2, 3, 4]));
  const bs = computeBahnState({
    n: 4, saetze: 4,
    doneMatrix: Array.from({ length: 4 }, () => [false, false, false, false]),
    laneOf: laneOfFrom(plan),
  });
  assert.deepEqual(bs.map((s) => s.lane), [1, 2, 3, 4]);
  assert.equal(bs.every((s) => !s.waiting && s.pos === 0), true);
});
