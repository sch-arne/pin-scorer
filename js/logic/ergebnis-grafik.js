// Ergebnis-Grafik: das MODELL hinter dem Bild-Export (logic/grafik-zeichnen.js zeichnet es,
// views/grafik-panel.js bedient es). Reine Logik — Browser + Node ladbar, per Unit-Test
// abgesichert, kein DOM-Zugriff.
//
// Aus den Rohdaten (Wettkampf + Durchgang-Spiele ODER einem einzelnen Spiel) wird ein flaches
// Modell gebaut, das nur noch Text und Zahlen enthält:
//   • modus 'duell' — zwei Mannschaften, Gegenüberstellung (Name · Holz · EWP je Seite),
//     Summenzeile, Logos und Spielpunkte. Das ist der Regelfall im Punktspiel.
//   • modus 'liste' — eine Rangliste (Rang · Name · Holz), für Trainingsspiele ohne
//     Mannschaften und für Wettkämpfe mit einer oder mehr als zwei Mannschaften.
//
// Bewusst ROHE Eingangsdaten (`{ wettkampf, games }` / `{ game }`) statt eines fertigen
// Stats-Objekts: so ist die Funktion allein testbar und die Views müssen die Rechenkette
// (computeWettkampfStats -> computeWertung -> assignEwp) nicht kennen.

import { computeWettkampfStats, wettkampfBaseStatus, gameBaseStatus } from './wettkampf.js';
import { computeWertung, assignEwp, fmtPunkte } from './wettkampf-wertung.js';
import { computeGameStats } from './statistik.js';
import { teilsatzRanges } from './teilsaetze.js';
import { dateiSicher, datumTeil } from './wurf-csv.js';

// Kegel-Gold als Rückfall für die Team-Akzentfarbe (wie im Overlay, views/overlay.js).
export const GRAFIK_ACCENT_DEFAULT = '#f5a623';

// Erlaubte Werte der Optionen. Die Pixel-Maße der Formate stehen in grafik-zeichnen.js —
// hier geht es nur um die Gültigkeit der gespeicherten Auswahl (gleiche Schlüssel!).
export const GRAFIK_FORMATE = ['hoch', 'story'];
// Schlüssel von SCHRIFTEN in grafik-zeichnen.js — dort stehen die Schriftstapel.
export const GRAFIK_SCHRIFTEN = ['system', 'schmal', 'serif'];
const TEXTFARBEN = ['hell', 'dunkel'];
const FLAECHEN = ['aus', 'dezent', 'kraeftig'];
const POSITIONEN = ['oben', 'mitte', 'unten'];

// Standard-Einstellungen der Grafik. Werden in den App-Einstellungen unter `grafik`
// gespeichert — siehe grafikOptionen() zur Merge-Falle.
export const GRAFIK_DEFAULT = {
  format: 'hoch',        // 'hoch' (1080x1440) | 'story' (1080x1920)
  schrift: 'system',     // Schriftart: 'system'|'schmal'|'serif'
  textfarbe: 'hell',     // helle Schrift für dunkle Hintergründe, sonst 'dunkel'
  kontur: true,          // Umrandung (Halo) um jede Schrift
  flaechen: 'dezent',    // halbtransparente Platten hinter den Zeilen: 'aus'|'dezent'|'kraeftig'
  logos: true,           // Mannschaftslogos zeigen
  spielpunkte: true,     // Spielstand (z. B. "3 : 0") zwischen den Logos
  ewp: true,             // EWP-Spalte (nur bei beendetem Wettkampf mit Wertung möglich)
  spaltenkoepfe: true,   // Kopfzeile über den Spalten
  position: 'mitte',     // vertikale Lage im nutzbaren Bereich
};

// Gespeicherte Einstellungen -> vollständige Grafik-Optionen.
//
// WICHTIG: getSettings()/saveSettings() in store.js mischen FLACH. `settings.grafik` wird
// beim Speichern also komplett ersetzt, und ein später ergänzter Default erreicht
// Bestandsnutzer nicht. Deshalb hier ein eigener Merge über GRAFIK_DEFAULT — er ist die
// einzige Stelle, die aus gespeicherten Werten Optionen macht.
export function grafikOptionen(settings) {
  const roh = settings && settings.grafik;
  return { ...GRAFIK_DEFAULT, ...(roh && typeof roh === 'object' ? roh : {}) };
}

// Optionen gegen das Modell gültig machen: unbekannte Werte auf den Standard zurück und
// alles abschalten, wofür die Daten fehlen (EWP vor Spielende, Logos ohne Logo,
// Spielpunkte ohne hinterlegte Wertung). Das Panel sperrt dieselben Schalter sichtbar.
export function normalisiereOptionen(opts, modell) {
  const o = { ...GRAFIK_DEFAULT, ...(opts && typeof opts === 'object' ? opts : {}) };
  if (!GRAFIK_FORMATE.includes(o.format)) o.format = GRAFIK_DEFAULT.format;
  if (!GRAFIK_SCHRIFTEN.includes(o.schrift)) o.schrift = GRAFIK_DEFAULT.schrift;
  if (!TEXTFARBEN.includes(o.textfarbe)) o.textfarbe = GRAFIK_DEFAULT.textfarbe;
  if (!FLAECHEN.includes(o.flaechen)) o.flaechen = GRAFIK_DEFAULT.flaechen;
  if (!POSITIONEN.includes(o.position)) o.position = GRAFIK_DEFAULT.position;
  o.kontur = !!o.kontur;
  o.logos = !!o.logos;
  o.spielpunkte = !!o.spielpunkte;
  o.ewp = !!o.ewp;
  o.spaltenkoepfe = !!o.spaltenkoepfe;
  const m = modell || {};
  if (!m.mitEwp) o.ewp = false;
  if (!m.hatLogos) o.logos = false;
  if (!m.mitSpielpunkte) o.spielpunkte = false;
  return o;
}

// Akzentfarbe einer Mannschaft, streng validiert (#rrggbb) — sie landet direkt als
// Canvas-Farbe.
function accentOf(team) {
  const c = team && team.accent;
  return /^#[0-9a-fA-F]{6}$/.test(c || '') ? c : GRAFIK_ACCENT_DEFAULT;
}

// Spieler einer Mannschaft in Aufstellungsreihenfolge (teamPos), wie playersOfTeam() im
// Overlay (views/overlay.js) — dort nicht exportiert, deshalb hier wiederholt.
function spielerDerMannschaft(einzel, teamId) {
  return (einzel || [])
    .filter((p) => p.mannschaftId === teamId)
    .sort((a, b) => (a.teamPos || 99) - (b.teamPos || 99) || (a.durchgangNr || 0) - (b.durchgangNr || 0));
}

// Hat der Spieler überhaupt gespielt? Sonst steht in der Grafik ein „–" statt einer 0 —
// ein laufender Wettkampf soll nicht aussehen, als hätten vier Leute null Holz geworfen.
function hatGespielt(p) {
  return (p.wurfCount || 0) > 0 || (p.gesamt || 0) > 0;
}

function zeileAusSpieler(p) {
  return {
    name: p.name || '',
    gesamt: p.gesamt || 0,
    ewp: p.ewp != null ? p.ewp : 0,
    gespielt: hatGespielt(p),
  };
}

// Platzierung nach Gesamtholz (Standard-„1224"-Zählung wie computeGameStats).
function rangliste(spieler) {
  const sorted = spieler.slice().sort((a, b) => (b.gesamt || 0) - (a.gesamt || 0));
  let rang = 0;
  let prev = null;
  return sorted.map((p, i) => {
    if (prev === null || (p.gesamt || 0) < prev) rang = i + 1;
    prev = p.gesamt || 0;
    return { rang, name: p.name || '', gesamt: p.gesamt || 0, gespielt: hatGespielt(p) };
  });
}

function datumText(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString('de-DE');
}

// Die Rechenkette eines Wettkampfs — identisch zu wettkampfTeamSection() in
// views/spiel-laufend.js und buildOverlayHtml() in views/overlay.js: erst die
// Einzel-Auswertung, dann die Wertung, dann die EWP auf die volle Feldgröße skalieren
// (bester Spieler = Spieler je Mannschaft × Anzahl Mannschaften).
function wettkampfAuswertung(wettkampf, games) {
  const stats = computeWettkampfStats(wettkampf, games);
  const wertung = computeWertung(wettkampf, stats, games);
  const teams = wettkampf.mannschaften || [];
  const feldGroesse = (wettkampf.spielerJeMannschaft || 0) * teams.length;
  assignEwp(stats.einzel, teams[0] && teams[0].id, wettkampf.wertung?.ewp?.minHolz ?? 1, feldGroesse);
  return { stats, wertung };
}

function wettkampfKopf(wettkampf) {
  return {
    titel: wettkampf.name || 'Ergebnis',
    untertitel: [datumText(wettkampf.datum), wettkampf.anlageName || ''].filter(Boolean).join(' · '),
    datumIso: wettkampf.datum || null,
  };
}

// Gegenüberstellung zweier Mannschaften (Heim = mannschaften[0], Gast = [1]).
function duellModell(wettkampf, games) {
  const { stats, wertung } = wettkampfAuswertung(wettkampf, games);
  const fertig = wettkampfBaseStatus(wettkampf, games) === 'beendet';
  // EWP NUR mit hinterlegter Wertung: ein beendeter Bohle-/Classic-Wettkampf ohne Wertung
  // liefert computeWertung -> null; die von assignEwp gesetzten Zahlen gehen dort in keine
  // Wertung ein und dürfen deshalb auch nicht als EWP-Spalte erscheinen.
  const mitEwp = fertig && !!wertung;
  const teams = (wettkampf.mannschaften || []).slice(0, 2).map((m) => {
    const spieler = spielerDerMannschaft(stats.einzel, m.id);
    const w = wertung && wertung.teams[m.id];
    return {
      id: m.id,
      name: m.name || '',
      accent: accentOf(m),
      logo: m.logo || null,
      logoBg: m.logoBg === 'light' ? 'light' : 'dark',
      zeilen: spieler.map(zeileAusSpieler),
      summeHolz: spieler.reduce((s, p) => s + (p.gesamt || 0), 0),
      summeEwp: spieler.reduce((s, p) => s + (p.ewp || 0), 0),
      spielpunkte: w ? fmtPunkte(w.spielpunkte) : null,
    };
  });
  return {
    modus: 'duell',
    ...wettkampfKopf(wettkampf),
    fertig,
    mitEwp,
    mitSpielpunkte: !!wertung,
    hatLogos: teams.some((t) => !!t.logo),
    teams,
    zeilen: [],
  };
}

// Rangliste über alle Spieler eines Wettkampfs (eine oder mehr als zwei Mannschaften).
function wettkampfListeModell(wettkampf, games) {
  const { stats } = wettkampfAuswertung(wettkampf, games);
  return {
    modus: 'liste',
    ...wettkampfKopf(wettkampf),
    fertig: wettkampfBaseStatus(wettkampf, games) === 'beendet',
    mitEwp: false,
    mitSpielpunkte: false,
    hatLogos: false,
    teams: [],
    zeilen: rangliste(stats.einzel),
  };
}

// Einzelspiel ohne Wettkampf (Training): schlichte Rangliste.
function spielModell(game) {
  const c = (game && game.config) || {};
  const bloecke = (game && game.erfassung && game.erfassung.bloecke) || [];
  const players = Array.isArray(c.spielerListe)
    ? computeGameStats(c, bloecke, teilsatzRanges(c)).players
    : [];
  return {
    modus: 'liste',
    titel: 'Ergebnis',
    untertitel: [datumText(game && game.createdAt), c.anlageName || ''].filter(Boolean).join(' · '),
    datumIso: (game && game.createdAt) || null,
    fertig: gameBaseStatus(game) === 'beendet',
    mitEwp: false,
    mitSpielpunkte: false,
    hatLogos: false,
    teams: [],
    zeilen: rangliste(players),
  };
}

function leeresModell() {
  return {
    modus: 'liste', titel: 'Ergebnis', untertitel: '', datumIso: null,
    fertig: false, mitEwp: false, mitSpielpunkte: false, hatLogos: false,
    teams: [], zeilen: [],
  };
}

// Rohdaten -> Grafik-Modell.
//   { wettkampf, games } — Wettkampf (zwei Mannschaften = Duell, sonst Rangliste)
//   { game }             — einzelnes Spiel (Rangliste)
export function grafikModell(quelle) {
  const q = quelle || {};
  if (q.wettkampf) {
    const teams = q.wettkampf.mannschaften || [];
    return teams.length === 2
      ? duellModell(q.wettkampf, q.games || [])
      : wettkampfListeModell(q.wettkampf, q.games || []);
  }
  if (q.game) return spielModell(q.game);
  return leeresModell();
}

// Dateiname der PNG: Ergebnis_<Titel>_<Datum>.png (Helfer wie beim CSV-Export).
export function grafikDateiname(modell) {
  const m = modell || {};
  return ['Ergebnis', dateiSicher(m.titel) || 'Spiel', datumTeil(m.datumIso)].join('_') + '.png';
}
