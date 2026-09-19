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

  test('Titel und Untertitel stehen beim Wiederöffnen wieder da', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    await oeffneGrafik(app);
    await app.setInput('[data-gfx-text="titel"]', 'Derby-Abend');
    await app.setInput('[data-gfx-text="untertitel"]', 'Halle 2 · 3. Spieltag');
    await app.click('[data-gfx="close"]');

    // Zweiter Aufruf: die eigenen Eingaben schlagen den Vorschlag aus dem Modell
    // (der waere wieder 'E2E-Cup').
    await oeffneGrafik(app);
    eq(app.need('[data-gfx-text="titel"]').value, 'Derby-Abend', 'Titel zurückgesetzt');
    eq(app.need('[data-gfx-text="untertitel"]').value, 'Halle 2 · 3. Spieltag', 'Untertitel zurückgesetzt');
    // Gemerkt wird JE SPIEL, nicht global — sonst truege der naechste Wettkampf den Namen mit.
    const topf = (app.store('settings') || {}).grafikTexte || {};
    eq(Object.keys(topf).length, 1, 'genau ein Eintrag erwartet');
    includes(Object.keys(topf)[0], 'wk:', 'Schlüssel gehört nicht zum Wettkampf');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Reiter „Livestream": Overlay-Vorschau, Logo-Felder und OBS-Hinweis', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk, DESKTOP);
    await oeffneGrafik(app);
    // Standard ist die Grafik; der zweite Reiter zeigt das Overlay.
    ok(!app.$('.gfx-pane[data-pane="grafik"]').hidden, 'Grafik-Reiter ist nicht offen');
    ok(app.$('.gfx-pane[data-pane="stream"]').hidden, 'Livestream-Reiter ist vorab offen');
    await app.click('[data-gfx-tab="stream"]');
    ok(app.$('.gfx-pane[data-pane="grafik"]').hidden, 'Grafik-Reiter blieb offen');
    const pane = app.need('.gfx-pane[data-pane="stream"]');
    ok(pane.querySelector('.gfx-ov-frame'), 'Vorschau-Rahmen fehlt');
    // In der Vorschau steckt das ECHTE Overlay-Markup (dieselbe Funktion wie in OBS).
    ok(pane.querySelector('.ov-bar'), 'Overlay-Vorschau ist leer');
    includes(pane.textContent, 'Heim', 'Mannschaft fehlt in der Vorschau');
    // Logos/Farben sind hier einstellbar — im Hub gab es das nur im Kontrollzentrum.
    eq(pane.querySelectorAll('input[data-accent]').length, 2, 'Akzentfarbe je Mannschaft');
    // Ungeteilter Wettkampf: statt der URL der Hinweis aufs Teilen.
    ok(!pane.querySelector('[data-overlay-url]'), 'URL trotz ungeteiltem Wettkampf');
    includes(pane.textContent, 'teilen', 'Hinweis auf das Teilen fehlt');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Akzentfarbe aus dem Livestream-Reiter landet im Wettkampf', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk, DESKTOP);
    await oeffneGrafik(app);
    await app.click('[data-gfx-tab="stream"]');
    await app.setInput('.gfx-pane[data-pane="stream"] input[data-accent="m1"]', '#123456');
    const gespeichert = app.activeWettkampf();
    eq(gespeichert.mannschaften[0].accent, '#123456', 'Akzentfarbe nicht gespeichert');
    // Das Panel baut den Reiter danach neu auf — der Wert muss stehen bleiben.
    eq(app.need('.gfx-pane[data-pane="stream"] input[data-accent="m1"]').value, '#123456',
      'Farbwähler zeigt den alten Wert');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Standardfarben: ein Tupfer setzt die Akzentfarbe und ist danach markiert', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk, DESKTOP);
    await oeffneGrafik(app);
    await app.click('[data-gfx-tab="stream"]');
    const tupfer = (team) => `.gfx-pane[data-pane="stream"] [data-accent-preset="${team}"]`;
    // Je Mannschaft dieselbe Palette; der Standard (Kegel-Gold) steht vorn und ist markiert,
    // solange die Mannschaft keine eigene Farbe hat.
    eq(app.$$(tupfer('m1')).length, app.$$(tupfer('m2')).length, 'Paletten unterschiedlich lang');
    eq(app.$$(tupfer('m1'))[0].dataset.hex, '#F5A623', 'Standardfarbe steht nicht vorn');
    ok(app.$$(tupfer('m1'))[0].classList.contains('is-on'), 'Standardfarbe ist nicht markiert');

    await app.click(`${tupfer('m1')}[data-hex="#6FD661"]`);
    eq(app.activeWettkampf().mannschaften[0].accent, '#6fd661', 'Farbe nicht gespeichert');
    // Nach dem Neuaufbau: der Tupfer ist markiert und der Farbwähler zeigt denselben Ton.
    ok(app.need(`${tupfer('m1')}[data-hex="#6FD661"]`).classList.contains('is-on'),
      'gewählter Tupfer ist nicht markiert');
    eq(app.need('.gfx-pane[data-pane="stream"] input[data-accent="m1"]').value, '#6fd661',
      'Farbwähler folgt dem Tupfer nicht');
    // Die Mitmannschaft bleibt unberührt.
    eq(app.activeWettkampf().mannschaften[1].accent, undefined, 'fremde Mannschaft mitgefärbt');

    // Zurück auf Kegel-Gold = Default -> das Feld wird wieder weggelassen (alte Stände gleich).
    await app.click(`${tupfer('m1')}[data-hex="#F5A623"]`);
    eq(app.activeWettkampf().mannschaften[0].accent, undefined, 'Default wurde gespeichert');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Reiter „Beamer": ausführliche Ergebnistafel mit Satz- und Abräum-Spalten', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk, DESKTOP);
    await oeffneGrafik(app);
    ok(app.$('.gfx-pane[data-pane="beamer"]').hidden, 'Beamer-Reiter ist vorab offen');
    await app.click('[data-gfx-tab="beamer"]');
    ok(app.$('.gfx-pane[data-pane="grafik"]').hidden, 'Grafik-Reiter blieb offen');
    ok(app.$('.gfx-pane[data-pane="stream"]').hidden, 'Livestream-Reiter blieb offen');
    const pane = app.need('.gfx-pane[data-pane="beamer"]');
    ok(pane.querySelector('.gfx-bm-frame'), 'Vorschau-Rahmen fehlt');
    // In der Vorschau steckt die ECHTE Tafel (dieselbe Funktion wie unter #/beamer).
    ok(pane.querySelector('.bm-page'), 'Beamer-Vorschau ist leer');
    // Eine Zeile je Spieler beider Mannschaften (2 x 4).
    eq(pane.querySelectorAll('.bm-row').length, 8, 'Spielerzeilen');
    // Standard ist die Bahn-Ansicht -> eine Überschrift über dem Gassen-Block, darunter die
    // blanken Nummern (die brechen nie um), innen das Gesamt mit der V/A-Aufteilung.
    eq([...pane.querySelectorAll('.bm-table-l .bm-grp-h')].map((th) => th.textContent).join(' · '),
      'Bahnen · Gesamt', 'Überschriften der Blöcke');
    eq([...pane.querySelectorAll('.bm-table-l .bm-nr-h')].map((th) => th.textContent).join(' '),
      '1 2 3 4', 'Bahn-Nummern');
    // Beim Gast bleiben die BAHNEN aufsteigend (dieselbe Bahn im Saal), alles andere spiegelt.
    eq([...pane.querySelectorAll('.bm-table-r .bm-nr-h')].map((th) => th.textContent).join(' '),
      '1 2 3 4', 'Bahnen laufen rechts rückwärts');
    eq(pane.querySelectorAll('.bm-table-l .bm-v-h').length, 1, 'V/A nur in der Gesamt-Gruppe');
    ok(pane.querySelector('.bm-table-l td.bm-v.is-ges'), 'Volle im Gesamt fehlen');
    ok(pane.querySelector('.bm-table-l td.bm-a.is-ges'), 'Abräumen im Gesamt fehlt');
    ok(!pane.querySelector('.bm-table-l td.bm-v:not(.is-ges)'), 'Volle stehen wieder je Gasse');
    // Ohne eingestellte Ueberschrift traegt die Tafel gar keine — und der Wettkampf-Satz im
    // Kopfband ist ebenfalls weg.
    ok(!pane.querySelector('.bm-titel'), 'Ueberschrift ohne Eingabe');
    ok(!pane.querySelector('.bm-wk'), 'der Wettkampf-Satz steht noch im Kopfband');
    // Unten links das Datum, unten rechts der Spielort.
    eq(pane.querySelector('.bm-fuss-l').textContent, '02.09.2026', 'Datum unten links');
    eq(pane.querySelector('.bm-fuss-r').textContent, 'Testhalle', 'Spielort unten rechts');
    // Ergebnisse zur Mitte: rechts steht der Name außen (gespiegelt wie im Livestream).
    // Nur die ERSTE Kopfzeile — die zweite trägt das V/A/Ges jeder Gruppe.
    const rechts = [...pane.querySelectorAll('.bm-table-r thead tr')[0].children].map((th) => th.className);
    eq(rechts[rechts.length - 1], 'bm-nm-h', 'rechte Tabelle ist nicht gespiegelt');
    eq(rechts[0], 'bm-ewp-h', 'rechts zeigt die EWP-Spalte nicht zur Mitte');
    // Durchgangs-Anzeige und Bestenliste sind bewusst weg.
    ok(!pane.querySelector('.bm-dg, .bm-dg-h, .bm-dg-chip'), 'Durchgangs-Anzeige ist noch da');
    ok(!pane.querySelector('.bm-foot, .bm-best'), 'Bestenliste ist noch da');
    // Vollbild geht auf DIESEM Gerät, ganz ohne Teilen; die URL kommt erst mit dem Teilen.
    ok(pane.querySelector('[data-gfx="beamer-voll"]'), 'Vollbild-Knopf fehlt');
    ok(!pane.querySelector('[data-beamer-url]'), 'URL trotz ungeteiltem Wettkampf');
    includes(pane.textContent, 'teilen', 'Hinweis auf das Teilen fehlt');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Geteilter Wettkampf: Beamer-URL zeigt auf #/beamer mit dem Zuschauer-Code', async (app) => {
    const wk = baueWettkampf();
    wk.wettkampf.linked = true;
    wk.wettkampf.zuschauerCode = 'ZS12';
    wk.wettkampf.code = 'EINGABE';
    await starteHub(app, wk, DESKTOP);
    await oeffneGrafik(app);
    await app.click('[data-gfx-tab="beamer"]');
    const url = app.need('[data-beamer-url]').value;
    includes(url, '#/beamer?code=ZS12', 'falsche Beamer-URL');
    // Spalten und Darstellung stellt das Gerät am Beamer selbst ein (Bedienleiste der Tafel) —
    // die URL bleibt kurz genug zum Abtippen.
    ok(!url.includes('spalten') && !url.includes('thema'), 'Einstellungen hängen noch in der URL');
    // Der EINGABE-Code darf nicht auf die Leinwand-URL — die Tafel liest nur mit.
    ok(!url.includes('EINGABE'), 'Eingabe-Code in der Beamer-URL');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Beamer-Einstellung: Spalten nach Bahnen oder nach Sätzen', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    wk.wettkampf.linked = true;
    wk.wettkampf.zuschauerCode = 'ZS12';
    await starteHub(app, wk, DESKTOP);
    await oeffneGrafik(app);
    await app.click('[data-gfx-tab="beamer"]');
    const pane = () => app.need('.gfx-pane[data-pane="beamer"]');
    const koepfe = () => [...pane().querySelectorAll('.bm-table-l .bm-grp-h')].map((th) => th.textContent).join(',')
      + ' [' + [...pane().querySelectorAll('.bm-table-l .bm-nr-h')].map((th) => th.textContent).join(' ') + ']';
    const schalter = (id, wert) => `[data-bm="${id}"][data-wert="${wert}"]`;
    // Standard: Bahnen (vier bespielte Bahnen) und dunkle Darstellung.
    eq(koepfe(), 'Bahnen,Gesamt [1 2 3 4]', 'Standard ist nicht die Bahn-Ansicht');
    ok(app.need(schalter('spalten', 'bahnen')).classList.contains('is-on'), 'Schalter zeigt Bahnen nicht an');
    ok(!pane().querySelector('.bm-page').classList.contains('is-hell'), 'Standard ist nicht dunkel');

    // Umschalten auf Sätze: der Wettkampf hat 2 Sätze -> zwei Gruppen plus Gesamt.
    await app.click(schalter('spalten', 'saetze'));
    eq(koepfe(), 'Sätze,Gesamt [1 2]', 'nach dem Umschalten keine Satz-Spalten');
    // Sätze sind eine Reihenfolge, keine Bahn -> beim Gast laufen sie rückwärts.
    eq([...pane().querySelectorAll('.bm-table-r .bm-nr-h')].map((th) => th.textContent).join(' '),
      '2 1', 'Sätze sind rechts nicht gespiegelt');
    ok(app.need(schalter('spalten', 'saetze')).classList.contains('is-on'), 'Schalter ist nicht umgesprungen');

    // Heller Modus für helle Säle — Tafel und Rahmen ziehen mit.
    await app.click(schalter('thema', 'hell'));
    ok(pane().querySelector('.bm-page').classList.contains('is-hell'), 'Tafel bleibt dunkel');
    ok(pane().querySelector('.gfx-bm-frame').classList.contains('is-hell'), 'Rahmen bleibt dunkel');
    // Ueberschrift: freies Feld. Ohne Eingabe traegt die Tafel keine Ueberschrift.
    ok(!pane().querySelector('.bm-titel'), 'Ueberschrift ohne Eingabe');
    await app.setInput('[data-bm-titel]', 'Stadtpokal 2026');
    eq(pane().querySelector('.bm-titel').textContent, 'Stadtpokal 2026', 'Ueberschrift nicht in der Tafel');

    // Gespeichert wird AM WETTKAMPF (nicht am Geraet): nur so sieht auch der zweite Rechner
    // am Beamer die Umstellung — er liest den Wettkampf und hat keine eigene Oberflaeche.
    eq((app.activeWettkampf() || {}).beamer.spalten, 'saetze', 'Spaltenwahl nicht am Wettkampf');
    eq((app.activeWettkampf() || {}).beamer.thema, 'hell', 'Darstellung nicht am Wettkampf');
    eq((app.activeWettkampf() || {}).beamer.titel, 'Stadtpokal 2026', 'Ueberschrift nicht am Wettkampf');

    // Nach dem Schließen und erneuten Öffnen stehen beide Wahlen noch.
    await app.click('[data-gfx="close"]');
    await oeffneGrafik(app);
    await app.click('[data-gfx-tab="beamer"]');
    eq(koepfe(), 'Sätze,Gesamt [1 2]', 'Einstellung beim Öffnen zurückgesetzt');
    ok(pane().querySelector('.bm-page').classList.contains('is-hell'), 'Darstellung beim Öffnen zurückgesetzt');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Trainingsspiel ohne Wettkampf: Livestream- und Beamer-Reiter erklären sich', async (app) => {
    const game = makeGame({
      preset: 'schere', saetze: 2, wuerfeProSatz: 4,
      teilsaetze: ['volle', 'kranz-abraeumen'], bahnen: 2, spieler: ['Anna', 'Bert'],
    });
    await app.boot({ hash: '/spiel-laufend', ...MOBIL, storage: { games: [game], 'active-game': game.id } });
    await oeffneGrafik(app);
    await app.click('[data-gfx-tab="stream"]');
    const pane = app.need('.gfx-pane[data-pane="stream"]');
    ok(!pane.querySelector('.gfx-ov-frame'), 'Vorschau trotz fehlendem Wettkampf');
    includes(pane.textContent, 'Wettkampf', 'Hinweis auf den fehlenden Wettkampf');
    // Dasselbe für die Beamer-Tafel: ohne Wettkampf gibt es nichts anzuzeigen.
    await app.click('[data-gfx-tab="beamer"]');
    const bm = app.need('.gfx-pane[data-pane="beamer"]');
    ok(!bm.querySelector('.gfx-bm-frame'), 'Beamer-Vorschau trotz fehlendem Wettkampf');
    includes(bm.textContent, 'Wettkampf', 'Hinweis auf den fehlenden Wettkampf');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Reiter „Spieler": Auswahl aller Spieler, Wurfbild und eigene Texte', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    // Ein Logo an der Heim-Mannschaft -> der Logo-Schalter ist nur dort frei.
    wk.wettkampf.mannschaften[0].logo = 'data:image/png;base64,AAA';
    await starteHub(app, wk, DESKTOP);
    await oeffneGrafik(app);
    ok(app.$('.gfx-pane[data-pane="spieler"]').hidden, 'Spieler-Reiter ist vorab offen');
    await app.click('[data-gfx-tab="spieler"]');
    ok(app.$('.gfx-pane[data-pane="grafik"]').hidden, 'Grafik-Reiter blieb offen');
    const pane = app.need('.gfx-pane[data-pane="spieler"]');

    // Alle 8 Spieler (2 Mannschaften à 4, über 2 Durchgänge), nach Mannschaft gruppiert.
    const wahl = pane.querySelector('[data-sp-wahl]');
    eq(wahl.options.length, 8, 'Spieler in der Auswahl');
    eq([...wahl.querySelectorAll('optgroup')].map((g) => g.label).join(' · '), 'Heim · Gast',
      'Gruppierung nach Mannschaft');

    // Das Bild entsteht mit denselben Maßen wie die Ergebnis-Grafik.
    const canvas = pane.querySelector('[data-sp-canvas]');
    eq(canvas.width, 1080, 'Canvas-Breite');
    eq(canvas.height, 1440, 'Canvas-Höhe');
    includes(pane.querySelector('[data-sp-meta]').textContent, 'Transparenz', 'Hinweis fehlt');
    // Ohne eigenen Namen steht der aus der Aufstellung im Platzhalter.
    eq(pane.querySelector('[data-sp-titel]').placeholder, wahl.options[0].text.replace(/^\d+\. /, '').replace(/ · Bahn.*$/, ''),
      'Platzhalter nennt nicht den Spielernamen');

    // Der Logo-Schalter hängt an der Mannschaft des GEWÄHLTEN Spielers.
    eq(pane.querySelector('.erf-switch[data-sgfx="logo"]').disabled, false, 'Heim hat ein Logo');
    await app.setSelect('[data-sp-wahl]', wahl.options[4].value); // erster Gast-Spieler
    eq(pane.querySelector('.erf-switch[data-sgfx="logo"]').disabled, true,
      'Gast hat kein Logo, der Schalter müsste gesperrt sein');
    await app.setSelect('[data-sp-wahl]', wahl.options[0].value);

    // Überschrift und Name werden JE SPIELER gemerkt.
    await app.setInput('[data-sp-ueber]', 'Einzelergebnis');
    await app.setInput('[data-sp-titel]', 'Der Kapitän');
    await app.setSelect('[data-sp-wahl]', wahl.options[1].value);
    eq(app.need('[data-sp-ueber]').value, '', 'Überschrift wanderte zum nächsten Spieler mit');
    await app.setSelect('[data-sp-wahl]', wahl.options[0].value);
    eq(app.need('[data-sp-ueber]').value, 'Einzelergebnis', 'Überschrift ging verloren');
    eq(app.need('[data-sp-titel]').value, 'Der Kapitän', 'Name ging verloren');

    // Reihenfolge und Optionen werden getrennt von der Ergebnis-Grafik gespeichert.
    await app.click('[data-sgfx="reihenfolge"][data-wert="bahnen"]');
    eq((app.store('settings') || {}).spielerGrafik.reihenfolge, 'bahnen', 'Reihenfolge nicht gemerkt');
    // Getrennte Töpfe: die Optionen der Ergebnis-Grafik bleiben unberührt (hier: ungesetzt).
    eq((app.store('settings') || {}).grafik, undefined, 'die Ergebnis-Grafik wurde mitverstellt');

    // PNG speichern trägt den eigenen Namen im Dateinamen.
    await app.waitFor(() => !pane.querySelector('[data-sgfx="download"]').disabled, 'PNG wurde nicht erzeugt');
    await app.click('[data-sgfx="download"]');
    eq(app.downloads.length, 1, 'kein Download ausgelöst');
    includes(app.downloads[0].name, 'Der-Kapitän', 'eigener Name fehlt im Dateinamen');
    includes(app.downloads[0].name, 'Wurfbild', 'Präfix fehlt im Dateinamen');
    await app.click('[data-gfx="close"]');
    app.assertClean();
  });

  test('Reiter „Spieler": Trainingsspiel ohne Mannschaften', async (app) => {
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
    await app.click('[data-gfx-tab="spieler"]');
    const pane = app.need('.gfx-pane[data-pane="spieler"]');
    // Ohne Wettkampf gibt es keine Gruppen, aber sehr wohl Spieler.
    eq(pane.querySelector('[data-sp-wahl]').options.length, 2, 'Spieler in der Auswahl');
    eq(pane.querySelectorAll('[data-sp-wahl] optgroup').length, 0, 'Gruppen ohne Mannschaften');
    // Ohne Logo bleibt der Schalter gesperrt — anders als Livestream und Beamer ist der
    // Reiter aber nutzbar: das Wurfbild braucht keinen Wettkampf.
    eq(pane.querySelector('.erf-switch[data-sgfx="logo"]').disabled, true, 'Logo ohne Mannschaft');
    ok(!pane.querySelector('.gfx-body').hidden, 'Vorschau fehlt im Trainingsspiel');
    await app.waitFor(() => !pane.querySelector('[data-sgfx="download"]').disabled, 'PNG wurde nicht erzeugt');
    await app.click('[data-sgfx="download"]');
    includes(app.downloads[0].name, 'Anna', 'Spielername fehlt im Dateinamen');
    await app.click('[data-gfx="close"]');
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
