-- =============================================================================
-- 002 — Frist für Klarnamen (stündlich per pg_cron)
-- =============================================================================
-- NACH policies.sql einspielen (braucht pins_klarnamen_frist()). Läuft genau einmal.
--
-- Plant die Funktion pins_klarnamen_frist() stündlich ein (Erklärung dort, policies.sql) und
-- ruft sie einmal sofort auf, damit der Altbestand — Spiele, die nie auf 'beendet' gingen —
-- nicht erst eine Stunde warten muss. Die letzte Zeile zeigt, wie viele Spiele dabei ihre
-- Klarnamen verloren haben.
--
-- Scheitert `create extension`, pg_cron im Supabase-Dashboard aktivieren
-- (Database -> Extensions -> pg_cron) und die Datei erneut einspielen.
-- =============================================================================
begin;

do $$
begin
  if to_regclass('public.schema_migration') is null then
    raise exception 'Zuerst supabase/migrations/000_schema_migration.sql einspielen.';
  end if;
  if exists (select 1 from schema_migration where name = '002_klarnamen_frist') then
    raise exception 'Migration 002_klarnamen_frist ist bereits eingespielt.';
  end if;
  if to_regprocedure('public.pins_klarnamen_frist()') is null then
    raise exception 'Zuerst supabase/policies.sql einspielen (pins_klarnamen_frist fehlt).';
  end if;
end $$;

create extension if not exists pg_cron with schema pg_catalog;

select cron.schedule('pins-klarnamen-frist', '23 * * * *', 'select public.pins_klarnamen_frist()');

insert into schema_migration (name) values ('002_klarnamen_frist');

select public.pins_klarnamen_frist() as spiele_ohne_klarnamen;

commit;
