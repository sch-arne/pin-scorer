// „Spiel beitreten": Beitritts-Code eines geteilten Spiels eingeben und dem Spiel
// mehrgeraetig beitreten. Laedt das Backend nur lazy (dynamic import), damit die
// local-first App ohne Verbindung unbeeintraechtigt bleibt.

import { navigate, currentQuery } from '../router.js';
import { saveGame, setActiveGame, saveWettkampf, setActiveWettkampf } from '../store.js';
import { setBruecke } from '../backend/sw-bruecke.js';

export function beitretenView() {
  const root = document.createElement('div');
  root.className = 'view view-page';
  root.innerHTML = `
    <header class="page-header">
      <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
      <h1 class="page-title">Spiel beitreten</h1>
    </header>
    <div class="join-body">
      <p class="join-hint">Gib den Beitritts-Code eines geteilten Spiels oder Wettkampfs ein. Den Code zeigt das erste Gerät unter ⚙ → Mehrgeräte (bzw. im Wettkampf unter „Teilen").</p>
      <input id="join-code" class="join-input" type="text" inputmode="latin" autocapitalize="characters"
             autocomplete="off" spellcheck="false" placeholder="z. B. AB12CD" maxlength="12" aria-label="Beitritts-Code" />
      <button type="button" id="join-go" class="erf-btn done join-go">Beitreten</button>
      <p id="join-msg" class="join-msg" role="status"></p>
    </div>`;

  const input = root.querySelector('#join-code');
  const btn = root.querySelector('#join-go');
  const msg = root.querySelector('#join-msg');

  input.addEventListener('input', () => {
    const pos = input.selectionStart;
    input.value = input.value.toUpperCase();
    input.setSelectionRange(pos, pos);
  });

  async function go() {
    const code = input.value.trim();
    if (!code) { msg.textContent = 'Bitte Code eingeben.'; return; }
    btn.disabled = true;
    msg.textContent = 'Verbinde …';
    try {
      const sync = await import('../backend/sync.js');
      // Ein Code kann zu einem Wettkampf ODER einem Einzelspiel gehören. Erst als
      // Wettkampf versuchen; schlägt das fehl (unbekannter Code), als Einzelspiel.
      try {
        const { wettkampf, games } = await sync.joinWettkampf(code);
        games.forEach((g) => saveGame(g));
        saveWettkampf(wettkampf);
        setActiveWettkampf(wettkampf.id);
        navigate('/wettkampf');
        return;
      } catch (_) { /* kein Wettkampf-Code → als Einzelspiel versuchen */ }
      const game = await sync.joinGame(code);
      saveGame(game);
      setActiveGame(game.id);
      navigate('/spiel-laufend');
    } catch (e) {
      msg.textContent = 'Beitritt fehlgeschlagen — Code prüfen und online sein.';
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', go);
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });

  // Deeplink `#/beitreten?code=…&push=…` — von der Sportwinner-Brücke beim Neustart geöffnet,
  // wenn dieses Match bereits existiert: Push-Endpoint merken, Code vorbelegen und automatisch
  // beitreten. Der Wettkampf-Hub übernimmt danach das Rückschreiben der Ergebnisse.
  const q = currentQuery();
  setBruecke(q.get('push'));
  const preCode = (q.get('code') || '').trim();
  if (preCode) {
    input.value = preCode.toUpperCase();
    go();
  }

  return root;
}
