// Was „Löschen" bedeutet, hängt davon ab, WO ein Spiel liegt. Drei Fälle, eine Entscheidung —
// hier, damit jede Stelle der Oberfläche (Neues Spiel, Wettkampf-Hub, Statistiken) dieselbe
// trifft und dieselbe Frage stellt:
//
//   KOMPLETT  — rein lokal (kein Gegenpart in der Datenbank). Endgültig weg, sofort, offline.
//   VERBERGEN — liegt in der Datenbank und gehört MIR. Es verschwindet aus MEINER Übersicht
//               und MEINER Statistik — sonst ändert sich nichts: die Aufzeichnung bleibt in
//               der Datenbank, der Freigabe-Link gilt weiter, Mitspieler, Zuschauer und das
//               OBS-Overlay merken nichts davon. Wer es bei sich entfernt, fliegt selbst
//               raus, nicht die anderen. Gilt ausdrücklich auch, WÄHREND anderswo noch
//               erfasst wird: die eigene Kopie geht immer weg, auch offline — nur der
//               Vermerk fürs Konto braucht Verbindung.
//   NUR_HIER  — liegt in der Datenbank, gehört mir NICHT, aber auf DIESEM Gerät liegt eine
//               Kopie (per Code beigetreten). Entfernt wird genau diese Kopie; in der
//               Datenbank ändert sich nichts, denn dort gehört mir nichts davon.
//   GESPERRT  — gehört mir nicht und liegt auch nicht hier: die Ergebnisse, die einen über
//               die eigene LizenzID aus fremd erfassten Spielen finden. Da ist schlicht
//               nichts, was sich entfernen ließe.
//
// Reine Logik ohne Store/DOM/Netz (Browser + Node ladbar, per Unit-Test abgesichert).

export const KOMPLETT = 'komplett';
export const VERBERGEN = 'verbergen';
export const NUR_HIER = 'nur-hier';
export const GESPERRT = 'gesperrt';

const txt = (v) => String(v == null ? '' : v).trim();

// Wem gehört der Eintrag? `besitzer` steht an aus der Datenbank geladenen Objekten
// (sync.assembleLocalGame/pullWettkampf); `erfasstVon` ist der Ersatzweg über die
// Ergebniszeile, wenn nur die vorliegt. Ist beides leer, ist es ein selbst angelegtes
// Objekt — dann bin ich der Besitzer.
function fremd(obj, konto, erfasstVon) {
  const ich = txt(konto);
  const besitzer = txt(obj && obj.besitzer) || txt(erfasstVon);
  if (!besitzer) return false;
  return besitzer !== ich;
}

// Wie ist mit diesem Spiel/Wettkampf umzugehen? `obj` ist ein lokales Spiel- oder
// Wettkampf-Objekt (auch ein aus der Datenbank assembliertes). `lokal` sagt, ob auf DIESEM
// Gerät eine Kopie liegt — daran entscheidet sich bei fremden Spielen, ob es überhaupt etwas
// zu entfernen gibt (Fortsetzen-Liste: ja; eine nur über die LizenzID gefundene Karte: nein).
export function loeschart(obj, { konto = null, erfasstVon = null, lokal = false } = {}) {
  if (!obj) return GESPERRT;
  const inDb = !!txt(obj.remoteId);
  const nichtMeins = fremd(obj, konto, erfasstVon);
  if (!inDb) return nichtMeins ? GESPERRT : KOMPLETT;
  if (!nichtMeins) return VERBERGEN;
  return lokal ? NUR_HIER : GESPERRT;
}

export const darfLoeschen = (art) => art !== GESPERRT;

// Die Rückfrage vor dem Löschen. Sie muss den Unterschied benennen, sonst wüsste niemand,
// ob gerade etwas endgültig verschwindet oder bloß aus der eigenen Sicht.
// `wettkampf: true` zieht die Durchgänge und das OBS-Overlay mit in den Text.
export function loeschFrage(art, { wettkampf = false } = {}) {
  const was = wettkampf ? 'Diesen Wettkampf mit allen Durchgängen' : 'Dieses Spiel';
  const er = wettkampf ? 'Er' : 'Es';
  if (art === KOMPLETT) {
    return `${was} wirklich löschen? ${er} liegt nur auf diesem Gerät und ist danach endgültig weg.`;
  }
  if (art === VERBERGEN) {
    return `${was} aus deiner Übersicht und deinen Statistiken entfernen?`
      + ' Das gilt nur für dich: die aufgezeichneten Daten bleiben in der Datenbank bestehen,'
      + ` der Freigabe-Link${wettkampf ? ' (inkl. OBS-Overlay)' : ''} gilt weiter, und wer`
      + ' gerade mit erfasst, macht ungestört weiter.';
  }
  if (art === NUR_HIER) {
    return `${was} von diesem Gerät entfernen?`
      + ' Es gehört einem anderen Konto — dort und bei allen anderen bleibt alles unverändert,'
      + ' und du kannst jederzeit mit dem Code wieder beitreten.';
  }
  return '';
}

// GESPERRT heißt: gehört einem anderen Konto UND liegt nicht auf diesem Gerät — es gibt also
// gar nichts zu entfernen. So kommen die Ergebnisse an, die einen über die eigene LizenzID aus
// fremd erfassten Spielen finden.
// Die eigene Statistik ohne das, was ich bei mir entfernt habe. `rows` sind Ergebniszeilen
// (spiel_ergebnis) mit `spiel_id`, `versteckt` die Menge meiner verborgenen Spiel-IDs.
//
// Das ist DIE Stelle, an der die Zusage „was ich lösche, zählt auch nicht mehr" eingelöst
// wird — und sie muss beide Wege ins Profil abfangen: die ausdrückliche Zuordnung
// (profil_id) UND den Fund über die eigene LizenzID (passnummer). Deshalb wird am SPIEL
// gefiltert und nicht daran, wie die Zeile gefunden wurde. Ein verborgener Wettkampf trägt
// dafür jeden seiner Durchgänge in `versteckt` (sync.verbergeWettkampf).
export function ohneVerborgene(rows, versteckt) {
  if (!versteckt || !versteckt.size) return rows || [];
  return (rows || []).filter((r) => !versteckt.has(r && r.spiel_id));
}

export const GESPERRT_HINWEIS =
  'Dieses Ergebnis kam über deine LizenzID aus einem Spiel, das jemand anderes erfasst hat. '
  + 'Auf diesem Gerät liegt nichts davon, und in fremden Aufzeichnungen wird nicht gelöscht.';

// Nach dem Entfernen, wenn der Vermerk fürs Konto nicht geschrieben werden konnte. Die eigene
// Kopie ist weg — verschwiegen wird aber nicht, dass das Spiel später wiederkommen kann.
export const VERMERK_FEHLT =
  'Von diesem Gerät entfernt. Der Vermerk für dein Konto ließ sich gerade nicht speichern '
  + '(keine Verbindung?) — sobald das Spiel beendet ist, kann es in deinen Statistiken wieder '
  + 'auftauchen. Dann dort erneut entfernen.';
