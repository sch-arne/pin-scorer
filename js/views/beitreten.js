// „Spiel beitreten": Beitritts-Code eines geteilten Spiels eingeben und dem Spiel
// mehrgeraetig beitreten. Laedt das Backend nur lazy (dynamic import), damit die
// local-first App ohne Verbindung unbeeintraechtigt bleibt.

import { navigate, currentQuery } from '../router.js';
import { saveGame, setActiveGame, saveWettkampf, setActiveWettkampf } from '../store.js';
import { setBruecke, getBruecke, vergissWettkampf } from '../backend/sw-bruecke.js';
import { fehlerText } from '../util.js';

// Ist der Fehler ein „Code unbekannt/deaktiviert" (RPC wirft 'Ungültiger Beitritts-Code'),
// also KEIN Verbindungsproblem? Nur dann ist der Code sicher tot; bei offline nicht.
function istCodeTot(e) {
  return /ung(ü|ue|.)?ltig|unbekannt|not.?found|invalid/i.test((e && e.message) || '');
}

export function beitretenView() {
  const root = document.createElement('div');
  root.className = 'view view-page';
  root.innerHTML = `
    <header class="page-header">
      <a class="back-btn" href="#/neues-spiel" aria-label="Zurück">←</a>
      <h1 class="page-title">Spiel beitreten</h1>
    </header>
    <div class="join-body">
      <p class="join-hint">Gib den Code eines geteilten Spiels oder Wettkampfs ein. Es gibt zwei Arten: der <b>Eingabe-Code</b> lässt dich mit erfassen, der <b>Zuschauer-Code</b> zeigt alles live, aber nur zum Ansehen. Die Codes zeigt das erste Gerät unter ⚙ → Mehrgeräte (bzw. im Wettkampf unter „Teilen").</p>
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

  // auto=true: von der Brücke ausgelöster Auto-Wiederbeitritt (Deeplink mit code+push). Nur
  // dann heilen wir einen toten Code selbst (Brücke vergessen lassen + Import zeigen).
  async function go(auto = false) {
    const code = input.value.trim();
    if (!code) { msg.textContent = 'Bitte Code eingeben.'; return; }
    btn.disabled = true;
    msg.textContent = 'Verbinde …';
    try {
      const sync = await import('../backend/sync.js');
      // Ein Code kann zu einem Wettkampf ODER einem Einzelspiel gehören, und je Code-Art
      // zum EINGABE-Code (mit erfassen) ODER zum ZUSCHAUER-Code (nur ansehen). Der Reihe nach
      // probieren; ein „Code tot" (unbekannt) heißt nur „diese Variante passt nicht" und geht
      // zur nächsten weiter — ein echter Verbindungsfehler (offline) bricht dagegen sofort ab
      // (sonst verschluckt der innere catch den Offline-Fall).
      // 1) Eingabe-Code eines Wettkampfs
      try {
        const { wettkampf, games } = await sync.joinWettkampf(code);
        games.forEach((g) => saveGame(g));
        saveWettkampf(wettkampf);
        setActiveWettkampf(wettkampf.id);
        navigate('/wettkampf');
        return;
      } catch (ew) {
        if (!istCodeTot(ew)) throw ew;
      }
      // 2) Eingabe-Code eines Einzelspiels
      try {
        const game = await sync.joinGame(code);
        saveGame(game);
        setActiveGame(game.id);
        navigate('/spiel-laufend');
        return;
      } catch (eg) {
        if (!istCodeTot(eg)) throw eg;
      }
      // 3) Zuschauer-Code eines Wettkampfs
      try {
        const { wettkampf, games } = await sync.zuschauerWettkampf(code);
        games.forEach((g) => saveGame(g));
        saveWettkampf(wettkampf);
        setActiveWettkampf(wettkampf.id);
        navigate('/wettkampf');
        return;
      } catch (ez) {
        if (!istCodeTot(ez)) throw ez;
      }
      // 4) Zuschauer-Code eines Einzelspiels
      const game = await sync.zuschauerGame(code);
      saveGame(game);
      setActiveGame(game.id);
      navigate('/spiel-laufend');
    } catch (e) {
      const tot = istCodeTot(e);
      // Toter Code aus einem Brücken-Auto-Wiederbeitritt: der Wettkampf wurde gelöscht bzw.
      // sein Link gekappt. Die Brücke dieses Match vergessen lassen (damit sie es beim nächsten
      // Öffnen nicht wieder findet) und zum frischen Sportwinner-Import wechseln.
      const base = getBruecke();
      if (auto && tot && base) {
        try { await vergissWettkampf({ code }); } catch (_) { /* Brücke evtl. weg */ }
        const src = encodeURIComponent(base + '/roster.json');
        navigate('/import/sportwinner?src=' + src + '&push=' + encodeURIComponent(base));
        return;
      }
      // Bei einem echten Fehler (kein toter Code) die Ursache NENNEN: RLS-Ablehnung, fehlende
      // Anmeldung und ein nicht eingespieltes SQL-Update sahen bisher alle wie „offline" aus.
      if (!tot) console.error('[beitreten] fehlgeschlagen', e);
      msg.textContent = tot
        ? 'Unbekannter oder deaktivierter Code.'
        : 'Beitritt fehlgeschlagen: ' + fehlerText(e, 'Code prüfen und online sein');
      btn.disabled = false;
    }
  }

  btn.addEventListener('click', () => go(false));
  input.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(false); });

  // Deeplink `#/beitreten?code=…&push=…` — von der Sportwinner-Brücke beim Neustart geöffnet,
  // wenn dieses Match bereits existiert: Push-Endpoint merken, Code vorbelegen und automatisch
  // beitreten. Der Wettkampf-Hub übernimmt danach das Rückschreiben der Ergebnisse.
  const q = currentQuery();
  setBruecke(q.get('push'));
  const preCode = (q.get('code') || '').trim();
  if (preCode) {
    input.value = preCode.toUpperCase();
    go(true);
  }

  return root;
}
