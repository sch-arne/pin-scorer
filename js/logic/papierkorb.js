// Der Papierkorb — was ich aus meinem Konto entfernt habe, für eine Weile zurückholbar.
//
// „Löschen" heißt für alles, was in der Datenbank liegt: VERBORGEN, und zwar nur für mich
// (logic/loeschen.js, Tabelle `verborgen`). Die Aufzeichnung bleibt also stehen — es fehlte
// bisher bloß der Weg zurück. Den beschreibt diese Datei:
//
//   • Eine verborgen-Zeile ist NEU genug (< AUFBEWAHRUNG_TAGE) -> sie erscheint als Eintrag
//     im Papierkorb und lässt sich mit einem Tippen zurückholen.
//   • Danach verschwindet nur der EINTRAG. Die Zeile bleibt, das Spiel bleibt ausgeblendet.
//     Das ist die wichtige Unterscheidung: Ablaufen lässt der Papierkorb die Möglichkeit,
//     etwas zurückzuholen — nicht das Verbergen selbst. Würde die Zeile mitverschwinden,
//     stünde das Spiel nach zwei Wochen von allein wieder in Liste und Statistik, und
//     ausgerechnet die Zusage „was ich entferne, zählt nicht mehr" wäre gebrochen.
//
// Ein Wettkampf ist EIN Eintrag, kein Stapel: verbergeWettkampf verbirgt ihn samt jedem
// seiner Durchgänge (sonst blieben deren Ergebnisse in der Statistik stehen). Im Papierkorb
// gehören die Durchgänge unter ihren Wettkampf und tauchen nicht einzeln auf — zurückgeholt
// wird ohnehin immer das Ganze.
//
// Zeilen ohne Gegenstück (das Spiel ist inzwischen wirklich aus der Datenbank verschwunden,
// oder es fehlt das Leserecht) fallen heraus: da ist nichts, was sich zurückholen ließe.
//
// Reine Logik ohne Store/DOM/Netz (Browser + Node ladbar, per Unit-Test abgesichert).

// Zwei Wochen. Lang genug, dass ein versehentliches Entfernen auffällt, kurz genug, dass der
// Papierkorb nicht zur zweiten Historie wird.
export const AUFBEWAHRUNG_TAGE = 14;

const TAG_MS = 24 * 60 * 60 * 1000;

const zeit = (v) => {
  const t = new Date(v == null ? NaN : v).getTime();
  return Number.isNaN(t) ? null : t;
};

// Wie viele Tage bleiben noch? Aufgerundet, damit „noch 1 Tag" bis zum letzten Moment gilt
// und nicht schon nach 23 Stunden auf 0 springt. 0 = abgelaufen (auch bei unlesbarem Datum:
// was sich nicht datieren lässt, gehört nicht in einen Papierkorb mit Frist).
export function restTage(verborgenAm, jetzt = Date.now(), tage = AUFBEWAHRUNG_TAGE) {
  const t = zeit(verborgenAm);
  if (t == null) return 0;
  const rest = (t + tage * TAG_MS) - (zeit(jetzt) ?? Date.now());
  return rest <= 0 ? 0 : Math.ceil(rest / TAG_MS);
}

export function imPapierkorb(verborgenAm, jetzt = Date.now(), tage = AUFBEWAHRUNG_TAGE) {
  return restTage(verborgenAm, jetzt, tage) > 0;
}

// Die Einträge des Papierkorbs aus den Rohdaten bauen.
//
//   rows        — Zeilen aus `verborgen`: { art, objekt_id, verborgen_am }
//   spiele      — { spiel_id -> Zeile aus `spiel` } (die, die sich lesen ließen)
//   wettkaempfe — { wettkampf_id -> Zeile aus `wettkampf` }
//
// Rückgabe: [{ art, id, verborgenAm, restTage, objekt }], zuletzt entferntes zuerst.
export function papierkorbEintraege(rows, {
  spiele = {}, wettkaempfe = {}, jetzt = Date.now(), tage = AUFBEWAHRUNG_TAGE,
} = {}) {
  const liste = (rows || []).filter((r) => r && r.objekt_id && imPapierkorb(r.verborgen_am, jetzt, tage));

  // Welche Wettkämpfe liegen selbst im Papierkorb? Ihre Durchgänge gehören dann zu ihnen.
  const wkImKorb = new Set(liste.filter((r) => r.art === 'wettkampf').map((r) => r.objekt_id));

  return liste
    .map((r) => {
      const wk = r.art === 'wettkampf';
      const objekt = wk ? wettkaempfe[r.objekt_id] : spiele[r.objekt_id];
      if (!objekt) return null;                    // nichts mehr da -> nichts zurückzuholen
      if (!wk && wkImKorb.has(objekt.wettkampf_id)) return null;  // Durchgang seines Wettkampfs
      return {
        art: r.art,
        id: r.objekt_id,
        verborgenAm: r.verborgen_am,
        restTage: restTage(r.verborgen_am, jetzt, tage),
        objekt,
      };
    })
    .filter(Boolean)
    .sort((a, b) => String(b.verborgenAm || '').localeCompare(String(a.verborgenAm || '')));
}

// Der Satz unter der Überschrift. Er muss beide Hälften sagen, sonst liest sich „verschwindet
// nach 14 Tagen" wie „kommt nach 14 Tagen von selbst zurück".
export const PAPIERKORB_HINWEIS =
  `Aus deinem Konto entfernt, in den letzten ${AUFBEWAHRUNG_TAGE} Tagen. Zurückholen stellt den `
  + 'Eintrag samt deiner Zuordnung wieder her. Danach verschwindet er nur aus dem Papierkorb — '
  + 'ausgeblendet bleibt er, und in der Datenbank hat ohnehin nie etwas gefehlt.';
