// Reine Holz-/Statusberechnung je Teilsatz und Satz. Bekommt `blk` (ein Satz-Block) und
// die Teilsatz-`ranges` — unabhängig vom View, spaeter auch von den Statistiken nutzbar.

export function teilsatzStats(blk, ranges, i, satzDone) {
  const r = ranges[i];
  const throwsIn = blk.wuerfe.slice(r.start, r.end);
  const sum = throwsIn.reduce((s, w) => s + w, 0);
  const manual = blk.overrides[i] != null;
  const laterHasThrows = blk.wuerfe.length > r.end; // ein spaeterer Teilsatz hat schon Wuerfe
  const settled = manual || laterHasThrows || satzDone;
  return {
    val: manual ? blk.overrides[i] : sum,
    // Ein manuell eingetragenes Ergebnis (z. B. aus der Übersicht, ohne Einzelwürfe) zählt als
    // vollständiger Teilsatz -> Wurfzähler springt auf Soll (statt bei den erfassten Würfen zu bleiben).
    count: manual ? r.soll : throwsIn.length,
    soll: r.soll,
    manual,
    // Mismatch-Warnung nur für ERFASSTE (nicht manuell gesetzte) Teilsätze: ein manuell
    // eingegebenes Ergebnis ist Absicht (z. B. nachgetragener Satz ohne Einzelwürfe) und
    // soll nicht als "falsche Wurfzahl" markiert werden.
    mark: settled && !manual && throwsIn.length !== r.soll,
  };
}

export function satzHolz(blk, ranges) {
  return ranges.reduce((s, r, i) => {
    const ov = blk.overrides[i];
    return s + (ov != null ? ov : blk.wuerfe.slice(r.start, r.end).reduce((a, w) => a + w, 0));
  }, 0);
}

export function satzStatus(blk) {
  if (blk.done) return 'done';
  if (blk.wuerfe.length > 0 || blk.overrides.some((o) => o != null)) return 'live';
  return 'pending';
}
