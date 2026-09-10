// Der Papierkorb in den Statistiken — was ich aus meinem Konto entfernt habe, für zwei
// Wochen mit einem Tippen zurückholbar.
//
// Er steht bewusst UNTEN auf der Statistik-Seite und nur dann, wenn tatsächlich etwas darin
// liegt: er ist ein Sicherheitsnetz, keine zweite Historie. Die Einträge sehen deshalb auch
// nicht aus wie Spielkarten (keine Ergebnisse, nicht anklickbar) — es gibt genau eine
// Handlung, und die steht als Knopf daneben.
//
// Was Frist und Zusammenstellung angeht, entscheidet logic/papierkorb.js; das Zurückholen
// selbst macht backend/sync.js (Vermerk weg + gelöste Zuordnung zurück). Hier ist nur die
// Darstellung — und der eine Satz, der den häufigsten Irrtum ausräumt: nach 14 Tagen
// verschwindet der EINTRAG, nicht das Verbergen. Von selbst kommt nichts zurück.

import { esc, fehlerText } from '../util.js';
import { labelOf, iconOf } from '../logic/spielarten.js';
import { PAPIERKORB_HINWEIS } from '../logic/papierkorb.js';

function fmtTag(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}.${d.getFullYear()}`;
}

// Woran erkennt man den Eintrag wieder? Bei einem Wettkampf am Namen, bei einem Einzelspiel
// an Spielart und Aufstellung. Nach Spielende stehen dort Anzeigenamen bzw. Platzhalter
// (Anonymisierung) — das genügt zum Wiedererkennen und verrät nichts, was nicht ohnehin
// in der Datenbank steht.
function titelVon(e) {
  if (e.art === 'wettkampf') {
    return `🏆 ${esc(e.objekt.name || 'Wettkampf')}`;
  }
  const cfg = e.objekt.config_json || {};
  const art = e.objekt.spielart || 'sportkegler-wk';
  const namen = (cfg.spielerListe || []).map((p) => (p && p.name) || '').filter(Boolean);
  const kurz = namen.slice(0, 3).join(', ') + (namen.length > 3 ? ` +${namen.length - 3}` : '');
  return `${iconOf(art)} ${esc(labelOf(art))}${kurz ? ` <small class="rank-team">${esc(kurz)}</small>` : ''}`;
}

function gespieltAm(e) {
  const o = e.objekt;
  return fmtTag(e.art === 'wettkampf' ? (o.datum || o.aktualisiert_am) : o.erstellt_am);
}

function zeile(e) {
  const rest = e.restTage === 1 ? 'noch 1 Tag' : `noch ${e.restTage} Tage`;
  const meta = [
    gespieltAm(e) ? `gespielt am ${gespieltAm(e)}` : '',
    `entfernt am ${fmtTag(e.verborgenAm)}`,
    rest,
  ].filter(Boolean).join(' · ');
  return `
    <div class="pk-row" data-pk-art="${esc(e.art)}" data-pk-id="${esc(e.id)}">
      <div class="pk-text">
        <div class="pk-titel">${titelVon(e)}</div>
        <div class="pk-meta">${esc(meta)}</div>
      </div>
      <button type="button" class="btn-mini pk-back">Zurückholen</button>
    </div>`;
}

// Das Markup zu einer fertigen Eintragsliste (logic/papierkorb.js). Getrennt vom Laden,
// damit sich die Darstellung ohne Konto und Netz ansehen laesst.
export function papierkorbHtml(eintraege) {
  if (!eintraege || !eintraege.length) return '';
  return `
    <h2 class="section-label">🗑 Papierkorb</h2>
    <div class="pk-box">
      <p class="field-hint pk-hint">${esc(PAPIERKORB_HINWEIS)}</p>
      ${eintraege.map(zeile).join('')}
    </div>`;
}

// Den Papierkorb in `el` aufbauen. `onDone` wird nach einem erfolgreichen Zurückholen
// gerufen (die Statistik-Seite lädt sich dann neu, damit der Eintrag wieder auftaucht).
// Ist nichts da, bleibt der Bereich leer — ein leerer Papierkorb braucht keine Überschrift.
export async function renderPapierkorb(el, { onDone = () => {} } = {}) {
  if (!el) return;
  let eintraege = [];
  try {
    const sync = await import('../backend/sync.js');
    eintraege = await sync.pullPapierkorb();
  } catch (e) {
    el.innerHTML = '';
    return;
  }
  el.innerHTML = papierkorbHtml(eintraege);
  if (!eintraege.length) return;

  el.querySelectorAll('.pk-back').forEach((b) => {
    b.addEventListener('click', async () => {
      const row = b.closest('.pk-row');
      if (!row) return;
      b.disabled = true;
      b.textContent = '…';
      try {
        const sync = await import('../backend/sync.js');
        await sync.papierkorbZurueckholen(row.dataset.pkArt, row.dataset.pkId);
        onDone();
      } catch (e) {
        b.disabled = false;
        b.textContent = 'Zurückholen';
        window.alert(`Zurückholen ging gerade nicht: ${fehlerText(e)}`);
      }
    });
  });
}
