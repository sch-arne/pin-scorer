// Der Strom erkannter Würfe: Reihenfolge, Entdopplung, Puffer, Betriebsmodus.
// Reine Logik, kein DOM, kein Netz, kein Store.
//
// `erkennung-zuordnung.js` entscheidet über EINEN Wurf. Diese Datei beantwortet die Fragen,
// die sich erst über viele Zeilen hinweg stellen:
//
//   * In welcher Reihenfolge? Nach `recorded_at`, nicht nach `id`.
//   * Welche Zeile hatten wir schon? Über die aufsteigende `id`.
//   * Was tun mit einem Wurf, der noch nicht passt? Puffern und nach jedem übernommenen
//     Wurf erneut prüfen — denn mit jedem Wurf ändert sich der Zustand, auf den die
//     Zuordnung schaut.
//   * Und was mit allem, was auf derselben Bahn danach kam? Ebenfalls warten. Innerhalb
//     einer Bahn ist die Reihenfolge der Zeilen die physische Reihenfolge der Würfe; darf
//     ein späterer vorrücken, wird aus 9-8-4 ein 9-4-8.
//   * Automatik oder Vorschlag? Hier, nicht in der Zuordnung.
//
// AUTOMATIK IST DER NORMALBETRIEB. Die App hat keine Vorschlagsliste: ein erkannter Wurf
// geht in den Satz, Korrektur wie bei jedem getippten Wurf. Deshalb traegt der Automatik-
// Betrieb auch ein `vorschlag` ein, sofern ein Platz feststeht — `grund` wird dann zum
// HINWEIS am Wurf. Nur das Kegelbild wird dabei fallen gelassen, wenn die Zuordnung es fuer
// strittig haelt (`bildStrittig`): die Holzzahl ist die gemessene Groesse, das Bild rechnet
// die App sich dann selbst zusammen.
//
// WAS BEI EINER ABLEHNUNG GESCHIEHT, und warum es in den Modi verschieden ist: Lehnt die
// Erfassung einen Wurf ab, ist das im Automatik-Betrieb endgueltig — der einzige Fall, der
// ueberhaupt bis dorthin kommt, ist „mehr Holz als Kegel standen" (die Erfassung prueft das
// in addWurfAn, die Zuordnung kann es nicht wissen). Diesen Wurf 15 Minuten lang erneut zu
// versuchen und dabei die BAHN ZU SPERREN hiesse: eine Fehlerkennung legt den Rest des Satzes
// still, und auf dem Bildschirm steht nur ein Warnzeichen. Also wird er sofort aufgegeben
// (`abgelehnt`) und die Bahn laeuft weiter. Der Preis ist bekannt und sichtbar: dem Satz fehlt
// ein Wurf, alles Folgende sitzt einen Platz zu frueh — genau das meldet der Hinweis an der
// Bahn, und genau das korrigiert ein Mensch in Sekunden. Im Vorschlagsbetrieb bleibt es beim
// Puffern: dort antwortet ohnehin jemand.
//
// WARUM `recorded_at` UND NICHT `id`: Der Erkenner stempelt die Zeit, wenn er den Wurf in
// seine Warteschlange legt. Nach einem Netzausfall liefert er den Puffer unverändert nach —
// die Zeilen bekommen dann NEUE, höhere ids, tragen aber ihre ALTE Zeit. Nach id sortiert
// landeten sie hinter den inzwischen eingegangenen Würfen und damit in den falschen Sätzen.
// Zum Entdoppeln ist die id dagegen genau richtig: sie wird beim Einfügen vergeben und
// steigt, also ist alles bis zur höchsten gesehenen id abgearbeitet.
//
// „Aus" kommt hier nicht vor. Ist die Erkennung abgeschaltet, holt der Aufrufer keine Zeilen
// — und wenn sie mitten im Spiel eingeschaltet wird, entscheidet er, ob der Rückstand der
// letzten Stunde noch jemanden interessiert. Dieses Modul verarbeitet, was man ihm gibt.

import { ordneEvent, AKTION } from './erkennung-zuordnung.js';
import { teilsatzRanges } from './teilsaetze.js';

export const MODUS = {
  AUS: 'aus',               // die App holt gar nichts (nur der Schalter kennt diese Stellung)
  VORSCHLAG: 'vorschlag',   // nichts wird gesetzt, alles kommt in die Vorschlagsliste
  AUTOMATIK: 'automatik',   // alles mit festem Platz wird eingetragen, mit Hinweis wo nötig
};

// Wie lange ein gepufferter Wurf auf seinen Platz warten darf. Ein Satz dauert rund zehn
// Minuten; wer dann noch keinen Platz gefunden hat, gehört zu einem Satz, der nie zustande
// kommt (abgebrochen, von Hand erfasst, anderes Gerät). Er verfällt dann LOKAL — die Zeile
// in der Datenbank bleibt unberührt, denn für ein anderes Gerät oder einen späteren Blick
// kann sie noch gültig sein.
export const MAX_ALTER_MS = 15 * 60 * 1000;

// Sortierschlüssel: Zeit zuerst, id als Stichentscheid (zwei Würfe im selben Millisekundenschlag
// sind in id-Reihenfolge eingegangen). Eine unlesbare Zeit sortiert nach hinten statt alles
// durcheinanderzubringen.
function zeit(zeile) {
  const t = Date.parse(zeile.recorded_at);
  return Number.isNaN(t) ? Infinity : t;
}

export function sortiereZeilen(zeilen) {
  return zeilen.slice().sort((a, b) => (zeit(a) - zeit(b)) || ((a.id ?? 0) - (b.id ?? 0)));
}

// Einen Schwung Zeilen verarbeiten.
//
// `zeilen` — neue Zeilen aus `erkannter_wurf` (Reihenfolge beliebig).
// `ctx`:
//   config, bloecke, erkenner, darfSchreiben, ranges  — gehen an ordneEvent weiter
//   modus        MODUS.VORSCHLAG | MODUS.AUTOMATIK
//   puffer       die Zeilen, die beim letzten Mal keinen Platz fanden (Vorgabe: keine)
//   gesehenBis   höchste bereits verarbeitete id (Vorgabe: 0)
//   schonImSatz  ids, die bereits in einem Satz stehen (aus `blk.erkannt`). Der zweite
//                Riegel gegen Doppel-Einträge, und der einzige, der einen Neustart
//                überlebt: `gesehenBis` lebt nur im Arbeitsspeicher, und ob die Zeile in
//                der Datenbank als zugeordnet vermerkt wurde, weiss die App beim Laden
//                nicht sicher (das Zuordnen kann fehlgeschlagen sein). Die ids im Satz
//                wissen es.
//   uebernehmen  (entscheidung, zeile) => boolean — schreibt den Wurf (in der App:
//                addWurfAn). Gibt false zurück, wenn eine Sperre der Erfassung es doch
//                abgelehnt hat; dann bleibt die Zeile im Puffer statt verloren zu gehen.
//   jetzt        Zeitbezug für das Verfallen (Vorgabe: Date.now())
//   maxAlterMs   siehe MAX_ALTER_MS
//
// Rückgabe:
//   gesetzt      [{ zeile, entscheidung }] — geschrieben
//   vorschlaege  [{ zeile, entscheidung }] — gehören dem Menschen
//   vermerke     [{ zeile, grund }]        — in erkannter_wurf.verworfen_grund schreiben
//   puffer       die Zeilen, die weiter warten
//   verfallen    [{ zeile, grund }]        — zu lange gewartet, NUR lokal aufgegeben
//   abgelehnt    [{ zeile, grund }]        — von der Erfassung endgültig abgelehnt; gehört
//                                            dem Menschen als Hinweis UND in verworfen_grund
//
// Der Unterschied zwischen `verfallen` und `abgelehnt` ist der Grund, warum es zwei Listen
// sind: Eine verfallene Zeile hat nur HIER keinen Platz gefunden (anderes Gerät, später
// nachgetragener Satz) — die Zeile in der Datenbank bleibt unberührt. Eine abgelehnte ist
// gemessen unmöglich; sie darf vermerkt werden, sonst wird sie nach jedem Neuladen erneut
// versucht.
//   gesehenBis   neuer Stand für den nächsten Aufruf
export function verarbeite(zeilen, ctx) {
  const {
    config, bloecke, erkenner = null, darfSchreiben = () => true,
    modus = MODUS.VORSCHLAG,
    puffer = [],
    offeneVorschlaege = [],
    gesehenBis = 0,
    schonImSatz = [],
    uebernehmen = () => false,
    jetzt = Date.now(),
    maxAlterMs = MAX_ALTER_MS,
  } = ctx;
  const ranges = ctx.ranges || teilsatzRanges(config);

  // Eine Zeile OHNE id laesst sich nicht entdoppeln -- sie gilt als neu. Sie stillschweigend
  // wegzufiltern waere die schlechtere Wahl: aus `erkannter_wurf` kommt immer eine id, also
  // stammt so eine Zeile von Hand oder aus einem Test, und dann soll sie durchlaufen.
  const imSatz = schonImSatz instanceof Set ? schonImSatz : new Set(schonImSatz || []);
  const neu = (zeilen || [])
    .filter((z) => z.id == null || z.id > gesehenBis)
    .filter((z) => z.id == null || !imSatz.has(z.id));
  // `hoechste` zaehlt AUCH die eben uebersprungenen: sie sind abgearbeitet, nur eben schon
  // frueher. Sonst holte der naechste Schwung sie wieder.
  const hoechste = (zeilen || [])
    .reduce((m, z) => (z.id != null ? Math.max(m, z.id) : m), gesehenBis);

  const gesetzt = [];
  const vorschlaege = [];
  const vermerke = [];
  const verfallen = [];
  const abgelehnt = [];

  // Alte Puffer-Zeilen zuerst: sie sind älter und gehören weiter vorn in den Satz.
  // Dabei nach id entdoppeln: Steht eine Zeile im Puffer UND in der neuen Lieferung -- weil
  // der Aufrufer `gesehenBis` nicht mitgeführt oder einen Schwung erneut geholt hat --, darf
  // sie nicht zweimal in den Satz.
  const nachId = new Map();
  for (const z of [...puffer, ...neu]) {
    if (z.id == null) continue;
    nachId.set(z.id, z);
  }
  let offen = sortiereZeilen([
    ...nachId.values(),
    ...[...puffer, ...neu].filter((z) => z.id == null),
  ]);

  // Zielplätze, für die schon ein Vorschlag beim Menschen liegt. Ein zweiter Vorschlag für
  // denselben Platz wäre kein Hinweis, sondern Rauschen: beide zeigen auf denselben Wurf,
  // und bestätigt werden kann nur einer. Das ist nicht der Ausnahmefall, sondern der
  // Regelfall am Satzanfang — der erste Wurf eines leeren Satzes wird immer nur
  // vorgeschlagen (Einspielwürfe, siehe erkennung-zuordnung.js), also wartet alles danach,
  // bis dieser eine Platz vergeben ist.
  // Dazu gehoeren auch die Vorschlaege, die der Aufrufer noch offen hat: Ohne sie wuerde
  // beim naechsten Schwung ein zweiter Vorschlag fuer denselben Platz entstehen -- der erste
  // liegt ja noch unbeantwortet in der Liste.
  const belegt = new Set();
  for (const v of offeneVorschlaege) {
    const z = v && (v.ziel || (v.entscheidung && v.entscheidung.ziel));
    if (z) belegt.add(`${z.sp}:${z.st}:${z.idx}`);
  }

  // Nach jedem gesetzten Wurf ändert sich der Zustand — ein gepufferter Wurf, der eben noch
  // nicht passte, kann jetzt passen. Deshalb nicht einmal durchlaufen, sondern so lange, wie
  // sich etwas bewegt. Der Zähler ist nur eine Reißleine: ohne Fortschritt bricht die
  // Schleife ohnehin ab.
  for (let runde = 0; runde < 1000; runde += 1) {
    const warten = [];
    let bewegung = false;
    // Bahnen, auf denen ein Wurf wartet. Wartet einer, MUSS alles dahinter auf derselben
    // Bahn auch warten -- sonst nimmt der spaetere Wurf den Platz des frueheren ein, und
    // aus 9-8-4 wird 9-4-8. Genau das ist der Grund, warum der Puffer je Bahn gefuehrt wird
    // und nicht als eine Liste: die Reihenfolge innerhalb einer Bahn ist die physische
    // Reihenfolge der Wuerfe, und die darf nichts umstellen.
    let gesperrt = new Set();

    // Warten lassen -- aber nicht endlos. Das Verfallsdatum muss für JEDEN Weg in den
    // Puffer gelten, nicht nur für die Zuordnung: Lehnt die Erfassung einen Wurf dauerhaft
    // ab (Satz fertig, fremdes Gerät), läge er sonst bis zum Spielende in der Schlange und
    // würde bei jedem Durchgang erneut geprüft.
    const warteOderVerfalle = (z, grund) => {
      const alter = jetzt - zeit(z);
      if (Number.isFinite(alter) && alter > maxAlterMs) {
        verfallen.push({ zeile: z, grund });
        bewegung = true;
      } else {
        warten.push(z);
      }
    };

    for (let i = 0; i < offen.length; i += 1) {
      const zeile = offen[i];
      const e = ordneEvent(zeile, { config, bloecke, erkenner, darfSchreiben, ranges });

      if (e.aktion === AKTION.VERWERFEN) {
        // Eine verworfene Zeile sperrt die Bahn NICHT. Sie traegt keine brauchbare Angabe
        // (fremde Bahn, unmoegliche Holzzahl), also waere Warten nur Stillstand bis zum
        // Verfallsdatum. Der Preis ist bekannt: War es doch ein echter Wurf, rutscht alles
        // Folgende einen Platz nach vorn -- und genau das meldet die Abraeum-Kette.
        if (e.merken) vermerke.push({ zeile, grund: e.grund });
        bewegung = true;
        continue;
      }

      if (gesperrt.has(e.bahn)) {
        warteOderVerfalle(zeile, `wartet hinter einem frueheren Wurf auf Bahn ${e.bahn}`);
        continue;
      }

      if (e.aktion === AKTION.PUFFERN) {
        gesperrt.add(e.bahn);
        warteOderVerfalle(zeile, e.grund);
        continue;
      }

      // Im Automatik-Betrieb wird eingetragen, was einen Platz hat — auch ein `vorschlag`.
      // Ein Vorschlag OHNE Platz kann nicht eingetragen werden und geht den Weg unten.
      const eintragbar = modus === MODUS.AUTOMATIK
        && (e.aktion === AKTION.SETZEN || (e.aktion === AKTION.VORSCHLAG && e.ziel));
      if (eintragbar) {
        // Strittiges Kegelbild: die Holzzahl bleibt, das Bild fällt weg (kegel = null heißt
        // „rechne es selbst aus", nicht „keine Kegel").
        const wurf = e.bildStrittig ? { ...e, kegel: null } : e;
        if (uebernehmen(wurf, zeile)) {
          gesetzt.push({ zeile, entscheidung: wurf, hinweis: wurf.grund || null });
          bewegung = true;
          // Der Zustand hat sich geändert: alles ab hier noch einmal von vorn prüfen,
          // zusammen mit dem, was bisher wartet.
          offen = sortiereZeilen([...warten, ...offen.slice(i + 1)]);
          i = -1;
          warten.length = 0;
          gesperrt = new Set();     // nichts wartet mehr: jede Bahn bekommt eine neue Chance
          continue;
        }
        // Endgültig abgelehnt — siehe Kopf dieser Datei. Die Bahn wird NICHT gesperrt.
        abgelehnt.push({ zeile, grund: wurf.grund || 'von der Erfassung abgelehnt' });
        bewegung = true;
        continue;
      }

      // Vorschlag — und im Vorschlagsmodus auch jedes `setzen`. Ab hier gehört der Wurf dem
      // Menschen: er landet NICHT im Puffer, sonst stünde er doppelt (einmal in der Liste,
      // einmal als wartende Zeile) und käme nach dem Bestätigen ein zweites Mal.
      const platz = e.ziel ? `${e.ziel.sp}:${e.ziel.st}:${e.ziel.idx}` : null;
      if (platz && belegt.has(platz)) {
        gesperrt.add(e.bahn);
        warteOderVerfalle(zeile, `wartet auf die Antwort zu Wurf ${e.ziel.idx + 1}`);
        continue;
      }
      if (platz) belegt.add(platz);
      // Ein Vorschlag sperrt seine Bahn ebenfalls: Solange niemand geantwortet hat, ist der
      // Platz nicht vergeben, und der physisch naechste Wurf kann nicht davor rutschen.
      gesperrt.add(e.bahn);
      vorschlaege.push({ zeile, entscheidung: e });
      bewegung = true;
    }

    offen = warten;
    if (!bewegung) break;
  }

  return { gesetzt, vorschlaege, vermerke, puffer: offen, verfallen, abgelehnt,
           gesehenBis: hoechste };
}
