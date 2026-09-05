import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseSpielListe, parseSpielerInfo, erkenneLayout, pruefeSeite, ergebnisBlock, buildImportSpec,
  istWebImport, buildImportWettkampf, teilsatzPlan,
} from '../js/logic/sw-web-import.js';
import { MODUS_GESAMT } from '../js/logic/sportkegeln-presets.js';
import { istLizenzWettkampf } from '../js/logic/spieler-identitaet.js';
import { computeGameStats } from '../js/logic/statistik.js';
import { teilsatzRanges } from '../js/logic/teilsaetze.js';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

// Eine ECHTE GetSpielerInfo-Antwort vom KVN-Ergebnisdienst (Referenzpartie 328202).
// Ohne sie waere die Spaltenzuordnung geraten — mit ihr ist sie belegt.
const SCHERE = JSON.parse(readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), 'fixtures', 'sw-web-spielerinfo-schere.json'),
  'utf8',
));

// Ein Programm mit EINEM Teilsatz je Satz — so sieht ein Import aus, dessen Bericht nur das
// Satz-Holz nennt (teilsatzPlan -> MODUS_GESAMT).
const gesamtConfig = (spielerListe) => ({
  preset: 'schere',
  spieler: spielerListe.length,
  spielerListe,
  saetze: 4,
  wuerfeProSatz: 30,
  gesamtwuerfe: 120,
  teilsaetze: [{ modus: MODUS_GESAMT, wuerfe: 30 }],
  bahnListe: [1, 2, 3, 4],
  ersteBahn: 1,
  bahnplan: [[1, 2, 3, 4]],
});

// Schere-Programm der App (PRESETS.schere): 4 Sätze à 30 Würfe, Volle + Kranz-Abräumen.
const schereConfig = (spielerListe) => ({
  preset: 'schere',
  spieler: spielerListe.length,
  spielerListe,
  saetze: 4,
  wuerfeProSatz: 30,
  gesamtwuerfe: 120,
  teilsaetze: [{ modus: 'volle', wuerfe: 15 }, { modus: 'kranz-abraeumen', wuerfe: 15 }],
  bahnListe: [1, 2, 3, 4],
  ersteBahn: 1,
  bahnplan: [[1, 2, 3, 4]],
});

// Echte GetSpiel-Zeilen (kvn.sportwinner.de, 2026-09-04, Liga 4328).
const SPIEL_ROWS = [
  ['328202', '29.08.2026', '12:30', 'VOK Osnabrück 1', '0', '3', 'SKC Greste-Lage 1', '1', '0',
    'beendet', '', '0', 'Herren / 2. Bundesliga Nord / 1. Spieltag', ''],
  ['328209', '05.09.2026', '13:00', 'KV Blau Weiß Sontra 1', '0', '0', 'VOK Osnabrück 1', '0', '0',
    'offen', '', '0', 'Herren / 2. Bundesliga Nord / 2. Spieltag', ''],
];

test('parseSpielListe: echte Zeilen — Termin, Wertung und Status', () => {
  const list = parseSpielListe(SPIEL_ROWS);
  assert.equal(list.length, 2);
  assert.equal(list[0].idSpiel, '328202');
  assert.equal(list[0].heim, 'VOK Osnabrück 1');
  assert.equal(list[0].gast, 'SKC Greste-Lage 1');
  assert.equal(list[0].datum, '2026-08-29');
  assert.equal(list[0].termin, '29.08.2026 · 12:30');
  assert.equal(list[0].wertung, 0);
  assert.equal(list[0].liga, 'Herren / 2. Bundesliga Nord / 1. Spieltag');
  assert.equal(list[0].gespielt, true);
});

test('parseSpielListe: eine offene Partie gilt NICHT als gespielt', () => {
  // Der Fallstrick: [4]/[5] sind auch bei einer angesetzten Partie mit "0" belegt. Nur der
  // Status in [9] unterscheidet — eine Pruefung auf "ist eine Zahl" haette hier true gesagt.
  const list = parseSpielListe(SPIEL_ROWS);
  assert.equal(list[1].status, 'offen');
  assert.equal(list[1].gespielt, false);
  assert.equal(list[1].heimWert, 0, 'die 0 steht da — sie bedeutet nur nichts');
});

test('erkenneLayout: alle drei Layouts werden an ihren eigenen Summen erkannt', () => {
  const classic = [['Meier', 150, 160, 155, 145, 610, 3, 2, 0, 1, 600, 140, 150, 160, 150, 'Schulz']];
  const holz = [[1, 'Meier', 420, 190, 2, 610, 600, 3, 180, 420, 'Schulz']];
  assert.equal(erkenneLayout(SCHERE.rows), 'schere');
  assert.equal(erkenneLayout(classic), 'classic');
  assert.equal(erkenneLayout(holz), 'holz');
  assert.equal(erkenneLayout([]), null);
});

test('pruefeSeite: Holzspalte ist die Gegenprobe der Spaltenzuordnung', () => {
  assert.equal(pruefeSeite({ kegel: 610, volle: 420, abr: 190 }, 'summe'), true);
  assert.equal(pruefeSeite({ kegel: 610, volle: 420, abr: 180 }, 'summe'), false);
  assert.equal(pruefeSeite({ kegel: 610, saetze: [{ holz: 150 }, { holz: 160 }, { holz: 155 }, { holz: 145 }] }, 'satz'), true);
  // Ohne Kegelspalte kann nicht geprueft werden -> kein Fehlalarm.
  assert.equal(pruefeSeite({ kegel: null, volle: 1, abr: 1 }, 'summe'), true);
});

test('parseSpielerInfo: Classic-Layout, Gastsaetze stehen rueckwaerts', () => {
  const rows = [
    ['Meier', 150, 160, 155, 145, 610, 3, 2, 0, 1, 600, 140, 150, 160, 150, 'Schulz'],
  ];
  const b = parseSpielerInfo(rows);
  assert.equal(b.layout, 'classic');
  assert.equal(b.proSatz, false);
  assert.deepEqual(b.paare[0].gg.saetze.map((s) => s.holz), [150, 160, 155, 145]);
  // Gast: Spalten 14,13,12,11 -> Satz 1..4
  assert.deepEqual(b.paare[0].g.saetze.map((s) => s.holz), [150, 160, 150, 140]);
  assert.deepEqual(b.warnungen, []);
});

test('parseSpielerInfo: Summen-Layout mit einer Zeile je Satz wird als Satzdaten erkannt', () => {
  // Vier Zeilen je Paarung, Name nur in der ersten -> proSatz.
  const rows = [
    [1, 'Meier', 105, 45, 0, 150, 140, 1, 40, 100, 'Schulz'],
    [2, '', 110, 50, 1, 160, 150, 0, 45, 105, ''],
    [3, '', 100, 55, 0, 155, 160, 0, 50, 110, ''],
    [4, '', 95, 50, 2, 145, 150, 1, 45, 105, ''],
  ];
  const b = parseSpielerInfo(rows);
  assert.equal(b.layout, 'holz');
  assert.equal(b.proSatz, true);
  assert.equal(b.paare.length, 1);
  assert.deepEqual(b.paare[0].gg.saetze.map((s) => s.holz), [150, 160, 155, 145]);
  assert.deepEqual(b.paare[0].gg.saetze.map((s) => s.fehler), [0, 1, 0, 2]);
  assert.equal(b.paare[0].gg.kegel, 610);
  assert.deepEqual(b.warnungen, []);
});

test('parseSpielerInfo: nur Gesamtsummen -> saetze null und eine Warnung', () => {
  const rows = [[1, 'Meier', 420, 190, 3, 610, 600, 2, 180, 420, 'Schulz']];
  const b = parseSpielerInfo(rows);
  assert.equal(b.proSatz, false);
  assert.equal(b.paare[0].gg.saetze, null);
  assert.deepEqual(b.paare[0].gg.gesamt, { volle: 420, abr: 190, fehler: 3 });
  assert.match(b.warnungen[0], /nur Gesamtsummen/);
});

test('parseSpielerInfo: Zeilen, deren Summen unter keinem Layout aufgehen, werden abgelehnt', () => {
  // Volle+Abraeumen ergeben 151, die Holzspalte sagt 150 — unter keinem der drei Layouts
  // geht das auf. Statt still falsche Zahlen zu importieren, bricht der Import ab.
  assert.throws(
    () => parseSpielerInfo([[1, 'Meier', 105, 46, 0, 150, 140, 1, 40, 100, 'Schulz']]),
    /nicht lesbar/,
  );
});

test('parseSpielerInfo: eine einzelne krumme Zeile erzeugt eine Warnung, kein Abbruch', () => {
  // Drei saubere Zeilen legen das Layout fest; die vierte passt nicht und wird gemeldet.
  const rows = [
    [1, 'Meier', 105, 45, 0, 150, 140, 1, 40, 100, 'Schulz'],
    [1, 'Kruse', 110, 50, 1, 160, 150, 0, 45, 105, 'Berg'],
    [1, 'Wolf', 100, 55, 0, 155, 160, 0, 50, 110, 'Stein'],
    [1, 'Ernst', 100, 55, 0, 999, 160, 0, 50, 110, 'Klein'],
  ];
  const b = parseSpielerInfo(rows, { saetze: 1 });
  assert.equal(b.layout, 'holz');
  assert.equal(b.paare.length, 4);
  assert.equal(b.warnungen.filter((w) => /Spaltenzuordnung/.test(w)).length, 1);
  assert.match(b.warnungen.find((w) => /Spaltenzuordnung/.test(w)), /Ernst/);
});

test('echte Antwort (328202): Layout, Namen und Holz stimmen', () => {
  const b = parseSpielerInfo(SCHERE.rows, { saetze: 4 });
  assert.equal(b.layout, 'schere');
  assert.equal(b.typ, 'satz');
  assert.deepEqual(b.warnungen, [], 'die Gegenprobe muss auf echten Daten sauber durchgehen');
  assert.equal(b.paare.length, 6, 'die Mannschaftssumme am Ende ist keine Paarung');

  const arne = b.paare[1];
  assert.equal(arne.gg.name, 'Schierbaum, Arne');
  assert.deepEqual(arne.gg.saetze.map((x) => x.holz), [195, 230, 202, 194]);
  assert.equal(arne.gg.kegel, 821);
  // Der Gast steht im Bericht rueckwaerts (Spalten 13,12,11,10) — hier wieder in Satzfolge.
  assert.equal(arne.g.name, 'Hartnack, Nils');
  assert.deepEqual(arne.g.saetze.map((x) => x.holz), [189, 207, 197, 217]);
  assert.equal(arne.g.kegel, 810);

  // Gegenprobe an der Mannschaftssumme aus der letzten (verworfenen) Zeile.
  const summeGG = b.paare.reduce((n, p) => n + p.gg.kegel, 0);
  const summeG = b.paare.reduce((n, p) => n + p.g.kegel, 0);
  assert.equal(summeGG, 4860);
  assert.equal(summeG, 4903);
});

test('echte Antwort (328202): kompletter Import bis zur Statistik', () => {
  const bericht = parseSpielerInfo(SCHERE.rows, { saetze: 4 });
  const spec = buildImportSpec(
    { heim: 'VOK Osnabrück 1', gast: 'SKC Greste-Lage 1', datum: '2026-08-29', idSpiel: '328202' },
    bericht,
  );
  spec.preset = 'schere';
  const { games, nurSatzHolz } = buildImportWettkampf(spec, { playedLanes: [2, 3, 4, 5] });
  // Schere nennt nur das Satz-Holz -> je Satz EIN Teilsatz mit dem Satzergebnis, nichts geraten.
  assert.equal(nurSatzHolz, true);
  assert.deepEqual(games[0].config.teilsaetze, [{ modus: MODUS_GESAMT, wuerfe: 30 }]);

  const holzVon = {};
  games.forEach((g) => {
    const { players } = computeGameStats(g.config, g.erfassung.bloecke, teilsatzRanges(g.config));
    players.forEach((p) => { if (p.gesamt > 0) holzVon[p.name] = p.gesamt; });
  });
  assert.equal(holzVon['Schierbaum, Arne'], 821);
  assert.equal(holzVon['Hartnack, Nils'], 810);
  assert.equal(holzVon['Hösel, Christoph'], 842);
  assert.equal(Object.keys(holzVon).length, 12);
  assert.equal(Object.values(holzVon).reduce((a, b) => a + b, 0), 4860 + 4903);
});

test('echte Antwort (328202): Satzergebnisse exakt, Volle/Abraeumen bleibt leer', () => {
  const bericht = parseSpielerInfo(SCHERE.rows, { saetze: 4 });
  const spec = buildImportSpec({ heim: 'VOK Osnabrück 1', gast: 'SKC Greste-Lage 1' }, bericht);
  spec.preset = 'schere';
  const { games } = buildImportWettkampf(spec, { playedLanes: [2, 3, 4, 5] });

  let gefunden = null;
  games.forEach((g) => {
    const { players } = computeGameStats(g.config, g.erfassung.bloecke, teilsatzRanges(g.config));
    const p = players.find((x) => x.name === 'Schierbaum, Arne');
    if (p) gefunden = p;
  });
  assert.ok(gefunden, 'der eigene Spieler muss in einem Durchgang stehen');
  // Jeder Satz traegt genau sein Ergebnis aus dem Bericht — kein Teilsatz-Anteil daneben.
  assert.deepEqual(gefunden.saetze.map((s) => s.holz), [195, 230, 202, 194]);
  assert.deepEqual(gefunden.saetze.map((s) => s.teilsaetze.map((ts) => ts.holz)),
    [[195], [230], [202], [194]]);
  assert.equal(gefunden.gesamt, 821);
  assert.equal(gefunden.wurfCount, 120, 'die Wurfzahl ist Programm, keine Schaetzung');
  assert.equal(gefunden.schnittWurf, 821 / 120);
  // Das eigentliche Ziel: nichts, was der Bericht nicht hergibt.
  assert.equal(gefunden.abraeum, 0, 'ohne Volle/Abraeum-Trennung gibt es kein Abraeum-Holz');
  assert.equal(gefunden.neuner, 0);
  assert.equal(gefunden.vollChance, 0);
});

test('ergebnisBlock: Volle/Abraeumen landen exakt auf ihren Teilsaetzen', () => {
  const c = schereConfig([{ name: 'Meier', startBahn: 1 }]);
  const block = ergebnisBlock(c, { volle: 105, abr: 45 });
  assert.deepEqual(block.overrides, [105, 45]);
  assert.deepEqual(block.wuerfe, []);
  assert.equal(block.done, true);
});

test('ergebnisBlock: nur Satz-Holz -> genau ein Teilsatz mit dem Satzergebnis', () => {
  const c = gesamtConfig([{ name: 'Meier', startBahn: 1 }]);
  const block = ergebnisBlock(c, { holz: 151 });
  assert.deepEqual(block.overrides, [151], 'das Satzergebnis, unaufgeteilt');
});

test('ergebnisBlock: nur Satz-Holz auf mehrere Teilsaetze -> Abbruch statt Schaetzung', () => {
  // Der eigentliche Punkt dieser Aenderung: aus 151 Holz laesst sich nicht ableiten, wie viel
  // davon in der Volle und wie viel im Abraeumen fiel. Frueher wurde nach Wurfzahl verteilt;
  // jetzt ist das ein Fehler — teilsatzPlan() sorgt dafuer, dass er nie auftritt.
  const c = schereConfig([{ name: 'Meier', startBahn: 1 }]);
  assert.throws(() => ergebnisBlock(c, { holz: 151 }), /Teilsätze/);
});

test('teilsatzPlan: exakte Trennung nur, wenn der Bericht sie hergibt', () => {
  // Volle/Abraeumen bekannt + genau ein Teilsatz je Seite -> das Programm bleibt, wie es ist.
  assert.deepEqual(teilsatzPlan('schere', { nurHolz: false }), ['volle', 'kranz-abraeumen']);
  assert.deepEqual(teilsatzPlan('classic', { nurHolz: false }), ['volle', 'abraeumen']);
  // Nur Satz-Holz -> ein Teilsatz ueber den ganzen Satz.
  assert.deepEqual(teilsatzPlan('schere', { nurHolz: true }), [MODUS_GESAMT]);
  // Bohle hat ZWEI Volle-Teilsaetze: auf die liesse sich auch eine bekannte Volle-Summe nur
  // raten -> ebenfalls ein Teilsatz.
  assert.deepEqual(teilsatzPlan('bohle', { nurHolz: false }), [MODUS_GESAMT]);
});

test('importiertes Spiel: Holz stimmt, aber 9er/Raeumer/volles Bild bleiben leer', () => {
  const c = schereConfig([{ name: 'Meier', startBahn: 1 }]);
  const satzWerte = [
    { volle: 105, abr: 45 }, { volle: 110, abr: 50 },
    { volle: 100, abr: 55 }, { volle: 95, abr: 50 },
  ];
  const bloecke = [satzWerte.map((w) => ergebnisBlock(c, w))];
  const { players } = computeGameStats(c, bloecke, teilsatzRanges(c));
  const p = players[0];

  assert.equal(p.gesamt, 610, 'Gesamtholz exakt wie im Ergebnisdienst');
  assert.equal(p.bester, 160);
  assert.equal(p.schnittSatz, 152.5);
  assert.equal(p.wurfCount, 120, 'Override zaehlt als voller Teilsatz');
  // Der eigentliche Punkt: nichts wird erfunden.
  assert.equal(p.neuner, 0);
  assert.equal(p.fehl, 0);
  assert.equal(p.raeumer, 0);
  assert.equal(p.vollChance, 0, 'ohne vollChance blendet die 9er-Quote-Kachel aus');
  // Abraeum-Holz als Feinwertung bleibt trotzdem korrekt.
  assert.equal(p.abraeum, 200);
});

test('buildImportSpec: Paarungsreihenfolge wird zur Team-Position, kein sportwinner-Block', () => {
  const rows = [
    [1, 'Meier', 105, 45, 0, 150, 140, 1, 40, 100, 'Schulz'],
    [2, '', 110, 50, 1, 160, 150, 0, 45, 105, ''],
    [1, 'Kruse', 100, 50, 0, 150, 150, 0, 50, 100, 'Berg'],
    [2, '', 100, 50, 0, 150, 150, 0, 50, 100, ''],
  ];
  const bericht = parseSpielerInfo(rows, { saetze: 2 });
  const spec = buildImportSpec(
    { heim: 'VOK Osnabrück 1', gast: 'SKC Greste-Lage 1', datum: '2026-08-29', idSpiel: '328202' },
    bericht,
  );
  assert.equal(spec.name, 'VOK Osnabrück 1 – SKC Greste-Lage 1');
  assert.equal(spec.datum, '2026-08-29');
  assert.equal(spec.idSpiel, '328202');
  assert.equal(spec.spielerJeMannschaft, 2);
  assert.equal(spec.mannschaften[0].spieler[0].name, 'Meier');
  assert.equal(spec.mannschaften[1].spieler[1].name, 'Berg');
  assert.equal(spec.mannschaften[0].spieler[0].pass, null, 'Web-Weg kennt keine LizenzIDen');
  assert.equal(spec.sportwinner, undefined, 'kein Rueckschreib-Block -> kein Lizenz-Wettkampf');
  const key = `${spec.mannschaften[0].id}|1`;
  assert.equal(spec.namesByTeamPos[key], 'Meier');
  assert.deepEqual(spec.ergebnisse[key].saetze.map((s) => s.holz), [150, 160]);
});

test('istWebImport erkennt den Web-Import und nur ihn', () => {
  assert.equal(istWebImport({ quelle: 'sportwinner-web' }), true);
  assert.equal(istWebImport({ swWeb: { idSpiel: '328202' } }), true);
  assert.equal(istWebImport({ quelle: 'sportwinner' }), false);
  assert.equal(istWebImport({}), false);
  assert.equal(istWebImport(null), false);
});

test('Web-Import ist KEIN Lizenz-Wettkampf — die manuelle Markierung muss gelten', () => {
  // Der Ergebnisdienst liefert keine LizenzIDen. Wuerde istLizenzWettkampf hier true sagen,
  // verwuerfe resolveIchIndex die manuelle "Das bin ich"-Auswahl (nurLizenz) und das
  // importierte Spiel landete nie in der Konto-Statistik.
  assert.equal(istLizenzWettkampf({ quelle: 'sportwinner-web' }), false);
  assert.equal(istLizenzWettkampf({ quelle: 'sportwinner-web', swWeb: { idSpiel: '1' } }), false);
  // Der Bruecken-Import bleibt dagegen lizenzgefuehrt.
  assert.equal(istLizenzWettkampf({ quelle: 'sportwinner' }), true);
});

// Ein vollstaendiger Import: 6 gegen 6, Schere, vier Saetze je Spieler, eine Zeile je Bahn.
// Deckt die Kette parseSpielerInfo -> buildImportSpec -> buildImportWettkampf -> computeGameStats
// ab, also genau das, was die View beim Klick auf "Importieren" tut.
function berichtZeilen(paare) {
  const rows = [];
  paare.forEach(([ggName, ggSaetze, gName, gSaetze]) => {
    ggSaetze.forEach((gg, i) => {
      const g = gSaetze[i];
      rows.push([
        i + 1, i === 0 ? ggName : '', gg.volle, gg.abr, gg.fehler, gg.volle + gg.abr,
        g.volle + g.abr, g.fehler, g.abr, g.volle, i === 0 ? gName : '',
      ]);
    });
  });
  return rows;
}

test('kompletter Import: 6 gegen 6 im Paarkreuz, Holz je Spieler exakt', () => {
  const satz = (v, a, f) => ({ volle: v, abr: a, fehler: f });
  const paare = [];
  for (let i = 0; i < 6; i += 1) {
    paare.push([
      `Heim ${i + 1}`, [satz(100 + i, 40, 0), satz(105 + i, 45, 1), satz(95 + i, 50, 0), satz(110 + i, 35, 2)],
      `Gast ${i + 1}`, [satz(90 + i, 45, 1), satz(95 + i, 50, 0), satz(100 + i, 40, 1), satz(85 + i, 55, 0)],
    ]);
  }
  const bericht = parseSpielerInfo(berichtZeilen(paare), { saetze: 4 });
  assert.deepEqual(bericht.warnungen, [], 'die Kegelprobe muss durchgehen');
  assert.equal(bericht.proSatz, true);
  assert.equal(bericht.paare.length, 6);

  const spec = buildImportSpec(
    { heim: 'VOK Osnabrück 1', gast: 'SKC Greste-Lage 1', datum: '2026-08-29', idSpiel: '328202' },
    bericht,
  );
  spec.preset = 'schere';
  const { wettkampf, games, nurSatzHolz } = buildImportWettkampf(spec, { playedLanes: [2, 3, 4, 5] });

  assert.equal(nurSatzHolz, false, 'Volle/Abraeumen kommen exakt aus der Quelle');
  assert.deepEqual(games[0].config.teilsaetze,
    [{ modus: 'volle', wuerfe: 15 }, { modus: 'kranz-abraeumen', wuerfe: 15 }]);
  assert.equal(wettkampf.status, 'beendet');
  assert.equal(wettkampf.quelle, 'sportwinner-web');
  assert.equal(istWebImport(wettkampf), true);
  // 12 Spieler auf 4 Bahnen: je Durchgang treten 2 Paarungen an -> 3 Durchgaenge.
  assert.equal(games.length, 3, 'Paarkreuz auf 4 Bahnen: 3 Durchgaenge');
  assert.ok(games.every((g) => g.status === 'beendet'));

  // Kein Klarname im Wettkampf-Objekt selbst (das reist bei geteilten Wettkaempfen mit).
  assert.equal(JSON.stringify(wettkampf).includes('Heim 1'), false);

  // Jeder Spieler taucht genau einmal auf und traegt sein Holz aus der Quelle.
  const holzVon = {};
  games.forEach((g) => {
    const ranges = teilsatzRanges(g.config);
    const { players } = computeGameStats(g.config, g.erfassung.bloecke, ranges);
    players.forEach((p) => {
      if (p.gesamt > 0) holzVon[p.name] = (holzVon[p.name] || 0) + p.gesamt;
    });
  });
  paare.forEach(([ggName, ggSaetze, gName, gSaetze]) => {
    const summe = (ss) => ss.reduce((n, x) => n + x.volle + x.abr, 0);
    assert.equal(holzVon[ggName], summe(ggSaetze), `${ggName} Holz`);
    assert.equal(holzVon[gName], summe(gSaetze), `${gName} Holz`);
  });
  assert.equal(Object.keys(holzVon).length, 12, 'alle 12 Spieler haben ein Ergebnis');
});

test('kompletter Import: die eigene Position ist auffindbar und traegt keine Wurfdetails', () => {
  const satz = (v, a, f) => ({ volle: v, abr: a, fehler: f });
  const rows = berichtZeilen([[
    'Meier', [satz(105, 45, 0), satz(110, 50, 1), satz(100, 55, 0), satz(95, 50, 2)],
    'Schulz', [satz(100, 40, 1), satz(105, 45, 0), satz(110, 50, 1), satz(105, 45, 0)],
  ]]);
  const spec = buildImportSpec({ heim: 'A', gast: 'B', idSpiel: '1' }, parseSpielerInfo(rows));
  spec.preset = 'schere';
  const { games } = buildImportWettkampf(spec, { playedLanes: [1, 2, 3, 4] });

  const ichKey = `${spec.mannschaften[0].id}|1`;
  const g = games[0];
  const pos = g.config.spielerListe.findIndex((sp) => `${sp.mannschaftId}|${sp.teamPos}` === ichKey);
  assert.ok(pos >= 0, 'die eigene Position muss ueber mannschaftId|teamPos auffindbar sein');
  assert.equal(g.config.spielerListe[pos].name, 'Meier');

  const { players } = computeGameStats(g.config, g.erfassung.bloecke, teilsatzRanges(g.config));
  const p = players[pos];
  assert.equal(p.gesamt, 610);
  assert.equal(p.neuner, 0);
  assert.equal(p.vollChance, 0);
  assert.ok(g.erfassung.bloecke[pos].every((b) => b.wuerfe.length === 0),
    'keine erfundenen Einzelwuerfe');
});
