# Herkunft dieses Ordners

Dieser Ordner ist **Kegel_CV** — die Bildererkennung, die die FUNK-Anzeigetafeln aus
Video oder Livestream liest und je Wurf Bahn und gefallene Kegel liefert.

| | |
|---|---|
| Quelle | <https://github.com/ni5080/Kegel_CV> (ni5080 / Niklas) |
| Stand | `e63e047` „Das Debug-Paket fehlte im Repo — .gitignore traf auch src/kegel_cv/debug" |
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

## Behoben: das fehlende `debug/`-Paket

Beim ersten Holen fehlte `src/kegel_cv/debug/` vollständig — die `.gitignore`-Zeile `debug/`
ohne führenden Schrägstrich traf nicht nur den Ausgabeordner, sondern auch das Quellpaket
(`git check-ignore -v src/kegel_cv/debug/` belegte es). `main.py` und `analysis/pipeline.py`
importieren daraus, also startete der Erkenner aus einem frischen Clone nicht, und 12
Testdateien ließen sich nicht einmal einlesen.

Gemeldet und **upstream behoben** (`e63e047`: die Zeile heißt jetzt `/debug/`, das Paket ist
drin). Am 11.11.2026 nachgezogen. Seither importieren `kegel_cv.main` und
`kegel_cv.analysis.pipeline` durch, und von den vorher 16 Fehlschlägen plus 12 Sammelfehlern
bleibt genau einer übrig: **1479 Tests grün, 1 rot, 1 übersprungen.** Der rote steht im
nächsten Abschnitt.

## Offen: OpenCV liest unter Windows keine Pfade mit Umlauten

**Das betrifft dieses Repo unmittelbar**, denn es liegt unter
`…\OneDrive - Verein Osnabrücker Kegler e.V\…`. Gemessen am 11.11.2026, dieselbe Datei:

```
cv2.imread(r"…\Osnabrücker Kegler e.V\…\data\boardtypes\FUNK_klassisch.png")  ->  None
cv2.imread(r"C:\Users\…\AppData\Local\Temp\ascii_test.png")                   ->  (191, 190, 3)
np.fromfile(<Umlaut-Pfad>) + cv2.imdecode(…)                                  ->  (191, 190, 3)
```

Die Datei ist in Ordnung — byte-identisch zum frischen Clone. OpenCV benutzt auf Windows die
ANSI-Dateifunktionen und findet sie unter diesem Namen nicht. Folge: Die Tafeltyp-Bibliothek
bleibt leer („Musterbild FUNK_klassisch.png liess sich nicht lesen"), die automatische
Kalibrierung findet keinen Typ, und `tests/unit/test_auto_kalibrieren.py` schlägt fehl.
Videodateien unter so einem Pfad kann `cv2.VideoCapture` ebenso nicht öffnen.

Ein Verzeichnis-Link mit ASCII-Namen auf diesen Ordner hilft **nicht**: der Code löst den
Pfad über `Path.resolve()` zur echten Stelle zurück — gemessen, die Prüfung bleibt auch über
die Verzweigung rot.

Betroffen sind wenige Stellen im fremden Code: `calibration/board_library.py` (`cv2.imread`,
`cv2.imwrite`), `debug/frame_logger.py` (`cv2.imwrite`) und `video/file_source.py`
(`cv2.VideoCapture`). Für Bilder ist der Umweg bekannt und einzeilig (`np.fromfile` +
`cv2.imdecode`, beim Schreiben `cv2.imencode` + `tofile`); für `VideoCapture` gibt es keinen
sauberen — dort hilft nur der kurze Pfadname (8.3) oder eben ein ASCII-Pfad.

**Deshalb hier nicht gepatcht:** Es ist ein Fehler des Erkenners, keiner der Anbindung, und
er trifft jeden Betreiber mit einem Umlaut im Pfad — in einem deutschen Verein also leicht
(„Osnabrücker", „Müller", „Köln"). Er gehört upstream behoben, sonst steht die Änderung bei
jedem Abgleich im Weg. Bis dahin: den Erkenner von einem Pfad ohne Umlaute betreiben. Für den
Rechner an der Bahn ist das ohnehin der Normalfall.

## Was wir geändert haben

Siehe [`docs/PINS_SCORER.md`](docs/PINS_SCORER.md) — dort steht in einer Datei, was unsere
Anbindung ausmacht: Tabellen, Anmeldung, Konfiguration und was davon den Upstream-Code berührt.
