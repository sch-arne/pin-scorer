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
// Leere Sätze. Achtung: Der erste Wurf eines leeren Satzes ist IMMER nur ein Vorschlag
// (Einspielwürfe) — wer das Setzen prüfen will, nimmt `begonnen()`.
const leer = () => [[blk()], [blk()]];
// Beide Sätze haben ihren ersten Wurf schon: Anna auf Bahn 1, Ben auf Bahn 2.
const begonnen = () => [[blk([9])], [blk([9])]];

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
function schreiber(bl, { lehntAb = () => false } = {}) {
  const geschrieben = [];
  const fn = (e) => {
    if (lehntAb(e)) return false;
    const b = bl[e.ziel.sp][e.ziel.st];
    if (e.ziel.idx !== b.wuerfe.length) return false;
    b.wuerfe.push(e.holz);
    b.kegel.push(e.kegel);
    b.koenig.push(e.koenigFlag);
    if (b.wuerfe.length >= config.wuerfeProSatz) b.done = true;
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

test('Automatik setzt das Zuordenbare und schlägt den Rest vor', () => {
  const bl = begonnen();
  const schreibt = schreiber(bl);
  // Nach der 4 mit konkretem Bild stehen noch 5 Kegel. Die 6 danach ist unmöglich — also
  // wurde ein Wurf übersehen oder falsch gelesen, und das gehört einem Menschen vorgelegt.
  const r = verarbeite([
    zeile(1, 1, 1, 8), zeile(2, 2, 1, 4, [1, 2, 3, 4]), zeile(3, 3, 1, 6),
  ], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    uebernehmen: schreibt,
  });

  assert.deepEqual(bl[0][0].wuerfe, [9, 8, 4]);
  assert.equal(r.gesetzt.length, 2);
  assert.equal(r.vorschlaege.length, 1);
  assert.match(r.vorschlaege[0].entscheidung.grund, /standen nur 5/);
});

// ── Der Satzanfang ───────────────────────────────────────────────────────────

test('Der erste Wurf eines Satzes wird genau einmal vorgeschlagen, der Rest wartet', () => {
  // Die Automatik kann einen Satz nicht selbst beginnen: Einspielwürfe sehen wie Würfe aus.
  // Also wird der erste Platz EINMAL vorgeschlagen — und alles danach wartet, statt sich als
  // Stapel von Vorschlägen für denselben Platz anzusammeln.
  const bl = leer();
  const r = lauf([zeile(1, 1, 1, 9), zeile(2, 2, 1, 8), zeile(3, 3, 1, 7)], bl);

  assert.equal(r.gesetzt.length, 0);
  assert.equal(r.vorschlaege.length, 1, 'ein Vorschlag, nicht drei');
  assert.equal(r.vorschlaege[0].zeile.id, 1);
  assert.deepEqual(r.puffer.map((z) => z.id), [2, 3]);
});

test('Ist der erste Platz vergeben, läuft der Puffer weiter', () => {
  const bl = leer();
  const erste = lauf([zeile(1, 1, 1, 9), zeile(2, 2, 1, 8), zeile(3, 3, 1, 7)], bl);

  // Der Mensch bestätigt den Vorschlag (so, wie die Oberfläche es täte).
  const e = erste.vorschlaege[0].entscheidung;
  schreiber(bl)(e);
  assert.deepEqual(bl[0][0].wuerfe, [9]);

  const zweite = lauf([], bl, { puffer: erste.puffer, gesehenBis: erste.gesehenBis,
                                uebernehmen: schreiber(bl) });

  assert.deepEqual(bl[0][0].wuerfe, [9, 8, 7]);
  assert.equal(zweite.puffer.length, 0);
});

// ── Puffer ───────────────────────────────────────────────────────────────────

test('Ein Wurf, den die Erfassung ablehnt, bleibt im Puffer statt verloren zu gehen', () => {
  // So verhält sich addWurfAn, wenn eine Sperre greift (fremdes Gerät, Satz voll,
  // ausstehender Bahnwechsel): es gibt false zurück.
  const bl = begonnen();
  const r = lauf([zeile(1, 1, 1, 8)], bl, { uebernehmen: () => false });

  assert.deepEqual(bl[0][0].wuerfe, [9]);
  assert.equal(r.puffer.length, 1);
  assert.equal(r.gesetzt.length, 0);
});

test('Nach einem gesetzten Wurf wird der Puffer erneut geprüft', () => {
  // DAS ist der Grund, warum der Strom eine Schleife ist und keine Liste: Mit jedem
  // gesetzten Wurf ändert sich der Zustand, auf den die Zuordnung schaut.
  const bl = begonnen();
  let erster = true;
  const schreibt = schreiber(bl, {
    // Der allererste Versuch wird abgelehnt (als wäre die Bahn kurz gesperrt), danach nicht.
    lehntAb: () => { if (erster) { erster = false; return true; } return false; },
  });
  const r = verarbeite([zeile(1, 1, 2, 8), zeile(2, 2, 2, 4)], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    uebernehmen: schreibt,
  });

  // Der zweite Wurf kann nicht vor dem ersten sitzen — beide warten, in ihrer Reihenfolge.
  assert.deepEqual(bl[1][0].wuerfe, [9]);
  assert.deepEqual(r.puffer.map((z) => z.id), [1, 2]);

  // Beim nächsten Durchgang sitzt beides, richtig geordnet.
  const r2 = verarbeite([], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    puffer: r.puffer, gesehenBis: r.gesehenBis, uebernehmen: schreiber(bl),
  });
  assert.deepEqual(bl[1][0].wuerfe, [9, 8, 4]);
  assert.equal(r2.puffer.length, 0);
});

test('Ein Wurf, der zu lange wartet, verfällt lokal — die Zeile bleibt unberührt', () => {
  // Ein Satz dauert rund zehn Minuten. Wer dann noch keinen Platz hat, gehört zu einem Satz,
  // der nie zustande kommt. Aufgegeben wird er aber nur HIER: in der Datenbank kann die
  // Zeile für ein anderes Gerät noch gültig sein, deshalb steht sie nicht in `vermerke`.
  const bl = begonnen();
  const alt = zeile(1, 1, 1, 8);
  const r = verarbeite([], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK,
    puffer: [alt], gesehenBis: 1,
    uebernehmen: () => false,                     // bleibt hängen
    jetzt: T0 + MAX_ALTER_MS + 2000,
  });

  assert.equal(r.puffer.length, 0);
  assert.equal(r.verfallen.length, 1);
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
    gesetzt: [], vorschlaege: [], vermerke: [], puffer: [], verfallen: [], gesehenBis: 0,
  });
});

// ── Bahnen bleiben unabhängig ────────────────────────────────────────────────

test('Eine wartende Bahn hält die anderen nicht auf', () => {
  // Projektregel: Die Bahnen sind unabhängig. Hängt Bahn 1, weil die Erfassung dort
  // ablehnt, darf Bahn 2 trotzdem weiterlaufen — sonst legte ein einziger strittiger Wurf
  // die ganze Halle still.
  const bl = begonnen();
  const schreibt = schreiber(bl, { lehntAb: (e) => e.bahn === 1 });
  const r = verarbeite([zeile(1, 1, 1, 8), zeile(2, 2, 2, 8)], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    uebernehmen: schreibt,
  });

  assert.deepEqual(bl[0][0].wuerfe, [9], 'Bahn 1 wartet');
  assert.deepEqual(bl[1][0].wuerfe, [9, 8], 'Bahn 2 läuft weiter');
  assert.deepEqual(r.puffer.map((z) => z.id), [1]);
});

test('Hinter einem wartenden Wurf wartet die ganze Bahn — auch ein sauberer', () => {
  // Der zweite Wurf wäre für sich zuordenbar. Dürfte er vor, nähme er den Platz des
  // ersten ein: aus 8 dann 4 würde 4 dann 8, und beide Teilsätze wären falsch.
  const bl = begonnen();
  const r = verarbeite([zeile(1, 1, 1, 8), zeile(2, 2, 1, 4, [1, 2, 3, 4])], {
    config, bloecke: bl, ranges, modus: MODUS.AUTOMATIK, jetzt: T0 + 60_000,
    uebernehmen: () => false,
  });

  assert.deepEqual(bl[0][0].wuerfe, [9]);
  assert.deepEqual(r.puffer.map((z) => z.id), [1, 2], 'beide warten, in ihrer Reihenfolge');
});

// ── Offene Vorschläge des Aufrufers ──────────────────────────────────────────

test('Ein noch unbeantworteter Vorschlag verhindert einen zweiten für denselben Platz', () => {
  // Über mehrere Schwünge hinweg: Der Vorschlag aus dem ersten Aufruf liegt noch beim
  // Menschen. Käme im zweiten Aufruf ein weiterer für denselben Wurf, stünden zwei
  // Vorschläge für einen Platz in der Liste — bestätigen kann man nur einen.
  const bl = leer();
  const erste = lauf([zeile(1, 1, 1, 9)], bl);
  assert.equal(erste.vorschlaege.length, 1);

  const zweite = lauf([zeile(2, 2, 1, 8)], bl, {
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
  const erste = lauf([zeile(1, 1, 1, 9)], bl);
  const zweite = lauf([zeile(2, 2, 1, 8)], bl,
                      { gesehenBis: erste.gesehenBis, uebernehmen: schreiber(bl) });

  assert.equal(zweite.vorschlaege.length, 1, 'ohne Mitgabe entsteht ein zweiter');
});
