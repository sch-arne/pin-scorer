// Der Papierkorb: welche verborgen-Zeilen als zurückholbarer Eintrag gelten und welche
// nicht — die Entscheidung selbst (logic/papierkorb.js) ohne Store, DOM und Netz.

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  AUFBEWAHRUNG_TAGE, restTage, imPapierkorb, papierkorbEintraege, PAPIERKORB_HINWEIS,
} from '../js/logic/papierkorb.js';

const TAG = 24 * 60 * 60 * 1000;
const JETZT = Date.parse('2026-09-08T12:00:00Z');
const vorTagen = (n) => new Date(JETZT - n * TAG).toISOString();

test('Die Frist läuft in Tagen, aufgerundet', () => {
  assert.equal(restTage(vorTagen(0), JETZT), AUFBEWAHRUNG_TAGE);
  assert.equal(restTage(vorTagen(1), JETZT), 13);
  assert.equal(restTage(vorTagen(13.5), JETZT), 1);  // angebrochener Tag zählt noch ganz
  assert.equal(restTage(vorTagen(14), JETZT), 0);
  assert.equal(restTage(vorTagen(30), JETZT), 0);
});

test('Ohne lesbares Datum gilt der Eintrag als abgelaufen', () => {
  assert.equal(restTage(null, JETZT), 0);
  assert.equal(restTage('kein Datum', JETZT), 0);
  assert.equal(imPapierkorb(undefined, JETZT), false);
});

test('Nach der Frist verschwindet der Eintrag aus dem Papierkorb', () => {
  const rows = [
    { art: 'spiel', objekt_id: 's1', verborgen_am: vorTagen(2) },
    { art: 'spiel', objekt_id: 's2', verborgen_am: vorTagen(20) },
  ];
  const spiele = { s1: { id: 's1' }, s2: { id: 's2' } };
  const eintraege = papierkorbEintraege(rows, { spiele, jetzt: JETZT });
  assert.deepEqual(eintraege.map((e) => e.id), ['s1']);
  assert.equal(eintraege[0].restTage, 12);
});

test('Zuletzt Entferntes steht oben', () => {
  const rows = [
    { art: 'spiel', objekt_id: 'alt', verborgen_am: vorTagen(9) },
    { art: 'spiel', objekt_id: 'neu', verborgen_am: vorTagen(1) },
    { art: 'spiel', objekt_id: 'mittel', verborgen_am: vorTagen(4) },
  ];
  const spiele = { alt: { id: 'alt' }, neu: { id: 'neu' }, mittel: { id: 'mittel' } };
  const eintraege = papierkorbEintraege(rows, { spiele, jetzt: JETZT });
  assert.deepEqual(eintraege.map((e) => e.id), ['neu', 'mittel', 'alt']);
});

test('Ein Wettkampf ist EIN Eintrag — seine Durchgänge tauchen nicht einzeln auf', () => {
  // verbergeWettkampf schreibt den Wettkampf UND jeden Durchgang in `verborgen`.
  const rows = [
    { art: 'wettkampf', objekt_id: 'w1', verborgen_am: vorTagen(1) },
    { art: 'spiel', objekt_id: 'd1', verborgen_am: vorTagen(1) },
    { art: 'spiel', objekt_id: 'd2', verborgen_am: vorTagen(1) },
  ];
  const spiele = { d1: { id: 'd1', wettkampf_id: 'w1' }, d2: { id: 'd2', wettkampf_id: 'w1' } };
  const wettkaempfe = { w1: { id: 'w1', name: 'Punktspiel' } };
  const eintraege = papierkorbEintraege(rows, { spiele, wettkaempfe, jetzt: JETZT });
  assert.equal(eintraege.length, 1);
  assert.equal(eintraege[0].art, 'wettkampf');
  assert.equal(eintraege[0].objekt.name, 'Punktspiel');
});

test('Ein einzeln entfernter Durchgang bleibt ein eigener Eintrag', () => {
  // Sein Wettkampf liegt NICHT im Papierkorb — dann gibt es nichts, worunter er gehörte.
  const rows = [{ art: 'spiel', objekt_id: 'd1', verborgen_am: vorTagen(1) }];
  const spiele = { d1: { id: 'd1', wettkampf_id: 'w1' } };
  const eintraege = papierkorbEintraege(rows, { spiele, jetzt: JETZT });
  assert.deepEqual(eintraege.map((e) => e.id), ['d1']);
});

test('Ohne Gegenstück in der Datenbank gibt es nichts zurückzuholen', () => {
  const rows = [
    { art: 'spiel', objekt_id: 's1', verborgen_am: vorTagen(1) },
    { art: 'wettkampf', objekt_id: 'w9', verborgen_am: vorTagen(1) },
  ];
  const eintraege = papierkorbEintraege(rows, { spiele: {}, wettkaempfe: {}, jetzt: JETZT });
  assert.deepEqual(eintraege, []);
});

test('Kaputte Eingaben kippen den Papierkorb nicht', () => {
  assert.deepEqual(papierkorbEintraege(null), []);
  assert.deepEqual(papierkorbEintraege([null, {}, { art: 'spiel' }], { jetzt: JETZT }), []);
});

test('Der Hinweis sagt beide Hälften: zurückholbar, aber nicht von selbst zurück', () => {
  assert.match(PAPIERKORB_HINWEIS, new RegExp(`${AUFBEWAHRUNG_TAGE} Tagen`));
  assert.match(PAPIERKORB_HINWEIS, /Zurückholen/);
  assert.match(PAPIERKORB_HINWEIS, /ausgeblendet bleibt er/);
});
