// Mannschafts-Übersicht eines Wettkampfs — gemeinsames Rendering für den Wettkampf-Hub UND die
// Live-Erfassung (spiel-laufend). Reine HTML-Erzeugung aus (wettkampf, games, stats, wertung);
// keine Verdrahtung. Beide Aufrufer teilen sich so exakt dieselbe Optik.
//
// Mit `editable:true` (Default — der Hub) sind Namen/Startbahnen Eingabefelder (Klassen
// roster-name/roster-lane, vom Hub verdrahtet). Mit `editable:false` (Live-Erfassung/Overlay)
// stehen dieselben Werte als reiner Text — gleiche Tafel, aber ohne Bearbeitung.

import { fmtPunkte } from '../logic/wettkampf-wertung.js';
import { esc } from '../util.js';

// Führende Mannschaft ermitteln: bei aktiver Duell-Wertung die mit den höheren Spielpunkten,
// sonst die (eindeutig) auf Gesamtholz-Rang 1 stehende. Gleichstand -> keine Führung markiert.
function leadTeamId(stats, wertung) {
  if (wertung && wertung.home && wertung.away && wertung.home.spielpunkte !== wertung.away.spielpunkte) {
    return wertung.home.spielpunkte > wertung.away.spielpunkte ? wertung.homeId : wertung.awayId;
  }
  const played = (stats.mannschaften || []).filter((t) => (t.gesamt || 0) > 0);
  const firsts = played.filter((t) => t.rang === 1);
  return firsts.length === 1 ? firsts[0].mannschaftId : null;
}

// Mannschafts-Übersicht: je Mannschaft eine Tafel mit integrierter Aufstellung. Oben Kopf (Name,
// Spielpunkte bei aktiver Duell/EWP-Wertung, Führungs-Markierung). Darunter die Spieler:
//   • solange die Mannschaft noch keine Ergebnisse hat: Aufstellung (Name + Startbahn),
//   • sobald Ergebnisse vorliegen: eine bahnweise Ergebnistabelle je Spieler (Ergebnis pro Bahn)
//     mit Ges. Volle, Ges. Abräumen, Gesamtholz und EWP, plus einer Mannschafts-Summenzeile.
export function teamUebersichtSection(wettkampf, games, stats, wertung, kz, opts = {}) {
  const editable = opts.editable !== false; // Default: bearbeitbar (Hub)
  const teams = wettkampf.mannschaften || [];
  if (!teams.length) return '';
  const lead = leadTeamId(stats, wertung);
  // Namen/Startbahnen der Aufstellung aus den Durchgang-Spielen (für die Bearbeitung im Setup).
  const nameOf = {}; const laneOf = {};
  (games || []).forEach((g) => (g.config?.spielerListe || []).forEach((p) => {
    if (p.mannschaftId && p.teamPos) {
      nameOf[`${p.mannschaftId}|${p.teamPos}`] = p.name || '';
      laneOf[`${p.mannschaftId}|${p.teamPos}`] = p.startBahn;
    }
  }));
  const anyResults = (stats.mannschaften || []).some((t) => (t.gesamt || 0) > 0);
  // Gegenüberstellung (Scoreboard): bei genau zwei Mannschaften auf breitem Schirm stehen sie
  // nebeneinander, die zweite gespiegelt — die Zahlen beider Teams zeigen so zur Mitte.
  const facing = !!kz && teams.length === 2;
  const cards = teams.map((m, ti) =>
    teamCard(wettkampf, m, stats, wertung, lead, nameOf, laneOf, anyResults, facing && ti === 1, editable)).join('');
  return `
    <section class="field kz-team-uebersicht${facing ? ' is-facing' : ''}">
      <div class="wk-teams">${cards}</div>
    </section>`;
}

// Gesamtholz eines Spielers auf einer bestimmten Bahn (summiert, falls die Bahn mehrfach
// gespielt wurde); null, wenn der Spieler auf dieser Bahn (noch) kein Ergebnis hat.
function holzAufBahn(p, bahn) {
  let sum = null;
  ((p && p.saetze) || []).forEach((s) => { if (s.bahn === bahn) sum = (sum || 0) + (s.holz || 0); });
  return sum;
}

// Startbahn-Steuerung eines (noch ergebnislosen) Spielers: Auswahl innerhalb der Team-Bahnen,
// bei nur einer Bahn (oder schreibgeschützt) die feste Anzeige. Änderungen laufen über die
// roster-lane-Verdrahtung (nur im Hub).
function startbahnCtrl(m, pos, teamLanes, laneOf, editable) {
  const cur = laneOf[`${m.id}|${pos}`];
  return (editable && teamLanes.length > 1)
    ? `<select class="wk-lane roster-lane" data-team="${esc(m.id)}" data-pos="${pos}" aria-label="Startbahn">
         ${teamLanes.map((n) => `<option value="${n}"${cur === n ? ' selected' : ''}>Bahn ${n}</option>`).join('')}
       </select>`
    : `<span class="wk-lane-fix">Bahn ${cur ?? (teamLanes[0] ?? '–')}</span>`;
}

function teamCard(wettkampf, m, stats, wertung, lead, nameOf, laneOf, anyResults, mirror, editable) {
  const P = wettkampf.spielerJeMannschaft || 0;
  const teamLanes = (m.lanes || []).slice().sort((a, b) => a - b);
  const st = (stats.mannschaften || []).find((t) => t.mannschaftId === m.id)
    || { gesamt: 0, spieler: 0, schnitt: 0 };
  const w = wertung && wertung.teams && wertung.teams[m.id];
  const isLead = lead === m.id;

  // Spieler dieses Teams nach Position (1 … P), jeweils mit ihrem Ergebnis-Objekt (falls vorhanden).
  const byPos = {};
  (stats.einzel || []).forEach((p) => { if (p.mannschaftId === m.id && p.teamPos) byPos[p.teamPos] = p; });
  const rows = Array.from({ length: P }, (_, k) => ({ pos: k + 1, p: byPos[k + 1] || null }));
  const teamHasResults = rows.some((r) => r.p && (r.p.gesamt || 0) > 0);
  const ewpSum = rows.reduce((s, r) => s + (r.p ? (r.p.ewp || 0) : 0), 0);

  // Kopfzeile mit Spielpunkten (nur bei aktiver Duell/EWP-Wertung UND sobald überhaupt Ergebnisse
  // vorliegen — im reinen Setup ist der Punktestand aus 0-Holz-Gleichstand nicht aussagekräftig).
  const spBox = w && anyResults
    ? `<span class="wk-team-sp" title="Spielpunkte">${fmtPunkte(w.spielpunkte)}<small>Punkte</small></span>`
    : '';
  const head = `
    <div class="wk-team-head">
      <span class="wk-team-rank">${isLead ? '🥇' : ''}</span>
      <span class="wk-team-name">${esc(m.name)}</span>
      <small class="wk-team-lanes">Bahn ${teamLanes.join(', ') || '—'}</small>
      ${spBox}
    </div>`;

  // Die früheren drei Summen-Kacheln (Gesamtholz/EWP/Aufschlüsselung) entfallen — dieselben Zahlen
  // stehen im Kopf (Spielpunkte) und in der Summenzeile der Tabelle (Ges./EWP).
  const body = teamHasResults
    ? ergebnisTabelle(m, rows, st, ewpSum, teamLanes, laneOf, mirror, editable)
    : aufstellungListe(m, rows, teamLanes, nameOf, laneOf, mirror, editable);

  return `
    <div class="wk-team-card${isLead ? ' is-lead' : ''}${mirror ? ' is-mirror' : ''}">
      ${head}
      ${body}
    </div>`;
}

// Nullen unterdrücken: 0/null/undefined werden leer dargestellt (bessere Lesbarkeit der Tabelle).
function nz(v) { return v ? v : ''; }

// Namenszelle: bearbeitbar -> Eingabefeld (roster-name, im Hub verdrahtet); schreibgeschützt ->
// reiner Text (leere Namen zeigen einen dezenten Platzhalter „Team N").
function nameField(m, pos, value, editable) {
  if (editable) {
    return `<input class="wk-name roster-name" data-team="${esc(m.id)}" data-pos="${pos}" type="text" placeholder="${esc(m.name)} ${pos}" value="${esc(value || '')}" />`;
  }
  return value
    ? `<span class="wk-name-static">${esc(value)}</span>`
    : `<span class="wk-name-static is-empty">${esc(m.name)} ${pos}</span>`;
}

// Bahnweise Ergebnistabelle: Pos, Name, Wurf (Startbahn — bei noch ergebnislosen Spielern wählbar),
// je eine Spalte pro gespielter Bahn, dann Volle/Abräumen/Gesamt/EWP. Je Spieler eine Zeile.
// Mannschaft als Fußzeile: je Bahn der Mannschafts-Durchschnitt, rechts die Summen.
// Bei `mirror` (gegenüberstehendes Team) werden die Spalten-Blöcke gespiegelt (Zahlen zur Mitte) —
// der Bahn-Block bleibt dabei ein zusammenhängendes Segment und damit auf beiden Seiten aufsteigend.
function ergebnisTabelle(m, rows, st, ewpSum, teamLanes, laneOf, mirror, editable) {
  // Bahn-Spalten = sortierte Vereinigung aller im Team gespielten Bahnen.
  const bahnSet = new Set();
  rows.forEach((r) => ((r.p && r.p.saetze) || []).forEach((s) => { if (s.bahn != null) bahnSet.add(s.bahn); }));
  const bahnen = [...bahnSet].sort((a, b) => a - b);
  // Die Bahn-Zellen als EIN Segment führen → beim Spiegeln bleibt ihre Reihenfolge aufsteigend.
  const ord = (cells) => (mirror ? cells.slice().reverse() : cells).join('');
  const bahnBlock = (mk) => bahnen.map(mk).join('');

  // Drei gleich breite Blöcke: (Nr + Name) | (W + Bahnen) | (Volle … EWP). Spaltenbreiten fix
  // über den Kopf (table-layout: fixed); reisen beim Spiegeln mit der jeweiligen Spalte mit.
  const T = 100 / 3;
  const nB = Math.max(1, bahnen.length);
  const wPos = 6;
  const wName = (T - wPos).toFixed(2);
  const wWurf = 12;
  const wBahn = ((T - wWurf) / nB).toFixed(2);
  const wNum = (T / 4).toFixed(2);

  const headCells = [
    `<th class="wk-c-pos" style="width:${wPos}%"></th>`,
    `<th class="wk-c-name" style="width:${wName}%"></th>`,
    `<th class="wk-c-wurf" style="width:${wWurf}%">W</th>`,
    bahnBlock((b) => `<th class="wk-c-bahn" style="width:${wBahn}%" title="Bahn ${b}">${b}</th>`),
    `<th class="wk-c-num" style="width:${wNum}%">Volle</th>`,
    `<th class="wk-c-num" style="width:${wNum}%">Abr.</th>`,
    `<th class="wk-c-num wk-c-ges" style="width:${wNum}%">Ges.</th>`,
    `<th class="wk-c-num wk-c-ewp" style="width:${wNum}%">EWP</th>`,
  ];

  const volleSum = rows.reduce((s, r) => s + (r.p ? (r.p.gesamt || 0) - (r.p.abraeum || 0) : 0), 0);
  const abrSum = rows.reduce((s, r) => s + (r.p ? (r.p.abraeum || 0) : 0), 0);

  const bodyRows = rows.map((r) => {
    const p = r.p;
    const played = !!(p && (p.gesamt || 0) > 0);
    const nameCell = `<td class="wk-c-name">${nameField(m, r.pos, p && p.name, editable)}</td>`;
    // W-Spalte: hat der Spieler begonnen → seine bisherige Wurfanzahl; sonst die (noch änderbare)
    // Startbahn zur Auswahl.
    const wurfCell = played
      ? `<td class="wk-c-wurf">${nz(p.wurfCount)}</td>`
      : `<td class="wk-c-wurf">${startbahnCtrl(m, r.pos, teamLanes, laneOf, editable)}</td>`;
    const bahnCells = bahnBlock((b) => `<td class="wk-c-bahn">${played ? nz(holzAufBahn(p, b)) : ''}</td>`);
    const volle = played ? (p.gesamt || 0) - (p.abraeum || 0) : null;
    const cells = [
      `<td class="wk-c-pos">${r.pos}</td>`,
      nameCell,
      wurfCell,
      bahnCells,
      `<td class="wk-c-num">${nz(volle)}</td>`,
      `<td class="wk-c-num">${played ? nz(p.abraeum) : ''}</td>`,
      `<td class="wk-c-num wk-c-ges">${played ? nz(p.gesamt) : ''}</td>`,
      `<td class="wk-c-num wk-c-ewp">${played ? nz(p.ewp) : ''}</td>`,
    ];
    return `<tr>${ord(cells)}</tr>`;
  });

  const footCells = [
    '<td class="wk-c-pos"></td>',
    '<td class="wk-c-name">Ø Mannschaft</td>',
    '<td class="wk-c-wurf"></td>',
    // Je Bahn der Durchschnitt der Mannschaft — nur über die tatsächlich gespielten Ergebnisse
    // (Holz > 0); noch nicht gespielte Bahnen zählen nicht in den Nenner.
    bahnBlock((b) => {
      let sum = 0; let cnt = 0;
      rows.forEach((r) => { const h = holzAufBahn(r.p, b); if (h) { sum += h; cnt += 1; } });
      return `<td class="wk-c-bahn">${cnt ? nz(Math.round(sum / cnt)) : ''}</td>`;
    }),
    `<td class="wk-c-num">${nz(volleSum)}</td>`,
    `<td class="wk-c-num">${nz(abrSum)}</td>`,
    `<td class="wk-c-num wk-c-ges">${nz(st.gesamt)}</td>`,
    `<td class="wk-c-num wk-c-ewp">${nz(ewpSum)}</td>`,
  ];

  // Mindestbreite der Tabelle, damit die dreistelligen Zahlen in LESBARER Größe stehen: reicht der
  // Platz nicht (schmaler Schirm / gegenübergestellte Mannschaften), scrollt die Tabelle im Wrapper
  // waagerecht — die Spalten bleiben groß, statt die Schrift klein zu schrumpfen. Auf breiten
  // Schirmen (Vereins-PC) ist die Tabelle ohnehin breiter, greift width:100% und es scrollt nicht.
  // Bindend ist die schmalste Zahlenspalte: eine Bahn hat nur (33,3−12)/nB %, eine Ergebnis-Spalte
  // 8,3 %; beide sollen ~36px breit sein (dreistellig + Padding, bequem lesbar).
  const COL = 36;
  const minW = Math.round(Math.max(COL / 0.0833, (COL / ((100 / 3 - 12) / nB)) * 100));

  return `
    <div class="wk-tbl-wrap">
      <table class="wk-tbl${mirror ? ' wk-mirror' : ''}" style="min-width:${minW}px">
        <thead><tr>${ord(headCells)}</tr></thead>
        <tbody>${bodyRows.join('')}</tbody>
        <tfoot><tr class="wk-tbl-sum">${ord(footCells)}</tr></tfoot>
      </table>
    </div>`;
}

// Aufstellung (reines Setup, noch keine Ergebnisse im Team): je Position ein Namensfeld und –
// innerhalb der Team-Bahnen – die Startbahn. Bei `mirror` liegen die Namen außen (Zahlen/Bahn
// zur Mitte). Namen und Startbahn werden direkt in die Durchgang-Spiele geschrieben (siehe wire()).
function aufstellungListe(m, rows, teamLanes, nameOf, laneOf, mirror, editable) {
  const lis = rows.map((r) => {
    const val = nameOf[`${m.id}|${r.pos}`] || '';
    return `
      <div class="wk-lu-row${mirror ? ' is-mirror' : ''}">
        <span class="wk-c-pos">${r.pos}</span>
        ${nameField(m, r.pos, val, editable)}
        ${startbahnCtrl(m, r.pos, teamLanes, laneOf, editable)}
      </div>`;
  }).join('');
  return `<div class="wk-lineup">${lis}</div>`;
}
