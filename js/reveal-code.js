// Verdeckt anzeigbarer Code (z. B. der Eingabe-Code eines geteilten Spiels/Wettkampfs):
// standardmäßig maskiert (••••••), per Klick 10 s im Klartext lesbar, danach automatisch
// wieder verdeckt. Ein zweiter Klick verdeckt sofort. Der Aufdeck-Zustand überlebt Re-Renders
// (Polling/Realtime), solange derselbe Code danach erneut per wireRevealCodes() verdrahtet wird.

import { esc } from './util.js';

const REVEAL_MS = 10000;
const revealedUntil = new Map(); // Code -> Ablauf-Timestamp (ms)

function mask(len) { return '•'.repeat(Math.max(4, len || 6)); }

// HTML eines verdeckbaren Codes. `code` = Klartext. Fällt bei leerem Code auf „—" zurück
// (dann kein Aufdecken).
export function revealCodeHtml(code) {
  const c = String(code || '');
  if (!c) return `<span class="erf-share-code">—</span>`;
  return `<button type="button" class="reveal-code" data-reveal-code="${esc(c)}"
      aria-label="Code anzeigen – antippen zum Aufdecken">
      <span class="reveal-code-text">${esc(mask(c.length))}</span>
      <span class="reveal-code-hint">👁 zeigen</span>
    </button>`;
}

// Verdrahtet alle verdeckbaren Codes unter `root`. Nach jedem Re-Render erneut aufrufen.
export function wireRevealCodes(root) {
  root.querySelectorAll('.reveal-code[data-reveal-code]').forEach((btn) => {
    if (btn.dataset.revealWired) return; // idempotent, falls versehentlich doppelt verdrahtet
    btn.dataset.revealWired = '1';
    const code = btn.getAttribute('data-reveal-code');
    const textEl = btn.querySelector('.reveal-code-text');
    const hintEl = btn.querySelector('.reveal-code-hint');
    let timer = null;

    function hide() {
      clearTimeout(timer); timer = null;
      revealedUntil.delete(code);
      btn.classList.remove('is-open');
      textEl.textContent = mask(code.length);
      if (hintEl) hintEl.textContent = '👁 zeigen';
    }
    function show(msLeft) {
      const dur = msLeft != null ? msLeft : REVEAL_MS;
      revealedUntil.set(code, Date.now() + dur);
      btn.classList.add('is-open');
      textEl.textContent = code;
      if (hintEl) hintEl.textContent = 'verdeckt gleich';
      clearTimeout(timer);
      timer = setTimeout(hide, dur);
    }

    // Aufdeck-Zustand über Re-Renders hinweg wiederherstellen (Rest-Laufzeit).
    const until = revealedUntil.get(code);
    if (until && until > Date.now()) show(until - Date.now());
    else hide();

    btn.addEventListener('click', () => {
      if (btn.classList.contains('is-open')) hide();
      else show();
    });
  });
}
