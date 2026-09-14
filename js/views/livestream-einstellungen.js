// Livestream-Einstellungen: Team-Logos, Akzentfarben, Logo-Hintergrund und die OBS-URL eines
// Wettkampfs.
//
// EIN Ort dafür: der Reiter „Livestream" im Grafik-Panel (views/grafik-panel.js, 🖼 in der
// Kopfzeile). Dort stehen die Einstellungen neben der Overlay-Vorschau — man sieht also
// sofort, was man einstellt — und sind aus dem Wettkampf-Hub wie aus der laufenden Erfassung
// erreichbar, auch vom Handy. Im Hub gab es bis 2026-09-14 eine zweite, gleich aussehende
// Sektion; zwei Orte für dieselben Werte haben nur Verwirrung gestiftet.
//
// Die Bausteine sind absichtlich getrennt: `livestreamFelderHtml()` liefert nur das Markup,
// `wireLivestreamFelder()` hängt die Handler an einen beliebigen Container. Geschrieben wird
// direkt in den Wettkampf (store) und danach die Config zum Server gespiegelt — sonst sähe
// das Overlay (und jedes andere Gerät) das neue Logo nicht.

import { saveWettkampf } from '../store.js';
import { esc } from '../util.js';

const ACCENT_DEFAULT = '#f5a623';

// Overlay-URL des Wettkampfs (Hash-Route + ZUSCHAUER-Code) — von einer OBS-Browser-Quelle
// eingebunden. Nutzt bewusst den read-only Zuschauer-Code (nicht den Eingabe-Code): das Overlay
// macht ohnehin keine Eingaben, und so gibt selbst eine geleakte OBS-URL kein Eingaberecht.
// Braucht einen geteilten Wettkampf (Code), da das Overlay read-only per Code liest.
export function overlayUrl(wettkampf) {
  const base = location.origin + location.pathname;
  return `${base}#/overlay?code=${encodeURIComponent((wettkampf && wettkampf.zuschauerCode) || '')}`;
}

// Ist der Wettkampf geteilt (und damit für OBS erreichbar)?
export function overlayBereit(wettkampf) {
  return !!(wettkampf && wettkampf.linked && wettkampf.zuschauerCode);
}

// Bilddatei → verkleinerte Data-URL (PNG, längste Kante ≤ MAX). Klein genug, um im
// Wettkampf-config_json mitzureisen (kein Storage-Bucket nötig).
export function fileToLogo(file, MAX = 256) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, MAX / Math.max(img.width, img.height));
      const w = Math.round(img.width * scale);
      const h = Math.round(img.height * scale);
      const cv = document.createElement('canvas');
      cv.width = w; cv.height = h;
      cv.getContext('2d').drawImage(img, 0, 0, w, h);
      resolve(cv.toDataURL('image/png'));
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('Bild konnte nicht geladen werden')); };
    img.src = url;
  });
}

function accentOf(m) {
  return /^#[0-9a-fA-F]{6}$/.test((m && m.accent) || '') ? m.accent : ACCENT_DEFAULT;
}

// Standard-Akzentfarben zum Antippen. Der Farbwähler daneben bleibt — das hier sind die
// Vorschläge, die erfahrungsgemäß gebraucht werden, ohne im Farbkreis zu suchen.
//
// Ausgewählt nach LESBARKEIT: die Akzentfarbe trägt im Overlay Mannschaftsnamen, Punkte und
// Bahn-Ränder — auf dunklem Grund (#1a1e27) und in der Ergebnis-Grafik über einem Foto. Jeder
// Ton hier hat gegen den dunklen Overlay-Grund mindestens 6:1 Kontrast (WCAG AA wäre 4.5:1);
// dunkle, satte Töne (Schwarz, Marineblau, Dunkelrot, Braun) fehlen deshalb bewusst — sie
// „saufen ab". Für Vereine in solchen Farben sind Silber/Grau und Hellblau die hellen
// Vertreter; wer den dunklen Ton trotzdem will, nimmt den Farbwähler.
//
// Reihenfolge: Kegel-Gold zuerst (das ist der Standard, den eine Mannschaft ohne eigene Farbe
// trägt), danach warm → kühl → neutral.
export const AKZENT_PRESETS = [
  { hex: '#F5A623', name: 'Kegel-Gold (Standard)' },
  { hex: '#FFD84D', name: 'Gelb' },
  { hex: '#FF8C42', name: 'Orange' },
  { hex: '#FF6B6B', name: 'Rot' },
  { hex: '#FF7FD1', name: 'Pink' },
  { hex: '#B49BFF', name: 'Flieder' },
  { hex: '#4DA3FF', name: 'Hellblau' },
  { hex: '#3DDCC8', name: 'Türkis' },
  { hex: '#6FD661', name: 'Grün' },
  { hex: '#C7CFDB', name: 'Silber' },
  { hex: '#EDF1F7', name: 'Weiß' },
];

// Die Farbtupfer einer Mannschaft. Die Hex-Werte stammen aus der Liste oben (nicht aus
// Nutzereingaben) und dürfen deshalb in ein inline `style`.
function presetsHtml(m) {
  const aktiv = accentOf(m).toLowerCase();
  const punkte = AKZENT_PRESETS.map(({ hex, name }) => `
    <button type="button" class="ov-swatch${hex.toLowerCase() === aktiv ? ' is-on' : ''}"
      style="background:${hex}" data-accent-preset="${esc(m.id)}" data-hex="${hex}"
      title="${esc(name)}" aria-label="Akzentfarbe ${esc(name)}"
      aria-pressed="${hex.toLowerCase() === aktiv ? 'true' : 'false'}"></button>`).join('');
  return `<div class="ov-swatches" role="group" aria-label="Standard-Akzentfarben">${punkte}</div>`;
}

// Logo-/Farb-Felder der (max. zwei) Mannschaften.
export function livestreamFelderHtml(wettkampf) {
  const teams = ((wettkampf && wettkampf.mannschaften) || []).slice(0, 2);
  const felder = teams.map((m) => `
    <div class="ov-logo-field">
      <div class="ov-logo-prev${m.logoBg === 'light' ? ' is-light' : ''}">${m.logo ? `<img src="${esc(m.logo)}" alt="">` : '<span>🎳</span>'}</div>
      <div class="ov-logo-meta">
        <span class="erf-setting-label">${esc(m.name)}</span>
        <label class="btn-mini ov-logo-btn">${m.logo ? 'Logo ändern' : 'Logo wählen'}
          <input type="file" accept="image/*" hidden data-logo="${esc(m.id)}">
        </label>
        ${m.logo ? `<button type="button" class="link-btn" data-logo-del="${esc(m.id)}">entfernen</button>` : ''}
        <label class="ov-opt">Akzentfarbe
          <input type="color" class="ov-accent-input" value="${accentOf(m)}" data-accent="${esc(m.id)}">
        </label>
        ${presetsHtml(m)}
        <label class="ov-opt">Logo-Hintergrund
          <select class="ov-logobg-input" data-logobg="${esc(m.id)}">
            <option value="dark"${m.logoBg === 'light' ? '' : ' selected'}>Dunkel</option>
            <option value="light"${m.logoBg === 'light' ? ' selected' : ''}>Hell</option>
          </select>
        </label>
      </div>
    </div>`).join('');
  return `<div class="ov-logo-fields">${felder || '<p class="field-hint">Keine Mannschaften.</p>'}</div>`;
}

// URL-Zeile für OBS — erst nach dem Teilen, sonst ein Hinweis darauf.
export function livestreamUrlHtml(wettkampf) {
  if (!overlayBereit(wettkampf)) {
    return `<p class="field-hint">Zuerst den <b>Wettkampf teilen</b> — dann erscheint hier die Overlay-URL für OBS.</p>`;
  }
  const url = esc(overlayUrl(wettkampf));
  return `<div class="ov-url-row">
      <input class="ov-url-input" type="text" readonly value="${url}" data-overlay-url aria-label="Overlay-URL">
      <button type="button" class="btn-mini" data-action="copy-overlay">Kopieren</button>
      <a class="btn-mini" href="${url}" target="_blank" rel="noopener">Öffnen</a>
    </div>
    <p class="field-hint">In OBS als <b>Browser-Quelle</b> (1920×1080) mit dieser URL einbinden — transparenter Hintergrund, zeigt die Ergebnisse live.</p>`;
}

// Handler für alles oben Erzeugte an `container` hängen.
//   onChange()  — nach jeder Änderung (der Aufrufer rendert seine Ansicht neu)
//   onMsg(text) — Statuszeile; ohne Angabe wird [data-overlay-msg] im Container gefüllt
//   onPush(wk)  — Config zum Server spiegeln (der Aufrufer reicht seinen eigenen Weg herein)
export function wireLivestreamFelder(container, wettkampf, opts = {}) {
  if (!container || !wettkampf) return;
  const onChange = opts.onChange || (() => {});
  const setMsg = opts.onMsg || ((m) => {
    const el = container.querySelector('[data-overlay-msg]');
    if (el) el.textContent = m || '';
  });
  const push = opts.onPush || (() => {});

  const team = (id) => ((wettkampf.mannschaften || []).find((x) => x.id === id) || null);
  const speichern = () => { saveWettkampf(wettkampf); onChange(); push(wettkampf); };

  container.querySelectorAll('input[data-logo]').forEach((inp) =>
    inp.addEventListener('change', async () => {
      const file = inp.files && inp.files[0];
      if (!file) return;
      const m = team(inp.dataset.logo);
      if (!m) return;
      try {
        m.logo = await fileToLogo(file);
        speichern();
      } catch (e) { setMsg('Logo konnte nicht geladen werden.'); }
    }));

  container.querySelectorAll('[data-logo-del]').forEach((b) =>
    b.addEventListener('click', () => {
      const m = team(b.dataset.logoDel);
      if (!m) return;
      delete m.logo;
      speichern();
    }));

  // Akzentfarbe setzen — aus dem Farbwähler wie aus den Standardfarben. Der Default (Gold)
  // wird als FEHLENDES Feld gespeichert, damit alte Stände unverändert bleiben.
  const setzeAkzent = (teamId, hex) => {
    const m = team(teamId);
    if (!m || !/^#[0-9a-fA-F]{6}$/.test(hex || '')) return;
    if (hex.toLowerCase() === ACCENT_DEFAULT) delete m.accent; else m.accent = hex.toLowerCase();
    speichern();
  };

  // `change` = wenn der Farbwähler schließt, nicht bei jedem Zwischenwert.
  container.querySelectorAll('input[data-accent]').forEach((inp) =>
    inp.addEventListener('change', () => setzeAkzent(inp.dataset.accent, inp.value)));

  container.querySelectorAll('[data-accent-preset]').forEach((b) =>
    b.addEventListener('click', () => setzeAkzent(b.dataset.accentPreset, b.dataset.hex)));

  container.querySelectorAll('select[data-logobg]').forEach((sel) =>
    sel.addEventListener('change', () => {
      const m = team(sel.dataset.logobg);
      if (!m) return;
      if (sel.value === 'light') m.logoBg = 'light'; else delete m.logoBg;
      speichern();
    }));

  const copy = container.querySelector('[data-action="copy-overlay"]');
  if (copy) copy.addEventListener('click', async () => {
    const url = overlayUrl(wettkampf);
    try { await navigator.clipboard.writeText(url); setMsg('URL kopiert.'); }
    catch (e) {
      const inp = container.querySelector('[data-overlay-url]');
      if (inp) { inp.focus(); inp.select(); }
      setMsg('Bitte manuell kopieren (Strg+C).');
    }
  });
}
