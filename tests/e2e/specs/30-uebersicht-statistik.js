// Spieler-Übersicht (Kontrollzentrum), Ergebnis-Eingabe über den Ziffernblock,
// Statistik-Tab und Wurf-Bild-Filter.

import { suite, test, ok, eq, deepEq, includes, notIncludes } from '../harness.js';
import { makeGame, makeErfassung } from '../fixtures.js';

const MOBIL = { width: 420, height: 900 };
const DESKTOP = { width: 1280, height: 900 };

// Zwei Spieler, 2 Sätze à 4 Würfe (Volle / Abräumen), 2 Bahnen.
function spielMitStand({ spieler = ['Anna', 'Bert'], wuerfe = null, teilsaetze = ['volle', 'volle'] } = {}) {
  const g = makeGame({
    preset: 'schere', saetze: 2, wuerfeProSatz: 4, teilsaetze,
    bahnen: 2, spieler,
  });
  g.status = 'laufend';
  g.erfassung = makeErfassung(g.config, wuerfe || [
    [[9, 8, 7, 6], [5, 5, 5, 5]],
    [[4, 4, 4, 4], [4, 4]],
  ], { done: [[true, true], [true, false]] });
  return g;
}

async function starte(app, game, layout = MOBIL) {
  await app.boot({ hash: '/spiel-laufend', ...layout, storage: { games: [game], 'active-game': game.id } });
  return game;
}

suite('Übersicht & Statistik', () => {
  test('Übersichts-Tabelle zeigt Bahn, Satz, Teilsätze, Holz und Summenzeile', async (app) => {
    await starte(app, spielMitStand());
    const rows = app.$$('.ub-table tbody tr');
    eq(rows.length, 2, 'eine Zeile je Satz');
    eq(rows[0].querySelector('.ub-bahn').textContent.trim(), 'B1', 'Bahn Satz 1');
    eq(rows[0].querySelector('.ub-holz').textContent.trim(), '30', 'Holz Satz 1 (9+8+7+6)');
    eq(rows[1].querySelector('.ub-holz').textContent.trim(), '20', 'Holz Satz 2');
    eq(app.$('.ub-grand').textContent.trim(), '50', 'Gesamtsumme');
    deepEq(app.$$('.ub-table tbody tr:first-child .ub-ts').map((t) => t.textContent.trim()),
      ['17', '13'], 'Teilsatz-Spalten');
    app.assertClean();
  });

  test('Kopfzelle „Bahn" sortiert die Zeilen um', async (app) => {
    const g = spielMitStand();
    await starte(app, g);
    const bahnen = () => app.$$('.ub-table tbody .ub-bahn').map((t) => t.textContent.trim());
    deepEq(bahnen(), ['B1', 'B2'], 'Standard: nach Satz');
    // Eine NEUE Sortierspalte beginnt absteigend, ein zweiter Klick dreht sie um.
    await app.click('[data-sort="bahn"]');
    deepEq(bahnen(), ['B2', 'B1'], 'neue Spalte startet absteigend');
    await app.click('[data-sort="bahn"]');
    deepEq(bahnen(), ['B1', 'B2'], 'zweiter Klick dreht die Richtung');
    app.assertClean();
  });

  test('Teilsatz-Ergebnis per Ziffernblock setzen und wieder auf die Würfe zurücknehmen', async (app) => {
    const g = spielMitStand();
    await starte(app, g);
    await app.click('[data-edit-ts="0:0:0"]');
    ok(app.$('[data-ovnum="1"]:not([disabled])'), 'Ziffernblock nicht aktiviert');
    await app.click('[data-ovnum="1"]');
    await app.click('[data-ovnum="5"]');
    await app.click('[data-act="override-apply"]');
    eq(app.game(g.id).erfassung.bloecke[0][0].overrides[0], 15, 'Override nicht gespeichert');
    eq(app.$$('.ub-table tbody tr')[0].querySelector('.ub-holz').textContent.trim(), '28',
      'Satzsumme mit Override (15 + 13)');
    ok(app.$('.ub-ts.is-manual'), 'manuelles Ergebnis nicht markiert');

    await app.click('[data-edit-ts="0:0:0"]');
    await app.click('[data-act="override-reset"]');
    eq(app.game(g.id).erfassung.bloecke[0][0].overrides[0], null, 'Override nicht entfernt');
    app.assertClean();
  });

  test('Ganzes Satz-Ergebnis ergänzt den EINEN offenen Teilsatz', async (app) => {
    // Berts Satz 2: Teilsatz 1 ist durchgeworfen (4+4=8), Teilsatz 2 offen.
    // Ein Satz-Ergebnis von 20 muss also 12 auf Teilsatz 2 ergänzen.
    const g = spielMitStand();
    await starte(app, g);
    await app.click('[data-player="1"]');
    await app.click('[data-edit-satz="1:1"]');
    await app.click('[data-ovnum="2"]');
    await app.click('[data-ovnum="0"]');
    await app.click('[data-act="override-apply"]');
    const blk = app.game(g.id).erfassung.bloecke[1][1];
    deepEq(blk.overrides, [null, 12], 'Rest nicht auf den offenen Teilsatz ergänzt');
    ok(blk.done, 'vollständiger Satz wurde nicht abgeschlossen');
    app.assertClean();
  });

  test('Satz-Ergebnis wird bei mehreren offenen Teilsätzen abgelehnt', async (app) => {
    const g = spielMitStand();
    g.erfassung.bloecke[1][1] = {
      wuerfe: [], kegel: [], koenig: [], overrides: [null, null], done: false,
    };
    await starte(app, g);
    await app.click('[data-player="1"]');
    await app.click('[data-edit-satz="1:1"]');
    await app.click('[data-ovnum="2"]');
    await app.click('[data-ovnum="0"]');
    await app.click('[data-act="override-apply"]');
    deepEq(app.game(g.id).erfassung.bloecke[1][1].overrides, [null, null],
      'mehrdeutige Verteilung wurde trotzdem eingetragen');
    includes(app.txt('#erf-toast'), 'einzeln', 'Hinweis fehlt');
    app.assertClean();
  });

  test('Zu großes Teilsatz-Ergebnis wird abgelehnt (Soll-Würfe × 9)', async (app) => {
    const g = spielMitStand();
    await starte(app, g);
    await app.click('[data-edit-ts="0:0:0"]');
    await app.click('[data-ovnum="4"]');
    await app.click('[data-ovnum="2"]');   // 42 > 2 Würfe × 9
    await app.click('[data-act="override-apply"]');
    eq(app.game(g.id).erfassung.bloecke[0][0].overrides[0], null, 'unmögliches Ergebnis übernommen');
    includes(app.txt('#erf-toast'), '18', 'Obergrenze nicht genannt');
    app.assertClean();
  });

  test('⌫ löscht die letzte Ziffer im Ergebnis-Feld', async (app) => {
    const g = spielMitStand();
    await starte(app, g);
    await app.click('[data-edit-ts="0:0:0"]');
    await app.click('[data-ovnum="4"]');
    await app.click('[data-ovnum="2"]');
    await app.click('[data-ovnum="back"]');
    await app.click('[data-act="override-apply"]');
    eq(app.game(g.id).erfassung.bloecke[0][0].overrides[0], 4, '⌫ wirkte nicht');
    app.assertClean();
  });

  test('Statistik-Tab zeigt die Kennzahlen des Spielers', async (app) => {
    await starte(app, spielMitStand());
    await app.click('.ueber-tabs [data-uebertab="statistik"]');
    const t = app.txt('.stats-metrics');
    includes(t, 'Ø / Satz', 'Kennzahl fehlt');
    includes(t, 'bester Satz', 'Kennzahl fehlt');
    includes(t, '30', 'bester Satz von Anna');
    includes(t, 'Fehlwürfe', 'Kennzahl fehlt');
    app.assertClean();
  });

  test('Wurf-Bild zeigt die Häufigkeitsverteilung und lässt sich nach Satz filtern', async (app) => {
    await starte(app, spielMitStand());
    await app.click('.ueber-tabs [data-uebertab="verteilung"]');
    ok(app.$('[data-wb-satz]'), 'Satz-Filter fehlt');
    const alle = app.txt('.ueber-dist');
    ok(alle.length > 0, 'Verteilung leer');
    await app.click('[data-wb-satz="1"]');
    ok(app.$('[data-wb-satz="1"]').classList.contains('is-on'), 'Filter nicht aktiv');
    app.assertClean();
  });

  test('Satz- und Bahn-Filter im Wurf-Bild schließen sich gegenseitig aus', async (app) => {
    await starte(app, spielMitStand());
    await app.click('.ueber-tabs [data-uebertab="verteilung"]');
    await app.click('[data-wb-satz="0"]');
    await app.click('[data-wb-bahn="2"]');
    ok(app.$('[data-wb-bahn="2"]').classList.contains('is-on'), 'Bahn-Filter nicht aktiv');
    ok(app.$('[data-wb-satz="alle"]').classList.contains('is-on'), 'Satz-Filter nicht zurückgesetzt');
    app.assertClean();
  });

  test('Desktop-Kontrollzentrum stellt alle Spieler nebeneinander', async (app) => {
    await starte(app, spielMitStand(), DESKTOP);
    ok(app.$('.erf-ueber-multi'), 'Mehr-Spieler-Übersicht fehlt');
    eq(app.$$('.eum-col').length, 2, 'eine Spalte je Spieler');
    const namen = app.$$('.eum-col .ueber-name').map((e) => e.textContent.trim());
    deepEq(namen, ['Anna', 'Bert'], 'Spaltenköpfe');
    app.assertClean();
  });

  test('Desktop: Zell-Cursor bewegt sich mit den Pfeiltasten', async (app) => {
    await starte(app, spielMitStand(), DESKTOP);
    const cursorCell = () => app.$('.is-cursor');
    ok(cursorCell(), 'kein Start-Cursor');
    const vorher = cursorCell().dataset.editTs || cursorCell().dataset.editSatz;
    await app.key('ArrowRight');
    const nachher = cursorCell().dataset.editTs || cursorCell().dataset.editSatz;
    ok(vorher !== nachher, 'Cursor bewegte sich nicht');
    app.assertClean();
  });

  test('Desktop: „Nach Bahn ordnen" wird global gespeichert', async (app) => {
    await starte(app, spielMitStand(), DESKTOP);
    await app.click('[data-act="toggle-bahnfolge"]');
    eq(app.store('settings').uebersichtBahnFolge, true, 'Einstellung nicht gespeichert');
    app.assertClean();
  });

  test('Desktop: Statistik- und Wurf-Bild-Tab in der Satz-Zeile', async (app) => {
    await starte(app, spielMitStand(), DESKTOP);
    await app.click('.erf-stabs-side [data-uebertab="statistik"]');
    ok(app.$('.stats-metrics'), 'Statistik-Spalten fehlen');
    await app.click('.erf-stabs-side [data-uebertab="verteilung"]');
    ok(app.$('[data-wb-satz]'), 'Wurf-Bild-Filter fehlt');
    app.assertClean();
  });

  test('Statistik-Vollbild nach Spielende zeigt die Rangliste', async (app) => {
    const g = spielMitStand();
    g.status = 'beendet';
    g.erfassung = makeErfassung(g.config, [
      [[9, 9, 9, 9], [9, 9, 9, 9]],
      [[1, 1, 1, 1], [1, 1, 1, 1]],
    ]);
    await starte(app, g);
    const txt = app.page();
    includes(txt, '72', 'Gesamt Anna');
    includes(txt, '8', 'Gesamt Bert');
    includes(txt, '🥇', 'Platzierung fehlt');
    app.assertClean();
  });
});
