// Modell und Layout der Spieler-Grafik (Ergebnisansicht eines Einzelspielers).
//
// Die heiklen Fälle sind erfahrungsgemäß: ein Spieler wird über MEHRERE Durchgänge hinweg
// eindeutig gefunden, ein Satz ohne Einzelwürfe (Import/Override) darf keine erfundenen
// Würfe zeigen, und ein langer Teilsatz muss umbrechen statt aus dem Bild zu laufen.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  spielerKey, spielerQuellen, spielerGrafikModell, spielerGrafikOptionen,
  normalisiereSpielerOptionen, spielerGrafikDateiname, spielerTextId, SPIELER_GRAFIK_DEFAULT,
} from '../js/logic/spieler-grafik.js';
import {
  berechneSpielerLayout, zellenAufteilung, spaltenGeometrie, sortiereSaetze, SP_METRIK,
} from '../js/logic/spieler-zeichnen.js';

// Schätzung statt echter Textmessung — wie in tests/grafik-zeichnen.test.js.
function messText(s, font) {
  const groesse = parseInt(String(font).match(/(\d+)px/)[1], 10);
  return String(s).length * groesse * 0.55;
}

// Ein Satz-Block mit Einzelwürfen. `kegel` optional (sonst kein Kegelbild).
function blk(wuerfe, { kegel = null, overrides = [null, null], done = true, satzOverride = null } = {}) {
  const b = {
    wuerfe: wuerfe.slice(),
    kegel: wuerfe.map((n, i) => (kegel && kegel[i] !== undefined ? kegel[i] : null)),
    koenig: wuerfe.map(() => false),
    overrides: overrides.slice(),
    done,
  };
  if (satzOverride != null) b.satzOverride = satzOverride;
  return b;
}

// Ein Spiel mit 2 Sätzen à 4 Würfen (2 Teilsätze Volle/Kranz-Abräumen à 2 Würfe).
function mkGame(id, spielerListe, bloecke) {
  return {
    id,
    createdAt: '2026-09-05T18:00:00.000Z',
    config: {
      spielerListe,
      saetze: 2,
      ersteBahn: 1,
      wuerfeProSatz: 4,
      teilsaetze: [{ modus: 'volle', wuerfe: 2 }, { modus: 'kranz-abraeumen', wuerfe: 2 }],
    },
    erfassung: { bloecke },
  };
}

test('spielerQuellen: Einzelspiel in Aufstellungsreihenfolge, mit stabilem Schlüssel', () => {
  const game = mkGame('g1', [{ name: 'Anna' }, { name: 'Bert' }], [
    [blk([9, 8, 7, 6]), blk([5, 4, 3, 2])],
    [blk([1, 2, 3, 4]), blk([5, 6, 7, 8])],
  ]);
  const q = spielerQuellen({ game });
  assert.deepEqual(q.map((x) => x.name), ['Anna', 'Bert']);
  assert.equal(q[0].key, spielerKey('g1', 0));
  assert.equal(q[1].key, spielerKey('g1', 1));
  // Ohne Aufstellung gibt es nichts zu wählen.
  assert.deepEqual(spielerQuellen({}), []);
  assert.deepEqual(spielerQuellen(null), []);
});

test('spielerQuellen: Wettkampf sortiert nach Mannschaft und Aufstellung, über alle Durchgänge', () => {
  const g1 = mkGame('g1', [
    { name: 'Heim 1', mannschaftId: 'm1', teamPos: 1, startBahn: 1 },
    { name: 'Gast 1', mannschaftId: 'm2', teamPos: 1, startBahn: 2 },
  ], [[blk([9, 9, 9, 9])], [blk([2, 2, 2, 2])]]);
  const g2 = mkGame('g2', [
    { name: 'Heim 2', mannschaftId: 'm1', teamPos: 2, startBahn: 1 },
    { name: 'Gast 2', mannschaftId: 'm2', teamPos: 2, startBahn: 2 },
  ], [[blk([8, 8, 8, 8])], [blk([3, 3, 3, 3])]]);
  const wettkampf = {
    id: 'w1', name: 'Derby', datum: '2026-09-05',
    mannschaften: [{ id: 'm1', name: 'Heim' }, { id: 'm2', name: 'Gast' }],
    durchgaenge: [{ nr: 1, gameId: 'g1' }, { nr: 2, gameId: 'g2' }],
  };
  const q = spielerQuellen({ wettkampf, games: [g1, g2] });
  // Erst alle der ersten Mannschaft (nach teamPos), dann die der zweiten.
  assert.deepEqual(q.map((x) => x.name), ['Heim 1', 'Heim 2', 'Gast 1', 'Gast 2']);
  assert.deepEqual(q.map((x) => x.mannschaft), ['Heim', 'Heim', 'Gast', 'Gast']);
  // Gleiche Position in verschiedenen Durchgängen ist trotzdem eindeutig.
  assert.equal(new Set(q.map((x) => x.key)).size, 4);
  assert.equal(q[1].key, spielerKey('g2', 0));
});

test('Modell: Einzelwürfe, Teilsatz- und Satzergebnisse eines Spielers', () => {
  const game = mkGame('g1', [{ name: 'Anna' }, { name: 'Bert' }], [
    [blk([9, 5, 4, 2]), blk([3, 3, 1, 1])],
    [blk([1, 1, 1, 1]), blk([2, 2, 2, 2])],
  ]);
  const m = spielerGrafikModell({ game }, spielerKey('g1', 0));
  assert.equal(m.name, 'Anna');
  assert.equal(m.saetze.length, 2);
  // Satz 1: Volle 9+5, Kranz-Abräumen 4+2 -> 20 Holz.
  assert.equal(m.saetze[0].holz, 20);
  assert.deepEqual(m.saetze[0].teilsaetze.map((t) => t.holz), [14, 6]);
  assert.deepEqual(m.saetze[0].teilsaetze[0].wuerfe.map((w) => w.wert), [9, 5]);
  assert.deepEqual(m.saetze[0].teilsaetze[1].wuerfe.map((w) => w.wert), [4, 2]);
  // Die Wurfnummer zählt innerhalb des Satzes weiter (nicht je Teilsatz von vorn).
  assert.deepEqual(m.saetze[0].teilsaetze[1].wuerfe.map((w) => w.nr), [3, 4]);
  assert.equal(m.gesamt, 28);
  // Teilsatz-Summen über beide Sätze: Volle 9+5+3+3, Kranz 4+2+1+1.
  assert.deepEqual(m.summen, [{ label: 'Volle', val: 20 }, { label: 'Kranz-Abräumen', val: 8 }]);
  assert.equal(m.neuner, 1);
  assert.equal(m.hatWuerfe, true);
  assert.equal(m.hatKegel, false); // ohne kegel[] gibt es kein Bild
  assert.equal(m.leer, false);
});

test('Modell: unbekannter Schlüssel nimmt den ersten Spieler, kaputte Daten ein leeres Modell', () => {
  const game = mkGame('g1', [{ name: 'Anna' }], [[blk([9, 9, 9, 9])]]);
  assert.equal(spielerGrafikModell({ game }, 'gibt-es-nicht').name, 'Anna');
  assert.equal(spielerGrafikModell({ game }, '').name, 'Anna');
  assert.equal(spielerGrafikModell({}, 'x').leer, true);
  assert.equal(spielerGrafikModell(null, '').saetze.length, 0);
});

test('Modell: Fehlwürfe, 9er und Kegelbilder kommen aus den Blöcken', () => {
  const game = mkGame('g1', [{ name: 'Anna' }], [[
    blk([9, 0, 4, 2], { kegel: [[1, 2, 3, 4, 5, 6, 7, 8, 9], [], null, null] }),
  ]]);
  const m = spielerGrafikModell({ game }, '');
  const w = m.saetze[0].teilsaetze[0].wuerfe;
  assert.equal(w[0].neuner, true);
  assert.deepEqual(w[0].kegel, [1, 2, 3, 4, 5, 6, 7, 8, 9]);
  assert.equal(w[1].fehl, true);
  assert.deepEqual(w[1].kegel, []);
  assert.equal(m.hatKegel, true);
  assert.equal(m.fehl, 1);
});

test('Modell: nur eingetragene Ergebnisse liefern Holz, aber keine erfundenen Würfe', () => {
  // Teilsatz-Overrides ohne Einzelwürfe — der Fall „aus der Übersicht nachgetragen".
  const game = mkGame('g1', [{ name: 'Anna' }], [[blk([], { overrides: [11, 7] })]]);
  const m = spielerGrafikModell({ game }, '');
  assert.equal(m.saetze[0].holz, 18);
  assert.deepEqual(m.saetze[0].teilsaetze.map((t) => t.holz), [11, 7]);
  assert.deepEqual(m.saetze[0].teilsaetze.map((t) => t.manual), [true, true]);
  assert.deepEqual(m.saetze[0].teilsaetze.map((t) => t.wuerfe.length), [0, 0]);
  assert.equal(m.hatWuerfe, false);
  // Ohne Einzelwürfe darf kein Schalter etwas versprechen, was es nicht gibt.
  const o = normalisiereSpielerOptionen(SPIELER_GRAFIK_DEFAULT, m);
  assert.equal(o.kegelbilder, false);
  assert.equal(o.wurfnummern, false);
});

test('Modell: Satz-Ergebnis ohne Teilsatz-Aufteilung ist als solches markiert', () => {
  // Web-Import: der Satz trägt sein Holz selbst, die Teilsätze sind unbekannt.
  const game = mkGame('g1', [{ name: 'Anna' }], [[blk([], { satzOverride: 42 })]]);
  const m = spielerGrafikModell({ game }, '');
  assert.equal(m.saetze[0].holz, 42);
  assert.equal(m.saetze[0].nurSatz, true);
  assert.deepEqual(m.saetze[0].teilsaetze.map((t) => t.ohneTeilsatz), [true, true]);
  // In die Teilsatz-Summen fließt so ein Satz nicht ein — sonst stünde dort eine 0 als Aussage.
  assert.deepEqual(m.summen.map((x) => x.val), [0, 0]);
});

test('Modell: noch nicht gespielter Satz ist nicht „0 Holz"', () => {
  const game = mkGame('g1', [{ name: 'Anna' }], [[
    blk([9, 9, 9, 9]),
    { wuerfe: [], kegel: [], koenig: [], overrides: [null, null], done: false },
  ]]);
  const m = spielerGrafikModell({ game }, '');
  assert.equal(m.saetze[0].gespielt, true);
  assert.equal(m.saetze[1].gespielt, false);
  const L = berechneSpielerLayout(m, normalisiereSpielerOptionen(SPIELER_GRAFIK_DEFAULT, m), messText);
  assert.equal(L.saetze[0].holzText, '36');
  assert.equal(L.saetze[1].holzText, '–');
});

test('Modell: Untertitel nimmt Mannschaft und die durchgereichte Kontextzeile', () => {
  const g1 = mkGame('g1', [{ name: 'Heim 1', mannschaftId: 'm1', teamPos: 1 }], [[blk([9, 9, 9, 9])]]);
  const wettkampf = {
    id: 'w1', name: 'Derby', datum: '2026-09-05',
    mannschaften: [{ id: 'm1', name: 'VOK Osnabrück 1' }],
    durchgaenge: [{ nr: 1, gameId: 'g1' }],
  };
  const roh = { wettkampf, games: [g1] };
  const m = spielerGrafikModell(roh, '', { untertitel: 'Derby-Abend' });
  assert.equal(m.titel, 'Heim 1');
  assert.equal(m.untertitel, 'VOK Osnabrück 1 · Derby-Abend');
  // Ohne eigenen Text fällt es auf Wettkampfname und Datum zurück.
  const ohne = spielerGrafikModell(roh, '', {});
  assert.ok(ohne.untertitel.startsWith('VOK Osnabrück 1 · Derby'));
  // Steht die Mannschaft schon in der Kontextzeile (Punktspiel „Heim – Gast"), nicht doppelt.
  const doppelt = spielerGrafikModell(roh, '', { untertitel: 'VOK Osnabrück 1 – KV Sontra 1' });
  assert.equal(doppelt.untertitel, 'VOK Osnabrück 1 – KV Sontra 1');
});

test('Layout: eine freie Überschrift steht ÜBER dem Namen und verdrängt ihn nicht', () => {
  const game = mkGame('g1', [{ name: 'Anna' }], [[blk([9, 9, 9, 9])]]);
  const ohne = spielerGrafikModell({ game }, '', {});
  const mit = spielerGrafikModell({ game }, '', { ueberschrift: 'Bestleistung' });
  assert.equal(ohne.ueberschrift, '');
  assert.equal(mit.ueberschrift, 'Bestleistung');
  assert.equal(mit.titel, 'Anna', 'der Name bleibt die große Zeile');
  const opts = normalisiereSpielerOptionen(SPIELER_GRAFIK_DEFAULT, mit);
  const LOhne = berechneSpielerLayout(ohne, opts, messText);
  const LMit = berechneSpielerLayout(mit, opts, messText);
  assert.equal(LOhne.ueberschrift.text, '');
  assert.equal(LOhne.y.ueberschrift, undefined, 'ohne Text darf die Zeile keinen Platz kosten');
  assert.equal(LMit.ueberschrift.text, 'Bestleistung');
  assert.ok(LMit.y.ueberschrift < LMit.y.titel, 'die Überschrift steht über dem Namen');
  assert.ok(LMit.y.titel < LMit.y.untertitel, 'die Kontextzeile bleibt unter dem Namen');
  assert.ok(LMit.hoehe > LOhne.hoehe, 'die zusätzliche Zeile braucht Platz');
});

test('Reihenfolge: nach Bahnen sortiert, ohne einen Satz zu verlieren', () => {
  // Ein Spieler, der auf Bahn 3 beginnt und reihum wechselt: Satz 1=B3, 2=B4, 3=B1, 4=B2.
  const saetze = [
    { nr: 1, bahn: 3 }, { nr: 2, bahn: 4 }, { nr: 3, bahn: 1 }, { nr: 4, bahn: 2 },
  ];
  assert.deepEqual(sortiereSaetze(saetze, 'saetze').map((s) => s.nr), [1, 2, 3, 4]);
  assert.deepEqual(sortiereSaetze(saetze, 'bahnen').map((s) => s.nr), [3, 4, 1, 2]);
  assert.deepEqual(sortiereSaetze(saetze, 'bahnen').map((s) => s.bahn), [1, 2, 3, 4]);
  // Die Vorlage bleibt unberührt, und eine unbekannte Bahn wandert ans Ende statt zu stören.
  assert.deepEqual(saetze.map((s) => s.nr), [1, 2, 3, 4]);
  const krumm = [{ nr: 1, bahn: null }, { nr: 2, bahn: 2 }];
  assert.deepEqual(sortiereSaetze(krumm, 'bahnen').map((s) => s.nr), [2, 1]);
  assert.equal(sortiereSaetze(null, 'bahnen').length, 0);
});

test('Reihenfolge: die Kopfzeile nennt vorn, wonach sortiert wurde', () => {
  const game = mkGame('g1', [{ name: 'Anna', startBahn: 2 }], [[blk([9, 9, 9, 9]), blk([8, 8, 8, 8])]]);
  game.config.bahnplan = [[2, 1]]; // Satz 1 auf Bahn 2, Satz 2 auf Bahn 1
  const m = spielerGrafikModell({ game }, '');
  const basis = normalisiereSpielerOptionen(SPIELER_GRAFIK_DEFAULT, m);

  const nachSaetzen = berechneSpielerLayout(m, { ...basis, reihenfolge: 'saetze' }, messText);
  assert.deepEqual(nachSaetzen.saetze.map((s) => s.label), ['1. Satz', '2. Satz']);
  assert.deepEqual(nachSaetzen.saetze.map((s) => s.bahnLabel), ['Bahn 2', 'Bahn 1']);

  const nachBahnen = berechneSpielerLayout(m, { ...basis, reihenfolge: 'bahnen' }, messText);
  assert.deepEqual(nachBahnen.saetze.map((s) => s.label), ['Bahn 1', 'Bahn 2']);
  assert.deepEqual(nachBahnen.saetze.map((s) => s.bahnLabel), ['2. Satz', '1. Satz']);
  // Die Ergebnisse wandern mit ihrem Satz mit — Bahn 1 ist der zweite Satz (32 Holz).
  assert.deepEqual(nachBahnen.saetze.map((s) => s.holzText), ['32', '36']);
  // Unsinn in den Optionen fällt auf die Spielreihenfolge zurück.
  assert.equal(normalisiereSpielerOptionen({ reihenfolge: 'zufall' }, m).reihenfolge, 'saetze');
});

test('Modell: der eigene Name schlägt den aus der Aufstellung — auch im Dateinamen', () => {
  const game = mkGame('g1', [{ name: 'Anna' }], [[blk([9, 9, 9, 9])]]);
  const ohne = spielerGrafikModell({ game }, '', {});
  assert.equal(ohne.titel, 'Anna');
  assert.equal(ohne.eigenerTitel, '');
  const mit = spielerGrafikModell({ game }, '', { titel: '  Anna räumt ab  ' });
  assert.equal(mit.titel, 'Anna räumt ab');
  assert.equal(mit.name, 'Anna', 'der Name bleibt am Modell — die Auswahlliste braucht ihn');
  assert.ok(spielerGrafikDateiname(mit).startsWith('Wurfbild_Anna-räumt-ab_'));
  assert.ok(spielerGrafikDateiname(ohne).startsWith('Wurfbild_Anna_'));
  // Und sie steht auch wirklich im Bild.
  const L = berechneSpielerLayout(mit, normalisiereSpielerOptionen(SPIELER_GRAFIK_DEFAULT, mit), messText);
  assert.equal(L.titel.text, 'Anna räumt ab');
});

test('spielerTextId: eigener Namensraum neben den Texten der Ergebnis-Grafik', () => {
  assert.equal(spielerTextId('g1#0'), 'spieler:g1#0');
  assert.notEqual(spielerTextId('g1#0'), 'sp:g1');
  assert.equal(spielerTextId(''), '');
});

test('Logo: kommt von der Mannschaft des Spielers und macht im Kopf Platz', () => {
  const g1 = mkGame('g1', [
    { name: 'Heim 1', mannschaftId: 'm1', teamPos: 1 },
    { name: 'Gast 1', mannschaftId: 'm2', teamPos: 1 },
  ], [[blk([9, 9, 9, 9])], [blk([5, 5, 5, 5])]]);
  const wettkampf = {
    id: 'w1', name: 'Derby', datum: '2026-09-05',
    mannschaften: [
      { id: 'm1', name: 'Heim', logo: 'data:image/png;base64,AAA', logoBg: 'light', accent: '#123456' },
      { id: 'm2', name: 'Gast' },
    ],
    durchgaenge: [{ nr: 1, gameId: 'g1' }],
  };
  const roh = { wettkampf, games: [g1] };
  const heim = spielerGrafikModell(roh, spielerKey('g1', 0));
  assert.equal(heim.hatLogo, true);
  assert.equal(heim.logo, 'data:image/png;base64,AAA');
  assert.equal(heim.logoBg, 'light');
  assert.equal(heim.accent, '#123456');
  assert.equal(heim.mannschaftId, 'm1');

  // Die andere Mannschaft hat keines — dann ist der Schalter nicht wählbar.
  const gast = spielerGrafikModell(roh, spielerKey('g1', 1));
  assert.equal(gast.hatLogo, false);
  assert.equal(normalisiereSpielerOptionen({ ...SPIELER_GRAFIK_DEFAULT, logo: true }, gast).logo, false);
  // Und eine unsinnige Akzentfarbe fällt auf den Standard zurück.
  assert.match(gast.accent, /^#[0-9a-f]{6}$/i);

  const opts = normalisiereSpielerOptionen(SPIELER_GRAFIK_DEFAULT, heim);
  assert.equal(opts.logo, true);
  const mit = berechneSpielerLayout(heim, opts, messText);
  const ohne = berechneSpielerLayout(heim, { ...opts, logo: false }, messText);
  assert.equal(mit.mitLogo, true);
  assert.equal(ohne.mitLogo, false);
  // Der Kopftext rückt nach rechts, statt unter dem Logo zu stehen.
  assert.ok(mit.y.kopfMitte > ohne.y.kopfMitte, 'der Kopftext müsste nach rechts rücken');
  assert.equal(ohne.y.kopfMitte, 540);
  assert.ok(mit.y.logo.x < mit.y.kopfMitte, 'das Logo steht links vom Text');
  assert.ok(mit.y.logo.oben >= 0);
});

test('Optionen: gespeicherte Wahl wird ergänzt, Unsinn zurückgesetzt', () => {
  assert.deepEqual(spielerGrafikOptionen({}), SPIELER_GRAFIK_DEFAULT);
  assert.equal(spielerGrafikOptionen({ spielerGrafik: { format: 'story' } }).format, 'story');
  // Ein später ergänzter Standard erreicht auch alte Einstellungen.
  assert.equal(spielerGrafikOptionen({ spielerGrafik: { format: 'story' } }).kennzahlen, true);
  const o = normalisiereSpielerOptionen(
    { format: 'quadrat', schrift: 'comic', textfarbe: 'blau', flaechen: 'viel', position: 'quer' },
    { hatKegel: true, hatWuerfe: true },
  );
  assert.equal(o.format, SPIELER_GRAFIK_DEFAULT.format);
  assert.equal(o.schrift, SPIELER_GRAFIK_DEFAULT.schrift);
  assert.equal(o.textfarbe, SPIELER_GRAFIK_DEFAULT.textfarbe);
  assert.equal(o.flaechen, SPIELER_GRAFIK_DEFAULT.flaechen);
  assert.equal(o.position, SPIELER_GRAFIK_DEFAULT.position);
});

test('Dateiname: Wurfbild, Spielername und Datum', () => {
  const name = spielerGrafikDateiname({ name: 'Anna Muster', datumIso: '2026-09-05T18:00:00.000Z' });
  assert.equal(name, 'Wurfbild_Anna-Muster_2026-09-05.png');
  assert.ok(spielerGrafikDateiname({}).startsWith('Wurfbild_Spieler_'));
});

test('Layout: lange Teilsätze brechen gleichmäßig um statt aus dem Bild zu laufen', () => {
  const geo = spaltenGeometrie();
  // 30 Würfe passen nicht mehr über SP_METRIK.minZelle — also zwei Zeilen à 15.
  const auf = zellenAufteilung(30, geo.wurfBreite);
  assert.equal(auf.zeilen, 2);
  assert.equal(auf.proZeile, 15);
  assert.ok(auf.zelleBreite >= SP_METRIK.minZelle);
  // Kurze Teilsätze bleiben einzeilig.
  assert.equal(zellenAufteilung(6, geo.wurfBreite).zeilen, 1);
  assert.equal(zellenAufteilung(0, geo.wurfBreite).zeilen, 0);
});

test('Layout: Titel, Sätze und Fußzeile ergeben einen Block im Korridor', () => {
  const game = mkGame('g1', [{ name: 'Anna' }], [
    [blk([9, 5, 4, 2]), blk([3, 3, 1, 1])],
  ]);
  const m = spielerGrafikModell({ game }, '');
  const opts = normalisiereSpielerOptionen(SPIELER_GRAFIK_DEFAULT, m);
  const L = berechneSpielerLayout(m, opts, messText);
  assert.equal(L.fmt.w, 1080);
  assert.equal(L.saetze.length, 2);
  assert.equal(L.saetze[0].label, '1. Satz');
  // Je Teilsatz eine Zeile, die Modus-Spalte nur an der ersten.
  assert.equal(L.saetze[0].zeilen.length, 2);
  assert.equal(L.saetze[0].zeilen[0].kurz, 'Volle');
  assert.equal(L.saetze[0].zeilen[0].tsText, '14');
  assert.deepEqual(L.saetze[0].zeilen[1].zellen.map((w) => w.wert), [4, 2]);
  // Der Block sitzt mittig im nutzbaren Korridor und läuft nicht über.
  const [oben, unten] = L.fmt.korridor;
  assert.ok(L.yTop >= oben);
  assert.ok(L.yTop + L.hoehe * L.skala <= unten + 0.5);
  assert.equal(L.fuss.gesamtText, '28');
});

test('Layout: sehr viele Sätze werden verkleinert statt abgeschnitten', () => {
  const viele = Array.from({ length: 8 }, () => blk([9, 9, 9, 9]));
  const game = mkGame('g1', [{ name: 'Anna' }], [viele]);
  game.config.saetze = 8;
  const m = spielerGrafikModell({ game }, '');
  const opts = normalisiereSpielerOptionen({ ...SPIELER_GRAFIK_DEFAULT, kegelbilder: false }, m);
  const L = berechneSpielerLayout(m, opts, messText);
  const [oben, unten] = L.fmt.korridor;
  assert.ok(L.skala < 1, 'acht Sätze müssten verkleinert werden');
  assert.ok(L.hoehe * L.skala <= (unten - oben) + 0.5);
});

test('Layout: ein Satz ohne Teilsatz-Aufteilung bekommt eine Hinweiszeile statt leerer Zeilen', () => {
  const game = mkGame('g1', [{ name: 'Anna' }], [[blk([], { satzOverride: 42 })]]);
  const m = spielerGrafikModell({ game }, '');
  const L = berechneSpielerLayout(m, normalisiereSpielerOptionen(SPIELER_GRAFIK_DEFAULT, m), messText);
  assert.equal(L.saetze[0].zeilen.length, 1);
  assert.ok(L.saetze[0].zeilen[0].hinweis.includes('Satz-Ergebnis'));
  assert.equal(L.saetze[0].zeilen[0].zellen.length, 0);
  assert.equal(L.saetze[0].holzText, '42');
});

test('Layout: Extras verändern die Zeilenhöhe, nicht den Inhalt', () => {
  const game = mkGame('g1', [{ name: 'Anna' }], [[blk([9, 5, 4, 2], { kegel: [[1, 2], [3], [4], [5]] })]]);
  const m = spielerGrafikModell({ game }, '');
  const schlicht = berechneSpielerLayout(
    m, normalisiereSpielerOptionen({ ...SPIELER_GRAFIK_DEFAULT, kegelbilder: false, wurfnummern: false }, m), messText,
  );
  const voll = berechneSpielerLayout(
    m, normalisiereSpielerOptionen({ ...SPIELER_GRAFIK_DEFAULT, kegelbilder: true, wurfnummern: true }, m), messText,
  );
  assert.ok(voll.hoehe > schlicht.hoehe, 'Kegelbilder und Wurfnummern brauchen Platz');
  assert.equal(voll.saetze[0].zeilen[0].zellen.length, schlicht.saetze[0].zeilen[0].zellen.length);
  // Ohne Kennzahlen fällt die Fußzeile über den Summen weg, das Gesamt bleibt.
  const ohne = berechneSpielerLayout(
    m, normalisiereSpielerOptionen({ ...SPIELER_GRAFIK_DEFAULT, kennzahlen: false }, m), messText,
  );
  assert.equal(ohne.fuss.zeilen.length, 0);
  assert.equal(ohne.fuss.gesamtText, '20');
});
