// Reine Logik rund um Sätze und Teilsätze — von Setup UND Wurferfassung genutzt.

// Teiler von n (fuer gleichmaessige Teilsatz-Aufteilung).
export function divisors(n) {
  const ds = [];
  for (let i = 1; i <= n; i++) if (n % i === 0) ds.push(i);
  return ds;
}

// Der Teiler von n, der target am naechsten liegt (bei Gleichstand der kleinere).
export function nearestDivisor(n, target) {
  const ds = divisors(n);
  return ds.reduce((best, d) => (Math.abs(d - target) < Math.abs(best - target) ? d : best), ds[0]);
}

// Wuerfe je Teilsatz (gleichmaessig; n teilt total).
export function throwsPerPart(total, n) {
  const base = Math.floor(total / n);
  const rest = total % n;
  return Array.from({ length: n }, (_, i) => base + (i < rest ? 1 : 0));
}

// Teilsatz-Bereiche (kumulative Wurf-Offsets) aus der Konfiguration.
export function teilsatzRanges(c) {
  const ranges = [];
  let start = 0;
  c.teilsaetze.forEach((t) => {
    ranges.push({ start, end: start + t.wuerfe, soll: t.wuerfe, modus: t.modus });
    start += t.wuerfe;
  });
  return ranges;
}
