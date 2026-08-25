// Reine Bahnwechsel-Logik: der statische Bahnplan (Setup-Vorschau) und die dynamische
// Bahn-Belegung mit Bahnwechsel-Gating (Wurferfassung). Beide Funktionen sind rein.

// ── Statischer Bahnplan (Setup) ──────────────────────────────────────────────
//
// Bahn je Spieler und Satz laut Startbahn + Bahnwechsel.
//  plus1/minus1 : jede Runde +1 bzw. -1 Bahn (mod Bahnanzahl)
//  fest         : bleibt auf der Startbahn
//  classic      : Duo (Nachbarpaar) — tauschen, dann Block +2, dann tauschen (swap/block/swap ...)
//  bohle        : Duo — tauschen, dann Block +2 MIT Tausch (gerade/ungerade wechseln)
// Geordnete Liste der bespielten Bahnnummern. Bei freier Bahnauswahl (Anlage) ist das die
// explizit gewählte Liste `bahnListe` (auch nicht fortlaufend erlaubt); sonst der klassische
// fortlaufende Bereich ersteBahn … ersteBahn+bahnen-1. Alle Bahn-Berechnungen laufen über
// den INDEX in dieser Liste, sodass Bahnwechsel auch bei beliebiger Bahnauswahl greift.
export function laneListOf(s) {
  if (Array.isArray(s.bahnListe) && s.bahnListe.length) return s.bahnListe.slice().sort((a, b) => a - b);
  return Array.from({ length: s.bahnen }, (_, i) => s.ersteBahn + i);
}

export function lanePlan(s) {
  const laneList = laneListOf(s);
  const B = laneList.length;
  const mode = s.bahnwechsel;
  return s.spielerData.map((pl) => {
    let startIdx = laneList.indexOf(pl.startBahn); // Index der Startbahn in der Liste
    if (startIdx < 0) startIdx = 0;                // Startbahn nicht (mehr) in der Liste -> erste
    const lanes = [];

    if (mode === 'classic' || mode === 'bohle') {
      const numDuos = Math.floor(B / 2);
      if (numDuos < 1) { // 1 Bahn -> kein Duo, bleibt fest
        for (let set = 0; set < s.saetze; set++) lanes.push(laneList[startIdx]);
        return lanes;
      }
      let duo = Math.floor(startIdx / 2) % numDuos;
      let pos = startIdx % 2;
      for (let set = 0; set < s.saetze; set++) {
        lanes.push(laneList[duo * 2 + pos]);
        if (set % 2 === 0) {
          pos = 1 - pos;                       // Tausch im Duo
        } else {
          duo = (duo + 1) % numDuos;           // Block auf die naechsten zwei Bahnen
          if (mode === 'bohle') pos = 1 - pos; // Bohle: dabei zusaetzlich tauschen
        }
      }
      return lanes;
    }

    const step = mode === 'plus1' ? 1 : mode === 'minus1' ? -1 : 0;
    for (let set = 0; set < s.saetze; set++) {
      const idx = (((startIdx + step * set) % B) + B) % B;
      lanes.push(laneList[idx]);
    }
    return lanes;
  });
}

// ── Dynamische Belegung mit Bahnwechsel-Gating (Wurferfassung) ────────────────
//
// Jeder Spieler steht physisch auf genau einer Bahn = der Bahn seines aktuell gespielten
// Satzes (`pos`). `pos` rueckt nur vor, wenn der Satz fertig ist UND die naechste Bahn frei
// wird:
//   - Naechste Bahn frei     -> Spieler wechselt automatisch dorthin.
//   - Naechste Bahn besetzt  -> Spieler WARTET, bleibt sichtbar auf alter Bahn.
//   - Duo-Tausch (Zyklus)    -> loest sich automatisch, sobald BEIDE fertig.
// Rein aus den done-Flags berechnet (kein Extra-Zustand). Eingaben:
//   n          = Anzahl Spieler
//   saetze     = Anzahl Saetze
//   doneMatrix = doneMatrix[sp][satz] -> bool (Satz fertig?)
//   laneOf     = (sp, satz) -> Bahnnummer
// Rückgabe: [{ pos, lane, waiting, fertig }] je Spieler.
export function computeBahnState({ n, saetze, doneMatrix, laneOf }) {
  const N = n;
  const S = saetze;

  // Wie weit ist jeder Spieler? Fuehrende fertige Saetze ab Satz 1.
  const progress = [];
  for (let sp = 0; sp < N; sp++) {
    let k = 0;
    while (k < S && doneMatrix[sp][k]) k++;
    progress[sp] = k;
  }

  const pos = new Array(N).fill(0);
  // Will wechseln: aktuellen Satz fertig, und es gibt eine naechste Bahn.
  const wants = (p) => pos[p] < progress[p] && pos[p] < S - 1;

  let guard = 0;
  for (;;) {
    if (guard++ > 2000) { console.warn('computeBahnState: Fixpunkt-Guard ausgelöst'); break; }
    const occ = {};
    for (let q = 0; q < N; q++) occ[laneOf(q, pos[q])] = q;

    // 1) Wechsel auf eine FREIE Bahn (sofort, ohne Partner).
    let moved = false;
    for (let p = 0; p < N; p++) {
      while (wants(p) && occ[laneOf(p, pos[p] + 1)] === undefined) {
        delete occ[laneOf(p, pos[p])];
        pos[p] += 1;
        occ[laneOf(p, pos[p])] = p;
        moved = true;
      }
    }
    if (moved) continue;

    // 2) Zyklus wartender Spieler gemeinsam rotieren (Bahntausch im Duo etc.).
    const cycle = findWaitingCycle(pos, occ, wants, N, laneOf);
    if (cycle) { cycle.forEach((p) => { pos[p] += 1; }); continue; }
    break;
  }

  const out = [];
  for (let sp = 0; sp < N; sp++) {
    out.push({
      pos: pos[sp],
      lane: laneOf(sp, pos[sp]),
      waiting: wants(sp),                       // am Fixpunkt: wollte, ging nicht -> wartet
      fertig: progress[sp] >= S && pos[sp] >= S - 1,
    });
  }
  return out;
}

// Kette target-Bahn -> dortiger Spieler verfolgen; schliesst sie sich unter lauter
// wartenden Spielern, ist es ein rotierbarer Bahntausch-Zyklus.
function findWaitingCycle(pos, occ, wants, N, laneOf) {
  for (let s = 0; s < N; s++) {
    if (!wants(s)) continue;
    const seen = [];
    let cur = s;
    while (cur != null && wants(cur) && !seen.includes(cur)) {
      seen.push(cur);
      cur = occ[laneOf(cur, pos[cur] + 1)];
    }
    if (cur != null && seen.includes(cur)) return seen.slice(seen.indexOf(cur));
  }
  return null;
}
