import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseWurfdatei, spielerAusDateiname, findeSpieler, ordneSaetze, baueBlock,
  pruefeSpalte, baueImportPlan, schwere, istImportierbar, importierbareSaetze, zeitSekunden,
  vergleichsname,
} from '../js/logic/wurf-csv-import.js';

// Ein kleines Programm in der Form der echten Dateien: 2 Sätze à 6 Würfe,
// Teilsätze 3× Volle + 3× Kranz-Abräumen (wie Schere, nur kurz genug zum Lesen).
const config = {
  spielerListe: [{ name: 'Arne Schierbaum' }, { name: 'Malte Schierbaum' }, { name: 'Rene Pütz' }],
  saetze: 2,
  bahnen: 4,
  ersteBahn: 2,
  wuerfeProSatz: 6,
  teilsaetze: [{ modus: 'volle', wuerfe: 3 }, { modus: 'kranz-abraeumen', wuerfe: 3 }],
  // Spieler 0 spielt Bahn 3 dann 4, Spieler 1 Bahn 2 dann 3, Spieler 2 pendelt (Duo).
  bahnplan: [[3, 4], [2, 3], [5, 5]],
};

// Eine Datei im Anlagen-Format bauen: je Gruppe ein Spalten-Tripel.
// gruppen = [{ label, wuerfe: [[holz, 'bild', 'zeit'], …], summe }]
function csv(gruppen) {
  const kopf = ['Wurf'];
  gruppen.forEach((g) => kopf.push(g.label, 'Wurfbild ' + g.label, 'Zeit ' + g.label));
  const hoch = Math.max(...gruppen.map((g) => g.wuerfe.length));
  const zeilen = [kopf.join(';')];
  for (let i = 0; i < hoch; i += 1) {
    const r = [String(i + 1)];
    gruppen.forEach((g) => {
      const w = g.wuerfe[i];
      if (!w) r.push('', '', ''); else r.push(String(w[0]), w[1], w[2] || '');
    });
    zeilen.push(r.join(';'));
  }
  const s = ['Summe'];
  gruppen.forEach((g) => s.push(g.summe == null ? '' : String(g.summe), '', ''));
  zeilen.push(s.join(';'));
  return zeilen.join('\r\n') + '\r\n';
}

// Ein vollständiger, in sich stimmiger Satz: 3 Volle + 3 Kranz-Abräumen.
//   Volle: 9, 7, 8
//   Räumer: 9 (alles) · 7 (es bleiben 5+8) · 2 (5+8 fallen -> abgeräumt)
const SATZ_OK = [
  [9, '1 2 3 4 5 6 7 8 9', '00:18:10'],
  [7, '1 2 3 4 6 7 9', '00:18:28'],
  [8, '1 2 3 4 5 6 8 9', '00:18:45'],
  [9, '1 2 3 4 5 6 7 8 9', '00:19:02'],
  [7, '1 2 3 4 6 7 9', '00:19:20'],
  [2, '5 8', '00:19:38'],
];
const SATZ_OK_HOLZ = 42;

test('parseWurfdatei: Warmwerfen und Bahn-Spalten werden als Gruppen erkannt', () => {
  const text = csv([
    { label: 'Warmwerfen', wuerfe: [[9, '1 2 3 4 5 6 7 8 9', '00:09:00'], [3, '1 5 9', '00:09:20']], summe: 12 },
    { label: 'Bahn 3', wuerfe: SATZ_OK, summe: SATZ_OK_HOLZ },
  ]);
  const { spalten, fehler } = parseWurfdatei(text);
  assert.deepEqual(fehler, []);
  assert.equal(spalten.length, 2);
  assert.equal(spalten[0].warm, true);
  assert.equal(spalten[0].bahn, null);
  assert.equal(spalten[0].wuerfe.length, 2);
  assert.equal(spalten[0].summe, 12);
  assert.equal(spalten[1].warm, false);
  assert.equal(spalten[1].bahn, 3);
  assert.equal(spalten[1].wuerfe.length, 6);
  assert.equal(spalten[1].summe, SATZ_OK_HOLZ);
  assert.deepEqual(spalten[1].wuerfe[1], { nr: 2, holz: 7, pins: [1, 2, 3, 4, 6, 7, 9], zeit: '00:18:28' });
});

test('parseWurfdatei: BOM, Quoting und fehlende Wurfbild-Spalte stören nicht', () => {
  const text = '\uFEFF"Wurf";"Bahn 3"\r\n1;9\r\n2;7\r\nSumme;16\r\n';
  const { spalten, fehler } = parseWurfdatei(text);
  assert.deepEqual(fehler, []);
  assert.equal(spalten.length, 1);
  assert.deepEqual(spalten[0].wuerfe.map((w) => w.holz), [9, 7]);
  assert.deepEqual(spalten[0].wuerfe[0].pins, []); // kein Bild erfasst
  assert.equal(spalten[0].summe, 16);
});

test('parseWurfdatei: eine Datei ohne Wurf-Spalte wird benannt, nicht stillschweigend gelesen', () => {
  const { fehler } = parseWurfdatei('Name;Punkte\r\nAnna;120\r\n');
  assert.ok(fehler.some((f) => /Wurf/.test(f)), 'Hinweis auf die fehlende Wurf-Spalte erwartet');
});

test('spielerAusDateiname: Unterstriche sind Leerzeichen, Zählendung fällt weg', () => {
  assert.equal(spielerAusDateiname('Arne_Schierbaum.csv'), 'Arne Schierbaum');
  assert.equal(spielerAusDateiname('C:\\Users\\x\\Downloads\\Rene_Puetz (1).csv'), 'Rene Puetz');
});

test('findeSpieler: exakt, umgedreht, Umlaut-tolerant — und mehrdeutig lieber nicht', () => {
  const liste = config.spielerListe;
  assert.equal(findeSpieler('Arne Schierbaum', liste), 0);
  assert.equal(findeSpieler('Schierbaum, Malte', liste), 1);
  assert.equal(findeSpieler('Rene Puetz', liste), 2);          // Puetz <-> Pütz
  assert.equal(vergleichsname('Christoph Hoesel'), vergleichsname('Christoph Hösel'));
  assert.equal(vergleichsname('Schaefer'), vergleichsname('Schäfer'));
  assert.equal(findeSpieler('Schierbaum', liste), -1);          // zwei Brüder -> keine Wahl
  assert.equal(findeSpieler('Jemand Fremdes', liste), -1);
  // Ein bereits belegter Slot zählt nicht mehr mit.
  assert.equal(findeSpieler('Arne Schierbaum', liste, [0]), -1);
});

test('ordneSaetze: Bahn-Spalten gehen über den Bahnplan auf die Sätze', () => {
  const spalten = [
    { label: 'Warmwerfen', warm: true, bahn: null },
    { label: 'Bahn 3', warm: false, bahn: 3 },
    { label: 'Bahn 4', warm: false, bahn: 4 },
  ];
  assert.deepEqual(ordneSaetze(spalten, config, 0), [null, 0, 1]);
  // Spieler 1 spielt Bahn 2 dann 3 — die 4 kommt bei ihm nicht vor.
  assert.deepEqual(ordneSaetze(spalten, config, 1), [null, 1, null]);
});

test('ordneSaetze: eine doppelt gespielte Bahn (Duo) füllt die Sätze in Spaltenreihenfolge', () => {
  const spalten = [
    { label: 'Bahn 5', warm: false, bahn: 5 },
    { label: 'Bahn 5', warm: false, bahn: 5 },
  ];
  assert.deepEqual(ordneSaetze(spalten, config, 2), [0, 1]);
});

test('baueBlock: Holz und Kegelbild je Wurf, Overrides je Teilsatz, done am Soll', () => {
  const wuerfe = SATZ_OK.map((w, i) => ({ nr: i + 1, holz: w[0], pins: w[1].split(' ').map(Number), zeit: w[2] }));
  const blk = baueBlock(wuerfe, config);
  assert.deepEqual(blk.wuerfe, [9, 7, 8, 9, 7, 2]);
  assert.deepEqual(blk.kegel[5], [5, 8]);
  assert.deepEqual(blk.koenig, [false, false, false, false, false, false]);
  assert.deepEqual(blk.overrides, [null, null]);
  assert.equal(blk.done, true);
  // Ein angefangener Satz bleibt offen.
  assert.equal(baueBlock(wuerfe.slice(0, 4), config).done, false);
});

test('pruefeSpalte: ein stimmiger Satz ergibt keinen Befund', () => {
  const { spalten } = parseWurfdatei(csv([{ label: 'Bahn 3', wuerfe: SATZ_OK, summe: SATZ_OK_HOLZ }]));
  assert.deepEqual(pruefeSpalte(spalten[0], config, 0), []);
});

test('pruefeSpalte: Holz und Kegelbild müssen zusammenpassen', () => {
  const kaputt = SATZ_OK.slice();
  kaputt[1] = [7, '1 2 3 4 6 7', '00:18:28']; // 7 Holz, aber nur 6 Kegel
  const { spalten } = parseWurfdatei(csv([{ label: 'Bahn 3', wuerfe: kaputt, summe: SATZ_OK_HOLZ }]));
  const b = pruefeSpalte(spalten[0], config, 0);
  assert.equal(schwere(b), 'fehler');
  assert.ok(b.some((x) => /Wurf 2.*6 Kegel/.test(x.text)), JSON.stringify(b));
});

test('pruefeSpalte: Summenzeile gegen die Einzelwürfe — Warnung, kein Fehler', () => {
  const { spalten } = parseWurfdatei(csv([{ label: 'Bahn 3', wuerfe: SATZ_OK, summe: 999 }]));
  const b = pruefeSpalte(spalten[0], config, 0);
  assert.equal(schwere(b), 'warnung');
  assert.ok(b.some((x) => /999/.test(x.text) && /42/.test(x.text)));
});

test('pruefeSpalte: rückwärts laufende Zeiten fallen auf', () => {
  const kaputt = SATZ_OK.map((w) => w.slice());
  kaputt[2][2] = '00:18:01'; // vor Wurf 2
  const { spalten } = parseWurfdatei(csv([{ label: 'Bahn 3', wuerfe: kaputt, summe: SATZ_OK_HOLZ }]));
  const b = pruefeSpalte(spalten[0], config, 0);
  assert.ok(b.some((x) => /zeitlich vor/.test(x.text)), JSON.stringify(b));
});

test('pruefeSpalte: im Kranz-Abräumen darf kein schon liegender Kegel wieder fallen', () => {
  // Räumer: 9 (Reset) · 7 (5+8 bleiben stehen) · 1 auf die „6" — die lag längst.
  const kaputt = SATZ_OK.slice(0, 5).concat([[1, '6', '00:19:38']]);
  const { spalten } = parseWurfdatei(csv([{ label: 'Bahn 3', wuerfe: kaputt, summe: 41 }]));
  const b = pruefeSpalte(spalten[0], config, 0);
  assert.equal(schwere(b), 'warnung'); // Holz stimmt, nur das Bild kann nicht sein
  assert.ok(b.some((x) => /Wurf 6/.test(x.text) && /Kegel 6/.test(x.text)), JSON.stringify(b));
});

test('pruefeSpalte: zu wenige Würfe = Hinweis, zu viele = Fehler', () => {
  const kurz = parseWurfdatei(csv([{ label: 'Bahn 3', wuerfe: SATZ_OK.slice(0, 4), summe: 33 }])).spalten[0];
  const bKurz = pruefeSpalte(kurz, config, 0);
  assert.equal(schwere(bKurz), 'hinweis');
  assert.ok(bKurz.some((x) => /4 von 6/.test(x.text)));

  const lang = parseWurfdatei(csv([{ label: 'Bahn 3', wuerfe: SATZ_OK.concat([[9, '1 2 3 4 5 6 7 8 9', '00:19:55']]), summe: 51 }])).spalten[0];
  assert.equal(schwere(pruefeSpalte(lang, config, 0)), 'fehler');
});

test('zeitSekunden: hh:mm:ss, sonst null', () => {
  assert.equal(zeitSekunden('01:20:19'), 4819);
  assert.equal(zeitSekunden(''), null);
  assert.equal(zeitSekunden('20:19'), null);
});

// ── Gesamtplan ───────────────────────────────────────────────────────────────

const spiel = (bloecke = []) => ({
  id: 'g1', config, erfassung: { aktiverSpieler: 0, aktiverSatz: 0, bloecke },
});

const dateiArne = () => ({
  dateiname: 'Arne_Schierbaum.csv',
  text: csv([
    { label: 'Warmwerfen', wuerfe: [[9, '1 2 3 4 5 6 7 8 9', '00:09:00']], summe: 9 },
    { label: 'Bahn 3', wuerfe: SATZ_OK, summe: SATZ_OK_HOLZ },
    { label: 'Bahn 4', wuerfe: SATZ_OK, summe: SATZ_OK_HOLZ },
  ]),
});

test('baueImportPlan: Datei -> Spieler, Bahn -> Satz, Warmwerfen bleibt draußen', () => {
  const [e] = baueImportPlan([dateiArne()], spiel());
  assert.equal(e.spielerName, 'Arne Schierbaum');
  assert.equal(e.spielerIndex, 0);
  assert.equal(e.warm, 1, 'die Einspielwürfe werden gezählt, nicht importiert');
  assert.deepEqual(e.saetze.map((s) => [s.satz, s.bahn, s.wuerfe, s.holz]),
    [[0, 3, 6, SATZ_OK_HOLZ], [1, 4, 6, SATZ_OK_HOLZ]]);
  assert.equal(schwere(e.befunde), 'ok');
  assert.equal(istImportierbar(e), true);
  assert.equal(importierbareSaetze(e).length, 2);
  // Die Blöcke sind die der App — inkl. Kegelbild je Wurf.
  assert.deepEqual(e.saetze[0].block.wuerfe, [9, 7, 8, 9, 7, 2]);
  assert.deepEqual(e.saetze[0].block.kegel[5], [5, 8]);
});

test('baueImportPlan: ein Name ohne eindeutigen Slot wird zur Hand-Zuordnung gemeldet', () => {
  const [e] = baueImportPlan([{ dateiname: 'Schierbaum.csv', text: dateiArne().text }], spiel());
  assert.equal(e.spielerIndex, -1);
  assert.equal(schwere(e.befunde), 'fehler');
  assert.equal(istImportierbar(e), false);

  // Mit Hand-Zuordnung geht dieselbe Datei durch.
  const [z] = baueImportPlan([{ dateiname: 'Schierbaum.csv', text: dateiArne().text }], spiel(), { 'Schierbaum.csv': 1 });
  assert.equal(z.spielerIndex, 1);
  // Spieler 1 spielt Bahn 2 und 3 — die Bahn-4-Spalte passt bei ihm nicht.
  assert.deepEqual(z.saetze.map((s) => s.satz), [1]);
  assert.ok(z.befunde.some((b) => /Bahn 4/.test(b.text)), JSON.stringify(z.befunde));
});

test('baueImportPlan: zwei Dateien nehmen sich nicht denselben Slot', () => {
  const plan = baueImportPlan([
    dateiArne(),
    { dateiname: 'Malte_Schierbaum.csv', text: dateiArne().text },
  ], spiel());
  assert.deepEqual(plan.map((e) => e.spielerIndex), [0, 1]);
});

test('baueImportPlan: vorhandene Würfe werden als „wird ersetzt" angekündigt', () => {
  const vorhanden = [[{
    wuerfe: [9, 9], kegel: [[1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 5, 6, 7, 8, 9]],
    koenig: [false, false], overrides: [null, null], done: false,
  }]];
  const [e] = baueImportPlan([dateiArne()], spiel(vorhanden));
  const satz0 = e.saetze.find((s) => s.satz === 0);
  assert.equal(satz0.ueberschreibt, true);
  assert.ok(satz0.befunde.some((b) => b.art === 'hinweis' && /bereits 2 Würfe/.test(b.text)));
  assert.equal(istImportierbar(e), true, 'Überschreiben blockiert den Import nicht');
});

test('baueImportPlan: ein Satz mit Fehler fällt aus, die übrigen Sätze derselben Datei nicht', () => {
  const kaputt = SATZ_OK.slice();
  kaputt[0] = [9, '1 2 3', '00:18:10']; // 9 Holz, 3 Kegel
  const datei = {
    dateiname: 'Arne_Schierbaum.csv',
    text: csv([
      { label: 'Bahn 3', wuerfe: kaputt, summe: SATZ_OK_HOLZ },
      { label: 'Bahn 4', wuerfe: SATZ_OK, summe: SATZ_OK_HOLZ },
    ]),
  };
  const [e] = baueImportPlan([datei], spiel());
  assert.equal(istImportierbar(e), true);
  assert.deepEqual(importierbareSaetze(e).map((s) => s.satz), [1]);
});

test('baueImportPlan: eine Datei mit nur Warmwerfen hat nichts zu importieren', () => {
  const datei = {
    dateiname: 'Arne_Schierbaum.csv',
    text: csv([{ label: 'Warmwerfen', wuerfe: SATZ_OK, summe: SATZ_OK_HOLZ }]),
  };
  const [e] = baueImportPlan([datei], spiel());
  assert.equal(schwere(e.befunde), 'fehler');
  assert.equal(istImportierbar(e), false);
  assert.equal(e.warm, 6);
});
