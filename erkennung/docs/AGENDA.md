# Behebungsagenda (Stand 2026-08-31)

Entstanden aus der Auswertung des Spieltags vom 2026-08-29 gegen
`Wurfprotokoll_Spieltag_1.pdf` (720 Würfe, 6 VOK-Spieler, 4 Bahnen).

Ausgangslage: **Bahn 5 bei 157/180 (87 %)**, Bahn 2 und 3 vollständig bei
100 % zugeordnet. Alle Punkte hier sind am Material gemessen, nicht vermutet.

---

## ERGEBNIS: 720 von 720

Vollständiger Lauf vom 2026-08-31 (86,7 min, 312 784 Frames, 1690 Würfe):

```
24 von 24 Saetzen sicher zugeordnet
Getroffene Wuerfe in den sicheren Funden: 720
```

| Bahn | Ausgangslage | nach A2 | **jetzt** |
|---|---|---|---|
| 2 | 180/180 | 180/180 | **180/180** |
| 3 | 180/180 | 180/180 | **180/180** |
| 4 | — | 156/180 | **180/180** |
| 5 | 157/180 | 179/180 | **180/180** |

Würfe je Bahn ausgeglichen, 0 Duplikate, Lauf endet von selbst.

### Struktur nach A9

| | vor A9 | nach A9 |
|---|---|---|
| Spielenden Bahn 4 | 8 | **14** |
| Spiele je Bahn | 16 / 16 / **9** / 16 | 16 / 16 / **14** / 16 |
| größtes Spiel auf Bahn 4 | **172 Würfe** | 50 Würfe |
| unmögliche Summen (≥ 1000) | **37 von 234** | **1 von 174** |

**Was noch offen ist:**

* **12 Grünzyklen ohne Wurfergebnis** (0,7 %) — untersucht am 2026-08-31,
  kein Protokollwurf fehlt. 6 kurzes Flackern (4–114 Frames, richtig
  verworfen), 5 echte Zyklen (Tafel verdeckt bzw. Kegelraute unverändert),
  4 das Ende der Aufzeichnung. **Kein Handlungsbedarf.**
* **15 Würfe mit Status ERROR** — Grund ist immer derselbe: mindestens eine der
  neun Kegellampen war unlesbar (`pins.is_complete` false). Der Wert stimmt;
  wo die Ziffer lesbar ist, stimmt sie mit den Lampen überein. 11 der 16 lagen
  auf Bahn 4.
* Bahn 4 hat noch ein Spiel mit 50 und eines mit 21 Würfen.

---

## A2 — Feste Schwelle durch gleitendes Histogramm ersetzt

**Status: erledigt und am Material bestätigt** · Schwere war: hoch

Die mitlaufenden Schwellen wurden aus Perzentilen gerechnet. Die setzen
voraus, dass beide Zustände im Fenster ungefähr im erwarteten Verhältnis
vorkommen — und genau das trägt nicht. Gemessen auf Bahn 5:

| Frame | Score | P20 | P90 | Spanne | AUS-Schwelle | Zustand |
|---|---|---|---|---|---|---|
| 40903 | 47,8 | 40,0 | 70,0 | 30,0 | 52,0 | **OFF** |
| 40906 | 47,8 | 41,8 | 70,0 | 28,2 | fest: 35,0 | **ON** |

Derselbe Score, zwei Zustände. Die Bahn lag 71 % des Fensters auf AN, also war
P20 kein AUS-Niveau, sondern der untere Rand der AN-Wolke — und die daraus
errechnete AUS-Schwelle (52,0) lag **mitten in der AN-Wolke**. Die Spanne
wackelte um die Sperre `adaptive_min_span` (30,0), und die Schwelle sprang
zwischen 52,0 und 35,0.

Das Histogramm desselben Fensters ist dagegen eindeutig zweigipflig:

| Bereich | Werte | |
|---|---|---|
| 18–26 | 233 | AUS-Wolke, Gipfel 24–26 |
| 26–52 | ~250 | dünn verteilt — die Flanken |
| 52–78 | ~1069 | AN-Wolke, Gipfel 56–58 |

Das Tal liegt bei 37. Damit ist 47,8 durchgehend AN.

**Sperre (unverhandelbar, vom Nutzer festgelegt):** Gibt es nur *eine* Wolke,
wird keine Schwelle gerechnet und die zuletzt gemessene behalten. Das ist
wörtlich BUG-013.

Gegenrechnung über die volle Grünspur (297 715 Frames je Bahn): Die Zahl der
GREEN_OFF-Ereignisse ändert sich zwischen 1500 und 45000 Frames Fensterlänge
um höchstens 13 — das Verfahren hängt nicht am Fenster.

**Ergebnis am Material** (Lauf F28000–56000, dieselbe Kalibrierung):

| | vorher | nachher |
|---|---|---|
| Spieler A, Bahn 5 | 16/30 | **30/30** |
| Spieler B, Bahn 3 | 30/30 | **30/30** |
| Phantomwurf 17 bei F40903 | vorhanden | **weg** |

Kein Wurf wurde dabei erfunden und keiner verloren.

Umgesetzt in `GleitendesHistogramm` (`detection/lamp_detectors.py`),
Parameter unter `detection.green.histogram_*`, Messwerkzeug
`tools/fit_green_histogram.py`, Tests `TestA2GleitendesHistogramm`.

---

## A1 — Eingeschobener Wurf verschiebt die ganze Wurfnummernkette

**Status:** umgesetzt, greift am Material aber nicht · **Schwere:** kritisch

Regel (vom Nutzer festgelegt): Ein kurzer Grünzyklus mit 0 Kegeln, bei dem
sich **weder die Wurfnummer noch die Fehlwurfanzeige verändert**, ist kein Wurf
und wird verworfen — mit Eintrag im Protokoll.

Umgesetzt als `discard_static_zero_cycles` mit sieben Regressionstests. Am
Material greift die Regel jedoch nicht, weil beide Zeugen im entscheidenden
Frame unlesbar sind:

    Bahn 5 F40903: 0 Kegel | throw_number=None | foul_count=None (zuletzt 0)

Die Sperre „bei unlesbaren Ständen wird nichts verworfen" stammt aus BUG-008,
wo Verwerfen bei unsicherer Lesung 28 % der Würfe kostete — sie bleibt richtig.

**Durch A2 ist der Anlass entfallen:** Der Zyklus bei F40903 entsteht gar nicht
mehr. Die Regel bleibt als zweite Sicherung stehen. Ob sie schärfer gefasst
werden soll (Bezug auf den zuletzt bekannten Stand statt auf die Lesung im
Zyklus), ist offen und liegt beim Nutzer.

---

## A3 — Lampen-ROI verkleinern

**Status: hinfällig** — durch A2 erledigt, ohne dass die ROI angefasst wurde.

Anlass war Spieler E Satz auf Bahn 5: fünf Räumwürfe (1–2 Kegel)
erreichten nur einen Grün-Score von 40,0 gegen eine feste AN-Schwelle bei ~45
und fielen aus. Gegenlauf über sein Fenster (F255000–282000) mit A2:

    Spieler E, Bahn 5:  30/30   (vorher 18/30)

Die Verkleinerung hätte den Kontrast verbessert (+18,9 → +35,4), aber das
Problem lag nie am Kontrast, sondern an der Schwelle darunter. Die
Beleg-Kalibrierung `data/calibrations/1Spieltag_bahn5_klein.json` bleibt
liegen, falls ein anderer Ort ein schwächeres Signal liefert.

---

## A4 — `000 0000` trug auf keiner Bahn durch

**Status: erledigt und am Material bestätigt** · Schwere war: hoch

Bei nahezu gleicher Wurfzahl (~370 je Bahn) wurden gezählt:

| Bahn | erkannte Spielenden |
|---|---|
| 2 | **2** |
| 3 | 13 |
| 4 | 7 |
| 5 | 13 |

Zwei getrennte Fehler, beide gemessen.

### Fehler 1 — die Prüfung hing am Wurffenster

Die späten Felder wurden nur zwischen GREEN_OFF und dem nächsten GREEN_ON
gelesen. Ob ein Spielwechsel erkannt wurde, entschied damit der Zufall — nämlich
ob die Anlage die Anzeige gerade während einer Grünpause zurücksetzte.

Unabhängig nachgemessen (`tools/measure_zero_display.py`, liest ohne jede
Bedingung):

| | `000/0000` steht | Fenster offen bis | |
|---|---|---|---|
| Bahn 2 | F127115–F128475 (54 s) | F127177 — **62 Frames** | nicht erkannt |
| Bahn 3 | F126680–F128715 (81 s) | F126964 — 284 Frames | erkannt |

Auf Bahn 2 ging Grün direkt danach an und blieb 1400 Frames lang an. 1360
Frames lang sah niemand hin, obwohl die Anzeige klar lesbar auf null stand
(184 gelungene Nullmessungen).

**Nicht die Ziffernerkennung war schuld, sondern die Bedingung, unter der
überhaupt gelesen wurde.** Der Nullzustand hat jetzt einen eigenen Takt
(`game_reset_check_interval`, 25 Frames), unabhängig vom Fenster — wie der
Fehlwurfzähler, aus demselben Grund. Die Prüfung bleibt billig: Sie liest
zuerst die Summe und die Wurfnummer nur, wenn die Summe null zeigt.

### Fehler 2 — derselbe Wechsel wurde mehrfach gemeldet

Der Nullzustand steht gemessen **40 bis 91 Sekunden**; der Takt trifft ihn
darin vielfach. Jede zweite Meldung erzeugte einen Geisterlauf
(„voriges Spiel endete mit 0 Kegeln").

Eine Sperre allein reichte nicht: Sie fiel bei jeder einzelnen Fehllesung, und
Bahn 2 liest in diesem Abschnitt nur zu 67 % sicher. Gemessen wurde deshalb,
wie lang die Fehllesungs-Strähnen **innerhalb** des Nullzustands wirklich sind
(Abschnitt F164535–F166780, Takt 25 Frames):

| Bahn | Strähnen | längste |
|---|---|---|
| 2 | 17 | 3 |
| 3 | 0 | — |
| 4 | 4 | **6** |
| 5 | 0 | — |

Mit einer Schwelle von 3 meldete Bahn 4 denselben Wechsel dreimal.
`game_reset_leave_frames` steht deshalb auf **10** — vier Messungen Luft über
das gemessene Maximum. Kostet nichts: 10 Sekunden, und so schnell beginnt kein
neues Spiel.

### Ergebnis

Zwei Gegenläufe über die beiden vermessenen Spielwechsel:

```
F124000-F131000:  4 Meldungen -- Bahn 4, 3, 5, 2, je genau eine
F163000-F168500:  4 Meldungen -- Bahn 2, 3, 5, 4, je genau eine
```

Vorher: Bahn 2 fand im ersten Fenster gar nichts, Bahn 4 meldete im zweiten
dreimal. Die erkannten Frames liegen 30 bis 135 Frames nach dem unabhängig
gemessenen Beginn des Nullzustands — das ist die Bestätigungszeit.

Protokoll unverändert: Spieler A 30/30, Spieler B 30/30.

Tests: `tests/unit/test_game_reset.py` (12), gegengeprüft — beide Fehler
einzeln nachgebaut, beide werden abgefangen.

---

## A5 — Helligkeitssperre der Ziffernerkennung

**Status: erledigt und am Material bestätigt** · Schwere war: mittel

### Was zunächst falsch aussah

Die erste Messung ergab: Von 4320 beleuchteten Ziffernzellen liefern nur 58 %
ein gültiges Sieben-Segment-Muster, 32 % werden auf das nächstliegende Muster
**geraten**, 9,8 % von der Helligkeitssperre verworfen.

Die 32 % beschreiben aber nur den **Weg**, nicht die Fehlerquote. Gegen eine
belastbare Wahrheit gemessen landet die Reparatur auf Abstand 1 fast immer
richtig. Der Erkenner ist deutlich besser als diese Zahl vermuten lässt.

### Die belastbare Wahrheit (Idee des Nutzers)

Nur Würfe **in die Vollen** nehmen: Dort standen vorher alle neun Kegel, also
zeigen Lampen und Ziffer zwangsläufig dieselbe Zahl. Beim Abräumen ist das
nicht so — die Lampen zeigen kumulativ, was liegt, die Ziffer nur den aktuellen
Wurf. Erkennbar ist der Vollen-Wurf **ohne jede Ziffernlesung**: Der bestätigte
Lampenstand war vorher leer.

Was der erste, naive Versuch anrichtete: Von 288 als `9` beschrifteten Bildern
waren nur 45 wirklich eine 9 — der Rest war `7+2`, `8+1`, `5+4`. Der Erkenner
hatte recht, die Beschriftung nicht.

Auf Bahn 4 und 5 bleibt die Beschriftung unsicher, weil die Lampenlesung dort
Frame für Frame unsicher ist (die Pipeline fängt das über ihre zeitliche
Aggregation ab, ein Einzelbild-Werkzeug nicht). Gemessen wird deshalb auf
Bahn 2 und 3.

### Ergebnis

| Erkenner | vorher | nachher |
|---|---|---|
| heute, Segmentabtastung | 95,7 % | **96,5 %** |
| davon unlesbar | 13 von 420 | **1 von 402** |
| nächster Mittelpunkt (Form als Ganzes) | 96,9 % | 95,8 % |
| 3 nächste Nachbarn (Form als Ganzes) | 96,4 % | — |

**Ein formbasierter Erkenner bringt nichts.** Er liegt im selben Bereich; der
Unterschied ist bei 402 Prüfbildern nicht von Rauschen zu trennen. Die
Segmentabtastung bleibt.

### Was geändert wurde

`min_display_brightness` wird auf das **Maximum** des Rotkanals angewandt statt
auf das 95. Perzentil, Schwelle 200 statt 230. Grund: Eine `1` leuchtet mit
zwei von sieben Segmenten und bleibt gemittelt dunkler als jede andere Ziffer,
obwohl sie im Bild eindeutig ist.

Über 4800 Zellen, Anteil im unsicheren Bereich 150–245:

| Kennzahl | Anteil |
|---|---|
| 95. Perzentil (vorher) | 24,9 % |
| 99. Perzentil | 6,5 % |
| **Maximum (jetzt)** | **3,6 %** |

Dunkle Zelle: Maximum 114–119. Leuchtende: 246–255. Die Schwelle 200 liegt in
der Lücke.

**Gegenlauf gegen das Protokoll** (F28000–56000): Spieler A 30/30,
Spieler B 30/30 — unverändert. Keine falschen Widersprüche.

Werkzeuge: `tools/measure_digit_failures.py`, `tools/cluster_digits.py`,
`tools/collect_digit_samples.py`, `tools/fit_digit_classifier.py`.

---

## A6 — Bahn 4 erfand 42 Würfe über den Fehlwurfzähler

**Status: erledigt und am Material bestätigt** · Schwere war: hoch

Im vollständigen Lauf zählte Bahn 4 **463 Würfe bei nur 426 Grünzyklen** — mehr
Würfe als Zyklen, während alle anderen Bahnen bei 420–431 lagen. Spieler Cs Satz fiel dort auf 11 von 30.

Die überzähligen Würfe kamen nicht von der grünen Lampe, sondern vom
Fehlwurfzähler. Er ist die einzige Quelle für einen Wurf ohne gefallenen Kegel
— solche Würfe erzeugen keinen Grünzyklus und wären sonst unsichtbar.

### Gemessen

Alle Anstiege des Zählers über den vollen Spieltag, nach Sprunghöhe:

| Bahn | Sprünge |
|---|---|
| 2 | +1: 1 |
| 3 | keine |
| 4 | +1: 1, **+3: 14** |
| 5 | +1: 2 |

Jeder Dreiersprung buchte drei Nullwürfe — zusammen **42 erfundene Würfe**, alle
auf einer Bahn. Zum Vergleich: Das Protokoll kennt auf 720 Würfen genau **zwei**
Nullwürfe.

**Bildbeleg (Frame 270290, Bahn 4):** Die Tafel zeigt `00`, der Erkenner liest
`03`. Der Störwert 3 ist für dieses Feld seit dem 2026-08-25 bekannt — er stand
schon damals in den Rohwerten (`{0: 10711, 1: 776, 3: 147, 7: 3, 70: 1}`),
überstand dort aber den Stabilitätsfilter nicht. Auf Bahn 4 übersteht er ihn.

### Die Regel

Der Zähler wird alle 10 Frames gelesen, ein Wurfzyklus dauert gemessen 216 bis
338 Frames. **Zwischen zwei Lesungen kann höchstens ein Wurf liegen.** Ein
größerer Sprung ist keine Serie von Nullwürfen, sondern eine Fehllesung.

Wichtig dabei: Der Störwert darf auch **nicht zum neuen Bezugspunkt** werden.
Sonst gälte der Rücksprung auf den richtigen Wert als Spielwechsel, und der
nächste echte Nullwurf fiele aus.

Parameter `detection.digits.foul_max_rise` (1).

### Ergebnis

Gegenlauf F268000–280000 — genau das Fenster, in dem die Störsprünge gemessen
wurden:

```
5 x "Fehlwurfzaehler springt 0 -> 3 ... Verworfen als Fehllesung"
Wuerfe je Bahn: {2: 17, 3: 19, 4: 18, 5: 18}   davon 0 Kegel: keine
```

Vorher hätte dieses Fenster allein 15 Phantomwürfe erzeugt. Bahn 4 liegt jetzt
genau bei den anderen Bahnen.

Tests: `tests/unit/test_foul_counter.py` (6), gegengeprüft.

---

## A7 — Derselbe Spielwechsel wurde von zwei Zeugen gezählt

**Status:** umgesetzt, am Material stichprobenartig bestätigt · Schwere: mittel

Nach A4 zählte Bahn 2 zwar Spielenden (12 statt 2), aber die Spiele fielen
merkwürdig aus. Würfe je erkanntem Spiel über den vollen Lauf:

| Bahn | Spiele | Würfe je Spiel |
|---|---|---|
| 2 | 25 | **1,1,1,1,1,1,1,1**, 19,19,19, 29×5, 30×6, 32 |
| 3 | 16 | 1, 19,20,21, 29, 30×11 |
| 4 | 9 | 21, 28, 30×5, 50, 214 |
| 5 | 20 | 1,2, 20,21,21,28, 30×8, 31×3 |

Ein Spiel hat 30 Würfe. Die Ein- und Zwei-Wurf-Spiele folgen ausnahmslos
demselben Muster:

```
Spiel 4  Wurf 30    Satz zu Ende
Spiel 5  Wurf  1    Wechsel erkannt
Spiel 6  Wurf  2    zweiter Wechsel, EINEN Wurf später
```

### Warum

Es gibt **zwei Zeugen** für denselben Wechsel, und beide sind gewollt:

* der Nullzustand der Anzeige (`000 0000`) — trägt auch dann, wenn die
  Wurfnummer unlesbar war,
* der Rückfall der Wurfnummer von über 30 auf unter 5 — trägt auch dann, wenn
  die Pause zu kurz zum Messen war.

Sie treffen nur **nicht gleichzeitig** ein: Der Nullzustand wird bewusst um bis
zu zwei Würfe weitergereicht (`_reset_weiterreichen`), weil er im Fenster des
*vorigen* Wurfs gesehen wird. Der Rückfall greift sofort. Der Kommentar im Code
behauptete, beide führten zu genau einem `start_new_game` — das gilt innerhalb
eines Wurfs, nicht über zwei.

### Die Regel

Zwei Spielenden im Abstand von einem Wurf gibt es nicht. `game_reset_min_gap_throws`
(5) deckt die gemessene Verzögerung von höchstens zwei Würfen ab und lässt echte
kurze Sätze (19, 20, 21 Würfe) unangetastet. Beide Zeugen bleiben erhalten.

### Ergebnis

Gegenlauf F44000–56000, das Fenster mit dem Ein-Wurf-Spiel auf Bahn 2:

```
Bahn 2: 20 Wuerfe, Spiele [9, 11]      (vorher: ein Spiel mit genau 1 Wurf)
Bahn 3: 19 Wuerfe, Spiele [9, 10]
Bahn 4: 18 Wuerfe, Spiele [6, 12]
Bahn 5: 19 Wuerfe, Spiele [9, 10]
```

Tests: `TestZweiZeugenEinSpielwechsel` (4), gegengeprüft.

**Offen:** Die Zahl der Spiele je Bahn (Bahn 4 hatte ein Spiel mit 214 Würfen)
lässt sich erst nach einem vollständigen neuen Lauf beurteilen — die alte
Messung ist durch A6 verunreinigt, das dort 42 Würfe erfand.

---

## A8 — Die AN-Schwelle der Kegellampen lag im Ausläufer der AUS-Wolke

**Status: erledigt und am Material bestätigt** · Schwere war: hoch

Nach dem vollständigen Lauf blieben sechs falsche Würfe (714/720). Das
Protokoll hatte in fünf von sechs Fällen recht — nachgewiesen an der
**Kegelzahl-Ziffer der Tafel selbst**, also an dem, was auch der Protokollführer
gesehen hat:

| Fall | Protokoll | erkannt | Tafel-Ziffer |
|---|---|---|---|
| B4 Malte W5 | 7 | 8 | **7** (40/40 Messungen) |
| B4 Malte W19 | 7 | 9 | **7** (mit Flackern zu 3) |
| B4 Malte W28 | 7 | 8 | **7** (40/40) |
| B4 Arne W4 | 9 | 8 | **9** (40/40) |
| B5 Malte W29 | 7 | 5 | **7** (40/40) |
| B4 Malte W27 | 8 | 9 | 2 (40/40) — passt zu keinem |

Vier davon hatte das System selbst als unsicher markiert (Confidence 0,00 /
0,00 / 0,03 / 0,40).

### Was die Lampenspur zeigte

Neu gebaut (`debug/lamp_trace.py`), weil es für die Kegellampen kein
Gegenstück zur `gruenspur.csv` gab. 137 484 Messungen über 36 Lampen:

| | Bahn 2 | Bahn 3 | Bahn 4 | Bahn 5 |
|---|---|---|---|---|
| **UNKNOWN** | **0,1 %** | 4,1 % | **11,3 %** | 5,6 % |

Ein Faktor 100. Die Helligkeitsverteilung erklärt es:

```
Bahn 2:  ████████ 140-170  ·  ····  ·  ████████ 250     Tal breit und leer
Bahn 4:  ██ 170-190  ███ 190-230  ██ 240-255            langer Auslaeufer
```

Die AN-Schwelle lag im Mittel bei **211–219** — mitten in diesem Ausläufer.

### Warum daraus zu viele Kegel wurden

Ein Kegel gilt als gefallen, wenn er in **einem** der rund zehn abgetasteten
Frames geleuchtet hat. Diese Regel ist richtig und gemessen begründet — die
Anlagenlampen blinken. Sie setzt aber voraus, dass eine Lampe *nicht
fälschlich leuchten* kann. Bei einer Schwelle im Ausläufer gilt das nicht:
Ein einziger Ausreißer unter zehn Frames genügt für einen Kegel, der nie fiel.

**Bildbeleg (Bahn 4, F54238):** Die Tafel zeigt 7, das Protokoll sagt 7, zwei
Lampen sind sichtbar grau, eine Einzelmessung liest ebenfalls 7 — der Lauf
zählte 8.

### Die Änderung

`baseline_on_fraction` von 0,50 auf **0,75**. Die Schwelle liegt damit bei
233–237 und im gemessenen Tal (220–240, der dünnste Bereich). Betroffen sind
nur Bahn 2 0,1 %, Bahn 3 0,6 %, Bahn 4 1,9 %, Bahn 5 0,7 % der Messungen —
genau der Ausläufer, nicht die AN-Wolke.

Nicht angetastet wurde die Vereinigungsregel: Sie schützt gegen das Blinken.

### Ergebnis

Gegenlauf F50000–112000 (sechs vollständige Sätze):

```
Bahn 4  Spieler B   30/30   (vorher 26)
Bahn 4  Spieler A    30/30   (vorher 29)
Bahn 5  Spieler B   30/30   (vorher 29)
Bahn 2  Arne, Bahn 2 Malte, Bahn 3 Arne   je 30/30 (unveraendert)
```

**180 von 180 Würfen.** Drei Würfe wanderten dabei von VALID nach ERROR — der
Wert stimmt, die strengere Schwelle macht die Lesung nur unsicherer.

**Offen:** ein vollständiger Lauf über alle 24 Sätze zur Bestätigung, und der
Fall B4 Malte W27, wo die Tafel eine 2 zeigt.

---

## A9 — Die Ziffern-ROIs des Summenfeldes saßen falsch

**Status: erledigt und am Material bestätigt** · Schwere war: hoch

Bahn 4 fand nur 8 Spielenden, die anderen Bahnen 12–17; ein Spiel umfasste dort
172 Würfe. Die Ursache war nicht die Logik.

### Gemessen

Während Bahn 3 und 5 auf `000 0000` standen, zeigte Bahn 4 stabil über 330
Messungen:

```
Bahn 3:  throw_number=000  total_b=0000   -> Spielende erkannt
Bahn 4:  throw_number=000  total_b=3000   -> nie erkannt
```

Die Prüfung verlangt eine Summe von null — mit `3000` kann sie nie zutreffen.
Die Segmentmessung der ersten Stelle:

| | a | b | c | d | **e** | **f** | g | gelesen |
|---|---|---|---|---|---|---|---|---|
| Bahn 4 | 0,99 | 0,76 | 0,74 | 0,88 | **0,21** | **0,20** | 0,23 | **3** |
| Bahn 3 | 0,96 | 0,63 | 0,66 | 0,63 | 0,57 | 0,20 | 0,13 | 0 |

Eine `0` ist abcdef. Fehlen die linken Segmente e und f, bleibt abcd —
nächstliegend die `3`. Fehlt zusätzlich d, bleibt abc: genau die `7`. Beide über
den Lauf beobachteten Fehlwerte sind dieselbe abgeschnittene Null. Betroffen
waren **37 von 234 lesbaren Summen (16 %)**.

### Das Maß, ohne das jede Verschiebung geraten wäre

**Die führende Stelle eines mehrstelligen Feldes ist auf dieser Tafel immer
null** — Wurfnummern 001–030, Summen 0–270 (1000 Kegel bräuchten 112 Würfe),
Fehlwurfzähler 00–0x. Eine von null verschiedene führende Stelle ist damit
nachweislich falsch, ohne dass man den wahren Wert kennen muss.

`tools/fit_digit_offsets.py` misst diesen Anteil über tausende Frames für jede
Verschiebung. Ergebnis über alle vier Bahnen und drei mehrstellige Felder:

| Bahn | Feld | heute falsch | empfohlen | dort | |
|---|---|---|---|---|---|
| 2 | total_b | **21 %** | +0,006 | 0 % | **ändern** |
| 4 | total_b | **10 %** | +0,002 | 0 % | **ändern** |
| 2 | left_display | 1 % | +0,006 | 0 % | lassen |
| übrige 9 | | 0 % | — | 0 % | lassen |

**Nur zwei von zwölf Kombinationen** waren betroffen. Die übrigen Empfehlungen
(±0,002) sind Rauschen — dort ist heute schon nichts falsch.

### Zwei Irrwege, beide gemessen

* **Nach links verschieben** hilft nicht — die Richtung ist umgekehrt. Die Box
  fing links den Ausläufer der Nachbarziffer mit; dieser Fremdanteil schob die
  eigentliche Ziffer beim Normieren auf die 24×40-Zelle nach rechts, und die
  Segmentflächen für e und f sammelten Zwischenraum ein.
* **Die linke Kante verbreitern** macht es schlechter, aus demselben Grund.
  `_trim_vertical` schneidet nur senkrecht zu — mit gutem Grund, denn eine `1`
  nutzt die Zellenbreite nicht aus.

### Ergebnis

Acht ROIs verschoben (`tools/shift_digit_rois.py`, Original gesichert als
`1Spieltag_vor_ziffernkorrektur.json`). Vollständiger Gegenlauf:

```
720/720 haelt -- alle 24 Saetze weiter 30/30
Spielenden Bahn 4        8  ->  14
groesstes Spiel Bahn 4  172  ->  50 Wuerfe
unmoegliche Summen       37 von 234  ->  1 von 174
```

**Der Preis:** Lesbare Summen 234 → 174. Die Verschiebung auf Bahn 2 kostet
Lesbarkeit, wie vorher gemessen — aber **keinen Wurf**. Die Summe ist nur
Gegenprobe, die Kegelzahl kommt von den Lampen. 60 Gegenproben weniger gegen
36 falsche weniger ist ein guter Handel.

---

## Erledigt

* **A2** — gleitendes Histogramm, siehe oben.
* **A3** — hinfällig, siehe oben.
* **A5** — Helligkeitssperre, siehe oben.
* **A4** — `000 0000`, siehe oben.
* **BUG-014** — Aufzeichnung begann nach jedem Verbindungsabriss von vorn
  (1693 Duplikate). Behoben durch Rücksprung an die alte Stelle; am
  2026-08-30 über 3,5 h bestätigt: 1 Neuverbindung, 0 verlorene Frames,
  **0 Wiederholungen**.
* **Analysetakt** — bei eingestellten 25 fps lief die Analyse mit 1,12facher
  Geschwindigkeit (aufsummierte Rundungsfehler). Jetzt fester Zeitplan.
* **Zyklusanzeige im Debug-Panel** entfernt — sie zeigte den rechnerischen
  Satz und hieß wie der Lauf zwischen zwei `000 0000`.
