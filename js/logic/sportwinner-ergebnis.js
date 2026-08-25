// Rückschreiben in Sportwinner: aus den erfassten Würfen eines Wettkampfs die Zahlen
// bauen, die die Brücke (interface.dll) je Spieler-Slot und Bahn setzt — Volle, Abräumen
// und Fehler. Reine Logik ohne Netz/DOM: die App (im Browser auf dem Vereins-PC, dem
// Wettkampf beigetreten) rechnet exakt mit derselben Auswertung wie in der Anzeige und
// schickt das Ergebnis lokal an die Brücke, die es per DLL-Setter in Sportwinner schreibt.
// Per Unit-Test abgesichert.

import { teilsatzRanges } from './teilsaetze.js';
import { teilsatzStats } from './holz.js';
import { lanePlan } from './bahnwechsel.js';

// Sportwinner kennt je Spielslot genau 4 Bahnen (= 4 Sätze). Mehr Sätze werden nicht
// geschrieben (die Brücke ignoriert Bahnen ausserhalb 0..maxBahnen-1 zusätzlich).
export const SW_BAHNEN = 4;

// Stabiler Schlüssel einer Ergebnis-Zelle (Seite/Slot/Bahn) — genutzt für das Freeze-Set
// (Konflikt-Erkennung) und als UI-Key. Muss zwischen Push und Konflikt-Logik identisch sein.
export function ergKey(side, slot, bahn) {
  return `erg|${side}|${slot}|${bahn}`;
}

// Teilsatz-Modi, die in Sportwinner als „Abräumen" zählen (der Rest = „Volle").
export const ABRAEUM_MODI = new Set(['abraeumen', 'kranz-abraeumen']);

// Ein Satz-Block -> { volle, abr, fehler } für Sportwinner.
//   volle  = Summe der Volle-Teilsätze
//   abr    = Summe der Abräum-Teilsätze
//   fehler = Fehlwürfe (Wurf = 0) in den Abräum-Teilsätzen
// Manuell als Summe eingetragene Teilsätze (Override) fliessen mit ihrem Wert ein; Fehler
// lassen sich daraus nicht ableiten (keine Einzelwürfe) und bleiben für diesen Teilsatz 0.
export function swSatzWerte(block, ranges) {
  const blk = {
    wuerfe: block && Array.isArray(block.wuerfe) ? block.wuerfe : [],
    overrides: block && Array.isArray(block.overrides) ? block.overrides : [],
  };
  let volle = 0;
  let abr = 0;
  let fehler = 0;
  ranges.forEach((r, i) => {
    const val = teilsatzStats(blk, ranges, i).val || 0;
    if (ABRAEUM_MODI.has(r.modus)) {
      abr += val;
      fehler += blk.wuerfe.slice(r.start, r.end).filter((w) => w === 0).length;
    } else {
      volle += val;
    }
  });
  return { volle, abr, fehler };
}

// (Mannschaft,teamPos) -> { side:'GG'|'G', slot } aus der Sportwinner-Zuordnung des Wettkampfs.
// Von Push UND Konflikt-Erkennung genutzt, damit beide identisch abbilden.
export function swSeitenMap(sw) {
  const map = {};
  if (!sw || !sw.seiten) return map;
  (sw.spieler || []).forEach((p) => {
    map[`${p.mannschaftId}|${p.teamPos}`] = { side: sw.seiten[p.mannschaftId], slot: p.slot };
  });
  return map;
}

// Sportwinner-Bahn-Slot eines Satzes: Position der physischen Bahn dieses Satzes in der
// (sortierten) Bahnliste; ohne Bahnplan/ohne Treffer -> Satz-Index (alte Semantik).
export function bahnSlot(bahnListe, plan, s) {
  if (plan && plan[s] != null) {
    const k = bahnListe.indexOf(plan[s]);
    if (k >= 0) return k;
  }
  return s;
}

// Bahnplan (physische Bahn je Spieler & Satz) eines Spiels bestimmen. Bevorzugt den beim
// Bau gespeicherten `config.bahnplan`; fehlt er, wird er aus Bahnliste + Startbahnen +
// Bahnwechsel neu gerechnet. Gibt null, wenn dafür die Daten fehlen (dann Satz-Index-Modus).
export function bahnplanOf(c) {
  if (Array.isArray(c.bahnplan) && c.bahnplan.length) return c.bahnplan;
  const liste = Array.isArray(c.bahnListe) ? c.bahnListe : [];
  const spieler = c.spielerListe || [];
  if (!liste.length || !spieler.some((sp) => sp.startBahn != null)) return null;
  return lanePlan({
    bahnListe: liste,
    saetze: c.saetze,
    bahnwechsel: c.bahnwechsel,
    spielerData: spieler.map((sp) => ({ startBahn: sp.startBahn })),
  });
}

// Kompletter Wettkampf + Durchgang-Spiele -> Rückschreib-Auftrag für die Brücke:
//   { spielNr, updates: [{ side:'GG'|'G', slot, bahn, volle, abr, fehler }] }
// Ordnet jeden App-Spieler über wettkampf.sportwinner (Mannschaft->Seite, teamPos->slot)
// seinem DLL-Slot zu. Sportwinner führt je Spieler-Slot genau 4 Bahn-Slots = die (bis zu 4)
// bespielten Bahnen der Partie in ihrer Reihenfolge. Das Ergebnis eines Satzes gehört auf die
// PHYSISCHE Bahn, auf der er gespielt wurde (bei Bahnwechsel/verschiedenen Startbahnen ist das
// NICHT der Satz-Index!): Bahn-Slot = Position der physischen Bahn in der sortierten Bahnliste.
// Fehlt der Bahnplan, fällt es auf den Satz-Index zurück (alte Semantik). Gibt null zurück,
// wenn der Wettkampf keine Sportwinner-Zuordnung trägt (dann ist kein Rückschreiben gemeint).
// `excludeKeys` (Set von ergKey(...)) friert einzelne Zellen ein: sie werden NICHT gepusht —
// so überschreibt die Brücke einen strittigen Sportwinner-Eintrag nicht, bevor der Nutzer
// den Konflikt entschieden hat.
export function buildSportwinnerPush(wettkampf, games, { maxBahnen = SW_BAHNEN, excludeKeys = null } = {}) {
  const sw = wettkampf && wettkampf.sportwinner;
  if (!sw || !sw.seiten) return null;

  const mapByKey = swSeitenMap(sw);

  const updates = [];
  (games || []).forEach((g) => {
    const c = g.config || {};
    if (!Array.isArray(c.teilsaetze) || !c.teilsaetze.length) return;
    const ranges = teilsatzRanges(c);
    const bloecke = (g.erfassung && g.erfassung.bloecke) || [];
    const bahnListe = Array.isArray(c.bahnListe) ? c.bahnListe : [];
    const bahnplan = bahnplanOf(c);
    (c.spielerListe || []).forEach((sp, idx) => {
      const m = mapByKey[`${sp.mannschaftId}|${sp.teamPos}`];
      if (!m || m.side == null || m.slot == null) return;
      const satzArr = Array.isArray(bloecke[idx]) ? bloecke[idx] : [];
      const plan = bahnplan && Array.isArray(bahnplan[idx]) ? bahnplan[idx] : null;
      const nSaetze = Math.min(c.saetze || satzArr.length, maxBahnen);
      for (let s = 0; s < nSaetze; s += 1) {
        const bahn = bahnSlot(bahnListe, plan, s);
        if (bahn >= maxBahnen) continue; // ausserhalb der 4 Sportwinner-Bahnen
        if (excludeKeys && excludeKeys.has(ergKey(m.side, m.slot, bahn))) continue; // gefroren
        const w = swSatzWerte(satzArr[s], ranges);
        updates.push({ side: m.side, slot: m.slot, bahn, volle: w.volle, abr: w.abr, fehler: w.fehler });
      }
    });
  });

  return { spielNr: sw.spielNr ?? null, updates };
}
