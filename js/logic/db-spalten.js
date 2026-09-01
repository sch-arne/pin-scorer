// Schreiben gegen eine Datenbank, die eine neue Spalte noch nicht kennt.
//
// Die SQL-Skripte (supabase/schema.sql, supabase/policies.sql) werden VON HAND eingespielt.
// Code und DB laufen deshalb regelmäßig kurz auseinander: die Test-DB ist migriert, die
// Prod-DB noch nicht — oder ein Deploy geht der Migration voraus. Nennt ein Insert/Upsert
// dann eine Spalte, die es auf DIESER DB nicht gibt, antwortet PostgREST mit PGRST204
// ("Could not find the '…' column … in the schema cache") und der GANZE Vorgang scheitert.
// Beim Teilen hieß das: kein geteiltes Spiel, nur ein „Teilen fehlgeschlagen" — obwohl bloß
// ein Zusatzfeld fehlte, an dem weder die Erfassung noch der Beitritt hängen.
//
// Deshalb: die optionalen Spalten einmal je Tabelle als „kennt diese DB nicht" merken, aus
// allen Zeilen entfernen und den Schreibvorgang wiederholen. Die daran hängende Funktion
// (Anonymisierung, accountbasierte Statistik) fällt still aus, das Teilen läuft weiter.
//
// Reine Logik ohne Netz: der eigentliche Schreibvorgang kommt als `run(rows)` herein.

// Meldet der Fehler eine Spalte, die es nicht gibt? PostgREST: PGRST204 (Schema-Cache),
// Postgres direkt: 42703. Der Textvergleich ist nur der Gürtel zum Hosenträger.
export function istUnbekannteSpalte(error) {
  if (!error) return false;
  if (error.code === 'PGRST204' || error.code === '42703') return true;
  return /column .* does not exist|could not find the .* column/i.test(error.message || '');
}

// Neue Zeilen ohne die genannten Schlüssel (Eingaben bleiben unverändert).
export function ohneSpalten(rows, keys) {
  return (rows || []).map((r) => {
    const o = { ...r };
    keys.forEach((k) => { delete o[k]; });
    return o;
  });
}

// Merkt sich je Tabelle, dass die optionalen Spalten hier fehlen — damit jeder weitere
// Schreibvorgang derselben Sitzung sie gar nicht erst mitschickt (ein Fehlversuch genügt).
export function neuerSpaltenSpeicher() {
  const fehlt = new Set();
  return {
    kennt: (table) => !fehlt.has(table),
    merken: (table) => fehlt.add(table),
  };
}

const globalerSpeicher = neuerSpaltenSpeicher();

// `run(rows)` führt Insert/Upsert aus und gibt { data, error } zurück (Supabase-Konvention).
// `onFallback(table, optionale, error)` wird einmal gerufen, wenn auf die Spalten verzichtet
// werden musste — für einen Konsolen-Hinweis, dass eine Migration fehlt.
export async function schreibeVertraeglich(table, rows, optionale, run, opts = {}) {
  const speicher = opts.speicher || globalerSpeicher;
  const versuchen = speicher.kennt(table);
  let res = await run(versuchen ? rows : ohneSpalten(rows, optionale));
  if (res && res.error && versuchen && istUnbekannteSpalte(res.error)) {
    speicher.merken(table);
    if (opts.onFallback) opts.onFallback(table, optionale, res.error);
    res = await run(ohneSpalten(rows, optionale));
  }
  return res;
}
