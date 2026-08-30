// Wettkampf-Auswertung: führt die Ergebnisse aller Durchgänge (jeweils ein
// sportkegler-wk-Spiel) zu einer gemeinsamen Einzel-Rangliste und einer
// Mannschafts-Rangliste zusammen. Reine Logik — Browser + Node ladbar,
// unabhängig vom View (per Unit-Test abgesichert).

import { computeGameStats } from './statistik.js';
import { teilsatzRanges } from './teilsaetze.js';

// Sitzordnung der Durchgänge planen (Paarkreuz auf festen Team-Startbahnen).
//   mannschaften:       [{ id, name }]
//   spielerJeMannschaft: P (Spieler pro Mannschaft)
//   teamLanes:          { [teamId]: number[] } — die Startbahnen je Mannschaft (Bahnnummern)
// Jede Mannschaft besetzt pro Durchgang ihre eigenen Bahnen: Spieler d·q+1 … d·q+q sitzen im
// Durchgang d auf den q Bahnen der Mannschaft (q = Anzahl ihrer Startbahnen). Die Zahl der
// Durchgänge = max über die Mannschaften von ceil(P / q). Ein Durchgang füllt alle Team-Bahnen.
// Rückgabe: Array von Durchgängen; jeder = [{ mannschaftId, mannschaftName, teamPos, startBahn }],
// nach Bahn sortiert.
export function planDurchgaenge({ mannschaften, spielerJeMannschaft, teamLanes }) {
  const teams = mannschaften || [];
  const P = Math.max(0, Math.floor(spielerJeMannschaft) || 0);
  const lanesOf = (id) => ((teamLanes && teamLanes[id]) || []).slice().sort((a, b) => a - b);

  let D = 0;
  teams.forEach((t) => {
    const q = lanesOf(t.id).length;
    if (q > 0) D = Math.max(D, Math.ceil(P / q));
  });

  const durchgaenge = [];
  for (let d = 0; d < D; d += 1) {
    const seat = [];
    teams.forEach((t) => {
      const lanes = lanesOf(t.id);
      const q = lanes.length;
      for (let j = 0; j < q; j += 1) {
        const pos = d * q + j + 1; // teamPos (1-basiert)
        if (pos <= P) seat.push({ mannschaftId: t.id, mannschaftName: t.name, teamPos: pos, startBahn: lanes[j] });
      }
    });
    seat.sort((a, b) => a.startBahn - b.startBahn);
    if (seat.length) durchgaenge.push(seat);
  }
  return durchgaenge;
}

// Standard-„1224"-Rangvergabe nach absteigendem Wert (gleicher Wert = gleicher Rang,
// der übersprungene Rang wird ausgelassen). Setzt `rang` direkt auf den Objekten und
// gibt die sortierte Liste zurück (wie in logic/statistik.js).
function assignRang(list, valueOf) {
  const sorted = list.slice().sort((a, b) => valueOf(b) - valueOf(a));
  let rang = 0;
  let prev = null;
  sorted.forEach((x, i) => {
    const v = valueOf(x);
    if (prev === null || v < prev) rang = i + 1;
    x.rang = rang;
    prev = v;
  });
  return sorted;
}

// Grund-Status eines Durchgang-Spiels aus den ERFASSUNGSDATEN ableiten (nicht aus der
// gespeicherten `status`-Spalte, die nur lokal gesetzt und nicht zum Server gepusht wird —
// ein Reload/das Overlay sähen sonst wieder 'setup'). Die Sätze/Blöcke werden dagegen
// synchronisiert, sind also überall verfügbar:
//   'beendet' — jeder Satz jedes Spielers ist beendet (done),
//   'laufend' — mindestens ein Ergebnis erfasst (done/Würfe/Teilsatz gesetzt), aber nicht alle,
//   'setup'   — noch nichts erfasst.
// Fehlt config/erfassung (z. B. Minimal-Objekt), greift der gespeicherte Status als Rückfall.
export function gameBaseStatus(game) {
  const c = game && game.config;
  const bloecke = (game && game.erfassung && game.erfassung.bloecke) || null;
  const nSp = c && Array.isArray(c.spielerListe) ? c.spielerListe.length : (bloecke ? bloecke.length : 0);
  const nSaetze = (c && c.saetze) || 0;
  if (!bloecke || !nSp || !nSaetze) return (game && game.status) || 'setup';
  const hatInhalt = (b) => !!b && (b.done
    || (Array.isArray(b.wuerfe) && b.wuerfe.length > 0)
    || (Array.isArray(b.overrides) && b.overrides.some((x) => x != null)));
  let anyInhalt = false;
  let alleDone = true;
  for (let sp = 0; sp < nSp; sp += 1) {
    const arr = bloecke[sp] || [];
    for (let st = 0; st < nSaetze; st += 1) {
      const b = arr[st];
      if (hatInhalt(b)) anyInhalt = true;
      if (!(b && b.done)) alleDone = false;
    }
  }
  if (alleDone && anyInhalt) return 'beendet';
  if (anyInhalt) return 'laufend';
  return 'setup';
}

// Abgeleiteter Anzeige-Status je Durchgang (nach Nummer sortiert):
//   'fertig'       — alle Sätze des Durchgangs beendet (Spiel-Status 'beendet'),
//   'laufend'      — noch offene Sätze, aber schon ein Ergebnis erfasst ('laufend'),
//   'vorbereitung' — der nächste Durchgang, der starten wird (der erste noch nicht
//                    gestartete, also mit kleinster Nummer),
//   'offen'        — alle übrigen noch nicht gestarteten Durchgänge.
// Grundlage ist der Spiel-Status (beendet/laufend/setup); fehlt das Spiel, greift der
// am Durchgang gespeicherte Status. Rückgabe: [{ nr, gameId, status }].
export function durchgangStatusList(wettkampf, games) {
  const byId = {};
  (games || []).forEach((g) => { byId[g.id] = g; });
  const list = ((wettkampf && wettkampf.durchgaenge) || [])
    .slice().sort((a, b) => (a.nr || 0) - (b.nr || 0));
  let vorbereitungVergeben = false;
  return list.map((d) => {
    const g = byId[d.gameId];
    const base = g ? gameBaseStatus(g) : (d.status || 'setup');
    let status;
    if (base === 'beendet') status = 'fertig';
    else if (base === 'laufend') status = 'laufend';
    else if (!vorbereitungVergeben) { status = 'vorbereitung'; vorbereitungVergeben = true; }
    else status = 'offen';
    return { nr: d.nr, gameId: d.gameId, status };
  });
}

// Abgeleiteter Wettkampf-Status aus den Durchgängen (analog gameBaseStatus für ein Spiel):
//   'beendet' — es gibt Durchgänge UND jeder ist 'fertig' (alle Sätze beendet),
//   'laufend' — mindestens ein Durchgang hat schon ein Ergebnis, aber nicht alle fertig,
//   'setup'   — noch kein Durchgang oder noch nichts erfasst.
// Wie bei den Durchgängen wird aus den (synchronisierten) Erfassungsdaten abgeleitet, damit
// jedes Gerät ohne extra Push zum selben Ergebnis kommt.
export function wettkampfBaseStatus(wettkampf, games) {
  const list = durchgangStatusList(wettkampf, games);
  if (!list.length) return 'setup';
  if (list.every((d) => d.status === 'fertig')) return 'beendet';
  if (list.some((d) => d.status === 'fertig' || d.status === 'laufend')) return 'laufend';
  return 'setup';
}

// Wettkampf + zugehörige Durchgang-Spiele -> { einzel, mannschaften }.
//   wettkampf: { mannschaften:[{id,name}], durchgaenge:[{nr, gameId}] }
//   games:     Array der Durchgang-Spielobjekte (config + erfassung.bloecke)
// Läuft auch mit teil-erfassten Durchgängen (Live-Zwischenstand): computeGameStats
// wertet aus, was da ist.
export function computeWettkampfStats(wettkampf, games) {
  const mannschaften = wettkampf.mannschaften || [];
  const teamName = {};
  mannschaften.forEach((m) => { teamName[m.id] = m.name; });
  const gameById = {};
  (games || []).forEach((g) => { gameById[g.id] = g; });

  // Einzel: jeden Spieler jedes Durchgangs mit seinem Gesamtholz sammeln.
  const einzel = [];
  (wettkampf.durchgaenge || []).forEach((d) => {
    const game = gameById[d.gameId];
    if (!game || !game.config || !Array.isArray(game.config.spielerListe)) return;
    const c = game.config;
    const bloecke = (game.erfassung && game.erfassung.bloecke) || [];
    const { players } = computeGameStats(c, bloecke, teilsatzRanges(c));
    players.forEach((p) => {
      const sp = c.spielerListe[p.index] || {};
      einzel.push({
        ...p,
        durchgangNr: d.nr,
        gameId: game.id,
        teamPos: sp.teamPos || null,
        startBahn: sp.startBahn ?? (p.saetze && p.saetze[0] && p.saetze[0].bahn) ?? null,
        mannschaftId: sp.mannschaftId || null,
        mannschaftName: (sp.mannschaftId && teamName[sp.mannschaftId]) || null,
      });
    });
  });

  const einzelRanking = assignRang(einzel, (p) => p.gesamt);

  // Mannschaften: Summe Gesamtholz je Team (+ Schnitt je Spieler). Auch Teams ohne
  // erfasste Spieler erscheinen (mit 0), damit die Übersicht vollständig bleibt.
  const byTeam = new Map();
  mannschaften.forEach((m) => byTeam.set(m.id, { mannschaftId: m.id, name: m.name, spieler: 0, gesamt: 0 }));
  einzel.forEach((p) => {
    if (!p.mannschaftId) return;
    if (!byTeam.has(p.mannschaftId)) byTeam.set(p.mannschaftId, { mannschaftId: p.mannschaftId, name: p.mannschaftName || '—', spieler: 0, gesamt: 0 });
    const t = byTeam.get(p.mannschaftId);
    t.spieler += 1;
    t.gesamt += p.gesamt;
  });
  const teams = [...byTeam.values()].map((t) => ({ ...t, schnitt: t.spieler ? t.gesamt / t.spieler : 0 }));
  const mannschaftRanking = assignRang(teams, (t) => t.gesamt);

  return { einzel: einzelRanking, mannschaften: mannschaftRanking };
}
