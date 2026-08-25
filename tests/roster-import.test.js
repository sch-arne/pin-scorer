import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseRoster, parseBahnen, germanDateToISO, splitLanes, sektionToBahnart, teamLanesByBahnart,
} from '../js/logic/roster-import.js';

test('parseBahnen: Bereich, Liste, Einzel, leer', () => {
  assert.deepEqual(parseBahnen('2 - 5'), [2, 3, 4, 5]);
  assert.deepEqual(parseBahnen('2-5'), [2, 3, 4, 5]);
  assert.deepEqual(parseBahnen('5 - 2'), [2, 3, 4, 5]); // verdreht -> sortiert
  assert.deepEqual(parseBahnen('2, 3, 4, 5'), [2, 3, 4, 5]);
  assert.deepEqual(parseBahnen('4'), [4]);
  assert.deepEqual(parseBahnen(''), []);
  assert.deepEqual(parseBahnen(null), []);
});

test('germanDateToISO', () => {
  assert.equal(germanDateToISO('29.08.2026'), '2026-08-29');
  assert.equal(germanDateToISO('1.2.2026'), '2026-02-01');
  assert.equal(germanDateToISO(''), '');
  assert.equal(germanDateToISO('2026-08-29'), '');
  assert.equal(germanDateToISO('32.01.2026'), '');
});

test('splitLanes: 4 Bahnen auf 2 Teams -> [1,2] und [3,4]', () => {
  assert.deepEqual(splitLanes(2, [1, 2, 3, 4]), [[1, 2], [3, 4]]);
  assert.deepEqual(splitLanes(2, [2, 3, 4, 5]), [[2, 3], [4, 5]]);
});

test('teamLanesByBahnart: 4 Bahnen, 2 Teams -> Muster je Bahnart', () => {
  // classic: Heim ungerade (1,3), Gast gerade (2,4)
  assert.deepEqual(teamLanesByBahnart('classic', [1, 2, 3, 4]), [[1, 3], [2, 4]]);
  // schere: Heim gerade (2,4), Gast ungerade (1,3)
  assert.deepEqual(teamLanesByBahnart('schere', [1, 2, 3, 4]), [[2, 4], [1, 3]]);
  // bohle: Heim außen (1,4), Gast innen (2,3)
  assert.deepEqual(teamLanesByBahnart('bohle', [1, 2, 3, 4]), [[1, 4], [2, 3]]);
  // unsortiert -> gleiches Ergebnis
  assert.deepEqual(teamLanesByBahnart('classic', [4, 2, 1, 3]), [[1, 3], [2, 4]]);
});

test('teamLanesByBahnart: Fallback zusammenhängend (n<4, unbekannte Bahnart, ≠2 Teams)', () => {
  assert.deepEqual(teamLanesByBahnart('classic', [1, 2]), [[1], [2]]);       // n<4
  assert.deepEqual(teamLanesByBahnart('bohle', [1, 2]), [[1], [2]]);          // n<4
  assert.deepEqual(teamLanesByBahnart(null, [1, 2, 3, 4]), [[1, 2], [3, 4]]); // keine Bahnart
  assert.deepEqual(teamLanesByBahnart('classic', [1, 2, 3, 4], 3), [[1], [2], [3, 4]]); // ≠2 Teams
});

const ROSTER = {
  spielNr: 2,
  seiten: {
    GG: {
      rolle: 'gastgeber',
      mannschaft: 'VOK Osnabrück 1',
      aufstellung: [
        { pos: 0, nachname: 'Schierbaum', vorname: 'Arne', pass: '095578', id: 93408, bahnen: [] },
        { pos: 1, nachname: 'Müller', vorname: 'Tim', pass: '095579', id: 93409, bahnen: [] },
      ],
    },
    G: {
      rolle: 'gast',
      mannschaft: 'SKC Greste-Lage 1',
      aufstellung: [
        { pos: 0, nachname: 'Mustermann', vorname: 'Max', pass: '088123', id: 71204, bahnen: [] },
      ],
    },
  },
  partie: {
    liga: 'Herren – 2. Bundesliga Nord',
    datum: '29.08.2026',
    uhrzeit: '12:30',
    spielId: '328202',
    ergebnis: '',
    heim: 'VOK Osnabrück 1',
    gast: 'SKC Greste-Lage 1',
    spielort: {
      anlage: 'Kegelcenter "Im Schütting"', strasse: 'Natruper Str. 133', plz: '49076', ort: 'Osnabrück',
      bahnen: '2 - 5', adresse: 'Kegelcenter "Im Schütting", Natruper Str. 133, 49076 Osnabrück',
    },
  },
};

test('parseRoster: Teams (GG=Heim zuerst), Datum, Anlage aus Spielort', () => {
  const s = parseRoster(ROSTER);
  assert.equal(s.mannschaften.length, 2);
  assert.equal(s.mannschaften[0].key, 'GG');
  assert.equal(s.mannschaften[0].name, 'VOK Osnabrück 1');
  assert.equal(s.mannschaften[1].name, 'SKC Greste-Lage 1');
  assert.equal(s.datum, '2026-08-29');
  assert.equal(s.name, 'VOK Osnabrück 1 – SKC Greste-Lage 1');

  // Anlage aus dem Spielort der Heim-Mannschaft.
  assert.equal(s.anlage.name, 'Kegelcenter "Im Schütting"');
  assert.equal(s.anlage.plz, '49076');
  assert.equal(s.anlage.ort, 'Osnabrück');
  assert.deepEqual(s.anlage.bahnen, [2, 3, 4, 5]);
  assert.equal(s.anlage.ausSpielort, true);
  assert.deepEqual(s.playedLanes, [2, 3, 4, 5]);

  // Spieler je Mannschaft = Maximum beider Aufstellungen; kürzere Seite behält Platzhalter.
  assert.equal(s.spielerJeMannschaft, 2);

  // Startbahnen: Heim [2,3], Gast [4,5].
  assert.deepEqual(s.mannschaften[0].lanes, [2, 3]);
  assert.deepEqual(s.mannschaften[1].lanes, [4, 5]);

  // Namen-Map (Team-Position -> echter Name).
  const gg = s.mannschaften[0];
  assert.equal(s.namesByTeamPos[`${gg.id}|1`], 'Arne Schierbaum');
  assert.equal(s.namesByTeamPos[`${gg.id}|2`], 'Tim Müller');
  const g = s.mannschaften[1];
  assert.equal(s.namesByTeamPos[`${g.id}|1`], 'Max Mustermann');
  assert.equal(s.namesByTeamPos[`${g.id}|2`], undefined); // nur 1 Spieler
});

test('parseRoster: ohne Spielort -> Fallback-Anlage + Standardbahnen 1–4', () => {
  const { partie, ...ohnePartie } = ROSTER;
  const s = parseRoster(ohnePartie);
  assert.equal(s.anlage.ausSpielort, false);
  assert.equal(s.anlage.name, 'VOK Osnabrück 1 (Heim)');
  assert.deepEqual(s.anlage.bahnen, [1, 2, 3, 4]);
  assert.ok(typeof s.datum === 'string' && s.datum.length === 10); // heutiges Datum
  assert.equal(s.partie, null);
});

test('parseRoster: leere Aufstellung -> Warnung, spielerJeMannschaft>=1', () => {
  const leer = { seiten: { GG: { mannschaft: 'A', aufstellung: [] }, G: { mannschaft: 'B', aufstellung: [] } } };
  const s = parseRoster(leer);
  assert.equal(s.spielerJeMannschaft, 1);
  assert.ok(s.warnungen.some((w) => /Aufstellung/i.test(w)));
});

test('parseRoster: ohne seiten wirft', () => {
  assert.throws(() => parseRoster({}), /seiten/i);
});

test('sektionToBahnart: 1=Classic, 2=Schere, sonst null', () => {
  assert.equal(sektionToBahnart(1), 'classic');
  assert.equal(sektionToBahnart('1'), 'classic');
  assert.equal(sektionToBahnart(2), 'schere');
  assert.equal(sektionToBahnart('2'), 'schere');
  assert.equal(sektionToBahnart(0), null);
  assert.equal(sektionToBahnart(null), null);
  assert.equal(sektionToBahnart(undefined), null);
});

test('parseRoster: Sektion 2 -> Bahnart Schere (vorgewählt + durchgereicht)', () => {
  const mitSektion = { ...ROSTER, partie: { ...ROSTER.partie, sektion: 2 } };
  const s = parseRoster(mitSektion);
  assert.equal(s.bahnart, 'schere');
  assert.equal(s.partie.sektion, 2);
});

test('parseRoster: ohne Sektion -> bahnart null (Import fällt auf Bohle zurück)', () => {
  const s = parseRoster(ROSTER); // ROSTER.partie hat kein sektion-Feld
  assert.equal(s.bahnart, null);
  assert.equal(s.partie.sektion, null);
});
