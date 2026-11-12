import { test } from 'node:test';
import assert from 'node:assert/strict';
import { verarbeite, sortiereZeilen, MODUS, MAX_ALTER_MS } from '../js/logic/erkennung-strom.js';
import { teilsatzRanges } from '../js/logic/teilsaetze.js';

// 2 Spieler, 1 Satz, 4 Würfe: 2 Volle, 2 Abräumen. Ein Satz je Spieler heißt: kein
// Bahnwechsel — so prüft diese Datei den STROM und nicht die Bahnlogik (die hat ihre
// eigenen Tests in erkennung-zuordnung.test.js).
const config = {
  spielerListe: [{ name: 'Anna' }, { name: 'Ben' }],
  saetze: 1,
  ersteBahn: 1,
  wuerfeProSatz: 4,
  teilsaetze: [{ modus: 'volle', wuerfe: 2 }, { modus: 'abraeumen', wuerfe: 2 }],
  bahnplan: [[1], [2]],
};
const ranges = teilsatzRanges(config);

const blk = (wuerfe = [], kegel = null) => ({
  wuerfe: wuerfe.slice(),
  kegel: kegel ? kegel.slice() : wuerfe.map(() => null),
  koenig: wuerfe.map(() => false),
  overrides: [null, null],
  done: false,
});
// Leere Sätze. Der erste Wurf eines leeren Satzes trägt immer einen HINWEIS
// (Einspielwürfe) — im Automatik-Betrieb wird er trotzdem eingetragen, im
// Vorschlagsbetrieb vorgelegt.
const leer = () => [[blk()], [blk()]];
// Beide Sätze haben ihren ersten Wurf schon: Anna auf Bahn 1, Ben auf Bahn 2.
const begonnen = () => [[blk([9])], [blk([9])]];

// Zweiter Aufbau, nur für den Bahnwechsel: 2 Spieler, 2 Sätze, 2 Würfe. Anna beginnt auf
// Bahn 1, Ben auf Bahn 2 — und sie tauschen. Damit lässt sich prüfen, dass ein gepufferter
// Wurf nach einem Bahnwechsel seinen Platz findet, OHNE die Bahnlogik nachzubauen.
const config2 = {
  spielerListe: [{ name: 'Anna' }, { name: 'Ben' }],
  saetze: 2,
  ersteBahn: 1,
  wuerfeProSatz: 2,
  teilsaetze: [{ modus: 'volle', wuerfe: 2 }],
  bahnplan: [[1, 2], [2, 1]],
};

const T0 = Date.parse('2026-11-11T19:00:00.000Z');
// Eine Zeile wie aus `erkannter_wurf`.
const zeile = (id, sekunde, lane, holz, pins = null) => ({
  id,
  recorded_at: new Date(T0 + sekunde * 1000).toISOString(),
  lane,
  pins_count: holz,
  pins,
});

// Der Schreiber, den die App als `uebernehmen` mitgibt (dort: addWurfAn). Hier hängt er die
// Würfe wirklich an die Blöcke — nur so ändert sich der Zustand, auf den die Zuordnung beim
// nächsten Wurf schaut.
function schreiber(bl, { lehntAb = () => false, cfg = config } = {}) {
  const geschrieben = [];
  const fn = (e) => {
    if (lehntAb(e)) return false;
    const b = bl[e.ziel.sp][e.ziel.st];
    if (e.ziel.idx !== b.wuerfe.length) return false;
    b.wuerfe.push(e.holz);
    b.kegel.push(e.kegel);
    b.koenig.push(e.koenigFlag);
    if (b.wuerfe.length >= cfg.wuerfeProSatz) b.done = true;
    geschrieben.push(e);
    return true;
  };
  fn.geschrieben = geschrieben;
  return fn;
}

const lauf = (zeilen, bl, extra = {}) => verarbeite(zeilen, {
  config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
  uebernehmen: schreiber(bl), ...extra,
});

// ── Reihenfolge ──────────────────────────────────────────────────────────────

test('Sortiert wird nach der Zeit, nicht nach der id', () => {
  // Der Erkenner stempelt die Zeit beim Einreihen und liefert nach einem Netzausfall den
  // Puffer unverändert nach: NEUE, höhere id, ALTE Zeit. Nach id sortiert landeten diese
  // Würfe hinter den inzwischen eingegangenen — und damit in den falschen Sätzen.
  const spaet = zeile(7, 10, 1, 5);     // kleine id, spätere Zeit
  const frueh = zeile(99, 1, 1, 9);     // große id, frühere Zeit (nachgeliefert)

  assert.deepEqual(sortiereZeilen([spaet, frueh]).map((z) => z.id), [99, 7]);
});

test('Nachgelieferte Würfe landen in der richtigen Reihenfolge im Satz', () => {
  const bl = begonnen();
  lauf([zeile(7, 10, 1, 5), zeile(99, 1, 1, 8)], bl);

  // Die 8 hat die frühere Zeit und steht vor der 5, obwohl ihre id größer ist.
  assert.deepEqual(bl[0][0].wuerfe, [9, 8, 5]);
});

test('Eine unlesbare Zeit sortiert nach hinten statt alles durcheinanderzubringen', () => {
  const kaputt = { id: 2, recorded_at: 'kein Datum', lane: 1, pins_count: 3 };
  const gut = zeile(5, 99, 1, 7);

  assert.deepEqual(sortiereZeilen([kaputt, gut]).map((z) => z.id), [5, 2]);
});

// ── Entdopplung ──────────────────────────────────────────────────────────────

test('Was schon verarbeitet ist, kommt nicht zweimal in den Satz', () => {
  const bl = begonnen();
  const erste = lauf([zeile(1, 1, 1, 8)], bl);
  assert.equal(erste.gesehenBis, 1);
  assert.deepEqual(bl[0][0].wuerfe, [9, 8]);

  // Derselbe Schwung noch einmal, plus eine neue Zeile — so holt ein Nachfassen nach einem
  // Verbindungsabriss.
  lauf([zeile(1, 1, 1, 8), zeile(2, 2, 1, 4)], bl,
       { gesehenBis: erste.gesehenBis, uebernehmen: schreiber(bl) });

  assert.deepEqual(bl[0][0].wuerfe, [9, 8, 4], 'nur der neue Wurf kommt hinzu');
});

test('Eine Zeile im Puffer UND in der Lieferung wird nur einmal verarbeitet', () => {
  // Der Fall tritt ein, wenn der Aufrufer `gesehenBis` nicht mitführt.
  const bl = begonnen();
  const warte = zeile(5, 5, 1, 8);

  const r = lauf([warte], bl, { puffer: [warte], gesehenBis: 0, uebernehmen: schreiber(bl) });

  assert.deepEqual(bl[0][0].wuerfe, [9, 8]);
  assert.equal(r.gesetzt.length, 1);
});

test('Eine Zeile ohne id gilt als neu, statt still zu verschwinden', () => {
  const bl = begonnen();
  const r = lauf([{ recorded_at: new Date(T0).toISOString(), lane: 1, pins_count: 8 }],
                 bl, { gesehenBis: 500, uebernehmen: schreiber(bl) });

  assert.equal(r.gesetzt.length, 1);
  assert.equal(r.gesehenBis, 500, 'ohne id bleibt der Stand unverändert');
});

// ── Betriebsmodus ────────────────────────────────────────────────────────────

test('Vorschlagsmodus setzt nichts — auch nicht das Zuordenbare', () => {
  const bl = begonnen();
  const schreibt = schreiber(bl);
  const r = verarbeite([zeile(1, 1, 1, 8)], {
    config, bloecke: bl, ranges, modus: MODUS.VORSCHLAG, jetzt: T0 + 60_000,
    uebernehmen: schreibt,
  });

  assert.equal(schreibt.geschrieben.length, 0);
  assert.deepEqual(bl[0][0].wuerfe, [9]);
  assert.equal(r.vorschlaege.length, 1);
  assert.equal(r.puffer.length, 0, 'ein Vorschlag wartet nicht zusätzlich im Puffer');
});

test('Automatik lässt nichts beim Menschen liegen — es gibt keine Vorschlagsliste', () => {
  // Nach der 4 mit konkretem Bild stehen noch 5 Kegel. Die 6 danach ist unmöglich — genau
  // dieser Wurf ist der einzige, der überhaupt bis zur Erfassung durchkommt und dort
  // abgelehnt wird (addWurfAn prüft die Abräum-Grenze). Hier spielt `lehntAb` das nach.
  const bl = begonnen();
  const schreibt = schreiber(bl, { lehntAb: (e) => /standen nur/.test(e.grund || '') });
  const r = verarbeite([
    zeile(1, 1, 1, 8), zeile(2, 2, 1, 4, [1, 2, 3, 4]), zeile(3, 3, 1, 6),
  ], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    uebernehmen: schreibt,
  });

  assert.deepEqual(bl[0][0].wuerfe, [9, 8, 4]);
  assert.equal(r.gesetzt.length, 2);
  assert.equal(r.vorschlaege.length, 0, 'im Automatik-Betrieb wird nichts vorgelegt');
  assert.equal(r.abgelehnt.length, 1);
  assert.match(r.abgelehnt[0].grund, /standen nur 5/);
  assert.equal(r.puffer.length, 0, 'ein abgelehnter Wurf wartet nicht — er ist aufgegeben');
});

test('Ein strittiges Kegelbild wird eingetragen, aber OHNE das Bild', () => {
  // 4 Holz, aber nur drei Kegel im Bild: eines von beiden ist falsch, und entscheidbar ist
  // es nicht. Die Holzzahl ist die gemessene Größe und bleibt; das Bild fällt weg, damit
  // die App es sich selbst zusammenrechnet (kegel = null).
  const bl = begonnen();
  const schreibt = schreiber(bl);
  const r = verarbeite([zeile(1, 1, 1, 4, [1, 2, 3])], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    uebernehmen: schreibt,
  });

  assert.deepEqual(bl[0][0].wuerfe, [9, 4]);
  assert.equal(bl[0][0].kegel[1], null, 'das widersprochene Bild steht nicht im Satz');
  assert.equal(r.gesetzt.length, 1);
  assert.match(r.gesetzt[0].hinweis, /4 Holz, aber 3 Kegel/);
});

// ── Der Satzanfang ───────────────────────────────────────────────────────────

test('Automatik beginnt den Satz selbst — mit einem Hinweis auf die Einspielwürfe', () => {
  // Einspielwürfe sehen für die Kamera aus wie Würfe; die Erkennung trennt das nicht. Die
  // Entscheidung ist trotzdem, einzutragen: Wer die Erkennung erst zum Anspiel einschaltet,
  // hat das Problem nicht, und wer es doch erwischt, räumt den Satz mit einem Griff.
  // Der Hinweis bleibt am Wurf — er ist der Grund, warum dieser Fall überhaupt auffällt.
  const bl = leer();
  const r = lauf([zeile(1, 1, 1, 9), zeile(2, 2, 1, 8), zeile(3, 3, 1, 7)], bl);

  assert.deepEqual(bl[0][0].wuerfe, [9, 8, 7]);
  assert.equal(r.gesetzt.length, 3);
  assert.equal(r.vorschlaege.length, 0);
  assert.match(r.gesetzt[0].hinweis, /Einspielwürfe/);
  assert.equal(r.gesetzt[1].hinweis, null, 'nur der erste Wurf trägt den Hinweis');
});

test('Vorschlagsbetrieb: ist der erste Platz vergeben, läuft der Puffer weiter', () => {
  // Dieses Verhalten gibt es weiter — nur nicht mehr als Standard. Es ist der Grund, warum
  // ein Vorschlag seine Bahn sperrt: solange niemand geantwortet hat, ist der Platz nicht
  // vergeben, und der physisch nächste Wurf darf nicht davor rutschen.
  const bl = leer();
  const vor = { config, bloecke: bl, ranges, modus: MODUS.VORSCHLAG, jetzt: T0 + 60_000 };
  const erste = verarbeite([zeile(1, 1, 1, 9), zeile(2, 2, 1, 8), zeile(3, 3, 1, 7)],
                           { ...vor, uebernehmen: schreiber(bl) });

  assert.equal(erste.vorschlaege.length, 1, 'ein Vorschlag, nicht drei');
  assert.deepEqual(erste.puffer.map((z) => z.id), [2, 3]);

  // Der Mensch bestätigt den Vorschlag (so, wie die Oberfläche es täte).
  schreiber(bl)(erste.vorschlaege[0].entscheidung);
  assert.deepEqual(bl[0][0].wuerfe, [9]);

  // Jetzt sind die beiden Wartenden sauber zuordenbar — im Vorschlagsbetrieb werden sie
  // vorgelegt, nicht gesetzt.
  const zweite = verarbeite([], { ...vor, bloecke: bl, puffer: erste.puffer,
                                  gesehenBis: erste.gesehenBis,
                                  uebernehmen: schreiber(bl) });
  assert.equal(zweite.vorschlaege.length, 1, 'einer je freiem Platz');
  assert.deepEqual(bl[0][0].wuerfe, [9], 'der Vorschlagsbetrieb schreibt nicht');
});

// ── Puffer ───────────────────────────────────────────────────────────────────

test('Ein abgelehnter Wurf wird aufgegeben, damit die Bahn weiterläuft', () => {
  // Die Gegenentscheidung wäre, ihn 15 Minuten lang erneut zu versuchen und die Bahn zu
  // sperren. Dann legte EINE Fehlerkennung den Rest des Satzes still, und auf dem Bildschirm
  // stünde nur ein Warnzeichen. Also: aufgeben, weiterlaufen, und den Grund sichtbar machen.
  const bl = begonnen();
  const schreibt = schreiber(bl, { lehntAb: (e) => e.holz === 8 });
  const r = lauf([zeile(1, 1, 1, 8), zeile(2, 2, 1, 4)], bl, { uebernehmen: schreibt });

  assert.equal(r.abgelehnt.length, 1);
  assert.equal(r.abgelehnt[0].zeile.id, 1);
  assert.equal(r.puffer.length, 0, 'nicht gepuffert — aufgegeben');
  assert.deepEqual(bl[0][0].wuerfe, [9, 4], 'der nächste Wurf läuft durch');
});

test('Der Preis der Aufgabe: der nächste Wurf rückt auf den freien Platz', () => {
  // Das ist die Kehrseite derselben Entscheidung und steht hier, damit sie nicht übersehen
  // wird: Wird ein Wurf aufgegeben, sitzt alles Folgende einen Platz zu früh. Aus 8-dann-4
  // wird im Satz eine 4 auf Platz 2. Entdeckt wird das an der Abräum-Kette (sie meldet den
  // Widerspruch) und am Hinweis an der Bahn — nicht an der Reihenfolge, denn die stimmt.
  const bl = begonnen();
  const r = lauf([zeile(1, 1, 1, 8), zeile(2, 2, 1, 4)], bl,
                 { uebernehmen: schreiber(bl, { lehntAb: (e) => e.holz === 8 }) });

  assert.deepEqual(bl[0][0].wuerfe, [9, 4]);
  assert.equal(r.abgelehnt.length, 1);
  assert.match(r.abgelehnt[0].grund, /.+/, 'der Grund steht für den Hinweis bereit');
});

test('Nach einem gesetzten Wurf wird der Puffer erneut geprüft', () => {
  // DAS ist der Grund, warum der Strom eine Schleife ist und keine Liste: Mit jedem
  // gesetzten Wurf ändert sich der Zustand, auf den die Zuordnung schaut — hier sogar die
  // Bahnbelegung.
  //
  // Der Aufbau: Annas Satz 1 ist fertig, sie will auf Bahn 2, dort steht noch Ben. Also
  // wartet sie, und ein Wurf auf Bahn 1 gehört in diesem Moment NIEMANDEM (puffern). Mit
  // Bens letztem Wurf tauschen beide die Bahn — und derselbe gepufferte Wurf ist jetzt
  // Bens erster Wurf im zweiten Satz. In EINEM Durchgang.
  const bl = [
    [blk([9, 9]), blk()],      // Anna: Satz 1 fertig, wartet auf Bahn 2
    [blk([9]), blk()],         // Ben: Satz 1 offen, steht auf Bahn 2
  ];
  bl[0][0].done = true;
  const ranges2 = teilsatzRanges(config2);
  const r = verarbeite([zeile(1, 1, 1, 7), zeile(2, 2, 2, 8)], {
    config: config2, bloecke: bl, ranges: ranges2, modus: MODUS.AUTOMATIK,
    jetzt: T0 + 60_000, uebernehmen: schreiber(bl, { cfg: config2 }),
  });

  assert.deepEqual(bl[1][0].wuerfe, [9, 8], 'Ben macht seinen Satz 1 voll');
  assert.deepEqual(bl[1][1].wuerfe, [7], 'der gepufferte Wurf wird nach dem Wechsel Bens');
  assert.deepEqual(bl[0][1].wuerfe, [], 'Anna hat auf ihrer neuen Bahn noch nicht geworfen');
  assert.equal(r.puffer.length, 0);
  assert.equal(r.gesetzt.length, 2);
});

test('Ein Wurf, der zu lange wartet, verfällt lokal — die Zeile bleibt unberührt', () => {
  // Ein Satz dauert rund zehn Minuten. Wer dann noch keinen Platz hat, gehört zu einem Satz,
  // der nie zustande kommt. Aufgegeben wird er aber nur HIER: in der Datenbank kann die
  // Zeile für ein anderes Gerät noch gültig sein, deshalb steht sie nicht in `vermerke`.
  //
  // Der Wurf hängt hier an einem FERTIGEN Satz (Anna hat ihren einen Satz abgeschlossen) —
  // das ist der Weg in den Puffer, der auch im Automatik-Betrieb bleibt. Eine Ablehnung der
  // Erfassung wäre es nicht: die wird sofort aufgegeben, nicht gepuffert.
  // "voll, aber offen": vier von vier Wuerfen erfasst, der Satz aber nicht abgeschlossen.
  // Ein ABGESCHLOSSENER Satz macht den Spieler bei einem Ein-Satz-Spiel fertig, und fertig
  // heisst verwerfen, nicht puffern -- dann pruefte dieser Test etwas anderes als gemeint.
  const bl = [[blk([9, 9, 9, 9])], [blk([9])]];
  const alt = zeile(1, 1, 1, 8);
  const r = verarbeite([], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK,
    puffer: [alt], gesehenBis: 1,
    uebernehmen: schreiber(bl),
    jetzt: T0 + MAX_ALTER_MS + 2000,
  });

  assert.equal(r.puffer.length, 0);
  assert.equal(r.verfallen.length, 1);
  assert.equal(r.abgelehnt.length, 0, 'verfallen ist nicht abgelehnt');
  assert.equal(r.vermerke.length, 0, 'kein Vermerk in der Datenbank');
});

// ── Vermerke ─────────────────────────────────────────────────────────────────

test('Nur allgemeingültige Befunde werden für die Datenbank vermerkt', () => {
  const bl = begonnen();
  const r = lauf([
    zeile(1, 1, 3, 9),        // Bahn 3 gehört nicht zu diesem Spiel -> gilt nur für mich
    zeile(2, 2, 1, 42),       // Holz 42 ist ein Lesefehler -> gilt für jeden
  ], bl);

  assert.deepEqual(r.vermerke.map((v) => v.zeile.id), [2]);
  assert.match(r.vermerke[0].grund, /42/);
});

test('Ein leerer Schwung ändert nichts und meldet nichts', () => {
  const r = lauf([], begonnen());

  assert.deepEqual(r, {
    gesetzt: [], vorschlaege: [], vermerke: [], puffer: [], verfallen: [], abgelehnt: [],
    gesehenBis: 0,
  });
});

// ── Bahnen bleiben unabhängig ────────────────────────────────────────────────

test('Eine abgelehnte Bahn hält die anderen nicht auf', () => {
  // Projektregel: Die Bahnen sind unabhängig. Lehnt die Erfassung auf Bahn 1 ab, darf
  // Bahn 2 trotzdem weiterlaufen — sonst legte ein einziger strittiger Wurf die ganze
  // Halle still.
  const bl = begonnen();
  const schreibt = schreiber(bl, { lehntAb: (e) => e.bahn === 1 });
  const r = verarbeite([zeile(1, 1, 1, 8), zeile(2, 2, 2, 8)], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    uebernehmen: schreibt,
  });

  assert.deepEqual(bl[0][0].wuerfe, [9], 'Bahn 1 bekommt nichts');
  assert.deepEqual(bl[1][0].wuerfe, [9, 8], 'Bahn 2 läuft weiter');
  assert.deepEqual(r.abgelehnt.map((a) => a.zeile.id), [1]);
});

test('Hinter einem WARTENDEN Wurf wartet die ganze Bahn — auch ein sauberer', () => {
  // Der Unterschied zur Ablehnung: Ein wartender Wurf (hier: Satz noch nicht so weit) ist
  // nicht aufgegeben, sein Platz also nicht frei. Dürfte der zweite Wurf vor, nähme er den
  // Platz des ersten ein: aus 8 dann 4 würde 4 dann 8, und beide Teilsätze wären falsch.
  // DAS ist die Reihenfolge-Sperre, und sie gilt weiter.
  // Bahn 1 ist "voll, aber offen" -> alles dort wartet (siehe Test zum Verfallen).
  const bl = [[blk([9, 9, 9, 9])], [blk([9])]];
  const r = verarbeite([zeile(1, 1, 1, 8), zeile(2, 2, 1, 4, [1, 2, 3, 4])], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    uebernehmen: schreiber(bl),
  });

  assert.deepEqual(bl[0][0].wuerfe, [9, 9, 9, 9]);
  assert.deepEqual(r.puffer.map((z) => z.id), [1, 2], 'beide warten, in ihrer Reihenfolge');
});

// ── Offene Vorschläge des Aufrufers ──────────────────────────────────────────

test('Ein noch unbeantworteter Vorschlag verhindert einen zweiten für denselben Platz', () => {
  // Über mehrere Schwünge hinweg: Der Vorschlag aus dem ersten Aufruf liegt noch beim
  // Menschen. Käme im zweiten Aufruf ein weiterer für denselben Wurf, stünden zwei
  // Vorschläge für einen Platz in der Liste — bestätigen kann man nur einen.
  const bl = leer();
  const vor = { config, bloecke: bl, ranges, modus: MODUS.VORSCHLAG, jetzt: T0 + 60_000 };
  const erste = verarbeite([zeile(1, 1, 1, 9)], { ...vor, uebernehmen: schreiber(bl) });
  assert.equal(erste.vorschlaege.length, 1);

  const zweite = verarbeite([zeile(2, 2, 1, 8)], {
    ...vor,
    gesehenBis: erste.gesehenBis,
    offeneVorschlaege: erste.vorschlaege,
    uebernehmen: schreiber(bl),
  });

  assert.equal(zweite.vorschlaege.length, 0, 'kein zweiter Vorschlag für Wurf 1');
  assert.deepEqual(zweite.puffer.map((z) => z.id), [2]);
});

test('Ohne die offenen Vorschläge wüsste der Strom nichts davon', () => {
  // Gegenprobe zum Test darüber: Der Aufrufer MUSS seine offene Liste mitgeben. Das ist
  // keine Bequemlichkeit, sondern die Bedingung dafür, dass dieses Modul zustandslos
  // bleiben kann — und dieser Test hält fest, was sonst passiert.
  const bl = leer();
  const vor = { config, bloecke: bl, ranges, modus: MODUS.VORSCHLAG, jetzt: T0 + 60_000 };
  const erste = verarbeite([zeile(1, 1, 1, 9)], { ...vor, uebernehmen: schreiber(bl) });
  const zweite = verarbeite([zeile(2, 2, 1, 8)],
                            { ...vor, gesehenBis: erste.gesehenBis,
                              uebernehmen: schreiber(bl) });

  assert.equal(erste.vorschlaege.length, 1);
  assert.equal(zweite.vorschlaege.length, 1, 'ohne Mitgabe entsteht ein zweiter');
});

// ── Der Riegel, der einen Neustart überlebt ────────────────────────────────

test('Was schon im Satz steht, kommt nach einem Neuladen nicht ein zweites Mal', () => {
  // `gesehenBis` lebt nur im Arbeitsspeicher. Nach einem Neuladen holt die App die offenen
  // Zeilen erneut — und ob das Zuordnen in der Datenbank geklappt hat, weiss sie nicht
  // sicher (es kann fehlgeschlagen sein, ohne dass der Wurf im Satz fehlt). Die ids, die im
  // Satz stehen, wissen es. Ohne diesen Riegel stände jeder Wurf nach einem Neuladen doppelt.
  const bl = begonnen();
  const r = lauf([zeile(7, 1, 1, 8)], bl, { gesehenBis: 0, schonImSatz: [7] });

  assert.deepEqual(bl[0][0].wuerfe, [9], 'nichts hinzugekommen');
  assert.equal(r.gesetzt.length, 0);
  assert.equal(r.puffer.length, 0);
  assert.equal(r.gesehenBis, 7, 'der Stand zählt die Zeile trotzdem als abgearbeitet');
});

test('Ein Set ist als schonImSatz genauso gut wie eine Liste', () => {
  const bl = begonnen();
  const r = lauf([zeile(7, 1, 1, 8)], bl, { schonImSatz: new Set([7]) });

  assert.equal(r.gesetzt.length, 0);
  assert.deepEqual(bl[0][0].wuerfe, [9]);
});
