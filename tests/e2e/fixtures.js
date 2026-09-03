// Fixtures fuer die E2E-Tests: fertige Spiel-/Wettkampf-Objekte zum Seeden des
// localStorage. Sie werden mit DENSELBEN Logik-Modulen gebaut, die auch das Setup
// benutzt (teilsaetze/bahnwechsel) — so kann kein Fixture entstehen, das die App
// selbst nie erzeugen wuerde.
//
// Der Setup-Ablauf selbst wird in specs/10-setup.js durch die echte Maske getestet;
// die Erfassungs-Tests seeden hier direkt, um nicht jedes Mal durch das Setup zu klicken.

import { throwsPerPart } from '../../js/logic/teilsaetze.js';
import { lanePlan } from '../../js/logic/bahnwechsel.js';
import { PRESETS } from '../../js/logic/sportkegeln-presets.js';
import { defaultKegel } from '../../js/logic/abraeumen.js';

let counter = 0;
const nextId = (p) => `${p}-e2e-${Date.now()}-${counter++}`;

// Spiel-Konfiguration wie sie setup-wk.js/start() erzeugt.
export function makeConfig({
  preset = 'bohle',
  spieler = ['Anna'],
  bahnen = null,
  ersteBahn = 1,
  saetze = null,
  wuerfeProSatz = null,
  teilsaetze = null,
  bahnwechsel = null,
  startBahnen = null,
  mannschaftIds = null,
} = {}) {
  const p = PRESETS[preset];
  const cfgSaetze = saetze ?? p.saetze;
  const cfgWps = wuerfeProSatz ?? p.wuerfeProSatz;
  const modi = teilsaetze ?? p.teilsaetze;
  const cfgBahnen = bahnen ?? p.bahnen;
  const cfgBw = bahnwechsel ?? p.bahnwechsel;
  const tpp = throwsPerPart(cfgWps, modi.length);

  const spielerListe = spieler.map((name, i) => {
    const sp = { name, startBahn: startBahnen ? startBahnen[i] : ersteBahn + i };
    if (mannschaftIds) sp.mannschaftId = mannschaftIds[i];
    return sp;
  });

  const state = {
    spieler: spielerListe.length,
    spielerData: spielerListe,
    bahnen: cfgBahnen,
    ersteBahn,
    saetze: cfgSaetze,
    bahnwechsel: cfgBw,
    bahnListe: [],
    anlageId: null,
  };

  return {
    preset,
    spieler: spielerListe.length,
    spielerListe,
    bahnen: cfgBahnen,
    ersteBahn,
    saetze: cfgSaetze,
    wuerfeProSatz: cfgWps,
    gesamtwuerfe: cfgSaetze * cfgWps,
    teilsaetze: modi.map((modus, i) => ({ modus, wuerfe: tpp[i] })),
    bahnwechsel: cfgBw,
    bahnplan: lanePlan(state),
  };
}

export function makeGame(opts = {}) {
  const { status = 'setup', wettkampfId = null, durchgangNr = null, ichIndex = null, ...rest } = opts;
  const game = {
    id: nextId('g'),
    schemaVersion: 1,
    createdAt: new Date().toISOString(),
    spiel: 'sportkegler-wk',
    status,
    ichIndex,
    config: makeConfig(rest),
  };
  if (wettkampfId) { game.wettkampfId = wettkampfId; game.durchgangNr = durchgangNr || 1; }
  return game;
}

// Wettkampf wie ihn setup-wettkampf.js anlegt (Stammdaten + Mannschaften + Vorlage).
export function makeWettkampf({
  name = 'Test-Cup',
  mannschaften = ['Heim', 'Gast'],
  spielerJeMannschaft = 2,
  preset = 'schere',
  bahnen = 2,
  ersteBahn = 1,
  status = 'setup',
} = {}) {
  const p = PRESETS[preset];
  const teams = mannschaften.map((n, i) => ({ id: `m${i + 1}`, name: n }));
  return {
    id: nextId('w'),
    createdAt: new Date().toISOString(),
    name,
    status,
    mannschaften: teams,
    spielerJeMannschaft,
    durchgaenge: [],
    programm: {
      preset,
      bahnen,
      ersteBahn,
      saetze: p.saetze,
      wuerfeProSatz: p.wuerfeProSatz,
      teilsaetze: [...p.teilsaetze],
      bahnwechsel: p.bahnwechsel,
      spieler: Math.min(bahnen, teams.length * spielerJeMannschaft),
      bahnListe: [],
      anlageId: null,
    },
  };
}

// Erfassungsstand: `wuerfe` ist [spieler][satz] -> Array Holzzahlen.
//
// Das Kegelbild wird wie in der App aus der Holzzahl abgeleitet (defaultKegel): 9 = alle
// neun, 0 = keiner, dazwischen offen (null). Das ist wichtig — ein Spiel, dessen LETZTER
// Wurf noch kein Bild hat, gilt der Erfassung als „noch nicht fertig" (kegelbildOffen) und
// wird nicht abgeschlossen. Mit `kegel` lässt sich ein Bild gezielt vorgeben.
export function makeErfassung(config, wuerfe, { done = null, kegel = null, aktiverSpieler = 0, aktiverSatz = 0 } = {}) {
  return {
    aktiverSpieler,
    aktiverSatz,
    bloecke: config.spielerListe.map((_, sp) =>
      Array.from({ length: config.saetze }, (_, st) => {
        const w = (wuerfe[sp] && wuerfe[sp][st]) || [];
        return {
          wuerfe: w.slice(),
          kegel: w.map((n, k) => {
            const vorgabe = kegel && kegel[sp] && kegel[sp][st] && kegel[sp][st][k];
            return vorgabe !== undefined && vorgabe !== null ? vorgabe.slice() : defaultKegel(n);
          }),
          koenig: w.map(() => false),
          overrides: config.teilsaetze.map(() => null),
          done: done ? !!(done[sp] && done[sp][st]) : w.length >= config.wuerfeProSatz,
        };
      })),
  };
}

// Gleichmaessige Wurfserie (z.B. 30x 7 Holz) — kurze Schreibweise in den Tests.
export function serie(n, wert) { return Array.from({ length: n }, () => wert); }
