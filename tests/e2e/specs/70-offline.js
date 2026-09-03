// Die local-first-Zusage der App: OHNE Verbindung geht alles Lokale unverändert weiter,
// Netz-Aktionen scheitern sichtbar statt still, und es gehen keine Daten verloren.
//
// Damit das deterministisch prüfbar ist, setzt `boot({ offline: true })` den Test-Schalter,
// an dem js/backend/supabase.js auf einem Entwicklungs-Host absichtlich scheitert. Ohne ihn
// hinge das Ergebnis daran, ob der Rechner gerade Netz hat — der Test wäre wertlos.

import { suite, test, ok, eq, deepEq, includes } from '../harness.js';
import { makeGame, makeErfassung } from '../fixtures.js';
import { buildWettkampf } from '../../../js/logic/wettkampf-build.js';

const MOBIL = { width: 420, height: 900 };

// Ein Spiel, das bereits geteilt ist (hat also einen Server-Gegenpart).
function geteiltesSpiel() {
  const g = makeGame({
    preset: 'schere', saetze: 2, wuerfeProSatz: 4,
    teilsaetze: ['volle', 'volle'], bahnen: 2, spieler: ['Anna'],
  });
  g.status = 'laufend';
  g.linked = true;
  g.remoteId = 'r-123';
  g.beitrittsCode = 'AB12CD';
  g.erfassung = makeErfassung(g.config, [[[9, 8], []]], { done: [[false, false]] });
  return g;
}

function lokalerWettkampf({ linked = false } = {}) {
  const wk = buildWettkampf({
    name: 'Offline-Cup',
    datum: '2026-09-02',
    preset: 'schere',
    saetze: 2,
    wuerfeProSatz: 4,
    teilsaetze: ['volle', 'kranz-abraeumen'],
    bahnwechsel: 'plus1',
    anlageId: linked ? 'a1' : null,
    anlageName: linked ? 'Testhalle' : '',
    anlageBahnen: linked ? [1, 2, 3, 4].map((n) => ({ id: 'b' + n, nummer: n, bahnart: 'schere' })) : [],
    playedLanes: [1, 2, 3, 4],
    mannschaften: [
      { id: 'm1', name: 'Heim', lanes: [1, 2] },
      { id: 'm2', name: 'Gast', lanes: [3, 4] },
    ],
    spielerJeMannschaft: 2,
  });
  if (linked) { wk.wettkampf.linked = true; wk.wettkampf.remoteId = 'rw-1'; wk.wettkampf.beitrittsCode = 'WK1234'; }
  return wk;
}

suite('Offline · local-first', () => {
  test('Menü und lokale Historie stehen ohne Verbindung unverändert', async (app) => {
    const g = makeGame({ preset: 'schere', saetze: 1, wuerfeProSatz: 4, teilsaetze: ['volle'], bahnen: 1, spieler: ['Anna'] });
    g.status = 'beendet';
    g.erfassung = makeErfassung(g.config, [[[9, 9, 9, 9]]]);
    await app.boot({ hash: '/statistiken', ...MOBIL, offline: true, storage: { games: [g] } });
    eq(app.$$('.stat-card').length, 1, 'lokale Historie fehlt offline');
    includes(app.txt('.stat-card'), '36', 'Ergebnis fehlt');
    app.assertClean();
  });

  test('Würfe eines geteilten Spiels werden offline lokal gespeichert', async (app) => {
    const g = geteiltesSpiel();
    await app.boot({ hash: '/spiel-laufend', ...MOBIL, offline: true, storage: { games: [g], 'active-game': g.id } });
    await app.click('[data-act="satz-overview"]');
    await app.waitFor(() => !!app.$('[data-num="7"]'), 'Wurferfassung fehlt');
    await app.click('[data-num="7"]');
    deepEq(app.game(g.id).erfassung.bloecke[0][0].wuerfe, [9, 8, 7], 'Wurf ging offline verloren');
    app.assertClean();
  });

  test('Beitreten meldet den Fehlschlag, statt still nichts zu tun', async (app) => {
    await app.boot({ hash: '/beitreten', ...MOBIL, offline: true });
    await app.setInput('#join-code', 'AB12CD');
    await app.click('#join-go');
    await app.waitFor(() => {
      const t = app.txt('#join-msg');
      return t.length > 0 && !t.includes('Verbinde');
    }, 'keine Rückmeldung beim Beitreten', 8000);
    eq(app.games().length, 0, 'offline wurde ein Spiel angelegt');
    app.assertClean();
  });

  test('Wettkampf teilen scheitert sichtbar und lässt den Wettkampf unangetastet', async (app) => {
    const wk = lokalerWettkampf({ linked: false });
    // Anlage vortäuschen, damit nicht schon die Anlagen-Pflicht greift, sondern das Netz.
    wk.wettkampf.anlageId = 'a1';
    wk.wettkampf.anlageName = 'Testhalle';
    await app.boot({
      hash: '/wettkampf', ...MOBIL, offline: true,
      storage: { wettkaempfe: [wk.wettkampf], games: wk.games, 'active-wettkampf': wk.wettkampf.id },
    });
    const vorher = JSON.stringify(app.activeWettkampf());
    await app.click('[data-action="share"]');
    await app.waitFor(() => {
      const t = app.txt('[data-sync-msg]');
      return t.length > 0 && !t.includes('Teile Wettkampf');
    }, 'kein Hinweis auf den fehlgeschlagenen Teilen-Versuch', 8000);
    eq(JSON.stringify(app.activeWettkampf()), vorher, 'Wettkampf wurde trotz Fehlschlag verändert');
    ok(!app.activeWettkampf().linked, 'Wettkampf gilt fälschlich als geteilt');
    app.assertClean();
  });

  test('Anlage nachtragen meldet offline einen klaren Fehler', async (app) => {
    const wk = lokalerWettkampf({ linked: false });
    await app.boot({
      hash: '/wettkampf', ...MOBIL, offline: true,
      storage: { wettkaempfe: [wk.wettkampf], games: wk.games, 'active-wettkampf': wk.wettkampf.id },
    });
    await app.waitFor(() => app.txt('[data-anlage-msg]').length > 0,
      'kein Hinweis, dass die Anlagen nicht geladen werden konnten', 8000);
    includes(app.txt('[data-anlage-msg]'), 'nicht geladen', 'Fehlermeldung unklar');
    eq(app.activeWettkampf().anlageId, null, 'Anlage wurde trotz Fehler gesetzt');
    app.assertClean();
  });

  // Die eigene Arbeitsliste gehoert MIR — auch ohne Verbindung. Frueher blieb ein geteiltes
  // Spiel hier stehen, weil das Entfernen den Freigabe-Link kappte und damit alle Beteiligten
  // traf; das tut es nicht mehr (es ist eine rein persoenliche Notiz). Also verschwindet die
  // eigene Kopie IMMER, und die App sagt ehrlich, dass der Konto-Vermerk noch aussteht.
  test('Geteiltes Spiel lässt sich offline aus „Fortsetzen" entfernen', async (app) => {
    const g = geteiltesSpiel();
    await app.boot({ hash: '/neues-spiel', ...MOBIL, offline: true, storage: { games: [g] } });
    eq(app.$$('[data-del]').length, 1, 'Spiel wird nicht zum Fortsetzen angeboten');
    app.confirmAnswer = true;
    await app.click('[data-del]');
    await app.waitFor(() => app.games().length === 0, 'Spiel blieb trotz Löschen liegen', 8000);
    await app.waitFor(() => app.alerts.length > 0, 'kein Hinweis auf den fehlenden Vermerk', 8000);
    includes(app.alerts[0], 'entfernt', 'Hinweis sagt nicht, dass es entfernt wurde');
    includes(app.alerts[0], 'wieder auftauchen', 'Hinweis verschweigt, dass es wiederkommen kann');
    app.assertClean();
  });

  test('Geteilter Wettkampf lässt sich offline entfernen', async (app) => {
    const wk = lokalerWettkampf({ linked: true });
    await app.boot({
      hash: '/neues-spiel', ...MOBIL, offline: true,
      storage: { wettkaempfe: [wk.wettkampf], games: wk.games },
    });
    eq(app.$$('[data-del-wk]').length, 1, 'Wettkampf wird nicht angeboten');
    app.confirmAnswer = true;
    await app.click('[data-del-wk]');
    await app.waitFor(() => app.wettkaempfe().length === 0, 'Wettkampf blieb liegen', 8000);
    eq(app.games().filter((g) => g.wettkampfId === wk.wettkampf.id).length, 0,
      'Durchgänge blieben liegen');
    app.assertClean();
  });

  test('Ein rein lokales Spiel lässt sich offline ganz normal löschen', async (app) => {
    const g = makeGame({ preset: 'schere', saetze: 1, wuerfeProSatz: 4, teilsaetze: ['volle'], bahnen: 1, spieler: ['Anna'] });
    g.status = 'laufend';
    g.erfassung = makeErfassung(g.config, [[[9]]], { done: [[false]] });
    await app.boot({ hash: '/neues-spiel', ...MOBIL, offline: true, storage: { games: [g] } });
    app.confirmAnswer = true;
    await app.click('[data-del]');
    await app.waitFor(() => app.games().length === 0, 'lokales Spiel ließ sich offline nicht löschen');
    eq(app.alerts.length, 0, 'unnötige Fehlermeldung bei einem rein lokalen Spiel');
    app.assertClean();
  });

  test('Account- und Anlagen-Seite montieren offline ohne Absturz', async (app) => {
    await app.boot({ hash: '/spieler', ...MOBIL, offline: true });
    await app.settle(6);
    ok(app.page().length > 0, 'Spieler-Seite blieb leer');
    await app.go('/anlagen');
    await app.settle(6);
    ok(app.page().length > 0, 'Anlagen-Seite blieb leer');
    app.assertClean();
  });
});
