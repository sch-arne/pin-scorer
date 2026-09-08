// Ergebnis-Grafik (🖼 im Kopf): Menü öffnen, Optionen schalten, PNG speichern, schließen.
//
// Das Panel hängt bewusst an document.body statt im View-Root — sonst würde die Canvas bei
// jedem Wurf mit `root.innerHTML = …` zerstört. Der Preis: es überlebt eine Navigation, wenn
// der UNMOUNT-Listener fehlt. Genau das prüft der letzte Test hier.

import { suite, test, ok, eq, includes } from '../harness.js';
import { buildWettkampf } from '../../../js/logic/wettkampf-build.js';
import { makeGame, makeErfassung } from '../fixtures.js';

const MOBIL = { width: 420, height: 900 };
const DESKTOP = { width: 1280, height: 900 };

// 2 Mannschaften à 4 Spieler auf 4 Bahnen, Schere, 2 Sätze à 4 Würfe -> 2 Durchgänge.
function baueWettkampf() {
  return buildWettkampf({
    name: 'E2E-Cup',
    datum: '2026-09-02',
    preset: 'schere',
    saetze: 2,
    wuerfeProSatz: 4,
    teilsaetze: ['volle', 'kranz-abraeumen'],
    bahnwechsel: 'plus1',
    anlageId: 'a1',
    anlageName: 'Testhalle',
    anlageBahnen: [1, 2, 3, 4].map((n) => ({ id: 'b' + n, nummer: n, bahnart: 'schere' })),
    playedLanes: [1, 2, 3, 4],
    mannschaften: [
      { id: 'm1', name: 'Heim', lanes: [1, 2] },
      { id: 'm2', name: 'Gast', lanes: [3, 4] },
    ],
    spielerJeMannschaft: 4,
    wertung: {
      modus: 'duell', gesamtholzPunkte: 2, kriterium2: 'ewp', kriterium2Punkte: 2, ewpSchwelle: 18,
    },
  });
}

// Alle Durchgänge füllen (Heim stark, Gast schwach) -> Wettkampf gilt als beendet.
function fuelleErgebnisse(games) {
  games.forEach((g) => {
    const c = g.config;
    const wuerfe = c.spielerListe.map((sp) => {
      const w = sp.mannschaftId === 'm1' ? 8 : 4;
      return Array.from({ length: c.saetze }, () => Array.from({ length: c.wuerfeProSatz }, () => w));
    });
    g.erfassung = makeErfassung(c, wuerfe);
    g.status = 'beendet';
  });
  return games;
}

async function starteHub(app, { wettkampf, games }, layout = MOBIL) {
  await app.boot({
    hash: '/wettkampf',
    ...layout,
    storage: { wettkaempfe: [wettkampf], games, 'active-wettkampf': wettkampf.id },
  });
}

async function oeffneGrafik(app) {
  await app.click('[data-act="grafik"]');
  ok(app.$('.gfx-backdrop'), 'Grafik-Menü hat sich nicht geöffnet');
}

// Das Bild entsteht asynchron (canvas.toBlob) — erst danach sind die Knöpfe frei.
async function warteAufDatei(app) {
  await app.waitFor(() => !app.$('[data-gfx="download"]').disabled, 'PNG wurde nicht erzeugt');
}

suite('Ergebnis-Grafik', () => {
  test('Hub: Menü öffnet außerhalb der View, Canvas im Hochformat', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    await oeffneGrafik(app);
    const backdrop = app.$('.gfx-backdrop');
    // Muss am body hängen, nicht in #app — sonst überlebt die Canvas kein Neu-Rendern.
    eq(backdrop.parentElement, app.doc.body, 'Panel hängt nicht am body');
    ok(!app.$('#app .gfx-backdrop'), 'Panel liegt fälschlich im View-Root');
    const canvas = app.need('.gfx-canvas');
    eq(canvas.width, 1080, 'Canvas-Breite');
    eq(canvas.height, 1440, 'Canvas-Höhe (Hochformat)');
    includes(app.txt('.gfx-meta'), 'Transparenz', 'Hinweis auf den transparenten Hintergrund');
    app.assertClean();
  });

  test('EWP-Schalter ist vor Spielende gesperrt und danach frei', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    await oeffneGrafik(app);
    const ewp = app.need('.erf-switch[data-gfx="ewp"]');
    eq(ewp.disabled, true, 'EWP ist im laufenden Wettkampf schaltbar');
    eq(ewp.classList.contains('is-on'), false, 'EWP ist im laufenden Wettkampf an');
    includes(app.txt('[data-hint="ewp"]'), 'Spielende', 'Hinweis zur Sperre fehlt');

    const fertig = baueWettkampf();
    fuelleErgebnisse(fertig.games);
    await starteHub(app, fertig);
    await oeffneGrafik(app);
    const ewp2 = app.need('.erf-switch[data-gfx="ewp"]');
    eq(ewp2.disabled, false, 'EWP bleibt nach Spielende gesperrt');
    eq(ewp2.classList.contains('is-on'), true, 'EWP ist nach Spielende nicht an');
    app.assertClean();
  });

  test('Formatwechsel stellt die Canvas auf Story um und zurück', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    await oeffneGrafik(app);
    await app.click('[data-gfx="format"][data-wert="story"]');
    eq(app.need('.gfx-canvas').height, 1920, 'Story-Höhe');
    includes(app.txt('.gfx-meta'), '1080 × 1920', 'Maßangabe');
    await app.click('[data-gfx="format"][data-wert="hoch"]');
    eq(app.need('.gfx-canvas').height, 1440, 'zurück ins Hochformat');
    // Die Auswahl wird in den App-Einstellungen gemerkt.
    eq((app.store('settings') || {}).grafik.format, 'hoch', 'Format nicht gespeichert');
    app.assertClean();
  });

  test('Schriftwahl und Umrandung wirken und werden gemerkt', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    await oeffneGrafik(app);
    const kontur = app.need('.erf-switch[data-gfx="kontur"]');
    eq(kontur.disabled, false, 'Umrandung ist nicht schaltbar');
    eq(kontur.classList.contains('is-on'), true, 'Umrandung ist nicht voreingestellt');

    await app.click('[data-gfx="schrift"][data-wert="schmal"]');
    await app.click('.erf-switch[data-gfx="kontur"]');
    eq(app.need('.erf-switch[data-gfx="kontur"]').classList.contains('is-on'), false,
      'Umrandung ließ sich nicht abschalten');
    const gemerkt = (app.store('settings') || {}).grafik;
    eq(gemerkt.schrift, 'schmal', 'Schrift nicht gespeichert');
    eq(gemerkt.kontur, false, 'Umrandung nicht gespeichert');
    // Ohne Kontur muss weiter gezeichnet UND eine Datei erzeugt werden.
    await warteAufDatei(app);
    app.assertClean();
  });

  test('PNG speichern lädt eine Datei mit sprechendem Namen', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk, DESKTOP);
    await oeffneGrafik(app);
    await warteAufDatei(app);
    await app.click('[data-gfx="download"]');
    eq(app.downloads.length, 1, 'kein Download ausgelöst');
    const name = app.downloads[0].name;
    includes(name, 'E2E-Cup', 'Wettkampfname im Dateinamen');
    ok(name.endsWith('.png'), 'Dateiendung ist nicht .png: ' + name);
    app.assertClean();
  });

  test('Trainingsspiel: Rangliste ohne Logos, Spielpunkte und EWP', async (app) => {
    const game = makeGame({
      preset: 'schere', saetze: 2, wuerfeProSatz: 4,
      teilsaetze: ['volle', 'kranz-abraeumen'], bahnen: 2, spieler: ['Anna', 'Bert'],
    });
    game.erfassung = makeErfassung(game.config, [
      [[9, 8, 7, 2], [6, 6, 5, 4]],
      [[3, 3, 3, 3], [2, 2, 2, 2]],
    ]);
    game.status = 'beendet';
    await app.boot({ hash: '/spiel-laufend', ...MOBIL, storage: { games: [game], 'active-game': game.id } });
    await oeffneGrafik(app);
    ['logos', 'spielpunkte', 'ewp'].forEach((id) => {
      eq(app.need(`.erf-switch[data-gfx="${id}"]`).disabled, true, `${id} müsste gesperrt sein`);
    });
    // Der Titel kommt aus dem Modell und lässt sich frei überschreiben.
    await app.setInput('[data-gfx-text="titel"]', 'Trainingsabend');
    await warteAufDatei(app);
    await app.click('[data-gfx="download"]');
    includes(app.downloads[0].name, 'Trainingsabend', 'geänderter Titel im Dateinamen');
    app.assertClean();
  });

  test('Menü schließt per ✕ und beim Verlassen der Seite', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    await oeffneGrafik(app);
    await app.click('[data-gfx="close"]');
    ok(!app.$('.gfx-backdrop'), 'Panel blieb nach ✕ stehen');

    // UNMOUNT-Regression: das Panel hängt außerhalb von #app und würde eine Navigation
    // ohne den Router-Listener überleben.
    await oeffneGrafik(app);
    await app.go('/statistiken');
    ok(!app.$('.gfx-backdrop'), 'Panel überlebt die Navigation');
    app.assertClean();
  });
});
