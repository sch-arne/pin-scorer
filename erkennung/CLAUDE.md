# CLAUDE.md — Arbeitsanweisung für dieses Projekt

## Vor jeder Aufgabe

1. **`.claude/skills/ORCHESTRATION.md` lesen** — Projektzustand, Phasenplan, Skill-Landkarte.
   Das ist der Kompass; dieses File hier ist nur die Kurzfassung.
2. Den passenden Fach-Skill laden (Trigger-Tabelle steht in der Orchestrierung).
3. Bei einem Bug: **`.claude/skills/BUG_ORCHESTRATION.md`** — Workflow einhalten,
   BugSkill anlegen.

## Sprache

- **Code, Modul- und Variablennamen, Config-Keys: englisch**
- **Kommentare, Docstrings, Log-Meldungen, GUI-Texte, Dokumentation: deutsch**

Der Nutzer liest Meldungen und Doku — Code folgt der Werkzeugkonvention.

## Die sieben Regeln, die hier am meisten wiegen

1. **Nicht raten — messen.** Bei Unklarheit über das Material: Frames extrahieren,
   ansehen, Ergebnis in `docs/VIDEO_ANALYSIS.md`. Bleibt es unklar →
   `docs/OPEN_QUESTIONS.md`. Eine geratene Annahme, die zufällig auf dem
   Testmaterial funktioniert, ist schlimmer als eine dokumentierte Lücke.
2. **Keine Magic Numbers.** Jeder Schwellwert steht in `config/default.yaml`,
   mit Begründung und — wenn gemessen — mit Messbeleg.
3. **Die vier Bahnen sind unabhängig.** Nie synchrone Ereignisse annehmen.
   Pro Bahn eigener Zustand, eigener Punktestand.
4. **Kein Frame-für-Frame-ML.** Billige Trigger steuern teure Analyse.
   Eskalation nur mit Messbeleg, dass die einfachere Stufe versagt.
5. **Jedes Ergebnis erklärt sich selbst.** `evidence` ist Pflicht, nicht Kür.
6. **Fehler beenden die Analyse nicht.** `except: pass` ist verboten
   (wird von `tests/unit/test_architecture.py` automatisch geprüft).
7. **Fehler brauchen ein belastbares GIF.** Jeder untersuchte Fehler wird als
   GIF der Tafel belegt — Frame für Frame, mit ALLEN dort ausgelesenen Werten:
   Zeit, Framenummer, Grünzustand, jede Kegellampe einzeln, jedes Ziffernfeld.
   Werkzeug: `tools/streitfall_gif.py`. Ein GIF hat an diesem Projekt bisher
   jedes Mal etwas aufgedeckt, das in Zahlen nicht zu sehen war — unter
   anderem, dass eine „15 Frames kurze Grünphase" in Wahrheit eine 140 Frames
   zu späte Erkennung war.

## Befehle

```bash
.venv/Scripts/python.exe -m kegel_cv.main          # Anwendung starten
```

```bash
.venv/Scripts/python.exe -m pytest tests/unit -q   # schnelle Tests
```

```bash
.venv/Scripts/python.exe tools/verify_rois.py --frame 90   # ROI-Sichtprüfung
```

Die venv liegt unter `.venv/`. Unter Windows/Git-Bash immer
`.venv/Scripts/python.exe` verwenden, nicht `python`.

## Vor dem Abschluss einer Aufgabe

- [ ] Tests geschrieben und die vollständige Suite grün
- [ ] Neue Parameter in `config/default.yaml` statt im Code
- [ ] Status in `.claude/skills/ORCHESTRATION.md` aktualisiert
- [ ] Bei aufgetretenem Bug: BugSkill angelegt, `BUGS_INDEX.md` ergänzt,
      **GIF erzeugt und im SKILL verlinkt** (Regel 7)
- [ ] Neue Messergebnisse in `docs/VIDEO_ANALYSIS.md`

## Was hier nicht passieren darf

| ❌ | Warum |
|---|---|
| Feste Pixelkoordinaten für ROIs | Overlay-Position variiert zwischen Sessions (gemessen) |
| Wurf allein an geänderter Kegelzahl erkennen | Würfe mit 0 Kegeln existieren |
| Ein einzelnes Frame entscheiden lassen | Ziffern flackern, Lampen rauschen |
| Qt-Widgets aus einem Worker-Thread berühren | sporadische, kaum reproduzierbare Fehler |
| `cv2.VideoCapture` in `analysis/` oder `detection/` | verhindert die spätere Stream-Quelle |
| Bei widersprüchlichen Quellen eine „wegentscheiden" | die Redundanz existiert, um Fehler zu zeigen |
