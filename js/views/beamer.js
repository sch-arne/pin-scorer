// Beamer-Ansicht: die ausführliche Ergebnistafel für die Leinwand im Saal (1920×1080).
//
// Abgrenzung zum OBS-Overlay (views/overlay.js): das Overlay liegt ÜBER einem Kamerabild,
// muss also schmal bleiben und die Mitte freilassen. Hier ist die ganze Fläche unsere —
// deshalb zeigt die Beamer-Ansicht das, wofür im Stream kein Platz ist: je Gasse (bzw. je
// Satz) und Spieler das Ergebnis, dazu innen das Gesamtergebnis in Volle, Abräumen und Summe
// samt EWP. Also der Spielbericht, wie er im Saal aushängt.
//
// EINE ZAHL JE GASSE, aufgeteilt nur beim Gesamtergebnis: die Aufteilung je Gasse hat die
// Tafel zugestellt (drei enge Spalten mal vier Bahnen), und gefragt wird im Saal nach dem
// Bahnergebnis. Die gewonnene Breite geht an größere Zahlen, ganze Namen und Luft zwischen
// den Blöcken — Name | Gassen | Gesamt | EWP stehen sichtbar getrennt.
//
// ANORDNUNG wie im Livestream: die Tabellen sind gespiegelt — der Name steht AUSSEN, die
// Zahlen stehen INNEN. So liegen die Ergebnisse beider Mannschaften nebeneinander in der
// Bildmitte und lassen sich vergleichen, ohne den Blick über die ganze Leinwand zu ziehen.
// Nur die Gassen-/Satz-Nummern laufen auf beiden Seiten aufsteigend (wie im Overlay).
//
// Zwei Wege auf die Leinwand, beide über den 🖼-Knopf → Reiter „Beamer":
//   • „Vollbild" — dieses Gerät zeigt die Tafel selbst (Fullscreen API), ganz ohne Teilen.
//     Der Normalfall, wenn der Beamer am Laptop hängt, auf dem auch erfasst wird.
//   • URL `#/beamer?code=…` — ein ZWEITES Gerät (anderer Laptop am Beamer) holt die Daten
//     read-only per Zuschauer-Code, wie das Overlay. Setzt einen geteilten Wettkampf voraus.
//
// SPALTENWAHL UND HELL/DUNKEL stehen AM WETTKAMPF (`wettkampf.beamer`), nicht am Gerät und
// nicht in der URL: eingestellt werden sie wie die Logos und Akzentfarben im 🖼-Panel
// (views/livestream-einstellungen.js), von dort reisen sie im config_json mit und stehen beim
// nächsten Abruf (3 s) auf der Leinwand. So bleibt die Beamer-URL kurz genug zum Abtippen,
// und das Gerät am Beamer braucht keine eigene Oberfläche — es zeigt nur an.
//
// `buildBeamerHtml()` ist bewusst eine reine Funktion über { wettkampf, games } — dieselben
// Daten, die fetchOverlay() liefert und die das Grafik-Panel lokal hat. So malt die Vorschau
// im Panel exakt das, was auf der Leinwand steht, und der Node-Test kommt ohne DOM aus.

import { currentQuery, UNMOUNT_EVENT } from '../router.js';
import { computeWettkampfStats, durchgangStatusList } from '../logic/wettkampf.js';
import { computeWertung, assignEwp, fmtPunkte } from '../logic/wettkampf-wertung.js';
import { esc } from '../util.js';

const POLL_MS = 3000;
const STAGE_W = 1920;
const STAGE_H = 1080;

// Spaltenwahl der Tabellen: je bespielter Bahn („Gasse") oder je Satz. Bahnen ist der
// Standard — auf der Leinwand wird nach Gassen verglichen („was steht auf der 4?").
export const SPALTEN_MODI = ['bahnen', 'saetze'];

// Dunkel oder hell. Dunkel ist der Standard (wie die App); hell ist für helle Säle gedacht,
// in denen ein dunkles Bild vom Beamer grau und flau an der Wand ankommt.
export const THEMEN = ['dunkel', 'hell'];

// Länge der Überschrift über der Tafel. Mehr passt in einer Zeile ohnehin nicht auf 1920px,
// und umbrechen soll sie nicht — sie steht über allem und gibt der Tafel ihre Höhe.
export const TITEL_MAX = 60;

// Anzeige-Einstellungen der Tafel aus dem WETTKAMPF holen (und auf gültige Werte bringen).
// Sie hängen am Wettkampf, damit sie jedes Gerät sehen, das ihn anzeigt — das zweite Gerät am
// Beamer bekommt eine Änderung also mit dem nächsten Abruf, ohne dass dort jemand steht.
export function beamerOptionen(wettkampf) {
  const b = (wettkampf && wettkampf.beamer) || {};
  return {
    spalten: SPALTEN_MODI.includes(b.spalten) ? b.spalten : 'bahnen',
    thema: THEMEN.includes(b.thema) ? b.thema : 'dunkel',
    // Freie Überschrift. Leer heißt: gar keine Überschrift (die Zeile fällt dann ganz weg).
    titel: typeof b.titel === 'string' ? b.titel.slice(0, TITEL_MAX).trim() : '',
  };
}

// Beamer-URL für ein zweites Gerät — wie die Overlay-URL mit dem read-only Zuschauer-Code
// (die Tafel macht keine Eingaben, eine geleakte URL gibt also kein Eingaberecht).
// Bewusst OHNE Spaltenwahl und Thema: die stehen am Wettkampf und reisen mit den Daten mit
// (siehe oben). So bleibt die URL kurz genug, um sie abzutippen, und eine einmal am Beamer
// geöffnete Seite muss nie wieder angefasst werden.
export function beamerUrl(wettkampf) {
  const base = location.origin + location.pathname;
  const code = encodeURIComponent((wettkampf && wettkampf.zuschauerCode) || '');
  return `${base}#/beamer?code=${code}`;
}

// ── Route #/beamer?code=XXXX ────────────────────────────────────────────────
export function beamerView() {
  const root = document.createElement('div');
  root.className = 'bm-root';
  root.innerHTML = `<div class="bm-stage"><div class="bm-wait">Warte auf Wettkampf-Daten …</div></div>`;
  const stage = root.querySelector('.bm-stage');

  const code = (currentQuery().get('code') || '').trim();
  let timer = null;
  let alive = true;
  let sync = null;
  let letztes = '';

  function fit() {
    const s = Math.min(window.innerWidth / STAGE_W, window.innerHeight / STAGE_H);
    stage.style.transform = `translate(-50%, -50%) scale(${s})`;
  }

  async function tick() {
    if (!alive) return;
    try {
      if (!sync) sync = await import('../backend/sync.js');
      const data = code ? await sync.fetchOverlay(code) : null;
      if (data) male(data);
      else if (!letztes) stage.innerHTML = `<div class="bm-wait">${code ? 'Wettkampf nicht gefunden — Code prüfen.' : 'Kein Code in der URL (#/beamer?code=…).'}</div>`;
    } catch (e) {
      if (!letztes) stage.innerHTML = `<div class="bm-wait">Keine Verbindung — erneuter Versuch …</div>`;
    }
    if (alive) timer = setTimeout(tick, POLL_MS);
  }

  function male(data) {
    // Hell/Dunkel steht in den Daten → auch der Rand um die Bühne zieht bei jedem Abruf mit.
    root.classList.toggle('is-hell', beamerOptionen(data && data.wettkampf).thema === 'hell');
    const html = buildBeamerHtml(data);
    if (html === letztes) return; // nichts geändert → DOM nicht anfassen (kein Flackern)
    letztes = html;
    stage.innerHTML = html;
    fit();
  }

  function teardown() {
    alive = false;
    clearTimeout(timer);
    window.removeEventListener('resize', fit);
    window.removeEventListener(UNMOUNT_EVENT, teardown);
  }

  window.addEventListener('resize', fit);
  window.addEventListener(UNMOUNT_EVENT, teardown);
  fit();
  tick();
  return root;
}

// ── Aufbereitung ────────────────────────────────────────────────────────────
// Spieler einer Mannschaft in Aufstellungsreihenfolge (wie im Overlay).
function playersOfTeam(stats, teamId) {
  return stats.einzel
    .filter((p) => p.mannschaftId === teamId)
    .sort((a, b) => (a.teamPos || 99) - (b.teamPos || 99) || (a.durchgangNr || 0) - (b.durchgangNr || 0));
}

// Zahl anzeigen — 0 bleibt leer, solange nichts gespielt wurde (leere Zeile statt Nullenwand).
function num(v, gespielt) {
  if (!gespielt) return '';
  return v == null ? '' : String(v);
}

function summe(list, f) {
  return list.reduce((s, x) => s + (f(x) || 0), 0);
}

// Hat der Spieler schon geworfen? Zählt auch importierte Sätze ohne Wurfdetails (Holz > 0).
function hatGespielt(p) {
  return (p.wurfCount || 0) > 0 || (p.gesamt || 0) > 0;
}

// Alle bespielten Gassen des Wettkampfs. Bevorzugt die im Wettkampf hinterlegte Liste
// (playedLanes) — sie enthält auch Bahnen, auf denen noch niemand geworfen hat, und genau
// die sollen als leere Spalte schon dastehen. Sonst aus den Sätzen abgeleitet.
function bespielteBahnen(wettkampf, alle) {
  const aus = ((wettkampf && wettkampf.playedLanes) || []).slice();
  if (aus.length) return aus.sort((a, b) => a - b);
  const set = new Set();
  alle.forEach((p) => (p.saetze || []).forEach((s) => { if (s.bahn != null) set.add(s.bahn); }));
  return [...set].sort((a, b) => a - b);
}

// Die Wert-Spalten der Tabellen: je Gasse (Standard) oder je Satz.
function spaltenDef(wettkampf, alle, modus) {
  if (modus === 'saetze') {
    const n = alle.reduce((m, p) => Math.max(m, (p.saetze || []).length), 0);
    return Array.from({ length: n }, (_, i) => ({ label: String(i + 1), satz: i }));
  }
  return bespielteBahnen(wettkampf, alle).map((n) => ({ label: String(n), bahn: n }));
}

// Den Satz eines Spielers zu einer Spalte finden (Satz-Nummer bzw. Gasse).
function satzZuSpalte(p, sp) {
  const saetze = p.saetze || [];
  return sp.satz != null ? saetze[sp.satz] : saetze.find((x) => x.bahn === sp.bahn && x.holz);
}

// Holz eines Spielers in einer Spalte (für Summen und Tests).
function spaltenHolz(p, sp) {
  const s = satzZuSpalte(p, sp);
  return (s && s.holz) || 0;
}

// ── Tabelle einer Mannschaft ────────────────────────────────────────────────
// Der Kopf läuft über ZWEI Zeilen, sobald abgeräumt wird: oben die Gasse (bzw. der Satz),
// darunter ihre Werte V (Volle) · A (Abräumen) · Ges. Rechts außen dieselbe Aufteilung als
// Gesamtergebnis. Die Spaltenbreiten stehen im <colgroup> — bei `table-layout: fixed` ist das
// die verlässliche Stelle dafür, gerade weil der Kopf mit colspan/rowspan arbeitet.
//
// Ein „Teil" ist eine solche Spaltengruppe: er bringt seine <col>s, seine Kopfzellen und je
// eine Funktion für die Spieler- und die Summenzeile mit. So lässt sich die Tabelle für die
// rechte Seite einfach spiegeln (siehe ordne()), ohne die Zellen zweimal zu bauen.
//   geteilt     — drei Spalten (V/A/Ges) statt einer
//   zweiZeilig  — die Tabelle hat eine zweite Kopfzeile (dann rowspan für einspaltige Teile)
//   extra       — zusätzliche Klasse auf den Wertzellen (die Gesamt-Gruppe hebt sich ab)
//   spiegeln    — die Spalten der Gruppe rückwärts ausgeben (rechte Tabelle, siehe ordne())
function wertTeil(label, holen, klassen, { geteilt, zweiZeilig, extra = '', spiegeln = false }) {
  const [cv, ca, cg] = klassen;
  const zus = extra ? ` ${extra}` : '';
  const dreh = (zellen) => (spiegeln ? zellen.slice().reverse() : zellen);
  if (!geteilt) {
    return {
      cols: [`<col class="${cg}">`],
      k1: [`<th class="bm-wert-h${zus}"${zweiZeilig ? ' rowspan="2"' : ''}>${esc(label)}</th>`],
      k2: [],
      td: (p) => [`<td class="bm-wert${zus}">${holen(p).holz || ''}</td>`],
      tf: (w) => [`<td class="bm-wert bm-sum${zus}">${w.holz || ''}</td>`],
    };
  }
  return {
    cols: dreh([`<col class="${cv}">`, `<col class="${ca}">`, `<col class="${cg}">`]),
    k1: [`<th class="bm-grp-h${zus}" colspan="3">${esc(label)}</th>`],
    k2: dreh([`<th class="bm-v-h${zus}">V</th>`, `<th class="bm-a-h${zus}">A</th>`, `<th class="bm-g-h${zus}">Ges</th>`]),
    td: (p) => {
      const w = holen(p);
      return dreh([
        `<td class="bm-v${zus}">${w.geteilt && w.volle ? w.volle : ''}</td>`,
        `<td class="bm-a${zus}">${w.geteilt && w.abr ? w.abr : ''}</td>`,
        `<td class="bm-wert${zus}">${w.holz || ''}</td>`,
      ]);
    },
    tf: (w) => dreh([
      `<td class="bm-v bm-sum${zus}">${w.volle || ''}</td>`,
      `<td class="bm-a bm-sum${zus}">${w.abr || ''}</td>`,
      `<td class="bm-wert bm-sum${zus}">${w.holz || ''}</td>`,
    ]),
  };
}

// Der Gassen-/Satz-Block als EIN Teil: oben die Überschrift über alle Spalten, darunter je
// Spalte nur noch die NUMMER. Vorher stand in jedem Spaltenkopf „Bahn 1" … „Bahn 12" — je
// nach Stellenzahl und Spaltenbreite brach das mal um und mal nicht, was die Kopfzeile
// unruhig machte. Eine Nummer bricht nie um, und die Überschrift sagt einmal, worum es geht.
//   spiegeln — Spalten rückwärts (rechte Tabelle in der SATZ-Ansicht, siehe teamTabelle)
function gassenTeil(spalten, titel, { spiegeln }) {
  if (!spalten.length) return { cols: [], k1: [], k2: [], td: () => [], tf: () => [] };
  const dreh = (zellen) => (spiegeln ? zellen.slice().reverse() : zellen);
  return {
    cols: dreh(spalten.map(() => '<col class="bm-c-g">')),
    k1: [`<th class="bm-grp-h is-gassen" colspan="${spalten.length}">${esc(titel)}</th>`],
    k2: dreh(spalten.map((sp) => `<th class="bm-nr-h">${esc(sp.label)}</th>`)),
    td: (p) => dreh(spalten.map((sp) => `<td class="bm-wert">${spaltenHolz(p, sp) || ''}</td>`)),
    // Fußzeile: der DURCHSCHNITT der Spieler, die auf dieser Gasse standen — eine Bahnsumme
    // über unterschiedlich viele Spieler ließe sich zwischen den Mannschaften nicht vergleichen.
    tf: (schnitte) => dreh(schnitte.map((v) => `<td class="bm-wert bm-schnitt">${v ? `<span class="bm-schnitt-z">⌀</span>${v}` : ''}</td>`)),
  };
}

// Die Teile einer Zeile in die richtige Reihenfolge bringen. Links steht der Name außen und
// die Zahlen innen; rechts ist alles gespiegelt — nur die Gassen-/Satz-Nummern bleiben auf
// beiden Seiten aufsteigend (wie im Overlay), sonst liest man rechts rückwärts.
//
// Die GESAMT-Gruppe wird dagegen mitgespiegelt (wertTeil({ spiegeln })): rechts steht sie als
// Ges · A · V, links als V · A · Ges. Dadurch liegen die beiden Gesamtergebnisse symmetrisch
// zur Bildmitte — die Zahl, die zählt, steht auf beiden Seiten innen.
function ordne(aussen, mitte, innen, side) {
  return side === 'l'
    ? aussen.concat(mitte, innen)
    : innen.slice().reverse().concat(mitte, aussen.slice().reverse());
}

function teamTabelle(players, side, { spalten, mitAbraeum, mitEwp, liveDgs }) {
  // Gesamtergebnis eines Spielers in derselben Form wie ein Satz (V/A/Summe).
  const gesamtWerte = (p) => ({
    holz: p.gesamt || 0,
    volle: (p.gesamt || 0) - (p.abraeum || 0),
    abr: p.abraeum || 0,
    geteilt: (p.abraeum || 0) > 0,
  });

  // Der Kopf hat zwei Zeilen, sobald es Gassen-Spalten (Nummern) oder die V/A-Aufteilung des
  // Gesamtergebnisses gibt. Einspaltige Teile spannen dann über beide Zeilen.
  const zweiZeilig = spalten.length > 0 || mitAbraeum;
  const nameTeil = {
    cols: ['<col class="bm-c-nm">'],
    k1: [`<th class="bm-nm-h"${zweiZeilig ? ' rowspan="2"' : ''}>Spieler</th>`],
    k2: [],
    // Der Name steckt in einem eigenen Block: der deckelt ihn auf zwei Zeilen und hält damit
    // die Zeilenhöhe konstant — sonst wäre eine Zeile mit langem Namen höher als die anderen,
    // und die Zeilen der beiden Mannschaften lägen sich nicht mehr gegenüber.
    td: (p) => [`<td class="bm-nm"><span class="bm-nm-t">${esc(p.name || '')}</span></td>`],
    // Die Summenzeile trägt keine Beschriftung: dass die letzte Zeile (abgesetzt, fett, mit
    // ⌀ vor den Gassen-Werten) die Mannschaft ist, sieht man ihr an — das Wort „Mannschaft"
    // stand nur im Weg, wo sonst Namen stehen.
    tf: () => ['<td class="bm-nm"></td>'],
  };
  // Je Gasse (bzw. Satz) genau EINE Zahl: das Ergebnis. Die Aufteilung in Volle und Abräumen
  // gibt es nur beim Gesamtergebnis — dort ist Platz dafür, und dort wird sie gebraucht.
  //
  // GESPIEGELT wird beim Gast alles — bis auf die BAHNEN: die Gasse 4 ist auf beiden Seiten
  // dieselbe Bahn im Saal, eine rückwärts laufende Bahnreihe wäre schlicht falsch zu lesen.
  // SÄTZE dagegen sind eine Reihenfolge und kein Ort; sie drehen mit, damit der jüngste Satz
  // auf beiden Seiten gleich weit von der Bildmitte steht.
  const gassen = gassenTeil(spalten, spalten[0] && spalten[0].bahn != null ? 'Bahnen' : 'Sätze',
    { spiegeln: side === 'r' && !!spalten[0] && spalten[0].bahn == null });
  const gesamtTeil = wertTeil('Gesamt', gesamtWerte, ['bm-c-gv', 'bm-c-ga', 'bm-c-gg'],
    { geteilt: mitAbraeum, zweiZeilig, extra: 'is-ges', spiegeln: side === 'r' });
  const ewpTeil = mitEwp ? {
    cols: ['<col class="bm-c-ewp">'],
    k1: [`<th class="bm-ewp-h"${zweiZeilig ? ' rowspan="2"' : ''}>EWP</th>`],
    k2: [],
    td: (p) => [`<td class="bm-ewp">${num(p.ewp, hatGespielt(p))}</td>`],
    tf: () => [`<td class="bm-ewp bm-sum">${summe(players, (x) => x.ewp) || ''}</td>`],
  } : null;

  const teile = ordne([nameTeil], [gassen], ewpTeil ? [gesamtTeil, ewpTeil] : [gesamtTeil], side);
  const sammle = (f) => teile.flatMap(f).join('');

  const zeilen = players.map((p) => {
    const gespielt = hatGespielt(p);
    const live = liveDgs.has(p.durchgangNr) && gespielt ? ' is-live' : '';
    const zellen = teile.map((t) => t.td(p).join('')).join('');
    return `<tr class="bm-row${live}${gespielt ? '' : ' is-offen'}">${zellen}</tr>`;
  }).join('');

  // Fußzeile: je Gasse der Durchschnitt der Spieler, die dort gespielt haben; beim Gesamt
  // (und bei den EWP) die Summe der Mannschaft.
  const summeVon = (holen) => players.reduce((acc, p) => {
    const w = holen(p);
    return {
      holz: acc.holz + w.holz,
      volle: acc.volle + (w.geteilt ? w.volle : 0),
      abr: acc.abr + (w.geteilt ? w.abr : 0),
    };
  }, { holz: 0, volle: 0, abr: 0 });
  const schnitte = spalten.map((sp) => {
    const werte = players.map((p) => spaltenHolz(p, sp)).filter((h) => h > 0);
    return werte.length ? Math.round(werte.reduce((a, b) => a + b, 0) / werte.length) : 0;
  });
  const fussZellen = ordne(
    [nameTeil.tf().join('')],
    [gassen.tf(schnitte).join('')],
    [gesamtTeil.tf(summeVon(gesamtWerte)).join(''), ...(ewpTeil ? [ewpTeil.tf().join('')] : [])],
    side,
  ).join('');

  const zweiteKopfzeile = sammle((t) => t.k2);
  const kopf2 = zweiteKopfzeile ? `<tr>${zweiteKopfzeile}</tr>` : '';
  return `
    <table class="bm-table bm-table-${side}">
      <colgroup>${sammle((t) => t.cols)}</colgroup>
      <thead><tr>${sammle((t) => t.k1)}</tr>${kopf2}</thead>
      <tbody>${zeilen}</tbody>
      <tfoot><tr class="bm-total">${fussZellen}</tr></tfoot>
    </table>`;
}

function logoBox(team) {
  const src = team && team.logo;
  const hell = team && team.logoBg === 'light' ? ' is-light' : '';
  return `<div class="bm-logo${hell}">${src ? `<img src="${esc(src)}" alt="">` : '<span>🎳</span>'}</div>`;
}

// Kopfband: Logo + Name je Mannschaft, in der Mitte der Spielstand.
// Der Wettkampfname steht seit 2026-09-16 NICHT mehr hier, sondern als Überschrift über der
// ganzen Tafel (frei einstellbar) — und der Satz über den Stand der Durchgänge ist ganz weg:
// welcher Durchgang läuft, zeigt die hervorgehobene Zeile in der Tabelle.
function kopf(teams, pHome, pAway, wertung) {
  const [home, away] = teams;
  const mitW = !!wertung;
  const links = mitW ? fmtPunkte(wertung.home.spielpunkte) : summe(pHome, (p) => p.gesamt);
  const rechts = mitW ? fmtPunkte(wertung.away.spielpunkte) : summe(pAway, (p) => p.gesamt);
  const label = mitW ? 'Spielpunkte' : 'Kegel';
  return `
    <header class="bm-head">
      <div class="bm-head-team bm-head-l">
        ${logoBox(home)}
        <span class="bm-head-nm">${esc(home.name || '')}</span>
      </div>
      <div class="bm-head-mitte">
        <div class="bm-score">
          <span class="bm-score-v">${links}</span>
          <span class="bm-score-x">:</span>
          <span class="bm-score-v">${rechts}</span>
        </div>
        <span class="bm-score-lbl">${label}</span>
      </div>
      <div class="bm-head-team bm-head-r">
        <span class="bm-head-nm">${esc(away.name || '')}</span>
        ${logoBox(away)}
      </div>
    </header>`;
}

// Datum des Wettkampfs, deutsch und zweistellig (16.09.2026) — wie im Mannschaftsbericht.
// Auf der Leinwand liest sich das ruhiger als das kurze „16.9.2026".
function datumText(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? ''
    : d.toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

// Fußleiste unter den Tabellen: links das Datum, rechts der Spielort (die Anlage), sofern
// hinterlegt. Beides steht ruhig am Rand — es beantwortet die Frage „welches Spiel ist das?",
// ohne Platz aus der Tafel zu nehmen.
//
// In der Mitte steht der Hinweis, solange noch nichts geworfen wurde. Er hat bewusst KEINE
// eigene Zeile: als eigener Absatz verschwand er mit dem ersten Wurf, und in dem Moment wuchsen
// alle Tabellenzeilen um ein paar Pixel — die Tafel ruckte, während gerade jemand hinsah.
function fussLeiste(wettkampf, hinweis) {
  const datum = datumText(wettkampf && wettkampf.datum);
  const ort = ((wettkampf && wettkampf.anlageName) || '').trim();
  if (!datum && !ort && !hinweis) return '';
  return `
    <footer class="bm-fuss">
      <span class="bm-fuss-l">${esc(datum)}</span>
      <span class="bm-fuss-m">${esc(hinweis || '')}</span>
      <span class="bm-fuss-r">${esc(ort)}</span>
    </footer>`;
}

// ── Reine Render-Funktion ───────────────────────────────────────────────────
// Aus { wettkampf, games } (wie fetchOverlay sie liefert bzw. das Grafik-Panel sie lokal hat)
// die vollständige Beamer-Tafel bauen. Ohne Netz und ohne DOM — deshalb testbar.
// Spalten ('bahnen' | 'saetze') und Thema ('dunkel' | 'hell') kommen aus `wettkampf.beamer`
// und damit aus denselben Daten wie die Ergebnisse — jede Anzeige zeigt dieselbe Fassung.
export function buildBeamerHtml(data) {
  const { wettkampf, games } = data || {};
  if (!wettkampf) return `<div class="bm-wait">Warte auf Wettkampf-Daten …</div>`;
  const teams = (wettkampf.mannschaften || []).slice(0, 2);
  if (teams.length < 2) {
    return `<div class="bm-wait">Die Beamer-Ansicht braucht zwei Mannschaften.</div>`;
  }
  const { spalten: modus, thema, titel } = beamerOptionen(wettkampf);

  const stats = computeWettkampfStats(wettkampf, games || []);
  const wertung = computeWertung(wettkampf, stats, games || []);
  // EWP wie im Hub/Overlay auf die volle Feldgröße skalieren, damit überall dieselbe Skala steht.
  if (wertung) {
    const feldGroesse = (wettkampf.spielerJeMannschaft || 0) * (wettkampf.mannschaften || []).length;
    assignEwp(stats.einzel, teams[0].id, wettkampf.wertung?.ewp?.minHolz ?? 1, feldGroesse);
  }

  const pHome = playersOfTeam(stats, teams[0].id);
  const pAway = playersOfTeam(stats, teams[1].id);
  const alle = pHome.concat(pAway);
  // Volle/Abräumen nur zeigen, wenn das Programm überhaupt abgeräumt wird (Schere/Classic) —
  // bei reinen Volle-Programmen (Bohle) wären es drei Spalten Nullen.
  const mitAbraeum = alle.some((p) => (p.abraeum || 0) > 0);
  const statusList = durchgangStatusList(wettkampf, games || []);
  const tabOpts = {
    spalten: spaltenDef(wettkampf, alle, modus),
    mitAbraeum,
    mitEwp: !!wertung,
    liveDgs: new Set(statusList.filter((d) => d.status === 'laufend').map((d) => d.nr)),
  };

  const leer = alle.every((p) => !hatGespielt(p))
    ? 'Noch kein Ergebnis erfasst — die Tafel füllt sich mit dem ersten Wurf.'
    : '';

  // Überschrift nur, wenn eine eingestellt ist. Kein Rückfall auf den Wettkampfnamen: wer das
  // Feld leer lässt, will die Zeile nicht — und die Tafel gewinnt die Höhe für die Tabellen.
  return `
    <div class="bm-page${thema === 'hell' ? ' is-hell' : ''}">
      ${titel ? `<h1 class="bm-titel">${esc(titel)}</h1>` : ''}
      ${kopf(teams, pHome, pAway, wertung)}
      <div class="bm-grid">
        <section class="bm-team bm-team-l">
          ${teamTabelle(pHome, 'l', tabOpts)}
        </section>
        <section class="bm-team bm-team-r">
          ${teamTabelle(pAway, 'r', tabOpts)}
        </section>
      </div>
      ${fussLeiste(wettkampf, leer)}
    </div>`;
}
