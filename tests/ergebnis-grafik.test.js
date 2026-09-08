// Modell der Ergebnis-Grafik: was am Ende als Bild gezeichnet wird, entsteht hier.
// Zwei Fälle sind erfahrungsgemäß die heiklen: die EWP-Spalte darf erst nach Spielende
// erscheinen UND nur bei hinterlegter Wertung, und ein Spieler ohne Würfe darf nicht als
// „0 Holz" dastehen.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  GRAFIK_DEFAULT, grafikModell, grafikOptionen, normalisiereOptionen, grafikDateiname,
} from '../js/logic/ergebnis-grafik.js';

// Ein Satz-Block, dessen zwei Teilsätze als Summen-Overrides gesetzt sind (holz = a + b) —
// wie in tests/overlay.test.js.
function blk(a, b, done = true) {
  return { wuerfe: [], overrides: [a, b], done };
}

function leerBlk() {
  return { wuerfe: [], overrides: [], done: false };
}

// Ein Durchgang-Spiel mit 2 Heim- + 2 Gast-Spielern, 4 Sätze, zwei Teilsätze à 15 Würfe.
// Volle + Kranz-Abräumen = Schere — die Bahnart, für die es eine Wertung (Spielpunkte, EWP)
// gibt; ohne sie liefert computeWertung null und das Modell zeigt keine EWP.
// `holz(p, satz)` liefert das Satz-Ergebnis; gibt sie null zurück, bleibt der Satz leer.
function mkGame(id, players, holz) {
  const spielerListe = players.map((p) => ({
    name: p.name, mannschaftId: p.team, teamPos: p.pos, startBahn: 2,
  }));
  const config = {
    spielerListe, saetze: 4, ersteBahn: 2, wuerfeProSatz: 30,
    teilsaetze: [{ modus: 'volle', wuerfe: 15 }, { modus: 'kranz-abraeumen', wuerfe: 15 }],
    bahnListe: [2, 3, 4, 5], bahnen: 4,
  };
  const bloecke = players.map((p) => [0, 1, 2, 3].map((s) => {
    const h = holz(p, s);
    return h == null ? leerBlk() : blk(h - 5, 5);
  }));
  return { id, config, erfassung: { bloecke } };
}

// Wettkampf mit zwei 4er-Mannschaften über zwei Durchgänge.
//   opts.nurDurchgang1 — im zweiten Durchgang wurde noch nichts erfasst (Wettkampf läuft)
//   opts.wertung       — die Wertungs-Konfiguration (fehlt sie ganz, greift der Schere-Standard)
//   opts.programm      — Bahnart-Preset
function mkWettkampf(opts = {}) {
  const namen = { A: ['Heim 1', 'Heim 2', 'Heim 3', 'Heim 4'], B: ['Gast 1', 'Gast 2', 'Gast 3', 'Gast 4'] };
  const games = [];
  const durchgaenge = [];
  for (let d = 0; d < 2; d += 1) {
    const players = [];
    for (let k = 0; k < 2; k += 1) {
      const pos = d * 2 + k + 1;
      // Bewusst Gast VOR Heim einspeisen — das Modell muss nach teamPos sortieren.
      players.push({ name: namen.B[pos - 1], team: 'B', pos });
      players.push({ name: namen.A[pos - 1], team: 'A', pos });
    }
    const leer = opts.nurDurchgang1 && d === 1;
    games.push(mkGame('g' + (d + 1), players, (p, s) => (leer ? null : 100 + p.pos + s + (p.team === 'A' ? 10 : 0))));
    durchgaenge.push({ nr: d + 1, gameId: 'g' + (d + 1) });
  }
  const wettkampf = {
    name: 'VOK gegen Sontra', datum: '2026-09-05T18:00:00.000Z', anlageName: 'Kegelhalle',
    mannschaften: [{ id: 'A', name: 'VOK Osnabrück 1' }, { id: 'B', name: 'KV Sontra 1' }],
    spielerJeMannschaft: 4, playedLanes: [2, 3, 4, 5], durchgaenge,
  };
  if (opts.wertung !== undefined) wettkampf.wertung = opts.wertung;
  if (opts.programm) wettkampf.programm = opts.programm;
  return { wettkampf, games };
}

test('Duell-Modell: zwei Mannschaften, Spieler nach teamPos, Summen und Spielpunkte', () => {
  const m = grafikModell(mkWettkampf());
  assert.equal(m.modus, 'duell');
  assert.equal(m.titel, 'VOK gegen Sontra');
  assert.ok(m.untertitel.includes('Kegelhalle'));
  assert.equal(m.teams.length, 2);
  // Heim = mannschaften[0], Reihenfolge trotz umgekehrter Einspeisung nach teamPos.
  assert.equal(m.teams[0].name, 'VOK Osnabrück 1');
  assert.deepEqual(m.teams[0].zeilen.map((z) => z.name), ['Heim 1', 'Heim 2', 'Heim 3', 'Heim 4']);
  assert.deepEqual(m.teams[1].zeilen.map((z) => z.name), ['Gast 1', 'Gast 2', 'Gast 3', 'Gast 4']);
  // Summe = Summe der Zeilen; Heim liegt durch den +10-Bonus vorn.
  assert.equal(m.teams[0].summeHolz, m.teams[0].zeilen.reduce((s, z) => s + z.gesamt, 0));
  assert.ok(m.teams[0].summeHolz > m.teams[1].summeHolz);
  // Spielpunkte als fertiger Text (fmtPunkte: halbe Punkte mit Komma).
  assert.equal(typeof m.teams[0].spielpunkte, 'string');
  assert.match(m.teams[0].spielpunkte, /^[0-9]+(,[0-9]+)?$/);
  // Ohne Logos: hatLogos false, Akzent auf Kegel-Gold.
  assert.equal(m.hatLogos, false);
  assert.equal(m.teams[0].accent, '#f5a623');
});

test('Duell-Modell: EWP erst nach Spielende', () => {
  const laufend = grafikModell(mkWettkampf({ nurDurchgang1: true }));
  assert.equal(laufend.fertig, false);
  assert.equal(laufend.mitEwp, false);

  const fertig = grafikModell(mkWettkampf());
  assert.equal(fertig.fertig, true);
  assert.equal(fertig.mitEwp, true);
  // EWP-Skala = volle Feldgröße (2 x 4 = 8), der Beste bekommt 8.
  const alle = fertig.teams.flatMap((t) => t.zeilen.map((z) => z.ewp));
  assert.equal(Math.max(...alle), 8);
  assert.equal(alle.reduce((s, e) => s + e, 0), 36); // 8+7+…+1
  assert.equal(fertig.teams[0].summeEwp + fertig.teams[1].summeEwp, 36);
});

test('Duell-Modell: beendeter Wettkampf OHNE hinterlegte Wertung zeigt keine EWP', () => {
  // Bohle-Programm und wertung: null -> computeWertung liefert null. Die von assignEwp
  // gesetzten Zahlen gehen dann in keine Wertung ein und dürfen nicht als Spalte erscheinen.
  const m = grafikModell(mkWettkampf({ wertung: null, programm: { preset: 'bohle' } }));
  assert.equal(m.fertig, true);
  assert.equal(m.mitEwp, false);
  assert.equal(m.mitSpielpunkte, false);
  assert.equal(m.teams[0].spielpunkte, null);
});

test('Duell-Modell: Spieler ohne Würfe sind nicht gespielt', () => {
  const m = grafikModell(mkWettkampf({ nurDurchgang1: true }));
  const alle = m.teams.flatMap((t) => t.zeilen);
  const gespielt = alle.filter((z) => z.gespielt);
  const offen = alle.filter((z) => !z.gespielt);
  assert.equal(gespielt.length, 4);            // Durchgang 1: je 2 Spieler
  assert.equal(offen.length, 4);               // Durchgang 2: noch nichts erfasst
  offen.forEach((z) => assert.equal(z.gesamt, 0));
});

test('Wettkampf mit einer oder drei Mannschaften fällt auf die Rangliste zurück', () => {
  const { wettkampf, games } = mkWettkampf();
  wettkampf.mannschaften = [{ id: 'A', name: 'VOK Osnabrück 1' }];
  const eine = grafikModell({ wettkampf, games });
  assert.equal(eine.modus, 'liste');
  assert.equal(eine.teams.length, 0);
  assert.ok(eine.zeilen.length > 0);

  wettkampf.mannschaften = [{ id: 'A', name: 'A' }, { id: 'B', name: 'B' }, { id: 'C', name: 'C' }];
  assert.equal(grafikModell({ wettkampf, games }).modus, 'liste');
});

test('Listen-Modell aus einem Trainingsspiel: nach Holz sortiert, Rang mit 1224-Zählung', () => {
  const players = [
    { name: 'Anna', team: null, pos: 1 },
    { name: 'Bernd', team: null, pos: 2 },
    { name: 'Cem', team: null, pos: 3 },
  ];
  // Anna und Bernd gleichauf (je 4x110), Cem darunter -> Ränge 1, 1, 3.
  const game = mkGame('t1', players, (p, s) => (p.name === 'Cem' ? 100 : 110) + s * 0);
  game.createdAt = '2026-09-05T10:00:00.000Z';
  game.config.anlageName = 'Trainingshalle';
  const m = grafikModell({ game });
  assert.equal(m.modus, 'liste');
  assert.equal(m.titel, 'Ergebnis');
  assert.ok(m.untertitel.includes('Trainingshalle'));
  assert.equal(m.mitEwp, false);
  assert.equal(m.mitSpielpunkte, false);
  assert.deepEqual(m.zeilen.map((z) => z.rang), [1, 1, 3]);
  assert.equal(m.zeilen[2].name, 'Cem');
  assert.ok(m.zeilen[0].gesamt > m.zeilen[2].gesamt);
});

test('grafikModell ohne verwertbare Quelle liefert ein leeres Modell', () => {
  const m = grafikModell(null);
  assert.equal(m.modus, 'liste');
  assert.deepEqual(m.zeilen, []);
  assert.equal(m.mitEwp, false);
});

test('normalisiereOptionen erzwingt, was die Daten hergeben', () => {
  const modell = { mitEwp: false, hatLogos: false, mitSpielpunkte: false };
  const o = normalisiereOptionen({ ewp: true, logos: true, spielpunkte: true, format: 'quadrat' }, modell);
  assert.equal(o.ewp, false);
  assert.equal(o.logos, false);
  assert.equal(o.spielpunkte, false);
  assert.equal(o.format, 'hoch');            // unbekanntes Format -> Standard

  const voll = normalisiereOptionen({ ewp: true, logos: true, spielpunkte: true, format: 'story' },
    { mitEwp: true, hatLogos: true, mitSpielpunkte: true });
  assert.equal(voll.ewp, true);
  assert.equal(voll.logos, true);
  assert.equal(voll.format, 'story');

  // Unsinnige Werte in den übrigen Feldern fallen ebenfalls auf den Standard zurück.
  const wirr = normalisiereOptionen({ textfarbe: 'lila', flaechen: 'knallig', position: 'schräg' }, modell);
  assert.equal(wirr.textfarbe, GRAFIK_DEFAULT.textfarbe);
  assert.equal(wirr.flaechen, GRAFIK_DEFAULT.flaechen);
  assert.equal(wirr.position, GRAFIK_DEFAULT.position);

  // Schrift und Umrandung hängen an keinen Daten — nur an einer gültigen Auswahl.
  assert.equal(normalisiereOptionen({ schrift: 'schmal' }, modell).schrift, 'schmal');
  assert.equal(normalisiereOptionen({ schrift: 'krakel' }, modell).schrift, GRAFIK_DEFAULT.schrift);
  assert.equal(normalisiereOptionen({ kontur: false }, modell).kontur, false);
  assert.equal(normalisiereOptionen({}, modell).kontur, true);
});

test('grafikOptionen: gespeicherte Teilmenge bekommt die fehlenden Defaults', () => {
  // store.js mischt FLACH — `grafik` wird beim Speichern komplett ersetzt. Ein später
  // ergänzter Default muss deshalb hier nachgezogen werden, nicht im Store.
  const o = grafikOptionen({ grafik: { format: 'story' } });
  assert.equal(o.format, 'story');
  assert.equal(o.textfarbe, GRAFIK_DEFAULT.textfarbe);
  assert.equal(o.flaechen, GRAFIK_DEFAULT.flaechen);
  assert.equal(o.spaltenkoepfe, GRAFIK_DEFAULT.spaltenkoepfe);
  assert.equal(o.schrift, GRAFIK_DEFAULT.schrift);
  assert.equal(o.kontur, GRAFIK_DEFAULT.kontur);
  // Ohne gespeicherte Werte (auch bei kaputtem Inhalt) die reinen Defaults.
  assert.deepEqual(grafikOptionen(null), GRAFIK_DEFAULT);
  assert.deepEqual(grafikOptionen({ grafik: 'kaputt' }), GRAFIK_DEFAULT);
});

test('grafikDateiname: Ergebnis_<Titel>_<Datum>.png', () => {
  const name = grafikDateiname({ titel: 'VOK / Sontra', datumIso: '2026-09-05T18:00:00.000Z' });
  assert.equal(name, 'Ergebnis_VOK-Sontra_2026-09-05.png');
  assert.match(grafikDateiname({}), /^Ergebnis_Spiel_\d{4}-\d{2}-\d{2}\.png$/);
});
