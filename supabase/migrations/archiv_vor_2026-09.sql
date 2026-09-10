-- =============================================================================
-- ARCHIV — NICHT AUSFÜHREN. Bereits auf Test- und Prod-DB gelaufen.
-- =============================================================================
-- Diese Einmal-Updates standen bis 2026-09 direkt in schema.sql bzw. policies.sql und liefen
-- damit bei JEDEM Einspielen erneut:
--   * der Zuschauer-Code-Backfill gab den per *_verbindung_kappen bewusst entwerteten Spielen
--     und Wettkämpfen jedes Mal wieder einen Code;
--   * die profil_id-Umdeutung setzte jedes Mal alle manuellen Zuordnungen ohne LizenzID zurück
--     (ergebnis_mir_zuordnen, „Das bin ich" im Einzelspiel).
-- Aufgehoben nur, damit nachvollziehbar bleibt, was mit den Alt-Daten passiert ist. Alles
-- Ausführbare steht in einem Kommentarblock.
-- =============================================================================
/*

-- --- aus schema.sql: Zuschauer-Code für bestehende Zeilen ---------------------
-- Bestehende Zeilen einmalig mit einem Code füllen (md5(random) ist volatil -> je Zeile ein
-- eigener Wert), danach den Default für neue Zeilen setzen.
update spiel     set zuschauer_code = upper(substr(md5(random()::text), 1, 6)) where zuschauer_code is null;
update wettkampf set zuschauer_code = upper(substr(md5(random()::text), 1, 6)) where zuschauer_code is null;

-- --- aus schema.sql: profil_id war der ERFASSER --------------------------------
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

-- --- aus policies.sql: Geräte aus der Zeit "Gerät = auth.uid()" -----------------
-- Früher standen in spiel_geraet.geraet / besitzer_geraet / satz_block.geraet direkt
-- auth.uid()-Werte. Damit diese alten Geräte-IDs weiter als gültige Geräte gelten,
-- werden sie als "sich selbst gehörend" (id = konto) ins Register übernommen.
insert into geraet (id, konto)
  select distinct sg.geraet, sg.geraet
  from spiel_geraet sg
  join auth.users u on u.id = sg.geraet
  on conflict (id, konto) do nothing;

*/
