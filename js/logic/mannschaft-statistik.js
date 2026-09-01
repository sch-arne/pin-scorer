// Mannschafts-Auswertung eines Wettkampfs: verdichtet die Einzel-Ergebnisse aller Durchgänge
// (computeWettkampfStats(...).einzel) zu Kennzahlen und einem Wurf-Bild JE MANNSCHAFT — wahlweise
// gefiltert nach Bahn, Satz und Teilsatz. Reine Logik (Browser + Node ladbar, per Unit-Test
// abgesichert), damit Hub und spätere Ansichten dieselben Zahlen sehen.
//
// Gefiltert wird auf Teilsatz-Ebene: jeder Teilsatz (logic/statistik.js -> saetze[].teilsaetze[])
// kennt seinen Modus und trägt seine Kennzahlen; sein Satz kennt Satz-Nummer und Bahn.
//
// Anders als im Einzelspiel sind Bahn und Satz hier NICHT deckungsgleich: die Spieler starten auf
// verschiedenen Bahnen und mehrere Durchgänge laufen über dieselben Bahnen. Alle drei Filter sind
// deshalb frei kombinierbar („Satz 1 auf Bahn 3, nur Volle").

import { addRaeumVert } from './statistik.js';

export const ALLE = 'alle';

// Ein Filter, in dem nichts eingeschränkt ist.
export function leererFilter() { return { bahn: ALLE, satz: ALLE, teil: ALLE }; }

// Welche Filter-Werte kommen im Wettkampf überhaupt vor? Grundlage der Chip-Leisten.
// Bahnen und Sätze aufsteigend, Modi in der Reihenfolge ihres ersten Auftretens.
export function filterOptionen(einzel) {
  const bahnen = new Set();
  const saetze = new Set();
  const modi = [];
  (einzel || []).forEach((p) => (p.saetze || []).forEach((s) => {
    if (s.bahn != null) bahnen.add(s.bahn);
    if (s.satz != null) saetze.add(s.satz);
    (s.teilsaetze || []).forEach((ts) => { if (ts.modus && !modi.includes(ts.modus)) modi.push(ts.modus); });
  }));
  return {
    bahnen: [...bahnen].sort((a, b) => a - b),
    saetze: [...saetze].sort((a, b) => a - b),
    modi,
  };
}

// Greift der Filter für diesen Teilsatz? `ausser` blendet EINE Dimension aus — für die
// Aufschlüsselungen (Bahn-Vergleich / Satz-Verlauf), die ihre eigene Dimension vollständig
// zeigen und die Auswahl nur hervorheben, statt die übrigen Zeilen verschwinden zu lassen.
function passt(satz, ts, filter, ausser) {
  const f = filter || {};
  if (ausser !== 'bahn' && f.bahn !== ALLE && f.bahn != null && satz.bahn !== f.bahn) return false;
  if (ausser !== 'satz' && f.satz !== ALLE && f.satz != null && satz.satz !== f.satz) return false;
  if (f.teil !== ALLE && f.teil != null && ts.modus !== f.teil) return false;
  return true;
}

// Alle passenden Teilsätze einer Mannschaft einsammeln — mit ihrem Satz und dem Spieler-Eintrag.
// Ein Spieler-Eintrag ist ein Start (Spieler in EINEM Durchgang); dieselbe Person kann in
// mehreren Durchgängen stehen, das zählt als eigener Start.
function sammle(einzel, mannschaftId, filter, ausser) {
  const out = [];
  (einzel || []).forEach((p) => {
    if (mannschaftId != null && p.mannschaftId !== mannschaftId) return;
    (p.saetze || []).forEach((satz) => (satz.teilsaetze || []).forEach((ts) => {
      if (passt(satz, ts, filter, ausser)) out.push({ p, satz, ts });
    }));
  });
  return out;
}

// Schlüssel eines Starts (Spieler in einem Durchgang) und eines einzelnen Spieler-Satzes —
// für „wie viele Spieler / wie viele Sätze stecken in dieser Auswahl".
const startKey = (p) => `${p.gameId || ''}|${p.index}`;
const satzKey = (p, satz) => `${startKey(p)}|${satz.satz}`;

// Eine Liste gesammelter Teilsätze zu Kennzahlen verdichten.
function verdichte(list) {
  const starts = new Set();
  const satzSet = new Set();
  const verteilung = Array.from({ length: 10 }, () => 0);
  // Zweite Verteilung: nur die Würfe auf das VOLLE Bild (in der Volle alle, beim Abräumen der
  // jeweils erste Wurf eines Laufs). Sie macht das Wurf-Bild zwischen Volle und Abräumen
  // vergleichbar — Reste eines Abräum-Laufs verzerren die Verteilung sonst nach unten.
  const verteilungVoll = Array.from({ length: 10 }, () => 0);
  const raeumVert = [];
  let holz = 0; let wurfCount = 0; let erfasst = 0; let erfasstVoll = 0;
  let neuner = 0; let fehl = 0; let kranz = 0;
  let raeumer = 0; let raeumWuerfe = 0; let vollChance = 0;
  list.forEach(({ p, satz, ts }) => {
    if (ts.wurfCount > 0) { starts.add(startKey(p)); satzSet.add(satzKey(p, satz)); }
    holz += ts.holz || 0;
    wurfCount += ts.wurfCount || 0;
    neuner += ts.neuner || 0;
    fehl += ts.fehl || 0;
    kranz += ts.kranz || 0;
    raeumer += ts.raeumer || 0;
    raeumWuerfe += ts.raeumWuerfe || 0;
    vollChance += ts.vollChance || 0;
    addRaeumVert(raeumVert, ts.raeumVert);
    const voll = ts.wuerfeVoll || [];
    (ts.wuerfe || []).forEach((w, i) => {
      if (w < 0 || w > 9) return;
      verteilung[w] += 1; erfasst += 1;
      if (voll[i]) { verteilungVoll[w] += 1; erfasstVoll += 1; }
    });
  });
  return {
    holz,
    wurfCount,                                        // inkl. nur als Summe eingetragener Teilsätze
    erfasst,                                          // einzeln erfasste Würfe (Basis des Wurf-Bildes)
    erfasstVoll,                                      // davon aus vollem Bild geworfen
    verteilung,
    verteilungVoll,
    spieler: starts.size,
    saetze: satzSet.size,
    schnittSatz: satzSet.size ? holz / satzSet.size : 0,
    schnittWurf: wurfCount ? holz / wurfCount : 0,
    neuner,
    neunerQuote: vollChance ? neuner / vollChance : 0,
    vollChance,
    fehl,
    kranz,
    raeumer,
    raeumSchnitt: raeumer ? raeumWuerfe / raeumer : 0,
    raeumVert,                                        // Index = Würfe je Räumer, Wert = Häufigkeit
  };
}

// Aufschlüsselung nach einer Dimension ('bahn' | 'satz'): je Wert eine Zeile mit Holz, Zahl der
// gewerteten Spieler-Sätze und dem Schnitt. Der Filter DIESER Dimension bleibt außen vor (alle
// Zeilen bleiben sichtbar, `gewaehlt` markiert die Auswahl); die übrigen Filter greifen.
function aufschluesselung(einzel, mannschaftId, filter, dim, werte) {
  const list = sammle(einzel, mannschaftId, filter, dim);
  const wert = (satz) => (dim === 'bahn' ? satz.bahn : satz.satz);
  const gewaehltRaw = dim === 'bahn' ? (filter || {}).bahn : (filter || {}).satz;
  return werte.map((v) => {
    const teil = list.filter(({ satz }) => wert(satz) === v);
    const k = verdichte(teil);
    return { wert: v, holz: k.holz, saetze: k.saetze, schnitt: k.schnittSatz, gewaehlt: gewaehltRaw === v };
  });
}

// Vollständige Auswertung EINER Mannschaft unter dem aktuellen Filter.
//   einzel:       computeWettkampfStats(...).einzel
//   mannschaftId: Mannschaft (null = alle Spieler, z. B. für eine Gesamtsicht)
//   filter:       { bahn, satz, teil } — je ALLE oder ein konkreter Wert
// Rückgabe: Kennzahlen + Wurf-Verteilung + Bahn-Vergleich + Satz-Verlauf.
export function mannschaftAuswertung(einzel, mannschaftId, filter, optionen) {
  const opt = optionen || filterOptionen(einzel);
  const k = verdichte(sammle(einzel, mannschaftId, filter, null));
  return {
    ...k,
    bahnen: aufschluesselung(einzel, mannschaftId, filter, 'bahn', opt.bahnen),
    satzReihe: aufschluesselung(einzel, mannschaftId, filter, 'satz', opt.saetze),
  };
}

// Greift überhaupt ein Filter? (für Hinweistexte und die „x von y"-Anzeige)
export function filterAktiv(filter) {
  const f = filter || {};
  return f.bahn !== ALLE || f.satz !== ALLE || f.teil !== ALLE;
}
