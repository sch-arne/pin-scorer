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
  VORSCHLAG: 'vorschlag',   // nichts wird gesetzt, alles kommt in die Vorschlagsliste
  AUTOMATIK: 'automatik',   // zuordenbare Würfe werden gesetzt, der Rest vorgeschlagen
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
//   verfallen    [{ zeile, grund }]        — zu lange gewartet, lokal aufgegeben
//   gesehenBis   neuer Stand für den nächsten Aufruf
export function verarbeite(zeilen, ctx) {
  const {
    config, bloecke, erkenner = null, darfSchreiben = () => true,
    modus = MODUS.VORSCHLAG,
    puffer = [],
    offeneVorschlaege = [],
    gesehenBis = 0,
    uebernehmen = () => false,
    jetzt = Date.now(),
    maxAlterMs = MAX_ALTER_MS,
  } = ctx;
  const ranges = ctx.ranges || teilsatzRanges(config);

  // Eine Zeile OHNE id laesst sich nicht entdoppeln -- sie gilt als neu. Sie stillschweigend
  // wegzufiltern waere die schlechtere Wahl: aus `erkannter_wurf` kommt immer eine id, also
  // stammt so eine Zeile von Hand oder aus einem Test, und dann soll sie durchlaufen.
  const neu = (zeilen || []).filter((z) => z.id == null || z.id > gesehenBis);
  const hoechste = neu.reduce((m, z) => (z.id != null ? Math.max(m, z.id) : m), gesehenBis);

  const gesetzt = [];
  const vorschlaege = [];
  const vermerke = [];
  const verfallen = [];

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

      if (e.aktion === AKTION.SETZEN && modus === MODUS.AUTOMATIK) {
        if (uebernehmen(e, zeile)) {
          gesetzt.push({ zeile, entscheidung: e });
          bewegung = true;
          // Der Zustand hat sich geändert: alles ab hier noch einmal von vorn prüfen,
          // zusammen mit dem, was bisher wartet.
          offen = sortiereZeilen([...warten, ...offen.slice(i + 1)]);
          i = -1;
          warten.length = 0;
          gesperrt = new Set();     // nichts wartet mehr: jede Bahn bekommt eine neue Chance
          continue;
        }
        // Die Erfassung hat abgelehnt (Sperre, fremdes Gerät, Satz voll). Nicht verlieren --
        // und die Bahn sperren, damit kein spaeterer Wurf diesen Platz nimmt.
        gesperrt.add(e.bahn);
        warteOderVerfalle(zeile, 'von der Erfassung abgelehnt');
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

  return { gesetzt, vorschlaege, vermerke, puffer: offen, verfallen, gesehenBis: hoechste };
}
