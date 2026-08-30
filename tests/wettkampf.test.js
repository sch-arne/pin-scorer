import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computeWettkampfStats, planDurchgaenge, durchgangStatusList, wettkampfBaseStatus } from '../js/logic/wettkampf.js';

const TWO_TEAMS = [{ id: 'mA', name: 'A' }, { id: 'mB', name: 'B' }];

test('durchgangStatusList: beendet->fertig, laufend->laufend, erster setup->vorbereitung, Rest->offen', () => {
  const wettkampf = {
    durchgaenge: [
      { nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' },
      { nr: 3, gameId: 'g3' }, { nr: 4, gameId: 'g4' },
    ],
  };
  const games = [
    { id: 'g1', status: 'beendet' }, { id: 'g2', status: 'laufend' },
    { id: 'g3', status: 'setup' }, { id: 'g4', status: 'setup' },
  ];
  const map = {};
  durchgangStatusList(wettkampf, games).forEach((d) => { map[d.nr] = d.status; });
  assert.deepEqual(map, { 1: 'fertig', 2: 'laufend', 3: 'vorbereitung', 4: 'offen' });
});

test('durchgangStatusList: Status aus der Erfassung abgeleitet, nicht aus der status-Spalte', () => {
  // Simuliert den Reload-/Overlay-Fall: der Server-Status ist ueberall 'setup' (nie gepusht),
  // der echte Stand steht aber in den Erfassungs-Bloecken.
  const mkGame = (id, bloecke) => ({ id, status: 'setup', config: { spielerListe: [{}, {}], saetze: 2 }, erfassung: { bloecke } });
  const done = { done: true, wuerfe: [], overrides: [null] };
  const empty = { done: false, wuerfe: [], overrides: [null] };
  const partial = { done: false, wuerfe: [], overrides: [120] };
  const wettkampf = { durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }, { nr: 3, gameId: 'g3' }] };
  const games = [
    mkGame('g1', [[done, done], [done, done]]),      // alle Saetze beendet -> fertig
    mkGame('g2', [[done, partial], [empty, empty]]), // Ergebnis da, nicht alle -> laufend
    mkGame('g3', [[empty, empty], [empty, empty]]),  // nichts erfasst -> setup -> erster = vorbereitung
  ];
  const map = {};
  durchgangStatusList(wettkampf, games).forEach((d) => { map[d.nr] = d.status; });
  assert.deepEqual(map, { 1: 'fertig', 2: 'laufend', 3: 'vorbereitung' });
});

test('durchgangStatusList: sortiert nach Nummer; genau ein Vorbereitungs-Durchgang', () => {
  const wettkampf = {
    durchgaenge: [{ nr: 2, gameId: 'g2' }, { nr: 1, gameId: 'g1' }, { nr: 3, gameId: 'g3' }],
  };
  const games = [{ id: 'g1', status: 'setup' }, { id: 'g2', status: 'setup' }, { id: 'g3', status: 'setup' }];
  const list = durchgangStatusList(wettkampf, games);
  assert.deepEqual(list.map((d) => d.nr), [1, 2, 3]);
  assert.equal(list.filter((d) => d.status === 'vorbereitung').length, 1);
  assert.equal(list[0].status, 'vorbereitung'); // kleinste Nummer ist der nächste
});

test('wettkampfBaseStatus: alle Durchgänge fertig -> beendet; sonst laufend/setup', () => {
  const mk = (id, status) => ({ id, status });
  const wettkampf = { durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }] };
  // Alle beendet -> beendet.
  assert.equal(wettkampfBaseStatus(wettkampf, [mk('g1', 'beendet'), mk('g2', 'beendet')]), 'beendet');
  // Einer noch offen -> laufend (mindestens ein Ergebnis vorhanden).
  assert.equal(wettkampfBaseStatus(wettkampf, [mk('g1', 'beendet'), mk('g2', 'laufend')]), 'laufend');
  // Einer beendet, der Rest noch nicht gestartet -> laufend.
  assert.equal(wettkampfBaseStatus(wettkampf, [mk('g1', 'beendet'), mk('g2', 'setup')]), 'laufend');
  // Nichts erfasst -> setup.
  assert.equal(wettkampfBaseStatus(wettkampf, [mk('g1', 'setup'), mk('g2', 'setup')]), 'setup');
  // Ohne Durchgänge -> setup.
  assert.equal(wettkampfBaseStatus({ durchgaenge: [] }, []), 'setup');
});

test('wettkampfBaseStatus: aus der Erfassung abgeleitet (nicht aus der status-Spalte)', () => {
  const mkGame = (id, bloecke) => ({ id, status: 'setup', config: { spielerListe: [{}, {}], saetze: 2 }, erfassung: { bloecke } });
  const done = { done: true, wuerfe: [], overrides: [null] };
  const wettkampf = { durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }] };
  const games = [
    mkGame('g1', [[done, done], [done, done]]),
    mkGame('g2', [[done, done], [done, done]]),
  ];
  assert.equal(wettkampfBaseStatus(wettkampf, games), 'beendet');
});

test('planDurchgaenge: 2 Teams je 6 Spieler, je 2 Startbahnen -> 3 Durchgänge, Team sitzt auf seinen Bahnen', () => {
  const teamLanes = { mA: [1, 2], mB: [3, 4] };
  const dg = planDurchgaenge({ mannschaften: TWO_TEAMS, spielerJeMannschaft: 6, teamLanes });
  assert.equal(dg.length, 3); // ceil(6/2)
  dg.forEach((d) => assert.equal(d.length, 4)); // alle 4 Bahnen besetzt
  // Team A immer auf Bahn 1/2, Team B auf 3/4.
  dg.forEach((d) => {
    d.filter((p) => p.mannschaftId === 'mA').forEach((p) => assert.ok([1, 2].includes(p.startBahn)));
    d.filter((p) => p.mannschaftId === 'mB').forEach((p) => assert.ok([3, 4].includes(p.startBahn)));
  });
  // Sitzordnung nach Bahn: Durchgang 1 = A1(B1), A2(B2), B1(B3), B2(B4).
  assert.deepEqual(dg[0].map((p) => p.startBahn), [1, 2, 3, 4]);
  assert.deepEqual(dg[0].map((p) => `${p.mannschaftName}${p.teamPos}`), ['A1', 'A2', 'B1', 'B2']);
  assert.deepEqual(dg[2].map((p) => `${p.mannschaftName}${p.teamPos}`), ['A5', 'A6', 'B5', 'B6']);
});

test('planDurchgaenge: ungleiche Bahnenzahl -> Durchgänge nach dem Team mit weniger Bahnen', () => {
  // Team A: 1 Bahn (braucht 6 Durchgänge), Team B: 2 Bahnen (3 Durchgänge) -> max = 6.
  const teamLanes = { mA: [1], mB: [2, 3] };
  const dg = planDurchgaenge({ mannschaften: TWO_TEAMS, spielerJeMannschaft: 6, teamLanes });
  assert.equal(dg.length, 6);
  // Alle Spieler beider Teams werden platziert (6 + 6 = 12).
  const total = dg.reduce((s, d) => s + d.length, 0);
  assert.equal(total, 12);
  // Team A immer auf Bahn 1.
  dg.forEach((d) => d.filter((p) => p.mannschaftId === 'mA').forEach((p) => assert.equal(p.startBahn, 1)));
});

// Ein Satz-Block mit gegebenen Würfen (ein Teilsatz "volle").
function blk(wuerfe) {
  return { wuerfe, kegel: wuerfe.map(() => null), koenig: wuerfe.map(() => false), overrides: [null], done: true };
}

// Ein Durchgang-Spiel: config (2 Spieler, 1 Satz, ein Teilsatz Volle à 3 Würfe) + erfassung.
function durchgangGame(id, spielerListe, bloecke) {
  return {
    id,
    config: { spielerListe, saetze: 1, ersteBahn: 1, wuerfeProSatz: 3, teilsaetze: [{ modus: 'volle', wuerfe: 3 }] },
    erfassung: { bloecke },
  };
}

const TEAMS = [{ id: 'mA', name: 'Team A' }, { id: 'mB', name: 'Team B' }];

test('Einzel-Rangliste über zwei Durchgänge zusammengeführt', () => {
  const g1 = durchgangGame('g1',
    [{ name: 'Anna', mannschaftId: 'mA' }, { name: 'Ben', mannschaftId: 'mB' }],
    [[blk([9, 9, 9])], [blk([5, 5, 5])]]); // Anna 27, Ben 15
  const g2 = durchgangGame('g2',
    [{ name: 'Cara', mannschaftId: 'mA' }, { name: 'Dirk', mannschaftId: 'mB' }],
    [[blk([8, 8, 8])], [blk([1, 1, 1])]]); // Cara 24, Dirk 3
  const wettkampf = { mannschaften: TEAMS, durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }] };

  const { einzel } = computeWettkampfStats(wettkampf, [g1, g2]);
  assert.deepEqual(einzel.map((p) => p.name), ['Anna', 'Cara', 'Ben', 'Dirk']);
  assert.deepEqual(einzel.map((p) => p.gesamt), [27, 24, 15, 3]);
  assert.deepEqual(einzel.map((p) => p.rang), [1, 2, 3, 4]);
  // Durchgang- und Team-Zuordnung bleiben erhalten.
  assert.equal(einzel[0].durchgangNr, 1);
  assert.equal(einzel[0].mannschaftName, 'Team A');
});

test('Mannschafts-Rangliste: Summe Gesamtholz je Team', () => {
  const g1 = durchgangGame('g1',
    [{ name: 'Anna', mannschaftId: 'mA' }, { name: 'Ben', mannschaftId: 'mB' }],
    [[blk([9, 9, 9])], [blk([5, 5, 5])]]); // A: 27, B: 15
  const g2 = durchgangGame('g2',
    [{ name: 'Cara', mannschaftId: 'mA' }, { name: 'Dirk', mannschaftId: 'mB' }],
    [[blk([8, 8, 8])], [blk([1, 1, 1])]]); // A: +24, B: +3
  const wettkampf = { mannschaften: TEAMS, durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }] };

  const { mannschaften } = computeWettkampfStats(wettkampf, [g1, g2]);
  const a = mannschaften.find((t) => t.mannschaftId === 'mA');
  const b = mannschaften.find((t) => t.mannschaftId === 'mB');
  assert.equal(a.gesamt, 51); // 27 + 24
  assert.equal(a.spieler, 2);
  assert.equal(a.schnitt, 25.5);
  assert.equal(b.gesamt, 18); // 15 + 3
  assert.equal(a.rang, 1);
  assert.equal(b.rang, 2);
});

test('Team ohne Spieler erscheint mit 0; teil-erfasster Durchgang wird gewertet', () => {
  // Nur ein Durchgang, Team B leer. Ben hat erst 2 von 3 Würfen -> Zwischenstand zählt.
  const g1 = durchgangGame('g1',
    [{ name: 'Anna', mannschaftId: 'mA' }, { name: 'Ben', mannschaftId: 'mA' }],
    [[blk([9, 9, 9])], [blk([7, 7])]]); // Anna 27, Ben 14 (teilweise)
  const wettkampf = { mannschaften: TEAMS, durchgaenge: [{ nr: 1, gameId: 'g1' }] };

  const { einzel, mannschaften } = computeWettkampfStats(wettkampf, [g1]);
  assert.equal(einzel.find((p) => p.name === 'Ben').gesamt, 14);
  assert.equal(mannschaften.find((t) => t.mannschaftId === 'mA').gesamt, 41);
  const b = mannschaften.find((t) => t.mannschaftId === 'mB');
  assert.equal(b.gesamt, 0);
  assert.equal(b.spieler, 0);
});

test('Gleichstand Einzel -> gleicher Rang, nächster übersprungen', () => {
  const g1 = durchgangGame('g1',
    [{ name: 'A', mannschaftId: 'mA' }, { name: 'B', mannschaftId: 'mB' }],
    [[blk([9, 9, 9])], [blk([9, 9, 9])]]); // beide 27
  const g2 = durchgangGame('g2',
    [{ name: 'C', mannschaftId: 'mA' }],
    [[blk([1, 1, 1])]]); // 3
  const wettkampf = { mannschaften: TEAMS, durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }] };

  const { einzel } = computeWettkampfStats(wettkampf, [g1, g2]);
  assert.equal(einzel[0].rang, 1);
  assert.equal(einzel[1].rang, 1); // Gleichstand
  assert.equal(einzel[2].rang, 3); // Platz 2 übersprungen
});
