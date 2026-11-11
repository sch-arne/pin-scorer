# Videoanalyse — gemessene Fakten

> **Alles in diesem Dokument wurde am realen Material gemessen, nicht geschätzt.**
> Vermutungen stehen in `OPEN_QUESTIONS.md`. Wer hier etwas ergänzt, nennt die
> Quelle: Video, Frame, Werkzeug.
>
> Stand: 2026-08-25

---

## 1. Das Material

11 Videos in `kegelVideos/`, zwei Aufnahme-Sessions:

| Session | Clips | Länge je Clip | Größe |
|---|---|---|---|
| `2024-09-03` | 9 | 13–30 s | 10–23 MB |
| `2026-08-22` | 2 | 5 s und lang | 3,7 MB und ~2,3 GB |

Einheitlich über alle Clips:

| Eigenschaft | Wert |
|---|---|
| Auflösung | **1920 × 1080** |
| Framerate | **25,00 fps** (konstant) |
| Codec | **h264** |

⇒ Echtzeit-Budget: **40 ms pro Frame**.

---

## 2. Aufnahmeort

**Kegelsportcenter die Anlage**, Halle des **Heimmannschaft**
(Wandaufschrift „…IN OSNABRÜCKER KEGLER e.V."). Anlagentyp: **FUNK**.
Klassisches deutsches Kegeln mit **9 Kegeln**.

Die Halle hat **5 Bahnen** (im Hintergrund nummeriert 1–5 sichtbar), das
Overlay zeigt jedoch nur **4 Anzeigetafeln** → siehe offene Frage Q1.

---

## 3. Bildaufbau

```
┌───────────────────────────────────────────────────────────────┐
│           ┌─────────────────────────────────────┐             │
│           │  OVERLAY (x≈430–1490, y≈35–300)     │             │
│           │  4 Anzeigetafeln in Nahaufnahme     │  ← ANALYSEQUELLE
│           │  [Tafel1][Tafel2][Tafel3][Tafel4]   │             │
│           └─────────────────────────────────────┘             │
│                                                               │
│         Weitwinkel-Totale der Halle, 5 Bahnen                 │
│         kleine Tafeln in der Ferne (unbrauchbar)              │  ← NICHT auswerten
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

Das Overlay ist ein eingeblendetes Bild (zweite Kamera oder digitaler Zoom).
Es ist die einzige brauchbare Quelle — die Tafeln im Hintergrund sind nur wenige
Dutzend Pixel groß.

### ⚠ Die Overlay-Position ist NICHT konstant

Gemessene x-Positionen der grünen Lampen:

| Session | Bahn 1 | Bahn 2 | Bahn 3 | Bahn 4 |
|---|---|---|---|---|
| 2024-09-03 | 538 | – | 1079 | 1378 |
| 2026-08-22 | 572 | 876 | 1105 | 1399 |

Auch die Tafelgrößen unterscheiden sich innerhalb einer Session
(Bahn 1: 157×124 px, Bahn 3: 160×142 px, Bahn 4: 156×105 px).

**Konsequenz:** Feste Koordinaten sind unbrauchbar. Kalibrierung erfolgt pro
Session und wird gespeichert. Die vier Tafeln sind zusätzlich unterschiedlich
perspektivisch verzerrt ⇒ Homographie **pro Bahn**, nicht global.

---

## 4. Die FUNK-Anzeigetafel

```
┌──────────────────────────────────────────┐
│ ▬▬▬▬▬▬▬ Laufschrift-Display ▬▬▬▬▬▬▬▬▬▬ │
│ ┌────────┐   ● rot   ● gelb  ┌────────┐ │  Statuslampen — KEINE Kegel
│ │ Name L │                   │ Name R │ │
│ └────────┘        ○ 1                   │
│              ○ 2      ○ 3               │  9 KEGELLAMPEN (Raute)
│         ○ 4      ○ 5      ○ 6           │  LEUCHTEND = GEFALLEN
│              ○ 7      ○ 8               │
│                   ○ 9                   │
│ ┌──────┐        ○ ● ○        ┌────────┐ │
│ │  00  │     GRÜNE LAMPE     │  0063  │ │  Summe A
│ └──────┘                     └────────┘ │
│ ┌─────────────────────────────────────┐ │
│ │   012        6         0063         │ │  Wurfnr · Kegel · Summe B
│ └─────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

### Verifizierte Ablesungen (Video 2026-08-22, Frame 42 und 90)

| Tafel | Leuchtende Lampen | Ziffer | Unteres Display | Lesart |
|---|---|---|---|---|
| 1 | 5 | 5 | `001 5 0005` | Wurf 1 → 5 Kegel → Summe 5 |
| 2 | 7 | 7 | `004 7 0023` | Wurf 4 → 7 Kegel → Summe 23 |
| 3 | 6 | 6 | `012 6 0063` | Wurf 12 → 6 Kegel → Summe 63 |
| 4 | 9 | 9 | `007 9 0028` | Wurf 7 → 9 Kegel → Summe 28 |

**Dreifach bestätigt:** Anzahl leuchtender Lampen == angezeigte Ziffer.
Bei Tafel 3, Frame 90 sind es konkret die Lampen 1, 3, 5, 6, 8, 9 (sechs Stück,
Anzeige „6"), während 2, 4, 7 matt bleiben.

⇒ **Leuchtend = Kegel gefallen.** Nicht umgekehrt.

Summe A (oben rechts) und Summe B (unten rechts) waren in allen untersuchten
Frames **identisch** → siehe Q3.

---

## 5. Grüne Lampe

- Position: mittig unter dem Kegelbild, zwischen den beiden Displays,
  flankiert von zwei kleinen hellen Punkten.
- Größe: ca. **6 × 8 px** im Originalframe.
- Detektion: HSV `H ∈ [40,90]`, `S > 80`, `V > 80`.

Gemessene Scores (Video 2026-08-22, 122 Frames, alle 4 Bahnen):

| Zustand | Score-Bereich |
|---|---|
| **AUS** | 17,3 – 24,0 |
| **AN** | 59,9 – 74,3 |

Beobachteter Zustandswechsel: **Bahn 2 springt bei Frame ~78 von ~22 auf ~73**
(GREEN ON). Die anderen drei Bahnen bleiben in diesem Zeitraum unverändert —
ein direkter Beleg für die Unabhängigkeit der Bahnen.

⚠ **Die Baseline ist nicht null** (das beige Gehäuse hat Grünanteil). Ein
absoluter Schwellwert nahe 0 würde also immer „AN" melden. Daraus folgt die
Hysterese mit `on_threshold=45` / `off_threshold=35`.

---

## 6. ROI-Positionen (normierte Tafelkoordinaten)

**Quelle: eine echte Nutzerkalibrierung**, gemittelt über alle vier Bahnen
(`data/calibrations/kalibrierung_2026-08-24_2258.json`). Die Streuung zwischen
den Bahnen beträgt nur **0,004–0,012** — rund 1–2 px. Bezugsrahmen ist das beige
Tafelgehäuse, also die Ecken, die der Nutzer anklickt.

### Kegellampen — streng regelmäßige Raute

| Zeile | y | x-Positionen |
|---|---|---|
| 1 | 0,342 | 0,498 |
| 2 | 0,419 | 0,335 · 0,661 |
| 3 | 0,497 | 0,175 · 0,498 · 0,821 |
| 4 | 0,573 | 0,335 · 0,660 |
| 5 | 0,651 | 0,498 |

Der Zeilenabstand ist **konstant 0,0775**, die x-Positionen liegen symmetrisch um
die Mitte. Lampengröße ca. 0,080 × 0,075.

> **Korrektur einer früheren Schätzung:** Eine erste, selbst geschätzte Variante
> lag systematisch zu hoch (erste Zeile bei 0,283 statt 0,342) und war zu weit
> gespreizt (Zeilenabstand 0,091 statt 0,0775). Die Abweichung fiel erst im
> Vergleich mit der Nutzerkalibrierung auf.

### Displays

| ROI | Mitte (x, y) | Größe (w, h) |
|---|---|---|
| `green_lamp` | 0,504 · 0,771 | 0,065 × 0,052 |
| `left_display` (Fehlwürfe) | 0,182 · 0,698 | 0,260 × 0,130 |
| `total_a` | 0,780 · 0,700 | 0,240 × 0,130 |
| `throw_number` | 0,232 · 0,888 | 0,240 × 0,130 |
| `pin_count` | 0,450 · 0,888 | 0,110 × 0,130 |
| `total_b` | 0,715 · 0,888 | 0,330 × 0,130 |

**Die Feldhöhe von 0,130 ist kein Zufallswert:** Die Ziffern selbst sind
normiert **0,099 hoch**. Eine frühere Größe von 0,093 war damit *kleiner als die
Ziffer* — die oberen und unteren Segmente fielen heraus. 0,130 entspricht der
Ziffernhöhe plus rund 30 % Rand; der Rand fängt Klickungenauigkeit und den
Versatz zwischen den vier perspektivisch verschiedenen Tafeln ab.

---

## 7. Automatische Tafelerkennung — nur ein Hilfsmittel

`tools/verify_rois.py` kann Tafeln über ihr helles, warmes Gehäuse finden
(HSV `H∈[10,40]`, `S∈[25,120]`, `V>120`).

**Ergebnis der Prüfung: nicht verlässlich genug für den Produktivbetrieb.**
Bei Bahn 3 lag die erkannte Box gut, bei **Bahn 1 deutlich daneben** — das untere
Zeilendisplay fiel heraus, wodurch sämtliche ROIs verrutschten und die grüne
Lampe außerhalb der Tafel lag.

⇒ Das bestätigt die Architekturentscheidung: **Der Nutzer kalibriert per Klick.**
Die automatische Erkennung bleibt ein Analysewerkzeug für die Entwicklung.

---

## 8. Die 7-Segment-Ziffern — gemessen

### Größe und Auflösung

| Feld | ROI im Frame | je Ziffer |
|---|---|---|
| `throw_number` (3-stellig) | 39 × 22 px | ~13 × 18 px |
| `pin_count` (1-stellig) | 19 × 22 px | ~13 × 18 px |
| `total_b` (4-stellig) | 54 × 22 px | ~13 × 18 px |

**Die Segmente sind nur 2–3 px dick.** Das ist die harte Grenze dieses Materials.

Die Ziffernbreite verhält sich konstant zur Höhe: gemessen **0,53–0,71**,
Schwerpunkt **0,65**. Das lässt sich nutzen, um Ziffernzellen aufzureihen, wenn
sich keine Lücken finden.

### Überstrahlung — der entscheidende Befund

Erwartet wurde eine sattrote Anzeige. Gemessen (Bahn 3, `total_b`, Frame 90):

| Bereich | B | G | R | R−G |
|---|---|---|---|---|
| Gehäuse (beige) | 153 | 163 | 189 | +26 |
| Display-Hintergrund | 20 | 22 | 24 | +2 |
| **Segment, hellster Punkt** | 178 | 141 | **255** | **+114** |

Die Segmentmitten sind **nahezu weiß**; nur die Ränder bleiben gesättigt rot.
Eine Maske über die Rot-Dominanz (`R−G > 45`) erfasst deshalb nur die Umrisse und
liefert **hohle** Ziffern, die kein Segmentmuster ergeben.

Was trägt, ist die Trennung **hell gegen dunkel** per Otsu auf dem Rotkanal:
Das Display ist schwarz (24), die Segmente sind hell (bis 255).

### Trefferquoten der Verfahren

Geprüft gegen 12 Felder mit bekanntem Sollwert (4 Bahnen × 3 Felder, Frame 90):

| Verfahren | Treffer |
|---|---|
| Segment-Dekodierung, Rot-Maske | 0/12 |
| Segment-Dekodierung, Otsu-Maske | 5/12 |
| Template Matching (synthetische Vorlagen) | 6/11 |
| Template Matching + zeitliche Aggregation | 7/12 |

**Höhere Auflösung hilft nicht.** Identisches Ergebnis bei entzerrten Tafeln in
440×530, 880×1060 und 1320×1590 — Interpolation fügt keine Information hinzu.

**Die verbleibenden Fehler sind systematisch, nicht zufällig.** Eine Bahn las in
25 von 25 Frames „4" statt „9". Zeitliche Aggregation hilft gegen Flackern, aber
nicht gegen einen konstant falsch messenden Detektor.

### Einzeln eingerahmte Ziffern — der Durchbruch

Alle automatischen Verfahren scheiterten an der **Positionierung** der
Ziffernzellen. Werden die Stellen dagegen **einzeln kalibriert** (je zwei Klicks
in der GUI), ändert sich das Bild deutlich.

Gemessen an vier Frames mit bekanntem Sollwert:

| Feld | Feld automatisch geteilt | einzeln eingerahmt |
|---|---|---|
| Wurfnummer | 2/4 | **4/4** |
| Kegelanzahl | 2/4 | 2/4 |
| Summe B | 3/4 | 2/4 |
| gesamt | 7/12 (58 %) | **8/12 (67 %)** |

Im vollständigen Analyselauf (8000 Frames, 38 Würfe) zählt vor allem, wie oft
eine **falsch** gelesene Ziffer der Lampenzählung widerspricht:

| Bahn | Ziffern eingerahmt | Würfe | Ziffer gelesen | korrekt | **falsch** |
|---|---|---|---|---|---|
| 2 | **ja** | 8 | 4 | 3 | **1** (13 %) |
| 3 | nein | 10 | 10 | 2 | 8 (80 %) |
| 4 | nein | 12 | 11 | 9 | 2 (17 %) |
| 5 | nein | 8 | 8 | 1 | 7 (88 %) |

Die eingerahmte Bahn liest seltener — meldet dafür aber kaum noch Falsches. Das
ist die gewünschte Richtung: Eine nicht gelesene Ziffer lässt den Wurf `VALID`
(die Lampen zählen), eine falsch gelesene erzeugt `ERROR`.

**Mit allen vier Bahnen eingerahmt** (12 000 Frames, 8 Minuten Video, 51 Würfe):

| Bahn | Würfe | Ziffer gelesen | korrekt | falsch | Summenkette |
|---|---|---|---|---|---|
| 2 | 16 | 7 | 5 | 2 | stimmig |
| 3 | 16 | 10 | 9 | 1 | stimmig |
| 4 | 8 | 5 | 5 | 0 | stimmig |
| 5 | 11 | 3 | 1 | 2 | stimmig |

**80 % der gelesenen Ziffern korrekt, nur 5 Falschlesungen bei 51 Würfen** — und
alle vier Summenketten stimmig. Zuvor lasen die nicht eingerahmten Bahnen 3 und 5
zu 80–88 % falsch.

### Die Ziffern stehen schief — und zwar von Hause aus

Nutzerbeobachtung, nachgemessen an 757 Einzelziffern über alle vier Tafeln,
**im entzerrten Tafelbild** (die Perspektive ist dort bereits herausgerechnet):

| Tafel | Bahn | Proben | Neigung |
|---|---|---|---|
| 1 (links) | 2 | 132 | −2,0° |
| 2 | 3 | 210 | −2,3° |
| 3 | 4 | 210 | −2,4° |
| 4 (rechts) | 5 | 205 | −2,9° |

**Spanne zwischen den Tafeln: 0,9°.** Käme die Neigung aus der Perspektive,
müssten die äußeren Tafeln deutlich abweichen — und die Homographie hätte sie
ohnehin beseitigt. Dass sie *nach* der Entzerrung auf allen Tafeln nahezu gleich
bleibt, belegt: **Die Ziffern der Anlage sind leicht kursiv.**

Praktische Folge: **keine.** Bei 18 px Ziffernhöhe entspricht −2,4° einem Versatz
von unter einem Pixel. Eine Scherungskorrektur verschlechtert das Ergebnis sogar,
weil die zusätzliche Interpolation bei 11×18 px mehr kostet, als der Versatz
ausmacht:

| Korrektur | Treffer |
|---|---|
| keine | **9/13** |
| Scherung −2,4° | 6/13 |
| Scherung −4,6° | 5/13 |

### Drei Fallstricke beim stellenweisen Lesen

1. **Messfläche für Segment `g` zu breit.** Sie erfasste die senkrechten
   Segmente links und rechts mit; jede „0" wurde zur „8", Trefferquote 17 %.
   Waagerechte Segmente nur im mittleren Drittel messen.
2. **„Größte Lücke" als Schwelle trägt nicht.** Bei einer „0" sind sechs
   Segmente aktiv, die größte Lücke liegt dann *innerhalb* der aktiven.
   Gemessen: `g=0,10 | a=0,26 f=0,27 | e=0,49 …` — die Schwelle landete bei 0,38
   statt 0,18. Verlässlich ist eine Schwelle **relativ zum hellsten Segment**.
3. **Otsu normalisiert.** In einem fast schwarzen Ausschnitt findet es trotzdem
   eine Schwelle und macht aus Rauschen eine Ziffer — bevorzugt eine „8".
   Deshalb vorab die absolute Helligkeit prüfen (gemessen: klar lesbar 255,
   verblassend 196–212, fast erloschen 76–96).

### Bestätigung des Flackerns (Q4)

`2026-08-22 09-15-50.mp4`, Bahn 2, Feld `pin_count`:
In **Frame 42** zeigt es klar „7", in **Frame 90** ist es **unbeleuchtet**.
Die Anzeige ist nicht in jedem Frame lesbar — genau das Verhalten aus Auftrag §8.
Der Detektor meldet dort korrekt „nicht lesbar" statt zu raten.

---

## 9. Werkzeuge zur Reproduktion

```bash
.venv/Scripts/python.exe tools/verify_rois.py --frame 90
```

```bash
.venv/Scripts/python.exe tools/verify_rois.py --calibration data/calibrations/meine.json
```

Ergebnisse landen in `debug/roi_check/`.

---

## Räumen — warum die Lampen nicht das Wurfergebnis sind

**Quelle: Nutzer, 2026-08-25.** Fachwissen, das aus dem Videomaterial allein
nicht ableitbar war.

Beim Kegeln gibt es die Bedingung **„Räumen"**: Die nach einem Wurf noch
stehenden Kegel müssen abgeräumt werden. Erkennbar am Zustand beim Einschalten
der grünen Lampe:

| Beim Grün-AN | Bedeutung |
|---|---|
| Kegellampen **aus** | „in die Vollen" — alle neun Kegel stehen |
| Kegellampen **teilweise an** | **Räumen** — die leuchtenden Kegel liegen bereits |

Die leuchtenden Lampen zeigen den **Zustand des Bildes**, nicht das Ergebnis des
laufenden Wurfs. Beim Räumen müssen die bereits liegenden Kegel nicht mehr
getroffen werden; sie zählen nicht zu diesem Wurf.

**Folge für die Auswertung:** Das Wurfergebnis ist die **Differenz**

```
gefallene Kegel = Lampen bei GREEN_OFF  −  Lampen bei GREEN_ON
```

Umgesetzt in `analysis/lane_processor.py::_measure_baseline` und
`analysis/throw_analyzer.py`. Konfiguriert über `sampling.baseline_offsets`.

### Gemessen

Über 12 000 Frames (8 Minuten, 4 Bahnen, 70 Würfe) war die Grundlinie bei jeder
Bahn **genau einmal** ungleich null — beim 17. Wurf, mit 7, 6, 7 bzw. 8 bereits
liegenden Kegeln. Das passt zum Rundenwechsel nach 15 Würfen.

Genau diese vier Würfe waren zuvor als Widerspruch aufgefallen: Die Lampen
meldeten 9, die Tafel 1, 2, 3 bzw. 4. Beide hatten recht — sie maßen
Verschiedenes.

### Was daraus folgt

Ein Widerspruch zwischen zwei Quellen bedeutet nicht, dass eine falsch misst. Er
kann bedeuten, dass sie **verschiedene Dinge messen**. Vor der Fehlersuche steht
die Frage, was die Quelle überhaupt aussagt.

### Erledigt: die vier Fälle „Ziffer 9 bei dunklen Lampen"

Bei vier Würfen zeigte die Tafel `9`, während alle Lampen dunkel waren. Das sah
nach einem eigenen Phänomen aus, war aber dasselbe Blinken (BUG-007): Der
Messzeitpunkt fiel jedes Mal in eine Dunkelphase von 13–15 Frames. Belegt und
abgeschlossen in `OPEN_QUESTIONS.md` (Q8).


---

## Status eines Wurfs: was ihn entwerten darf — und was nicht

**Auf Hinweis des Nutzers geändert (2026-08-25):** „nur weil die Wurfnummer
nicht richtig erkannt wird, soll bitte das Ergebnis noch nicht direkt als ERROR
ausgegeben werden."

Vorher zählte jede fehlgeschlagene Plausibilitätsprüfung gleich viel; ab zwei
Verstößen galt ein Wurf als `ERROR`. Zwei davon betrafen aber gar nicht das
Ergebnis:

| Prüfung | betrifft |
|---|---|
| Lampen == angezeigte Kegelzahl | **das Ergebnis** |
| Summe alt + Kegel == Summe neu | **das Ergebnis** |
| Wurfnummer steigt / plausibel / lückenlos | die Buchführung |

Die Wurfnummer sagt nichts darüber, wie viele Kegel gefallen sind. Sie ist
dreistellig, flackert entsprechend häufig, und ein sauber gemessener Wurf wurde
allein dadurch entwertet.

Seitdem trägt `PlausibilityCheck` das Feld `affects_result`. Nur ergebnis-
relevante Verstöße führen zu `ERROR`; Buchführungsfehler bleiben in der
Beweiskette sichtbar und kosten 0,05 statt 0,15 Confidence.

**Die dahinterliegende Regel:** Ein Status beschreibt die Verlässlichkeit einer
bestimmten Aussage — hier: wie viele Kegel gefallen sind. Prüfungen, die eine
*andere* Aussage betreffen, dürfen ihn nicht senken. Sonst sammelt sich
Misstrauen aus unbeteiligten Quellen an.


---

## Spielstruktur: 30 Würfe, dann setzt die Tafel zurück

**Vom Nutzer angekündigt, über 52 Minuten bestätigt.** Der Hinweis lautete: „die
Ergebniszeile unten wird nach (ich glaube 30 Wurf) zurückgesetzt. DAS ist ein
Zeichen dafür, dass hier zuvor ein Endergebnis stand."

Gemessen über das ganze Training, drei Bahnen unabhängig:

```
Bahn 2:  Wurf 30 (189 -> 0)   Wurf 60 (185 -> 0)   Wurf 92 (182 -> 5)
Bahn 3:  Wurf 30 (199 -> 0)                        Wurf 90 (216 -> 0)
Bahn 4:  Wurf 29 (188 -> 0)   Wurf 59 (191 -> 0)   Wurf 89 (200 -> 0)
```

Ein **Spiel** umfasst 30 Würfe — zwei 15er-Runden. Danach springt die Tafel auf
Wurf 1 und Summe 0 zurück. **Der letzte Stand vor der Rücksetzung ist das
Spielergebnis.**

### Warum das keine Lesefehler sind

Zwei Bahnen sprangen im Abstand von zwei Sekunden gemeinsam von 33 auf 4:

```
16:02:23  Bahn 3: Wurfnummer 4 liegt nicht über der letzten (33)
16:02:25  Bahn 5: Wurfnummer 4 liegt nicht über der letzten (33)
```

Zwei unabhängige OCR-Fehler treffen nicht gleichzeitig denselben Wert.

### Abgrenzung zur Regel aus BUG-008

BUG-008 verlangt, eine zurückfallende Wurfnummer **nicht** zu glauben, sondern
fortzuzählen — sonst löscht ein Lesefehler die restliche Serie. Beim Spielwechsel
ist der Rückfall aber echt. Unterschieden wird an der **Höhe**:

| Rückfall | Deutung |
|---|---|
| um wenige Stellen (12 → 11) | Lesefehler, wird fortgezählt |
| von über 10 auf unter 5 (33 → 4) | Spielwechsel, Zählung beginnt neu |

Konfiguriert über `scoring.game_reset_after` und `scoring.game_reset_below`.

### Was ohne diese Erkennung falsch war

Die interne Summe lief über die Rücksetzung hinweg weiter und driftete von der
Tafel ab:

```
Wurf 28   Tafel 188   intern 180
Wurf 29   Tafel   0   intern 189     <- Rücksetzung
Wurf 30   Tafel   7   intern 196
```

Ab dem 30. Wurf war die Gegenprobe gegen die Summenanzeige damit wertlos — also
für rund 80 % des Trainings.


---

## Die Lampenhelligkeit driftet über die Aufnahme

**Gemessen über 52 Minuten** (siehe BUG-011). Die Helligkeit der
*ausgeschalteten* Kegellampen steigt stetig:

```
Minute:              1     7    12    17    23    28    33    39    44    49
AUS-Median:        151   160   157   162   167   166   178   176   170   185
über Schwelle 195: 0,4%  0,2%  0,4%  1,4%  1,6%  2,6%  8,4%  5,8%  5,1% 23,9%
```

Am Ende liegt fast ein Viertel aller AUS-Messungen über der festen Schwelle.

**Woher die Drift kommt** — nur die Tafeln werden heller:

```
Minute:            1     7    12    17    23    28    33    39    44    49
Tafeln:         94,9  98,8 100,9 100,6 101,5 102,7 104,1 104,9 106,1 109,4
restliches Bild: 100,2 105,6 104,4 106,3 103,3 102,4 102,7 102,7 102,7 100,8
Bahnbereich:     74,8  83,0  83,3  82,5  81,9  81,0  79,2  78,4  77,1  74,7
```

Das übrige Bild bleibt flach, der Bahnbereich wird sogar dunkler. Damit sind
Kamera-Nachregelung und Hallenbeleuchtung ausgeschlossen — die Anlage selbst
wird heller. (Eine erste Vermutung, es werde draußen hell, war falsch: Die
Aufnahme entstand abends gegen 21:25. Hinweis des Nutzers.)

**Folge:** Ein globaler Helligkeitsausgleich über das Bild würde nichts nützen.
Der Bezugspunkt muss von der Lampe selbst kommen — umgesetzt als mitlaufendes
AUS-Niveau je Lampe (`detection.lamps.adaptive_baseline`).


---

## Die grüne Lampe driftet ebenfalls — und dort kostet es den Messzeitpunkt

Gemessen über 52 Minuten je Bahn (Score der grünen Lampe):

```
                AUS 50%  AUS 95% |  AN 5%  AN 50%   Abstand
Min 1-3    B2      28,3     38,4 |   71,7    75,8    +33,3
Min 47-49  B2      36,4     43,4 |   69,7    74,7    +26,3
Min 47-49  B4      36,1     41,7 |   56,5    63,0    +14,8
```

Beide Verteilungen wandern aufeinander zu, überlappen aber nie. Die feste
AUS-Schwelle (35) liegt am Ende **mitten in der AUS-Verteilung** — der Anteil
der Messungen im Graubereich steigt von 4,6 % auf 16,5 %.

**Folge:** `GREEN_OFF` löste erst aus, wenn ein zufälliger Ausreißer die
Schwelle unterschritt — gemessen bis zu 180 Frames zu spät. Bis dahin hatte die
Anlage die Kegellampen bereits zurückgesetzt:

```
Frame 64075   grün geht tatsächlich aus, Kegellampen zeigen 7
Frame 64195   die Anlage stellt neu auf, Kegellampen gehen auf 0
Frame 64255   GREEN_OFF löst erst JETZT aus  -> Ergebnis wird als 0 gelesen
Frame 64282   grün wieder an
```

Diese Fälle sahen wie „die Lampen zählen 0" aus, obwohl mit den Lampen nichts
war. **Ein falscher Messwert verfälscht eine Zahl; ein falscher Zeitpunkt misst
etwas ganz anderes.**

Gelöst über `detection.green.adaptive_thresholds`: Die Schwellen liegen anteilig
zwischen den beiden beobachteten Niveaus statt auf festen Werten.

### Nebenbefund

Mit der korrigierten Flankenerkennung wurden **sechs zusätzliche Grünzyklen**
sichtbar (486 statt 480) — Würfe, die zuvor mit dem Nachbarzyklus verschmolzen.


---

## Uneindeutige Ziffern von den Lampen auflösen lassen

**Vorschlag des Nutzers (2026-08-25):** „wenn er eine 4 oder 9 als Text erkennt,
und oben 9 Lampen leuchten => 9 … Wir werden es ja dann merken, wenn die Summe
steigt."

Der Gedanke: Statt einzelne Messwerte immer weiter zu verfeinern, lässt man die
**Quellen einander auflösen** — und behält die Summenanzeige als unabhängige
Kontrolle.

### Der Anlass, gemessen

Bahn 5, Frame 22269. Die Anzeigetafel zeigte `005 4 0029` — also eine 4:

```
fills = [a 0,333  b 0,571  c 0,517  d 0,000  e 0,024  f 0,333  g 0,878]
Schwelle 0,3072   ->  aktiv 'abcfg' = 9
```

Segment `a` und `f` liegen beide knapp über der Schwelle. Seit BUG-009 trennt
die 4 (`bcfg`) von der 9 (`abcfg`) ein einziges Segment. Die Messung **kann**
aus sich heraus nicht entscheiden.

### Wie es umgesetzt ist — und warum die Prüfung ehrlich bleibt

Der Leser liefert bei Uneindeutigkeit die **Kandidatenmenge** statt nur `?`
(`digit_reader.segment_candidates`). Der Analyzer prüft dann:

| Fall | Ergebnis |
|---|---|
| Lampenzahl steht unter den Kandidaten | stimmig, aufgelöst — in der Beweiskette vermerkt |
| Lampenzahl steht **nicht** darunter | echter Widerspruch, bleibt sichtbar |

Entscheidend ist die **Richtung**: Die Lampen dürfen zwischen den Kandidaten
*wählen*, aber keinen neuen Wert *setzen*. Melden sie 7, während {4, 9} zur Wahl
steht, bleibt es ein Widerspruch. Die Gegenprobe ist also weiterhin in der Lage,
die Lampen zu widerlegen — genau das unterscheidet sie von einer Scheinprüfung.

Vollständig unabhängig bleibt ohnehin die **Summenanzeige**: Sie stammt aus einem
anderen Ziffernfeld und muss um genau die gezählte Kegelzahl steigen.

### Warum das dem Nachjustieren von Schwellen vorzuziehen ist

Die Alternative wäre gewesen, die Segmentflächen oder die Schwelle so lange zu
verschieben, bis dieser eine Fall stimmt. Das hätte an einer Bahn geholfen und
an einer anderen geschadet — die Ziffern stehen je nach Blickwinkel
unterschiedlich schräg. Die Auflösung über eine zweite Quelle ist unabhängig von
der Geometrie und trägt damit auch für Bahnen und Videos, die noch nicht
vermessen sind.


---

## Der zeitliche Ablauf eines Wurfs

**Vom Nutzer erklärt (2026-08-25)** — die Grundlage dafür, wann welcher Wert
gültig ist:

```
grün AN ─────────────────────────────────────► grün AUS
   │                                              │
   │  Kegel fallen in dieser Zeit                 │  jetzt kann kein Kegel
   │  Wurfzähler springt hoch                     │  mehr fallen: die Lampen
   │  └── ab da genau 4 Sekunden ────────────────►│  zeigen das Ergebnis
```

Drei Folgerungen für die Auswertung:

1. **Die Lampen leuchten bereits, während grün an ist.** Das ist normal und kein
   Fehler — die Kegel fallen ja in dieser Phase.
2. **Gemessen wird bei Grün-AUS**, denn erst dann steht das Ergebnis fest.
3. **Die Räum-Grundlinie gehört kurz NACH Grün-AN**, nicht davor. Vor Grün-AN
   steht noch das Ergebnis des vorherigen Wurfs auf der Tafel.

### Was Punkt 3 gekostet hat

Die Grundlinie wurde mit den Offsets `[0, -4, -8, -12, -16]` **rückwärts**
gemessen — also im Fenster des vorherigen Wurfs. Sie enthielt dadurch dessen
Kegel, und die Differenz ergab null:

```
Bahn 2, Frame 44352:
   Grundlinie (bei Grün-AN):  9 Kegel [1..9]
   Endstand:                  9 Kegel [1..9]
   Differenz = 0  ->  "Räumen: 9 Kegel lagen bereits vor dem Wurf"
```

Alle neun Lampen wurden dabei mit Helligkeit 254 klar als AN erkannt — die
Messung war einwandfrei, nur der **Bezugszeitpunkt** falsch. Betroffen waren acht
Würfe, und 92 Würfe wurden fälschlich als Räumen eingestuft.

Seitdem gilt `baseline_offsets: [0, 6, 12, 18, 25]` — Frames **nach** Grün-AN,
gesammelt während des Wurfs. 25 Frames sind eine Sekunde, deutlich vor dem
Aufschlag des Balls.

### Blinken heißt „alle Neune"

Ebenfalls vom Nutzer: Das Blinken der Lampen ist der **Spezialeffekt für einen
Wurf mit neun Kegeln**, kein allgemeines Verhalten. Die Abhilfe aus BUG-007
(über das Fenster aggregieren, je Lampe das Maximum) bleibt davon unberührt —
sie war richtig, die Deutung war nur zu weit gefasst.


---

## Der Livestream ist dieselbe Produktion

**Vom Nutzer belegt (2026-08-25):** Die vorhandenen Aufnahmen sind Mitschnitte
eines Livestreams auf sporteurope.tv. Overlay-Panel, Tafelmodell und Bildgröße
sind identisch.

```
Aufnahmen:      Panel bei x 493..1481, y  50..215
Livestream:     Panel bei x 445..1465, y   5..310
```

Die leichte Verschiebung ist bekannt und der Grund, weshalb pro Übertragung
kalibriert wird.

### Randbedingungen, vom Nutzer geklärt

| Frage | Antwort |
|---|---|
| Bleibt das Overlay eingeblendet? | **Immer.** Keine Werbeunterbrechung, kein Kameraschnitt. |
| Verschiebt es sich während einer Übertragung? | Nein, innerhalb einer Übertragung stabil. |
| Rückspringen im Stream? | Technisch möglich, aber **nicht betrachtet**. |

Damit entfallen die schwierigen Fälle: Es genügt **eine** Kalibrierung zu Beginn,
und die Analyse muss nicht erkennen, ob gerade etwas anderes im Bild ist.

### Ein Irrtum meinerseits, und was daraus folgt

Aus dem **Vorschaubild** der Seite hatte ich geschlossen, die Übertragung zeige
nur einen Weitwinkel auf Tafeln ohne Kegelraute — und daraus, dass das ganze
Verfahren dort nicht trägt. Das war falsch: Das Vorschaubild ist ein Werbestill,
kein Ausschnitt der Übertragung. Ein Screenshot des Nutzers aus dem laufenden
Stream zeigt das Overlay mit allen vier FUNK-Tafeln samt Kegelraute.

Derselbe Fehler wie in `messen-vor-bauen` beschrieben: **aus einem einzelnen
Bild eine Eigenschaft der Quelle geschlossen.**

### Was der Stream zusätzlich hergibt

Links und rechts stehen Mannschaftstabellen mit **Spielernamen**, und über jeder
Tafel steht, wer gerade auf welcher Bahn spielt:

```
Bahn 2: KV Gelsenkirchen 2 / Erich Wolf
Bahn 5: Heimmannschaft    / Spieler A
```

Diese Felder werden **heute von Hand gepflegt** und nur alle 15 Würfe
nachgetragen — sie automatisch zu füllen ist laut Nutzer der eigentliche Zweck
dieses Werkzeugs. Die Namen stehen in normaler Schrift statt als 7-Segment und
dürften für OCR leichter sein als die Ziffern. Noch nicht umgesetzt.


---

## Negatives Ergebnis: das Maximum-Fenster bringt nichts

**Gemessen 2026-08-26** über alle 486 Wurffenster des 52-Minuten-Videos.

Die Überlegung war: Während eines Wurfs können Lampen nur dazukommen — Kegel
stehen nicht wieder auf. Blinken zieht die Zahl kurz nach unten, das Aufstellen
auf null, aber nie nach oben. Also müsste das **Maximum über das ganze Fenster
von Grün-AN bis zum nächsten Grün-AN** das Ergebnis sein, unabhängig davon, wann
genau `GREEN_OFF` erkannt wird. Damit verschwände der Messzeitpunkt als
Fehlerquelle.

```
A  ab GREEN_OFF (heutiges Verhalten)     380 von 454
B  ab GREEN_ON  (Vorschlag)              380 von 454

A und B unterscheiden sich bei 0 von 486 Fenstern.
```

**Kein einziger Unterschied.** Der Grund ist einleuchtend, sobald man ihn sieht:
Die Lampen halten ihr Ergebnis noch lange nach Grün-AUS — das Aufstellen kommt
erst viel später. Was während der Grünphase gefallen ist, leuchtet bei Grün-AUS
weiterhin. Das bestehende Fenster erfasst also bereits alles.

Der ursprünglich beobachtete Fehler (`GREEN_OFF` bis zu 180 Frames zu spät) war
real, ist aber durch die mitlaufenden Schwellen der grünen Lampe behoben —
deshalb misst sich heute kein Unterschied mehr. **Nicht umgebaut.**

### Ein Fehler in der Messung selbst, der fast zur falschen Deutung geführt hätte

Die 83,7 % sehen alarmierend aus, sind aber ein Artefakt: Als Bezug diente die
Kegelziffer aus **einem einzelnen Frame**, ohne die zeitliche Aggregation der
Pipeline. Die Abweichungen zeigen es deutlich:

```
Differenz Messung minus Ziffer:   +6: 56x   (von 74 Abweichungen)
Beispiele: gemessen 8 / Ziffer 2      gemessen 9 / Ziffer 3
```

8→2 und 9→3 sind beide genau minus 6 — der bekannte Ziffernfehler, konzentriert
auf Bahn 2 und 5. Nicht die Lampen lagen daneben, sondern meine Referenz. In der
Pipeline liegt die Übereinstimmung bei 98,6 %.

**Lehre:** Eine Messung ist nur so gut wie die Wahrheit, gegen die sie misst.
Wer als Referenz eine Größe wählt, die selbst fehleranfällig ist, misst am Ende
diese Größe.

---

## Die grüne Lampe: Perzentile taugen nicht als Wolkentrennung (2026-08-30)

Anlass war ein Phantomwurf auf Bahn 5 bei Frame 40903, der die gesamte folgende
Wurfnummernkette um eins verschob (Spieler A: 16 von 30 Würfen richtig
zugeordnet statt 30 von 30).

### Der Befund im Bild

Ausgegeben mit `tools/export_roi_frames.py`, mit allen kalibrierten Rahmen:
**Die grüne Lampe leuchtet bei F40903 sichtbar.** Sie ging nie aus.

### Der Befund in der Grünspur

```
Frame   Score    P20    P90  Spanne  AUS-Schwelle  Zustand
40894    56,7   37,6   70,0    32,4          50,5  ON
40898    55,6   39,8   70,0    30,2          51,9  UNKNOWN
40903    47,8   40,0   70,0    30,0          52,0  OFF
40906    47,8   41,8   70,0    28,2  fest: 35,0    ON
```

Derselbe Score (47,8) ist einmal AUS und drei Frames später AN. Zwei Ursachen
greifen ineinander:

1. Die Bahn lag **71 % des Fensters auf AN**. Damit ist das 20. Perzentil kein
   AUS-Niveau mehr, sondern der untere Rand der AN-Wolke. Die daraus
   errechnete AUS-Schwelle (52,0) liegt **innerhalb** der AN-Wolke.
2. Die Spanne P90−P20 wackelte um die Sperre `adaptive_min_span` (30,0). Fällt
   sie darunter, gelten schlagartig die festen Schwellen (45/35) — die Schwelle
   springt um 17 Punkte.

Perzentile setzen voraus, dass beide Zustände im Fenster im erwarteten
Verhältnis vorkommen. Diese Voraussetzung ist am Material nicht erfüllt.

### Das Histogramm desselben Fensters

```
18-20   26 | 20-22   24 | 22-24   56 | 24-26  127     <- AUS-Wolke
26-28    6 | 28-30    1 | 30-32   11 | 32-34   32
34-36    6 | 36-38    5 | 38-40    1 | 40-42    8     <- Tal
42-44   45 | 44-46    5 | 46-48   54 | 48-50    9
50-52   15 | 52-54   70 | 54-56  164 | 56-58  176     <- AN-Wolke
58-60  118 | 60-62  120 | ... | 76-78    5
```

Zweigipflig und eindeutig. Geglättet über drei Bins liegt das tiefste Tal bei
**37**. Damit ist 47,8 durchgehend AN, und der Phantomwurf entsteht nicht.

### Gegenrechnung über die volle Grünspur

`tools/fit_green_histogram.py` spielt die aufgezeichnete Spur (297 715 Frames
je Bahn) durch das Verfahren:

```
Fenster   Bahn 2   Bahn 3   Bahn 4   Bahn 5     GREEN_OFF-Ereignisse
   1500      426      422      431      418
   7500      425      420      425      431
  22500      425      421      425      430
  45000      426      420      425      426
im Lauf      431      424      425      417
```

Höchstens 13 Ereignisse Unterschied über eine Spanne von 1 zu 30 in der
Fensterlänge — das Verfahren hängt nicht an dieser Zahl. Gewählt wurden 22500
Frames (15 min) nach Vorgabe des Nutzers.

Der Anteil zweigipfliger Fenster liegt auf Bahn 2–4 bei 96–97 %, auf Bahn 5 nur
bei 83 %. Das ist kein Mangel, sondern die richtige Antwort: Bahn 5 hat das
schwächste Signal, und dort greift die Sperre häufiger.

### Ergebnis am Material

Lauf F28000–56000, gleiche Kalibrierung, nur der Detektor geändert:

| | vorher | nachher |
|---|---|---|
| Spieler A, Bahn 5 | 16/30 | **30/30** |
| Spieler B, Bahn 3 | 30/30 | **30/30** |

Kein Wurf erfunden, keiner verloren.

---

## Ziffernerkennung: Wie gut ist sie wirklich? (2026-08-30)

Beobachtung des Nutzers am Bildbeleg: Die Ziffern sind in der Rotmaske
eindeutig zu lesen, die Erkennung liefert trotzdem `?`.

### Wo der Weg abbricht (4320 beleuchtete Zellen)

```
gueltiges Sieben-Segment-Muster gelesen            58,0 %
kein gueltiges Muster -- auf das naechste geraten  32,1 %
von der Helligkeitssperre verworfen                 9,8 %
mehrdeutig / kein Muster in Reichweite              0,1 %
```

Die 32 % beschreiben den **Weg**, nicht die Fehlerquote — gegen eine belastbare
Wahrheit gemessen landet die Reparatur auf Abstand 1 fast immer richtig.

### Eine belastbare Wahrheit — und wie man sie verfehlt

Die Idee (Nutzer, 2026-08-30): Nur Würfe **in die Vollen** nehmen. Dort standen
vorher alle neun Kegel, also zeigen Lampen und Ziffer dieselbe Zahl. Erkennbar
ohne jede Ziffernlesung: Der bestätigte Lampenstand war vorher leer.

Der naive Weg — einfach die leuchtenden Lampen zählen — geht schief, weil die
Lampen **kumulativ** zeigen, was liegt, die Ziffer aber nur den aktuellen Wurf:

```
leuchtende Lampen   Ziffer   in Wahrheit
          9            2     7, dann Raeumung 2
          9            1     8, dann Raeumung 1
          9            4     5, dann 4
          9            9     alle neune, erster Wurf
```

Von 288 so als `9` beschrifteten Bildern waren nur 45 wirklich eine 9. Die
Pipeline rechnet das längst richtig (`neu_gefallen = end_pins - base_pins`);
das Messwerkzeug tat es nicht. **Eine Wahrheit, die man nicht prüft, misst am
Ende die eigene Annahme.**

Auf Bahn 4 und 5 bleibt die Beschriftung auch dann unsicher: Dort ist die
Lampenlesung Frame für Frame unzuverlässig (Bahn 5, Label 7: nur 37 % stimmen
mit dem Bild überein; Bahn 2 und 3: 92–100 %). Die Pipeline fängt das über ihre
zeitliche Aggregation ab — ein Einzelbild-Werkzeug nicht.

### Ergebnis auf Bahn 2 und 3

| Erkenner | vorher | nach der Änderung |
|---|---|---|
| Segmentabtastung | 95,7 % | **96,5 %** |
| davon unlesbar | 13 von 420 | **1 von 402** |
| nächster Mittelpunkt | 96,9 % | 95,8 % |
| 3 nächste Nachbarn | 96,4 % | — |

Ein formbasierter Erkenner (Form als Ganzes statt sieben Flächen) bringt
nichts — er liegt im selben Bereich. Die Segmentabtastung bleibt.

### Die Änderung

`min_display_brightness` wird auf das **Maximum** des Rotkanals angewandt statt
auf das 95. Perzentil, Schwelle 200 statt 230. Eine `1` leuchtet mit zwei von
sieben Segmenten und bleibt gemittelt dunkler als jede andere Ziffer:

```
Bahn 5, F40903    angezeigt   P95   Maximum   gelesen
throw_number [2]      1       220     254       ?  -> jetzt 1
total_b      [2]      1       229     255       ?  -> jetzt 1
pin_count    [1]   (dunkel)    97     114       ?     bleibt ?
```

Über 4800 Zellen, Anteil im unsicheren Bereich 150–245: 95. Perzentil 24,9 %,
99. Perzentil 6,5 %, **Maximum 3,6 %**. Dunkle Zelle 114–119, leuchtende
246–255 — die Schwelle 200 liegt in der Lücke.

Gegenlauf gegen das Protokoll (F28000–56000): Spieler A 30/30, Spieler B 30/30 — unverändert.


---

## Spielwechsel: Wann steht `000 0000` — und wann sieht jemand hin? (2026-08-30)

Die Erkennung zählte bei nahezu gleicher Wurfzahl (~370 je Bahn) völlig
verschieden viele Spielenden: Bahn 2 nur zwei, Bahn 3 dreizehn.

### Was die Tafel wirklich zeigt

`tools/measure_zero_display.py` liest Wurfnummer und Summe **ohne jede
Bedingung**, Frame für Frame, für alle vier Bahnen:

```
Abschnitt um F126600           Abschnitt um F164600
  Bahn 2  F127115-F128475  54 s   Bahn 2  F164535-F166780  90 s
  Bahn 3  F126680-F128715  81 s   Bahn 3  F165220-F166735  61 s
  Bahn 4  F126535-F128820  91 s   Bahn 4  F165695-F166745  42 s
  Bahn 5  F126825-F128915  84 s   Bahn 5  F165590-F166600  40 s
```

Der Nullzustand steht also auf allen Bahnen, 40 bis 91 Sekunden lang, und er
ist lesbar (Bahn 3 und 5: 100 % der Messungen darin, Bahn 2: 53–67 %).

### Warum er trotzdem nicht erkannt wurde

Die Pipeline las die späten Felder nur bei offenem Wurffenster — also zwischen
GREEN_OFF und dem nächsten GREEN_ON. Aus der Grünspur:

```
Bahn 2   GREEN_OFF F126877 -> GREEN_ON F127177 -> GREEN_OFF F128593
         000/0000 begann F127115. Fenster noch 62 Frames offen. Verpasst.
         Danach 1416 Frames Gruen AN -- niemand sah hin.
Bahn 3   GREEN_OFF F126108 -> GREEN_ON F126964
         000/0000 begann F126680. Fenster noch 284 Frames offen. Erkannt.
```

**Nicht die Ziffernerkennung war schuld, sondern die Bedingung, unter der
gelesen wurde.**

### Wie lang sind die Fehllesungs-Strähnen?

Eine Sperre gegen Doppelmeldungen muss wissen, wann die Anzeige den
Nullzustand wirklich verlassen hat. Gemessen im Abschnitt F164535–F166780,
Takt 25 Frames — Strähnen von Nicht-Null-Messungen **innerhalb** des
Nullzustands:

```
Bahn 2   17 Straehnen, laengste 3   Verteilung {1: 14, 2: 1, 3: 2}
Bahn 3    0 Straehnen
Bahn 4    4 Straehnen, laengste 6   Verteilung {1: 1, 2: 1, 4: 1, 6: 1}
Bahn 5    0 Straehnen
```

Mit einer Schwelle von 3 meldete Bahn 4 denselben Wechsel dreimal. Bei 10 ist
vier Messungen Luft über dem Maximum.

### Ergebnis

```
F124000-F131000:  4 Meldungen -- Bahn 4, 3, 5, 2, je genau eine
F163000-F168500:  4 Meldungen -- Bahn 2, 3, 5, 4, je genau eine
```

Die erkannten Frames liegen 30 bis 135 Frames nach dem unabhängig gemessenen
Beginn — das ist die Bestätigungszeit. Protokoll unverändert bei 30/30.


---

## Der Fehlwurfzähler auf Bahn 4: ein Störwert, der die Stabilitätsprüfung übersteht (2026-08-31)

Im vollständigen Lauf über den Spieltag zählte Bahn 4 **463 Würfe bei 426
Grünzyklen** — mehr Würfe als Zyklen. Die anderen Bahnen lagen bei 420–431.

### Wo die Würfe herkamen

```
Wuerfe mit 0 Kegeln je Bahn:   Bahn 2: 4 | Bahn 3: 1 | Bahn 4: 48 | Bahn 5: 8
Nullwuerfe im Protokoll:       Bahn 2: 0 | Bahn 3: 0 | Bahn 4:  1 | Bahn 5: 1
```

Alle Anstiege des Fehlwurfzählers nach Sprunghöhe:

```
Bahn 2   +1: 1
Bahn 3   keine
Bahn 4   +1: 1,  +3: 14
Bahn 5   +1: 2
```

Vierzehn Sprünge um drei, alle auf einer Bahn, jeder als drei Nullwürfe
gebucht: **42 erfundene Würfe**.

### Der Bildbeleg

Frame 270290, Bahn 4, `left_display`:

```
Tafel zeigt:      0 0
Erkenner liest:   0 3      (Helligkeit 244 / 255 -- die Zelle ist hell)
```

Die zweite Stelle wird als 3 gelesen. Der Wert 3 ist für dieses Feld seit dem
2026-08-25 als Störwert bekannt — die damalige Messung über 52 Minuten auf
Bahn 2 ergab Rohwerte `{0: 10711, 1: 776, 3: 147, 7: 3, 70: 1}`. Dort hielt der
Stabilitätsfilter (5 gleiche Lesungen in Folge) ihn ab. Auf Bahn 4 hält er nicht.

### Warum eine Plausibilitätsgrenze trägt, wo der Filter versagt

Der Zähler wird alle 10 Frames gelesen. Ein Wurfzyklus dauert gemessen 216 bis
338 Frames. Zwischen zwei Lesungen kann also **höchstens ein Wurf** liegen —
unabhängig davon, wie stabil ein Messwert aussieht.

Das ist der Unterschied zwischen einem Filter und einem Argument: Der Filter
fragt „habe ich das oft genug gesehen", das Argument fragt „kann das überhaupt
sein".

### Ergebnis

Gegenlauf F268000–280000, dasselbe Fenster:

```
5 x verworfen als Fehllesung
Wuerfe je Bahn: {2: 17, 3: 19, 4: 18, 5: 18}   davon 0 Kegel: keine
```

---

## Der Anlauf der grünen Lampe (2026-09-01)

**Anlass:** Auf Bahn 2 fehlte im Satz 2.3 ein Räumwurf zwischen Wurf 25
(F180238) und Wurf 27 (F181062). Vermutet wurde eine zu kurze Grünphase.

**Quelle:** `gruenspur.csv` und `lampenspur.csv` des Laufs
`lauf_2026-09-01_14-08-10` über den Spieltag 2026-08-22.

### Die Grünphase war nicht zu kurz

| Zyklus (Bahn 2) | Frames | Median-Score | Max | UNKNOWN |
|---|---|---|---|---|
| Wurf 23 | 180 | 68,8 | 73,8 | 2,2 % |
| Wurf 24 | 210 | 70,0 | 78,8 | 2,4 % |
| Wurf 25 | 200 | 71,2 | 77,5 | 0,0 % |
| **verworfen** | **175** | **60,0** | **70,0** | **57,1 %** |
| Wurf 27 | 248 | 71,2 | 78,8 | 0,0 % |

Die Dauer liegt im Normalbereich. Auffällig ist der Score: Median 60,0 gegen
sonst 68 bis 74, und mehr als die Hälfte der Frames in der Totzone zwischen
AUS- und AN-Schwelle.

### Die Schwelle steht ruhig

Über **484 Übergänge nach ON** auf Bahn 2 beträgt der erste ON-Score fast immer
exakt **62,5** (Median aller ersten ON-Scores: 63,7; Min 51,2; Max 78,8). Die
AN-Schwelle des gleitenden Histogramms ist also stabil — das Signal dieses
Zyklus war schwächer, nicht der Maßstab verrutscht.

### Der Anlauf als Kennzahl

Der Score kroch über rund 70 Frames durch die Totzone:

```
F180435  22,5   F180438  50,0   F180468  60,0   F180498  61,3   F180507  62,5
```

Gesunde Zyklen springen in ein bis sechs Frames über die Schwelle. Diese
Differenz — die Zahl der UNKNOWN-Frames unmittelbar vor dem ersten ON — heißt
hier **Anlauf** und ist mit `tools/measure_green_onset.py` messbar.

Über den ganzen Spieltag (1706 Zyklen, 1690 Würfe):

```
Bahn  Zyklen  ohne Wurf   Anlauf>20   beides
   2     429          8          10        1
   3     421          2           9        1
   4     426          4          12        2
   5     430          7          25        1
```

Fünf Zyklen vereinen langen Anlauf und fehlenden Wurf: Bahn 2 F180506 (Anlauf
56), Bahn 3 F66750 (50), Bahn 4 F47150 (78) und F144401 (46), Bahn 5 F296850
(92).

### Warum daraus ein verlorener Wurf wird

Der Zustandsautomat meldete GREEN_ON erst bei F180508, rund 69 Frames (2,8 s)
nach dem tatsächlichen Einschalten. Die Grundlinie wird bei GREEN_ON plus
`baseline_offsets` [0, 6, 12, 18, 25] gemessen, hier also F180508 … F180533.
Aus der Lampenspur:

```
F180500   8 Lampen an   pin_lamp_2: 164,7  OFF
F180525   9 Lampen an   pin_lamp_2: 253,4  ON
```

Der geräumte Kegel fiel **innerhalb** des Grundlinienfensters. Da
`aggregate_pin_readings` über die Frames vereinigt, hob eine einzige Messung
die Grundlinie auf neun. Ergebnis neun, Grundlinie neun, nichts neu gefallen —
`discard_unchanged_cycles` verwarf den Zyklus. Siehe BUG-016.

Gegenprobe: Bei GREEN_ON um F180440 hätte das Fenster F180440 … F180465
umfasst; dort lagen nachweislich acht Kegel.

### Wie oft die Vereinigungsregel sonst stört

242 Räumwürfe (Grundlinie > 0) im Lauf, davon **2** mit Abweichung zwischen
Lampenzahl und Tafelziffer. Die Regel ist im Normalfall harmlos — sie hat nur
keine Reserve gegen ein verspätetes GREEN_ON.

### Offen

Warum der Score in diesem Zyklus langsam anstieg statt zu springen, ist nicht
entschieden. Ein allmählich weichender Teilverdecker passt zum Verlauf, ist aber
ohne Blick in die Frames nicht belegt — das Material lag nur als Stream vor.
Siehe `docs/OPEN_QUESTIONS.md`.

### Probe: Was passiert, wenn die Grundlinie geschnitten statt vereinigt wird?

**Anlass:** Naheliegende Abhilfe gegen BUG-016 — für die Grundlinie nicht das
Maximum über die Frames nehmen. Vor dem Einbau geprüft.

**Wie gemessen:** Die gespeicherten ROI-Ausschnitte der Ereignisse
(4 Bahnen × ~200 Ereignisse × 9 Lampen = 7245 Lampen-Ereignisse, je 10 Frames
über 38 Frames Spanne) — dasselbe Zeitmaß wie das Grundlinienfenster. Während
eines Ereignisses fällt kein Kegel mehr, jede Abweichung zwischen den zehn
Messungen ist Blinken.

```
alle aus       970  13,39 %
alle an       3524  48,64 %
geteilt       2751  37,97 %     <- hier entscheiden die Regeln verschieden
```

**Fast vier von zehn Lampen blinken innerhalb des Fensters.** Damit ist der
Schnitt erledigt, bevor er gebaut ist. Gegen die Tafel-Ziffer als Wahrheit,
655 Würfe in die Vollen:

| Regel | richtig | Quote | häufigster Fehler |
|---|---|---|---|
| Vereinigung (heute) | 616 | 94,05 % | +1 Kegel: 19× |
| mindestens 2 Messungen | 619 | 94,50 % | +1 Kegel: 16× |
| Mehrheit | 458 | 69,92 % | −9 Kegel: 90× |
| Schnitt | 319 | 48,70 % | −9 Kegel: 192× |

Der Schnitt verliert bei 192 Würfen **alle neun** Kegel: Neun Lampen brannten,
keine einzige durchgehend. In der Testsuite schlagen mit dem Schnitt drei
Integrationstests fehl (`test_pipeline_smoke.py`), darunter der einfachste
Durchlauf überhaupt.

> Die absoluten Quoten sind eine Nachbildung mit fester Trennschwelle (204)
> statt der gleitenden Grundlinie des echten Detektors — der Lauf selbst
> erreicht 720/720 **erfasste** Würfe. Der **Vergleich** der Regeln trägt
> trotzdem, weil alle vier dieselbe Nachbildung benutzen.
> *(Nachtrag 2026-10-06: „720/720" war hier wie weiter unten die Spalte*
> *`erfasst`, nicht die Trefferquote. Siehe den Abschnitt zur blockweisen*
> *Ausrichtung am Ende dieser Datei.)*

### Wie lang muss das Grundlinienfenster sein?

Vereinigung über die ersten *n* Messungen, gegen dieselbe Wahrheit:

| Messungen | Spanne | richtig | Quote |
|---|---|---|---|
| 3 | 5 F | 508 | 77,56 % |
| 4 | 10 F | 567 | 86,56 % |
| **5** | **16 F** | **618** | **94,35 %** |
| 6 | 22 F | 618 | 94,35 % |
| 8 | 32 F | 617 | 94,20 % |
| 10 | 38 F | 616 | 94,05 % |

Ab fünf Messungen über 16 Frames ist nichts mehr zu gewinnen — danach wird es
minimal schlechter. Das heutige Grundlinienfenster reicht mit
`baseline_offsets` bis +25 also **neun Frames weiter in die Grünphase hinein,
als es müsste**, ohne dafür etwas zu bekommen.

Gerettet hätte das den Wurf auf Bahn 2 trotzdem nicht: Der Kegel fiel zwischen
F180500 und F180525, das verkürzte Fenster hätte F180508 … F180524 umfasst. Bei
69 Frames Verspätung liegt auch ein kurzes Fenster mitten in der Fallzeit. Die
Länge ist die Angriffsfläche, der Startzeitpunkt ist die Ursache.

### Die Grundlinie aus zwei Quellen (2026-09-01)

Nutzeridee: Beim Räumen bleiben die Ergebnislampen leuchten, bis der nächste
Wurf abgeschlossen ist — der Stand kurz **vor** dem Grün-AN müsste derselbe
sein wie kurz danach, und er hängt an keiner Erkennung.

Der Einwand stand im Code („vor GREEN_ON steht noch das Ergebnis des vorherigen
Wurfs"). Gegen 1610 Würfe geprüft, mit der Tafel-Ziffer als Wahrheit:

| Grundlinie aus | richtig | Quote |
|---|---|---|
| nur nachher (bisher) | 1604 | 99,63 % |
| nur vorher | 1601 | 99,44 % |
| **Schnittmenge beider** | **1604** | **99,63 %** |

Die beiden Einzelmessungen unterscheiden sich bei 3 von 1610 Würfen — dort
hatte die Anlage erst 17 bis 24 Frames vor dem Grün-AN gelöscht, der Stand
davor war also noch der alte. Beide Fehlerarten machen die Grundlinie zu
**groß**, nie zu klein. Deshalb die Schnittmenge.

Verworfene Zyklen kommen damit zurück — nachgewiesen im Vollauf weiter unten.

**Reserve — korrigiert.** Zuerst stand hier "der Ball braucht rund 100
Frames"; die Zahl kam aus einem Kommentar, der den Abstand Wurfzähler →
GREEN_OFF meint, nicht den Einschlag. Nachgemessen, 1448 Zyklen vom erkannten
Grün-AN bis zur ersten neu leuchtenden Lampe:

| Wurfart | Anzahl | 1. Perzentil | Median | unter 25 F | unter 50 F |
|---|---|---|---|---|---|
| in die Vollen | 1207 | 67 F (2,7 s) | 166 F (6,6 s) | 0 | 0 |
| Räumen | 235 | 50 F (2,0 s) | 114 F (4,6 s) | 0 | 2 (0,85 %) |

Beim Räumen wird zügiger geworfen — genau die Wurfart, die BUG-016 trifft. Die
Tabelle misst ab dem *erkannten* Grün-AN und enthält die fünf verworfenen
Zyklen nicht, die stehen ja in keiner `wuerfe.csv`.

**Blinken die Lampen synchron?** Nein — von 30 415 Messungen mit null
brennenden Lampen haben nur 204 (0,67 %) unmittelbar davor *und* danach
brennende Lampen. Eine Null ist also fast immer ein echtes Löschen, kein
gemeinsamer Aussetzer.


## Der Fix an zwei Quellen, am ganzen Spieltag nachgemessen (2026-09-01)

Der Lauf `lauf_2026-09-01_17-38-42` über 312 784 Frames, Zeile für Zeile gegen
den Vergleichslauf `14-08-10` derselben Quelle gehalten:

| | vorher | nachher |
|---|---|---|
| Würfe | 1690 | **1695** |
| davon VALID | 1662 | **1667** |
| EMPTY / ERROR | 13 / 15 | **13 / 15** |
| Räumwürfe | 242 | **247** |
| Kegel gesamt | 11 477 | **11 483** |

**Fünf Würfe kamen hinzu, keiner ging verloren.** Die Differenzmenge in der
Gegenrichtung ist leer — kein einziger Wurf des alten Laufs fehlt im neuen.
EMPTY und ERROR bleiben Zahl für Zahl gleich: Der Fix bringt nur saubere Würfe
hinzu, er verdirbt keinen bestehenden.

Die fünf, jeder mit der Tafel-Ziffer als unabhängiger Bestätigung:

| Bahn | Grün-AN | Meldung | Grundlinie | Kegel | Wurfbild | Ziffer |
|---|---|---|---|---|---|---|
| 4 | 41026 | 41147 | 7 | 2 | 5 7 | **2** |
| 3 | 66750 | 66871 | 8 | 1 | 8 | **1** |
| 4 | 144401 | 144523 | 7 | 1 | 4 | **1** |
| 2 | 180506 | 180615 | 8 | 1 | 7 | **1** |
| 5 | 296850 | 296973 | 8 | 1 | 6 | **1** |

Alle fünf sind Räumwürfe, alle fünf VALID, und bei allen fünf nennt die
Anzeigetafel dieselbe Kegelzahl wie die Lampen — eine Quelle, die am Fix nicht
beteiligt ist.

### Die zweite Quelle greift nur dort ein, wo sie gebraucht wird

Über 1702 Grünzyklen meldet das Log genau **fünf** Widersprüche zwischen dem
Stand vor dem Grün-AN und dem danach — und es sind genau diese fünf. In den
übrigen 1697 sind beide Messungen einig, die Schnittmenge ändert dort nichts.
Der Eingriff ist also so eng, wie er sein soll.

### Was die fünf verbindet, ist nicht der Anlauf

Die Vorhersage aus der Analyse traf in vier von fünf Fällen. Bahn 4 F47150 war
erwartet worden und kam nicht zurück; stattdessen kam Bahn 4 F41026, den die
Anlauf-Heuristik nicht gefunden hatte — sein Anlauf betrug nur 7 Frames.

Der gemeinsame Nenner ist ein **schwaches Grünsignal**:

| Bahn | Grün-AN | Anlauf | max. Score der Phase |
|---|---|---|---|
| 4 | 41026 | 7 | 56,2 |
| 3 | 66750 | 50 | 68,1 |
| 4 | 144401 | 46 | 60,0 |
| 2 | 180506 | 56 | 70,0 |
| 5 | 296850 | 92 | **44,4** |

Gesunde Zyklen auf Bahn 2 erreichen 77 bis 79. Der lange Anlauf ist ein
*Symptom* der schwachen Phase, nicht die Ursache — und nicht das einzige.
Daraus folgt etwas Beruhigendes über den Fix: Der Stand aus der Pause hängt an
**gar keiner** Eigenschaft der Grünerkennung. Er trägt deshalb auch dort, wo
sie auf eine Weise irrt, die noch niemand vorhergesehen hat.

### Bahn 4 hat ein Lampenproblem, das hiermit nichts zu tun hat

Bei F47150 lagen die beiden stehenden Kegel dauerhaft in der Totzone: Lampe 5
und 7 messen über 350 Frames stabil 210, bei AUS-Schwelle 198 und AN-Schwelle
234 — also durchgehend UNKNOWN, während die sieben liegenden Kegel bei 252
klar ON sind.

UNKNOWN-Anteil je Bahn, über alle neun Lampen und den ganzen Spieltag:

| Bahn | UNKNOWN |
|---|---|
| 2 | 0,14 – 0,34 % |
| 3 | 0,78 – 5,72 % |
| 4 | **5,71 – 9,04 %** |
| 5 | 0,53 – 7,13 % |

Das Helligkeitshistogramm über alle 438 813 Messungen zeigt, warum: Die
AUS-Wolke reicht von 130 bis 219 und läuft flach aus, die AN-Wolke sitzt scharf
bei 240–259. Dazwischen liegt bei 220–239 ein Tal mit 0,93 %. Ein Wert von 210
ist also eine **helle AUS-Lampe**, keine halb leuchtende — die AUS-Schwelle bei
198 ist für diese ROIs nur zu tief angesetzt.

Warum die zweite Quelle bei F47150 trotzdem neun statt sieben Kegel lieferte,
lässt sich aus den vorhandenen Spuren nicht belegen: Die Lampenspur schreibt
alle 25 Frames, die Pause-Messungen laufen alle 5. Offen als Q13.
## Bahn 4: kein Farbstich, sondern eine Schwelle an der falschen Stelle (2026-09-01)

Anlass war die Frage, ob ein Weißabgleich Bahn 4 helfen würde. Sie lässt sich
aus der Lampenspur nicht beantworten — die schreibt nur `value`, nicht die
Kanäle. Also 5400 Messungen der einzelnen Farbkanäle direkt an der Quelle
(`tools/measure_lamp_channels.py`, Frames 15000–30000, alle 100):

| Bahn | Zustand | B | G | R | value |
|---|---|---|---|---|---|
| 2 | AUS | 120,0 | 128,4 | 147,9 | 147,9 |
| 3 | AUS | 138,4 | 146,6 | 166,7 | 166,8 |
| **4** | **AUS** | **159,6** | **163,0** | **181,1** | **181,4** |
| 5 | AUS | 138,8 | 145,4 | 160,3 | 160,4 |
| 2 | AN | 202,6 | 240,2 | 254,2 | 254,8 |
| **4** | **AN** | **190,8** | **215,6** | **250,4** | **250,4** |

Bahn 4 ist auf allen drei Kanälen um rund 34 Punkte angehoben — gleichmäßig.
Das ist ein **Schwarzwert-Versatz**, kein Farbstich.

**Warum ein Weißabgleich hier nichts ausrichtet.** Der Detektor misst
`value = max(B,G,R)`. Gemessen ist **Rot in 99,7 bis 100 % aller Fälle der
größte Kanal** — auf jeder Bahn, bei AUS wie bei AN:

| Bahn | AUS | Totzone | AN |
|---|---|---|---|
| 2 | 100,0 % | 100,0 % | 100,0 % |
| 3 | 100,0 % | 100,0 % | 100,0 % |
| 4 | 99,7 % | 100,0 % | 100,0 % |
| 5 | 100,0 % | — | 100,0 % |

Der Messwert hängt damit ausschließlich am Rotkanal. Blau und Grün zu
skalieren ändert ihn nicht; Rot zu skalieren verschiebt AUS und AN gemeinsam.
Ein Weißabgleich ist multiplikativ, der Fehler ist additiv — das falsche
Werkzeug. Simuliert bringt er Bahn 4 **−6,6** Kontrastpunkte.

### Die Formel arbeitet gegen sich selbst

Die adaptive Schwelle rechnet `Niveau + Anteil × (255 − Niveau)`. Je höher das
Ruheniveau, desto kleiner der Spielraum — und desto enger der Abstand zur
Schwelle. Genau dort, wo wegen der breiteren Streuung der größte Abstand nötig
wäre, gibt sie den kleinsten:

| Bahn | Niveau | AUS-Schwelle | Abstand | AUS p95 | Reserve |
|---|---|---|---|---|---|
| 2 | 145,2 | 194,3 | 49,1 | 170,7 | **+23,6** |
| 3 | 165,6 | 194,3 | 28,7 | 196,7 | −2,4 |
| 4 | 182,1 | 204,7 | **22,6** | 213,5 | **−8,8** |
| 5 | 162,2 | 194,3 | 32,1 | 201,4 | −7,1 |

Bahn 2 bekommt 49 Punkte Abstand, Bahn 4 nur 23 — bei breiterer Streuung. Ist
die Reserve negativ, landen über 5 % der AUS-Messungen in der Totzone. Genau
das misst die UNKNOWN-Rate.

**Der Platz ist da, er wird nur nicht genutzt.** Zwischen AUS p95 (213,5) und
AN p5 (245,7) liegen auf Bahn 4 volle 32 Punkte brach. Und in der Totzone
steckt nichts, was verloren ginge: Von allen UNKNOWN-Messungen liegt auf
**keiner** Bahn eine einzige im AN-Bereich (0,0 %), auf Bahn 4 dagegen 63 % im
normalen AUS-Bereich.

| `baseline_off_fraction` | Bahn 2 | Bahn 3 | Bahn 4 | Bahn 5 |
|---|---|---|---|---|
| 0,31 (heute) | 0,49 % | 2,88 % | **6,71 %** | 5,10 % |
| 0,50 | 0,24 % | 0,36 % | **0,87 %** | 0,53 % |
| 0,55 | 0,22 % | 0,29 % | **0,51 %** | 0,37 % |

Das ist eine Simulation über die aufgezeichneten Werte, kein Lauf — die Zahl
gehört erst nach einem Vollauf mit Gegenprobe in die Konfiguration. Siehe Q13.

**Was das Kegeln angeht:** Bahn 4 trägt 11 der 15 ERROR-Würfe des Spieltags
(2,6 % ihrer Würfe gegen 0,0 % auf den Bahnen 2 und 3). Gegen die Tafel-Ziffer
gehalten liegt sie mit 0,25 % Abweichung dagegen im Feld — der Schaden zeigt
sich als Unentschiedenheit, nicht als falsche Zahl.

### Die ROIs sitzen richtig — angesehen, nicht vermutet

Die zweite Erklärung war, dass die ROIs von Bahn 4 ungünstiger sitzen. Frame
20000 auf beiden Bahnen exportiert (`tools/export_roi_frames.py`, Bilder unter
`debug/roi_bahn2/` und `debug/roi_bahn4/`): Die Rahmen sitzen auf beiden Bahnen
sauber und zentriert auf den Lampen, sind gleich groß (80 × 75 normiert auf
allen vier Bahnen) und die Bilder sind gleich unscharf.

Was der Vergleich stattdessen zeigt: **Die Tafel auf Bahn 4 ist überstrahlt.**
Gehäuse und Lampenkappen sind heller und blasser, wo dieselbe Tafel auf Bahn 2
bräunlich und satt erscheint. Die ausgeschalteten Lampen sind glänzende
Halbkugeln — sie spiegeln die hellere Umgebung, und genau das hebt ihren
AUS-Wert.

Die Farbsättigung `(max − min) / max` bestätigt es, und zwar gegenläufig:

| Bahn | AUS | AN | AN-Messungen bei ≥ 254 |
|---|---|---|---|
| 2 | **18,2 %** | 20,3 % | **84,3 %** |
| 3 | 16,2 % | 21,9 % | 51,2 % |
| 4 | **11,6 %** | 23,6 % | **2,6 %** |
| 5 | 13,4 % | 25,4 % | 11,6 % |

Bei AUS ist Bahn 4 am flachsten — Streulicht hebt alle Kanäle gemeinsam. Bei AN
ist sie am gesättigtsten, weil sie als einzige nicht in die Sättigung läuft; wo
alle Kanäle gegen 255 gehen, verschwindet der Farbabstand ohnehin.

Bahn 4 ist also nicht anders gefärbt, sondern hat den engeren nutzbaren
Bereich: Schwarzwert angehoben, Weißwert nicht ausgereizt.

### Die grüne Lampe folgt demselben Muster — aber über einen anderen Mechanismus

Sie wird nicht über `max(B,G,R)` gelesen, sondern über eine HSV-Maske
(`inRange(40,80,80 … 90,255,255)`); der Score ist der Anteil passender Pixel.
Dort zählt die **Sättigung**, und die Maske verlangt mindestens 80:

| Bahn | AUS p95 | AN p5 | Lücke | UNKNOWN |
|---|---|---|---|---|
| 2 | 37,5 | 66,2 | **28,7** | 0,67 % |
| 3 | 45,8 | 68,1 | 22,3 | 0,96 % |
| 4 | 40,0 | 55,0 | **15,0** | 1,36 % |
| 5 | 31,1 | 42,2 | **11,1** | 3,20 % |

Bahn 5 ist hier die schwächste, nicht Bahn 4 — die Rangfolge der Kegellampen
überträgt sich also nicht.

**Auch hier ist die Sättigung nicht der Engpass.** Gemessen über 10 000 Frames,
über die grün getönten Pixel der Lampe:

| Bahn | Zustand | Score | Sättigung | Helligkeit | grüner Anteil |
|---|---|---|---|---|---|
| 2 | AN | 71,9 | 167,8 | 180,2 | 76,2 % |
| 3 | AN | 77,8 | 167,3 | 193,8 | 80,6 % |
| 4 | AN | **62,5** | **151,7** | 184,4 | 75,0 % |
| 5 | AN | **58,9** | **141,2** | 178,3 | 83,3 % |

Die Maske verlangt Sättigung ≥ 80. Gemessen werden 141 bis 168 — die Reserve
ist auf jeder Bahn mehr als doppelt so groß wie die Anforderung. Der
Score-Unterschied entsteht nicht im Kern der Lampe, sondern an ihrem **Rand**:
Auf Bahn 2 fallen 4,3 Prozentpunkte der grün getönten Pixel durch die Maske,
auf Bahn 4 sind es 12,5.

Damit zielt auch hier ein Weißabgleich am Problem vorbei. Der begrenzende
Faktor ist die Randschärfe, nicht die Farbe — und die Lücke zwischen AUS (28,8)
und AN (62,5) ist auf Bahn 4 immer noch vorhanden, nur schmaler.

## Der Kegellampen-ROI: 12 × 11 Pixel, und was ein engerer bringt (2026-09-01)

Anlass war die Frage, ob ein kleinerer Rahmen — „nur noch die mittleren Pixel"
— die Trennung verbessert. Gemessen mit `tools/measure_roi_shrink.py` über
10 800 Ausschnitte auf zwei Strecken (Frames 15000–30000 und 250000–265000).

**Erste Überraschung: Der Rahmen ist bereits winzig.** Die 80 × 75 der
Kalibrierung sind normierte Einheiten; im Bild sind es **12 × 11 Pixel**. Eine
Verkleinerung auf 30 % ließe 3 × 3 Pixel übrig, und davon nähme der
Kernfilter nochmals die hellsten 30 % — drei Pixel.

**Die Kennzahl** ist die Trennlücke `p5(AN) − p95(AUS)`: der Abstand zwischen
dem dunkelsten Zwanzigstel der leuchtenden und dem hellsten der dunklen
Messungen. Der Kontrast der Mediane taugt nicht — er kann groß sein, während
sich die Ränder berühren.

### Befund 1: Der halbe Gewinn kommt vom Nachzentrieren

Bahn 4, Zuschnitt auf 80 %, frühe Strecke:

| | Trennlücke |
|---|---|
| heute (100 %) | 44,8 |
| 80 %, geometrisch zentriert | 49,0 |
| 80 %, **auf den Lampenschwerpunkt zentriert** | **54,3** |

Die Lampen sitzen im Median 4–10 % oberhalb und links der Rahmenmitte, im
Extremfall 15 % daneben — bei 12 Pixeln knapp zwei Pixel. Der Gewinn zeigt
sich an der AN-Seite: Bahn 4 steigt von 245,3 auf 253,5 (p5), die Lampen
**sättigen endlich** wie auf Bahn 2. Die AUS-Seite bleibt fast unverändert.

### Befund 2: Kernfilter und Rahmengröße ersetzen einander

Bahn 4, frühe Strecke:

| Zuschnitt | mit Kernfilter (70) | ohne Kernfilter |
|---|---|---|
| 100 % | 44,8 | 16,3 |
| 80 % | 54,3 | 30,1 |
| 60 % | 42,6 | 48,7 |
| **50 %** | 42,1 | **61,8** |
| 40 % | 38,0 | 61,7 |

Bei weitem Rahmen braucht es den Filter, bei engem schadet er — er nimmt einer
ohnehin kleinen Pixelmenge nochmals 70 %. **`core_percentile` ist ein Notbehelf
für einen zu weiten Rahmen.** Sitzt der Rahmen eng, wird er überflüssig, und
das Ergebnis ist besser als beides einzeln.

### Befund 3: Die Position ist stabil, die Helligkeit nicht

Zwischen den beiden Strecken liegen rund 2,6 Stunden:

| Bahn | Versatz des Schwerpunkts | größter |
|---|---|---|
| 2 | −0,2 % / +2,0 % | 4,8 % |
| 3 | +0,1 % / +2,2 % | 3,9 % |
| 4 | +0,1 % / +1,7 % | **2,9 %** |
| 5 | −0,2 % / +2,4 % | 4,8 % |

Die Einblendung wandert also praktisch nicht — ein 50 %-Zuschnitt lässt 25 %
Rand je Seite und hat davon reichlich Reserve. **Das AUS-Niveau steigt im
selben Zeitraum dagegen um 10 bis 23 Punkte**, und die Trennlücke schrumpft
entsprechend:

| Trennlücke Bahn 4 | früh | spät |
|---|---|---|
| heute | 44,8 | **33,7** |
| 80 % + Kern 70 | 54,3 | 37,5 |
| **50 % ohne Kern** | **61,8** | **44,8** |
| 40 % ohne Kern | 61,7 | **51,2** |

Der schlechteste Fall über alle vier Bahnen und beide Strecken: heute 33,7 —
bei 50 % ohne Kernfilter 44,8, bei 40 % 47,1. **Der Zuschnitt löst die Drift
nicht, er vergrößert nur den Abstand, den sie aufzehrt.**

### Was daraus nicht folgt

Dass die Zahl einfach eingetragen werden kann. Ein anderer Zuschnitt verschiebt
**alle** Niveaus: Bei 50 % ohne Kernfilter fällt AN p5 auf Bahn 4 spät auf
240,0, während die heutige AN-Schwelle anteilig bei 233 bis 237 landet — das
wäre zu knapp. `brightness_on_threshold`, `brightness_off_threshold` und beide
Fractions müssten mitbestimmt und ein Vollauf dagegen gehalten werden.

Die Rohdaten liegen unter `debug/roi_proben/`, damit die Frage ohne neuen
Quellzugriff weiterverfolgt werden kann — der Stream-Zugang läuft am
2026-09-02 ab.

## Der enge ROI im Vollauf bestätigt (2026-09-02)

`lauf_2026-09-02_18-30-19`, ganzer Spieltag über die Stream-Quelle, mit
`1Spieltag_enge_lampen.json` und dem neu bestimmten Schwellensatz. Gegen den
Referenzlauf `2026-09-01_17-38-42` derselben Quelle gehalten:

| | weiter ROI | **enger ROI** |
|---|---|---|
| Grünzyklen / Würfe | 1702 / 1695 | 1702 / **1695** |
| Status VALID | 1667 | **1679** |
| Status EMPTY | 13 | 16 |
| **Status ERROR** | **15** | **0** |
| Kegel gesamt | 11 483 | 11 479 |
| Abweichung zur Tafel-Ziffer | 8 von 1621 | **7 von 1621** |

**Die Zielgröße, UNKNOWN-Anteil der Kegellampen über den ganzen Spieltag:**

| Bahn | weiter ROI | enger ROI |
|---|---|---|
| 2 | 0,27 % | **0,11 %** |
| 3 | 1,83 % | **0,26 %** |
| 4 | **6,73 %** | **0,50 %** |
| 5 | 3,01 % | **0,28 %** |

Bahn 4 fällt um den Faktor 13. Damit liegen alle vier Bahnen erstmals im selben
Bereich — die Sonderrolle von Bahn 4 ist verschwunden.

**Alle 15 ERROR-Würfe sind aufgelöst, ohne dass sich eine Zahl änderte.** 13
wurden VALID, 2 blieben als EMPTY stehen (sie waren schon vorher 0 Kegel). Die
Kegelzahl ist in jedem der 15 Fälle dieselbe geblieben, und wo eine Tafel-Ziffer
vorlag, stimmt sie überein. Der ERROR-Status kam also nicht von einer falschen
Zahl, sondern von unlesbaren Lampen — 11 der 15 lagen auf Bahn 4.

### Die vier abweichenden Würfe, mit der Tafel als Schiedsrichter

| Bahn | Frame | alt | neu | Tafel | Urteil |
|---|---|---|---|---|---|
| 3 | 14502 | 8 | **9** | 9 | enger ROI |
| 4 | 14327 | 8 | **5** | 5 | enger ROI |
| 4 | 289308 | **9** | 8 | 9 | weiter ROI |
| 5 | 16256 | 1 | 0 | — | offen |

Zwei gewonnen, eine verloren, eine ohne Zeugen. Die Gesamtabweichung zur Tafel
sinkt von 8 auf 7 von 1621.

**Was offen bleibt:** Bahn 4 F289308 verliert einen Kegel, den die Tafel zählt.
Ein Einzelfall unter 1621 geprüften Würfen, aber ungeklärt — mit dem engen
Rahmen kann eine Lampe verfehlt werden, deren Leuchtfläche außermittig sitzt.
Dasselbe gilt womöglich für Bahn 5 F16256.

## Spielwechsel nur an der Wurfnummer (2026-09-02)

Nutzeridee: Die Wurfnummer wird zu 100 % gelesen, die Summe nicht — also nur
die Wurfnummer als Zeugen nehmen. Wo `000` steht, muss ein neuer Zyklus
beginnen; einen ersten Wurf mit einer Summe über null kann es nicht geben.

**Warum das mehr ist als eine Vereinfachung:** Die Summe wurde ZUERST gelesen
und war damit der Torwächter — bei `not summe.is_readable` brach die Prüfung
ab, und die Wurfnummer kam nie zum Zug. Der schwächere Zeuge entschied über
den stärkeren.

Vollauf `lauf_2026-09-02_21-11-00` gegen `18-30-19`, gleiche Kalibrierung:

| | vorher | nachher |
|---|---|---|
| Würfe / Kegel | 1695 / 11 479 | **1695 / 11 479** |
| VALID / EMPTY / ERROR | 1679 / 16 / 0 | **1679 / 16 / 0** |
| Abweichung zur Tafel-Ziffer | 7 von 1621 | **7 von 1621** |

**Nichts verändert sich — außer der Abschnittsstruktur auf Bahn 4:**

| Bahn | vorher | nachher |
|---|---|---|
| 2 | 16 Abschnitte | 16 |
| 3 | 16 | 16 |
| **4** | **14** | **16** |
| 5 | 16 | 16 |

Der 51-Wurf-Block auf Bahn 4 zerfällt in `1 + 19 + 29 + 31 …` — also 20 Würfe
Warmwerfen und dann die Sätze, dasselbe Muster wie auf den anderen drei
Bahnen. Nach dem Streichen der Nullwürfe stehen alle vier Bahnen auf
**16 Abschnitten mit 12 Sätzen**.

**Was offen bleibt:** Die Wurfnummernketten laufen weiterhin in 46 von 48
langen Abschnitten sauber 1…30 durch — die Zahl ändert sich nicht, die
Fehlerstelle wandert nur (vorher Bahn 4 Spiel 1 mit 51 Würfen, jetzt Bahn 4
Spiel 3 mit 29). Die neue Trennstelle sitzt also um einen Wurf verschoben. Das
ist ein kleinerer Fehler als ein verschmolzenes Spiel, aber kein perfekter
Schnitt.

**Schalter:** `scoring.game_reset_number_only` (an).
**Regressionstests:** `test_game_reset.py::TestNurDieWurfnummer` — vier Fälle,
darunter die Gegenprobe, dass es ohne den Schalter beim alten Verhalten bleibt.

## Enge Lampen-ROIs in der geführten Kalibrierung (2026-09-03)

Die geführte Kalibrierung legte weiterhin die alten weiten Rahmen an
(0,080 × 0,075) — der Umbau vom Vortag steckte nur in der einen
Kalibrierungsdatei, nicht in der Vorlage. Damit wäre jedes neue Video wieder
mit dem alten Verhalten gestartet.

**Nachgemessen wurden dabei auch die Positionen.** Die Vorlage stammte aus
einer Nutzerkalibrierung von Hand und lag systematisch zu hoch:

| | Vorlage alt | gemessen | Abweichung |
|---|---|---|---|
| erste Zeile y | 0,342 | 0,353 | +0,011 |
| Zeilenabstand | 0,0775 | 0,0753 | −0,0022 |
| Mittelachse x | 0,498 | 0,501 | +0,003 |

Beim weiten Rahmen fiel das nicht auf. Beim halbierten wären 0,011 fast ein
Drittel der Höhe — der Rahmen hätte die Leuchtfläche angeschnitten. Die neue
Vorlage ist zudem sauber symmetrisch: Der Mittelpunkt der äußeren wie der
mittleren Lampen liegt auf 0,501, die Abstände sind ±0,322 und ±0,161.

Die Streuung zwischen den vier Bahnen liegt bei 0,006 bis 0,012 — die Vorlage
kann also nur ein Ausgangspunkt sein, den der Nutzer nachzieht. Genau dafür
sind die Rahmen mit der Maus verschiebbar.

## Der erste Wurfbeleg findet gleich etwas (2026-09-03)

Erster Einsatz von `debug.throw_sheet` am echten Material (Frames 14000–24000,
50 Würfe, 6,7 MB). Zwei Beobachtungen aus den Bildern:

**Die engen Lampen-ROIs sitzen sichtbar mittig** auf den Leuchtflächen — die
gemessene Vorlage trifft, was sich vorher nur aus Zahlen ableiten ließ.

**Bahn 4, Spiel 2, Wurf 2: Die Ziffer ist klar lesbar, wird aber verworfen.**
Im Belegbild zeigt `pin_count` eine unübersehbare **9**, alle neun Lampen
leuchten, und die Wurfzeile trägt trotzdem „Tafel unlesbar". Die Lampenlesung
(9 Kegel) ist richtig — nur die zweite Quelle fällt aus, obwohl sie im Bild
steht.

Das ist genau der Fall, für den der Beleg gebaut wurde: Aus `wuerfe.csv` allein
wäre nur zu sehen, dass die Ziffernspalte leer ist — nicht, dass die Ziffer
dastand. Es stützt die Vermutung des Nutzers, dass an der Ziffernerkennung noch
etwas zu holen ist, und grenzt sie zugleich ein: Nicht die *Lampen* sind das
Problem, sondern die Segment-Dekodierung bei gut lesbaren Ziffern.

Passend dazu die frühere Messung: Die Kegelzahl-Ziffer ist auf Bahn 4 nur zu
92,9 % verfügbar, auf Bahn 2 zu 99,5 %.

**Was der Beleg nicht klärt:** Die Tafelsumme steht bei Wurf 2 auf 0014,
während der Lauf 18 zählt. Der Ausschnitt beginnt mitten im Spiel, die Summen
sind deshalb nicht vergleichbar — ein Vollauf müsste das entscheiden.

## Drei Schwellen, die am falschen Ort standen (2026-09-03)

Anlass waren zwei Beobachtungen des Nutzers an den Videoclips der Streitfälle.
Beide führten auf denselben Fehlertyp: eine Schwelle am **Rand** einer Wolke
statt in der Lücke zwischen zweien.

### 1. Die AN-Schwelle klebte an der AN-Wolke

Nutzerfrage: „Warum ist unsere Grenze für AN so nah an den AN-Werten? Dann
setze ich die Schwelle doch bitte möglichst mittig dazwischen."

Gemessen am Lauf `2026-09-02_21-11-00`:

| Bahn | AUS-Wolke bis | AN-Wolke ab | Mitte wäre | AN-Schwelle war | zu hoch |
|---|---|---|---|---|---|
| 2 | 160,8 | 248,1 | 204,4 | 220,0 | +15,6 |
| 3 | 179,9 | 244,3 | 212,1 | 224,2 | +12,1 |
| **4** | 190,6 | **232,2** | 211,4 | **226,4** | **+15,0** |
| 5 | 179,4 | 239,1 | 209,2 | 221,4 | +12,2 |

Auf Bahn 4 blieben **5,8 Punkte** zwischen Schwelle und Wolke. Genau dort ging
der einzige Wurf verloren, der gegen das Wurfprotokoll falsch war.

Der Denkfehler steckte in der Herleitung: Die Bedingung lautete „AN-Schwelle
unter dem 5. Perzentil der AN-Messungen" — das erfüllt auch eine Schwelle, die
*gerade eben* darunter liegt.

### 2. Die obere Seite war gar nicht gemessen, sondern angenommen

Nutzerfrage: „Ich dachte, wir machen, dass das sich live anpasst?"

Halb richtig — und das war das Problem:

```
Schwelle = Niveau + (255 − Niveau) × Anteil
           ~~~~~~   ~~~
           gemessen  feste Annahme
```

Das AUS-Niveau läuft je Lampe mit. Die obere Seite ist `brightness_saturated`,
also die Annahme, eine leuchtende Lampe sei im Bild gesättigt. Gemessen:

| Bahn | AN-Wolke (Median) | angenommen | Fehler |
|---|---|---|---|
| 2 | 252,6 | 255 | +2,4 |
| 3 | 249,0 | 255 | +6,0 |
| **4** | **243,3** | 255 | **+11,7** |
| 5 | 246,2 | 255 | +8,8 |

Weil die Schwelle als *Anteil dieses Abstands* gerechnet wird, rutscht sie
genau dort nach oben, wo die Lampen am schwächsten leuchten — der Fehler
verstärkt sich selbst.

**Abhilfe (`adaptive_on_level`):** ein zweites Gedächtnis für die leuchtenden
Messungen. Die Schwellen liegen dann mittig zwischen zwei *gemessenen*
Wolkenrändern, ohne jede Annahme über Sättigung.

**Die Rückkopplung ist bewusst durchbrochen:** Das AN-Gedächtnis wird an einer
festen Schranke gefüllt (`an_ignore_below`), nicht an der Klassifikation. Sonst
entschiede die Schwelle darüber, welche Messungen sie selbst bestimmen — ein
Kreis, der beliebig weit driften kann, ohne aufzufallen. Zwei weitere Sperren:
`min_wolken_abstand` (berühren sich die Wolken, wird zurückgefallen) und
mindestens 50 Messungen je Seite.

**Ergebnis am Streitfall F289308:**

| | vorher | nachher |
|---|---|---|
| Kegel | 8 (falsch) | **9** (richtig) |
| Confidence | **0,09** | **1,00** |

Alle zehn Würfe des geprüften Abschnitts stimmen danach mit der Tafel-Ziffer
überein, neun davon mit Confidence 1,00.

### 3. Die Verdeckungsschwelle stand am Rand statt im Tal

Nutzerbeobachtung: In zwei Clips läuft eine Person durchs Bild und unterbricht
die Grünphase. Die Frage war, ob man dafür Personenerkennung braucht.

**Man braucht keine.** Über 512 049 als AUS gelesene Grünscores des ganzen
Spieltags:

| Score | Messungen | Bedeutung |
|---|---|---|
| 0–1 | **32 298** | Tafel verdeckt |
| 2–11 | **286** | Tal (0,06 %) |
| 12–41 | **479 465** | echtes Grün-AUS |

Eine ausgeschaltete Lampe **kann nicht auf null fallen** — das beige Gehäuse
hat immer Grünanteil, echtes AUS liegt bei 20 bis 30. Ein Wert unter 12 heißt
zwingend, dass etwas davor ist. Das ist Eskalationsstufe 1 (Schwellwert auf
ROI-Statistik); ein Modell zur Personenerkennung wäre Stufe 5 und wüsste
nichts, was diese eine Zahl nicht schon sagt.

Die Schwelle stand bei **2,0**, also am Rand der Verdeckungswolke. Auf Bahn 2
fiel der Score bei F265718 auf **6,2** — zu hoch für „verdeckt", zu niedrig für
„aus". Die Zustandsmaschine löste GREEN_OFF aus und buchte einen Wurf, zwei
Frames bevor der Score 0,0 erreichte. Jetzt steht sie bei **12,0**.

**Zwei Fehler mit einer Änderung behoben:** Der Phantomwurf ist weg — und mit
ihm die erfundene Tafel-Ziffer „1". Sie entstand aus einem Ausschnitt, in dem
eine Person stand; während einer erkannten Verdeckung wird auch die
Ziffernlesung eingefroren.

### Was der Nutzer an den Clips gesehen hat

Seine Bewertung der zehn Streitfälle, als Bodenwahrheit festgehalten:

| Fall | Tafel zeigt | wir lasen | Urteil |
|---|---|---|---|
| Bahn 5, F148152 | 8 | 2 | Ziffernerkennung falsch |
| Bahn 5, F208871 | 8 | 2 | Ziffernerkennung falsch |
| Bahn 5, F210507 | 9 | 7 | Ziffernerkennung falsch |
| Bahn 5, F252902 | 9 | 7 | Ziffernerkennung falsch |
| Bahn 2, F265720 | 0 | 1 | **erfunden**, Anzeige war dunkel |
| Bahn 5, F272689 | 8 | 0 | Ziffernerkennung falsch |
| Bahn 4, F14327 | 5 | 5 | enger ROI richtig, weiter falsch |
| Bahn 3, F14502 | 9 | 9 | enger ROI richtig |
| Bahn 5, F16256 | — | — | enger ROI richtig, Verdeckung |

**In allen sechs Ziffernfällen hatten die Lampen recht.** Fünf davon sind
übersehene Segmente (8→2, 9→7, 8→0), einer ist eine erfundene Ziffer bei
dunkler Anzeige. Der enge ROI ist in allen drei Vergleichsfällen bestätigt.

### Der Vollauf mit allen drei Änderungen (2026-09-03)

`lauf_2026-09-03_11-14-04`, ganzer Spieltag, gegen das Wurfprotokoll geprüft:

| | weiter ROI (01.09.) | enger ROI (02.09.) | **mit den drei Änderungen** |
|---|---|---|---|
| **gegen das Protokoll (erfasst)** | 720/720 | 719/720 | **720/720** |
| Würfe | 1695 | 1695 | 1694 |
| Kegel gesamt | 11 483 | 11 479 | 11 480 |
| VALID / EMPTY / ERROR | 1667/13/15 | 1679/16/0 | 1679/**15**/0 |
| Abweichung zur Tafel-Ziffer | 8 von 1621 | 7 von 1621 | **5 von 1620** |

Der eine Wurf weniger ist der **Phantomwurf aus der Verdeckung** — ein EMPTY,
das es nie gab. Zwei der verschwundenen Ziffer-Abweichungen waren erfundene
Ziffern aus verdeckten Ausschnitten.

**UNKNOWN-Anteil der Kegellampen**, die Wirkung der zweiseitigen Anpassung:

| Bahn | 01.09. | 02.09. | **03.09.** |
|---|---|---|---|
| 2 | 0,27 % | 0,11 % | **0,06 %** |
| 3 | 1,83 % | 0,26 % | **0,12 %** |
| **4** | **6,73 %** | 0,50 % | **0,17 %** |
| 5 | 3,01 % | 0,28 % | **0,13 %** |

**Verdeckungen:** 48 Phasen, 2611 Frames — 0,8 % der Aufzeichnung. Die
schärfere Schwelle friert selten ein und kostet keine echten Würfe.

### Was diese Sitzung methodisch gezeigt hat

Alle drei Schwellen hatten denselben Fehler: Sie standen am **Rand** einer
Wolke statt in der Lücke zwischen zweien. Dreimal wurde geprüft, ob die
Schwelle die eine Wolke *knapp* verfehlt — statt zu fragen, wo zwischen beiden
sie hingehört. Der Erkennungs-Skill fordert unter §8 genau das Gegenteil
(„Schwelle in die Lücke legen, mit Reserve zu beiden Seiten").

Und: Sieben Zwischenkennzahlen wurden verbessert (Trennlücke, UNKNOWN-Rate,
ERROR-Zahl), bevor überhaupt jemand die einzige Kennzahl ansah, die zählt. Der
Vergleich gegen das Protokoll lief seit Wochen nicht — dabei hätte er sofort
gezeigt, dass der Stand bereits bei 100 % lag und der ROI-Umbau einen Wurf
kostete.

**Konsequenz:** `tools/compare_protocol.py` nimmt jetzt eine `wuerfe.csv` und
ein wählbares Protokoll. Die Blockprobe (je Spielerblock die beste Fundstelle
suchen, statt die Bahn am Stück auszurichten) läuft in Sekunden und gehört vor
jede Bewertung einer Änderung.

## Falsche Nullwürfe: das Zurücksetzen ist kein Wurf (2026-09-03)

Nutzerwunsch: „Wir brauchen eher etwas, was falsche 0en rausnimmt."

**Die 19 Nullwürfe des Spieltags, nach Herkunft getrennt:**

| Herkunft | Anzahl | Tafel-Ziffer | Lage im Abschnitt |
|---|---|---|---|
| `fehlwurfzaehler` | 4 | **immer 0** | mitten im Satz |
| `gruenzyklus` | 15 | **nie vorhanden** | Rand des Abschnitts |

Die Trennung ist vollständig: Jeder echte Nullwurf kommt vom Fehlwurfzähler und
trägt die Ziffer 0 als Beleg.

### Was die acht häufigsten sind

Das Log sagt es in zwei Zeilen direkt untereinander:

```
Bahn 4: Anzeige stand auf 000/0000 -- voriges Spiel endete mit 195 Kegeln
Bahn 4: Wurf 1 erkannt -- 0 Kegel [], Gesamt 0, EMPTY (1.00)
```

Der Grünzyklus, in dem die Anlage **zurücksetzt**, wird als erster Wurf des
neuen Spiels gebucht — mit null Kegeln, weil die Raute leer ist. Dadurch hatten
die betroffenen Sätze 31 statt 30 Würfe.

**Warum `discard_static_zero_cycles` das nicht fing:** Jene Regel verlangt eine
*unveränderte* Wurfnummer. Beim Spielwechsel springt sie von 30 auf 1 — das ist
eine Änderung, also greift sie nicht.

### Zwei Fehlversuche, beide lehrreich

**Erster Versuch — nur die Tafel-Ziffer als Zeugen.** Fünf bestehende Tests
fielen durch. Sie hielten fest, dass es *drei* Zeugen gibt: die Ziffer 0, ein
gestiegener Fehlwurfzähler oder eine um eins weitergezählte Wurfnummer.

**Zweiter Versuch — über die Wurfnummer urteilen** („springt sie von 30 auf 1
zurück?"). Formal richtig, aber **wirkungslos**: Der Vollauf ergab 19 Nullwürfe
vorher, 19 nachher. Genau dort, wo die Fälle entstehen, ist die Wurfnummer
nicht lesbar — die Anzeige steht ja auf null. Und Schweigen darf nichts
verwerfen (BUG-008, dort kostete diese Verwechslung 28 % der Würfe).

**Dritter Versuch — das Spielwechsel-Zeichen.** `display_reset` sagt genau, was
in diesem Moment geschehen ist, und war längst vorhanden. Geprüft an
F48000–72000: Beide Nullwürfe des Abschnitts (F50619, F69502) sind weg, kein
anderer Wurf ging verloren.

**Die Lehre:** Ich habe zweimal nach einem Merkmal in den Zahlen gesucht, statt
zu lesen, was die Anwendung selbst über den Moment sagt. Das Kriterium stand
die ganze Zeit im Log.

### Was offen bleibt

Von den 19 bleiben nach diesem Filter:

* **4 echte** vom Fehlwurfzähler — sollen bleiben
* **5** am Ende eines Warmwerf-Blocks (Wurfnummer 21 nach 20)
* **2** auf Bahn 5 mitten im Block (F15569, F16256)

Bei den Warmwerf-Fällen zählt die Anzeige laut Lesung auf 21 weiter. Ob die
Anlage dort wirklich zählt oder die 21 eine Fehllesung ist, entscheidet nur ein
Blick auf die Stelle.

**Nutzerangabe vom 2026-09-03: Warmwerfen sind immer exakt 20 Würfe.** Geprüft
an den zwölf Blöcken des Spieltags: 11 von 12 stimmen nach Abzug der
Nullwürfe. Das ist ein Prüfstein, der ohne Bodenwahrheit auskommt.

## 2026-09-08 — Direkte Hallenkamera (Reolink, RTSP): Photometrie passt nicht

Gemessen an `rtsp://…10.0.0.8…/h265Preview_02_main`, Kalibrierung
`Training.json`, 464 Frames, laufender Trainingsbetrieb.

**Quelle:** 2304x1296, **15 fps**, h264 (nicht h265, trotz des Pfadnamens).
Kein Overlay — rohes Hallenbild, Tafeln im Hintergrund. Die Bahn-Quads sind
mit 192x192 px sogar groesser als im Overlay (152x154), die GEOMETRIE ist also
in Ordnung. Das Problem ist die Helligkeit.

### Transportweg (Ursache des Hakelns)

Je 12 s, dieselbe Kamera, dieselbe Minute:

| Transport | gelesen | groesste Luecke | Decoder |
|---|---|---|---|
| udp |  4,7 fps | 5089 ms | `error while decoding MB 72 18` |
| tcp | 15,9 fps |  235 ms | fehlerfrei |

Behoben ueber `video.stream_rtsp_transport: "tcp"`.

### Gruene Lampe — Verdeckungsschwelle greift ins Leere

`occlusion_score: 12.0` friert den Zustand ein. Anteil der Frames darunter:

| Bahn | min | p25 | median | p75 | max | Anteil < 12,0 |
|---|---|---|---|---|---|---|
| 2 | 0,0 |  1,3 | 57,1 | 65,6 | 76,6 | **48,3 %** |
| 3 | 3,9 | 11,7 | 65,6 | 72,1 | 79,2 | **25,4 %** |
| 4 | 12,6 | 15,4 | 16,8 | 18,4 | 83,2 | 0,0 % |
| 5 | 0,0 | 54,8 | 64,3 | 66,1 | 68,5 | **23,5 %** |

Im Overlay konnte echtes AUS nicht auf null fallen — das beige Gehaeuse hatte
Gruenanteil, AUS lag bei 20-30, und alles darunter hiess zwingend "verdeckt".
An dieser Kamera faellt AUS auf **0-1**. Die Schwelle liegt damit MITTEN in der
AUS-Wolke statt darunter, und die Bahnen 2, 3 und 5 sind ein Viertel bis die
Haelfte der Zeit eingefroren. Eine eingefrorene Bahn bucht keinen Wurf --
das erklaert "erfasst super wenig Wuerfe".

Bahn 4 liegt mit median 16,8 knapp darueber, aber ohne Reserve.

### Kegellampen — Waermeschranke verwirft fast alles

`score()` liefert `(Waerme, Helligkeit)`. Mediane je Bahn ueber alle 9 Lampen:

| Bahn | Waerme | Helligkeit | gegen `warmth_min: 12,0` |
|---|---|---|---|
| 2 | 3,1 - 17,1 | 137 - 255 | fast alles darunter |
| 3 | 1,2 -  27,3 | 146 - 255 | fast alles darunter |
| 4 | 12,8 - 29,4 | 130 - 255 | knapp darueber |
| 5 | 14,6 - 22,9 |  90 - 103 | darueber, aber dunkel |

Referenz aus dem Overlay: **AUS 154+-23 / AN 254+-3** Helligkeit,
**AUS 19+-10 / AN 57+-13** Waerme.

Zwei Befunde:

1. Auf Bahn 2 und 3 ist die Tafel **ausgebrannt** — Helligkeit 250+ bei Waerme
   unter 8. Die Kamera belichtet auf die dunkle Halle, die LED-Flaeche saettigt
   ins Weisse, und Weiss hat keine Waerme. Die Plausibilitaetsschranke
   `warmth_min` verwirft diese Lampen als UNKNOWN — unabhaengig davon, ob sie
   leuchten. Das ist das "willkuerlich" aus der Nutzermeldung.
2. Bahn 5 liegt bei Helligkeit ~100, Bahn 2 bei ~250. Im Overlay waren alle
   vier Tafeln vom Produzenten angeglichen; hier trennen sie 150 Helligkeits-
   stufen. Eine globale Schwelle kann beide nicht zugleich bedienen.

### Schlussfolgerung

Die Schwellwerte sind samt und sonders am Overlay eingemessen. Fuer diese
Kamera muessen sie NEU gemessen werden -- nicht geschaetzt. Ohne Ground Truth
ist jede Anpassung geraten, und eine geratene Schwelle, die zufaellig auf
zwanzig Frames passt, ist schlimmer als eine dokumentierte Luecke.

Offen: eigener Schwellensatz je Quelle (Overlay / Hallenkamera), und die Frage,
ob die Kamerabelichtung so eingestellt werden kann, dass die Tafel nicht
saettigt.

### Nachtrag desselben Abends: geloest

Die Schlussfolgerung oben ("muss neu gemessen werden") war richtig -- die
Messung liess sich aber noch am selben Abend machen. Ergebnis: DREI Werte, alle
belegt. Sie stehen in `config/hallenkamera.yaml`; `default.yaml` bleibt
unveraendert fuer das Overlay.

**Korrektur an der Zwischendiagnose oben.** Der erste Befund lautete "Waerme
trennt, Helligkeit ist gesaettigt". Das war ein Artefakt meines groben
Histogrammtests ueber ZUSAMMENGELEGTE Lampen. Mit einem echten Trennmass
(Abstand der Wolken durch ihre Streuung), je Lampe gerechnet ueber 354 Muster:

| Bahn | 2 | 3 | 4 | 5 | Overlay-Referenz |
|---|---|---|---|---|---|
| Helligkeit | 8,98 | 18,57 | 3,04 | 7,57 | 7,66 |
| Waerme | 2,76 | 4,73 | 3,10 | 1,70 | 3,35 |

Die Helligkeit traegt hier auf drei von vier Bahnen BESSER als im Overlay. Sie
bleibt das Hauptkriterium; die Regel dahinter war nie falsch.

Der Kernfilter aendert daran nichts -- geprueft mit `core_percentile` 0/50/70/85
an denselben Mustern, Unterschiede unter 1,5 Punkte. Er bleibt auf 0.

**Was tatsaechlich blockierte:** die Waermeschranke. Anteil der LEUCHTENDEN
Messungen, den `warmth_min` verwirft:

| warmth_min | median verworfen | Lampen mit >50 % Verlust |
|---|---|---|
| 12,0 (default) | 89,5 % | 22 von 36 |
| 6,0 | 48,2 % | 18 von 36 |
| **0,0** | **0,0 %** | **0 von 36** |

Je Bahn: Bahn 2 verlor 93-100 %, Bahn 3 92-99 %, Bahn 4 **0 %**, Bahn 5 0-90 %.
Daher der Eindruck "willkuerlich" -- eine Bahn ging, die andere nie. Ursache:
Auf Bahn 2 und 3 brennt die Tafel aus, die leuchtende Lampe saettigt ins
Weisse, und Weiss hat keine Waerme.

Gegenprobe an denselben 12 744 Messungen, alter gegen neuer Satz:

| | AN | AUS | UNBEKANNT |
|---|---|---|---|
| default.yaml | 621 (4,9 %) | 8341 | 3782 (29,7 %) |
| hallenkamera.yaml | 4292 (33,7 %) | **8341** | 111 (0,9 %) |

Die AUS-Zahl ist IDENTISCH. Es wurde keine erloschene Lampe zu "AN"
umgedeutet -- der Fix holt ausschliesslich vorher unentscheidbare zurueck.

**Dritter Wert: `stream_restart_check: false`.** Der erste Lauf mit den neuen
Schwellen brach nach 1,5 min ab: "Der Stream hat wieder von vorn begonnen
(Frame 1333)". Fehlalarm. Eine feste Kamera auf eine unbewegte Halle liefert so
aehnliche Anfangsbilder, dass mehrere denselben Fingerabdruck bekommen und eine
zufaellig aufsteigende Kette entsteht. Beim Overlay wechselte staendig das
Kamerabild; dort trat das nie auf. Eine RTSP-Kamera hat ohnehin keine
Aufzeichnung, zu der sie zurueckspringen koennte.

**Ergebnis im Betrieb**, 1,5 min live gegen die Kamera:
12 Gruenzyklen, 12 Wuerfe, Status `{'VALID': 12}`. Vorher nahezu nichts.

---

## Sitzt der automatisch gefundene Rahmen? (2026-09-10)

**Frage des Nutzers**, beim Blick auf die Übersicht: *„ist vielleicht die Maske
schlecht? weil der nimmt ja nicht ansatzweise den klaren Rand der Tafel"*

### 1. Wo liegt die Rahmenkante gegenüber der Bildkante?

Gemessen **lokal**, nicht über eine globale Maske: senkrecht zu jeder
Rahmenkante ein Streifen von ±14 px, darin die stärkste Helligkeitsänderung,
Median über 41 Stützstellen. Negativ = die stärkste Kante liegt *innerhalb* des
Rahmens.

| | oben | rechts | unten | links |
|---|---|---|---|---|
| **automatisch** | −4,2 (σ 3,3) | −0,2 (σ 1,3) | −7,5 (σ 4,9) | +1,5 (σ 1,5) |
| **von Hand** | −6,5 (σ 3,5) | −2,2 (σ 1,1) | −6,8 (σ 4,0) | +2,0 (σ 0,0) |

**Die Handkalibrierung rahmt genauso.** Der Rahmen ist also nicht „falsch"
gesetzt, sondern folgt derselben Auffassung davon, wo die Tafel endet.

*Grenze dieser Messung:* Oben und unten liegt innerhalb von 14 px das dunkle
Anzeigefenster — die stärkste Kante dort ist dessen Rand, nicht die Silhouette
des Gehäuses. Belastbar sind deshalb nur **links und rechts**, und dort sitzt
der Rahmen auf 1–2 px.

**Ein gleichmäßiger Versatz ist ohnehin harmlos:** Die ROIs liegen in
normierten Tafelkoordinaten *derselben* Bezugsfläche. Verschiebt sich der
Rahmen um 5 px, verschieben sich die ROIs mit — relativ zur Tafel bleibt alles,
wo es war.

### 2. Sitzen die ROIs? — gemessen an den dunklen Anzeigefenstern

`total_a` und `left_display` sind schwarze Rechtecke auf beigem Gehäuse. Ihre
Kanten sind unabhängig davon, welche Lampen brennen und welche Ziffern stehen.
Verglichen wird der Schwerpunkt des dunklen Fensters mit der Mitte der ROI.

Frame 84750, vier Tafeln, zwei Felder je Tafel:

| | dx | dy | Streuung |
|---|---|---|---|
| automatisch | −0,9 px | −1,3 px | 0,8 / 0,9 |
| von Hand | −0,2 px | −1,8 px | 0,8 / 0,5 |

Der systematische Anteil (dy ≈ −1,5 px) ist in **beiden** gleich — er steckt in
den ROI-Definitionen selbst, nicht im Finden der Tafel.

### 3. Streuung zwischen unabhängigen Suchläufen

Acht Läufe an verschiedenen Stellen des Spiels, 31 gefundene Tafeln, Betrag des
ROI-Versatzes:

```
Mittel 2,38 px    Streuung 0,77 px    größter 4,0 px
```

Zum Vergleich die Handkalibrierung nach demselben Maß: **2,0 px**.

Nach Position von links:

| Tafel | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| mittlerer Versatz | **1,8 px** | 2,6 px | 2,5 px | 2,8 px |

Die linke Tafel sitzt am besten, die rechte rund einen Pixel schlechter — ein
schwacher Trend, kein Ausreißer. Sieben von acht Läufen fanden alle vier.

**Einordnung:** Ein Pixel entschied bei der Ziffernerkennung über neun
Prozentpunkte (54 → 60 von 66 Stellen). Ein mittlerer Versatz von 2,4 px ist
für die Lampen unerheblich und für die Ziffern nicht — genau dafür gibt es
„Ziffern verschieben".

---

## Vier Versuche, die Ecken genauer zu treffen (2026-09-10)

**Einwand des Nutzers:** *„es sitzt immer noch krumm und schief … da können
Ziffern halt einfach nicht passen"* und *„die Tafeln sind doch klar vom
Hintergrund abgesetzt? … das kann doch jeder gute CV-Ansatz eigentlich lösen?"*

### Der richtige Maßstab

Der erste Maßstab — Abstand zwischen ROI-Mitte und der Mitte des dunklen
Anzeigefensters — hat einen **systematischen Anteil**: Die ROIs sind von Hand
gesetzt und sitzen nicht zwangsläufig mittig. Der taugt für einen Vergleich
nicht.

**Die vier Tafeln sind baugleich.** Also ist die richtige Größe die *Streuung
zwischen ihnen*: Sitzt die Kalibrierung, sehen alle vier gleich aus. Der
Mittelwert darf beliebig sein.

### Was gemessen wurde

Frame 84750, Streuung der ROI-Lagen über die vier Tafeln, in Pixeln der
Originaltafel (rund 160 px Kantenlänge):

| Verfahren | Streuung |
|---|---|
| von Hand gesetzt | **0,89** |
| Merkmalsabgleich (Ausgangslage) | 1,35 |
| + Kanten nachziehen (Hochpass) | 1,90 |
| + ECC-Feinjustierung über alle Pixel | 2,34 |

**Beide Verbesserungsversuche machen es schlechter.** Beide sind verworfen.

*Warum:* Nachziehen verschiebt die **Bezugsfläche** — die ROIs liegen in
normierten Koordinaten des Vierecks, das der Vorlage entspricht. ECC richtet
auf das *Musterbild* aus und zieht dabei an genau den Stellen, die sich
unterscheiden: brennende Lampen, wechselnde Ziffern.

### Was doch hilft: über die Funde mitteln

Die Suche sammelt je Tafel mehrere Funde aus verschiedenen Bildern und warf
bisher alle bis auf den mit den meisten tragenden Merkmalen weg. Acht Stellen
des Spiels, je bis zu zwölf Bilder:

| Stelle | Funde je Tafel | bester | Median |
|---|---|---|---|
| 0 | 13/12/12/11 | 0,85 | **0,74** |
| 42375 | 11/13/12/12 | 1,02 | **0,94** |
| 84750 | 12/12/13/12 | 1,05 | **0,95** |
| 127125 | 11/11/9/8 | 1,29 | **1,20** |
| 169500 | 11/8/10/8 | 1,04 | **0,95** |
| 254250 | 5/7/6/4 | 1,80 | 1,80 |
| 300000 | 6/12/11/2 | 2,96 | **2,20** |
| 317812 | 12/13/12/6 | 1,24 | **1,20** |
| **Mittel** | | **1,41** | **1,25** |

Der Median gewinnt in allen acht Fällen oder liegt gleichauf. Übernommen.

Sichtbar ist außerdem: **Wo viele Funde vorliegen, ist die Streuung klein.**
Bei 11–13 Funden je Tafel liegt sie um 0,9 px, bei 2–7 Funden über 1,8 px.
Mehr Standbilder sammeln lohnt sich also unmittelbar.

### Warum die Kontur nicht reicht

Die Idee, die Tafel als helles Viereck auf dunklem Grund zu finden, ist
richtig — aber im Bildmaterial nur zu drei Vierteln wahr:

* **links, rechts, unten** grenzt die Tafel an dunkles Overlay. Dort sitzt der
  Rahmen laut Hochpassmessung auf **0 bis 2 px** genau.
* **oben** grenzt sie an die beige Hallenwand, und die beige Leiste des
  Gehäuses ist nur rund fünf Pixel breit. Dort greift keine Trennung.

Eine globale Farbmaske scheitert vollständig: In der Halle ist alles beige —
Bahnen, Wand, Tafeln (siehe `debug/silhouette_maske.png`, 0 Kandidaten).

---

## Ziffern-Selbstausrichtung: gebaut, gemessen, verworfen (2026-09-10)

**Wunsch des Nutzers:** *„die Ziffern sollten zusätzlich nochmal die Chance
bekommen sich selbst nachzukalibrieren … die sitzen immer bisschen schlecht"*

### Die Idee

Jedes Ziffernfeld sitzt in einem schwarzen Anzeigefenster auf beigem Gehäuse.
Dessen Kanten hängen **nicht** davon ab, was gerade angezeigt wird — damit
wäre es das erste **ergebnisunabhängige** Kriterium für den Ziffernversatz.
Das Fenster im Musterbild und in der gefundenen Tafel vermessen, die Differenz
ist der Versatz.

### Was die Messung zunächst sagte

Restversatz gegenüber dem Musterbild, vier Tafeln × fünf Felder:

| | Mittel | schlechteste Bahn |
|---|---|---|
| vorher | 2,02 px | 5,33 px |
| nachher | **0,00 px** | 0,00 px |

### Warum das falsch war

Der Nutzer sah es sofort im Bild: *„die 2. Bahn ist die einzige die okay ist,
der Rest ist ja ganz wild verschoben."* Und er hatte recht.

Die Messung war **zirkulär**: Sie prüfte, ob das Feld nach der Verschiebung
so zum Schwerpunkt liegt wie im Muster — und genau darauf war verschoben
worden. Sie musste null ergeben, egal wie unsinnig der Ruck war.

Die Gegenprobe deckte die Ursache auf. Schwerpunkt und Rahmenmitte des
gefundenen „Fensters" für `left_display` und für die untere Zeile lieferten
**denselben Wert**:

```
Bahn 1: 0,56 / 0,56 / 0,56    Bahn 2: 1,30 / 1,30 / 1,30
Bahn 3: 0,98 / 0,98 / 0,98    Bahn 4: 3,05 / 3,05 / 3,05
```

Die dunklen Fenster hängen zu **einem** Gebilde zusammen. Was gemessen wurde,
war nicht das Fenster eines Feldes, sondern ein Blob über mehrere Fenster —
und dessen Schwerpunkt wandert mit den **leuchtenden Ziffern**, die sich in
die dunkle Fläche fressen. Auf Bahn 4 ergab das einen Ruck von 5,3 px in die
falsche Richtung.

Ein Schließen der Maske (31 px) macht es nicht besser: Dann verschmilzt die
halbe Tafel zu einer Fläche, und für drei von vier Bahnen wird gar nichts mehr
gefunden.

**Verworfen und zurückgebaut.** Die Lehre: Ein Maß, das nach der Korrektur
misst, was die Korrektur hergestellt hat, beweist nichts. Es braucht einen
Bezug, der von der Korrektur unberührt bleibt — hier wäre das der Blick aufs
Bild gewesen, und der kam vom Nutzer.

### Was als Anker noch in Frage kommt

* die **Lampenlöcher** — physisch, immer an derselben Stelle, aber im
  Aussehen stark wechselnd (an/aus)
* das **FUNK-Logo** — aufgedruckt, unveränderlich, aber klein und kontrastarm
* die **Gehäusekanten** — links, rechts und unten auf 0–2 px messbar, oben
  nicht (die beige Leiste ist nur rund fünf Pixel breit)

---

## Nachlauf: nach dem Fund weitersammeln (2026-09-10)

Die Ecken werden über die Funde gemittelt — und gegen Schätzrauschen hilft
Mitteln nur, wenn es genug zu mitteln gibt:

| Funde je Tafel | Streuung der ROI-Lagen |
|---|---|
| 11–13 | **0,9 px** |
| 2–7 | 1,8 px |

Die Suche war bisher meist nach **zwei bis vier** Bildern vollständig — genau
im schlechten Bereich. Sie hört jetzt nicht mehr beim Fund auf, sondern sammelt
`boardtype_nachlauf_bilder` (6) weiter.

Gemessen über acht Stellen des Verbandsligaspiels:

| Stelle | ohne Nachlauf | | mit Nachlauf | |
|---|---|---|---|---|
| | Bilder | Streuung | Bilder | Streuung |
| 0 | 3 | 0,94 | 9 | **0,72** |
| 42375 | 3 | 1,71 | 9 | **1,26** |
| 84750 | 2 | 1,06 | 8 | 1,07 |
| 127125 | 6 | 1,87 | 12 | **1,22** |
| 169500 | 6 | 1,05 | 12 | **0,88** |
| 254250 | 10 | 1,69 | 14 | **1,63** |
| 300000 | 12 | 2,42 | 14 | 3,33 |
| 317812 | 7 | 6,28 | 13 | **1,13** |
| **Mittel** | | **2,13** | | **1,40** |

Besser an sechs von acht Stellen, gleichauf an einer, schlechter an einer. Der
größte Gewinn: 6,28 → 1,13 px.

Kosten im Livestream rund fünf Sekunden. Die Zeitgrenze (`boardtype_live_timeout_s`)
deckelt auch den Nachlauf — sonst hinge die Suche fest, wenn die Bilder nicht
schnell genug kommen.

---

## Ziffern an den Nullen ausrichten (2026-09-10)

**Vorschlag des Nutzers:** *„wie wäre es, wenn er Anfangs die Ziffern ganz
unten verschiebt, bis er die 0en halbwegs sicher sieht? Auch bei der
Fehlwurfanzeige? so können wir das niemandem als ‚automatisierte
Kalibrierung' verkaufen…"*

### Warum das nicht zirkulär ist

Zu Spielbeginn steht auf der Tafel `000`, `0`, `0000` — ein **bekannter
Sollwert**, keine Vermutung. Verschoben wird also nicht auf die Lesequalität
hin, sondern auf einen Inhalt, der unabhängig davon feststeht. Genau daran war
der Versuch mit den Anzeigefenstern gescheitert.

Gesucht wird die **Mitte des Plateaus** aus Versätzen, die alle Stellen sicher
als Null lesen — nicht der beste Einzelpunkt. Ein Rahmen am Rand des lesbaren
Bereichs liest heute richtig und morgen nicht.

### Der Maßstab: Anteil unlesbarer Stellen

Unabhängig von jeder Justage; gezählt wird, wie oft der Leser `?` sagt.

**Was die Bauart-Korrektur brachte** (Verbandsligaspiel, 8 Frames mitten im
Spiel, 320 Stellen):

| Kalibrierung | unlesbar | Anteil |
|---|---|---|
| von Hand | 18 / 320 | **5,6 %** |
| automatisch, alte Bauart | 51 / 320 | 15,9 % |
| automatisch, korrigierte Bauart | 25 / 320 | **7,8 %** |

**Was die Nullpassung bringt** (Hallenstream, angepasst an *einem* Bild,
gemessen an *acht späteren*):

| | unlesbar | Anteil |
|---|---|---|
| ohne | 69 / 320 | 21,6 % |
| mit Nullpassung | 56 / 320 | **17,5 %** |

### Zwei Befunde nebenbei

**KORREKTUR (vom Nutzer richtiggestellt).** Ich hatte die Fehlwurfanzeige mit
`pin_count` verwechselt. Sie ist `left_display` (`detection.foul_field`), zeigt
zu Spielbeginn `00` und liest sich sauber — sie fehlte in der Liste der
Nullfelder und ist jetzt drin.

`pin_count` — das Feld in der **Mitte** der unteren Zeile — ist tatsächlich
dunkel und zeigt keinen Wert, auch keine Null. Auf Nullen einstellen lässt es
sich also nicht. Der Nutzer kennt die Anlage:

> „der Abstand zwischen der linkesten 0 bei Gesamtsumme und dem rechtesten bei
> Wurfnummer zu dem Wert in der Mitte ist immer identisch"

Dieselbe Anzeigezeile, derselbe Versatz. `pin_count` **erbt** deshalb den
Mittelwert dessen, was für Wurfnummer und Gesamtsumme gefunden wurde.

Voller Durchlauf am Hallenstream danach: 8 Bilder in 6,4 s, 4 Tafeln mit 386
tragenden Merkmalen, **9 Ziffernfelder auf 4 Bahnen** an den Nullen
ausgerichtet.

**Nicht jede Aufnahme bietet Nullen.** Im Verbandsligavideo zeigt in den ersten
vier Minuten (24 Stichproben) kein einziges Feld durchgehend Nullen — die
Aufzeichnung beginnt mitten im Einspielen. Dort feuert die Nullpassung nicht
und ändert nichts. Das ist beabsichtigt.

### Die obere rechte Ecke

Der Nutzer wies auf die Ecken hin. Gemessen an der nächsten Bildkante,
Hallenaufnahme:

| Bahn | Ecke oben rechts | y | Abweichung senkrecht |
|---|---|---|---|
| 1 | | 49 | +1 |
| 2 | | 46 | −2 |
| 3 | | 49 | +0 |
| **4** | | **59** | **+10** |

Bahn 4 sitzt zehn Pixel zu tief, und ihre obere Kante fällt über die Breite um
elf Pixel ab. Das ist keine Perspektive — die vier Tafeln hängen in einer
Reihe — sondern ein Schätzfehler des Merkmalsabgleichs auf der äußersten
Tafel. **Offen.**

---

## Bild in Bild ersetzt den Merkmalsabgleich (2026-09-10)

**Entscheidung des Nutzers:** *„wir lassen alle deine Ansätze und fangen doch
an, automatische Kalibrierung darüber, das Bild in Bild gesucht wird … dann
kann man das Bild auch bisschen verzerren und verkippen lassen."*

### Was dabei möglich wird, was ORB nie konnte

Die **veränderlichen Teile lassen sich ausblenden**. Brennende Kegellampen und
wechselnde Ziffern sind genau das, woran der Merkmalsabgleich scheitert — und
aus der Bauart wissen wir, wo sie liegen. `matchTemplate` rechnet mit einer
Maske; ORB kann das nicht.

### Die Maske hatte ein Loch

Die obere Leiste der Tafel ist eine **Matrixanzeige mit wechselndem Text**. Sie
ist als einzige Fläche kein ROI und blieb deshalb unmaskiert. ZNCC an der von
Hand gesetzten Kalibrierung, acht Stellen des Spiels:

| | ohne Leistenmaske | mit Leistenmaske |
|---|---|---|
| 84750 | 0,684 | 0,577 |
| 42375 | 0,680 | 0,573 |
| 127125 | **−0,009** | 0,524 |
| 169500 | **−0,005** | 0,525 |
| 211875 | **−0,010** | 0,523 |
| 254250 | **−0,006** | 0,527 |
| 300000 | **−0,015** | 0,529 |
| 330000 | **−0,026** | 0,518 |

An sechs von acht Stellen war die Übereinstimmung **exakt null**. Maskiert wird
die Leiste als *eigenes Rechteck*, nicht als Band über das obere Drittel — ein
Band nähme die beiden oberen Fenster mit, und die sind die stabilsten Merkmale
der Tafel (Streuung 0,02–0,04 px über 20 Frames).

### Warum die Güte eigens gerechnet wird

`TM_CCORR_NORMED` mit Maske ist über verschiedene **Vorlagengrößen** nicht
vergleichbar: Eine kleiner gerechnete Vorlage erreicht fast überall höhere
Werte. Wer damit den Maßstab wählt, landet am Rand des Rasters — gemessen an
zwei von vier Stellen, Streuung 14,8 statt 0,8 px. Die *Lage* wird deshalb
weiter mit `matchTemplate` gesucht, die *Auswahl* zwischen Maßstäben über den
maskierten ZNCC im entzerrten Raum.

### Das Ergebnis

Acht Stellen des Spiels, Streuung der ROI-Lagen zwischen den vier baugleichen
Tafeln:

| Start | Merkmalsabgleich | Bild in Bild |
|---|---|---|
| 0 | 0,94 | 0,98 |
| 42375 | 1,26 | **0,97** |
| 84750 | 1,07 | 1,08 |
| 127125 | 1,22 | **1,16** |
| 169500 | 0,88 | 0,92 |
| 254250 | 1,63 | **0,92** |
| 300000 | **3,33** | **0,92** |
| 317812 | 1,13 | **1,03** |
| **Mittel** | **1,43** | **1,00** |

Zum Vergleich die Handkalibrierung: **0,89 px**.

Wichtiger noch als der Mittelwert: **Alle acht Stellen finden alle vier
Tafeln.** Der Merkmalsabgleich schaffte das an dreien nicht, und sein
schlechtester Wert war mit 3,33 px unbrauchbar.

### Der Preis und wie er gedrückt wurde

| | Zeit je Kalibrierung |
|---|---|
| Merkmalsabgleich | ~7 s |
| Bild in Bild, volles Raster jedes Mal | 98 s |
| + Maßstab nach dem ersten Fund merken | 27–42 s |
| + Suchgegend merken | **16 s** |

Die Suchgegend schränkt nur die **Höhe** ein, nicht die Breite: Die Tafeln
stehen in einer Reihe, und wer die Breite aus dem ersten Bild ableitet,
schließt die Tafeln aus, die dort noch fehlten (gemessen: 3 statt 4).

### Verkippung: die Ecken einzeln nachziehen (2026-09-10)

Maßstab und Drehung allein beschreiben nur eine **Ähnlichkeit**. Die vier
Tafeln im Overlay stehen unterschiedlich schräg — die äußeren werden stärker
perspektivisch verzerrt gesehen. Nach dem Fund wird deshalb jede Ecke einzeln
versetzt und behalten, was den maskierten ZNCC verbessert.

Wie weit gesucht wird, ist gemessen und nicht geraten: Die Kippung einer
Rahmenkante gegen die Bildkante lag bei bis zu **9 px**, im Mittel 2,3 (16
Kanten). Drei Pixel je Ecke und Runde decken das ab.

Dazu **getrennte Maskenränder**: Bei den Lampen greift der Schein weit über
die ROI hinaus (2,2 %), bei den Ziffern nicht (0,8 %) — dort fraß der große
Rand die erhabenen Fensterrahmen mit weg.

| Verfahren | Streuung | Zeit |
|---|---|---|
| Merkmalsabgleich | 1,43 px | ~7 s |
| Bild in Bild | 1,00 px | 16 s |
| + getrennte Ränder | 0,97 px | 20–24 s |
| **+ Verkippung** | **0,76 px** | 24–32 s |
| von Hand gesetzt | 0,89 px | Minuten |

Damit sitzt die automatische Kalibrierung erstmals **besser als die von
Hand**. Je Stelle:

| Start | Merkmale | Bild in Bild + Verkippung |
|---|---|---|
| 0 | 0,94 | 0,91 |
| 42375 | 1,26 | **0,55** |
| 84750 | 1,07 | 0,76 |
| 127125 | 1,22 | 0,98 |
| 169500 | 0,88 | 0,69 |
| 254250 | 1,63 | 0,69 |
| 300000 | 3,33 | 0,72 |
| 317812 | 1,13 | 0,78 |

## Personenmodell auf dem Tafelband (2026-09-13)

**Material.** Livestream "Fastlane" (Overlay, 1920x1080, 25 fps), Kalibrierung
`data/calibrations/Fastlane.json`. Tafeln 134-136 px breit, alle in einem Band
y = 71..217, x = 534..1378. Beweisstellen aus dem Vollauf vom selben Tag:
F42177-42246 (Mensch laeuft durch die Gruenphase von Bahn 2), F265667-265736
(Mensch laeuft ueber die Tafeln 2 und 3), F305359-305393 (Streamende, keine
Halle), F100000-100599 (600 Frames Normalbetrieb ohne Menschen).

**Modell.** YOLOv8n, aus `yolov8n.pt` (Ultralytics, AGPL-3.0) nach ONNX
exportiert, gelesen mit `cv2.dnn` (OpenCV 5.0, CPU). Nur Klasse 0 (person).

### Der Zuschnitt entscheidet

| Zuschnitt | Laeufe/Frame | F42177-42246 | F265667-265736 | Fehlalarme/600 | ms/Frame |
|---|---|---|---|---|---|
| Tafel allein (136x136) | 4 | 19 / 70 | 37 / 70 | 0 | 263 |
| Tafel + 100 % Luft | 4 | 55 / 70 | 70 / 70 | 0 | 266 |
| Tafel + 300 % Luft | 4 | 61 / 70 | 70 / 70 | 0 | 268 |
| Band ueber alle Tafeln | 1 | 53 / 70 | 62 / 70 | 0 | 62 |
| Band + 100 % nach unten | 1 | 57 / 70 | 69 / 70 | 0 | 68 |
| Band + 200 % nach unten | 1 | 57 / 70 | 69 / 70 | 0 | 97 |

Gewaehlt: **Band + 100 % nach unten**, ein Lauf je Frame.

Gegenprobe an den 1682 Tafelbildern, die im Vollauf wirklich an die Datenbank
gingen (`debug/fastlane_bilder/`): auf dem blanken Ausschnitt **0 von 2**
bekannten Gesichtern gefunden, dafuer 1 Fehlalarm (F305389, Hallenboden).
Das ist dieselbe Aussage wie Zeile 1 der Tabelle, an echtem Material.

### An der Beweisstelle

Die zehn Frames, in denen der Gruen-Score von Bahn 2 auf exakt 0,0 fiel:

| Frame | Tafel bedeckt | Gruenlampe bedeckt | Vertrauen | Ampel |
|---|---|---|---|---|
| 42222 | 35 % | 100 % | 0,81 | 63,9 |
| 42224 | 38 % | 100 % | 0,86 | **0,0** |
| 42226 | 40 % | 100 % | 0,82 | **0,0** |
| 42228 | 41 % | 100 % | 0,86 | **0,0** |
| 42230 | 29 % | 100 % | 0,77 | **0,0** |
| 42232 | 34 % | 100 % | 0,71 | **0,0** |
| 42233 | 34 % | 100 % | 0,71 | **0,0** |
| 42235 | 29 % | 100 % | 0,82 | 70,8 |

Auf den Bahnen 3, 4 und 5 meldet das Modell in denselben Frames nichts.

### Modellwahl (2026-09-14)

Alle im selben Zuschnitt gemessen (Band + 100 % nach unten), conf 0,25:

| Modell | Eingang | F42177-42246 | F265667-265736 | Fehlalarme/600 | Netz | Groesse | Lizenz |
|---|---|---|---|---|---|---|---|
| YOLOv8n | 640 | 57 / 70 | 69 / 70 | 0 | 62 ms | 12,8 MB | **AGPL-3.0** |
| YOLOv8n | 320 | 45 / 70 | -- | 0 | 17 ms | 12,7 MB | **AGPL-3.0** |
| YOLOX-S | 640 | 57 / 70 | 69 / 70 | 0 | 100 ms | 35,9 MB | Apache-2.0 |
| **YOLOX-Tiny** | **416** | **55 / 70** | **68 / 70** | **0** | **28 ms** | 20,2 MB | Apache-2.0 |
| YOLOX-Nano | 416 | 55 / 70 | 64 / 70 | 0 | 13 ms | 3,7 MB | Apache-2.0 |
| YOLOX-S int8 | 640 | -- | -- | -- | 227 ms | 9,1 MB | Apache-2.0 |
| NanoDet-Plus | 416 | -- | -- | -- | -- | 3,8 MB | Apache-2.0 |

**GEWAEHLT: YOLOX-Tiny.** Zwei Gruende, und der Lizenzgrund ist nur der
zweite. Das Projekt steht unter MIT, und ein Werk mit AGPL-Teilen kann nicht
unter MIT stehen -- Ultralytics-Modelle scheiden damit aus. Der Punkt ist
aber: Es kostet nichts. YOLOX-Tiny ist mit 28 ms **mehr als doppelt so
schnell** wie YOLOv8n und verliert zwei von 70 Beweisframes.

Gegen YOLOX-Nano (nochmals halb so teuer) entschied der Abstand zur Schwelle.
An den zehn Frames, in denen die Ampel auf 0,0 fiel:

| Frame | 42224 | 42226 | 42228 | 42230 | 42232 | 42233 |
|---|---|---|---|---|---|---|
| YOLOX-Tiny | 0,77 | 0,83 | 0,81 | 0,73 | 0,73 | 0,75 |
| YOLOX-Nano | 0,54 | 0,66 | 0,72 | 0,72 | 0,63 | 0,64 |

Beide finden ihn in allen zehn, Tiny mit deutlich mehr Reserve -- und auf der
zweiten Beweisstrecke 68 statt 64 von 70 Frames. Bei einer Schutzfunktion,
deren Versagen ein Gesicht in eine oeffentliche Datenbank traegt, zaehlt die
Reserve mehr als 15 ms.

Die int8-Fassung ist mit OpenCVs DNN-Modul LANGSAMER als das float-Original
(227 statt 100 ms) -- es fehlen die passenden Kerne. NanoDet-Plus liess sich
mit OpenCV 5.0 gar nicht auswerten: Die Nachbereitung des OpenCV Zoo setzt eine
Reihenfolge der Netzausgaenge voraus, die diese Version nicht liefert
(`IndexError` in `post_process`). Nicht weiterverfolgt.

**Fallstrick bei YOLOX:** Es erwartet rohe BGR-Werte 0..255 als float --
KEIN Teilen durch 255, keine Mittelwertkorrektur. Beides steckt im Netz. Wer
normalisiert, bekommt ein Netz, das nichts mehr findet, ohne dass irgendwo ein
Fehler auftaucht. Und die Kaesten kommen gegen ein Ankergitter, das aus der
Eingangskante gerechnet wird: Passt `input_size` nicht zur Modelldatei, liegen
die Funde plausibel aussehend an der falschen Stelle.

### Wie oft das Modell ueberhaupt laufen muss

GEMESSEN ueber 20 000 Frames des Livestreams: In **1,95 %** der Frames faellt
ueberhaupt eine Bahn unter ihre Verdeckungsschwelle (alle 389 auf Bahn 4,
keine einzige auf 2, 3 oder 5). Ohne Streife saehe das Modell also nie den
Menschen, der auf der Tafel steht, ohne die gruene Lampe zu beruehren --
deshalb `patrol_interval: 10`.

### Schwaerzung, durch den echten Weg gemessen

Nicht der Modellausgang, sondern das Ergebnis von `encode_board` -- dieselbe
Zeichenkette, die als `board_jpeg` in die Datenbank ginge. Anteil dunkler
Pixel (< 24 nach JPEG q40):

| | F42237 (Bahn 2) | F265727 (Bahn 2) |
|---|---|---|
| ohne Schwaerzung | 27,6 % | 21,4 % |
| nur Tafelwache | 27,6 % | 21,4 % |
| Wache + Personenmodell | **47,2 %** | **34,0 %** |

Beide Gesichter vollstaendig verdeckt, Beleg `debug/schwaerzung_mit_modell.png`.

### Was das Modell wirklich kostet -- und was ein festhaengender Zeuge anrichtet

Voller Lauf ueber den Hallenmitschnitt (13 530 Frames, 15 fps, Kalibrierung
`debug/aktuell_mitschnitt.json`):

| | Wuerfe | Frames/s | ms/Frame | Netzlaeufe |
|---|---|---|---|---|
| ohne Modell | 64 | 32 | 31,4 | -- |
| YOLOv8n, ohne Mindestabstand | 64 | 11 | 88,9 | 94 % der Frames |
| YOLOv8n, Abstand je Bahn (5) | -- | -- | -- | 33 % |
| YOLOv8n, Abstand ueber alle Bahnen (5) | 64 | 21 | 48,0 | 20 % |
| **YOLOX-Tiny, Abstand ueber alle Bahnen (5)** | **64** | **27** | **37,1** | **20 %** |

**Keine Regression: 64 Wuerfe in allen Faellen** -- und nicht nur der Zahl
nach: Frames, Bahnen, Kegelzahlen und Kegelnummern sind Zeile fuer Zeile
identisch (`debug/regression_aus.csv` gegen `debug/regression_an.csv`).

Der Aufschlag betraegt mit dem ausgelieferten Modell **5,7 ms je Frame** ueber
den ganzen Lauf (YOLOv8n waeren 16,6 gewesen). Und das ist der Preis auf der
Aufnahme mit der festhaengenden Bahn 5 -- dem schlechtesten bekannten Fall.
Wo kein Zeuge festhaengt, traegt allein die Streife, also ein Zehntel von
28 ms.

Die 94 % waren kein Rechenfehler, sondern ein Befund. Ueber 3000 Frames:

| Bahn | Gruen unter Schwelle | Personenmaske | Tafelwache | Streife |
|---|---|---|---|---|
| 2 | 482 | 9 | 0 | 300 |
| 3 | 0 | 0 | 0 | 300 |
| 4 | 0 | 0 | 0 | 300 |
| **5** | 0 | 75 | **2704** | 300 |

**Auf Bahn 5 meldet die Tafelwache in 90 % der Frames Fremdes.** Diese Bahn
steht auf dieser Aufnahme dauerhaft in der Verdeckungsbremse -- das Protokoll
sagt es selbst: *"Bahn 5: seit 2250 Frames (90 s) verdeckt, Gruen-Score 73,4
-- kommt hier nichts mehr, passt womoeglich die Kalibrierung nicht zu dieser
Tafel"*. Ein Gruen-Score von 73,4 heisst: Die Lampe ist klar AN und gut
sichtbar. Die Wache irrt hier, oder die Kalibrierung passt nicht.

**Das ist ein eigener, aelterer Befund und nicht vom Modell verursacht** --
aber er zeigt, warum ein Ausloeser allein die Kostenrechnung nicht traegt: EIN
festhaengender Zeuge genuegt, um teure Analyse in jeden Frame zu ziehen. Daher
der Mindestabstand, und daher zaehlt er ueber alle Bahnen: Das Netz sucht in
einem Band ueber alle vier Tafeln, seine Antwort gilt fuer alle zugleich.

OFFEN: Warum die Wache auf Bahn 5 dieses Mitschnitts festhaengt. Das Modell
koennte es beantworten (sieht es dort einen Menschen oder nicht) -- gemessen
ist es nicht, und ohne Messung wird die Bremse nicht gelockert.

### Steht auf Bahn 5 wirklich ein Mensch? (2026-09-14)

Die Frage aus der Kostenmessung: Die Tafelwache meldete auf Bahn 5 des
Hallenmitschnitts in 90 % der Frames Fremdes, bei einem Gruen-Score von 73 --
also klar sichtbarer Lampe. Ein Mensch, oder eine falsche Referenz?

Gemessen auf einem festen Raster ueber alle 13 530 Frames, 541 Messpunkte je
Bahn, mit dem Personenmodell als unabhaengigem Zeugen:

| Bahn | Wache meldet | Modell sieht einen Menschen | Wache-Abweichung Median | Ampel Median |
|---|---|---|---|---|
| 2 | 1,3 % | 4,2 % | 1,2 % | 58,7 |
| 3 | 0,0 % | 0,0 % | 0,0 % | 76,2 |
| 4 | 0,0 % | 0,0 % | 0,0 % | 66,2 |
| **5** | **98,3 %** | **0,6 %** | **25,2 %** | 72,7 |

**Kein Mensch.** Und der Beweis liegt nicht nur im Modell, sondern in der
Verteilung selbst: Auf den 533 Messpunkten mit Wache-Alarm betraegt die
Abweichung im Median 25,2 % und im MAXIMUM 26,0 %. Median gleich Maximum heisst
voellig unbewegt -- ein Mensch schwankt.

Der Verlauf zeigt, wann es passierte:

```
F0   bis F215    0,0 bis 3,4 %     Referenz wird gelernt
F215 bis F220    3,4 -> 13,0 %     Sprung ueber die Nachlernschwelle (10 %)
F220 bis F13530  25,2 %            festgehakt
```

Das Differenzbild (`debug/bahn5_referenz.png`) zeigt doppelte Kanten an jedem
Rahmen: derselbe Ausschnitt, um wenige Pixel versetzt. Der Nutzer kannte die
Ursache -- am Anfang dieser Aufnahme hatte jemand hinten die Klappe geoeffnet;
die Szene war also gerade untypisch, als die Referenz gelernt wurde, und kehrte
danach in ihren Normalzustand zurueck.

Siehe BUG-026. Der Fix ist NICHT auf diesen Videoanfang gemuenzt: Dieselbe
Sperre schnappt bei jeder Aenderung mitten im Lauf zu.

| | vorher | mit Erholung |
|---|---|---|
| Dauerwarnungen "seit N Frames verdeckt" | 17 | **0** |
| Wuerfe | 64 | **64**, Zeile fuer Zeile gleich |
| ms/Frame | 37,1 | **35,6** |

Schneller, weil das Personenmodell nicht mehr von der festhaengenden Wache in
jeden Frame gezogen wird.

## Die Verdeckungsschwelle: unterer Rand statt Gipfel (2026-09-14)

**Der Anlass.** Bahn 2 des Hallenmitschnitts galt in **26,7 %** aller Frames
als verdeckt. Drei Stichproben aus diesen 3617 Frames zeigten: In zweien lag
die Tafel voellig frei und die gruene Lampe war **echt aus**; nur in der
dritten stand tatsaechlich ein Mensch davor.

Folgenlos war das nicht, aber auch kein Wurfverlust. Gegenprobe mit
abgeschaltetem Gruen-Zeugen ueber den ganzen Mitschnitt:

| | mit | ohne |
|---|---|---|
| Wuerfe gesamt | 64 | 64 |
| je Bahn (2/3/4) | 29/12/23 | 29/12/23 |
| Kegelzahl, Kegelnummern, Status | -- | **64 von 64 identisch** |

Die Bremse kostete keine Wuerfe, sie **verzoegerte** sie: 21 der 29 Wuerfe auf
Bahn 2 wurden spaeter gebucht, im Extremfall **139 Frames = 9,3 Sekunden**.
Fuer die Zaehlung folgenlos, fuer einen Liveticker der Unterschied zwischen
live und hinterher.

### Warum der Gipfel die falsche Bezugsgroesse war

Die AUS-Wolke, sauber definiert: nur Frames, in denen Tafelwache UND
Personenmodell schweigen -- also unabhaengig vom Gruen-Score selbst, sonst
waere die Messung zirkulaer.

**Hallenmitschnitt**, 13 530 Frames:

| Bahn | saubere AUS-Messungen | Minimum | p1 | p5 | Median | Schwelle alt |
|---|---|---|---|---|---|---|
| 2 | 6344 | 0,0 | 0,0 | 0,0 | 0,7 | 0,90 |
| 3 | 956 | 1,4 | 1,4 | 2,1 | 3,5 | 1,50 |
| 4 | 3489 | **7,1** | 7,1 | 8,4 | 11,7 | 3,30 |
| 5 | 216 | 0,0 | 0,0 | 0,0 | 0,0 | 0,90 |

**Livestream Fastlane**, 42 400 Frames:

| Bahn | saubere AUS-Messungen | Minimum | p1 | p5 | Median | Schwelle alt |
|---|---|---|---|---|---|---|
| 2 | 10 875 | 13,9 | 20,8 | 23,6 | 29,2 | 8,70 |
| 3 | 10 475 | 17,3 | 18,5 | 21,0 | 25,9 | 7,50 |
| 4 | 11 990 | 21,2 | 25,0 | 25,0 | 31,2 | 9,30 |
| 5 | 7 956 | 15,0 | 16,2 | 18,8 | 23,8 | 6,90 |

Der Stream liegt durchweg hoeher -- die Vermutung "abends im Training dunkel,
am Spieltag hell" ist also nicht falsch. Sie erklaert aber nicht das
Entscheidende: In DERSELBEN dunklen Halle, im selben Frame, hat Bahn 4 eine
AUS-Wolke von 7,1 bis 11,7 und Bahn 2 eine von 0,0 bis 0,7. Das ist eine
Eigenschaft der einzelnen Lampe und ihres ROI-Sitzes, keine der Beleuchtung.
Ein Anteil am GIPFEL kann das nicht abbilden: Er sagt, wo AUS ueblicherweise
liegt, nicht wie weit die Wolke nach unten reicht.

### Der Schaetzer -- und warum ein Quantil nicht geht

Naheliegend waere das 1. Perzentil der AUS-Wolke. Es ist unbrauchbar, weil die
Wolke im Betrieb VERSCHMUTZT ist: Jeder Frame mit einem Menschen vor der Lampe
liegt als 0,0 mit darin.

Wahrheit = p1 der gereinigten Wolke, gerechnet wird auf der rohen:

| Quelle | Bahn | Wahrheit | Quantil roh | Gipfelabstieg roh |
|---|---|---|---|---|
| Halle | 2 | 0,0 | 0,0 | 0,0 |
| Halle | 3 | 1,4 | 1,4 | 1,0 |
| Halle | 4 | 7,1 | 7,1 | 7,0 |
| Stream | 2 | 20,8 | 20,8 | 25,0 |
| Stream | 3 | 18,5 | **0,0** | 22,0 |
| Stream | 4 | 25,0 | **0,0** | 30,0 |
| Stream | 5 | 16,2 | 16,2 | 20,0 |

| Schaetzer | mittlerer Abstand | groesster Fehler |
|---|---|---|
| Quantil p1 | 5,44 | **25,0** |
| Gipfelabstieg 10 % | 2,23 | 5,0 |
| Gipfelabstieg 5 % | **2,12** | **5,0** |
| Median − 3·MAD | 2,38 | 4,9 |

Auf Bahn 3 und 4 des Streams zieht ein Bruchteil verdeckter Frames das Quantil
auf **null** -- die Bremse haette sich selbst abgeschaltet, ausgerechnet dort,
wo sie am besten arbeitet, und kein Test waere rot geworden. Der Abstieg vom
Gipfel sieht den Schmutz nicht, solange dazwischen eine Luecke liegt.
Verschmelzen Wolke und Schmutz (Halle, Bahn 2), liefert er richtigerweise 0.

**Damit braucht das Histogramm keine Lernsperre.** Die zunaechst geplante
Loesung -- nur "saubere" Frames ins Histogramm lassen -- entfaellt; der
Schaetzer traegt die Verschmutzung von allein.

### Der Sicherheitsfaktor

Der Abstieg landet im Stream ueber der Wahrheit (25,0 gegen 20,8) -- die
falsche Richtung, denn eine zu hohe Schwelle bremst auf echtem AUS. Weil eine
Verdeckung 0,0 liest und die Wolke im Stream bei 14 anfaengt, ist die Luecke
riesig; man darf also konservativ sein.

Schwelle = Faktor x Rand. Geprueft auf allen acht Bahn/Quelle-Paaren, ob sie
unter dem p1 der gereinigten Wolke bleibt:

| Faktor | bleibt ueberall unter der Wolke | Bremsrate Stream | Bremsrate Halle |
|---|---|---|---|
| 0,4 | ja | 0,03 / 0,45 / 0,92 / 0,16 % | 0 % |
| **0,5** | **ja** | 0,03 / 0,46 / 0,92 / 0,16 % | **0 %** |
| 0,6 | ja | 0,04 / 0,52 / 0,95 / 0,16 % | 0 % |

0,5 gewaehlt. Zum Vergleich die alte Regel: Halle Bahn 2 **18,7 %**, Bahn 5
2,2 %; Stream 0,03 / 0,44 / 0,92 / 0,15 %.

### Gegenprobe am ganzen Hallenmitschnitt

| | Gipfel-Regel | Rand-Regel |
|---|---|---|
| Verdeckungen begonnen | 121 (davon Bahn 2: 117) | **8** (davon Bahn 2: 5) |
| Wuerfe | 64 | **64** |
| ms/Frame | 35,6 | **29,8** |

Schneller, weil die Bremse nicht mehr staendig zuschnappt und das
Personenmodell nicht staendig mitzieht.

### Gegenprobe am Livestream

Volle Pipeline ueber F0 bis F42400 der Fastlane-Uebertragung, also bis ueber
die Beweisstelle hinaus. Gemessene Schwellen am Ende des Laufs:

| Bahn | Rand der AUS-Wolke | Gipfel | Schwelle |
|---|---|---|---|
| 2 | 20,0 | 29,0 | 10,00 |
| 3 | 16,0 | 25,0 | 8,00 |
| 4 | 22,0 | 31,0 | 11,00 |
| 5 | 14,0 | 23,0 | 7,00 |

Die Schwellen liegen damit ueber den alten (6,9 bis 9,3) und weit unter dem
unteren Rand der jeweiligen Wolke -- schaerfer, ohne in echtes AUS zu ragen.

**Wuerfe auf Bahn 2 zwischen F42150 und F42350: keiner.** Der Phantomwurf, an
dem diese ganze Kette begann -- Mensch laeuft durch die Gruenphase, Score
faellt zehn Frames auf 0,0, Wurf mit 0 Kegeln und Gesicht in der Datenbank --
wird weiterhin aufgehalten. 148 Wuerfe im Abschnitt insgesamt.

Damit traegt EINE Konfiguration beide Quellen, ohne Fallunterscheidung:

| | Halle: Fehlbremsen | Stream: Phantomwurf |
|---|---|---|
| feste Zahl 12 | alle Bahnen dauerhaft eingefroren | gefangen |
| feste Zahl 0 | keine | **entsteht** |
| Anteil am Gipfel (0,3) | Bahn 2 in 26,7 % der Frames | gefangen |
| **Anteil am Rand (0,5)** | **keine** | **gefangen** |

## Was der Tafelabgleich vertraegt (2026-09-15)

**Der Anlass.** Die Handy-App fand auf einer gross und frontal im Bild
stehenden FUNK-Tafel nichts. Das sah aus, als truege das Verfahren nicht.

**Erste Erkenntnis: Das Musterbild passt nur zu seiner Quelle.**

| Quelle | tragende Merkmale | Tafeln gefunden |
|---|---|---|
| Hallenframe 2304x1296 (Herkunft des Musters) | **154** | 4 |
| Streamframe 1920x1080 (Overlay) | 0 | -- |

`FUNK_klassisch` stammt von der RTSP-Hallenkamera und passt dorthin. Die
Overlay-Tafeln des Livestreams sind eine andere Darstellung; die Kalibrierung
`Fastlane` ist nicht ueber diese Suche entstanden.

### Der Toleranzbereich

Gemessen am Hallenframe, in dem alle vier Tafeln sicher gefunden werden. Das
Zielbild wurde schrittweise verschoben; noetig sind 18 tragende Merkmale.

| | vertraegt | kippt bei |
|---|---|---|
| **Massstab** | **0,8x bis 1,5x** | 0,6x und 2,0x |
| Drehung | jede, bis 90 Grad | -- |
| Unschaerfe | Gauss-Kern bis 13 px | 21 px |
| Neigung | bis 20 % Trapez | 30 % |

Drehung und Unschaerfe sind unkritisch -- ORB ist drehinvariant, und die
Merkmale halten erstaunlich viel Weichzeichnung aus. **Der Massstab ist das
schmale Fenster**, und genau daran scheiterte die App: Auf dem Telefon fuellte
eine Tafel rund 900 Bildpunkte gegen 190 im Muster. Das Fuenffache.

### Die Massstabsleiter

Das Musterbild wird in mehreren Groessen angeboten, statt die Kamera so lange
zu verschieben, bis es zufaellig passt:

| Zielmassstab | nur Original | mit Leiter |
|---|---|---|
| 0,3x | 0 | 0 |
| 0,6x | 0 | 25 |
| 0,8x | 86 | 86 |
| 1,0x | 154 | 154 |
| 1,5x | 102 | 228 |
| **2,0x** | **0** | **461** |
| **3,0x** | **0** | **398** |
| **4,0x** | **0** | **666** |

Aus 0,8-1,5x wird **0,6-4,0x**. Unter 0,3x bleibt es dabei -- eine Tafel unter
rund 60 Bildpunkten traegt keine Merkmale mehr, und lesbar waere sie ohnehin
nicht.

Die teuren Merkmale des ZIELBILDES werden nur einmal berechnet; jede weitere
Sprosse kostet nur den Vergleich.

**Der Tischrechner-Weg bleibt unberuehrt.** `erkenne` nimmt die Leiter als
freiwilligen Zusatz; ohne sie benutzt es genau die eine Vorlage wie bisher.
Eine fest montierte Hallenkamera steht immer gleich weit weg -- dort loest die
Leiter kein Problem und koennte nur eines schaffen.

### Ein Maß, das NICHT taugt

Als Rueckmeldung beim Ausrichten lag eine Schaerfepruefung nahe (Streuung der
Laplace-Kanten). GEMESSEN:

| | Laplace-Streuung |
|---|---|
| unscharfes Handybild (Kamera zu nah) | **1851** |
| scharfer Tafelausschnitt | 1465 |
| Musterbild | 79 |

Das unscharfe Bild ist "schaerfer" als das scharfe: Staubkoerner und das
Pixelraster des Monitors erzeugen genau die Hochfrequenz, die das Mass zaehlt.
Verworfen. Die ehrliche Rueckmeldung ist die Zahl, die der Abgleich ohnehin
berechnet -- `BoardFinder.beste_inlier`, die tragenden Merkmale der besten
Uebereinstimmung, auch wenn sie unter der Schwelle bleibt.

### Der Handyblick, aus dem Mitschnitt nachgestellt (2026-09-15)

Weil eine Kegelbahn nicht in fuenf Minuten erreichbar ist, wurde der Blick
nachgestellt: `tools/simuliere_handykamera.py` schneidet aus einem Hallenframe
einen Ausschnitt um EINE Tafel, gerade so gross, dass sie denselben Anteil der
Bildbreite fuellt wie auf einem Telefon aus der gewuenschten Entfernung, und
skaliert ihn auf 1440x1920 hoch.

Tafel im Hallenframe: 187 px breit. Musterbild: 190 px. Noetig: 18 Merkmale.

| Tafel fuellt | Tafel dann | ohne Leiter | mit Leiter | Tafeln gefunden |
|---|---|---|---|---|
| 15 % | 216 px | 179 | 292 | 3 |
| 25 % | 360 px | **0** | 252 | 2 |
| 40 % | 576 px | **0** | 200 | 1 |
| 60 % | 864 px | **0** | 147 | 1 |
| 80 % | 1152 px | **0** | 100 | 1 |

**Ohne Leiter traegt genau ein Abstand** -- der, bei dem die Tafel zufaellig
Mustergroesse hat. Schon bei 25 % Bildfuellung faellt es auf null. Mit Leiter
traegt jeder Abstand von 15 bis 80 %.

Dazu schraeg und unscharf, bei 40 % Bildfuellung:

| Neigung | Unschaerfe | Merkmale | Tafeln |
|---|---|---|---|
| 0 % | 0 px | 200 | 1 |
| 10 % | 0 px | 243 | 1 |
| 20 % | 0 px | 156 | 1 |
| 0 % | 9 px | 203 | 1 |
| 10 % | 5 px | 236 | 1 |

Gemeinsam gehalten. Das bestaetigt den Toleranzbereich von oben: Winkel und
Schaerfe sind unkritisch, der Massstab war alles.

**WAS DAMIT NICHT GEZEIGT IST** -- und das gehoert dazu:

* **Andere Optik.** Ein Handyobjektiv zeichnet anders als eine RTSP-Kamera:
  andere Verzeichnung, andere Schaerfeverteilung, andere Farbabstimmung.
* **Andere Beleuchtung.** Der Mitschnitt entstand abends im Training.
* **Echte Aufloesung.** Hochskalieren erfindet keine Bildpunkte.

Der letzte Punkt macht die Simulation zur UNTEREN SCHRANKE, was die Aufloesung
angeht: Ein Telefon aus einem Meter Entfernung sieht mehr Einzelheiten als
dieser Ausschnitt. Die ersten beiden Punkte bleiben offen -- gezeigt ist, dass
der MASSSTAB der Blocker war und die Leiter ihn raeumt, nicht, dass die
Merkmale einer Handykamera zu einem Muster aus einer Hallenkamera passen.

Faellt das vor Ort durch, steht die Antwort schon bereit: `speichere_typ` legt
einen Tafeltyp aus dem Handybild selbst an. Dann vermisst man einmal eine
Tafel von Hand, und die Suche findet die uebrigen.

## Die Gegenprobe: vier Messungen, die einander befragen (2026-09-15)

Der Nutzer: *"ich moechte erreichen, dass wir 2 Messsysteme parallel laufen
haben, die sich am Ende gegenseitig korrigieren."* Vorerst beobachtend --
`analysis/gegenprobe.py` aendert kein Ergebnis, es zaehlt aus.

### Wer ueberhaupt etwas sagen kann

GEMESSEN ueber 57 Wuerfe des Hallenmitschnitts, wie oft jede Quelle beim Wurf
vorlag:

| Quelle | vorhanden |
|---|---|
| Lampen | 57 von 57 |
| Kegelziffer | 56 von 57 |
| Wurfnummer | 40 von 57 |
| **Summe** | **2 von 57** |

Der erste Entwurf stuetzte sich auf die Summendifferenz und schwieg damit in
95 % der Faelle. Die Summe ist der **Schiedsrichter**, nicht die Grundlage:
Verglichen wird Lampen gegen Kegelziffer, die Summe tritt hinzu, wenn die
beiden sich uneinig sind.

### Das Ergebnis

| Urteil | Anteil |
|---|---|
| Lampen und Ziffer einig | **86,0 %** (49) |
| Lampen gegen Ziffer, kein Schiedsrichter | 7,0 % (4) |
| Wurfnummer springt -- Wurf fehlt | 5,3 % (3) |
| nur die Lampen, nichts zu vergleichen | 1,8 % (1) |
| Lampen verdaechtig / Ziffer falsch / unklar | 0 |
| Fehlwurfzaehler passt zum Ergebnis | 94,7 % der lesbaren |

Die vier strittigen Faelle sind dieselben, die eine Handzaehlung zuvor gefunden
hatte (F3278, F6891, F7743, F8759) -- drei davon trugen bereits eine Confidence
von 0,45. Das Werkzeug wusste also in drei von vier Faellen selbst, dass es
wackelt.

### Warum die Summe fehlt -- und es NICHT an der Ziffernerkennung liegt

Vermutung des Nutzers: *"zu wenig gelesen koennte ja stimmen => Weil der Wurf
ja erst relativ spaet angerechnet wird."* Geprueft, indem alle Ziffernfelder
UNABHAENGIG vom Auswertefenster gelesen wurden, jeder 10. Frame ueber den
ganzen Mitschnitt:

| Bahn | total_b | pin_count | throw_number | left_display |
|---|---|---|---|---|
| 2 | 18,7 % | 57,9 % | 63,9 % | 99,2 % |
| 3 | 19,6 % | 12,8 % | 96,9 % | 99,6 % |
| 4 | **77,0 %** | 36,1 % | 96,6 % | 100 % |
| 5 | 32,7 % | 0,2 % | 97,9 % | 98,2 % |

**Die Vermutung stimmt.** Auf Bahn 4 ist das Summenfeld in 77 % aller Frames
lesbar, im Auswertefenster aber fast nie. Es ist ein Zeitpunktproblem, kein
Erkennungsproblem -- und damit billig zu beheben.

### Nebenbefund: Bahn 2 liest ihre Summe systematisch falsch

| Bahn | Lesungen | davon plausibel (0..600) | Spanne |
|---|---|---|---|
| 2 | 253 | **0 (0 %)** | -- |
| 3 | 265 | 265 (100 %) | 0..93 |
| 4 | 1042 | 980 (94 %) | 2..176 |
| 5 | 442 | 439 (99 %) | 203..209 |

Bahn 2 liefert Werte wie 2237, 3813, 3213 -- fuer eine laufende Summe, die
zwischen 0 und rund 600 liegen muss. Die hinteren drei Stellen sind meist
plausibel (237, 213, 233): **die fuehrende Stelle wird falsch gelesen**, wo
eigentlich eine Null oder nichts steht. Derselbe Fall, fuer den es bei der
Wurfnummer schon `throw_number_ignore_leading` gibt.

Gefallen ist das nie auf, weil die Summe bisher nirgends gegengeprueft wurde.
Die Gegenprobe hat es in ihrem ersten Lauf gefunden.

## 2026-09-15 — Geführtes Lesen der Summe und die Systematik dahinter

Nutzerwunsch: *"gerade standen wir bei 0172 -> jetzt melden Ziffer und Lampen
eine 3 -> sicher dass du hier eine 8176 melden willst und nicht eher eine
0175?"* — und, zur harten Grenze von 9 × 30 = 270 Punkten: *"es ist nur der
Regelfall, wer weiß was manche Leute im Training oder so machen, also bitte
keine harte Grenze einbauen.... eher das systematische fördern, es muss
eigentlich immer mit 0 losgehen und dann steigen."*

Gebaut: `analysis/gefuehrtes_lesen.py`. Keine feste Obergrenze, sondern eine
**mitwachsende**: Nach N Würfen kann höchstens `N * pin_count` auf der Tafel
stehen; N liefert die Wurfnummer der Tafel selbst. Nach dreißig Würfen sind das
270, nach hundert 900.

### Was die Systematik allein trägt

13.530 Frames, jeder zehnte gelesen, 1.353 Summenlesungen je Bahn. "Eindeutig"
heißt: Die Systematik ließ genau **einen** Wert zu — die Lesung war aufgelöst,
**ohne** die Lampen zu befragen.

| Bahn | eindeutig | Widerspruch | unmöglich |
|---|---|---|---|
| 2 | 35 | 36 | **1250 (92 %)** |
| 3 | 1332 (98 %) | 4 | 12 |
| 4 | 1202 (89 %) | 21 | 107 |
| 5 | 391 | 922 | 36 |

Bahn 2 fällt fast vollständig durch — dasselbe Feld, das schon am 2026-09-14
als systematisch falsch gelesen auffiel. Die Regel repariert es nicht, sie
macht es sichtbar. Bahn 5 zeigt den dritten Fall: 922 Widersprüche heißt nicht
"falsch", sondern "mehrere Werte wären möglich" — dort hilft erst die Führung.

### Im vollen Lauf (64 Würfe, 57 Befunde)

| | vorher | nachher |
|---|---|---|
| Summe auf beiden Seiten lesbar | 2 von 57 | **8 von 57** |
| Summe überhaupt gelesen | — | 19 von 57 |
| Bahn 2: gelesene Summen | 2237, 3813, 3213 … | 133, 132, 133 |
| Würfe insgesamt | 64 | 64 (unverändert) |

Die Laufzeit blieb bei 30,9 ms/Frame.

### Zwei ehrliche Einschränkungen

**Die Führung selbst hat auf diesem Material nie gegriffen** (0 von 19). Die
zusammengefassten Lesungen sind fast immer eindeutig oder gar nicht vorhanden —
der Fall "die Anzeige schwankt zwischen 3 und 9" ist bei der Summe selten.
Gearbeitet hat die Systematik, nicht die Erwartung. Der geführte Pfad bleibt
richtig gebaut und getestet, aber er ist hier kein Hebel.

**Von den 8 Fällen mit Summe auf beiden Seiten stimmten nur 2.** Die übrigen 6
sind fast alle Zeitversatz, nicht Lesefehler:

    B4 W20  Summe 123 -> 132 (Diff 9), Lampen 8
    B4 W18  Summe 123, B4 W20 Summe 123 -- zwei Würfe ohne Bewegung
    B4 W1   Summe   2 ->   3 (Diff 1), Lampen 9

Das Nachlaufmodell "die Tafel zeigt den Stand vor genau diesem Wurf" ist zu
einfach: Manchmal hängt sie zwei Würfe zurück. Vorher war das unsichtbar, weil
die Summe fast nie gelesen wurde. **Offen** — ein eigener Schritt, kein
Nebenbei-Fix.

## 2026-09-15 — Wahrscheinlichkeiten je Ziffer statt einer Liste ohne Rangfolge

Nutzerwunsch: *"wie wäre es, wenn wir die Wahrscheinlichkeit beim auslesen
haben? Also jede Ziffer gibt an, zu 0,1% eine 1, zu 5,2% eine 2 usw. und zu 85%
eine 9 -> dann könnten wir uns immer die top Kandidaten anschauen."*

Anlass war eine Frage, auf die es keine gute Antwort gab: *"Warum kann ich die
Ziffern in dem GIF so sauber erkennen aber unser Modell nicht?"*

### Die Antwort: Das Modell sieht die Ziffer. Es entscheidet falsch.

GEMESSEN, Bahn 4, F5400, letzte Stelle — im Bild zweifelsfrei eine **9**
(`debug/warum_falsch.png`):

    a=0,885 an   b=0,668 an   c=0,853 an   g=0,853 an
    d=0,000 aus  e=0,007 aus  f=0,182 aus      Schwelle 0,310

Das Muster `abcg` steht in keiner Tabelle. Im Hamming-Abstand 1 liegen **zwei**
Ziffern: die 3 (d müsste an, liegt 0,31 daneben) und die 9 (f müsste an, liegt
0,13 daneben). Der Hamming-Abstand sieht da keinen Unterschied — also gewann
die, die in `SEGMENT_PATTERNS` früher steht. **Die Ziffer wurde von einer
Dictionary-Reihenfolge entschieden.**

### Die Skala der Wahrscheinlichkeit ist gemessen, nicht gesetzt

Rauschen eines Füllgrades bei UNVERÄNDERTER Anzeige, Bahn 3 und 4, vier
Fenster, 1329 Frames: Median 0,003 bis 0,016, 90. Perzentil **0,040**,
Maximum 0,119. Genommen wird das 90. Perzentil
(`segment_probability_scale: 0.04`).

### Was der Umbau bringt

Verglichen auf DENSELBEN Frames, gegen ein von beiden Verfahren unabhängiges
Kriterium (die Summe darf nicht fallen und je Wurf höchstens um 9 steigen):

| Bahn | hart | Wahrscheinlichkeit |
|---|---|---|
| 2 | 49,6 % | **56,7 %** |
| 3 | 98,5 % | 98,5 % |
| 4 | 94,8 % | 94,8 % |
| 5 | 98,6 % | **99,1 %** |

Im Vollauf (64 Würfe, 29,0 statt 30,9 ms/Frame):

| | vorher | jetzt |
|---|---|---|
| Bahn 4, Summenverlauf | 2, 3, 32, 72, 73, 82, 116, 123, 123, 132 | **3, 9, 16, 22, 59, 61, 93, 129, 133, 139** |
| Differenz trifft die Lampen | 2 von 8 | 3 von 7 |
| „unklar" | 6 | 4 |

Vorher stieg die Summe von 2 auf 3, während neun Kegel fielen. Jetzt läuft sie
mit rund sieben Punkten je Wurf durch.

### Ein Rückschritt auf dem Weg, und was ihn verursachte

Der erste Anlauf gab die Wahrscheinlichkeit auch als **Confidence** zurück.
Damit flossen Lesungen aus dem Notfallpfad plötzlich in die harten Feldwerte
ein: **61 statt 64 gültige Würfe**, 11 statt 3 Meldungen „Wurf fehlt". Ein
ungültiges Segmentmuster bleibt ein Warnzeichen, ganz gleich wie klar der
wahrscheinlichste Kandidat führt. Die Confidence bleibt deshalb bei 0,35 —
geändert wird nur, WELCHE Ziffer gewählt wird.

### Offen: Die Messflächen sitzen schief

Füllgrad je Segment im aktiven Zustand, 49.000 Messungen über den ganzen
Mitschnitt:

| Segment | Mittel aktiv | Abstand zur Schwelle | 10. Perzentil |
|---|---|---|---|
| a (oben) | 0,867 | 0,542 | 0,353 |
| c (unten rechts) | 0,748 | 0,428 | 0,208 |
| **f (oben links)** | **0,617** | **0,292** | **0,051** |

Links (f, e) liest 0,664, rechts (b, c) 0,735. Segment f liegt in jedem
zehnten Fall nur 0,05 über der Schwelle — bei a sind es 0,35. Es fällt deshalb
als erstes aus, und genau daraus entstehen die ungültigen Muster.

Sichtbar in `debug/segmentlage.png`: Eine klar lesbare `0` auf Bahn 3 kommt als
**8 zu 52,4 % gegen 0 zu 47,4 %** heraus, weil die Fläche g in der absoluten
Mitte Striche erwischt, die nicht zu ihr gehören. Der Nutzer beim Blick auf
dasselbe Bild: *"dann sitzen die Flächen der linken Seite oben und in der
absoluten Mitte falsch"*.

Die Behebung (Messflächen an die Schräglage der Ziffern anpassen) ist ein
eigener Schritt mit eigener Messung — **noch nicht gemacht**.

## 2026-09-15 — Drei Vorschläge zur Ziffernerkennung, gemessen

Nutzervorschläge: (1) ein CV-Modell je eingerahmter Ziffer statt der sieben
Segmente, (2) der Nutzer legt die sieben Flächen selbst, (3) beim Einrahmen
werden die Mittelpunkte der Flächen angezeigt, damit er sieht, wie die Ziffer
zu platzieren ist.

### (1) CV-Modell: gemessen, bringt nichts — und zwar beweisbar nichts

Der Vergleich existierte schon (`tools/fit_digit_classifier.py`, 2026-08-30).
Neu gefahren auf `data/ground_truth/ziffern_neue_sperre.npz`, getrennt nach
zusammenhängenden Läufen:

| Datensatz | Segmentabtastung | kNN (k=3) |
|---|---|---|
| nur Bahn 2+3 (belastbare Wahrheit) | 96,5 % | 96,5 % |
| alle Bahnen | 83,9 % | 87,0 % |

Entscheidend ist aber die **Fehlerüberlappung** auf der Prüfhälfte (608 Bilder):

| | |
|---|---|
| Segmentabtastung richtig | 533 (87,7 %) |
| kNN richtig | 529 (87,0 %) |
| **beide falsch** | **72** |
| nur eines richtig | 10 |

Die Verfahren sind sich in **97 % der Fälle einig — auch im Irrtum**. Eine
Kombination brächte höchstens drei Bilder. Ein formbasierter Erkenner liest
dasselbe wie die Segmentabtastung, nur teurer. **Damit ist die Frage erledigt.**

Die 72 gemeinsamen Fehler liegen fast alle auf Bahn 4 und 5 (69,3 % gegen
97,0 % auf Bahn 2+3) — dort, wo die BESCHRIFTUNG unsicher ist. Bahn 4s
Lampenlesung wurde am 2026-09-02 repariert, der Datensatz stammt von davor.

### (2)/(3) Geometrie: ein Versuch, der sich am Material widerlegt hat

Der Nutzer beim Blick auf `debug/segmentlage.png`: *"dann sitzen die Flächen
der linken Seite oben und in der absoluten Mitte falsch"*. Die Zahlen stützten
das — Segment f erreicht aktiv im Mittel 0,617 gegen 0,867 bei a.

Gebaut wurden zwei Parameter: `segment_shear` (Schräglage) und
`segment_middle_inset` (Einzug der mittleren Fläche). Am beschrifteten
Datensatz sahen sie gut aus: Treffer 86,8 % → 87,7 %, gültige Muster
88,0 % → 94,0 %, auf der bei der Wahl unberührten Hälfte bestätigt.

**Am laufenden Material kehrte sich das um.** Summenfeld `total_b`,
fortlaufend gelesen, gegen die Systematik (darf nicht fallen, je Wurf
höchstens +9):

| Bahn | ohne | mit Scherung 0,08 / Einzug 0,06 |
|---|---|---|
| 2 | 73,7 % | **52,8 %** |
| 3 | 98,5 % | 99,0 % |
| 4 | 94,8 % | **91,4 %** |
| 5 | 98,3 % | 99,0 % |

Auf Bahn 2 stieg die Zahl der Lesungen von 362 auf 996. Die neue Geometrie
erzeugt **gültige Muster, wo vorher geschwiegen wurde** — und die sind falsch.

**Die Lehre:** Ein gültiges Segmentmuster ist nicht dasselbe wie eine richtige
Lesung. Die Gültigkeitsrate als Zielgröße zu nehmen war der Fehler; sie belohnt
Geometrien, die aus Schweigen falsche Antworten machen.

**Die Vorgaben stehen deshalb auf 0,0.** Die Parameter bleiben, weil die
Richtung stimmt und eine andere Anlage sie brauchen kann — aber sie werden
nicht eingeschaltet, solange keine Messung am laufenden Material sie trägt.

Warum der beschriftete Datensatz das nicht zeigen konnte: Er besteht zu zwei
Dritteln aus Bahn 2+3 und misst vor allem `pin_count`, ein EINSTELLIGES Feld.
Die Probleme liegen bei der vierstelligen Summe auf Bahn 2 und 4.

## 2026-09-15 — Was eine Kalibrierung mit Sicht auf die Messung bringt

Der Nutzer hat mit der neuen Ziffernlupe Bahn 2 des Hallenmitschnitts
nachkalibriert (`data/calibrations/deutlichbesser.json`). Bahn 3 verschob sich
dabei gleichmäßig um +0,0052/+0,0045 auf allen Bereichen — die Signatur der
automatischen Tafelerkennung, keine Handarbeit. Bahn 4 und 5 blieben
unangetastet und dienen als Kontrolle.

### Fortlaufendes Lesen (13.530 Frames, jeder zehnte)

| Bahn | | Summenlesungen | davon systematisch sauber | Wurfnummer gelesen |
|---|---|---|---|---|
| **2** | alt | 362 | 73,7 % | 812 |
| **2** | **neu** | **1157** | **97,0 %** | **1316** |
| **3** | alt | 265 | 98,5 % | 1311 |
| **3** | **neu** | **1303** | **99,8 %** | 1311 |
| 4 | unverändert | 1011 | 94,8 % | 1307 |
| 5 | unverändert | 461 | 98,3 → 98,7 % | 1346 |

Bahn 2 liest dreimal so oft und liegt dabei von 73,7 auf 97,0 % richtig.

### Die Gegenprobe im Vollauf

| | alt | **neu** |
|---|---|---|
| Summe auf beiden Seiten lesbar | 7 von 57 | **35 von 57** |
| Differenz trifft die Lampen | 1 | **30** |
| `einig` (alle drei Quellen) | 3 (5,3 %) | **25 (43,9 %)** |
| `wurf_fehlt` | 3 | **0** |
| Würfe | 64 VALID | 62 VALID, 2 ERROR |

Bahn 2s Summenverlauf ist zum ersten Mal durchgehend plausibel:
16, 24, 33, 42, 50, 55, 64, 73, 82, 87, … 117, 126, 135, 142, 143, 147, 151,
152, 161, 170, 179, 186, 188, 196.

### Die zwei ERROR sind kein Rückschritt

Es sind genau die beiden Würfe, die in JEDEM früheren Lauf als `strittig`
auffielen. Vorher galten sie als gültig, weil die Summe nicht lesbar war und
eine Prüfung deshalb gar nicht erst griff. Jetzt greift sie:

**Bahn 3 Wurf 8** — Lampen 4, Ziffer 9, Summendifferenz **4**. Die Summe stützt
die LAMPEN; die Ziffer ist falsch gelesen. Das gebuchte Ergebnis (4) stimmt,
die Meldung ist übervorsichtig.

**Bahn 2 Wurf 21** — Lampen 5, Ziffer 4, Summendifferenz **4**. Die Summe
stützt die ZIFFER. **Zum ersten Mal überführen zwei voneinander unabhängige
Quellen gemeinsam die Lampen.** Genau dafür wurde die Gegenprobe gebaut
(`lampen_verdaechtig`).

### Offen

Bahn 4 liefert vier `unklar`: Die Summendifferenz liegt dort durchweg zwei bis
drei unter der Lampenzahl (Lampen 9 gegen Differenz 6, Lampen 7 gegen 2). Ihre
Ziffernrahmen wurden nicht nachgezogen — dieselbe Behandlung wie bei Bahn 2
wäre der nächste Schritt.

## 2026-09-16 — BUG-027: Null ist nicht aus

Anlass war die Rückfrage des Nutzers zu einem Befund, den ich falsch gedeutet
hatte: *„aber ich dachte die Lampen passen sich selbst an? Also müsste dieses
'flackernd' wirkende (ich sehe da keine Helligkeitsänderungen) doch automatisch
die Wolken im Histogram anpassen, oder nicht?"*

Er hatte recht. GEMESSEN, Bahn 2, Kegel 3, F6600–6960:

```
Frame   Helligkeit  Waerme  AN-Schwelle  AUS-Schwelle  Zustand
  6624       255.0     0.0        213.0         205.0       ON
  6636       254.9    -0.3        213.0         205.0  UNKNOWN
  6660       255.0     0.0        213.0         205.0       ON
  6696       255.0    -0.2        213.0         205.0  UNKNOWN
```

Die Helligkeit steht konstant bei 255,0, die Schwellen bewegen sich nie, die
Lampe geht kein einziges Mal auf AUS. Das gleitende Histogramm arbeitet
einwandfrei — es ist nur nicht zuständig. Umgeschaltet hat die **Wärme**
(`rot − blau`), die bei einer weiß gesättigten Lampe um null pendelt, bei einer
Schranke von exakt 0,0.

Über den ganzen Mitschnitt: **99 von 3685 hellen Messungen der Bahn 2 verworfen
(2,7 %)**, auf Bahn 3 und 4 keine einzige. Wärme-Median bei hellen Messungen:
Bahn 2 **0,78**, Bahn 3 2,87, Bahn 4 **24,17**.

Die Behebung: `warmth_min` ist jetzt `float | None`, Vorgabe `None` = aus.

| | vorher | **nachher** |
|---|---|---|
| Bahn 2 Wurf 21 | 5 Kegel (ERROR) | **4 Kegel (VALID)** |
| `lampen_verdaechtig` | 1 | **0** |
| `einig` | 25 (43,9 %) | **26 (45,6 %)** |
| Differenz trifft die Lampen | 30 von 35 | **31 von 35** |
| ERROR-Würfe | 2 | **1** |
| Würfe | 64 | 64 |
| ms/Frame | 23,76 | **23,80** |

Die Laufzeit wurde eigens nachgemessen, weil ein Lauf zwischendurch 49 ms
meldete: Dasselbe Skript über dieselben 13.530 Frames liefert 23,76 gegen
23,80 ms — die Verlangsamung kam von parallel laufender Arbeit, nicht von der
Änderung.

Vollständige Herleitung samt der falschen Fährte („die Lampe flackert") in
`.claude/skills/bugs/BUG-027-null-ist-nicht-aus/SKILL.md`.

## 2026-09-17 — BUG-028: Der erste Wurf jedes zweiten Spiels fehlte

Der Nutzer nach einem Spieltag mit 477 Würfen: *„da sind fast überall sehr
große Unterschiede zwischen den Lampen und den Ziffern"* — und, nach dem ersten
Messen: *„Es scheint mir aber auch bei späteren Sätzen, dass jeweils immer der
erste gefehlt hat."* Der zweite Satz traf es.

### Was NICHT das Problem war

| Prüfung | Ergebnis |
|---|---|
| Lampen gegen Kegelziffer | **358 von 360 gleich (99,4 %)** |
| Gegenprobe „einig" | 363 von 472 (76,9 %) |
| Lampe hell, aber nicht als AN gemeldet | **1 von 226.404 Messungen** |
| UNKNOWN-Lampen | 304 von 226.404 (0,13 %) |

Die Feinkalibrierung der Ziffern hat getragen. Kaputt war der **Startwert** der
laufenden Summe, nicht ihr Verlauf.

### Die Spur: ein konstanter Fehler zeigt auf den Startwert

Restfehler `(LaufendeSumme − SummeTafel) − Kegel`, nach Spielen gruppiert:

| Bahn | Spiel | erster gebuchter Wurf | Rest |
|---|---|---|---|
| 2 | 2 und 5 | Wurfnummer **2** | konstant −7 |
| 3 | 2 | Wurfnummer **2** | konstant −9 |
| 4 | 2 | Wurfnummer **2** | konstant −5 |
| 5 | 2, 4, 6 | Wurfnummer **2** | konstant −7 / −9 / −6 |
| alle übrigen | | Wurfnummer **1** | **±0** |

Sieben von 25 Spielen, jeweils über das ganze Spiel konstant — und der Betrag
ist genau die Kegelzahl des verlorenen ersten Wurfs.

### Ursache

`_pruefe_nullzustand` läuft in eigenem Takt, unabhängig vom Wurffenster (das
war A4, eine richtige frühere Korrektur). Damit kann der Nullzustand an zwei
Zeitpunkten gesehen werden — **im** Wurffenster oder **zwischen** zwei Würfen —
und beides ging in denselben Briefkasten. Der zweite Fall kam dadurch einen
Wurf zu spät, und der erste Wurf des neuen Spiels landete im alten.

Ob es auffiel, entschied der Wurfrhythmus. Deshalb waren 18 Spiele richtig.

### Was das über die Gegenprobe sagt

Sie war blind dafür — sie vergleicht **Differenzen**, und eine Differenz ist
gegen einen falschen Startwert immun. Sie meldete 76,9 % „einig", während der
Punktestand auf jeder Bahn danebenlag. Für einen Versatz braucht es den
absoluten Vergleich `LaufendeSumme` gegen `SummeTafel`.

### Stand der Prüfung

Behoben und mit `test_game_reset.py::TestWohinDasZeichenGeht` festgenagelt; die
Tests fallen nachweislich durch, wenn man die Korrektur zurücknimmt.

**Am Hallenmitschnitt: 64 Würfe, unverändert** — Regressionsprüfung, nichts
kaputt.

### Nachgemessen — die Annahme „nicht wiederholbar" war falsch

Ich hatte geschrieben, der Lauf sei nicht nachmessbar, weil er gegen einen
Livestream lief. **Das stimmt nicht:** Die Stream-URL liefert von vorn, nicht
vom Live-Rand. Ein zweiter Lauf gegen dieselbe URL bucht dieselben Würfe (Bahn 4
Kegel 5 mit `1 3 6 8 9`, Bahn 3 Kegel 9, Bahn 5 Kegel 7 mit `1 2 3 4 6 7 9` —
Zeichen für Zeichen).

Damit ist das Material wiederholbar, und die Wirkung ist gemessen. Über die
ersten 98 Würfe, alle vier Bahnen, mit `1Spieltag_Neu_Feinkalibriert.json`:

| | Rest = 0 (richtig) | Spiele mit konstantem Fehlbetrag |
|---|---|---|
| vorher | 22 von 96 (**22,9 %**) | 4 (−7, −9, −5, −7) |
| **nachher** | **96 von 96 (100,0 %)** | **0** |

Bahn 3 im Einzelnen — vorher begann Spiel 2 bei Wurf 2 und schleppte −9 mit,
jetzt bleibt alles in Spiel 1 und die laufende Summe liegt genau einen Wurf vor
der Tafel, wie es der Nachlauf verlangt:

```
vorher   Spiel 1 W1 Lauf  9 Tafel  0   Spiel 2 W2 Lauf  9 Tafel  9  Rest -9
nachher  Spiel 1 W1 Lauf  9 Tafel  0   Spiel 1 W2 Lauf 18 Tafel  9  Rest +0
```

## 2026-09-25 — Fehlercodes der Tafel, und warum sie wie ein Ergebnis aussehen

Nutzer, nach dem 2. Spieltag: *„Bei Wurf 22 auf Bahn 4 nach ca. 39:05 sek
fallen 7 Kegel während der Grünphase... Danach fängt die Anzeige an mit den
Kegeln 1,2,3,4,5,8 zu blinken, während 6,7,9 dauerleuchten... das ist ein
Fehlercode, den die Tafel an den Spieler sendet. Es gibt verschiedene
Fehlercodes [immer bestehend aus dauerleuchtenden und blinkenden Lampen]
(dieser bedeutet, ein Kegel befindet sich im Kugelkran)."*

### Was die Lampenspur dazu sagt

Bahn 4, Wurf 22, Grün-AUS bei Frame 46676. Je Lampe über das Fenster gezählt:

```
WÄHREND der Grünphase (F46600–46676)      NACH Grün-AUS (F46678–46760)
Kegel 1  20x AN,  0x AUS,  0 Wechsel      Kegel 1   8x AN,  6x AUS,  5 Wechsel
Kegel 2  20x AN,  0x AUS,  0 Wechsel      Kegel 2   8x AN,  6x AUS,  5 Wechsel
Kegel 3  20x AN,  0x AUS,  0 Wechsel      Kegel 3   8x AN,  6x AUS,  5 Wechsel
Kegel 4   0x AN, 20x AUS                  Kegel 4   5x AN,  9x AUS,  4 Wechsel
Kegel 5   0x AN, 20x AUS                  Kegel 5   5x AN,  9x AUS,  4 Wechsel
Kegel 6  20x AN,  0x AUS,  0 Wechsel      Kegel 6  14x AN,  0x AUS,  0 Wechsel
Kegel 7  20x AN,  0x AUS,  0 Wechsel      Kegel 7  14x AN,  0x AUS,  0 Wechsel
Kegel 8  20x AN,  0x AUS,  0 Wechsel      Kegel 8   8x AN,  6x AUS,  5 Wechsel
Kegel 9  20x AN,  0x AUS,  0 Wechsel      Kegel 9  14x AN,  0x AUS,  0 Wechsel
```

Während der Grünphase steht das Ergebnis ruhig da: sieben Lampen an, Kegel 4
und 5 aus, **null Wechsel**. Der erste Wechsel kommt bei Frame 46683, sieben
Frames nach Grün-AUS. Die Tafelsumme bestätigt die sieben.

### Die Semantik des Blinkens (vom Nutzer erklärt)

Blinken bedeutet genau drei Dinge, und die ersten beiden setzen **einen
einzigen Wurf** voraus:

| Anzeige | dauerleuchtend | blinkend | aus |
|---|---|---|---|
| Alle Neune, 1 Wurf | leer | alle neun | leer |
| 8er Kranz, 1 Wurf | leer | 1,2,3,4,6,7,8,9 | Kegel 5 (er steht) |
| Räumen über mehrere Würfe | die gefallenen | **nichts blinkt** | die stehenden |
| **Fehlercode** | **nicht leer** | **nicht leer** | ggf. leer |

Der Kern: Bei den beiden Jubel-Effekten blinkt **alles, was leuchtet** — die
dauerleuchtende Menge ist leer. Nur ein Fehlercode hat beide Mengen zugleich
besetzt. Damit lässt er sich **ohne Codekatalog** erkennen.

Das korrigiert einen älteren Eintrag: „8→0→8→0 über ~100 Frames" war kein
allgemeines Lampenverhalten und auch nicht nur „alle Neune", sondern ein
8er Kranz.

### Gegenprobe über den ganzen Spieltag (`tools/messe_blinken.py`)

Je Wurf und Lampe die AN/AUS-Wechsel gezählt, getrennt nach Grünphase (`bis`)
und den 120 Frames danach (`nach`). Ab zwei Wechseln gilt eine Lampe als
blinkend — ein einzelnes AUS reicht bewusst nicht, sonst wäre Bahn 5 Kegel 8
(ROI sitzt zwei Pixel zu tief) ein Dauerblinker.

```
Phase  Muster                                Anzahl
bis    FEST UND BLINKEND (Fehlercode)             2
bis    alles Leuchtende blinkt (Jubel)          750
bis    nichts blinkt                            946
nach   FEST UND BLINKEND (Fehlercode)             2
nach   alles Leuchtende blinkt (Jubel)          711
nach   nichts blinkt                            978
```

**Vier Treffer im ganzen Lauf, und es sind genau die vier bekannten
Fehlbuchungen** — die beiden +10-Spiele auf Bahn 4. Null Fehlalarme über rund
3300 geprüfte Fenster. Zwei verschiedene Codes:

```
Bahn   Frame  Phase Ziffer gebucht  dauerleuchtend  blinkend
   4   46676   nach      -       9  [6, 7, 9]       [1, 2, 3, 4, 5, 8]
   4   47674    bis      3       9  [6, 7, 9]       [1, 2, 3, 4, 5, 8]
   4  138158   nach      -       9  [6, 7, 8, 9]    [1, 2, 3, 4, 5]
   4  139069    bis      -       9  [6, 7, 8, 9]    [1, 2, 3, 4, 5]
```

### Zwei der vier Treffer sind Fehlalarme des Messwerkzeugs

**Korrektur, noch am selben Tag.** Zuerst stand hier, der Code laufe in den
nächsten Wurf hinein, weil zwei der vier Treffer in der Phase `bis` lagen.
Der Nutzer hat widersprochen: *„Bevor der nächste Wurf freigegeben wird, ist
das Problem IMMER behoben!"* — und die Frames geben ihm recht:

```
Zyklus vor Wurf 23: Grün-AN 47103, Grün-AUS 47674
  letzter AN/AUS-Wechsel bei Frame 47605 -- 25,1 s nach Grün-AN,
  danach 3,5 s ruhig, Stand [1,2,3,4,6,7,8,9]

Zyklus vor Wurf 21: Grün-AN 138731, Grün-AUS 139069
  letzter AN/AUS-Wechsel bei Frame 139000 -- 13,4 s nach Grün-AN,
  danach 3,5 s ruhig, Stand [1,2,3,4,6,7,8,9]
```

Der letzte Wechsel ist jeweils **kein Blinken, sondern der fallende Kegel**
(7 wird zu 8). Alle übrigen Wechsel dieser Zyklen liegen in den ersten rund 30
Frames nach Grün-AN — dort, wo die Anzeige vom vorigen Stand auf den neuen
umschaltet. Genau deshalb wird die Räum-Grundlinie erst *kurz nach* Grün-AN
gemessen und nicht bei Grün-AN selbst.

**Der Klassifikator kann den Umschaltmoment nicht vom Fehlercode trennen**,
weil beide „etwas fest, etwas wechselnd" ergeben. Echte Fehlercodes stehen nur
in den beiden `nach`-Fenstern.

**Was daraus folgt:**

* Die Regel „Fehlercodes beginnen erst nach Grün-AUS und sind vor der Freigabe
  des nächsten Wurfs behoben" ist **nicht** widerlegt.
* Ein Blinkerkenner braucht einen **Anlauf nach Grün-AN**, sonst meldet er bei
  jedem Wurf den Umschaltmoment. Wie lang der sein muss, ist ungemessen.
* Ob dann noch vier, zwei oder mehr Treffer übrig bleiben, ist damit offen.
  Die Zahl „vier Treffer, null Fehlalarme" gilt nur für das Werkzeug in seiner
  jetzigen, zu groben Form.

**Lehre daraus:** Ein Klassifikator, der in genau den vier gesuchten Fällen
anschlägt, sieht nach einem Volltreffer aus — auch dann, wenn er aus zwei
verschiedenen Gründen anschlägt. Vier von vier ist kein Beweis, solange nicht
geprüft ist, *warum* er jeweils anschlug.

### Zwei Dinge, die dabei nebenbei widerlegt wurden

1. *„Wir müssten viel dichter abtasten, um Blinken zu sehen."* Nein. Während
   der Grünphase wird alle 5 Frames gelesen, die Blinkperiode beträgt 25
   Frames (20 fps) mit etwa 15 Frames Dunkelphase — rund fünf Messungen je
   Periode. Die gesamte Auswertung oben stammt aus der Spur, die der Lauf
   ohnehin geschrieben hat. Fehlt nicht Abtastung, sondern Buchführung:
   `aggregate_pin_readings` bildet je Lampe das Maximum und wirft die
   Zeitstruktur genau dort weg.
2. Ein erster Messversuch schnitt die Fenster an den **Wurfframes** statt an
   der Grünspur. „bis" reichte damit vom vorigen Wurf bis zu diesem und
   umfasste das Löschen der Anzeige und das Stellen des neuen Satzes — dabei
   geht jede leuchtende Lampe aus und wieder an. Ergebnis: 1455 gemeldete
   „Jubel"-Muster, wo es höchstens ein paar Dutzend geben kann. Ein
   Messfenster, das einen Anzeigenwechsel enthält, misst den Wechsel.

### Folge für die Prämisse

Der Nutzer, 2026-09-19: *„An der Prämisse, ein Kegel kann nicht falsch
leuchten nur falsch aus sein, dürfen wir nicht rütteln, wegen dem Blinken."*

Sie bleibt gültig — **solange die Tafel ein Ergebnis zeigt.** Im Fehlercode
gilt sie nicht: dort leuchten Lampen, die keinen gefallenen Kegel meinen. Die
Aggregation über das Maximum ist also richtig; sie braucht nur eine Grenze,
und die Grenze ist der Fehlercode, nicht die Zeit.

## 2026-09-25 — Wieviel Raum die Grundlinie hat, und wie lange die Anzeige braucht

Anlass: Der Fehlercode (siehe oben) leuchtet nach dem Grün-AN des nächsten
Zyklus noch rund zwei Sekunden nach. Am GIF abgelesen, Bahn 4:

```
47093  OFF  [1..9]              Wurfnr 022    Fehlercode blinkt
47103  ON   [1..9]              022           <-- GRÜN AN
47117  ON   [1..9]              022           ... Code blinkt weiter
47141  ON   [1,2,3,6,7,8,9]     022           ab hier ruhig: 7 Kegel liegen
```

Der Nutzer dazu: *„der Code ist noch kurz an, und leuchtet sogar dabei nochmal
merkwürdig zwischen."* Seine Regel („vor der Freigabe ist das Problem immer
behoben") und die Messung widersprechen sich nicht — behoben ist die
**Störung**, nachleuchten tut die **Anzeige**.

### Ein fester Anlauf ist widerlegt

Der Nutzer hatte den Einwand gleich mitgeliefert: *„Bei der Grundlinie müssen
so späte Frames wie möglich genommen werden, was aber spät heißt ist davon
abhängig, wann der nächste Wurf stattfindet, gerade beim Räumen haben wir
teils sehr kurze Zyklusräume."*

Gemessen — Raum zwischen Grün-AN und dem ersten dazukommenden Kegel:

```
Art          N   Median   p10   p05   p01   min    davon < 40 Frames
Vollen    1407      133    84    71    56    14      3  (0,2 %)
Räumen     206       84    47    38    27    14     11  (5,3 %)
```

Ein fester Anlauf von 40 Frames (2,0 s) würde die Grundlinie in **11
Räumwürfen** hinter den ersten fallenden Kegel schieben, um **2** Fälle zu
retten. Netto schlechter. Das aktuelle Fenster `baseline_offsets: [0,6,12,18,25]`
sitzt schon nah an der Grenze.

### Warten statt Zählen kostet nichts

Frames vom Grün-AN, bis der Lampenstand dreimal hintereinander gleich ist:

```
Art          N   Median   p90   p99   max    >= 30 Frames
Vollen    1489        2     2     4    39      2  (0,1 %)
Räumen     206        2     3    20    38      1  (0,5 %)
```

**Median zwei Frames.** Die drei Zyklen mit 30 Frames und mehr sind die beiden
bekannten Fehlercode-Nachfolger (F47674, F139069) und **eine Messlücke**
(Bahn 4, Grün-AUS 185000: völlig normaler Räumwurf, die erste Lampenmessung
kam erst 38 Frames nach dem Grün-AN der Grünspur).

Diese Messlücke ist selten: Versatz der ersten Lampenmessung nach Grün-AN über
1698 Zyklen — Median 2, p99 6, **>= 30 Frames nur 2-mal (0,1 %)**.

### Gegenprobe des Blink-Erkenners an etikettierten Würfen

`tools/pruefe_blinkerkennung.py`. Etiketten aus Kegelziffer und Tafelsumme,
nicht aus den Lampen. Anlauf an den ungeraden Spielen gesucht, an den geraden
geprüft.

```
FEHLALARME (gesunder Wurf als Fehlercode beurteilt): 0 von 1169
Trefferquote Eichung 98,6 %, Prüfung 97,7 %
Anlauf 0 bis 90 Frames: unverändert 98,6 %
```

Der Anlauf bringt in der Breite nichts — das Muster entsteht nicht beim
Umschalten der Anzeige, sondern nur dort, wo ein Fehlercode nachleuchtet.

Von 22 abweichenden Urteilen hat der Erkenner in 21 recht und das Etikett
unrecht: 19-mal BUG-034 (Bahn 5, Lampe 8 fehlt im Wurfbild, der Neuner wird
trotzdem als Blinken erkannt), 2-mal ein Fehlercode, der erst **nach**
Grün-AUS beginnt und in der Grünphase deshalb korrekt „ruhig" ist. Ein
einziger echter Fehler: Bahn 3, Spiel 13, Wurf 4 — ein Neuner nicht als
Blinken erkannt.

### Fehler in der ersten Fassung der Messung

1. Das Etikett verlangte zusätzlich eine passende Tafelsumme und schrieb sonst
   „ruhig". Die Summe ist das schwächste Feld; 295 Würfe landeten dadurch
   falsch in der Gegenprobe. **Wo die Ziffer schweigt, gibt es kein Etikett,
   nicht das Etikett „ruhig".**
2. Das Einschwingen wurde nur an Frames gemessen, an denen mindestens eine
   Lampe brennt. In den Vollen ist der Satz frisch gestellt, alle Lampen aus —
   dieser Zustand fehlte ganz, und das Einschwingen schien erst mit dem ersten
   fallenden Kegel zu beginnen (Median 140 statt 2).

## 2026-09-25 — Sechs Varianten fuer Grundlinie und Ergebnis, keine gewinnt

Nutzer: *„miss das noch... und miss bitte weitere Moeglichkeiten das zu
loesen"*. Alle gegen die Kegelziffer, 1243 Wuerfe mit lesbarer Ziffer.

```
Ergebnisfenster            G1 Vereinigung     G2 Plateau
E1 Vereinigung alles        1160   93,3%   1160   93,3%    <- heute
E2 nur bis Gruen-AUS        1140   91,7%   1140   91,7%
E3 letzter Stand             816   65,6%    815   65,6%
E4 Mehrheit                   97    7,8%    101    8,1%
E5 letztes Plateau           751   60,4%    750   60,3%
E6 alles, ausser Fehlercode 1157   93,1%   1157   93,1%
```

G1 ist die Grundlinie von heute (Vereinigung ueber `baseline_offsets`), G2 das
erste Plateau, nach dem keine Lampe mehr ausgeht. **Die Grundlinienvariante
macht keinen Unterschied** — G1 und G2 liegen ueberall gleichauf; ueber alle
Wuerfe gerechnet 2 besser, 2 schlechter.

**Der heutige Stand ist der beste gemessene.** Die Einzelbefunde:

* **Das Fenster bei Gruen-AUS abzuschneiden kostet 20 Wuerfe**, um 2 zu
  retten. Die Messungen nach Gruen-AUS tragen echte Information -- eine Lampe,
  die vorher zu dunkel war, wird dort noch erkannt.
* **Die Mehrheit statt der Vereinigung ist katastrophal** (7,8 %). Erwartbar:
  Beim Blinken ist jede Lampe die halbe Zeit aus. Das ist der Zahlenbeleg fuer
  die Praemisse des Nutzers, an der nicht geruettelt werden darf.
* **Auch die chirurgische Variante verliert.** E6 nimmt das Fenster nach
  Gruen-AUS nur dann heraus, wenn dort das Fehlercode-Muster steht -- und
  kommt trotzdem auf 1157 statt 1160.

### Was das fuer BUG-036 heisst

Die zwei Fehlercodes kosten auf Bahn 4 zwei Spiele mit je +10 Kegeln. Jede
gemessene Gegenmassnahme kostet mehr. **Empfehlung: nichts aendern**, den
Befund stehenlassen und die betroffenen Spiele von Hand korrigieren -- die
Tafel meldet die Stoerung ja selbst, sie ist an der Anzeige erkennbar.

Falls Fehlercodes haeufiger werden (etwa an einer stoerungsanfaelligen Bahn),
liegt die Erkennung fertig gemessen vor: 0 Fehlalarme auf 1169 gesunden
Wuerfen. Dann waere neu abzuwaegen.


## Der Wurf NACH dem Fehlercode (2026-09-29)

Nach dem Fehlercode-Filter (BUG-036) blieben zwei Spiele auf Bahn 4 um je
**8 Kegel** zu hoch — nicht der Fehlercode-Wurf, sondern der Wurf danach:

```
Spiel  4   Wurf 22 = 7 (Fehlercode, korrigiert)   Wurf 23 gebucht 9, Tafel 1
Spiel 10   Wurf 20 = 7 (Fehlercode, korrigiert)   Wurf 21 gebucht 9, Tafel 1
```

### Die Tafel wird waehrend des Fehlercodes KOMPLETT dunkel

Gemessen zwischen Gruen-AUS von Wurf 22 (F46676) und Gruen-AN von Wurf 23
(F47103), Bahn 4, Helligkeit je Kegellampe (AN-Schwelle rund 215):

```
46850   1:240  2:244  3:235  4:247  5:242  6:240  7:244  8:240  9:243
46875   1:198  2:189  3:184  4:189  5:187  6:188  7:183  8:178  9:185
46900   1:187  2:186  3:182  4:178  5:178  6:179  7:173  8:166  9:178
46925   1:195  2:191  3:187  4:195  5:189  6:243  7:244  8:173  9:245
```

2,5 Sekunden lang alles dunkel, im zweiten Fall 3,75. Das ist keine
Dunkelphase des Blinkens — auch die dauerleuchtenden 6, 7, 9 sind aus.
Im GIF (`debug/streitfaelle/streit_bahn4_f46576-47220.gif`, 182 Bilder) ist
die Ziffernanzeige dabei weiter zu lesen (`022 / 7 / 0170`); es ist also
nicht die Bahn verdeckt, sondern die Lampenreihe selbst aus.

`grundlinie_aus_spur` nimmt den kleinsten Stand über eine Blinkperiode
seit dem vorigen Gruen-AUS — und der ist damit leer.

### Der Code leuchtet in die Gruenphase nach

```
47103  Gruen-AN
47105  .....67.9   Fehlercode
47117  123456789   Fehlercode
47130  ...4567.9   Fehlercode, letztes Aufflackern
47140  123..6789   der wahre Stand, 23 Sekunden lang unveraendert
47605  1234.6789   Kegel 4 faellt
47674  Gruen-AUS
```

Leere Grundlinie, Ergebnismenge mit dem Code darin: neun statt einem Kegel.

### Varianten, gemessen gegen die Tafelsumme (1473 Wuerfe)

`SummeTafel(N+1) - SummeTafel(N)` ist die Kegelzahl von Wurf N — der
unabhängigste Zeuge, und anders als die Kegelziffer auf Bahn 4 auch
lesbar. Heutiger Stand: 1410 richtig (95,7 %).

```
Plateau-Regel (tools/simuliere_plateau.py)
  Plateau >= 1,0 s   1411   95,8 %    BESSER 4 | SCHLECHTER 3
  Plateau >= 2,0 s   1401   95,1 %    BESSER 5 | SCHLECHTER 14
  Plateau >= 3,0 s   1360   92,3 %    BESSER 4 | SCHLECHTER 54
  Plateau >= 5,0 s   1135   77,1 %    BESSER 4 | SCHLECHTER 279

Vorstand-Regel (tools/simuliere_vorstand.py)
  nur Grundlinie                      Bahn 4 Wurf 23 wird 2 statt 1
  Grundlinie UND Ergebnisbeginn
                     1412   95,9 %    BESSER 4 | SCHLECHTER 2
                     Anker in 1671 von 1678 Wuerfen gefunden
```

Längere Plateaus sind deutlich schlechter, weil der **Ergebnisstand
ebenfalls ein Plateau ist und ebenfalls monoton**: Wird die Schwelle zu lang,
rastet die Grundlinie erst nach dem Fall ein und der Wurf wird null.

Die Vorstand-Regel (Nutzeridee): Die Grundlinie darf nur leer sein oder der
Stand des vorigen Wurfs, und der Wurf beginnt, wenn die Tafel einen der
beiden zeigt. Sie erwähnt den Fehlercode nicht — alles, was weder
das eine noch das andere ist, ist Nachleuchten. Volle und Abräumen
unterscheidet sie von selbst.

### Im echten Video nachgemessen

Zwei gezielte Läufe über alle vier Bahnen, verglichen gegen den
Vollauf vom 2026-09-28:

```
Fall 1  F38500-48600    92 vergleichbare Wuerfe   89 -> 91 richtig
  Bahn 4 Wurf 23   alt 9 -> neu 1   Tafel 1
  Bahn 5 Wurf 25   alt 2 -> neu 1   Tafel 1

Fall 2  F130500-140200  58 vergleichbare Wuerfe   51 -> 57 richtig
  Bahn 4 Wurf 21   alt 9 -> neu 1   Tafel 1
  Bahn 5 Wurf  8   alt 6 -> neu 7   Tafel 7
  Bahn 5 Wurf  9   alt 8 -> neu 9   Tafel 9
  Bahn 5 Wurf 10   alt 7 -> neu 8   Tafel 8
  Bahn 5 Wurf 14   alt 8 -> neu 9   Tafel 9
```

Acht besser, keiner schlechter. **Die Bahn-5-Zeilen gehören nicht der
Regel**: Diese Läufe benutzten zugleich die korrigierte Kalibrierung
`2Spieltag_neu.json`. Deren einziger Unterschied liegt auf Bahn 5 —
`pin_lamp_3` (Kegel 8) um 2,7 px und `pin_lamp_6` (Kegel 6) um 6,6 px nach
oben:

```
Bahn 5, Kegel 8, Helligkeit ueber F38500-48600 (Schwelle 215)
  alte Kalibrierung   Median 147,7   p90 213,5   p99 216,8
  neue Kalibrierung   Median 179,1   p90 255,0   p99 255,0
```

Bahn 2, 3 und 4 sind unverändert kalibriert; was sich dort ändert,
ist ausschließlich die Regel — und dort liegen beide Zielwürfe.

### Eine einzelne flackernde Lampe ist kein Fehlercode

Nutzer: *„es gab nur 2 Fehlercodes im ganzen Spiel und meines Wissens
nach alle auf Bahn 4."* `ist_fehlercode` meldete fünf. Die vier
überzähligen lagen auf Bahn 5 und waren alle Kegel 8 (BUG-034), der
binnen zwei Sekunden zweimal flackerte.

```
blinkende Lampen >= 1   5 Treffer   (Bahn 4: 1, Bahn 5: 4)
blinkende Lampen >= 2   1 Treffer   (Bahn 4: 1)

Beide echten Codes, an den Messreihen der Pipeline geprueft:
  Fall 1, 11 Messungen   blinkend [1,2,3,4,5,8]   fest [6,7,9]
  Fall 2, 16 Messungen   blinkend [1,2,3,4,5]     fest [6,7,8,9]
```

`sampling.error_code_min_blinking_lamps: 2`.

### Der Vollauf ueber den ganzen Spieltag (2026-09-29, 110 min)

Regel eingeschaltet, dazu die korrigierte Kalibrierung `2Spieltag_neu.json`:

```
                                   alt (28.09.)      neu
  Wuerfe                           1678              1679
  gegen die Tafelsumme richtig     1410  95,7 %      1437  97,6 %
  Lampen/Ziffer/Summe einig        1099  65,8 %      1131  67,7 %
  Tafelprobe Wurf fuer Wurf        1474  97,2 %      1477  97,4 %
  Spiele mit falschem Endstand        4 von 60          1 von 60
  Luecken                             2                 1
  nachtraegliche Korrekturen         39                 0
  Gruenzyklen ohne Ergebnis          13                12
  Fehlercode-Meldungen               19                 2
```

Null Wuerfe schlechter bei 1678 gepaarten. Nach Ursache getrennt -- Bahn 2,
3 und 4 sind unveraendert kalibriert, dort wirkt nur die Regel:

```
  Bahn 2    0 Unterschiede
  Bahn 3    0 Unterschiede
  Bahn 4    2 Unterschiede -- beide besser, beide die Zielwuerfe  (Regel)
  Bahn 5   39 Unterschiede -- 25 von der Tafelsumme bestaetigt    (Kalibrierung)
```

Die Regel meldete sich am ganzen Spieltag zweimal, an genau den Wuerfen, fuer
die sie gebaut ist. Der Fehlercode-Filter zweimal statt neunzehnmal -- die
siebzehn Fehlalarme waren Bahn 5 Kegel 8.

Nebenbefund: Die nachtraegliche Korrektur der Wurftabelle findet nichts mehr
zu korrigieren; vorher waren es 39 Wuerfe.

## Die Kegelziffer auf Bahn 4 sitzt einen Pixel daneben (2026-09-29)

Der Vollauf meldete neun Wuerfe, in denen Lampen und Kegelziffer sich
widersprechen -- siebenmal `7` gelesen als `3`, zweimal `1` gelesen als `3`.
Die Tafelbilder zeigen, dass die Tafel recht hat:

```
Frame 204625   Tafel 001 | 7 | 0000   gelesen 3   Lampen 1,2,3,4,7,8,9 = 7
Frame  35111   Tafel 030 | 1 | 0188   gelesen 3   Lampen alle aus = 1
```

Belege: `debug/streitfaelle/beleg_ziffer_wird_3.png`,
`debug/streitfaelle/streit_bahn4_f204537.gif`. Ein dritter, unabhaengiger
Zeuge steckt in den Zahlen: Spiel 15 und Spiel 16 haben je dreimal 7, und die
Tafelsumme steht danach auf 21.

### Gemessen (tools/messe_ziffernversatz.py)

Das Mass ist die TAFELSUMME -- `SummeTafel(N+1) - SummeTafel(N)` weiss nichts
von den Lampen und nichts vom Ziffernleser. Der Rahmen wird probeweise
verschoben, gezaehlt wird die Uebereinstimmung.

```
Feld pin_count      heute              bester Versatz       dort
  Bahn 2            191/191  100,0 %   (0,0)                --
  Bahn 3            168/181   92,8 %   (0,-2)               169   93,4 %
  Bahn 4             89/191   46,6 %   (-1,0)               191  100,0 %
  Bahn 5            177/178   99,4 %   (0,0)                --

Bahn 4, Rasterausschnitt (Treffer von 191):
dy\dx    -2    -1     0     1     2
  -1     180   179    81    13     9
   0     188   191    89    14     9
   1     188   191   105    18    11
```

**Nur Bahn 4, und genau ein Pixel.** Die Verwechslungen bei (0,0):

```
7 gelesen als 3   33x      8 gelesen als 6    9x
9 gelesen als 5   31x      8 gelesen als 5    8x
1 gelesen als 3   13x
```

Auf die gebuchten Ergebnisse wirkt das nicht -- die Lampen entscheiden, die
Ziffer wird bei Widerspruch als strittig protokolliert. Es kostet aber 102
von 191 Wuerfen ihren zweiten Zeugen, und zwar auf der Bahn, deren
Tafelsumme ohnehin am haeufigsten schweigt.

Bahn 3 behaelt 13 Fehler, die KEIN Versatz repariert -- das ist etwas
anderes und bleibt offen (`docs/OPEN_QUESTIONS.md`).


## Die Gruenlampen-ROI auf Bahn 4 und 5 (2026-10-02)

Auf Bahn 5 fehlte Wurf 19 des Laufs 1.4 -- der Nutzer hat ihn an der Tafel
abgelesen (*„Wurf 19 ist eine 1 auf Kegel 8 ... Die Zeit ist exakt 01:01:56"*).
Die Bahn hatte den unschaerfsten Gruenkanal aller vier, also wurde die ROI
nachgemessen: `tools/fit_green_lamp.py` legt sie ueber etikettierte
Referenzframes aus der Gruenspur neu.

Gegenprobe ueber 2000 Bilder (Frame 64000-104000), beide ROIs normiert auf
dieselbe Groesse, damit nur die LAGE verglichen wird:

```
=== vorher ===
Bahn       AUS      AN   Abstand   Fisher  Graubereich
2         25.5    63.5      37.9     38.2         0.8 %
3         22.9    61.4      38.5     33.0         4.0 %
4         31.4    60.0      28.6     16.0         9.3 %
5         25.7    64.3      38.6     19.7         9.8 %

=== nachher ===
4         50.3    85.3      35.0     25.7         5.1 %
5         34.8    74.0      39.2     20.3         5.9 %
```

Der Graubereich -- der Anteil der Messungen, der naeher an der Schwelle liegt
als ein Viertel des Wolkenabstands -- halbiert sich auf beiden Bahnen. Bahn 5
Wurf 19 ist seitdem da, mit allen drei Zeugen einig:

```
F74420  Wurf 19  1 Kegel [8]  Ziffer 1  Tafel 141 (vorher 133, danach 142)
```

**Und die Verbesserung auf Bahn 4 kostete zuerst drei Wuerfe.** Das AUS-Niveau
stieg dabei von 31,4 auf 50,3, also ueber die feste globale AN-Schwelle von
45. Warum das drei Wuerfe kostet und was dagegen gebaut wurde:
BUG-038 und der uebernaechste Abschnitt.

## Ein mitlaufendes Fitting der Gruenlampen-ROI: gemessen, nicht gebaut (2026-10-02)

Nutzerfrage: *„aber koennte man daraus nicht bei einem Livestream theoretisch
ein fitting bauen? ... das sollte halt irgendwie nicht unsupervised laufen,
bevor dann die Lampe die ganze Zeit aus oder an ist (weil sie gar nicht mehr
auf der Lampe liegt)."*

Die Sorge im Nachsatz ist genau die richtige, und sie trifft den ersten
Ansatz ins Mark.

**Weg A -- eine Kennzahl ueber Lage und Groesse maximieren** (Fisher nach
Otsu; Otsu deshalb, weil ein Livestream keine Etiketten hat).
`tools/messe_gruenfit_stabilitaet.py`. Ergebnis: untauglich.

- Ohne Sicherungen gewannen die **Ecken des Suchraums** mit Fisher 5,6e+31.
  Eine ROI neben der Lampe liest fast immer denselben Wert, Otsu zerlegt auch
  das in zwei Punkte, und Abstand²/Streuung explodiert. Das ist exakt der
  Fall, den der Nutzer vorhergesagt hat.
- Mit Mindestwolkenanteil (10 %) und Streuungsboden lief die **Groesse** an
  den Rand des Suchbereichs.
- Die **Lage** streute auf Bahn 4 und 5 um bis zu 12 px zwischen Fenstern --
  ausgerechnet auf den beiden Bahnen, die einen Fehler hatten.

Eine Kennzahl weiss nicht, wie eine Lampe aussieht. Sie hat entartete
Richtungen, und ein Wachhund waere ihnen gefolgt.

**Weg B -- das Signalbild statt einer Suche.** Nutzeridee: *„wie waere es,
wenn wir anhand aller Gruenlampenbilder die wir haben (aus unserer Gruenspur)
auch dort ein Bild-in-Bild Suche machen?"* Ist bekannt, wann die Lampe an war,
dann ist

```
Signal(Pixel) = P(Pixel gruen | AN) - P(Pixel gruen | AUS)
```

ein direktes Bild der Lampe. Keine Suche, kein Suchraumrand, keine
Groessenfreiheit. `tools/messe_lampensignal.py`, gerechnet auf 16 001
Ausschnitten je Bahn aus `tools/sammle_gruenfelder.py`:

```
Bahn   AN / AUS      Gipfel   Flaeche > halber Gipfel   Lampenmitte (Zeile, Spalte)
  2   9241 / 6716     1.00          35 px                  9.29  10.60
  3   9130 / 6710     1.00          34 px                 10.76  10.49
  4   8728 / 6923     1.00          27 px                  9.10  10.53
  5   9543 / 5786     0.99          41 px                 10.02  10.41
```

Die Spalte stimmt ueber alle vier Bahnen auf 0,2 px ueberein -- bei baugleichen
Tafeln ist das die Gegenprobe. Und die Schaetzung ist **stabil**, hier Bahn 5:

```
Fenster  Anzahl  dx median  dx Streuung  dx max-Abw  dy max-Abw
    200      69       0.01         0.19        0.62        0.62
    800      20      -0.01         0.11        0.32        0.48
   3200       5      -0.04         0.08        0.15        0.27
```

Schon 200 Ausschnitte reichen fuer eine Lage auf einen Dreiviertelpixel.

**Trotzdem nicht gebaut.** Der gemessene Versatz der heutigen ROIs liegt bei
0,4 bis 1,2 px -- unter dem, was eine Verschiebung rechtfertigt, und die
Etiketten stammen aus der bisherigen ROI, sind also leicht zirkulaer. Ein
mitlaufender Wachhund hat damit nichts zu korrigieren, aber jede Menge
Gelegenheit, etwas kaputtzumachen. **Weg A ist widerlegt, Weg B ist moeglich
und unnoetig.** Wenn das Thema wiederkommt: Weg B nehmen, nie Weg A.

## Der Anlauf: ohne zweite Wolke zaehlt nur die Aenderung (2026-10-06)

Zu Beginn einer Aufzeichnung ist die Anlage freigegeben und die gruene Lampe
durchgehend an. Histogramm und Perzentile brauchen beide Zustaende im Fenster,
finden also nichts; es traegt allein die feste globale Schwelle 45/35.
GEMESSEN am 2. Spieltag, Frame des ersten echten Gruen-AUS:

```
Bahn 2   7558       Bahn 4   10480   (achteinhalb Minuten)
Bahn 3  10400       Bahn 5    5607
```

Dass die feste Schwelle dort passt, ist Zufall -- sie ist keine Eigenschaft
der Anlage, sondern eine der ROI. Die bessere Bahn-4-ROI hob das AUS-Niveau
auf 50,3 und damit darueber; die Lampe ging im Anlauf nie aus, und die ersten
drei Wuerfe des Spieltags fehlten (BUG-038).

Nutzeridee: *„am Anfang brauchen wir eine Aenderung > 10 oder so"*. Eine
Aenderung haengt an keiner ROI. Frame des ersten erkannten Gruen-AUS, beide
Vollaeufe:

```
                     absolut   >5     >10     >15     >20
  alte ROIs  Bahn 2     7558    161   3200    7557    7558
             Bahn 3    10400     40  10392   10392   10399
             Bahn 4    10480     79   1801   10479   14124
             Bahn 5     5607    977   5605    5605    5605
  neue ROI   Bahn 4     KEINS    91   2097   10470   10479
             Bahn 5     5607     87   5605    5605    5605
```

Bei 15 trifft die Regel ueberall dasselbe AUS wie die absolute Schwelle, ohne
Fehlausloeser davor, und findet es auch dort, wo die absolute Schwelle nichts
findet. `detection.green.warmup_min_change: 15.0`.

**Vollauf zum Nachweis** (2026-10-06, 242 255 Frames, gegen den Lauf vom
2026-09-29):

```
                              vorher     nachher
Wuerfe                          1679        1680
Luecken                            1           0
Spiele mit falschem Endstand    1/60        0/60
Gegenprobe: Lampen gegen Ziffer    0           0
            Summe stuetzt eine Seite gegen die andere: 0
```

Wurf fuer Wurf: 1482 vergleichbar, 1446 in BEIDEN Laeufen richtig, keine
einzige geaenderte Kegelzahl. Der einzige Unterschied ist Bahn 5 Wurf 19.
Die 44 Ziffernwidersprueche auf Bahn 4 aus dem Vorlauf sind mit dem
Ziffernversatz von einem Pixel ebenfalls weg -- Bahn 4 steht jetzt in jedem
Lauf auf 29/29.


## Das Wurfprotokoll war falsch ausgerichtet (2026-10-06)

Der Vergleich gegen das handgefuehrte Wurfprotokoll ist die einzige Kennzahl
dieses Projekts, die nicht aus dem Bild stammt. Sie stand wochenlang bei
**88,8 Prozent**, und niemand hat ihr misstraut -- auch nicht, als die
Zeile oben mit „720/720" danebenstand. Die 720 war die Spalte **erfasst**
(alle Wuerfe gefunden), nicht die Trefferquote.

Aufgefallen ist es erst, als dasselbe Werkzeug den frischen Lauf vom
1. Spieltag bewertete und wieder exakt 88,8 Prozent meldete, waehrend drei
andere Pruefungen den Lauf fuer fast fehlerfrei hielten:

```
gegen die Tafelsumme, Wurf fuer Wurf     1402/1452   96,6 %
Lampen gegen Kegelziffer                   17/1561
gegen die amtliche Ergebnistafel          45 von 48 Spielen exakt
```

**Der Widerspruch loest sich an einer Zeile des Werkzeugs selbst:** *„Von 81
falschen Wuerfen haette die Ziffernanzeige 0 richtig gehabt."* In ALLEN 81
Faellen stimmten unsere Lampen mit der Kegelziffer der Tafel ueberein. Zwei
unabhaengige Lesungen desselben Bildes gegen das Protokoll -- das ist kein
Erkennungsfehler, das ist eine falsche Zuordnung.

### Warum die freie Ausrichtung hier nicht funktionieren kann

`wurfprotokoll_spieltag_1.csv` deckt nur die Heimmannschaft ab, sechs von
zwoelf Spielern. Zwischen zwei Protokollbloecken liegen also die 30 Wuerfe
des Gegners. Die Ausrichtung nahm die Bahn als EINE Wurffolge und klebte
einen Block ueber zwei Spiele hinweg zusammen:

```
Protokollblock "Bahn 2, Satz 2, ein Spieler", 30 Wuerfe
   Wurf  1-10  zugeordnet an unser Spiel 5
   Wurf 11-30  zugeordnet an unser Spiel 6
im selben Zeitfenster liegen 75 unserer Wuerfe
```

### Die blockweise Ausrichtung

Ein Block des Protokolls (eine Bahn, ein Satz, ein Spieler, 30 Wuerfe) ist
genau EIN Spiel des Laufs. Verglichen wird innerhalb des Paares ueber die
**Wurfnummer der Tafel** -- eine Groesse, die weder aus unseren Lampen noch
aus dem Protokoll stammt, und die einen verlorenen Wurf als Luecke stehen
laesst, statt alles dahinter zu verschieben.

```
                        frei     block
Lauf vom 2026-10-06   639/720   720/720   (88,8 % -> 100,0 %)
Lauf vom 2026-09-03   639/720   626/720   (86,9 %)
```

Der September-Lauf ist also wirklich schlechter -- die freie Ausrichtung hat
beide Staende auf dieselbe Zahl eingeebnet.

**Zwei Annahmen sind dabei gescheitert, und beide stehen jetzt im Test:**

1. *Die Bloecke kommen in derselben Reihenfolge wie unsere Spiele.* Nein. Im
   Protokoll stehen sie nach Satz und Spieler sortiert, auf der Bahn spielen
   die Saetze verschraenkt: Ein Trio wandert die Bahnen 3-4-5-2 ab, das
   andere 5-2-3-4. Mit Monotonie kam die Ausrichtung auf **68,2 Prozent** --
   schlechter als der Fehler, den sie beheben sollte. Gebaut ist jetzt eine
   echte Zuordnung ohne Ordnungsannahme (Tiefensuche mit oberer Schranke).
2. *Ein Spiel des Laufs ist ein Block.* Meistens. Hat die Anlage mittendrin
   neu begonnen, steht es bei uns als zwei Spiele mit sich ergaenzenden
   Wurfnummern (gemessen: Bahn 5, 1-18 und 19-30). Die werden zusammengelegt.

Die gewaehlte Zuordnung wird mit ausgegeben. Beim Lauf vom 2026-10-06 ist sie
vollkommen regelmaessig -- je Bahn jedes fuenfte Spiel, in zwei Versaetzen --,
ohne dass das vorgegeben waere. Das ist die beste Gegenprobe, die es dafuer
gibt. Beim September-Lauf ist sie es NICHT, und das ist ebenfalls ein Signal:
Wo viel falsch erkannt wird, rutscht auch die Zuordnung.

### Was der 1. Spieltag damit wirklich wert ist

```
gegen das Wurfprotokoll (720 Wuerfe)       720/720   100,0 %
gegen die amtliche Ergebnistafel (48)       45/48
Spieltagstotal            wir 9756, amtlich 9763   (-7)
```

Alle drei abweichenden Spiele gehoeren zur **Gastmannschaft**, die das
Protokoll nicht abdeckt:

| Bahn | Spiel | Abw. | Befund |
|---|---|---|---|
| 5 | 17 | −7 | **Wurf 7 fehlt** -- die Tafel zeigt `007 / 7 / 0049`, bei uns springt die Nummer von 6 auf 8. 194 + 7 = 201 = amtlich. |
| 2 | 15 | +2 | Die Tafel zeigt am Spielende selbst `0196`, die Summenkette stimmt Wurf fuer Wurf. Der Spielberichtsbogen sagt 194. |
| 3 | 16 | −2 | Die Tafel zeigt am Spielende selbst `0213`, alle 30 Wuerfe mit Ziffer und Summe einig. Der Bogen sagt 215. |

Die beiden ±2 heben sich im Spieltagstotal auf; aus dem Video sind sie nicht
zu entscheiden. Belege: `debug/fehlwuerfe/streit_bahn2_f280550-281500.gif`
und `debug/fehlwuerfe/streit_bahn3_f302700-303650.gif`.

**Und ein Nebenbefund:** In Spiel 17 auf Bahn 5 lesen die Lampen fuenfmal 9,
wo die Kegelziffer 7 zeigt. Die Lampen haben recht -- die Tafelsumme steht
vor Wurf 26 auf 173 und vor Wurf 29 auf 192, bei Wurf 26 = 1 bleiben fuer die
Wuerfe 27 und 28 genau 18. Das ist BUG-009 in neuem Gewand: die 9 ohne
unteren Balken.

## Der fehlende Wurf auf Bahn 5: zwei Wuerfe in einer Gruenphase (2026-10-06)

Die einzige echte Luecke des 1. Spieltags. Bahn 5, Spiel 17: amtlich 201,
von uns 194. `tools/compare_protocol.py --ausrichtung block` zeigte den
Sprung der Tafel-Wurfnummer von 6 auf 8.

**Die Gruenspur, Bahn 5:**

```
F286392   Gruen AUS  Score 53,6     Wurf 6 wird gebucht (7 Kegel)
F286570   Gruen AN
F286950   Score 57,1  UNKNOWN       tiefster Punkt der ganzen Phase
F287402   Gruen AUS  Score 53,6     Wurf 8 wird gebucht
```

832 Frames, 33 Sekunden, EINE Phase. Der Score haette unter 52,5 fallen
muessen; er kam bis 57,1 und blieb damit in der Totzone zwischen AUS- und
AN-Schwelle.

**Die Lampenspur sagt, was wirklich geschah:**

```
F286500  an=[]                  die Anlage stellt auf
F286750  an=[1,2,3,6]           WURF 7 faellt
F286775..286890                 Blinken, Takt rund 30 Frames, alle neun
F287005  an=[]                  die Anlage stellt auf
F287220  an=[1,2,3,6]           WURF 8 faellt
F287225  an=[1,2,3,6,7,8,9]     7 Kegel
```

Zwei vollstaendige Wurfbilder in einer Gruenphase, dazwischen geraeumt.

**Der Schaden hat zwei Haelften, und die Rechnung geht exakt auf:**

```
Wurf 7 = 9 (Alle Neune)   nicht gebucht      -9
Wurf 8 = 7                gebucht als 9      +2
                                             --
                                             -7      194 + 7 = 201 = amtlich
```

Die zweite Haelfte ist der neue Teil: **Die Blinkbilder von Wurf 7 liegen im
Ergebnisfenster von Wurf 8.** Der Blinkfilter aus BUG-036 greift nicht -- der
entfernt Blinken NACH dem Gruen-AUS, dieses liegt mitten in der Phase.

### Ein Erkenner dafuer, falschalarmfrei

`tools/finde_zwei_wuerfe_in_einer_gruenphase.py`. Blinken und ein zweiter
Wurf sehen gleich aus -- Licht, dunkel, Licht. Der Unterschied ist die Pause:

```
Blinken (Alle Neune, 8er Kranz)   rund 30 Frames Takt
zweiter Wurf                      raeumen, aufstellen, ausholen -- Hunderte
```

Zusammengelegt wird alles unter 60 Frames, gemeldet nur, was danach noch
mindestens 120 Frames Dunkelheit laesst. Eine dritte Bedingung macht es erst
brauchbar: Das erste Bild muss NACH dem Raeumen entstanden sein -- steht es
schon beim Gruen-AN, ist es das Nachleuchten des vorigen Wurfs. Ohne sie
kommt genau ein Fehlalarm je Spieltag.

```
GEMESSEN ueber zwei volle Spieltage, 3359 Wuerfe:
   1. Spieltag   1 Fund    Bahn 5, F286570-287402   <- der echte Fall
   2. Spieltag   0 Funde
```

Beleg: `debug/fehlwuerfe/streit_bahn5_f286300-287500.gif`. Fortschreibung in
BUG-035, Fall C.

