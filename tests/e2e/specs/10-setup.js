// Setup „Sportkegeln-Training" (setup-wk.js) durch die echte Maske geklickt.

import { suite, test, ok, eq, deepEq, includes } from '../harness.js';

const SETUP = '/setup/sportkegler-wk';

suite('Setup Training', () => {
  test('Bohle ist voreingestellt (4 Sätze · 30 Würfe · 2× Volle · 4 Bahnen)', async (app) => {
    await app.boot({ hash: SETUP });
    ok(app.$('.seg-btn.is-active').textContent.includes('Bohle'), 'Bohle nicht aktiv');
    eq(app.$('[data-bahnen].is-active').textContent.trim(), '4', 'Anzahl Bahnen');
    eq(app.$('[data-input="spieler"]').value, '1', 'Anzahl Spieler');
    eq(app.$('[data-field="bahnwechsel"]').value, 'bohle', 'Bahnwechsel-Voreinstellung');

    await app.click('[data-tab="optionen"]');
    eq(app.$('[data-input="saetze"]').value, '4', 'Sätze');
    eq(app.$('[data-input="wuerfeProSatz"]').value, '30', 'Würfe pro Satz');
    includes(app.txt('.field-readout'), '120', 'Gesamtwurfzahl');
    const modi = app.$$('.part-modus').map((s) => s.value);
    deepEq(modi, ['volle', 'volle'], 'Teilsatz-Modi');
    app.assertClean();
  });

  test('Bahnart-Wechsel setzt das ganze Programm um (Schere / Classic)', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-preset="schere"]');
    await app.click('[data-tab="optionen"]');
    deepEq(app.$$('.part-modus').map((s) => s.value), ['volle', 'kranz-abraeumen'], 'Schere-Teilsätze');
    await app.click('[data-tab="modus"]');
    eq(app.$('[data-field="bahnwechsel"]').value, 'plus1', 'Schere-Bahnwechsel');

    await app.click('[data-preset="classic"]');
    await app.click('[data-tab="optionen"]');
    deepEq(app.$$('.part-modus').map((s) => s.value), ['volle', 'abraeumen'], 'Classic-Teilsätze');
    app.assertClean();
  });

  test('Spielerzahl ist auf die Bahnenzahl gedeckelt', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-bahnen="2"]');
    for (let i = 0; i < 5; i++) await app.click('[data-step="inc"][data-field="spieler"]');
    eq(app.$('[data-input="spieler"]').value, '2', 'Spieler über Bahnenzahl hinaus erhöht');
    // Direkteingabe muss ebenso klemmen.
    await app.setInput('[data-input="spieler"]', '9');
    eq(app.$('[data-input="spieler"]').value, '2', 'Direkteingabe nicht geklemmt');
    // Zurück auf 1 und darunter nicht.
    await app.click('[data-step="dec"][data-field="spieler"]');
    await app.click('[data-step="dec"][data-field="spieler"]');
    eq(app.$('[data-input="spieler"]').value, '1', 'Untergrenze 1 verletzt');
    app.assertClean();
  });

  test('Teilsatz-Anzahl bietet nur Teiler und passt sich an Würfe/Satz an', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-tab="optionen"]');
    const chips = () => app.$$('[data-teilsatz]').map((b) => b.textContent.trim());
    deepEq(chips(), ['1', '2', '3', '5', '6', '10', '15', '30'], 'Teiler von 30');
    await app.click('[data-teilsatz="3"]');
    eq(app.$$('.part-modus').length, 3, 'drei Teilsätze');
    includes(app.txt('.parts'), '10 Wurf', 'Würfe je Teilsatz');
    // 30 -> 28: 3 teilt 28 nicht, die Anzahl muss auf den nächsten Teiler rutschen.
    await app.setInput('[data-input="wuerfeProSatz"]', '28');
    const n = app.$$('.part-modus').length;
    ok(28 % n === 0, `Teilsatz-Anzahl ${n} teilt 28 nicht`);
    app.assertClean();
  });

  test('Startbahn-Wechsel tauscht statt doppelt zu belegen', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-bahnen="4"]');
    for (let i = 0; i < 3; i++) await app.click('[data-step="inc"][data-field="spieler"]');
    await app.click('[data-tab="spieler"]');
    const lanes = () => app.$$('.player-lane').map((s) => parseInt(s.value, 10));
    deepEq(lanes(), [1, 2, 3, 4], 'Startbelegung');
    await app.setSelect('.player-lane[data-player="0"]', '3');
    deepEq(lanes(), [3, 2, 1, 4], 'Tausch Spieler 1 <-> Spieler 3');
    ok(new Set(lanes()).size === 4, 'Bahn doppelt belegt');
    app.assertClean();
  });

  test('Zufällige Startbahnen bleiben eine Permutation', async (app) => {
    await app.boot({ hash: SETUP });
    for (let i = 0; i < 3; i++) await app.click('[data-step="inc"][data-field="spieler"]');
    await app.click('[data-tab="spieler"]');
    for (let r = 0; r < 5; r++) {
      await app.click('[data-action="shuffle"]');
      const lanes = app.$$('.player-lane').map((s) => parseInt(s.value, 10));
      eq(new Set(lanes).size, 4, 'Doppelbelegung nach Zufall');
      lanes.forEach((l) => ok(l >= 1 && l <= 4, `Bahn ${l} ausserhalb 1–4`));
    }
    app.assertClean();
  });

  test('Vorschau-Tabelle bildet den Bahnwechsel ab (Reihum +1)', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-preset="schere"]');   // plus1
    await app.click('[data-bahnen="4"]');
    await app.click('[data-step="inc"][data-field="spieler"]');
    await app.click('[data-tab="spieler"]');
    const rows = app.$$('.preview tbody tr');
    eq(rows.length, 4, 'eine Zeile je Satz');
    // Satz 1: Spieler 1 auf Bahn 1, Spieler 2 auf Bahn 2; Satz 2 je +1.
    const cell = (r, c) => rows[r].children[c].textContent.trim();
    eq(cell(0, 1), '1', 'Satz 1 / Bahn 1');
    eq(cell(0, 2), '2', 'Satz 1 / Bahn 2');
    eq(cell(1, 2), '1', 'Satz 2 / Bahn 2');
    eq(cell(1, 3), '2', 'Satz 2 / Bahn 3');
    app.assertClean();
  });

  test('„Spiel starten" legt ein vollständiges Spiel an und öffnet die Erfassung', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-preset="schere"]');
    await app.click('[data-bahnen="2"]');
    await app.click('[data-step="inc"][data-field="spieler"]');   // 2 Spieler
    await app.clickText('.btn-primary', 'Weiter');                 // -> Optionen
    await app.setInput('[data-input="saetze"]', '2');
    await app.clickText('.btn-primary', 'Weiter');                 // -> Spieler
    await app.setInput('.player-name[data-player="0"]', 'Anna');
    await app.setInput('.player-name[data-player="1"]', 'Bert');
    await app.click('[data-ich="0"]');
    await app.clickText('.btn-primary', 'Spiel starten');

    await app.waitFor(() => app.route() === '/spiel-laufend', 'Erfassung wurde nicht geöffnet');
    const g = app.activeGame();
    ok(g, 'kein aktives Spiel gespeichert');
    eq(g.spiel, 'sportkegler-wk', 'Spielart');
    eq(g.status, 'setup', 'Status direkt nach dem Start');
    eq(g.schemaVersion, 1, 'schemaVersion');
    eq(g.ichIndex, 0, '„Das bin ich"-Markierung');
    const c = g.config;
    eq(c.preset, 'schere');
    eq(c.spieler, 2);
    deepEq(c.spielerListe.map((p) => p.name), ['Anna', 'Bert'], 'Spielernamen');
    eq(c.saetze, 2);
    eq(c.wuerfeProSatz, 30);
    eq(c.gesamtwuerfe, 60);
    deepEq(c.teilsaetze, [{ modus: 'volle', wuerfe: 15 }, { modus: 'kranz-abraeumen', wuerfe: 15 }]);
    deepEq(c.bahnplan, [[1, 2], [2, 1]], 'Bahnplan (2 Bahnen, Reihum)');
    app.assertClean();
  });

  test('Leere Namen werden zu „Spieler N"', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-tab="spieler"]');
    await app.clickText('.btn-primary', 'Spiel starten');
    await app.waitFor(() => app.route() === '/spiel-laufend', 'Erfassung wurde nicht geöffnet');
    eq(app.activeGame().config.spielerListe[0].name, 'Spieler 1', 'Ersatzname');
    app.assertClean();
  });

  test('Angefangenes Spiel taucht unter „Fortsetzen" auf und lässt sich löschen', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-tab="spieler"]');
    await app.clickText('.btn-primary', 'Spiel starten');
    await app.waitFor(() => app.route() === '/spiel-laufend', 'Erfassung wurde nicht geöffnet');

    await app.go('/neues-spiel');
    includes(app.page(), 'Fortsetzen', 'Fortsetzen-Abschnitt fehlt');
    eq(app.$$('[data-resume]').length, 1, 'ein fortsetzbares Spiel');

    app.confirmAnswer = false;
    await app.click('[data-resume] ~ [data-del], [data-del]');
    eq(app.games().length, 1, 'trotz „Abbrechen" gelöscht');

    app.confirmAnswer = true;
    await app.click('[data-del]');
    await app.waitFor(() => app.games().length === 0, 'Spiel wurde nicht gelöscht');
    eq(app.$$('[data-resume]').length, 0, 'Karte blieb stehen');
    app.assertClean();
  });
});
