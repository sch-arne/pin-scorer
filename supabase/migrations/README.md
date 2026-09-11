# Migrationen

`schema.sql` und `policies.sql` beschreiben den **Soll-Zustand** und sind idempotent: sie werden
bei jeder Änderung komplett im Supabase-SQL-Editor eingespielt. Deshalb stehen dort **keine
einmaligen Datenänderungen** — sie liefen bei jedem Einspielen erneut. Genau das ist passiert:
ein alter Block in `schema.sql` setzte bei jedem Lauf alle manuellen „Das bin ich"-Zuordnungen
ohne LizenzID zurück.

Einmalige Änderungen (Backfills, Umbau eines Primärschlüssels, Aufräumen von Altbestand) stehen
hier als nummerierte Dateien. Jede läuft **genau einmal** je Datenbank. Welche gelaufen sind,
steht in der Tabelle `schema_migration` (`select * from schema_migration order by am;`); jede
Datei bricht bei einem zweiten Lauf mit einer Fehlermeldung ab, ohne etwas zu ändern.

## Reihenfolge

Immer erst auf der Test-DB, dann auf Prod. Im Kopf jeder Datei steht, ob sie **vor** oder
**nach** `schema.sql`/`policies.sql` laufen muss.

Bestehende Datenbank (Test/Prod), Stand 2026-09:

1. `000_schema_migration.sql`
2. `001_rechte_am_konto.sql`
3. `schema.sql`
4. `policies.sql`
5. `002_klarnamen_frist.sql`
6. `003_altbestand_lizenz.sql`

Frische Datenbank: `schema.sql`, `policies.sql`, danach alle Migrationen der Reihe nach (sie
laufen auch auf leeren Tabellen fehlerfrei durch und werden dabei als erledigt vermerkt).

`archiv_vor_2026-09.sql` enthält die früher in `schema.sql`/`policies.sql` eingebetteten
Einmal-Updates — auskommentiert, nur zur Nachvollziehbarkeit. **Nicht ausführen.**
