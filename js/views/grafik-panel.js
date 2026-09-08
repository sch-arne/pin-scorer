// Grafik-Menü: Vorschau + Optionen der Ergebnis-Grafik, dazu Teilen und PNG-Speichern.
// Wird aus der Wurferfassung (views/spiel-laufend.js) und dem Wettkampf-Hub
// (views/wettkampf-hub.js) über den 🖼-Knopf in der Kopfzeile geöffnet.
//
// Das Panel hängt sich SELBST an document.body statt Teil eines View-Templates zu sein:
// spiel-laufend setzt bei jedem Wurf `root.innerHTML = template()` — eine Canvas darin wäre
// bei jeder Eingabe zerstört (Bitmap weg, Texteingabe verliert den Fokus). Der Preis ist,
// dass das Panel eine Navigation überleben würde; deshalb ist der UNMOUNT_EVENT-Listener
// hier Pflicht und nicht optional.
//
// Der Inhalt ist ein SCHNAPPSCHUSS: `datenFn()` wird beim Öffnen und beim ↻ aufgerufen, damit
// sich die Zahlen beim Konfigurieren nicht unter den Händen bewegen.

import { UNMOUNT_EVENT } from '../router.js';
import { getSettings, saveSettings } from '../store.js';
import {
  grafikModell, grafikOptionen, normalisiereOptionen, grafikDateiname,
} from '../logic/ergebnis-grafik.js';
import { FORMATE, zeichneGrafik } from '../logic/grafik-zeichnen.js';
import { esc } from '../util.js';

// Es gibt immer höchstens EIN Panel — ein zweiter Öffnen-Klick ersetzt das erste.
let offen = null;

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
  ['logos', 'Logos', 'Mannschaftslogos unter der Tabelle', 'hatLogos', 'Im Wettkampf-Hub unter „OBS-Overlay" hochladen.'],
  ['spaltenkoepfe', 'Spaltenköpfe', 'Kopfzeile über den Spalten', null, ''],
  ['kontur', 'Umrandung', 'Dunkler Rand um jede Schrift — hält den Text auf unruhigen Fotos lesbar', null, ''],
];

function segmentHtml(id, label, hinweis, werte) {
  const btns = werte.map(([w, t]) =>
    `<button type="button" class="erf-seg-btn" data-gfx="${id}" data-wert="${w}">${esc(t)}</button>`).join('');
  return `
    <div class="erf-setting-row">
      <div class="erf-setting-text">
        <span class="erf-setting-label">${esc(label)}</span>
        <span class="erf-setting-hint">${esc(hinweis)}</span>
      </div>
      <div class="erf-seg" role="group" aria-label="${esc(label)}">${btns}</div>
    </div>`;
}

function schalterHtml(id, label, hinweis) {
  return `
    <div class="erf-setting-row" data-row="${id}">
      <div class="erf-setting-text">
        <span class="erf-setting-label">${esc(label)}</span>
        <span class="erf-setting-hint" data-hint="${id}">${esc(hinweis)}</span>
      </div>
      <button type="button" class="erf-switch" role="switch" data-gfx="${id}" aria-label="${esc(label)}">
        <span class="erf-switch-knob"></span>
      </button>
    </div>`;
}

function panelHtml(titel, untertitel) {
  return `
    <div class="gfx-sheet" role="dialog" aria-modal="true" aria-label="Ergebnis-Grafik">
      <div class="erf-settings-head">
        <h2 class="erf-settings-title">🖼 Ergebnis-Grafik</h2>
        <span class="gfx-head-btns">
          <button type="button" class="icon-btn" data-gfx="refresh" aria-label="Stand aktualisieren" title="Aktuellen Spielstand holen">↻</button>
          <button type="button" class="icon-btn" data-gfx="close" aria-label="Schließen">✕</button>
        </span>
      </div>
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
    </div>`;
}

// Das Menü öffnen. `datenFn()` liefert die Rohdaten für grafikModell()
// ({ wettkampf, games } oder { game }) — bei jedem Aufruf frisch.
export function oeffneGrafikMenue({ datenFn }) {
  if (offen) offen.schliessen();
  let lebt = true;
  let historyEintrag = false;
  let letzteDatei = null;
  const bilder = {};

  let modell = holeModell();
  let opts = normalisiereOptionen(grafikOptionen(getSettings()), modell);
  let titel = modell.titel;
  let untertitel = modell.untertitel;

  function holeModell() {
    try { return grafikModell(datenFn()); } catch (e) { return grafikModell(null); }
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
  function planeBlob() {
    letzteDatei = null;
    shareBtn.disabled = true;
    downloadBtn.disabled = true;
    try {
      canvas.toBlob((blob) => {
        if (!lebt || !blob) return;
        letzteDatei = new File([blob], grafikDateiname({ ...modell, titel }), { type: 'image/png' });
        shareBtn.disabled = false;
        downloadBtn.disabled = false;
      }, 'image/png');
    } catch (e) {
      metaEl.textContent = 'Das Bild konnte nicht erzeugt werden.';
    }
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

  // Nur die dauerhaften Optionen sichern — Titel/Untertitel gehören zum konkreten Spiel und
  // würden beim nächsten Wettkampf den falschen Namen vorschlagen.
  // ACHTUNG: saveSettings mischt flach, `grafik` wird also komplett ersetzt.
  function merken() {
    saveSettings({ grafik: { ...opts } });
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
    modell = holeModell();
    opts = normalisiereOptionen(opts, modell);
    ladeBilder();
    syncUi();
    zeichne();
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

  async function teilen() {
    const datei = letzteDatei;
    if (!datei) return;
    if (navigator.share && navigator.canShare && navigator.canShare({ files: [datei] })) {
      try {
        await navigator.share({ files: [datei], title: titel || 'Ergebnis' });
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
    lebt = false;
    offen = null;
    window.removeEventListener(UNMOUNT_EVENT, schliessen);
    window.removeEventListener('popstate', aufPopstate);
    document.removeEventListener('keydown', aufTaste);
    letzteDatei = null;
    canvas.width = 0;
    canvas.height = 0;
    backdrop.remove();
    if (historyEintrag) { historyEintrag = false; history.back(); }
  }

  function aufPopstate() {
    historyEintrag = false; // der Eintrag ist bereits weg — kein zusätzliches history.back()
    schliessen();
  }

  function aufTaste(e) {
    if (e.key === 'Escape') { e.preventDefault(); schliessen(); }
  }

  backdrop.addEventListener('click', (e) => {
    if (e.target === backdrop) { schliessen(); return; }
    const el = e.target.closest('[data-gfx]');
    if (!el || el.disabled) return;
    const id = el.dataset.gfx;
    if (id === 'close') schliessen();
    else if (id === 'refresh') aktualisieren();
    else if (id === 'share') teilen();
    else if (id === 'download') { if (letzteDatei) herunterladen(letzteDatei); }
    else if (el.dataset.wert !== undefined) setOption(id, el.dataset.wert);
    else setOption(id, !opts[id]);
  });

  titelEl.addEventListener('input', () => { titel = titelEl.value; zeichne(); });
  untertitelEl.addEventListener('input', () => { untertitel = untertitelEl.value; zeichne(); });

  window.addEventListener(UNMOUNT_EVENT, schliessen);
  window.addEventListener('popstate', aufPopstate);
  document.addEventListener('keydown', aufTaste);
  // Eigener History-Eintrag, damit die Zurück-Geste das Panel schließt statt die Seite zu
  // verlassen. Der Hash bleibt gleich -> kein hashchange, der Router rendert nicht neu.
  try { history.pushState({ gfx: 1 }, '', location.href); historyEintrag = true; } catch (e) { /* egal */ }

  syncUi();
  zeichne();
  ladeBilder();
  // Erst mit geladenen Schriften stimmt die Textmessung (und damit die Namenskürzung).
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { if (lebt) zeichne(); });

  offen = { schliessen };
  return { schliessen };
}
