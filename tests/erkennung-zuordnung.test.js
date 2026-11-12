import { test } from 'node:test';
import assert from 'node:assert/strict';
import { ordneEvent, bahnFuerLane, bahnBelegung, AKTION, MAX_LUECKE } from '../js/logic/erkennung-zuordnung.js';
import { teilsatzRanges } from '../js/logic/teilsaetze.js';
import { volleKranz, abraeumScan, isAbraeumMode } from '../js/logic/abraeumen.js';
import { readFileSync } from 'node:fs';

// 2 Spieler, 2 Sätze, je Satz 4 Würfe: 2 Volle, dann 2 Abräumen.
// Bahnplan: Spieler 1 spielt Bahn 1 dann 2, Spieler 2 umgekehrt (Duo-Tausch).
const config = {
  spielerListe: [{ name: 'Anna' }, { name: 'Ben' }],
  saetze: 2,
  ersteBahn: 1,
  wuerfeProSatz: 4,
  teilsaetze: [{ modus: 'volle', wuerfe: 2 }, { modus: 'abraeumen', wuerfe: 2 }],
  bahnplan: [[1, 2], [2, 1]],
};
const ranges = teilsatzRanges(config);

function blk(wuerfe = [], kegel = null, done = false) {
  return {
    wuerfe: wuerfe.slice(),
    kegel: kegel ? kegel.slice() : wuerfe.map(() => null),
    koenig: wuerfe.map(() => false),
    overrides: [null, null],
    done,
  };
}
// Zwei Spieler, je zwei Sätze.
const bloecke = (a0 = blk(), a1 = blk(), b0 = blk(), b1 = blk()) => [[a0, a1], [b0, b1]];

const wurf = (lane, pins_count, pins = null) => ({ lane, pins_count, pins });
const ordne = (zeile, bl, extra = {}) =>
  ordneEvent(zeile, { config, bloecke: bl, ranges, ...extra });

// ── Bahnübersetzung ──────────────────────────────────────────────────────────

test('Bahnübersetzung: ohne Erkenner ist die gemeldete Zahl die Bahn', () => {
  assert.equal(bahnFuerLane(null, 3), 3);
  assert.equal(bahnFuerLane({ bahn_zuordnung: {} }, 3), 3);
});

test('Bahnübersetzung: eine gekoppelte Bahn schlägt die Tafel', () => {
  // Ein Erkenner, der genau eine Bahn liest (Telefon an Bahn 5): was auf der Tafel steht,
  // ist unerheblich — er sieht nur diese eine.
  assert.equal(bahnFuerLane({ bahn_nummer: 5, bahn_zuordnung: { 1: 2 } }, 1), 5);
});

test('Bahnübersetzung: Tafelposition 1…4 wird auf die echten Bahnen 2–5 gezogen', () => {
  // Ohne kalibrierte Bahnnummern zählt die Erkennung die Tafeln von links. Ohne diese
  // Übersetzung wäre JEDE Zuordnung um eins verschoben, ohne dass es auffällt.
  const e = { bahn_zuordnung: { 1: 2, 2: 3, 3: 4, 4: 5 } };
  assert.deepEqual([1, 2, 3, 4].map((l) => bahnFuerLane(e, l)), [2, 3, 4, 5]);
});

// ── Der Normalfall ───────────────────────────────────────────────────────────

test('Bahn → Spieler → Satz → Wurfindex: ein Wurf landet an der richtigen Stelle', () => {
  const bl = bloecke(blk([9]));                 // Anna hat auf Bahn 1 schon einen Wurf
  const r = ordne(wurf(1, 7, [1, 2, 3, 4, 6, 7, 9]), bl);

  assert.equal(r.aktion, AKTION.SETZEN);
  assert.deepEqual(r.ziel, { sp: 0, st: 0, idx: 1 });
  assert.equal(r.holz, 7);
  assert.deepEqual(r.kegel, [1, 2, 3, 4, 6, 7, 9]);
  assert.equal(r.koenigFlag, false);
});

test('Die zweite Bahn gehört dem zweiten Spieler', () => {
  const bl = bloecke(blk([9]), blk(), blk([5]));
  const r = ordne(wurf(2, 8), bl);

  assert.equal(r.ziel.sp, 1);
  assert.equal(r.ziel.idx, 1);
});

test('Der Satz kommt aus der Bahn-Belegung, nicht aus der Reihenfolge der Sätze', () => {
  // Anna ist mit Satz 1 (Bahn 1) fertig, Ben auch — beide sind gewechselt. Anna steht jetzt
  // auf Bahn 2. Ein Wurf auf Bahn 2 ist also Annas Satz 2, nicht Bens Satz 1.
  const bl = bloecke(blk([9, 9, 9, 9], null, true), blk(), blk([5, 5, 5, 5], null, true), blk());
  assert.deepEqual(bahnBelegung(config, bl).map((b) => b.lane), [2, 1]);

  const r = ordne(wurf(2, 6), bl);
  assert.deepEqual(r.ziel, { sp: 0, st: 1, idx: 0 });
});

test('Ein Fehlwurf ist ein Wurf: 0 Holz, leeres Bild', () => {
  // Ohne Wurf-Trigger bei 0 Holz würde die Wurfzahl im Teilsatz nicht mehr stimmen. Die
  // Erkennung meldet ihn, und er muss hier genauso ankommen wie jeder andere Wurf.
  const r = ordne(wurf(1, 0, []), bloecke(blk([9])));

  assert.equal(r.aktion, AKTION.SETZEN);
  assert.equal(r.holz, 0);
  assert.deepEqual(r.kegel, []);
});

test('Kranz in der Volle entsteht aus dem Bild, nicht aus einem Flag', () => {
  const r = ordne(wurf(1, 8, [9, 8, 7, 6, 4, 3, 2, 1]), bloecke(blk([9])));

  assert.deepEqual(r.kegel, [1, 2, 3, 4, 6, 7, 8, 9]);   // sortiert, ohne die 5
  assert.equal(r.koenigFlag, false);
  // Gegenprobe mit der Erfassungslogik: so eingetragen ist es ein Kranz.
  const nachher = blk([9, 8], [null, r.kegel]);
  assert.equal(volleKranz(nachher, 1), true);
});

// ── Einspielwürfe ────────────────────────────────────────────────────────────

test('Der erste Wurf eines leeren Satzes wird nur vorgeschlagen', () => {
  // Einspielwürfe finden auf derselben Bahn statt und sehen genauso aus. In der Aufzeichnung
  // vom 29.08. standen auf einer Bahn 20 Probewürfe vor dem ersten Satz.
  const r = ordne(wurf(1, 9, [1, 2, 3, 4, 5, 6, 7, 8, 9]), bloecke());

  assert.equal(r.aktion, AKTION.VORSCHLAG);
  assert.match(r.grund, /Einspielwürfe/);
  assert.deepEqual(r.ziel, { sp: 0, st: 0, idx: 0 });     // der Platz steht trotzdem fest
  assert.deepEqual(r.kegel, [1, 2, 3, 4, 5, 6, 7, 8, 9]); // und die Daten auch
});

// ── Was nicht in dieses Spiel gehört ─────────────────────────────────────────

test('Eine fremde Bahn wird verworfen — aber nicht in der Datenbank vermerkt', () => {
  // Auf einer Anlage können mehrere Spiele gleichzeitig laufen. Bahn 4 gehört einem anderen
  // Spiel; schriebe dieses Gerät dort „verworfen" hin, nähme es dem anderen den Wurf weg.
  const r = ordne(wurf(4, 9), bloecke());

  assert.equal(r.aktion, AKTION.VERWERFEN);
  assert.equal(r.merken, false);
  assert.match(r.grund, /Bahn 4/);
});

test('Ein Spieler eines anderen Geräts wird verworfen, ohne Vermerk', () => {
  const r = ordne(wurf(2, 9), bloecke(), { darfSchreiben: (sp) => sp === 0 });

  assert.equal(r.aktion, AKTION.VERWERFEN);
  assert.equal(r.merken, false);
});

test('Unmögliche Holzzahlen sind Lesefehler, keine Würfe', () => {
  for (const holz of [10, -1, 1.5, null, undefined, '9']) {
    const r = ordne(wurf(1, holz), bloecke(blk([9])));
    assert.equal(r.aktion, AKTION.VERWERFEN, `Holz ${holz}`);
    assert.equal(r.ziel, null);
  }
});

test('Ein fertiger Spieler bekommt keine Würfe mehr', () => {
  const voll = blk([9, 9, 9, 9], null, true);
  const r = ordne(wurf(2, 9), bloecke(voll, blk([9, 9, 9, 9], null, true), voll, voll));

  assert.equal(r.aktion, AKTION.VERWERFEN);
  assert.match(r.grund, /fertig/);
});

// ── Puffern statt raten ──────────────────────────────────────────────────────

test('Wer auf den Bahnwechsel wartet, bekommt seine Würfe gepuffert', () => {
  // Anna ist mit Satz 1 fertig und will auf Bahn 2 — dort spielt Ben aber noch. Sie steht
  // also physisch weiter auf Bahn 1, und was dort erkannt wird, gehört niemandem.
  const bl = bloecke(blk([9, 9, 9, 9], null, true), blk(), blk([5]), blk());
  const stand = bahnBelegung(config, bl);
  assert.equal(stand[0].waiting, true);

  const r = ordne(wurf(1, 7), bl);
  assert.equal(r.aktion, AKTION.PUFFERN);
  assert.match(r.grund, /Bahnwechsel/);
  assert.equal(r.ziel, null, 'wohin, ist noch nicht entschieden');
});

test('Ein voller, aber offener Satz puffert — mit Platzangabe für die Korrektur', () => {
  // Voll UND abgeschlossen kommt hier nie an: dann ist der Spieler entweder gewechselt, er
  // wartet (Regel darüber) oder er ist fertig. Offen bleibt der Fall "alle Würfe da, Satz
  // nicht abgeschlossen" — etwa nach einem wieder geöffneten Satz. Dann ist Puffern richtig:
  // als Korrekturvorschlag brauchbar, als stiller Eintrag falsch.
  const bl = bloecke(blk([9, 9, 9, 9], null, false));
  const r = ordne(wurf(1, 5), bl);

  assert.equal(r.aktion, AKTION.PUFFERN);
  assert.match(r.grund, /ist voll/);
  assert.deepEqual(r.ziel, { sp: 0, st: 0, idx: 4 });
});

test('Nach dem letzten Satz ist ein Wurf auf der Bahn ein Fehltrigger', () => {
  // Gemessen am 29.08.: auf Bahn 5 hängte ein Fehltrigger einen 31. Wurf (0 Holz) an den
  // letzten Satz. Ein fertiger Spieler bekommt ihn nicht — und ein Platz wird auch nicht
  // angeboten, denn im vollen Satz gibt es keinen.
  const voll = blk([9, 9, 9, 9], null, true);
  const r = ordne(wurf(2, 0, []), bloecke(voll, voll, voll, voll));

  assert.equal(r.aktion, AKTION.VERWERFEN);
  assert.equal(r.ziel, null);
});

// ── Abräumen: die Kette als Sicherheitsnetz ──────────────────────────────────

test('Abräumen: ein sauberer Wurf wird gesetzt, mit exaktem Bild', () => {
  // Volle fertig (2 Würfe), dann Abräumen: erster Abräum-Wurf trifft das volle Bild.
  const bl = bloecke(blk([9, 8], [null, [1, 2, 3, 4, 6, 7, 8, 9]]));
  const r = ordne(wurf(1, 4, [1, 2, 3, 4]), bl);

  assert.equal(r.aktion, AKTION.SETZEN);
  assert.deepEqual(r.ziel, { sp: 0, st: 0, idx: 2 });
  assert.deepEqual(r.kegel, [1, 2, 3, 4]);
});

test('Abräumen: mehr Holz als Kegel standen → Vorschlag, nicht Eintrag', () => {
  // Nach einem 4er stehen noch 5 Kegel. Eine 6 ist unmöglich — entweder wurde ein Wurf
  // übersehen oder einer falsch gelesen.
  const bl = bloecke(blk([9, 9, 4], [null, null, [1, 2, 3, 4]]));
  const r = ordne(wurf(1, 6), bl);

  assert.equal(r.aktion, AKTION.VORSCHLAG);
  assert.match(r.grund, /standen nur 5/);
  assert.deepEqual(r.ziel, { sp: 0, st: 0, idx: 3 });
});

test('Abräumen: ein Kegel, der schon lag, verrät den verpassten Wurf', () => {
  // DAS ist der einzige Hinweis, den es auf eine Teilerkennung gibt: Der Erkenner liefert
  // kein Bild des Vorzustands, also kann nur die Abräum-Kette zeigen, dass dazwischen etwas
  // fehlt. Gemessen am 29.08.: viermal fiel der abräumende Wurf aus, einmal wurde eine 9 als
  // „2" gemeldet.
  const bl = bloecke(blk([9, 9, 4], [null, null, [1, 2, 3, 4]]));
  const r = ordne(wurf(1, 2, [2, 7]), bl);      // die 2 lag schon

  assert.equal(r.aktion, AKTION.VORSCHLAG);
  assert.match(r.grund, /Kegel 2 stand nicht mehr/);
});

test('Abräumen: ohne exaktes Vorbild zählt nur die Zahl', () => {
  // Wurde vorher per Hand nur eine Holzzahl ohne Kegel erfasst, ist die Restmenge unbekannt
  // (`exact: false`). Dann darf ein Kegel im Bild nicht als Widerspruch gelten — die Prüfung
  // gegen die Anzahl bleibt.
  const bl = bloecke(blk([9, 9, 4], [null, null, null]));
  const r = ordne(wurf(1, 2, [2, 7]), bl);

  assert.equal(r.aktion, AKTION.SETZEN);
  assert.deepEqual(r.kegel, [2, 7]);
});

// ── Das Kegelbild ────────────────────────────────────────────────────────────

test('Bild und Holzzahl widersprechen sich: die Zahl gilt, das Bild fällt weg', () => {
  const r = ordne(wurf(1, 5, [1, 2]), bloecke(blk([9])));

  assert.equal(r.aktion, AKTION.VORSCHLAG);
  assert.equal(r.holz, 5);
  assert.equal(r.kegel, null);
  assert.match(r.grund, /5 Holz, aber 2 Kegel/);
});

test('Unsinnige Kegelnummern machen das Bild unbrauchbar, nicht den Wurf', () => {
  for (const pins of [[0, 1], [1, 10], [3, 3]]) {
    const r = ordne({ lane: 1, pins_count: 2, pins }, bloecke(blk([9])));
    assert.equal(r.aktion, AKTION.VORSCHLAG, JSON.stringify(pins));
    assert.equal(r.holz, 2);
    assert.equal(r.kegel, null);
  }
});

test('Bekannte Grenze: eine Teilerkennung in der VOLLE ist nicht erkennbar', () => {
  // In der Volle trifft jeder Wurf ohnehin das ganze Bild — es gibt keine Kette, gegen die
  // sich prüfen ließe. Eine 9, die als „2" mit Bild [2 7] gemeldet wird, ist in sich stimmig
  // und geht als gewöhnlicher Wurf durch. Dieser Test hält die Lücke fest, damit sie nicht
  // für behoben gehalten wird: auffallen kann sie nur an der Satzsumme.
  const r = ordne(wurf(1, 2, [2, 7]), bloecke(blk([9])));

  assert.equal(r.aktion, AKTION.SETZEN);
  assert.equal(r.holz, 2);
});

// ── Gegen eine echte Aufzeichnung ────────────────────────────────────────────

// Die Aufzeichnung liegt im geklonten Erkenner (erkennung/data/fixtures/) und stammt aus
// einer Trainingseinheit vom 08.09.2026: 65 Würfe auf den Bahnen 2, 3 und 4 in einer
// Viertelstunde, dazu 13 Aufstellvorgänge. Soll-Zahlen gibt es nicht — es ist kein
// Punktspiel. Geprüft werden deshalb EIGENSCHAFTEN an echten Daten, und eine davon ist die
// wichtigste Zusicherung der ganzen Anbindung (siehe unten: Kettenfehler nur, wo angemahnt).
//
// Format: `bildVor`/`bildNach` sind die STEHENDEN Kegel — so sieht der Kontrakt im Plan aus.
// Die Tabelle `erkannter_wurf` führt die GEFALLENEN, wie der Erkenner heute sendet. Hier
// wird umgerechnet; das ist genau der Unterschied, den man sonst leicht übersieht.
test('Echte Aufzeichnung: 60 von 65 Würfen sauber, kein Holz verloren', () => {
  const { zeilen, c, ranges: r, bl, zaehler } = replay();

  assert.equal(zeilen.length, 65);
  // Gemessen. Feste Zahlen mit Absicht: Ändert sich hier etwas, soll es auffallen.
  assert.deepEqual(zaehler, { setzen: 60, vorschlag: 5, puffern: 0, verwerfen: 0 });

  // Nichts ist unterwegs verloren gegangen: die Summen je Bahn aus der Aufzeichnung
  // (190/49/152 Holz) stehen hinterher je Spieler im Satz.
  assert.deepEqual(bl.map((a) => a[0].wuerfe.reduce((x, w) => x + w, 0)), [190, 49, 152]);
  assert.deepEqual(bl.map((a) => a[0].wuerfe.length), [30, 12, 23]);
  bl.forEach((a) => assert.ok(a[0].wuerfe.length <= c.wuerfeProSatz));
  void r;
});

test('Echte Aufzeichnung: ein Kettenfehler steht nur dort, wo auch angemahnt wurde', () => {
  // DAS ist die Zusicherung, auf die es ankommt. Beim Abräumen trifft jeder Wurf nur die
  // zuvor stehenden Kegel; bricht diese Kette, wurde ein Wurf übersehen oder nur teilweise
  // erkannt. Würde ordneEvent so einen Wurf durchwinken, zeigte die Erfassung hinterher
  // einen Fehler an einem Wurf, den die Zuordnung für sauber erklärt hat — zwei Regeln, die
  // sich widersprechen. In dieser echten Aufzeichnung bleiben nach dem Einspielen zwei
  // Kettenfehler übrig, und beide sitzen an Würfen, die als VORSCHLAG markiert waren.
  const { c, ranges: r, bl, markiert } = replay();

  const fehlerstellen = [];
  bl.forEach((saetze, sp) => saetze.forEach((b, st) => r.forEach((rg) => {
    if (!isAbraeumMode(rg.modus) || b.wuerfe.length <= rg.start) return;
    const scan = abraeumScan(b, rg);
    const ende = Math.min(rg.end, b.wuerfe.length);
    for (let j = rg.start; j < ende; j += 1) {
      if (scan.error[j]) fehlerstellen.push(`${sp}:${st}:${j}`);
    }
  })));

  for (const stelle of fehlerstellen) {
    assert.equal(markiert.get(stelle), AKTION.VORSCHLAG,
      `Wurf ${stelle} bricht die Abräum-Kette, wurde aber nicht angemahnt`);
  }
  assert.equal(fehlerstellen.length, 2, 'gemessen: zwei Stellen in dieser Aufzeichnung');
  void c;
});

// Spielt die Aufzeichnung durch und gibt Blöcke, Zähler und die Marken zurück.
// Angenommen wird `setzen` UND `vorschlag` — letzteres so, wie ein Mensch es nach einem
// Blick auf die Bahn bestätigen würde. Nur so füllen sich die Sätze überhaupt, und nur so
// lässt sich hinterher prüfen, ob die Mahnungen an den richtigen Stellen standen.
function replay() {
  const roh = JSON.parse(readFileSync(
    new URL('../erkennung/data/fixtures/erkennung_2026-09-08.json', import.meta.url), 'utf8'));
  const zeilen = roh.ereignisse.filter((e) => e.art === 'wurf').map((e) => {
    const gefallen = e.bildVor.filter((p) => !e.bildNach.includes(p));
    return { lane: e.bahn, pins_count: gefallen.length, pins: gefallen };
  });

  // Ein Spiel, das zu einer Trainingseinheit passt: drei Spieler, je ein Satz auf der
  // eigenen Bahn, 40 Würfe (20 Volle, 20 Abräumen). Kein Bahnwechsel — sonst stünden die
  // Spieler mitten im Lauf still und die Daten blieben ungenutzt.
  const c = {
    spielerListe: [{ name: 'A' }, { name: 'B' }, { name: 'C' }],
    saetze: 1,
    ersteBahn: 2,
    wuerfeProSatz: 40,
    teilsaetze: [{ modus: 'volle', wuerfe: 20 }, { modus: 'abraeumen', wuerfe: 20 }],
    bahnplan: [[2], [3], [4]],
  };
  const ranges = teilsatzRanges(c);
  const bl = [0, 1, 2].map(() => [blk()]);
  const zaehler = { setzen: 0, vorschlag: 0, puffern: 0, verwerfen: 0 };
  const markiert = new Map();

  for (const zeile of zeilen) {
    const e = ordneEvent(zeile, { config: c, bloecke: bl, ranges });
    assert.ok(e.aktion in zaehler, `unbekannte Aktion ${e.aktion}`);
    zaehler[e.aktion] += 1;
    if ((e.aktion !== AKTION.SETZEN && e.aktion !== AKTION.VORSCHLAG) || !e.ziel) continue;
    const b = bl[e.ziel.sp][e.ziel.st];
    if (e.ziel.idx !== b.wuerfe.length) continue;
    b.wuerfe.push(e.holz);
    b.kegel.push(e.kegel);
    b.koenig.push(e.koenigFlag);
    markiert.set(`${e.ziel.sp}:${e.ziel.st}:${e.ziel.idx}`, e.aktion);
    if (b.wuerfe.length >= c.wuerfeProSatz) b.done = true;
  }
  return { zeilen, c, ranges, bl, zaehler, markiert };
}

// ── bildStrittig: darf der Automatik-Betrieb dem Kegelbild glauben? ──────────
//
// Die Frage entsteht nur, weil es keine Vorschlagsliste gibt: Was die Zuordnung früher einem
// Menschen vorlegte, trägt die App jetzt selbst ein. Dann muss sie wissen, ob sie das BILD
// mitnehmen darf — die Holzzahl ist gemessen, das Bild kann ihr widersprechen.

test('Ein Bild, dessen Anzahl nicht zur Holzzahl passt, ist strittig', () => {
  const e = ordne(wurf(1, 4, [1, 2, 3]), bloecke(blk([9])));

  assert.equal(e.aktion, AKTION.VORSCHLAG);
  assert.equal(e.bildStrittig, true);
  assert.equal(e.kegel, null, 'das unbrauchbare Bild wird gar nicht erst weitergegeben');
  assert.equal(e.holz, 4, 'die gemessene Zahl bleibt');
});

test('Ein Bild mit Kegeln, die schon lagen, ist strittig', () => {
  // Abräumen: Wurf 3 nahm 1-2-3-4, es stehen noch 5-6-7-8-9. Meldet Wurf 4 den Kegel 2,
  // kann das nicht sein.
  const vorher = blk([9, 9, 4], [null, null, [1, 2, 3, 4]]);
  const e = ordne(wurf(1, 2, [2, 5]), bloecke(vorher));

  assert.equal(e.aktion, AKTION.VORSCHLAG);
  assert.equal(e.bildStrittig, true);
  assert.match(e.grund, /Kegel 2 stand nicht mehr/);
  assert.deepEqual(e.kegel, [2, 5], 'das Bild wird mitgeliefert — verwerfen darf der Aufrufer');
});

test('Mehr Holz als Kegel standen ist KEIN Bildstreit — da zweifelt die Zahl', () => {
  // Hier hilft das Verwerfen des Bildes nichts: nicht das Bild ist strittig, sondern der
  // ganze Wurf. Die Erfassung lehnt ihn ab, und das soll sie auch.
  const vorher = blk([9, 9, 4], [null, null, [1, 2, 3, 4]]);
  const e = ordne(wurf(1, 7), bloecke(vorher));

  assert.equal(e.aktion, AKTION.VORSCHLAG);
  assert.equal(e.bildStrittig, false);
  assert.match(e.grund, /standen nur 5/);
});

test('Ein sauberer Wurf ist in keiner Hinsicht strittig', () => {
  const e = ordne(wurf(1, 8, [1, 2, 3, 4, 5, 6, 7, 8]), bloecke(blk([9])));

  assert.equal(e.aktion, AKTION.SETZEN);
  assert.equal(e.bildStrittig, false);
  assert.equal(e.grund, null);
});

test('Der Satzanfang nennt seine Art — der Hinweis daran hängt an einem Feld, nicht am Wortlaut', () => {
  // Die Ansicht laesst den Satzanfang-Hinweis ab Satz 2 weg (eingespielt wird vor dem
  // Spiel, nicht nach jedem Bahnwechsel). Sie erkennt ihn an `art`, nicht am Text —
  // dieser Test haelt fest, dass das Feld gesetzt ist, und nur hier.
  const anfang = ordne(wurf(1, 9), bloecke());
  assert.equal(anfang.art, 'satzanfang');

  const spaeter = ordne(wurf(1, 4, [1, 2, 3]), bloecke(blk([9])));
  assert.equal(spaeter.art, null, 'ein anderer Befund traegt die Art nicht');

  const sauber = ordne(wurf(1, 8, [1, 2, 3, 4, 5, 6, 7, 8]), bloecke(blk([9])));
  assert.equal(sauber.art, null);
});

// ── Die Wurfnummer von der Tafel ─────────────────────────────────────────────
//
// Bis zum 12.11.2026 landete jeder erkannte Wurf am ENDE der Liste. Das hat einen Bruch:
// Wird ein Wurf nicht eingetragen -- weil die Erfassung ihn ablehnt und sofort aufgibt --,
// sitzt alles Folgende einen Platz zu frueh, und zwar bis zum Satzende. Die Wurfnummer, die
// auf der Tafel steht, loest das: Sie sagt, der WIEVIELTE Wurf das war.
//
// Die Regel, auf Ansage: Die Nummer bekommt den Platz. Keine Nummer -> naechster freier
// Platz. Nummer belegt -> der Wurf dort wird ersetzt, mit Hinweis.

const mitNr = (lane, pins_count, nr, pins = null) =>
  ({ lane, pins_count, pins, displayed_throw_number: nr });

test('Tafelnummer: ohne Nummer bleibt alles wie bisher — naechster freier Platz', () => {
  const bl = bloecke(blk([9]));
  const r = ordne(wurf(1, 8), bl);
  assert.equal(r.ziel.idx, 1);
  assert.equal(r.nummer, null);
  assert.equal(r.ersetzt, false);
  assert.equal(r.luecke, 0);
});

test('Tafelnummer: die passende Nummer bestaetigt nur — kein Hinweis', () => {
  const bl = bloecke(blk([9]));
  const r = ordne(mitNr(1, 8, 2), bl);           // ein Wurf drin, Tafel sagt Wurf 2
  assert.equal(r.aktion, AKTION.SETZEN);
  assert.equal(r.ziel.idx, 1);
  assert.equal(r.nummer, 2);
  assert.equal(r.grund, null);
});

test('Tafelnummer: ein belegter Platz wird ERSETZT, nicht angehaengt', () => {
  // Genau der Fall, fuer den die Nummer da ist: Die Tafel sagt, das ist Wurf 1 -- obwohl
  // schon zwei Wuerfe dastehen. Dann stand dort etwas Falsches.
  const bl = bloecke(blk([9, 8]));
  const r = ordne(mitNr(1, 5, 1), bl);
  assert.equal(r.ziel.idx, 0);
  assert.equal(r.ersetzt, true);
  assert.equal(r.aktion, AKTION.VORSCHLAG);      // eintragen ja, aber nicht stillschweigend
  assert.equal(r.art, 'nummer-ersetzt');
  assert.match(r.grund, /ersetzt/);
});

test('Tafelnummer: eine Luecke bleibt offen, statt alles zu verschieben', () => {
  // Zwei Wuerfe stehen, die Tafel ist bei Wurf 4: Platz 3 wurde verpasst. Er bleibt offen,
  // der neue Wurf sitzt auf Platz 4 -- und nicht auf 3, wo er bisher gelandet waere.
  const bl = bloecke(blk([9, 8]));
  const r = ordne(mitNr(1, 7, 4), bl);
  assert.equal(r.ziel.idx, 3);
  assert.equal(r.luecke, 1);
  assert.equal(r.art, 'nummer-luecke');
  assert.match(r.grund, /nachzutragen/);
});

test('Tafelnummer: eine verlesene Ziffer reisst keinen Satz auf', () => {
  // Aus "4" wird "14": Die Nummer liegt mehr als MAX_LUECKE Plaetze weiter. Sie wird
  // verworfen, der Wurf kommt ans Ende -- und sagt, dass die Tafel nicht passte.
  const weit = { ...config, wuerfeProSatz: 20,
                 teilsaetze: [{ modus: 'volle', wuerfe: 20 }] };
  const r = ordneEvent(mitNr(1, 7, 2 + MAX_LUECKE + 2),
                       { config: weit, bloecke: bloecke(blk([9, 8])),
                         ranges: teilsatzRanges(weit) });
  assert.equal(r.ziel.idx, 2);                   // ans Ende, nicht auf Platz 9
  assert.equal(r.luecke, 0);
  assert.equal(r.art, 'nummer-unbrauchbar');
  assert.match(r.grund, /verworfen/);
});

test('Tafelnummer: eine Nummer, die es im Satz nicht gibt, wird nicht geraten', () => {
  // 4 Wuerfe je Satz -- "7" kann nicht stimmen. Der Wurf geht trotzdem rein (ans Ende):
  // Eine unlesbare Tafel darf keinen Wurf kosten.
  const bl = bloecke(blk([9]));
  const r = ordne(mitNr(1, 8, 7), bl);
  assert.equal(r.ziel.idx, 1);
  assert.equal(r.nummer, null);
  assert.equal(r.art, 'nummer-unbrauchbar');
  assert.match(r.grund, /gibt es im Satz nicht/);
});

test('Tafelnummer: 0 und Unsinn werden wie "keine Nummer" behandelt', () => {
  const bl = bloecke(blk([9]));
  for (const n of [0, -1, 2.5, 'zwei']) {
    const r = ordne(mitNr(1, 8, n), bl);
    assert.equal(r.ziel.idx, 1, `Nummer ${n}`);
    assert.equal(r.nummer, null, `Nummer ${n}`);
  }
});

test('Tafelnummer: mit Luecke wird die Abraeum-Kette NICHT geprueft', () => {
  // Beim Abraeumen prueft die Zuordnung sonst, ob mehr Holz gemeldet wird als Kegel standen.
  // Steht davor eine Luecke, weiss niemand, was dort fiel -- die Pruefung wuerde dann einen
  // richtigen Wurf ablehnen. Platz 3 und 4 sind Abraeumen (Teilsatz 2).
  const bl = bloecke(blk([9, 9]));               // Volle voll, Abraeumen beginnt bei idx 2
  const ohne = ordne(wurf(1, 9), bl);            // ohne Nummer: Platz 2, volle Kegel -> ok
  assert.equal(ohne.ziel.idx, 2);
  const mit = ordne(mitNr(1, 9, 4), bl);         // Tafel sagt Platz 4, Platz 3 bleibt offen
  assert.equal(mit.ziel.idx, 3);
  assert.equal(mit.luecke, 1);
  assert.equal(mit.art, 'nummer-luecke');        // und NICHT "es standen nur N Kegel"
});
