// Reine Regel- und Wertungslogik fuer das Spiel "Hausnummern".
//
// Gespielt wird reihum: jeder Spieler wirft pro DURCHGANG so viele Wuerfe in die Vollen, wie
// die Hausnummer Stellen hat (klassisch vier). Jeder Wurf liefert eine ZIFFER (das gefallene
// Holz), und die Ziffern ergeben nebeneinander gelegt eine Zahl — die Hausnummer. Gewertet
// wird die Summe ueber alle Durchgaenge; je nach Variante gewinnt die hoechste oder die
// niedrigste Summe.
//
// Zwei Dinge unterscheiden das Spiel von allem anderen in dieser App:
//   • Der Wert eines Durchgangs ist KEINE Holzsumme, sondern eine Ziffernfolge — wo ein Wurf
//     landet, entscheidet daher genauso viel wie wie viel Holz faellt.
//   • "Wenig Holz" kann das Ziel sein (niedrige Hausnummer). Deshalb haengt die Ziffer eines
//     Fehlwurfs an der Variante: sie ist immer die SCHLECHTESTE Ziffer.
//
// Reine Logik ohne Store/DOM/Netz (Browser + Node ladbar, per Unit-Test abgesichert).

// Die beiden Spielvarianten.
export const VARIANTEN = [
  { key: 'hoch', label: 'Hohe Hausnummer', desc: 'Die höchste Zahl gewinnt' },
  { key: 'niedrig', label: 'Niedrige Hausnummer', desc: 'Die niedrigste Zahl gewinnt' },
];

// Wie die einzelnen Wuerfe auf die Stellen der Hausnummer verteilt werden. Das ist vor dem
// Spiel auszumachen; 'vorn'/'hinten' laufen automatisch, die beiden Ansage-Varianten fragen
// bei jedem Wurf nach der Stelle (der Unterschied ist nur, WANN gefragt wird — vor oder nach
// dem Wurf; gespeichert wird beides gleich).
export const PLATZIERUNGEN = [
  { key: 'vorn', label: 'Von vorn nach hinten', desc: 'Wurf 1 ganz links, dann weiter nach rechts' },
  { key: 'hinten', label: 'Von hinten nach vorn', desc: 'Wurf 1 ganz rechts, dann weiter nach links' },
  { key: 'ansage-vor', label: 'Stelle vorher ansagen', desc: 'Erst die Stelle ansagen, dann werfen' },
  { key: 'wahl-nach', label: 'Stelle nachher wählen', desc: 'Erst werfen, dann die Stelle wählen' },
];

// Was zaehlt beim Niedrig-Spiel eine DURCHGELAUFENE Kugel — also ein regulaerer Wurf, bei dem
// kein Holz faellt? Standard ist 'neun' (dann ist 1111 die beste Hausnummer: man muss treffen,
// aber moeglichst wenig). Die Sonderregel 'null' laesst den Durchlaeufer als 0 zaehlen, dann
// ist 0000 die beste Zahl.
//
// WICHTIG — das ist nicht dasselbe wie ein UNGUELTIGER Wurf: der zaehlt immer 9 (fehlwurfZiffer),
// auch unter der Sonderregel. Sonst waere die 0 gratis zu haben, indem man absichtlich einen
// Fehlwurf setzt, statt sauber durch die Gasse zu spielen.
//
// Nur bei der niedrigen Hausnummer relevant — beim Hoch-Spiel ist 0 ohnehin die schlechteste Ziffer.
export const NULL_REGELN = [
  { key: 'neun', label: 'Zählt 9', desc: 'Auch ohne Holz muss die Stelle bezahlt werden — beste Zahl 1111' },
  { key: 'null', label: 'Zählt 0', desc: 'Sonderregel: die durchgelaufene Kugel ist eine 0 — beste Zahl 0000' },
];

export const STELLEN_MIN = 2;
export const STELLEN_MAX = 8;
export const STELLEN_DEFAULT = 4;

const istNiedrig = (c) => (c && c.variante) === 'niedrig';

// Anzahl Stellen (= Wuerfe je Durchgang), auf den erlaubten Bereich begrenzt.
export function stellenOf(c) {
  const n = Math.round(Number((c && c.stellen) ?? STELLEN_DEFAULT));
  if (!Number.isFinite(n)) return STELLEN_DEFAULT;
  return Math.min(STELLEN_MAX, Math.max(STELLEN_MIN, n));
}

// Die Ziffer eines ungueltigen Wurfs: immer die schlechtestmoegliche.
export function fehlwurfZiffer(c) {
  return istNiedrig(c) ? 9 : 0;
}

// Holz eines Wurfs -> Ziffer der Hausnummer.
//   ungueltig: der Wurf war ungueltig (Fehlschritt, Kugel von der Bahn o.ae.) -> IMMER die
//              schlechteste Ziffer, unabhaengig von der Durchlaeufer-Regel
//   0 Holz:    beim Niedrig-Spiel die durchgelaufene Kugel -> je nach nullRegel 9 oder 0
export function ziffer(wurf, ungueltig, c) {
  if (ungueltig) return fehlwurfZiffer(c);
  const w = Math.min(9, Math.max(0, Math.round(Number(wurf) || 0)));
  if (w === 0 && istNiedrig(c) && (c.nullRegel || 'neun') === 'neun') return 9;
  return w;
}

// Beste bzw. schlechteste ueberhaupt erreichbare Hausnummer eines Durchgangs — im Setup als
// Rueckmeldung auf die gewaehlten Regeln ("die niedrigste mögliche Hausnummer ist 1111").
export function besteZiffer(c) {
  if (!istNiedrig(c)) return 9;
  return (c && c.nullRegel) === 'null' ? 0 : 1;
}

export function besteHausnummer(c) {
  return Number(String(besteZiffer(c)).repeat(stellenOf(c)));
}

export function schlechtesteHausnummer(c) {
  return Number(String(fehlwurfZiffer(c)).repeat(stellenOf(c)));
}

// Die Stelle, auf der Wurf Nr. `k` (0-basiert) automatisch landet — oder null, wenn die
// Platzierung angesagt/gewaehlt wird und damit nicht aus der Wurfnummer folgt.
export function autoPosition(k, c) {
  const p = (c && c.platzierung) || 'vorn';
  const stellen = stellenOf(c);
  if (p === 'vorn') return k < stellen ? k : null;
  if (p === 'hinten') return k < stellen ? stellen - 1 - k : null;
  return null;
}

// Stelle je bereits geworfenem Wurf. Bei den automatischen Varianten aus der Wurfnummer
// abgeleitet (der gespeicherte Wert dient nur als Rueckfall), bei den Ansage-Varianten der
// gespeicherte Wert. Wuerfe ohne gueltige Stelle liefern null und zaehlen nicht mit.
export function positionen(blk, c) {
  const stellen = stellenOf(c);
  const wuerfe = (blk && blk.wuerfe) || [];
  const pos = (blk && blk.pos) || [];
  const auto = (c && c.platzierung) === 'vorn' || (c && c.platzierung) === 'hinten';
  const belegt = new Set();
  return wuerfe.map((_, k) => {
    const p = auto ? autoPosition(k, c) : pos[k];
    const ok = Number.isInteger(p) && p >= 0 && p < stellen && !belegt.has(p);
    if (!ok) return null;
    belegt.add(p);
    return p;
  });
}

// Noch freie Stellen dieses Durchgangs (aufsteigend) — die Auswahl der Ansage-Varianten.
export function freieStellen(blk, c) {
  const belegt = new Set(positionen(blk, c).filter((p) => p != null));
  const out = [];
  for (let i = 0; i < stellenOf(c); i += 1) if (!belegt.has(i)) out.push(i);
  return out;
}

// Die Stelle, auf der der NAECHSTE Wurf landet — null, wenn sie erst angesagt/gewaehlt wird
// (oder der Durchgang voll ist).
export function naechsteStelle(blk, c) {
  const frei = freieStellen(blk, c);
  if (!frei.length) return null;
  const p = autoPosition(((blk && blk.wuerfe) || []).length, c);
  return p != null && frei.includes(p) ? p : null;
}

// Die Hausnummer eines Durchgangs Stelle fuer Stelle: Ziffer oder null (noch nicht geworfen).
export function ziffernOf(blk, c) {
  const out = Array.from({ length: stellenOf(c) }, () => null);
  const pos = positionen(blk, c);
  const wuerfe = (blk && blk.wuerfe) || [];
  const ung = (blk && blk.ungueltig) || [];
  pos.forEach((p, k) => {
    if (p != null) out[p] = ziffer(wuerfe[k], ung[k], c);
  });
  return out;
}

// Sind alle Stellen geworfen?
export function durchgangFertig(blk, c) {
  return ziffernOf(blk, c).every((z) => z != null);
}

// Der Zahlenwert eines Durchgangs. Noch offene Stellen zaehlen 0 — deshalb ist der Wert eines
// UNFERTIGEN Durchgangs nur ein Zwischenstand und geht nicht in die Wertung ein (siehe summe).
export function hausnummerWert(blk, c) {
  return ziffernOf(blk, c).reduce((n, z) => n * 10 + (z == null ? 0 : z), 0);
}

// Anzeigetext der Hausnummer, offene Stellen als "–". Fuehrende Nullen bleiben stehen: bei
// vier Stellen ist 0421 eine andere Hausnummer als 421.
export function hausnummerText(blk, c) {
  return ziffernOf(blk, c).map((z) => (z == null ? '–' : String(z))).join('');
}

// Eine Zahl in der Stellenzahl des Spiels darstellen (mit fuehrenden Nullen).
export function formatZahl(wert, c) {
  return String(Math.max(0, Math.round(Number(wert) || 0))).padStart(stellenOf(c), '0');
}

// Gewertete Summe eines Spielers: nur ABGESCHLOSSENE Durchgaenge. Ein halb geworfener
// Durchgang wuerde beim Niedrig-Spiel sonst als Bestwert dastehen, nur weil die restlichen
// Stellen noch 0 sind.
export function summe(satzArr, c) {
  return (satzArr || []).reduce((s, blk) => s + (durchgangFertig(blk, c) ? hausnummerWert(blk, c) : 0), 0);
}

// Ist das ganze Spiel durch (alle Spieler, alle Durchgaenge)?
export function spielFertig(c, bloecke) {
  const runden = (c && c.saetze) || 0;
  const arr = bloecke || [];
  if (!arr.length) return false;
  return arr.every((satzArr) => (satzArr || []).length >= runden
    && satzArr.slice(0, runden).every((blk) => durchgangFertig(blk, c)));
}

// Rangliste ueber alle Spieler. Rueckgabe je Spieler:
//   { pos, name, zahlen[], fertig[], summe, gespielt, rang }
// `zahlen` traegt je Durchgang den Zahlenwert (auch unfertige, fuer die Anzeige), `fertig`
// sagt, ob er gewertet wurde. Gleiche Summe = gleicher Rang (danach wird uebersprungen).
export function rangliste(c, bloecke) {
  const runden = (c && c.saetze) || 0;
  const namen = (c && c.spielerListe) || [];
  const rows = (bloecke || []).map((satzArr, i) => {
    const saetze = (satzArr || []).slice(0, runden);
    return {
      pos: i,
      name: (namen[i] && namen[i].name) || ('Spieler ' + (i + 1)),
      zahlen: saetze.map((blk) => hausnummerWert(blk, c)),
      fertig: saetze.map((blk) => durchgangFertig(blk, c)),
      summe: summe(saetze, c),
      gespielt: saetze.filter((blk) => durchgangFertig(blk, c)).length,
    };
  });
  const besser = istNiedrig(c)
    ? (a, b) => a.summe - b.summe
    : (a, b) => b.summe - a.summe;
  // Wer noch gar keinen Durchgang beendet hat, steht nicht vorn: seine Summe 0 waere beim
  // Niedrig-Spiel sonst unschlagbar. Solche Spieler landen hinter allen anderen.
  const sortiert = rows.slice().sort((a, b) => {
    if (!a.gespielt !== !b.gespielt) return a.gespielt ? -1 : 1;
    return besser(a, b) || a.pos - b.pos;
  });
  let rang = 0;
  let letzte = null;
  sortiert.forEach((r, i) => {
    if (letzte === null || r.summe !== letzte || !r.gespielt) rang = i + 1;
    letzte = r.gespielt ? r.summe : null;
    r.rang = rang;
  });
  return sortiert;
}
