// Wurferfassung (views/spiel-laufend.js) — der Kern der App.
// Gespielt wird bewusst mit einem KLEINEN Programm (2 Sätze × 4 Würfe), damit ein
// kompletter Spielverlauf in wenigen Klicks durchläuft.

import { suite, test, ok, eq, deepEq, includes, notIncludes } from '../harness.js';
import { makeGame, makeConfig, makeErfassung } from '../fixtures.js';

const MOBIL = { width: 420, height: 900 };

// Kleines Spiel: 2 Sätze à 4 Würfe, Teilsatz 1 Volle / Teilsatz 2 wie angegeben.
function kleinesSpiel(opts = {}) {
  return makeGame({
    preset: 'schere',
    saetze: 2,
    wuerfeProSatz: 4,
    teilsaetze: ['volle', 'volle'],
    bahnen: 2,
    spieler: ['Anna'],
    ...opts,
  });
}

async function starte(app, game, opts = {}) {
  await app.boot({
    hash: '/spiel-laufend',
    ...MOBIL,
    ...opts,
    storage: { games: [game], 'active-game': game.id, ...(opts.storage || {}) },
  });
  return game;
}

// Von der Übersicht in die Wurferfassung umschalten (▦).
// Achtung: .erf-numpad gibt es AUCH in der Übersicht (Ziffernblock des Ergebnis-Sheets).
// Eindeutiges Kennzeichen der Wurferfassung ist .erf-play-main bzw. [data-num].
async function zurErfassung(app) {
  if (!app.$('.erf-play-main')) await app.click('[data-act="satz-overview"]');
  await app.waitFor(() => !!app.$('.erf-play-main') && !!app.$('[data-num]'),
    'Wurferfassung erschien nicht');
}

const wirf = async (app, ...zahlen) => {
  for (const n of zahlen) await app.click(`[data-num="${n}"]`);
};

const chipWerte = (app) => app.$$('.erf-chip[data-chip] .ec-pins').map((e) => e.textContent.trim());
const teilsatzWerte = (app) => app.$$('.erf-chip-result .ecr-val').map((e) => e.textContent.trim());
const satzWerte = (app) => app.$$('.erf-stab[data-satz] .est-val').map((e) => e.textContent.trim());

suite('Erfassung · Würfe', () => {
  test('Erfassung öffnet mit der Spieler-Übersicht, ▦ schaltet zur Wurfeingabe', async (app) => {
    await starte(app, kleinesSpiel());
    ok(app.$('.erf-ueber'), 'Übersicht war beim Öffnen nicht sichtbar');
    ok(!app.$('.erf-play-main'), 'Wurferfassung war gleichzeitig offen');
    await app.click('[data-act="satz-overview"]');
    ok(app.$('[data-num="9"]'), 'Ziffernblock fehlt nach dem Umschalten');
    ok(app.$('.erf-kegel-grid'), 'Kegelbrett fehlt');
    // Antippbar wird die Raute erst, wenn es einen Ziel-Wurf gibt.
    eq(app.$$('[data-pin]').length, 0, 'Raute war ohne Wurf schon antippbar');
    await app.click('[data-num="5"]');
    eq(app.$$('[data-pin]').length, 9, 'neun Kegel im Brett');
    app.assertClean();
  });

  test('Würfe landen als Chips, Teilsatz- und Satzsumme stimmen', async (app) => {
    const g = await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 9, 7);          // Teilsatz 1
    deepEq(chipWerte(app), ['9', '7'], 'Chips nach zwei Würfen');
    deepEq(teilsatzWerte(app), ['16', '0'], 'Teilsatz-Summen');
    await wirf(app, 5, 3);          // Teilsatz 2 -> Satz voll
    deepEq(teilsatzWerte(app), ['16', '8'], 'Teilsatz-Summen nach vier Würfen');
    eq(satzWerte(app)[0], '24', 'Satz-1-Summe im Tab');
    const blk = app.game(g.id).erfassung.bloecke[0][0];
    deepEq(blk.wuerfe, [9, 7, 5, 3], 'gespeicherte Würfe');
    ok(blk.done, 'voller Satz wurde nicht automatisch beendet');
    app.assertClean();
  });

  test('Der Ziffernblock sperrt, sobald der Satz voll ist', async (app) => {
    await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 9, 9, 9, 9);
    ok(app.$('[data-num="5"]').disabled, 'Ziffernblock blieb nach vollem Satz offen');
    app.assertClean();
  });

  test('↩ nimmt den letzten Wurf zurück und öffnet den automatisch beendeten Satz wieder', async (app) => {
    const g = await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 9, 8, 7, 6);
    ok(app.game(g.id).erfassung.bloecke[0][0].done, 'Satz nicht automatisch fertig');
    await app.click('[data-act="undo"]');
    const blk = app.game(g.id).erfassung.bloecke[0][0];
    deepEq(blk.wuerfe, [9, 8, 7], 'Wurf nicht zurückgenommen');
    ok(!blk.done, 'Satz blieb nach ↩ fertig');
    app.assertClean();
  });

  test('↩ ist ohne Würfe ausgegraut', async (app) => {
    await starte(app, kleinesSpiel());
    await zurErfassung(app);
    ok(app.$('[data-act="undo"]').disabled, '↩ war ohne Würfe bedienbar');
    app.assertClean();
  });

  test('Chip antippen → Wurf korrigieren und löschen', async (app) => {
    const g = await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 9, 4);
    await app.click('.erf-chip[data-chip="0"]');
    ok(app.$('.erf-chip[data-chip="0"]').classList.contains('is-edit'), 'Korrekturmodus nicht aktiv');
    await app.click('[data-num="6"]');
    deepEq(app.game(g.id).erfassung.bloecke[0][0].wuerfe, [6, 4], 'Korrektur wirkte nicht');

    await app.click('.erf-chip[data-chip="1"]');
    await app.click('[data-act="delete"]');
    deepEq(app.game(g.id).erfassung.bloecke[0][0].wuerfe, [6], 'Löschen wirkte nicht');
    app.assertClean();
  });

  test('Korrektur lässt sich abbrechen', async (app) => {
    const g = await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 9);
    await app.click('.erf-chip[data-chip="0"]');
    await app.click('[data-act="cancel-edit"]');
    ok(!app.$('.erf-chip[data-chip="0"]').classList.contains('is-edit'), 'Korrekturmodus blieb aktiv');
    await app.click('[data-num="3"]');
    deepEq(app.game(g.id).erfassung.bloecke[0][0].wuerfe, [9, 3], 'Wurf nach Abbruch nicht angehängt');
    app.assertClean();
  });

  test('Kegelbild: „stehend"-Modus schaltet den getippten Kegel aus', async (app) => {
    const g = await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 8);   // 8 gefallen -> genau 1 Kegel steht
    await app.click('[data-pin="5"]');
    const blk = app.game(g.id).erfassung.bloecke[0][0];
    deepEq(blk.kegel[0], [1, 2, 3, 4, 6, 7, 8, 9], 'König sollte stehen bleiben');
    // Kranz-Abzeichen am Chip (8 gefallen, nur die 5 steht).
    ok(app.$('.erf-chip[data-chip="0"]').classList.contains('is-koenig'), 'Kranz nicht erkannt');
    app.assertClean();
  });

  test('Kegelbild: „gefallen"-Modus sammelt genau die gefallenen Kegel', async (app) => {
    const g = await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 2);
    await app.click('[data-pinmode="gefallen"]');
    await app.click('[data-pin="1"]');
    await app.click('[data-pin="9"]');
    deepEq(app.game(g.id).erfassung.bloecke[0][0].kegel[0], [1, 9], 'gefallene Kegel');
    app.assertClean();
  });

  test('Neuner setzt alle neun Kegel automatisch und bekommt sein Abzeichen', async (app) => {
    const g = await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 9);
    deepEq(app.game(g.id).erfassung.bloecke[0][0].kegel[0], [1, 2, 3, 4, 5, 6, 7, 8, 9], 'Neuner-Bild');
    ok(app.$('.erf-chip[data-chip="0"]').classList.contains('is-neuner'), 'Neuner-Abzeichen fehlt');
    app.assertClean();
  });

  test('Fehlwurf (0) setzt ein leeres Bild', async (app) => {
    const g = await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 0);
    deepEq(app.game(g.id).erfassung.bloecke[0][0].kegel[0], [], 'Fehlwurf-Bild');
    app.assertClean();
  });
});

suite('Erfassung · Abräumen', () => {
  const abraeumSpiel = () => makeGame({
    preset: 'classic', saetze: 1, wuerfeProSatz: 4,
    teilsaetze: ['abraeumen'], bahnen: 1, spieler: ['Anna'],
  });

  test('Beim Abräumen sind höhere Zahlen als stehende Kegel gesperrt', async (app) => {
    await starte(app, abraeumSpiel());
    await zurErfassung(app);
    await wirf(app, 6);      // 3 Kegel stehen noch
    ok(app.$('[data-num="4"]').disabled, '4 war trotz nur 3 stehender Kegel erlaubt');
    ok(!app.$('[data-num="3"]').disabled, '3 war fälschlich gesperrt');
    app.assertClean();
  });

  test('Abgeräumter Lauf stellt das volle Bild wieder her', async (app) => {
    await starte(app, abraeumSpiel());
    await zurErfassung(app);
    await wirf(app, 6, 3);   // Lauf abgeräumt -> zurück auf 9
    ok(!app.$('[data-num="9"]').disabled, 'nach dem Abräumen stand nicht wieder alles');
    app.assertClean();
  });

  test('Kranz-Abräumen: Langdruck-Taste ist markiert', async (app) => {
    await starte(app, makeGame({
      preset: 'schere', saetze: 1, wuerfeProSatz: 4,
      teilsaetze: ['kranz-abraeumen'], bahnen: 1, spieler: ['Anna'],
    }));
    await zurErfassung(app);
    ok(app.$('[data-num="8"][data-koenig="1"]'), 'Kranz-Langdruck nicht auf der 8');
    app.assertClean();
  });

  test('Unplausibler Lauf wird am Chip als Fehler markiert', async (app) => {
    // Zwei Würfe, die zusammen mehr Kegel fällen als standen (6 + 5 aus dem vollen Bild).
    const g = abraeumSpiel();
    const c = g.config;
    g.erfassung = makeErfassung(c, [[[6, 5]]], { done: [[false]] });
    await starte(app, g);
    await zurErfassung(app);
    ok(app.$('.erf-chip[data-chip="1"].is-error'), 'unmöglicher Wurf nicht markiert');
    includes(app.txt('.erf-chip-err'), 'Wurf 2', 'Fehlerhinweis fehlt');
    app.assertClean();
  });
});

suite('Erfassung · Sätze, Bahnen, Spielende', () => {
  test('Satz beenden gibt die Bahn frei und der Bahnwechsel greift', async (app) => {
    const g = kleinesSpiel({ spieler: ['Anna', 'Bert'], bahnen: 2 });
    deepEq(g.config.bahnplan, [[1, 2], [2, 1]], 'Testvoraussetzung: Bahnplan');
    await starte(app, g);
    await zurErfassung(app);
    includes(app.txt('.ek-bahn'), 'Bahn 1', 'Spieler 1 startet nicht auf Bahn 1');
    await wirf(app, 5, 5, 5, 5);          // Satz 1 voll -> fertig
    // Bert hat Satz 1 noch nicht beendet -> Anna wartet auf Bahn 1.
    await app.click('[data-satz="1"]');
    await zurErfassung(app);
    includes(app.txt('.ek-bahn'), 'Bahn 2', 'Bahnplan-Bahn für Satz 2 falsch');
    app.assertClean();
  });

  test('In einen späteren Satz kann man nicht vorgreifen', async (app) => {
    const g = kleinesSpiel();
    await starte(app, g);
    await zurErfassung(app);
    await app.click('[data-satz="1"]');
    await zurErfassung(app);
    await wirf(app, 9);
    const bloecke = app.game(g.id).erfassung.bloecke[0];
    eq(bloecke[1].wuerfe.length, 0, 'Wurf landete im zweiten Satz, obwohl der erste offen ist');
    includes(app.txt('#erf-toast'), 'Satz 1', 'Hinweis fehlt');
    app.assertClean();
  });

  test('Kompletter Spielverlauf endet in der Statistik und im Status „beendet"', async (app) => {
    const g = kleinesSpiel();
    await starte(app, g);
    await zurErfassung(app);
    await wirf(app, 9, 9, 9, 9);
    await app.click('[data-satz="1"]');
    await zurErfassung(app);
    await wirf(app, 8, 8, 8, 8);
    // Der letzte Wurf wartet noch auf sein Kegelbild -> Statistik kommt erst danach.
    await app.click('[data-pin="5"]');
    await app.waitFor(() => !!app.$('.erf-stats, [data-act="stats-close"]'), 'Statistik-Screen blieb aus');
    await app.waitFor(() => app.game(g.id).status === 'beendet', 'Status wurde nicht „beendet"');
    includes(app.page(), '68', 'Gesamtholz (36 + 32) fehlt in der Statistik');
    app.assertClean();
  });

  test('Beendetes Spiel öffnet beim erneuten Aufruf direkt die Statistik', async (app) => {
    const g = kleinesSpiel();
    g.status = 'beendet';
    g.erfassung = makeErfassung(g.config, [[[9, 9, 9, 9], [8, 8, 8, 8]]]);
    await starte(app, g);
    ok(app.$('[data-act="stats-close"]'), 'Statistik nicht automatisch offen');
    await app.click('[data-act="stats-close"]');
    ok(!app.$('[data-act="stats-close"]'), 'Statistik ließ sich nicht schließen');
    app.assertClean();
  });

  test('Spielstand überlebt einen Reload', async (app) => {
    const g = kleinesSpiel();
    await starte(app, g);
    await zurErfassung(app);
    await wirf(app, 7, 6);
    await app.reload();
    await zurErfassung(app);
    deepEq(chipWerte(app), ['7', '6'], 'Würfe nach dem Reload verloren');
    app.assertClean();
  });

  test('Spielerwechsel über die Übersicht', async (app) => {
    const g = kleinesSpiel({ spieler: ['Anna', 'Bert'], bahnen: 2 });
    await starte(app, g);
    await zurErfassung(app);
    includes(app.txt('.ek-name'), 'Anna', 'startet nicht bei Anna');
    await app.click('[data-player="1"]');
    await zurErfassung(app);
    includes(app.txt('.ek-name'), 'Bert', 'Spielerwechsel wirkte nicht');
    app.assertClean();
  });

  test('„Kein Spiel" statt Absturz, wenn der aktive Zeiger ins Leere geht', async (app) => {
    await app.boot({ hash: '/spiel-laufend', ...MOBIL, storage: { games: [], 'active-game': 'gibt-es-nicht' } });
    includes(app.page(), 'Kein aktives Spiel', 'Leerzustand fehlt');
    app.assertClean();
  });
});

suite('Erfassung · Einstellungen', () => {
  test('Einstellungsmenü öffnet und schließt', async (app) => {
    await starte(app, kleinesSpiel());
    await app.click('[data-act="settings"]');
    ok(app.$('[data-act="settings-close"]'), 'Einstellungen öffneten nicht');
    await app.click('.erf-settings-backdrop, [data-act="settings-close"]');
    ok(!app.$('[data-act="toggle-vorschlaege"]'), 'Einstellungen schlossen nicht');
    app.assertClean();
  });

  test('Vorschläge lassen sich abschalten und werden global gespeichert', async (app) => {
    await starte(app, kleinesSpiel());
    await app.click('[data-act="settings"]');
    await app.click('[data-act="toggle-vorschlaege"]');
    eq(app.store('settings').vorschlaege, false, 'Einstellung nicht gespeichert');
    await app.click('[data-act="toggle-vorschlaege"]');
    eq(app.store('settings').vorschlaege, true, 'Einstellung nicht zurückgeschaltet');
    app.assertClean();
  });

  test('Standard-Kegelbilder sind vorbelegt und im Editor bearbeitbar', async (app) => {
    await starte(app, kleinesSpiel());
    const sb = app.store('standardbilder');
    ok(sb && Object.keys(sb).length > 0, 'Werksvoreinstellung wurde nicht geseedet');
    await app.click('[data-act="settings"]');
    ok(app.$('[data-sbnum="1"]'), 'Standardbilder-Editor fehlt');
    await app.click('[data-sbnum="3"]');
    await app.click('[data-sbpin="1"]');
    await app.click('[data-sbpin="2"]');
    await app.click('[data-sbpin="3"]');
    const frei = app.$('[data-sbplace]');
    ok(frei, 'kein freies Feld zum Ablegen');
    await app.click('[data-sbplace]');
    const nach = app.store('standardbilder')['3'] || [];
    ok(nach.some((e) => JSON.stringify(e.pins || e) === '[1,2,3]'), 'neues Bild nicht gespeichert');
    app.assertClean();
  });

  test('Schnellauswahl-Pop-up erscheint nach einer Zahl mit hinterlegten Bildern', async (app) => {
    await starte(app, kleinesSpiel());
    await zurErfassung(app);
    await wirf(app, 1);
    ok(app.$('[data-pick]'), 'Pop-up erschien nicht');
    await app.click('[data-pick="0"]');
    ok(!app.$('[data-pick]'), 'Pop-up schloss nicht');
    app.assertClean();
  });

  test('Bahneinstellung: Satz beenden / wieder öffnen', async (app) => {
    const g = kleinesSpiel();
    await starte(app, g);
    await zurErfassung(app);
    await wirf(app, 5);
    await app.click('[data-act="lane-settings"]');
    await app.click('[data-act="end-satz"]');
    ok(app.game(g.id).erfassung.bloecke[0][0].done, 'Satz wurde nicht beendet');
    await app.click('[data-act="lane-settings"]');
    await app.click('[data-act="end-satz"]');
    ok(!app.game(g.id).erfassung.bloecke[0][0].done, 'Satz wurde nicht wieder geöffnet');
    app.assertClean();
  });

  test('Bahneinstellung: Spiel beenden setzt alle Sätze fertig', async (app) => {
    const g = kleinesSpiel();
    await starte(app, g);
    await zurErfassung(app);
    await app.click('[data-act="lane-settings"]');
    await app.click('[data-act="end-game"]');
    const bloecke = app.game(g.id).erfassung.bloecke[0];
    ok(bloecke.every((b) => b.done), 'nicht alle Sätze fertig');
    await app.waitFor(() => app.game(g.id).status === 'beendet', 'Status nicht „beendet"');
    app.assertClean();
  });
});
