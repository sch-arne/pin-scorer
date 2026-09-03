// Views, die ein Backend brauchen (Account, Anlagen, Beitreten, Sportwinner-Import,
// Overlay). Diese Tests prüfen KEINE Server-Antworten — sie prüfen, dass die Views
// ohne Anmeldung und ohne Daten sauber montieren, ihren Leerzustand zeigen und beim
// Bedienen keine unbehandelten Fehler werfen (local-first-Zusage der App).
//
// Ausserdem: Statistiken-View und der Aufruf eines beendeten Spiels aus der Historie.

import { suite, test, ok, eq, deepEq, includes } from '../harness.js';
import { makeGame, makeErfassung } from '../fixtures.js';
import { buildWettkampf } from '../../../js/logic/wettkampf-build.js';

const MOBIL = { width: 420, height: 900 };

// Ein beendetes Trainingsspiel — optional auf einer Anlage und mit gesetztem Zeitpunkt
// (fuer die Reihenfolge in der Historie).
function training({ spieler = ['Anna', 'Bert'], anlageId = null, anlageName = '', ts = null } = {}) {
  const g = makeGame({
    preset: 'schere', saetze: 1, wuerfeProSatz: 4, teilsaetze: ['volle'], bahnen: 2, spieler,
  });
  g.status = 'beendet';
  g.erfassung = makeErfassung(g.config, spieler.map((_, i) => [[9 - i, 9 - i, 9 - i, 9 - i]]));
  if (anlageId) { g.config.anlageId = anlageId; g.config.anlageName = anlageName; }
  if (ts) { g.createdAt = ts; g.updatedAt = ts; }
  return g;
}

// Ein fertiger Wettkampf (2 Mannschaften a 2 Spieler auf 4 Bahnen -> 1 Durchgang) samt
// Wuerfen, damit er als EIN Eintrag in der Historie steht.
function wettkampfMitErgebnis() {
  const { wettkampf, games } = buildWettkampf({
    name: 'Filter-Cup', datum: '2026-02-15', preset: 'schere',
    saetze: 1, wuerfeProSatz: 4, teilsaetze: ['volle'], bahnwechsel: 'plus1',
    anlageId: 'anl-2', anlageName: 'Kegelzentrum',
    anlageBahnen: [1, 2, 3, 4].map((n) => ({ id: 'b' + n, nummer: n, bahnart: 'schere' })),
    playedLanes: [1, 2, 3, 4],
    mannschaften: [{ id: 'm1', name: 'Heim', lanes: [1, 2] }, { id: 'm2', name: 'Gast', lanes: [3, 4] }],
    spielerJeMannschaft: 2,
  });
  games.forEach((g) => {
    g.erfassung = makeErfassung(g.config, g.config.spielerListe.map(() => [[7, 7, 7, 7]]));
    g.status = 'beendet';
    g.updatedAt = '2026-02-15T10:00:00.000Z';
  });
  wettkampf.updatedAt = '2026-02-15T10:00:00.000Z';
  return { wettkampf, games };
}

suite('Statistiken', () => {
  test('Leere Historie zeigt den Hinweistext', async (app) => {
    await app.boot({ hash: '/statistiken', ...MOBIL });
    includes(app.page(), 'Noch keine Daten', 'Leerzustand fehlt');
    app.assertClean();
  });

  test('Beendetes Spiel erscheint als Karte mit Ergebnis', async (app) => {
    const g = makeGame({ preset: 'schere', saetze: 2, wuerfeProSatz: 4, teilsaetze: ['volle', 'volle'], bahnen: 2, spieler: ['Anna', 'Bert'] });
    g.status = 'beendet';
    g.erfassung = makeErfassung(g.config, [
      [[9, 9, 9, 9], [9, 9, 9, 9]],
      [[2, 2, 2, 2], [2, 2, 2, 2]],
    ]);
    await app.boot({ hash: '/statistiken', ...MOBIL, storage: { games: [g] } });
    eq(app.$$('.stat-card').length, 1, 'keine Spielkarte');
    includes(app.txt('.stat-card'), 'Anna', 'Spielername');
    includes(app.txt('.stat-card'), '72', 'Gesamtholz Anna');
    includes(app.txt('.stat-card'), '🥇', 'Platzierung');
    includes(app.txt('.stat-card'), 'Beendet', 'Status-Abzeichen');
    app.assertClean();
  });

  test('Karte antippen ruft das beendete Spiel wieder auf', async (app) => {
    const g = makeGame({ preset: 'schere', saetze: 1, wuerfeProSatz: 4, teilsaetze: ['volle'], bahnen: 1, spieler: ['Anna'] });
    g.status = 'beendet';
    g.erfassung = makeErfassung(g.config, [[[9, 9, 9, 9]]]);
    await app.boot({ hash: '/statistiken', ...MOBIL, storage: { games: [g] } });
    await app.click('[data-open]');
    await app.waitFor(() => app.route() === '/spiel-laufend', 'Spiel wurde nicht geöffnet');
    eq(app.store('active-game'), g.id, 'falsches Spiel aktiviert');
    app.assertClean();
  });

  test('Laufendes Spiel ist in der Historie sichtbar, aber nicht anklickbar', async (app) => {
    const g = makeGame({ preset: 'schere', saetze: 1, wuerfeProSatz: 4, teilsaetze: ['volle'], bahnen: 1, spieler: ['Anna'] });
    g.status = 'laufend';
    g.erfassung = makeErfassung(g.config, [[[9, 9]]], { done: [[false]] });
    await app.boot({ hash: '/statistiken', ...MOBIL, storage: { games: [g] } });
    includes(app.txt('.stat-card'), 'Läuft', 'Status-Abzeichen');
    eq(app.$$('[data-open]').length, 0, 'laufendes Spiel war anklickbar');
    app.assertClean();
  });

  test('Trainingsspiel lässt sich nachträglich dem eigenen Profil zuordnen', async (app) => {
    // Der ★ im Setup wurde vergessen — nachholen muss trotzdem gehen, sonst käme das
    // Ergebnis nie in die eigene Statistik.
    const g = training();
    await app.boot({ hash: '/statistiken', ...MOBIL, storage: { games: [g] } });
    ok(app.$(`[data-zu-select="${g.id}"]`), 'Zuordnungs-Auswahl fehlt');
    includes(app.txt('.stat-zuordnung'), 'nur auf diesem Gerät',
      'Hinweis zum ungeteilten Spiel fehlt');
    await app.setSelect(`[data-zu-select="${g.id}"]`, '1');
    await app.click(`[data-zu-set="${g.id}"]`);
    await app.waitFor(() => app.game(g.id).ichIndex === 1, 'Zuordnung nicht gespeichert');
    await app.waitFor(() => !!app.$(`[data-zu-clear="${g.id}"]`), 'Karte zeigt die Zuordnung nicht');
    includes(app.txt('.stat-zuordnung'), 'Bert', 'zugeordneter Spieler');
    includes(app.txt('.stat-card'), '★ du', 'eigene Ergebniszeile nicht hervorgehoben');
    await app.click(`[data-zu-clear="${g.id}"]`);
    await app.waitFor(() => app.game(g.id).ichIndex === null, 'Zuordnung nicht gelöst');
    await app.waitFor(() => !!app.$(`[data-zu-select="${g.id}"]`), 'Auswahl kam nicht zurück');
    app.assertClean();
  });

  test('Historie lässt sich nach Anlage filtern und umsortieren', async (app) => {
    const nord = training({ spieler: ['Anna'], anlageId: 'anl-1', anlageName: 'Halle Nord', ts: '2026-02-01T10:00:00.000Z' });
    const zentrum = training({ spieler: ['Bert'], anlageId: 'anl-2', anlageName: 'Kegelzentrum', ts: '2026-03-01T10:00:00.000Z' });
    const ohne = training({ spieler: ['Cem'], ts: '2026-01-01T10:00:00.000Z' });
    await app.boot({ hash: '/statistiken', ...MOBIL, storage: { games: [nord, zentrum, ohne] } });
    const sichtbar = () => app.$$('.stat-card:not([hidden])');
    eq(sichtbar().length, 3, 'alle Karten sichtbar');
    ok(app.$('#stat-filter').offsetParent !== null, 'Filterleiste fehlt');
    // Die Anlage steht an der Karte selbst (neueste zuerst -> Kegelzentrum oben).
    includes(sichtbar()[0].textContent, '📍 Kegelzentrum', 'Anlage steht nicht an der Karte');
    includes(sichtbar()[1].textContent, '📍 Halle Nord', 'Anlage steht nicht an der Karte');

    await app.setSelect('#stat-f-anlage', 'anl-1');
    eq(sichtbar().length, 1, 'Anlagen-Filter greift nicht');
    includes(sichtbar()[0].textContent, 'Anna', 'falsche Karte übrig');

    await app.setSelect('#stat-f-anlage', 'ohne');
    eq(sichtbar().length, 1, '„Ohne Anlage" greift nicht');
    includes(sichtbar()[0].textContent, 'Cem', 'falsche Karte übrig');

    await app.setSelect('#stat-f-anlage', '');
    await app.setSelect('#stat-f-sort', 'alt');
    includes(sichtbar()[0].textContent, 'Cem', 'älteste Karte steht nicht oben');
    app.assertClean();
  });

  // Geprueft wird die SICHTBARKEIT, nicht das hidden-Attribut. Genau daran lag ein Fehler:
  // das Attribut sass richtig, aber `.stat-filter { display: flex }` schlug das `display: none`
  // des Browsers — die Leiste stand trotzdem da. Ein Test auf `.hidden` haette das nie gesehen.
  test('Bei nur einer Art auf einer Anlage bleibt die Filterleiste weg', async (app) => {
    const g = training({ spieler: ['Anna'], anlageId: 'anl-1', anlageName: 'Halle Nord' });
    await app.boot({ hash: '/statistiken', ...MOBIL, storage: { games: [g] } });
    eq(app.$$('.stat-card').length, 1, 'Karte fehlt');
    const bar = app.$('#stat-filter');
    ok(bar.hidden, 'Filterleiste ist nicht als ausgeblendet markiert');
    ok(bar.offsetParent === null, 'Filterleiste steht trotz hidden sichtbar auf der Seite');
    app.assertClean();
  });

  test('Filter trennt Training und Wettkampf', async (app) => {
    const g = training({ spieler: ['Anna'], ts: '2026-02-20T10:00:00.000Z' });
    const wk = wettkampfMitErgebnis();
    await app.boot({
      hash: '/statistiken', ...MOBIL,
      storage: { games: [g, ...wk.games], wettkaempfe: [wk.wettkampf] },
    });
    const sichtbar = () => app.$$('.stat-card:not([hidden])');
    eq(sichtbar().length, 2, 'Training + Wettkampf als je EIN Eintrag');
    includes(app.txt('#stat-f-art'), 'Sportkegeln-Training', 'Spielart-Auswahl fehlt');

    await app.setSelect('#stat-f-art', 'sportkegler-wettkampf');
    eq(sichtbar().length, 1, 'Spielart-Filter greift nicht');
    includes(sichtbar()[0].textContent, 'Filter-Cup', 'falscher Eintrag übrig');

    await app.setSelect('#stat-f-art', 'sportkegler-wk');
    eq(sichtbar().length, 1, 'Spielart-Filter greift nicht');
    includes(sichtbar()[0].textContent, 'Anna', 'falscher Eintrag übrig');

    // Anlage und Spielart wirken zusammen: das Training war ohne Anlage.
    await app.setSelect('#stat-f-anlage', 'anl-2');
    eq(sichtbar().length, 0, 'Filter wirken nicht zusammen');
    includes(app.page(), 'Keine Spiele passen', 'Hinweis auf die leere Auswahl fehlt');
    app.assertClean();
  });
});

suite('Backend-Views (ohne Anmeldung)', () => {
  test('Spieler/Account zeigt Anmelden & Registrieren', async (app) => {
    await app.boot({ hash: '/spieler', ...MOBIL });
    await app.waitFor(() => !!app.$('#acc-email'), 'Anmeldeformular erschien nicht', 8000);
    ok(app.$('#acc-pw'), 'Passwortfeld fehlt');
    ok(app.$('#acc-go'), 'Anmelde-Knopf fehlt');
    app.assertClean();
  });

  test('Anmeldung ohne Eingaben meldet sauber statt zu stürzen', async (app) => {
    await app.boot({ hash: '/spieler', ...MOBIL });
    await app.waitFor(() => !!app.$('#acc-go'), 'Anmeldeformular erschien nicht', 8000);
    await app.click('#acc-go');
    await app.waitFor(() => app.txt('#acc-msg').length > 0, 'keine Rückmeldung', 8000);
    app.assertClean();
  });

  test('Passwort-Sichtbarkeit lässt sich umschalten', async (app) => {
    await app.boot({ hash: '/spieler', ...MOBIL });
    await app.waitFor(() => !!app.$('#acc-eye'), 'Auge-Knopf fehlt', 8000);
    eq(app.$('#acc-pw').type, 'password', 'Startzustand');
    await app.click('#acc-eye');
    eq(app.$('#acc-pw').type, 'text', 'Umschalten wirkte nicht');
    app.assertClean();
  });

  test('Anlagen-Verwaltung montiert und zeigt ihren Zustand', async (app) => {
    await app.boot({ hash: '/anlagen', ...MOBIL });
    includes(app.txt('.page-title'), 'Anlage', 'Kopfzeile');
    await app.settle(4);
    app.assertClean();
  });

  test('Beitreten: leerer Code wird abgefangen', async (app) => {
    await app.boot({ hash: '/beitreten', ...MOBIL });
    await app.click('#join-go');
    includes(app.txt('#join-msg'), 'Code eingeben', 'Hinweis fehlt');
    app.assertClean();
  });

  test('Beitreten: Eingabe wird in Großbuchstaben normalisiert', async (app) => {
    await app.boot({ hash: '/beitreten', ...MOBIL });
    await app.setInput('#join-code', 'ab12cd');
    eq(app.$('#join-code').value, 'AB12CD', 'Code nicht normalisiert');
    app.assertClean();
  });

  test('Sportwinner-Import montiert ohne Brücke', async (app) => {
    await app.boot({ hash: '/import/sportwinner', ...MOBIL });
    includes(app.page(), 'Sportwinner', 'Kopfzeile');
    await app.settle(4);
    app.assertClean();
  });

  test('Overlay ohne Code sagt, dass der Code fehlt', async (app) => {
    await app.boot({ hash: '/overlay', ...MOBIL });
    ok(app.$('.ov-root'), 'Overlay-Wurzel fehlt');
    await app.waitFor(() => app.txt('.ov-root').includes('Kein Code'), 'Hinweis auf den fehlenden Code fehlt');
    await app.settle(6);
    app.assertClean();
  });

  test('Overlay mit unbekanntem Code bleibt beim Wartezustand', async (app) => {
    await app.boot({ hash: '/overlay?code=ZZZZZZ', ...MOBIL });
    ok(app.$('.ov-root'), 'Overlay-Wurzel fehlt');
    await app.settle(6);
    ok(app.txt('.ov-root').length > 0, 'Overlay blieb leer');
    app.assertClean();
  });
});
