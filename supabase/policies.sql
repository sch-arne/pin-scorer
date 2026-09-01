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
--
-- DATENSCHUTZ: `config_json` wird um den Block `sportwinner` bereinigt (jsonb `-`). Er trägt
-- die Passnummern/LizenzIDs und die Sportwinner-internen Spieler-IDs der Aufstellung und hätte
-- hier sonst jeden, der den Code kennt, ohne Login an fremde Verbands-IDs kommen lassen. Der
-- Client schreibt ihn seit `sportwinnerOhnePersonendaten` gar nicht mehr mit hoch — der Filter
-- deckt zusätzlich die bereits gespeicherten Alt-Wettkämpfe ab.
drop function if exists wettkampf_overlay(text);
create or replace function wettkampf_overlay(p_code text)
returns jsonb
language sql security definer stable
set search_path = public as $$
  with wk as (
    -- NUR der read-only ZUSCHAUER-Code. Der Eingabe-Code wurde früher ebenfalls akzeptiert;
    -- das vermischte Lese- und Schreibrecht in einer geteilten OBS-URL. Die App erzeugt die
    -- Overlay-URL ohnehin aus dem Zuschauer-Code (wettkampf-hub.js overlayUrl).
    select id, name, status, config_json - 'sportwinner' as config_json
    from wettkampf where zuschauer_code = upper(p_code)
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

-- Read-only Schnappschuss eines SPIELS per ZUSCHAUER-Code — fürs Live-Zuschauen in der App
-- (Menü „Spiel beitreten" mit einem Zuschauer-Code). Analog zu wettkampf_overlay: security
-- definer + anon-grant, damit auch ein NICHT angemeldetes Gerät zusehen kann, OHNE dem Spiel
-- als Gerät beizutreten. Gibt AUSSCHLIESSLICH lesbare Daten zurück (Setup, Aufstellung, Würfe,
-- Status) — WEDER beitritts_code/zuschauer_code NOCH Besitzer/Geräte. So kann ein Zuschauer
-- weder schreiben noch den Eingabe-Code auslesen. Liefert null bei unbekanntem Code.
drop function if exists spiel_zuschauer(text);
create or replace function spiel_zuschauer(p_code text)
returns jsonb
language sql security definer stable
set search_path = public as $$
  with s as (
    select id, spielart, status, config_json, erstellt_am, aktualisiert_am, anonymisiert_am
    from spiel where zuschauer_code = upper(p_code)
  )
  select case when not exists (select 1 from s) then null else
    jsonb_build_object(
      'spiel', (select jsonb_build_object(
        'id', s.id, 'spielart', s.spielart, 'status', s.status,
        'config_json', s.config_json, 'erstellt_am', s.erstellt_am,
        'aktualisiert_am', s.aktualisiert_am,
        'anonymisiert_am', s.anonymisiert_am) from s),
      'spieler', coalesce((
        select jsonb_agg(jsonb_build_object(
          'id', sp.id, 'position', sp.position, 'name', sp.name, 'start_bahn', sp.start_bahn)
          order by sp.position)
        from spiel_spieler sp where sp.spiel_id = (select id from s)
      ), '[]'::jsonb),
      'bloecke', coalesce((
        select jsonb_agg(jsonb_build_object(
          'spieler_id', b.spieler_id, 'satz', b.satz, 'block_json', b.block_json))
        from satz_block b where b.spiel_id = (select id from s)
      ), '[]'::jsonb)
    )
  end;
$$;

grant execute on function spiel_zuschauer(text) to anon, authenticated;

-- Read-only Schnappschuss eines WETTKAMPFS per ZUSCHAUER-Code — für die volle Wettkampf-Ansicht
-- (Hub) im Zuschauer-Modus. Wie spiel_zuschauer, aber inkl. aller Durchgang-Spiele (jeweils mit
-- Aufstellung + Würfen). Der zuschauer_code JEDES Durchgangs ist enthalten, damit der geöffnete
-- Durchgang in der Erfassungs-Ansicht ebenfalls live pollen kann — es ist ein reiner Lese-Code,
-- der kein Eingaberecht gibt. KEIN beitritts_code, KEIN Besitzer/Gerät. Liefert null bei
-- unbekanntem Code.
drop function if exists wettkampf_zuschauer(text);
create or replace function wettkampf_zuschauer(p_code text)
returns jsonb
language sql security definer stable
set search_path = public as $$
  with wk as (
    -- config_json ohne den `sportwinner`-Block (Passnummern/LizenzIDs) — siehe wettkampf_overlay.
    select id, name, datum, status, anlage_id,
           config_json - 'sportwinner' as config_json, erstellt_am, aktualisiert_am
    from wettkampf where zuschauer_code = upper(p_code)
  )
  select case when not exists (select 1 from wk) then null else
    jsonb_build_object(
      'wettkampf', (select jsonb_build_object(
        'id', w.id, 'name', w.name, 'datum', w.datum, 'status', w.status,
        'anlage_id', w.anlage_id, 'config_json', w.config_json,
        'erstellt_am', w.erstellt_am, 'aktualisiert_am', w.aktualisiert_am) from wk w),
      'spiele', coalesce((
        select jsonb_agg(jsonb_build_object(
          'id', s.id, 'durchgang_nr', s.durchgang_nr, 'spielart', s.spielart,
          'status', s.status, 'config_json', s.config_json,
          'zuschauer_code', s.zuschauer_code,
          'anonymisiert_am', s.anonymisiert_am,
          'spieler', coalesce((
            select jsonb_agg(jsonb_build_object(
              'id', sp.id, 'position', sp.position, 'name', sp.name, 'start_bahn', sp.start_bahn)
              order by sp.position)
            from spiel_spieler sp where sp.spiel_id = s.id
          ), '[]'::jsonb),
          'bloecke', coalesce((
            select jsonb_agg(jsonb_build_object(
              'spieler_id', b.spieler_id, 'satz', b.satz, 'block_json', b.block_json))
            from satz_block b where b.spiel_id = s.id
          ), '[]'::jsonb)
        ) order by s.durchgang_nr)
        from spiel s where s.wettkampf_id = (select id from wk)
      ), '[]'::jsonb)
    )
  end;
$$;

grant execute on function wettkampf_zuschauer(text) to anon, authenticated;

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
  update spiel set beitritts_code = null, zuschauer_code = null where id = p_spiel;
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
  update wettkampf set beitritts_code = null, zuschauer_code = null where id = p_wettkampf;
  delete from wettkampf_geraet where wettkampf_id = p_wettkampf;
  update spiel set beitritts_code = null, zuschauer_code = null where wettkampf_id = p_wettkampf;
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

-- NICHT an `anon`: die View hat keinen Zeilenfilter, ein anon-Grant hätte also die
-- Anzeigenamen ALLER Accounts ohne Login auslesbar gemacht. Angemeldete Nutzer reichen
-- für den geplanten Zweck (Mitspieler-Anzeige); der Livestream-Name kommt inzwischen aus
-- der Anonymisierung (pins_spiel_anonymisieren schreibt anzeigename direkt in spiel_spieler).
revoke all on profil_public from anon;
grant select on profil_public to authenticated;

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
    and (profil_id is null or profil_id = auth.uid())
  );

-- USING (alte Zeile): der Ersteller darf immer; ein Mitglied darf nur übernehmen,
-- wenn der Spieler frei ist, bereits einem EIGENEN Gerät gehört oder der Vorbesitzer
-- inaktiv ist (heartbeat älter als 30s / nie gesetzt). So kann kein FREMDER Account
-- einen aktiv bespielten Spieler an sich reißen — Regel "ein Spieler, ein Gerät".
-- WITH CHECK (neue Zeile): als Besitzer nur ein EIGENES Gerät eintragen oder freigeben,
-- und profil_id ("das bin ICH als Spieler") nur auf den EIGENEN Account setzen — sonst
-- könnte ein Mitglied einem fremden Account Ergebnisse unterschieben.
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
    and (profil_id is null or profil_id = auth.uid())
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

-- WITH CHECK zusätzlich: profil_id ("das bin ICH als Spieler") und erfasst_von dürfen nur
-- auf den EIGENEN Account zeigen. Ohne diese Schranke könnte ein Mitglied einem fremden
-- Account beliebige Ergebnisse in dessen Statistik schreiben.
drop policy if exists spiel_ergebnis_insert on spiel_ergebnis;
create policy spiel_ergebnis_insert on spiel_ergebnis for insert
  with check (
    exists (
      select 1 from spiel_spieler s
      where s.id = spieler_id and pins_ist_mein_geraet(s.besitzer_geraet)
    )
    and (profil_id is null or profil_id = auth.uid())
    and (erfasst_von is null or erfasst_von = auth.uid())
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
    and (profil_id is null or profil_id = auth.uid())
    and (erfasst_von is null or erfasst_von = auth.uid())
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
  v_uid    uuid := auth.uid();
  v_pass   text;
  v_spiele uuid[];
begin
  if v_uid is null then
    raise exception 'nicht angemeldet';
  end if;

  -- Eigene LizenzID merken, SOLANGE das Profil noch existiert (es kaskadiert in Schritt 4 weg).
  select passnummer into v_pass from profil where id = v_uid;

  -- 1a) Eigene Wettkämpfe -> kaskadiert wettkampf_geraet UND die Durchgang-Spiele
  --     (spiel.wettkampf_id ON DELETE CASCADE) inkl. deren spiel_spieler/satz_block/…
  delete from wettkampf where besitzer = v_uid;

  -- 1b) Restliche eigene (Einzel-)Spiele -> kaskadiert spiel_geraet, spiel_spieler,
  --     satz_block, spiel_ergebnis dieser Spiele (alle ON DELETE CASCADE auf spiel_id).
  delete from spiel where besitzer = v_uid;

  -- 2) Eigene Ergebnis-Snapshots in FREMDEN Spielen vollständig entfernen
  --    (statt nur profil_id auf NULL zu setzen).
  delete from spiel_ergebnis where profil_id = v_uid;

  -- 3) Als SPIELER (nicht als Erfasser) hinterlassene Spuren in fremd erfassten Spielen:
  --    Ergebniszeilen, die über die eigene LizenzID zuzuordnen sind, sowie die LizenzID an
  --    der Aufstellung. Ohne diesen Schritt bliebe die eigene Verbands-ID in Spielen stehen,
  --    die ein anderer Account (z.B. der Vereins-PC) erfasst hat. Der Name in spiel_spieler
  --    wird zusätzlich neutralisiert, sofern das Spiel bereits anonymisiert wurde — bei noch
  --    laufenden Spielen bleibt er, damit die laufende Erfassung nicht zerreißt.
  if v_pass is not null then
    delete from spiel_ergebnis where passnummer = v_pass;

    -- Betroffene Spiele merken, SOLANGE die LizenzID sie noch auffindbar macht.
    select array_agg(distinct sp.spiel_id) into v_spiele
      from spiel_spieler sp where sp.passnummer = v_pass;

    -- 3a) Aufstellung: LizenzID + Konto-Zuordnung entfernen. Der Name wird nur in bereits
    --     ANONYMISIERTEN (beendeten) Spielen neutralisiert — in noch laufenden bleibt er,
    --     damit die aktive Erfassung nicht mitten im Spiel zerreißt.
    update spiel_spieler sp
       set passnummer = null,
           profil_id  = null,
           name = case
             when exists (select 1 from spiel s
                           where s.id = sp.spiel_id and s.anonymisiert_am is not null)
               then pins_platzhalter_name(
                      (select w.config_json -> 'mannschaften' from spiel s
                         left join wettkampf w on w.id = s.wettkampf_id where s.id = sp.spiel_id),
                      (select s.config_json -> 'spielerListe' from spiel s where s.id = sp.spiel_id),
                      sp.position)
             else sp.name
           end
     where sp.passnummer = v_pass;

    -- 3b) Die ZWEITE Namenskopie nachziehen: spiel.config_json.spielerListe[].name. Der
    --     Anzeigename stünde dort sonst weiter, obwohl das Profil gelöscht wird. Es genügt,
    --     die geänderte Position zu schreiben — das weckt trg_spiel_anonymisieren, der die
    --     ganze Liste wieder aus spiel_spieler (jetzt neutral) aufbaut.
    update spiel s
       set config_json = jsonb_set(s.config_json,
             array['spielerListe', sp.position::text, 'name'], to_jsonb(sp.name))
      from spiel_spieler sp
     where sp.spiel_id = s.id
       and s.id = any(v_spiele)
       and s.anonymisiert_am is not null
       and sp.name is distinct from (s.config_json #>> array['spielerListe', sp.position::text, 'name']);
  end if;

  -- 4) Auth-User -> kaskadiert profil + geraet (ON DELETE CASCADE) sowie die
  --    auth-internen identities/sessions.
  delete from auth.users where id = v_uid;
end;
$$;

revoke all on function konto_loeschen() from public;
grant execute on function konto_loeschen() to authenticated;

-- =============================================================================
-- Anonymisierung bei Spielende (DSGVO / Datenminimierung)
-- -----------------------------------------------------------------------------
-- Leitidee: Klarnamen sind nur so lange nötig, wie sie gebraucht werden — nämlich
-- WÄHREND des Spiels (Mitspieler-Geräte, Zuschauer, Livestream-Overlay). Sobald ein
-- Spiel auf `beendet` steht, ersetzt der Trigger die Namen serverseitig:
--
--   1) Hat ein Spieler eine LizenzID (spiel_spieler.passnummer), zu der ein Profil mit
--      derselben passnummer existiert, steht künftig dessen ÖFFENTLICHER Anzeigename
--      (profil.anzeigename) da — der Betroffene hat ihn selbst gewählt und freigegeben.
--   2) Sonst ein neutraler Platzhalter ("<Mannschaft> <Pos>" bzw. "Spieler N") — exakt
--      die Bezeichnung, die buildDurchgangGame/computeGameStats ohnehin verwenden.
--
-- Beide Namenskopien werden ersetzt: spiel_spieler.name UND
-- spiel.config_json.spielerListe[].name — sonst lieferten die Zuschauer-/Overlay-RPCs
-- weiter die Klarnamen aus dem config_json.
--
-- Geräte, die WÄHREND des Spiels verbunden waren, behalten die Klarnamen in ihrer lokalen
-- Kopie (Client-seitiger Merge in sync.js mergeSpielerNamen) — nur die DB und alle, die erst
-- danach beitreten/pullen, sehen die anonymisierte Fassung.
-- =============================================================================

-- Neutraler Platzhalter für eine Spieler-Position: "<Mannschaftsname> <teamPos>", sonst
-- "Spieler N". p_teams = wettkampf.config_json->'mannschaften' (kann null sein),
-- p_liste = spiel.config_json->'spielerListe', p_pos = 0-basierte Position.
create or replace function pins_platzhalter_name(p_teams jsonb, p_liste jsonb, p_pos int)
returns text
language plpgsql immutable
set search_path = public as $$
declare
  v_eintrag jsonb := p_liste -> p_pos;          -- spielerListe[p_pos] (null-sicher)
  v_teampos text  := v_eintrag ->> 'teamPos';
  v_team    text;
begin
  if v_teampos is not null then
    select t ->> 'name' into v_team
      from jsonb_array_elements(coalesce(p_teams, '[]'::jsonb)) t
     where t ->> 'id' = (v_eintrag ->> 'mannschaftId')
     limit 1;
  end if;
  if v_team is not null then
    return v_team || ' ' || v_teampos;          -- "Grün-Weiß Osnabrück 3"
  end if;
  return 'Spieler ' || (p_pos + 1);             -- Einzelspiel-Fallback (wie computeGameStats)
end;
$$;

create or replace function pins_spiel_anonymisieren()
returns trigger
language plpgsql security definer
set search_path = public as $$
declare
  r        record;
  v_name   text;
  v_liste  jsonb := new.config_json -> 'spielerListe';
  v_teams  jsonb;
  v_frisch boolean := (new.anonymisiert_am is null);
begin
  if jsonb_typeof(v_liste) is distinct from 'array' then
    -- Kein Aufstellungs-Array im config_json -> nur die Aufstellungstabelle behandeln.
    v_liste := null;
  end if;

  -- Mannschaftsnamen des Wettkampfs für den neutralen Platzhalter (null bei Einzelspielen).
  select w.config_json -> 'mannschaften' into v_teams
    from wettkampf w where w.id = new.wettkampf_id;

  -- passnummer bevorzugt aus der Aufstellung; ersatzweise aus dem soeben geschriebenen
  -- Ergebnis-Snapshot. Der Fallback deckt Spiele ab, die geteilt wurden, BEVOR es
  -- spiel_spieler.passnummer gab (dort trägt nur spiel_ergebnis die LizenzID).
  for r in
    select sp.id, sp.position, sp.name,
           coalesce(sp.passnummer,
                    (select e.passnummer from spiel_ergebnis e
                      where e.spieler_id = sp.id and e.passnummer is not null limit 1)) as passnummer
      from spiel_spieler sp where sp.spiel_id = new.id
  loop
    if v_frisch then
      v_name := null;
      if r.passnummer is not null then
        select nullif(btrim(p.anzeigename), '') into v_name
          from profil p where p.passnummer = r.passnummer limit 1;
      end if;
      if v_name is null then
        v_name := pins_platzhalter_name(v_teams, new.config_json -> 'spielerListe', r.position);
      end if;
      update spiel_spieler set name = v_name where id = r.id;
    else
      -- Bereits anonymisiert: nur ein nachträglich gepushtes config_json wieder einfangen.
      v_name := r.name;
    end if;
    if v_liste is not null and v_liste -> r.position is not null then
      v_liste := jsonb_set(v_liste, array[r.position::text, 'name'], to_jsonb(v_name));
    end if;
  end loop;

  if v_liste is not null then
    new.config_json := jsonb_set(new.config_json, '{spielerListe}', v_liste);
  end if;
  if v_frisch then
    new.anonymisiert_am := now();
  end if;
  return new;
end;
$$;

-- Feuert beim Übergang auf `beendet` (die eigentliche Anonymisierung) und danach bei jedem
-- weiteren config_json-Schreibvorgang auf einem beendeten Spiel (fängt ein nachträgliches
-- pushConfig ab, das die lokal noch vorhandenen Klarnamen zurückschreiben würde).
drop trigger if exists trg_spiel_anonymisieren on spiel;
create trigger trg_spiel_anonymisieren before update on spiel
  for each row
  when (new.status = 'beendet'
        and (old.status is distinct from 'beendet'
             or new.config_json is distinct from old.config_json))
  execute function pins_spiel_anonymisieren();

-- =============================================================================
-- Ergebnis nachträglich dem eigenen Account zuordnen
-- -----------------------------------------------------------------------------
-- Für Spiele ohne LizenzID (Training/Freizeit) und für Alt-Daten, deren profil_id durch die
-- Migration in schema.sql gelöst wurde: der Nutzer markiert in den Statistiken, welcher
-- Spieler er war. security definer, weil die normale spiel_ergebnis_update-Policy den
-- Geräte-Besitz des Spielers verlangt — den hat ein anderes Gerät womöglich längst abgegeben.
-- Setzt NUR auf den eigenen Account und NUR auf noch freie Zeilen (profil_id is null), und
-- nur, wenn der Aufrufer das Spiel ohnehin lesen darf.
drop function if exists ergebnis_mir_zuordnen(uuid);
create or replace function ergebnis_mir_zuordnen(p_ergebnis uuid)
returns boolean
language plpgsql security definer
set search_path = public as $$
declare v_n int := 0;
begin
  if auth.uid() is null then
    raise exception 'nicht angemeldet';
  end if;
  update spiel_ergebnis e
     set profil_id = auth.uid()
   where e.id = p_ergebnis
     and e.profil_id is null
     and (pins_ist_mitglied(e.spiel_id)
          or pins_ist_spiel_besitzer(e.spiel_id)
          or pins_lizenz_im_spiel(e.spiel_id));
  get diagnostics v_n = row_count;
  return v_n > 0;
end;
$$;

grant execute on function ergebnis_mir_zuordnen(uuid) to authenticated;

-- Gegenstück: eine irrtümliche Zuordnung wieder lösen (nur die eigene).
drop function if exists ergebnis_zuordnung_loesen(uuid);
create or replace function ergebnis_zuordnung_loesen(p_ergebnis uuid)
returns void
language sql security definer
set search_path = public as $$
  update spiel_ergebnis set profil_id = null
   where id = p_ergebnis and profil_id = auth.uid();
$$;

grant execute on function ergebnis_zuordnung_loesen(uuid) to authenticated;

-- =============================================================================
-- „Das bin ich" — Selbst-Zuordnung an der Aufstellung (auch für Mitspieler)
-- -----------------------------------------------------------------------------
-- Damit ein Mitspieler seine Ergebnisse in die EIGENE Statistik bekommt, ohne dass er das
-- Spiel erfasst hat und ohne dass er eine LizenzID hinterlegt hat, markiert er sich an der
-- Aufstellung selbst: spiel_spieler.profil_id = sein Konto.
--
-- Warum als security-definer-RPC und nicht über die normale Policy?
--   spiel_spieler_update ist an den ERFASSUNGS-Lock gebunden (besitzer_geraet muss ein eigenes
--   Gerät sein, oder der Spieler ist frei/inaktiv). Das schützt die Wurf-Hoheit — solange der
--   Vereins-PC aktiv erfasst, dürfte ein Mitspieler die Zeile also gar nicht anfassen. Diese
--   Regel wird bewusst NICHT gelockert; die Frage „wer bin ich" hat mit der Wurf-Hoheit nichts
--   zu tun und bekommt deshalb einen eigenen, eng begrenzten Weg.
--
-- Sicherheit: geschrieben wird AUSSCHLIESSLICH auth.uid(). Eine fremde profil_id ist über
-- diesen Weg unmöglich, und eine bereits von jemand anderem beanspruchte Zeile wird nicht
-- überschrieben. Voraussetzung ist Lese-Zugriff auf das Spiel (Mitglied, Ersteller oder die
-- eigene LizenzID steht darin).
drop function if exists spieler_bin_ich(uuid);
create or replace function spieler_bin_ich(p_spieler uuid)
returns boolean
language plpgsql security definer
set search_path = public as $$
declare
  v_spiel uuid;
  v_alt   uuid;
begin
  if auth.uid() is null then
    raise exception 'nicht angemeldet';
  end if;
  select spiel_id, profil_id into v_spiel, v_alt from spiel_spieler where id = p_spieler;
  if v_spiel is null then
    return false;
  end if;
  if not (pins_ist_mitglied(v_spiel)
          or pins_ist_spiel_besitzer(v_spiel)
          or pins_lizenz_im_spiel(v_spiel)) then
    raise exception 'Kein Zugriff auf dieses Spiel';
  end if;
  -- In einem aus Sportwinner importierten Wettkampf ist die Zuordnung durch die amtliche
  -- Aufstellung (LizenzID je Spieler) bereits festgelegt. Eine manuelle Selbstzuordnung ist
  -- dort nicht vorgesehen — sie könnte die amtliche Zuordnung überstimmen und jemandem fremde
  -- Ergebnisse in die Statistik schreiben. Nur manuell angelegte Wettkämpfe und Einzelspiele
  -- (ohne LizenzIDen) lassen die Selbstmarkierung zu. Der Client blendet sie dort ohnehin aus;
  -- diese Prüfung setzt die Regel serverseitig durch.
  if exists (
    select 1 from spiel s
      join wettkampf w on w.id = s.wettkampf_id
     where s.id = v_spiel and w.config_json ->> 'quelle' = 'sportwinner'
  ) then
    raise exception 'In einem Sportwinner-Wettkampf erfolgt die Zuordnung über die LizenzID.';
  end if;
  if v_alt is not null and v_alt <> auth.uid() then
    return false; -- gehört bereits einem anderen Konto: nicht überschreiben
  end if;
  -- Eine Person kann in einem Spiel nur EINE Position sein: eigene Altmarkierung lösen.
  update spiel_spieler set profil_id = null
   where spiel_id = v_spiel and profil_id = auth.uid() and id <> p_spieler;
  update spiel_spieler set profil_id = auth.uid() where id = p_spieler;
  return true;
end;
$$;

grant execute on function spieler_bin_ich(uuid) to authenticated;

-- Gegenstück: die eigene Markierung wieder lösen (nur die eigene).
drop function if exists spieler_bin_ich_loesen(uuid);
create or replace function spieler_bin_ich_loesen(p_spieler uuid)
returns void
language sql security definer
set search_path = public as $$
  update spiel_spieler set profil_id = null
   where id = p_spieler and profil_id = auth.uid();
$$;

grant execute on function spieler_bin_ich_loesen(uuid) to authenticated;

-- Noch freie Ergebniszeilen beanspruchen, deren Aufstellungs-Zeile ICH SELBST markiert habe.
-- Nötig, weil die Ergebniszeilen der ERFASSER schreibt (z.B. der Vereins-PC für alle 12
-- Spieler) und die RLS ihm bewusst verbietet, eine fremde profil_id einzutragen — die
-- Zuordnung holt sich der Spieler daher selbst ab, sobald er online ist.
-- Schreibt ausschließlich auth.uid() und nur auf Zeilen, die noch niemandem gehören.
drop function if exists meine_ergebnisse_beanspruchen();
create or replace function meine_ergebnisse_beanspruchen()
returns int
language plpgsql security definer
set search_path = public as $$
declare v_n int := 0;
begin
  if auth.uid() is null then
    return 0;
  end if;
  update spiel_ergebnis e
     set profil_id = auth.uid()
    from spiel_spieler sp
   where sp.id = e.spieler_id
     and sp.profil_id = auth.uid()
     and e.profil_id is null;
  get diagnostics v_n = row_count;
  return v_n;
end;
$$;

grant execute on function meine_ergebnisse_beanspruchen() to authenticated;
