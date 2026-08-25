import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildWettkampf } from '../js/logic/wettkampf-build.js';
import { parseRoster } from '../js/logic/roster-import.js';

const BASE = {
  name: 'Testpokal',
  datum: '2026-08-29',
  preset: 'bohle',
  saetze: 4,
  wuerfeProSatz: 30,
  teilsaetze: ['volle', 'volle'],
  bahnwechsel: 'bohle',
  anlageId: 'anl1',
  anlageName: 'Testhalle',
  anlageBahnen: [
    { id: 'b1', nummer: 1, bahnart: 'bohle' }, { id: 'b2', nummer: 2, bahnart: 'bohle' },
    { id: 'b3', nummer: 3, bahnart: 'bohle' }, { id: 'b4', nummer: 4, bahnart: 'bohle' },
  ],
  playedLanes: [1, 2, 3, 4],
  mannschaften: [
    { id: 'mA', name: 'A', lanes: [1, 2] },
    { id: 'mB', name: 'B', lanes: [3, 4] },
  ],
  spielerJeMannschaft: 6,
};

test('buildWettkampf: 2 Teams je 6 Spieler, 2 Bahnen -> 3 Durchgänge', () => {
  const { wettkampf, games } = buildWettkampf(BASE);
  assert.equal(games.length, 3);
  assert.equal(wettkampf.durchgaenge.length, 3);
  assert.equal(wettkampf.typ, 'sportkegler-wettkampf');
  assert.equal(wettkampf.status, 'setup');
  assert.equal(wettkampf.name, 'Testpokal');
  assert.equal(wettkampf.spielerJeMannschaft, 6);
  // Jeder Durchgang: 4 Spieler (2 pro Team), Bahn-Zuordnung + Bahnart gesetzt.
  games.forEach((g) => {
    assert.equal(g.spiel, 'sportkegler-wk');
    assert.equal(g.config.spielerListe.length, 4);
    assert.equal(g.config.anlageId, 'anl1');
    assert.ok(g.config.bahnZuordnung[1] && g.config.bahnZuordnung[1].id === 'b1');
    assert.ok(Array.isArray(g.config.bahnplan));
  });
  // Durchgang -> gameId Verknüpfung stimmt.
  assert.deepEqual(wettkampf.durchgaenge.map((d) => d.gameId), games.map((g) => g.id));
});

test('buildWettkampf: Wertungskriterien werden am Wettkampf mitgeführt', () => {
  const wertung = { modus: 'duell', gesamtholzPunkte: 2, kriterium2: 'ewp', kriterium2Punkte: 1, ewp: { beste: 'anzahlSpieler', schlechteste: 1, minHolz: 1 }, ewpSchwelle: 31 };
  const { wettkampf } = buildWettkampf({ ...BASE, wertung });
  assert.deepEqual(wettkampf.wertung, wertung);
  // Ohne Angabe bleibt das Feld weg (kein leeres Objekt erzwingen).
  assert.equal(buildWettkampf(BASE).wettkampf.wertung, undefined);
});

test('buildWettkampf: namesByTeamPos füllt echte Namen, sonst Platzhalter', () => {
  const namesByTeamPos = { 'mA|1': 'Arne Schierbaum', 'mB|1': 'Max Mustermann' };
  const { games } = buildWettkampf({ ...BASE, namesByTeamPos });
  // Durchgang 1 sitzt teamPos 1+2 beider Teams.
  const g1 = games[0];
  const namen = g1.config.spielerListe.map((p) => p.name);
  assert.ok(namen.includes('Arne Schierbaum'));
  assert.ok(namen.includes('Max Mustermann'));
  assert.ok(namen.includes('A 2')); // Platzhalter für teamPos 2 ohne echten Namen
});

test('parseRoster -> buildWettkampf: Ende-zu-Ende aus Sportwinner-Roster', () => {
  const roster = {
    seiten: {
      GG: { mannschaft: 'VOK 1', aufstellung: [
        { nachname: 'Schierbaum', vorname: 'Arne', pass: '1', id: 1 },
        { nachname: 'Müller', vorname: 'Tim', pass: '2', id: 2 },
      ] },
      G: { mannschaft: 'SKC 1', aufstellung: [
        { nachname: 'Mustermann', vorname: 'Max', pass: '3', id: 3 },
        { nachname: 'Meier', vorname: 'Jan', pass: '4', id: 4 },
      ] },
    },
    partie: { heim: 'VOK 1', gast: 'SKC 1', datum: '29.08.2026',
      spielort: { anlage: 'Halle X', bahnen: '2 - 5', plz: '49076', ort: 'Osnabrück' } },
  };
  const spec = parseRoster(roster);
  // Anlage-Bahnen für buildWettkampf aus den Roster-Bahnen (bahnart aus Preset).
  const anlageBahnen = spec.anlage.bahnen.map((n, i) => ({ id: `b${i}`, nummer: n, bahnart: 'bohle' }));
  const { wettkampf, games } = buildWettkampf({
    ...spec, preset: 'bohle', saetze: 4, wuerfeProSatz: 30, teilsaetze: ['volle', 'volle'],
    bahnwechsel: 'bohle', anlageId: 'anl', anlageName: spec.anlage.name, anlageBahnen,
  });
  assert.equal(wettkampf.name, 'VOK 1 – SKC 1');
  assert.equal(wettkampf.datum, '2026-08-29');
  assert.equal(spec.spielerJeMannschaft, 2);
  assert.equal(games.length, 1); // 2 Spieler / 2 Bahnen je Team -> 1 Durchgang
  const namen = games[0].config.spielerListe.map((p) => p.name).sort();
  assert.deepEqual(namen, ['Arne Schierbaum', 'Jan Meier', 'Max Mustermann', 'Tim Müller']);
});
