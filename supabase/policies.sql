-- =============================================================================
-- Pins-Scorer — Row-Level-Security (RLS)
-- =============================================================================
-- NACH schema.sql im Supabase SQL-Editor ausführen. Idempotent (drop policy if
-- exists vor jedem create). Setzt voraus, dass "Anonymous Sign-In" im Supabase-
-- Projekt aktiviert ist (Authentication → Providers → Anonymous).
--
-- Durchgesetzte Garantien:
--  * Nur einem Spiel BEIGETRETENE Geräte dürfen es lesen/beschreiben.
--  * Würfe (satz_block) eines Spielers darf NUR das Gerät schreiben, das den
--    Spieler aktuell besitzt (besitzer_geraet = auth.uid()).
--  * Setup/Config des Spiels verwaltet nur der Ersteller (spiel.besitzer).
--  * Die eigene Statistik-Historie ist über profil_id = auth.uid() lesbar.
-- =============================================================================

-- Helfer: Ist der aktuelle Nutzer (auth.uid()) dem Spiel beigetreten?
-- security definer, damit die Policy die Mitgliedschaftstabelle lesen darf, ohne
-- selbst wieder RLS auszulösen (Rekursion).
create or replace function pins_ist_mitglied(p_spiel uuid)
returns boolean
language sql security definer stable
set search_path = public as $$
  select exists (
    select 1 from spiel_geraet
    where spiel_id = p_spiel and geraet = auth.uid()
  );
$$;

-- Einem Spiel per Beitritts-Code beitreten. security definer, weil das beitretende
-- Gerät das Spiel noch nicht lesen darf (Henne/Ei). Legt die Mitgliedschaft an.
create or replace function spiel_beitreten(p_code text)
returns uuid
language plpgsql security definer
set search_path = public as $$
declare
  v_id uuid;
begin
  select id into v_id from spiel where beitritts_code = upper(p_code);
  if v_id is null then
    raise exception 'Ungültiger Beitritts-Code';
  end if;
  insert into spiel_geraet (spiel_id, geraet)
    values (v_id, auth.uid())
    on conflict (spiel_id, geraet) do nothing;
  return v_id;
end;
$$;

grant execute on function spiel_beitreten(text) to anon, authenticated;

-- --- RLS aktivieren ----------------------------------------------------------
alter table profil          enable row level security;
alter table anlage          enable row level security;
alter table spiel           enable row level security;
alter table spiel_geraet    enable row level security;
alter table spiel_spieler   enable row level security;
alter table satz_block      enable row level security;
alter table spiel_ergebnis  enable row level security;

-- =============================================================================
-- profil — nur die eigene Zeile
-- =============================================================================
drop policy if exists profil_select on profil;
create policy profil_select on profil for select
  using (id = auth.uid());

drop policy if exists profil_insert on profil;
create policy profil_insert on profil for insert
  with check (id = auth.uid());

drop policy if exists profil_update on profil;
create policy profil_update on profil for update
  using (id = auth.uid()) with check (id = auth.uid());

drop policy if exists profil_delete on profil;
create policy profil_delete on profil for delete
  using (id = auth.uid());

-- =============================================================================
-- spiel — Mitglieder lesen; nur der Ersteller ändert Setup/Status
-- =============================================================================
drop policy if exists spiel_select on spiel;
create policy spiel_select on spiel for select
  using (pins_ist_mitglied(id) or besitzer = auth.uid());

drop policy if exists spiel_insert on spiel;
create policy spiel_insert on spiel for insert
  with check (besitzer = auth.uid());

drop policy if exists spiel_update on spiel;
create policy spiel_update on spiel for update
  using (besitzer = auth.uid()) with check (besitzer = auth.uid());

drop policy if exists spiel_delete on spiel;
create policy spiel_delete on spiel for delete
  using (besitzer = auth.uid());

-- =============================================================================
-- spiel_geraet — Mitgliedschaft
--  * Ersteller trägt sich selbst ein (Beitritt anderer läuft über spiel_beitreten).
--  * Jeder sieht die Mitglieder von Spielen, in denen er selbst ist.
--  * Jeder kann seine eigene Mitgliedschaft wieder verlassen.
-- =============================================================================
drop policy if exists spiel_geraet_select on spiel_geraet;
create policy spiel_geraet_select on spiel_geraet for select
  using (geraet = auth.uid() or pins_ist_mitglied(spiel_id));

drop policy if exists spiel_geraet_insert on spiel_geraet;
create policy spiel_geraet_insert on spiel_geraet for insert
  with check (
    geraet = auth.uid()
    and exists (select 1 from spiel where id = spiel_id and besitzer = auth.uid())
  );

drop policy if exists spiel_geraet_delete on spiel_geraet;
create policy spiel_geraet_delete on spiel_geraet for delete
  using (geraet = auth.uid());

-- =============================================================================
-- spiel_spieler — Roster + Besitz-Lock
--  * Mitglieder lesen alle Teilnehmer.
--  * Ersteller legt die Aufstellung an / löscht sie.
--  * Jedes Mitglied darf einen Spieler ÜBERNEHMEN (besitzer_geraet = self) oder
--    FREIGEBEN (NULL) — Höflichkeits-/stale-Regeln setzt die App durch.
-- =============================================================================
drop policy if exists spiel_spieler_select on spiel_spieler;
create policy spiel_spieler_select on spiel_spieler for select
  using (pins_ist_mitglied(spiel_id));

drop policy if exists spiel_spieler_insert on spiel_spieler;
create policy spiel_spieler_insert on spiel_spieler for insert
  with check (
    exists (select 1 from spiel where id = spiel_id and besitzer = auth.uid())
    and besitzer_geraet is null
  );

-- USING (alte Zeile): der Ersteller darf immer; ein Mitglied darf nur übernehmen,
-- wenn der Spieler frei ist, ihm bereits gehört oder der Vorbesitzer inaktiv ist
-- (heartbeat älter als 30s / nie gesetzt). So kann kein Gerät einen aktiv
-- bespielten Spieler an sich reißen — deine Regel "ein Spieler, ein Gerät".
-- WITH CHECK (neue Zeile): als Besitzer nur sich selbst eintragen oder freigeben.
drop policy if exists spiel_spieler_update on spiel_spieler;
create policy spiel_spieler_update on spiel_spieler for update
  using (
    exists (select 1 from spiel where id = spiel_id and besitzer = auth.uid())
    or (
      pins_ist_mitglied(spiel_id)
      and (
        besitzer_geraet is null
        or besitzer_geraet = auth.uid()
        or heartbeat_am is null
        or heartbeat_am < now() - interval '30 seconds'
      )
    )
  )
  with check (
    pins_ist_mitglied(spiel_id)
    and (besitzer_geraet = auth.uid() or besitzer_geraet is null)
  );

drop policy if exists spiel_spieler_delete on spiel_spieler;
create policy spiel_spieler_delete on spiel_spieler for delete
  using (exists (select 1 from spiel where id = spiel_id and besitzer = auth.uid()));

-- =============================================================================
-- satz_block — DER Nebenläufigkeits-Kern
--  * Mitglieder lesen alle Blöcke.
--  * Schreiben (insert/update/delete) NUR, wenn das Gerät den Spieler besitzt.
-- =============================================================================
drop policy if exists satz_block_select on satz_block;
create policy satz_block_select on satz_block for select
  using (pins_ist_mitglied(spiel_id));

drop policy if exists satz_block_insert on satz_block;
create policy satz_block_insert on satz_block for insert
  with check (
    geraet = auth.uid()
    and exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and s.besitzer_geraet = auth.uid()
    )
  );

drop policy if exists satz_block_update on satz_block;
create policy satz_block_update on satz_block for update
  using (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and s.besitzer_geraet = auth.uid()
    )
  )
  with check (
    geraet = auth.uid()
    and exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and s.besitzer_geraet = auth.uid()
    )
  );

drop policy if exists satz_block_delete on satz_block;
create policy satz_block_delete on satz_block for delete
  using (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and s.besitzer_geraet = auth.uid()
    )
  );

-- =============================================================================
-- spiel_ergebnis — Snapshot bei Spielende
--  * Lesbar für Mitglieder UND für die eigene Person (Historie über Spiele hinweg).
--  * Schreibt das Gerät, das den Spieler besitzt.
-- =============================================================================
drop policy if exists spiel_ergebnis_select on spiel_ergebnis;
create policy spiel_ergebnis_select on spiel_ergebnis for select
  using (pins_ist_mitglied(spiel_id) or profil_id = auth.uid());

drop policy if exists spiel_ergebnis_insert on spiel_ergebnis;
create policy spiel_ergebnis_insert on spiel_ergebnis for insert
  with check (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and s.besitzer_geraet = auth.uid()
    )
  );

drop policy if exists spiel_ergebnis_update on spiel_ergebnis;
create policy spiel_ergebnis_update on spiel_ergebnis for update
  using (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and s.besitzer_geraet = auth.uid()
    )
  )
  with check (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and s.besitzer_geraet = auth.uid()
    )
  );

-- =============================================================================
-- anlage — Stub (Zukunft): nur der Besitzer
-- =============================================================================
drop policy if exists anlage_all on anlage;
create policy anlage_all on anlage for all
  using (besitzer = auth.uid()) with check (besitzer = auth.uid());
