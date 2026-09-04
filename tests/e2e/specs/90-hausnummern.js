// Spiel „Hausnummern" — Setup und Erfassung durch die echte Oberflaeche geklickt.
//
// Geprueft wird vor allem das, was dieses Spiel von allen anderen unterscheidet: WO ein Wurf
// landet (vier Platzierungs-Varianten), wie ein Fehlwurf zaehlt (hoch 0 / niedrig 9) und dass
// beim Niedrig-Spiel die KLEINSTE Summe gewinnt.

import { suite, test, ok, eq, deepEq, includes } from '../harness.js';

const SETUP = '/setup/hausnummern';

// Setup durchklicken und das Spiel starten. `opts` deckt die Regeln ab, `namen` die Spieler.
async function starte(app, { variante = 'hoch', platzierung = 'vorn', stellen = null,
  nullRegel = null, durchgaenge = 1, namen = ['A', 'B'] } = {}) {
  await app.boot({ hash: SETUP });
  if (variante !== 'hoch') await app.click(`[data-variante="${variante}"]`);
  if (nullRegel) await app.click(`[data-nullregel="${nullRegel}"]`);
  if (platzierung !== 'vorn') await app.setSelect('[data-field="platzierung"]', platzierung);
  if (stellen) await app.click(`[data-stellen="${stellen}"]`);
  for (let i = 1; i < durchgaenge; i += 1) await app.click('[data-step="inc"][data-field="durchgaenge"]');
  await app.click('[data-tab="spieler"]');
  await app.setInput('[data-input="spieler"]', String(namen.length));
  for (let i = 0; i < namen.length; i += 1) await app.setInput(`.player-name[data-player="${i}"]`, namen[i]);
  await app.click('.btn-primary');
  await app.waitFor(() => app.route() === '/hausnummern', 'Erfassung nicht erreicht');
  return app;
}

// Die aktuell sichtbaren Ziffern des Kaestchen-Streifens.
const ziffern = (app) => app.$$('.hn-digit').map((e) => e.textContent.trim()).join('');
// Der Livestand über der Erfassung: die Summen-Spalte (nur bei mehreren Durchgängen) …
const staende = (app) => app.$$('.hn-live-table tbody .hn-live-summe').map((e) => e.textContent.trim());
// … und die Hausnummern-Zellen (Spieler für Spieler, je Durchgang).
const zellen = (app) => app.$$('.hn-live-cell').map((e) => e.textContent.trim());

// Einen Wurf erfassen — bei den Ansage-Varianten mit der Stelle, sonst ohne.
async function wurf(app, zahl, stelle = null) {
  if (stelle != null && app.$(`.hn-cell[data-stelle="${stelle}"].is-wahl`) === null
    && app.$('[data-num="0"]').disabled) {
    // 'ansage-vor': erst die Stelle, dann die Zahl.
    await app.click(`[data-stelle="${stelle}"]`);
    await app.click(`[data-num="${zahl}"]`);
    return;
  }
  await app.click(`[data-num="${zahl}"]`);
  if (stelle != null) await app.click(`[data-stelle="${stelle}"]`);
}

suite('Hausnummern', () => {
  test('„Neues Spiel" bietet Hausnummern an und führt ins Setup', async (app) => {
    await app.boot({ hash: '/neues-spiel' });
    includes(app.page(), 'Hausnummern', 'Kachel fehlt');
    await app.click('a[href="#/setup/hausnummern"]');
    eq(app.route(), SETUP, 'Setup nicht erreicht');
    app.assertClean();
  });

  test('Setup: Voreinstellung hoch · 4 Stellen · beste 9999', async (app) => {
    await app.boot({ hash: SETUP });
    includes(app.$('.seg-btn.is-active').textContent, 'Hohe Hausnummer', 'Variante');
    eq(app.$('[data-stellen].is-active').textContent.trim(), '4', 'Stellen');
    eq(app.$('[data-field="platzierung"]').value, 'vorn', 'Platzierung');
    eq(app.$('[data-input="durchgaenge"]').value, '1', 'Durchgänge');
    includes(app.txt('.field-readout'), '9999', 'beste Hausnummer');
    ok(!app.$('[data-nullregel]'), 'Null-Regel gehört nur zum Niedrig-Spiel');
    app.assertClean();
  });

  test('Setup: Niedrig zeigt die Null-Regel — 1111 bzw. 0000', async (app) => {
    await app.boot({ hash: SETUP });
    await app.click('[data-variante="niedrig"]');
    ok(app.$('[data-nullregel="neun"].is-active'), '„0 Holz zählt 9" ist die Voreinstellung');
    includes(app.txt('.field-readout'), '1111', 'beste Hausnummer bei 0=9');
    await app.click('[data-nullregel="null"]');
    includes(app.txt('.field-readout'), '0000', 'beste Hausnummer bei 0=0');
    // Mehr Stellen -> laengere Zahl.
    await app.click('[data-stellen="6"]');
    includes(app.txt('.field-readout'), '000000', 'sechsstellig');
    app.assertClean();
  });

  test('Spielstart legt die Regeln im Spiel ab', async (app) => {
    await starte(app, { variante: 'niedrig', platzierung: 'hinten', stellen: 5, durchgaenge: 3, namen: ['Anna', 'Bo'] });
    const g = app.activeGame();
    eq(g.spiel, 'hausnummern', 'Spielart');
    eq(g.config.variante, 'niedrig', 'Variante');
    eq(g.config.platzierung, 'hinten', 'Platzierung');
    eq(g.config.stellen, 5, 'Stellen');
    eq(g.config.saetze, 3, 'Durchgänge');
    eq(g.config.wuerfeProSatz, 5, 'Würfe je Durchgang folgen den Stellen');
    deepEq(g.config.spielerListe.map((p) => p.name), ['Anna', 'Bo'], 'Spieler');
    app.assertClean();
  });

  test('Von vorn nach hinten: Wurf 1 steht links, danach wechselt der Spieler', async (app) => {
    await starte(app, { namen: ['A', 'B'] });
    eq(ziffern(app), '––––', 'leerer Streifen');
    await wurf(app, 9);
    await wurf(app, 4);
    eq(ziffern(app), '94––', 'Würfe laufen von links nach rechts');
    await wurf(app, 0);
    await wurf(app, 7);
    // Durchgang voll -> reihum weiter zum zweiten Spieler.
    eq(app.activeGame().erfassung.aktiverSpieler, 1, 'kein Spielerwechsel');
    deepEq(zellen(app), ['9407', '–'], 'Livestand');
    app.assertClean();
  });

  test('Oben steht immer, ob hoch oder niedrig gespielt wird', async (app) => {
    // Mehrere Durchgänge: dort stand in der Kopfzeile bisher nur „Durchgang 1/2".
    await starte(app, { durchgaenge: 2, namen: ['A', 'B'] });
    includes(app.txt('.page-title'), 'Hohe Hausnummer', 'Variante fehlt im Titel');
    for (const n of [1, 2, 3, 4]) await wurf(app, n);
    includes(app.txt('.page-title'), 'Hohe Hausnummer', 'Variante verschwindet beim Spielen');

    await starte(app, { variante: 'niedrig', durchgaenge: 2, namen: ['A'] });
    includes(app.txt('.page-title'), 'Niedrige Hausnummer', 'Variante fehlt im Titel');
    app.assertClean();
  });

  test('Der Livestand steht über der Erfassung und springt zum angetippten Durchgang', async (app) => {
    await starte(app, { durchgaenge: 2, namen: ['Anna', 'Bo'] });
    // Er wächst mit: der angefangene Durchgang steht schon in der Tabelle.
    await wurf(app, 5);
    deepEq(zellen(app), ['5–––', '–', '–', '–'], 'Teilstand im Livestand');
    includes(app.txt('.hn-live'), 'Anna', 'Spieler fehlen im Livestand');
    deepEq(staende(app), ['–', '–'], 'angefangener Durchgang zählt noch nicht');
    for (const n of [5, 5, 5]) await wurf(app, n);
    deepEq(staende(app), ['5555', '–'], 'fertiger Durchgang zählt');
    includes(app.txt('.hn-live'), '🥇', 'Führender ist nicht markiert');
    // Eine Zelle antippen wechselt Spieler UND Durchgang.
    await app.click('[data-zug="0-1"]');
    const e = app.activeGame().erfassung;
    eq(e.aktiverSpieler, 0, 'Spieler'); eq(e.aktiverSatz, 1, 'Durchgang');
    includes(app.txt('.hn-head'), 'Durchgang 2/2', 'Kopfzeile folgt der Auswahl');
    app.assertClean();
  });

  test('Von hinten nach vorn: derselbe Wurf landet rechts', async (app) => {
    await starte(app, { platzierung: 'hinten', namen: ['A'] });
    await wurf(app, 9);
    eq(ziffern(app), '–––9', 'Wurf 1 ganz rechts');
    await wurf(app, 4);
    eq(ziffern(app), '––49', 'Wurf 2 daneben');
    app.assertClean();
  });

  test('Stelle vorher ansagen: ohne Ansage keine Zahl', async (app) => {
    await starte(app, { platzierung: 'ansage-vor', namen: ['A'] });
    ok(app.$('[data-num="5"]').disabled, 'Zahlen sind vor der Ansage gesperrt');
    await app.click('[data-stelle="3"]');
    ok(!app.$('[data-num="5"]').disabled, 'nach der Ansage sind die Zahlen frei');
    includes(app.txt('.hn-hint'), 'Angesagt', 'Hinweis zur Ansage');
    await app.click('[data-num="5"]');
    eq(ziffern(app), '–––5', 'Wurf landet auf der angesagten Stelle');
    ok(app.$('[data-num="5"]').disabled, 'für den nächsten Wurf wieder gesperrt');
    app.assertClean();
  });

  test('Stelle nachher wählen: die geworfene Zahl wartet auf ihren Platz', async (app) => {
    await starte(app, { platzierung: 'wahl-nach', namen: ['A'] });
    await app.click('[data-num="6"]');
    includes(app.txt('.hn-hint'), 'jetzt die Stelle wählen', 'Hinweis');
    ok(app.$('[data-num="6"]').disabled, 'Zahlen gesperrt, bis platziert wurde');
    eq(app.$$('.hn-cell.is-wahl').length, 4, 'alle freien Stellen stehen zur Wahl');
    await app.click('[data-stelle="1"]');
    eq(ziffern(app), '–6––', 'Zahl liegt auf der gewählten Stelle');
    ok(!app.$('[data-num="6"]').disabled, 'danach wieder frei');
    app.assertClean();
  });

  test('Fehlwurf zählt beim Hoch-Spiel 0', async (app) => {
    await starte(app, { namen: ['A'] });
    await app.click('[data-act="fehl"]');
    eq(ziffern(app), '0–––', 'Fehlwurf = 0');
    ok(app.activeGame().erfassung.bloecke[0][0].ungueltig[0], 'als ungültig gemerkt');
    app.assertClean();
  });

  test('Standard beim Niedrig-Spiel: Durchläufer UND ungültiger Wurf zählen neun', async (app) => {
    await starte(app, { variante: 'niedrig', namen: ['A'] });
    await app.click('[data-act="fehl"]');
    await app.click('[data-num="0"]');
    await app.click('[data-num="1"]');
    eq(ziffern(app), '991–', 'Fehlwurf und 0 Holz sind beide die 9');
    app.assertClean();
  });

  test('Sonderregel: der Durchläufer zählt 0, der ungültige Wurf weiter 9', async (app) => {
    await starte(app, { variante: 'niedrig', nullRegel: 'null', namen: ['A'] });
    await app.click('[data-num="0"]');
    await app.click('[data-act="fehl"]');
    eq(ziffern(app), '09––', 'nur die durchgelaufene Kugel ist die 0');
    // Die Taste sagt selbst, was sie zählt — sonst wären beide Nullen nicht zu unterscheiden.
    includes(app.$('[data-act="fehl"]').textContent, 'zählt 9', 'Fehlwurf-Taste ohne Zusatz');
    ok(!app.$('[data-num="0"] .hn-num-note'), '0 zählt hier 0 und braucht keinen Zusatz');
    app.assertClean();
  });

  test('Ohne Sonderregel trägt die 0-Taste ihren Wert offen', async (app) => {
    await starte(app, { variante: 'niedrig', namen: ['A'] });
    includes(app.$('[data-num="0"]').textContent, 'zählt 9', 'Zusatz auf der 0 fehlt');
    includes(app.txt('.hn-head'), 'Durchläufer zählt 9', 'Regel in der Kopfzeile');
    app.assertClean();
  });

  test('Rückgängig nimmt den letzten Wurf zurück — auch über den Spielerwechsel hinweg', async (app) => {
    await starte(app, { namen: ['A', 'B'] });
    for (const n of [1, 2, 3, 4]) await wurf(app, n);
    eq(app.activeGame().erfassung.aktiverSpieler, 1, 'Spieler B ist dran');
    await app.click('[data-act="undo"]');
    eq(app.activeGame().erfassung.aktiverSpieler, 0, 'Rückgängig springt zu A zurück');
    eq(ziffern(app), '123–', 'letzter Wurf ist weg');
    app.assertClean();
  });

  test('Ein belegtes Kästchen antippen korrigiert den Wurf', async (app) => {
    await starte(app, { namen: ['A'] });
    for (const n of [1, 2, 3]) await wurf(app, n);
    await app.click('[data-stelle="1"]');
    ok(app.$('.hn-cell.is-edit'), 'Korrektur-Markierung');
    includes(app.txt('.hn-hint'), 'Korrektur', 'Hinweis');
    await app.click('[data-num="9"]');
    eq(ziffern(app), '193–', 'Wert getauscht, Stelle geblieben');
    // Löschen entfernt den Wurf ganz.
    await app.click('[data-stelle="0"]');
    await app.click('[data-act="delete"]');
    eq(app.activeGame().erfassung.bloecke[0][0].wuerfe.length, 2, 'Wurf nicht gelöscht');
    app.assertClean();
  });

  test('Mehrere Durchgänge: erst alle Spieler, dann der nächste Durchgang', async (app) => {
    await starte(app, { durchgaenge: 2, namen: ['A', 'B'] });
    for (const n of [1, 1, 1, 1]) await wurf(app, n);
    let e = app.activeGame().erfassung;
    eq(e.aktiverSpieler, 1, 'B ist dran'); eq(e.aktiverSatz, 0, 'noch Durchgang 1');
    for (const n of [2, 2, 2, 2]) await wurf(app, n);
    e = app.activeGame().erfassung;
    eq(e.aktiverSpieler, 0, 'zurück zu A'); eq(e.aktiverSatz, 1, 'jetzt Durchgang 2');
    app.assertClean();
  });

  test('Spielende: Ergebnis mit Rangliste, beim Niedrig-Spiel gewinnt die kleinste Summe', async (app) => {
    await starte(app, { variante: 'niedrig', namen: ['Anna', 'Bo'] });
    for (const n of [5, 5, 5, 5]) await wurf(app, n);   // Anna 5555
    for (const n of [1, 2, 3, 4]) await wurf(app, n);   // Bo    1234
    eq(app.activeGame().status, 'beendet', 'Spiel nicht beendet');
    await app.waitFor(() => app.$('.hn-sieger'), 'Ergebnis-Bildschirm fehlt');
    includes(app.txt('.hn-sieger'), 'Bo', 'kleinste Summe gewinnt');
    includes(app.txt('.hn-table'), '5555', 'Hausnummer in der Tabelle');
    includes(app.txt('.hn-table'), '1234', 'Hausnummer in der Tabelle');
    app.assertClean();
  });

  test('Der Stand übersteht einen Neustart der App', async (app) => {
    await starte(app, { durchgaenge: 2, namen: ['A', 'B'] });
    for (const n of [7, 7, 7, 7]) await wurf(app, n);
    await app.reload();
    eq(app.route(), '/hausnummern', 'Route nach Neustart');
    deepEq(staende(app), ['7777', '–'], 'Stand nach Neustart');
    app.assertClean();
  });

  test('Ein laufendes Spiel lässt sich über „Fortsetzen" wieder aufnehmen', async (app) => {
    await starte(app, { namen: ['A', 'B'] });
    await wurf(app, 8);
    const id = app.activeGame().id;
    await app.go('/neues-spiel');
    const karte = app.need('.resume-card');
    includes(karte.textContent, 'Hausnummern', 'Spielart auf der Karte');
    await app.click(`[data-resume="${id}"]`);
    eq(app.route(), '/hausnummern', 'Fortsetzen führt in die falsche Erfassung');
    eq(ziffern(app), '8–––', 'Stand nicht wiederhergestellt');
    app.assertClean();
  });

  test('Ein beendetes Spiel steht in der Historie und lässt sich wieder aufrufen', async (app) => {
    await starte(app, { namen: ['Anna', 'Bo'] });
    for (const n of [9, 9, 9, 9]) await wurf(app, n);
    for (const n of [1, 1, 1, 1]) await wurf(app, n);
    const id = app.activeGame().id;
    await app.go('/statistiken');
    const karte = await app.waitFor(() => app.$('.stat-card[data-art="hausnummern"]'), 'Karte fehlt');
    includes(karte.textContent, 'Anna', 'Spieler auf der Karte');
    includes(karte.textContent, '9999', 'Summe auf der Karte');
    karte.click();
    await app.settle();
    await app.waitFor(() => app.route() === '/hausnummern', 'Spiel nicht wieder geöffnet');
    eq(app.store('active-game'), id, 'falsches Spiel geöffnet');
    app.assertClean();
  });
});
