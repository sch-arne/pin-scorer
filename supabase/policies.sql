-- =============================================================================
-- Pins-Scorer — Row-Level-Security (RLS)
-- =============================================================================
-- NACH schema.sql im Supabase SQL-Editor ausführen. Idempotent (drop policy if
-- exists vor jedem create). Setzt voraus, dass "Anonymous Sign-In" im Supabase-
-- Projekt aktiviert ist (Authentication → Providers → Anonymous).
--
-- Geräte-Identität ist ENTKOPPELT vom Account (siehe schema.sql, Tabelle `geraet`):
--   * auth.uid()  = Person / Account  (spiel.besitzer, profil, profil_id)
--   * geraet.id   = einzelnes Gerät   (spiel_geraet.geraet, besitzer_geraet, satz_block.geraet)
-- Ein Gerät gehört per geraet.konto = auth.uid() zu genau seinem Account. Die RLS
-- vertraut NUR dieser Bindung — eine allein vom Client gelieferte Geräte-ID zählt nicht.
--
-- Durchgesetzte Garantien:
--  * Nur Geräte, deren Account einem Spiel BEIGETRETEN ist, dürfen es lesen/beschreiben.
--  * Würfe (satz_block) eines Spielers darf NUR ein Gerät des besitzenden Accounts
--    schreiben (besitzer_geraet gehört zu auth.uid()). Zwischen den EIGENEN Geräten
--    koordiniert die App (Heartbeat/Übernehmen); fremde Accounts sind DB-hart gesperrt.
--  * Setup/Config des Spiels verwaltet nur der Ersteller (spiel.besitzer).
--  * Die eigene Statistik-Historie ist über profil_id = auth.uid() lesbar.
-- =============================================================================

-- Helfer: Gehört die Geräte-ID zum aktuellen Account (auth.uid())?
-- security definer, damit die Policy `geraet` lesen darf, ohne selbst RLS auszulösen.
create or replace function pins_ist_mein_geraet(p_geraet uuid)
returns boolean
language sql security definer stable
set search_path = public as $$
  select exists (
    select 1 from geraet where id = p_geraet and konto = auth.uid()
  );
$$;

-- Helfer: Ist der aktuelle Account (über EINES seiner Geräte) dem Spiel beigetreten?
create or replace function pins_ist_mitglied(p_spiel uuid)
returns boolean
language sql security definer stable
set search_path = public as $$
  select exists (
    select 1
    from spiel_geraet sg
    join geraet g on g.id = sg.geraet
    where sg.spiel_id = p_spiel and g.konto = auth.uid()
  );
$$;

-- Einem Spiel per Beitritts-Code beitreten. security definer, weil das beitretende
-- Gerät das Spiel noch nicht lesen darf (Henne/Ei). p_geraet muss zum aufrufenden
-- Account gehören; die Mitgliedschaft wird auf DIESES Gerät eingetragen.
drop function if exists spiel_beitreten(text);
create or replace function spiel_beitreten(p_code text, p_geraet uuid)
returns uuid
language plpgsql security definer
set search_path = public as $$
declare
  v_id uuid;
begin
  if not exists (select 1 from geraet where id = p_geraet and konto = auth.uid()) then
    raise exception 'Unbekanntes Gerät (nicht zu diesem Account registriert)';
  end if;
  select id into v_id from spiel where beitritts_code = upper(p_code);
  if v_id is null then
    raise exception 'Ungültiger Beitritts-Code';
  end if;
  insert into spiel_geraet (spiel_id, geraet)
    values (v_id, p_geraet)
    on conflict (spiel_id, geraet) do nothing;
  return v_id;
end;
$$;

grant execute on function spiel_beitreten(text, uuid) to anon, authenticated;

-- --- RLS aktivieren ----------------------------------------------------------
alter table geraet          enable row level security;
alter table profil          enable row level security;
alter table anlage          enable row level security;
alter table spiel           enable row level security;
alter table spiel_geraet    enable row level security;
alter table spiel_spieler   enable row level security;
alter table satz_block      enable row level security;
alter table spiel_ergebnis  enable row level security;

-- =============================================================================
-- geraet — jedes Gerät sieht/verwaltet nur die eigenen Bindungen (konto = ich)
-- =============================================================================
drop policy if exists geraet_select on geraet;
create policy geraet_select on geraet for select
  using (konto = auth.uid());

drop policy if exists geraet_insert on geraet;
create policy geraet_insert on geraet for insert
  with check (konto = auth.uid());

drop policy if exists geraet_update on geraet;
create policy geraet_update on geraet for update
  using (konto = auth.uid()) with check (konto = auth.uid());

drop policy if exists geraet_delete on geraet;
create policy geraet_delete on geraet for delete
  using (konto = auth.uid());

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
-- spiel_geraet — Mitgliedschaft (pro Gerät)
--  * Ersteller trägt eines seiner Geräte selbst ein (Beitritt anderer via spiel_beitreten).
--  * Jeder sieht die Mitglieder von Spielen, in denen er selbst (irgendein Gerät) ist.
--  * Jeder kann die Mitgliedschaft eines EIGENEN Geräts wieder verlassen.
-- =============================================================================
drop policy if exists spiel_geraet_select on spiel_geraet;
create policy spiel_geraet_select on spiel_geraet for select
  using (pins_ist_mein_geraet(geraet) or pins_ist_mitglied(spiel_id));

drop policy if exists spiel_geraet_insert on spiel_geraet;
create policy spiel_geraet_insert on spiel_geraet for insert
  with check (
    pins_ist_mein_geraet(geraet)
    and exists (select 1 from spiel where id = spiel_id and besitzer = auth.uid())
  );

drop policy if exists spiel_geraet_delete on spiel_geraet;
create policy spiel_geraet_delete on spiel_geraet for delete
  using (pins_ist_mein_geraet(geraet));

-- =============================================================================
-- spiel_spieler — Roster + Besitz-Lock
--  * Mitglieder lesen alle Teilnehmer.
--  * Ersteller legt die Aufstellung an / löscht sie.
--  * Jedes Mitglied darf einen Spieler ÜBERNEHMEN (besitzer_geraet = eigenes Gerät)
--    oder FREIGEBEN (NULL) — Höflichkeits-/stale-Regeln setzt die App durch.
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
-- wenn der Spieler frei ist, bereits einem EIGENEN Gerät gehört oder der Vorbesitzer
-- inaktiv ist (heartbeat älter als 30s / nie gesetzt). So kann kein FREMDER Account
-- einen aktiv bespielten Spieler an sich reißen — Regel "ein Spieler, ein Gerät".
-- WITH CHECK (neue Zeile): als Besitzer nur ein EIGENES Gerät eintragen oder freigeben.
drop policy if exists spiel_spieler_update on spiel_spieler;
create policy spiel_spieler_update on spiel_spieler for update
  using (
    exists (select 1 from spiel where id = spiel_id and besitzer = auth.uid())
    or (
      pins_ist_mitglied(spiel_id)
      and (
        besitzer_geraet is null
        or pins_ist_mein_geraet(besitzer_geraet)
        or heartbeat_am is null
        or heartbeat_am < now() - interval '30 seconds'
      )
    )
  )
  with check (
    pins_ist_mitglied(spiel_id)
    and (pins_ist_mein_geraet(besitzer_geraet) or besitzer_geraet is null)
  );

drop policy if exists spiel_spieler_delete on spiel_spieler;
create policy spiel_spieler_delete on spiel_spieler for delete
  using (exists (select 1 from spiel where id = spiel_id and besitzer = auth.uid()));

-- =============================================================================
-- satz_block — DER Nebenläufigkeits-Kern
--  * Mitglieder lesen alle Blöcke.
--  * Schreiben (insert/update/delete) NUR, wenn ein EIGENES Gerät den Spieler besitzt
--    und der Schreib-Tag (geraet) ebenfalls ein eigenes Gerät ist.
-- =============================================================================
drop policy if exists satz_block_select on satz_block;
create policy satz_block_select on satz_block for select
  using (pins_ist_mitglied(spiel_id));

drop policy if exists satz_block_insert on satz_block;
create policy satz_block_insert on satz_block for insert
  with check (
    pins_ist_mein_geraet(geraet)
    and exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and pins_ist_mein_geraet(s.besitzer_geraet)
    )
  );

drop policy if exists satz_block_update on satz_block;
create policy satz_block_update on satz_block for update
  using (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and pins_ist_mein_geraet(s.besitzer_geraet)
    )
  )
  with check (
    pins_ist_mein_geraet(geraet)
    and exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and pins_ist_mein_geraet(s.besitzer_geraet)
    )
  );

drop policy if exists satz_block_delete on satz_block;
create policy satz_block_delete on satz_block for delete
  using (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and pins_ist_mein_geraet(s.besitzer_geraet)
    )
  );

-- =============================================================================
-- spiel_ergebnis — Snapshot bei Spielende
--  * Lesbar für Mitglieder UND für die eigene Person (Historie über Spiele hinweg).
--  * Schreibt ein Gerät, das den Spieler besitzt.
-- =============================================================================
drop policy if exists spiel_ergebnis_select on spiel_ergebnis;
create policy spiel_ergebnis_select on spiel_ergebnis for select
  using (pins_ist_mitglied(spiel_id) or profil_id = auth.uid());

drop policy if exists spiel_ergebnis_insert on spiel_ergebnis;
create policy spiel_ergebnis_insert on spiel_ergebnis for insert
  with check (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and pins_ist_mein_geraet(s.besitzer_geraet)
    )
  );

drop policy if exists spiel_ergebnis_update on spiel_ergebnis;
create policy spiel_ergebnis_update on spiel_ergebnis for update
  using (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and pins_ist_mein_geraet(s.besitzer_geraet)
    )
  )
  with check (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and pins_ist_mein_geraet(s.besitzer_geraet)
    )
  );

-- =============================================================================
-- anlage — Stub (Zukunft): nur der Besitzer
-- =============================================================================
drop policy if exists anlage_all on anlage;
create policy anlage_all on anlage for all
  using (besitzer = auth.uid()) with check (besitzer = auth.uid());

-- =============================================================================
-- MIGRATION (einmalig, optional) — bestehende Daten aus der Zeit "Gerät = auth.uid()"
-- -----------------------------------------------------------------------------
-- Früher standen in spiel_geraet.geraet / besitzer_geraet / satz_block.geraet direkt
-- auth.uid()-Werte. Damit diese alten Geräte-IDs weiter als gültige Geräte gelten,
-- werden sie als "sich selbst gehörend" (id = konto) ins Register übernommen. Nur für
-- Nutzer, deren Auth-Konto noch existiert. Danach funktionieren bereits geteilte Spiele
-- für ihre ursprünglichen Ersteller weiter. NEUE Geräte bekommen frische Geräte-IDs;
-- ein bereits geteiltes Spiel muss auf einem weiteren Gerät ggf. einmalig neu beigetreten
-- werden. Rein lokale (unverknüpfte) Spiele sind nicht betroffen.
insert into geraet (id, konto)
  select distinct sg.geraet, sg.geraet
  from spiel_geraet sg
  join auth.users u on u.id = sg.geraet
  on conflict (id, konto) do nothing;
