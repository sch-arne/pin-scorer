// Transport der erkannten Würfe: aus der Tabelle `erkannter_wurf` in die App.
//
// Wird nur LAZY geladen (dynamic import), wie der ganze Sync — ohne Verbindung läuft die
// App vollständig weiter, nur eben ohne Erkennung.
//
// Diese Datei holt und schreibt, sie entscheidet nichts. Die Entscheidungen liegen in
// `logic/erkennung-zuordnung.js` (welcher Wurf gehört wohin) und `logic/erkennung-strom.js`
// (Reihenfolge, Puffer, Modus); die Wurferfassung schreibt über `addWurfAn`. So bleibt der
// Teil, der Regeln kennt, ohne Netz prüfbar.
//
// ZWEI DINGE, DIE HIER WICHTIG SIND:
//
// 1. **Das Tafelbild wird NIE in einer Liste mitgeladen.** `board_jpeg` ist ein Base64-JPEG
//    von rund 5 KB je Wurf; bei 2000 Würfen am Spieltag wären das 9 MB, die über die
//    Leitung gingen, nur um eine Wurfliste zu zeigen. Es gibt deshalb eine eigene Funktion
//    für den einen Wurf, den jemand ansieht.
// 2. **Kein `select()` nach dem Einfügen** — das betrifft hier nur den Erkenner, aber der
//    Grund lohnt die Notiz: Ein `insert ... returning` verlangt zusätzlich das Leserecht
//    auf die neue Zeile. Beim Zuordnen (update) brauchen wir die Rückgabe dagegen, denn
//    `0 Zeilen` ist die Antwort der Datenbank auf „die gehört dir nicht".

import { supabase } from './supabase.js';
import { WURF_SELECT, erkennerAusZeile, nurGemessenes } from '../logic/erkennung-zeilen.js';

// Die Spaltenliste und die Zeilen-Umformungen stehen in logic/erkennung-zeilen.js — sie
// sind ohne Netz pruefbar, und an der Spaltenliste haengt, ob versehentlich die Tafelbilder
// mitgeladen werden. Hier nur weitergereicht, damit Aufrufer eine Anlaufstelle haben.
export { WURF_SELECT, erkennerAusZeile, nurGemessenes };

export async function erkennerFuerAnlage(anlageId) {
  if (!anlageId) return [];
  const { data, error } = await supabase
    .from('erkenner')
    .select('id, name, aktiv, anlage_id, bahn_zuordnung, bahn:bahn_id(nummer)')
    .eq('anlage_id', anlageId)
    .eq('aktiv', true);
  if (error) throw error;
  return (data || []).map(erkennerAusZeile);
}

// Die noch offenen Würfe dieser Erkenner. `seitId` ist der Stand aus
// `erkennung-strom.js` (`gesehenBis`): die id steigt beim Einfügen, also ist alles
// darunter abgearbeitet.
//
// Sortiert wird hier nach `id`, nicht nach `recorded_at` — absichtlich: Es geht nur darum,
// den Schwung zu begrenzen und keine Zeile zu überspringen. Die fachliche Reihenfolge stellt
// `sortiereZeilen` im Strom her, und die ist eine andere (nachgelieferte Würfe tragen eine
// neue id, aber ihre alte Zeit).
export async function offeneWuerfe({ erkennerIds, seitId = 0, limit = 200 }) {
  if (!erkennerIds || !erkennerIds.length) return [];
  const { data, error } = await supabase
    .from('erkannter_wurf')
    .select(WURF_SELECT)
    .in('erkenner_id', erkennerIds)
    .is('satz_block_id', null)
    .is('verworfen_grund', null)
    .gt('id', seitId)
    .order('id', { ascending: true })
    .limit(limit);
  if (error) throw error;
  return data || [];
}

// Neue Würfe, während gespielt wird. Ein Kanal, ein Abo je Erkenner — die Filter von
// Realtime kennen nur einfache Vergleiche, und `eq` je Erkenner ist eindeutiger als eine
// Liste. `onNeu` bekommt die eingefügte Zeile; sie enthält alle Spalten der Tabelle,
// also AUCH das Tafelbild. Deshalb reicht der Transport nur die gemessenen Felder weiter:
// sonst hinge am Live-Pfad unbemerkt ein Megabyte je Minute.
export function abonniereWuerfe({ erkennerIds, onNeu }) {
  if (!erkennerIds || !erkennerIds.length) return () => {};
  const kanal = supabase.channel('erk:' + Math.random().toString(36).slice(2, 7));
  erkennerIds.forEach((id) => {
    kanal.on('postgres_changes',
      { event: 'INSERT', schema: 'public', table: 'erkannter_wurf', filter: `erkenner_id=eq.${id}` },
      ({ new: zeile }) => onNeu && onNeu(nurGemessenes(zeile)));
  });
  kanal.subscribe();
  return () => { supabase.removeChannel(kanal); };
}

// Die id der Satz-Zeile, an die ein Wurf gebunden wird.
//
// WARUM EINE EIGENE ABFRAGE: Die App kennt ihre Blöcke als `bloecke[sp][st]` — eine
// Position im Array, keine Datenbank-id. Geschrieben werden sie mit einem `upsert` auf
// (spieler_id, satz), das nichts zurückgibt. Für `erkannter_wurf.satz_block_id` braucht es
// aber genau diese id: sie ist der Verweis vom erkannten Wurf auf den Wurf im Satz, und
// damit der ganze Zweck der Anbindung.
//
// Der Aufrufer merkt sich das Ergebnis je (Spieler, Satz) — es ändert sich nicht mehr,
// sobald die Zeile einmal existiert. Gibt es sie noch nicht (der erste Wurf ist gerade
// hochgeschrieben worden, die Antwort steht noch aus), kommt `null` zurück; dann wird der
// Wurf eben beim nächsten Mal gebunden. Dass der Wurf im Satz steht, hängt nicht daran.
export async function satzBlockId({ spielId, spielerId, satz }) {
  if (!spielId || !spielerId || satz == null) return null;
  const { data, error } = await supabase
    .from('satz_block')
    .select('id')
    .eq('spiel_id', spielId)
    .eq('spieler_id', spielerId)
    .eq('satz', satz)
    .maybeSingle();
  if (error) throw error;
  return (data && data.id) || null;
}

// Einen erkannten Wurf an seine Stelle im Satz binden. Rückgabe false = die Datenbank hat
// es verweigert (fremde Bahn, fremdes Spiel) oder jemand war schneller. Das ist kein
// Fehlerfall, sondern die normale Antwort auf „die Zeile gehört dir nicht" — deshalb eine
// Rückgabe und keine Ausnahme.
export async function zuordnen(wurfId, { spielId, satzBlockId, wurfIndex }) {
  const { data, error } = await supabase
    .from('erkannter_wurf')
    .update({
      spiel_id: spielId,
      satz_block_id: satzBlockId,
      wurf_index: wurfIndex,
      uebernommen_am: new Date().toISOString(),
    })
    .eq('id', wurfId)
    .is('satz_block_id', null)          // nicht überschreiben, was schon zugeordnet ist
    .select('id');
  if (error) throw error;
  return Array.isArray(data) && data.length > 0;
}

// Einen Wurf als bewusst nicht übernommen vermerken. NUR für Befunde, die für jedes Gerät
// gelten (`merken` in der Zuordnung) — eine fremde Bahn ist nur für mich keine Bahn, und
// ein Vermerk nähme dem anderen Spiel den Wurf weg.
export async function verwerfen(wurfId, grund) {
  const { data, error } = await supabase
    .from('erkannter_wurf')
    .update({ verworfen_grund: String(grund || 'verworfen').slice(0, 300) })
    .eq('id', wurfId)
    .is('satz_block_id', null)
    .select('id');
  if (error) throw error;
  return Array.isArray(data) && data.length > 0;
}

// Einen Wurf, der SCHON zugeordnet war, wieder freigeben und als verworfen vermerken.
//
// Der Weg dafür ist „Erkannte Würfe dieses Satzes verwerfen": Die Kamera lief schon beim
// Einspielen, ihre Würfe stehen im Satz, und sie sollen alle wieder heraus. `verwerfen`
// kann das nicht — es lässt eine zugeordnete Zeile bewusst in Ruhe, damit niemand einen
// fremden Verweis überschreibt. Hier ist das Gegenteil gewollt: Der Verweis MUSS weg, sonst
// zeigt er auf einen Wurf, den es im Satz nicht mehr gibt.
//
// `wurf_index` und `uebernommen_am` werden mitgeräumt — eine Zeile, die auf nichts mehr
// zeigt, soll auch nicht behaupten, sie sei um 19:42 übernommen worden.
export async function freigeben(wurfId, grund) {
  const { data, error } = await supabase
    .from('erkannter_wurf')
    .update({
      spiel_id: null,
      satz_block_id: null,
      wurf_index: null,
      uebernommen_am: null,
      verworfen_grund: String(grund || 'verworfen').slice(0, 300),
    })
    .eq('id', wurfId)
    .select('id');
  if (error) throw error;
  return Array.isArray(data) && data.length > 0;
}

// Das Tafelbild eines einzelnen Wurfs — der Beleg, wenn jemand einen Wert anzweifelt.
// Bewusst eine eigene Abfrage: siehe Kopf dieser Datei.
export async function tafelbild(wurfId) {
  const { data, error } = await supabase
    .from('erkannter_wurf')
    .select('id, board_jpeg, board_before_jpeg, displayed_pin_count, displayed_throw_number, '
            + 'displayed_foul_count, displayed_total')
    .eq('id', wurfId)
    .maybeSingle();
  if (error) throw error;
  return data || null;
}
