// Wettkampf: Setup-Maske, Hub (Aufstellung, Durchgänge, Wertung, Auswertung,
// Mannschafts-Export) und der Weg vom Durchgang in die Erfassung und zurück.

import { suite, test, ok, eq, deepEq, includes, notIncludes } from '../harness.js';
import { buildWettkampf } from '../../../js/logic/wettkampf-build.js';
import {
  parseSpielerInfo, buildImportSpec, buildImportWettkampf,
} from '../../../js/logic/sw-web-import.js';
import { makeErfassung } from '../fixtures.js';

const MOBIL = { width: 420, height: 900 };
const DESKTOP = { width: 1280, height: 900 };

// Ein vollständiger Wettkampf, gebaut mit dem PRODUKTIVEN Builder (logic/wettkampf-build.js):
// 2 Mannschaften à 4 Spieler auf 4 Bahnen (je 2), Schere, 2 Sätze à 4 Würfe
// -> planDurchgaenge ergibt 2 Durchgänge.
function baueWettkampf({ wertung = null } = {}) {
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
    // EWP-Schwelle in der neutralen Mitte des Team-EWP-Bereichs (Topf 36 bei 8 Spielern):
    // so entscheidet der Zusatzpunkt wirklich mit und geht nicht automatisch an den Gast.
    wertung: wertung || {
      modus: 'duell', gesamtholzPunkte: 2, kriterium2: 'ewp', kriterium2Punkte: 2, ewpSchwelle: 18,
    },
  });
}

// Derselbe Wettkampf, aber OHNE Anlage (rein lokal) — freie Bahnnummern, keine Zuordnung.
function baueWettkampfOhneAnlage() {
  return buildWettkampf({
    name: 'Lokaler Cup',
    datum: '2026-09-02',
    preset: 'schere',
    saetze: 2,
    wuerfeProSatz: 4,
    teilsaetze: ['volle', 'kranz-abraeumen'],
    bahnwechsel: 'plus1',
    anlageId: null,
    anlageName: '',
    anlageBahnen: [],
    playedLanes: [1, 2, 3, 4],
    mannschaften: [
      { id: 'm1', name: 'Heim', lanes: [1, 2] },
      { id: 'm2', name: 'Gast', lanes: [3, 4] },
    ],
    spielerJeMannschaft: 4,
  });
}

// Ein Wettkampf aus dem WEB-IMPORT, gebaut mit der produktiven Kette (logic/sw-web-import.js).
// Der Ergebnisdienst nennt bei Schere nur das Satz-Holz, also bekommt jeder Satz genau EINEN
// Teilsatz — hier wird geprüft, dass der Hub damit umgeht, statt eine Volle/Abräum-Trennung zu
// zeigen, die es nicht gibt. Zeilenformat wie in tests/fixtures/sw-web-spielerinfo-schere.json.
function baueWebImport() {
  const summe = (s) => s.reduce((a, b) => a + b, 0);
  const zeile = (nGG, sGG, nG, sG) => ['', nGG, ...sGG, 0, summe(sGG),
    summe(sG), 0, ...sG.slice().reverse(), nG, '', 0, 0];
  const bericht = parseSpielerInfo([
    zeile('Heim 1', [150, 160, 155, 145], 'Gast 1', [140, 150, 160, 150]),
    zeile('Heim 2', [160, 150, 150, 150], 'Gast 2', [150, 150, 150, 150]),
  ], { saetze: 4 });
  const spec = buildImportSpec(
    { heim: 'Heim', gast: 'Gast', datum: '2026-09-02', idSpiel: '328202' }, bericht,
  );
  spec.preset = 'schere';
  return buildImportWettkampf(spec, { playedLanes: [1, 2, 3, 4] });
}

async function starteHub(app, { wettkampf, games }, layout = MOBIL) {
  await app.boot({
    hash: '/wettkampf',
    ...layout,
    storage: { wettkaempfe: [wettkampf], games, 'active-wettkampf': wettkampf.id },
  });
  return { wettkampf, games };
}

// Alle Durchgänge mit Würfen füllen (Heim stark, Gast schwach) — für Rangliste/Wertung.
function fuelleErgebnisse(games, { heimWurf = 8, gastWurf = 4 } = {}) {
  games.forEach((g) => {
    const c = g.config;
    const wuerfe = c.spielerListe.map((sp) => {
      const w = sp.mannschaftId === 'm1' ? heimWurf : gastWurf;
      return Array.from({ length: c.saetze }, () => Array.from({ length: c.wuerfeProSatz }, () => w));
    });
    g.erfassung = makeErfassung(c, wuerfe);
    g.status = 'beendet';
  });
  return games;
}

suite('Wettkampf · Setup-Maske', () => {
  test('Setup zeigt drei Tabs und lässt sich ohne Anlage abschließen', async (app) => {
    await app.boot({ hash: '/setup/wettkampf', ...MOBIL });
    deepEq(app.$$('.tabs .tab').map((t) => t.textContent.trim()),
      ['Programm', 'Mannschaften', 'Wertung'], 'Tab-Leiste');
    includes(app.txt('.setup'), 'bleibt der Wettkampf auf', 'Hinweis zum lokalen Wettkampf fehlt');
    await app.click('[data-tab="wertung"]');
    const primary = app.$('.btn-primary');
    eq(primary.dataset.action, 'create', 'letzter Tab führt nicht zum Anlegen');
    ok(!primary.disabled, 'Anlegen war ohne Anlage gesperrt');
    app.assertClean();
  });

  test('Ohne Anlage wird der Bahnbereich frei gewählt', async (app) => {
    await app.boot({ hash: '/setup/wettkampf', ...MOBIL });
    ok(app.$('[data-input="freiBahnen"]'), 'Bahnen-Stepper fehlt');
    eq(app.$('[data-input="freiBahnen"]').value, '4', 'Standard: 4 Bahnen');
    await app.setInput('[data-input="freiBahnen"]', '6');
    await app.setInput('[data-input="freiErsteBahn"]', '3');
    includes(app.txt('.setup'), 'Bahn 3–8', 'Bahnbereich falsch');
    await app.click('[data-tab="mannschaften"]');
    deepEq(app.$$('.team-block .field-hint').map((x) => x.textContent.trim()),
      ['Startbahn(en): 3, 4, 5', 'Startbahn(en): 6, 7, 8'], 'Standard-Aufteilung auf die Teams');
    app.assertClean();
  });

  test('Ein lokaler Wettkampf entsteht komplett ohne Anlage', async (app) => {
    await app.boot({ hash: '/setup/wettkampf', ...MOBIL });
    await app.setInput('[data-field="name"]', 'Lokaler Cup');
    await app.click('[data-preset="schere"]');
    await app.click('[data-tab="wertung"]');
    await app.clickText('.btn-primary', 'Wettkampf erstellen');
    await app.waitFor(() => app.route() === '/wettkampf', 'Hub wurde nicht geöffnet');
    const w = app.activeWettkampf();
    eq(w.name, 'Lokaler Cup', 'Name');
    eq(w.anlageId, null, 'Anlage wurde gesetzt, obwohl keine gewählt war');
    deepEq(w.playedLanes, [1, 2, 3, 4], 'bespielte Bahnen');
    ok(w.durchgaenge.length > 0, 'keine Durchgänge geplant');
    const g = app.games().find((x) => x.wettkampfId === w.id);
    deepEq(g.config.bahnZuordnung, {}, 'ohne Anlage darf es keine Bahn-Zuordnung geben');
    app.assertClean();
  });

  test('Bahnart, Sätze und Teilsätze lassen sich im Programm-Tab setzen', async (app) => {
    await app.boot({ hash: '/setup/wettkampf', ...MOBIL });
    await app.click('[data-preset="classic"]');
    await app.setInput('[data-input="saetze"]', '6');
    eq(app.$('[data-input="saetze"]').value, '6', 'Sätze');
    deepEq(app.$$('.part-modus').map((s) => s.value), ['volle', 'abraeumen'], 'Classic-Teilsätze');
    app.assertClean();
  });

  test('Mannschaften-Tab: Anzahl, Namen und Bahn-Aufteilung', async (app) => {
    await app.boot({ hash: '/setup/wettkampf', ...MOBIL });
    await app.click('[data-tab="mannschaften"]');
    eq(app.$$('.team-name').length, 2, 'zwei Mannschaften voreingestellt');
    await app.setInput('.team-name', 'Osnabrück');
    eq(app.$('.team-name').value, 'Osnabrück', 'Name nicht übernommen');
    await app.click('[data-step="inc"][data-field="mannschaftenCount"]');
    eq(app.$$('.team-name').length, 3, 'dritte Mannschaft fehlt');
    // Bahnen werden neu aufgeteilt; keine Bahn darf zwei Teams gehören.
    const zuordnung = app.$$('.team-block .chip.is-active').map((c) => c.textContent.trim());
    eq(new Set(zuordnung).size, zuordnung.length, 'Bahn doppelt zugeordnet');
    app.assertClean();
  });

  test('Wertungs-Tab: Kriterium umschalten', async (app) => {
    await app.boot({ hash: '/setup/wettkampf', ...MOBIL });
    await app.click('[data-tab="wertung"]');
    ok(app.$('[data-krit2="satzpunkte"]'), 'Satzpunkte-Auswahl fehlt');
    await app.click('[data-krit2="satzpunkte"]');
    ok(app.$('[data-krit2="satzpunkte"]').className.match(/is-(active|on)/), 'Auswahl nicht aktiv');
    app.assertClean();
  });
});

suite('Wettkampf · Hub', () => {
  test('Hub zeigt Kopf, Mannschaften und die geplanten Durchgänge', async (app) => {
    const wk = baueWettkampf();
    eq(wk.games.length, 2, 'Testvoraussetzung: zwei Durchgänge');
    await starteHub(app, wk);
    includes(app.page(), 'E2E-Cup', 'Wettkampf-Name');
    includes(app.page(), 'Testhalle', 'Anlage in der Kopfzeile');
    eq(app.$$('.wk-team-card').length, 2, 'zwei Mannschafts-Tafeln');
    eq(app.$$('.wk-dg').length, 2, 'zwei Durchgangs-Karten');
    includes(app.txt('.wk-dg'), 'Vorbereitung', 'erster Durchgang nicht in Vorbereitung');
    app.assertClean();
  });

  test('Aufstellung: Name eintragen landet im Durchgang-Spiel', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    const feld = app.$('.roster-name[data-team="m1"][data-pos="1"]');
    ok(feld, 'Aufstellungsfeld fehlt');
    await app.setInput('.roster-name[data-team="m1"][data-pos="1"]', 'Anna Meier');
    const alle = app.games().filter((g) => g.wettkampfId === wk.wettkampf.id);
    const treffer = alle.flatMap((g) => g.config.spielerListe)
      .filter((p) => p.mannschaftId === 'm1' && p.teamPos === 1);
    ok(treffer.length > 0, 'kein Spieler auf m1|1');
    ok(treffer.every((p) => p.name === 'Anna Meier'), 'Name nicht in alle Durchgänge übernommen');
    app.assertClean();
  });

  test('Startbahn eines Spielers lässt sich innerhalb der Team-Bahnen wechseln', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    const sel = app.$('.roster-lane[data-team="m1"][data-pos="1"]');
    ok(sel, 'Startbahn-Auswahl fehlt');
    deepEq(Array.from(sel.options).map((o) => o.value), ['1', '2'], 'nur die Team-Bahnen');
    await app.setSelect('.roster-lane[data-team="m1"][data-pos="1"]', '2');
    const g0 = app.games().find((g) => g.durchgangNr === 1);
    const p = g0.config.spielerListe.find((x) => x.mannschaftId === 'm1' && x.teamPos === 1);
    eq(p.startBahn, 2, 'Startbahn nicht übernommen');
    app.assertClean();
  });

  test('Durchgang öffnen führt in die Erfassung, Zurück in den Hub', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    await app.click('.wk-dg-main');
    await app.waitFor(() => app.route() === '/spiel-laufend', 'Durchgang öffnete nicht');
    eq(app.$('.back-btn').getAttribute('href'), '#/wettkampf', 'Zurück führt nicht in den Hub');
    await app.click('.back-btn');
    await app.waitFor(() => app.route() === '/wettkampf', 'Rückweg funktionierte nicht');
    app.assertClean();
  });

  test('Durchgang löschen fragt nach und entfernt ihn', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    app.confirmAnswer = false;
    await app.click('[data-del-durchgang]');
    eq(app.$$('.wk-dg').length, 2, 'trotz Abbruch gelöscht');
    app.confirmAnswer = true;
    await app.click('[data-del-durchgang]');
    await app.waitFor(() => app.$$('.wk-dg').length === 1, 'Durchgang wurde nicht gelöscht');
    eq(app.activeWettkampf().durchgaenge.length, 1, 'Durchgang blieb im Wettkampf');
    app.assertClean();
  });

  test('„+ Durchgang" öffnet das Durchgangs-Setup mit der Wettkampf-Vorlage', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    await app.click('[data-action="add-durchgang"]');
    await app.waitFor(() => app.route() === '/setup/wettkampf-durchgang', 'Setup öffnete nicht');
    includes(app.txt('.page-title'), 'Durchgang', 'Titel');
    ok(app.$('.seg-btn.is-active').textContent.includes('Schere'), 'Bahnart nicht aus der Vorlage');
    await app.click('[data-tab="spieler"]');
    ok(app.$('.player-team'), 'Mannschafts-Zuordnung fehlt im Wettkampf-Modus');
    app.assertClean();
  });

  test('Ergebnisse füllen Einzel- und Mannschaftszahlen der Übersicht', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    // Heim: 2 Spieler × 2 Durchgänge? Nein — je Spieler 2 Sätze à 4 Würfe à 8 = 64.
    includes(app.txt('.wk-teams'), '64', 'Einzelergebnis Heim fehlt');
    includes(app.txt('.wk-teams'), '32', 'Einzelergebnis Gast fehlt');
    includes(app.txt('.wk-teams'), '🥇', 'Führung nicht markiert');
    app.assertClean();
  });

  test('Duell-Wertung vergibt Spielpunkte an die stärkere Mannschaft', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    const punkte = app.$$('.wk-team-sp').map((e) => e.textContent.replace(/Punkte/, '').trim());
    eq(punkte.length, 2, 'keine Spielpunkte angezeigt');
    // Heim gewinnt Gesamtholz (2 Punkte) UND den EWP-Punkt (Gast bleibt unter der Schwelle).
    deepEq(punkte, ['4', '0'], 'Spielpunkte des Duells');
    app.assertClean();
  });

  test('Ansichts-Leiste schaltet zwischen Durchgängen, Statistik und Wurf-Bild', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    ok(app.$('.wk-dg'), 'Durchgänge nicht die Startansicht');
    await app.click('[data-hubansicht="statistik"]');
    ok(!app.$('.wk-dg'), 'Durchgänge blieben sichtbar');
    ok(app.$('[data-mb-bahn]'), 'Auswertungs-Filter fehlen');
    await app.click('[data-hubansicht="wurfbild"]');
    ok(app.$('[data-mb-bild]'), 'Wurf-Bild-Filter fehlt');
    await app.click('[data-hubansicht="durchgaenge"]');
    ok(app.$('.wk-dg'), 'Rückweg zu den Durchgängen fehlt');
    app.assertClean();
  });

  test('Web-Import: Holz stimmt, Teilsatz-Filter entfällt (nichts geschätzt)', async (app) => {
    const wk = baueWebImport();
    await starteHub(app, wk);
    await app.click('[data-hubansicht="statistik"]');
    deepEq(
      app.$$('.kz-team-auswertung .wk-team-sp').map((e) => e.textContent.replace('Holz', '').trim()),
      ['1220', '1200'],
      'Mannschaftsholz aus dem Ergebnisdienst',
    );
    // Der Bericht trennt Volle und Abräumen nicht — also gibt es hier auch nichts zu filtern.
    eq(app.$$('[data-mb-teil]').length, 0, 'Teilsatz-Filter trotz fehlender Trennung');
    ok(app.$('[data-mb-satz="1"]'), 'nach Sätzen muss sich weiter filtern lassen');
    app.assertClean();
  });

  test('Auswertungs-Filter (Bahn / Satz / Teilsatz) lassen sich setzen', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    await app.click('[data-hubansicht="statistik"]');
    await app.click('[data-mb-satz="1"]');
    ok(app.$('[data-mb-satz="1"]').classList.contains('is-on'), 'Satz-Filter nicht aktiv');
    await app.click('[data-mb-bahn="3"]');
    ok(app.$('[data-mb-bahn="3"]').classList.contains('is-on'), 'Bahn-Filter nicht aktiv');
    await app.click('[data-mb-teil="volle"]');
    ok(app.$('[data-mb-teil="volle"]').classList.contains('is-on'), 'Teilsatz-Filter nicht aktiv');
    app.assertClean();
  });

  test('Mannschafts-CSV enthält alle Spieler des Teams mit Durchgang-Spalte', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    await app.click('[data-export-team-csv="m1"]');
    eq(app.downloads.length, 1, 'kein Download');
    const csv = await app.downloadText();
    const kopf = csv.trim().split(/\r?\n/)[0];
    includes(kopf, 'Durchgang', 'Durchgang-Spalte fehlt');
    includes(kopf, 'Mannschaft', 'Mannschafts-Spalte fehlt');
    ok(csv.includes('Heim'), 'eigene Mannschaft fehlt');
    ok(!csv.includes('Gast 1'), 'fremde Mannschaft mit exportiert');
    app.assertClean();
  });

  test('Mannschafts-PDF wird gedruckt', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    await app.click('[data-export-team-pdf="m1"]');
    await app.waitFor(() => app.prints.length > 0, 'Druck wurde nicht ausgelöst', 6000);
    includes(app.prints[0], 'Heim', 'Mannschaft im Protokoll');
    app.assertClean();
  });

  test('Kontrollzentrum-Layout stellt beide Mannschaften gegenüber', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk, DESKTOP);
    ok(app.$('.kz-team-uebersicht.is-facing'), 'Gegenüberstellung fehlt');
    ok(app.$('.kz-side'), 'Seitenspalte fehlt');
    app.assertClean();
  });

  test('Lokaler Wettkampf: Teilen gesperrt, Anlage-Nachtrag angeboten', async (app) => {
    const wk = baueWettkampfOhneAnlage();
    await starteHub(app, wk);
    const share = app.$('[data-action="share"]');
    ok(share, 'Teilen-Knopf fehlt');
    ok(share.disabled, 'Teilen war ohne Anlage möglich');
    includes(app.txt('.setup'), 'Erst eine Anlage zuweisen', 'Begründung fehlt');
    ok(app.$('[data-anlage-msg]'), 'Anlage-Nachtrag-Sektion fehlt');
    includes(app.txt('.setup'), 'bespielten Bahnen 1, 2, 3, 4', 'geforderte Bahnen nicht genannt');
    app.assertClean();
  });

  test('Lokaler Wettkampf lässt sich trotzdem voll erfassen', async (app) => {
    const wk = baueWettkampfOhneAnlage();
    await starteHub(app, wk);
    await app.click('.wk-dg-main');
    await app.waitFor(() => app.route() === '/spiel-laufend', 'Durchgang öffnete nicht');
    await app.click('[data-act="satz-overview"]');
    await app.waitFor(() => !!app.$('[data-num="9"]'), 'Wurferfassung fehlt');
    await app.click('[data-num="9"]');
    const g = app.games().find((x) => x.wettkampfId === wk.wettkampf.id && x.durchgangNr === 1);
    deepEq(g.erfassung.bloecke[0][0].wuerfe, [9], 'Wurf wurde nicht gespeichert');
    app.assertClean();
  });

  test('Wettkampf mit Anlage bietet keinen Nachtrag an', async (app) => {
    const wk = baueWettkampf();
    await starteHub(app, wk);
    eq(app.$$('[data-action="assign-anlage"]').length, 0, 'Nachtrag trotz Anlage angeboten');
    ok(!app.$('[data-action="share"]').disabled, 'Teilen mit Anlage gesperrt');
    app.assertClean();
  });

  test('Wettkampf ohne aktiven Zeiger stürzt nicht ab', async (app) => {
    await app.boot({ hash: '/wettkampf', ...MOBIL, storage: { wettkaempfe: [], 'active-wettkampf': 'weg' } });
    ok(app.page().length > 0, 'leere Seite');
    app.assertClean();
  });

  test('Beendeter Wettkampf verlässt „Neues Spiel" und steht in den Statistiken', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    // Der gespeicherte Status ist ABSICHTLICH veraltet ('laufend'): die Listen leiten ihn
    // aus den Durchgängen ab, sonst bliebe ein anderswo beendeter Wettkampf hier hängen.
    wk.wettkampf.status = 'laufend';
    await starteHub(app, wk);
    await app.go('/neues-spiel');
    eq(app.$$('[data-resume-wk]').length, 0, 'beendeter Wettkampf noch in der Arbeitsliste');
    await app.go('/statistiken');
    eq(app.$$('[data-open-wk]').length, 1, 'Wettkampf fehlt in der Historie');
    includes(app.txt('[data-open-wk]'), 'E2E-Cup', 'Wettkampf-Name');
    includes(app.txt('[data-open-wk]'), 'Beendet', 'Status-Abzeichen');
    includes(app.txt('[data-open-wk]'), 'Heim', 'Mannschafts-Rangliste');
    // Die einzelnen Durchgänge dürfen NICHT als eigene Spiele erscheinen.
    eq(app.$$('.stat-card').length, 1, 'Durchgänge als eigene Karten gelistet');
    await app.click('[data-open-wk]');
    await app.waitFor(() => app.route() === '/wettkampf', 'Karte öffnete den Hub nicht');
    app.assertClean();
  });

  test('Wettkampf lässt sich im Hub löschen', async (app) => {
    const wk = baueWettkampf();
    fuelleErgebnisse(wk.games);
    await starteHub(app, wk);
    app.confirmAnswer = true;
    await app.click('[data-action="del-wettkampf"]');
    await app.waitFor(() => app.wettkaempfe().length === 0, 'Wettkampf nicht gelöscht');
    eq(app.games().filter((g) => g.wettkampfId).length, 0, 'Durchgang-Spiele blieben liegen');
    await app.waitFor(() => app.route() === '/statistiken', 'nach dem Löschen keine Historie');
    app.assertClean();
  });

  test('Ein beendeter Durchgang setzt den Wettkampf-Status auf „beendet"', async (app) => {
    const wk = baueWettkampf();
    // Nur EIN Durchgang existiert -> mit dessen Spielende ist der Wettkampf fertig.
    wk.wettkampf.durchgaenge = wk.wettkampf.durchgaenge.slice(0, 1);
    wk.games = wk.games.slice(0, 1);
    wk.wettkampf.status = 'laufend';
    const g = wk.games[0];
    g.status = 'laufend';
    // Alle Spieler durchgeworfen — nur beim ersten fehlt der letzte Wurf.
    g.erfassung = makeErfassung(g.config, g.config.spielerListe.map((_, i) =>
      (i === 0 ? [[9, 9, 9, 9], [9, 9, 9]] : [[9, 9, 9, 9], [9, 9, 9, 9]])));
    await starteHub(app, wk);
    await app.click('.wk-dg-main');
    await app.waitFor(() => app.route() === '/spiel-laufend', 'Durchgang öffnete nicht');
    await app.click('[data-act="satz-overview"]');
    await app.waitFor(() => !!app.$('[data-num="9"]'), 'Wurferfassung fehlt');
    await app.click('[data-satz="1"]');
    await app.click('[data-num="9"]');
    await app.waitFor(() => app.activeWettkampf().status === 'beendet',
      'Wettkampf-Status folgte dem Durchgang nicht', 6000);
    app.assertClean();
  });
});
