# Kegel_CV auf dem Telefon

> **Stand: Fundament, noch keine Anwendung.** Dieser Ordner enthält eine App,
> die genau eine Frage beantwortet — läuft der Erkennungskern auf echter
> Hardware, und was kosten die Rechenschritte? Kamera und Bedienung kommen
> danach. Wer zuerst die Oberfläche baut, merkt zu spät, dass das Fundament
> nicht trägt.

## Warum überhaupt eine App

Damit man nicht darauf angewiesen ist, dass die Halle einen Kamerastream
anbietet. Freizeitsport soll dieselbe Erfassung bekommen wie der Profisport.

## Die eine Bedingung: Stativ

Das gesamte Verfahren setzt eine **feste Kamera** voraus, und zwar nicht als
Empfehlung, sondern rechnerisch:

- Die Personenmaske ist ein Hintergrundmodell — bewegt sich die Kamera, ist
  *alles* Vordergrund.
- Das Kalibrierviereck sind feste Bildkoordinaten.
- Die Tafelwache vergleicht dieselben Bildpunkte gegen eine Referenz.

Bei BUG-026 haben **wenige Pixel Versatz** eine Bahn für 13 000 Frames
stillgelegt. Freihändig filmen ist kein „etwas ungenauer", sondern ein anderes
Verfahren. Die App sagt das dem Nutzer, statt es im Kleingedruckten zu
verstecken.

## Was mitwandert — und was nicht

Der gemessene Kern wird **nicht neu geschrieben**. Das ist keine Bequemlichkeit:
Jeder Schwellwert dieses Projekts ist an dieser Implementierung gemessen; eine
zweite Fassung in Kotlin wäre in einem Monat ein zweites Programm mit eigenen
Fehlern.

| kommt mit (Python, unverändert) | wird neu (Kotlin) |
|---|---|
| `detection/`, `analysis/`, `calibration/`, `models/`, `sinks/` | Kamera (CameraX) |
| `config/` samt aller Messwerte | Oberfläche, Tafelsuche-Dialog |
| das Personenmodell | Schreibweg zur Datenbank |

Nicht mit kommt `gui/` (PySide6) und `video/` — beides ersetzt die App.

## Die drei Machbarkeitsfragen (geprüft 2026-09-14)

| Frage | Antwort |
|---|---|
| Gibt es OpenCV für Chaquopy? | Ja — 4.5.1.48 für `cp310`/`arm64`, dazu numpy 1.26 |
| Läuft unser Kern auf OpenCV 4.5? | Ja — keine einzige echte Inkompatibilität |
| Liest OpenCV 4.5 das Personenmodell? | **Nein.** Siehe unten. |

### Auf dem Gerät gemessen (Xiaomi 2306EPN60G, Android 15, arm64)

```
Python   3.10.19      numpy 1.26.2      OpenCV 4.5.1

Grünlampe (50x50)        0.02 ms
Tafel entzerren          0.96 ms
Bewegungsmaske (1/4)     0.98 ms
```

Alle drei Schritte, die in jedem Frame stecken, kosten zusammen rund **2 ms**.
Das Fundament trägt.

### Das Personenmodell trägt jetzt auch

```
Slice layer only supports steps = 1
```

Die **Focus-Schicht** am Netzeingang zerlegt das Bild mit Schrittweite 2.
Neuere ONNX-Importer können das, der von OpenCV 4.5.1 nicht.

Und hier steckt eine Lehre, die teurer war als nötig: Der Vorabtest lief gegen
OpenCV **4.5.5**, weil es für 4.5.1 keine Räder für Python 3.10 auf Windows
gibt. Dabei stand in diesem README der Satz *„die API ist zwischen beiden
unverändert"* — **er war falsch**, geraten statt geprüft. 4.5.5 lädt das
Modell, 4.5.1 nicht. Gefunden hat es erst das Gerät.

Alle Kandidaten lokal auf genau diese Operation untersucht:

| Modell | Slices mit Schrittweite ≠ 1 | lädt auf 4.5.1 |
|---|---|---|
| YOLOX-Tiny | 8 | nein |
| YOLOX-Nano | 8 | nein |
| YOLOX-S (OpenCV Zoo) | 8 | nein |
| **NanoDet-Plus** | **0** | ja |

Eine andere Inferenz-Maschine gibt es in Chaquopy nicht: `onnxruntime` fehlt,
`tflite-runtime` und `torch` gibt es nur für `cp38` — und `cp310` ist wegen
OpenCV gesetzt.

Damit bleiben drei Wege:

1. **ONNX-Chirurgie.** Die acht Slices durch etwas ersetzen, das 4.5.1 liest
   (eine gruppierte Faltung mit Schrittweite 2 leistet dasselbe). Behält das
   Modell, das ausgiebig vermessen wurde; die Gleichwertigkeit lässt sich auf
   dem Entwicklungsrechner gegen das Original beweisen, statt sie zu hoffen.
2. **NanoDet-Plus.** Lädt sofort, 3,8 MB — aber die gesamte Trefferqualität
   müsste neu gemessen werden, und seine Nachbereitung ist schon einmal an
   OpenCV 5.0 gescheitert.
3. **Inferenz in Kotlin** (ONNX Runtime für Android). Saubere Naht: Kotlin
   rechnet das Netz, Python behält Ankergitter und NMS. Kostet eine Brücke und
   eine zweite Inferenz-Maschine neben dem Entwicklungsrechner.

**Gegangen wurde Weg 1, und er trägt.** `tools/modell_fuer_android.py` ersetzt
die acht Slices durch eine Faltung 3→12, Kern 2×2, Schrittweite 2, mit genau
einer Eins je Ausgangskanal. Das ist keine Näherung, sondern dieselbe Rechnung
in anderer Schreibweise — und das Werkzeug beweist es, statt es zu behaupten:
Es lässt beide Netze auf demselben Zufallsbild laufen und vergleicht.

```
9 Knoten ersetzt durch eine Faltung mit 12 Einsen.
Größter Unterschied in der Ausgabe: 0.000e+00
```

**Bitgleich.** Auf dem Gerät läuft das umgebaute Netz in **133,7 ms**.

### Der Versionstest gehört wiederholt

Entwickelt wird auf **OpenCV 5.0**, die App läuft auf **4.5.1**. Diese Schere
schließt sich nicht von allein. Bevor eine der beiden Versionen steigt:

```bash
python -m venv /tmp/cv45
/tmp/cv45/Scripts/python.exe -m pip install "opencv-python==4.5.5.64" "numpy<2" pydantic PyYAML pytest
```

```bash
/tmp/cv45/Scripts/python.exe -m pytest tests/unit -q --ignore=tests/unit/test_analyse_sperrt_wiedergabe.py --ignore=tests/unit/test_analysis_worker.py --ignore=tests/unit/test_auto_kalibrieren.py --ignore=tests/unit/test_bahnen_finden_gui.py --ignore=tests/unit/test_livestream_analysestart.py --ignore=tests/unit/test_nachkalibrieren.py --ignore=tests/unit/test_stream_reader.py --ignore=tests/unit/test_ziffern_in_der_anzeige.py
```

Die ausgeschlossenen Dateien brauchen PySide6 — genau die Schicht, die auf dem
Telefon nicht existiert.

**4.5.5 statt 4.5.1**, weil es für 4.5.1 keine Räder für Python 3.10 auf
Windows gibt. Dieser Ersatz ist *kein* vollwertiger Test: Genau zwischen diesen
beiden Fassungen liegt der Unterschied, an dem das Personenmodell scheitert
(siehe oben). Er prüft die Bildverarbeitung, nicht den ONNX-Importer. Was das
Modell angeht, gilt allein die Messung auf dem Gerät.

## pydantic — erledigt

**pydantic v2 läuft nicht auf Android** (Kern in Rust). Betroffen waren genau
zwei Dateien mit zusammen 24 Klassen. Sie benutzen jetzt
`src/kegel_cv/schema.py`, eine projekteigene Feldprüfung mit genau der
Oberfläche, die hier gebraucht wird. Begründung und verworfene Alternativen
stehen in `docs/ARCHITECTURE.md`, Abschnitt 11.

Der Umstieg lief ohne einen einzigen roten Test der bestehenden Suite.

### Damit importiert der Kern auf dem Gerät

```
Erkennungskern:
  ok       eigene Feldprüfung
  ok       Konfigurationsschema
  ok       Kalibrierungsmodell
  ok       Lampenerkennung
  ok       Personenmodell
  ok       Bahnverarbeitung
  ok       Pipeline
  ok       Konfiguration gelesen, Verdeckungsanteil 0.5
```

Zwei Dinge waren dafür nötig, beide im Hauptzweig und beide auch am Schreibtisch
richtig:

- `find_project_root` überging bisher keine unlesbaren Verzeichnisse. Auf
  Android ist `/config` ein gesperrtes Kernel-Verzeichnis — der Zugriff wirft
  `PermissionError`, statt schlicht „nein" zu sagen, und die Suche brach ab.
- `load_config` nimmt jetzt eine Projektwurzel entgegen. Auf dem Telefon gibt
  es kein Projektverzeichnis, sondern nur den privaten Ordner der Anwendung —
  und relativ dazu werden Modelldatei und Ausgaben aufgelöst.

### Beim Messen: Bildschirm an

Dieselbe Messung schwankt um den Faktor neun, je nachdem ob das Gerät wach ist:

| | Bildschirm an | gedrosselt |
|---|---|---|
| Grünlampe | 0,02 ms | 0,19 ms |
| Tafel entzerren | 1,91 ms | 4,38 ms |
| Bewegungsmaske | 1,08 ms | 7,62 ms |
| Personenmodell | 133,7 ms | 1174,6 ms |

Android drosselt Anwendungen im Hintergrund hart. Wer hier Zahlen erhebt, muss
den Bildschirm anlassen und die App im Vordergrund halten — sonst misst er die
Energieverwaltung.

## Bauen und aufspielen

Voraussetzungen: Android Studio (bringt JDK und SDK mit), ein Gerät mit
USB-Debugging.

```bash
cd android && ./gradlew :app:assembleDebug
```

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Das Personenmodell wird als Asset mitgeliefert und muss vor dem Bauen dort
liegen:

```bash
cp models/yolox_tiny.onnx android/app/src/main/assets/
```

### Xiaomi / HyperOS

`adb install` scheitert dort mit `INSTALL_FAILED_USER_RESTRICTED`. Was hilft,
ohne irgendeine Einstellung am Telefon zu ändern:

```bash
adb install -r --user 0 app/build/outputs/apk/debug/app-debug.apk
```

Alternativ in den Entwickleroptionen **„USB-Debugging
(Sicherheitseinstellungen)"** einschalten — das verlangt allerdings ein
angemeldetes Mi-Konto.

Eingaben lassen sich auf MIUI **nicht** über `adb shell input tap` einspielen
(`INJECT_EVENTS`-Berechtigung fehlt). Deshalb startet der Selbsttest von
selbst und schreibt sein Ergebnis zusätzlich ins Protokoll:

```bash
adb logcat -d -s KegelCV:I
```

Und Dateien unter `/sdcard` sieht die App seit Android 11 nicht mehr — was sie
lesen soll, gehört ins APK oder in ihr eigenes Verzeichnis.

## Warum diese Versionen

| | | warum nicht anders |
|---|---|---|
| Chaquopy | 17.0 | einzige Fassung mit Python 3.10–3.14 **und** AGP bis 9.2 |
| Python | 3.10 | OpenCV liegt bei Chaquopy nur für `cp38` und `cp310` vor |
| OpenCV | 4.5.1.48 | das Neueste in Chaquopys Paketquelle |
| ABI | nur `arm64-v8a` | jede weitere Architektur legt Python, numpy und OpenCV ein zweites Mal ins APK |
| minSdk | 24 | Mindestanforderung von Chaquopy 17 |
