// Wurfdaten als CSV — die Tabellen-Variante des Wurfprotokolls (logic/wurfprotokoll.js).
//
// Das PDF ist zum Ausdrucken und Abheften da; die CSV enthält die ROHDATEN: eine Zeile je
// Einzelwurf, sonst nichts. Bewusst KEINE Kennzahlen, Summen oder Statistik — die rechnet
// jede Tabellenkalkulation selbst aus (und die App zeigt sie ohnehin). Genau eine Tabelle mit
// Kopfzeile in Zeile 1, damit Excel/Calc sie direkt als Datenbereich sehen (Pivot, Filter).
//
// Die Spalten sind so gewählt, dass sich der Erfassungsstand daraus wieder AUFBAUEN lässt —
// diese Datei ist die vorgesehene Vorlage für den späteren CSV-Import:
//   Spieler; Satz; Bahn; Teilsatz; Modus; Wurf; Holz; Kegel
// Alles andere (Summen, 9er, Kränze, Fehlwürfe, volles Bild, Räumer) ist daraus ableitbar und
// steht deshalb nicht in der Datei. `Kegel` ist die Liste der gefallenen Kegel ("1 3 5"); ist
// sie leer, wurde nur die Holzzahl erfasst (kein Kegelbild) — das ist erlaubt.
//
// Sonderfall: ein Teilsatz, der nur als ERGEBNIS eingetragen wurde (ohne Einzelwürfe), steht
// als eine Zeile mit leerer Wurf-Nummer und dem Teilsatz-Holz in `Holz`. So geht auch dieser
// Stand nicht verloren, ohne dass die Tabelle eine Extra-Spalte braucht.
//
// Der Mannschafts-Export (logic/mannschaft-export.js) nutzt dieselben Zeilen, stellt ihnen aber
// die Spalten `Durchgang` und `Mannschaft` voran — mehrere Durchgänge in einer Datei wären sonst
// nicht auseinanderzuhalten. Ein späterer Import muss also führende Kontext-Spalten dulden und
// sich an den Spaltenköpfen orientieren, nicht an festen Positionen.
//
// Trennzeichen ist das Semikolon — so öffnet ein deutsches Excel die Datei per Doppelklick
// spaltenrichtig (eine Komma-CSV landet dort in EINER Spalte). Die BOM beim Download sorgt
// dafür, dass Excel UTF-8 erkennt (sonst stehen dort kaputte Umlaute).

import { teilsatzStats, satzStatus } from './holz.js';
import { isAbraeumMode, abraeumScan } from './abraeumen.js';

const SEP = ';';
const NL = '\r\n'; // CRLF: das erwarten Excel & Co. bei CSV
const MODUS_LBL = { volle: 'Volle', abraeumen: 'Abräumen', 'kranz-abraeumen': 'Kranz-Abräumen' };

// Spaltenköpfe — zugleich das Format, das ein späterer Import erwarten darf.
export const CSV_SPALTEN = ['Spieler', 'Satz', 'Bahn', 'Teilsatz', 'Modus', 'Wurf', 'Holz', 'Kegel'];

// Eine Zelle CSV-sicher machen: Texte mit Trennzeichen/Anführungszeichen/Zeilenumbruch in "…"
// (innere " verdoppelt). Zahlen sind hier durchweg ganzzahlig — kein Dezimaltrenner nötig.
function cell(v) {
  if (v == null || v === '') return '';
  const s = String(v);
  return /[";\r\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}
const row = (arr) => arr.map(cell).join(SEP);

// Gefallene Kegel eines Wurfs als "1 3 5". Unbekannt (nicht erfasst) -> leer.
const pinList = (pins) => (Array.isArray(pins) ? pins.slice().sort((a, b) => a - b).join(' ') : '');

// Bahn eines Spielers im Satz — wie in logic/statistik.js.
const bahnOf = (c, sp, st) => (c.bahnplan?.[sp]?.[st] ?? (c.ersteBahn + st));

// Zeilen EINES Satz-Blocks: je Teilsatz entweder die Einzelwürfe oder — wenn der Teilsatz nur
// als Ergebnis eingetragen wurde — eine Zeile ohne Wurf-Nummer mit dem Teilsatz-Holz.
// Für ALTDATEN (Kranz-Langdruck ohne gespeicherte Kegel) wird das Kegelbild wie im PDF aus dem
// Reststand rekonstruiert, sofern der exakt bekannt ist.
function blockZeilen(blk, ranges, kopf) {
  const out = [];
  const bw = Array.isArray(blk.wuerfe) ? blk.wuerfe : [];
  const done = satzStatus(blk) === 'done';
  ranges.forEach((r, ti) => {
    const label = MODUS_LBL[r.modus] || r.modus;
    const t = teilsatzStats(blk, ranges, ti, done);
    if (t.manual) {
      out.push(kopf.concat([ti + 1, label, '', t.val, '']));
      return;
    }
    const scan = isAbraeumMode(r.modus) ? abraeumScan(blk, r) : null;
    const end = Math.min(r.end, bw.length);
    for (let k = r.start; k < end; k += 1) {
      const val = bw[k];
      const koenig = Array.isArray(blk.koenig) ? !!blk.koenig[k] : false;
      let kegel = Array.isArray(blk.kegel) ? blk.kegel[k] : null;
      if (kegel == null && koenig && scan) {
        const st = scan.before[k];
        if (st && st.exact) {
          const fallen = st.standing.filter((p) => p !== 5);
          if (fallen.length === val) kegel = fallen;
        }
      }
      out.push(kopf.concat([ti + 1, label, k + 1, val, pinList(kegel)]));
    }
  });
  return out;
}

// Die Wurf-Zeilen EINES Spiels (ohne Kopfzeile) als Zellen-Arrays — Grundlage von buildWurfCSV
// und des Mannschafts-Exports (logic/mannschaft-export.js), der die Zeilen mehrerer Durchgänge
// mit zusätzlichen Kontext-Spalten in EINE Tabelle legt.
//   game:          { config, erfassung }
//   ranges:        teilsatzRanges(config)
//   playerIndices: welche Spieler (Index in spielerListe); leer/fehlend -> alle
export function wurfZeilen(game, ranges, playerIndices) {
  const c = game.config;
  const bloecke = (game.erfassung && game.erfassung.bloecke) || [];
  const alle = (c.spielerListe || []).map((_, i) => i);
  const idx = (playerIndices && playerIndices.length) ? playerIndices : alle;

  const out = [];
  idx.forEach((sp) => {
    const spieler = c.spielerListe[sp];
    if (!spieler) return;
    const name = spieler.name || ('Spieler ' + (sp + 1));
    (bloecke[sp] || []).forEach((blk, st) => {
      blockZeilen(blk, ranges, [name, st + 1, bahnOf(c, sp, st)]).forEach((z) => out.push(z));
    });
  });
  return out;
}

// Kopfzeile + Zeilen zu einem CSV-Text zusammensetzen (Semikolon, CRLF).
export function csvText(spalten, zeilen) {
  return [row(spalten)].concat(zeilen.map(row)).join(NL) + NL;
}

// Öffentliches API: aus einem Spiel die Wurf-Tabelle als CSV-Text bauen.
export function buildWurfCSV(game, ranges, playerIndices) {
  return csvText(CSV_SPALTEN, wurfZeilen(game, ranges, playerIndices));
}

// Ein Stück Text für einen Dateinamen tauglich machen: ohne die Zeichen, die Windows/macOS
// dort verbieten, Leerzeichen als Bindestrich, auf eine handliche Länge gekürzt.
export function dateiSicher(s) {
  return String(s || '').replace(/[\/:*?"<>|]/g, '').replace(/\s+/g, '-').slice(0, 40);
}

// Datum als YYYY-MM-DD für den Dateinamen; ohne (gültige) Angabe der heutige Tag.
export function datumTeil(iso) {
  const d = iso ? new Date(iso) : new Date();
  const g = Number.isNaN(d.getTime()) ? new Date() : d;
  return `${g.getFullYear()}-${String(g.getMonth() + 1).padStart(2, '0')}-${String(g.getDate()).padStart(2, '0')}`;
}

// Dateiname aus Spielname + Datum (+ Spielername, wenn genau einer exportiert wird).
export function csvDateiname(meta = {}, namen = []) {
  const teile = ['Wurfdaten', dateiSicher(meta.titel) || 'Spiel', datumTeil()];
  if (namen.length === 1 && dateiSicher(namen[0])) teile.push(dateiSicher(namen[0]));
  return teile.join('_') + '.csv';
}

// Den CSV-Text als Datei herunterladen (nur im Browser). BOM voran, damit Excel UTF-8 erkennt.
export function downloadCSV(dateiname, text) {
  const blob = new Blob(['\uFEFF' + text], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = dateiname;
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  // Erst nach dem Klick aufräumen — Safari braucht den Link noch einen Tick lang.
  setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1000);
}
