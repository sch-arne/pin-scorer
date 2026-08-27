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

-- Helfer: Ist der aktuelle Account (über EINES seiner Geräte) einem WETTKAMPF beigetreten?
-- security definer, damit die Policy wettkampf_geraet lesen darf, ohne selbst RLS auszulösen.
create or replace function pins_ist_wettkampf_mitglied(p_wettkampf uuid)
returns boolean
language sql security definer stable
set search_path = public as $$
  select exists (
    select 1
    from wettkampf_geraet wg
    join geraet g on g.id = wg.geraet
    where wg.wettkampf_id = p_wettkampf and g.konto = auth.uid()
  );
$$;

-- Helfer: Ist der aktuelle Account (über EINES seiner Geräte) dem Spiel beigetreten?
-- Zwei Wege zur Mitgliedschaft:
--   1) direkt am Spiel (spiel_geraet) — der klassische Einzelspiel-Beitritt, ODER
--   2) am WETTKAMPF, zu dem das Spiel als Durchgang gehört (spiel.wettkampf_id).
-- Weg 2 öffnet automatisch auch später ergänzte Durchgänge, ohne pro Durchgang neu
-- beizutreten. Wirkt auf alle Policies, die pins_ist_mitglied nutzen (select der
-- spiel/spiel_spieler/satz_block/spiel_ergebnis sowie das Übernehmen von Spielern).
create or replace function pins_ist_mitglied(p_spiel uuid)
returns boolean
language sql security definer stable
set search_path = public as $$
  select exists (
    select 1
    from spiel_geraet sg
    join geraet g on g.id = sg.geraet
    where sg.spiel_id = p_spiel and g.konto = auth.uid()
  ) or exists (
    select 1
    from spiel s
    join wettkampf_geraet wg on wg.wettkampf_id = s.wettkampf_id
    join geraet g on g.id = wg.geraet
    where s.id = p_spiel and g.konto = auth.uid()
  );
$$;

-- Helfer: Ist der aktuelle Account (auth.uid()) der ERSTELLER des Spiels?
-- Getrennt von der Mitgliedschaft (pins_ist_mitglied): der Ersteller darf seine EIGENEN
-- Spiele auf JEDEM seiner Geräte vollständig lesen (Aufstellung + Würfe + Ergebnisse),
-- auch ohne dass dieses Gerät dem Spiel je beigetreten ist. So erscheinen beendete
-- Spiele geräteübergreifend in den Statistiken und lassen sich dort wieder aufrufen.
-- security definer, damit die Policy `spiel` lesen darf, ohne selbst RLS auszulösen.
create or replace function pins_ist_spiel_besitzer(p_spiel uuid)
returns boolean
language sql security definer stable
set search_path = public as $$
  select exists (
    select 1 from spiel where id = p_spiel and besitzer = auth.uid()
  );
$$;

-- Helfer: die LizenzID/Passnummer des aktuellen Accounts (profil.passnummer von auth.uid()).
-- Ein Spieler darf SEINE Ergebniszeilen (spiel_ergebnis.passnummer) auch in fremd erfassten
-- Spielen lesen, ohne dem Spiel beigetreten zu sein — Grundlage für die Statistik „meine
-- Ergebnisse aus fremden Spielen". Gibt NULL zurück, wenn kein Profil / keine Passnummer.
-- security definer, damit die Policy profil lesen darf, ohne selbst RLS auszulösen.
create or replace function pins_meine_passnummer()
returns text
language sql security definer stable
set search_path = public as $$
  select passnummer from profil where id = auth.uid();
$$;

-- Helfer: Ist meine LizenzID (profil.passnummer) in DIESEM Spiel als Spieler geführt?
-- Basis ist der Ergebnis-Snapshot (spiel_ergebnis.passnummer, bei Spielende geschrieben) —
-- also nur für BEENDETE Spiele wirksam. Erlaubt es einem Spieler, ein fremd erfasstes Spiel,
-- in dem er selbst gespielt hat, vollständig zu ÖFFNEN (Auswertung/Wurfprotokoll aller
-- Mitspieler), ohne ihm beigetreten zu sein. security definer, um RLS-Rekursion zu vermeiden.
create or replace function pins_lizenz_im_spiel(p_spiel uuid)
returns boolean
language sql security definer stable
set search_path = public as $$
  select exists (
    select 1 from spiel_ergebnis e
    where e.spiel_id = p_spiel
      and e.passnummer is not null
      and e.passnummer = pins_meine_passnummer()
  );
$$;

-- Helfer: Ist der aktuelle Account für die erweiterten Anlagen-Funktionen freigeschaltet?
-- (Whitelist `freischaltung`, vom Betreiber per SQL gepflegt.) security definer, damit die
-- Policy/Frontend die Tabelle prüfen kann, ohne selbst RLS auszulösen. Wird in dieser Etappe
-- nur zur Status-Anzeige genutzt; die Feature-Gates folgen mit den erweiterten Funktionen.
create or replace function pins_ist_freigeschaltet()
returns boolean
language sql security definer stable
set search_path = public as $$
  select exists (select 1 from freischaltung where konto = auth.uid());
$$;

grant execute on function pins_ist_freigeschaltet() to anon, authenticated;

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

-- Einem WETTKAMPF per Beitritts-Code beitreten (RPC). Wie spiel_beitreten, aber trägt
-- das Gerät in wettkampf_geraet ein. Über pins_ist_mitglied öffnet das automatisch alle
-- Durchgang-Spiele des Wettkampfs (auch später ergänzte) — kein Beitritt je Durchgang nötig.
drop function if exists wettkampf_beitreten(text, uuid);
create or replace function wettkampf_beitreten(p_code text, p_geraet uuid)
returns uuid
language plpgsql security definer
set search_path = public as $$
declare
  v_id uuid;
begin
  if not exists (select 1 from geraet where id = p_geraet and konto = auth.uid()) then
    raise exception 'Unbekanntes Gerät (nicht zu diesem Account registriert)';
  end if;
  select id into v_id from wettkampf where beitritts_code = upper(p_code);
  if v_id is null then
    raise exception 'Ungültiger Beitritts-Code';
  end if;
  insert into wettkampf_geraet (wettkampf_id, geraet)
    values (v_id, p_geraet)
    on conflict (wettkampf_id, geraet) do nothing;
  return v_id;
end;
$$;

grant execute on function wettkampf_beitreten(text, uuid) to anon, authenticated;

-- Read-only Schnappschuss eines Wettkampfs per Beitritts-Code — für das OBS-Livestream-
-- Overlay. security definer + anon-grant, damit eine OBS-Browser-Quelle (ein eigener,
-- NICHT angemeldeter Browser, evtl. auf einem anderen PC) die Ergebnisse live zeigen kann,
-- OHNE dem Wettkampf als Gerät beizutreten. Gibt AUSSCHLIESSLICH lesbare Ergebnis-Daten
-- zurück (kein Besitz, keine Geräte, keine fremden Profildaten) und nur, wer den Code kennt.
-- Liefert null bei unbekanntem Code. Wirft nichts, schreibt nichts.
drop function if exists wettkampf_overlay(text);
create or replace function wettkampf_overlay(p_code text)
returns jsonb
language sql security definer stable
set search_path = public as $$
  with wk as (
    select id, name, status, config_json
    from wettkampf where beitritts_code = upper(p_code)
  )
  select case when not exists (select 1 from wk) then null else
    jsonb_build_object(
      'wettkampf', (select jsonb_build_object(
        'name', w.name, 'status', w.status, 'config', w.config_json) from wk w),
      'spiele', coalesce((
        select jsonb_agg(jsonb_build_object(
          'durchgang_nr', s.durchgang_nr,
          'status', s.status,
          'config', s.config_json,
          'bloecke', coalesce((
            select jsonb_agg(jsonb_build_object(
              'position', sp.position, 'satz', b.satz, 'block', b.block_json))
            from satz_block b
            join spiel_spieler sp on sp.id = b.spieler_id
            where b.spiel_id = s.id
          ), '[]'::jsonb)
        ) order by s.durchgang_nr)
        from spiel s where s.wettkampf_id = (select id from wk)
      ), '[]'::jsonb)
    )
  end;
$$;

grant execute on function wettkampf_overlay(text) to anon, authenticated;

-- Verbindung eines SPIELS kappen, OHNE das Spiel zu löschen. Entwertet den Beitritts-Code
-- (kein Beitreten mehr) und entfernt ALLE Geräte-Mitgliedschaften (auch fremder Accounts) —
-- dafür security definer, weil die normale RLS (spiel_geraet_delete) nur eigene Geräte-Zeilen
-- löschen ließe. Die Wurf-/Aufstellungs-/Ergebnisdaten (spiel_spieler, satz_block,
-- spiel_ergebnis) BLEIBEN erhalten. Nur der Ersteller (spiel.besitzer) darf.
drop function if exists spiel_verbindung_kappen(uuid);
create or replace function spiel_verbindung_kappen(p_spiel uuid)
returns void
language plpgsql security definer
set search_path = public as $$
begin
  if not exists (select 1 from spiel where id = p_spiel and besitzer = auth.uid()) then
    raise exception 'Nicht berechtigt';
  end if;
  update spiel set beitritts_code = null where id = p_spiel;
  delete from spiel_geraet where spiel_id = p_spiel;
end;
$$;

grant execute on function spiel_verbindung_kappen(uuid) to anon, authenticated;

-- Verbindung eines WETTKAMPFS kappen, OHNE ihn zu löschen. Entwertet den Wettkampf-Code
-- (kein Beitreten, kein Overlay mehr) und entfernt alle wettkampf_geraet-Mitgliedschaften.
-- Zusätzlich für JEDEN Durchgang: dessen Code entwerten + spiel_geraet leeren — sonst blieben
-- Durchgänge über die Wettkampf-Mitgliedschaft (pins_ist_mitglied, Weg 2) erreichbar. Alle
-- Ergebnisdaten bleiben erhalten. Nur der Ersteller (wettkampf.besitzer) darf.
drop function if exists wettkampf_verbindung_kappen(uuid);
create or replace function wettkampf_verbindung_kappen(p_wettkampf uuid)
returns void
language plpgsql security definer
set search_path = public as $$
begin
  if not exists (select 1 from wettkampf where id = p_wettkampf and besitzer = auth.uid()) then
    raise exception 'Nicht berechtigt';
  end if;
  update wettkampf set beitritts_code = null where id = p_wettkampf;
  delete from wettkampf_geraet where wettkampf_id = p_wettkampf;
  update spiel set beitritts_code = null where wettkampf_id = p_wettkampf;
  delete from spiel_geraet
    where spiel_id in (select id from spiel where wettkampf_id = p_wettkampf);
end;
$$;

grant execute on function wettkampf_verbindung_kappen(uuid) to anon, authenticated;

-- --- RLS aktivieren ----------------------------------------------------------
alter table geraet          enable row level security;
alter table wettkampf       enable row level security;
alter table wettkampf_geraet enable row level security;
alter table profil          enable row level security;
alter table anlage          enable row level security;
alter table bahn            enable row level security;
alter table freischaltung   enable row level security;
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

-- Öffentliche Sicht: NUR (id, anzeigename). Der Anzeigename darf für Mitspieler / im
-- Livestream sichtbar sein; alle übrigen profil-Spalten (vorname/nachname/verein/
-- passnummer) bleiben durch die self-only-RLS der Basistabelle privat.
--
-- Die View läuft mit den Rechten ihres Owners (security_invoker = off) und umgeht damit
-- bewusst die RLS der Basistabelle — legt aber ausschließlich anzeigename offen.
-- WICHTIG: security_invoker muss `off` bleiben (sonst greift wieder self-only und Fremde
-- sehen nichts), und die Basistabelle `profil` wird NIE an anon/authenticated ge-grantet.
create or replace view profil_public
  with (security_invoker = off) as
  select id, anzeigename from profil;

grant select on profil_public to anon, authenticated;

-- =============================================================================
-- spiel — Mitglieder lesen; nur der Ersteller ändert Setup/Status
-- =============================================================================
drop policy if exists spiel_select on spiel;
create policy spiel_select on spiel for select
  using (pins_ist_mitglied(id) or besitzer = auth.uid() or pins_lizenz_im_spiel(id));

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
-- wettkampf — Mitglieder lesen; nur der Ersteller ändert Stammdaten/Status
-- (Config der Durchgänge bleibt am jeweiligen spiel; hier nur die Klammer.)
-- =============================================================================
drop policy if exists wettkampf_select on wettkampf;
create policy wettkampf_select on wettkampf for select
  using (pins_ist_wettkampf_mitglied(id) or besitzer = auth.uid());

drop policy if exists wettkampf_insert on wettkampf;
create policy wettkampf_insert on wettkampf for insert
  with check (besitzer = auth.uid());

drop policy if exists wettkampf_update on wettkampf;
create policy wettkampf_update on wettkampf for update
  using (besitzer = auth.uid()) with check (besitzer = auth.uid());

drop policy if exists wettkampf_delete on wettkampf;
create policy wettkampf_delete on wettkampf for delete
  using (besitzer = auth.uid());

-- =============================================================================
-- wettkampf_geraet — Wettkampf-Mitgliedschaft (pro Gerät)
--  * Ersteller trägt eines seiner Geräte selbst ein; Beitritt anderer via wettkampf_beitreten.
--  * Jeder sieht die Mitglieder von Wettkämpfen, in denen er selbst (irgendein Gerät) ist.
--  * Jeder kann die Mitgliedschaft eines EIGENEN Geräts wieder verlassen.
-- =============================================================================
drop policy if exists wettkampf_geraet_select on wettkampf_geraet;
create policy wettkampf_geraet_select on wettkampf_geraet for select
  using (pins_ist_mein_geraet(geraet) or pins_ist_wettkampf_mitglied(wettkampf_id));

drop policy if exists wettkampf_geraet_insert on wettkampf_geraet;
create policy wettkampf_geraet_insert on wettkampf_geraet for insert
  with check (
    pins_ist_mein_geraet(geraet)
    and exists (select 1 from wettkampf where id = wettkampf_id and besitzer = auth.uid())
  );

drop policy if exists wettkampf_geraet_delete on wettkampf_geraet;
create policy wettkampf_geraet_delete on wettkampf_geraet for delete
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
  using (pins_ist_mitglied(spiel_id) or pins_ist_spiel_besitzer(spiel_id) or pins_lizenz_im_spiel(spiel_id));

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
  using (pins_ist_mitglied(spiel_id) or pins_ist_spiel_besitzer(spiel_id) or pins_lizenz_im_spiel(spiel_id));

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
  using (
    pins_ist_mitglied(spiel_id)
    or pins_ist_spiel_besitzer(spiel_id)
    or profil_id = auth.uid()
    or (passnummer is not null and passnummer = pins_meine_passnummer())
    or pins_lizenz_im_spiel(spiel_id)
  );

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
-- anlage — jeder darf LESEN (auf Anlagen spielen); Anlegen jeder eingeloggte Account;
-- Ändern/Löschen nur der Besitzer.
-- =============================================================================
-- Alte owner-only-Policy entfernen (sie blockierte das Fremd-Lesen).
drop policy if exists anlage_all on anlage;

drop policy if exists anlage_select on anlage;
create policy anlage_select on anlage for select
  using (true);

drop policy if exists anlage_insert on anlage;
create policy anlage_insert on anlage for insert
  with check (besitzer = auth.uid());

drop policy if exists anlage_update on anlage;
create policy anlage_update on anlage for update
  using (besitzer = auth.uid()) with check (besitzer = auth.uid());

drop policy if exists anlage_delete on anlage;
create policy anlage_delete on anlage for delete
  using (besitzer = auth.uid());

-- =============================================================================
-- bahn — für alle lesbar; Schreiben nur der Besitzer der zugehörigen Anlage.
-- =============================================================================
drop policy if exists bahn_select on bahn;
create policy bahn_select on bahn for select
  using (true);

drop policy if exists bahn_insert on bahn;
create policy bahn_insert on bahn for insert
  with check (exists (select 1 from anlage a where a.id = anlage_id and a.besitzer = auth.uid()));

drop policy if exists bahn_update on bahn;
create policy bahn_update on bahn for update
  using (exists (select 1 from anlage a where a.id = anlage_id and a.besitzer = auth.uid()))
  with check (exists (select 1 from anlage a where a.id = anlage_id and a.besitzer = auth.uid()));

drop policy if exists bahn_delete on bahn;
create policy bahn_delete on bahn for delete
  using (exists (select 1 from anlage a where a.id = anlage_id and a.besitzer = auth.uid()));

-- =============================================================================
-- freischaltung — nur lesen, nur die eigene Zeile. Schreiben ausschließlich per SQL /
-- Service-Role (der Betreiber pflegt die Whitelist im SQL-Editor). Keine Client-Writes.
-- =============================================================================
drop policy if exists freischaltung_select on freischaltung;
create policy freischaltung_select on freischaltung for select
  using (konto = auth.uid());

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

-- =============================================================================
-- Konto-Löschung (DSGVO) — self-service, atomar
-- -----------------------------------------------------------------------------
-- Der Client (anon/authenticated) darf auth.users NICHT selbst löschen — das braucht
-- erhöhte Rechte. Diese Funktion läuft `security definer` (als Owner) und löscht
-- ausschließlich die Daten des AUFRUFERS (auth.uid()).
--
-- WICHTIG (FK-Verhalten, siehe schema.sql): spiel.besitzer, spiel_spieler.profil_id und
-- spiel_ergebnis.profil_id sind ON DELETE SET NULL. Ein reines DELETE der auth.users-Zeile
-- würde daher die vom Nutzer erstellten Spiele + Sätze als personenbezogene Restdaten
-- stehen lassen. Deshalb werden eigene Spiele (und eigene Ergebnis-Snapshots in fremden
-- Spielen) hier EXPLIZIT gelöscht; profil + geraet kaskadieren über auth.users.
create or replace function konto_loeschen()
returns void
language plpgsql
security definer
set search_path = public, auth
as $$
declare
  v_uid uuid := auth.uid();
begin
  if v_uid is null then
    raise exception 'nicht angemeldet';
  end if;

  -- 1a) Eigene Wettkämpfe -> kaskadiert wettkampf_geraet UND die Durchgang-Spiele
  --     (spiel.wettkampf_id ON DELETE CASCADE) inkl. deren spiel_spieler/satz_block/…
  delete from wettkampf where besitzer = v_uid;

  -- 1b) Restliche eigene (Einzel-)Spiele -> kaskadiert spiel_geraet, spiel_spieler,
  --     satz_block, spiel_ergebnis dieser Spiele (alle ON DELETE CASCADE auf spiel_id).
  delete from spiel where besitzer = v_uid;

  -- 2) Eigene Ergebnis-Snapshots in FREMDEN Spielen vollständig entfernen
  --    (statt nur profil_id auf NULL zu setzen).
  delete from spiel_ergebnis where profil_id = v_uid;

  -- 3) Auth-User -> kaskadiert profil + geraet (ON DELETE CASCADE) sowie die
  --    auth-internen identities/sessions.
  delete from auth.users where id = v_uid;
end;
$$;

revoke all on function konto_loeschen() from public;
grant execute on function konto_loeschen() to authenticated;
