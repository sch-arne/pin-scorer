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
-- Geräte-Identität ist ENTKOPPELT vom Account: jedes Gerät hat eine eigene, vom
-- Client erzeugte UUID (Tabelle `geraet`), unabhängig davon, wer eingeloggt ist.
--   * auth.uid()  = Person / Account  -> spiel.besitzer, profil, Statistik (profil_id)
--   * geraet.id   = dieses Gerät      -> Mitgliedschaft (spiel_geraet), Spieler-Lock
-- So können MEHRERE Geräte GLEICHZEITIG im selben Account erfassen (verschiedene
-- Geräte-IDs => der Besitz-Lock trennt sie sauber). Die RLS vertraut nur der
-- serverseitigen Bindung geraet.konto = auth.uid().
-- =============================================================================

-- Geräte-Register: bindet eine (client-seitig erzeugte) Geräte-ID an einen Account.
-- Primärschlüssel (id, konto): dasselbe Gerät kann über die Zeit an mehrere Accounts
-- gebunden sein (anonym -> Account, oder Kontowechsel auf demselben Browser).
create table if not exists geraet (
  id            uuid not null,               -- vom Client erzeugt (localStorage), NICHT auth.uid()
  konto         uuid not null references auth.users(id) on delete cascade,
  name          text,
  erstellt_am   timestamptz not null default now(),
  gesehen_am    timestamptz not null default now(),
  primary key (id, konto)
);
create index if not exists idx_geraet_konto on geraet(konto);

-- 1:1 zu auth.users. Wird erst im Account-Schritt befüllt (anon-Nutzer haben keins).
-- Nur `anzeigename` wird öffentlich (View profil_public, siehe policies.sql) und erscheint
-- im Livestream. Alle übrigen Felder sind privat (self-only RLS). vorname/nachname/verein
-- sind selbst eingegeben; passnummer (Sportwinner-SpielerID) dient dem späteren Abgleich.
create table if not exists profil (
  id            uuid primary key references auth.users(id) on delete cascade,
  anzeigename   text,
  vorname       text,
  nachname      text,
  verein        text,
  passnummer    text,
  erstellt_am   timestamptz not null default now()
);
-- Idempotent für bereits bestehende profil-Tabellen (ALTER ist ein No-op, wenn Spalte da).
alter table profil add column if not exists vorname    text;
alter table profil add column if not exists nachname   text;
alter table profil add column if not exists verein     text;
alter table profil add column if not exists passnummer text;

-- Kegel-Anlage (physischer Standort mit Bahnen). Jeder eingeloggte Account darf eine
-- Anlage anlegen (reale Daten sind im Formular Pflicht); alle dürfen Anlagen lesen und
-- darauf spielen (RLS: select = true). Ändern/Löschen nur der Besitzer. Erweiterte
-- Funktionen (Kontrollzentrum, Sportwinner, Livestream/OBS) sind späteren Etappen
-- vorbehalten und nur für freigeschaltete Accounts (Tabelle `freischaltung`).
create table if not exists anlage (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  ort           text,
  besitzer      uuid references auth.users(id) on delete set null,
  erstellt_am   timestamptz not null default now()
);
-- Idempotente Erweiterungen (No-op, wenn Spalte bereits existiert).
alter table anlage add column if not exists strasse         text;
alter table anlage add column if not exists plz             text;
alter table anlage add column if not exists anzahl_bahnen   int not null default 4;
alter table anlage add column if not exists aktualisiert_am timestamptz not null default now();
-- Weicher Duplikat-Index (nur zur Warnung im Formular; KEINE Unique-Constraint —
-- verschiedene Anlagen dürfen denselben Namen tragen).
create index if not exists idx_anlage_dupe on anlage(lower(name), plz);

-- Bahnen einer Anlage. Nummer je Anlage eindeutig; bahnart optional pro Bahn.
-- roi_json ist für die spätere OCR-Kalibrierung (FUNK-Display) reserviert.
create table if not exists bahn (
  id        uuid primary key default gen_random_uuid(),
  anlage_id uuid not null references anlage(id) on delete cascade,
  nummer    int  not null,
  bahnart   text,
  roi_json  jsonb,
  unique (anlage_id, nummer)
);
create index if not exists idx_bahn_anlage on bahn(anlage_id);

-- Hinweis: Bahngruppen (welche Bahnen zusammen bespielt werden) sind bewusst NICHT
-- Teil der Anlagen-Stammdaten. Sie werden später beim Spiel-Setup zusammengestellt
-- (Etappe 2), da die Zusammenstellung je Spiel unterschiedlich ist.

-- Freischaltung (Betreiber-Whitelist). Pflegt der Betreiber ausschließlich per SQL:
--   insert into freischaltung(konto) values ('<auth.users.id>');
-- Schaltet die erweiterten Anlagen-Funktionen für diesen Account frei. Clients dürfen
-- die Tabelle nur LESEN (eigene Zeile), niemals schreiben (siehe policies.sql).
create table if not exists freischaltung (
  konto       uuid primary key references auth.users(id) on delete cascade,
  stufe       text not null default 'erweitert',
  notiz       text,
  erstellt_am timestamptz not null default now()
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
-- LizenzID/Passnummer des Spielers (Sportwinner-SpielerID) am Ergebnis mitschreiben, damit ein
-- Spieler SEINE Ergebnisse auch in fremd erfassten Spielen (z.B. Vereins-PC) wiederfindet, ohne
-- dem Spiel beigetreten zu sein — Abgleich gegen profil.passnummer (siehe policies.sql). Idempotent.
alter table spiel_ergebnis add column if not exists passnummer text;
create index if not exists idx_spiel_ergebnis_passnummer on spiel_ergebnis(passnummer);

-- --- Wettkampf: Klammer über mehrere Durchgänge ------------------------------
-- Ein Wettkampf bündelt mehrere Durchgänge (jeder Durchgang = ein normales `spiel`,
-- verknüpft über spiel.wettkampf_id). Die gesamte lokale Wettkampf-Struktur
-- (Mannschaften inkl. Bahnen, Programm-Vorlage, spielerJeMannschaft, …) liegt in
-- config_json — genau wie spiel.config_json das Setup eines Spiels hält. Die
-- Durchgang-Liste wird NICHT aus config_json gelesen, sondern relational über die
-- `spiel`-Zeilen (wettkampf_id, durchgang_nr) rekonstruiert, damit später ergänzte
-- Durchgänge automatisch bei allen beigetretenen Geräten auftauchen.
create table if not exists wettkampf (
  id             uuid primary key default gen_random_uuid(),
  besitzer       uuid references auth.users(id) on delete set null,
  name           text,
  datum          date,
  anlage_id      uuid references anlage(id) on delete set null,
  status         text not null default 'setup' check (status in ('setup','laufend','beendet')),
  config_json    jsonb not null default '{}'::jsonb,
  beitritts_code text unique default upper(substr(md5(random()::text), 1, 6)),
  erstellt_am    timestamptz not null default now(),
  aktualisiert_am timestamptz not null default now()
);

-- Mitgliedschaft: welches Gerät ist welchem Wettkampf beigetreten. Analog zu
-- spiel_geraet, aber auf Wettkampf-Ebene: die Mitgliedschaft öffnet den Lese-/
-- Schreibzugriff auf ALLE Durchgang-Spiele des Wettkampfs (siehe policies.sql:
-- pins_ist_mitglied prüft zusätzlich die Wettkampf-Mitgliedschaft).
create table if not exists wettkampf_geraet (
  wettkampf_id   uuid not null references wettkampf(id) on delete cascade,
  geraet         uuid not null,
  beigetreten_am timestamptz not null default now(),
  primary key (wettkampf_id, geraet)
);
create index if not exists idx_wettkampf_geraet_geraet on wettkampf_geraet(geraet);

-- Ein Durchgang gehört zu genau einem Wettkampf (oder zu keinem = Einzelspiel).
-- ON DELETE CASCADE: einen Wettkampf löschen entfernt serverseitig seine Durchgänge
-- (spiegelt die lokale deleteWettkampf-Semantik). durchgang_nr = 1-basierte Reihenfolge.
alter table spiel add column if not exists wettkampf_id uuid references wettkampf(id) on delete cascade;
alter table spiel add column if not exists durchgang_nr int;
create index if not exists idx_spiel_wettkampf on spiel(wettkampf_id);

-- --- Zuschauer-Code: zweiter, NUR-LESEN-Code ---------------------------------
-- Neben dem beitritts_code (Eingabe/Erfassen) trägt jedes Spiel/jeder Wettkampf einen
-- SEPARATEN zuschauer_code. Wer ihn kennt, darf live ZUSEHEN — über die anonymen Snapshot-
-- RPCs spiel_zuschauer / wettkampf_zuschauer (policies.sql), die AUSSCHLIESSLICH lesbare
-- Ergebnisdaten liefern und WEDER Codes NOCH Besitz preisgeben. Ein Zuschauer wird KEIN
-- Gerät-Mitglied (kein Eintrag in spiel_geraet/wettkampf_geraet) und kann daher per
-- Konstruktion nichts schreiben und den Eingabe-Code nicht auslesen. So lässt sich ein
-- reiner Zuschauer-Link teilen, ohne Eingaberecht zu vergeben. Idempotent.
alter table spiel     add column if not exists zuschauer_code text;
alter table wettkampf add column if not exists zuschauer_code text;
-- Bestehende Zeilen einmalig mit einem Code füllen (md5(random) ist volatil -> je Zeile ein
-- eigener Wert), danach den Default für neue Zeilen setzen.
update spiel     set zuschauer_code = upper(substr(md5(random()::text), 1, 6)) where zuschauer_code is null;
update wettkampf set zuschauer_code = upper(substr(md5(random()::text), 1, 6)) where zuschauer_code is null;
alter table spiel     alter column zuschauer_code set default upper(substr(md5(random()::text), 1, 6));
alter table wettkampf alter column zuschauer_code set default upper(substr(md5(random()::text), 1, 6));
create unique index if not exists idx_spiel_zuschauer_code     on spiel(zuschauer_code);
create unique index if not exists idx_wettkampf_zuschauer_code on wettkampf(zuschauer_code);

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

drop trigger if exists trg_anlage_touch on anlage;
create trigger trg_anlage_touch before update on anlage
  for each row execute function pins_touch_aktualisiert_am();

drop trigger if exists trg_wettkampf_touch on wettkampf;
create trigger trg_wettkampf_touch before update on wettkampf
  for each row execute function pins_touch_aktualisiert_am();

-- --- LizenzID/Passnummer nur EINMAL setzbar ----------------------------------
-- Die Passnummer verknüpft den Account mit allen Spielen, in denen sie als Spieler geführt
-- wird (Statistik + Öffnen dieser Spiele). Damit niemand per nachträglicher Änderung fremde
-- Spiele „an sich zieht", ist sie einmalig: null -> Wert ist erlaubt, jede spätere Änderung
-- eines bereits gesetzten Werts (auch das Zurücksetzen auf null) wird serverseitig abgelehnt.
create or replace function pins_passnummer_set_once()
returns trigger language plpgsql as $$
begin
  if old.passnummer is not null and new.passnummer is distinct from old.passnummer then
    raise exception 'LizenzID kann nicht geändert werden (nur einmalig setzbar).'
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

drop trigger if exists trg_profil_passnummer_once on profil;
create trigger trg_profil_passnummer_once before update on profil
  for each row execute function pins_passnummer_set_once();

-- --- Realtime: satz_block + spiel_spieler in die Realtime-Publication ---------
-- (Live-Sync der Würfe und des Besitz-Locks an alle beigetretenen Geräte.)
do $$
begin
  begin execute 'alter publication supabase_realtime add table satz_block';    exception when duplicate_object then null; end;
  begin execute 'alter publication supabase_realtime add table spiel_spieler';  exception when duplicate_object then null; end;
  begin execute 'alter publication supabase_realtime add table spiel';          exception when duplicate_object then null; end;
  begin execute 'alter publication supabase_realtime add table wettkampf';       exception when duplicate_object then null; end;
end $$;

-- --- Spieler-Identität: wer ist WER in einem Spiel? --------------------------
-- Bisher trug NUR spiel_ergebnis.passnummer die LizenzID — und die wird erst bei
-- Spielende geschrieben. Für die Anonymisierung (Trigger, siehe policies.sql) und für
-- die Zuordnung „dieser Slot bin ich" braucht die Aufstellung sie ab dem Anlegen.
--
-- WICHTIG (Datenschutz): spiel_spieler wird von KEINER Zuschauer-/Overlay-RPC
-- ausgeliefert (spiel_zuschauer/wettkampf_zuschauer geben nur id/position/name/start_bahn
-- zurück). Die LizenzID liegt damit ausschließlich hinter der RLS — anders als bisher,
-- wo sie über wettkampf.config_json.sportwinner an `anon` durchgereicht wurde.
alter table spiel_spieler add column if not exists passnummer text;
create index if not exists idx_spiel_spieler_passnummer on spiel_spieler(passnummer);

-- Wer hat die Ergebniszeile ERFASST (Gerät/Account des Schreibers) — getrennt von
-- profil_id, das ab jetzt ausschließlich „das bin ICH als Spieler" bedeutet. Vorher
-- stand in profil_id der Erfasser, wodurch alle mit erfassten Gegner/Mitspieler in
-- der eigenen Account-Statistik landeten.
alter table spiel_ergebnis add column if not exists erfasst_von uuid references auth.users(id) on delete set null;
create index if not exists idx_spiel_ergebnis_erfasst_von on spiel_ergebnis(erfasst_von);

-- Zeitstempel der serverseitigen Anonymisierung bei Spielende (macht den Trigger
-- pins_spiel_anonymisieren idempotent; siehe policies.sql).
alter table spiel add column if not exists anonymisiert_am timestamptz;

-- --- MIGRATION (einmalig) — profil_id war der ERFASSER -----------------------
-- Alt-Daten: pushResults setzte profil_id für JEDEN vom Gerät gesteuerten Spieler auf
-- das eigene Konto. Diese Bedeutung zieht auf erfasst_von um; profil_id behält die
-- Zuordnung nur dort, wo sie über die LizenzID belegbar ist (passnummer der Zeile =
-- passnummer des verknüpften Profils). Alles übrige wird gelöst — nicht auflösbare
-- Zuordnungen lassen sich in den Statistiken per RPC ergebnis_mir_zuordnen nachtragen.
update spiel_ergebnis
   set erfasst_von = profil_id
 where erfasst_von is null and profil_id is not null;

update spiel_ergebnis e
   set profil_id = null
 where e.profil_id is not null
   and not exists (
     select 1 from profil p
      where p.id = e.profil_id
        and p.passnummer is not null
        and p.passnummer = e.passnummer
   );
