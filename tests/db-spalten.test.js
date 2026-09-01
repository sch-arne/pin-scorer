import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  istUnbekannteSpalte, ohneSpalten, schreibeVertraeglich, neuerSpaltenSpeicher,
} from '../js/logic/db-spalten.js';

// Der echte PostgREST-Fehler, an dem das Teilen gegen eine noch nicht migrierte DB scheitert.
const PGRST204 = {
  code: 'PGRST204',
  message: "Could not find the 'passnummer' column of 'spiel_spieler' in the schema cache",
};

test('istUnbekannteSpalte: PostgREST PGRST204 und Postgres 42703', () => {
  assert.equal(istUnbekannteSpalte(PGRST204), true);
  assert.equal(istUnbekannteSpalte({ code: '42703', message: 'column "erfasst_von" does not exist' }), true);
});

test('istUnbekannteSpalte: andere Fehler NICHT abfangen', () => {
  // RLS-Ablehnung und Constraint-Verletzungen müssen weiterhin durchschlagen — sie durch
  // Weglassen einer Spalte "reparieren" zu wollen, würde echte Fehler verschleiern.
  assert.equal(istUnbekannteSpalte({ code: '42501', message: 'new row violates row-level security policy' }), false);
  assert.equal(istUnbekannteSpalte({ code: '23505', message: 'duplicate key value' }), false);
  assert.equal(istUnbekannteSpalte(null), false);
});

test('ohneSpalten entfernt nur die genannten Schlüssel und lässt die Eingabe unberührt', () => {
  const rows = [{ position: 0, name: 'A', passnummer: '000000', profil_id: 'u1' }];
  const out = ohneSpalten(rows, ['passnummer']);
  assert.deepEqual(out, [{ position: 0, name: 'A', profil_id: 'u1' }]);
  assert.equal(rows[0].passnummer, '000000');
});

test('schreibeVertraeglich: DB kennt die Spalte -> genau ein Versuch, Zeilen unverändert', async () => {
  const versuche = [];
  const res = await schreibeVertraeglich('spiel_spieler', [{ name: 'A', passnummer: '1' }], ['passnummer'],
    (rs) => { versuche.push(rs); return { data: rs, error: null }; },
    { speicher: neuerSpaltenSpeicher() });
  assert.equal(versuche.length, 1);
  assert.deepEqual(versuche[0], [{ name: 'A', passnummer: '1' }]);
  assert.equal(res.error, null);
});

test('schreibeVertraeglich: unbekannte Spalte -> zweiter Versuch ohne sie gelingt', async () => {
  const versuche = [];
  const hinweise = [];
  const res = await schreibeVertraeglich('spiel_spieler', [{ name: 'A', passnummer: '1' }], ['passnummer'],
    (rs) => {
      versuche.push(rs);
      return 'passnummer' in rs[0] ? { data: null, error: PGRST204 } : { data: rs, error: null };
    },
    { speicher: neuerSpaltenSpeicher(), onFallback: (t) => hinweise.push(t) });
  assert.equal(versuche.length, 2);
  assert.deepEqual(versuche[1], [{ name: 'A' }]);
  assert.equal(res.error, null);
  assert.deepEqual(hinweise, ['spiel_spieler']);
});

test('schreibeVertraeglich: die fehlende Spalte wird gemerkt — kein zweiter Fehlversuch', async () => {
  const speicher = neuerSpaltenSpeicher();
  const run = (rs) => ('passnummer' in rs[0] ? { data: null, error: PGRST204 } : { data: rs, error: null });
  const versuche = [];
  const zaehlend = (rs) => { versuche.push(rs); return run(rs); };
  await schreibeVertraeglich('spiel_spieler', [{ name: 'A', passnummer: '1' }], ['passnummer'], zaehlend, { speicher });
  await schreibeVertraeglich('spiel_spieler', [{ name: 'B', passnummer: '2' }], ['passnummer'], zaehlend, { speicher });
  assert.equal(versuche.length, 3);           // 1. Aufruf: Fehlversuch + Wiederholung, 2. Aufruf: direkt ohne
  assert.deepEqual(versuche[2], [{ name: 'B' }]);
});

test('schreibeVertraeglich: echter Fehler wird NICHT durch Weglassen kaschiert', async () => {
  const rls = { code: '42501', message: 'new row violates row-level security policy' };
  let n = 0;
  const res = await schreibeVertraeglich('spiel_spieler', [{ name: 'A', passnummer: '1' }], ['passnummer'],
    () => { n += 1; return { data: null, error: rls }; }, { speicher: neuerSpaltenSpeicher() });
  assert.equal(n, 1);
  assert.equal(res.error, rls);
});
