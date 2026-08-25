import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildKonflikte, adoptErgebnisBlock, adoptAufstellung, aufKey } from '../js/logic/sportwinner-konflikte.js';
import { swSatzWerte, ergKey } from '../js/logic/sportwinner-ergebnis.js';
import { teilsatzRanges } from '../js/logic/teilsaetze.js';

// Classic-Satz: 3 Würfe Volle + 3 Würfe Abräumen.
const CLASSIC = { teilsaetze: [{ modus: 'volle', wuerfe: 3 }, { modus: 'abraeumen', wuerfe: 3 }] };

// Wettkampf mit Sportwinner-Zuordnung: Heim (mA/GG, Slot 0, Startbahn 1), Gast (mB/G, Slot 1, Startbahn 3).
function wettkampf() {
  return {
    sportwinner: {
      spielNr: 5,
      seiten: { mA: 'GG', mB: 'G' },
      spieler: [
        { mannschaftId: 'mA', teamPos: 1, slot: 0, pass: '100', extId: 11 },
        { mannschaftId: 'mB', teamPos: 1, slot: 1, pass: '200', extId: 22 },
      ],
    },
  };
}

function game(bloecke) {
  return {
    id: 'g1', durchgangNr: 1,
    config: {
      saetze: 4, bahnwechsel: 'plus1', bahnListe: [1, 2, 3, 4],
      teilsaetze: [{ modus: 'volle', wuerfe: 3 }, { modus: 'abraeumen', wuerfe: 3 }],
      spielerListe: [
        { mannschaftId: 'mA', teamPos: 1, startBahn: 1, name: 'Heim 1' },
        { mannschaftId: 'mB', teamPos: 1, startBahn: 3, name: 'Gast 1' },
      ],
    },
    erfassung: { bloecke: bloecke || [[], []] },
  };
}

// SW-Live: pro Seite ein Slot mit Pass + 4 Bahnen (volle/abr/fehler).
function swLive({ heimPass = '100', gastPass = '200', heimBahnen = null, gastBahnen = null,
  heimName = 'Heim 1', gastName = 'Gast 1' } = {}) {
  const nullB = () => [0, 1, 2, 3].map(() => ({ volle: 0, abr: 0, fehler: 0 }));
  const [gvn, gnn] = gastName.split(' ');
  const [hvn, hnn] = heimName.split(' ');
  return {
    seiten: {
      GG: { aufstellung: [{ pos: 0, vorname: hvn, nachname: hnn, pass: heimPass, id: 11, bahnen: heimBahnen || nullB() }] },
      G: { aufstellung: [{ pos: 1, vorname: gvn, nachname: gnn, pass: gastPass, id: 22, bahnen: gastBahnen || nullB() }] },
    },
  };
}

test('buildKonflikte: leerer Sportwinner-Stand -> keine Konflikte', () => {
  const k = buildKonflikte(wettkampf(), [game()], swLive());
  assert.equal(k.ergebnis.length, 0);
  assert.equal(k.aufstellung.length, 0);
});

test('buildKonflikte: Ergebnis-Konflikt landet über den Bahnplan (Bahnwechsel) am richtigen Satz', () => {
  // Gast startet Bahn 3 (plus1) -> Sätze auf Bahnen [3,4,1,2] -> Bahn-Slots [2,3,0,1].
  // Sportwinner hat auf Bahn-Slot 2 (= physische Bahn 3) einen Wert; App ist leer -> Konflikt bei Satz 0.
  const gastBahnen = [0, 1, 2, 3].map((b) => (b === 2 ? { volle: 50, abr: 40, fehler: 1 } : { volle: 0, abr: 0, fehler: 0 }));
  const k = buildKonflikte(wettkampf(), [game()], swLive({ gastBahnen }));
  assert.equal(k.ergebnis.length, 1);
  const c = k.ergebnis[0];
  assert.equal(c.key, ergKey('G', 1, 2));
  assert.equal(c.satz, 0);
  assert.equal(c.bahn, 2);
  assert.equal(c.bahnNummer, 3);
  assert.deepEqual(c.sw, { volle: 50, abr: 40, fehler: 1 });
  assert.deepEqual(c.app, { volle: 0, abr: 0, fehler: 0 });
});

test('buildKonflikte: gleiche Werte in App und Sportwinner -> kein Konflikt', () => {
  // App Satz 0 des Gasts = {volle 27, abr 12, fehler 1}; Sportwinner auf Bahn-Slot 2 identisch.
  const block = { wuerfe: [9, 9, 9, 5, 0, 7], overrides: [null, null] }; // volle 27, abr 12, fehler 1
  const app = swSatzWerte(block, teilsatzRanges(CLASSIC));
  assert.deepEqual(app, { volle: 27, abr: 12, fehler: 1 });
  const gastBahnen = [0, 1, 2, 3].map((b) => (b === 2 ? { ...app } : { volle: 0, abr: 0, fehler: 0 }));
  const k = buildKonflikte(wettkampf(), [game([[], [block, {}, {}, {}]])], swLive({ gastBahnen }));
  assert.equal(k.ergebnis.length, 0);
});

test('buildKonflikte: Aufstellungs-Konflikt bei abweichender Passnummer (Auswechslung)', () => {
  const k = buildKonflikte(wettkampf(), [game()], swLive({ gastPass: '999', gastName: 'Max Ersatz' }));
  assert.equal(k.aufstellung.length, 1);
  const c = k.aufstellung[0];
  assert.equal(c.key, aufKey('G', 1));
  assert.equal(c.app.pass, '200');
  assert.equal(c.sw.pass, '999');
  assert.equal(c.sw.name, 'Max Ersatz');
});

test('adoptErgebnisBlock: reproduziert Volle/Abräumen/Fehler exakt (Classic)', () => {
  const sw = { volle: 24, abr: 9, fehler: 1 };
  const block = adoptErgebnisBlock(CLASSIC, sw);
  assert.deepEqual(swSatzWerte(block, teilsatzRanges(CLASSIC)), sw);
  assert.equal(block.done, true);
});

test('adoptErgebnisBlock: nur-Volle-Programm (Bohle) -> abr 0, keine Fehler', () => {
  const bohle = { teilsaetze: [{ modus: 'volle', wuerfe: 3 }, { modus: 'volle', wuerfe: 3 }] };
  const sw = { volle: 31, abr: 0, fehler: 0 };
  const block = adoptErgebnisBlock(bohle, sw);
  assert.deepEqual(swSatzWerte(block, teilsatzRanges(bohle)), sw);
});

test('adoptAufstellung: setzt Namen im Spiel und Pass/Id in der Sportwinner-Zuordnung', () => {
  const k = buildKonflikte(wettkampf(), [game()], swLive({ gastPass: '999', gastName: 'Max Ersatz' })).aufstellung[0];
  const { wettkampf: w, game: g } = adoptAufstellung(wettkampf(), game(), k);
  assert.equal(g.config.spielerListe[1].name, 'Max Ersatz');
  const eintrag = w.sportwinner.spieler.find((p) => p.mannschaftId === 'mB' && p.teamPos === 1);
  assert.equal(eintrag.pass, '999');
  assert.equal(eintrag.extId, 22);
});
