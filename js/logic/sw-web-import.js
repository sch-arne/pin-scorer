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
// nur das Satz-Holz, dann wird auch nur das Satzergebnis gesetzt (`satzOverride`, siehe
// logic/holz.js) — die Teilsätze bleiben LEER. Der Wettkampf bekommt trotzdem die Teilsätze
// seiner Bahnart, damit ein importiertes Spiel dieselbe Form hat wie ein selbst erfasstes und
// sich die Aufteilung später von Hand nachtragen lässt. Erfunden wird sie nicht: eine
// Auswertung nach Teilsätzen gibt es für so ein Spiel erst, wenn jemand sie nachträgt.
//
// BAHNEN
// ------
// Der Ergebnisdienst nummeriert die vier Ergebnisspalten je Spieler von 1 bis 4. Das sind nicht
// die Sätze, sondern die BAHNEN der Partie in ihrer Reihenfolge — Spalte 1 ist die erste
// bespielte Bahn der Anlage, auch wenn die die Nummer 5 trägt. Welchen Satz ein Spieler dort
// gespielt hat, hängt an seiner Startbahn und am Bahnwechsel; bei verschiedenen Startbahnen ist
// die Spalte also NICHT der Satz-Index. buildImportWettkampf dreht die Zuordnung deshalb über
// denselben Bahnplan um, den buildSportwinnerPush zum Rückschreiben benutzt (bahnSlot()).
//
// ZEILENFORMATE
// -------------
// Die Antworten sind reine Arrays ohne Feldnamen, und das Layout hängt an Sektion und Wertung.
// Alle drei Formen sind aus den `columns`-Definitionen des `detailFormatter` abgelesen und am
// echten Ergebnisdienst geprüft (Referenzpartie 328202, siehe tests/fixtures/):
//
//   schere  — Sektion ≠ Classic (Schere/Bohle), 18 Spalten:
//      [0]Vermerk GG [1]Name GG [2..5]Satz 1-4 GG [6]EWP GG [7]Holz GG
//      [8]Holz G [9]EWP G [10..13]Satz 4-1 G (RÜCKWÄRTS) [14]Name G [15]Vermerk G
//      [16]geteilt GG [17]geteilt G
//
//   classic — Classic mit Punktwertung, 16 Spalten:
//      [0]Name GG [1..4]Satz 1-4 GG [5]Kegel GG [6]SP [7]MP
//      [8]MP G [9]SP G [10]Kegel G [11..14]Satz 4-1 G (RÜCKWÄRTS) [15]Name G
//
//   holz    — Classic mit Holzwertung, 12 Spalten:
//      [0]leer [1]Name GG [2]Volle [3]Abräumen [4]Fehler [5]Kegel GG
//      [6]Kegel G [7]Fehler G [8]Abräumen G [9]Volle G [10]Name G [11]leer
//
// TEILSTAENDE
// -----------
// Importiert wird nicht nur die beendete Partie: auch eine, die gerade LAEUFT oder auf die
// Abnahme wartet (parseSpielListe -> importierbar). Der Bericht nennt dann fuer noch nicht
// bespielte Bahnen leere Zellen — und die bleiben POSITIONSTREU stehen (`null` an ihrer Stelle),
// statt die Liste zusammenzuschieben: Spalte k ist die k-te bespielte Bahn, nicht der k-te
// gespielte Satz. Wer auf Bahn 5 von 5-8 anfaengt, fuellt zuerst die letzte Spalte; eine
// gestauchte Liste haette sein erstes Ergebnis auf Bahn 5 dem Satz zugeordnet, der auf Bahn 8
// gespielt wird. Ein zweiter Import derselben Partie ergaenzt dann nur, was noch fehlt
// (trageErgebnisseEin mit `nurLeere`).
//
// GETEILTE POSITIONEN (Auswechslung, vorzeitiges Ende)
// ---------------------------------------------------
// Eine Position muss nicht einem Spieler gehören. Wird gewechselt, bespielen zwei Leute je
// einen Teil der vier Bahnen — und der Bericht sagt das auf DREI verschiedene Weisen, je
// Sektion. Alle drei sind an echten Partien abgelesen (siehe tests/fixtures/):
//
//   1. classic — der Eingewechselte bekommt eine EIGENE ZEILE, die nur auf SEINER Seite einen
//      Namen trägt; die Gegenseite der Zeile ist komplett leer. Seine Bahnen ergänzen die des
//      Ausgewechselten lückenlos, das Positionsholz ist die Summe beider Zeilen.
//      (1. Bundesliga Classic, Spieltag 1+2: 6 von 10 Partien — das ist der Normalfall.)
//
//   2. schere mit Doppel-Flag — [16] (Gastgeber) bzw. [17] (Gast) trägt eine „1". Das ist keine
//      Zierde, sondern die Angabe des Dienstes selbst: sein eigener Client verbindet dann die
//      Holz- und EWP-Zelle dieser Zeile per `rowspan: 2` über ZWEI Zeilen (`teamDoppeltGG`/
//      `teamDoppeltG` in sportwinner.js). Heißt: diese Zeile und die nächste sind EINE Position,
//      und die Holz-Zelle der ERSTEN Zeile ist schon die Summe beider.
//
//   3. schere ohne Doppel-Flag — der Dienst schreibt alle vier Bahnen unter den Namen dessen,
//      der angefangen hat, und hängt den Eingewechselten als ergebnislose VERMERKZEILE an das
//      Ende des Berichts. Wer wirklich welche Bahn gespielt hat, steht dann nicht im Bericht;
//      der einzige Hinweis sind die Buchstaben in [0]/[15] und die Bemerkung der Partie.
//
// Die Buchstaben in [0]/[15] stehen auf der Seite des betroffenen Spielers — aus den Daten
// abgelesen und von der Bemerkung der Partie gestützt: `a` beim Ausgewechselten, `e` beim
// Eingewechselten, `b` bei einem Abbruch. Eine Position mit `a` oder `b` trägt deshalb Holz,
// das nicht einer Person allein gehört (Fall 3) — `eindeutig: false`. Genau daran hängt, ob
// sich die Zeile in die eigene Konto-Statistik übernehmen lässt: ein `spiel_ergebnis` ist ein
// Spiel EINER Person, und fremde Bahnen haben darin nichts zu suchen.
//
// Erfunden wird auch hier nichts: in Fall 1 und 2 sind die Bahnen je Spieler bekannt und werden
// zusammengelegt (`teiler`), in Fall 3 sind sie es nicht — dann bleibt das Holz, wie der Dienst
// es meldet, und der Nutzer bekommt es gesagt.
//
// WICHTIG: `schere` und `classic` liefern nur das SATZ-HOLZ — keine Volle/Abräum-Trennung und
// keine Fehlwürfe. Nur `holz` trennt Volle/Abräumen, dafür ohne Satz-Detail.
//
// Welches Layout vorliegt, wird nicht geraten und nicht aus der Sektion geschlossen, sondern
// aus der Antwort selbst bestimmt: erkenneLayout() probiert alle drei und nimmt das, dessen
// Werte gegen die im selben Datensatz mitgelieferte Kegel-/Holz-Summe aufgehen (pruefeSeite).
// Passt keines, bricht der Import ab, statt still falsche Zahlen in die Statistik zu schreiben.

import { teilsatzRanges } from './teilsaetze.js';
import { blockHatInhalt } from './holz.js';
import { gameBaseStatus, wettkampfBaseStatus } from './wettkampf.js';
import { ABRAEUM_MODI, bahnSlot, bahnplanOf } from './sportwinner-ergebnis.js';
import { buildWettkampf } from './wettkampf-build.js';
import { defaultWertung } from './wettkampf-wertung.js';
import { teamLanesByBahnart } from './roster-import.js';
import { PRESETS } from './sportkegeln-presets.js';

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
// ABER: die Spaltenzahl haengt am Dienst. `dskb` (nur Bundesligen) schickt 13 Spalten und
// KEINE wertung — dort steht an [11] schon die "Liga / Spieltag"-Zeile. Mit festen Indizes
// wurde daraus eine Wertung "2" (aus "2. Bundesliga Nord" gelesen) und eine leere Liga.
// Deshalb werden beide Felder am INHALT erkannt: die Wertung ist eine reine Zahl, die
// Liga-Zeile traegt Schraegstriche. Fehlt die Wertung, ist das kein Mangel — spielbericht()
// sendet dann 0, und genau das erwartet der Dienst fuer die Schere.
//
// Der Status steht in [9] und ist die EINZIGE verlässliche Auskunft darüber, ob gespielt wurde:
// [4]/[5] sind auch bei einer offenen Partie mit "0" belegt, eine Prüfung auf "ist eine Zahl"
// würde also jede angesetzte Partie als gespielt ausgeben.
//
// Drei Lager, und der Unterschied zwischen den ersten beiden ist nur die VOLLSTAENDIGKEIT:
//   fertig  — "beendet", "abnahmebereit": alle Sätze stehen im Bericht.
//   laufend — "wird gespielt", "unterbrochen": der Bericht zeigt einen Zwischenstand.
//   sonst   — "offen"/angesetzt/abgesagt: es gibt nichts zu holen.
// Importierbar sind die ersten beiden. Ein Zwischenstand ist kein halbes Spiel, sondern ein
// vollstaendiger Wettkampf mit noch leeren Saetzen — nachgeholt wird er durch einen zweiten
// Import derselben Partie, der nur die Luecken fuellt.
const DATUM_RE = /(\d{1,2})\.(\d{1,2})\.(\d{4})/;
const STATUS_FERTIG = /beendet|abnahme|gewertet|bestätigt|bestaetigt/i;
const STATUS_LAUFEND = /wird gespielt|läuft|laeuft|laufend|unterbrochen|begonnen/i;

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
      // Reine Zahl an [11] -> Wertung; steht dort Text, kennt dieser Dienst die Spalte nicht.
      const wertungZelle = txt(r[11]);
      // "Liga / Spieltag": die letzte Zelle mit Schraegstrich und Buchstaben.
      const ligaZelle = [...r].reverse().find((z) => {
        const t = klarText(z);
        return t.includes('/') && /\p{L}/u.test(t);
      });
      return {
        idSpiel: txt(r[0]),
        wertung: /^\d+$/.test(wertungZelle) ? Number(wertungZelle) : null,
        heim: klarText(r[3]),
        gast: klarText(r[6]),
        heimWert: num(r[4]),
        gastWert: num(r[5]),
        status,
        termin: [datumZelle, uhrzeit].filter(Boolean).join(' · '),
        datum: m ? `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}` : '',
        bemerkung: klarText(r[10]),
        liga: klarText(ligaZelle),
        gespielt: STATUS_FERTIG.test(status),
        laufend: !STATUS_FERTIG.test(status) && STATUS_LAUFEND.test(status),
        importierbar: STATUS_FERTIG.test(status) || STATUS_LAUFEND.test(status),
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
    // Die Randspalten, die der Dienst-Client selbst auswertet — siehe Kopf, GETEILTE POSITIONEN.
    vermerk: { gg: 0, g: 15 },
    doppelt: { gg: 16, g: 17 },
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

// Die Vermerk-Buchstaben aus [0]/[15], siehe Kopf. Erkannt wird GENAU ein Buchstabe — bei den
// meisten Partien ist die Spalte leer, und alles Längere ist kein Vermerk, sondern etwas, das
// wir nicht kennen (und dann auch nicht deuten).
export const VERMERK_TEXT = {
  a: 'ausgewechselt',
  e: 'eingewechselt',
  b: 'abgebrochen',
};
const vermerkVon = (v) => {
  const s = klarText(v).toLowerCase();
  return /^[a-z]$/.test(s) ? s : '';
};

// Das Doppel-Flag aus [16]/[17]: „diese Zeile und die nächste sind eine Position".
const doppeltVon = (v) => klarText(v) === '1';

// „Nachname, Vorname" -> „Vorname Nachname".
//
// Der Ergebnisdienst meldet jeden Spieler in Listenform, die App schreibt Namen aber überall
// so, wie man sie sagt — der Brücken-Import setzt sie aus vorname+nachname genauso zusammen
// (roster-import.js). Ohne diese Drehung stünde in der Aufstellung, in der Rangliste und im
// Overlay eines importierten Spiels eine andere Namensform als in jedem selbst erfassten.
//
// Gedreht wird nur bei GENAU EINEM Komma mit Text auf beiden Seiten. Alles andere („Meyer",
// „Meyer, Hans, jun.") bleibt unverändert stehen: dort ist nicht sicher, welcher Teil der
// Vorname wäre, und ein falsch zusammengesetzter Name ist schlechter als der rohe.
export function spielerName(roh) {
  const s = klarText(roh);
  const teile = s.split(',');
  if (teile.length !== 2) return s;
  const nach = teile[0].trim();
  const vor = teile[1].trim();
  return nach && vor ? `${vor} ${nach}` : s;
}

// Die Werte EINER Seite aus einer Zeile lesen.
function leseSeite(zeile, map, typ) {
  const name = spielerName(zeile[map.name]);
  const kegel = num(zeile[map.kegel]);
  if (typ === 'satz') {
    // POSITIONSTREU, siehe Kopf (TEILSTAENDE): die nicht gespielte Bahn bleibt als `null` an
    // ihrer Stelle. Leer ist dabei auch die 0 — einen ganzen Satz mit null Holz gibt es nicht,
    // wohl aber eine 0 als Platzhalter fuer eine Bahn, die noch aussteht.
    return {
      name,
      kegel,
      saetze: map.saetze.map((i) => {
        const holz = num(zeile[i]);
        return holz ? { holz } : null;
      }),
    };
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
    ? (seite.saetze || []).reduce((s, x) => s + ((x && x.holz) || 0), 0)
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

// --- Zeilen -> Positionen ----------------------------------------------------

// Eine Rohzeile mit beiden Seiten UND den Randsignalen des Dienstes.
function leseZeile(zeile, def) {
  return {
    gg: leseSeite(zeile, def.gg, def.typ),
    g: leseSeite(zeile, def.g, def.typ),
    vermerk: {
      gg: def.vermerk ? vermerkVon(zeile[def.vermerk.gg]) : '',
      g: def.vermerk ? vermerkVon(zeile[def.vermerk.g]) : '',
    },
    doppelt: {
      gg: def.doppelt ? doppeltVon(zeile[def.doppelt.gg]) : false,
      g: def.doppelt ? doppeltVon(zeile[def.doppelt.g]) : false,
    },
  };
}

// Trägt die Zeile überhaupt Ergebniswerte? Zeilen ohne Namen sind entweder FOLGEZEILEN einer
// Position (beim `holz`-Layout steht je Bahn eine Zeile und der Name nur oben) oder
// Zusatzzeilen — vor allem die Mannschaftssumme am Ende. Unterschieden werden sie hier am
// Zahlenanteil, nicht am Namen: nach dem Namen zu filtern würde die Satzzeilen wegwerfen.
const hatWerte = (p, typ) => ['gg', 'g'].some((s) => (typ === 'satz'
  ? (p[s].saetze || []).some((x) => x != null)
  : p[s].kegel != null || p[s].volle || p[s].abr));

// Eine Position, die noch gar nicht angetreten ist, trägt zwei NAMEN und keine Werte. Sie muss
// stehen bleiben: die Reihenfolge der Positionen IST die Team-Position (buildImportSpec), eine
// übersprungene Zeile würde alle folgenden verschieben. Verlangt sind beide Namen — die
// Mannschaftssumme trägt keinen, eine Vermerkzeile höchstens einen.
const paarung = (p) => istName(p.gg.name) && istName(p.g.name);

// Gehört diese Zeile noch zur laufenden Position — nach ihrer FORM?
//
// Das Doppel-Flag des Dienstes wird hier nicht geprüft: es ist die verlässlichere Angabe und
// entscheidet deshalb schon in bildeBloecke, bevor überhaupt geraten werden muss. Bleiben drei
// Formen:
//
//   halb     — genau eine Seite benannt, die andere Seite ganz leer: Fall 1 im Kopf (classic).
//   namenlos — keine Seite benannt, aber Werte: Satz-je-Zeile beim `holz`-Layout.
//   gleich   — derselbe Name wie im Blockkopf. NUR beim `summe`-Layout, wo mehrere Zeilen je
//              Position die Regel sind; bei `satz` wäre es ein Fehlgriff — dort sitzt derselbe
//              Spieler auch auf einer ZWEITEN, eigenen Position (Damen-Bundesliga: Sonnhalter
//              teilt Position 3 und 4 mit zwei verschiedenen Leuten). Genau daran verschwand
//              vorher eine Spielerin samt ihrem Holz.
function gehoertDazu(p, block, def, saetze) {
  if (!block || block.zeilen.length >= saetze) return false;
  const nurEine = istName(p.gg.name) !== istName(p.g.name);
  const leer = (s) => !istName(p[s].name) && !(p[s].saetze || []).some((x) => x != null);
  if (nurEine && (leer('gg') || leer('g'))) return true;
  if (!istName(p.gg.name) && !istName(p.g.name)) return true;
  if (def.typ === 'summe') {
    return ['gg', 'g'].some((s) => p[s].name && p[s].name === block.zeilen[0][s].name);
  }
  return false;
}

// Die Positionen eines Berichts. Rückgabe: [{ zeilen:[...], doppelt:boolean }].
function bildeBloecke(zeilen, def, saetze) {
  const bloecke = [];
  // Der Umschalter des Dienst-Clients: die erste geflaggte Zeile ÖFFNET die Verbindung, die
  // zweite schließt sie wieder (siehe Kopf). Je Seite eigenständig — geflaggt ist in der Praxis
  // beides zugleich, aber verlassen muss man sich darauf nicht.
  let offenGG = false;
  let offenG = false;
  zeilen.forEach((p) => {
    const letzte = bloecke[bloecke.length - 1];
    const offen = offenGG || offenG;
    if (p.doppelt.gg) offenGG = !offenGG;
    if (p.doppelt.g) offenG = !offenG;
    if (letzte && offen) { letzte.zeilen.push(p); letzte.doppelt = true; return; }
    if (gehoertDazu(p, letzte, def, saetze)) { letzte.zeilen.push(p); return; }
    bloecke.push({ zeilen: [p], doppelt: false });
  });
  return bloecke;
}

// Eine Seite EINER Position zusammenlegen (nur `satz`-Layouts — beim `summe`-Layout ist eine
// Folgezeile ein Satz, keine zweite Person, und das macht seiteSumme weiter unten).
//
// Die Bahnen der Beteiligten ergänzen sich lückenlos: wer die ersten zwei gespielt hat, hat die
// letzten zwei nicht. Zusammengelegt wird deshalb POSITIONSTREU — Bahn k bleibt Bahn k, egal in
// welcher Zeile ihr Wert stand. Beansprucht doch einmal eine zweite Zeile dieselbe Bahn, gewinnt
// die erste und die Kollision wird gemeldet, statt stillschweigend überschrieben.
//
// Das Positionsholz: beim Doppel-Flag steht es schon in der Kopfzeile (der Dienst verbindet die
// Zelle über beide Zeilen), sonst ist es die Summe der Zeilen. Beides am echten Bericht geprüft.
function seiteSatz(block, s, kollisionen) {
  const spalten = block.zeilen[0][s].saetze.length;
  const werte = Array.from({ length: spalten }, () => null);
  const beitraege = [];
  let kegelKopf = null;
  let kegelSumme = null;
  block.zeilen.forEach((p, zi) => {
    const seite = p[s];
    if (zi === 0) kegelKopf = seite.kegel;
    if (seite.kegel != null) kegelSumme = (kegelSumme || 0) + seite.kegel;
    const bahnen = [];
    (seite.saetze || []).forEach((w, bi) => {
      if (!w || bi >= spalten) return;
      if (werte[bi] == null) { werte[bi] = w; bahnen.push(bi); } else kollisionen.push(bi + 1);
    });
    // Ein Name ohne eigene Bahn zählt nur in der Kopfzeile — dort ist es die noch nicht
    // angetretene Position. In einer Folgezeile ist es die leere Gegenseite einer
    // Wechselzeile, und die ist keine Person dieser Position.
    if (istName(seite.name) && (zi === 0 || bahnen.length)) {
      beitraege.push({ name: seite.name, bahnen });
    }
  });
  const namen = beitraege.map((b) => b.name);
  const vermerke = [...new Set(block.zeilen.map((p) => p.vermerk[s]).filter(Boolean))];
  return {
    name: namen.join(' / '),
    namen,
    // `teiler` nur, wenn es wirklich mehrere sind — der Normalfall bleibt schlank.
    teiler: namen.length > 1 ? beitraege : null,
    vermerke,
    // Gehört dieses Holz genau EINER Person? Fall 3 aus dem Kopf sagt nein, obwohl nur ein Name
    // dasteht — daran hängt die Übernahme in die Konto-Statistik.
    //
    // Nur `a` (ausgewechselt) macht die Zeile uneindeutig: dort kam jemand für ihn, und dessen
    // Bahnen stecken im selben Holz. Ein `b` (abgebrochen) dagegen bleibt eindeutig — wer
    // abbricht, wird nicht ersetzt, sein Holz ist sein eigenes, nur eben kurz.
    eindeutig: namen.length <= 1 && !vermerke.includes('a'),
    kegel: block.doppelt ? kegelKopf : kegelSumme,
    saetze: werte,
  };
}

// GetSpielerInfo-Antwort -> POSITIONEN mit Ergebnissen je Seite.
//
// Eine Position, nicht eine Zeile: bei einem Wechsel stehen zwei Zeilen für eine Position, und
// zusammengelegt werden sie hier (siehe Kopf, GETEILTE POSITIONEN). Die Reihenfolge der
// Positionen IST die Team-Position — eine Zeile zu viel verschiebt alle folgenden Spieler.
//
// Rückgabe: { layout, typ, proSatz, paare:[{ gg, g }], warnungen, hinweise }
//   gg/g = { name, namen, teiler, vermerke, eindeutig, kegel, saetze }
//     name      — alle Beteiligten, mit „ / " verbunden (meist genau einer)
//     namen     — dieselben einzeln, in Spielreihenfolge
//     teiler    — [{ name, bahnen:[Index] }], nur bei MEHR als einem Beteiligten
//     vermerke  — die Buchstaben aus [0]/[15], siehe Kopf
//     eindeutig — gehört dieses Holz genau EINER Person? Daran hängt die Konto-Statistik.
//     saetze    — [{holz}] je Bahn, LÜCKENTREU (null = nicht bespielt)   (Satz-Layout)
//                 [{volle,abr,fehler,holz}] je Satz          (Summen-Layout, Satz je Zeile)
//                 null, dazu gesamt:{volle,abr,fehler}       (nur Gesamtsummen)
//   warnungen — der Bericht passt nicht zu sich selbst (Spaltenzuordnung prüfen)
//   hinweise  — Wechsel/Abbruch; hinweisTexte() macht Sätze daraus
export function parseSpielerInfo(rows, { saetze = 4 } = {}) {
  const alle = (Array.isArray(rows) ? rows : []).filter((r) => Array.isArray(r) && r.length >= 6);
  // GAR KEINE Zeilen ist etwas anderes als „Zeilen in unbekannter Form" und braucht eine eigene
  // Meldung: der Ergebnisdienst antwortet auf GetSpielerInfo auch dann mit HTTP 200 und einem
  // LEEREN Koerper, wenn er die Anfrage ablehnt (am 26.09.2026 fing er an, den bis dahin
  // gesendeten leeren `thumbmark` zu sperren — siehe supabase/functions/sportwinner-proxy).
  // Die alte Meldung schickte in genau diesem Fall auf die falsche Fahndung: sie las sich wie
  // eine geaenderte Tabellenform, obwohl ueberhaupt nichts angekommen war.
  if (!alle.length) {
    throw new Error('Der Ergebnisdienst hat zu dieser Partie keine Zeile geliefert. '
      + 'Entweder ist der Spielbericht dort noch nicht veröffentlicht — oder der Dienst hat die '
      + 'Anfrage abgelehnt (dann hilft nur ein Blick in die Serverfunktion, nicht ein neuer Versuch).');
  }
  const layout = erkenneLayout(alle);
  if (!layout) throw new Error('Spielbericht nicht lesbar — unbekanntes Zeilenformat.');
  const def = LAYOUTS[layout];
  const typ = def.typ;
  const warnungen = [];
  const hinweise = [];

  // Zeilen, die KEINE Position sind, fallen hier heraus: die Mannschaftssumme (kein Name) und
  // die Vermerkzeilen des Dienstes (ein Name, kein Ergebnis — Fall 3 im Kopf). Weggeworfen wird
  // dabei nur die Summe; der Vermerk wird festgehalten, denn er ist die einzige Auskunft über
  // einen Wechsel, den der Bericht sonst verschweigt.
  const zeilen = [];
  alle.map((z) => leseZeile(z, def)).forEach((p) => {
    if (hatWerte(p, typ) || paarung(p)) { zeilen.push(p); return; }
    ['gg', 'g'].forEach((s) => {
      if (istName(p[s].name)) {
        hinweise.push({ art: 'vermerk', seite: s, name: p[s].name, vermerk: p.vermerk[s] });
      }
    });
  });
  if (!zeilen.length) throw new Error('Spielbericht enthält keine Spielerzeilen.');

  const bloecke = bildeBloecke(zeilen, def, saetze);
  if (!bloecke.length) throw new Error('Spielbericht enthält keine Spielerzeilen.');

  const proSatz = typ === 'summe' && bloecke.some((b) => b.zeilen.length > 1);

  // Beim `summe`-Layout ist eine Folgezeile ein SATZ, keine zweite Person — dort bleibt die
  // alte Auswertung. Nur `satz`-Layouts legen geteilte Positionen zusammen (seiteSatz).
  function seiteSumme(block, s) {
    const kopf = block.zeilen[0][s];
    if (proSatz) {
      return {
        name: kopf.name,
        namen: istName(kopf.name) ? [kopf.name] : [],
        teiler: null,
        vermerke: [],
        eindeutig: true,
        kegel: block.zeilen.reduce((n, z) => n + (z[s].volle || 0) + (z[s].abr || 0), 0),
        saetze: block.zeilen.map((z) => ({
          volle: z[s].volle, abr: z[s].abr, fehler: z[s].fehler,
          holz: (z[s].volle || 0) + (z[s].abr || 0),
        })),
      };
    }
    // Nur Gesamtsummen: KEIN Satz-Detail. Bewusst nicht auf vier Sätze verteilt — das wäre
    // erfunden. Der Aufrufer entscheidet, was er damit macht (import-sw-web.js lehnt ab).
    return {
      name: kopf.name,
      namen: istName(kopf.name) ? [kopf.name] : [],
      teiler: null,
      vermerke: [],
      eindeutig: true,
      kegel: kopf.kegel,
      saetze: null,
      gesamt: { volle: kopf.volle, abr: kopf.abr, fehler: kopf.fehler },
    };
  }

  const paare = bloecke.map((block, bi) => {
    const seite = (s) => {
      const kollisionen = [];
      const out = typ === 'satz' ? seiteSatz(block, s, kollisionen) : seiteSumme(block, s);
      const pos = `Position ${bi + 1}`;
      const wer = out.name ? ` (${out.name})` : '';
      // Die Gegenprobe gegen die mitgelieferte Holzzahl.
      //
      // Bei `satz`-Layouts auf der ZUSAMMENGELEGTEN Position: zeilenweise geprüft meldete eine
      // geteilte Position jedes Mal Fehlalarm, weil in der Kopfzeile die Summe beider Spieler
      // steht und in den Bahnspalten nur die Hälfte davon.
      //
      // Beim `summe`-Layout dagegen weiter ZEILENWEISE: dort ist eine Folgezeile ein Satz, und
      // jede Zeile trägt ihre eigene Volle/Abräum-Summenspalte. Auf dem Aggregat gäbe es die
      // Felder gar nicht, die die Probe braucht.
      if (typ === 'satz') {
        if (!pruefeSeite(out, typ)) {
          warnungen.push(`${pos}${wer}: Summe passt nicht zur Holzzahl des Ergebnisdienstes `
            + '— Spaltenzuordnung prüfen.');
        }
      } else {
        block.zeilen.forEach((p, zi) => {
          if (pruefeSeite(p[s], typ)) return;
          warnungen.push(`${pos}${block.zeilen.length > 1 ? `, Zeile ${zi + 1}` : ''}${wer}: `
            + 'Summe passt nicht zur Holzzahl des Ergebnisdienstes — Spaltenzuordnung prüfen.');
        });
      }
      if (kollisionen.length) {
        warnungen.push(`${pos}${wer}: zwei Zeilen nennen ein Ergebnis für Bahn `
          + `${[...new Set(kollisionen)].join(', ')} — die erste gilt.`);
      }
      if (out.teiler) {
        hinweise.push({
          art: 'geteilt', seite: s, position: bi + 1, name: out.name, teiler: out.teiler,
        });
      }
      out.vermerke.forEach((v) => hinweise.push({
        art: 'markiert', seite: s, position: bi + 1, name: out.name, vermerk: v,
      }));
      return out;
    };
    return { gg: seite('gg'), g: seite('g') };
  });

  if (typ === 'summe' && !proSatz) {
    warnungen.push('Der Ergebnisdienst liefert für diese Partie nur Gesamtsummen je Spieler, '
      + 'keine Satzergebnisse.');
  }
  return { layout, typ, proSatz, paare, warnungen, hinweise };
}

// Die Hinweise aus parseSpielerInfo als lesbare Sätze — bewusst getrennt von `warnungen`:
// ein Wechsel ist kein Fehler im Bericht, sondern ein Vorgang im Spiel, den der Nutzer kennen
// muss. Die Namen der Mannschaften kommen von der Partie, damit „Gastgeber"/„Gast" nicht
// geraten werden müssen.
export function hinweisTexte(hinweise, { heim = 'Gastgeber', gast = 'Gast' } = {}) {
  const team = (s) => (s === 'gg' ? heim : gast);
  return (hinweise || []).map((h) => {
    if (h.art === 'geteilt') {
      const wer = h.teiler
        .map((t) => `${t.name} (Bahn ${t.bahnen.map((b) => b + 1).join('+') || '—'})`)
        .join(', ');
      return `🔄 ${team(h.seite)}, Position ${h.position}: zwei Spieler geteilt — ${wer}. `
        + 'Das Positionsholz stimmt exakt; in die eigene Konto-Statistik lässt sich eine '
        + 'geteilte Position nicht übernehmen.';
    }
    if (h.art === 'markiert') {
      const was = VERMERK_TEXT[h.vermerk] || `Vermerk „${h.vermerk}"`;
      if (h.vermerk === 'a') {
        return `🔄 ${team(h.seite)}, Position ${h.position}: ${h.name} ist dort als ${was} `
          + 'vermerkt, der Bericht nennt aber nur EINEN Satz Ergebnisse. In diesem Holz steckt '
          + 'dann auch das des Ersatzspielers — wer welche Bahn gespielt hat, sagt der '
          + 'Ergebnisdienst nicht. Deshalb keine Übernahme in die Konto-Statistik.';
      }
      if (h.vermerk === 'b') {
        return `🔄 ${team(h.seite)}, Position ${h.position}: ${h.name} hat das Spiel `
          + 'abgebrochen. Die nicht bespielten Bahnen bleiben leer — das Holz der gespielten '
          + 'stimmt exakt.';
      }
      return `🔄 ${team(h.seite)}, Position ${h.position}: ${h.name} — ${was}.`;
    }
    const was = VERMERK_TEXT[h.vermerk] || (h.vermerk ? `Vermerk „${h.vermerk}"` : 'ohne Ergebnis');
    return `🔄 ${team(h.seite)}: ${h.name} steht als ${was} im Bericht, ohne eigenes Ergebnis. `
      + 'Die dort gespielten Bahnen zählen beim Spieler, der angefangen hat.';
  });
}

// --- Satz-Werte -> Satz-Block ------------------------------------------------

// Das Holz eines Satzes aus den Werten des Berichts — egal, in welcher Form er sie nennt.
const satzHolzVon = (w) => (w && w.holz != null
  ? w.holz
  : ((w && w.volle) || 0) + ((w && w.abr) || 0));

// Welche Teilsätze bekommt der importierte Wettkampf? Die der BAHNART — immer.
//
// Früher bekam ein Spiel, dessen Bericht nur das Satz-Holz nennt, je Satz einen einzigen
// Ersatz-Teilsatz über alle Würfe. Das machte aus einem importierten Schere-Spiel ein Programm,
// das es so gar nicht gibt: nicht vergleichbar mit selbst erfassten Spielen und von Hand nicht
// zu vervollständigen. Jetzt steht in der Config, was auf der Bahn wirklich gespielt wurde
// (Schere: Volle + Kranz-Abräumen), und was der Bericht nicht hergibt, bleibt schlicht leer —
// das Satz-Holz sitzt dann auf dem Satz statt auf einem erfundenen Teilsatz (ergebnisBlock).
export function teilsatzPlan(preset) {
  const p = PRESETS[preset];
  if (!p) throw new Error(`Unbekannte Bahnart: ${preset}`);
  return [...(p.teilsaetze || [])];
}

// Aus den Summen EINES Satzes einen Satz-Block bauen — über `overrides`, nicht über erfundene
// Einzelwürfe. Genau darin unterscheidet sich diese Funktion von adoptErgebnisBlock()
// (logic/sportwinner-konflikte.js): dort werden synthetische Würfe gebraucht, damit der
// Konflikt-Abgleich die Fehlerzahl exakt reproduziert; hier ginge dieselbe Synthese als echtes
// Wurfbild in die Statistik ein und würde 9er und Räumer erfinden.
//
// werte: { volle, abr } oder { holz }.
// Verteilt wird NICHTS. Drei Fälle, und der dritte ist der Regelfall bei Schere und Classic
// mit Punktwertung:
//   1. Ein einziger Teilsatz -> er bekommt das Satz-Holz.
//   2. Der Bericht trennt Volle und Abräumen UND das Programm hat genau einen Teilsatz je Seite
//      -> jeder bekommt seinen exakten Wert.
//   3. Sonst (nur Satz-Holz; oder Bohle mit zwei Volle-Teilsätzen, auf die sich eine Summe nicht
//      eindeutig aufteilen lässt) -> das Holz sitzt als `satzOverride` auf dem SATZ, die
//      Teilsätze bleiben leer. Satz- und Gesamtholz stimmen exakt, die Aufteilung behauptet
//      niemand — und wer sie kennt, kann sie in der Übersicht nachtragen.
export function ergebnisBlock(config, werte) {
  const ranges = teilsatzRanges(config);
  const overrides = ranges.map(() => null);
  let satzOverride = null;

  const idx = (abraeum) => {
    const treffer = ranges
      .map((r, i) => ({ r, i }))
      .filter(({ r }) => ABRAEUM_MODI.has(r.modus) === abraeum);
    return treffer.length === 1 ? treffer[0].i : -1;
  };
  const iV = idx(false);
  const iA = idx(true);
  const exakt = werte && werte.volle != null && werte.abr != null && iV >= 0 && iA >= 0;

  if (ranges.length === 1) {
    overrides[0] = satzHolzVon(werte);
  } else if (exakt) {
    overrides[iV] = werte.volle || 0;
    overrides[iA] = werte.abr || 0;
  } else {
    satzOverride = satzHolzVon(werte);
  }

  return {
    wuerfe: [],            // keine Einzelwürfe — der Ergebnisdienst liefert sie nicht
    kegel: [],
    koenig: [],
    overrides,
    satzOverride,          // != null: Satz-Holz ohne Teilsatz-Aufteilung (siehe logic/holz.js)
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
      // `namen`/`teiler`/`eindeutig` reisen bis in die View mit: eine geteilte Position zeigt
      // beide Namen, und nur eine EINDEUTIGE laesst sich als eigene Zeile ins Konto uebernehmen
      // (siehe Kopf, GETEILTE POSITIONEN).
      m.spieler.push({
        teamPos,
        name: s.name,
        namen: s.namen && s.namen.length ? s.namen : [s.name],
        teiler: s.teiler || null,
        eindeutig: s.eindeutig !== false,
        pass: null,
        extId: null,
        slot: i,
      });
      ergebnisse[`${m.id}|${teamPos}`] = {
        saetze: s.saetze,
        gesamt: s.gesamt || null,
        kegel: s.kegel,
        teiler: s.teiler || null,
        eindeutig: s.eindeutig !== false,
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
    // Wechsel und Abbrueche als lesbare Saetze, plus die Bemerkung der Partie — sie ist oft die
    // einzige Stelle, an der steht, WANN gewechselt wurde („nach 60 Wurf").
    hinweise: hinweisTexte(bericht.hinweise, {
      heim: mannschaften[0].name, gast: mannschaften[1].name,
    }),
    bemerkung: txt(partie && partie.bemerkung),
    // Laut Ergebnisdienst fertig gespielt. Das entscheidet, ob leer gebliebene Saetze als
    // BEENDET gelten (buildImportWettkampf) — wer aufgibt oder ausgewechselt wird, hinterlaesst
    // leere Saetze, und die duerfen den Wettkampf nicht fuer immer auf „laufend" halten.
    gespielt: !!(partie && partie.gespielt),
  };
}

// Das Holz einer Position aus einem Spec-Eintrag (spec.ergebnisse[key]).
//
// Steht hier und nicht in der View, weil `saetze` LÜCKEN hat: eine nicht bespielte Bahn ist
// `null` — bei einem Zwischenstand, bei einer Aufgabe, bei einem Abbruch und in jeder geteilten
// Position. Die View hatte die Summe selbst gebildet und dabei die Lücke nicht bedacht; der
// TypeError flog mitten im Aufbau von root.innerHTML, und die Ansicht blieb ohne jede Meldung
// auf „Lade Spielbericht …" stehen. Eine Funktion, ein Test, kein zweiter Anlauf.
export function positionsHolz(erg) {
  if (!erg) return 0;
  if (erg.saetze) return erg.saetze.reduce((n, x) => n + ((x && x.holz) || 0), 0);
  const g = erg.gesamt;
  return g ? (g.volle || 0) + (g.abr || 0) : 0;
}

// Stammt dieser Wettkampf aus dem Web-Import?
//
// Zwei Dinge haengen daran:
//
//  1. Die STARTBAHN bleibt aenderbar, obwohl schon Ergebnisse dranstehen, und die Ergebnisse
//     wandern dabei mit (bloeckeNachBahn): beim Web-Import haengen sie an der Bahn, nicht am
//     Satz (siehe Kopf). Bei selbst erfassten Spielen waere genau das falsch.
//
//  2. Solange der Wettkampf NICHT geteilt ist, liegt in der Datenbank allein die eigene
//     Ergebniszeile — ohne Namen (sync.linkEigenesErgebnis). Aenderungen gehen dann ueber
//     pushEigenesErgebnis statt ueber pushConfig, das die volle Aufstellung schriebe.
//     Wird er geteilt, gilt der normale Weg: die Aufstellung geht mit in die DB — die
//     KLARNAMEN aber nur, solange der WETTKAMPF laeuft und die Live-Anzeige sie braucht.
//     Ein Durchgang eines laengst beendeten Wettkampfs wird von vornherein mit Platzhaltern
//     eingefuegt (sync.linkGame ueber anonymeSpielerListe); den oeffentlichen Anzeigenamen
//     zur LizenzID setzt danach der Anonymisierungs-Trigger — genau wie bei jedem selbst
//     erfassten Wettkampf.
export function istWebImport(wettkampf) {
  if (!wettkampf) return false;
  return wettkampf.quelle === 'sportwinner-web' || !!wettkampf.swWeb;
}

// Laesst sich eine Ergebnisspalte ueberhaupt einer Bahn zuordnen?
//
// Nur wenn jeder Satz auf einer eigenen Bahn lief — also genau so viele bespielte Bahnen wie
// Saetze. Dann ist Spalte k die Bahn bahnListe[k]. Sportwinner fuehrt je Spieler vier Bahn-Slots
// (SW_BAHNEN); bei weniger Bahnen wuerden mehrere Saetze auf denselben Slot fallen, bei mehr
// saehe der Bericht nicht, welche vier gemeint sind. In beiden Faellen sagt der Bericht ueber die
// Bahn nichts — dann gilt seine Reihenfolge als Spielreihenfolge (Satz-Index), das Verhalten
// vor dieser Zuordnung. Dieselbe Grenze zieht buildSportwinnerPush beim Rueckschreiben.
function bahnZuordnungMoeglich(bahnListe, saetze, spalten) {
  return bahnListe.length === saetze && spalten >= saetze;
}

// Satz-Bloecke EINES Spielers auf einen geaenderten Bahnplan umhaengen.
//
// Beim Web-Import haengen die Ergebnisse an der BAHN, nicht am Satz (siehe Kopf): der Bericht
// nennt je Spieler vier Bahn-Spalten, welcher Satz das war, folgt erst aus seiner Startbahn.
// Wird die spaeter korrigiert (Mannschafts-Uebersicht im Hub), muss deshalb jedes Ergebnis auf
// den Satz wandern, in dem seine Bahn jetzt gespielt wird — sonst behauptete ein importiertes
// Satzergebnis ploetzlich eine Bahn, auf der es nie erzielt wurde.
//
// altPlan/neuPlan = die Bahn je Satz (eine Zeile aus config.bahnplan). Ist die Zuordnung nicht
// eindeutig — eine Bahn kommt mehrfach vor, oder es sind gar nicht dieselben Bahnen —, bleibt
// die bisherige Reihenfolge stehen: dann sagt der Plan ueber die Bahn nichts Eindeutiges.
export function bloeckeNachBahn(bloecke, altPlan, neuPlan) {
  const arr = Array.isArray(bloecke) ? bloecke : [];
  const alt = Array.isArray(altPlan) ? altPlan : [];
  const neu = Array.isArray(neuPlan) ? neuPlan : [];
  if (!alt.length || alt.length !== neu.length || arr.length !== alt.length) return arr;
  if (new Set(alt).size !== alt.length || new Set(neu).size !== neu.length) return arr;
  if (neu.some((b) => !alt.includes(b))) return arr;
  return neu.map((bahn) => arr[alt.indexOf(bahn)]);
}

// --- Ergebnisse eintragen (erster Import UND Nachimport) ---------------------

// Steht in diesem Satz schon etwas? Ein `done`-Haken zaehlt mit: wer einen Satz von Hand
// abgeschlossen hat, hat ihn entschieden — auch wenn er leer blieb.
export function blockLeer(block) {
  return !(block && (block.done || blockHatInhalt(block)));
}

// Spec-Mannschaft -> Mannschaft des vorhandenen Wettkampfs.
//
// buildImportSpec vergibt bei JEDEM Abruf frische uid()s. Beim Nachimport muessen die
// Ergebnisse aber die Spieler des ersten Imports treffen; zugeordnet wird deshalb ueber den
// Mannschaftsnamen, den beide Male derselbe Ergebnisdienst liefert. Faellt der aus (umbenannte
// Mannschaft), gilt die Reihenfolge — Heim zuerst, wie in buildImportSpec.
function teamKarte(spec, ziele) {
  const karte = {};
  const norm = (x) => klarText(x).toLowerCase();
  (spec.mannschaften || []).forEach((m, i) => {
    if (!ziele || !ziele.length) { karte[m.id] = m.id; return; }
    const treffer = ziele.find((z) => norm(z.name) === norm(m.name)) || ziele[i] || null;
    karte[m.id] = treffer ? treffer.id : m.id;
  });
  return karte;
}

// spec.ergebnisse auf die IDs des Ziel-Wettkampfs umschluesseln (ohne `ziele` unveraendert).
function uebersetzteErgebnisse(spec, ziele) {
  const karte = teamKarte(spec, ziele);
  const out = {};
  Object.entries((spec && spec.ergebnisse) || {}).forEach(([key, erg]) => {
    const i = key.indexOf('|');
    const mid = i < 0 ? key : key.slice(0, i);
    out[`${karte[mid] || mid}${i < 0 ? '' : key.slice(i)}`] = erg;
  });
  return out;
}

// Die Ergebnisse eines Import-Specs in die Durchgaenge eintragen.
//
// Herzstueck des ersten Imports UND des Nachimports: dieselbe Zuordnung (Mannschaft|Position ->
// Spieler, Bahnspalte -> Satz), nur der Umgang mit dem, was schon dasteht, unterscheidet sich.
//
//   nurLeere     — nur Saetze fuellen, in denen noch nichts steht. Damit laesst sich eine
//                  laufende Partie mehrfach importieren: jedes Mal kommen genau die Saetze dazu,
//                  die seither gespielt wurden. Nichts wird ueberschrieben — weder ein frueher
//                  importiertes Ergebnis noch eine von Hand nachgetragene Teilsatz-Aufteilung.
//   probe        — nichts schreiben, nur zaehlen (fuer „X Ergebnisse kommen dazu").
//   mannschaften — die Mannschaften des VORHANDENEN Wettkampfs ({id,name}). Pflicht beim
//                  Nachimport: buildImportSpec vergibt bei jedem Abruf neue Mannschafts-IDs,
//                  die Durchgaenge tragen aber die des ersten Imports (siehe teamKarte).
//   abschliessen — die Partie ist laut Ergebnisdienst FERTIG: was dann leer geblieben ist,
//                  bleibt es auch. Solche Saetze bekommen den `done`-Haken, damit der Status
//                  abgeleitet 'beendet' wird (gameBaseStatus). Ohne das blieb jede Partie mit
//                  Aufgabe, Abbruch oder Wechsel fuer immer 'laufend' — und beim Teilen gaebe
//                  es dann keine Ergebnis-Snapshots (sync.linkGame prueft genau diesen Status).
//                  Bei einer noch LAUFENDEN Partie darf das nicht passieren: dort sind die
//                  leeren Saetze wirklich nur noch nicht gespielt.
//
// Rueckgabe: { gefuellt, geaendert:[games], nurSatzHolz, abgeschlossen }.
export function trageErgebnisseEin(games, spec, {
  nurLeere = false, probe = false, mannschaften = null, abschliessen = false,
} = {}) {
  let nurSatzHolz = false;
  let gefuellt = 0;
  let abgeschlossen = 0;
  const geaendert = [];
  const ergebnisse = uebersetzteErgebnisse(spec, mannschaften);
  (games || []).forEach((g) => {
    const c = g && g.config;
    const bloecke = (g && g.erfassung && g.erfassung.bloecke) || null;
    if (!c || !Array.isArray(bloecke) || !Array.isArray(c.spielerListe)) return;
    // Bahnplan des Durchgangs: physische Bahn je Spieler und Satz. Er dreht die Spalten des
    // Berichts auf die Saetze — siehe Kopf, Abschnitt BAHNEN.
    const bahnplan = bahnplanOf(c);
    const bahnListe = Array.isArray(c.bahnListe) ? c.bahnListe : [];
    let dieses = 0;
    // Adressiert ueber mannschaftId|teamPos, NICHT ueber die Reihenfolge: im Paarkreuz sitzt
    // derselbe Spieler in jedem Durchgang auf einem anderen Index.
    c.spielerListe.forEach((sp, i) => {
      const erg = ergebnisse[`${sp.mannschaftId}|${sp.teamPos}`];
      if (!erg || !erg.saetze || !Array.isArray(bloecke[i])) return;
      const nachBahn = bahnZuordnungMoeglich(bahnListe, c.saetze, erg.saetze.length);
      const plan = bahnplan && Array.isArray(bahnplan[i]) ? bahnplan[i] : null;
      for (let satz = 0; satz < c.saetze; satz += 1) {
        // Spalte des Berichts = Position der in diesem Satz bespielten Bahn in der Bahnliste.
        // Ohne Bahnplan faellt bahnSlot() auf den Satz-Index zurueck (eine Bahn je Satz, der
        // Reihe nach) — dieselbe Ruecknahme wie beim Rueckschreiben.
        const w = erg.saetze[nachBahn ? bahnSlot(bahnListe, plan, satz) : satz];
        if (!w) continue;                                   // Bahn noch nicht gespielt
        if (nurLeere && !blockLeer(bloecke[i][satz])) continue;
        const block = ergebnisBlock(c, w);
        if (block.satzOverride != null) nurSatzHolz = true;
        if (!probe) bloecke[i][satz] = block;
        dieses += 1;
      }
    });
    // Fertige Partie: die Luecken sind endgueltig. Sie zaehlen NICHT als `gefuellt` — dort steht
    // kein Ergebnis, und „X Ergebnisse kommen dazu" darf nicht luegen. Das Spiel gilt trotzdem
    // als geaendert, damit der Haken gespeichert und uebertragen wird.
    let zu = 0;
    if (abschliessen) {
      bloecke.forEach((satzArr) => (satzArr || []).forEach((b) => {
        if (!b || b.done) return;
        zu += 1;
        if (!probe) b.done = true;
      }));
    }
    abgeschlossen += zu;
    gefuellt += dieses;
    if (dieses || zu) geaendert.push(g);
  });
  return { gefuellt, geaendert, nurSatzHolz, abgeschlossen };
}

// --- Spec -> fertiger, gefuellter Wettkampf ----------------------------------

// Aus dem Import-Spec den kompletten Wettkampf samt Durchgaengen bauen UND die Ergebnisse
// eintragen. Bewusst hier und nicht im View: das ist der eigentliche Import, und er soll
// ohne DOM pruefbar sein (die View macht danach nur noch speichern und uebertragen).
//
// opt = { playedLanes[], anlageId, anlageName, anlageBahnen[] }
// Rueckgabe: { wettkampf, games, nurSatzHolz }
//   nurSatzHolz = true, wenn der Bericht keine Volle/Abraeum-Trennung hergab und die Saetze
//   deshalb nur ihr Satz-Holz tragen (ergebnisBlock -> satzOverride).
export function buildImportWettkampf(spec, opt = {}) {
  const played = (opt.playedLanes || []).slice().sort((a, b) => a - b);
  const p = PRESETS[spec.preset];
  if (!p) throw new Error(`Unbekannte Bahnart: ${spec.preset}`);
  const split = teamLanesByBahnart(spec.preset, played, spec.mannschaften.length);
  const teilsaetze = teilsatzPlan(spec.preset);
  let nurSatzHolz = false;

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
    // Wertung aus der Bahnart des Berichts ableiten — siehe views/import-sportwinner.js.
    wertung: defaultWertung(spec.preset, spec.spielerJeMannschaft, spec.mannschaften.length),
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
  });

  nurSatzHolz = trageErgebnisseEin(games, spec, { abschliessen: !!spec.gespielt }).nurSatzHolz;

  // Der Status wird ABGELEITET, nicht gesetzt: bei einer laufenden Partie sind noch nicht alle
  // Saetze da, und dann ist der Wettkampf eben 'laufend' und kein fertiges Spiel. Genau dieselbe
  // Ableitung benutzt der Rest der App (gameBaseStatus arbeitet auf den Bloecken). Dass eine
  // FERTIGE Partie auch dann 'beendet' herauskommt, wenn jemand aufgegeben hat, besorgt der
  // `done`-Haken aus `abschliessen` — nicht ein hier gesetzter Status.
  games.forEach((g) => { g.status = gameBaseStatus(g); });
  wettkampf.status = wettkampfBaseStatus(wettkampf, games);
  wettkampf.swWeb = { idSpiel: spec.idSpiel, nurSatzHolz };
  games.forEach((g) => { g.swWeb = wettkampf.swWeb; });
  return { wettkampf, games, nurSatzHolz };
}
