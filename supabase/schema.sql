-- =============================================================================
-- Pins-Scorer — Supabase / Postgres Schema
-- =============================================================================
-- Im Supabase SQL-Editor ausführen (einmalig; ist idempotent per IF NOT EXISTS).
-- Danach policies.sql ausführen (Row-Level-Security).
--
-- Leitidee: Ein Spieler gehört zu jeder Zeit genau EINEM Gerät (ein Gerät darf
-- mehrere Spieler steuern). Deshalb ist die natürliche Partitionsgrenze der
-- Spieler, nicht der einzelne Wurf. Die Live-Erfassung liegt pro Spieler pro
-- Satz als eine Zeile (satz_block.block_json) — 1:1 wie die heutige lokale
-- Struktur erfassung.bloecke[spieler][satz].
--
-- Geräte-Identität = anonyme Supabase-Auth-uid (Anonymous Sign-In). Beim späteren
-- Account-Schritt wird der anonyme Nutzer per Magic-Link zu einem echten Account
-- aufgewertet; die uid bleibt gleich, deshalb ist auth.uid() gleichzeitig das
-- "Gerät" (Spielbetrieb) UND die Person (Statistik-Historie).
-- =============================================================================

-- 1:1 zu auth.users. Wird erst im Account-Schritt befüllt (anon-Nutzer haben keins).
create table if not exists profil (
  id            uuid primary key references auth.users(id) on delete cascade,
  anzeigename   text,
  erstellt_am   timestamptz not null default now()
);

-- Stub für den späteren Anlagen-Schritt (Menü-Kachel "Anlagen"). Bewusst minimal.
create table if not exists anlage (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  ort           text,
  besitzer      uuid references auth.users(id) on delete set null,
  erstellt_am   timestamptz not null default now()
);

-- Ein Spiel. config_json = das gesamte Setup-Objekt (bahnart, bahnen, ersteBahn,
-- spieler, bahnwechsel, saetze, wuerfeProSatz, teilsaetze[], bahnplan[][], ...).
-- Setup-Metadaten ändern sich selten und werden vom Ersteller verwaltet.
create table if not exists spiel (
  id             uuid primary key default gen_random_uuid(),
  besitzer       uuid references auth.users(id) on delete set null,
  spielart       text not null default 'sportkegler-wk',
  status         text not null default 'setup' check (status in ('setup','laufend','beendet')),
  config_json    jsonb not null default '{}'::jsonb,
  beitritts_code text unique default upper(substr(md5(random()::text), 1, 6)),
  anlage_id      uuid references anlage(id) on delete set null,
  erstellt_am    timestamptz not null default now(),
  aktualisiert_am timestamptz not null default now()
);

-- Mitgliedschaft: welches Gerät ist welchem Spiel beigetreten. Basis der RLS-Regeln.
create table if not exists spiel_geraet (
  spiel_id       uuid not null references spiel(id) on delete cascade,
  geraet         uuid not null,
  beigetreten_am timestamptz not null default now(),
  primary key (spiel_id, geraet)
);

-- Teilnehmer eines Spiels (= Spieler-Index/Position). besitzer_geraet ist der Lock:
-- nur dieses Gerät darf die satz_block-Zeilen des Spielers schreiben.
create table if not exists spiel_spieler (
  id              uuid primary key default gen_random_uuid(),
  spiel_id        uuid not null references spiel(id) on delete cascade,
  position        int  not null,               -- 0-basiert, = Spieler-Index in der App
  name            text,
  start_bahn      int,
  profil_id       uuid references auth.users(id) on delete set null,  -- Stats-Verknüpfung
  besitzer_geraet uuid,                         -- aktuell steuerndes Gerät (NULL = frei)
  besitzer_seit   timestamptz,
  heartbeat_am    timestamptz,                  -- für stale-Erkennung / Übernahme
  unique (spiel_id, position)
);

-- Live-Erfassung: eine Zeile pro Spieler pro Satz.
-- block_json = { wuerfe:[], kegel:[[]], koenig:[], overrides:[], done:bool }
-- (exakt der heutige erfassung.bloecke[spieler][satz]).
create table if not exists satz_block (
  id              uuid primary key default gen_random_uuid(),
  spiel_id        uuid not null references spiel(id) on delete cascade,
  spieler_id      uuid not null references spiel_spieler(id) on delete cascade,
  satz            int  not null,
  block_json      jsonb not null default '{}'::jsonb,
  geraet          uuid,                         -- schreibendes Gerät (= besitzer_geraet)
  aktualisiert_am timestamptz not null default now(),
  unique (spieler_id, satz)
);

-- Ergebnis-Snapshot je Spieler bei Spielende. Für schnelle Historie/Statistik,
-- ohne jeden Wurf aggregieren zu müssen. Aus computeGameStats geschrieben.
create table if not exists spiel_ergebnis (
  id            uuid primary key default gen_random_uuid(),
  spiel_id      uuid not null references spiel(id) on delete cascade,
  spieler_id    uuid not null references spiel_spieler(id) on delete cascade,
  profil_id     uuid references auth.users(id) on delete set null,
  gesamt        int,
  schnitt_satz  numeric,
  schnitt_wurf  numeric,
  bester_satz   int,
  neuner        int,
  fehl          int,
  wurf_count    int,
  rang          int,
  erstellt_am   timestamptz not null default now(),
  unique (spiel_id, spieler_id)
);

-- --- Indizes ----------------------------------------------------------------
create index if not exists idx_spiel_geraet_geraet   on spiel_geraet(geraet);
create index if not exists idx_spiel_spieler_spiel    on spiel_spieler(spiel_id);
create index if not exists idx_satz_block_spiel       on satz_block(spiel_id);
create index if not exists idx_satz_block_spieler     on satz_block(spieler_id);
create index if not exists idx_spiel_ergebnis_profil  on spiel_ergebnis(profil_id);
create index if not exists idx_spiel_ergebnis_spiel   on spiel_ergebnis(spiel_id);

-- --- aktualisiert_am automatisch pflegen ------------------------------------
create or replace function pins_touch_aktualisiert_am()
returns trigger language plpgsql as $$
begin
  new.aktualisiert_am := now();
  return new;
end;
$$;

drop trigger if exists trg_spiel_touch on spiel;
create trigger trg_spiel_touch before update on spiel
  for each row execute function pins_touch_aktualisiert_am();

drop trigger if exists trg_satz_block_touch on satz_block;
create trigger trg_satz_block_touch before update on satz_block
  for each row execute function pins_touch_aktualisiert_am();

-- --- Realtime: satz_block + spiel_spieler in die Realtime-Publication ---------
-- (Live-Sync der Würfe und des Besitz-Locks an alle beigetretenen Geräte.)
do $$
begin
  begin execute 'alter publication supabase_realtime add table satz_block';    exception when duplicate_object then null; end;
  begin execute 'alter publication supabase_realtime add table spiel_spieler';  exception when duplicate_object then null; end;
  begin execute 'alter publication supabase_realtime add table spiel';          exception when duplicate_object then null; end;
end $$;
