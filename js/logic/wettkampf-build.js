// Wettkampf-Erzeugung: aus einem normalisierten Spec (Programm + Anlage + Mannschaften)
// die Wettkampf-Klammer und ihre Durchgang-Spiele (Paarkreuz) bauen. Reine Logik ohne
// Store/DOM — teilen sich das manuelle Setup (views/setup-wettkampf.js) und der
// Sportwinner-Import (views/import-sportwinner.js), damit beide Wege identische Objekte
// erzeugen und per Unit-Test abgesichert sind.

import { throwsPerPart } from './teilsaetze.js';
import { lanePlan } from './bahnwechsel.js';
import { planDurchgaenge } from './wettkampf.js';

export const SCHEMA_VERSION = 1;

const sortNum = (arr) => arr.slice().sort((a, b) => a - b);

// Programm-Snapshot (dient auch als Vorlage für manuell hinzugefügte Durchgänge im Hub).
export function snapshotProgramm(p) {
  const lanes = sortNum(p.playedLanes || []);
  return {
    preset: p.preset,
    spieler: lanes.length,
    bahnen: lanes.length,
    ersteBahn: lanes[0] || 1,
    saetze: p.saetze,
    wuerfeProSatz: p.wuerfeProSatz,
    teilsaetze: [...(p.teilsaetze || [])],
    bahnwechsel: p.bahnwechsel,
    anlageId: p.anlageId,
    bahnListe: lanes,
  };
}

// Ein Durchgang-Spiel (sportkegler-wk) aus Programm + Sitzordnungs-Slice bauen.
// slice = [{ mannschaftId, mannschaftName, teamPos, startBahn }] (nach Bahn sortiert).
// namesByTeamPos (optional): { `${mannschaftId}|${teamPos}`: name } — echte Spielernamen,
// sonst der Platzhalter „<Mannschaft> <Pos>".
export function buildDurchgangGame(p, slice, nr, wettkampfId, namesByTeamPos = null) {
  const tpp = throwsPerPart(p.wuerfeProSatz, (p.teilsaetze || []).length);
  const playedLanes = sortNum(p.playedLanes || []);
  const nameOf = (pl) => {
    const real = namesByTeamPos && namesByTeamPos[`${pl.mannschaftId}|${pl.teamPos}`];
    return (real && String(real).trim()) || `${pl.mannschaftName} ${pl.teamPos}`;
  };
  const spielerData = slice.map((pl) => ({ name: nameOf(pl), startBahn: pl.startBahn, mannschaftId: pl.mannschaftId }));
  const gstate = { bahnListe: playedLanes, saetze: p.saetze, bahnwechsel: p.bahnwechsel, spielerData };
  const zuordnung = {};
  playedLanes.forEach((n) => {
    const b = (p.anlageBahnen || []).find((x) => x.nummer === n);
    if (b) zuordnung[n] = { id: b.id, bahnart: b.bahnart || null };
  });
  return {
    id: 'g' + Date.now().toString(36) + '-' + nr + '-' + Math.random().toString(36).slice(2, 6),
    schemaVersion: SCHEMA_VERSION,
    createdAt: new Date().toISOString(),
    spiel: 'sportkegler-wk',
    status: 'setup',
    wettkampfId,
    durchgangNr: nr,
    config: {
      preset: p.preset,
      spieler: spielerData.length,
      spielerListe: spielerData.map((sp, i) => ({
        name: sp.name, startBahn: sp.startBahn, mannschaftId: sp.mannschaftId, teamPos: slice[i].teamPos,
      })),
      bahnen: playedLanes.length,
      ersteBahn: playedLanes[0],
      saetze: p.saetze,
      wuerfeProSatz: p.wuerfeProSatz,
      gesamtwuerfe: p.saetze * p.wuerfeProSatz,
      teilsaetze: (p.teilsaetze || []).map((modus, i) => ({ modus, wuerfe: tpp[i] })),
      bahnwechsel: p.bahnwechsel,
      bahnplan: lanePlan(gstate),
      anlageId: p.anlageId,
      anlageName: p.anlageName || '',
      bahnZuordnung: zuordnung,
      bahnListe: playedLanes,
    },
  };
}

// Kompletter Wettkampf + Durchgang-Spiele aus einem Spec. Rein: persistieren
// (saveGame/saveWettkampf) macht der Aufrufer. Rückgabe: { wettkampf, games }.
//
// spec = {
//   id?, name, datum,
//   preset, saetze, wuerfeProSatz, teilsaetze[], bahnwechsel,
//   anlageId, anlageName, anlageBahnen[{id?,nummer,bahnart}],
//   playedLanes[], mannschaften[{id,name,lanes[]}], spielerJeMannschaft,
//   namesByTeamPos?, quelle?, sportwinner?
// }
export function buildWettkampf(spec) {
  const mannschaften = (spec.mannschaften || []).map((m) => ({
    id: m.id, name: (m.name || '').trim() || 'Mannschaft', lanes: sortNum(m.lanes || []),
  }));
  const teamLanes = {};
  mannschaften.forEach((m) => { teamLanes[m.id] = m.lanes; });

  const wettkampf = {
    id: spec.id || ('w' + Date.now()),
    schemaVersion: SCHEMA_VERSION,
    createdAt: new Date().toISOString(),
    typ: 'sportkegler-wettkampf',
    status: 'setup',
    name: (spec.name || '').trim() || 'Wettkampf',
    datum: spec.datum,
    anlageId: spec.anlageId,
    anlageName: spec.anlageName || '',
    playedLanes: sortNum(spec.playedLanes || []),
    mannschaften,
    spielerJeMannschaft: spec.spielerJeMannschaft,
    programm: snapshotProgramm(spec),
    durchgaenge: [],
  };
  // Wertungskriterien (Punktvergabe) — im Setup „Wertung"-Tab definiert. Reist über
  // config_json durch link/pullWettkampf mit; von computeWertung noch nicht konsumiert.
  if (spec.wertung) wettkampf.wertung = spec.wertung;
  if (spec.quelle) wettkampf.quelle = spec.quelle;
  // Sportwinner-Rückschreib-Zuordnung (Mannschaft->DLL-Seite, Spieler->DLL-Slot) unverändert
  // mitführen; reist über config_json durch linkWettkampf/pullWettkampf mit.
  if (spec.sportwinner) wettkampf.sportwinner = spec.sportwinner;

  const plan = planDurchgaenge({
    mannschaften: mannschaften.map((m) => ({ id: m.id, name: m.name })),
    spielerJeMannschaft: spec.spielerJeMannschaft,
    teamLanes,
  });

  const games = [];
  plan.forEach((slice, di) => {
    const game = buildDurchgangGame(spec, slice, di + 1, wettkampf.id, spec.namesByTeamPos || null);
    games.push(game);
    wettkampf.durchgaenge.push({ nr: di + 1, gameId: game.id, status: 'setup' });
  });

  return { wettkampf, games };
}
