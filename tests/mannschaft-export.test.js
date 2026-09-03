import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  mannschaftDurchgaenge, mannschaftExportInfo, buildMannschaftCSV,
  buildMannschaftProtokollHTML, mannschaftCsvDateiname, MANNSCHAFT_CSV_SPALTEN,
} from '../js/logic/mannschaft-export.js';

// Ein Satz-Block: Würfe (+ optional nur eingetragene Teilsatz-Ergebnisse).
function blk(wuerfe, overrides = [null, null]) {
  return { wuerfe, kegel: wuerfe.map(() => null), koenig: wuerfe.map(() => false), overrides, done: true };
}
const leer = () => blk([]);

// Ein Durchgang mit vier Spielern: je zwei Heim (A) und Gast (B), abwechselnd auf den Bahnen.
function durchgang(nr, bloecke) {
  return {
    id: 'g' + nr,
    wettkampfId: 'w1',
    durchgangNr: nr,
    config: {
      preset: 'Sportkegeln',
      anlageName: 'Kegelhalle',
      spielerListe: [
        { name: 'Anna', mannschaftId: 'A', teamPos: 1, startBahn: 1 },
        { name: 'Bea', mannschaftId: 'B', teamPos: 1, startBahn: 2 },
        { name: 'Cem', mannschaftId: 'A', teamPos: 2, startBahn: 3 },
        { name: 'Dirk', mannschaftId: 'B', teamPos: 2, startBahn: 4 },
      ],
      saetze: 1,
      ersteBahn: 1,
      wuerfeProSatz: 4,
      teilsaetze: [{ modus: 'volle', wuerfe: 2 }, { modus: 'abraeumen', wuerfe: 2 }],
    },
    erfassung: { bloecke },
  };
}

const wettkampf = {
  id: 'w1',
  name: 'Pokalrunde',
  datum: '2026-03-14T18:00:00.000Z',
  mannschaften: [{ id: 'A', name: 'VOK 1' }, { id: 'B', name: 'Gäste' }],
};

// Durchgang 2 steht bewusst VOR Durchgang 1 in der Liste (Reihenfolge im Store ist beliebig).
const games = [
  durchgang(2, [[blk([1, 2, 3, 4])], [blk([5, 5, 5, 5])], [blk([6, 6, 6, 6])], [leer()]]),
  durchgang(1, [[blk([9, 8, 7, 6])], [blk([4, 4, 4, 4])], [leer()], [blk([3, 3, 3, 3])]]),
];
const tabelle = (csv) => csv.split('\r\n').filter((z) => z !== '').map((z) => z.split(';'));

test('Durchgänge einer Mannschaft: nach Nummer sortiert, je Durchgang die Spieler mit Daten', () => {
  const dg = mannschaftDurchgaenge(wettkampf, games, 'A');
  assert.deepEqual(dg.map((d) => d.nr), [1, 2]);
  assert.deepEqual(dg[0].indices, [0]);    // Cem hat in Durchgang 1 nichts erfasst
  assert.deepEqual(dg[1].indices, [0, 2]); // Anna (Pos 1) vor Cem (Pos 2)
});

test('Nur eingetragenes Teilsatz-Ergebnis zählt als erfasst', () => {
  const nurErgebnis = [durchgang(1, [[blk([], [22, null])], [leer()], [leer()], [leer()]])];
  assert.deepEqual(mannschaftDurchgaenge(wettkampf, nurErgebnis, 'A')[0].indices, [0]);
});

test('Mannschaft ohne erfasste Würfe: keine Durchgänge, leere Ausgaben', () => {
  const ohne = [durchgang(1, [[leer()], [leer()], [leer()], [leer()]])];
  assert.deepEqual(mannschaftDurchgaenge(wettkampf, ohne, 'A'), []);
  assert.equal(buildMannschaftCSV(wettkampf, ohne, 'A'), '');
  assert.equal(buildMannschaftProtokollHTML(wettkampf, ohne, 'A'), '');
});

test('Export-Info zählt Spieler, Blätter und Durchgänge', () => {
  assert.deepEqual(mannschaftExportInfo(wettkampf, games, 'A'),
    { durchgaenge: 2, blaetter: 3, spieler: 2 });
  assert.deepEqual(mannschaftExportInfo(wettkampf, games, 'B'),
    { durchgaenge: 2, blaetter: 3, spieler: 2 });
});

test('CSV: Durchgang und Mannschaft vor den Wurf-Spalten', () => {
  const [kopf, ...zeilen] = tabelle(buildMannschaftCSV(wettkampf, games, 'A'));
  assert.deepEqual(kopf, MANNSCHAFT_CSV_SPALTEN);
  assert.deepEqual(kopf.slice(0, 4), ['Durchgang', 'Mannschaft', 'Spieler', 'Satz']);
  // 3 Blätter à 4 Würfe, Durchgang 1 zuerst, innerhalb des Durchgangs nach Startnummer.
  assert.equal(zeilen.length, 12);
  assert.deepEqual(zeilen[0].slice(0, 3), ['1', 'VOK 1', 'Anna']);
  assert.deepEqual(zeilen[4].slice(0, 3), ['2', 'VOK 1', 'Anna']);
  assert.deepEqual(zeilen[8].slice(0, 3), ['2', 'VOK 1', 'Cem']);
  // Nur die eigene Mannschaft — kein Gast-Spieler in der Datei.
  assert.ok(!zeilen.some((z) => z[2] === 'Bea' || z[2] === 'Dirk'));
});

test('PDF-Dokument: ein Blatt je Spieler und Durchgang, mit Mannschaft im Kopf', () => {
  const html = buildMannschaftProtokollHTML(wettkampf, games, 'A');
  assert.equal((html.match(/class="wp-page"/g) || []).length, 3);
  assert.ok(html.includes('<title>Wurfprotokoll — Pokalrunde · VOK 1</title>'));
  assert.ok(html.includes('Durchgang 1') && html.includes('Durchgang 2'));
  assert.ok(html.includes('Anna') && html.includes('Cem'));
  assert.ok(!html.includes('Bea') && !html.includes('Dirk'));
  assert.ok(html.includes('VOK 1')); // Mannschaftszeile auf dem Blatt
});

test('CSV-Dateiname: Wettkampf, Wettkampf-Datum und Mannschaft', () => {
  assert.equal(mannschaftCsvDateiname(wettkampf, 'A'), 'Wurfdaten_Pokalrunde_2026-03-14_VOK-1.csv');
  // Verbotene Dateizeichen fliegen raus; ohne Datum wird der heutige Tag genommen.
  const wk = { name: 'Pokal: A/B', mannschaften: [{ id: 'A', name: 'VOK 1' }] };
  assert.match(mannschaftCsvDateiname(wk, 'A'), /^Wurfdaten_Pokal-AB_\d{4}-\d{2}-\d{2}_VOK-1\.csv$/);
});
