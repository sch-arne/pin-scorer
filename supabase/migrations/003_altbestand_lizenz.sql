-- =============================================================================
-- 003 — LizenzIDs aus dem Wettkampf-Altbestand entfernen
-- =============================================================================
-- NACH policies.sql einspielen (braucht den Trigger trg_wettkampf_ohne_personendaten).
-- Läuft genau einmal.
--
-- Wettkämpfe, die vor sportwinnerOhnePersonendaten geteilt wurden, tragen in
-- config_json.sportwinner.spieler[] noch `pass` (LizenzID) und `extId` jedes Spielers. Die
-- Zuschauer-/Overlay-RPCs lassen den Block zwar weg, Mitglieder lesen ihn aber mit. Das Update
-- schreibt config_json unverändert zurück; der Trigger entfernt dabei beide Felder. `seiten`
-- und `slot` bleiben stehen — das Rückschreiben an Sportwinner braucht nur sie.
-- =============================================================================
begin;

do $$
begin
  if to_regclass('public.schema_migration') is null then
    raise exception 'Zuerst supabase/migrations/000_schema_migration.sql einspielen.';
  end if;
  if exists (select 1 from schema_migration where name = '003_altbestand_lizenz') then
    raise exception 'Migration 003_altbestand_lizenz ist bereits eingespielt.';
  end if;
  if not exists (select 1 from pg_trigger where tgname = 'trg_wettkampf_ohne_personendaten') then
    raise exception 'Zuerst supabase/policies.sql einspielen (Trigger trg_wettkampf_ohne_personendaten fehlt).';
  end if;
end $$;

update wettkampf
   set config_json = config_json
 where jsonb_typeof(config_json #> '{sportwinner,spieler}') = 'array';

insert into schema_migration (name) values ('003_altbestand_lizenz');

commit;
