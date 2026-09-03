// Export-Wege: CSV-Download und Wurfprotokoll-Druck aus der Erfassung.
// Der Runner fängt Anker-Downloads und den Druck-Aufruf ab (siehe harness.js), es
// landet also nichts im Dateisystem und es öffnet sich kein Druckdialog.
//
// Zwei Ausgabestellen gibt es:
//   * Statistik-Vollbild (🏁, nach Spielende): Häkchen je Spieler, EINE Datei.
//   * Statistik-Tab der Spieler-Übersicht: je Spieler ein PDF-/CSV-Knopf.

import { suite, test, ok, eq, deepEq, includes } from '../harness.js';
import { makeGame, makeErfassung } from '../fixtures.js';

const MOBIL = { width: 420, height: 900 };

function beendetesSpiel() {
  const g = makeGame({
    preset: 'schere', saetze: 2, wuerfeProSatz: 4,
    teilsaetze: ['volle', 'kranz-abraeumen'], bahnen: 2, spieler: ['Anna', 'Bert'],
  });
  g.status = 'beendet';
  g.erfassung = makeErfassung(g.config, [
    [[9, 8, 7, 2], [6, 6, 5, 4]],
    [[3, 3, 3, 3], [2, 2, 2, 2]],
  ]);
  return g;
}

async function starte(app, game) {
  await app.boot({ hash: '/spiel-laufend', ...MOBIL, storage: { games: [game], 'active-game': game.id } });
  return game;
}

const zeilen = (csv) => csv.trim().split(/\r?\n/);

suite('Export', () => {
  test('CSV aller Spieler: genau eine Tabelle mit Kopfzeile und einer Zeile je Wurf', async (app) => {
    await starte(app, beendetesSpiel());
    ok(app.$('[data-wp-player]'), 'Spieler-Auswahl fehlt im Statistik-Screen');
    await app.click('[data-act="export-csv"]');
    eq(app.downloads.length, 1, 'kein Download ausgelöst');
    includes(app.downloads[0].name, 'Wurfdaten', 'Dateiname');
    const csv = await app.downloadText();
    const z = zeilen(csv);
    eq(z[0], 'Spieler;Satz;Bahn;Teilsatz;Modus;Wurf;Holz;Kegel', 'Kopfzeile');
    eq(z.length, 17, 'Kopfzeile + 2 Spieler × 8 Würfe');
    includes(z[1], 'Anna;1;1;1;Volle;1;9', 'erste Wurfzeile');
    ok(csv.includes('Bert'), 'zweiter Spieler fehlt');
    app.assertClean();
  });

  test('Abgewählter Spieler landet nicht in der Datei', async (app) => {
    await starte(app, beendetesSpiel());
    await app.check('[data-wp-player="1"]', false);
    await app.click('[data-act="export-csv"]');
    const csv = await app.downloadText();
    ok(csv.includes('Anna'), 'Anna fehlt');
    ok(!csv.includes('Bert'), 'abgewählter Spieler ist trotzdem drin');
    includes(app.downloads[0].name, 'Anna', 'Einzelname im Dateinamen');
    app.assertClean();
  });

  test('Ohne Häkchen wird nichts exportiert', async (app) => {
    await starte(app, beendetesSpiel());
    await app.check('[data-wp-player="0"]', false);
    await app.check('[data-wp-player="1"]', false);
    await app.click('[data-act="export-csv"]');
    eq(app.downloads.length, 0, 'leerer Export erzeugte eine Datei');
    includes(app.txt('#erf-toast'), 'Keine Spieler', 'Hinweis fehlt');
    app.assertClean();
  });

  test('CSV je Spieler aus dem Statistik-Tab der Übersicht', async (app) => {
    await starte(app, beendetesSpiel());
    await app.click('[data-act="stats-close"]');
    await app.click('.ueber-tabs [data-uebertab="statistik"]');
    await app.click('[data-export-csv="0"]');
    const csv = await app.downloadText();
    ok(csv.includes('Anna'), 'Anna fehlt');
    ok(!csv.includes('Bert'), 'anderer Spieler mit exportiert');
    app.assertClean();
  });

  test('Manuell gesetztes Teilsatz-Ergebnis wird als eigene Zeile exportiert', async (app) => {
    const g = beendetesSpiel();
    g.erfassung.bloecke[0][0].wuerfe = [];
    g.erfassung.bloecke[0][0].kegel = [];
    g.erfassung.bloecke[0][0].koenig = [];
    g.erfassung.bloecke[0][0].overrides = [17, null];
    await starte(app, g);
    await app.check('[data-wp-player="1"]', false);
    await app.click('[data-act="export-csv"]');
    const csv = await app.downloadText();
    ok(zeilen(csv).some((r) => r.startsWith('Anna;1;1;1;Volle;;17;')),
      'Ergebnis-Zeile ohne Wurf-Nummer fehlt:\n' + csv);
    app.assertClean();
  });

  test('Kegelbild landet als Liste der gefallenen Kegel in der CSV', async (app) => {
    const g = beendetesSpiel();
    g.erfassung.bloecke[0][0].kegel[0] = [1, 2, 3, 4, 5, 6, 7, 8, 9];
    await starte(app, g);
    await app.check('[data-wp-player="1"]', false);
    await app.click('[data-act="export-csv"]');
    const csv = await app.downloadText();
    ok(zeilen(csv)[1].endsWith('1 2 3 4 5 6 7 8 9'), 'Kegelbild fehlt: ' + zeilen(csv)[1]);
    app.assertClean();
  });

  test('Wurfprotokoll-Druck erzeugt ein Blatt mit den Spielern', async (app) => {
    await starte(app, beendetesSpiel());
    await app.click('[data-act="print-protokoll"]');
    await app.waitFor(() => app.prints.length > 0, 'Druck wurde nicht ausgelöst', 6000);
    const html = app.prints[0];
    includes(html, 'Anna', 'Spielername im Protokoll');
    includes(html, 'Bert', 'zweiter Spieler im Protokoll');
    app.assertClean();
  });

  test('Export aus dem ⚙-Menü betrifft den aktiven Spieler', async (app) => {
    const g = beendetesSpiel();
    g.status = 'laufend';
    g.erfassung.bloecke.forEach((arr) => arr.forEach((b) => { b.done = false; }));
    await starte(app, g);
    await app.click('[data-player="1"]');
    await app.click('[data-act="settings"]');
    await app.click('[data-act="export-csv-current"]');
    const csv = await app.downloadText();
    ok(csv.includes('Bert'), 'aktiver Spieler nicht exportiert');
    ok(!csv.includes('Anna'), 'anderer Spieler mit exportiert');
    app.assertClean();
  });
});
