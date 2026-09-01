// Reine Spiel-Auswertung: aus config + erfassung.bloecke + Teilsatz-ranges eine Statistik
// je Spieler und eine Platzierung berechnen. Browser + Node ladbar, unabhängig vom View
// (per Unit-Test abgesichert, später auch von der Statistik-Seite nutzbar).

import { satzHolz } from './holz.js';
import { isAbraeumMode, abraeumScan, volleKranz } from './abraeumen.js';

// Kennzahlen EINES Teilsatzes (ein ranges-Bereich in einem Satz-Block). Das ist die feinste
// Ebene der Auswertung: die Spieler-Werte weiter unten sind schlicht die Summe darüber, und die
// Mannschafts-Auswertung (logic/mannschaft-statistik.js) filtert genau hier nach Bahn/Satz/
// Teilsatz. Ein manuell eingetragenes Ergebnis (Override) liefert Holz und volle Wurfzahl, aber
// keine Einzelwürfe — Verteilung, 9er, Kränze usw. bleiben dort leer.
//   blk: Satz-Block, r: ranges-Eintrag { start, end, soll, modus }, ov: overrides[i] (oder null)
function teilsatzMetrik(blk, r, ov) {
  const bw = Array.isArray(blk.wuerfe) ? blk.wuerfe : [];
  const wuerfe = bw.slice(r.start, r.end);
  const manual = ov != null;
  const abraeum = isAbraeumMode(r.modus);
  const end = Math.min(r.end, bw.length);
  // Abräum-Lauf einmal scannen: liefert Kranz-Treffer und den Bild-Zustand vor jedem Wurf.
  const scan = abraeum ? abraeumScan(blk, r) : null;
  let kranz = 0;
  let raeumer = 0;      // vollständig abgeräumte Läufe
  let raeumWuerfe = 0;  // dafür benötigte Würfe (Ø Würfe/Räumer = Tempo)
  let vollChance = 0;   // Würfe aus vollem Bild (Nenner der 9er-Quote)
  let runLen = 0;
  for (let k = r.start; k < end; k += 1) {
    const hit = scan ? !!scan.kranzAt[k] : (r.modus === 'volle' && volleKranz(blk, k));
    if (hit) kranz += 1;
    if (!scan) continue;
    if (scan.before[k] && scan.before[k].count === 9) vollChance += 1;
    runLen += 1;
    const after = scan.before[k + 1]; // Zustand VOR dem Folgewurf = Zustand NACH Wurf k
    // Ein frischer Lauf (volles Bild) direkt nach dem Wurf heißt: der Lauf wurde abgeräumt.
    if (after && after.count === 9 && after.exact === true && after.picked === false) {
      raeumer += 1; raeumWuerfe += runLen; runLen = 0;
    }
  }
  // In der Volle steht vor JEDEM Wurf das volle Bild.
  if (r.modus === 'volle') vollChance = Math.max(0, end - r.start);
  return {
    modus: r.modus,
    manual,
    wuerfe,                                        // einzeln erfasste Würfe (leer bei Override)
    soll: r.soll,
    holz: manual ? ov : wuerfe.reduce((a, w) => a + w, 0),
    // Ein manuell eingetragenes Ergebnis zählt als vollständiger Teilsatz (Soll-Würfe), sonst
    // die tatsächlich erfassten Würfe. So steigt "Würfe" auch bei reinen Summen-Eingaben.
    wurfCount: manual ? r.soll : wuerfe.length,
    neuner: wuerfe.filter((w) => w === 9).length,  // Maximalwürfe (Alle Neune / voller Abräumer)
    fehl: wuerfe.filter((w) => w === 0).length,    // Fehlwürfe (kein Kegel getroffen)
    kranz,                                          // nur König 5 blieb stehen
    raeumer,
    raeumWuerfe,
    vollChance,
  };
}

// Summe eines Teilsatz-Feldes über eine Liste von Teilsätzen (nur die, die `pick` zulässt).
function sumTs(list, feld, pick) {
  return list.reduce((s, ts) => s + ((!pick || pick(ts)) ? (ts[feld] || 0) : 0), 0);
}

// Auswertung eines (beendeten) Spiels.
//   config:  game.config  (spielerListe, saetze, bahnplan, ersteBahn, wuerfeProSatz …)
//   bloecke: erfassung.bloecke  (je Spieler ein Array von Satz-Blöcken)
//   ranges:  teilsatzRanges(config)
// Rückgabe: { players:[…in Aufstellungs-Reihenfolge…], ranking:[…nach Gesamt absteigend…] }.
// players und ranking teilen sich dieselben Objekte -> `rang` ist auf beiden gesetzt.
export function computeGameStats(config, bloecke, ranges) {
  const players = config.spielerListe.map((sp, i) => {
    const arr = Array.isArray(bloecke[i]) ? bloecke[i] : [];
    const saetze = arr.map((blk, st) => {
      const overrides = Array.isArray(blk.overrides) ? blk.overrides : [];
      const teilsaetze = ranges.map((r, ti) => teilsatzMetrik(blk, r, overrides[ti]));
      return {
        satz: st + 1,
        bahn: config.bahnplan?.[i]?.[st] ?? (config.ersteBahn + st),
        holz: satzHolz(blk, ranges),
        teilsaetze,
      };
    });
    // Alle Teilsätze des Spielers am Stück — die Spieler-Kennzahlen sind ihre Summe.
    const alleTs = saetze.flatMap((s) => s.teilsaetze);
    const gesamt = saetze.reduce((s, x) => s + x.holz, 0);
    // Abräum-Holz je Spieler: Summe der Teilsätze im Abräum-Modus (Abräumen / Kranz-Abräumen)
    // über alle Sätze. Dient u. a. als Feinwertung (z. B. EWP-Gleichstand innerhalb einer
    // Mannschaft) — bei reinen Volle-Programmen (Bohle) bleibt es 0.
    const abraeum = sumTs(alleTs, 'holz', (ts) => isAbraeumMode(ts.modus));
    const wurfCount = sumTs(alleTs, 'wurfCount');
    const neuner = sumTs(alleTs, 'neuner');
    const vollChance = sumTs(alleTs, 'vollChance');
    const raeumer = sumTs(alleTs, 'raeumer');
    const raeumWuerfe = sumTs(alleTs, 'raeumWuerfe');
    return {
      index: i,
      name: sp.name || ('Spieler ' + (i + 1)),
      gesamt,
      abraeum,                                        // Abräum-Holz (Feinwertung, z. B. EWP-Gleichstand)
      saetze,
      bester: saetze.reduce((m, x) => Math.max(m, x.holz), 0),
      schnittSatz: saetze.length ? gesamt / saetze.length : 0,
      schnittWurf: wurfCount ? gesamt / wurfCount : 0,
      wurfCount,
      neuner,                                         // Maximalwürfe (Alle Neune / voller Abräumer)
      neunerQuote: vollChance ? neuner / vollChance : 0, // Anteil 9er an Würfen aus vollem Bild
      fehl: sumTs(alleTs, 'fehl'),                    // Fehlwürfe (kein Kegel getroffen)
      kranz: sumTs(alleTs, 'kranz'),                  // Kränze (nur König 5 blieb stehen)
      raeumer,                                        // vollständig abgeräumte Läufe
      raeumSchnitt: raeumer ? raeumWuerfe / raeumer : 0, // Ø Würfe je Räumer (Tempo)
      vollChance,                                     // Würfe aus vollem Bild (Nenner der Quote)
      rang: 1,
    };
  });
  // Platzierung: nach Gesamt absteigend; gleiche Gesamtzahl = gleicher Rang (Standard-„1224"-
  // Zählung: nach einem Gleichstand wird der übersprungene Rang ausgelassen).
  const ranking = players.slice().sort((a, b) => b.gesamt - a.gesamt);
  let rang = 0;
  let prev = null;
  ranking.forEach((p, i) => {
    if (prev === null || p.gesamt < prev) rang = i + 1;
    p.rang = rang;
    prev = p.gesamt;
  });
  return { players, ranking };
}
