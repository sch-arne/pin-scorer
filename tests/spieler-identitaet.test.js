import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  slotKey, passByPosition, resolveIchIndex, ichSlotAusRoster, mergeSpielerNamen,
  istLizenzWettkampf, anonymeSpielerListe,
} from '../js/logic/spieler-identitaet.js';

// Ein Durchgang mit 4 Positionen aus 2 Mannschaften (wie buildDurchgangGame ihn baut).
const CONFIG = {
  spielerListe: [
    { name: 'Anna Adam', startBahn: 1, mannschaftId: 'mA', teamPos: 1 },
    { name: 'Bernd Berg', startBahn: 2, mannschaftId: 'mB', teamPos: 1 },
    { name: 'Cem Celik', startBahn: 3, mannschaftId: 'mA', teamPos: 2 },
    { name: 'Dora Dietz', startBahn: 4, mannschaftId: 'mB', teamPos: 2 },
  ],
};

const SW = {
  spielNr: 7,
  seiten: { mA: 'GG', mB: 'G' },
  spieler: [
    { mannschaftId: 'mA', teamPos: 1, slot: 0, pass: '095578', extId: 11 },
    { mannschaftId: 'mB', teamPos: 1, slot: 0, pass: '100200', extId: 12 },
    { mannschaftId: 'mA', teamPos: 2, slot: 1, pass: '', extId: 13 },     // ohne Pass
    { mannschaftId: 'mB', teamPos: 2, slot: 1, pass: '300400', extId: 14 },
  ],
};

test('slotKey: Team-Zuordnung -> Schlüssel, Einzelspiel -> null', () => {
  assert.equal(slotKey({ mannschaftId: 'mA', teamPos: 3 }), 'mA|3');
  assert.equal(slotKey({ name: 'Solo' }), null);
  assert.equal(slotKey(null), null);
});

test('passByPosition: löst über mannschaftId|teamPos auf, überspringt leere Pässe', () => {
  const map = passByPosition(CONFIG, SW);
  assert.deepEqual(map, { 0: '095578', 1: '100200', 3: '300400' });
  assert.equal(map[2], undefined); // Cem hat keinen Pass im Roster
});

test('passByPosition: kein Roster -> leeres Objekt', () => {
  assert.deepEqual(passByPosition(CONFIG, null), {});
  assert.deepEqual(passByPosition(CONFIG, { spieler: [] }), {});
});

test('passByPosition: folgt der Position, nicht dem Namen (Umbenennung schadet nicht)', () => {
  const umbenannt = {
    spielerListe: CONFIG.spielerListe.map((sp) => ({ ...sp, name: 'Gast ' + sp.teamPos })),
  };
  assert.deepEqual(passByPosition(umbenannt, SW), { 0: '095578', 1: '100200', 3: '300400' });
});

test('resolveIchIndex: automatisch über die eigene LizenzID', () => {
  const passByPos = passByPosition(CONFIG, SW);
  assert.equal(resolveIchIndex(CONFIG, { passByPos, meinePass: '300400' }), 3);
  assert.equal(resolveIchIndex(CONFIG, { passByPos, meinePass: ' 095578 ' }), 0);
});

test('resolveIchIndex: fremde/fehlende LizenzID -> null', () => {
  const passByPos = passByPosition(CONFIG, SW);
  assert.equal(resolveIchIndex(CONFIG, { passByPos, meinePass: '999999' }), null);
  assert.equal(resolveIchIndex(CONFIG, { passByPos, meinePass: null }), null);
  assert.equal(resolveIchIndex(CONFIG, {}), null);
});

test('resolveIchIndex: ichSlot gilt über Durchgänge hinweg (andere Position)', () => {
  // Zweiter Durchgang: dieselben Spieler, andere Reihenfolge.
  const dg2 = {
    spielerListe: [
      { name: 'Dora Dietz', mannschaftId: 'mB', teamPos: 2 },
      { name: 'Anna Adam', mannschaftId: 'mA', teamPos: 1 },
    ],
  };
  assert.equal(resolveIchIndex(dg2, { ichSlot: 'mA|1' }), 1);
  assert.equal(resolveIchIndex(CONFIG, { ichSlot: 'mA|1' }), 0);
});

test('resolveIchIndex: ichSlot, der in diesem Durchgang nicht antritt -> null', () => {
  assert.equal(resolveIchIndex(CONFIG, { ichSlot: 'mA|6' }), null);
});

test('resolveIchIndex: manuelle Markierung schlägt die LizenzID-Automatik', () => {
  const passByPos = passByPosition(CONFIG, SW);
  assert.equal(
    resolveIchIndex(CONFIG, { ichSlot: 'mB|2', passByPos, meinePass: '095578' }),
    3,
  );
  assert.equal(
    resolveIchIndex(CONFIG, { ichIndex: 2, passByPos, meinePass: '095578' }),
    2,
  );
});

test('resolveIchIndex: ichIndex außerhalb der Aufstellung wird ignoriert', () => {
  assert.equal(resolveIchIndex(CONFIG, { ichIndex: 9 }), null);
  assert.equal(resolveIchIndex(CONFIG, { ichIndex: -1 }), null);
});

test('ichSlotAusRoster: eigene LizenzID -> Wettkampf-Slot', () => {
  assert.equal(ichSlotAusRoster(SW, '100200'), 'mB|1');
  assert.equal(ichSlotAusRoster(SW, '999999'), null);
  assert.equal(ichSlotAusRoster(SW, ''), null);
  assert.equal(ichSlotAusRoster(null, '100200'), null);
});

test('mergeSpielerNamen: lokale Klarnamen schlagen die anonymisierte Fassung', () => {
  const anonym = [
    { name: 'A 1', startBahn: 1 }, { name: 'Bernd B.', startBahn: 2 },
    { name: 'A 2', startBahn: 3 }, { name: 'B 2', startBahn: 4 },
  ];
  const merged = mergeSpielerNamen(anonym, CONFIG.spielerListe);
  assert.deepEqual(merged.map((s) => s.name),
    ['Anna Adam', 'Bernd Berg', 'Cem Celik', 'Dora Dietz']);
  // Übrige Remote-Felder bleiben erhalten …
  assert.equal(merged[0].startBahn, 1);
  // … und die Eingaben werden nicht verändert.
  assert.equal(anonym[0].name, 'A 1');
});

test('mergeSpielerNamen: ohne lokale Kopie bleibt die Remote-Liste unverändert', () => {
  const anonym = [{ name: 'A 1' }];
  assert.equal(mergeSpielerNamen(anonym, []), anonym);
  assert.equal(mergeSpielerNamen(anonym, null), anonym);
});

test('mergeSpielerNamen: leere/fehlende lokale Namen übernehmen den Remote-Namen', () => {
  const anonym = [{ name: 'A 1' }, { name: 'A 2' }, { name: 'A 3' }];
  const lokal = [{ name: '  ' }, {}, { name: 'Cem Celik' }];
  assert.deepEqual(mergeSpielerNamen(anonym, lokal).map((s) => s.name),
    ['A 1', 'A 2', 'Cem Celik']);
});

// --- Sportwinner-Wettkampf: NUR die LizenzID zaehlt --------------------------

test('istLizenzWettkampf: Sportwinner-Import ja, manueller Wettkampf nein', () => {
  assert.equal(istLizenzWettkampf({ quelle: 'sportwinner' }), true);
  assert.equal(istLizenzWettkampf({ sportwinner: { spieler: [] } }), true);
  assert.equal(istLizenzWettkampf({ name: 'Vereinsmeisterschaft' }), false);
  assert.equal(istLizenzWettkampf(null), false);
});

test('nurLizenz: manuelle Markierung wird ignoriert, LizenzID entscheidet', () => {
  const passByPos = passByPosition(CONFIG, SW);
  // Ohne nurLizenz gewinnt die Markierung ...
  assert.equal(
    resolveIchIndex(CONFIG, { ichSlot: 'mB|2', passByPos, meinePass: '095578' }), 3,
  );
  // ... mit nurLizenz zaehlt ausschliesslich die eigene LizenzID (Position 0).
  assert.equal(
    resolveIchIndex(CONFIG, { nurLizenz: true, ichSlot: 'mB|2', passByPos, meinePass: '095578' }), 0,
  );
  assert.equal(
    resolveIchIndex(CONFIG, { nurLizenz: true, ichIndex: 3, passByPos, meinePass: '095578' }), 0,
  );
});

test('nurLizenz: ohne LizenzID-Treffer keine Zuordnung (auch nicht ueber Markierung)', () => {
  const passByPos = passByPosition(CONFIG, SW);
  assert.equal(resolveIchIndex(CONFIG, { nurLizenz: true, ichSlot: 'mA|1' }), null);
  assert.equal(
    resolveIchIndex(CONFIG, { nurLizenz: true, ichIndex: 2, passByPos, meinePass: null }), null,
  );
  // Spieler ohne Pass im Roster (Cem, Position 2) bleibt unzuordenbar.
  assert.equal(
    resolveIchIndex(CONFIG, { nurLizenz: true, ichSlot: 'mA|2', passByPos, meinePass: '' }), null,
  );
});

// --- anonymeSpielerListe: die Aufstellung ohne Klarnamen ----------------------
// Muss Zeichen für Zeichen dasselbe liefern wie pins_platzhalter_name() in
// supabase/policies.sql — sonst stünde nach dem Teilen eines fertigen Spiels lokal ein
// anderer Platzhalter als in der Datenbank.

const TEAMS = [{ id: 'mA', name: 'Grün-Weiß Osnabrück' }, { id: 'mB', name: 'SG Hasetal' }];

test('anonymeSpielerListe: „<Mannschaft> <teamPos>" statt Klarname, Rest bleibt', () => {
  const out = anonymeSpielerListe(CONFIG.spielerListe, TEAMS);
  assert.deepEqual(out.map((sp) => sp.name), [
    'Grün-Weiß Osnabrück 1', 'SG Hasetal 1', 'Grün-Weiß Osnabrück 2', 'SG Hasetal 2',
  ]);
  assert.deepEqual(out.map((sp) => sp.startBahn), [1, 2, 3, 4]);
  assert.equal(out[0].mannschaftId, 'mA');
  assert.equal(out[0].teamPos, 1);
  // Die Eingabe bleibt unangetastet — lokal stehen weiter die echten Namen.
  assert.equal(CONFIG.spielerListe[0].name, 'Anna Adam');
});

test('anonymeSpielerListe: ohne Team-Zuordnung „Spieler N"', () => {
  const liste = [{ name: 'Anna Adam', startBahn: 1 }, { name: 'Bernd Berg', startBahn: 2 }];
  assert.deepEqual(anonymeSpielerListe(liste).map((sp) => sp.name), ['Spieler 1', 'Spieler 2']);
  // Unbekannte Mannschaft -> ebenfalls der neutrale Fallback, nie der Klarname.
  assert.deepEqual(
    anonymeSpielerListe([{ name: 'Cem Celik', mannschaftId: 'mX', teamPos: 3 }], TEAMS)
      .map((sp) => sp.name),
    ['Spieler 1'],
  );
});

test('anonymeSpielerListe: leere/fehlende Liste', () => {
  assert.deepEqual(anonymeSpielerListe(null, TEAMS), []);
  assert.deepEqual(anonymeSpielerListe([], TEAMS), []);
});
