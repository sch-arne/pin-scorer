# Spieltag — Kurzanleitung

Für den Einsatz vor Ort. Alles Weitere steht in `.claude/skills/ORCHESTRATION.md`.

---

## Ablauf

```bash
.venv/Scripts/python.exe -m kegel_cv.main
```

1. **Quelle wählen** — Videodatei oder Stream-Adresse (`.m3u8`, `rtsp://`).
   Bei einem Stream läuft das Bild während des Kalibrierens weiter.
2. **Kalibrieren** oder eine gespeicherte Kalibrierung laden.
3. **Analyse starten.** Ab hier geht jeder Wurf sofort an Supabase.

Die Analyse lässt sich **anhalten und fortsetzen**; der Versand lässt sich
getrennt stoppen. Ausgewertet und protokolliert wird immer.

---

## Was ein Lauf schreibt

```
debug/<quelle>/lauf_JJJJ-MM-TT_HH-MM-SS/
├── wuerfe.csv       jeder Wurf, sofort geschrieben
├── gruenspur.csv    Grün-Score je Frame und Bahn
└── lane_N/event_M/  Bilder je Ereignis
```

Der Ordnername enthält Quelle **und** Startzeit — mehrere Läufe an einem Tag
überschreiben sich nicht.

`wuerfe.csv` wird zeilenweise geschrieben und sofort geleert: Bricht der Lauf
ab, steht alles bis zum letzten Wurf trotzdem drin.

**Die drei Spalten, die beim Nachforschen am meisten helfen:**

| Spalte | wofür |
|---|---|
| `Zeit` | `mm:ss` im Video — eine strittige Zeile im Bild wiederfinden |
| `Herkunft` | `gruenzyklus` oder `fehlwurfzaehler` — ein Nullwurf ist kein Fehler |
| `Prüfungen` | die **gescheiterten** Gegenproben im Klartext |

---

## Kalibrieren an einem neuen Ort

Die Reihenfolge fragt alles ab: 9 Kegellampen, grüne Lampe, dann die Displays.
Danach die Ziffern **stellenweise** einrahmen — das Auswahlfeld erlaubt, nur
einzelne Felder nachzubessern.

**Der Fehlwurfzähler (linkes zweistelliges Display) muss dabei sein.** Er ist
die einzige Quelle für Würfe ohne Kegel: Fällt nichts, schaltet die Anlage die
grüne Lampe gar nicht aus, und der Wurf ist sonst unsichtbar. Auswahl
„nur Fehlwurfzähler (2)".

Ein Raster von 0,01 reicht beim Einrahmen **nicht** — bei rund 11 px
Ziffernbreite sind drei Pixel Versatz genug, damit der Leser die Segmente
verfehlt.

---

## Was zu prüfen ist, bevor es losgeht

- [ ] Vorschaubild zeigt das Overlay mit allen vier Tafeln
- [ ] Nach den ersten Würfen: Kegelzahl in der Tabelle stimmt mit der Tafel
- [ ] `wuerfe.csv` wächst mit
- [ ] Supabase: kommen Zeilen an? Sonst landen sie in
      `debug/versand_puffer.jsonl` und werden beim nächsten Start nachgeliefert
- [ ] Log auf `verdeckt` durchsehen (siehe unten)

---

## Wenn eine Bahn nichts meldet

Im Log nachsehen:

```
Bahn N: seit ... Frames verdeckt ... kommt hier nichts mehr, passt
womoeglich die Kalibrierung nicht zur Tafel
```

**Hintergrund:** Ein Grün-Score nahe null heißt nicht „Lampe aus", sondern
„keine Lampe im Bild" — die unbeleuchtete Lampe sitzt auf beigem Gehäuse mit
Grünanteil und liegt bei 17–24. Fällt der Score unter 2, friert die Bahn ein,
damit kein Wurf erfunden wird, wenn jemand davorsteht.

Diese Schwelle ist **an einer einzigen Halle gemessen**. Passt sie zum neuen
Ort nicht, meldet die Bahn nie wieder etwas. Abhilfe:

```yaml
detection:
  green:
    occlusion_score: 2.0     # herabsetzen oder auf 0 zum Abschalten
```

---

## Die Stellschrauben, die vor Ort etwas bringen

Alle in `config/default.yaml`, jede mit ihrer Messung im Kommentar.

| Schlüssel | Bedeutung |
|---|---|
| `sampling.report_after_green_off` | Wartezeit bis zur Meldung (40 = 1,6 s). 0 stellt das alte Verhalten her |
| `detection.green.occlusion_score` | ab wann eine Tafel als verdeckt gilt |
| `scoring.detect_zero_throws` | Nullwürfe über den Fehlwurfzähler |
| `scoring.discard_unchanged_cycles` | Zyklen ohne Veränderung verwerfen |
| `output.supabase.enabled` | Versand |
| `debug.save_frames` | Bilder je Ereignis — kostet Platz, hilft beim Nachforschen |

---

## Stand der Erkennung

Gemessen gegen ein handgeführtes Wurfprotokoll (52 Minuten, 480 Würfe,
4 Bahnen): **480 von 480 richtig**, alle 16 Sätze aufs Kegel genau,
3224 Kegel gegen 3224.

Das ist **ein** Video, **eine** Kalibrierung, **ein** Abend. Als Eigenschaft
des Werkzeugs ist daraus nichts belegt — belegt ist, dass es auf diesem
Material vollständig stimmt. An einem neuen Ort gehören die Schwellen
nachgeprüft, allen voran die Verdeckungsschwelle und die Lampenhelligkeit.
