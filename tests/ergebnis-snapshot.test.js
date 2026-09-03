// Der Ergebnis-Snapshot ist die EINZIGE Quelle der Konto-Statistik. Zwei Wege schreiben ihn —
// das Spielende in der Erfassung und das nachträgliche Teilen eines schon fertigen Spiels —
// und beide müssen dieselben Zeilen erzeugen. Genau hier lag ein Fehler: das Teilen schrieb
// gar keine, weshalb ein importierter, geteilter Wettkampf mit Codes und Würfen in der
// Datenbank lag, die eigene Statistik aber leer blieb.

import test from 'node:test';
import assert from 'node:assert/strict';
import { ergebnisZeilen } from '../js/logic/ergebnis-snapshot.js';

const spieler = (n) => ({
  gesamt: n, schnittSatz: n / 2, schnittWurf: n / 20, bester: n, neuner: 1, fehl: 0,
  wurfCount: 20, rang: 1,
});

const basis = { spielId: 'sp-1', spielerIdFuer: (pos) => 'id-' + pos, konto: 'konto-1' };

test('Je Position eine Zeile mit den Kennzahlen', () => {
  const rows = ergebnisZeilen([spieler(500), spieler(480)], basis);
  assert.equal(rows.length, 2);
  assert.equal(rows[0].spiel_id, 'sp-1');
  assert.equal(rows[0].spieler_id, 'id-0');
  assert.equal(rows[0].gesamt, 500);
  assert.equal(rows[1].spieler_id, 'id-1');
});

test('profil_id steht NUR an der eigenen Zeile', () => {
  // Sonst landen auf einem Vereins-PC alle mit erfassten Gegner in der eigenen Statistik.
  const rows = ergebnisZeilen([spieler(500), spieler(480), spieler(460)], { ...basis, ichIndex: 1 });
  assert.deepEqual(rows.map((r) => r.profil_id), [null, 'konto-1', null]);
  // Erfasst hat sie dagegen in jedem Fall ich.
  assert.deepEqual(rows.map((r) => r.erfasst_von), ['konto-1', 'konto-1', 'konto-1']);
});

test('Ohne eigene Position trägt keine Zeile eine profil_id', () => {
  const rows = ergebnisZeilen([spieler(500)], basis);
  assert.equal(rows[0].profil_id, null);
});

test('passnummer steht an jeder Zeile, die eine hat — und fehlt sonst ganz', () => {
  // Darüber findet ein Mitspieler sein Ergebnis auch in einem fremd erfassten Spiel wieder.
  const rows = ergebnisZeilen([spieler(500), spieler(480)],
    { ...basis, passByPos: { 0: '123456' } });
  assert.equal(rows[0].passnummer, '123456');
  assert.equal('passnummer' in rows[1], false, 'leere Spalte würde eine alte DB kippen');
});

test('Positionen ohne Spieler-ID werden übersprungen', () => {
  // In der Erfassung: Spieler, die gerade ein anderes Gerät steuert — deren Zeile schreibt es.
  const rows = ergebnisZeilen([spieler(500), spieler(480), spieler(460)],
    { ...basis, spielerIdFuer: (pos) => (pos === 1 ? null : 'id-' + pos) });
  assert.deepEqual(rows.map((r) => r.spieler_id), ['id-0', 'id-2']);
});

test('Ohne Spieler kommen keine Zeilen heraus', () => {
  assert.deepEqual(ergebnisZeilen([], basis), []);
  assert.deepEqual(ergebnisZeilen(null, basis), []);
});
