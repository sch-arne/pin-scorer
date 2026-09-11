-- =============================================================================
-- 001 — Rechte am KONTO statt an der Geräte-ID
-- =============================================================================
-- Bestehende DB: VOR schema.sql + policies.sql einspielen (die neuen Policies brauchen die
-- Spalten). Läuft genau einmal (Guard unten).
--
-- Warum: Die Tabelle `geraet` bindet eine vom Client erzeugte Geräte-ID an ein Konto, und
-- dieselbe ID darf an mehrere Konten gebunden sein (PK (id, konto)). Mitgliedschaft und
-- Erfassungs-Lock wurden bisher über diese Bindung aufgelöst. Wer eine fremde Geräte-ID kannte
-- — sie steht in spiel_geraet und spiel_spieler.besitzer_geraet, für jedes Mitglied lesbar —,
-- konnte sie an sein eigenes (auch anonymes) Konto binden und war damit Mitglied in allen
-- Spielen dieses Geräts: Eingabe-Codes, Klarnamen und LizenzIDs lesen, Würfe für die gehaltenen
-- Spieler schreiben.
--
-- Ab hier hängen die Rechte am Konto: spiel_geraet / wettkampf_geraet tragen das Konto, das
-- beigetreten ist, spiel_spieler.besitzer_konto das Konto, das den Spieler hält. Die Geräte-ID
-- bleibt als Etikett (Koordination zwischen den eigenen Geräten), gibt aber keine Rechte mehr.
--
-- Der Backfill übernimmt JEDE heutige Bindung als eigene Zeile. Der Zugriff ist unmittelbar
-- danach also genau derselbe wie vorher — er lässt sich ab jetzt nur nicht mehr erweitern.
-- Spieler, deren Geräte-ID an mehrere Konten gebunden ist (anonym -> Konto auf demselben
-- Browser), werden freigegeben: das erfassende Gerät übernimmt sie beim nächsten Öffnen neu.
-- =============================================================================
begin;

do $$
begin
  if to_regclass('public.schema_migration') is null then
    raise exception 'Zuerst supabase/migrations/000_schema_migration.sql einspielen.';
  end if;
  if exists (select 1 from schema_migration where name = '001_rechte_am_konto') then
    raise exception 'Migration 001_rechte_am_konto ist bereits eingespielt.';
  end if;
end $$;

-- --- spiel_geraet: Mitgliedschaft je Konto -----------------------------------
alter table spiel_geraet add column if not exists konto uuid references auth.users(id) on delete cascade;
alter table spiel_geraet drop constraint if exists spiel_geraet_pkey;
insert into spiel_geraet (spiel_id, geraet, konto, beigetreten_am)
  select sg.spiel_id, sg.geraet, g.konto, sg.beigetreten_am
    from spiel_geraet sg
    join geraet g on g.id = sg.geraet
   where sg.konto is null;
delete from spiel_geraet where konto is null;
alter table spiel_geraet alter column konto set default auth.uid();
alter table spiel_geraet alter column konto set not null;
alter table spiel_geraet add constraint spiel_geraet_pkey primary key (spiel_id, konto, geraet);
create index if not exists idx_spiel_geraet_konto on spiel_geraet(konto);

-- --- wettkampf_geraet: dasselbe auf Wettkampf-Ebene --------------------------
alter table wettkampf_geraet add column if not exists konto uuid references auth.users(id) on delete cascade;
alter table wettkampf_geraet drop constraint if exists wettkampf_geraet_pkey;
insert into wettkampf_geraet (wettkampf_id, geraet, konto, beigetreten_am)
  select wg.wettkampf_id, wg.geraet, g.konto, wg.beigetreten_am
    from wettkampf_geraet wg
    join geraet g on g.id = wg.geraet
   where wg.konto is null;
delete from wettkampf_geraet where konto is null;
alter table wettkampf_geraet alter column konto set default auth.uid();
alter table wettkampf_geraet alter column konto set not null;
alter table wettkampf_geraet add constraint wettkampf_geraet_pkey primary key (wettkampf_id, konto, geraet);
create index if not exists idx_wettkampf_geraet_konto on wettkampf_geraet(konto);

-- --- spiel_spieler: welches Konto hält den Spieler? --------------------------
alter table spiel_spieler add column if not exists besitzer_konto uuid references auth.users(id) on delete set null;
update spiel_spieler sp
   set besitzer_konto = (select g.konto from geraet g where g.id = sp.besitzer_geraet)
 where sp.besitzer_geraet is not null
   and (select count(*) from geraet g where g.id = sp.besitzer_geraet) = 1;
update spiel_spieler
   set besitzer_geraet = null, besitzer_seit = null
 where besitzer_geraet is not null and besitzer_konto is null;

insert into schema_migration (name) values ('001_rechte_am_konto');

commit;
