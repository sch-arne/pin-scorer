// Layout der Ergebnis-Grafik: die reine Rechnung (Kürzung, Höhen, Skalierung) ohne Canvas.
// `messText` wird injiziert — im Browser misst ctx.measureText, hier eine Schätzung.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  FORMATE, METRIK, SCHRIFTEN, kuerze, kuerzeName, passeEin, berechneLayout,
} from '../js/logic/grafik-zeichnen.js';
import { GRAFIK_DEFAULT, normalisiereOptionen } from '../js/logic/ergebnis-grafik.js';

// Schätzung statt echter Textmessung: 0,55 × Schriftgröße je Zeichen.
function messText(s, font) {
  const groesse = parseInt(String(font).match(/(\d+)px/)[1], 10);
  return String(s).length * groesse * 0.55;
}
const messMit = (groesse) => (s) => messText(s, `600 ${groesse}px x`);

function mkModell(spieler, extra = {}) {
  const team = (id, name, n) => ({
    id, name, accent: '#f5a623', logo: null, logoBg: 'dark',
    zeilen: Array.from({ length: n }, (_, i) => ({
      name: `Spieler ${i + 1}`, gesamt: 500 + i, ewp: n - i, gespielt: true,
    })),
    summeHolz: 3000, summeEwp: 20, spielpunkte: '3',
  });
  return {
    modus: 'duell', titel: 'Testspiel', untertitel: '05.09.2026 · Halle',
    fertig: true, mitEwp: true, mitSpielpunkte: true, hatLogos: false,
    teams: [team('A', 'Heim', spieler), team('B', 'Gast', spieler)], zeilen: [],
    ...extra,
  };
}

test('kuerze: schneidet erst ab, wenn es nicht passt', () => {
  const mess = messMit(34);
  const kurz = 'Kurz';
  assert.equal(kuerze(kurz, 1000, mess), kurz);
  const lang = 'Ein ziemlich unfassbar langer Mannschaftsname';
  const g = kuerze(lang, 200, mess);
  assert.ok(g.endsWith('…'));
  assert.ok(g.length < lang.length);
  assert.ok(mess(g) <= 200);
  assert.equal(kuerze('', 10, mess), '');
});

test('kuerzeName: erst der Vorname zum Initial, dann zeichenweise', () => {
  const mess = messMit(34);
  const name = 'Christoph Hösel';
  // Passt vollständig.
  assert.equal(kuerzeName(name, 400, mess), name);
  // Zu eng für den vollen Namen, aber genug für „C. Hösel".
  const initial = kuerzeName(name, mess('C. Hösel') + 1, mess);
  assert.equal(initial, 'C. Hösel');
  // Auch dafür zu eng -> zeichenweise mit „…".
  const winzig = kuerzeName(name, 60, mess);
  assert.ok(winzig.endsWith('…'));
  assert.ok(mess(winzig) <= 60);
  // Ein einzelnes Wort hat keine Vorstufe.
  assert.ok(kuerzeName('Unaussprechlichkeitsname', 60, mess).endsWith('…'));
});

test('passeEin: erst kleinere Schrift, dann erst kürzen', () => {
  const passt = passeEin('Kurz', 960, [54, 800], 30, messText);
  assert.equal(passt.text, 'Kurz');
  assert.deepEqual(passt.schrift, [54, 800]);

  // Ein langer Paarungstitel bleibt vollständig, wird aber kleiner gesetzt.
  const lang = 'KV Blau Weiß Sontra 1 – VOK Osnabrück 1';
  const eng = passeEin(lang, 960, [54, 800], 30, messText);
  assert.equal(eng.text, lang, 'Titel wurde gekürzt statt verkleinert');
  assert.ok(eng.schrift[0] < 54);
  assert.ok(eng.schrift[0] >= 30);
  assert.ok(messText(eng.text, `800 ${eng.schrift[0]}px x`) <= 960);

  // Auch die kleinste Stufe reicht irgendwann nicht mehr — dann wird gekürzt.
  const riesig = passeEin(lang.repeat(4), 960, [54, 800], 30, messText);
  assert.equal(riesig.schrift[0], 30);
  assert.ok(riesig.text.endsWith('…'));
});

test('berechneLayout: langer Titel läuft nicht über die Bildbreite hinaus', () => {
  const modell = mkModell(6, { titel: 'KV Blau Weiß Sontra 1 – VOK Osnabrück 1' });
  const L = berechneLayout(modell, normalisiereOptionen(GRAFIK_DEFAULT, modell), messText);
  const breite = messText(L.titel.text, `${L.titel.schrift[1]} ${L.titel.schrift[0]}px x`);
  assert.ok(breite <= 1080 - 2 * METRIK.rand, 'Titel ist breiter als der Inhaltsbereich');
  // Auch die Mannschaftsnamen bleiben in ihrer Hälfte.
  L.teams.forEach((t) => {
    const w = messText(t.kopf.text, `${t.kopf.schrift[1]} ${t.kopf.schrift[0]}px x`);
    assert.ok(w <= L.geo.halb, 'Mannschaftsname läuft über seine Hälfte hinaus');
  });
});

test('berechneLayout: 6er-Mannschaften passen in beide Formate ohne Verkleinerung', () => {
  const modell = mkModell(6);
  ['hoch', 'story'].forEach((format) => {
    const opts = normalisiereOptionen({ ...GRAFIK_DEFAULT, format }, modell);
    const L = berechneLayout(modell, opts, messText);
    assert.equal(L.skala, 1, format);
    assert.equal(L.fmt, FORMATE[format]);
    const [oben, unten] = FORMATE[format].korridor;
    assert.ok(L.yTop >= oben - 0.001, format);
    assert.ok(L.yTop + L.hoehe <= unten + 0.001, format);
    assert.equal(L.y.zeilen.length, 6);
  });
});

test('berechneLayout: sehr viele Spieler werden verkleinert statt überzulaufen', () => {
  const modell = mkModell(16);
  const opts = normalisiereOptionen({ ...GRAFIK_DEFAULT, format: 'hoch' }, modell);
  const L = berechneLayout(modell, opts, messText);
  assert.ok(L.skala < 1);
  const [oben, unten] = FORMATE.hoch.korridor;
  assert.ok(L.hoehe * L.skala <= (unten - oben) + 0.001);
  assert.ok(L.yTop >= oben - 0.001);
});

test('berechneLayout: Position steuert die vertikale Lage', () => {
  const modell = mkModell(4);
  const bau = (position) => berechneLayout(modell,
    normalisiereOptionen({ ...GRAFIK_DEFAULT, position }, modell), messText);
  const [oben, unten] = FORMATE.hoch.korridor;
  assert.equal(bau('oben').yTop, oben);
  assert.equal(bau('unten').yTop, unten - bau('unten').hoehe);
  const mitte = bau('mitte');
  assert.ok(mitte.yTop > oben && mitte.yTop + mitte.hoehe < unten);
});

test('berechneLayout: ohne EWP wird die Namensspalte breiter', () => {
  const modell = mkModell(6);
  const mit = berechneLayout(modell, normalisiereOptionen(GRAFIK_DEFAULT, modell), messText);
  const ohne = berechneLayout(modell,
    normalisiereOptionen({ ...GRAFIK_DEFAULT, ewp: false }, modell), messText);
  assert.equal(mit.mitEwp, true);
  assert.equal(ohne.mitEwp, false);
  assert.equal(mit.geo.breiten.name, METRIK.spalten.mitEwp.name);
  assert.equal(ohne.geo.breiten.name, METRIK.spalten.ohneEwp.name);
  // Beide Seiten bleiben gleich breit und die Mitte frei.
  [mit, ohne].forEach((L) => {
    assert.equal(L.geo.links.x1 - L.geo.links.x0, L.geo.halb);
    assert.equal(L.geo.rechts.x0 - L.geo.links.x1, METRIK.mitte);
    assert.equal(L.geo.rechts.x1, 1080 - METRIK.rand);
  });
});

test('berechneLayout: Zeilen ohne Würfe bekommen einen Strich statt einer 0', () => {
  const modell = mkModell(2);
  modell.teams[0].zeilen[1] = { name: 'Noch offen', gesamt: 0, ewp: 0, gespielt: false };
  const L = berechneLayout(modell, normalisiereOptionen(GRAFIK_DEFAULT, modell), messText);
  assert.equal(L.teams[0].zeilen[0].holzText, '500');
  assert.equal(L.teams[0].zeilen[1].holzText, '–');
  assert.equal(L.teams[0].zeilen[1].ewpText, '–');
});

test('berechneLayout: Listen-Modus rechnet einspaltig', () => {
  const modell = {
    modus: 'liste', titel: 'Training', untertitel: '', fertig: true,
    mitEwp: false, mitSpielpunkte: false, hatLogos: false, teams: [],
    zeilen: [
      { rang: 1, name: 'Anna Beispiel', gesamt: 540, gespielt: true },
      { rang: 2, name: 'Bernd Beispiel', gesamt: 500, gespielt: true },
    ],
  };
  const L = berechneLayout(modell, normalisiereOptionen(GRAFIK_DEFAULT, modell), messText);
  assert.equal(L.duell, false);
  assert.equal(L.geo, null);
  assert.equal(L.liste.length, 2);
  assert.equal(L.liste[0].holzText, '540');
  assert.equal(L.y.zeilen.length, 2);
  assert.equal(L.skala, 1);
});

test('berechneLayout: ohne Titel und Untertitel fehlen deren Höhen', () => {
  const modell = mkModell(6, { titel: '', untertitel: '' });
  const opts = normalisiereOptionen(GRAFIK_DEFAULT, modell);
  const ohne = berechneLayout(modell, opts, messText);
  const mit = berechneLayout(mkModell(6), opts, messText);
  assert.equal(ohne.y.titel, undefined);
  assert.equal(ohne.y.untertitel, undefined);
  assert.equal(mit.hoehe - ohne.hoehe, METRIK.hoehen.titel + METRIK.hoehen.untertitel);
});

test('Spaltenmaße füllen jede Hälfte exakt aus', () => {
  const modell = mkModell(6);
  const halb = (1080 - 2 * METRIK.rand - METRIK.mitte) / 2;
  [true, false].forEach((mitEwp) => {
    const L = berechneLayout(modell,
      normalisiereOptionen({ ...GRAFIK_DEFAULT, ewp: mitEwp }, modell), messText);
    const b = L.geo.breiten;
    const spalten = mitEwp ? 3 : 2;
    assert.equal(L.geo.halb, halb);
    // Restlos aufgeteilt: was die Zahlenspalten nicht brauchen, gehört den Namen.
    assert.equal(b.name + b.holz + b.ewp + (spalten - 1) * METRIK.spaltenLuft, halb,
      `Spalten passen nicht in die Hälfte (mitEwp=${mitEwp})`);
  });
});

test('Namensspalte bietet Platz für übliche Kegelnamen', () => {
  // Zwei lange, aber ganz normale Namen müssen bei voller Schriftgröße hineinpassen.
  const namen = ['Christoph Hösel', 'Malte Schier'];
  const modell = mkModell(2);
  modell.teams[0].zeilen[0].name = namen[0];
  modell.teams[0].zeilen[1].name = namen[1];
  const L = berechneLayout(modell, normalisiereOptionen(GRAFIK_DEFAULT, modell), messText);
  assert.deepEqual(L.namenGroesse, METRIK.schrift.name, 'Namen mussten verkleinert werden');
  L.teams[0].zeilen.forEach((z, i) => {
    assert.equal(z.nameKurz, namen[i], 'Name wurde gekürzt');
  });
});

test('Schriftwahl geht in jede Messung und ins Layout ein', () => {
  const modell = mkModell(6);
  const gesehen = [];
  const spion = (s, font) => { gesehen.push(font); return messText(s, font); };
  const L = berechneLayout(modell,
    normalisiereOptionen({ ...GRAFIK_DEFAULT, schrift: 'serif' }, modell), spion);
  assert.equal(L.familie, SCHRIFTEN.serif.stack);
  assert.ok(gesehen.length > 0, 'es wurde nichts gemessen');
  assert.ok(gesehen.every((f) => f.endsWith(SCHRIFTEN.serif.stack)),
    'gemessen wurde mit einer anderen Schrift als gezeichnet wird');
  // Unbekannte Auswahl fällt auf die Systemschrift zurück.
  const standard = berechneLayout(modell,
    normalisiereOptionen({ ...GRAFIK_DEFAULT, schrift: 'krakel' }, modell), messText);
  assert.equal(standard.familie, SCHRIFTEN.system.stack);
});
