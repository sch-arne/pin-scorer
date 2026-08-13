// Reine Spiel-Auswertung: aus config + erfassung.bloecke + Teilsatz-ranges eine Statistik
// je Spieler und eine Platzierung berechnen. Browser + Node ladbar, unabhängig vom View
// (per Unit-Test abgesichert, später auch von der Statistik-Seite nutzbar).

import { satzHolz } from './holz.js';
import { isAbraeumMode, abraeumScan, volleKranz } from './abraeumen.js';

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
      const blkWuerfe = Array.isArray(blk.wuerfe) ? blk.wuerfe : [];
      const overrides = Array.isArray(blk.overrides) ? blk.overrides : [];
      // Einzelwürfe je Teilsatz — nur die tatsächlich ERFASSTEN Würfe (leer, wenn ein Teilsatz nur
      // als Summe/Override eingetragen wurde). So kann der View die gefallenen Kegel je Wurf zeigen,
      // sofern sie einzeln erfasst wurden.
      const teilsaetze = ranges.map((r, ti) => ({
        modus: r.modus,
        manual: overrides[ti] != null,
        wuerfe: blkWuerfe.slice(r.start, r.end),
      }));
      return {
        satz: st + 1,
        bahn: config.bahnplan?.[i]?.[st] ?? (config.ersteBahn + st),
        holz: satzHolz(blk, ranges),
        teilsaetze,
      };
    });
    const gesamt = saetze.reduce((s, x) => s + x.holz, 0);
    const wuerfe = arr.flatMap((b) => (Array.isArray(b.wuerfe) ? b.wuerfe : []));
    // Kränze je Spieler — deckungsgleich mit der ♔-Markierung an den Wurf-Chips: im Kranz-
    // Abräumen aus dem Lauf-Scan (Wurf lässt nur den König 5 stehen), in der Volle über
    // volleKranz (eine 8, die genau den König übrig lässt). Nur einzeln erfasste Würfe können
    // ein Kranz sein; rein als Summe eingetragene Ergebnisse liefern keine Kegelbilder.
    const kranz = arr.reduce((tot, b) => {
      const bw = Array.isArray(b.wuerfe) ? b.wuerfe : [];
      return tot + ranges.reduce((s, r) => {
        const end = Math.min(r.end, bw.length);
        const scan = isAbraeumMode(r.modus) ? abraeumScan(b, r) : null;
        let c = 0;
        for (let k = r.start; k < end; k += 1) {
          const hit = scan ? !!scan.kranzAt[k] : (r.modus === 'volle' && volleKranz(b, k));
          if (hit) c += 1;
        }
        return s + c;
      }, 0);
    }, 0);
    // Abräum-Tempo & Neuner-Quote am vollen Bild — ein Durchlauf je Block über alle Teilsätze.
    //   raeumer / raeumWuerfe: vollständig abgeräumte Läufe und die dafür benötigten Würfe
    //     (Ø Würfe/Räumer = wie schnell ein volles Bild weggeräumt wird; ein 9er-Räumer = 1 Wurf).
    //   vollChance: Würfe aus vollem Bild — in der Volle jeder Wurf, im Abräumen nur solange alle 9
    //     standen (Lauf-Beginn). Nenner der Neuner-Quote: ein 9er setzt ein volles Bild voraus,
    //     deshalb ist der Zähler schlicht die Gesamt-Neunerzahl.
    let raeumer = 0;
    let raeumWuerfe = 0;
    let vollChance = 0;
    arr.forEach((b) => {
      const bw = Array.isArray(b.wuerfe) ? b.wuerfe : [];
      ranges.forEach((r) => {
        const end = Math.min(r.end, bw.length);
        if (isAbraeumMode(r.modus)) {
          const scan = abraeumScan(b, r);
          let runLen = 0;
          for (let k = r.start; k < end; k += 1) {
            if (scan.before[k] && scan.before[k].count === 9) vollChance += 1;
            runLen += 1;
            const after = scan.before[k + 1]; // Zustand VOR dem Folgewurf = Zustand NACH Wurf k
            // Ein frischer Lauf (volles Bild) direkt nach dem Wurf heißt: der Lauf wurde abgeräumt.
            if (after && after.count === 9 && after.exact === true && after.picked === false) {
              raeumer += 1; raeumWuerfe += runLen; runLen = 0;
            }
          }
        } else if (r.modus === 'volle') {
          vollChance += Math.max(0, end - r.start);
        }
      });
    });
    const neuner = wuerfe.filter((w) => w === 9).length; // Maximalwürfe (Alle Neune / voller Abräumer)
    // Wurfzahl je Teilsatz: manuell eingetragenes Ergebnis (Override) zählt als voller Teilsatz
    // (Soll-Würfe), sonst die tatsächlich erfassten Würfe im Teilsatz-Bereich. So steigt "Würfe"
    // auch, wenn Ergebnisse nur als Summe (ohne Einzelwürfe) über die Übersicht eingetragen wurden.
    const wurfCount = arr.reduce((tot, b) => tot + ranges.reduce((s, r, i) => {
      const manual = Array.isArray(b.overrides) && b.overrides[i] != null;
      const actual = (Array.isArray(b.wuerfe) ? b.wuerfe.slice(r.start, r.end) : []).length;
      return s + (manual ? r.soll : actual);
    }, 0), 0);
    return {
      index: i,
      name: sp.name || ('Spieler ' + (i + 1)),
      gesamt,
      saetze,
      bester: saetze.reduce((m, x) => Math.max(m, x.holz), 0),
      schnittSatz: saetze.length ? gesamt / saetze.length : 0,
      schnittWurf: wurfCount ? gesamt / wurfCount : 0,
      wurfCount,
      neuner,                                         // Maximalwürfe (Alle Neune / voller Abräumer)
      neunerQuote: vollChance ? neuner / vollChance : 0, // Anteil 9er an Würfen aus vollem Bild
      fehl: wuerfe.filter((w) => w === 0).length,    // Fehlwürfe (kein Kegel getroffen)
      kranz,                                          // Kränze (nur König 5 blieb stehen)
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
