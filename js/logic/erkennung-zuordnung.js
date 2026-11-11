// Erkannte Würfe den Würfen im Satz zuordnen — reine Logik, kein DOM, kein Netz, kein Store.
//
// Die Bilderkennung (erkennung/, siehe erkennung/docs/PINS_SCORER.md) liefert je Wurf genau
// vier Dinge: BAHN, Anzahl gefallener Kegel, WELCHE Kegel, und wann. Sie kennt weder Spieler
// noch Satz, Teilsatz oder Programm — und soll sie nicht kennen. Diese Datei ist die Stelle,
// die den Rest ableitet:
//
//   Bahn --(computeBahnState)--> Spieler --(.pos)--> Satz
//        --(blk.wuerfe.length)--> Wurfindex --(rangeOfThrow)--> Teilsatz + Modus
//
// Warum das hier und nicht im Erkenner: Beide Seiten KÖNNTEN Spieler und Satz herleiten, und
// sobald beide es tun, laufen sie auseinander. Im Ursprungsprojekt der Erkennung ist genau das
// passiert — die von der Tafel gelesene Wurfnummer löschte 28 % der Würfe, die Spielerkennung
// nach 30 Würfen traf den Bahnwechsel nicht, die laufende Summe driftete ab. Deshalb gilt:
// gemessen wird dort, abgeleitet wird hier.
//
// Die Funktion ENTSCHEIDET nicht über den Betriebsmodus. Sie sagt, was die Daten hergeben:
// `setzen` heißt "sauber zuordenbar", nicht "bitte sofort eintragen". Ein Betrieb im
// Vorschlagsmodus stuft jedes `setzen` zu `vorschlag` herab — das ist Sache des Aufrufers.
// Ebenso die Entdopplung: eine Zeile zweimal zu verarbeiten verhindert die id, nicht diese
// Datei.

import { computeBahnState, laneOf } from './bahnwechsel.js';
import { teilsatzRanges } from './teilsaetze.js';
import { rangeOfThrow, isAbraeumMode, abraeumStateBefore } from './abraeumen.js';

export const AKTION = {
  SETZEN: 'setzen',        // sauber zuordenbar
  VORSCHLAG: 'vorschlag',  // zuordenbar, aber jemand muss hinsehen
  PUFFERN: 'puffern',      // gehört ins Spiel, nur noch nicht hierhin — später erneut prüfen
  VERWERFEN: 'verwerfen',  // gehört nicht in dieses Spiel
};

// Welche Bahnnummer meint die vom Erkenner gemeldete `lane`?
//
// SPIEGELT pins_erkenner_bahn in supabase/policies.sql — dort entscheidet dieselbe Regel, wer
// eine Zeile überhaupt sehen darf. Drei Fälle in dieser Reihenfolge:
//   1) Der Erkenner ist an genau eine Bahn gekoppelt -> die gilt, die Tafel ist unerheblich.
//   2) `bahn_zuordnung` übersetzt sie: Kegel_CV liest die Bahnnummer von der Anzeigetafel;
//      sind dort keine Nummern kalibriert, zählt es die Tafeln von links (1…4) — auf den
//      Bahnen 2–5 wäre dann jede Zuordnung um eins verschoben, ohne dass es auffällt.
//   3) Sonst IST die gemeldete Zahl die Bahnnummer.
// `erkenner` ist die Zeile aus der Tabelle `erkenner` (bahn_nummer = die Nummer der
// gekoppelten Bahn, von der App mitgelesen).
export function bahnFuerLane(erkenner, lane) {
  if (!erkenner) return lane;
  if (erkenner.bahn_nummer != null) return erkenner.bahn_nummer;
  const z = erkenner.bahn_zuordnung;
  if (z && z[String(lane)] != null) {
    const n = Number(z[String(lane)]);
    if (Number.isInteger(n)) return n;
  }
  return lane;
}

// Die Bahn-Belegung des Spiels: je Spieler { pos, lane, waiting, fertig }.
// Genau dieselbe Rechnung wie in der Erfassung (views/spiel-laufend.js) — eine Wahrheit.
export function bahnBelegung(config, bloecke) {
  return computeBahnState({
    n: config.spielerListe.length,
    saetze: config.saetze,
    doneMatrix: bloecke.map((arr) => arr.map((b) => b.done)),
    laneOf: (sp, st) => laneOf(config, sp, st),
  });
}

const ergebnis = (aktion, grund, extra = {}) => ({
  aktion, grund, ziel: null, holz: null, kegel: null, koenigFlag: false,
  // Darf dieser Befund in `erkannter_wurf.verworfen_grund` geschrieben werden?
  // Nur wenn er für JEDES Gerät gilt. „Gehört einem anderen Gerät" gilt eben nicht: für das
  // andere Gerät ist derselbe Wurf richtig, und ein dort hingeschriebenes „verworfen" nähme
  // ihm den Wurf weg.
  merken: true,
  ...extra,
});

// Ein Kegelbild aus dem Erkenner prüfen. Rückgabe { kegel, befund }:
//   kegel  = sortierte Liste der gefallenen Kegel, oder null (unbrauchbar -> Holz zählt)
//   befund = Text, wenn etwas nicht stimmt
// Die Erkennung liefert das Bild der GEFALLENEN Kegel, und die Anzahl stimmt mit der Holzzahl
// überein — ausnahmslos, gemessen an der Aufzeichnung vom 29.08.2026 (4 Bahnen, 48 Sätze).
// Stimmt sie doch nicht, ist nicht entscheidbar, ob die Zahl oder das Bild falsch ist. Dann
// zählt die Zahl (sie ist die gemessene Größe) und das Bild fällt weg.
function pruefeBild(pins, holz) {
  if (pins == null) return { kegel: null, befund: null };
  if (!Array.isArray(pins)) return { kegel: null, befund: 'Kegelbild ist keine Liste' };
  if (pins.some((p) => !Number.isInteger(p) || p < 1 || p > 9)) {
    return { kegel: null, befund: `Kegelnummer außerhalb 1–9 (${pins.join(' ')})` };
  }
  if (new Set(pins).size !== pins.length) {
    return { kegel: null, befund: `derselbe Kegel mehrfach im Bild (${pins.join(' ')})` };
  }
  if (pins.length !== holz) {
    return { kegel: null, befund: `${holz} Holz, aber ${pins.length} Kegel im Bild (${pins.join(' ')})` };
  }
  return { kegel: pins.slice().sort((a, b) => a - b), befund: null };
}

// Einen erkannten Wurf einordnen.
//
// `zeile`  — eine Zeile aus `erkannter_wurf`: { lane, pins_count, pins }. Weitere Spalten
//            (recorded_at, video_time_s, displayed_*, board_jpeg) spielen hier keine Rolle:
//            sie sind Beleg, nicht Eingabe.
// `ctx`    — { config, bloecke, erkenner?, darfSchreiben?, ranges? }
//            config/bloecke wie in der Erfassung; `erkenner` nur, wenn die Bahn noch
//            übersetzt werden muss; `darfSchreiben(sp)` = hält DIESES Gerät den Spieler
//            (canEdit); `ranges` optional vorberechnet.
//
// Rückgabe { aktion, grund, bahn, ziel:{sp,st,idx}, holz, kegel, koenigFlag, merken }.
// `ziel` ist gesetzt, sobald ein Platz im Satz feststeht (auch bei `vorschlag`).
export function ordneEvent(zeile, ctx) {
  const { config, bloecke, erkenner = null, darfSchreiben = () => true } = ctx;
  const ranges = ctx.ranges || teilsatzRanges(config);
  const bahn = zeile.bahn != null ? zeile.bahn : bahnFuerLane(erkenner, zeile.lane);
  const holz = zeile.pins_count;

  // 1) Ist die Zeile in sich brauchbar? Eine Holzzahl außerhalb 0–9 ist kein Wurf, sondern
  //    ein Lesefehler — den trägt niemand ein, auch nicht als Vorschlag.
  if (!Number.isInteger(holz) || holz < 0 || holz > 9) {
    return ergebnis(AKTION.VERWERFEN, `Holz ${holz} liegt nicht zwischen 0 und 9`, { bahn });
  }
  const bild = pruefeBild(zeile.pins, holz);

  // 2) Welcher Spieler steht auf dieser Bahn? Das ist die einzige Frage, die der Erkenner
  //    nicht beantworten kann und die App exakt beantworten muss.
  const belegung = bahnBelegung(config, bloecke);
  const sp = belegung.findIndex((b) => b.lane === bahn);
  if (sp < 0) {
    // Entweder eine Bahn eines PARALLELEN Spiels auf derselben Anlage (das ist vorgesehen),
    // oder eine falsch übersetzte Bahnnummer. Beides ist hier richtig verworfen — aber nicht
    // gemerkt: für das Gerät des anderen Spiels ist dieselbe Zeile gültig.
    return ergebnis(AKTION.VERWERFEN, `Bahn ${bahn} gehört nicht zu diesem Spiel`,
                    { bahn, merken: false });
  }
  const stand = belegung[sp];

  // 3) Gehört der Spieler einem anderen Gerät? Dann Finger weg. Würden beide Geräte schreiben,
  //    gäbe es zwei Fassungen desselben Satzes — die RLS verhindert es ohnehin (nur das Gerät
  //    mit dem Lock darf satz_block schreiben), aber es soll gar nicht erst versucht werden.
  if (!darfSchreiben(sp)) {
    return ergebnis(AKTION.VERWERFEN, `Spieler ${sp + 1} wird von einem anderen Gerät erfasst`,
                    { bahn, merken: false });
  }

  // 4) Wartet er auf den Bahnwechsel, ist sein Satz fertig und die nächste Bahn noch besetzt.
  //    Was jetzt auf dieser Bahn erkannt wird, gehört niemandem — PUFFERN statt raten: sobald
  //    `pos` vorrückt, wird die Zeile erneut geprüft und landet dann richtig.
  if (stand.waiting) {
    return ergebnis(AKTION.PUFFERN, `Spieler ${sp + 1} wartet auf den Bahnwechsel`, { bahn });
  }
  if (stand.fertig) {
    return ergebnis(AKTION.VERWERFEN, `Spieler ${sp + 1} ist fertig`, { bahn });
  }

  const st = stand.pos;                      // der SATZ, nicht state.aktiverSatz (nur UI)
  const blk = bloecke[sp] && bloecke[sp][st];
  if (!blk) {
    return ergebnis(AKTION.VERWERFEN, `Satz ${st + 1} von Spieler ${sp + 1} gibt es nicht`, { bahn });
  }

  // 5) Satz voll oder abgeschlossen: PUFFERN, nicht verwerfen. Das ist der Fall, in dem ein
  //    Wurf am Satzende verpasst wurde — der Satz hat 29 statt 30 Würfe, und der nächste
  //    erkannte Wurf gehört in Wahrheit noch hierher. Als Korrekturvorschlag ist er brauchbar,
  //    als stiller Eintrag wäre er falsch.
  if (blk.done || blk.wuerfe.length >= config.wuerfeProSatz) {
    return ergebnis(AKTION.PUFFERN, `Satz ${st + 1} von Spieler ${sp + 1} ist voll`,
                    { bahn, ziel: { sp, st, idx: blk.wuerfe.length } });
  }

  const idx = blk.wuerfe.length;
  const range = rangeOfThrow(ranges, idx);
  if (!range) {
    return ergebnis(AKTION.PUFFERN, `Wurf ${idx + 1} liegt in keinem Teilsatz`,
                    { bahn, ziel: { sp, st, idx } });
  }

  const ziel = { sp, st, idx };
  const daten = { bahn, ziel, holz, kegel: bild.kegel, koenigFlag: false };

  // 6) Beim Abräumen trifft jeder Wurf nur die zuvor stehengebliebenen Kegel. Das ist der
  //    wichtigste Sicherheitsmechanismus der ganzen Anbindung: Fällt ein Kegel, der schon lag,
  //    oder fallen mehr Kegel als standen, dann wurde entweder ein Wurf GAR NICHT erkannt oder
  //    einer nur TEILWEISE. Beides ist an der Abräum-Kette zu sehen und sonst nirgends — eine
  //    Teilerkennung (eine 9, gemeldet als „2") zählt als Wurf und ist allein an der Zahl nicht
  //    von einem echten Wurf zu unterscheiden.
  //    Der Erkenner liefert kein Bild des Vorzustands, mit dem sich das direkt vergleichen
  //    ließe; diese Kette ist der Ersatz dafür.
  if (isAbraeumMode(range.modus)) {
    const vor = abraeumStateBefore(blk, range, idx);
    if (holz > vor.count) {
      return ergebnis(AKTION.VORSCHLAG,
        `${holz} Holz, aber es ${vor.count === 1 ? 'stand' : 'standen'} nur ${vor.count} Kegel`,
        daten);
    }
    if (bild.kegel && vor.exact) {
      const lagen = bild.kegel.filter((p) => !vor.standing.includes(p));
      if (lagen.length) {
        return ergebnis(AKTION.VORSCHLAG,
          `Kegel ${lagen.join(', ')} ${lagen.length === 1 ? 'stand' : 'standen'} nicht mehr`,
          daten);
      }
    }
  }

  // 7) Ein unbrauchbares Kegelbild macht den Wurf nicht unbrauchbar — die Holzzahl bleibt die
  //    gemessene Größe. Aber eintragen soll das ein Mensch.
  if (bild.befund) return ergebnis(AKTION.VORSCHLAG, `Wurf ${idx + 1}: ${bild.befund}`, daten);

  // 8) Der erste Wurf eines noch leeren Satzes wird nur vorgeschlagen. Grund: Einspielwürfe.
  //    Sie finden auf derselben Bahn statt, sehen genauso aus und würden sonst stillschweigend
  //    als Wurf 1 gezählt. In der Aufzeichnung vom 29.08. standen auf einer Bahn 20
  //    Probewürfe vor dem ersten Satz, einmal ohne eigene Spalte — die Erkennung trennt das
  //    nicht zuverlässig, ein Mensch mit einem Blick auf die Bahn schon.
  if (idx === 0) {
    return ergebnis(AKTION.VORSCHLAG,
      `Erster Wurf in Satz ${st + 1} von Spieler ${sp + 1} — Einspielwürfe?`, daten);
  }

  return ergebnis(AKTION.SETZEN, null, daten);
}
