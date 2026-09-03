// Router + Grundgeruest: jede registrierte Route muss ohne unbehandelten Fehler
// montieren und ihren Kopf zeigen — auch ohne jegliche Daten (Erststart).

import { suite, test, ok, eq, includes } from '../harness.js';

const ROUTES = [
  { path: '/menu', marker: 'Pin-Scorer' },
  { path: '/neues-spiel', marker: 'Neues Spiel' },
  { path: '/statistiken', marker: 'Statistiken' },
  { path: '/setup/sportkegler-wk', marker: 'Bahnart' },
  { path: '/setup/wettkampf', marker: 'Wettkampf' },
  { path: '/wettkampf', marker: 'Wettkampf' },
  { path: '/spiel-laufend', marker: 'Kein Spiel' },
  { path: '/beitreten', marker: 'Code' },
  { path: '/spieler', marker: 'Spieler' },
  { path: '/anlagen', marker: 'Anlage' },
  { path: '/import/sportwinner', marker: 'Sportwinner' },
];

suite('Router & Einstieg', () => {
  test('Hauptmenü zeigt alle fünf Kacheln', async (app) => {
    await app.boot({ hash: '/menu' });
    const tiles = app.$$('.tile');
    eq(tiles.length, 5, 'Anzahl Kacheln');
    const labels = tiles.map((t) => t.querySelector('.tile-label').textContent);
    ['Neues Spiel', 'Spiel beitreten', 'Statistiken', 'Spieler', 'Anlagen']
      .forEach((l) => ok(labels.includes(l), `Kachel "${l}" fehlt`));
    app.assertClean();
  });

  test('Alle registrierten Routen montieren ohne Fehler (leerer Erststart)', async (app) => {
    await app.boot({ hash: '/menu' });
    const probleme = [];
    for (const r of ROUTES) {
      await app.go(r.path);
      const txt = app.page();
      if (!txt) probleme.push(`${r.path}: leere Seite`);
      else if (!txt.includes(r.marker)) probleme.push(`${r.path}: "${r.marker}" fehlt — "${txt.slice(0, 120)}"`);
    }
    ok(probleme.length === 0, probleme.join('\n'));
    app.assertClean('Routen-Rundgang');
  });

  test('Unbekannte Route fällt auf das Menü zurück', async (app) => {
    await app.boot({ hash: '/gibt-es-nicht' });
    includes(app.page(), 'Deine Kegel-Würfe im Blick', 'notFound zeigt das Menü');
    app.assertClean();
  });

  test('Navigation über die Kacheln und zurück', async (app) => {
    await app.boot({ hash: '/menu' });
    await app.clickText('.tile', 'Neues Spiel');
    await app.waitFor(() => app.route() === '/neues-spiel', 'Kachel navigierte nicht');
    await app.click('.back-btn');
    await app.waitFor(() => app.route() === '/menu', 'Zurück-Pfeil navigierte nicht');
    app.assertClean();
  });

  test('Overlay-Route liest den Code aus dem Query-Teil des Hashes', async (app) => {
    await app.boot({ hash: '/overlay?code=ABCD' });
    eq(app.route(), '/overlay', 'Query darf die Route nicht verändern');
    // Ohne erreichbaren Server bleibt der Wartetext stehen — Hauptsache: kein Absturz.
    ok(app.$('.ov-root'), 'Overlay-Wurzel fehlt');
    app.assertClean();
  });

  test('Router meldet der alten View das Abräumen, bevor er sie ersetzt', async (app) => {
    // Views hängen ihr Aufräumen (Timer, Realtime-Abos, globale Klassen) an dieses Ereignis.
    // Früher lief das über „hashchange" — das feuert aber NICHT, wenn navigate() bei
    // gleichem Pfad direkt neu rendert; die alte View blieb dann mit ihren Timern liegen.
    await app.boot({ hash: '/menu' });
    let gemeldet = 0;
    app.win.addEventListener('pins:view-unmount', () => { gemeldet += 1; });
    await app.go('/statistiken');
    ok(gemeldet >= 1, 'kein Abräum-Signal beim Ansichtswechsel');
    await app.go('/menu');
    ok(gemeldet >= 2, 'Abräum-Signal kam nur einmal');
    app.assertClean();
  });

  test('Overlay räumt seinen Body-Modus beim Verlassen wieder auf', async (app) => {
    await app.boot({ hash: '/overlay?code=ABCD' });
    ok(app.doc.body.classList.contains('overlay-mode'), 'overlay-mode wurde nicht gesetzt');
    await app.go('/menu');
    await app.waitFor(() => !app.doc.body.classList.contains('overlay-mode'),
      'overlay-mode blieb nach dem Verlassen stehen');
    ok(!app.doc.documentElement.classList.contains('overlay-mode'), 'html behielt overlay-mode');
    app.assertClean();
  });
});
