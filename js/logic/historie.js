// Historie sortieren und filtern — die Auswahl über den Karten in den Statistiken.
//
// Ein Historien-Eintrag ist ein SPIEL (ein Einzelspiel oder ein ganzer Wettkampf, siehe
// views/statistiken.js). Zum Wiederfinden zählen zwei Merkmale, die jeder Eintrag trägt:
//
//   • die SPIELART  — Training oder Wettkampf (spielarten.js kennt Label + Icon),
//   • die ANLAGE    — auf der gespielt wurde; ohne Anlage bleibt ein Spiel rein lokal.
//
// Beides steht an unterschiedlichen Stellen (Einzelspiel: config, Wettkampf: Stammdaten),
// deshalb vereinheitlichen metaOfGame/metaOfWettkampf sie hier zu EINER Form. Der Rest ist
// reine Mengenarbeit: welche Werte kommen überhaupt vor (filterOptionen) und passt ein
// Eintrag zur aktuellen Auswahl (passtZuFilter).
//
// Reine Logik ohne Store/DOM/Netz (Browser + Node ladbar, per Unit-Test abgesichert).

import { labelOf, iconOf } from './spielarten.js';

export const ALLE = '';          // Filterwert „keine Einschränkung"
export const OHNE_ANLAGE = 'ohne'; // Filterwert „Spiele ohne Anlage"

const txt = (v) => String(v == null ? '' : v).trim();

// Merkmale eines Einzelspiels. Die Anlage steht in der Spiel-Config (setup-wk.js schreibt
// anlageId/anlageName beim Start); `spiel` ist der Spielart-Schlüssel aus spielarten.js.
export function metaOfGame(g) {
  const c = (g && g.config) || {};
  return {
    art: txt(g && g.spiel) || 'sportkegler-wk',
    anlageId: txt(c.anlageId),
    anlageName: txt(c.anlageName),
  };
}

// Merkmale eines Wettkampfs. Anlage und Typ stehen hier direkt an den Stammdaten.
export function metaOfWettkampf(w) {
  return {
    art: txt(w && w.typ) || 'sportkegler-wettkampf',
    anlageId: txt(w && w.anlageId),
    anlageName: txt(w && w.anlageName),
  };
}

// Welche Filterwerte kommen in dieser Historie vor? Rückgabe:
//   { arten: [{ key, label, n }], anlagen: [{ id, name, n }] }
// Gezählt wird je Wert, damit die Auswahl zeigt, wie viel dahinter steckt. Der Name einer
// Anlage wird über alle Einträge hinweg zusammengetragen: eine ferngeladene Karte kennt
// womöglich nur die id, eine lokale desselben Orts aber den Klarnamen.
// „Ohne Anlage" ist ein eigener Eintrag (id = OHNE_ANLAGE) — nur wenn es solche Spiele gibt.
export function filterOptionen(metas) {
  const arten = new Map();
  const anlagen = new Map();
  let ohne = 0;
  (metas || []).forEach((m) => {
    const art = txt(m && m.art);
    if (art) arten.set(art, (arten.get(art) || 0) + 1);
    const id = txt(m && m.anlageId);
    if (!id) { ohne += 1; return; }
    const cur = anlagen.get(id) || { id, name: '', n: 0 };
    cur.n += 1;
    if (!cur.name) cur.name = txt(m && m.anlageName);
    anlagen.set(id, cur);
  });

  const artListe = [...arten.entries()]
    .map(([key, n]) => ({ key, label: `${iconOf(key)} ${labelOf(key)}`, n }))
    .sort((a, b) => a.label.localeCompare(b.label, 'de'));
  const anlagenListe = [...anlagen.values()]
    .map((a) => ({ ...a, name: a.name || 'Anlage' }))
    .sort((a, b) => a.name.localeCompare(b.name, 'de'));
  if (ohne) anlagenListe.push({ id: OHNE_ANLAGE, name: 'Ohne Anlage', n: ohne });
  return { arten: artListe, anlagen: anlagenListe };
}

// Passt ein Eintrag zur Auswahl? filter = { art, anlage } — leere Werte schränken nicht ein.
export function passtZuFilter(meta, filter) {
  const f = filter || {};
  const m = meta || {};
  const art = txt(f.art);
  if (art && txt(m.art) !== art) return false;
  const anlage = txt(f.anlage);
  if (!anlage) return true;
  if (anlage === OHNE_ANLAGE) return !txt(m.anlageId);
  return txt(m.anlageId) === anlage;
}

// Lohnt sich die Filterleiste überhaupt? Erst wenn es etwas zu unterscheiden GIBT — bei
// lauter gleichartigen Spielen auf derselben Anlage wäre sie nur Beiwerk.
export function filterSinnvoll(optionen) {
  if (!optionen) return false;
  return (optionen.arten || []).length > 1 || (optionen.anlagen || []).length > 1;
}

// Wie kam dieses Ergebnis in MEINE Statistik? Die beiden Wege sind gleichwertig, aber
// unterschiedlich verlässlich — und der Nutzer soll sehen, welcher gegriffen hat:
//   'lizenz'    — die eigene LizenzID steht an der Ergebniszeile. Das findet einen auch in
//                 fremd erfassten Spielen und lässt sich nicht versehentlich verstellen.
//   'zuordnung' — jemand (ich) hat die Zeile ausdrücklich dem eigenen Konto zugeordnet:
//                 ★ im Setup, ★ im Wettkampf-Hub oder „Das war ich" in der Historie.
export function ergebnisQuelle(row, meinePass) {
  const pass = txt(meinePass);
  if (pass && txt(row && row.passnummer) === pass) return 'lizenz';
  return 'zuordnung';
}

export const QUELLE_LABEL = {
  lizenz: '🔖 über LizenzID',
  zuordnung: '★ zugeordnet',
};

// Zählt die Wege einer Ergebnisliste -> { lizenz, zuordnung }. Für die Kennzahlen-Box:
// „12 Spiele · 8 über LizenzID · 4 zugeordnet".
export function quellenZaehlen(rows, meinePass) {
  const out = { lizenz: 0, zuordnung: 0 };
  (rows || []).forEach((r) => { out[ergebnisQuelle(r, meinePass)] += 1; });
  return out;
}
