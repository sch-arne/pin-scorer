# Herkunft dieses Ordners

Dieser Ordner ist **Kegel_CV** — die Bildererkennung, die die FUNK-Anzeigetafeln aus
Video oder Livestream liest und je Wurf Bahn und gefallene Kegel liefert.

| | |
|---|---|
| Quelle | <https://github.com/ni5080/Kegel_CV> (ni5080 / Niklas) |
| Stand | `4e60f75` „BUG-035 Fall C: zwei Wuerfe in einer Gruenphase, gemessen am Schaden" |
| Geholt | 11.11.2026, `master`, ohne Fremd-Historie |
| Lizenz | siehe [LICENSE](LICENSE) |

## Warum kopiert und nicht als Submodul

Wir bauen die **Senke** um: Kegel_CV schreibt hier in die Datenbank des Pin Scorers, nicht
in das Supabase-Projekt des Urhebers. Dazu kommt ein eigener Anmeldeweg (siehe unten), den
es upstream nicht gibt. Bei dieser Änderungstiefe wäre ein Submodul eine Fessel ohne Nutzen —
Verbesserungen von Niklas holen wir bei Bedarf von Hand nach.

**Regel für diesen Ordner:** Fremde Dateien bleiben unangetastet, wo es irgend geht. Jede
Änderung an Upstream-Code vergrößert den nächsten Abgleich. Was uns gehört, steht möglichst
in eigenen Dateien.

## Was beim Holen weggelassen wurde

| Weggelassen | Grund |
|---|---|
| `apps/liveticker/` | Weboberfläche zum Mitlesen. Das macht bei uns der Pin Scorer selbst — ein zweiter Ticker wäre eine zweite Wahrheit. (Im README und in `tools/export_erkennungs_fixture.py` wird er noch erwähnt; die Texte sind absichtlich unverändert geblieben.) |
| `.github/` | Enthielt nur den Workflow, der den Liveticker baut. |
| `.claude/` | 11 Skills und 38 Fehlerberichte des Urhebers. Inhaltlich wertvoll (der Code verweist auf `BUG-xxx`), würde aber in **jeder** Sitzung dieses Repos in der Skill-Liste auftauchen. Bei Bedarf dort nachlesen: <https://github.com/ni5080/Kegel_CV/tree/master/.claude/skills> |
| `scratch_*.py` | Kurzlebige Skripte des Urhebers, von nichts aufgerufen. |

`android/` ist bewusst **mitgekommen**: ein Telefon als zweiter Sensor an der Bahn bleibt eine
Option, und `BahnFilterSink` trennt mehrere Sensoren schon heute saubereinander.

## Was wir geändert haben

Siehe [`docs/PINS_SCORER.md`](docs/PINS_SCORER.md) — dort steht in einer Datei, was unsere
Anbindung ausmacht: Tabellen, Anmeldung, Konfiguration und was davon den Upstream-Code berührt.
