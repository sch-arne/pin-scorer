// Ein Spiel oder einen Wettkampf entfernen — EINE Stelle für alle Aufrufer („Neues Spiel",
// Wettkampf-Hub, Statistiken). Was dabei geschieht, entscheidet logic/loeschen.js:
//
//   • rein LOKAL       -> komplett weg. Geht offline, ist endgültig.
//   • in der DATENBANK -> verbergen, und zwar NUR FÜR MICH: raus aus meinen Listen und
//                         meiner Statistik. Sonst ändert sich nichts — die Aufzeichnung
//                         bleibt stehen (sie gehört auch den Mitspielern, deren Profile über
//                         ihre LizenzID daran hängen), der Freigabe-Link gilt weiter und
//                         andere Geräte, Zuschauer und das OBS-Overlay laufen unverändert.
//   • FREMDES mit lokaler Kopie -> nur die Kopie auf diesem Gerät. In der Datenbank gehört
//                         mir nichts davon, also wird dort auch nichts angefasst.
//   • FREMDES ohne Kopie -> gar nichts zu tun. So kommen die Ergebnisse an, die einen über
//                         die eigene LizenzID finden.
//
// WICHTIG — die Reihenfolge ist eine Zusage: die eigene Kopie verschwindet IMMER, auch
// offline und auch dann, wenn anderswo gerade weitergespielt wird. Der Vermerk fürs Konto
// (`verborgen`) wird davor versucht; klappt er nicht, wird trotzdem entfernt und ehrlich
// gesagt, dass das Spiel später wieder auftauchen kann. Früher blieb bei einem Fehlschlag
// alles stehen — das war richtig, solange das Entfernen den Freigabe-Link kappte und damit
// alle Beteiligten traf. Seit es eine rein persönliche Notiz ist, gibt es keinen Grund mehr,
// jemanden auf seiner eigenen Liste sitzen zu lassen.
//
// Ein Wettkampf hängt zusätzlich an der Sportwinner-Brücke, die sich das Match samt Code
// merkt — die wird beim Entfernen mit vergessen gemacht.

import { getGame, deleteGame, getWettkampf, deleteWettkampf } from '../store.js';
import { vergissWettkampf } from '../backend/sw-bruecke.js';
import {
  VERBERGEN, GESPERRT, GESPERRT_HINWEIS, VERMERK_FEHLT, loeschart, loeschFrage,
} from '../logic/loeschen.js';

// Wer bin ich? Kennt der Aufrufer das Konto nicht (z.B. „Neues Spiel"), wird es hier
// nachgeschlagen — davon hängt ab, ob ein geteiltes Spiel MIR gehört (verbergen) oder ob ich
// ihm nur beigetreten bin (nur die eigene Kopie). Best effort: ohne Verbindung bleibt es
// unbekannt, und dann ist die vorsichtige Antwort ohnehin „nur die eigene Kopie".
async function meinKonto(konto) {
  if (konto) return konto;
  try {
    const sync = await import('../backend/sync.js');
    return await sync.kontoId();
  } catch (e) {
    return null;
  }
}

// Den Vermerk „bei mir entfernt" fürs Konto schreiben. true = geschrieben, false = ging
// gerade nicht (offline, Migration noch nicht eingespielt). Blockiert nichts.
async function vermerke(fn, remoteId) {
  try {
    const sync = await import('../backend/sync.js');
    await sync[fn](remoteId);
    return true;
  } catch (e) {
    return false;
  }
}

// Ein Spiel entfernen. `game` darf ein lokales Spiel oder ein nur remote geladenes Objekt
// sein (dann greift deleteGame ins Leere — gewollt, es liegt hier ja gar nicht).
// Rückgabe: true = entfernt, false = abgebrochen, gesperrt oder fehlgeschlagen.
export async function spielLoeschen(game, { konto = null, erfasstVon = null } = {}) {
  const g = typeof game === 'string' ? getGame(game) : game;
  if (!g) return false;
  const art = loeschart(g, { konto: await meinKonto(konto), erfasstVon, lokal: !!getGame(g.id) });
  if (art === GESPERRT) { window.alert(GESPERRT_HINWEIS); return false; }
  if (!window.confirm(loeschFrage(art))) return false;
  const vermerkt = art !== VERBERGEN || await vermerke('verbergeSpiel', g.remoteId);
  deleteGame(g.id);
  if (!vermerkt) window.alert(VERMERK_FEHLT);
  return true;
}

// Einen Wettkampf entfernen — inklusive seiner Durchgänge. `w` darf wie oben ein lokaler
// Wettkampf, dessen id oder ein nur remote geladenes Objekt sein.
export async function wettkampfLoeschen(w, { konto = null } = {}) {
  const wk = typeof w === 'string' ? getWettkampf(w) : w;
  if (!wk) return false;
  const art = loeschart(wk, { konto: await meinKonto(konto), lokal: !!getWettkampf(wk.id) });
  if (art === GESPERRT) { window.alert(GESPERRT_HINWEIS); return false; }
  if (!window.confirm(loeschFrage(art, { wettkampf: true }))) return false;
  const vermerkt = art !== VERBERGEN || await vermerke('verbergeWettkampf', wk.remoteId);

  // Kam der Wettkampf aus Sportwinner, die Brücke dieses Match vergessen lassen, damit sie
  // beim nächsten Öffnen nicht den (nun toten) Code wiederfindet. Nur wirksam, wenn die
  // Brücke in dieser Session bekannt ist (Vereins-PC); sonst still no-op.
  const swNr = wk.sportwinner && wk.sportwinner.spielNr;
  if (swNr != null || wk.beitrittsCode) {
    vergissWettkampf({ code: wk.beitrittsCode || '', spielNr: swNr ?? null,
      heim: wk.mannschaften?.[0]?.name, gast: wk.mannschaften?.[1]?.name });
  }
  deleteWettkampf(wk.id);
  if (!vermerkt) window.alert(VERMERK_FEHLT);
  return true;
}
