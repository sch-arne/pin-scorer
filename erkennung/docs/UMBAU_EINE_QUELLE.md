# Umbauplan: Eine Bildquelle statt zweier

**Stand: 2026-09-17 — geschrieben, noch nicht begonnen.**
*Überarbeitet am selben Tag: Schritt 3 entfällt, siehe dort.*

Nutzervorschlag: *„Wollen wir nicht Player und Analyse endgültig vereinen? Ich
verstehe immer noch nicht den Mehrwert davon 2 Systeme zu haben... Dann soll
doch besser immer eine Analyse laufen, und erst wenn man auf 'Analyse starten'
klickt, wie an Supabase geschrieben."*

---

## Warum

Heute lesen **zwei unabhängige Systeme dieselbe Quelle**:

| | öffnet | wann |
|---|---|---|
| `VideoPlayer` | eigene `VideoSource` | beim Laden |
| `AnalysisWorker` | eigene `VideoSource` (`analysis_worker.py:184`) | beim Start der Analyse |

Sie schließen einander aus: Für einen Stream ruft das Hauptfenster
`player.close()` (`main_window.py:2174`), damit nicht zwei Verbindungen offen
sind.

Daraus folgt eine ganze Klasse von Fehlern, und zwei davon sind am 2026-09-17
tatsächlich aufgetreten:

1. **Das eingefrorene Bild beim Nachkalibrieren.** `_bild_zum_nachziehen`
   fragte zuerst den Player. Der war während der Analyse geschlossen, hielt
   aber sein letztes Bild von VOR dem Start — „frisches Bild" lieferte für
   immer dasselbe. Der Nutzer: *„Die Feinkalibrierung mit Standbild und
   frisches Bild funktioniert btw nicht. Zumindest nicht, wenn man bereits in
   der Analyse steckt."*
2. **Zwei Zeitpunkte nebeneinander ohne Hinweis.** Die Kegelraute zeigt den
   Live-Lampenstand, die Zeile darunter den zuletzt gebuchten Wurf. Daran sind
   an diesem Tag beide Seiten hängengeblieben — der Nutzer beim Lampenkranz,
   ich beim Frame 47057.

Die Reparaturen waren jedes Mal Sonderfälle: eine dreistufige Rückfallkette in
`_bild_zum_nachziehen`, ein zusätzliches `_analyse_bild`, ein Sonderpfad in
`_springe_frames`. Solange es zwei Quellen gibt, kommt die nächste Variante.

---

## Was schon da ist

Der Umbau ist kleiner, als er klingt. Zwei Bausteine existieren bereits:

* **`AnalysisWorker.set_sending(aktiv)`** — der Versand ist schon getrennt. Die
  Statusmeldung lautet heute wörtlich *„Versand pausiert — es wird weiter
  ausgewertet und angezeigt"*. Genau das, was der Vorschlag verlangt.
* **`AnalysisWorker.uebernimm_kalibrierung(kal)`** — eine laufende Analyse
  nimmt eine geänderte Kalibrierung entgegen. Ohne das wäre „kalibrieren,
  während es läuft" gar nicht möglich.

**Nicht** gebaut werden muss also: die Versandlogik, die Live-Übernahme der
Kalibrierung, die Signalwege zur Oberfläche.

---

## Was sich ändert

### 1. Der Worker wird der einzige Leser

`AnalysisWorker` öffnet die Quelle und liefert jeden Frame weiter. Der
`VideoPlayer` liest nicht mehr selbst, sondern wird zur **Steuerung**:
Abspielen, Pause, Tempo. Seine Signale (`frame_ready`, `opened`,
`finished`) bleiben — sie werden künftig vom Worker gespeist.

Damit gibt es genau ein aktuelles Bild, und die Frage „welches ist das
richtige" stellt sich nicht mehr.

### 2. Die Analyse beginnt beim Laden, nicht auf Knopfdruck

Wer eine Datei oder einen Stream öffnet, sieht ab dem ersten Frame die
Auswertung. Der Knopf heißt dann nicht mehr „Analyse starten", sondern trägt,
was er wirklich tut: **an die Datenbank senden**.

### 3. Springen entfällt in der Bedienung

Der Nutzer dazu (2026-09-17): *„das springen ist glaube ich nicht wichtig, ich
habe es noch nie benutzt."*

Damit fällt der teuerste Teil dieses Umbaus weg. Ursprünglich stand hier, ein
Sprung müsse den Analysezustand verwerfen — die Auswertung läuft streng
vorwärts (Grünphasen, Wurffenster, gleitende Schwellen), ein Rücksprung macht
sie ungültig. Wird gar nicht gesprungen, gibt es das Problem nicht.

**Was intern trotzdem springt, und weiter darf:**

* `AnalysisWorker._vorspulen` — spult beim Start auf einen Anfangsframe vor
  (`--start-frame`). Der Worker besitzt die Quelle, also bleibt das, wie es
  ist.
* Die Sammlung mehrerer Frames für die automatische Tafelerkennung
  (`main_window.py:1282`). Sie springt **nur bei einer Datei**; für einen
  Stream nutzt dieselbe Funktion schon heute `step_forward()`. Nach dem Umbau
  geht beides über das Vorwärtslaufen.

Verloren geht damit nur das Frame-Springen der Ziffernlupe bei Dateien
(∓1/10/100), das am selben Tag entstand. Für den Stream — den eigentlichen
Betriebsfall — gab es dort ohnehin nur „frisches Bild".

### 4. Was ersatzlos verschwindet

* die dreistufige Rückfallkette in `_bild_zum_nachziehen`
* `_analyse_bild` und `_analyse_bild_index`
* der Sonderpfad für `_analyse_aktiv` in `_springe_frames`
* die Fallunterscheidung „Player geladen / Stream / Analyse läuft" bei den
  Rückwärtsknöpfen des Tafeleditors

---

## Was es kostet

**Die Analyse läuft immer mit: rund 25–30 ms je Frame**, samt Personenmodell.
Bei 25 fps sind das etwa drei Viertel eines Kerns. Wer ein Video nur
durchschauen will, zahlt das ohne Nutzen.

Deshalb gehört ein Schalter dazu: *Auswertung aus* für das bloße Sichten. Er
ist billig zu haben — der Worker kann bereits pausieren (`set_paused`).

**Gemessen ist diese Zahl an der Analyse, nicht am gemeinsamen Betrieb.** Ob
das Zusammenlegen von Lesen und Auswerten in einem Thread die Bildrate hält,
ist offen und gehört vor dem Umbau geprüft (siehe Schritt 0).

---

## Reihenfolge, und wie jeder Schritt geprüft wird

**Schritt 0 — messen, bevor gebaut wird.**
Hält ein einzelner Thread Lesen und Auswerten bei 25 fps durch? Gemessen wird
am Livestream über 5000 Frames: erreichte Bildrate, verlorene Frames, ms je
Frame. Fällt das durch, ändert sich der Zuschnitt (Lesen und Auswerten in
getrennten Threads mit einer Warteschlange), nicht das Ziel.

**Schritt 1 — der Worker liefert jeden Frame.**
`preview_ready` wird zu einem vollwertigen Frame-Signal. Der Player bezieht
seine Bilder daraus statt aus eigener Quelle.
*Geprüft:* Die bestehenden Offscreen-Tests am echten Hauptfenster laufen
weiter; ein neuer Test hält fest, dass nach dem Laden genau **eine** Quelle
geöffnet ist.

**Schritt 2 — Analyse ab dem Laden.**
Der Worker startet mit der Quelle, `sending` ist aus.
*Geprüft:* Ein Test lädt eine Datei und erwartet Auswertungsergebnisse, ohne
dass jemand einen Knopf gedrückt hat.

**Schritt 3 — entfällt.** Siehe oben: Es wird nicht gesprungen.

**Schritt 4 — die Sonderfälle löschen.**
Erst wenn 1 bis 3 stehen. Die heute dafür geschriebenen Tests
(`test_ziffernlupe_gui.py::TestNachkalibrierenWaehrendDerAnalyse`) werden
umgeschrieben: Sie prüfen dann, dass es nur noch **einen** Weg zum aktuellen
Bild gibt.

**Schritt 5 — der Knopf heißt, was er tut.**
„Analyse starten" wird zu „An Datenbank senden". Dazu ein Schalter
„Auswertung aus" für das bloße Sichten.

---

## Was dieser Umbau NICHT anfasst

* die Auswertung selbst (`analysis/`, `detection/`) — sie bekommt dieselben
  Frames wie heute
* den Versand und seine Warteschlange
* die Kalibrierung und die Ziffernlupe
* die Gegenprobe

---

## Risiken, offen benannt

**~~Der Player ist heute die einzige Stelle, die das Springen beherrscht.~~**
Entfallen: Es wird nicht gesprungen (siehe Punkt 3). Das war das größte Risiko
dieses Umbaus, und es ist mit einem Satz des Nutzers weggefallen -- ein gutes
Argument dafür, vor dem Bauen zu fragen, was tatsächlich benutzt wird.

**Ein Stream hat kein Ende.** Läuft die Auswertung ab dem Laden, läuft sie auch
stundenlang weiter, während jemand nur zusieht. Der Schalter aus Schritt 5 ist
deshalb kein Beiwerk.

**Ich habe an diesem Tag zweimal an dieser Stelle danebengegriffen** — einmal
beim Standbild, einmal beim Bild aus dem Worker. Beide Male, weil ich den
Unterschied zwischen den zwei Quellen unterschätzt habe. Das ist ein Argument
für den Umbau, aber auch eine Warnung, ihn nicht in einem Zug zu machen.
