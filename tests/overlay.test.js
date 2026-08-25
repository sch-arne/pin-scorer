import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildOverlayHtml, chooseLaneDurchgangNr } from '../js/views/overlay.js';
import { buildWettkampf } from '../js/logic/wettkampf-build.js';

// Ein Satz-Block, dessen zwei Teilsätze als Summen-Overrides gesetzt sind (holz = a + b).
function blk(a, b) {
  return { wuerfe: [], overrides: [a, b], done: true };
}

// Ein Durchgang-Spiel: 2 Heim- + 2 Gast-Spieler auf 4 Bahnen (2,3,4,5), 4 Sätze,
// zwei Teilsätze Volle à 15 Würfe. Jeder Spieler bekommt je Satz feste Holzwerte.
function mkGame(id, players) {
  const teilsaetze = [{ modus: 'volle', wuerfe: 15 }, { modus: 'volle', wuerfe: 15 }];
  const spielerListe = players.map((p) => ({
    name: p.name, mannschaftId: p.team, teamPos: p.pos, startBahn: 2,
  }));
  const config = {
    spielerListe, saetze: 4, ersteBahn: 2, wuerfeProSatz: 30,
    teilsaetze, bahnListe: [2, 3, 4, 5], bahnen: 4,
  };
  // 4 Sätze je Spieler; holz = 100 + kleine Variation, damit Summen eindeutig sind.
  const bloecke = players.map((p) =>
    [0, 1, 2, 3].map((s) => blk(100 + p.pos + s, 5)));
  return { id, config, erfassung: { bloecke } };
}

function mkWettkampf() {
  const home = ['Heim 1', 'Heim 2', 'Heim 3', 'Heim 4'];
  const away = ['Gast 1', 'Gast 2', 'Gast 3', 'Gast 4'];
  const games = [];
  const durchgaenge = [];
  for (let d = 0; d < 2; d += 1) {
    const players = [];
    for (let k = 0; k < 2; k += 1) {
      const pos = d * 2 + k + 1;
      players.push({ name: home[pos - 1], team: 'A', pos });
      players.push({ name: away[pos - 1], team: 'B', pos });
    }
    const id = 'ov-' + (d + 1);
    games.push(mkGame(id, players));
    durchgaenge.push({ nr: d + 1, gameId: id });
  }
  const wettkampf = {
    mannschaften: [{ id: 'A', name: 'VOK Osnabrück 1' }, { id: 'B', name: 'SV Union Lohne 1' }],
    playedLanes: [2, 3, 4, 5], spielerJeMannschaft: 4, durchgaenge,
  };
  return { wettkampf, games };
}

test('buildOverlayHtml: zwei Team-Tabellen mit Namen, Bahn-Spalten und Kegel-Summe', () => {
  const html = buildOverlayHtml(mkWettkampf());
  // Beide Mannschaften im Kopf.
  assert.ok(html.includes('VOK Osnabrück 1'));
  assert.ok(html.includes('SV Union Lohne 1'));
  // Alle vier Heim-Spieler in Aufstellungsreihenfolge (teamPos) vorhanden.
  ['Heim 1', 'Heim 2', 'Heim 3', 'Heim 4'].forEach((n) => assert.ok(html.includes(n)));
  ['Gast 1', 'Gast 4'].forEach((n) => assert.ok(html.includes(n)));
  // Kegel-Spalte + Bahn-Spalten (Holz je Bahn 2..5) wieder vorhanden.
  assert.ok(html.includes('<th>Kegel</th>'));
  assert.ok(html.includes('ov-lane-h'), 'Bahn-Kopfzellen wieder da');
  [2, 3, 4, 5].forEach((n) => assert.ok(html.includes(`ov-lane-h">${n}<`), `Bahn-Kopf ${n}`));
  // Kegel-Summe je Spieler: Heim 1 = Summe über 4 Sätze von (100+1+s + 5).
  // s=0..3 -> (106+107+108+109) = 430.
  assert.ok(html.includes('>430<'));
  // Holz je Bahn: Heim 1 (pos 1) auf Bahn 2 (Satz 0) = 100+1+0 + 5 = 106.
  assert.ok(html.includes('ov-c ov-lane">106<'));
});

test('buildOverlayHtml ohne Wertung: Team-Kopf zeigt Kegel-Zwischenstand', () => {
  const { wettkampf, games } = mkWettkampf();
  const html = buildOverlayHtml({ wettkampf, games });
  // Heim-Gesamt = Summe der vier Heim-Spieler.
  // Heim p: Summe_s (100+p+s+5) = 4*105 + 4*p + (0+1+2+3) = 420 + 4p + 6 = 426 + 4p.
  // p=1..4 -> 430+434+438+442 = 1744. Ohne hinterlegte Wertung zeigt die Team-Kopfzeile
  // den Kegel-Zwischenstand mit Label "Kegel".
  assert.ok(html.includes('ov-th-pts">1744<'));
  assert.ok(html.includes('ov-th-lbl">Kegel<'));
});

// Ein echter Schere-Wettkampf (2 Teams je 4 Spieler, 4 Bahnen, kranz-abräumen) über
// buildWettkampf gebaut, alle Sätze als Summen (volle+abräumen) gefüllt.
function mkSchere() {
  const spec = {
    name: 'Test', datum: '2026-08-20', preset: 'schere', saetze: 4, wuerfeProSatz: 30,
    teilsaetze: ['volle', 'kranz-abraeumen'], bahnwechsel: 'plus1',
    anlageId: 'a1', anlageName: 'Halle',
    anlageBahnen: [2, 3, 4, 5].map((n) => ({ id: 'b' + n, nummer: n, bahnart: 'schere' })),
    playedLanes: [2, 3, 4, 5],
    mannschaften: [{ id: 'A', name: 'VOK Osnabrück 1', lanes: [2, 3, 4, 5] },
      { id: 'B', name: 'SV Union Lohne 1', lanes: [2, 3, 4, 5] }],
    spielerJeMannschaft: 4,
  };
  const { wettkampf, games } = buildWettkampf(spec);
  games.forEach((g) => g.config.spielerListe.forEach((sp, i) => {
    g.erfassung = g.erfassung || { bloecke: [] };
    g.erfassung.bloecke[i] = [0, 1, 2, 3].map((s) => ({ wuerfe: [], overrides: [90 + i * 3 + s, 40 + i * 2 + s], done: true }));
  }));
  return { wettkampf, games };
}

test('buildOverlayHtml Schere: EWP-Spalte, Spielpunkte-Score (Summe 3) und Bahn-Übersicht', () => {
  const html = buildOverlayHtml(mkSchere());
  // EWP-Spalte vorhanden.
  assert.ok(html.includes('ov-ewp-h'), 'EWP-Kopf');
  // Spielpunkte je Team in der Kopfzeile (außen), Summe = 3.
  const pts = [...html.matchAll(/ov-th-pts">([\d,]+)</g)].map((m) => Number(m[1].replace(',', '.')));
  assert.equal(pts.length, 2, 'zwei Team-Köpfe');
  assert.equal(pts.reduce((a, b) => a + b, 0), 3);
  // EWP-Team-Summen = 8..1 zusammen = 36.
  const ewpTot = [...html.matchAll(/ov-ewp ov-total-val">(\d+)</g)].map((m) => Number(m[1]));
  assert.equal(ewpTot.reduce((a, b) => a + b, 0), 36);
  // Bahn-Übersicht: 4 Karten Bahn 2..5.
  assert.equal((html.match(/ov-lane-card/g) || []).length, 4);
  [2, 3, 4, 5].forEach((n) => assert.ok(html.includes(`Bahn ${n}`)));
});

// Die Bahn-Karten der Mitte müssen GENAUSO rotieren wie die Bahn-Anzeige der Wurferfassung
// (physische Bahn aus computeBahnState mit Bahnwechsel-Gating), nicht die Bahn des zuletzt
// abgeschlossenen Satzes zeigen. Setup: Heim auf 2/4, Gast auf 3/5, plus1. Nach einem komplett
// gespielten ersten Satz haben ALLE gemeinsam eine Bahn weitergerückt (geschlossener Zyklus) —
// der Startbahn-2-Spieler steht danach auf Bahn 3, nicht mehr auf Bahn 2.
test('buildOverlayHtml: Bahn-Karten rotieren wie die Spieleingabe (plus1, nach Runde weiter)', () => {
  const spec = {
    name: 'Rot', datum: '2026-08-20', preset: 'schere', saetze: 4, wuerfeProSatz: 30,
    teilsaetze: ['volle', 'kranz-abraeumen'], bahnwechsel: 'plus1',
    anlageId: 'a1', anlageName: 'Halle',
    anlageBahnen: [2, 3, 4, 5].map((n) => ({ id: 'b' + n, nummer: n, bahnart: 'schere' })),
    playedLanes: [2, 3, 4, 5],
    mannschaften: [{ id: 'A', name: 'Heim', lanes: [2, 4] }, { id: 'B', name: 'Gast', lanes: [3, 5] }],
    spielerJeMannschaft: 2,
    namesByTeamPos: { 'A|1': 'Start2', 'A|2': 'Start4', 'B|1': 'Start3', 'B|2': 'Start5' },
  };
  const { wettkampf, games } = buildWettkampf(spec);
  // Nur den ERSTEN Satz aller Spieler abschließen (done), Rest offen -> Runde ist voll, alle
  // rücken gemeinsam eine Bahn weiter.
  games[0].config.spielerListe.forEach((_, i) => {
    games[0].erfassung = games[0].erfassung || { bloecke: [] };
    games[0].erfassung.bloecke[i] = [0, 1, 2, 3].map((s) => ({
      wuerfe: [], overrides: [100, 20], done: s === 0,
    }));
  });
  const html = buildOverlayHtml({ wettkampf, games });
  // Karte „Bahn 3" gehört jetzt dem Startbahn-2-Spieler (rotiert), NICHT dem Startbahn-3-Spieler.
  const bahn3 = html.slice(html.indexOf('Bahn 3'), html.indexOf('Bahn 3') + 90);
  assert.ok(bahn3.includes('Start2'), 'Startbahn-2-Spieler steht nach der Runde auf Bahn 3');
  assert.ok(!bahn3.includes('Start3'), 'Startbahn-3-Spieler ist von Bahn 3 weitergerückt');
});

test('chooseLaneDurchgangNr: fertiger Durchgang bleibt 1 min, dann Umschalten auf Vorbereitung', () => {
  const wettkampf = { durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }] };
  const games = [{ id: 'g1', status: 'beendet' }, { id: 'g2', status: 'setup' }];
  // Durchgang 1 hat Würfe (fertig), Durchgang 2 noch nicht (Vorbereitung).
  const stats = { einzel: [
    { durchgangNr: 1, wurfCount: 30 }, { durchgangNr: 2, wurfCount: 0 },
  ] };
  const state = { fertigNr: null, fertigSeit: 0 };
  const t0 = 1000000;
  assert.equal(chooseLaneDurchgangNr(wettkampf, games, stats, state, t0, 60000), 1, 'sofort: Endstand von DG1');
  assert.equal(chooseLaneDurchgangNr(wettkampf, games, stats, state, t0 + 59000, 60000), 1, 'nach 59 s: noch DG1');
  assert.equal(chooseLaneDurchgangNr(wettkampf, games, stats, state, t0 + 60000, 60000), 2, 'nach 60 s: auf Vorbereitung (DG2)');
});

test('chooseLaneDurchgangNr: startet DG2 selbst, greift sofort der laufende Durchgang', () => {
  const wettkampf = { durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }] };
  const games = [{ id: 'g1', status: 'beendet' }, { id: 'g2', status: 'laufend' }];
  // DG2 hat jetzt Würfe -> ist der laufende Durchgang (max mit Würfen).
  const stats = { einzel: [
    { durchgangNr: 1, wurfCount: 30 }, { durchgangNr: 2, wurfCount: 3 },
  ] };
  const state = { fertigNr: 1, fertigSeit: 500 }; // war im Halten
  assert.equal(chooseLaneDurchgangNr(wettkampf, games, stats, state, 5000, 60000), 2);
  assert.equal(state.fertigNr, null, 'Halte-Zustand zurückgesetzt');
});

test('chooseLaneDurchgangNr: letzter Durchgang fertig, kein Vorbereitung -> bleibt stehen', () => {
  const wettkampf = { durchgaenge: [{ nr: 1, gameId: 'g1' }] };
  const games = [{ id: 'g1', status: 'beendet' }];
  const stats = { einzel: [{ durchgangNr: 1, wurfCount: 30 }] };
  const state = { fertigNr: null, fertigSeit: 0 };
  const t0 = 1000000;
  assert.equal(chooseLaneDurchgangNr(wettkampf, games, stats, state, t0, 60000), 1);
  assert.equal(chooseLaneDurchgangNr(wettkampf, games, stats, state, t0 + 120000, 60000), 1, 'ohne Vorbereitung bleibt DG1');
});

test('buildOverlayHtml: opts.laneNr erzwingt den in der Bahnansicht gezeigten Durchgang', () => {
  const data = mkWettkampf(); // 2 Durchgänge: DG1 = Pos 1/2, DG2 = Pos 3/4 (beide gespielt)
  // Ohne Override zeigt die Bahnansicht den laufenden Durchgang (max mit Würfen = DG2).
  const def = buildOverlayHtml(data);
  const defLanes = def.slice(def.indexOf('ov-lanes'));
  assert.ok(defLanes.includes('Heim 3') && defLanes.includes('Heim 4'), 'Standard: DG2-Aufstellung auf den Bahnen');
  // Mit laneNr = 1 (z. B. Halten des Endstands) zeigt die Bahnansicht DG1.
  const forced = buildOverlayHtml(data, { laneNr: 1 });
  const forcedLanes = forced.slice(forced.indexOf('ov-lanes'));
  assert.ok(forcedLanes.includes('Heim 1') && forcedLanes.includes('Heim 2'), 'Override: DG1-Aufstellung auf den Bahnen');
  assert.ok(!forcedLanes.includes('Heim 3'), 'Override: keine DG2-Spieler in der Bahnansicht');
});

test('buildOverlayHtml: ohne Daten -> Warte-Hinweis, mit einer Mannschaft -> Hinweis', () => {
  assert.ok(buildOverlayHtml(null).includes('Warte'));
  assert.ok(buildOverlayHtml({ wettkampf: { mannschaften: [{ id: 'A', name: 'A' }] }, games: [] })
    .includes('zwei Mannschaften'));
});
