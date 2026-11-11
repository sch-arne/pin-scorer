// Die Form der Zeilen aus `erkannter_wurf` und `erkenner` — reine Logik, ohne Netz.
//
// Warum getrennt von `backend/erkennung.js`: Dort steckt der Supabase-Client, und der kommt
// per Netz-Import von esm.sh. Alles, was sich ohne Verbindung prüfen lässt, gehört deshalb
// hierher — die Spaltenliste eingeschlossen, denn genau an ihr entscheidet sich, ob
// versehentlich ein Megabyte Tafelbilder mitgeladen wird.

// Die Spalten, die eine WURFLISTE braucht: die gemessenen plus die Zuordnung.
//
// Bewusst OHNE `board_jpeg`/`board_before_jpeg`. Das Tafelbild ist ein Base64-JPEG von rund
// 5 KB je Wurf; bei 2000 Würfen am Spieltag wären das 9 MB, nur um eine Liste zu zeigen.
// Es wird einzeln geholt, für den einen Wurf, den jemand ansieht.
// Auch ohne die vier Tafel-Ablesungen (`displayed_*`): Sie sind Beleg, keine Eingabe für
// die Zuordnung, und gehören zum Bild.
export const WURF_SPALTEN = [
  'id', 'erkenner_id', 'lane', 'pins_count', 'pins', 'recorded_at', 'video_time_s',
  'video_id', 'spiel_id', 'satz_block_id', 'wurf_index', 'uebernommen_am', 'verworfen_grund',
];

export const WURF_SELECT = WURF_SPALTEN.join(', ');

// Spalten, die in einer Liste NIE vorkommen dürfen. Als eigene Liste, damit ein Test das
// zusichern kann: Die Grenze ist leicht übersehbar, und ihr Verlust fällt erst an der
// Leitung auf.
export const NUR_EINZELN = ['board_jpeg', 'board_before_jpeg'];

// Eine `erkenner`-Zeile (mit eingebetteter Bahn) in die Form bringen, die
// `erkennung-zuordnung.js` erwartet: `bahn_nummer` ist die NUMMER der gekoppelten Bahn,
// nicht ihre id — sonst müsste die Zuordnung nachfragen, um eine `lane` zu übersetzen.
export function erkennerAusZeile(zeile) {
  if (!zeile) return null;
  return {
    id: zeile.id,
    name: zeile.name || '',
    aktiv: zeile.aktiv !== false,
    anlage_id: zeile.anlage_id || null,
    bahn_nummer: zeile.bahn && zeile.bahn.nummer != null ? zeile.bahn.nummer : null,
    bahn_zuordnung: zeile.bahn_zuordnung || {},
  };
}

// Aus einer Realtime-Zeile nur das behalten, was in eine Liste gehört.
//
// Realtime liefert die GANZE eingefügte Zeile, Tafelbild inklusive — eine Spaltenauswahl
// wie beim Abfragen gibt es dort nicht. Ohne dieses Sieb hinge am Live-Pfad unbemerkt ein
// Megabyte je Minute, und die Zeilen lägen mitsamt Bild im Puffer der App.
export function nurGemessenes(zeile) {
  const raus = {};
  if (!zeile) return raus;
  WURF_SPALTEN.forEach((name) => {
    if (name in zeile) raus[name] = zeile[name];
  });
  return raus;
}
