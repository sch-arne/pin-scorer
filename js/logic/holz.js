// Reine Holz-/Statusberechnung je Teilsatz und Satz. Bekommt `blk` (ein Satz-Block) und
// die Teilsatz-`ranges` — unabhängig vom View, spaeter auch von den Statistiken nutzbar.
//
// SATZ-ERGEBNIS OHNE TEILSATZ-AUFTEILUNG (`blk.satzOverride`)
// ----------------------------------------------------------
// Neben den Teilsatz-`overrides` kann ein Block das Ergebnis des GANZEN Satzes tragen, ohne zu
// sagen, wie es sich auf Volle und Abräumen verteilt. Gebraucht wird das vom Web-Import
// (logic/sw-web-import.js): der Sportwinner-Ergebnisdienst nennt bei Schere und Classic mit
// Punktwertung ausschliesslich das Satz-Holz. Der Wettkampf bekommt trotzdem die Teilsätze
// SEINER BAHNART — sie bleiben nur leer, statt dass eine erfundene Aufteilung sie füllt.
//
// Vorrang: solange noch ein Teilsatz ohne Ergebnis ist, gilt `satzOverride` als Satz-Holz. Erst
// wenn jeder Teilsatz einen Wert hat (manuell oder erfasst), zählen die Teilsätze — so bleibt
// das importierte Satz-Holz beim Nachtragen von Hand erhalten, bis es vollständig ersetzt ist.

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
    // soll nicht als "falsche Wurfzahl" markiert werden. Ebenso wenig ein Teilsatz, dessen Satz
    // sein Holz selbst trägt (Web-Import): dass dort keine Würfe stehen, ist die Aussage — die
    // Quelle kennt die Aufteilung nicht, das ist kein Erfassungsfehler.
    mark: settled && !manual && !satzOverrideAktiv(blk, ranges) && throwsIn.length !== r.soll,
  };
}

// Hat dieser Teilsatz überhaupt ein Ergebnis — manuell gesetzt ODER Würfe erfasst?
function teilsatzGefuellt(blk, r, i) {
  const ov = Array.isArray(blk.overrides) ? blk.overrides[i] : null;
  if (ov != null) return true;
  const w = Array.isArray(blk.wuerfe) ? blk.wuerfe : [];
  return w.slice(r.start, r.end).length > 0;
}

// Gilt für diesen Satz das Satz-Ergebnis (statt der Summe seiner Teilsätze)? Siehe Kopf.
export function satzOverrideAktiv(blk, ranges) {
  if (!blk || blk.satzOverride == null) return false;
  return ranges.some((r, i) => !teilsatzGefuellt(blk, r, i));
}

export function satzHolz(blk, ranges) {
  if (satzOverrideAktiv(blk, ranges)) return blk.satzOverride;
  return ranges.reduce((s, r, i) => {
    const ov = blk.overrides[i];
    return s + (ov != null ? ov : blk.wuerfe.slice(r.start, r.end).reduce((a, w) => a + w, 0));
  }, 0);
}

// Wurfzahl eines Satzes fürs Zählen (Schnitt/Wurf, Wurf-Zähler): ein manuell gesetzter Teilsatz
// zählt als vollständig, ein reines Satz-Ergebnis als der ganze Satz. Sonst wären Schnitt und
// Wurfzahl eines importierten Spiels 0, obwohl das Holz exakt stimmt.
export function satzWurfCount(blk, ranges) {
  if (satzOverrideAktiv(blk, ranges)) return ranges.reduce((s, r) => s + r.soll, 0);
  return ranges.reduce((s, r, i) => {
    const manual = Array.isArray(blk.overrides) && blk.overrides[i] != null;
    return s + (manual ? r.soll : blk.wuerfe.slice(r.start, r.end).length);
  }, 0);
}

export function satzStatus(blk) {
  if (blk.done) return 'done';
  if (blk.wuerfe.length > 0 || blk.overrides.some((o) => o != null) || blk.satzOverride != null) return 'live';
  return 'pending';
}

// Trägt ein Satz-Ergebnis Inhalt (Würfe, Teilsatz- oder Satz-Ergebnis)? Für „hat hier überhaupt
// jemand etwas erfasst" — von Status-Ableitung und Export geteilt, damit beide gleich urteilen.
export function blockHatInhalt(blk) {
  return !!blk && ((Array.isArray(blk.wuerfe) && blk.wuerfe.length > 0)
    || (Array.isArray(blk.overrides) && blk.overrides.some((o) => o != null))
    || blk.satzOverride != null);
}
