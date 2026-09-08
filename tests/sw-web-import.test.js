import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseSpielListe, parseSpielerInfo, erkenneLayout, pruefeSeite, ergebnisBlock, buildImportSpec,
  istWebImport, buildImportWettkampf, teilsatzPlan, bloeckeNachBahn, trageErgebnisseEin, blockLeer,
} from '../js/logic/sw-web-import.js';
import { MODUS_GESAMT } from '../js/logic/sportkegeln-presets.js';
import { istLizenzWettkampf } from '../js/logic/spieler-identitaet.js';
import { computeGameStats } from '../js/logic/statistik.js';
import { satzHolz, satzWurfCount } from '../js/logic/holz.js';
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

// Ein Programm mit EINEM Teilsatz je Satz. So sahen Web-Importe bis Version 1 aus, deren Bericht
// nur das Satz-Holz nennt; heute nur noch Altbestand (MODUS_GESAMT) — und ein Ein-Teilsatz-Fall
// fuer ergebnisBlock.
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
  // Schere nennt nur das Satz-Holz -> die Saetze tragen es selbst, die Teilsaetze bleiben leer.
  assert.equal(nurSatzHolz, true);
  // Der Wettkampf bekommt trotzdem das Programm SEINER Bahnart, nicht ein Ersatz-Programm.
  assert.deepEqual(games[0].config.teilsaetze,
    [{ modus: 'volle', wuerfe: 15 }, { modus: 'kranz-abraeumen', wuerfe: 15 }]);
  assert.ok(games.every((g) => g.erfassung.bloecke.every((satzArr) =>
    satzArr.every((b) => b.satzOverride != null && b.overrides.every((o) => o === null)))),
  'jeder Satz traegt sein Holz selbst, kein Teilsatz behauptet eine Aufteilung');

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
  // Die vier Spalten des Berichts sind BAHNEN, nicht Saetze: Spalte 1 ist die erste bespielte
  // Bahn (hier die 2). Arne startet auf Bahn 5, sein erster Satz ist also Spalte 4.
  const spaltenNachBahn = { 2: 195, 3: 230, 4: 202, 5: 194 };
  assert.deepEqual(gefunden.saetze.map((s) => s.bahn), [5, 2, 3, 4]);
  gefunden.saetze.forEach((s) => {
    assert.equal(s.holz, spaltenNachBahn[s.bahn], `Satz ${s.satz} auf Bahn ${s.bahn}`);
  });
  // Und eben NICHT stumpf in Berichtsreihenfolge — das war der Fehler.
  assert.notDeepEqual(gefunden.saetze.map((s) => s.holz), [195, 230, 202, 194]);
  // Die Teilsaetze der Bahnart sind da, aber leer: der Bericht sagt nichts ueber die Aufteilung.
  assert.deepEqual(gefunden.saetze.map((s) => s.teilsaetze.map((ts) => ts.holz)),
    [[0, 0], [0, 0], [0, 0], [0, 0]]);
  assert.ok(gefunden.saetze.every((s) => s.nurSatz));
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

test('ergebnisBlock: nur Satz-Holz -> Satzergebnis am Satz, Teilsaetze leer', () => {
  // Der Kern der Regel: aus 151 Holz laesst sich nicht ableiten, wie viel davon in der Volle und
  // wie viel im Abraeumen fiel. Also traegt der SATZ das Holz und kein Teilsatz behauptet etwas.
  const c = schereConfig([{ name: 'Meier', startBahn: 1 }]);
  const block = ergebnisBlock(c, { holz: 151 });
  assert.equal(block.satzOverride, 151);
  assert.deepEqual(block.overrides, [null, null]);
  assert.equal(satzHolz(block, teilsatzRanges(c)), 151);
  assert.equal(satzWurfCount(block, teilsatzRanges(c)), 30, 'der Satz zaehlt seine Soll-Wuerfe');
});

test('ergebnisBlock: Volle-Summe auf zwei Volle-Teilsaetze (Bohle) -> ebenfalls nur der Satz', () => {
  // Bohle hat ZWEI Volle-Teilsaetze. Auf die liesse sich auch eine BEKANNTE Volle-Summe nur
  // raten — also wandert auch hier das Satz-Holz auf den Satz.
  const c = { ...schereConfig([{ name: 'Meier', startBahn: 1 }]), preset: 'bohle',
    teilsaetze: [{ modus: 'volle', wuerfe: 15 }, { modus: 'volle', wuerfe: 15 }] };
  const block = ergebnisBlock(c, { volle: 105, abr: 45 });
  assert.equal(block.satzOverride, 150);
  assert.deepEqual(block.overrides, [null, null]);
});

test('teilsatzPlan: immer die Teilsaetze der Bahnart', () => {
  // Ein importiertes Spiel soll dieselbe Form haben wie ein selbst erfasstes — sonst ist es
  // weder vergleichbar noch von Hand zu vervollstaendigen.
  assert.deepEqual(teilsatzPlan('schere'), ['volle', 'kranz-abraeumen']);
  assert.deepEqual(teilsatzPlan('classic'), ['volle', 'abraeumen']);
  assert.deepEqual(teilsatzPlan('bohle'), ['volle', 'volle']);
  assert.throws(() => teilsatzPlan('kegelbahn'), /Unbekannte Bahnart/);
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

test('mehr bespielte Bahnen als Saetze: Berichtsreihenfolge gilt als Spielreihenfolge', () => {
  // Sportwinner fuehrt je Spieler vier Bahn-Slots. Laufen die vier Saetze ueber sechs Bahnen,
  // sagt der Bericht nicht, welche vier gemeint sind — dann darf nicht umsortiert werden.
  const bericht = parseSpielerInfo(SCHERE.rows, { saetze: 4 });
  const spec = buildImportSpec({ heim: 'VOK Osnabrück 1', gast: 'SKC Greste-Lage 1' }, bericht);
  spec.preset = 'schere';
  const { games } = buildImportWettkampf(spec, { playedLanes: [1, 2, 3, 4, 5, 6] });
  let arne = null;
  games.forEach((g) => {
    const { players } = computeGameStats(g.config, g.erfassung.bloecke, teilsatzRanges(g.config));
    const p = players.find((x) => x.name === 'Schierbaum, Arne');
    if (p) arne = p;
  });
  assert.ok(arne);
  assert.deepEqual(arne.saetze.map((x) => x.holz), [195, 230, 202, 194], 'in Berichtsreihenfolge');
  assert.equal(arne.gesamt, 821);
});

// --- Startbahn nachtragen (Mannschafts-Uebersicht im Hub) --------------------
//
// Sportwinner nennt die Startbahnen nicht. Wird eine spaeter korrigiert, muss jedes importierte
// Ergebnis auf den Satz wandern, in dem seine BAHN jetzt gespielt wird — sonst behauptet es
// ploetzlich eine Bahn, auf der es nie erzielt wurde.

const blk = (holz) => ({ wuerfe: [], kegel: [], koenig: [], overrides: [null, null], satzOverride: holz, done: true });

test('bloeckeNachBahn: die Ergebnisse folgen ihrer Bahn', () => {
  const bloecke = [blk(195), blk(230), blk(202), blk(194)];
  // Vorher startete der Spieler auf Bahn 2, jetzt auf Bahn 4 (Schere, Reihum +1).
  const alt = [2, 3, 4, 5];
  const neu = [4, 5, 2, 3];
  const neuBloecke = bloeckeNachBahn(bloecke, alt, neu);
  assert.deepEqual(neuBloecke.map((b) => b.satzOverride), [202, 194, 195, 230]);
  // Gegenprobe: jedes Ergebnis steht weiter auf derselben Bahn wie vorher.
  neu.forEach((bahn, satz) => {
    assert.equal(neuBloecke[satz].satzOverride, bloecke[alt.indexOf(bahn)].satzOverride);
  });
});

test('bloeckeNachBahn: uneindeutige Plaene bleiben unangetastet', () => {
  const bloecke = [blk(1), blk(2), blk(3), blk(4)];
  // Eine Bahn doppelt (weniger Bahnen als Saetze) -> keine eindeutige Zuordnung.
  assert.equal(bloeckeNachBahn(bloecke, [2, 3, 2, 3], [3, 2, 3, 2]), bloecke);
  // Andere Bahn-Menge -> der Plan spricht nicht von denselben Bahnen.
  assert.equal(bloeckeNachBahn(bloecke, [2, 3, 4, 5], [6, 7, 8, 9]), bloecke);
  // Unpassende Laengen / leere Eingaben.
  assert.equal(bloeckeNachBahn(bloecke, [2, 3], [3, 2]), bloecke);
  assert.equal(bloeckeNachBahn(bloecke, null, null), bloecke);
  // Unveraendert bleibt unveraendert.
  assert.deepEqual(bloeckeNachBahn(bloecke, [2, 3, 4, 5], [2, 3, 4, 5]).map((b) => b.satzOverride),
    [1, 2, 3, 4]);
});

// --- Zwischenstaende: laufende Partie, zweiter Import ------------------------

const PARTIE = {
  heim: 'VOK Osnabrück 1', gast: 'SKC Greste-Lage 1', datum: '2026-08-29', idSpiel: '328202',
};

// Dieselbe echte Partie als ZWISCHENSTAND: gespielt sind erst die Bahnen 2 und 3 — also die
// Berichtsspalten 1 und 2. Die Spalten 3 und 4 sind leer, die Holzspalte nennt die Teilsumme.
// Beim Gast stehen die Spalten rueckwaerts (13,12,11,10), leer sind dort also 11 und 10.
const teilRows = () => SCHERE.rows.map((r) => {
  const z = r.slice();
  if (!z[1] && !z[14]) return z;                 // Mannschaftssumme unveraendert lassen
  z[4] = ''; z[5] = '';
  z[7] = String(Number(z[2]) + Number(z[3]));
  z[10] = ''; z[11] = '';
  z[8] = String(Number(z[13]) + Number(z[12]));
  return z;
});

// Wo sitzt ein Spieler? -> { g, i } (Durchgang-Spiel + Index in seiner spielerListe).
function ort(games, name) {
  for (const g of games) {
    const i = g.config.spielerListe.findIndex((sp) => sp.name === name);
    if (i >= 0) return { g, i };
  }
  return null;
}

const leereSaetze = (games) => games.reduce((n, g) => n
  + g.erfassung.bloecke.reduce((m, arr) => m + arr.filter((b) => blockLeer(b)).length, 0), 0);

const STATUS_ROWS = [
  ['400001', '12.09.2026', '19:00', 'A 1', '0', '0', 'B 1', '0', '0', 'wird gespielt', '', '0', '', ''],
  ['400002', '12.09.2026', '19:00', 'C 1', '5', '3', 'D 1', '4', '4', 'abnahmebereit', '', '0', '', ''],
  ['400003', '19.09.2026', '19:00', 'E 1', '0', '0', 'F 1', '0', '0', 'abgesagt', '', '0', '', ''],
];

test('parseSpielListe: laufend und abnahmebereit sind importierbar, abgesagt/offen nicht', () => {
  const [laeuft, abnahme, abgesagt] = parseSpielListe(STATUS_ROWS);
  assert.equal(laeuft.laufend, true);
  assert.equal(laeuft.gespielt, false, 'ein Zwischenstand ist kein fertiges Spiel');
  assert.equal(laeuft.importierbar, true);
  // "abnahmebereit" heisst: fertig gespielt, wartet nur noch auf die Bestaetigung.
  assert.equal(abnahme.gespielt, true);
  assert.equal(abnahme.laufend, false);
  assert.equal(abnahme.importierbar, true);
  assert.equal(abgesagt.importierbar, false);
  assert.equal(parseSpielListe(SPIEL_ROWS)[1].importierbar, false, 'offen: es gibt nichts zu holen');
});

test('Zwischenstand: leere Bahnen bleiben an ihrer Stelle stehen', () => {
  const b = parseSpielerInfo(teilRows(), { saetze: 4 });
  assert.equal(b.layout, 'schere');
  assert.equal(b.paare.length, 6, 'die Mannschaftssumme ist weiterhin keine Paarung');
  const arne = b.paare[1];
  // Der entscheidende Punkt: NICHT [195, 230] — die Luecke traegt die Zuordnung zur Bahn.
  assert.deepEqual(arne.gg.saetze.map((x) => x && x.holz), [195, 230, null, null]);
  assert.deepEqual(arne.g.saetze.map((x) => x && x.holz), [189, 207, null, null]);
  assert.equal(arne.gg.kegel, 425);
  assert.deepEqual(b.warnungen, [], 'die Teilsumme muss zur Holzspalte passen');
});

test('Zwischenstand: eine noch nicht angetretene Paarung verschiebt die Positionen nicht', () => {
  // Paarung 2 (Arne) hat noch gar nicht gespielt: zwei Namen, keine Werte. Wird die Zeile
  // verworfen, ruecken alle folgenden Spieler eine Team-Position nach vorn.
  const rows = teilRows().map((r, i) => {
    if (i !== 1) return r;
    const z = r.slice();
    [2, 3, 4, 5, 7, 8, 10, 11, 12, 13].forEach((k) => { z[k] = ''; });
    return z;
  });
  const b = parseSpielerInfo(rows, { saetze: 4 });
  assert.equal(b.paare.length, 6);
  assert.equal(b.paare[1].gg.name, 'Schierbaum, Arne');
  assert.ok(b.paare[1].gg.saetze.every((x) => x === null));
  assert.equal(b.paare[2].gg.name, 'Hösel, Christoph', 'Paarung 3 bleibt Position 3');

  const spec = buildImportSpec(PARTIE, b);
  const m = spec.mannschaften[0];
  assert.equal(spec.namesByTeamPos[`${m.id}|3`], 'Hösel, Christoph');
});

test('Zwischenstand: das Ergebnis landet auf dem Satz, der auf DIESER Bahn gespielt wird', () => {
  const spec = buildImportSpec(PARTIE, parseSpielerInfo(teilRows(), { saetze: 4 }));
  spec.preset = 'schere';
  const { wettkampf, games } = buildImportWettkampf(spec, { playedLanes: [2, 3, 4, 5] });

  const arne = ort(games, 'Schierbaum, Arne');
  const { players } = computeGameStats(
    arne.g.config, arne.g.erfassung.bloecke, teilsatzRanges(arne.g.config),
  );
  const p = players[arne.i];
  // Arne startet auf Bahn 5; gespielt sind erst die Bahnen 2 und 3 — das sind seine Saetze 2
  // und 3. Wuerde der Bericht stumpf von vorn abgearbeitet, stuenden 195/230 auf Satz 1 und 2.
  assert.deepEqual(p.saetze.map((x) => x.bahn), [5, 2, 3, 4]);
  assert.deepEqual(p.saetze.map((x) => x.holz), [0, 195, 230, 0]);
  assert.notDeepEqual(p.saetze.map((x) => x.holz), [195, 230, 0, 0]);
  assert.equal(p.gesamt, 425);

  // Ein Zwischenstand ist kein fertiges Spiel — der Status wird abgeleitet, nicht behauptet.
  assert.equal(wettkampf.status, 'laufend');
  assert.ok(games.every((g) => g.status === 'laufend'));
  assert.equal(leereSaetze(games), 24, '12 Spieler mit je zwei offenen Saetzen');
});

test('vollstaendige Partie bleibt beendet', () => {
  const spec = buildImportSpec(PARTIE, parseSpielerInfo(SCHERE.rows, { saetze: 4 }));
  spec.preset = 'schere';
  const { wettkampf, games } = buildImportWettkampf(spec, { playedLanes: [2, 3, 4, 5] });
  assert.equal(wettkampf.status, 'beendet');
  assert.ok(games.every((g) => g.status === 'beendet'));
  assert.equal(leereSaetze(games), 0);
});

test('Nachimport: der zweite Import fuellt nur die Luecken', () => {
  const teil = buildImportSpec(PARTIE, parseSpielerInfo(teilRows(), { saetze: 4 }));
  teil.preset = 'schere';
  const { wettkampf, games } = buildImportWettkampf(teil, { playedLanes: [2, 3, 4, 5] });

  // Von Hand nachgetragen: die Volle/Abraeum-Aufteilung eines schon importierten Satzes. Genau
  // sie darf ein zweiter Import nicht wieder plattmachen.
  const malte = ort(games, 'Schierbaum, Malte');
  const satz = malte.g.erfassung.bloecke[malte.i].findIndex((b) => b.satzOverride != null);
  malte.g.erfassung.bloecke[malte.i][satz] = {
    wuerfe: [], kegel: [], koenig: [], overrides: [100, 83], satzOverride: null, done: true,
  };

  // Zweiter Abruf derselben Partie, jetzt fertig — mit FRISCHEN Mannschafts-IDs.
  const voll = buildImportSpec(PARTIE, parseSpielerInfo(SCHERE.rows, { saetze: 4 }));
  voll.preset = 'schere';
  assert.notEqual(voll.mannschaften[0].id, teil.mannschaften[0].id, 'die IDs sind jedes Mal neu');

  const probe = trageErgebnisseEin(games, voll, {
    nurLeere: true, probe: true, mannschaften: wettkampf.mannschaften,
  });
  assert.equal(probe.gefuellt, 24, 'es fehlen 12 Spieler x 2 Saetze');
  assert.equal(leereSaetze(games), 24, 'die Probe schreibt nichts');

  const { gefuellt, geaendert } = trageErgebnisseEin(games, voll, {
    nurLeere: true, mannschaften: wettkampf.mannschaften,
  });
  assert.equal(gefuellt, 24);
  assert.equal(geaendert.length, games.length);
  assert.equal(leereSaetze(games), 0);

  // Das von Hand Nachgetragene steht unveraendert da.
  assert.deepEqual(malte.g.erfassung.bloecke[malte.i][satz].overrides, [100, 83]);
  assert.equal(malte.g.erfassung.bloecke[malte.i][satz].satzOverride, null);

  // Und die ergaenzten Saetze sitzen richtig: Arne kommt auf sein volles Holz.
  const arne = ort(games, 'Schierbaum, Arne');
  const { players } = computeGameStats(
    arne.g.config, arne.g.erfassung.bloecke, teilsatzRanges(arne.g.config),
  );
  assert.deepEqual(players[arne.i].saetze.map((x) => x.holz), [194, 195, 230, 202]);
  assert.equal(players[arne.i].gesamt, 821);

  // Ein dritter Import bringt nichts Neues mehr — und ruehrt nichts an.
  const nochmal = trageErgebnisseEin(games, voll, {
    nurLeere: true, mannschaften: wettkampf.mannschaften,
  });
  assert.equal(nochmal.gefuellt, 0);
  assert.equal(nochmal.geaendert.length, 0);
});

test('Nachimport ohne Mannschaftsliste trifft nichts — die IDs sind neu', () => {
  // Absicherung der Zuordnung selbst: ohne `mannschaften` sucht der Nachimport unter den
  // frischen uid()s des zweiten Abrufs und findet keinen einzigen Spieler.
  const teil = buildImportSpec(PARTIE, parseSpielerInfo(teilRows(), { saetze: 4 }));
  teil.preset = 'schere';
  const { games } = buildImportWettkampf(teil, { playedLanes: [2, 3, 4, 5] });
  const voll = buildImportSpec(PARTIE, parseSpielerInfo(SCHERE.rows, { saetze: 4 }));
  voll.preset = 'schere';
  assert.equal(trageErgebnisseEin(games, voll, { nurLeere: true, probe: true }).gefuellt, 0);
});

test('blockLeer: was schon dasteht, wird nicht ueberschrieben', () => {
  assert.equal(blockLeer(null), true);
  assert.equal(blockLeer({ wuerfe: [], overrides: [null, null], satzOverride: null }), true);
  assert.equal(blockLeer({ wuerfe: [], overrides: [null, null], satzOverride: 195 }), false);
  assert.equal(blockLeer({ wuerfe: [], overrides: [100, null], satzOverride: null }), false);
  assert.equal(blockLeer({ wuerfe: [{ holz: 9 }], overrides: [null], satzOverride: null }), false);
  // Leer, aber von Hand abgeschlossen: das ist eine Entscheidung, kein freier Platz.
  assert.equal(blockLeer({ wuerfe: [], overrides: [null], satzOverride: null, done: true }), false);
});
