import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fehlerText } from '../js/util.js';

// fehlerText steht hinter jeder Sync-Fehlermeldung (Teilen, Beitreten). Bisher zeigten die
// Views pauschal „online?" — dahinter verschwanden fehlende Anmeldung, RLS-Ablehnung und eine
// nicht eingespielte SQL-Migration ununterscheidbar.
test('fehlerText: PostgREST-Fehler -> Meldung + Code', () => {
  const e = { message: "Could not find the 'passnummer' column of 'spiel_spieler'", code: 'PGRST204' };
  assert.equal(fehlerText(e), "Could not find the 'passnummer' column of 'spiel_spieler' (PGRST204)");
});

test('fehlerText: RLS-Ablehnung ohne message -> details', () => {
  const e = { message: '', details: 'new row violates row-level security policy', code: '42501' };
  assert.equal(fehlerText(e), 'new row violates row-level security policy (42501)');
});

test('fehlerText: normaler Error ohne Code', () => {
  assert.equal(fehlerText(new Error('nicht angemeldet')), 'nicht angemeldet');
});

test('fehlerText: nichts Verwertbares -> Fallback', () => {
  assert.equal(fehlerText(null, 'online?'), 'online?');
  assert.equal(fehlerText({}, 'online?'), 'online?');
});
