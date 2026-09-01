// Mannschafts-Auswertung eines Wettkampfs (Wettkampf-Hub): je Mannschaft eine Tafel mit
// Kennzahlen + Bahn-/Satz-Vergleich ODER dem Wurf-Bild — wahlweise gefiltert nach Bahn, Satz und
// Teilsatz. Welche der beiden Ansichten gilt, sagt `ui.tab` ('statistik' | 'wurfbild'); umgeschaltet
// wird im Hub, dessen Leiste zwischen Durchgängen und diesen beiden Ansichten wählt.
// Reine HTML-Erzeugung aus (wettkampf, stats, ui); verdrahtet wird im Hub (die Filter-Chips
// setzen nur den View-State und rendern neu).
//
// Anders als im Einzelspiel sind Bahn und Satz hier eigenständige Dimensionen (siehe
// logic/mannschaft-statistik.js) — alle drei Filter sind frei kombinierbar.
//
// Die Optik übernimmt bewusst die vorhandenen Bausteine: Team-Tafeln (.wk-team-card) wie in der
// Mannschafts-Übersicht, Filter-Chips (.wb-*) und Balkenzeilen (.ud-*) wie im Wurf-Bild der
// Erfassung. So sieht der Wettkampf aus wie das Einzelspiel, nur eine Ebene höher.

import {
  ALLE, filterOptionen, mannschaftAuswertung, filterAktiv,
} from '../logic/mannschaft-statistik.js';
import { esc } from '../util.js';

const MODUS_LABEL = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz-Abräumen' };

// Standard-Filter der Ansicht (Hub-State). Der aktive Tab (Statistik/Wurf-Bild) kommt vom
// Umschalter im Hub und wird als `ui.tab` hereingereicht.
export function leererAuswertungFilter() { return { bahn: ALLE, satz: ALLE, teil: ALLE }; }

// Eine Chip-Zeile der Filterleiste.
function chipRow(label, attr, werte, cur, alleLabel) {
  const chip = (val, txt) => {
    const on = String(cur) === String(val);
    return `<button type="button" class="wb-chip${on ? ' is-on' : ''}" ${attr}="${esc(String(val))}" aria-pressed="${on}">${esc(txt)}</button>`;
  };
  const chips = [chip(ALLE, alleLabel)].concat(werte.map((w) => chip(w.val, w.txt))).join('');
  return `<div class="wb-row"><span class="wb-row-lbl">${esc(label)}</span><div class="wb-chips">${chips}</div></div>`;
}

// Balkenzeile (wie im Wurf-Bild): Beschriftung, Balken, Zahl + kleiner Zusatz.
function barRow(val, note, breite, zahl, zusatz, cls) {
  return `
    <div class="ud-row${cls || ''}">
      <span class="ud-val">${esc(String(val))}${note ? `<span class="ud-note">${esc(note)}</span>` : ''}</span>
      <span class="ud-bar"><span class="ud-total" style="width:${breite}%"><span class="ud-fill" style="width:100%"></span></span></span>
      <span class="ud-count">${esc(String(zahl))}${zusatz ? `<span class="ud-pct">${esc(String(zusatz))}</span>` : ''}</span>
    </div>`;
}

// Kennzahl-Kacheln einer Mannschaft — bewusst die Zahlen, die NICHT schon in der Mannschafts-
// Übersicht darüber stehen (Holz/Volle/Abräumen/EWP stehen dort in der Ergebnistabelle).
function kacheln(k, opt) {
  const m = (val, lbl) => `<div class="stats-metric"><span class="stats-metric-val">${val}</span><span class="stats-metric-lbl">${lbl}</span></div>`;
  const hatKranz = opt.modi.includes('kranz-abraeumen') || k.kranz > 0;
  const hatAbraeum = opt.modi.some((x) => x === 'abraeumen' || x === 'kranz-abraeumen');
  return `
    <div class="stats-metrics">
      ${m(k.wurfCount, 'Würfe')}
      ${m(k.neuner, 'Alle Neune ☆')}
      ${k.vollChance ? m(Math.round(k.neunerQuote * 100) + ' %', '9er-Quote (volles Bild)') : ''}
      ${hatKranz ? m(k.kranz, 'Kränze ♔') : ''}
      ${hatAbraeum && k.raeumer ? m(k.raeumSchnitt.toFixed(1), 'Ø Würfe/Räumer') : ''}
    </div>`;
}

// Bahn-Vergleich und Satz-Verlauf: je Zeile ein Balken mit dem Mannschafts-Schnitt.
// Beide zeigen IMMER alle Bahnen/Sätze — die gefilterte Zeile ist hervorgehoben (is-sel),
// damit der Vergleich seinen Bezug behält (siehe aufschluesselung() in der Logik).
function reihe(titel, zeilen, praefix, skala, hinweis) {
  if (!zeilen.length) return '';
  const rows = zeilen.map((z) => barRow(
    `${praefix}${z.wert}`, '',
    skala ? (z.schnitt / skala) * 100 : 0,
    z.schnitt ? Math.round(z.schnitt) : '–',
    z.holz ? `${z.holz} Holz` : '',
    z.gewaehlt ? ' is-sel' : '',
  )).join('');
  return `
    <p class="mba-sub">${esc(titel)}<small>${esc(hinweis)}</small></p>
    <div class="ueber-dist">${rows}</div>`;
}

// Wurf-Bild einer Mannschaft: wie häufig welches Holz-Ergebnis fiel (nur einzeln erfasste Würfe).
function wurfBild(k, skala) {
  if (!k.erfasst) {
    return `<p class="ueber-dist-empty">Keine einzeln erfassten Würfe in dieser Auswahl.<br><span>Nur als Summe eingetragene Ergebnisse zählen hier nicht mit.</span></p>`;
  }
  const rows = [];
  for (let v = 9; v >= 0; v -= 1) {
    const n = k.verteilung[v];
    const pct = k.erfasst ? Math.round((n / k.erfasst) * 100) : 0;
    const cls = v === 9 ? ' is-neuner' : v === 0 ? ' is-fehl' : '';
    const note = v === 9 ? '☆' : v === 0 ? 'Fehl' : '';
    rows.push(barRow(v, note, skala ? (n / skala) * 100 : 0, n, `${pct}%`, cls));
  }
  return `
    <p class="mba-sub">Wurf-Bild<small>${k.erfasst} erfasste Würfe · gleiche Skala in beiden Mannschaften</small></p>
    <div class="ueber-dist">${rows.join('')}</div>`;
}

// Kopfzeile einer Tafel: Name, wie viel Auswahl dahintersteckt (Spieler/Sätze) und das Holz.
function kopf(name, k) {
  const teile = `${k.spieler} Spieler · ${k.saetze} ${k.saetze === 1 ? 'Satz' : 'Sätze'}`;
  return `
    <div class="wk-team-head">
      <span class="wk-team-name">${esc(name)}</span>
      <small class="wk-team-lanes">${esc(teile)}</small>
      <span class="wk-team-sp">${k.holz}<small>Holz</small></span>
    </div>`;
}

// Die ganze Sektion. `ui` = { bahn, satz, teil, tab }, `kz` = Kontrollzentrum-Layout (breit).
export function mannschaftAuswertungSection(wettkampf, stats, ui, kz) {
  const teams = (wettkampf && wettkampf.mannschaften) || [];
  if (!teams.length) return '';
  const einzel = (stats && stats.einzel) || [];
  const opt = filterOptionen(einzel);
  const facing = !!kz && teams.length === 2;
  const rahmen = (inhalt) => `
    <section class="field kz-team-auswertung${facing ? ' is-facing' : ''}">${inhalt}</section>`;

  // Vor dem ersten erfassten Durchgang gibt es weder Bahnen noch Sätze — statt leerer Balken
  // ein Hinweis, was hier entstehen wird.
  if (!opt.bahnen.length) {
    return rahmen('<p class="field-hint">Sobald im ersten Durchgang erfasst wird, stehen hier Mannschafts-Kennzahlen und das Wurf-Bild — filterbar nach Bahn, Satz und Teilsatz.</p>');
  }

  // Filterleiste: Bahn · Satz · Teilsatz (Letzterer nur, wenn das Programm mehrere Modi kennt).
  const filter = { bahn: ui.bahn, satz: ui.satz, teil: ui.teil };
  const rows = [
    chipRow('Bahn', 'data-mb-bahn', opt.bahnen.map((b) => ({ val: b, txt: `Bahn ${b}` })), ui.bahn, 'Alle Bahnen'),
    chipRow('Satz', 'data-mb-satz', opt.saetze.map((s) => ({ val: s, txt: `Satz ${s}` })), ui.satz, 'Alle Sätze'),
    opt.modi.length > 1
      ? chipRow('Teilsatz', 'data-mb-teil', opt.modi.map((m) => ({ val: m, txt: MODUS_LABEL[m] || m })), ui.teil, 'Alle')
      : '',
  ].join('');

  // Auswertung je Mannschaft — die Skalen laufen über BEIDE Tafeln, damit die Balken der
  // Mannschaften direkt vergleichbar sind (gleiche Länge = gleicher Wert).
  const daten = teams.map((m) => ({ m, k: mannschaftAuswertung(einzel, m.id, filter, opt) }));
  const maxSchnittBahn = Math.max(1, ...daten.flatMap((d) => d.k.bahnen.map((b) => b.schnitt)));
  const maxSchnittSatz = Math.max(1, ...daten.flatMap((d) => d.k.satzReihe.map((s) => s.schnitt)));
  const maxVert = Math.max(1, ...daten.flatMap((d) => d.k.verteilung));

  const cards = daten.map(({ m, k }, ti) => {
    const body = ui.tab === 'wurfbild'
      ? wurfBild(k, maxVert)
      : `${kacheln(k, opt)}
         ${reihe('Bahn-Vergleich', k.bahnen, 'B', maxSchnittBahn, 'Ø Holz je Spieler und Satz')}
         ${reihe('Satz-Verlauf', k.satzReihe, 'S', maxSchnittSatz, 'Ø Holz je Spieler')}`;
    const mirror = facing && ti === 1;
    return `
      <div class="wk-team-card${mirror ? ' is-mirror mba-mirror' : ''}">
        ${kopf(m.name, k)}
        ${body}
      </div>`;
  }).join('');

  const hinweis = filterAktiv(filter)
    ? 'Kennzahlen und Wurf-Bild folgen dem Filter. Bahn-Vergleich und Satz-Verlauf zeigen weiter alle Zeilen — die gewählte ist hervorgehoben.'
    : 'Bahn, Satz und Teilsatz sind frei kombinierbar — z. B. „Satz 1 auf Bahn 3, nur Volle".';

  return rahmen(`
      <div class="wb-filter">${rows}</div>
      <div class="wk-teams">${cards}</div>
      <p class="field-hint">${esc(hinweis)}</p>`);
}
