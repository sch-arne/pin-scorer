-- =============================================================================
-- 000 — Buchführung über eingespielte Migrationen
-- =============================================================================
-- Einmalig vor allen anderen Migrationen. Idempotent: darf beliebig oft laufen.
-- Hintergrund und Reihenfolge: supabase/migrations/README.md
--
-- Kein Client liest oder schreibt die Tabelle: RLS an, keine Policies. Gepflegt wird sie
-- ausschließlich von den Migrationsdateien im SQL-Editor.
create table if not exists schema_migration (
  name text primary key,
  am   timestamptz not null default now()
);
alter table schema_migration enable row level security;
