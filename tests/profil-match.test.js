import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  normalisiere, vereinMatcht, partiePasst, nameMatcht, meineKeys, profilVollstaendig,
} from '../js/logic/profil-match.js';

const PROFIL = { vorname: 'Arne', nachname: 'Schierbaum', verein: 'VOK Osnabrück' };

// Ein Spec, wie buildImportSpec es liefert: zwei Mannschaften, Namen in der Schreibweise
// des Ergebnisdienstes ("Nachname, Vorname"). Im Gegnerteam steht ein Namensvetter.
const SPEC = {
  mannschaften: [
    {
      id: 'mA',
      name: 'VOK Osnabrück 1',
      spieler: [
        { teamPos: 1, name: 'Meier, Jens' },
        { teamPos: 2, name: 'Schierbaum, Arne' },
      ],
    },
    {
      id: 'mB',
      name: 'SKC Greste-Lage 2',
      spieler: [
        { teamPos: 1, name: 'Schierbaum, Arne' },   // Namensvetter beim Gegner
        { teamPos: 2, name: 'Hartnack, Nils' },
      ],
    },
  ],
};

// --- normalisiere ------------------------------------------------------------

test('normalisiere faltet Umlaute, Satzzeichen und Mehrfach-Leerzeichen', () => {
  assert.equal(normalisiere('VOK Osnabrück'), 'vok osnabruck');
  assert.equal(normalisiere('  SKC  Greste-Lage '), 'skc greste lage');
  assert.equal(normalisiere('Schierbaum, Arne'), 'schierbaum arne');
  assert.equal(normalisiere(null), '');
});

// --- vereinMatcht ------------------------------------------------------------

test('Mannschaftsnummer des Ergebnisdienstes stoert den Vereinsabgleich nicht', () => {
  assert.ok(vereinMatcht('VOK Osnabrück 1', 'VOK Osnabrück'));
  assert.ok(vereinMatcht('VOK Osnabrück 2', 'VOK Osnabrück'));
  assert.ok(vereinMatcht('SKC Greste-Lage III', 'SKC Greste-Lage'));
  // auch andersherum: im Profil steht die Mannschaft, beim Dienst der Verein
  assert.ok(vereinMatcht('VOK Osnabrück', 'VOK Osnabrück 1'));
});

test('Vereinsabgleich ist tolerant gegen Schreibweise, nicht gegen andere Vereine', () => {
  assert.ok(vereinMatcht('VOK Osnabrueck 1', 'VOK Osnabrueck'));
  assert.ok(vereinMatcht('VOK Osnabrück 1', 'vok  osnabruck'));
  assert.ok(vereinMatcht('VOK Osnabrück 1', 'Osnabrück'));       // Teil des Namens genuegt
  assert.ok(!vereinMatcht('SKC Greste-Lage 1', 'VOK Osnabrück'));
  assert.ok(!vereinMatcht('VOK Osnabrück 1', ''));
});

test('zu kurze Vereinsnamen greifen nicht (sonst passt „SV" auf halb Deutschland)', () => {
  assert.ok(!vereinMatcht('SV Bad Essen 1', 'SV'));
  assert.ok(!vereinMatcht('SV', 'SV Bad Essen'));
});

test('partiePasst prueft Heim UND Gast', () => {
  const partie = { heim: 'SKC Greste-Lage 1', gast: 'VOK Osnabrück 2' };
  assert.ok(partiePasst(partie, 'VOK Osnabrück'));
  assert.ok(partiePasst({ heim: 'VOK Osnabrück 1', gast: 'SV Bad Essen 1' }, 'VOK Osnabrück'));
  assert.ok(!partiePasst(partie, 'SV Bad Essen'));
  assert.ok(!partiePasst(null, 'VOK Osnabrück'));
});

// --- nameMatcht --------------------------------------------------------------

test('Name trifft in beiden Schreibrichtungen', () => {
  assert.ok(nameMatcht('Schierbaum, Arne', PROFIL));
  assert.ok(nameMatcht('Arne Schierbaum', PROFIL));
  assert.ok(nameMatcht('SCHIERBAUM, ARNE', PROFIL));
});

test('abgekuerzter Vorname in der Aufstellung zaehlt, im Profil nicht', () => {
  assert.ok(nameMatcht('Schierbaum, A.', PROFIL));
  assert.ok(!nameMatcht('Schierbaum, B.', PROFIL));
  // Umgekehrt: wer sich selbst nur "A." ins Profil schreibt, trifft den vollen Namen nicht.
  assert.ok(!nameMatcht('Schierbaum, Arne', { vorname: 'A', nachname: 'Schierbaum' }));
});

test('Doppelnamen und zweite Vornamen bleiben zuordenbar', () => {
  const p = { vorname: 'Anna Maria', nachname: 'Meyer-Schmidt' };
  assert.ok(nameMatcht('Meyer-Schmidt, Anna Maria', p));
  assert.ok(nameMatcht('Meyer Schmidt, Anna Maria', p));
  // Der zweite Vorname fehlt in der Aufstellung -> kein Treffer (bewusst streng).
  assert.ok(!nameMatcht('Meyer-Schmidt, Anna', p));
});

test('Nachname allein genuegt nicht — Bruder und Vater waeren sonst dieselbe Person', () => {
  assert.ok(!nameMatcht('Schierbaum, Nils', PROFIL));
  assert.ok(!nameMatcht('Hartnack, Arne', PROFIL));
});

test('ohne Vor- oder Nachnamen im Profil gibt es keinen Treffer', () => {
  assert.ok(!nameMatcht('Schierbaum, Arne', { nachname: 'Schierbaum' }));
  assert.ok(!nameMatcht('Schierbaum, Arne', { vorname: 'Arne' }));
  assert.ok(!nameMatcht('Schierbaum, Arne', null));
  assert.ok(!nameMatcht('', PROFIL));
});

// --- meineKeys ---------------------------------------------------------------

test('meineKeys findet die eigene Zeile in der eigenen Mannschaft', () => {
  assert.deepEqual(meineKeys(SPEC, PROFIL), ['mA|2']);
});

test('ein gleichnamiger Gegner ist NICHT meine Zeile', () => {
  // Der Namensvetter steht auf mB|1 — ohne die Vereinsbedingung waere er waehlbar.
  assert.ok(!meineKeys(SPEC, PROFIL).includes('mB|1'));
});

test('meineKeys liefert im Paarkreuz mehrere Positionen', () => {
  const spec = {
    mannschaften: [{
      id: 'mA',
      name: 'VOK Osnabrück 1',
      spieler: [
        { teamPos: 1, name: 'Schierbaum, Arne' },
        { teamPos: 3, name: 'Schierbaum, Arne' },
      ],
    }],
  };
  assert.deepEqual(meineKeys(spec, PROFIL), ['mA|1', 'mA|3']);
});

test('fremder Verein oder fehlendes Profil ergeben keine Zeile', () => {
  assert.deepEqual(meineKeys(SPEC, { ...PROFIL, verein: 'SV Bad Essen' }), []);
  assert.deepEqual(meineKeys(SPEC, { ...PROFIL, nachname: 'Hartnack' }), []);
  assert.deepEqual(meineKeys(SPEC, null), []);
  assert.deepEqual(meineKeys(null, PROFIL), []);
});

// --- profilVollstaendig ------------------------------------------------------

test('profilVollstaendig benennt genau die fehlenden Felder', () => {
  assert.deepEqual(profilVollstaendig(PROFIL), { ok: true, fehlend: [] });
  assert.deepEqual(profilVollstaendig({ vorname: 'Arne' }),
    { ok: false, fehlend: ['Nachname', 'Verein'] });
  assert.deepEqual(profilVollstaendig(null),
    { ok: false, fehlend: ['Vorname', 'Nachname', 'Verein'] });
  // Ein zu kurzer Vereinsname zaehlt wie keiner — er wuerde ohnehin nie matchen.
  assert.deepEqual(profilVollstaendig({ ...PROFIL, verein: 'SV' }),
    { ok: false, fehlend: ['Verein'] });
});
