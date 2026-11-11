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
Option, und `BahnFilterSink` trennt mehrere Sensoren schon heute sauber voneinander.

## Was im Ursprungs-Repo fehlt: `src/kegel_cv/debug/`

**Der Erkenner lässt sich aus einem frischen Clone nicht starten.** Das Paket
`src/kegel_cv/debug/` ist auf GitHub nicht vorhanden — und zwar nicht aus
Absicht, sondern wegen einer Zeile im `.gitignore` des Ursprungsprojekts:

```
$ git check-ignore -v src/kegel_cv/debug/
.gitignore:36:debug/    src/kegel_cv/debug/
```

Gemeint war damit der Ausgabeordner `debug/` im Projektstamm (Ereignisbilder,
Spuren, hunderte Megabyte je Lauf). Ohne führenden Schrägstrich passt das
Muster aber auf **jeden** Ordner dieses Namens, also auch auf das Quellpaket.
Daraus importieren `src/kegel_cv/main.py` (`logging_setup`) und
`src/kegel_cv/analysis/pipeline.py` (`frame_logger`, `green_trace`,
`lamp_trace`, `cycle_sheet`, `throw_log`, `throw_sheet`).

Folgen hier:

* `python -m kegel_cv.main` bricht beim Import ab.
* 12 Testdateien lassen sich nicht einlesen (dieselben Importe).
* Der **Versand** ist davon unberührt: `sinks/` importiert nichts aus `debug/`,
  und `tests/unit/test_pins_scorer.py` läuft vollständig.

Zu beheben ist das nur beim Urheber: `.gitignore` auf `/debug/` ändern und
`src/kegel_cv/debug/` nachreichen. Nachbauen wäre der falsche Weg — es sind
seine Debug-Werkzeuge, und eine eigene Fassung davon würde bei jedem Abgleich
kollidieren.

## Was wir geändert haben

Siehe [`docs/PINS_SCORER.md`](docs/PINS_SCORER.md) — dort steht in einer Datei, was unsere
Anbindung ausmacht: Tabellen, Anmeldung, Konfiguration und was davon den Upstream-Code berührt.
