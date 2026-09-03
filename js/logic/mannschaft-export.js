// Mannschafts-Export: alle Wurfprotokolle (PDF) und alle Wurfdaten (CSV) EINER Mannschaft
// eines Wettkampfs — über sämtliche Durchgänge hinweg, in EINER Ausgabe.
//
// Bisher lief der Export nur je Spiel (Statistik-Screen der Erfassung): ein Durchgang, die dort
// gewählten Spieler. Nach dem Wettkampf will man aber „alles von meiner Mannschaft" — Blatt für
// Blatt für jeden Spieler und jeden Durchgang, plus die Rohdaten in einer Tabelle.
//
// Zwei Ausgaben, gleiche Auswahl:
//   PDF — ein A4-Blatt je Spieler UND Durchgang (Reihenfolge: Durchgang, dann Startnummer).
//         Ein Dokument, weil der Browser-Druck genau eine Datei erzeugt; die Blätter sind
//         durch `page-break-after` sauber getrennt (siehe logic/wurfprotokoll.js).
//   CSV — dieselbe Wurf-Tabelle wie beim Einzelspiel, davor die Spalten `Durchgang` und
//         `Mannschaft`. Damit bleibt jede Zeile eindeutig zuzuordnen, wenn mehrere Durchgänge
//         (und damit derselbe Spielername mehrfach) in einer Datei stehen.
//
// Spieler ohne einen einzigen erfassten Wurf in einem Durchgang bleiben draußen — ein leeres
// Blatt und leere Zeilen helfen niemandem. Ist für eine Mannschaft gar nichts erfasst, geben
// die Builder '' zurück; der Aufrufer zeigt dann einen Hinweis statt einer leeren Datei.

import { teilsatzRanges } from './teilsaetze.js';
import { buildProtokollSeiten, protokollDokument } from './wurfprotokoll.js';
import { wurfZeilen, csvText, CSV_SPALTEN, dateiSicher, datumTeil } from './wurf-csv.js';

// Spalten der Mannschafts-CSV: die Wurf-Tabelle des Einzelspiels mit zwei Kontext-Spalten davor.
export const MANNSCHAFT_CSV_SPALTEN = ['Durchgang', 'Mannschaft', ...CSV_SPALTEN];

// Hat der Spieler in diesem Durchgang überhaupt etwas erfasst — Einzelwürfe ODER ein nur
// eingetragenes Teilsatz-Ergebnis? (Ein Satz kann als `done` markiert und trotzdem leer sein.)
function hatDaten(bloecke) {
  return (bloecke || []).some((blk) => blk
    && ((Array.isArray(blk.wuerfe) && blk.wuerfe.length > 0)
      || (Array.isArray(blk.overrides) && blk.overrides.some((o) => o != null))));
}

const teamNamen = (wettkampf) => {
  const map = {};
  ((wettkampf && wettkampf.mannschaften) || []).forEach((m) => { map[m.id] = m.name; });
  return map;
};

const datumText = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
};

// Kopf-Angaben eines Protokoll-Blatts — wie in der Erfassung (views/spiel-laufend.js:
// protokollMeta), nur hier aus Wettkampf + Durchgang statt aus dem laufenden Spiel gebaut.
function metaOf(wettkampf, game, namen) {
  const c = game.config || {};
  const parts = [];
  if (game.durchgangNr) parts.push('Durchgang ' + game.durchgangNr);
  const dat = datumText(wettkampf.datum || game.createdAt);
  if (dat) parts.push(dat);
  if (c.anlageName) parts.push(c.anlageName);
  if (c.preset) parts.push(c.preset);
  return {
    titel: wettkampf.name || 'Wettkampf',
    sub: parts.join(' · '),
    istWettkampf: true,
    teamNameById: namen,
  };
}

// Die Durchgänge einer Mannschaft, aufsteigend nach Durchgangsnummer: je Durchgang die
// Spieler-Indizes (Reihenfolge = Startnummer im Team), die dort Daten haben. Durchgänge ohne
// erfasste Spieler dieser Mannschaft fallen weg.
export function mannschaftDurchgaenge(wettkampf, games, mannschaftId) {
  return (games || [])
    .slice()
    .sort((a, b) => (a.durchgangNr || 0) - (b.durchgangNr || 0))
    .map((game) => {
      const liste = (game.config && game.config.spielerListe) || [];
      const bloecke = (game.erfassung && game.erfassung.bloecke) || [];
      const indices = liste
        .map((sp, i) => ({ sp, i }))
        .filter(({ sp, i }) => sp && sp.mannschaftId === mannschaftId && hatDaten(bloecke[i]))
        .sort((a, b) => (a.sp.teamPos || 0) - (b.sp.teamPos || 0))
        .map(({ i }) => i);
      return { game, nr: game.durchgangNr || 0, indices };
    })
    .filter((d) => d.indices.length > 0);
}

// Was steckt im Export? Für die Beschriftung der Knöpfe: wie viele Durchgänge, wie viele Blätter
// (Spieler × Durchgang) und wie viele verschiedene Spieler.
export function mannschaftExportInfo(wettkampf, games, mannschaftId) {
  const dg = mannschaftDurchgaenge(wettkampf, games, mannschaftId);
  const namen = new Set();
  dg.forEach((d) => d.indices.forEach((i) => {
    const sp = (d.game.config.spielerListe || [])[i];
    namen.add((sp && sp.name) || `${mannschaftId}|${(sp && sp.teamPos) || i}`);
  }));
  return {
    durchgaenge: dg.length,
    blaetter: dg.reduce((s, d) => s + d.indices.length, 0),
    spieler: namen.size,
  };
}

// Alle Wurfprotokolle der Mannschaft als EIN Druck-Dokument (HTML-String); '' wenn nichts da ist.
export function buildMannschaftProtokollHTML(wettkampf, games, mannschaftId) {
  const namen = teamNamen(wettkampf);
  const seiten = mannschaftDurchgaenge(wettkampf, games, mannschaftId)
    .map((d) => buildProtokollSeiten(
      d.game, teilsatzRanges(d.game.config), d.indices, metaOf(wettkampf, d.game, namen)))
    .join('');
  if (!seiten) return '';
  const team = namen[mannschaftId] || 'Mannschaft';
  return protokollDokument(`${wettkampf.name || 'Wettkampf'} · ${team}`, seiten);
}

// Alle Wurfdaten der Mannschaft als EINE CSV-Tabelle; '' wenn nichts da ist.
export function buildMannschaftCSV(wettkampf, games, mannschaftId) {
  const team = teamNamen(wettkampf)[mannschaftId] || 'Mannschaft';
  const zeilen = [];
  mannschaftDurchgaenge(wettkampf, games, mannschaftId).forEach((d) => {
    wurfZeilen(d.game, teilsatzRanges(d.game.config), d.indices)
      .forEach((z) => zeilen.push([d.nr || '', team, ...z]));
  });
  return zeilen.length ? csvText(MANNSCHAFT_CSV_SPALTEN, zeilen) : '';
}

// Dateiname der Mannschafts-CSV: Wettkampf, Wettkampf-Datum (nicht der heutige Tag — der Export
// passiert oft erst Tage später) und die Mannschaft.
export function mannschaftCsvDateiname(wettkampf, mannschaftId) {
  const team = teamNamen(wettkampf)[mannschaftId] || 'Mannschaft';
  const teile = [
    'Wurfdaten',
    dateiSicher(wettkampf && wettkampf.name) || 'Wettkampf',
    datumTeil(wettkampf && wettkampf.datum),
    dateiSicher(team) || 'Mannschaft',
  ];
  return teile.join('_') + '.csv';
}
