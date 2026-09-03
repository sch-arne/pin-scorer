import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildWurfCSV, csvDateiname, CSV_SPALTEN } from '../js/logic/wurf-csv.js';
import { teilsatzRanges } from '../js/logic/teilsaetze.js';

// Ein Satz-Block: Würfe + (optional) konkrete Kegelbilder je Wurf.
function blk(wuerfe, kegel = null, overrides = [null, null], done = true) {
  return {
    wuerfe,
    kegel: kegel || wuerfe.map(() => null),
    koenig: wuerfe.map(() => false),
    overrides,
    done,
  };
}

// 2 Spieler, 2 Sätze, 2 Teilsätze (Volle/Abräumen) à 2 Würfe.
const config = {
  spielerListe: [{ name: 'Anna' }, { name: 'Ben' }],
  saetze: 2,
  ersteBahn: 1,
  wuerfeProSatz: 4,
  teilsaetze: [{ modus: 'volle', wuerfe: 2 }, { modus: 'abraeumen', wuerfe: 2 }],
};
const ranges = teilsatzRanges(config);

const spiel = (bloecke) => ({ config, erfassung: { bloecke } });
// Die Datei als Zeilen-Arrays: [0] ist die Kopfzeile, danach die Datenzeilen.
const tabelle = (csv) => csv.split('\r\n').filter((z) => z !== '').map((z) => z.split(';'));

test('Genau eine Tabelle: Kopfzeile in Zeile 1, danach nur Wurfzeilen', () => {
  const csv = buildWurfCSV(spiel([
    [blk([9, 8, 5, 4]), blk([7, 6, 3, 2])],
    [blk([9, 9, 1, 1]), blk([0, 2, 4, 4])],
  ]), ranges, [0]);

  const [kopf, ...zeilen] = tabelle(csv);
  assert.deepEqual(kopf, CSV_SPALTEN);
  assert.deepEqual(kopf, ['Spieler', 'Satz', 'Bahn', 'Teilsatz', 'Modus', 'Wurf', 'Holz', 'Kegel']);
  // 2 Sätze à 4 Würfe, nur Anna — keine Summen-, Satz- oder Kennzahl-Zeilen mehr.
  assert.equal(zeilen.length, 8);
  assert.ok(zeilen.every((z) => z.length === kopf.length && z[0] === 'Anna'));
  assert.ok(!csv.includes('Zusammenfassung') && !csv.includes('Gesamt'));
});

test('Wurfzeile: Satz, Bahn, Teilsatz, Modus, Wurf-Nr und Holz', () => {
  const csv = buildWurfCSV(spiel([[blk([9, 8, 5, 4]), blk([7, 6, 3, 2])], []]), ranges, [0]);
  const [, ...zeilen] = tabelle(csv);

  assert.deepEqual(zeilen[0], ['Anna', '1', '1', '1', 'Volle', '1', '9', '']);
  // Dritter Wurf des Satzes ist der erste Abräum-Wurf (Teilsatz 2), Nummerierung läuft im Satz weiter.
  assert.deepEqual(zeilen[2], ['Anna', '1', '1', '2', 'Abräumen', '3', '5', '']);
  // Zweiter Satz liegt (ohne Bahnplan) auf der Folgebahn.
  assert.deepEqual(zeilen[4], ['Anna', '2', '2', '1', 'Volle', '1', '7', '']);
});

test('Kegelbild als Liste der gefallenen Kegel; ohne Erfassung leer', () => {
  const kegel = [[9, 7, 5, 3, 1], [], null, null];
  const csv = buildWurfCSV(spiel([[blk([5, 0, 0, 0], kegel)], []]), ranges, [0]);
  const [kopf, ...zeilen] = tabelle(csv);
  const kSpalte = kopf.indexOf('Kegel');

  assert.equal(zeilen[0][kSpalte], '1 3 5 7 9'); // sortiert
  assert.equal(zeilen[1][kSpalte], '');          // Fehlwurf: kein Kegel gefallen
  assert.equal(zeilen[2][kSpalte], '');          // gar kein Bild erfasst
});

test('Nur eingetragenes Teilsatz-Ergebnis: eine Zeile ohne Wurf-Nummer', () => {
  const csv = buildWurfCSV(spiel([[blk([], null, [23, 17])], []]), ranges, [0]);
  const [kopf, ...zeilen] = tabelle(csv);
  const w = kopf.indexOf('Wurf');
  const h = kopf.indexOf('Holz');

  assert.equal(zeilen.length, 2); // je Teilsatz eine Zeile
  assert.equal(zeilen[0][w], '');
  assert.equal(zeilen[0][h], '23');
  assert.equal(zeilen[1][h], '17');
});

test('Teilsatz mit Einzelwürfen und Teilsatz mit Ergebnis im selben Satz', () => {
  // Volle einzeln erfasst, Abräumen nur als Summe (Override im zweiten Teilsatz).
  const csv = buildWurfCSV(spiel([[blk([9, 8], null, [null, 14])], []]), ranges, [0]);
  const [kopf, ...zeilen] = tabelle(csv);
  const w = kopf.indexOf('Wurf');

  assert.equal(zeilen.length, 3);
  assert.deepEqual([zeilen[0][w], zeilen[1][w]], ['1', '2']);
  assert.equal(zeilen[2][w], '');
  assert.equal(zeilen[2][kopf.indexOf('Holz')], '14');
});

test('Mehrere Spieler stehen in EINER Datei, in der übergebenen Reihenfolge', () => {
  const csv = buildWurfCSV(spiel([[blk([9, 8, 5, 4])], [blk([1, 2, 3, 4])]]), ranges, [0, 1]);
  const namen = tabelle(csv).slice(1).map((z) => z[0]);
  assert.deepEqual(namen, ['Anna', 'Anna', 'Anna', 'Anna', 'Ben', 'Ben', 'Ben', 'Ben']);
});

test('Ohne Spieler-Auswahl sind alle Spieler dabei', () => {
  const csv = buildWurfCSV(spiel([[blk([9, 8, 5, 4])], [blk([1, 2, 3, 4])]]), ranges, []);
  const namen = new Set(tabelle(csv).slice(1).map((z) => z[0]));
  assert.deepEqual([...namen], ['Anna', 'Ben']);
});

test('Bahnplan schlägt die Folgebahn-Annahme', () => {
  const cfg = { ...config, bahnplan: [[3, 4], [4, 3]] };
  const game = { config: cfg, erfassung: { bloecke: [[blk([9, 8, 5, 4]), blk([1, 1, 1, 1])], []] } };
  const [kopf, ...zeilen] = tabelle(buildWurfCSV(game, ranges, [0]));
  const b = kopf.indexOf('Bahn');
  assert.equal(zeilen[0][b], '3');
  assert.equal(zeilen[4][b], '4');
});

test('Semikolon im Spielernamen wird gequotet', () => {
  const cfg = { ...config, spielerListe: [{ name: 'Meier; Anna' }, { name: 'Ben' }] };
  const csv = buildWurfCSV({ config: cfg, erfassung: { bloecke: [[blk([9, 8, 5, 4])], []] } }, ranges, [0]);
  assert.ok(csv.includes('"Meier; Anna"'));
});

test('csvDateiname: Datum, Spielname und (bei einem Spieler) der Name', () => {
  const eins = csvDateiname({ titel: 'Sportkegeln-Training' }, ['Anna']);
  assert.match(eins, /^Wurfdaten_Sportkegeln-Training_\d{4}-\d{2}-\d{2}_Anna\.csv$/);
  // Mehrere Spieler -> kein Name im Dateinamen; verbotene Zeichen fliegen raus.
  const viele = csvDateiname({ titel: 'Pokal: A/B' }, ['Anna', 'Ben']);
  assert.match(viele, /^Wurfdaten_Pokal-AB_\d{4}-\d{2}-\d{2}\.csv$/);
});
