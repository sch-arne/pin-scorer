// Sportwinner-Roster (roster.json der Brücke) -> normalisiertes Wettkampf-Import-Spec.
// Reine Logik ohne Netz/DOM: die Brücke liest über interface.dll die Partie (Heim=GG,
// Gast=G) samt Aufstellung und optionalem Ergebnisdienst-Block (`partie` mit Liga,
// Datum, Spielort/Bahnen). Diese Datei formt daraus die Werte, aus denen
// views/import-sportwinner.js Anlage + Wettkampf erzeugt. Per Unit-Test abgesichert.

const uid = (p) => p + Math.random().toString(36).slice(2, 8);
const sortNum = (arr) => arr.slice().sort((a, b) => a - b);

// Sportwinner-Sektion (Disziplin/Bahnart) -> Bahnart-Preset der App.
// In Sportwinner (Globals.Sektion): 1 = Classic, 2 = Schere. Über die Sektion
// wird beim Import die Bahnart vorgewählt; Bohle hat keine eigene Sektion.
export function sektionToBahnart(sektion) {
  const n = Number(sektion);
  if (n === 1) return 'classic';
  if (n === 2) return 'schere';
  return null;
}

// Bahnen-String des Ergebnisdienstes zu Bahnnummern. Beispiele:
//   "2 - 5" / "2-5"  -> [2,3,4,5]   (Bereich)
//   "2, 3, 4, 5"     -> [2,3,4,5]   (Liste)
//   "4"              -> [4]
//   "" / null        -> []
export function parseBahnen(str) {
  const s = (str == null ? '' : String(str)).trim();
  if (!s) return [];
  const range = s.match(/^(\d+)\s*[-–]\s*(\d+)$/);
  if (range) {
    let a = parseInt(range[1], 10);
    let b = parseInt(range[2], 10);
    if (a > b) [a, b] = [b, a];
    const out = [];
    for (let n = a; n <= b; n += 1) out.push(n);
    return out;
  }
  const nums = s.split(/[^\d]+/).map((x) => parseInt(x, 10)).filter((n) => Number.isFinite(n) && n > 0);
  return sortNum([...new Set(nums)]);
}

// "29.08.2026" -> "2026-08-29"; leer/ungültig -> ''.
export function germanDateToISO(str) {
  const m = (str || '').trim().match(/^(\d{1,2})\.(\d{1,2})\.(\d{4})$/);
  if (!m) return '';
  const [, d, mo, y] = m;
  const dd = d.padStart(2, '0');
  const mm = mo.padStart(2, '0');
  if (+mm < 1 || +mm > 12 || +dd < 1 || +dd > 31) return '';
  return `${y}-${mm}-${dd}`;
}

const spielerName = (p) => `${(p.vorname || '').trim()} ${(p.nachname || '').trim()}`.trim();

// Aufstellung einer Seite -> Liste echter Spieler (leere Slots weglassen), in Reihenfolge.
// `slot` = der Sportwinner-Spielslot (aufstellung[].pos) — für das Rückschreiben der
// Ergebnisse in die DLL gebraucht, daher hier bereits mitgeführt.
function spielerListe(seite) {
  const auf = (seite && seite.aufstellung) || [];
  return auf
    .map((p, i) => ({
      name: spielerName(p), pass: (p.pass || '').trim() || null, extId: p.id ?? null,
      slot: Number.isFinite(p.pos) ? p.pos : i,
    }))
    .filter((p) => p.name || p.pass);
}

// Bespielte Bahnen (bahnen) fortlaufend + gleichmäßig auf n Mannschaften aufteilen.
// Spiegelt assignDefaultLanes aus setup-wettkampf.js (jede Bahn gehört genau einem Team).
export function splitLanes(n, bahnen) {
  const lanes = sortNum(bahnen || []);
  const total = lanes.length;
  const out = [];
  for (let i = 0; i < n; i += 1) {
    const start = Math.floor((i * total) / n);
    const end = Math.floor(((i + 1) * total) / n);
    out.push(lanes.slice(start, end));
  }
  return out;
}

// Startbahn-Verteilung je Bahnart auf n Mannschaften. Für den Regelfall (2 Teams: Heim/Gast,
// 4 Bahnen) bahnartspezifische Muster auf den aufsteigend sortierten bespielten Bahnen; sonst —
// und falls ein Muster ein leeres Team ergäbe — Rückfall auf die zusammenhängende Aufteilung
// (splitLanes). Muster (Beispiel Bahnen 1–4):
//   classic: Heim ungerade Bahnen (1,3), Gast gerade (2,4)  -> owner(pos) = pos % 2
//   schere:  Heim gerade Bahnen (2,4), Gast ungerade (1,3)  -> owner(pos) = 1 - pos % 2
//   bohle:   Heim außen (1,4), Gast innen (2,3)             -> owner(pos) = min(pos, n-1-pos) % 2
// owner 0 = erste Mannschaft (Heim/GG), owner 1 = zweite (Gast/G).
const LANE_OWNER = {
  classic: (pos) => pos % 2,
  schere: (pos) => 1 - (pos % 2),
  bohle: (pos, n) => Math.min(pos, n - 1 - pos) % 2,
};
export function teamLanesByBahnart(bahnart, bahnen, nTeams = 2) {
  const lanes = sortNum(bahnen || []);
  const fn = LANE_OWNER[bahnart];
  if (nTeams !== 2 || lanes.length < 4 || !fn) return splitLanes(nTeams, lanes);
  const n = lanes.length;
  const out = [[], []];
  lanes.forEach((lane, pos) => out[fn(pos, n)].push(lane));
  if (!out[0].length || !out[1].length) return splitLanes(nTeams, lanes);
  return out;
}

// roster.json -> Import-Spec. Wirft, wenn keine Mannschaften erkennbar sind.
// Rückgabe:
// {
//   name, datum,
//   bahnart: 'classic'|'schere'|null,   // aus der Sportwinner-Sektion vorgeschlagen (null = keine Angabe)
//   anlage: { name, strasse, plz, ort, bahnen:[], adresse, ausSpielort:bool },
//   playedLanes:[],
//   spielerJeMannschaft,
//   mannschaften: [{ id, key:'GG'|'G', name, lanes:[], spieler:[{teamPos,name,pass,extId,slot}] }],
//   namesByTeamPos: { `${teamId}|${teamPos}`: name },
//   sportwinner: { spielNr, spieltagNr, seiten:{[teamId]:'GG'|'G'}, spieler:[{mannschaftId,teamPos,slot,pass,extId}] },
//   partie: { liga, datum, uhrzeit, spielId, ergebnis, sektion } | null,
//   warnungen: []
// }
export function parseRoster(roster) {
  const r = roster || {};
  const seiten = r.seiten || {};
  const partie = r.partie || null;
  const warnungen = [];

  // GG = Gastgeber/Heim zuerst, dann G = Gast (an echtem Match bestätigt, siehe BRUECKE.md).
  const seitenDef = [
    { key: 'GG', fallback: 'Heim' },
    { key: 'G', fallback: 'Gast' },
  ].filter((s) => seiten[s.key]);
  if (!seitenDef.length) throw new Error('Kein Mannschafts-Datensatz (seiten) im Roster gefunden.');

  const mannschaften = seitenDef.map((def) => {
    const seite = seiten[def.key];
    const sp = spielerListe(seite);
    const name = (seite.mannschaft || '').trim()
      || (partie && (def.key === 'GG' ? partie.heim : partie.gast)) || def.fallback;
    return {
      id: uid('m'),
      key: def.key,
      name,
      lanes: [],
      spieler: sp.map((p, i) => ({ teamPos: i + 1, ...p })),
    };
  });

  // Sportwinner-Zuordnung für das spätere Rückschreiben: welche Mannschaft ist welche
  // DLL-Seite (GG=Heim, G=Gast) und welcher Team-Spieler sitzt auf welchem DLL-Slot.
  const sportwinner = {
    spielNr: Number.isFinite(r.spielNr) ? r.spielNr : null,
    spieltagNr: Number.isFinite(r.spieltagNr) ? r.spieltagNr : null,
    seiten: {},
    spieler: [],
  };
  mannschaften.forEach((m) => {
    sportwinner.seiten[m.id] = m.key;
    m.spieler.forEach((p) => sportwinner.spieler.push({
      mannschaftId: m.id, teamPos: p.teamPos, slot: p.slot, pass: p.pass, extId: p.extId,
    }));
  });

  const spielerJeMannschaft = Math.max(1, ...mannschaften.map((m) => m.spieler.length));
  if (mannschaften.every((m) => !m.spieler.length)) {
    warnungen.push('Keine Aufstellung im Roster — in Sportwinner die Schnittstelle „Start" und nach dem Legen erneut exportieren.');
  }

  // Anlage aus dem Spielort (Bahnanlage der Heim-Mannschaft) des Ergebnisdienstes.
  const so = (partie && partie.spielort) || null;
  let bahnen = parseBahnen(so && so.bahnen);
  const ausSpielort = !!so;
  if (!bahnen.length) {
    bahnen = [1, 2, 3, 4]; // Bundesliga-Standard, wenn der Ergebnisdienst keine Bahnen nennt
    if (ausSpielort) warnungen.push('Spielort ohne Bahnangabe — Standard 1–4 angenommen.');
  }
  const heimName = mannschaften[0] ? mannschaften[0].name : 'Heim';
  const anlage = {
    name: (so && (so.anlage || '').trim()) || `${heimName} (Heim)`,
    strasse: (so && (so.strasse || '').trim()) || '',
    plz: (so && (so.plz || '').trim()) || '',
    ort: (so && (so.ort || '').trim()) || '',
    bahnen,
    adresse: (so && so.adresse) || '',
    ausSpielort,
  };

  // Startbahnen fortlaufend auf die Teams aufteilen.
  const split = splitLanes(mannschaften.length, bahnen);
  mannschaften.forEach((m, i) => { m.lanes = split[i]; });

  // Namen-Map für buildWettkampf (Team-Position -> echter Name).
  const namesByTeamPos = {};
  mannschaften.forEach((m) => m.spieler.forEach((p) => {
    if (p.name) namesByTeamPos[`${m.id}|${p.teamPos}`] = p.name;
  }));

  const datum = germanDateToISO(partie && partie.datum) || new Date().toISOString().slice(0, 10);
  const name = mannschaften.length >= 2
    ? `${mannschaften[0].name} – ${mannschaften[1].name}`
    : (mannschaften[0] ? mannschaften[0].name : 'Wettkampf');

  // Bahnart-Vorschlag aus der Sektion (Disziplin) der aufgelösten Partie.
  const sektion = partie && partie.sektion != null && partie.sektion !== '' ? Number(partie.sektion) : null;
  const bahnart = sektionToBahnart(sektion);

  return {
    name,
    datum,
    bahnart,
    anlage,
    playedLanes: bahnen,
    spielerJeMannschaft,
    mannschaften,
    namesByTeamPos,
    sportwinner,
    partie: partie ? {
      liga: partie.liga || '', datum: partie.datum || '', uhrzeit: partie.uhrzeit || '',
      spielId: partie.spielId || partie.spielId === 0 ? partie.spielId : null,
      ergebnis: partie.ergebnis || '',
      sektion: Number.isFinite(sektion) ? sektion : null,
    } : null,
    warnungen,
  };
}
