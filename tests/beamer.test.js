// Beamer-Ergebnistafel (views/beamer.js) — die ausführliche Tafel für die Leinwand.
//
// Geprüft wird die reine Render-Funktion buildBeamerHtml(): dass je Gasse (bzw. Satz) Volle,
// Abräumen und Summe in der richtigen Spalte stehen, dass die Mannschaftssummen stimmen, dass
// die rechte Tabelle gespiegelt ist (Ergebnisse zur Mitte) und dass die Aufteilung nur dort
// erscheint, wo es sie gibt. Genau das ist der Teil, der im Saal an der Wand hängt — ein
// falscher Summenwert fällt dort allen auf.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildBeamerHtml, beamerUrl, beamerOptionen } from '../js/views/beamer.js';
import { buildWettkampf } from '../js/logic/wettkampf-build.js';

// Satz-Holz eines Spielers im Fixture: beide Teilsätze als Summen-Override.
const VOLLE = (i, s) => 90 + i * 3 + s;
const ABR = (i, s) => 40 + i * 2 + s;
const SATZ = (i, s) => VOLLE(i, s) + ABR(i, s);

// Ein Wettkampf über buildWettkampf, alle Sätze gefüllt. `teilsaetze` steuert die Bahnart:
// mit 'kranz-abraeumen' gibt es Abräum-Holz und (Schere) eine Wertung, mit zwei 'volle'
// nicht. `gespielt` begrenzt, wie viele Durchgänge Ergebnisse haben.
function mkWettkampf({ preset = 'schere', teilsaetze = ['volle', 'kranz-abraeumen'], spielerJeMannschaft = 4, gespielt = Infinity, bahnen = [2, 3, 4, 5] } = {}) {
  const halb = Math.ceil(bahnen.length / 2);
  const spec = {
    name: 'Testpokal', datum: '2026-09-15', preset, saetze: 4, wuerfeProSatz: 30,
    teilsaetze, bahnwechsel: 'plus1',
    anlageId: 'a1', anlageName: 'Halle',
    anlageBahnen: bahnen.map((n) => ({ id: 'b' + n, nummer: n, bahnart: preset })),
    playedLanes: bahnen,
    mannschaften: [{ id: 'A', name: 'VOK Osnabrück 1', lanes: bahnen.slice(0, halb) },
      { id: 'B', name: 'SV Union Lohne 1', lanes: bahnen.slice(halb) }],
    spielerJeMannschaft,
  };
  const { wettkampf, games } = buildWettkampf(spec);
  games.forEach((g, dg) => {
    g.erfassung = g.erfassung || { bloecke: [] };
    g.config.spielerListe.forEach((_, i) => {
      g.erfassung.bloecke[i] = [0, 1, 2, 3].map((s) => (dg < gespielt
        ? { wuerfe: [], overrides: [VOLLE(i, s), ABR(i, s)], done: true }
        : { wuerfe: [], overrides: [null, null], done: false }));
    });
  });
  return { wettkampf, games };
}

// Anzeige-Einstellungen der Tafel stehen AM WETTKAMPF (nicht am Gerät) — so kommen sie auf
// jedes anzeigende Gerät. Fürs Testen hier draufgesetzt.
function mitEinstellung(daten, beamer) {
  return { ...daten, wettkampf: { ...daten.wettkampf, beamer } };
}

// Die Kopfzeilen EINER Tabelle (0 = links/Heim, 1 = rechts/Gast) als Zellen je Zeile.
function kopfzeilen(html, nr) {
  const tabelle = html.split('<table class="bm-table')[nr + 1];
  const kopf = tabelle.slice(tabelle.indexOf('<thead>'), tabelle.indexOf('</thead>'));
  return kopf.split('<tr>').slice(1).map((zeile) =>
    [...zeile.matchAll(/<th class="([a-z0-9 -]+)"[^>]*>([^<]*)</g)]
      .map((m) => ({ klasse: m[1], text: m[2].trim() })));
}

// Die Überschriften einer Tabelle (Bahnen · Gesamt) — die erste Kopfzeile.
function gruppen(html, nr) {
  return kopfzeilen(html, nr)[0]
    .filter((z) => z.klasse.startsWith('bm-grp-h') || z.klasse.startsWith('bm-wert-h'))
    .map((z) => z.text);
}

// Die Gassen-/Satz-Nummern unter der Überschrift — die zweite Kopfzeile.
function nummern(html, nr) {
  return (kopfzeilen(html, nr)[1] || []).filter((z) => z.klasse === 'bm-nr-h').map((z) => z.text);
}

test('Beamer-Tafel: beide Mannschaften und jede Spielerzeile', () => {
  const html = buildBeamerHtml(mkWettkampf());
  assert.ok(html.includes('VOK Osnabrück 1'));
  assert.ok(html.includes('SV Union Lohne 1'));
  // Der Wettkampfname steht nirgends mehr von selbst — nur noch als frei gesetzte Überschrift.
  assert.ok(!html.includes('Testpokal'), 'Wettkampfname taucht ungefragt auf');
  assert.equal((html.match(/class="bm-row/g) || []).length, 8, '2 Mannschaften à 4 Spieler');
});

test('Standard sind die GASSEN: je Bahn genau EINE Zahl, das Bahnergebnis', () => {
  const html = buildBeamerHtml(mkWettkampf());
  // EINE Überschrift über dem ganzen Block, darunter nur die Nummern (die brechen nie um).
  assert.deepEqual(gruppen(html, 0), ['Bahnen', 'Gesamt']);
  assert.deepEqual(nummern(html, 0), ['2', '3', '4', '5']);
  // Nur EINE V/A-Gruppe je Tabelle: die des Gesamtergebnisses. Je Gasse steht die Summe.
  assert.equal((html.split('<table class="bm-table')[1].match(/bm-v-h/g) || []).length, 1);
  assert.ok(html.includes(`bm-wert">${SATZ(0, 0)}<`), 'Summe der Gasse fehlt');
  // Die Aufteilung der GASSE ist bewusst weg — sie hat die Tafel zugestellt.
  assert.ok(!html.includes(`bm-v">${VOLLE(0, 0)}<`), 'Volle steht wieder je Gasse');
  assert.ok(!html.includes(`bm-a">${ABR(0, 0)}<`), 'Abräumen steht wieder je Gasse');
});

test('Gesamt-Gruppe: Volle, Abräumen und Gesamtsumme je Spieler', () => {
  const html = buildBeamerHtml(mkWettkampf());
  const volle0 = [0, 1, 2, 3].reduce((s, st) => s + VOLLE(0, st), 0);
  const abr0 = [0, 1, 2, 3].reduce((s, st) => s + ABR(0, st), 0);
  assert.ok(html.includes(`bm-v is-ges">${volle0}<`), 'Volle gesamt');
  assert.ok(html.includes(`bm-a is-ges">${abr0}<`), 'Abräumen gesamt');
  assert.ok(html.includes(`bm-wert is-ges">${volle0 + abr0}<`), 'Gesamtsumme');
});

test('Umschalten auf SÄTZE: der Block heißt Sätze und zählt 1..n', () => {
  const html = buildBeamerHtml(mitEinstellung(mkWettkampf(), { spalten: 'saetze' }));
  assert.deepEqual(gruppen(html, 0), ['Sätze', 'Gesamt']);
  assert.deepEqual(nummern(html, 0), ['1', '2', '3', '4']);
});

test('Beim Gast ist alles gespiegelt — außer den BAHNEN, die bleiben aufsteigend', () => {
  // Die Gasse 4 ist auf beiden Seiten dieselbe Bahn im Saal: eine rückwärts laufende
  // Bahnreihe wäre falsch zu lesen. Sätze sind dagegen eine Reihenfolge und drehen mit.
  const bahnen = buildBeamerHtml(mkWettkampf());
  assert.deepEqual(nummern(bahnen, 0), ['2', '3', '4', '5']);
  assert.deepEqual(nummern(bahnen, 1), ['2', '3', '4', '5'], 'Bahnen laufen rechts rückwärts');
  const saetze = buildBeamerHtml(mitEinstellung(mkWettkampf(), { spalten: 'saetze' }));
  assert.deepEqual(nummern(saetze, 0), ['1', '2', '3', '4']);
  assert.deepEqual(nummern(saetze, 1), ['4', '3', '2', '1'], 'Sätze sind rechts nicht gespiegelt');
});

test('Gassen- und Satz-Ansicht zeigen dieselben Werte, nur anders sortiert', () => {
  const daten = mkWettkampf();
  const werte = (modus) => [...buildBeamerHtml(mitEinstellung(daten, { spalten: modus }))
    .matchAll(/bm-wert">(\d+)</g)].map((m) => Number(m[1])).sort((a, b) => a - b);
  assert.deepEqual(werte('bahnen'), werte('saetze'));
});

test('Ergebnisse zur Mitte: die rechte Tabelle ist gespiegelt (Name außen)', () => {
  const html = buildBeamerHtml(mkWettkampf());
  const links = kopfzeilen(html, 0)[0].map((z) => z.klasse);
  const rechts = kopfzeilen(html, 1)[0].map((z) => z.klasse);
  // Links: Name außen, danach der Gassen-Block, innen Gesamt und EWP.
  assert.deepEqual(links, ['bm-nm-h', 'bm-grp-h is-gassen', 'bm-grp-h is-ges', 'bm-ewp-h']);
  // Rechts: exakt gespiegelt — EWP und Gesamt zeigen zur Mitte, der Name steht außen.
  assert.deepEqual(rechts, ['bm-ewp-h', 'bm-grp-h is-ges', 'bm-grp-h is-gassen', 'bm-nm-h']);
  assert.deepEqual(gruppen(html, 1), ['Gesamt', 'Bahnen']);
});

test('Die Gesamt-Gruppe selbst ist gespiegelt: links V·A·Ges, rechts Ges·A·V', () => {
  const html = buildBeamerHtml(mkWettkampf());
  const zweite = (nr) => kopfzeilen(html, nr)[1].map((z) => z.klasse).filter((k) => k.endsWith('is-ges'));
  // Zweite Kopfzeile: nur die Gesamt-Gruppe hat eine, und sie läuft rechts rückwärts —
  // so liegt die Gesamtsumme beider Mannschaften symmetrisch zur Bildmitte.
  assert.deepEqual(zweite(0), ['bm-v-h is-ges', 'bm-a-h is-ges', 'bm-g-h is-ges']);
  assert.deepEqual(zweite(1), ['bm-g-h is-ges', 'bm-a-h is-ges', 'bm-v-h is-ges']);
  // Auch die Werte einer Zeile drehen mit: rechts kommt die Summe VOR Volle und Abräumen.
  const zellen = (nr) => [...html.split('<table class="bm-table')[nr + 1]
    .matchAll(/<td class="(bm-[a-z]+) is-ges"/g)].map((m) => m[1]);
  assert.deepEqual(zellen(0).slice(0, 3), ['bm-v', 'bm-a', 'bm-wert']);
  assert.deepEqual(zellen(1).slice(0, 3), ['bm-wert', 'bm-a', 'bm-v']);
});

test('Weder Durchgangs-Spalte noch Bestenliste', () => {
  const html = buildBeamerHtml(mkWettkampf({ gespielt: 1 }));
  assert.ok(!html.includes('bm-dg'), 'die Durchgangs-Anzeige ist noch da');
  assert.ok(!html.includes('Beste Einzelergebnisse'), 'die Bestenliste ist noch da');
  assert.ok(!html.includes('bm-foot'), 'die Fußleiste ist noch da');
});

test('Fußzeile: je Gasse der Durchschnitt, beim Gesamt die Mannschaftssumme', () => {
  const { wettkampf, games } = mkWettkampf();
  const html = buildBeamerHtml({ wettkampf, games });
  const gesamtEinesSpielers = (i) => [0, 1, 2, 3].reduce((s, st) => s + SATZ(i, st), 0);
  const summeTeam = (teamId) => games.reduce((s, g) => s + g.config.spielerListe
    .reduce((t, sp, i) => t + (sp.mannschaftId === teamId ? gesamtEinesSpielers(i) : 0), 0), 0);
  // Gesamt bleibt die SUMME der Mannschaft.
  const gesamt = [...html.matchAll(/bm-wert bm-sum is-ges">(\d+)</g)].map((m) => Number(m[1]));
  assert.deepEqual(gesamt, [summeTeam('A'), summeTeam('B')]);
  // Je Gasse steht der DURCHSCHNITT derer, die dort gespielt haben: im Fixture spielen auf
  // jeder Gasse genau zwei Spieler je einen Satz -> Mittel ihrer beiden Satzergebnisse.
  const schnitte = [...html.matchAll(/bm-wert bm-schnitt"><span class="bm-schnitt-z">.<\/span>(\d+)</g)]
    .map((m) => Number(m[1]));
  assert.equal(schnitte.length, 8, 'vier Gassen-Durchschnitte je Mannschaft');
  const spielerGesamt = gesamtEinesSpielers(0);
  schnitte.forEach((v) => {
    assert.ok(v < spielerGesamt, `Durchschnitt ${v} sieht aus wie eine Summe`);
    assert.ok(v > 100, `Durchschnitt ${v} ist unplausibel klein`);
  });
});

test('Auch bei sechs Gassen: je Gasse die Summe, Aufteilung nur beim Gesamt', () => {
  const html = buildBeamerHtml(mkWettkampf({ bahnen: [1, 2, 3, 4, 5, 6] }));
  assert.deepEqual(gruppen(html, 0), ['Bahnen', 'Gesamt']);
  assert.deepEqual(nummern(html, 0), ['1', '2', '3', '4', '5', '6']);
  // Nur noch EINE V/A-Gruppe je Tabelle: die des Gesamtergebnisses.
  assert.equal((html.split('<table class="bm-table')[1].match(/bm-v-h/g) || []).length, 1);
  assert.ok(html.includes('bm-v is-ges'), 'Volle gesamt fehlt');
});

test('Ohne Abräumen (Bohle): eine Spalte je Gasse, keine V/A-Aufteilung', () => {
  const html = buildBeamerHtml(mkWettkampf({ preset: 'bohle', teilsaetze: ['volle', 'volle'] }));
  assert.ok(!html.includes('bm-v-h'), 'V/A-Kopfzeile trotz reinem Volle-Programm');
  assert.ok(!html.includes('bm-ewp-h'), 'EWP-Spalte ohne hinterlegte Wertung');
  assert.deepEqual(gruppen(html, 0), ['Bahnen', 'Gesamt']);
  assert.deepEqual(nummern(html, 0), ['2', '3', '4', '5']);
  assert.ok(html.includes('>Kegel<'), 'Kopf zeigt den Kegelstand');
});

test('Schere: EWP-Spalte und Spielpunkte im Kopf', () => {
  const html = buildBeamerHtml(mkWettkampf());
  assert.ok(html.includes('bm-ewp-h'), 'EWP-Spalte');
  assert.ok(html.includes('>Spielpunkte<'), 'Kopf zeigt Spielpunkte');
  const pts = [...html.matchAll(/bm-score-v[^>]*>([\d,]+)</g)].map((m) => Number(m[1].replace(',', '.')));
  assert.equal(pts.length, 2);
  assert.equal(pts.reduce((a, b) => a + b, 0), 3, 'zwei Gesamtholz- plus ein EWP-Punkt');
});

test('Heller Modus: die Tafel trägt die Kennzeichnung, dunkel ist der Standard', () => {
  assert.ok(buildBeamerHtml(mitEinstellung(mkWettkampf(), { thema: 'hell' })).includes('bm-page is-hell'));
  assert.ok(!buildBeamerHtml(mkWettkampf()).includes('is-hell'), 'dunkel ist nicht der Standard');
});

test('Noch nicht gespielte Spieler stehen als leere Zeile da', () => {
  const html = buildBeamerHtml(mkWettkampf({ gespielt: 1 }));
  assert.ok(html.includes('bm-row is-offen'), 'Zeile für den offenen Durchgang');
});

test('Ohne Daten Warte-Hinweis, mit einer Mannschaft ein Hinweis', () => {
  assert.ok(buildBeamerHtml(null).includes('Warte'));
  assert.ok(buildBeamerHtml({}).includes('Warte'));
  const eins = buildBeamerHtml({ wettkampf: { mannschaften: [{ id: 'A', name: 'Allein' }] }, games: [] });
  assert.ok(eins.includes('zwei Mannschaften'));
});

test('beamerOptionen: unbekannte Werte fallen auf die Standards zurück', () => {
  assert.deepEqual(beamerOptionen(null), { spalten: 'bahnen', thema: 'dunkel', titel: '' });
  assert.deepEqual(beamerOptionen({ beamer: { spalten: 'quatsch', thema: 'bunt', titel: 42 } }),
    { spalten: 'bahnen', thema: 'dunkel', titel: '' });
  assert.deepEqual(beamerOptionen({ beamer: { spalten: 'saetze', thema: 'hell', titel: '  Stadtmeisterschaft ' } }),
    { spalten: 'saetze', thema: 'hell', titel: 'Stadtmeisterschaft' });
});

test('Überschrift: nur die eingestellte — ohne Eingabe gar keine', () => {
  // Leeres Feld heißt: die Zeile fällt weg (kein Rückfall auf den Wettkampfnamen).
  const ohne = buildBeamerHtml(mkWettkampf());
  assert.ok(!ohne.includes('bm-titel'), 'ohne Eingabe steht trotzdem eine Überschrift da');
  assert.ok(!ohne.includes('Testpokal'), 'der Wettkampfname taucht irgendwo auf');
  const eigen = buildBeamerHtml(mitEinstellung(mkWettkampf(), { titel: 'Stadtpokal 2026' }));
  assert.ok(eigen.includes('<h1 class="bm-titel">Stadtpokal 2026</h1>'), 'eigene Überschrift fehlt');
});

test('Kopfband ohne Wettkampf-Satz, Fußleiste mit Datum und Spielort', () => {
  const html = buildBeamerHtml(mkWettkampf());
  // Der Satz über den Stand der Durchgänge ist weg (welcher läuft, zeigt die Tabelle).
  assert.ok(!html.includes('bm-wk'), 'die Wettkampf-Zeile steht noch im Kopfband');
  assert.ok(!html.includes('Durchgang 1 von'), 'der Durchgangs-Satz steht noch da');
  // Unten links das Datum, unten rechts der Spielort.
  assert.ok(html.includes('<span class="bm-fuss-l">15.09.2026</span>'), 'Datum unten links fehlt');
  assert.ok(html.includes('<span class="bm-fuss-r">Halle</span>'), 'Spielort unten rechts fehlt');
});

test('beamerUrl nutzt den read-only Zuschauer-Code und bleibt kurz', () => {
  // In Node gibt es kein location — die Funktion baut die URL daraus, deshalb hier ein Stub.
  globalThis.location = { origin: 'https://example.org', pathname: '/pins-scorer/' };
  const url = beamerUrl({ zuschauerCode: 'AB CD', code: 'GEHEIM' });
  assert.equal(url, 'https://example.org/pins-scorer/#/beamer?code=AB%20CD');
  assert.ok(!url.includes('GEHEIM'), 'der Eingabe-Code darf nicht in der Beamer-URL landen');
  // Spalten und Thema gehören NICHT mehr in die URL — die stellt das Gerät am Beamer
  // an der Bedienleiste der Tafel ein (und merkt sie sich).
  assert.ok(!url.includes('spalten') && !url.includes('thema'), 'Einstellungen hängen noch in der URL');
  delete globalThis.location;
});
