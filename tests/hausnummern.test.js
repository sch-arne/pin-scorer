import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  stellenOf, ziffer, fehlwurfZiffer, besteHausnummer, schlechtesteHausnummer,
  autoPosition, positionen, freieStellen, naechsteStelle,
  ziffernOf, durchgangFertig, hausnummerWert, hausnummerText, formatZahl,
  summe, spielFertig, rangliste,
} from '../js/logic/hausnummern.js';

// Ein Konfigurations-Gerüst wie es setup-hausnummern.js speichert.
const cfg = (over = {}) => ({
  variante: 'hoch', platzierung: 'vorn', stellen: 4, nullRegel: 'neun',
  saetze: 1, spielerListe: [{ name: 'A' }],
  ...over,
});

// Ein Durchgang-Block aus Würfen (optional Stellen und Ungültig-Flags).
const blk = (wuerfe, pos = [], ungueltig = []) => ({ wuerfe, pos, ungueltig, done: false });

test('stellenOf begrenzt auf 2..8 und faellt auf 4 zurueck', () => {
  assert.equal(stellenOf(cfg()), 4);
  assert.equal(stellenOf(cfg({ stellen: 6 })), 6);
  assert.equal(stellenOf(cfg({ stellen: 99 })), 8);
  assert.equal(stellenOf(cfg({ stellen: 1 })), 2);
  assert.equal(stellenOf({}), 4);
});

test('Ziffer beim Hoch-Spiel: Holz zaehlt, Fehlwurf ist 0', () => {
  const c = cfg();
  assert.equal(ziffer(9, false, c), 9);
  assert.equal(ziffer(0, false, c), 0);
  assert.equal(ziffer(7, true, c), 0);      // ungültig schlägt das Holz
  assert.equal(fehlwurfZiffer(c), 0);
});

test('Ziffer beim Niedrig-Spiel: der Durchläufer zählt je nach Regel 9 oder 0', () => {
  const neun = cfg({ variante: 'niedrig', nullRegel: 'neun' });
  const null0 = cfg({ variante: 'niedrig', nullRegel: 'null' });
  assert.equal(fehlwurfZiffer(neun), 9);
  assert.equal(ziffer(0, false, neun), 9);  // Standard: auch ohne Holz kostet die Stelle 9
  assert.equal(ziffer(0, false, null0), 0); // Sonderregel: die durchgelaufene Kugel ist eine 0
  assert.equal(ziffer(1, false, neun), 1);
});

// Der Kern der Sonderregel: sie gilt NUR für die durchgelaufene Kugel. Ein ungültiger Wurf
// bleibt die 9 — sonst wäre die 0 gratis zu haben, indem man ihn absichtlich setzt.
test('Ein ungültiger Wurf zählt auch unter der Sonderregel 9', () => {
  const null0 = cfg({ variante: 'niedrig', nullRegel: 'null' });
  assert.equal(ziffer(3, true, null0), 9);  // Holz gefallen, aber ungültig
  assert.equal(ziffer(0, true, null0), 9);  // kein Holz UND ungültig -> kein Durchläufer
  assert.equal(ziffer(0, false, null0), 0); // nur der saubere Durchläufer zählt 0
});

test('beste/schlechteste Hausnummer folgen den Regeln', () => {
  assert.equal(besteHausnummer(cfg()), 9999);
  assert.equal(schlechtesteHausnummer(cfg()), 0);
  assert.equal(besteHausnummer(cfg({ variante: 'niedrig' })), 1111);
  assert.equal(schlechtesteHausnummer(cfg({ variante: 'niedrig' })), 9999);
  assert.equal(besteHausnummer(cfg({ variante: 'niedrig', nullRegel: 'null' })), 0);
  assert.equal(besteHausnummer(cfg({ stellen: 6 })), 999999);
});

test('autoPosition: von vorn und von hinten', () => {
  const vorn = cfg();
  const hinten = cfg({ platzierung: 'hinten' });
  assert.deepEqual([0, 1, 2, 3].map((k) => autoPosition(k, vorn)), [0, 1, 2, 3]);
  assert.deepEqual([0, 1, 2, 3].map((k) => autoPosition(k, hinten)), [3, 2, 1, 0]);
  assert.equal(autoPosition(4, vorn), null);          // Durchgang voll
  assert.equal(autoPosition(0, cfg({ platzierung: 'ansage-vor' })), null);
});

test('Ziffernfolge: von vorn notiert', () => {
  const c = cfg();
  const b = blk([9, 4, 0, 7]);
  assert.deepEqual(ziffernOf(b, c), [9, 4, 0, 7]);
  assert.equal(hausnummerWert(b, c), 9407);
  assert.equal(hausnummerText(b, c), '9407');
  assert.ok(durchgangFertig(b, c));
});

test('Ziffernfolge: von hinten notiert', () => {
  const c = cfg({ platzierung: 'hinten' });
  const b = blk([9, 4, 0, 7]);
  assert.deepEqual(ziffernOf(b, c), [7, 0, 4, 9]);
  assert.equal(hausnummerWert(b, c), 7049);
});

test('Ziffernfolge: angesagte Stellen', () => {
  const c = cfg({ platzierung: 'ansage-vor' });
  const b = blk([5, 8, 2, 6], [3, 0, 2, 1]);       // Wurf 1 ganz hinten, Wurf 2 ganz vorn
  assert.deepEqual(ziffernOf(b, c), [8, 6, 2, 5]);
  assert.equal(hausnummerWert(b, c), 8625);
});

test('Angesagte Stellen: doppelt belegte oder unsinnige Stelle zaehlt nicht mit', () => {
  const c = cfg({ platzierung: 'wahl-nach' });
  const b = blk([5, 8, 2], [0, 0, 9]);             // Stelle 0 doppelt, dann außerhalb
  assert.deepEqual(positionen(b, c), [0, null, null]);
  assert.deepEqual(ziffernOf(b, c), [5, null, null, null]);
  assert.equal(durchgangFertig(b, c), false);
});

test('Teilstand: offene Stellen erscheinen als Strich', () => {
  const c = cfg();
  const b = blk([9, 4]);
  assert.equal(hausnummerText(b, c), '94––');
  assert.equal(durchgangFertig(b, c), false);
  assert.equal(hausnummerWert(b, c), 9400);        // Zwischenstand, nicht gewertet
});

test('freie Stellen und naechste Stelle', () => {
  const vorn = cfg();
  assert.deepEqual(freieStellen(blk([9, 4]), vorn), [2, 3]);
  assert.equal(naechsteStelle(blk([9, 4]), vorn), 2);
  assert.equal(naechsteStelle(blk([9, 4, 0, 7]), vorn), null); // voll

  const ansage = cfg({ platzierung: 'ansage-vor' });
  assert.deepEqual(freieStellen(blk([9, 4], [3, 1]), ansage), [0, 2]);
  assert.equal(naechsteStelle(blk([9, 4], [3, 1]), ansage), null); // wird angesagt
});

test('fuehrende Nullen bleiben erhalten', () => {
  const c = cfg();
  const b = blk([0, 4, 2, 1]);
  assert.equal(hausnummerWert(b, c), 421);
  assert.equal(hausnummerText(b, c), '0421');
  assert.equal(formatZahl(421, c), '0421');
  assert.equal(formatZahl(9999, c), '9999');
});

test('Summe zaehlt nur abgeschlossene Durchgaenge', () => {
  const c = cfg({ saetze: 2 });
  const saetze = [blk([9, 4, 0, 7]), blk([1, 2])];
  assert.equal(summe(saetze, c), 9407);
  saetze[1] = blk([1, 2, 3, 4]);
  assert.equal(summe(saetze, c), 9407 + 1234);
});

test('spielFertig erst, wenn alle Spieler alle Durchgaenge geworfen haben', () => {
  const c = cfg({ saetze: 2, spielerListe: [{ name: 'A' }, { name: 'B' }] });
  const voll = () => [blk([1, 2, 3, 4]), blk([5, 6, 7, 8])];
  assert.equal(spielFertig(c, [voll(), voll()]), true);
  assert.equal(spielFertig(c, [voll(), [blk([1, 2, 3, 4]), blk([5, 6])]]), false);
  assert.equal(spielFertig(c, []), false);
});

test('Rangliste hoch: hoechste Summe gewinnt', () => {
  const c = cfg({ saetze: 2, spielerListe: [{ name: 'A' }, { name: 'B' }, { name: 'C' }] });
  const r = rangliste(c, [
    [blk([1, 1, 1, 1]), blk([2, 2, 2, 2])],   // 1111 + 2222 = 3333
    [blk([9, 0, 0, 0]), blk([0, 0, 0, 1])],   // 9000 +    1 = 9001
    [blk([5, 0, 0, 0]), blk([5, 0, 0, 0])],   // 5000 + 5000 = 10000
  ]);
  assert.deepEqual(r.map((x) => x.name), ['C', 'B', 'A']);
  assert.deepEqual(r.map((x) => x.rang), [1, 2, 3]);
  assert.deepEqual(r.map((x) => x.summe), [10000, 9001, 3333]);
});

test('Rangliste niedrig: niedrigste Summe gewinnt', () => {
  const c = cfg({ variante: 'niedrig', saetze: 1, spielerListe: [{ name: 'A' }, { name: 'B' }] });
  const r = rangliste(c, [
    [blk([1, 1, 1, 1])],                       // 1111
    [blk([1, 0, 1, 1])],                       // 0 Holz zählt 9 -> 1911
  ]);
  assert.deepEqual(r.map((x) => x.name), ['A', 'B']);
  assert.deepEqual(r.map((x) => x.summe), [1111, 1911]);
});

test('Rangliste: Gleichstand teilt sich den Rang', () => {
  const c = cfg({ saetze: 1, spielerListe: [{ name: 'A' }, { name: 'B' }, { name: 'C' }] });
  const r = rangliste(c, [
    [blk([4, 3, 2, 1])],
    [blk([9, 9, 9, 9])],
    [blk([4, 3, 2, 1])],
  ]);
  assert.deepEqual(r.map((x) => x.name), ['B', 'A', 'C']);
  assert.deepEqual(r.map((x) => x.rang), [1, 2, 2]);
});

test('Rangliste: wer noch nichts fertig hat, steht hinten', () => {
  const c = cfg({ variante: 'niedrig', saetze: 1, spielerListe: [{ name: 'A' }, { name: 'B' }] });
  const r = rangliste(c, [
    [blk([1, 2])],        // noch nicht fertig -> Summe 0, darf nicht führen
    [blk([5, 5, 5, 5])],
  ]);
  assert.deepEqual(r.map((x) => x.name), ['B', 'A']);
  assert.deepEqual(r.map((x) => x.rang), [1, 2]);
});
