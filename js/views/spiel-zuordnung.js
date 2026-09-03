// „Das war ich" — die Zuordnung eines EINZELSPIELS (Sportkegeln-Training) zum eigenen Profil.
//
// Ein Spieler ist in diesem Datenmodell nur eine Position in einem Spiel (siehe
// logic/spieler-identitaet.js). Damit ein Ergebnis in der eigenen Konto-Statistik landet,
// muss genau EINE Position als „das bin ich" markiert sein. Dafür gibt es drei Momente:
//
//   • beim Setup      — der ★ neben dem Spieler (setup-wk.js),
//   • im Wettkampf    — die Aufstellung im Hub (wettkampf-hub.js),
//   • nachträglich    — hier, an der Karte in den Statistiken.
//
// Der dritte Weg fehlte für Einzelspiele: wer den ★ im Setup vergessen hatte, kam an seine
// eigene Trainings-Statistik nicht mehr heran. Diese Datei ist die eine Stelle, an der das
// nachgeholt (und wieder gelöst) wird — für lokale wie für ferngeladene Spiele.
//
// Was dabei geschrieben wird, hängt davon ab, wie weit das Spiel gereist ist:
//   game.ichIndex             — immer; die lokale Wahrheit, die beim Teilen/Spielende mitgeht
//   spiel_spieler.profil_id   — sobald das Spiel geteilt ist (RPC spieler_bin_ich)
//   spiel_ergebnis.profil_id  — sobald es einen Ergebnis-Snapshot gibt (RPC ergebnis_mir_zuordnen
//                               bzw. meine_ergebnisse_beanspruchen für die Zeilen, die wir
//                               hier gar nicht geladen haben)
// Die RPCs schreiben ausschließlich das eigene Konto und lehnen fremd belegte Zeilen ab.

import { getGame, saveGame } from '../store.js';
import { esc } from '../util.js';
import { ergebnisQuelle, QUELLE_LABEL } from '../logic/historie.js';

const spielerListe = (game) => ((game && game.config && game.config.spielerListe) || []);
const nameOf = (game, i) => {
  const sp = spielerListe(game)[i];
  return (sp && sp.name && sp.name.trim()) || `Spieler ${i + 1}`;
};

// Welche Position gehört MIR in diesem Spiel? Zwei Quellen, serverseitig zuerst:
// spiel_spieler.profil_id gilt geräteübergreifend, game.ichIndex ist die lokale Markierung
// (auch für Spiele, die nie geteilt wurden). null = keine.
export function ichPosVon(game, konto = null) {
  const n = spielerListe(game).length;
  const owners = (game && game.spielerOwners) || {};
  if (konto) {
    const pos = Object.keys(owners).map(Number)
      .find((p) => owners[p] && owners[p].profil === konto);
    if (pos != null && pos < n) return pos;
  }
  const i = game && game.ichIndex;
  return Number.isInteger(i) && i >= 0 && i < n ? i : null;
}

// Die Ergebniszeile zu einer Position (über die Aufstellungs-id) — oder null.
function ergebnisZuPos(game, pos, ergebnisse) {
  const owner = ((game && game.spielerOwners) || {})[pos];
  if (!owner || !owner.id) return null;
  return (ergebnisse || []).find((r) => r.spieler_id === owner.id) || null;
}

// Gehört eine Position bereits einem ANDEREN Konto? Dann taucht sie in der Auswahl nicht auf —
// die RPC würde sie ohnehin ablehnen.
function fremdBelegt(game, pos, konto) {
  const owner = ((game && game.spielerOwners) || {})[pos];
  return !!(owner && owner.profil && konto && owner.profil !== konto);
}

// Der Zuordnungs-Block einer Spielkarte. Drei Zustände:
//   • über die LizenzID zugeordnet -> nur der Hinweis (lösen wäre sinnlos, die LizenzID
//     findet das Ergebnis beim nächsten Laden wieder),
//   • ausdrücklich zugeordnet      -> Hinweis + „Zuordnung lösen",
//   • noch offen                   -> Auswahl + „Das war ich".
// `ichPos` überschreibt die Erkennung (die Statistik kennt die eigene Position bei
// ferngeladenen Spielen aus der Ergebniszeile). Leerer String = kein Block.
export function zuordnungBlock(game, {
  konto = null, ergebnisse = [], meinPass = null, ichPos = undefined,
} = {}) {
  const liste = spielerListe(game);
  if (!liste.length) return '';
  const id = esc(game.id);
  const ich = ichPos === undefined ? ichPosVon(game, konto) : ichPos;

  if (ich != null) {
    const row = ergebnisZuPos(game, ich, ergebnisse);
    const quelle = row ? ergebnisQuelle(row, meinPass) : 'zuordnung';
    const loesbar = quelle !== 'lizenz';
    return `
      <div class="stat-zuordnung">
        <p class="field-hint">${QUELLE_LABEL[quelle]}: <strong>${esc(nameOf(game, ich))}</strong>${
          quelle === 'lizenz' ? ' — deine LizenzID steht in der Aufstellung.' : ''}</p>
        ${loesbar ? `<button type="button" class="btn-mini" data-zu-clear="${id}">Zuordnung lösen</button>` : ''}
      </div>`;
  }

  const opts = liste.map((sp, i) => (fremdBelegt(game, i, konto) ? ''
    : `<option value="${i}">${esc(nameOf(game, i))}</option>`)).filter(Boolean).join('');
  if (!opts) return '';
  return `
    <div class="stat-zuordnung">
      <label class="field-hint" for="zu-${id}">★ Warst du dabei? Ordne dein Ergebnis zu:</label>
      <div class="field-row">
        <select class="select-full sm" id="zu-${id}" data-zu-select="${id}">
          <option value="">— auswählen —</option>${opts}
        </select>
        <button type="button" class="btn-mini" data-zu-set="${id}">Das war ich</button>
      </div>
      ${game.remoteId ? '' : '<p class="field-hint">Dieses Spiel liegt nur auf diesem Gerät — '
        + 'in deine Konto-Statistik zählt es, sobald du es teilst.</p>'}
    </div>`;
}

// Die Markierung setzen. Lokal IMMER (auch offline und für nie geteilte Spiele), serverseitig
// zusätzlich, sobald das Spiel verknüpft ist. Rückgabe: { ok, belegt?, fehler? }.
async function zuordnen(game, pos, ergebnisse, konto) {
  merkeLokal(game, pos, konto);
  if (!game.remoteId) return { ok: true };
  try {
    const sync = await import('../backend/sync.js');
    const owner = ((game.spielerOwners) || {})[pos];
    if (owner && owner.id && !(await sync.spielerBinIch(owner.id))) return { ok: false, belegt: true };
    const row = ergebnisZuPos(game, pos, ergebnisse);
    if (row && !row.profil_id) {
      if (!(await sync.ergebnisMirZuordnen(row.id))) return { ok: false, belegt: true };
    } else if (!row) {
      // Die Ergebniszeile ist hier nicht geladen (oder es gibt noch keine): die RPC holt
      // alle freien Zeilen, deren Aufstellung ich markiert habe — auch die von morgen.
      await sync.meineErgebnisseBeanspruchen();
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, fehler: e };
  }
}

// Die Markierung wieder lösen — in derselben Reihenfolge rückwärts.
async function loesen(game, pos, ergebnisse, konto) {
  merkeLokal(game, null, konto);
  if (!game.remoteId || pos == null) return { ok: true };
  try {
    const sync = await import('../backend/sync.js');
    const owner = ((game.spielerOwners) || {})[pos];
    if (owner && owner.id) await sync.spielerBinIchLoesen(owner.id);
    const row = ergebnisZuPos(game, pos, ergebnisse);
    if (row) await sync.ergebnisZuordnungLoesen(row.id);
    return { ok: true };
  } catch (e) {
    return { ok: false, fehler: e };
  }
}

// Lokale Markierung schreiben: am übergebenen Objekt (die Ansicht zeigt sofort das Richtige)
// und, wenn das Spiel lokal liegt, auch im Speicher. Ein nur ferngeladenes Spiel wird dabei
// bewusst NICHT lokal angelegt — es gehört in die Historie, nicht in den Gerätespeicher.
function merkeLokal(game, pos, konto) {
  game.ichIndex = pos;
  setzeProfil(game.spielerOwners, pos, konto);
  const lokal = getGame(game.id);
  if (!lokal) return;
  lokal.ichIndex = pos;
  setzeProfil(lokal.spielerOwners, pos, konto);
  saveGame(lokal);
}

// Die Besitz-Landkarte nachziehen, damit die Karte sofort das Richtige zeigt: meine
// Position bekommt mein Konto, eine frühere Markierung desselben Kontos fällt weg.
function setzeProfil(owners, pos, konto) {
  if (!owners) return;
  Object.keys(owners).forEach((p) => {
    if (!owners[p]) return;
    if (Number(p) === pos) owners[p] = { ...owners[p], profil: konto || owners[p].profil || null };
    else if (konto && owners[p].profil === konto) owners[p] = { ...owners[p], profil: null };
  });
}

// Die Knöpfe eines Containers verdrahten (mehrfach aufrufbar — schon verdrahtete bleiben).
//   gameById(id)      -> das Spielobjekt zur Karte (lokal oder ferngeladen)
//   ergebnisseFor(g)  -> die bekannten Ergebniszeilen dieses Spiels (optional)
//   onChanged()       -> neu aufbauen, nachdem sich etwas geändert hat
//   melden(text)      -> Rückmeldung an den Nutzer (Vorgabe: window.alert)
export function wireZuordnung(container, {
  gameById, ergebnisseFor = () => [], konto = null,
  onChanged = () => {}, melden = (t) => window.alert(t),
} = {}) {
  if (!container || typeof gameById !== 'function') return;
  container.querySelectorAll('[data-zu-set], [data-zu-clear]').forEach((btn) => {
    if (btn.dataset.wired) return;
    btn.dataset.wired = '1';
    btn.addEventListener('click', async (e) => {
      e.stopPropagation(); // die Karte darf davon nicht aufgehen
      const setzen = 'zuSet' in btn.dataset;
      const gameId = setzen ? btn.dataset.zuSet : btn.dataset.zuClear;
      const game = gameById(gameId);
      if (!game) return;
      const ergebnisse = ergebnisseFor(game) || [];
      btn.disabled = true;
      try {
        let res;
        if (setzen) {
          const sel = container.querySelector(`[data-zu-select="${CSS.escape(gameId)}"]`);
          const pos = sel && sel.value !== '' ? parseInt(sel.value, 10) : null;
          if (pos == null || Number.isNaN(pos)) return;
          res = await zuordnen(game, pos, ergebnisse, konto);
        } else {
          res = await loesen(game, ichPosVon(game, konto), ergebnisse, konto);
        }
        if (res.belegt) melden('Diese Position ist bereits einem anderen Konto zugeordnet.');
        else if (res.fehler) {
          melden('Die Zuordnung konnte nicht übertragen werden — bist du online?'
            + ' Auf diesem Gerät ist sie gespeichert.');
        }
        onChanged();
      } finally { btn.disabled = false; }
    });
  });
}
