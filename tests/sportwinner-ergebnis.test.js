import { test } from 'node:test';
import assert from 'node:assert/strict';
import { swSatzWerte, buildSportwinnerPush } from '../js/logic/sportwinner-ergebnis.js';
import { teilsatzRanges } from '../js/logic/teilsaetze.js';
import { parseRoster } from '../js/logic/roster-import.js';
import { buildWettkampf } from '../js/logic/wettkampf-build.js';

// Classic-Satz: 3 Würfe Volle + 3 Würfe Abräumen.
const CFG = { teilsaetze: [{ modus: 'volle', wuerfe: 3 }, { modus: 'abraeumen', wuerfe: 3 }] };
const RANGES = teilsatzRanges(CFG);

test('swSatzWerte: trennt Volle/Abräumen und zählt Fehler im Abräumen', () => {
  const block = { wuerfe: [9, 8, 7, 5, 0, 4], overrides: [null, null] };
  assert.deepEqual(swSatzWerte(block, RANGES), { volle: 24, abr: 9, fehler: 1 });
});

test('swSatzWerte: leerer Block -> alles 0', () => {
  assert.deepEqual(swSatzWerte({ wuerfe: [], overrides: [] }, RANGES), { volle: 0, abr: 0, fehler: 0 });
  assert.deepEqual(swSatzWerte(undefined, RANGES), { volle: 0, abr: 0, fehler: 0 });
});

test('swSatzWerte: manuelle Summe (Override) fliesst ein, Fehler bleibt 0', () => {
  const block = { wuerfe: [], overrides: [20, 15] };
  assert.deepEqual(swSatzWerte(block, RANGES), { volle: 20, abr: 15, fehler: 0 });
});

test('swSatzWerte: nur-Volle-Programm (Bohle) -> abr 0, keine Fehler', () => {
  const cfg = { teilsaetze: [{ modus: 'volle', wuerfe: 3 }, { modus: 'volle', wuerfe: 3 }] };
  const ranges = teilsatzRanges(cfg);
  const block = { wuerfe: [9, 0, 7, 5, 6, 4], overrides: [null, null] };
  assert.deepEqual(swSatzWerte(block, ranges), { volle: 31, abr: 0, fehler: 0 });
});

test('buildSportwinnerPush: mappt (Mannschaft,teamPos) auf DLL-Seite/Slot und Sätze auf Bahnen', () => {
  const wettkampf = {
    sportwinner: {
      spielNr: 42,
      seiten: { mA: 'GG', mB: 'G' },
      spieler: [
        { mannschaftId: 'mA', teamPos: 1, slot: 0 },
        { mannschaftId: 'mB', teamPos: 1, slot: 3 },
      ],
    },
  };
  const games = [{
    config: {
      saetze: 2,
      teilsaetze: [{ modus: 'volle', wuerfe: 3 }, { modus: 'abraeumen', wuerfe: 3 }],
      spielerListe: [
        { mannschaftId: 'mA', teamPos: 1, name: 'Heim 1' },
        { mannschaftId: 'mB', teamPos: 1, name: 'Gast 1' },
      ],
    },
    erfassung: {
      bloecke: [
        [{ wuerfe: [9, 8, 7, 5, 0, 4], overrides: [null, null] }, { wuerfe: [6, 6, 6, 6, 6, 6], overrides: [null, null] }],
        [{ wuerfe: [], overrides: [20, 15] }, { wuerfe: [], overrides: [null, null] }],
      ],
    },
  }];

  const push = buildSportwinnerPush(wettkampf, games);
  assert.equal(push.spielNr, 42);
  // 2 Spieler × 2 Sätze = 4 Updates.
  assert.equal(push.updates.length, 4);

  const heimS0 = push.updates.find((u) => u.side === 'GG' && u.slot === 0 && u.bahn === 0);
  assert.deepEqual(heimS0, { side: 'GG', slot: 0, bahn: 0, volle: 24, abr: 9, fehler: 1 });
  const heimS1 = push.updates.find((u) => u.side === 'GG' && u.slot === 0 && u.bahn === 1);
  assert.deepEqual(heimS1, { side: 'GG', slot: 0, bahn: 1, volle: 18, abr: 18, fehler: 0 });
  const gastS0 = push.updates.find((u) => u.side === 'G' && u.slot === 3 && u.bahn === 0);
  assert.deepEqual(gastS0, { side: 'G', slot: 3, bahn: 0, volle: 20, abr: 15, fehler: 0 });
});

test('buildSportwinnerPush: Satz-Ergebnis geht auf die PHYSISCHE Bahn (Bahnwechsel), nicht den Satz-Index', () => {
  const wettkampf = {
    sportwinner: {
      spielNr: 5,
      seiten: { mA: 'GG', mB: 'G' },
      spieler: [
        { mannschaftId: 'mA', teamPos: 1, slot: 0 }, // startet Bahn 1
        { mannschaftId: 'mB', teamPos: 1, slot: 1 }, // startet Bahn 3
      ],
    },
  };
  // 4 Bahnen (1..4), plus1-Bahnwechsel. Spieler B startet auf Bahn 3:
  //   Sätze auf Bahnen [3,4,1,2] -> Bahn-Slots [2,3,0,1].
  const nur = { modus: 'volle', wuerfe: 1 };
  const games = [{
    config: {
      saetze: 4, bahnwechsel: 'plus1', bahnListe: [1, 2, 3, 4],
      teilsaetze: [nur],
      spielerListe: [
        { mannschaftId: 'mA', teamPos: 1, startBahn: 1, name: 'Heim 1' },
        { mannschaftId: 'mB', teamPos: 1, startBahn: 3, name: 'Gast 1' },
      ],
    },
    erfassung: {
      bloecke: [
        [{ wuerfe: [11] }, { wuerfe: [12] }, { wuerfe: [13] }, { wuerfe: [14] }],
        [{ wuerfe: [21] }, { wuerfe: [22] }, { wuerfe: [23] }, { wuerfe: [24] }],
      ],
    },
  }];

  const push = buildSportwinnerPush(wettkampf, games);
  const heim = push.updates.filter((u) => u.side === 'GG').sort((a, b) => a.bahn - b.bahn);
  // Heim startet Bahn 1 -> Satz s auf Bahn-Slot s, Werte 11..14 der Reihe nach.
  assert.deepEqual(heim.map((u) => [u.bahn, u.volle]), [[0, 11], [1, 12], [2, 13], [3, 14]]);
  // Gast startet Bahn 3: Satz0 (Wert 21) -> Bahn-Slot 2; Satz1 (22) -> 3; Satz2 (23) -> 0; Satz3 (24) -> 1.
  const gast = push.updates.filter((u) => u.side === 'G');
  const slotVal = (b) => gast.find((u) => u.bahn === b).volle;
  assert.equal(slotVal(2), 21);
  assert.equal(slotVal(3), 22);
  assert.equal(slotVal(0), 23);
  assert.equal(slotVal(1), 24);
});

test('buildSportwinnerPush: ohne sportwinner-Block -> null (kein Rückschreiben gemeint)', () => {
  assert.equal(buildSportwinnerPush({}, []), null);
});

test('buildSportwinnerPush: begrenzt auf 4 Bahnen (Sportwinner-Slot hat 4 Bahnen)', () => {
  const wettkampf = { sportwinner: { seiten: { mA: 'GG' }, spieler: [{ mannschaftId: 'mA', teamPos: 1, slot: 0 }] } };
  const games = [{
    config: { saetze: 6, teilsaetze: [{ modus: 'volle', wuerfe: 3 }], spielerListe: [{ mannschaftId: 'mA', teamPos: 1 }] },
    erfassung: { bloecke: [[]] },
  }];
  const push = buildSportwinnerPush(wettkampf, games);
  assert.equal(push.updates.length, 4);
  assert.deepEqual(push.updates.map((u) => u.bahn), [0, 1, 2, 3]);
});

test('parseRoster: emittiert sportwinner-Zuordnung mit Seiten + Slots', () => {
  const roster = {
    spielNr: 328202,
    seiten: {
      GG: { mannschaft: 'VOK 1', aufstellung: [
        { nachname: 'Schierbaum', vorname: 'Arne', pass: '1', id: 11, pos: 0 },
        { nachname: 'Müller', vorname: 'Tim', pass: '2', id: 12, pos: 1 },
      ] },
      G: { mannschaft: 'SKC 1', aufstellung: [
        { nachname: 'Mustermann', vorname: 'Max', pass: '3', id: 21, pos: 0 },
      ] },
    },
  };
  const spec = parseRoster(roster);
  const sw = spec.sportwinner;
  assert.equal(sw.spielNr, 328202);
  const heimId = spec.mannschaften[0].id;
  const gastId = spec.mannschaften[1].id;
  assert.equal(sw.seiten[heimId], 'GG');
  assert.equal(sw.seiten[gastId], 'G');
  assert.equal(sw.spieler.length, 3);
  const heim2 = sw.spieler.find((p) => p.mannschaftId === heimId && p.teamPos === 2);
  assert.equal(heim2.slot, 1);
  assert.equal(heim2.pass, '2');
});

test('parseRoster -> buildWettkampf: sportwinner-Block überlebt den Bau', () => {
  const roster = {
    spielNr: 7,
    seiten: {
      GG: { mannschaft: 'A', aufstellung: [{ nachname: 'X', vorname: 'A', pass: '1', id: 1, pos: 0 }] },
      G: { mannschaft: 'B', aufstellung: [{ nachname: 'Y', vorname: 'B', pass: '2', id: 2, pos: 0 }] },
    },
    partie: { spielort: { bahnen: '1 - 2' } },
  };
  const spec = parseRoster(roster);
  const anlageBahnen = spec.anlage.bahnen.map((n, i) => ({ id: `b${i}`, nummer: n, bahnart: 'bohle' }));
  const { wettkampf } = buildWettkampf({
    ...spec, preset: 'bohle', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'volle'],
    bahnwechsel: 'bohle', anlageId: 'anl', anlageName: spec.anlage.name, anlageBahnen,
    sportwinner: spec.sportwinner,
  });
  assert.ok(wettkampf.sportwinner);
  assert.equal(wettkampf.sportwinner.spielNr, 7);
});
