import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  WURF_SPALTEN, WURF_SELECT, NUR_EINZELN, erkennerAusZeile, nurGemessenes,
} from '../js/logic/erkennung-zeilen.js';
import { readFileSync } from 'node:fs';

// ── Die Spaltenliste ─────────────────────────────────────────────────────────

test('Kein Tafelbild in der Wurfliste', () => {
  // Der eigentliche Grund für dieses Modul: `board_jpeg` ist ein Base64-JPEG von rund 5 KB
  // je Wurf. In einer Liste von 2000 Würfen wären das 9 MB über die Leitung, nur um eine
  // Tabelle zu zeigen. Der Verlust fällt nicht beim Programmieren auf, sondern am Spieltag
  // im Netz der Halle.
  for (const spalte of NUR_EINZELN) {
    assert.ok(!WURF_SPALTEN.includes(spalte), `${spalte} darf nicht in der Liste stehen`);
    assert.ok(!WURF_SELECT.includes(spalte));
  }
});

test('Die Liste trägt alles, was die Zuordnung braucht', () => {
  for (const spalte of ['id', 'erkenner_id', 'lane', 'pins_count', 'pins', 'recorded_at']) {
    assert.ok(WURF_SPALTEN.includes(spalte), `${spalte} fehlt`);
  }
  // Und die Hälfte, die die App selbst schreibt — ohne sie wüsste niemand, was schon
  // übernommen wurde.
  for (const spalte of ['spiel_id', 'satz_block_id', 'wurf_index', 'verworfen_grund']) {
    assert.ok(WURF_SPALTEN.includes(spalte), `${spalte} fehlt`);
  }
});

test('WURF_SELECT ist die Liste in PostgREST-Form', () => {
  assert.equal(WURF_SELECT, WURF_SPALTEN.join(', '));
  assert.ok(!/,,|,\s*$/.test(WURF_SELECT), 'keine leeren Felder');
});

// ── Der Erkenner ─────────────────────────────────────────────────────────────

test('Aus der Erkenner-Zeile wird die Bahn-NUMMER, nicht die id', () => {
  // Die Zuordnung übersetzt eine gemeldete `lane` über `bahn_nummer`. Käme hier die id der
  // Bahn an, wäre die Übersetzung stillschweigend wirkungslos — eine uuid ist nie eine
  // Bahnnummer, und auffallen würde es erst an falsch zugeordneten Sätzen.
  const e = erkennerAusZeile({
    id: 'e1', name: 'Bahn-Rechner', aktiv: true, anlage_id: 'a1',
    bahn_zuordnung: { 1: 2 }, bahn: { nummer: 5 },
  });

  assert.equal(e.bahn_nummer, 5);
  assert.deepEqual(e.bahn_zuordnung, { 1: 2 });
});

test('Ohne gekoppelte Bahn bleibt bahn_nummer leer', () => {
  // Der Normalfall: eine Kamera sieht alle vier Tafeln. Dann steht die Bahn in jeder Zeile.
  const e = erkennerAusZeile({ id: 'e1', anlage_id: 'a1', bahn: null });

  assert.equal(e.bahn_nummer, null);
  assert.deepEqual(e.bahn_zuordnung, {});
});

test('Ein mobiler Erkenner ohne Anlage ist gültig', () => {
  const e = erkennerAusZeile({ id: 'e2', name: 'Telefon', aktiv: true, anlage_id: null });

  assert.equal(e.anlage_id, null);
  assert.equal(e.aktiv, true);
});

test('aktiv nur dann false, wenn es wirklich false ist', () => {
  // `aktiv` ist der Aus-Schalter. Fehlt die Spalte in einer Antwort (alte DB, schmaler
  // select), darf der Erkenner nicht stillschweigend als abgeschaltet gelten.
  assert.equal(erkennerAusZeile({ id: 'e' }).aktiv, true);
  assert.equal(erkennerAusZeile({ id: 'e', aktiv: false }).aktiv, false);
});

test('Nichts hinein, null heraus', () => {
  assert.equal(erkennerAusZeile(null), null);
});

// ── Das Sieb für Realtime ────────────────────────────────────────────────────

test('Realtime-Zeilen kommen ohne Tafelbild in die App', () => {
  // Realtime liefert die GANZE eingefügte Zeile — eine Spaltenauswahl wie beim Abfragen
  // gibt es dort nicht. Ohne dieses Sieb lägen die Bilder im Puffer der App.
  const zeile = {
    id: 7, erkenner_id: 'e1', lane: 3, pins_count: 9, pins: [1, 2, 3, 4, 5, 6, 7, 8, 9],
    recorded_at: '2026-11-11T19:00:00Z', video_time_s: 12.5, video_id: 'stream',
    spiel_id: null, satz_block_id: null, wurf_index: null, uebernommen_am: null,
    verworfen_grund: null,
    board_jpeg: 'x'.repeat(5000), board_before_jpeg: 'y'.repeat(5000),
    displayed_total: 123, displayed_pin_count: 9,
  };

  const gesiebt = nurGemessenes(zeile);

  assert.ok(!('board_jpeg' in gesiebt));
  assert.ok(!('board_before_jpeg' in gesiebt));
  assert.ok(!('displayed_total' in gesiebt), 'Ablesungen sind Beleg, nicht Eingabe');
  assert.equal(gesiebt.pins_count, 9);
  assert.deepEqual(gesiebt.pins, [1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.equal(gesiebt.lane, 3);
  assert.equal(JSON.stringify(gesiebt).length < 400, true, 'die Zeile bleibt klein');
});

test('Fehlende Felder werden nicht erfunden', () => {
  const gesiebt = nurGemessenes({ id: 1, lane: 2, pins_count: 0 });

  assert.deepEqual(Object.keys(gesiebt).sort(), ['id', 'lane', 'pins_count']);
});

test('Nichts hinein, leer heraus', () => {
  assert.deepEqual(nurGemessenes(null), {});
});

// ── Gegen das Schema ─────────────────────────────────────────────────────────

test('Jede Spalte der Liste gibt es in erkannter_wurf wirklich', () => {
  // PostgREST lehnt eine Abfrage mit unbekannter Spalte komplett ab (42703) — und zwar
  // erst auf der Leitung. Ein Tippfehler oder eine umbenannte Spalte fiele also erst im
  // Betrieb auf. Deshalb liest dieser Test das Schema mit, so wie es der Python-Test der
  // Senke auf der anderen Seite tut.
  const schema = readFileSync(new URL('../supabase/schema.sql', import.meta.url), 'utf8');
  const anfang = schema.indexOf('create table if not exists erkannter_wurf');
  assert.ok(anfang > 0, 'Tabelle im Schema gefunden');

  const spalten = new Set();
  for (const zeile of schema.slice(anfang).split('\n').slice(1)) {
    const ohneKommentar = zeile.split('--')[0].trim();
    if (ohneKommentar.startsWith(')')) break;
    if (!ohneKommentar) continue;
    spalten.add(ohneKommentar.split(/\s+/)[0].replace(/,$/, ''));
  }

  for (const s of [...WURF_SPALTEN, ...NUR_EINZELN]) {
    assert.ok(spalten.has(s), `Spalte ${s} steht nicht in erkannter_wurf`);
  }
});
