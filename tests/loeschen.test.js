// Was „Löschen" bedeutet, hängt davon ab, wo ein Spiel liegt und wem es gehört —
// die Entscheidung selbst (logic/loeschen.js) ohne Store, DOM und Netz.

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  KOMPLETT, VERBERGEN, NUR_HIER, GESPERRT,
  loeschart, darfLoeschen, loeschFrage, ohneVerborgene,
} from '../js/logic/loeschen.js';

const ICH = 'konto-1';

test('Ohne Gegenpart in der Datenbank wird komplett gelöscht', () => {
  assert.equal(loeschart({ id: 'g1' }, { konto: ICH }), KOMPLETT);
  assert.equal(loeschart({ id: 'g1', remoteId: '' }, { konto: ICH }), KOMPLETT);
});

test('Ein eigenes Spiel aus der Datenbank wird verborgen, nicht gelöscht', () => {
  assert.equal(loeschart({ id: 'r-1', remoteId: '1' }, { konto: ICH }), VERBERGEN);
  assert.equal(loeschart({ id: 'r-1', remoteId: '1', besitzer: ICH }, { konto: ICH }), VERBERGEN);
});

test('Ein fremd erfasstes Spiel ohne Kopie hier lässt sich gar nicht entfernen', () => {
  // Der Fall „kam über meine LizenzID": die Zeile gehört mir, das SPIEL nicht — und auf
  // diesem Gerät liegt nichts davon. Es gibt schlicht nichts zu entfernen.
  assert.equal(loeschart({ id: 'r-1', remoteId: '1', besitzer: 'konto-2' }, { konto: ICH }), GESPERRT);
  // Ersatzweg, wenn nur die Ergebniszeile vorliegt.
  assert.equal(loeschart({ id: 'r-1', remoteId: '1' }, { konto: ICH, erfasstVon: 'konto-2' }), GESPERRT);
});

test('Einem fremden Spiel beigetreten: die Kopie auf DIESEM Gerät darf weg', () => {
  // Fortsetzen-Liste auf dem Tablet: das Spiel läuft anderswo weiter, meine Kopie geht.
  const fremd = { id: 'r-1', remoteId: '1', besitzer: 'konto-2' };
  assert.equal(loeschart(fremd, { konto: ICH, lokal: true }), NUR_HIER);
  assert.equal(darfLoeschen(NUR_HIER), true);
  // Am fremden Spiel selbst wird nichts angefasst — das sagt die Frage auch.
  const frage = loeschFrage(NUR_HIER);
  assert.match(frage, /von diesem Gerät entfernen/);
  assert.match(frage, /bleibt alles unverändert/);
  assert.match(frage, /wieder beitreten/);
});

test('Beim eigenen Spiel schlägt Verbergen das blosse Entfernen der Kopie', () => {
  // `lokal` darf die Entscheidung nur bei FREMDEN Spielen beeinflussen.
  const meins = { id: 'r-1', remoteId: '1', besitzer: ICH };
  assert.equal(loeschart(meins, { konto: ICH, lokal: true }), VERBERGEN);
  assert.equal(loeschart(meins, { konto: ICH, lokal: false }), VERBERGEN);
});

test('Der Besitzer am Objekt schlägt den Erfasser der Ergebniszeile', () => {
  assert.equal(
    loeschart({ id: 'r-1', remoteId: '1', besitzer: ICH }, { konto: ICH, erfasstVon: 'konto-2' }),
    VERBERGEN,
  );
});

test('Ohne bekanntes Konto gilt ein fremder Besitzer weiterhin als fremd', () => {
  // Offline/abgemeldet ist die vorsichtige Antwort „nur die eigene Kopie" — nie „verbergen",
  // denn ein Vermerk fürs Konto liesse sich ohnehin nicht schreiben.
  assert.equal(loeschart({ id: 'r-1', remoteId: '1', besitzer: 'konto-2' }, {}), GESPERRT);
  assert.equal(loeschart({ id: 'r-1', remoteId: '1', besitzer: 'konto-2' }, { lokal: true }), NUR_HIER);
  assert.equal(loeschart({ id: 'g1' }, {}), KOMPLETT);
});

test('Kein Objekt ist nicht löschbar', () => {
  assert.equal(loeschart(null, { konto: ICH, lokal: true }), GESPERRT);
  assert.equal(darfLoeschen(GESPERRT), false);
  assert.equal(darfLoeschen(KOMPLETT), true);
  assert.equal(darfLoeschen(VERBERGEN), true);
});

test('Die Frage benennt den Unterschied: endgültig weg vs. bleibt bestehen', () => {
  const lokal = loeschFrage(KOMPLETT);
  assert.match(lokal, /endgültig/);
  assert.match(lokal, /nur auf diesem Gerät/);

  const db = loeschFrage(VERBERGEN);
  assert.match(db, /bleiben in der Datenbank bestehen/);
  assert.doesNotMatch(db, /endgültig/);
  // Und der Punkt, auf den es ankommt: es trifft NUR mich, nicht die Mitspieler.
  assert.match(db, /nur für dich/);
  assert.match(db, /Freigabe-Link .*gilt weiter/);
  assert.doesNotMatch(db, /deaktiviert/);

  // Beim Wettkampf hängen die Durchgänge dran; das Overlay läuft ausdrücklich weiter.
  assert.match(loeschFrage(KOMPLETT, { wettkampf: true }), /allen Durchgängen/);
  assert.match(loeschFrage(KOMPLETT, { wettkampf: true }), /Er liegt nur auf diesem Gerät/);
  assert.match(loeschFrage(VERBERGEN, { wettkampf: true }), /OBS-Overlay\) gilt weiter/);

  assert.equal(loeschFrage(GESPERRT), '');
});

// --- Was ich entfernt habe, zählt auch nicht mehr ---------------------------
// Die Kennzahlen der Account-Statistik (Spiele, Ø Gesamt, bester Satz) rechnen über genau
// diese Liste. Was hier durchrutscht, färbt die Statistik weiter — obwohl die Karte weg ist.

const erg = (id, spiel, extra = {}) => ({ id, spiel_id: spiel, gesamt: 500, ...extra });

test('Ergebnisse eines entfernten Spiels fallen aus der eigenen Statistik', () => {
  const rows = [erg('e1', 's1'), erg('e2', 's2')];
  const uebrig = ohneVerborgene(rows, new Set(['s1']));
  assert.deepEqual(uebrig.map((r) => r.id), ['e2']);
});

test('Gefiltert wird am SPIEL — beide Wege ins Profil sind damit erfasst', () => {
  // Dieselbe Zusage muss für die ausdrückliche Zuordnung (profil_id) UND für den Fund über
  // die eigene LizenzID (passnummer) gelten. Die Passnummer bleibt an der Zeile stehen, das
  // Spiel ist trotzdem raus.
  const rows = [
    erg('zugeordnet', 's1', { profil_id: 'konto-1' }),
    erg('ueber-lizenz', 's1', { passnummer: '123456' }),
    erg('anderes', 's2', { passnummer: '123456' }),
  ];
  assert.deepEqual(ohneVerborgene(rows, new Set(['s1'])).map((r) => r.id), ['anderes']);
});

test('Ein entfernter Wettkampf nimmt seine Durchgänge mit', () => {
  // sync.verbergeWettkampf trägt jeden Durchgang einzeln ein — sonst blieben genau die
  // Ergebnisse stehen, die man selbst geworfen hat.
  const rows = [erg('dg1', 'd1'), erg('dg2', 'd2'), erg('fremd', 's9')];
  assert.deepEqual(ohneVerborgene(rows, new Set(['d1', 'd2'])).map((r) => r.id), ['fremd']);
});

test('Ohne verborgene Spiele bleibt die Liste unangetastet', () => {
  const rows = [erg('e1', 's1')];
  assert.deepEqual(ohneVerborgene(rows, new Set()), rows);
  assert.deepEqual(ohneVerborgene(rows, null), rows);
  assert.deepEqual(ohneVerborgene(null, new Set(['s1'])), []);
});
