// Reine Spiel-Auswertung: aus config + erfassung.bloecke + Teilsatz-ranges eine Statistik
// je Spieler und eine Platzierung berechnen. Browser + Node ladbar, unabhängig vom View
// (per Unit-Test abgesichert, später auch von der Statistik-Seite nutzbar).

import { satzHolz } from './holz.js';

// Auswertung eines (beendeten) Spiels.
//   config:  game.config  (spielerListe, saetze, bahnplan, ersteBahn, wuerfeProSatz …)
//   bloecke: erfassung.bloecke  (je Spieler ein Array von Satz-Blöcken)
//   ranges:  teilsatzRanges(config)
// Rückgabe: { players:[…in Aufstellungs-Reihenfolge…], ranking:[…nach Gesamt absteigend…] }.
// players und ranking teilen sich dieselben Objekte -> `rang` ist auf beiden gesetzt.
export function computeGameStats(config, bloecke, ranges) {
  const players = config.spielerListe.map((sp, i) => {
    const arr = Array.isArray(bloecke[i]) ? bloecke[i] : [];
    const saetze = arr.map((blk, st) => ({
      satz: st + 1,
      bahn: config.bahnplan?.[i]?.[st] ?? (config.ersteBahn + st),
      holz: satzHolz(blk, ranges),
    }));
    const gesamt = saetze.reduce((s, x) => s + x.holz, 0);
    const wuerfe = arr.flatMap((b) => (Array.isArray(b.wuerfe) ? b.wuerfe : []));
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
      neuner: wuerfe.filter((w) => w === 9).length, // Maximalwürfe (Alle Neune / voller Abräumer)
      fehl: wuerfe.filter((w) => w === 0).length,    // Fehlwürfe (kein Kegel getroffen)
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
