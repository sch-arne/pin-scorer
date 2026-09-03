// Wurfprotokoll als druckfertiges DIN-A4-Blatt (schwarz-weiß).
//
// Baut aus einem Spiel (config + erfassung.bloecke) je ausgewähltem Spieler eine A4-Seite:
//   Kopf   — „Wurfprotokoll" + Spielname, Name (+ Mannschaft im Wettkampf), Bahn.
//   Mitte  — satzweise, je Teilsatz eine Zeile mit Einzelwürfen; über jeder Wurfzahl das
//            Kegelbild (● gefallen · ○ stehend) und darunter klein die Wurfnummer (pro Satz).
//            Rechts je Teilsatz die TS-Summe und je Satz das Satz-Ergebnis.
//   Fuß    — Teilsatz-Summen (Volle/Abräumen/…), 9er · Kränze · Fehler und das Gesamt.
//
// Rein für den Aufbau; der Druck läuft über einen unsichtbaren <iframe> (offline, ohne
// Fremdpaket). Kennzahlen (9er/Kränze/Fehler/Gesamt) kommen aus logic/statistik.js, damit
// sie exakt zum „Spiel beendet"-Screen passen. Das Kegelbild je Wurf stammt aus blk.kegel[].

import { computeGameStats } from './statistik.js';
import { teilsatzStats, satzHolz, satzStatus } from './holz.js';
import { abraeumScan, isAbraeumMode, volleKranz } from './abraeumen.js';

const MODUS_ABK = { volle: 'Vo', abraeumen: 'Ab', 'kranz-abraeumen': 'Kr' };
const MODUS_LBL = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz-Abräumen' };

// Kegel-Anordnung als Raute, Spalte/Reihe im 5×5-Raster (wie in der Erfassung).
//        9
//     7     8
//  4     5     6
//     2     3
//        1
const POS = { 9: [3, 1], 7: [2, 2], 8: [4, 2], 4: [1, 3], 5: [3, 3], 6: [5, 3], 2: [2, 4], 3: [4, 4], 1: [3, 5] };

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

// Winzige Kegel-Raute als SVG: gefallene Kegel schwarz gefüllt, stehende hohl.
// fallenPins = Array der gefallenen Kegel-Nummern; null/undefined -> kein Bild (unbekannt).
function pinSvg(fallenPins) {
  if (!Array.isArray(fallenPins)) return '';
  const set = new Set(fallenPins);
  let dots = '';
  for (let n = 1; n <= 9; n += 1) {
    const [col, row] = POS[n];
    const x = (col - 1) * 4 + 3;
    const y = (row - 1) * 4 + 3;
    dots += set.has(n)
      ? `<circle cx="${x}" cy="${y}" r="1.7" fill="#000"/>`
      : `<circle cx="${x}" cy="${y}" r="1.5" fill="#fff" stroke="#999" stroke-width="0.6"/>`;
  }
  return `<svg class="wp-svg" width="20" height="20" viewBox="0 0 22 22">${dots}</svg>`;
}

// Eine Wurf-Zelle: Kegelbild oben, Wurfzahl mittig, Wurfnummer (pro Satz) klein unten.
// kranz = echter Kranz (eine 8, nach der nur der König steht) -> ♔; NICHT bloß "König steht".
function throwCell(val, kegel, kranz, nr) {
  const leer = val == null;
  const cls = leer ? 'wp-empty' : (val === 9 ? 'is-neuner' : (val === 0 ? 'is-fehl' : ''));
  const anzeige = leer ? '·' : String(val);
  const kranzMark = kranz ? '<span class="wp-koenig">♔</span>' : '';
  return `<span class="wp-cell">`
    + `<span class="wp-pin">${leer ? '' : pinSvg(kegel)}</span>`
    + `<span class="wp-val ${cls}">${anzeige}${kranzMark}</span>`
    + `<span class="wp-idx">${nr}</span>`
    + `</span>`;
}

// Teilsatz-Zeile: [Satz-Zelle nur i=0] [Würfe] [TS] [Holz-Zelle nur i=0]. Satz- und Holz-Zelle
// spannen per rowspan über alle Teilsätze des Satzes, stehen also nur in der ersten Zeile.
function teilsatzRow(blk, ranges, i, done, satzCell, holzCell) {
  const r = ranges[i];
  const ts = teilsatzStats(blk, ranges, i, done);
  const label = MODUS_ABK[r.modus] || r.modus;

  // Beim (Kranz-)Abräumen liefert der Scan die vor jedem Wurf stehenden Kegel — nötig, um
  // das Kegelbild eines Kranz-Langdrucks (kegel=null, König steht) zu rekonstruieren.
  const scan = isAbraeumMode(r.modus) ? abraeumScan(blk, r) : null;

  let cells = '';
  if (ts.manual && blk.wuerfe.slice(r.start, r.end).length === 0) {
    // Nur als Ergebnis eingetragen (ohne Einzelwürfe) -> Hinweis statt Wurf-Raster.
    cells = `<span class="wp-note">nur Ergebnis eingetragen</span>`;
  } else {
    for (let k = r.start; k < r.end; k += 1) {
      const has = k < blk.wuerfe.length;
      const val = has ? blk.wuerfe[k] : null;
      const koenig = has && Array.isArray(blk.koenig) ? blk.koenig[k] : false;
      // Echter Kranz (fürs ♔): genau wie in der Erfassung — kranzAt aus dem Abräum-Scan bzw.
      // volleKranz in der Volle. NICHT das koenig-Flag ("König steht danach"): eine 2 per
      // Langdruck lässt zwar den König stehen, ist aber kein Kranz.
      const kranz = scan ? !!scan.kranzAt[k] : (r.modus === 'volle' && volleKranz(blk, k));
      let kegel = has ? blk.kegel[k] : null;
      // Fallback für ALTDATEN: früher speicherte der Kranz-Langdruck kegel=null (nur König-Flag).
      // Neue Würfe legen die konkreten Kegel direkt ab; für alte/gerätesynchronisierte Spiele
      // hier das Bild rekonstruieren — die vor dem Wurf stehenden Kegel außer dem König —, aber
      // nur wenn der Reststand exakt bekannt ist UND die Anzahl zum Wurf passt. Sonst kein Bild.
      if (has && kegel == null && koenig && scan) {
        const st = scan.before[k];
        if (st && st.exact) {
          const fallen = st.standing.filter((p) => p !== 5);
          if (fallen.length === val) kegel = fallen;
        }
      }
      cells += throwCell(val, kegel, kranz, k + 1);
    }
  }

  const tsVal = (ts.count > 0 || ts.manual) ? ts.val : '';
  const rowCls = `${i === 0 ? 'wp-satz-first' : ''} ${i === ranges.length - 1 ? 'wp-satz-last' : ''}`.trim();
  return `<tr class="${rowCls}">`
    + (i === 0 ? satzCell : '')
    + `<td class="wp-wuerfe"><div class="wp-wline"><span class="wp-mod">${label}</span><div class="wp-throws">${cells}</div></div></td>`
    + `<td class="wp-ts">${tsVal}</td>`
    + (i === 0 ? holzCell : '')
    + `</tr>`;
}

// Alle Sätze eines Spielers als Tabellenkörper.
function satzRows(arr, ranges) {
  const nTs = ranges.length;
  return arr.map((blk) => {
    const done = satzStatus(blk) === 'done';
    const pending = satzStatus(blk) === 'pending';
    const holz = pending ? '' : satzHolz(blk, ranges);
    const satzCell = `<td class="wp-satz" rowspan="${nTs}"><span class="wp-satz-nr">${blk.__satz}</span><span class="wp-satz-bahn">Bahn ${esc(blk.__bahn)}</span></td>`;
    const holzCell = `<td class="wp-holz" rowspan="${nTs}">${holz}</td>`;
    return ranges.map((_, i) => teilsatzRow(blk, ranges, i, done, satzCell, holzCell)).join('');
  }).join('');
}

// Teilsatz-Summen je Modus (Volle/Abräumen/Kranz) über alle Sätze — für den Fuß.
function teilsatzSummen(arr, ranges) {
  const order = [];
  const sums = {};
  arr.forEach((blk) => {
    const done = satzStatus(blk) === 'done';
    ranges.forEach((r, i) => {
      const lbl = MODUS_LBL[r.modus] || r.modus;
      if (!(lbl in sums)) { sums[lbl] = 0; order.push(lbl); }
      sums[lbl] += teilsatzStats(blk, ranges, i, done).val;
    });
  });
  return order.map((lbl) => ({ label: lbl, val: sums[lbl] }));
}

// Eine A4-Seite für einen Spieler.
function playerPage(p, arr, ranges, meta) {
  // Bahn je Satz + Satznummer an die Blöcke heften (für die Zeilen-Beschriftung).
  arr.forEach((blk, st) => {
    blk.__satz = st + 1;
    blk.__bahn = p.saetze[st] ? p.saetze[st].bahn : '';
  });

  const sums = teilsatzSummen(arr, ranges);
  const sumHtml = sums.map((s) =>
    `<div class="wp-foot-item"><span class="wp-foot-lbl">${esc(s.label)}</span><strong>${s.val}</strong></div>`).join('');

  const mannschaft = meta.istWettkampf && p.mannschaft
    ? `<div><span class="wp-k">Mannschaft</span> <strong>${esc(p.mannschaft)}</strong></div>` : '';
  const bahnKopf = p.startBahn != null ? `<div class="wp-head-right">Bahn ${esc(p.startBahn)}</div>` : '';

  return `
    <section class="wp-page">
      <div class="wp-head">
        <div>
          <div class="wp-title">WURFPROTOKOLL</div>
          <div class="wp-spielname">${esc(meta.titel)}</div>
          <div class="wp-sub">${esc(meta.sub)}</div>
        </div>
        ${bahnKopf}
      </div>
      <div class="wp-name-line">
        <div><span class="wp-k">Name</span> <strong>${esc(p.name)}</strong></div>
        ${mannschaft}
      </div>
      <div class="wp-legende">Kegelbild: ● gefallen · ○ stehend</div>
      <table class="wp-tbl">
        <thead>
          <tr>
            <th rowspan="2" class="wp-th-satz">Satz / Bahn</th>
            <th rowspan="2" class="wp-th-w">Würfe</th>
            <th colspan="2" class="wp-th-erg">Ergebnis</th>
          </tr>
          <tr>
            <th class="wp-th-ts">TS</th>
            <th class="wp-th-holz">Satz</th>
          </tr>
        </thead>
        <tbody>${satzRows(arr, ranges)}</tbody>
      </table>
      <div class="wp-foot">
        <div class="wp-foot-row">
          <div class="wp-foot-group">${sumHtml}</div>
          <div class="wp-foot-group">
            <div class="wp-foot-item"><span class="wp-foot-lbl">9er</span><strong>${p.neuner}</strong></div>
            <div class="wp-foot-item"><span class="wp-foot-lbl">Kränze</span><strong>${p.kranz}</strong></div>
            <div class="wp-foot-item"><span class="wp-foot-lbl">Fehler</span><strong>${p.fehl}</strong></div>
          </div>
        </div>
        <div class="wp-total"><span class="wp-k">GESAMT</span> <strong>${p.gesamt}</strong></div>
      </div>
    </section>`;
}

// Druck-CSS (im Dokument eingebettet, damit das Blatt unabhängig vom App-CSS ist).
const STYLE = `
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body { font-family: Arial, Helvetica, sans-serif; color: #000; background: #fff; font-size: 11px; }
  .wp-page { padding: 10mm 10mm 8mm; page-break-after: always; }
  .wp-page:last-child { page-break-after: auto; }
  .wp-head { display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 2px solid #000; padding-bottom: 6px; }
  .wp-title { font-size: 17px; font-weight: bold; letter-spacing: .5px; }
  .wp-spielname { font-size: 14px; font-weight: bold; margin-top: 2px; }
  .wp-sub { font-size: 10px; color: #333; margin-top: 2px; }
  .wp-head-right { font-size: 11px; color: #333; text-align: right; white-space: nowrap; }
  .wp-name-line { display: flex; justify-content: space-between; gap: 16px; margin: 8px 0 4px; font-size: 12px; }
  .wp-k { color: #555; }
  .wp-legende { font-size: 9px; color: #666; margin-bottom: 8px; }
  table.wp-tbl { width: 100%; border-collapse: collapse; }
  .wp-tbl th { font-weight: normal; font-size: 10px; color: #333; text-align: left; padding: 2px 4px; }
  .wp-th-erg { text-align: center; border-bottom: 1px solid #bbb; }
  .wp-th-ts, .wp-th-holz { text-align: right; }
  .wp-tbl thead tr:last-child th { border-bottom: 1px solid #000; }
  .wp-satz { width: 52px; vertical-align: middle; padding: 4px; border-bottom: 1px solid #000; }
  .wp-satz-nr { font-weight: bold; display: block; }
  .wp-satz-bahn { color: #666; }
  .wp-wuerfe { padding: 3px 4px 5px; }
  .wp-wline { display: flex; align-items: center; }
  .wp-mod { color: #555; width: 18px; flex: none; font-size: 10px; }
  /* Würfe über die ganze Spaltenbreite verteilen (füllen die Zeile statt links zu stehen);
     bei sehr vielen Würfen umbrechen, ohne unter die Kegelbild-Breite zu schrumpfen. */
  .wp-throws { flex: 1; display: flex; flex-wrap: wrap; align-content: center; }
  .wp-holz { width: 36px; text-align: right; vertical-align: middle; font-weight: bold; font-size: 13px; padding: 4px; border-bottom: 1px solid #000; }
  .wp-ts { width: 30px; text-align: right; vertical-align: middle; font-family: 'Courier New', monospace; }
  .wp-satz-first .wp-wuerfe, .wp-satz-first .wp-ts { border-top: 1px dotted #ccc; }
  .wp-satz-last td { border-bottom: 1px solid #000; }
  .wp-cell { flex: 1 0 22px; text-align: center; margin-bottom: 1px; }
  .wp-pin { display: block; line-height: 0; height: 20px; }
  .wp-val { font-family: 'Courier New', monospace; font-size: 10px; line-height: 1.1; display: block; }
  .wp-val.is-neuner { font-weight: bold; }
  .wp-val.is-fehl { text-decoration: underline; }
  .wp-val.wp-empty { color: #bbb; }
  .wp-idx { font-size: 6px; color: #999; line-height: 1; display: block; }
  .wp-koenig { font-size: 7px; vertical-align: super; }
  .wp-note { color: #888; font-style: italic; font-size: 10px; }
  .wp-foot { margin-top: 10px; border-top: 2px solid #000; padding-top: 6px; }
  .wp-foot-row { display: flex; justify-content: space-between; font-size: 11px; }
  .wp-foot-group { display: flex; gap: 16px; }
  .wp-foot-item .wp-foot-lbl { color: #555; margin-right: 4px; }
  .wp-foot-item strong { font-size: 14px; }
  .wp-total { text-align: right; border-top: 1px solid #ccc; margin-top: 6px; padding-top: 5px; font-size: 12px; }
  .wp-total strong { font-size: 20px; }
  @page { size: A4 portrait; margin: 8mm; }
`;

// Die A4-Seiten EINES Spiels bauen (ohne Dokument-Rahmen) — je gewähltem Spieler eine Seite.
// Getrennt vom Rahmen, damit der Mannschafts-Export (logic/mannschaft-export.js) die Seiten
// mehrerer Durchgänge hintereinander in EIN Dokument legen kann.
//   game:          { config, erfassung }
//   playerIndices: welche Spieler (Index in spielerListe); default alle
//   meta:          { titel, sub, istWettkampf, teamNameById }
export function buildProtokollSeiten(game, ranges, playerIndices, meta) {
  const c = game.config;
  const bloecke = (game.erfassung && game.erfassung.bloecke) || [];
  const { players } = computeGameStats(c, bloecke, ranges);
  const idx = (playerIndices && playerIndices.length) ? playerIndices : players.map((p) => p.index);

  return idx.map((i) => {
    const p = players[i];
    if (!p) return '';
    const sp = c.spielerListe[i] || {};
    const rich = {
      ...p,
      mannschaft: meta.teamNameById && sp.mannschaftId ? meta.teamNameById[sp.mannschaftId] : null,
      startBahn: sp.startBahn ?? (p.saetze[0] ? p.saetze[0].bahn : null),
    };
    const arr = (bloecke[i] || []).map((b) => ({ ...b }));
    return playerPage(rich, arr, ranges, meta);
  }).join('');
}

// Fertige Seiten in das Druck-Dokument fassen (Kopf, Druck-CSS). `titel` ist zugleich der
// Dokumenttitel — Chrome & Co. schlagen ihn beim „Als PDF speichern" als Dateinamen vor.
export function protokollDokument(titel, seiten) {
  return `<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">`
    + `<title>Wurfprotokoll — ${esc(titel)}</title><style>${STYLE}</style></head>`
    + `<body>${seiten}</body></html>`;
}

// Öffentliches API: aus einem Spiel das Protokoll-Dokument (ganzer HTML-String) bauen.
export function buildProtokollHTML(game, ranges, playerIndices, meta) {
  return protokollDokument(meta.titel, buildProtokollSeiten(game, ranges, playerIndices, meta));
}

// Das Dokument über einen unsichtbaren iframe drucken (Nutzer wählt „Als PDF speichern").
// document.write ist synchron und das Kegelbild ist Inline-SVG (kein externer Ladevorgang),
// deshalb ist der Inhalt direkt nach close() fertig — wir drucken nach einem kurzen Tick,
// statt uns auf das (bei dynamischem Schreiben unzuverlässige) iframe-onload zu verlassen.
export function printProtokollHTML(html) {
  const iframe = document.createElement('iframe');
  iframe.setAttribute('aria-hidden', 'true');
  iframe.style.cssText = 'position:fixed; right:0; bottom:0; width:0; height:0; border:0; visibility:hidden;';
  document.body.appendChild(iframe);
  const remove = () => { try { iframe.remove(); } catch (e) { /* schon weg */ } };
  const doc = iframe.contentWindow.document;
  doc.open(); doc.write(html); doc.close();
  setTimeout(() => {
    try {
      const cw = iframe.contentWindow;
      cw.focus();
      cw.onafterprint = () => setTimeout(remove, 100);
      cw.print();
      setTimeout(remove, 60000); // Sicherheitsnetz, falls onafterprint nicht feuert
    } catch (e) { remove(); }
  }, 150);
}
