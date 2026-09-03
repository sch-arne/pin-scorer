// Spiele und Wettkämpfe löschen — die drei Fälle, die die App unterscheiden MUSS:
//
//   1) rein LOKAL      -> komplett weg (localStorage), auch aus der Historie heraus,
//   2) in der DATENBANK -> nur für MICH unsichtbar (Übersicht + Statistik). Die Daten bleiben,
//                          der Freigabe-Link gilt weiter, Mitspieler merken nichts,
//   3) über die LIZENZ  -> gar nicht löschbar (fremd erfasst, gehört mir nicht).
//
// Getestet wird über die echte Oberfläche. Alles Netzabhängige läuft offline: Fall 2 muss
// dann sichtbar scheitern und darf lokal NICHTS entfernen, Fall 1 muss trotzdem gehen.

import { suite, test, ok, eq, includes } from '../harness.js';
import { makeGame, makeErfassung } from '../fixtures.js';
import { buildWettkampf } from '../../../js/logic/wettkampf-build.js';

const MOBIL = { width: 420, height: 900 };

// Ein beendetes, rein lokales Trainingsspiel.
function lokalesSpiel(spieler = ['Anna', 'Bert']) {
  const g = makeGame({
    preset: 'schere', saetze: 1, wuerfeProSatz: 4, teilsaetze: ['volle'], bahnen: 2, spieler,
  });
  g.status = 'beendet';
  g.erfassung = makeErfassung(g.config, spieler.map((_, i) => [[9 - i, 9 - i, 9 - i, 9 - i]]));
  return g;
}

// Dasselbe Spiel, aber mit Gegenpart in der Datenbank.
function dbSpiel() {
  const g = lokalesSpiel(['Cara']);
  g.linked = true;
  g.remoteId = 'r-777';
  g.beitrittsCode = 'ZZ99YY';
  return g;
}

function beendeterWettkampf({ linked = false } = {}) {
  const wk = buildWettkampf({
    name: 'Lösch-Cup', datum: '2026-03-01', preset: 'schere',
    saetze: 1, wuerfeProSatz: 4, teilsaetze: ['volle'], bahnwechsel: 'plus1',
    anlageId: linked ? 'a1' : null, anlageName: linked ? 'Testhalle' : '',
    anlageBahnen: linked ? [1, 2, 3, 4].map((n) => ({ id: 'b' + n, nummer: n, bahnart: 'schere' })) : [],
    playedLanes: [1, 2, 3, 4],
    mannschaften: [{ id: 'm1', name: 'Heim', lanes: [1, 2] }, { id: 'm2', name: 'Gast', lanes: [3, 4] }],
    spielerJeMannschaft: 2,
  });
  wk.games.forEach((g) => {
    g.erfassung = makeErfassung(g.config, g.config.spielerListe.map(() => [[7, 7, 7, 7]]));
    g.status = 'beendet';
  });
  wk.wettkampf.status = 'beendet';
  if (linked) {
    wk.wettkampf.linked = true;
    wk.wettkampf.remoteId = 'rw-777';
    wk.wettkampf.beitrittsCode = 'WK99ZZ';
  }
  return wk;
}

suite('Löschen', () => {
  test('Beendetes lokales Spiel lässt sich aus den Statistiken löschen', async (app) => {
    const g = lokalesSpiel();
    await app.boot({ hash: '/statistiken', ...MOBIL, offline: true, storage: { games: [g] } });
    eq(app.$$('.stat-card').length, 1, 'Spiel fehlt in der Historie');
    eq(app.$$('[data-del-spiel]').length, 1, 'kein Löschen-Knopf an der Karte');
    app.confirmAnswer = true;
    await app.click('[data-del-spiel]');
    await app.waitFor(() => app.games().length === 0, 'Spiel wurde nicht gelöscht');
    eq(app.$$('.stat-card').length, 0, 'Karte steht noch in der Historie');
    app.assertClean();
  });

  test('Beendeter lokaler Wettkampf lässt sich aus den Statistiken löschen', async (app) => {
    const wk = beendeterWettkampf();
    await app.boot({
      hash: '/statistiken', ...MOBIL, offline: true,
      storage: { wettkaempfe: [wk.wettkampf], games: wk.games },
    });
    eq(app.$$('[data-del-wk]').length, 1, 'kein Löschen-Knopf an der Wettkampf-Karte');
    app.confirmAnswer = true;
    await app.click('[data-del-wk]');
    await app.waitFor(() => app.wettkaempfe().length === 0, 'Wettkampf wurde nicht gelöscht');
    eq(app.games().length, 0, 'Durchgänge blieben liegen');
    app.assertClean();
  });

  // Die eigene Kopie verschwindet IMMER — sie gehoert mir und niemandem sonst. Nur der
  // Vermerk fuers Konto braucht Verbindung; fehlt er, wird das gesagt statt verschwiegen.
  test('Spiel aus der Datenbank geht offline weg — mit ehrlichem Hinweis', async (app) => {
    const g = dbSpiel();
    await app.boot({ hash: '/statistiken', ...MOBIL, offline: true, storage: { games: [g] } });
    eq(app.$$('[data-del-spiel]').length, 1, 'kein Löschen-Knopf an der Karte');
    app.confirmAnswer = true;
    await app.click('[data-del-spiel]');
    await app.waitFor(() => app.games().length === 0, 'Spiel blieb trotz Löschen liegen', 8000);
    await app.waitFor(() => app.alerts.length > 0, 'kein Hinweis auf den fehlenden Vermerk', 8000);
    includes(app.alerts[0], 'wieder auftauchen', 'Hinweis verschweigt, dass es wiederkommen kann');
    app.assertClean();
  });

  // Ein Spiel, dem ich nur BEIGETRETEN bin (fremdes Konto): in der Datenbank gehoert mir
  // nichts davon, aber die Kopie auf diesem Geraet darf ich wegraeumen — auch waehrend
  // anderswo noch erfasst wird.
  test('Beigetretenes Spiel lässt sich von diesem Gerät entfernen', async (app) => {
    const g = dbSpiel();
    g.besitzer = 'fremdes-konto';
    g.status = 'laufend';
    await app.boot({ hash: '/neues-spiel', ...MOBIL, offline: true, storage: { games: [g] } });
    eq(app.$$('[data-del]').length, 1, 'Spiel wird nicht zum Fortsetzen angeboten');
    app.confirmAnswer = false;
    await app.click('[data-del]');
    await app.waitFor(() => app.confirms.length > 0, 'es wurde gar nicht gefragt', 8000);
    includes(app.confirms[0], 'von diesem Gerät', 'Frage nennt nicht, dass nur die Kopie geht');
    includes(app.confirms[0], 'wieder beitreten', 'Frage verschweigt den Weg zurück');
    eq(app.games().length, 1, 'Abbruch entfernte trotzdem');
    app.confirmAnswer = true;
    await app.click('[data-del]');
    await app.waitFor(() => app.games().length === 0, 'Kopie blieb liegen', 8000);
    eq(app.alerts.length, 0, 'unnötiger Hinweis — in der Datenbank war nichts zu vermerken');
    app.assertClean();
  });

  test('Die Frage nennt beim DB-Spiel das Verbergen, beim lokalen das Löschen', async (app) => {
    await app.boot({ hash: '/statistiken', ...MOBIL, offline: true, storage: { games: [lokalesSpiel()] } });
    app.confirmAnswer = false;
    await app.click('[data-del-spiel]');
    await app.waitFor(() => app.confirms.length > 0, 'es wurde gar nicht gefragt', 8000);
    includes(app.confirms[0], 'endgültig', 'lokale Frage sagt nicht, dass es endgültig ist');
    eq(app.games().length, 1, 'Abbruch löschte trotzdem');

    await app.boot({ hash: '/statistiken', ...MOBIL, offline: true, storage: { games: [dbSpiel()] } });
    app.confirmAnswer = false;
    await app.click('[data-del-spiel]');
    await app.waitFor(() => app.confirms.length > 0, 'es wurde gar nicht gefragt', 8000);
    includes(app.confirms[0], 'bleiben', 'DB-Frage sagt nicht, dass die Daten erhalten bleiben');
    // Der Punkt, auf den es ankommt: es trifft nur mich, nicht die Mitspieler.
    includes(app.confirms[0], 'nur für dich', 'DB-Frage sagt nicht, dass es nur für mich gilt');
    includes(app.confirms[0], 'gilt weiter', 'DB-Frage verschweigt, dass der Link weiter gilt');
    app.assertClean();
  });
});
