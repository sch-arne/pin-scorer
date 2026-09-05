// Sportwinner-ERGEBNISDIENST (Web) -> normalisiertes Import-Spec.
//
// Zweiter Weg neben der Brücke (logic/roster-import.js): dort liefert die interface.dll ein
// roster.json vom Vereins-PC, hier kommt ein bereits GESPIELTES Spiel über die öffentliche
// JSON-Schnittstelle des Verbands (`https://<verband>.sportwinner.de/php/<verband>/service.php`).
// Reine Logik ohne Netz/DOM — den Abruf macht backend/sw-web.js über das Relay.
//
// Der entscheidende Unterschied zur Brücke: der Ergebnisdienst liefert SUMMEN, nie Einzelwürfe.
// Was hier herauskommt, sind deshalb Summen, die als `overrides` in einen Satz-Block wandern
// (ergebnisBlock). computeGameStats behandelt einen Override als „manuell eingetragen":
// Holz und Wurfzahl stimmen, 9er/Kränze/Räumer/volles Bild bleiben 0. Genau so soll es sein —
// erfundene Einzelwürfe (wie adoptErgebnisBlock sie für den Konflikt-Abgleich baut) hätten in
// der Statistik als echte 9er und Räumer gezählt.
//
// Und die Regel dahinter gilt eine Ebene höher genauso: GESCHÄTZT WIRD NICHTS. Nennt der Bericht
// nur das Satz-Holz, dann wird auch nur das Satzergebnis gesetzt — der Wettkampf bekommt dafür
// je Satz einen einzigen Teilsatz (MODUS_GESAMT), statt die Volle/Abräum-Trennung zu erfinden.
// Eine Auswertung nach Teilsätzen gibt es für so ein Spiel dann nicht; das ist ehrlicher als
// eine, die nach Zahlen aussieht und keine sind. Welche Form vorliegt, entscheidet teilsatzPlan().
//
// ZEILENFORMATE
// -------------
// Die Antworten sind reine Arrays ohne Feldnamen, und das Layout hängt an Sektion und Wertung.
// Alle drei Formen sind aus den `columns`-Definitionen des `detailFormatter` abgelesen und am
// echten Ergebnisdienst geprüft (Referenzpartie 328202, siehe tests/fixtures/):
//
//   schere  — Sektion ≠ Classic (Schere/Bohle), 18 Spalten:
//      [0]leer [1]Name GG [2..5]Satz 1-4 GG [6]EWP GG [7]Holz GG
//      [8]Holz G [9]EWP G [10..13]Satz 4-1 G (RÜCKWÄRTS) [14]Name G [15]leer
//
//   classic — Classic mit Punktwertung, 16 Spalten:
//      [0]Name GG [1..4]Satz 1-4 GG [5]Kegel GG [6]SP [7]MP
//      [8]MP G [9]SP G [10]Kegel G [11..14]Satz 4-1 G (RÜCKWÄRTS) [15]Name G
//
//   holz    — Classic mit Holzwertung, 12 Spalten:
//      [0]leer [1]Name GG [2]Volle [3]Abräumen [4]Fehler [5]Kegel GG
//      [6]Kegel G [7]Fehler G [8]Abräumen G [9]Volle G [10]Name G [11]leer
//
// WICHTIG: `schere` und `classic` liefern nur das SATZ-HOLZ — keine Volle/Abräum-Trennung und
// keine Fehlwürfe. Nur `holz` trennt Volle/Abräumen, dafür ohne Satz-Detail.
//
// Welches Layout vorliegt, wird nicht geraten und nicht aus der Sektion geschlossen, sondern
// aus der Antwort selbst bestimmt: erkenneLayout() probiert alle drei und nimmt das, dessen
// Werte gegen die im selben Datensatz mitgelieferte Kegel-/Holz-Summe aufgehen (pruefeSeite).
// Passt keines, bricht der Import ab, statt still falsche Zahlen in die Statistik zu schreiben.

import { teilsatzRanges } from './teilsaetze.js';
import { ABRAEUM_MODI } from './sportwinner-ergebnis.js';
import { buildWettkampf } from './wettkampf-build.js';
import { teamLanesByBahnart } from './roster-import.js';
import { PRESETS, MODUS_GESAMT } from './sportkegeln-presets.js';

const uid = (p) => p + Math.random().toString(36).slice(2, 8);
const txt = (v) => (v == null ? '' : String(v)).trim();
// Zellen kommen als Zahl ODER als String, teils mit HTML aus den Formattern. null = keine Zahl.
const num = (v) => {
  if (v == null) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const m = String(v).replace(/<[^>]*>/g, ' ').match(/-?\d+/);
  return m ? parseInt(m[0], 10) : null;
};
const istZahl = (v) => num(v) != null;
const klarText = (v) => txt(v).replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();

// --- GetSpiel: die Partien einer Auswahl -------------------------------------
//
// Spalten, am echten Ergebnisdienst abgelesen (14 Stück):
//   [0]id_spiel [1]Datum [2]Uhrzeit [3]Gastgeber [4]MP GG [5]MP G [6]Gast [7]SP GG [8]SP G
//   [9]Status ("offen"/"beendet") [10]Bemerkung [11]wertung [12]"Liga / Spieltag" [13]leer
//
// Der Status steht in [9] und ist die EINZIGE verlässliche Auskunft darüber, ob gespielt wurde:
// [4]/[5] sind auch bei einer offenen Partie mit "0" belegt, eine Prüfung auf "ist eine Zahl"
// würde also jede angesetzte Partie als gespielt ausgeben.
const DATUM_RE = /(\d{1,2})\.(\d{1,2})\.(\d{4})/;

export function parseSpielListe(rows) {
  return (Array.isArray(rows) ? rows : [])
    .filter((r) => Array.isArray(r) && txt(r[0]))
    .map((r) => {
      // Datum steht in [1]; als Rückfall die erste datumsförmige Zelle der Zeile.
      const datumZelle = DATUM_RE.test(txt(r[1]))
        ? txt(r[1])
        : (r.find((z) => typeof z === 'string' && DATUM_RE.test(z)) || '');
      const m = datumZelle.match(DATUM_RE);
      const uhrzeit = /^\d{1,2}:\d{2}$/.test(txt(r[2])) ? txt(r[2]) : '';
      const status = klarText(r[9]);
      return {
        idSpiel: txt(r[0]),
        wertung: num(r[11]),
        heim: klarText(r[3]),
        gast: klarText(r[6]),
        heimWert: num(r[4]),
        gastWert: num(r[5]),
        status,
        termin: [datumZelle, uhrzeit].filter(Boolean).join(' · '),
        datum: m ? `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}` : '',
        bemerkung: klarText(r[10]),
        liga: klarText(r[12]),
        gespielt: /beendet/i.test(status),
      };
    });
}

// --- GetSpielerInfo: der Spielbericht ----------------------------------------

// Spalten-Zuordnung je Layout (siehe Kopf). `saetze` steht bereits in Satz-Reihenfolge 1..n —
// beim Gast liest der Ergebnisdienst die Tabelle spiegelverkehrt, dort also rückwärts.
export const LAYOUTS = {
  schere: {
    typ: 'satz',
    gg: { name: 1, saetze: [2, 3, 4, 5], kegel: 7 },
    g: { name: 14, saetze: [13, 12, 11, 10], kegel: 8 },
  },
  classic: {
    typ: 'satz',
    gg: { name: 0, saetze: [1, 2, 3, 4], kegel: 5 },
    g: { name: 15, saetze: [14, 13, 12, 11], kegel: 10 },
  },
  holz: {
    typ: 'summe',
    gg: { name: 1, volle: 2, abr: 3, fehler: 4, kegel: 5 },
    g: { name: 10, volle: 9, abr: 8, fehler: 7, kegel: 6 },
  },
};

// Sieht die Zelle nach einem Namen aus? Ein Satzergebnis tut das nie — der Unterschied trägt
// die Layout-Erkennung, weil sich die Layouts vor allem in der Namensspalte unterscheiden.
const istName = (v) => /\p{L}/u.test(klarText(v));

// Die Werte EINER Seite aus einer Zeile lesen.
function leseSeite(zeile, map, typ) {
  const name = klarText(zeile[map.name]);
  const kegel = num(zeile[map.kegel]);
  if (typ === 'satz') {
    const saetze = map.saetze.map((i) => num(zeile[i])).filter((n) => n != null);
    return { name, kegel, saetze: saetze.map((holz) => ({ holz })) };
  }
  return {
    name,
    kegel,
    volle: num(zeile[map.volle]) || 0,
    abr: num(zeile[map.abr]) || 0,
    fehler: num(zeile[map.fehler]) || 0,
  };
}

// Selbstprüfung: die gelesenen Werte müssen die mitgelieferte Kegel-/Holz-Summe ergeben. Das ist
// der Schutz gegen eine falsche Spaltenzuordnung — ohne ihn würde ein verschobenes Layout
// stillschweigend falsche Zahlen importieren.
export function pruefeSeite(seite, typ) {
  if (seite.kegel == null) return true;            // keine Summenspalte -> nichts zu prüfen
  const summe = typ === 'satz'
    ? seite.saetze.reduce((s, x) => s + (x.holz || 0), 0)
    : (seite.volle || 0) + (seite.abr || 0);
  if (!summe && !seite.kegel) return true;
  return summe === seite.kegel;
}

// Welches Layout liegt vor? Bewusst NICHT aus der Sektion abgeleitet: die Zuordnung
// Sektion -> Layout ist nirgends zugesichert, und ein Fehlgriff wäre in der Statistik nicht
// mehr zu erkennen. Stattdessen werden alle drei Layouts durchprobiert und dasjenige genommen,
// unter dem die meisten Zeilen als Spielerzeile durchgehen: beide Seiten tragen einen Namen UND
// ihre Werte ergeben die mitgelieferte Summe.
export function erkenneLayout(rows) {
  const zeilen = (Array.isArray(rows) ? rows : []).filter((r) => Array.isArray(r) && r.length >= 11);
  if (!zeilen.length) return null;
  let bestes = null;
  let bestPunkte = 0;
  Object.entries(LAYOUTS).forEach(([key, def]) => {
    const punkte = zeilen.reduce((n, z) => {
      const gg = leseSeite(z, def.gg, def.typ);
      const g = leseSeite(z, def.g, def.typ);
      if (!istName(gg.name) || !istName(g.name)) return n;
      return pruefeSeite(gg, def.typ) && pruefeSeite(g, def.typ) ? n + 1 : n;
    }, 0);
    if (punkte > bestPunkte) { bestPunkte = punkte; bestes = key; }
  });
  return bestes;
}

// GetSpielerInfo-Antwort -> Paarungen mit Ergebnissen je Seite.
// Rückgabe: { layout, proSatz, paare:[{ gg, g }], warnungen }
//   gg/g = { name, kegel, saetze:[{holz}] }                         (Satz-Layout)
//          { name, kegel, saetze:[{volle,abr,fehler,holz}] }        (Summen-Layout, je Satz eine Zeile)
//          { name, kegel, saetze:null, gesamt:{volle,abr,fehler} }  (nur Gesamtsummen)
export function parseSpielerInfo(rows, { saetze = 4 } = {}) {
  const alle = (Array.isArray(rows) ? rows : []).filter((r) => Array.isArray(r) && r.length >= 6);
  const layout = erkenneLayout(alle);
  if (!layout) throw new Error('Spielbericht nicht lesbar — unbekanntes Zeilenformat.');
  const def = LAYOUTS[layout];
  const typ = def.typ;
  const warnungen = [];

  // Zeilen ohne Namen sind entweder FOLGEZEILEN einer Paarung (bei manchen Partien steht je
  // Bahn eine Zeile und der Name nur oben) oder Zusatzzeilen — vor allem die Mannschaftssumme
  // am Ende. Unterschieden werden sie am Zahlenanteil: eine reine Bemerkungszeile trägt keine
  // Ergebniswerte. Deshalb hier NICHT nach dem Namen filtern, das würde die Satzzeilen
  // wegwerfen; die Summenzeile fällt stattdessen unten bei der Gruppierung heraus.
  const hatWerte = (p) => ['gg', 'g'].some((s) => (typ === 'satz'
    ? p[s].saetze.length > 0
    : p[s].kegel != null || p[s].volle || p[s].abr));
  const zeilen = alle
    .map((z) => ({ gg: leseSeite(z, def.gg, typ), g: leseSeite(z, def.g, typ) }))
    .filter(hatWerte);
  if (!zeilen.length) throw new Error('Spielbericht enthält keine Spielerzeilen.');

  // Gruppieren: eine neue Paarung beginnt mit einem neuen Namen, namenlose Zeilen hängen an
  // der laufenden. Eine namenlose Zeile OHNE laufende Paarung (oder wenn die schon voll ist)
  // wird verworfen — so verschwindet die Mannschaftssumme, ohne sie kennen zu müssen.
  const gruppen = [];
  zeilen.forEach((p) => {
    const letzte = gruppen[gruppen.length - 1];
    const hatName = istName(p.gg.name) || istName(p.g.name);
    const gleich = letzte && hatName
      && ((p.gg.name && p.gg.name === letzte.gg.name) || (p.g.name && p.g.name === letzte.g.name));
    if (letzte && (!hatName || gleich) && letzte.zeilen.length < saetze) {
      letzte.zeilen.push(p);
      return;
    }
    if (!hatName) return;
    gruppen.push({ gg: p.gg, g: p.g, zeilen: [p] });
  });
  if (!gruppen.length) throw new Error('Spielbericht enthält keine Spielerzeilen.');

  // Erst JETZT die Gegenprobe, und nur auf den Zeilen, die wirklich zu einer Paarung gehören —
  // sonst meldete die Mannschaftssumme jedes Mal einen Fehlalarm.
  gruppen.forEach((gr, gi) => gr.zeilen.forEach((p, zi) => ['gg', 'g'].forEach((s) => {
    if (!pruefeSeite(p[s], typ)) {
      warnungen.push(`Paarung ${gi + 1}${gr.zeilen.length > 1 ? `, Zeile ${zi + 1}` : ''}`
        + `${gr[s].name ? ` (${gr[s].name})` : ''}: Summe passt nicht zur Holzzahl des `
        + 'Ergebnisdienstes — Spaltenzuordnung prüfen.');
    }
  })));

  const proSatz = typ === 'summe' && gruppen.some((gr) => gr.zeilen.length > 1);

  const paare = gruppen.map((gr) => {
    const seite = (s) => {
      const kopf = gr[s];
      if (typ === 'satz') return { name: kopf.name, kegel: kopf.kegel, saetze: kopf.saetze };
      if (proSatz) {
        return {
          name: kopf.name,
          kegel: gr.zeilen.reduce((n, z) => n + (z[s].volle || 0) + (z[s].abr || 0), 0),
          saetze: gr.zeilen.map((z) => ({
            volle: z[s].volle, abr: z[s].abr, fehler: z[s].fehler,
            holz: (z[s].volle || 0) + (z[s].abr || 0),
          })),
        };
      }
      // Nur Gesamtsummen: KEIN Satz-Detail. Bewusst nicht auf vier Sätze verteilt — das wäre
      // erfunden. Der Aufrufer entscheidet, was er damit macht (import-sw-web.js lehnt ab).
      return {
        name: kopf.name,
        kegel: kopf.kegel,
        saetze: null,
        gesamt: { volle: kopf.volle, abr: kopf.abr, fehler: kopf.fehler },
      };
    };
    return { gg: seite('gg'), g: seite('g') };
  });

  if (typ === 'summe' && !proSatz) {
    warnungen.push('Der Ergebnisdienst liefert für diese Partie nur Gesamtsummen je Spieler, '
      + 'keine Satzergebnisse.');
  }
  return { layout, typ, proSatz, paare, warnungen };
}

// --- Satz-Werte -> Satz-Block ------------------------------------------------

// Das Holz eines Satzes aus den Werten des Berichts — egal, in welcher Form er sie nennt.
const satzHolzVon = (w) => (w && w.holz != null
  ? w.holz
  : ((w && w.volle) || 0) + ((w && w.abr) || 0));

// Welche Teilsätze bekommt der importierte Wettkampf?
//
// Die Antwort hängt daran, was der Bericht hergibt, und sie gilt für den ganzen Wettkampf (die
// Teilsatz-Einteilung steht in der Config, nicht am einzelnen Satz):
//
//   • Der Bericht trennt Volle und Abräumen UND das Programm hat genau einen Teilsatz je Seite
//     -> die Teilsätze des Programms, jeder mit seinem exakten Wert.
//   • Sonst (nur Satz-Holz; oder ein Programm wie Bohle mit zwei Volle-Teilsätzen, auf die sich
//     eine Summe nicht eindeutig aufteilen lässt) -> EIN Teilsatz über den ganzen Satz.
//
// Der zweite Fall ist die bewusste Entscheidung gegen jede Schätzung: lieber gar keine
// Teilsatz-Auswertung als eine erfundene.
export function teilsatzPlan(preset, spec) {
  const p = PRESETS[preset];
  if (!p) throw new Error(`Unbekannte Bahnart: ${preset}`);
  const teile = p.teilsaetze || [];
  const volle = teile.filter((m) => !ABRAEUM_MODI.has(m));
  const abraeum = teile.filter((m) => ABRAEUM_MODI.has(m));
  const exakt = spec && !spec.nurHolz && volle.length === 1 && abraeum.length === 1;
  return exakt ? [...teile] : [MODUS_GESAMT];
}

// Aus den Summen EINES Satzes einen Satz-Block bauen — über `overrides`, nicht über erfundene
// Einzelwürfe. Genau darin unterscheidet sich diese Funktion von adoptErgebnisBlock()
// (logic/sportwinner-konflikte.js): dort werden synthetische Würfe gebraucht, damit der
// Konflikt-Abgleich die Fehlerzahl exakt reproduziert; hier ginge dieselbe Synthese als echtes
// Wurfbild in die Statistik ein und würde 9er und Räumer erfinden.
//
// werte: { volle, abr } oder { holz }.
// Verteilt wird NICHTS: entweder passt jeder Wert auf genau einen Teilsatz, oder der Satz hat
// (per teilsatzPlan) nur einen einzigen Teilsatz und bekommt schlicht sein Satzergebnis. Passt
// beides nicht, ist das ein Programmierfehler und kein Grund zu raten -> Abbruch.
export function ergebnisBlock(config, werte) {
  const ranges = teilsatzRanges(config);
  const overrides = ranges.map(() => null);

  if (ranges.length === 1) {
    overrides[0] = satzHolzVon(werte);
  } else if (werte && werte.volle != null && werte.abr != null) {
    const idx = (abraeum) => {
      const treffer = ranges
        .map((r, i) => ({ r, i }))
        .filter(({ r }) => ABRAEUM_MODI.has(r.modus) === abraeum);
      return treffer.length === 1 ? treffer[0].i : -1;
    };
    const iV = idx(false);
    const iA = idx(true);
    if (iV < 0 || iA < 0) {
      throw new Error('Teilsätze passen nicht zum Bericht — ein Satzergebnis wäre zu raten.');
    }
    overrides[iV] = werte.volle || 0;
    overrides[iA] = werte.abr || 0;
  } else {
    throw new Error('Nur Satz-Holz, aber mehrere Teilsätze — siehe teilsatzPlan().');
  }

  return {
    wuerfe: [],            // keine Einzelwürfe — der Ergebnisdienst liefert sie nicht
    kegel: [],
    koenig: [],
    overrides,
    done: true,
  };
}

// --- Partie + Spielbericht -> Import-Spec ------------------------------------

// Formt aus der gewählten Partie (parseSpielListe) und ihrem Spielbericht (parseSpielerInfo)
// dieselbe Zwischenform, die auch parseRoster() liefert — damit views/import-sw-web.js und
// views/import-sportwinner.js beide buildWettkampf() mit gleichen Feldern füttern.
//
// Bewusst NICHT gesetzt: der `sportwinner`-Block. Er ist die Rückschreib-Zuordnung zur DLL und
// trägt LizenzIDen; über den Web-Weg gibt es beides nicht. Sein Fehlen ist zugleich das Signal
// für istLizenzWettkampf() (logic/spieler-identitaet.js), dass hier die manuelle
// „Das bin ich"-Markierung gilt statt einer amtlichen LizenzID-Zuordnung.
export function buildImportSpec(partie, bericht) {
  if (!bericht || !bericht.paare.length) throw new Error('Spielbericht ohne Paarungen.');
  const mannschaften = [
    { id: uid('m'), key: 'GG', name: txt(partie && partie.heim) || 'Heim', lanes: [], spieler: [] },
    { id: uid('m'), key: 'G', name: txt(partie && partie.gast) || 'Gast', lanes: [], spieler: [] },
  ];

  // Die Reihenfolge der Paarungen IST die Team-Position: Paarung 1 = Spieler 1 beider Teams.
  const ergebnisse = {};
  bericht.paare.forEach((paar, i) => {
    const teamPos = i + 1;
    [['gg', 0], ['g', 1]].forEach(([seite, mi]) => {
      const s = paar[seite];
      if (!s || !s.name) return;
      const m = mannschaften[mi];
      m.spieler.push({ teamPos, name: s.name, pass: null, extId: null, slot: i });
      ergebnisse[`${m.id}|${teamPos}`] = {
        saetze: s.saetze, gesamt: s.gesamt || null, kegel: s.kegel,
      };
    });
  });

  const namesByTeamPos = {};
  mannschaften.forEach((m) => m.spieler.forEach((p) => {
    if (p.name) namesByTeamPos[`${m.id}|${p.teamPos}`] = p.name;
  }));

  return {
    name: `${mannschaften[0].name} – ${mannschaften[1].name}`,
    datum: (partie && partie.datum) || new Date().toISOString().slice(0, 10),
    spielerJeMannschaft: Math.max(1, ...mannschaften.map((m) => m.spieler.length)),
    mannschaften,
    namesByTeamPos,
    ergebnisse,
    proSatz: bericht.proSatz || bericht.typ === 'satz',
    // `satz` heisst: der Bericht nennt nur das Satz-HOLZ. Die Volle/Abraeum-Aufteilung ist dann
    // unbekannt — teilsatzPlan() gibt dem Wettkampf deshalb einen einzigen Teilsatz je Satz,
    // und die View sagt dem Nutzer, dass es fuer dieses Spiel keine Teilsatz-Auswertung gibt.
    nurHolz: bericht.typ === 'satz',
    idSpiel: (partie && partie.idSpiel) || null,
    warnungen: [...bericht.warnungen],
  };
}

// Stammt dieser Wettkampf aus dem Web-Import?
//
// Wichtig fuer die Teilen-Sperre: ein so importierter Wettkampf traegt die KLARNAMEN der Mit-
// und Gegenspieler, und die liegen bewusst nur lokal (siehe sync.linkEigenesErgebnis). Ihn zu
// teilen wuerde genau diese Namen ueber Beitritts-/Zuschauercode und das OBS-Overlay an Dritte
// ausliefern — an Leute, die von dieser App nichts wissen. Deshalb sperren wettkampf-hub.js
// und die Overlay-Sektion das Teilen fuer diese Wettkaempfe.
export function istWebImport(wettkampf) {
  if (!wettkampf) return false;
  return wettkampf.quelle === 'sportwinner-web' || !!wettkampf.swWeb;
}

// --- Spec -> fertiger, gefuellter Wettkampf ----------------------------------

// Aus dem Import-Spec den kompletten Wettkampf samt Durchgaengen bauen UND die Ergebnisse
// eintragen. Bewusst hier und nicht im View: das ist der eigentliche Import, und er soll
// ohne DOM pruefbar sein (die View macht danach nur noch speichern und uebertragen).
//
// opt = { playedLanes[], anlageId, anlageName, anlageBahnen[] }
// Rueckgabe: { wettkampf, games, nurSatzHolz }
//   nurSatzHolz = true, wenn der Bericht keine Volle/Abraeum-Trennung hergab und deshalb je Satz
//   nur EIN Teilsatz mit dem Satzergebnis entstanden ist (teilsatzPlan).
export function buildImportWettkampf(spec, opt = {}) {
  const played = (opt.playedLanes || []).slice().sort((a, b) => a - b);
  const p = PRESETS[spec.preset];
  if (!p) throw new Error(`Unbekannte Bahnart: ${spec.preset}`);
  const split = teamLanesByBahnart(spec.preset, played, spec.mannschaften.length);
  const teilsaetze = teilsatzPlan(spec.preset, spec);
  const nurSatzHolz = teilsaetze.length === 1 && teilsaetze[0] === MODUS_GESAMT;

  const { wettkampf, games } = buildWettkampf({
    name: spec.name,
    datum: spec.datum,
    preset: spec.preset,
    saetze: p.saetze,
    wuerfeProSatz: p.wuerfeProSatz,
    teilsaetze,
    bahnwechsel: p.bahnwechsel,
    anlageId: opt.anlageId || null,
    anlageName: opt.anlageName || '',
    anlageBahnen: opt.anlageBahnen || [],
    playedLanes: played,
    mannschaften: spec.mannschaften.map((m, i) => ({ id: m.id, name: m.name, lanes: split[i] || [] })),
    spielerJeMannschaft: spec.spielerJeMannschaft,
    namesByTeamPos: spec.namesByTeamPos,
    quelle: 'sportwinner-web',
  });

  games.forEach((g) => {
    const c = g.config;
    // buildWettkampf liefert Spiele OHNE Erfassung (die legt sonst spiel-laufend.js beim ersten
    // Oeffnen an, initErfassung). Ein importiertes Spiel wird nie erfasst — die Struktur muss
    // also hier entstehen, sonst haette es gar keinen Wurfspeicher.
    g.erfassung = {
      aktiverSpieler: 0,
      aktiverSatz: 0,
      bloecke: c.spielerListe.map(() => Array.from({ length: c.saetze }, () => ({
        wuerfe: [], kegel: [], koenig: [], overrides: c.teilsaetze.map(() => null), done: false,
      }))),
    };
    // Adressiert ueber mannschaftId|teamPos, NICHT ueber die Reihenfolge: im Paarkreuz sitzt
    // derselbe Spieler in jedem Durchgang auf einem anderen Index.
    c.spielerListe.forEach((sp, i) => {
      const erg = spec.ergebnisse[`${sp.mannschaftId}|${sp.teamPos}`];
      if (!erg || !erg.saetze) return;
      erg.saetze.slice(0, c.saetze).forEach((w, satz) => {
        g.erfassung.bloecke[i][satz] = ergebnisBlock(c, w);
      });
    });
    g.status = 'beendet';
  });

  wettkampf.status = 'beendet';
  wettkampf.swWeb = { idSpiel: spec.idSpiel, nurSatzHolz };
  games.forEach((g) => { g.swWeb = wettkampf.swWeb; });
  return { wettkampf, games, nurSatzHolz };
}
