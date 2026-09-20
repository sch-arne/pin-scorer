// Grafik-Menü: das Ausgabe-Fenster des 🖼-Knopfs. Vier Reiter:
//   • „Ergebnis-Grafik" — Vorschau + Optionen des Bild-Exports, Teilen und PNG-Speichern.
//   • „Spieler"         — dasselbe für EINEN Spieler: alle Einzelwürfe mit Teilsatz- und
//                         Satzergebnissen auf einem Bild (das Wurfprotokoll zum Teilen).
//   • „Livestream"      — Vorschau des OBS-Overlays, Team-Logos/Farben und die OBS-URL.
//   • „Beamer"          — Vorschau der ausführlichen Ergebnistafel für die Leinwand, mit
//                         Vollbild auf diesem Gerät und einer URL für ein zweites Gerät.
// Geöffnet aus der Wurferfassung (views/spiel-laufend.js) und dem Wettkampf-Hub
// (views/wettkampf-hub.js) über den 🖼-Knopf in der Kopfzeile.
//
// Der Livestream-Reiter liegt bewusst HIER und nicht nur im Hub: die Overlay-Sektion des Hubs
// gibt es nur im Kontrollzentrum-Layout (breiter Bildschirm). Über den 🖼-Knopf ist dieselbe
// Übersicht auch vom Handy und mitten aus der laufenden Erfassung erreichbar. Markup und
// Handler kommen aus views/livestream-einstellungen.js — eine Quelle für beide Orte.
//
// Das Panel hängt sich SELBST an document.body statt Teil eines View-Templates zu sein:
// spiel-laufend setzt bei jedem Wurf `root.innerHTML = template()` — eine Canvas darin wäre
// bei jeder Eingabe zerstört (Bitmap weg, Texteingabe verliert den Fokus). Der Preis ist,
// dass das Panel eine Navigation überleben würde; deshalb ist der UNMOUNT_EVENT-Listener
// hier Pflicht und nicht optional.
//
// Die GRAFIK ist ein SCHNAPPSCHUSS: `datenFn()` wird beim Öffnen und beim ↻ aufgerufen, damit
// sich die Zahlen beim Konfigurieren nicht unter den Händen bewegen. Die Livestream-Vorschau
// dagegen läuft mit (Polling) — sie soll ja zeigen, was der Stream gerade sendet.

import { UNMOUNT_EVENT } from '../router.js';
import { getSettings, saveSettings } from '../store.js';
import {
  grafikModell, grafikOptionen, normalisiereOptionen, grafikDateiname,
  grafikTexte, merkeGrafikTexte,
} from '../logic/ergebnis-grafik.js';
import { FORMATE, zeichneGrafik } from '../logic/grafik-zeichnen.js';
import {
  spielerQuellen, spielerGrafikModell, spielerGrafikOptionen, normalisiereSpielerOptionen,
  spielerGrafikDateiname, spielerTextId,
} from '../logic/spieler-grafik.js';
import { zeichneSpielerGrafik } from '../logic/spieler-zeichnen.js';
import { overlayHtmlLive } from './overlay.js';
import { buildBeamerHtml, beamerUrl, beamerOptionen } from './beamer.js';
import {
  livestreamFelderHtml, livestreamUrlHtml, wireLivestreamFelder, overlayBereit,
  beamerFelderHtml, wireBeamerFelder,
} from './livestream-einstellungen.js';
import { esc } from '../util.js';

// Es gibt immer höchstens EIN Panel — ein zweiter Öffnen-Klick ersetzt das erste.
let offen = null;

// Takt der mitlaufenden Vorschauen (Livestream/Beamer, nur solange der Reiter offen ist).
// Etwas ruhiger als das Overlay selbst (2 s) — die Vorschau ist eine Kontrolle, kein Stream.
const STREAM_POLL_MS = 3000;
const STAGE_W = 1920;
const STAGE_H = 1080;

const SEGMENTE = [
  ['format', 'Format', 'Seitenverhältnis des Bildes', [['hoch', 'Hochformat'], ['story', 'Story']]],
  ['schrift', 'Schrift', 'Schmal bringt lange Namen ungekürzt unter; nicht jedes Gerät hat jede Schrift', [['system', 'System'], ['schmal', 'Schmal'], ['serif', 'Serif']]],
  ['textfarbe', 'Textfarbe', 'Helle Schrift für dunkle Hintergründe — und umgekehrt', [['hell', 'Hell'], ['dunkel', 'Dunkel']]],
  ['flaechen', 'Flächen', 'Halbtransparente Platten hinter den Zeilen halten den Text auch auf unruhigen Fotos lesbar', [['aus', 'Aus'], ['dezent', 'Dezent'], ['kraeftig', 'Kräftig']]],
  ['position', 'Position', 'Wo der Block im Bild sitzt', [['oben', 'Oben'], ['mitte', 'Mitte'], ['unten', 'Unten']]],
];

const SCHALTER = [
  ['ewp', 'EWP-Spalte', 'Einzelwettkampfpunkte je Spieler', 'mitEwp', 'Erst nach Spielende verfügbar (und nur mit hinterlegter Wertung).'],
  ['spielpunkte', 'Spielpunkte', 'Der Spielstand zwischen den Logos', 'mitSpielpunkte', 'Für diese Bahnart ist keine Wertung hinterlegt.'],
  ['logos', 'Logos', 'Mannschaftslogos unter der Tabelle', 'hatLogos', 'Im Reiter „Livestream" hochladen.'],
  ['spaltenkoepfe', 'Spaltenköpfe', 'Kopfzeile über den Spalten', null, ''],
  ['kontur', 'Umrandung', 'Dunkler Rand um jede Schrift — hält den Text auf unruhigen Fotos lesbar', null, ''],
];

// Die Regler des Spieler-Reiters: erst die Reihenfolge der Blöcke (nur hier), dann dieselben
// fünf wie oben. Die Optionen werden GETRENNT gemerkt — eine Wurftabelle braucht oft ein
// anderes Format als die Rangliste.
const SEGMENTE_SP = [
  ['reihenfolge', 'Reihenfolge', 'Blöcke nach Satz-Nummer oder nach Bahnnummer (wie die Spalten der Beamer-Tafel)', [['saetze', 'Sätze'], ['bahnen', 'Bahnen']]],
  ...SEGMENTE,
];

const SCHALTER_SP = [
  ['logo', 'Mannschaftslogo', 'Das Logo der Mannschaft links neben dem Namen', 'hatLogo', 'Für diese Mannschaft ist kein Logo hinterlegt (Reiter „Livestream").'],
  ['kegelbilder', 'Kegelbilder', 'Über jedem Wurf das Bild: ● gefallen · ○ stehend', 'hatKegel', 'Für dieses Spiel sind keine Kegelbilder erfasst.'],
  ['wurfnummern', 'Wurfnummern', 'Kleine Nummer unter jedem Wurf (je Satz gezählt)', 'hatWuerfe', 'Es sind keine Einzelwürfe erfasst.'],
  ['kennzahlen', 'Kennzahlen', 'Fußzeile mit Teilsatz-Summen, 9ern, Kränzen und Fehlern', null, ''],
  ['kontur', 'Umrandung', 'Dunkler Rand um jede Schrift — hält den Text auf unruhigen Fotos lesbar', null, ''],
];

// `attr` ist der Datenname, an dem die Klick-Auswertung hängt: 'gfx' für die Ergebnis-Grafik,
// 'sgfx' für den Spieler-Reiter. So stören sich die beiden Optionssätze nicht.
function segmentHtml(id, label, hinweis, werte, attr = 'gfx') {
  const btns = werte.map(([w, t]) =>
    `<button type="button" class="erf-seg-btn" data-${attr}="${id}" data-wert="${w}">${esc(t)}</button>`).join('');
  return `
    <div class="erf-setting-row">
      <div class="erf-setting-text">
        <span class="erf-setting-label">${esc(label)}</span>
        <span class="erf-setting-hint">${esc(hinweis)}</span>
      </div>
      <div class="erf-seg" role="group" aria-label="${esc(label)}">${btns}</div>
    </div>`;
}

function schalterHtml(id, label, hinweis, attr = 'gfx') {
  return `
    <div class="erf-setting-row" data-row="${id}">
      <div class="erf-setting-text">
        <span class="erf-setting-label">${esc(label)}</span>
        <span class="erf-setting-hint" data-hint="${id}">${esc(hinweis)}</span>
      </div>
      <button type="button" class="erf-switch" role="switch" data-${attr}="${id}" aria-label="${esc(label)}">
        <span class="erf-switch-knob"></span>
      </button>
    </div>`;
}

function reiterHtml(id, label, aktiv) {
  return `<button type="button" class="gfx-tab${aktiv ? ' is-on' : ''}" role="tab"
    data-gfx-tab="${id}" aria-selected="${aktiv ? 'true' : 'false'}">${esc(label)}</button>`;
}

function panelHtml(titel, untertitel) {
  return `
    <div class="gfx-sheet" role="dialog" aria-modal="true" aria-label="Grafik, Livestream und Beamer">
      <div class="erf-settings-head">
        <h2 class="erf-settings-title">🖼 Grafik, Stream &amp; Beamer</h2>
        <span class="gfx-head-btns">
          <button type="button" class="icon-btn" data-gfx="refresh" aria-label="Stand aktualisieren" title="Aktuellen Spielstand holen">↻</button>
          <button type="button" class="icon-btn" data-gfx="close" aria-label="Schließen">✕</button>
        </span>
      </div>
      <div class="gfx-tabs" role="tablist" aria-label="Ansicht">
        ${reiterHtml('grafik', '🖼 Ergebnis-Grafik', true)}
        ${reiterHtml('spieler', '👤 Spieler', false)}
        ${reiterHtml('stream', '📺 Livestream', false)}
        ${reiterHtml('beamer', '📽 Beamer', false)}
      </div>

      <div class="gfx-pane" data-pane="grafik" role="tabpanel">
        <div class="gfx-body">
          <div class="gfx-preview">
            <div class="gfx-canvas-wrap"><canvas class="gfx-canvas" role="img" aria-label="Vorschau der Ergebnis-Grafik"></canvas></div>
            <p class="gfx-meta" data-meta role="status"></p>
          </div>
          <div class="gfx-options">
            <label class="acc-label" for="gfx-titel">Titel</label>
            <input class="join-input acc-text" id="gfx-titel" type="text" data-gfx-text="titel" maxlength="60" placeholder="Ohne Titel" value="${esc(titel)}">
            <label class="acc-label" for="gfx-untertitel">Untertitel</label>
            <input class="join-input acc-text" id="gfx-untertitel" type="text" data-gfx-text="untertitel" maxlength="80" placeholder="Ohne Untertitel" value="${esc(untertitel)}">
            <p class="gfx-hint gfx-text-hint">Titel und Untertitel bleiben für dieses Spiel gespeichert — beim nächsten Öffnen stehen sie wieder da.</p>
            ${SEGMENTE.map(([id, l, h, w]) => segmentHtml(id, l, h, w)).join('')}
            ${SCHALTER.map(([id, l, h]) => schalterHtml(id, l, h)).join('')}
          </div>
        </div>
        <div class="gfx-actions">
          <button type="button" class="erf-btn done" data-gfx="share" disabled>↗ Teilen</button>
          <button type="button" class="erf-btn" data-gfx="download" disabled>⤓ PNG speichern</button>
        </div>
        <p class="gfx-hint">Der Hintergrund bleibt transparent — das Bild lässt sich über ein eigenes Foto legen.
          Auf dem iPhone am besten „Teilen" → „Bild sichern".</p>
      </div>

      <div class="gfx-pane" data-pane="spieler" role="tabpanel" hidden>${spielerPaneHtml()}</div>
      <div class="gfx-pane" data-pane="stream" role="tabpanel" hidden></div>
      <div class="gfx-pane" data-pane="beamer" role="tabpanel" hidden></div>
    </div>`;
}

// Inhalt des Spieler-Reiters. Er wird EINMAL mit dem Panel gebaut und danach nur noch
// neu gezeichnet: die Canvas darin überlebt kein innerHTML (dasselbe Argument, aus dem das
// ganze Panel am body und nicht im View-Root hängt). Aktualisiert werden später nur noch
// die Einträge der Spieler-Auswahl (fuelleSpielerWahl) und das Bild selbst.
function spielerPaneHtml() {
  return `
    <p class="gfx-stream-info">Die Ergebnisansicht EINES Spielers: alle Einzelwürfe, je Teilsatz
      die Summe, je Satz das Ergebnis — das Wurfprotokoll als teilbares Bild.</p>
    <div class="gfx-sp-wahl">
      <label class="acc-label" for="gfx-sp-wahl">Spieler</label>
      <select class="join-input acc-text" id="gfx-sp-wahl" data-sp-wahl></select>
    </div>
    <div class="gfx-sp-titel">
      <label class="acc-label" for="gfx-sp-ueber">Überschrift</label>
      <input class="join-input acc-text" id="gfx-sp-ueber" type="text" data-sp-ueber maxlength="60"
        placeholder="Ohne Überschrift">
      <label class="acc-label" for="gfx-sp-titel">Name</label>
      <input class="join-input acc-text" id="gfx-sp-titel" type="text" data-sp-titel maxlength="60"
        placeholder="Name des Spielers">
      <p class="gfx-hint gfx-text-hint">Die Überschrift steht über dem Namen; leer lassen heißt:
        keine Überschrift. Beim Namen heißt leer: der Name aus der Aufstellung.
        Beides bleibt je Spieler gespeichert.</p>
    </div>
    <p class="field-hint gfx-stream-leer" data-sp-leer hidden>Für dieses Spiel ist noch niemand
      in der Aufstellung — es gibt hier nichts anzuzeigen.</p>
    <div class="gfx-body">
      <div class="gfx-preview">
        <div class="gfx-canvas-wrap"><canvas class="gfx-canvas" data-sp-canvas role="img" aria-label="Vorschau des Spieler-Bildes"></canvas></div>
        <p class="gfx-meta" data-sp-meta role="status"></p>
      </div>
      <div class="gfx-options">
        ${SEGMENTE_SP.map(([id, l, h, w]) => segmentHtml(id, l, h, w, 'sgfx')).join('')}
        ${SCHALTER_SP.map(([id, l, h]) => schalterHtml(id, l, h, 'sgfx')).join('')}
      </div>
    </div>
    <div class="gfx-actions">
      <button type="button" class="erf-btn done" data-sgfx="share" disabled>↗ Teilen</button>
      <button type="button" class="erf-btn" data-sgfx="download" disabled>⤓ PNG speichern</button>
    </div>
    <p class="gfx-hint">Auch hier bleibt der Hintergrund transparent. Titel und Untertitel des
      Reiters „Ergebnis-Grafik" stehen als Kontextzeile unter dem Namen.</p>`;
}

// Inhalt des Livestream-Reiters. `roh` sind die Rohdaten aus datenFn() ({ wettkampf, games }
// oder { game }); ohne Wettkampf gibt es kein Overlay — dann nur ein Hinweis.
function streamHtml(roh, bearbeitbar) {
  const wettkampf = roh && roh.wettkampf;
  if (!wettkampf) {
    return `<p class="field-hint gfx-stream-leer">Das Livestream-Overlay gehört zu einem <b>Wettkampf</b>.
      Dieses Spiel läuft ohne Wettkampf — es gibt hier nichts zu übertragen.</p>`;
  }
  const felder = bearbeitbar
    ? `<div class="gfx-stream-felder">
         ${livestreamFelderHtml(wettkampf)}
         ${livestreamUrlHtml(wettkampf)}
         <p class="join-msg" data-overlay-msg role="status"></p>
       </div>`
    : `<p class="field-hint">Du siehst diesen Wettkampf als Zuschauer — Logos und OBS-URL sind nicht änderbar.</p>`;
  return `
    <p class="gfx-stream-info">So sieht das Overlay gerade in OBS aus (1920×1080, transparenter Hintergrund).
      Die Vorschau läuft mit dem Spielstand mit.</p>
    <div class="gfx-ov-frame gfx-buehne"><div class="ov-stage gfx-ov-stage" data-stage></div></div>
    ${felder}`;
}

// Inhalt des Beamer-Reiters: Vorschau der Ergebnistafel, die Anzeige-Einstellungen, der
// Vollbild-Knopf für DIESES Gerät und — nur bei geteiltem Wettkampf — die URL für ein
// zweites Gerät am Beamer. Die Einstellungen (Markup und Handler) kommen aus
// views/livestream-einstellungen.js: sie stehen am Wettkampf, nicht am Gerät.
function beamerHtml(roh, bearbeitbar) {
  const wettkampf = roh && roh.wettkampf;
  if (!wettkampf) {
    return `<p class="field-hint gfx-stream-leer">Die Beamer-Tafel zeigt einen <b>Wettkampf</b> mit zwei Mannschaften.
      Dieses Spiel läuft ohne Wettkampf — es gibt hier nichts anzuzeigen.</p>`;
  }
  const url = esc(beamerUrl(wettkampf));
  const zweitgeraet = overlayBereit(wettkampf)
    ? `<div class="ov-url-row">
         <input class="ov-url-input" type="text" readonly value="${url}" data-beamer-url aria-label="Beamer-URL">
         <button type="button" class="btn-mini" data-action="copy-beamer">Kopieren</button>
         <a class="btn-mini" href="${url}" target="_blank" rel="noopener">Öffnen</a>
       </div>
       <p class="field-hint">Für einen <b>zweiten Rechner</b> am Beamer: diese URL dort öffnen und
         mit F11 auf Vollbild stellen — sie liest den Stand live mit. Spalten und Darstellung
         stellt man weiter <b>hier</b> um; die Leinwand zieht wenige Sekunden später nach.</p>`
    : `<p class="field-hint">Hängt der Beamer an einem <b>anderen Gerät</b>, zuerst den
         <b>Wettkampf teilen</b> — dann erscheint hier eine URL für dieses Gerät.</p>`;
  return `
    <p class="gfx-stream-info">Die ausführliche Tafel für die Leinwand: jede Gasse, Volle, Abräumen
      und Fehlwürfe, Gesamt und EWP — dazu die Bestenliste. Läuft mit dem Spielstand mit.</p>
    <div class="gfx-bm-einstellungen">${beamerFelderHtml(wettkampf, bearbeitbar)}</div>
    <div class="gfx-bm-frame gfx-buehne${beamerOptionen(wettkampf).thema === 'hell' ? ' is-hell' : ''}"><div class="bm-stage gfx-bm-stage" data-stage></div></div>
    <div class="gfx-actions">
      <button type="button" class="erf-btn done" data-gfx="beamer-voll">⛶ Vollbild auf diesem Gerät</button>
    </div>
    <p class="join-msg" data-beamer-msg role="status"></p>
    ${zweitgeraet}`;
}

// Das Menü öffnen.
//   datenFn()   — Rohdaten für grafikModell() ({ wettkampf, games } oder { game }), bei jedem
//                 Aufruf frisch.
//   livestream  — { onChange, onPush } erlaubt das Bearbeiten von Logos/Farben im
//                 Livestream-Reiter (der Aufrufer rendert danach seine Ansicht neu und
//                 spiegelt die Config zum Server). Ohne Angabe ist der Reiter nur Anzeige.
export function oeffneGrafikMenue({ datenFn, livestream }) {
  if (offen) offen.schliessen();
  let lebt = true;
  let historyEintrag = false;
  let letzteDatei = null;
  let reiter = 'grafik';
  let vorschauTimer = null;
  let streamHtmlStand = '';   // zuletzt gezeichnetes Overlay-HTML (kein Flackern)
  let beamerHtmlStand = '';   // dito für die Beamer-Tafel
  const laneHold = { fertigNr: null, fertigSeit: 0 }; // Bahnansicht-Halten wie im Overlay
  let textTimer = null;       // entprellt das Merken von Titel/Untertitel
  const bilder = {};
  // Spieler-Reiter: gewählter Spieler, sein Modell und seine (eigenen) Optionen.
  // `spWunsch` ist die GEMERKTE Wahl, `spOpts` die gegen das Modell gültig gemachte Fassung —
  // getrennt, damit ein Spiel ohne Kegelbilder den Schalter nicht dauerhaft löscht.
  let spKey = '';
  let spModell = null;
  let spWunsch = spielerGrafikOptionen(getSettings());
  let spOpts = normalisiereSpielerOptionen(spWunsch, null);
  let spDatei = null;
  let spGezeichnet = false;   // erst beim ersten Öffnen des Reiters zeichnen
  let spUeber = '';           // freie Überschrift über dem Namen ('' = keine Zeile)
  let spTitel = '';           // eigener Name des gewählten Spielers ('' = der aus der Aufstellung)
  let spTextTimer = null;     // entprellt das Merken der Überschrift

  let roh = holeRoh();
  let modell = grafikModell(roh);
  let opts = normalisiereOptionen(grafikOptionen(getSettings()), modell);
  // Titel/Untertitel: die eigenen Eingaben zu DIESEM Spiel schlagen den Vorschlag aus dem
  // Modell — sonst wäre jede Anpassung beim nächsten Öffnen wieder weg.
  const gemerkt = grafikTexte(getSettings(), modell.id);
  let titel = gemerkt ? gemerkt.titel : modell.titel;
  let untertitel = gemerkt ? gemerkt.untertitel : modell.untertitel;

  function holeRoh() {
    try { return datenFn() || null; } catch (e) { return null; }
  }

  const backdrop = document.createElement('div');
  backdrop.className = 'gfx-backdrop';
  backdrop.innerHTML = panelHtml(titel, untertitel);
  document.body.appendChild(backdrop);

  const canvas = backdrop.querySelector('.gfx-canvas');
  const metaEl = backdrop.querySelector('[data-meta]');
  const shareBtn = backdrop.querySelector('[data-gfx="share"]');
  const downloadBtn = backdrop.querySelector('[data-gfx="download"]');
  const titelEl = backdrop.querySelector('[data-gfx-text="titel"]');
  const untertitelEl = backdrop.querySelector('[data-gfx-text="untertitel"]');
  const streamPane = backdrop.querySelector('[data-pane="stream"]');
  const beamerPane = backdrop.querySelector('[data-pane="beamer"]');
  const spielerPane = backdrop.querySelector('[data-pane="spieler"]');
  const spCanvas = spielerPane.querySelector('[data-sp-canvas]');
  const spMetaEl = spielerPane.querySelector('[data-sp-meta]');
  const spShareBtn = spielerPane.querySelector('[data-sgfx="share"]');
  const spDownloadBtn = spielerPane.querySelector('[data-sgfx="download"]');
  const spWahlEl = spielerPane.querySelector('[data-sp-wahl]');
  const spTitelEl = spielerPane.querySelector('[data-sp-titel]');
  const spUeberEl = spielerPane.querySelector('[data-sp-ueber]');

  // ── Zeichnen ───────────────────────────────────────────────────────────────
  function zeichne() {
    if (!lebt) return;
    let layout = null;
    try {
      layout = zeichneGrafik(canvas, { ...modell, titel, untertitel }, opts, bilder);
    } catch (e) {
      metaEl.textContent = 'Die Grafik konnte nicht gezeichnet werden.';
      return;
    }
    const fmt = FORMATE[opts.format];
    const eng = layout.skala < 0.6 ? ' · viele Spieler — die Tabelle wird verkleinert' : '';
    metaEl.textContent = `${fmt.masse} · PNG mit Transparenz${eng}`;
    canvas.setAttribute('aria-label', bildBeschreibung());
    planeBlob();
  }

  function bildBeschreibung() {
    if (modell.modus === 'duell') {
      return `Ergebnis ${modell.teams.map((t) => `${t.name} ${t.summeHolz}`).join(' gegen ')}`;
    }
    return `Rangliste mit ${modell.zeilen.length} Spielern`;
  }

  // Die PNG-Datei EAGER nach jedem Zeichnen erzeugen: navigator.share() muss synchron in der
  // Nutzergeste stehen — ein `await toBlob()` davor verbraucht die User-Activation und iOS
  // wirft NotAllowedError. Der Teilen-Knopf teilt deshalb eine schon fertige Datei.
  // Beide Bilder (Ergebnis-Grafik und Spieler-Reiter) gehen denselben Weg, deshalb ein
  // gemeinsamer Helfer: `merke` legt die fertige Datei dort ab, wo der jeweilige Reiter sie
  // beim Teilen/Speichern sucht.
  //
  // toBlob ist ASYNCHRON: tippt jemand weiter, ist schon das nächste Zeichnen unterwegs,
  // bevor das vorige seine Datei abgeliefert hat. Deshalb zählt `blobLauf` je Ziel mit — ein
  // verspäteter Rückruf aus einem überholten Lauf wird verworfen, statt die neuere Datei
  // (und ihren Dateinamen) zu überschreiben. `nameFn` wird aus demselben Grund erst im
  // Rückruf ausgewertet.
  const blobLauf = { grafik: 0, spieler: 0 };
  function planeDatei(ziel, cv, nameFn, share, download, meta, merke) {
    const lauf = (blobLauf[ziel] += 1);
    merke(null);
    share.disabled = true;
    download.disabled = true;
    try {
      cv.toBlob((blob) => {
        if (!lebt || !blob || blobLauf[ziel] !== lauf) return;
        merke(new File([blob], nameFn(), { type: 'image/png' }));
        share.disabled = false;
        download.disabled = false;
      }, 'image/png');
    } catch (e) {
      meta.textContent = 'Das Bild konnte nicht erzeugt werden.';
    }
  }

  function planeBlob() {
    planeDatei('grafik', canvas, () => grafikDateiname({ ...modell, titel }),
      shareBtn, downloadBtn, metaEl, (d) => { letzteDatei = d; });
  }

  // Logos einmal laden und merken; die Vorschau startet sofort ohne sie und wird danach
  // nachgezeichnet, damit sie nicht leer bleibt.
  function ladeBilder() {
    const offeneTeams = (modell.teams || []).filter((t) => t.logo && !bilder[t.id]);
    if (!offeneTeams.length) return;
    Promise.all(offeneTeams.map((t) => new Promise((fertig) => {
      const img = new Image();
      img.onload = () => { bilder[t.id] = img; fertig(); };
      img.onerror = () => fertig();
      img.src = t.logo;
    }))).then(() => { if (lebt) zeichne(); });
  }

  // ── Spieler-Reiter ─────────────────────────────────────────────────────────
  // Die Auswahlliste (neu) befüllen. Getrennt vom Zeichnen, weil sie sich nur beim ↻ ändert
  // (ein nachgetragener Name, ein neuer Durchgang) — und weil ein Neuaufbau des <select>
  // mitten im Zeichnen die Auswahl des Nutzers verlöre.
  function fuelleSpielerWahl() {
    const quellen = spielerQuellen(roh);
    const leerHinweis = spielerPane.querySelector('[data-sp-leer]');
    const body = spielerPane.querySelector('.gfx-body');
    const aktionen = spielerPane.querySelector('.gfx-actions');
    const wahlBox = spielerPane.querySelector('.gfx-sp-wahl');
    const hatSpieler = quellen.length > 0;
    if (leerHinweis) leerHinweis.hidden = hatSpieler;
    if (body) body.hidden = !hatSpieler;
    if (aktionen) aktionen.hidden = !hatSpieler;
    // Bei nur einem Spieler (Training) ist die Auswahl überflüssig.
    if (wahlBox) wahlBox.hidden = quellen.length < 2;
    if (!hatSpieler) { spKey = ''; return; }
    if (!quellen.some((q) => q.key === spKey)) waehleSpieler(quellen[0].key);

    // Im Wettkampf nach Mannschaften gruppieren — bei zwölf Namen ist das der Unterschied
    // zwischen Suchen und Finden.
    const eintrag = (q) => {
      const pos = q.teamPos ? q.teamPos + '. ' : '';
      const bahn = q.startBahn == null ? '' : ' · Bahn ' + q.startBahn;
      return `<option value="${esc(q.key)}"${q.key === spKey ? ' selected' : ''}>${esc(pos + q.name + bahn)}</option>`;
    };
    const gruppen = [];
    quellen.forEach((q) => {
      const name = q.mannschaft || '';
      const letzte = gruppen[gruppen.length - 1];
      if (letzte && letzte.name === name) letzte.eintraege.push(q);
      else gruppen.push({ name, eintraege: [q] });
    });
    spWahlEl.innerHTML = gruppen.map((g) => (g.name
      ? `<optgroup label="${esc(g.name)}">${g.eintraege.map(eintrag).join('')}</optgroup>`
      : g.eintraege.map(eintrag).join(''))).join('');
  }

  // Auf einen anderen Spieler umschalten. Die Überschrift gehört zum SPIELER, nicht zum
  // Panel: beim Wechsel wird erst das Getippte des bisherigen gesichert, dann die gemerkte
  // Überschrift des neuen geladen.
  function waehleSpieler(key) {
    if (spKey && spKey !== key) merkeSpielerTitel();
    spKey = key;
    // Der Topf hält je Eintrag ein Paar {titel, untertitel}; hier sind das Name und
    // Überschrift dieses Spielers.
    const gemerkt = grafikTexte(getSettings(), spielerTextId(spKey));
    spTitel = gemerkt ? gemerkt.titel : '';
    spUeber = gemerkt ? gemerkt.untertitel : '';
    if (spTitelEl) spTitelEl.value = spTitel;
    if (spUeberEl) spUeberEl.value = spUeber;
  }

  // Name und Überschrift je Spieler merken — derselbe Topf und dieselbe Deckelung wie bei
  // Titel/Untertitel der Ergebnis-Grafik (siehe merkeGrafikTexte), nur unter eigenem Schlüssel.
  function merkeSpielerTitel() {
    const id = spielerTextId(spKey);
    if (!id) return;
    // Wer nichts eingegeben hat, soll auch keinen Platz im (gedeckelten) Topf belegen —
    // sonst verdrängte schon das bloße Öffnen des Reiters die Titel anderer Spiele.
    const leer = !String(spTitel).trim() && !String(spUeber).trim();
    if (leer && !grafikTexte(getSettings(), id)) return;
    saveSettings({
      grafikTexte: merkeGrafikTexte(getSettings(), id, { titel: spTitel, untertitel: spUeber }),
    });
  }

  function planeSpielerTitelMerken() {
    clearTimeout(spTextTimer);
    spTextTimer = setTimeout(() => { if (lebt) merkeSpielerTitel(); }, 400);
  }

  // Das Spieler-Bild neu zeichnen. Holt die Rohdaten NICHT selbst — wie die Ergebnis-Grafik
  // ist es ein Schnappschuss von `roh`, damit sich die Zahlen beim Einstellen nicht bewegen.
  function zeichneSpieler() {
    if (!lebt || !spKey) { spMetaEl.textContent = ''; return; }
    // Titel/Untertitel des ersten Reiters als Kontextzeile: das Bild soll sagen, aus welchem
    // Spiel diese Würfe stammen, ohne dass es dafür ein zweites Textfeld braucht.
    spModell = spielerGrafikModell(roh, spKey, {
      ueberschrift: spUeber,
      titel: spTitel,
      untertitel: [titel, untertitel].filter(Boolean).join(' · '),
    });
    // Der Platzhalter zeigt, was ohne eigene Überschrift dastünde.
    if (spTitelEl) spTitelEl.placeholder = spModell.name || 'Name des Spielers';
    spOpts = normalisiereSpielerOptionen(spWunsch, spModell);
    let layout = null;
    try {
      layout = zeichneSpielerGrafik(spCanvas, spModell, spOpts, bilder);
    } catch (e) {
      spMetaEl.textContent = 'Das Bild konnte nicht gezeichnet werden.';
      return;
    }
    spGezeichnet = true;
    ladeSpielerLogo();
    syncSpielerUi();
    const fmt = FORMATE[spOpts.format];
    const eng = layout.skala < 0.8 ? ' · viele Würfe — die Tabelle wird verkleinert' : '';
    const ohne = spModell.hatWuerfe ? '' : ' · keine Einzelwürfe erfasst, nur die Ergebnisse';
    spMetaEl.textContent = `${fmt.masse} · PNG mit Transparenz${eng}${ohne}`;
    spCanvas.setAttribute('aria-label',
      `Wurfbild von ${spModell.name || 'Spieler'}, Gesamt ${spModell.gesamt} Holz`);
    planeDatei('spieler', spCanvas, () => spielerGrafikDateiname(spModell),
      spShareBtn, spDownloadBtn, spMetaEl, (d) => { spDatei = d; });
  }

  // Das Logo der Mannschaft dieses Spielers nachladen. Teilt sich den Bild-Cache `bilder`
  // mit der Ergebnis-Grafik (Schlüssel ist dort wie hier die Mannschafts-ID), lädt also im
  // Duell meist gar nichts nach. Nach dem Laden einmal neu zeichnen — die Vorschau startet
  // ohne Logo, statt auf das Bild zu warten.
  function ladeSpielerLogo() {
    const id = spModell && spModell.mannschaftId;
    if (!id || !spModell.logo || bilder[id]) return;
    const img = new Image();
    img.onload = () => {
      bilder[id] = img;
      if (lebt && reiter === 'spieler') zeichneSpieler();
    };
    img.onerror = () => { /* ohne Logo weiterzeichnen */ };
    img.src = spModell.logo;
  }

  // Schalterstellung im Spieler-Reiter spiegeln. Streng auf `spielerPane` beschränkt: die
  // Zeilen tragen dieselben data-row/data-hint-Namen wie die der Ergebnis-Grafik.
  function syncSpielerUi() {
    spielerPane.querySelectorAll('.erf-seg-btn[data-sgfx]').forEach((b) => {
      const an = spOpts[b.dataset.sgfx] === b.dataset.wert;
      b.classList.toggle('is-on', an);
      b.setAttribute('aria-pressed', String(an));
    });
    SCHALTER_SP.forEach(([id, , hinweis, bedingung, gesperrtText]) => {
      const btn = spielerPane.querySelector(`.erf-switch[data-sgfx="${id}"]`);
      if (!btn) return;
      const moeglich = !bedingung || !!(spModell && spModell[bedingung]);
      btn.classList.toggle('is-on', !!spOpts[id]);
      btn.setAttribute('aria-checked', String(!!spOpts[id]));
      btn.disabled = !moeglich;
      const row = btn.closest('.erf-setting-row');
      if (row) row.classList.toggle('is-gesperrt', !moeglich);
      const hint = row && row.querySelector(`[data-hint="${id}"]`);
      if (hint) hint.textContent = moeglich ? hinweis : gesperrtText;
    });
  }

  // Eine Option des Spieler-Bildes setzen. Gemerkt wird der WUNSCH (spWunsch), nicht die
  // gegen das Modell gekürzte Fassung — sonst wäre „Kegelbilder" nach einem Spiel ohne
  // erfasste Kegel dauerhaft aus.
  function setSpielerOption(id, wert) {
    spWunsch = { ...spWunsch, [id]: wert };
    saveSettings({ spielerGrafik: { ...spWunsch } });
    zeichneSpieler();
  }

  // ── Livestream-Reiter ──────────────────────────────────────────────────────
  // Gerüst (Vorschau-Rahmen + Felder) neu aufbauen und verdrahten. Passiert beim Öffnen des
  // Reiters, beim ↻ und nach jeder Logo-/Farb-Änderung — nicht beim Poll-Takt, sonst verlöre
  // der Farbwähler bei jedem Tick den Fokus.
  function baueStream() {
    const bearbeitbar = !!(livestream && roh && roh.wettkampf);
    streamPane.innerHTML = streamHtml(roh, bearbeitbar);
    streamHtmlStand = '';
    if (bearbeitbar) {
      wireLivestreamFelder(streamPane, roh.wettkampf, {
        onChange: () => {
          if (livestream.onChange) livestream.onChange();
          // Die Logos stecken auch in der Ergebnis-Grafik -> Modell und Bild-Cache erneuern.
          Object.keys(bilder).forEach((k) => { delete bilder[k]; });
          aktualisieren();
        },
        onPush: livestream.onPush || (() => {}),
      });
    }
    malStream();
  }

  // Nur die Overlay-Vorschau neu malen (Gerüst bleibt stehen).
  function malStream() {
    const stage = streamPane.querySelector('[data-stage]');
    if (!stage) return;
    let html = '';
    // Dieselbe Fassung wie in OBS — inklusive des Haltens der Bahnansicht nach einem
    // fertigen Durchgang (`laneHold` traegt den Stand ueber die Takte).
    try { html = overlayHtmlLive(holeRoh() || {}, laneHold); }
    catch (e) { html = '<div class="ov-wait">Vorschau nicht möglich.</div>'; }
    if (html !== streamHtmlStand) {
      streamHtmlStand = html;
      stage.innerHTML = html;
    }
    passeBuehnenAn();
  }

  // ── Beamer-Reiter ──────────────────────────────────────────────────────────
  // Gerüst (Vorschau-Rahmen, Vollbild-Knopf, URL) aufbauen und verdrahten.
  function baueBeamer() {
    // Die Tafel-Einstellungen stehen am Wettkampf — ändern darf sie, wer auch Logos/Farben
    // ändern darf (also nicht der Zuschauer). Danach: Gerüst neu (Schalter und Vorschau
    // zeigen die Wahl) und die Config spiegeln, damit die Leinwand nachzieht.
    const bearbeitbar = !!(livestream && roh && roh.wettkampf);
    beamerPane.innerHTML = beamerHtml(roh, bearbeitbar);
    beamerHtmlStand = '';
    if (bearbeitbar) {
      // Kein livestream.onChange: die Wahl ändert nur die Tafel, nicht die aufrufende Ansicht.
      wireBeamerFelder(beamerPane, roh.wettkampf, {
        onChange: baueBeamer,
        onVorschau: malBeamer, // Tippen in der Überschrift: nur die Tafel neu malen (Fokus!)
        onPush: livestream.onPush || (() => {}),
      });
    }
    const copy = beamerPane.querySelector('[data-action="copy-beamer"]');
    if (copy) copy.addEventListener('click', async () => {
      const url = beamerUrl(roh.wettkampf);
      try { await navigator.clipboard.writeText(url); beamerMsg('URL kopiert.'); }
      catch (e) {
        const inp = beamerPane.querySelector('[data-beamer-url]');
        if (inp) { inp.focus(); inp.select(); }
        beamerMsg('Bitte manuell kopieren (Strg+C).');
      }
    });
    malBeamer();
  }

  function beamerMsg(text) {
    const el = beamerPane.querySelector('[data-beamer-msg]');
    if (el) el.textContent = text || '';
  }

  // Nur die Tafel neu malen (Gerüst bleibt stehen) — dieselbe Fassung wie unter #/beamer.
  function malBeamer() {
    const stage = beamerPane.querySelector('[data-stage]');
    if (!stage) return;
    let html = '';
    try { html = buildBeamerHtml(holeRoh() || {}); }
    catch (e) { html = '<div class="bm-wait">Vorschau nicht möglich.</div>'; }
    if (html !== beamerHtmlStand) {
      beamerHtmlStand = html;
      stage.innerHTML = html;
    }
    passeBuehnenAn();
  }

  // Vollbild auf DIESEM Gerät — der Normalfall, wenn der Beamer am erfassenden Laptop hängt
  // (kein Teilen, keine zweite URL nötig). Der Rahmen selbst geht ins Vollbild, die Bühne
  // wird danach neu eingepasst (fullscreenchange).
  function vollbild() {
    const frame = beamerPane.querySelector('.gfx-bm-frame');
    if (!frame) return;
    if (document.fullscreenElement || document.webkitFullscreenElement) {
      (document.exitFullscreen || document.webkitExitFullscreen || (() => {})).call(document);
      return;
    }
    const anfrage = frame.requestFullscreen || frame.webkitRequestFullscreen;
    if (!anfrage) {
      // iPhone-Safari kennt Vollbild nur für Videos — dort bleibt die URL auf einem zweiten
      // Gerät der Weg auf die Leinwand.
      beamerMsg('Dieses Gerät kann kein Vollbild — bitte die Beamer-URL auf dem Anzeigegerät öffnen.');
      return;
    }
    try {
      Promise.resolve(anfrage.call(frame)).catch(() => beamerMsg('Vollbild wurde abgelehnt.'));
    } catch (e) { beamerMsg('Vollbild wurde abgelehnt.'); }
    // Manche eingebetteten Browser verschlucken die Anfrage lautlos (kein Fehler, kein
    // Vollbild). Dann bleibt der Knopf scheinbar wirkungslos — deshalb nach kurzer Frist
    // nachsehen und den Weg über die Taste F11 nennen.
    setTimeout(() => {
      if (lebt && !document.fullscreenElement && !document.webkitFullscreenElement) {
        beamerMsg('Dieser Browser gibt kein Vollbild frei — mit F11 (Windows) bzw. ⌃⌘F (Mac) geht es trotzdem.');
      }
    }, 1200);
  }

  // Die 1920×1080-Bühnen in ihre Rahmen skalieren (wie fit() in views/overlay.js). Gilt für
  // beide Vorschauen und auch für den Vollbild-Rahmen, der nicht 16:9 sein muss.
  function passeBuehnenAn() {
    backdrop.querySelectorAll('.gfx-buehne').forEach((frame) => {
      const stage = frame.querySelector('[data-stage]');
      if (!stage) return;
      const breite = frame.clientWidth || frame.offsetWidth || 0;
      const hoehe = frame.clientHeight || frame.offsetHeight || 0;
      if (!breite || !hoehe) return;
      const skala = Math.min(breite / STAGE_W, hoehe / STAGE_H);
      stage.style.transform = `translate(-50%, -50%) scale(${skala})`;
    });
  }

  // Ein Takt für beide mitlaufenden Vorschauen — gemalt wird nur der offene Reiter.
  function vorschauTakt(an) {
    clearInterval(vorschauTimer);
    vorschauTimer = null;
    if (!an) return;
    vorschauTimer = setInterval(() => {
      if (!lebt) return;
      if (reiter === 'stream') malStream();
      else if (reiter === 'beamer') malBeamer();
    }, STREAM_POLL_MS);
  }

  // Nach dem Wechsel in/aus dem Vollbild hat der Rahmen eine andere Größe — Bühne neu
  // einpassen (erst nach dem Layout-Schritt).
  function aufVollbild() {
    requestAnimationFrame(passeBuehnenAn);
  }

  function setzeReiter(id) {
    reiter = (id === 'stream' || id === 'beamer' || id === 'spieler') ? id : 'grafik';
    backdrop.querySelectorAll('[data-gfx-tab]').forEach((b) => {
      const an = b.dataset.gfxTab === reiter;
      b.classList.toggle('is-on', an);
      b.setAttribute('aria-selected', String(an));
    });
    backdrop.querySelectorAll('.gfx-pane').forEach((p) => {
      p.hidden = p.dataset.pane !== reiter;
    });
    if (reiter === 'stream') baueStream();
    else if (reiter === 'beamer') baueBeamer();
    // Das Spieler-Bild erst beim ersten Öffnen zeichnen — es kostet ein paar hundert
    // Textausgaben, die niemand braucht, der nur die Ergebnis-Grafik teilen will.
    else if (reiter === 'spieler' && !spGezeichnet) zeichneSpieler();
    // Nur Livestream und Beamer laufen mit; das Spieler-Bild ist wie die Ergebnis-Grafik
    // ein Schnappschuss und wird über das ↻ aktualisiert.
    vorschauTakt(reiter === 'stream' || reiter === 'beamer');
  }

  // ── Bedienelemente ─────────────────────────────────────────────────────────
  function syncUi() {
    backdrop.querySelectorAll('.erf-seg-btn[data-gfx]').forEach((b) => {
      const an = opts[b.dataset.gfx] === b.dataset.wert;
      b.classList.toggle('is-on', an);
      b.setAttribute('aria-pressed', String(an));
    });
    SCHALTER.forEach(([id, , hinweis, bedingung, gesperrtText]) => {
      const btn = backdrop.querySelector(`.erf-switch[data-gfx="${id}"]`);
      if (!btn) return;
      const moeglich = !bedingung || !!modell[bedingung];
      btn.classList.toggle('is-on', !!opts[id]);
      btn.setAttribute('aria-checked', String(!!opts[id]));
      btn.disabled = !moeglich;
      const row = backdrop.querySelector(`[data-row="${id}"]`);
      if (row) row.classList.toggle('is-gesperrt', !moeglich);
      const hint = backdrop.querySelector(`[data-hint="${id}"]`);
      if (hint) hint.textContent = moeglich ? hinweis : gesperrtText;
    });
  }

  // Nur die dauerhaften Optionen sichern — Titel/Untertitel liegen getrennt je Spiel
  // (merkeTexte unten), sonst schlüge der Titel eines Wettkampfs beim nächsten durch.
  // ACHTUNG: saveSettings mischt flach, `grafik` wird also komplett ersetzt.
  function merken() {
    saveSettings({ grafik: { ...opts } });
  }

  // Titel/Untertitel je Quelle merken (entprellt — sonst ein Schreibvorgang je Tastendruck).
  function merkeTexte() {
    if (!modell.id) return;
    saveSettings({ grafikTexte: merkeGrafikTexte(getSettings(), modell.id, { titel, untertitel }) });
  }

  function planeTextMerken() {
    clearTimeout(textTimer);
    textTimer = setTimeout(() => { if (lebt) merkeTexte(); }, 400);
  }

  function setOption(id, wert) {
    opts = normalisiereOptionen({ ...opts, [id]: wert }, modell);
    merken();
    syncUi();
    zeichne();
  }

  // Frischen Spielstand holen. Titel/Untertitel bleiben stehen — sie können vom Nutzer
  // bearbeitet sein und sollen nicht unter der Hand zurückspringen.
  function aktualisieren() {
    roh = holeRoh();
    modell = grafikModell(roh);
    opts = normalisiereOptionen(opts, modell);
    ladeBilder();
    syncUi();
    zeichne();
    fuelleSpielerWahl();
    if (reiter === 'stream') baueStream();
    else if (reiter === 'beamer') baueBeamer();
    else if (reiter === 'spieler') zeichneSpieler();
  }

  // ── Ausgabe ────────────────────────────────────────────────────────────────
  function herunterladen(datei) {
    const url = URL.createObjectURL(datei);
    const a = document.createElement('a');
    if (!('download' in a)) { window.open(url, '_blank'); setTimeout(() => URL.revokeObjectURL(url), 60000); return; }
    a.href = url;
    a.download = datei.name;
    a.style.display = 'none';
    document.body.appendChild(a);
    a.click();
    // Erst nach dem Klick aufräumen — Safari braucht den Link noch einen Tick lang.
    setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 1000);
  }

  async function teilen(datei, name) {
    if (!datei) return;
    if (navigator.share && navigator.canShare && navigator.canShare({ files: [datei] })) {
      try {
        await navigator.share({ files: [datei], title: name || 'Ergebnis' });
        return;
      } catch (e) {
        if (e && e.name === 'AbortError') return; // Nutzer hat abgebrochen
      }
    }
    herunterladen(datei); // kein Teilen möglich (Desktop, altes iOS) -> Datei speichern
  }

  // ── Lebenszyklus ───────────────────────────────────────────────────────────
  function schliessen() {
    if (!lebt) return;
    // Noch nicht gesichertes Getipptes festhalten, bevor alles abgeräumt wird.
    clearTimeout(textTimer);
    merkeTexte();
    clearTimeout(spTextTimer);
    merkeSpielerTitel();
    lebt = false;
    offen = null;
    vorschauTakt(false);
    // Ein offenes Vollbild gehört zum Panel — mit ihm verschwinden.
    if (document.fullscreenElement && backdrop.contains(document.fullscreenElement)) {
      try { document.exitFullscreen(); } catch (e) { /* egal */ }
    }
    window.removeEventListener(UNMOUNT_EVENT, schliessen);
    window.removeEventListener('popstate', aufPopstate);
    window.removeEventListener('resize', passeBuehnenAn);
    document.removeEventListener('fullscreenchange', aufVollbild);
    document.removeEventListener('webkitfullscreenchange', aufVollbild);
    document.removeEventListener('keydown', aufTaste);
    letzteDatei = null;
    spDatei = null;
    canvas.width = 0;
    canvas.height = 0;
    spCanvas.width = 0;
    spCanvas.height = 0;
    backdrop.remove();
    if (historyEintrag) { historyEintrag = false; history.back(); }
  }

  function aufPopstate() {
    historyEintrag = false; // der Eintrag ist bereits weg — kein zusätzliches history.back()
    schliessen();
  }

  function aufTaste(e) {
    // Im Vollbild beendet Escape zuerst das Vollbild — das Panel darf dabei nicht mit
    // zugehen, sonst ist die Tafel samt Einstellungen weg.
    if (document.fullscreenElement && backdrop.contains(document.fullscreenElement)) return;
    if (e.key === 'Escape') { e.preventDefault(); schliessen(); }
  }

  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) { schliessen(); return; }
    const tab = e.target.closest('[data-gfx-tab]');
    if (tab) { setzeReiter(tab.dataset.gfxTab); return; }
    // Der Spieler-Reiter führt seinen eigenen Satz Optionen (data-sgfx) — sonst schaltete
    // ein Klick dort die Ergebnis-Grafik mit um.
    const sp = e.target.closest('[data-sgfx]');
    if (sp) {
      if (sp.disabled) return;
      const sid = sp.dataset.sgfx;
      if (sid === 'share') teilen(spDatei, (spModell && spModell.name) || 'Ergebnis');
      else if (sid === 'download') { if (spDatei) herunterladen(spDatei); }
      else if (sp.dataset.wert !== undefined) setSpielerOption(sid, sp.dataset.wert);
      else setSpielerOption(sid, !spOpts[sid]);
      return;
    }
    const el = e.target.closest('[data-gfx]');
    if (!el || el.disabled) return;
    const id = el.dataset.gfx;
    if (id === 'close') schliessen();
    else if (id === 'refresh') aktualisieren();
    else if (id === 'share') teilen(letzteDatei, titel || 'Ergebnis');
    else if (id === 'download') { if (letzteDatei) herunterladen(letzteDatei); }
    else if (id === 'beamer-voll') vollbild();
    else if (el.dataset.wert !== undefined) setOption(id, el.dataset.wert);
    else setOption(id, !opts[id]);
  });

  // Titel und Untertitel stehen auch unter dem Namen im Spieler-Bild — aber nur neu zeichnen,
  // wenn dieser Reiter gerade offen ist (sonst je Tastendruck ein ganzes Wurfraster).
  titelEl.addEventListener('input', () => {
    titel = titelEl.value; planeTextMerken(); zeichne();
    if (reiter === 'spieler') zeichneSpieler();
  });
  untertitelEl.addEventListener('input', () => {
    untertitel = untertitelEl.value; planeTextMerken(); zeichne();
    if (reiter === 'spieler') zeichneSpieler();
  });
  spWahlEl.addEventListener('change', () => { waehleSpieler(spWahlEl.value); zeichneSpieler(); });
  spTitelEl.addEventListener('input', () => {
    spTitel = spTitelEl.value;
    planeSpielerTitelMerken();
    zeichneSpieler();
  });
  spUeberEl.addEventListener('input', () => {
    spUeber = spUeberEl.value;
    planeSpielerTitelMerken();
    zeichneSpieler();
  });

  window.addEventListener(UNMOUNT_EVENT, schliessen);
  window.addEventListener('popstate', aufPopstate);
  window.addEventListener('resize', passeBuehnenAn);
  document.addEventListener('fullscreenchange', aufVollbild);
  document.addEventListener('webkitfullscreenchange', aufVollbild);
  document.addEventListener('keydown', aufTaste);
  // Eigener History-Eintrag, damit die Zurück-Geste das Panel schließt statt die Seite zu
  // verlassen. Der Hash bleibt gleich -> kein hashchange, der Router rendert nicht neu.
  try { history.pushState({ gfx: 1 }, '', location.href); historyEintrag = true; } catch (e) { /* egal */ }

  syncUi();
  zeichne();
  ladeBilder();
  fuelleSpielerWahl();
  syncSpielerUi();
  // Erst mit geladenen Schriften stimmt die Textmessung (und damit die Namenskürzung).
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => {
    if (!lebt) return;
    zeichne();
    if (reiter === 'spieler') zeichneSpieler();
  });

  offen = { schliessen };
  return { schliessen };
}
