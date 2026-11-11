# Offene technische Fragen

> Grundsatz aus dem Projektauftrag (§25): **Bei Unklarheit nicht raten.**
> Was sich am Material klären lässt, wird gemessen und wandert nach
> `VIDEO_ANALYSIS.md`. Was Fachwissen über die Anlage oder den Spielbetrieb
> erfordert, steht hier — bis es beantwortet ist.
>
> Stand: 2026-08-24

---

## Q1 — Welche realen Bahnen zeigen die vier Overlay-Tafeln? ✅ GEKLÄRT

**Antwort (Nutzerauskunft):** Das Overlay zeigt die **Bahnen 2, 3, 4, 5**.
Bahn 1 ist nicht relevant.

**Umsetzung:** `calibration.lane_number_mapping: [2, 3, 4, 5]` in der Konfiguration.
Der Nutzer kann das pro Bahn über `LaneCalibration.real_lane_number` übersteuern —
die Zuordnung soll bedienbar bleiben, nicht fest verdrahtet sein.

---

## Q2 — Was bedeutet das linke zweistellige Display (`00`)? ✅ GEKLÄRT

**Antwort (Nutzerauskunft):** Es zählt die **Fehlwürfe** — also Würfe mit 0 Punkten.

**Warum das wertvoll ist:** Damit gibt es eine **unabhängige Gegenprobe** für die
schwierigste Fehlerklasse dieses Projekts. Ein Wurf mit 0 Kegeln ändert weder die
Kegelanzeige noch die Summe; er ist deshalb der am leichtesten zu übersehende Fall.
Der Fehlwurfzähler muss genau so oft hochzählen, wie Würfe mit 0 Kegeln erkannt
werden — jede Abweichung deckt einen verpassten Leerwurf auf.

**Umsetzung:** `scoring.check_foul_count: true`. Die ROI heißt `left_display`
und wird in Phase 7 (Ziffernerkennung) aktiviert.

---

## Q3 — Was genau zeigen Summe A und Summe B?

**Sachstand (teilweise geklärt):** Nutzerauskunft — **beide Felder sind Summen**,
aber sie sind **nicht identisch**.

Beleg: `2024-09-03 21-10-40.mp4`, Frame 254 (t = 10,16 s), Tafel 4:
oben `1388`, unten `089 [Ziffer unlesbar] 0675`.
Auf dieser Bahn wurde in dem Moment **nicht gespielt** — angezeigt wird ein alter
Spielstand: 89 Würfe, 1388 Punkte gesamt.

Am Spielanfang stimmen beide überein (`0063`/`0063` bei Wurf 12, Video 2026).

**Was noch offen ist:** Die genaue Bedeutung von B. Naheliegend wäre die
Rundensumme, aber 675 ist bei 15 Würfen unmöglich (Maximum 9 × 15 = 135) — die
Rundengröße der Anlage ist unbekannt. Auch A ist ungeklärt: 1388 bei 89 Würfen
wäre ein Schnitt von 15,6 Kegeln pro Wurf, ebenfalls unmöglich für einen einzelnen
Spieler. Vermutlich summiert A über mehrere Spieler oder Durchgänge.

⚠ **Hinweis zur Verlässlichkeit:** Diese Tafel ist genau jene mit den schwer
lesbaren Ziffern (siehe Q4) — beim ersten Ablesen wurde `1990` statt `1388`
erkannt. Zahlen von dieser Tafel sind ohne zeitliche Aggregation nicht belastbar.

**Vorgehen bis zur Klärung:** `scoring.check_total_a_vs_b` steht auf `false`.
Maßgeblich für die Wurfauswertung ist die **untere Zeile** (Wurfnummer, Kegel,
Summe B), weil dort alle drei Werte zusammen stehen und gegeneinander prüfbar sind.

**Zu klären:** Rundengröße der Anlage; Beobachtung über einen kompletten
Durchgang im langen Video.

---

## Q10 — Warum fehlen Nullwürfe? ✅ URSACHE GEKLÄRT, Behebung offen (2026-08-28)

**Fällt bei einem Wurf kein Kegel, schaltet die Anlage die grüne Lampe nicht
aus.** Es gibt nichts zu zählen und nichts aufzustellen — die Bahn bleibt
freigegeben, der Spieler wirft direkt weiter. Damit ist ein Nullwurf für den
Grünlampen-Trigger **strukturell unsichtbar**.

Belegt an der Grünspur:

```
Bahn 4   F16366 grün AN ... F17477 grün AUS   (1111 Frames, EINE Phase)
         darin Wurf 28 (0 Kegel) und Wurf 29 (1 Kegel)
Bahn 2   F50986 grün AN ... F51566 grün AUS   (580 Frames)
         darin Wurf 18 (0 Kegel) und Wurf 19 (2 Kegel)
```

Betroffen sind **2 von 480 Würfen** (0,4 %) im Wurfprotokoll.

### Zwei Wege geprüft, beide tragen nicht

**1. „Wurfnummer ändert sich während Grün" — widerlegt.**
GEMESSEN über das ganze Video: **521 Wechsel bei 480 Grünphasen**. Die Anlage
zählt den Wurfzähler hoch, wenn sie die Bahn *freigibt* — der Wechsel während
Grün ist der Normalfall. Eine darauf gebaute Regel hätte rund 519 Würfe
erfunden.

**2. „Zwei Wechsel in einer Grünphase" — ebenfalls widerlegt.**
9 Kandidaten, davon 1 echt, 8 falsch, und der Nullwurf auf Bahn 4 gar nicht
gefunden (dort steht die Wurfnummer stabil falsch: 28 wird als 23 gelesen).
Bei den acht Falschen liegt der erste Wechsel 0 bis 91 Frames nach GREEN_ON —
das ist dieselbe normale Umschaltung, nur von der Phasengrenze zerschnitten.

### Der Weg, der trägt — belegt am Material

Der **Fehlwurfzähler** im linken Display (Q2) zählt genau diese Würfe. Er galt
als unlesbar (0 von 36 789 Messungen). **Der Grund war `enabled: false`** —
das Feld wurde beim Kalibrieren nie aktiviert, es wurde also nie ein einziges
Mal versucht zu lesen. Der ROI sitzt waagerecht richtig, deckt aber nur den
oberen Teil der Ziffern ab.

Mit stellenweise gesetzten Rahmen auf Bahn 2 (`tools/pin_left_display.py`,
am Feingitter mit Raster 0,005 abgelesen):

```
Stelle 1   x 0,112  y 0,647  b 0,060  h 0,110
Stelle 2   x 0,189  y 0,647  b 0,060  h 0,110
```

GEMESSEN über die vollen 52 Minuten (`tools/verify_foul_counter.py`):

```
11 638 von 15 557 Messungen lesbar (74,8 %)
Rohwerte: {0: 10711, 1: 776, 3: 147, 7: 3, 70: 1}

nach Stabilitätsfilter (5 Messungen in Folge = 1 s):
   F    35   0:01   Zähler = 0
   F 51230  34:09   Zähler = 1     <== der Nullwurf aus dem Protokoll
   F 58585  39:03   Zähler = 0     <== Rücksetzung beim Spielwechsel

genau EIN Anstieg, an der richtigen Stelle
```

Die Vorhersage war widerlegbar: Das Protokoll nennt für Bahn 2 genau einen
Nullwurf. Mehr Anstiege hätten den Zähler entwertet. Das Rauschen (147× „3",
3× „7", 1× „70") übersteht den Stabilitätsfilter nicht — keiner dieser Werte
stand fünfmal in Folge.

**Damit ist die Nullwurf-Erkennung lösbar:** Steigt der Fehlwurfzähler stabil,
ist auf dieser Bahn ein Wurf ohne Kegel gefallen.

### Umgesetzt und am ganzen Video bestätigt

Rahmen auf allen vier Bahnen gesetzt (`tools/pin_left_display.py`), je Bahn
eigene Koordinaten — ein gemeinsamer Wert reicht nicht, genau das war der
Ausgangsfehler. Lesbarkeit: Bahn 3, 4 und 5 bei **100 %**, Bahn 2 bei 60 %
(dort ist die Anzeige unschärfer; ein Suchlauf über 50 Verschiebungen brachte
höchstens 61 %, gewählt wurde die rauschfreie Variante).

Die Erkennung liest den Zähler **immer**, nicht nur im Wurffenster — ein
Nullwurf fällt ja, während die grüne Lampe an ist. Steigt er stabil, wird ein
Wurf mit 0 Kegeln gebucht, mit dem Zeitstempel des Zählerstands. Ein Rückfall
ist der Spielwechsel und wird als solcher protokolliert.

Lauf über die vollen 52 Minuten:

```
Bahn 4  F17110  11:24  →  Protokoll Satz 1 Wurf 28   passt
Bahn 2  F51240  34:09  →  Protokoll Satz 3 Wurf 18   passt
```

Genau zwei gemeldet, genau die zwei richtigen, keine falschen dazu. Damit ist
die Erfassung auf **allen vier Bahnen bei 100 %** — kein Wurf fehlt mehr.

**Was der Weg dahin gelehrt hat:** Drei Vermutungen, drei Widerlegungen —
„Nullwürfe sind unsichtbar" (falsch, die untere Reihe zeigt sie), „der
Gesamtfeld-Leser ist zu schwach" (falsch, das Feld war abgeschaltet),
„Wurfnummer-Wechsel während Grün verrät sie" (falsch, 521 Wechsel bei 480
Grünphasen). Getragen hat erst das Hinsehen auf ein Gitterbild mit Raster
0,005 — bei Raster 0,01 lagen die Rahmen drei Pixel daneben und lasen 17 %.

---

## Q9 — Wann blinken die Kegellampen? ✅ GEKLÄRT (2026-08-28)

**Vom Nutzer erklärt.** Die Anlage blinkt, wenn in **einem einzigen Wurf alles
gefallen ist, was noch stand**. Das ist eine Auszeichnung, kein Störsignal.

Zwei Punkte, die ich vorher falsch hatte:

1. **Es ist nicht „alle Neune".** Auch acht Kegel blinken — aber nur, wenn es
   dieselben acht **eines** Wurfes sind. Lagen schon welche und der Wurf holt
   den Rest, blinkt es ebenfalls; fallen acht Kegel verteilt über zwei Würfe,
   nicht.
2. **Der König zählt nie mit.** Er muss nie geräumt werden. Fällt alles außer
   ihm, gilt das als vollständig und blinkt.

**Was das für die Erkennung heißt:** Aus der Kegelzahl allein lässt sich nicht
ableiten, ob ein Wurf blinkt — es braucht die **Grundlinie** (was lag schon).
Die Prüfung lautet:

```
{1,2,3,4,6,7,8,9} - Grundlinie - Gefallen   ==   leer   ->  blinkt
```

Der König (Mitte der Raute, Kegel 5) steht bewusst nicht in dieser Menge.

**Warum das zählt:** Das Blinken ist genau der Fall, in dem eine
Einzelmessung versagt (siehe Q8 und BUG-007). Wer wissen will, wie viele Würfe
gefährdet sind, muss sie so abgrenzen — nicht über `Kegel >= 8`.

---

## Q8 — „Ziffer 9 bei dunklen Lampen" — GEKLÄRT (2026-08-25)

**Vermutung des Nutzers, belegt:** Es war dasselbe Blinken wie in BUG-007.

Beobachtet worden war: Die Tafel zeigt in der Kegelzahl eine `9`, während
sämtliche Kegellampen dunkel sind (Bahn 5 Wurf 1, 2, 10; Bahn 2 Wurf 5).

**Beleg — Lampenzahl Frame für Frame, `^` markiert den alten Messzeitpunkt:**

```
Bahn 5 F1271   00000000000119999999999999000000000000000999999999...
                                 ^
Bahn 5 F1752   90000000000000039999999999999900000000000001199999...
                                 ^
Bahn 2 F5329   00000000000999999999999999000000000000001999999999...
                                 ^
Bahn 5 F7397   00000000000009999999999999990000000000000779999999...
                                 ^
```

In allen vier Fällen fiel der Messzeitpunkt in eine Dunkelphase (13–15 Frames),
und in allen vier Fällen beträgt das Maximum über das Fenster 9 Lampen — genau
das, was die Tafel anzeigt. Bildbeleg: `debug/q8_beleg_blinken.png` zeigt
dieselbe Tafel mit identischer Anzeige `001 9 0000` im Abstand von 13 Frames,
einmal vollständig dunkel und einmal mit allen neun Lampen.

Seit die Lampen über das ganze Fenster gesammelt werden, melden alle vier Würfe
9 Lampen und 9 als Ziffer — Status `VALID`.

### Der Trugschluss, der die Frage überhaupt entstehen ließ

Aus der Anzeige `001 9 0000` hatte ich geschlossen, auf dieser Bahn sei noch
nicht gespielt worden — die Gesamtsumme stand ja auf null. Das war falsch: Die
Summe wird erst kurz vor dem nächsten Wurf eingetragen (BUG-010). Wurf 1 hatte
sehr wohl neun Kegel geworfen.

**Zwei Fehler stützten sich gegenseitig und ergaben eine plausible dritte
Erklärung** („Maschinenzustand"). Wo eine Beobachtung nur durch eine neue
Annahme erklärbar wird, lohnt zuerst die Frage, ob eine der bekannten Ursachen
sie schon deckt.

---

## Q11 — Warum reißt die Übertragung nach rund einer Stunde ab?

**Status:** offen, aber entschärft.

**Beobachtung (2026-08-29/30).** Im Lauf vom 29.08. 21:23 rissen Vorschau und
Analyse zur selben Sekunde ab — 22:24:40 und 22:24:47, also **60,6 Minuten**
nach dem Verbindungsaufbau. Beide verbanden neu und bekamen dieselbe
Aufzeichnung wieder ab Frame 0. Der Abstand der Wiederholungen war über den
ganzen Lauf exakt konstant (70033 Frames, alle vier Bahnen, ohne Jitter) — also
stündlich ein Abriss bei gleichbleibendem Analysetempo.

**Was es nicht ist.** Die Signaturen der URLs. Am 2026-08-30 dekodiert:

```
Playlist-Signatur   0x6a948747 = 2026-08-30 19:40 UTC   (+11,85 h)
Chunk-Signaturen    0x6a948bc0 = 2026-08-30 20:00 UTC   (+12,16 h)
```

Sie gelten rund zwölf Stunden, nicht eine. Auch die Playlist selbst ist
einwandfrei: VOD, 3128 Segmente lückenlos, 3:28:31, keine Discontinuity, keine
Abweichung zwischen `EXTINF` und `PROGRAM-DATE-TIME`.

**Offen bleibt** die Gegenseite — CDN-Sitzungsgrenze, Verbindungs-Timeout oder
etwas im FFmpeg-HLS-Demuxer. Um das zu trennen, bräuchte es einen Lauf mit
FFmpeg-Protokoll auf Debug-Ebene über mehr als eine Stunde.

**Warum es nicht mehr kritisch ist:** Seit BUG-014 wird nach einem Abriss an die
alte Stelle zurückgesprungen (framegenau, am echten Stream geprüft). Der Abriss
kostet dann nur noch die Sekunden des Neuaufbaus, nicht mehr die Auswertung.

---

## Q12 — Warum kriecht der Grünscore manchmal durch die Totzone?

**Gestellt:** 2026-09-01 · **Blockiert:** nichts, aber erklärt einen Wurfverlust

Bei fünf Grünzyklen des Spieltags 2026-08-22 stieg der Score der grünen Lampe
nicht sprunghaft an, sondern über 46 bis 92 Frames langsam durch die Totzone
zwischen AUS- und AN-Schwelle. Gesunde Zyklen brauchen dafür ein bis sechs
Frames. Der späte Zustandswechsel kostete auf Bahn 2 einen Räumwurf (BUG-016).

Gemessen ist: Die AN-Schwelle stand dabei ruhig (484 Übergänge, erster ON-Score
fast immer exakt 62,5) und der Median-Score des Zyklus lag mit 60,0 unter dem
der Nachbarzyklen (68 bis 74). Das Signal war also schwächer, nicht der Maßstab
verrutscht.

**Nicht entschieden ist die Ursache.** Ein Teilverdecker, der langsam aus dem
ROI wandert, passt zum Verlauf — ebenso das erhöhte AUS-Niveau danach (32,5
gegen 21 bis 23 davor). Belegt ist beides nicht: Das Material lag nur als
HLS-Stream vor, die Frames sind nicht mehr greifbar.

**Wie es zu klären wäre:** Einen Lauf mit `debug.save_roi_crops` über den
Bereich F180400–180700 auf Bahn 2, und den Ausschnitt der grünen Lampe
ansehen. Dafür wird die Stream-Adresse des Spieltags gebraucht.

**Warum es trotzdem wartet:** Die Abhilfe gegen den Wurfverlust hängt nicht an
dieser Antwort. Die Grundlinie ist auch bei sauberer Erkennung ungeschützt —
ihr Messfenster reicht 25 Frames in die Grünphase hinein, und
`aggregate_pin_readings` vereinigt über die Frames, statt für die Grundlinie zu
schneiden. Siehe BUG-016.

## Q13 — Warum ist Bahn 4 signalschwächer? ✅ GEKLÄRT und BEHOBEN (2026-09-02)

**Gestellt:** 2026-09-01 · **Behoben:** 2026-09-02

**Ursache:** Die Tafel auf Bahn 4 ist überstrahlt — der Schwarzwert liegt auf
allen drei Farbkanälen um rund 34 Punkte höher. Die ausgeschalteten Lampen sind
glänzende Halbkugeln, die die hellere Umgebung spiegeln, und der zu weite
ROI fing zusätzlich Gehäuse mit ein.

**Abhilfe:** Lampen-ROIs auf 50 % verkleinert und auf die gemessene Lampenmitte
zentriert (`1Spieltag_enge_lampen.json`), Kernfilter abgeschaltet, Schwellensatz
neu bestimmt. Im Vollauf vom 2026-09-02 fällt der UNKNOWN-Anteil auf Bahn 4 von
6,73 % auf 0,50 %, die 15 ERROR-Würfe des Spieltags gehen auf 0 zurück.

**Was NICHT half und warum — siehe unten:** ein Weißabgleich.

Bahn 4 liegt in jeder gemessenen Kennzahl schlechter als Bahn 2:

| | Bahn 2 | Bahn 3 | Bahn 4 | Bahn 5 |
|---|---|---|---|---|
| UNKNOWN-Anteil der Kegellampen | 0,14–0,34 % | 0,78–5,72 % | **5,71–9,04 %** | 0,53–7,13 % |

Der Zyklus Bahn 4 F47150 zeigt, was das kostet: Die beiden stehenden Kegel
messen über 350 Frames stabil 210 — bei AUS-Schwelle 198 und AN-Schwelle 234
also durchgehend UNKNOWN, während die sieben liegenden bei 252 klar ON sind.
Der Zyklus wurde als „nichts verändert" verworfen, obwohl ein Räumwurf mit zwei
Kegeln darin steckt. Auch die grüne Lampe ist dort schwächer: Die zugehörige
Phase erreichte im Höchstwert 56,2, wo Bahn 2 auf 77 bis 79 kommt.

### Nachgemessen am 2026-09-01: ein Weißabgleich hilft nicht

Die naheliegende Vermutung war ein Farbstich. 5400 Messungen der einzelnen
Farbkanäle (`tools/measure_lamp_channels.py`, Frames 15000–30000) widerlegen
sie:

| Bahn | Zustand | B | G | R | value |
|---|---|---|---|---|---|
| 2 | AUS | 120,0 | 128,4 | 147,9 | 147,9 |
| 4 | AUS | 159,6 | 163,0 | 181,1 | 181,4 |
| 2 | AN | 202,6 | 240,2 | 254,2 | 254,8 |
| 4 | AN | 190,8 | 215,6 | 250,4 | 250,4 |

Bahn 4 ist **auf allen drei Kanälen um rund 34 Punkte angehoben** — das ist ein
Schwarzwert-Versatz, kein Farbstich. Und entscheidend: Der Detektor misst
`max(B,G,R)`, und **Rot ist in 99,7 bis 100 % aller Messungen der größte
Kanal** — auf jeder Bahn, bei AUS wie bei AN.

Daraus folgt zwingend: Blau und Grün zu skalieren ändert den gemessenen Wert
überhaupt nicht, Rot zu skalieren verschiebt AUS und AN gemeinsam. Ein
Weißabgleich ist multiplikativ und kann einen additiven Versatz nicht
beseitigen. Simuliert bringt er Bahn 4 −6,6 Kontrastpunkte, also eine
Verschlechterung.

### Belegt ist stattdessen: die AUS-Schwelle sitzt an der falschen Stelle

Die adaptive Schwelle rechnet `Niveau + Anteil × (255 − Niveau)`. Diese Formel
arbeitet gegen sich selbst: Je höher das Ruheniveau, desto kleiner der
Spielraum — und desto enger der Abstand zur Schwelle. Genau dort, wo wegen der
breiteren Streuung der größte Abstand nötig wäre, gibt sie den kleinsten:

| Bahn | Niveau | AUS-Schwelle | Abstand | AUS p95 | Reserve |
|---|---|---|---|---|---|
| 2 | 145,2 | 194,3 | 49,1 | 170,7 | **+23,6** |
| 3 | 165,6 | 194,3 | 28,7 | 196,7 | −2,4 |
| 4 | 182,1 | 204,7 | **22,6** | 213,5 | **−8,8** |
| 5 | 162,2 | 194,3 | 32,1 | 201,4 | −7,1 |

Ist die Reserve negativ, landen über 5 % der AUS-Messungen in der Totzone —
und genau das misst die UNKNOWN-Rate.

**Der Platz dafür ist da.** Zwischen AUS p95 (213,5) und AN p5 (245,7) liegen
auf Bahn 4 volle 32 Punkte ungenutzt. Und die Totzone enthält nichts, was
verloren ginge: Von allen UNKNOWN-Messungen liegt auf **keiner** Bahn eine
einzige im AN-Bereich (0,0 %), auf Bahn 4 dagegen 63 % im normalen AUS-Bereich.

Simuliert über die Lampenspur:

| `baseline_off_fraction` | Bahn 2 | Bahn 3 | Bahn 4 | Bahn 5 | Restlücke Bahn 4 |
|---|---|---|---|---|---|
| 0,31 (heute) | 0,49 % | 2,88 % | **6,71 %** | 5,10 % | 32,1 |
| 0,50 | 0,24 % | 0,36 % | **0,87 %** | 0,53 % | 18,2 |
| 0,55 | 0,22 % | 0,29 % | **0,51 %** | 0,37 % | ~14 |

**Was noch offen ist:** Diese Rechnung ist eine Simulation über die
aufgezeichneten Werte, kein Lauf. Bevor die Zahl in `config/default.yaml`
wandert, gehört ein Vollauf mit 0,50 dagegen gehalten — gegen die Tafel-Ziffer
als Wahrheit, mit besonderem Blick darauf, ob Räumwürfe verloren gehen. Der
Preis der höheren Schwelle ist, dass eine schwach leuchtende Lampe als AUS
statt als UNKNOWN gemeldet würde: ein stiller Fehler anstelle eines sichtbaren.

### Die zweite Erklärung ist widerlegt: die ROIs sitzen richtig

Angesehen wurde Frame 20000 auf beiden Bahnen (`tools/export_roi_frames.py`,
Bilder unter `debug/roi_bahn2/` und `debug/roi_bahn4/`). Die Rahmen sitzen auf
beiden Bahnen sauber auf den Lampen, gleich groß (80 × 75 normiert auf allen
vier Bahnen) und gleich zentriert. Beide Bilder sind gleich unscharf.

Was der Vergleich stattdessen zeigt: **Die Tafel auf Bahn 4 ist überstrahlt.**
Gehäuse und Lampenkappen sind heller und blasser als auf Bahn 2, wo dieselbe
Tafel bräunlich und satter erscheint. Die ausgeschalteten Lampen sind glänzende
Halbkugeln — sie reflektieren die hellere Umgebung, und genau das hebt ihren
AUS-Wert.

Dazu passt die Farbsättigung `(max − min) / max`, über dieselben 5400
Messungen:

| Bahn | AUS | AN |
|---|---|---|
| 2 | **18,2 %** | 20,3 % |
| 3 | 16,2 % | 21,9 % |
| 4 | **11,6 %** | 23,6 % |
| 5 | 13,4 % | 25,4 % |

Das ist gegenläufig und erklärt beide Enden: Bei AUS ist Bahn 4 am flachsten —
das Streulicht hebt alle Kanäle gemeinsam. Bei AN ist sie dagegen am
gesättigtsten, weil sie als einzige **nicht** in die Sättigung läuft (2,6 % der
AN-Messungen bei ≥ 254 gegen 84,3 % auf Bahn 2); wo alle Kanäle gegen 255
gehen, verschwindet der Farbabstand.

Bahn 4 ist also nicht anders gefärbt, sie hat schlicht den engeren nutzbaren
Bereich: Der Schwarzwert ist angehoben, der Weißwert nicht ausgereizt. Das ist
eine Eigenschaft der Aufnahme, die keine Farbtransformation zurückholt.

### Was noch nicht gemessen ist: die grüne Lampe

Die grüne Lampe wird über eine **HSV-Maske** gelesen (`inRange(40,80,80 …
90,255,255)`) — dort zählt die Sättigung, nicht `max(B,G,R)`. Auch sie ist auf
Bahn 4 schwächer:

| Bahn | AUS p95 | AN p5 | Lücke | UNKNOWN |
|---|---|---|---|---|
| 2 | 37,5 | 66,2 | **28,7** | 0,67 % |
| 3 | 45,8 | 68,1 | 22,3 | 0,96 % |
| 4 | 40,0 | 55,0 | **15,0** | 1,36 % |
| 5 | 31,1 | 42,2 | **11,1** | 3,20 % |

Die naheliegende Vermutung war, dass die Maske hier an der Sättigung
scheitert. Nachgemessen über 10 000 Frames trifft auch das nicht zu:

| Bahn | Zustand | Score | Sättigung | Helligkeit | grüner Anteil |
|---|---|---|---|---|---|
| 2 | AN | 71,9 | 167,8 | 180,2 | 76,2 % |
| 4 | AN | **62,5** | **151,7** | 184,4 | 75,0 % |
| 5 | AN | **58,9** | **141,2** | 178,3 | 83,3 % |

Die Maske verlangt 80, gemessen werden 141 bis 168 — die Reserve ist überall
mehr als doppelt so groß wie nötig. Der Unterschied entsteht am **Rand** der
Lampe: Auf Bahn 2 fallen 4,3 Prozentpunkte der grün getönten Pixel durch die
Maske, auf Bahn 4 sind es 12,5.

**Damit ist die Weißabgleich-Frage auch für die grüne Lampe beantwortet: Nein.**
Der begrenzende Faktor ist die Randschärfe, nicht die Farbe.

### Nachgemessen: der engere ROI hilft, aber anders als gedacht

Für die **Kegellampen** ist es gemessen (`tools/measure_roi_shrink.py`, 10 800
Ausschnitte auf zwei Strecken, Details in `VIDEO_ANALYSIS.md`):

| Trennlücke Bahn 4 | früh | spät |
|---|---|---|
| heute (100 %, Kernfilter 70) | 44,8 | **33,7** |
| 50 % ohne Kernfilter, nachzentriert | **61,8** | **44,8** |

Drei Dinge daran sind nicht offensichtlich:

1. Der Rahmen ist schon **12 × 11 Pixel** groß — nicht 80 × 75, das sind
   normierte Einheiten.
2. Der halbe Gewinn kommt vom **Nachzentrieren**, nicht vom Verkleinern: Die
   Lampen sitzen im Median 4–10 % oberhalb und links der Rahmenmitte.
3. **Kernfilter und Rahmengröße ersetzen einander.** Bei weitem Rahmen braucht
   es den Filter (44,8 mit, 16,3 ohne), bei engem schadet er (42,1 mit, 61,8
   ohne).

Die Einblendung wandert über 2,6 Stunden um höchstens 4,8 % der Kantenlänge —
ein 50 %-Zuschnitt hat davon reichlich Reserve. Das AUS-Niveau steigt im selben
Zeitraum um 10 bis 23 Punkte; der Zuschnitt löst diese Drift nicht, er
vergrößert nur den Abstand, den sie aufzehrt.

**Was noch offen ist:** Ein anderer Zuschnitt verschiebt alle Niveaus. Bei 50 %
ohne Kernfilter fällt AN p5 auf Bahn 4 spät auf 240,0, während die heutige
AN-Schwelle anteilig bei 233 bis 237 landet — zu knapp. Die vier Schwellwerte
müssten mitbestimmt und ein Vollauf dagegen gehalten werden. Rohdaten unter
`debug/roi_proben/`, damit das ohne neuen Quellzugriff geht.

**Für die grüne Lampe ist es nicht gemessen.** Dort ist der Score ein
Pixelanteil in einer HSV-Maske, keine Helligkeit — ein engerer Rahmen ändert
dort Zähler und Nenner zugleich. Derselbe Gedanke wie A3 der Agenda, aber
eine eigene Messung.

**Nicht entschieden:** Warum die Grundlinie aus der Pause (BUG-016) bei F47150
neun statt sieben Kegel lieferte, obwohl `is_on` UNKNOWN nicht als AN wertet.
Aus den Spuren nicht zu belegen: Die Lampenspur schreibt alle 25 Frames, die
Pause-Messungen laufen alle 5 — der entscheidende Frame kann dazwischen liegen.

**Wie es zu klären wäre:** Ein gezielter Lauf über F46500–47500 auf Bahn 4 mit
`debug.save_roi_crops`, dazu die Pause-Messungen im Klartext protokollieren.
Beides braucht nur 1000 Frames, ist also billig — die Stream-Adresse
vorausgesetzt.

**Verwandt:** Q12 (kriechender Grünscore) beschreibt dasselbe Phänomen an der
grünen Lampe. Der 51-Wurf-Block auf Bahn 4 in den Wurftabellen könnte
dieselbe Wurzel haben.

## Q14 — Verdeckt ein grünes Trikot die eigene Verdeckung?

**Kontext (2026-09-03):** BUG-017 nutzt den rohen Grün-Score, um eine echte
Tafel-Verdeckung zu erkennen (Score fällt auf exakt 0.0, siehe
`tools/messe_gruenscore_um_frame.py`). Der Nutzer wies auf das Gegenteil-Risiko
hin: Eine Person mit **grünem Trikot** vor der Tafel würde den Grünanteil im
Bild eher ERHÖHEN als auf 0 senken — die Verdeckungsbremse (`occlusion_score`)
würde dann möglicherweise gar nicht auslösen, obwohl die Tafel in Wahrheit
verdeckt ist.

**Nicht gemessen:** Kein einziger Fall dieser Art ist im bisherigen Material
beobachtet worden — alle drei gemessenen Verdeckungen fielen sauber auf 0.0.

**Wie es zu klären wäre:** Sobald ein Video mit einer erkennbar grün
gekleideten Person vor einer Tafel vorliegt, denselben Messweg wie bei BUG-017
anwenden (`tools/messe_gruenscore_um_frame.py`) und prüfen, ob der Score in
diesem Fall spürbar über der Verdeckungsschwelle bleibt. Ohne einen solchen
Beleg wird hier nichts "vorsorglich" gefixt — eine geratene Gegenmaßnahme ist
schlimmer als die dokumentierte Lücke.

**Verwandt:** BUG-017 (Verdeckung im Fenster gilt als leerer Wurf).

## Q15 — Der Fehlwurf-Pfad liest die Wurfnummer aus einem einzigen Frame

**Kontext (2026-09-03, aus BUG-019):** `LaneProcessor._wurfnummer_lesen()` liest
die Wurfnummer für ein Fehlwurf-Ereignis aus **genau einem** Frame, während der
normale Grünzyklus-Pfad über zehn Frames aggregiert (`FieldAggregator`). Das ist
bewusst so gebaut — Fehlwürfe sind selten (über einen Spieltag ein knappes
Dutzend), und drei zusätzliche Ziffernstellen alle zehn Frames wären dafür zu
teuer.

**Gemessener Fall:** An F202870 (Bahn 4) las dieser Pfad eine **20**, wo die
Tafel **30** zeigte — das bekannte Muster „ein Segment fällt weg" (3 → 2, siehe
die fünf Ziffer-Abweichungen im Stand vom 2026-09-03).

**Warum es aktuell nicht schadet:** Der Fallback in `_resolve_throw_number`
(`throw_number <= last` → `last + 1`) fängt die Fehllesung auf und liefert die
richtige Nummer — allerdings nur, solange die Kette davor stimmt. Genau das war
bei BUG-019 nicht der Fall, weshalb der Fehler dort sichtbar wurde.

**Offen:** Ob ein Fehlwurf mit einer Fehllesung, die *größer* als der wahre Wert
ist (z. B. 30 → 80), denselben Schutz genießt. Der Sprung-Filter
(`max_throw_number_jump`) müsste greifen — aber das ist an diesem Pfad nicht
gemessen.

**Wie es zu klären wäre:** Die Fehlwurf-Ereignisse eines Vollaufs sammeln und
die einzelne Lesung gegen eine nachträgliche Mehrframe-Aggregation derselben
Frames halten. Billig, weil es nur ein knappes Dutzend Stellen sind.

**Verwandt:** BUG-019, BUG-008 (Ziffernlesung darf einen Wurf nicht verwerfen).

## Q16 — Die 9 wird an der Einerstelle als 0 gelesen (25 % der Fälle)

**Gemessen 2026-09-04** an 24 echten Würfen mit Wurfnummer 3, 8 oder 9 über
alle vier Bahnen, jeweils über die zehn echten Sample-Frames aggregiert:

| Bahn | echter Wurf | gelesen | Einigkeit |
|---|---|---|---|
| 3 | 9 | `('0','3','0')` | 1,00 |
| 4 | 9 | `('0','1','0')` | 1,00 |

Zwei von acht Neunern (**25 %**) wurden an der Einerstelle als **0** gelesen —
und zwar in *zehn von zehn* Frames. Das ist keine flackernde Fehllesung,
sondern eine systematische: Der Detektor ist sich sicher und liegt falsch.

**Warum das gefährlich ist:** Eine Regel, die auf „die Wurfnummer zeigt 0"
reagiert (`discard_zero_throw_number`), kann einen echten Wurf verwerfen.
Gerettet wurden diese beiden Fälle nur dadurch, dass die *Zehner*stelle
ebenfalls falsch war (3 bzw. 1 statt 0) — also durch Zufall, nicht durch
Konstruktion. Der Nutzer hat genau darauf hingewiesen: „ein 9 als 30 ist
durchaus sehr nah an 00".

**Was zeitliche Einigkeit hier NICHT leistet:** Sie schützt gegen Flackern,
nicht gegen systematische Fehllesung (siehe BUG-020). Bei Einigkeit 1,00
sieht eine falsche Lesung genauso aus wie eine richtige.

**Weitere beobachtete Fehllesungen derselben Messung:** 3→4 (zweimal),
8→9, 8→2, 9→8. Insgesamt rund ein Viertel der Lesungen. Damit ist die
verbreitete Annahme „die Wurfnummer wird zu 100 % erkannt" widerlegt.

**Wie es zu klären wäre:** Die Segmentmuster von 9 und 0 auf dieser Anlage
vergleichen — verwandt mit BUG-009 (die 9 wird ohne unteren Balken
gezeichnet). Mit `debug.save_digit_rois` lassen sich die Ausschnitte jetzt
ablegen und nebeneinanderlegen. Solange das offen ist, darf keine Regel
allein auf einer gelesenen 0 aufbauen.

**Verwandt:** BUG-009 (9 ohne unteren Balken → 4), BUG-020 (Einigkeit statt
Bildgüte), Q15.

## Skalierung auf weitere Anlagen (2026-09-15)

Das Anlagenprofil (`calibration/anlage.py`) trennt jetzt, was beim
Hallenwechsel mitreist. Von den drei Fragen, die ich dabei aufgeworfen hatte,
sind zwei **keine Fragen** — der Nutzer kennt die Domäne, ich nicht:

**Polarität der Kegellampen — erledigt.** „Leuchtet = gefallen" ist Standard,
nicht Konvention einer Halle. Ein Schalter dafür wäre ein ungetesteter
Schalter für einen Fall, den es nicht gibt.

**Gespiegelte Kegelnummern — erledigt, zweifach.** Die Nummerierung ist
genormt (oben ist hinten), und die Kalibrierung sagt ausdrücklich, welcher
Bereich welcher Kegel ist. Dazu kommt der stärkere Beleg: **Der Liveticker
zeigt bei jedem Wurf das Kegelbild**, und es wird während des Spiels
mitgelesen. Eine vertauschte Seite wäre über Wochen jedem Spieler aufgefallen
— ein gefallener Kegel steht sichtbar woanders. Der Vorbehalt in
`config/default.yaml` („Annahme, nicht Messung") ist entsprechend ersetzt.

Damit bleibt **eine** Frage offen, und sie ist die nützlichste von den dreien:

### Woher weiß man, dass eine neue Halle trägt?

Die Bausteine sind da (`PlausibilityCheck`, `evidence`, die Confidence), die
Zusammenfassung fehlt: *„Über 120 Würfe stimmten Lampen und Ziffern in 96 %
überein, die Summe in 99 %, die Wurfnummer lief lückenlos."*

Ohne so einen Einmessbericht merkt niemand, dass eine neue Halle nur *fast*
funktioniert — und anders als bei der Kegelnummerierung gibt es dafür keinen
Liveticker, der es im Betrieb aufdeckt: Die Abweichungen wären einzelne
falsche Würfe zwischen vielen richtigen.

Gebaut wird das, sobald Material einer zweiten Anlage da ist. Es jetzt gegen
die Halle zu entwickeln, die das Werkzeug schon kennt, beweist nichts.

### Bahn 3: 13 Ziffernfehler, die kein Versatz repariert (2026-10-06)

Der Versatztest (`tools/messe_ziffernversatz.py`, Schiedsrichter ist die
Tafelsumme) hat Bahn 4 vollstaendig erklaert — ein Pixel nach links, 89/191
auf 191/191. Bahn 3 bleibt bei 168/181; der beste Versatz (0,-2) bringt
genau einen Treffer mehr. Das ist also kein Lagefehler.

Was es stattdessen ist, wurde nicht untersucht. Kandidaten: schlechterer
Kontrast auf dieser Tafel, ein anderer Ziffernsatz, oder die Faelle liegen
alle an Stellen, an denen die Tafel ohnehin umschaltet.

Folgen hat es nur fuer die Redundanz — die Lampen entscheiden, der
Widerspruch wird protokolliert. Es kostet die Bahn aber ihren zweiten Zeugen
in 13 von 181 Faellen.

### Bahn 5: das Feld `digit_pin_count_1` sitzt woanders (2026-10-06)

Auf den Bahnen 2, 3 und 4 liegt das Feld an derselben relativen Stelle, auf
Bahn 5 nicht. Aufgefallen beim Nachmessen des Ziffernversatzes; die Bahn
liest trotzdem 177/178 richtig, also ist nichts kaputt. Ob die Tafel dort
anders gebaut ist oder nur die Kalibrierung abweicht, ist nicht geprueft.

