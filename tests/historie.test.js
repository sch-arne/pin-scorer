// Historie-Filter: welche Auswahl kommt in der Historie vor, was passt dazu, und auf
// welchem Weg ist ein Ergebnis ins Profil gekommen.

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  OHNE_ANLAGE, metaOfGame, metaOfWettkampf, filterOptionen, passtZuFilter, filterSinnvoll,
  ergebnisQuelle, quellenZaehlen,
} from '../js/logic/historie.js';

const spiel = (anlageId, anlageName, art = 'sportkegler-wk') => ({
  spiel: art, config: { anlageId, anlageName },
});

test('metaOfGame liest Spielart und Anlage aus der Spiel-Config', () => {
  assert.deepEqual(metaOfGame(spiel('a1', ' Halle Nord ')),
    { art: 'sportkegler-wk', anlageId: 'a1', anlageName: 'Halle Nord' });
});

test('metaOfGame faellt auf Training zurueck, wenn die Spielart fehlt', () => {
  assert.equal(metaOfGame({ config: {} }).art, 'sportkegler-wk');
  assert.equal(metaOfGame({}).anlageId, '');
});

test('metaOfWettkampf liest die Stammdaten des Wettkampfs', () => {
  assert.deepEqual(metaOfWettkampf({ typ: 'sportkegler-wettkampf', anlageId: 'a2', anlageName: 'Kegelzentrum' }),
    { art: 'sportkegler-wettkampf', anlageId: 'a2', anlageName: 'Kegelzentrum' });
  // Ein ferngeladener Wettkampf ohne Typ gilt trotzdem als Wettkampf.
  assert.equal(metaOfWettkampf({ anlageId: 'a2' }).art, 'sportkegler-wettkampf');
});

test('filterOptionen zaehlt Spielarten und Anlagen', () => {
  const opt = filterOptionen([
    metaOfGame(spiel('a1', 'Halle Nord')),
    metaOfGame(spiel('a1', 'Halle Nord')),
    metaOfWettkampf({ anlageId: 'a2', anlageName: 'Kegelzentrum' }),
  ]);
  assert.deepEqual(opt.arten.map((a) => [a.key, a.n]).sort(),
    [['sportkegler-wettkampf', 1], ['sportkegler-wk', 2]]);
  assert.deepEqual(opt.anlagen.map((a) => [a.name, a.n]),
    [['Halle Nord', 2], ['Kegelzentrum', 1]]);
});

test('filterOptionen traegt fehlende Anlagen-Namen aus anderen Eintraegen nach', () => {
  // Eine ferngeladene Karte kennt womoeglich nur die id — der Klarname steht an einer anderen.
  const opt = filterOptionen([
    metaOfGame(spiel('a1', '')),
    metaOfGame(spiel('a1', 'Halle Nord')),
  ]);
  assert.deepEqual(opt.anlagen, [{ id: 'a1', name: 'Halle Nord', n: 2 }]);
});

test('filterOptionen fuehrt „Ohne Anlage" nur, wenn es solche Spiele gibt', () => {
  assert.equal(filterOptionen([metaOfGame(spiel('a1', 'Halle'))]).anlagen.length, 1);
  const mit = filterOptionen([metaOfGame(spiel('', '')), metaOfGame(spiel('a1', 'Halle'))]);
  assert.deepEqual(mit.anlagen[mit.anlagen.length - 1], { id: OHNE_ANLAGE, name: 'Ohne Anlage', n: 1 });
});

test('passtZuFilter: leere Auswahl laesst alles durch', () => {
  const m = metaOfGame(spiel('a1', 'Halle'));
  assert.equal(passtZuFilter(m, {}), true);
  assert.equal(passtZuFilter(m, { art: '', anlage: '' }), true);
});

test('passtZuFilter grenzt nach Spielart ein', () => {
  const training = metaOfGame(spiel('a1', 'Halle'));
  const wettkampf = metaOfWettkampf({ anlageId: 'a1' });
  assert.equal(passtZuFilter(training, { art: 'sportkegler-wk' }), true);
  assert.equal(passtZuFilter(wettkampf, { art: 'sportkegler-wk' }), false);
});

test('passtZuFilter grenzt nach Anlage ein — inklusive „ohne Anlage"', () => {
  const mit = metaOfGame(spiel('a1', 'Halle'));
  const ohne = metaOfGame(spiel('', ''));
  assert.equal(passtZuFilter(mit, { anlage: 'a1' }), true);
  assert.equal(passtZuFilter(mit, { anlage: 'a2' }), false);
  assert.equal(passtZuFilter(ohne, { anlage: OHNE_ANLAGE }), true);
  assert.equal(passtZuFilter(mit, { anlage: OHNE_ANLAGE }), false);
});

test('passtZuFilter verknuepft Spielart UND Anlage', () => {
  const m = metaOfGame(spiel('a1', 'Halle'));
  assert.equal(passtZuFilter(m, { art: 'sportkegler-wk', anlage: 'a1' }), true);
  assert.equal(passtZuFilter(m, { art: 'sportkegler-wk', anlage: 'a2' }), false);
});

test('filterSinnvoll: erst wenn es etwas zu unterscheiden gibt', () => {
  const eins = filterOptionen([metaOfGame(spiel('a1', 'Halle')), metaOfGame(spiel('a1', 'Halle'))]);
  assert.equal(filterSinnvoll(eins), false, 'lauter gleiche Spiele brauchen keinen Filter');
  const zwei = filterOptionen([metaOfGame(spiel('a1', 'Halle')), metaOfWettkampf({ anlageId: 'a1' })]);
  assert.equal(filterSinnvoll(zwei), true);
  const anlagen = filterOptionen([metaOfGame(spiel('a1', 'Halle')), metaOfGame(spiel('', ''))]);
  assert.equal(filterSinnvoll(anlagen), true);
});

test('ergebnisQuelle: die eigene LizenzID an der Zeile schlaegt die Zuordnung', () => {
  assert.equal(ergebnisQuelle({ passnummer: '095578', profil_id: 'k1' }, '095578'), 'lizenz');
  assert.equal(ergebnisQuelle({ passnummer: ' 095578 ' }, '095578'), 'lizenz');
});

test('ergebnisQuelle: fremde oder fehlende LizenzID -> ausdrueckliche Zuordnung', () => {
  assert.equal(ergebnisQuelle({ passnummer: '111111', profil_id: 'k1' }, '095578'), 'zuordnung');
  assert.equal(ergebnisQuelle({ profil_id: 'k1' }, '095578'), 'zuordnung');
  assert.equal(ergebnisQuelle({ passnummer: '095578' }, null), 'zuordnung',
    'ohne eigene LizenzID kann nichts ueber sie gefunden worden sein');
});

test('quellenZaehlen trennt die beiden Wege ins Profil', () => {
  const rows = [
    { passnummer: '095578' }, { passnummer: '095578' }, { profil_id: 'k1' },
  ];
  assert.deepEqual(quellenZaehlen(rows, '095578'), { lizenz: 2, zuordnung: 1 });
  assert.deepEqual(quellenZaehlen([], '095578'), { lizenz: 0, zuordnung: 0 });
});
