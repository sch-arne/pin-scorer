"""Konfigurationsschema mit Validierung.

Grundsatz (siehe Skill `kegel-architektur`): Alle Parameter kommen aus der
Konfiguration, nicht aus dem Code. Die Validierung passiert beim Laden --
nicht beim ersten Zugriff, wenn die Analyse schon laeuft.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..schema import BaseModel, Field, model_validator


class VideoConfig(BaseModel):
    directory: str = "kegelVideos"
    source: str | None = None
    playback_fps: float = Field(default=25.0, gt=0)
    max_consecutive_read_failures: int = Field(default=10, ge=1)
    # Verhalten bei einem Livestream. Ein Aussetzer ist dort Alltag -- WLAN,
    # Puffer, Umschaltung der Qualitaetsstufe -- und kein Grund aufzugeben.
    stream_reconnect_attempts: int = Field(default=5, ge=1)
    stream_reconnect_delay_s: float = Field(default=2.0, ge=0)
    # Erst nach so vielen erfolglosen Leseversuchen lohnt der teure
    # Verbindungsaufbau. 25 Frames sind rund eine Sekunde.
    stream_read_failures: int = Field(default=8, ge=1)
    # Zeitlimits fuer den Stream. OHNE diese wartet FFmpeg 30 SEKUNDEN je
    # Leseversuch -- gemessen, nachdem die Verbindung waehrend des Kalibrierens
    # weggelaufen war. Mit 8 Wiederholungen ergaeben das ueber vier Minuten
    # Blockade, und da der Player im GUI-Thread liest, friert dabei die ganze
    # Oberflaeche ein.
    stream_open_timeout_ms: int = Field(default=10000, ge=100)
    stream_read_timeout_ms: int = Field(default=5000, ge=100)
    # Transportweg fuer RTSP. "tcp", "udp" oder "" (FFmpeg entscheidet).
    #
    # GEMESSEN 2026-09-08 an der Hallenkamera (Reolink, 2304x1296, h264):
    #     udp: 4,7 fps gelesen, groesste Luecke 5089 ms, Decoder meldet
    #          "error while decoding MB 72 18" -- verstuemmelte Bilder
    #     tcp: 15,9 fps gelesen, groesste Luecke 235 ms, keine Decoderfehler
    #
    # UDP verliert Pakete. Ein verlorenes Paket zerstoert das ganze Bild:
    # entweder es fehlt (Stillstand) oder es kommt mit Blockfehlern durch --
    # und ein zerhackter Block ueber einer Ziffer liefert einen falschen Wert,
    # obwohl die ROI genau richtig sitzt.
    stream_rtsp_transport: str = "tcp"
    # Neuanfang der Quelle erkennen (siehe StreamVideoSource._laeuft_von_vorn)
    stream_restart_check: bool = True
    stream_restart_probe_frames: int = Field(default=90, ge=10)
    stream_restart_matches: int = Field(default=3, ge=2)
    stream_resume_tolerance_frames: int = Field(default=100, ge=1)
    # So nah am Ende gilt eine Aufzeichnung als ABGESPIELT, nicht als
    # abgerissen.
    #
    # GEMESSEN 2026-08-30/31 (BUG-015): Der Lauf ueber den vollen Spieltag
    # erreichte Frame 312784 von gemeldeten 312786 -- also zwei Frames vor dem
    # Ende. Danach drehte er endlos: alle sieben Sekunden ein Abriss, ein
    # erfolgreicher Ruecksprung auf 312784, und wieder kein Frame. Der Lauf
    # endete erst, als der Rechner heruntergefahren wurde, und die Schlussbilanz
    # (Gruenzyklen ohne Wurfergebnis, Statusverteilung) entstand nie.
    #
    # Die letzten Frames einer HLS-Aufzeichnung fehlen regelmaessig; die
    # gemeldete Laenge ist eine Angabe aus der Playlist, kein Versprechen.
    # 100 Frames sind 4 Sekunden -- kurz genug, dass kein echter Wurf darin
    # verlorengeht (kuerzester gemessener Wurfzyklus: 7 Frames Gruenphase,
    # aber der Zyklus als ganzes dauert 216-338 Frames).
    stream_end_tolerance_frames: int = Field(default=100, ge=0)
    # Hoechste Aufloesung, die von einer YouTube-Adresse geholt wird.
    #
    # Mehr Pixel heissen mehr Decodierarbeit je Frame, und breiter wird die
    # Tafel davon nicht: Im Overlay-Video ist eine Tafel rund 190 Pixel gross,
    # und genau darauf wurde kalibriert (2026-09-09, 1521 gueltige Wuerfe bei
    # 11 Widerspruechen). Wer die Quelle in 1440p holt, rechnet doppelt so viel
    # und liest dieselben Ziffern.
    youtube_max_height: int = Field(default=1080, ge=144)


class ProcessingConfig(BaseModel):
    frame_buffer_size: int = Field(default=50, ge=1)
    buffer_roi_only: bool = False
    green_check_interval: int = Field(default=1, ge=1)

    # WELCHE BAHNEN DIESES GERAET ERFASST -- als Bahnnummern, wie sie auf der
    # Anlage stehen (2, 3, 4, 5), nicht als laufender Index.
    #
    # Leer heisst: alle, die die Kalibrierung hergibt. So verhaelt sich alles
    # wie bisher, solange niemand etwas einstellt.
    #
    # WOZU (Nutzer, 2026-09-24): *"Mein Gedanke ist gerade fuer eine Bahn die
    # vielleicht schwer zu lesen ist, einfach eine zusaetzliche Kamera durch
    # mein Handy einzusetzen. Dann soll unser Livestream quasi nur noch Bahn 2
    # und 3 uebertragen und Bahn 3 und 4 kommen vom Handy."* Eine nicht
    # erfasste Bahn bekommt gar keinen Prozessor -- sie kostet dann auch keine
    # Rechenzeit, was auf einem Telefon der eigentliche Punkt ist.
    lanes: list[int] = Field(default_factory=list)


class CalibrationConfig(BaseModel):
    directory: str = "data/calibrations"
    warped_width: int = Field(default=440, ge=50)
    warped_height: int = Field(default=530, ge=50)
    # Bibliothek bekannter Tafelbauarten. Beim Laden eines Videos oder
    # Streams wird darin gesucht -- kennt das Werkzeug die Bauart, schlaegt es
    # die fertige Kalibrierung vor.
    boardtype_directory: str = "data/boardtypes"
    # So viele tragende Merkmale muss ein Treffer haben. GEMESSEN 2026-09-09
    # ueber zwei verschiedene Quellen: gelungene Treffer hatten 15 bis 197,
    # ein Fehltreffer 7 -- und der lag 1429 Pixel daneben.
    boardtype_min_inlier: int = Field(default=14, ge=4)
    # SUCHE UEBER MEHRERE STANDBILDER. GEMESSEN 2026-09-10, 16 Stichproben
    # ueber ein Spiel von 3:08 h, vier gleiche Tafeln im Bild:
    #
    #     4 Tafeln gefunden   1 Frame
    #     3 Tafeln            6 Frames
    #     1 Tafel             4 Frames
    #     gar nichts          5 Frames
    #
    # Brennende Kegellampen und wechselnde Ziffern veraendern genau die
    # Merkmale, an denen der Abgleich haengt -- auf einem Bild mit vielen
    # leuchtenden Lampen wurde KEINE Tafel gefunden, obwohl alle vier klar zu
    # sehen waren. Die LAGE aendert sich dagegen nicht.
    boardtype_sample_frames: int = Field(default=14, ge=1)
    # SO VIELE BILDER NACH DEM VOLLSTAENDIGEN FUND noch weitersammeln. Die
    # Ecken werden ueber die Funde gemittelt, und gegen Schaetzrauschen hilft
    # Mitteln nur, wenn es genug zu mitteln gibt. GEMESSEN 2026-09-10 ueber
    # acht Stellen eines Spiels, Streuung der ROI-Lagen zwischen den vier
    # baugleichen Tafeln:
    #
    #     11 bis 13 Funde je Tafel    0,9 px
    #      2 bis  7 Funde je Tafel    1,8 px
    #
    # Die Suche ist meist nach zwei bis vier Bildern vollstaendig -- genau im
    # schlechten Bereich. Sechs weitere Bilder kosten im Livestream rund fuenf
    # Sekunden und halbieren den Fehler.
    boardtype_nachlauf_bilder: int = Field(default=6, ge=0)
    # Abstand zwischen den Stichproben in einer Datei. 150 Frames sind sechs
    # Sekunden -- weit genug, dass Lampen und Ziffern anders stehen.
    boardtype_sample_step: int = Field(default=150, ge=1)
    # Bei einem Stream laesst sich nicht springen: Da wird gewartet.
    boardtype_sample_wait_s: float = Field(default=0.8, ge=0.0)
    # Schranke fuer die Tafeln NACH der ersten. Sie darf niedriger liegen,
    # weil die Wiederholung ueber mehrere Bilder die Sicherheit ersetzt.
    # GEMESSEN: Die vierte Tafel kam mit 11 tragenden Merkmalen -- unter der
    # Schranke 14, aber an der richtigen Stelle und in mehreren Bildern.
    boardtype_anchor_inlier: int = Field(default=8, ge=4)
    # In so vielen Bildern muss eine Tafel an derselben Stelle auftauchen.
    # Eins wuerde jeden Zufallstreffer durchlassen, drei verliert die
    # schwaechste Tafel.
    boardtype_min_frames: int = Field(default=2, ge=1)
    # Zeitgrenze fuer die Suche im LIVESTREAM. Dort laesst sich nicht
    # springen -- es gibt nur das naechste Bild.
    #
    # NACHGEMESSEN 2026-09-11: Der alte Wert (20 s) stammte aus der Zeit des
    # Merkmalsabgleichs. Nach dem Umbau auf Bild in Bild kostete das erste
    # Bild 20,5 s -- die Suche war vorbei, bevor das zweite Bild an der Reihe
    # war, und ein einzelnes Bild zaehlt nicht (`boardtype_min_frames`). Sie
    # scheiterte still, obwohl sie im ersten Bild alle vier Tafeln sah.
    #
    # Mit dem zweistufigen Raster: erstes Bild 4,3 s, jedes weitere 1,3 s.
    boardtype_live_timeout_s: float = Field(default=30.0, gt=0)
    # Ziffernrahmen nach der Erkennung an den NULLEN ausrichten.
    #
    # Zu Spielbeginn steht auf der Tafel 000, 0, 0000 -- ein bekannter
    # Sollwert. Deshalb ist das keine Optimierung auf das eigene Ergebnis.
    #
    # GEMESSEN 2026-09-10 am Hallenstream: angepasst an einem Bild, gemessen
    # an acht spaeteren -- unlesbare Ziffernstellen 21,6 % -> 17,5 %.
    #
    # Zeigt die Tafel keine Nullen, geschieht nichts.
    digit_zero_fit: bool = True
    # BILD IN BILD: die Tafel als Ganzes suchen statt ueber Merkmalspunkte.
    #
    # GEMESSEN 2026-09-10 an acht Stellen eines Spiels von 3:08 h, Streuung
    # der ROI-Lagen zwischen den vier baugleichen Tafeln:
    #
    #     Merkmalsabgleich   1,43 px, groesster Ausreisser 3,33
    #     Bild in Bild       1,00 px, groesster Wert       1,16
    #     von Hand gesetzt   0,89 px
    #
    # Und: Alle acht Stellen finden alle vier Tafeln. Der Merkmalsabgleich
    # schaffte das an dreien nicht. Der Preis sind rund 16 statt 7 Sekunden.
    #
    # So sicher muss ein Fund sein (maskierter ZNCC). GEMESSEN: echte Tafeln
    # 0,52 bis 0,87, und die naechstbeste Stelle im Bild lag klar darunter.
    boardmatch_min_guete: float = Field(default=0.45, ge=0.0, le=1.0)
    # FEINSCHLIFF DER LAMPEN JE TAFEL. Nach dem Fund wird jede Tafel einzeln
    # gegen das Musterbild nachgezogen -- getrennt fuer Kegellampen und
    # Gruenlampe. GEMESSEN 2026-09-11: Ueber die vier Tafeln wandert die
    # Gruenlampe um 1,6 px, waehrend die Lampenraute stehenbleibt. Eine
    # Verschiebung der ganzen Tafel kann das nicht einfangen.
    #
    # Trennschaerfe der gruenen Lampe (Fisher, schwaechste Bahn entscheidet):
    #     automatisch            6,3
    #     + Feinschliff          9,1
    #     + groessere ROI       13,4     (von Hand gesetzt: 10,1)
    roi_feinschliff: bool = True
    # Suchweite in Vorlagenpixeln. Groesser als der erwartete Fehler (gemessen
    # bis 1,6 px), sonst misst man die Fenstergrenze statt den Versatz.
    roi_feinschliff_weite: int = Field(default=5, ge=1, le=20)
    # Unter so vielen unveraenderlichen Pixeln im Ausschnitt ist das Ergebnis
    # nicht belastbar. GEMESSEN: Lampenraute 9272 px, Gruenlampe 456 px.
    roi_feinschliff_min_pixel: int = Field(default=200, ge=20)
    # Groesserer Versatz heisst nicht Feinschliff, sondern dass etwas anderes
    # nicht stimmt -- dann wird verworfen statt verschoben.
    roi_feinschliff_max_versatz: float = Field(default=3.0, gt=0.0)
    lane_count: int = Field(default=4, ge=1)
    lane_number_mapping: list[int] | None = None
    # ZUORDNUNG LAMPE -> KEGELNUMMER (beantwortet die offene Frage Q5).
    #
    # Die Lampen der Tafel liegen als Raute. Unsere ROIs zaehlen sie von OBEN
    # nach unten, der Sport zaehlt von VORN -- und vorn ist auf der Tafel
    # unten. Vom Nutzer festgelegt am 2026-09-01:
    #
    #     Tafel (unsere Lampen)        Kegel (Sport)
    #            L1                           9
    #         L2    L3                     7     8
    #      L4   L5    L6                4    5     6
    #         L7    L8                     2     3
    #            L9                           1
    #
    # Das ist eine Spiegelung von oben nach unten; links bleibt links.
    #
    # GESTUETZT durch einen Einzelfall: Bahn 2, Wurf 25 bei Frame 180238 fiel
    # eine Acht, bei der unsere L2 stehen blieb. Der Nutzer hatte unabhaengig
    # davon "hinten links" vorhergesagt -- seine 7, und L2 bildet auf 7 ab.
    #
    # WAS NICHT BELEGT IST: dass die Tafel die Raute nicht zusaetzlich
    # seitenverkehrt zeigt. Die Zeilenzuordnung folgt zwingend aus der
    # Anordnung, die Seitenzuordnung nur aus der Annahme. Ein zweiter Fall mit
    # einem stehenden Kegel LINKS oder RECHTS (nicht mittig) wuerde es klaeren.
    #
    # Die ZAEHLUNG der Kegel beruehrt das nicht -- nur ihre Namen.
    pin_number_mapping: list[int] = Field(
        default_factory=lambda: [9, 7, 8, 4, 5, 6, 2, 3, 1])

    @model_validator(mode="after")
    def _check_mapping(self) -> CalibrationConfig:
        # Eine Zuordnung, die eine Nummer doppelt vergibt, wuerde Kegel
        # stillschweigend verschmelzen -- das faellt sonst nirgends auf.
        if sorted(self.pin_number_mapping) != list(
                range(1, len(self.pin_number_mapping) + 1)):
            raise ValueError(
                "pin_number_mapping muss jede Kegelnummer genau einmal "
                f"vergeben, ist aber {self.pin_number_mapping}")
        if self.lane_number_mapping is not None:
            if len(self.lane_number_mapping) != self.lane_count:
                raise ValueError(
                    f"lane_number_mapping braucht genau {self.lane_count} Eintraege, "
                    f"hat aber {len(self.lane_number_mapping)}"
                )
        return self


class GreenDetectionConfig(BaseModel):
    implementation: Literal["hsv"] = "hsv"
    hue_min: int = Field(default=40, ge=0, le=179)
    hue_max: int = Field(default=90, ge=0, le=179)
    saturation_min: int = Field(default=80, ge=0, le=255)
    value_min: int = Field(default=80, ge=0, le=255)
    on_threshold: float = 45.0
    off_threshold: float = 35.0
    # Mitlaufende Schwellen fuer die gruene Lampe.
    #
    # GEMESSEN ueber 52 Minuten: Beide Verteilungen wandern aufeinander zu.
    #                AUS 50%  AUS 95% |  AN 5%  AN 50%   Abstand
    #     Min 1-3       28,3     38,4 |   71,7    75,8    +33,3
    #     Min 47-49     36,4     43,4 |   69,7    74,7    +26,3
    #     Min 47-49 B4  36,1     41,7 |   56,5    63,0    +14,8
    #
    # Sie ueberlappen nie -- aber die festen Schwellen (35/45) liegen am Ende
    # mitten in der AUS-Verteilung. Folge: Die Grenze wurde nicht mehr sauber
    # erkannt, GREEN_OFF loeste bis zu 180 Frames zu spaet aus, und die
    # Kegellampen waren dann bereits zurueckgesetzt.
    #
    # Deshalb werden die Schwellen ANTEILIG zwischen die beiden beobachteten
    # Niveaus gelegt statt auf feste Werte.
    adaptive_thresholds: bool = True
    # Laenge des Gedaechtnisses in Frames. Die gruene Lampe wird JEDEN Frame
    # gemessen; 1500 Frames sind 60 Sekunden und decken damit mehrere
    # Wurfzyklen ab (gemessen 216-338 Frames je Zyklus) -- lang genug, dass
    # beide Zustaende sicher darin vorkommen.
    adaptive_window: int = Field(default=1500, ge=100)
    # Perzentile, die als AUS- bzw. AN-Niveau gelten
    adaptive_off_percentile: float = Field(default=20.0, ge=0.0, le=50.0)
    adaptive_on_percentile: float = Field(default=90.0, ge=50.0, le=100.0)
    # Lage der Schwellen zwischen beiden Niveaus (0 = AUS-Niveau, 1 = AN-Niveau)
    adaptive_on_fraction: float = Field(default=0.55, gt=0.0, lt=1.0)
    adaptive_off_fraction: float = Field(default=0.40, gt=0.0, lt=1.0)
    # Mindestabstand beider Niveaus, damit die Anpassung ueberhaupt greift.
    #
    # Liegen sie dicht beieinander, war die Lampe im Fenster durchgehend in
    # EINEM Zustand. Dann liegen beide Perzentile in derselben Verteilung, und
    # die Schwelle traennt blosses Rauschen.
    #
    # Der frueherer Wert 12 war zu knapp und hat genau das ausgeloest: Auf einer
    # Bahn kippte der Zustand bei Score 78,8 auf AUS und bei 79,8 zurueck auf AN
    # -- obwohl die absolute AN-Schwelle bei 45 liegt und die Lampe durchgehend
    # leuchtete. Aus einem Wurf wurden dadurch zwei.
    #
    # GEMESSEN ueber eine Spur von 65 896 Messungen (4 Bahnen, 11 Minuten):
    #     Spanne bei durchgehend AN     3 .. 9
    #     Spanne bei echtem Wechsel     4 .. 69
    #
    # Die Bereiche ueberlappen -- eine saubere Trennung gibt es nicht. Das ist
    # aber unschaedlich: Ist die Spanne klein, sind die absoluten Schwellen
    # ohnehin richtig, denn dann ist nichts gedriftet. Die Anpassung wird nur
    # gebraucht, wenn BEIDE Zustaende im Fenster vorkommen, und das zeigt sich
    # als grosse Spanne.
    #
    # Nachgerechnet ueber dieselbe Spur: Mit 30 verschwindet die Phantomphase,
    # und keine echte Gruenphase faellt weg (geprueft auf allen vier Bahnen).
    adaptive_min_span: float = Field(default=30.0, gt=0)

    # GLEITENDES HISTOGRAMM statt Perzentilen.
    #
    # Die Perzentile oben setzen voraus, dass BEIDE Zustaende im Fenster
    # vorkommen -- und zwar ungefaehr im erwarteten Verhaeltnis. Genau das
    # traegt nicht. GEMESSEN am 2026-08-30 auf Bahn 5, Frames 40894-40914:
    #
    #     Frame   Score    P20    P90  Spanne  AUS-Schwelle  Zustand
    #     40903    47,8   40,0   70,0    30,0          52,0  OFF
    #     40906    47,8   41,8   70,0    28,2  fest: 35,0    ON
    #
    # DERSELBE Score, zwei Zustaende. Die Bahn lag 71 % des Fensters auf AN,
    # also war P20 kein AUS-Niveau, sondern der untere Rand der AN-Wolke --
    # und die daraus errechnete AUS-Schwelle (52,0) lag MITTEN in der AN-Wolke.
    # Der so entstandene GREEN_OFF erzeugte einen Wurf, den es nie gab, und
    # verschob die ganze folgende Wurfnummernkette (docs/AGENDA.md, A1).
    #
    # Das Histogramm desselben Fensters ist dagegen eindeutig zweigipflig:
    #     18-26   233 Werte   AUS-Wolke, Gipfel 24-26
    #     26-52  ~250         duenn -- die Flanken
    #     52-78 ~1069         AN-Wolke, Gipfel 56-58
    # Das Tal liegt bei 37. Damit ist 47,8 durchgehend AN.
    histogram_thresholds: bool = True
    # 22500 Frames = 15 Minuten bei 25 fps. GEGENGERECHNET ueber die Gruenspur
    # des Laufs vom 2026-08-30 (297 715 Frames je Bahn): Die Zahl der
    # GREEN_OFF-Ereignisse aendert sich zwischen 1500 und 45000 Frames
    # Fensterlaenge um hoechstens 13 -- das Verfahren haengt nicht am Fenster.
    histogram_window: int = Field(default=22500, ge=500)
    # So viele Messungen muessen im Fenster liegen, bevor daraus ueberhaupt
    # eine Schwelle abgeleitet wird. 1500 Frames sind 60 Sekunden und decken
    # mehrere Wurfzyklen ab (gemessen 216-338 Frames je Zyklus) -- lang genug,
    # dass beide Zustaende vorkommen koennen. Bis dahin gelten die festen.
    histogram_min_samples: int = Field(default=1500, ge=100)
    histogram_bin: float = Field(default=2.0, gt=0.0, le=10.0)
    # Ab welchem Bruchteil der Gipfelhoehe die AUS-Wolke als "zu Ende" gilt.
    # Der Abstieg vom Gipfel nach unten haelt an, sobald das Histogramm
    # darunter faellt -- das ist der untere Rand der Wolke.
    # GEMESSEN 2026-09-14 ueber beide Quellen: 0,05 und 0,10 liefern dasselbe
    # Ergebnis auf allen acht Bahnen. 0,05 gewaehlt, weil es weiter absteigt
    # und damit die konservativere Kante findet.
    histogram_edge_fraction: float = Field(default=0.05, gt=0.0, le=0.5)
    # Ueber so viele Bins wird geglaettet. Ein einzelner leerer Bin ist
    # Rauschen, kein Tal.
    histogram_smoothing: int = Field(default=3, ge=1)
    # Jede Wolke muss mindestens diesen Anteil des Fensters halten. Ein Gipfel
    # aus fuenf Frames ist kein Zustand, sondern eine Flanke.
    histogram_min_cloud: float = Field(default=0.05, gt=0.0, lt=0.5)
    # Mindestabstand der beiden Gipfel in Score-Punkten.
    histogram_min_gap: float = Field(default=15.0, gt=0.0)
    # Das Tal muss deutlich tiefer sein als der KLEINERE Gipfel, sonst ist es
    # keine Trennung, sondern eine Delle in einer einzigen Wolke.
    histogram_max_valley: float = Field(default=0.25, gt=0.0, le=1.0)
    # Hysterese um das Tal, als Anteil des Gipfelabstands.
    histogram_hysteresis: float = Field(default=0.10, ge=0.0, lt=0.5)
    # Neuberechnung nur alle n Frames (25 = einmal je Sekunde). Das Histogramm
    # selbst laeuft bei jedem Frame mit; nur die Talsuche ist getaktet.
    histogram_interval: int = Field(default=25, ge=1)

    min_stable_frames: int = Field(default=3, ge=1)

    # VERDECKTE TAFEL. Ein Score nahe null heisst nicht "Lampe aus", sondern
    # "keine Lampe im Bild": Selbst die unbeleuchtete Lampe sitzt auf beigem
    # Gehaeuse mit Gruenanteil, die AUS-Grundlinie ist deshalb NIE null.
    #
    # GEMESSEN ueber 52 Minuten, Verteilung der niedrigen Scores:
    #
    #     Score      Bahn 2   Bahn 3   Bahn 4   Bahn 5
    #      0- 1        1044      169        0        0
    #      2- 3           5        8        0        0
    #      4- 5           2        4        0        0
    #
    # Ein scharfer Gipfel bei exakt null, danach fast nichts bis 20. Die 1213
    # Frames liegen in acht zusammenhaengenden Abschnitten von 1 bis 18
    # Sekunden -- im Bild steht dort ein Spieler vor der Tafel.
    #
    # Was passiert, wenn man das als "aus" liest: Der Score faellt, die
    # Zustandsmaschine meldet GREEN_OFF, und es entsteht ein Wurf, den es nie
    # gab. Beide Phantomwuerfe des Videos (F3228 und F43514) fallen exakt in
    # eine solche Verdeckung. Einer davon hat zusaetzlich die Grundlinie des
    # naechsten echten Wurfs vergiftet.
    #
    # Waehrend der Verdeckung wird der Zustand eingefroren: keine Uebergaenge,
    # keine Messungen. Lieber eine Luecke im Protokoll als ein erfundener Wurf.
    # ANLAUF: ohne zwei Wolken gibt es keine Schwelle, nur eine Aenderung.
    #
    # Die Schwellen lernt der Detektor im Betrieb -- aus dem Histogramm,
    # hilfsweise aus Perzentilen. Beides braucht BEIDE Zustaende im Fenster.
    # Zu Beginn einer Aufzeichnung ist die Anlage aber freigegeben und die
    # Lampe durchgehend an; gemessen am 2. Spieltag kam das erste AUS auf
    # Bahn 4 erst bei Frame 10480, also nach achteinhalb Minuten.
    #
    # Bis dahin galt eine feste globale Schwelle (45/35). Die passt zu den
    # gemessenen AUS-Niveaus (25,5 / 22,9 / 31,4 / 25,7) eher zufaellig: Eine
    # nach Trennschaerfe bessere ROI hob das AUS-Niveau auf Bahn 4 auf 50,3,
    # und die Lampe ging im Anlauf nie mehr aus -- die ersten drei Wuerfe des
    # Spieltags gingen verloren.
    #
    # Nutzeridee 2026-10-06: *"wir hoffen ja nur, dass aus irgendwo drunter
    # liegt und an irgendwo drueber... ich denke wir sollten eher mal
    # schauen, ob wir es dadurch schaffen, dass wir sagen am Anfang brauchen
    # wir eine Aenderung > 10 oder so"*. Das braucht die absolute Lage nicht
    # und haengt damit an keiner ROI.
    #
    # GEMESSEN an beiden Vollaeufen, Frame des ersten erkannten Gruen-AUS:
    #
    #                        absolut   >5     >10     >15     >20
    #   alte ROIs  Bahn 2      7558    161   3200    7557    7558
    #              Bahn 3     10400     40  10392   10392   10399
    #              Bahn 4     10480     79   1801   10479   14124
    #              Bahn 5      5607    977   5605    5605    5605
    #   neue ROI   Bahn 4      KEINS    91   2097   10470   10479
    #              Bahn 5      5607     87   5605    5605    5605
    #
    # Bei 15 trifft die Regel ueberall dasselbe AUS wie die absolute Schwelle
    # -- auf wenige Frames genau, ohne Fehlausloeser davor -- und sie findet
    # es auch dort, wo die absolute Schwelle nichts findet. Bei 10 kommen
    # Fehlausloeser, bei 20 wird Bahn 4 zu spaet. Die kleinste gemessene
    # Spanne zwischen den Wolken ist 35, also mehr als das Doppelte.
    #
    # 0 schaltet die Regel ab; dann gilt im Anlauf wieder die feste Schwelle.
    warmup_min_change: float = Field(default=15.0, ge=0.0, le=100.0)

    # Wie traege das Niveau des laufenden Zustands nachgefuehrt wird (0..1).
    # Klein genug, dass eine einzelne Messung es nicht verschiebt, gross
    # genug, dass langsame Helligkeitsaenderungen im Saal mitgenommen werden.
    warmup_level_decay: float = Field(default=0.01, gt=0.0, le=1.0)

    occlusion_score: float = Field(default=2.0, ge=0.0)
    # ... und derselbe Gedanke ANTEILIG am UNTEREN RAND der AUS-Wolke. Er
    # traegt, wo eine feste Zahl es nicht kann.
    #
    # WARUM AM RAND UND NICHT AM GIPFEL (Aenderung 2026-09-14). Bis dahin
    # bezog sich der Anteil auf das AUS-NIVEAU, also den Gipfel der Wolke. Der
    # sagt, wo AUS ueblicherweise liegt -- aber nichts darueber, wie weit die
    # Wolke nach unten reicht, und genau dort entscheidet es sich.
    #
    # GEMESSEN 2026-09-14 an der Hallenkamera, echte AUS-Wolke (Frames, in
    # denen Tafelwache UND Personenmodell schweigen):
    #
    #     Bahn   Wolke von .. bis   Gipfel   unterer Rand
    #       2        0,0 .. 0,7        0,7        0,0
    #       3        1,4 .. 3,5        3,5        1,0
    #       4        7,1 .. 11,7      11,7        7,0
    #
    # Gleiche Halle, gleiches Licht, gleicher Frame -- und drei voellig
    # verschiedene Lampen. Am Gipfel gemessen bekam Bahn 2 eine Schwelle von
    # 0,9 und bremste in 28 % ALLER Frames auf voellig freier Tafel: Ihr
    # echtes AUS liest selbst 0,0. Am Rand gemessen bekommt sie 0,0 -- die
    # Bremse schweigt dort, weil der Gruen-Score dort nichts trennen kann.
    #
    # Im Livestream wirkt dieselbe Regel umgekehrt: Die Wolken liegen bei 14
    # bis 31, der Rand bei 20 bis 30, und die Schwelle steigt von rund 8 auf
    # 10 bis 15 -- also SCHAERFER, bei praktisch gleicher Bremsrate
    # (0,03/0,46/0,92/0,16 % gegen 0,03/0,44/0,92/0,15 %).
    #
    # 0,5 gewaehlt: Auf allen acht gemessenen Bahn/Quelle-Paaren bleibt die
    # Schwelle unter dem 1. Perzentil der gereinigten AUS-Wolke, faengt aber
    # eine Verdeckung (liest 0,0) mit grossem Abstand. 0,4 und 0,6 wurden
    # mitgemessen und erfuellen das auch; 0,6 laesst weniger Luft.
    #
    # 0 schaltet den Anteil ab; dann gilt nur der feste Wert.
    occlusion_edge_fraction: float = Field(default=0.5, ge=0.0, le=1.0)
    # Zwei Frames, damit ein einzelner Ausreisser nicht einfriert -- und
    # weniger als `min_stable_frames`, damit die Zustandsmaschine in der
    # Zwischenzeit nicht schon umschaltet.
    occlusion_min_frames: int = Field(default=2, ge=1)
    # Wie oft waehrend einer Verdeckung erinnert wird (Frames; 750 = 30 s).
    # Ohne das bliebe eine dauerhaft eingefrorene Bahn nach EINER Logzeile
    # stumm -- und genau so sieht es aus, wenn die Schwelle zum Material nicht
    # passt: Die Bahn meldet nie wieder einen Wurf, ohne dass etwas danach
    # aussieht. Die Schwelle ist an einer einzigen Halle gemessen.
    occlusion_reminder_frames: int = Field(default=750, ge=0)

    @model_validator(mode="after")
    def _check_hysteresis(self) -> GreenDetectionConfig:
        # Ohne diese Pruefung waere die Hysterese wirkungslos oder invertiert --
        # ein Fehler, der sich sonst erst als sporadisches Flattern zeigt.
        if self.off_threshold >= self.on_threshold:
            raise ValueError(
                f"off_threshold ({self.off_threshold}) muss kleiner sein als "
                f"on_threshold ({self.on_threshold}) -- sonst greift die Hysterese nicht"
            )
        if self.hue_min >= self.hue_max:
            raise ValueError("hue_min muss kleiner als hue_max sein")
        return self


class LampDetectionConfig(BaseModel):
    implementation: Literal["warmth"] = "warmth"
    # HELLIGKEIT ist das Hauptkriterium. GEMESSEN ueber 3600 Einzelmessungen
    # (4 Tafeln x 9 Lampen x 100 Frames):
    #     Helligkeit  AUS 154 +- 23   AN 254 +- 3    Trennguete 7,66
    #     Waerme      AUS  19 +- 10   AN  57 +- 13   Trennguete 3,35
    # Optimale Schwelle laut Otsu: 203 -- hier mit Hysterese darum herum.
    brightness_on_threshold: int = Field(default=210, ge=0, le=255)
    brightness_off_threshold: int = Field(default=195, ge=0, le=255)
    # Waerme nur als Plausibilitaetsschranke gegen helle, farblose Reflexe.
    # Bewusst locker: Waren beide Kriterien mit UND verknuepft, bestimmte das
    # schwaechere das Ergebnis -- klar leuchtende Lampen galten als UNKNOWN.
    # Mitlaufender AUS-Bezugswert je Lampe.
    #
    # GEMESSEN ueber 52 Minuten: Die Helligkeit der AUSGESCHALTETEN Lampen
    # steigt im Lauf der Aufnahme von Median 151 auf 185 -- am Ende liegen fast
    # 24 % aller AUS-Messungen ueber der festen Schwelle von 195 und werden
    # dadurch UNKNOWN. Die Drift betrifft NUR die Tafeln (Mittelwert 94.9 ->
    # 109.4), waehrend das uebrige Bild flach bleibt (100.2 -> 100.8) und der
    # Bahnbereich sogar dunkler wird. Es ist also weder die Kamera noch die
    # Hallenbeleuchtung, sondern die Anlage selbst.
    #
    # Konsequenz: Eine absolute Schwelle kann ueber eine lange Aufnahme nicht
    # tragen. Die Schwellen werden deshalb relativ zum eigenen AUS-Niveau jeder
    # Lampe gebildet, das fortlaufend nachgefuehrt wird.
    adaptive_baseline: bool = True
    # Laenge des Gedaechtnisses in MESSUNGEN (nicht Frames). Bei einer Messung
    # alle 5 Frames entsprechen 400 Messungen rund 80 Sekunden -- lang genug,
    # dass jede Lampe darin mehrfach aus war (die Anlage stellt zwischen den
    # Wuerfen neu auf), aber kurz genug, um der Drift zu folgen.
    baseline_window: int = Field(default=400, ge=20)
    # Perzentil, das als AUS-Niveau gilt. Nicht das Minimum: Ein einzelner
    # Ausreisser nach unten wuerde sonst das Niveau bestimmen.
    baseline_percentile: float = Field(default=15.0, ge=0.0, le=50.0)
    # Abstaende ueber dem AUS-Niveau. Nur noch als Untergrenze der Grundlinie
    # in Gebrauch -- die Schwellen selbst liegen ANTEILIG (siehe unten).
    baseline_on_margin: float = Field(default=45.0, gt=0)
    baseline_off_margin: float = Field(default=28.0, gt=0)

    # Helligkeit einer leuchtenden Lampe: gesaettigt. GEMESSEN ueber 479 Wuerfe
    # (4311 Einzelmessungen): AN min 229,1 / Median 253,7 / max 255,0.
    brightness_saturated: float = Field(default=255.0, gt=0)
    # BEIDE Wolken mitfuehren statt nur der AUS-Seite. Begruendung und
    # Messbelege stehen in `config/default.yaml` und im Detektor.
    adaptive_on_level: bool = False
    # Ab hier praegt eine Messung das AN-Gedaechtnis. FESTE Schranke, damit die
    # Schwelle nicht darueber entscheidet, was sie selbst bestimmt.
    an_ignore_below: float = Field(default=225.0, ge=0)
    # Welche Raender der Wolken die Mitte aufspannen.
    aus_rand_percentile: float = Field(default=95.0, ge=50.0, le=100.0)
    an_rand_percentile: float = Field(default=5.0, ge=0.0, le=50.0)
    # Breite der Totzone als Anteil des Wolkenabstands.
    totzone_anteil: float = Field(default=0.18, ge=0.0, le=0.8)
    # Beruehren sich die Wolken, wird nicht getrennt, sondern zurueckgefallen.
    min_wolken_abstand: float = Field(default=20.0, ge=0)
    # Die Schwellen liegen anteilig zwischen Grundlinie und Saettigung statt in
    # festem Abstand darueber. Ein fester Abstand setzt voraus, dass das
    # AN-Niveau mitwandert -- das kann es nicht.
    #
    # Beobachtet an einer Lampe mit AUS-Niveau 212 (statt der ueblichen 164):
    # Additiv landete ihre AN-Schwelle bei 257, oberhalb der Saettigung. Sie
    # leuchtete mit 254 und galt als UNKNOWN.
    #
    # Die Anteile sind so gewaehlt, dass sich beim gemessenen TYPISCHEN
    # AUS-Niveau (Median 164) dieselben Schwellen ergeben wie bisher:
    #     164 + (255-164) * 0,50 = 209   (additiv: 164 + 45 = 209)
    #     164 + (255-164) * 0,31 = 192   (additiv: 164 + 28 = 192)
    # GEMESSEN 2026-08-31 ueber die Lampenspur (137 484 Messungen, 36 Lampen,
    # Frames 50000-112000). Verteilung der Helligkeit je Bahn, 10er-Schritte:
    #
    #     Bahn 2   grosse Wolke 140-170, dann fast nichts bis 250
    #     Bahn 4   Wolke 170-190, LANGER AUSLAEUFER 190-230, dann 240-255
    #
    # Der Anteil unentscheidbarer Messungen (UNKNOWN) lag dadurch bei
    #     Bahn 2  0,1 %   Bahn 3  4,1 %   Bahn 4  11,3 %   Bahn 5  5,6 %
    # -- ein Faktor 100 zwischen der besten und der schlechtesten Bahn.
    #
    # Mit 0,50 lag die AN-Schwelle im Mittel bei 211-219, also MITTEN im
    # Auslaeufer der AUS-Wolke. Das war der Schaden: Ein Kegel gilt als
    # gefallen, wenn er in EINEM der rund zehn abgetasteten Frames leuchtete
    # (die Anlagenlampen blinken, siehe `_aggregate_pins`). Diese Regel setzt
    # voraus, dass eine Lampe nicht faelschlich leuchten kann -- bei einer
    # Schwelle im Auslaeufer gilt das nicht.
    #
    # BILDBELEG (Bahn 4, Frame 54238): Die Tafel zeigt 7, das Protokoll sagt 7,
    # zwei Lampen sind sichtbar grau, eine Einzelmessung liest ebenfalls 7 --
    # der Lauf zaehlte 8.
    #
    # Mit 0,75 liegt die Schwelle bei 233-237 und damit im gemessenen TAL
    # (220-240, der duennste Bereich der Verteilung). Betroffen sind
    #     Bahn 2  0,1 %   Bahn 3  0,6 %   Bahn 4  1,9 %   Bahn 5  0,7 %
    # der Messungen -- genau der Auslaeufer, nicht die AN-Wolke (240-255).
    baseline_on_fraction: float = Field(default=0.75, gt=0.0, lt=1.0)
    baseline_off_fraction: float = Field(default=0.31, gt=0.0, lt=1.0)
    # Messungen ab diesem Wert gehen NICHT ins Gedaechtnis ein.
    #
    # Das Gedaechtnis soll das AUS-Niveau schaetzen -- eine leuchtende Lampe darf
    # es nicht mitbestimmen. Ohne diese Schranke zog eine dauerhaft leuchtende
    # Lampe ihren eigenen Bezugswert nach oben und wurde am Ende als AUS
    # gelesen (von `test_dauerleuchten_zieht_den_bezugswert_nicht_beliebig_mit`
    # aufgedeckt, bevor es Material erreichte).
    #
    # 235 liegt sicher zwischen beiden Verteilungen: AN ist gesaettigt bei
    # 254 +- 3, das hoechste beobachtete AUS-Niveau lag bei 212.
    baseline_ignore_above: float = Field(default=235.0, gt=0)
    # Zweite Sicherung: Weiter als das darf der Bezugswert nicht steigen.
    baseline_max_drift: float = Field(default=70.0, ge=0)

    # None heisst AUS -- die Helligkeit entscheidet allein.
    #
    # VORSICHT, HIER LAG EIN FEHLER (2026-09-16, vom Nutzer aufgedeckt): Der
    # Wert stand auf 0,0 mit dem Kommentar "abgeschaltet fuer diese Kamera".
    # Abgeschaltet war er damit NICHT. Die Waerme ist `rot - blau` und wird
    # bei einer weiss gesaettigten Lampe NEGATIV (gemessen -0,3 bis +0,3).
    # Null ist deshalb nicht "aus", sondern genau die Kante, auf der eine
    # weisse Lampe zittert -- und das Vorzeichen eines Rauschwerts entschied
    # ueber ON oder UNKNOWN.
    #
    # Der Nutzer dazu, und er hat auf ganzer Linie recht: *"wenn ich jetzt
    # weiter denke, eben an andere Bahnen, die vielleicht mit Gruen oder Roten
    # Lampen die Kegel anzeigen, waere dann NUR Helligkeit nicht cleverer?"*
    # `rot - blau` ist auf ROTE Lampen zugeschnitten. Bei gruenen Lampen laege
    # der Wert um null, bei blauen deutlich darunter -- jede einzelne Lampe
    # fiele durch, und niemand kaeme auf die Ursache, weil die Helligkeit ja
    # stimmt.
    #
    # Eine Anlage mit farbigen Lampen kann die Schranke ueber das
    # `AnlagenProfil` wieder einschalten. Die Vorgabe ist aus.
    warmth_min: float | None = None
    # Nur der helle Kern des ROI wird gemessen -- die Lampe fuellt das Rechteck
    # nie ganz aus, der Rand ist Gehaeuse.
    core_percentile: int = Field(default=70, ge=0, le=99)
    min_stable_frames: int = Field(default=2, ge=1)
    # Jeden n-ten Frame die Lampen fuer die Live-Anzeige lesen (0 = aus).
    # Nur fuer die Darstellung -- das Wurfergebnis kommt weiterhin
    # ausschliesslich aus dem GREEN_OFF-Moment.
    live_preview_interval: int = Field(default=5, ge=0)
    # Ueber so viele FRAMES wird die Live-Anzeige geglaettet (0 = gar nicht).
    #
    # WARUM -- gemessen 2026-09-08 an der Hallenkamera: Die neun Kegellampen
    # blinken GEMEINSAM, mit einer Periode von rund 15 Frames (1 Sekunde),
    # davon etwa 40 Prozent dunkel:
    #
    #     Bahn 3:  9 9 9 0 0 0 9 9 9 0 0 9 9 9 9 ...
    #
    # Das Wurfergebnis stoert das nicht -- es fasst viele Frames mit "AN, wenn
    # in mindestens einem an" zusammen. Die LIVE-ANZEIGE liest dagegen einen
    # einzelnen Frame und meldet darum regelmaessig "aus", obwohl die Lampe
    # sichtbar leuchtet. Der Nutzer sieht dann Flackern und misstraut zu Recht
    # der Messung.
    #
    # 20 Frames decken bei 15 fps eine volle Blinkperiode ab. Der Preis ist
    # eine Nachlaufzeit von gut einer Sekunde, wenn die Lampen wirklich
    # ausgehen -- fuer eine Anzeige belanglos, fuer die Zaehlung ohnehin ohne
    # Bedeutung: Sie benutzt diesen Wert nicht.
    live_preview_smoothing_frames: int = Field(default=20, ge=0)

    # Nach wie vielen Wuerfen in Folge, bei denen die Lampen NULL melden und
    # die Anzeigetafel etwas anderes, wird ein Messfehler gemeldet.
    #
    # GEMESSEN an drei Laeufen (Serie = Wuerfe in Folge auf DERSELBEN Bahn):
    #
    #   Lauf                    Wuerfe   Widersprueche   laengste Serie
    #   2026-09-04 12:31          706          0              --
    #   2026-09-04 15:12         1677          2               1
    #   2026-09-07 13:14 (defekt)  67         61          12 bis 17
    #
    # Die Luecke zwischen 1 und 12 ist so breit, dass die genaue Wahl kaum ins
    # Gewicht faellt. Fuenf liegt in der Mitte: weit ueber allem, was gesundes
    # Material je erreicht hat, und weit unter der kuerzesten Serie des
    # Defekts -- die Meldung kommt also nach rund fuenf Wuerfen je Bahn und
    # nicht erst am Ende des Laufs.
    silent_failure_after: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def _check_hysteresis(self) -> LampDetectionConfig:
        if self.brightness_off_threshold >= self.brightness_on_threshold:
            raise ValueError(
                f"brightness_off_threshold ({self.brightness_off_threshold}) muss "
                f"kleiner sein als brightness_on_threshold "
                f"({self.brightness_on_threshold}) -- sonst greift die Hysterese nicht"
            )
        return self


class DigitDetectionConfig(BaseModel):
    # Einigkeit, die eine EINZELNE Stelle ueber die Frames erreichen muss.
    # Niedriger als bei ganzen Werten: Eine Stelle hat zehn moegliche
    # Ausgaenge, aber die Fehler streuen nicht -- gemessen kippte eine Stelle
    # ausschliesslich zwischen zwei Ziffern (35:5). Ein klarer Sieger reicht.
    min_digit_agreement: float = Field(default=0.5, ge=0.0, le=1.0)
    # Band um die Segmentschwelle, in dem eine Messung als UNENTSCHIEDEN gilt.
    #
    # Kippt die Entscheidung an EINEM Segment, das genau auf der Schwelle liegt,
    # ist die gelesene Ziffer geraten. GEMESSEN auf Bahn 5: Segment a lag
    # konstant bei 0,333 bei einer Schwelle von 0,288-0,326 -- aus 'bcfg' (4)
    # wurde 'abcfg' (9), und die Tafel zeigte nachweislich eine 4.
    #
    # Diese beiden Muster unterscheiden sich seit BUG-009 in genau einem
    # Segment. Ein knapper Ausgang darf deshalb kein Ergebnis liefern: Die
    # Ziffer ist Gegenprobe zu den Lampen, und eine FALSCHE Gegenprobe ist
    # schaedlicher als gar keine -- sie erzeugt einen Widerspruch, wo keiner ist.
    segment_ambiguous_band: float = Field(default=0.06, ge=0.0, le=0.5)
    # Felder, die die Tafel ERST SPAET aktualisiert (Nutzerhinweis, gemessen):
    # Wurfnummer und Kegelzahl stehen sofort nach GREEN_OFF richtig da, die
    # Summe erst kurz vor dem naechsten GREEN_ON. Diese Felder werden deshalb
    # aus den letzten Messungen des Fensters gebildet, nicht aus den ersten.
    late_fields: list[str] = Field(default_factory=lambda: ["total_a", "total_b"])
    # Abstand der Mitlesungen waehrend des Fensters (in Frames)
    late_read_interval: int = Field(default=5, ge=1)

    # ZIFFERN IN DER LIVE-ANZEIGE. Jeden n-ten Frame werden alle Felder
    # gelesen und im Bahnpanel angezeigt -- 0 schaltet es ab.
    #
    # WOFUER (Nutzer, 2026-09-11): "ich haette gerne, dass dort auch steht, was
    # er gerade an Ziffern erkannt hat ... das wuerde mir helfen bei der
    # Evaluierung, ob wir die Ziffern bald wieder reinnehmen."
    #
    # Diese Lesungen gehen in KEINE Zaehlung. 25 Frames sind eine Sekunde --
    # schnell genug fuers Auge. GEMESSEN 2026-09-11: 4,25 ms je Bahn und
    # Lesung, bei Takt 25 also 0,68 ms je Frame. Die Bahnen lesen VERSETZT,
    # damit kein einzelner Frame alle vier auf einmal traegt.
    live_read_interval: int = Field(default=25, ge=0)

    # FEHLWURFZAEHLER (linkes Display). Er ist die einzige Quelle, die einen
    # Wurf ohne Kegel verraet: Faellt nichts, schaltet die Anlage die gruene
    # Lampe gar nicht aus, und der Wurf ist fuer den Trigger unsichtbar (Q10).
    #
    # Wird IMMER gelesen, nicht nur im Wurffenster -- der Nullwurf geschieht ja
    # waehrend die gruene Lampe an ist.
    foul_field: str = "left_display"
    foul_read_interval: int = Field(default=10, ge=0)
    # So viele gleiche Messungen in Folge gelten als stabiler Wert.
    # GEMESSEN ueber 52 Minuten auf Bahn 2: Die Rohwerte enthielten 147-mal
    # "3", dreimal "7" und einmal "70" als Fehllesung -- keiner dieser Werte
    # stand fuenfmal hintereinander. Der Filter entfernte alle, ohne den einen
    # echten Anstieg zu verlieren.
    foul_stable_readings: int = Field(default=5, ge=1)
    # Um hoechstens so viel darf der Fehlwurfzaehler zwischen zwei stabilen
    # Staenden STEIGEN. Ein groesserer Sprung ist keine Serie von Nullwuerfen,
    # sondern eine Fehllesung.
    #
    # WARUM DAS SICHER IST: Der Zaehler wird alle `foul_read_interval` Frames
    # gelesen (10), ein Wurfzyklus dauert gemessen 216 bis 338 Frames. Zwischen
    # zwei Lesungen kann also hoechstens EIN Wurf liegen.
    #
    # GEMESSEN ueber den vollen Spieltag 2026-08-29 (1731 Wuerfe, 4 Bahnen) --
    # alle Anstiege des Zaehlers nach Sprunghoehe:
    #
    #     Bahn 2   +1: 1
    #     Bahn 3   keine
    #     Bahn 4   +1: 1,  +3: 14      <-- 14 Spruenge um drei, alle auf EINER Bahn
    #     Bahn 5   +1: 2
    #
    # Jeder dieser Spruenge buchte DREI Nullwuerfe; zusammen 42 erfundene
    # Wuerfe. Bahn 4 zaehlte dadurch 463 Wuerfe bei 426 Gruenzyklen, und
    # Spieler Cs Satz fiel auf 11 von 30.
    #
    # BILDBELEG (Frame 270290, Bahn 4): Die Tafel zeigt `00`, der Erkenner
    # liest `03`. Der Wert 3 ist als Stoerwert dieses Feldes seit langem
    # bekannt -- er stand schon in der Messung von 2026-08-25 in den Rohwerten
    # ({0: 10711, 1: 776, 3: 147, 7: 3, 70: 1}), ueberstand dort aber den
    # Stabilitaetsfilter nicht.
    foul_max_rise: int = Field(default=1, ge=1)
    # Wie viele der letzten Mitlesungen in die Abstimmung eingehen.
    # 14 x 5 Frames decken rund 70 Frames vor GREEN_ON ab -- gemessen war die
    # Summe dort bereits aktualisiert (spaetestens ab -60). Die letzten ~4 Frames
    # vor GREEN_ON sind unbrauchbar (die Anzeige wechselt dort, Lesung wird '?'),
    # sie fallen bei der stellenweisen Abstimmung aber ohnehin heraus.
    #
    # GEMESSEN ueber vier Kombinationen (lesbare Summen / Summenkette stimmig):
    #     keep= 8 interval=8:  37/70 | 80,6 %
    #     keep= 8 interval=5:  37/70 | 73,3 %
    #     keep=14 interval=8:  36/70 | 76,7 %
    #     keep=14 interval=5:  39/70 | 82,4 %   <- gewaehlt
    late_keep: int = Field(default=14, ge=1)
    # Feinausrichtung der handgesetzten Ziffernrahmen (in Pixeln, je Richtung).
    # STANDARD 0 = aus. Siehe config/default.yaml: Das Verfahren richtet auf
    # hoechste Confidence aus, und die misst Musterschaerfe statt Richtigkeit --
    # gemessen wurde aus "001" ein "081".
    refine_radius: int = Field(default=0, ge=0, le=5)
    # Mindestgewinn an Confidence, damit ein Versatz uebernommen wird. Ohne
    # diese Huerde gewinnt Rauschen, und die Ausrichtung springt je Video.
    min_refine_gain: float = Field(default=0.05, ge=0.0, le=1.0)
    implementation: Literal["seven_segment", "template", "ocr", "ml"] = "seven_segment"
    min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # Rotschwelle der leuchtenden Segmente
    red_threshold: int = Field(default=120, ge=0, le=255)
    # Mindestabstand von Rot zu Gruen und Blau. Das beige Gehaeuse ist im
    # Rotkanal ebenfalls hell -- erst der Abstand trennt Anzeige von Gehaeuse.
    red_min_margin: int = Field(default=45, ge=0, le=255)
    # Ab welchem Fuellgrad ein Segment als aktiv gilt (0..1)
    segment_on_ratio: float = Field(default=0.35, gt=0.0, lt=1.0)
    # Breite einer Ziffer im Verhaeltnis zu ihrer Hoehe.
    # GEMESSEN ueber alle Felder und Bahnen: 0.53-0.71, Schwerpunkt 0.65.
    digit_aspect_ratio: float = Field(default=0.65, gt=0.1, lt=2.0)
    # Mindestgroesse der Luecke zwischen aktiven und inaktiven Segmenten, damit
    # die adaptive Schwelle greift. Darunter wird segment_on_ratio verwendet.
    min_segment_gap: float = Field(default=0.15, gt=0.0, lt=1.0)
    # Fuer einzeln eingerahmte Ziffern: Ein Segment gilt als aktiv, wenn es
    # diesen Anteil des HELLSTEN Segments derselben Ziffer erreicht.
    # Das hellste Segment ist immer aktiv -- daran laesst sich der Rest messen.
    segment_relative_ratio: float = Field(default=0.35, gt=0.0, lt=1.0)
    # Untergrenze, damit bei dunkler Anzeige kein Rauschen als Segment zaehlt.
    segment_floor: float = Field(default=0.12, ge=0.0, lt=1.0)
    # Wie schnell die Sicherheit eines Segments mit dem Abstand zur Schwelle
    # waechst (Skala der Logistik in `segment_probabilities`).
    #
    # GEMESSEN am 2026-09-15 als Rauschen eines Fuellgrades bei UNVERAENDERTER
    # Anzeige -- Bahn 3 und Bahn 4, vier Fenster, 1329 Frames:
    #     Median 0,003 bis 0,016   |   90. Perzentil 0,040   |   Maximum 0,119
    # Genommen wird das 90. Perzentil: Bei diesem Abstand zur Schwelle ist eine
    # Ziffer zu 73 % sicher, beim Doppelten zu 88 %, beim Dreifachen zu 95 %.
    # Der Median waere zu selbstsicher -- er gilt fuer die ruhigsten Segmente,
    # nicht fuer die, an denen Entscheidungen haengen.
    segment_probability_scale: float = Field(default=0.04, gt=0.0, lt=1.0)
    # Wie wahrscheinlich die beste Ziffer sein muss, damit ein UNGUELTIGES
    # Segmentmuster trotzdem gelesen wird. Darunter bleibt es bei "?".
    #
    # GEMESSEN an den vier von Hand nachgeprueften Faellen (Bahn 4, F5400,
    # F6100, F6400, F6650): Die im Bild eindeutige Ziffer kam dort auf 74 %
    # bis 100 %. Der naechstschwaechere Kandidat lag bei 26 %. Die Schwelle
    # liegt darunter, damit diese Faelle gelesen werden, und ueber dem
    # Muenzwurf, damit ein echtes Patt schweigt.
    segment_probability_min: float = Field(default=0.5, gt=0.0, le=1.0)
    # SCHRAEGLAGE DER ZIFFERN. Die Messflaechen werden umso weiter nach rechts
    # gerueckt, je weiter oben sie liegen. 0,08 heisst: die oberste Flaeche
    # sitzt um 8 % der Zellenbreite weiter rechts als die unterste.
    #
    # Der Nutzer beim Blick auf `debug/segmentlage.png` (2026-09-15): *"dann
    # sitzen die Flaechen der linken Seite oben und in der absoluten Mitte
    # falsch"*. Die Ziffern dieser Tafel stehen kursiv, die Flaechen standen
    # gerade -- Segment f (oben links) erreichte aktiv im Mittel nur 0,617
    # gegen 0,867 bei a und fiel als erstes unter die Schwelle.
    #
    # GEMESSEN an 1187 beschrifteten Ziffernbildern
    # (`data/ground_truth/ziffern_neue_sperre.npz`, Wahrheit aus den Lampen),
    # Einstellung auf der einen Haelfte gewaehlt, auf der anderen geprueft:
    #
    #     Scherung   Treffer (Pruefhaelfte)   gueltige Muster
    #       0,00            86,8 %                88,0 %
    #       0,04            87,7 %                91,1 %
    #       0,08            87,7 %                94,0 %
    #       0,12            86,7 %                94,4 %
    #       0,16            86,7 %                97,6 %
    #
    # Der Gewinn an TREFFERN ist klein (0,9 Punkte, also 6 von 608 Bildern)
    # und liegt auf einem flachen Plateau von 0,04 bis 0,10; darueber faellt
    # er wieder. Der Gewinn an GUELTIGKEIT ist der eigentliche: Der Anteil der
    # Lesungen, die auf den Notfallpfad fallen, halbiert sich von 12 % auf
    # 6 %. Diese Zahl kommt ohne jede Beschriftung aus -- sie zaehlt nur, ob
    # das gemessene Muster ueberhaupt in der Tabelle steht.
    #
    # Gewaehlt ist die Mitte des Plateaus, nicht sein Rand.
    #
    # ABGESCHALTET (Vorgabe 0,0), UND ZWAR NACH EINER GEGENPROBE, DIE DAGEGEN
    # SPRACH. Am beschrifteten Datensatz sah die Scherung gut aus. Am ganzen
    # Mitschnitt gemessen -- Summenfeld `total_b`, fortlaufend gelesen, gegen
    # dieselbe Systematik wie oben -- kehrte sich das um:
    #
    #     Bahn   ohne Scherung   mit 0,08 / Einzug 0,06
    #       2       73,7 %              52,8 %
    #       3       98,5 %              99,0 %
    #       4       94,8 %              91,4 %
    #       5       98,3 %              99,0 %
    #
    # Auf Bahn 2 stieg die Zahl der Lesungen von 362 auf 996: Die geaenderte
    # Geometrie erzeugt gueltige Muster, wo vorher geschwiegen wurde -- und
    # die sind falsch. Der beschriftete Datensatz konnte das nicht zeigen, er
    # besteht zu zwei Dritteln aus Bahn 2+3 und misst vor allem das
    # EINSTELLIGE Feld `pin_count`, nicht die vierstellige Summe.
    #
    # Die Parameter bleiben, weil die Richtung stimmt und eine andere Anlage
    # sie brauchen kann. Die Vorgabe bleibt bei null, bis eine Messung am
    # laufenden Material sie traegt.
    segment_shear: float = Field(default=0.0, ge=0.0, le=0.5)
    # Wie weit die MITTLERE Flaeche (g) beidseitig eingezogen wird.
    #
    # Sie liegt zwischen den senkrechten Segmenten und erwischt bei schraeger
    # Schrift deren Striche -- im Bild sichtbar an einer klar lesbaren `0`, die
    # als "8 zu 52,4 % gegen 0 zu 47,4 %" herauskam. Die Richtung ist nicht
    # neu: Die Flaeche wurde schon einmal verengt, weil jede `0` als `8`
    # gelesen wurde. Sie war nur noch nicht schmal genug.
    #
    # GEMESSEN am selben Datensatz: Der Einzug hebt die Treffer von 86,8 % auf
    # 87,7 % und auf Bahn 4 und 5 von 66,8 % auf 69,3 % -- ab 0,06 und dann
    # unveraendert bis 0,12. Auf die Gueltigkeit wirkt er nicht.
    #
    # WICHTIG: Einzug und Scherung heben DIESELBEN Faelle, sie addieren sich
    # nicht. Beide stehen trotzdem, weil sie verschiedene Ursachen treffen und
    # bei einer anderen Anlage verschieden ausfallen duerften.
    segment_middle_inset: float = Field(default=0.0, ge=0.0, lt=0.16)
    # Mindesthelligkeit im Ziffern-ROI (95. Perzentil Rotkanal), damit ueberhaupt
    # gelesen wird. Ohne diese Schranke macht Otsu aus Rauschen eine Ziffer --
    # gemessen bevorzugt eine "8". Klare Anzeige = 255, verblassend <= 212.
    min_display_brightness: int = Field(default=200, ge=0, le=255)
    # WORAUF die Schwelle angewandt wird. 100 = Maximum des Rotkanals.
    #
    # Vorher galt das 95. Perzentil ueber die ganze Zelle. Das benachteiligt
    # systematisch die schmalen Ziffern: Eine "1" leuchtet mit zwei von sieben
    # Segmenten, gemittelt bleibt sie dunkler als jede andere Ziffer, obwohl
    # sie im Bild eindeutig ist.
    #
    # GEMESSEN ueber 4800 Ziffernzellen aus vier Bloecken der Aufzeichnung,
    # Anteil im Graubereich 150-245 (dort ist die Entscheidung unsicher):
    #     95. Perzentil   1196 Zellen   24,9 %
    #     99. Perzentil    313 Zellen    6,5 %
    #     Maximum          175 Zellen    3,6 %
    # Eine dunkle Zelle (Anzeige leer, nur Rauschen) erreicht ein Maximum von
    # 114-119, eine leuchtende 246-255. Die Schwelle 200 liegt in der Luecke.
    brightness_percentile: float = Field(default=100.0, gt=0.0, le=100.0)
    # Mindest-Korrelation beim Template Matching, damit eine Ziffer als erkannt
    # gilt. Darunter wird "?" gemeldet statt geraten.
    template_min_score: float = Field(default=0.30, ge=-1.0, le=1.0)


class BoardSearchConfig(BaseModel):
    """Die automatische Tafelsuche (siehe `calibration/board_library.py`)."""

    # IN WELCHEN GROESSEN das Musterbild angeboten wird.
    #
    # WARUM ES DIE LEITER BRAUCHT. Der Merkmalsabgleich vertraegt nur einen
    # schmalen Massstabsbereich. GEMESSEN 2026-09-15 an einem Hallenframe, in
    # dem alle vier Tafeln sicher gefunden werden (154 tragende Merkmale) --
    # das Zielbild schrittweise vergroessert und verkleinert:
    #
    #     Zielmassstab   nur Original   mit Leiter
    #            0,6x              0           25
    #            0,8x             86           86
    #            1,0x            154          154
    #            1,5x            102          228
    #            2,0x              0          461
    #            3,0x              0          398
    #            4,0x              0          666
    #
    # Ohne Leiter reicht es von 0,8 bis 1,5 -- mit ihr von 0,6 bis 4,0.
    #
    # WARUM DAS ZAEHLT: Eine fest montierte Hallenkamera steht immer gleich
    # weit weg, ein Handy nicht. Auf dem Telefon fuellte eine Tafel rund 900
    # Bildpunkte gegen 190 im Muster -- das Fuenffache, weit ausserhalb des
    # Fensters. Die Suche fand nichts, und es sah aus, als koenne das
    # Verfahren nichts.
    #
    # Die TEUREN Merkmale des Zielbildes werden nur EINMAL berechnet; jede
    # weitere Sprosse kostet nur den Vergleich.
    #
    # Zum Abschalten: eine Liste mit einer einzigen 1.0.
    scale_ladder: list[float] = Field(
        default_factory=lambda: [0.35, 0.5, 0.7, 1.0, 1.4, 2.0, 2.8, 4.0])

    @model_validator(mode="after")
    def _check_ladder(self) -> BoardSearchConfig:
        if not self.scale_ladder:
            raise ValueError("scale_ladder darf nicht leer sein -- fuer die "
                             "unveraenderte Vorlage genuegt [1.0]")
        if any(f <= 0 for f in self.scale_ladder):
            raise ValueError("scale_ladder: Massstaebe muessen positiv sein")
        return self


class PersonMaskConfig(BaseModel):
    """Menschen schwaerzen und Tafelverdeckung erkennen.

    Siehe `detection/person_maske.py` fuer die Messungen dahinter.
    """

    enabled: bool = True
    # Wie viele Frames das Hintergrundmodell zurueckblickt. 500 Frames sind
    # bei 15 fps rund 33 Sekunden. Wer laenger stillsteht, wandert ins Modell
    # und wird nicht mehr geschwaerzt -- die bekannte Grenze des Verfahrens.
    history: int = Field(default=500, ge=50)
    var_threshold: float = Field(default=32.0, gt=0)
    # Gerechnet wird auf dem verkleinerten Bild. 3 heisst ein Neuntel der
    # Pixel -- das entscheidet ueber die Rechenzeit.
    scale: int = Field(default=4, ge=1, le=8)
    # Kleiner als das ist kein Mensch, sondern Kugel, Kegel oder Rauschen
    # (Pixel im VOLLBILD gerechnet).
    min_blob_px: int = Field(default=400, ge=0)
    # Die Person zu einer Flaeche schliessen. Ein halb geschwaerztes Gesicht
    # ist kein geschwaerztes Gesicht.
    dilate_px: int = Field(default=9, ge=1)
    # Ab diesem Anteil bewegten Vordergrunds im Tafelbereich gilt die Bahn als
    # VERDECKT und wird eingefroren.
    #
    # GEMESSEN 2026-09-08 ueber 13 530 Frames des Trainingsmitschnitts:
    #     Median ueber alle Frames        0,001
    #     echte Wuerfe, hoechster Wert    0,128
    #     Phantomwurf F13224 (Bahn 2)     0,197
    #     Phantomwurf F171   (Bahn 4)     0,150
    # 0,14 liegt zwischen dem hoechsten echten und dem niedrigsten falschen
    # Wert. Der Abstand ist knapp -- er stammt aus EINER Aufzeichnung und
    # gehoert nachgemessen, sobald mehr Material da ist.
    occlusion_fraction: float = Field(default=0.14, ge=0.0, le=1.0)
    # Solange das Hintergrundmodell lernt, gilt nichts als verdeckt.
    # Im ersten Frame ist alles Vordergrund -- gemessen 1,0 auf allen
    # vier Bahnen. Ohne diese Sperre faellt jeder Laufstart in die Bremse.
    warmup_frames: int = Field(default=60, ge=0)
    # WACHE UEBER DEN TAFELAUSSCHNITT (siehe `analysis/tafel_wache.py`).
    #
    # ANLASS (Nutzer, 2026-09-13): "im Liveticker sieht man sehr haeufig noch
    # Gesichter -> immer dann, wenn sie Phantomwuerfe erzeugen." Die
    # Tafelbereiche sind vom Schwaerzen ausgenommen, weil dort das Signal
    # steht -- und genau dieses Rechteck geht als `board_jpeg` hinaus.
    #
    # Die Bewegungsmaske reicht dafuer NICHT: GEMESSEN am Mitschnitt vom
    # 2026-09-08, Frame 13489 -- ein Mensch beugt sich ueber die Tafel, ist im
    # Bild voll zu sehen, und die Bewegung meldet 0,081 (Schwelle 0,14). Er
    # steht still und ist ins Hintergrundmodell gewandert.
    #
    # Die Wache haelt stattdessen eine Referenz der eigenen Tafel und lernt nur
    # nach, wenn diese normal aussieht -- dann kann niemand hineinwandern.
    #
    # Ab dieser Abweichung (Graustufen) gilt ein Pixel als anders:
    wache_abweichung_grau: int = Field(default=40, ge=1, le=255)
    # Ab diesem Anteil abweichender STABILER Pixel (Gehaeuse, Fensterrahmen)
    # steckt etwas vor der Tafel. GEMESSEN ueber 2705 Messungen:
    #     Normalbetrieb    Median 1,41 %, 95. Perzentil 2,55 %
    #     Mensch davor     11,9 bis 14,1 %   (zugleich das Maximum des Laufs)
    # 0,05 liegt in der Luecke. 0 schaltet die Wache ab.
    wache_schwelle: float = Field(default=0.05, ge=0.0, le=1.0)
    # AB WANN DIE WACHE DIE AUSWERTUNG ANHAELT -- getrennt von der Schwelle
    # zum Schwaerzen, und bewusst viel hoeher.
    #
    # DER GRUND (BUG-030): `wache_schwelle` ist fuer den Datenschutz gemessen
    # und dafuer richtig. Die Wache selbst sagt dazu in ihrem Kopf: "Diese
    # Wache entscheidet NICHTS ueber Wuerfe." In der Verdeckungsbremse stand
    # sie trotzdem, mit derselben Schwelle -- und eine festhaengende Referenz
    # hielt damit eine Bahn 1089 Frames an, waehrend Gruen-Score (75,0) und
    # Personenmodell beide sagten, dass nichts verdeckt ist. Ein Wurf ging
    # dabei verloren.
    #
    # GEMESSEN am Stream vom 2026-09-17, Bahn 2, Referenz im Normalbetrieb
    # gelernt:
    #
    #     Normalbetrieb                       0,000
    #     festhaengende Referenz (BUG-030)    0,123 bis 0,198
    #     halb verdeckt                       0,246
    #     alles schwarz                       0,551
    #     dunkle Tafel am Streamende          0,622
    #
    # 0,40 trennt die beiden Gruppen mit Abstand nach beiden Seiten. Der Fall,
    # fuer den die Wache ueberhaupt in die Bremse kam -- Streamende, wo
    # Gruen-Score und Personenmaske beide blind sind und ohne sie drei Wuerfe
    # gebucht wurden -- liegt bei 0,62 und bleibt gefangen.
    #
    # Die Schwelle zum SCHWAERZEN bleibt bei 0,05: Ein Bild zu viel zu
    # schwaerzen kostet nichts, ein Gesicht zu veroeffentlichen schon.
    wache_bremse_schwelle: float = Field(default=0.40, ge=0.0, le=1.0)
    # Nachgelernt wird nur unterhalb dieses Anteils -- der Kern des Verfahrens.
    wache_nachlernen_unter: float = Field(default=0.10, ge=0.0, le=1.0)
    wache_lernrate: float = Field(default=0.05, gt=0.0, le=1.0)
    # Wie stark die Fremdmaske verbreitert wird, im Verhaeltnis zur Tafelkante.
    # Die rohe Abweichung ist loechrig: Wo die Kleidung zufaellig die Farbe des
    # Gehaeuses trifft, bliebe ein Loch -- und ein halb geschwaerztes Gesicht
    # ist kein geschwaerztes Gesicht.
    wache_wachstum: float = Field(default=0.10, ge=0.0, le=1.0)
    # Jeden n-ten Frame nachfuehren. Die Referenz aendert sich langsam (Licht,
    # nicht Inhalt), taeglich waere Verschwendung.
    wache_takt: int = Field(default=5, ge=0)
    # NEUSTART NACH DAUERALARM (BUG-026). Die Bewachung der Referenz schuetzt
    # davor, dass ein Mensch hineinwandert -- und macht die Wache damit
    # unfaehig, sich von einer ECHTEN Aenderung zu erholen.
    #
    # GEMESSEN 2026-09-14 am Hallenmitschnitt: Bei Frame 215 verschiebt sich
    # das Bild um wenige Pixel, die Abweichung auf Bahn 5 springt von 3,4 auf
    # 13 % -- ueber `wache_nachlernen_unter` -- und bleibt danach 13 000 Frames
    # bei 25,2 % stehen (Median = Maximum, also voellig unbewegt). Die Bahn war
    # den ganzen Mitschnitt lang eingefroren. Das Personenmodell sah dort auf
    # 0,6 % der Messpunkte einen Menschen, die Wache meldete auf 98,3 %.
    #
    # Verworfen wird die Referenz nur, wenn das Personenmodell ueber diese
    # ganze Strecke KEINEN Menschen auf der Tafel gesehen hat. Ohne geladenes
    # Modell passiert gar nichts -- dann fehlt der Zeuge, der es verantworten
    # kann.
    #
    # 750 Frames: GEMESSEN ueber denselben Lauf dauerten 118 echte Verdeckungen
    # im Median 30 Frames, im 99. Perzentil 142, die laengste 250. 750 ist das
    # Dreifache der laengsten -- und bei 25 fps eine halbe Minute.
    # 0 schaltet den Neustart ab.
    # Auf Nutzerwunsch von 750 auf 250 gesenkt (2026-09-17): *"das sind 10
    # Sekunden, das wird nie wieder vorkommen... eigentlich ist alles ueber 5
    # Sekunden schon zu lang.. aber puffer ist gut."*
    #
    # SEIT BUG-030 KOSTET DIESE FRIST KEINE WUERFE MEHR. Die Bremse haengt
    # nicht mehr an dieser Wache (`wache_bremse_schwelle`), also steuert die
    # Frist nur noch, wie lange eine festhaengende Referenz zu viel schwaerzt.
    #
    # Das verbleibende Risiko liegt damit beim DATENSCHUTZ, nicht beim Zaehlen:
    # Heilt sie, waehrend ein Mensch davorsteht und das Personenmodell ihn
    # gerade nicht sieht, lernt sie ihn in die Referenz hinein -- und danach
    # wird er nicht mehr geschwaerzt. Der Zaehler laeuft nur, solange das
    # Modell niemanden meldet, aber es findet gemessen 53 bis 57 von 70 Frames.
    # Bei 250 braucht es zehn Sekunden am Stueck, in denen es versagt.
    wache_neustart_frames: int = Field(default=250, ge=0)


class PersonModelConfig(BaseModel):
    """Das Personenmodell auf dem Tafelband -- der vierte Zeuge.

    Alle Zahlen hier sind am 2026-09-13 am Livestream gemessen; die Belege
    stehen im Kopf von `detection/personen_modell.py`.
    """

    enabled: bool = True
    # YOLOX-Tiny (Megvii, Apache-2.0). Die Gewichte liegen nicht im Repo, weil
    # sie 20 MB gross sind und sich nicht aendern -- `tools/hole_personenmodell.py`
    # holt sie. Fehlt die Datei, laeuft die Analyse mit drei Zeugen weiter.
    #
    # WARUM NICHT YOLOv8n: AGPL-3.0, und dieses Projekt steht unter MIT. Die
    # beiden vertragen sich nur in eine Richtung. YOLOX ist ausserdem
    # schneller -- die Lizenz kostet hier also gar nichts.
    model_path: str = "models/yolox_tiny.onnx"
    # Eingangskante. MUSS zur Modelldatei passen: Der ONNX-Export hat eine
    # feste Eingangsgroesse, und das Ankergitter wird daraus gerechnet.
    #     YOLOX-Tiny / -Nano   416
    #     YOLOX-S              640
    input_size: int = Field(default=416, ge=64, le=1280)
    # GEMESSEN: An den zehn Frames, in denen die Ampel auf 0,0 fiel, meldet
    # YOLOX-Tiny 0,73 bis 0,83; auf 600 Frames ohne Menschen gab es bei 0,25
    # keinen einzigen Fehlalarm.
    confidence: float = Field(default=0.25, gt=0.0, lt=1.0)
    nms: float = Field(default=0.45, gt=0.0, lt=1.0)
    # Das Suchband nach UNTEN verlaengern, im Verhaeltnis zur Tafelhoehe.
    # Ein Mensch vor der Tafel hat dort seinen Rumpf, und mit Rumpf findet ihn
    # das Netz sicherer: GEMESSEN 57 statt 53 von 70 Frames, Fehlalarme
    # unveraendert null. 2,0 bringt nichts mehr und kostet 30 ms.
    band_below: float = Field(default=1.0, ge=0.0, le=4.0)
    band_sides: float = Field(default=0.05, ge=0.0, le=1.0)
    # Ab diesem Anteil einer bedeckten Tafel gilt sie als von einem Menschen
    # verdeckt. 0 heisst: jede Beruehrung zaehlt.
    board_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    # STREIFE. Ausserhalb der billigen Ausloeser laeuft das Modell nur jeden
    # n-ten Frame. GEMESSEN ueber 20 000 Frames: In 1,95 % der Frames faellt
    # ueberhaupt eine Bahn unter ihre Verdeckungsschwelle -- ohne Streife saehe
    # das Modell einen Menschen also nie, der die Lampe gar nicht beruehrt.
    # 0 schaltet die Streife ab (nur noch Ausloeser).
    patrol_interval: int = Field(default=10, ge=0)
    # MINDESTABSTAND IM ALARMFALL. Auch wenn ein billiger Zeuge meldet, wird
    # das Netz nicht in JEDEM Frame gefragt -- seine Antwort aendert sich nicht
    # im 40-Millisekunden-Takt, ein Mensch steht rund 50 Frames im Bild.
    #
    # WARUM ES DIESE ZAHL BRAUCHT, gemessen 2026-09-13 ueber 3000 Frames des
    # Hallenmitschnitts: Auf Bahn 5 meldete die Tafelwache in 2704 Frames
    # (90 %) Fremdes -- diese Bahn steht auf dieser Aufnahme dauerhaft in der
    # Bremse. Ohne Mindestabstand lief das Netz dadurch in 94 % aller Frames
    # und der Durchsatz fiel von 32 auf 11 Frames/s. EIN festhaengender Zeuge
    # genuegt, um die Kostenrechnung umzuwerfen.
    #
    # 5 gewaehlt: Die kuerzeste bekannte Verdeckung dauerte 10 Frames
    # (F42224-42233), sie wird damit noch zweimal befragt.
    alarm_interval: int = Field(default=5, ge=1)
    # Woher `tools/hole_personenmodell.py` die Datei holt, und wie sie
    # aussehen muss. Die Pruefsumme ist kein Zierrat: Ein stillschweigend
    # ausgetauschtes Modell aendert das Verhalten der Schutzfunktion, ohne
    # dass ein Test rot wird.
    model_url: str = ("https://github.com/Megvii-BaseDetection/YOLOX/releases/"
                      "download/0.1.1rc0/yolox_tiny.onnx")
    model_sha256: str = ("427cc366d34e27ff7a03e2899b5e3671425c262ea2291f88bb"
                         "942bc1cc70b0f7")


class DetectionConfig(BaseModel):
    board_search: BoardSearchConfig = Field(default_factory=BoardSearchConfig)
    person_mask: PersonMaskConfig = Field(default_factory=PersonMaskConfig)
    person_model: PersonModelConfig = Field(default_factory=PersonModelConfig)
    green: GreenDetectionConfig = Field(default_factory=GreenDetectionConfig)
    lamps: LampDetectionConfig = Field(default_factory=LampDetectionConfig)
    digits: DigitDetectionConfig = Field(default_factory=DigitDetectionConfig)
    minimum_confidence: float = Field(default=0.6, ge=0.0, le=1.0)


class SamplingConfig(BaseModel):
    frames_after_green_off: list[int] = Field(
        default_factory=lambda: [2, 5, 10, 16, 22, 28, 34])
    frames_before_green_on: list[int] = Field(
        default_factory=lambda: [-2, -8])
    max_frames_per_event: int = Field(default=10, ge=1)
    # Frames NACH GREEN_ON, aus denen die Raeum-Grundlinie gebildet wird.
    #
    # Frueher wurde rueckwaerts gemessen ([0, -4, -8, ...]). Das war falsch:
    # Vor GREEN_ON steht noch das Ergebnis des VORHERIGEN Wurfs auf der Tafel.
    # Die Grundlinie enthielt dadurch dessen Kegel, und die Differenz ergab
    # null -- gemessen bei acht Wuerfen, bei denen alle neun Lampen mit
    # Helligkeit 254 klar leuchteten und trotzdem "0 Kegel" herauskam.
    #
    # Vom Nutzer erklaert: Die Kegel fallen, WAEHREND die gruene Lampe an ist.
    # Nach dem Hochzaehlen des Wurfzaehlers vergehen rund 4 Sekunden bis
    # GREEN_OFF. Kurz NACH GREEN_ON ist die Anlage also neu aufgestellt und der
    # Ball noch unterwegs -- genau dann zeigen die Lampen, welche Kegel bereits
    # lagen (beim Raeumen) bzw. gar keine (beim Spiel in die Vollen).
    #
    # 25 Frames sind eine Sekunde -- deutlich vor dem Aufschlag des Balls.
    baseline_offsets: list[int] = Field(default_factory=lambda: [0, 6, 12, 18, 25])

    # ... UND ZUGLEICH VOR GREEN_ON (BUG-016, Nutzeridee vom 2026-09-01).
    #
    # Das Fenster oben haengt am ERKANNTEN Gruen-AN, nicht am tatsaechlichen.
    # Meldet der Detektor zu spaet -- gemessen bis 69 Frames -- rutscht es in
    # die Zeit, in der die Kegel fallen, und die Grundlinie enthaelt den Wurf
    # selbst. Fuenf Wuerfe des Spieltags 2026-08-22 gingen so verloren.
    #
    # Der Nutzer wies auf die Gegenprobe hin: Beim Raeumen bleiben die
    # Ergebnislampen leuchten, bis der naechste Wurf abgeschlossen ist. Der
    # Stand kurz VOR dem Gruen-AN muss also derselbe sein -- und der haengt an
    # keiner Erkennung.
    #
    # Allein taugt er trotzdem nicht: Beim Aufstellen loescht die Anlage die
    # Lampen, und das faellt gemessen in 3 von 1610 Faellen in die letzten 17
    # bis 24 Frames vor dem Gruen-AN. Dann ist der Stand davor zu HOCH.
    #
    # Beide Fehler zeigen in dieselbe Richtung -- der falsche Wert ist immer
    # der groessere. Darum die SCHNITTMENGE: Ein Kegel gehoert zur Grundlinie,
    # wenn er vorher UND nachher lag.
    #
    # GEMESSEN an 1610 Wuerfen gegen die Tafel-Ziffer:
    #     nur nachher (vorher)   99,63 %
    #     nur vorher             99,44 %
    #     Schnittmenge           99,63 %   und rettet die fuenf Wuerfe
    baseline_before_green: bool = True

    # Wie weit vor dem Gruen-AN gesammelt wird. 50 Frames = 2 s; die Lampen
    # blinken mit 28-30 Frames Periode, ueber diese Spanne wird also jede
    # brennende Lampe mehrfach getroffen. Laenger schadet nicht -- in der
    # Pause steht der Stand still --, kostet aber Speicher je Bahn.
    baseline_before_frames: int = Field(default=50, ge=0)

    # DIE GRUNDLINIE AUS DER LAUFENDEN SPUR (BUG-031).
    #
    # Beide Wege oben haengen am ERKANNTEN Gruen-AN. Trifft dieses Fenster den
    # falschen Augenblick, ist die Grundlinie falsch und die Kegelzahl mit ihr.
    # Gemessen an einem Spieltag dreimal: Fenster kuerzer als die Gruenphase,
    # Fenster 87 Sekunden vor dem Wurf, Bahn waehrenddessen verdeckt.
    #
    # Fuer die Anzeige werden ohnehin alle paar Frames die Kegellampen gelesen.
    # Beim Raeumen bleiben die alten Lampen an -- der KLEINSTE Stand seit dem
    # vorigen Wurf ist die Grundlinie; nach dem Neuaufstellen faellt er auf
    # null, und das ist dann die richtige Grundlinie.
    #
    # GEMESSEN gegen die Kegelziffer der Tafel (tools/messe_grundlinie.py):
    #
    #     Lauf 2026-09-17 12:53, 874 Wuerfe   Fenster 99,54 %  Spur  99,77 %
    #     Lauf 2026-09-18 07:30, 421 Wuerfe   Fenster 99,51 %  Spur 100,00 %
    #
    # false stellt den alten Weg wieder her.
    baseline_from_trace: bool = True

    # Ueber wie viele FRAMES die laufenden Messungen zusammengefasst werden,
    # bevor der kleinste Stand gesucht wird. Muss laenger sein als eine
    # Blinkperiode (28-30 Frames, Dunkelphase bis 15 -- BUG-007a), sonst
    # erfindet eine Dunkelphase eine leere Grundlinie.
    #
    # IN FRAMES, NICHT IN MESSUNGEN. Der erste Anlauf zaehlte Messungen ("drei
    # gleiche hintereinander") und war an der `lampenspur.csv` geeicht, die nur
    # alle 25 Frames schreibt -- dort sind drei Messungen 75 Frames. Im Betrieb
    # werden die Lampen alle 5 Frames gelesen (`live_preview_interval`), drei
    # Messungen sind also 15 Frames: genau die maximale Dunkelphase. Der
    # Spieltagslauf 2026-09-18 verlor dadurch zwei zuvor richtige Wuerfe
    # (Bahn 4 F180292 und F198502). Siehe BUG-031.
    #
    # 40 Frames = 1,6 s, mehr als eine Blinkperiode, mit Puffer.
    baseline_trace_window_frames: int = Field(default=40, ge=1)

    # WAEHREND der Gruenphase mitlesen. Vom Nutzer vorgeschlagen (2026-08-28):
    # "Ich messe in einer Gruenphase immer, wie viele Lampen leuchten -- jetzt?
    # und jetzt? -- und dann steigt die Zahl ja optimalerweise."
    #
    # GEMESSEN gegen das Wurfprotokoll (tools/measure_report_delay.py, 474 Wuerfe):
    #
    #     ein Frame bei Gruen-AUS          82,7 %
    #     Maximum ueber die Gruenphase     98,9 %
    #     ganzes Fenster danach (frueher)  98,5 %
    #     Gruenphase + 40 Frames           99,4 %   <- beides zusammen
    #
    # Die Kegel fallen, waehrend Gruen an ist. Wer nur danach misst, verlaesst
    # sich darauf, dass das Ergebnis stehen bleibt -- und verliert es, wenn die
    # Pause kurz ist (auf Bahn 4 dreimal belegt). Wer nur davor misst, verliert
    # es bei sehr kurzen Gruenphasen. Zusammen decken sie sich gegenseitig ab.
    green_phase_interval: int = Field(default=5, ge=0)

    # DER BREAKPOINT: die Wurfnummer der Tafel trennt Grundlinie und Ergebnis.
    #
    # Nutzer, 2026-09-28: *„wenn die Wurfnummer hochzählt, beginnen die 4 sek.
    # sonst nehmen wir das als Breakpoint und davor ist Grundlinie und danach
    # bis Grün aus ist Ergebnis."*
    #
    # Damit haengt die Trennung an einem EREIGNIS AUF DER TAFEL statt an
    # Frameversaetzen nach dem Gruen-AN. Drei Dinge werden dadurch besser:
    #
    #   * Die Grundlinie ist "alles bis zum Sprung" -- bei kurzen Raeumzyklen
    #     entsprechend kurz. GEMESSEN: Zwischen Gruen-AN und erstem fallenden
    #     Kegel liegen beim Raeumen im Median 84 Frames, p05 nur 38; ein festes
    #     Fenster passt dort nicht.
    #   * Das Ergebnis ist "ab dem Sprung" und damit frei vom Nachleuchten der
    #     vorigen Anzeige.
    #   * Kein Schwellwert muss zum Spieltag passen.
    #
    # GEMESSEN am 2026-09-28 ueber 100 Gruenzyklen aller vier Bahnen
    # (`tools/messe_wurfnummer_sprung.py`):
    #
    #     Bahn   Nummer lesbar   Sprung gesehen   Abstand vor Gruen-AUS
    #       2         26/26           96,2 %      Median 3,95 s
    #       3         25/25           96,0 %      Median 3,95 s
    #       4         23/23           95,7 %      Median 4,25 s
    #       5         26/26           88,5 %      Median 4,35 s
    #
    # Wird kein Sprung gesehen, gilt das bisherige Verfahren unveraendert.
    breakpoint_from_throw_number: bool = True

    # Welche Bildguete eine einzelne Lesung der Wurfnummer haben muss, damit
    # sie in die Spur kommt.
    #
    # EIGENER WERT, NICHT `scoring.throw_number_min_confidence` (0,9). Jener
    # entscheidet ueber das Verwerfen ganzer Zyklen und darf streng sein. Hier
    # zaehlt eine EINZELNE Messung von vielen, und ein Sprung braucht nur zwei
    # brauchbare hintereinander.
    #
    # GEMESSEN am 2026-09-28, Anteil der Zyklen mit erkanntem Sprung:
    #
    #     Gate    Bahn 2   Bahn 3   Bahn 4   Bahn 5   Median des Abstands
    #     0,5      100 %     96 %     96 %     88 %   3,95 / 3,95 / 4,25 / 4,35 s
    #     0,7      100 %     96 %     96 %     88 %   3,90 / 3,95 / 4,25 / 4,35 s
    #     0,8       92 %     96 %    100 %     85 %   3,80 / 3,95 / 4,25 / 4,22 s
    #     0,9       15 %     52 %     48 %     58 %   2,98 / 3,65 / 4,00 / 3,95 s
    #
    # Bei 0,9 bricht nicht nur die Trefferquote ein -- der Median wandert,
    # der gefundene Sprung ist dann oft der falsche. Mit 0,9 (mein erster
    # Versuch) blieb der ganze Spieltagslauf bitgleich zum alten.
    # NACHTRAG 2026-09-28, an der frameweisen Spur nachgemessen: 0,7 ist zu
    # hoch. GENAU AM SPRUNG faellt die Guete ein, weil die Anzeige dort
    # wechselt -- auf Bahn 5 von 0,98 auf 0,64:
    #
    #     14328   007   0,98   (alle aus)
    #     14329   003   0,64   (alle aus)   <- die 7 kurz als 3 gelesen
    #     14331   008   0,70   (alle aus)   <- der Sprung
    #     14334   008   0,64   1 2          <- erste Lampe, 3 Frames spaeter
    #
    # Ein Gate von 0,7 verwirft ausgerechnet die Frames am Sprung. Die
    # Fehllesung (7 als 3) ist ungefaehrlich: Der Breakpoint sucht einen
    # Anstieg um genau eins und uebergeht Rueckfaelle.
    breakpoint_min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    # BEI GRUEN-AUS IST DIE ZAEHLUNG FERTIG.
    #
    # Nutzer, 2026-09-28: *„sobald Grünaus geht, müssen wir fertig sein mit
    # unserer Zählung."* Physisch begruendet: Bei Gruen-AUS kann kein Kegel
    # mehr fallen, das hat der Nutzer von Anfang an so erklaert.
    #
    # Das Ereignisfenster bleibt danach trotzdem offen -- aber nur fuer die
    # ZIFFERN, die spaet nachziehen (Wurfnummer und Summe stehen erst kurz vor
    # dem naechsten Gruen-AN richtig da). Die Lampen waren bisher an dieses
    # Fenster gekoppelt und sammelten weiter mit.
    #
    # WAS DAS KOSTETE: Genau nach Gruen-AUS beginnt ein Fehlercode der Tafel
    # (BUG-036, gemessen sieben Frames danach). Die Vereinigung nahm dessen
    # dauerleuchtende UND blinkende Lampen ins Ergebnis -- auf Bahn 4 wurden
    # daraus zweimal alle neun Kegel, wo die Tafel 7 zaehlte.
    #
    # ZURUECKGENOMMEN am 2026-09-28. Die Praemisse stimmt -- nach Gruen-AUS
    # faellt kein Kegel mehr. Das ABLESEN ist dort aber nicht fertig: Bei
    # „alle Neune" und beim 8er Kranz blinkt die Anzeige, und die Frames nach
    # Gruen-AUS waren es oft, die eine Lampe ueberhaupt einmal leuchtend
    # erwischten. GEMESSEN ueber die ersten 42 Minuten des Spieltags: 97,8 %
    # auf 94,1 % gefallen, 11 Wuerfe veraendert, davon 9 schlechter und kein
    # einziger besser -- und jedes Mal ZU NIEDRIG (9 auf 1, 8 auf 1, 9 auf 3).
    #
    # Der Fehlercode wird stattdessen ueber den Breakpoint ausgeschlossen: Er
    # beginnt nach Gruen-AUS, das Ergebnisfenster beginnt beim Sprung der
    # Wurfnummer.
    count_closes_at_green_off: bool = False

    # Wie viele Lampen BLINKEN muessen, damit es ein Fehlercode ist.
    #
    # Nutzer, 2026-09-29: *„es gab nur 2 Fehlercodes im ganzen Spiel und
    # meines Wissens nach alle auf Bahn 4."* Mit einer einzigen blinkenden
    # Lampe meldete die Regel ueber denselben Spieltag fuenf -- vier davon
    # waren Bahn 5 Kegel 8, die zweimal flackerte (BUG-034).
    #
    # GEMESSEN an beiden echten Codes:
    #     Fall 1, 11 Messungen: blinkend [1,2,3,4,5,8]  fest [6,7,9]
    #     Fall 2, 16 Messungen: blinkend [1,2,3,4,5]    fest [6,7,8,9]
    # Beide bleiben bei 2 erkannt, alle vier Fehlalarme fallen weg.
    error_code_min_blinking_lamps: int = Field(default=2, ge=1, le=9)

    # DIE GRUNDLINIE IST NICHT FREI (Nutzeridee 2026-09-29): *„wie waere es
    # mit, die Grundlinie darf nur 0 sein ODER derselbe Wert wie im Wurf
    # zuvor?"*
    #
    # Kegel stehen nicht wieder auf. Nach einem Wurf liegt genau das, was
    # vorher lag, plus was dieser Wurf umwarf. Nur wenn die Anlage neu
    # aufstellt -- bei den Vollen nach jedem Wurf, beim Abraeumen nach allen
    # neunen -- liegt nichts. Es gibt also genau zwei erlaubte Grundlinien,
    # und welche gilt, zeigt die Tafel zu Beginn der Gruenphase selbst.
    #
    # ALLES ANDERE IST NACHLEUCHTEN des vorigen Wurfs: Jubelblinken oder ein
    # Fehlercode. Damit faellt beides weg, ohne dass die Regel es erwaehnt --
    # und der Wurf BEGINNT an derselben Stelle, an der die Grundlinie steht.
    #
    # GEMESSEN ueber den Spieltag (tools/simuliere_vorstand.py, 1473 Wuerfe
    # mit lesbarer Tafelsumme): Anker in 1671 von 1678 Wuerfen gefunden,
    # 1410 auf 1412 richtig, vier besser und zwei schlechter -- die zwei sind
    # das zu kurze Fenster des Simulators und Bahn 5 Kegel 8.
    baseline_from_previous_state: bool = False

    # Wie lange nach GREEN_OFF gewartet wird, bevor der Wurf gemeldet wird.
    #
    # Frueher wurde bis zum NAECHSTEN GREEN_ON gewartet -- im Mittel 15 Sekunden,
    # beim Spielwechsel bis zu einer Minute, und der letzte Wurf einer Aufnahme
    # ging ganz verloren. GEMESSEN ist ab 40 Frames nichts mehr zu gewinnen:
    #
    #     +25 Frames   470 von 474 richtig
    #     +40 Frames   471           blinkende Wuerfe 100 %
    #     +150 Frames  471           keine Verbesserung mehr
    #
    # 0 stellt das alte Verhalten wieder her (Meldung erst beim naechsten
    # GREEN_ON).
    report_after_green_off: int = Field(default=40, ge=0)

    @model_validator(mode="after")
    def _check_offsets(self) -> SamplingConfig:
        if any(o < 0 for o in self.frames_after_green_off):
            raise ValueError("frames_after_green_off darf keine negativen Offsets enthalten")
        if any(o > 0 for o in self.frames_before_green_on):
            raise ValueError("frames_before_green_on darf keine positiven Offsets enthalten")
        if any(o < 0 for o in self.baseline_offsets):
            raise ValueError("baseline_offsets darf keine negativen Offsets enthalten "
                             "-- vor GREEN_ON steht noch das vorige Wurfergebnis")
        return self


class StateMachineConfig(BaseModel):
    analyzing_timeout_s: float = Field(default=5.0, gt=0)
    stabilization_timeout_s: float = Field(default=3.0, gt=0)
    wait_green_timeout_s: float = Field(default=300.0, gt=0)
    min_frames_between_throws: int = Field(default=25, ge=0)
    # Mindestdauer eines Wurffensters (GREEN_OFF bis zum naechsten GREEN_ON).
    #
    # AUS (0), und das ist eine Korrektur. Der Wert stand auf 100, begruendet
    # mit "kuerzestes echtes Fenster 158 Frames, unter 100 nur Fehlausloeser".
    # Diese Messung war ZIRKULAER: Als "echtes Fenster" galt, was das Werkzeug
    # selbst zu einem Wurf gemacht hatte -- die kurzen Fenster hatte es bereits
    # verworfen und wurden deshalb als Fehlausloeser gezaehlt.
    #
    # Das handgefuehrte Wurfprotokoll (2026-08-28) zeigt das Gegenteil. Auf
    # Bahn 4 im vierten Satz verwarf die Sperre drei Fenster:
    #
    #     F73574  51 Frames  -> Protokoll: Wurf 22, 2 Kegel
    #     F74452  46 Frames  -> Protokoll: Wurf 24, 2 Kegel
    #     F76247  44 Frames  -> Protokoll: Wurf 27, 7 Kegel
    #
    # Alle drei sind echt. Zusammen mit dem am Videoende verlorenen Wurf 30
    # ergaben sie genau die 18 Kegel, die dem Satz fehlten.
    #
    # Damit ueberlappen die Bereiche: echtes Fenster ab 44 Frames, der
    # Fehlausloeser aus BUG-013 war 64 Frames lang. Eine Schwelle auf der
    # FENSTERLAENGE kann beides grundsaetzlich nicht trennen. Gegen BUG-013
    # wirkt `detection.green.adaptive_min_span` -- dort liegt die Ursache
    # (Rauschen, das von mitlaufenden Schwellen zerschnitten wird), und dort
    # gehoert die Abhilfe hin.
    #
    # Der Parameter bleibt bestehen, wirkt aber NUR zusammen mit
    # `sampling.report_after_green_off = 0` (Meldung erst beim naechsten
    # GREEN_ON). Bei frueher Meldung ist der Wurf bereits heraus, bevor
    # feststeht, wie lang die Pause war.
    min_throw_frames: int = Field(default=0, ge=0)


class ScoringConfig(BaseModel):
    throws_per_cycle: int = Field(default=15, ge=1)
    # ENTFERNT: `throws_per_game`. Der Wert stand auf 30 und wurde NIRGENDS
    # im Code verwendet -- ein toter Parameter, der genau die falsche Annahme
    # nahelegt. Ein Lauf endet NICHT nach einer festen Zahl von Wuerfen,
    # sondern erst, wenn die Anlage zuruecksetzt (`000  0000`). Beim Training
    # kann jemand 35 Wuerfe machen; die Zaehlung folgt der Anlage, nicht einer
    # Erwartung. Vom Nutzer klargestellt (2026-08-28).
    # Ab welcher gelesenen Wurfnummer aufwaerts ein Rueckfall als SPIELWECHSEL
    # gilt statt als Lesefehler. Zwei Bahnen sprangen im Abstand von zwei
    # Sekunden gemeinsam von 33 auf 4 -- zwei unabhaengige Lesefehler treffen
    # nicht gleichzeitig denselben Wert.
    game_reset_below: int = Field(default=5, ge=1)
    game_reset_after: int = Field(default=10, ge=1)
    # Zweites, unabhaengiges Zeichen fuer den Spielwechsel: Die untere Reihe
    # steht auf `000  0000`. GEMESSEN am 52-Minuten-Video (siehe
    # tools/measure_display_reset.py): 20 bis 90 Sekunden Standzeit an jeder
    # Satzgrenze, kein einziger Treffer in 3000 Kontrollframes mitten im Satz.
    game_reset_by_zero_display: bool = True
    # Ein Wurf, bei dem die Tafel die Summe 0 zeigt, beginnt ein neues Spiel.
    #
    # Die Tafel traegt verspaetet nach: Zum Meldezeitpunkt steht dort der Stand
    # VOR diesem Wurf. Eine Null heisst also, dass die Anlage vor ihm
    # zurueckgesetzt hat -- unabhaengig von der Wurfnummer.
    #
    # Gebraucht wird das, weil die beiden anderen Wege BEIDE an der Wurfnummer
    # haengen und auf einer Bahn mit schlecht lesbarem Nummernfeld gemeinsam
    # versagen (BUG-029, Bahn 5).
    #
    # GEMESSEN am Stream vom 2026-09-17, 315 Wuerfe: 12 Wuerfe mit Summe 0,
    # davon 11 der erste Wurf ihres Spiels -- der zwoelfte war der Fehlerfall.
    # Kein einziger Wurf mitten im Spiel zeigte eine Null.
    game_reset_by_zero_total: bool = True
    # Wie viele Messungen (alle late_read_interval Frames) den Nullzustand
    # zeigen muessen. Bei 20 s kuerzester Standzeit und Messung alle 5 Frames
    # sind rund 100 Messungen zu erwarten -- 3 ist reichlich vorsichtig und
    # schliesst einen einzelnen Lesefehler dennoch aus.
    game_reset_min_frames: int = Field(default=3, ge=1)
    game_reset_total_field: str = "total_b"
    game_reset_number_field: str = "throw_number"
    # Nur die Wurfnummer als Zeugen fuer den Spielwechsel nehmen, ohne die
    # Summe. Begruendung und Messbeleg stehen in `config/default.yaml`.
    game_reset_number_only: bool = False
    # Takt der Nullzustands-Pruefung, in Frames. UNABHAENGIG vom Wurffenster.
    #
    # GEMESSEN 2026-08-30, warum die Bindung ans Fenster nicht traegt: Die
    # spaeten Felder wurden nur zwischen GREEN_OFF und dem naechsten GREEN_ON
    # gelesen. Ob der Spielwechsel erkannt wurde, hing damit daran, ob die
    # Anlage die Anzeige zufaellig waehrend einer Gruenpause zuruecksetzte.
    #
    #     Bahn 2:  000/0000 stand F127115-F128475 (54 s)
    #              Fenster war offen bis F127177 -- 62 Frames. NICHT erkannt.
    #     Bahn 3:  000/0000 stand F126680-F128715 (81 s)
    #              Fenster war offen bis F126964 -- 284 Frames. Erkannt.
    #
    # Der Nullzustand steht gemessen 40 bis 91 Sekunden. Ein eigener Takt von
    # 25 Frames (1 s) trifft ihn damit vielfach. Die Pruefung ist billig: Sie
    # liest zuerst die Summe und die Wurfnummer nur dann, wenn die Summe null
    # zeigt -- im laufenden Spiel also fast nie.
    game_reset_check_interval: int = Field(default=25, ge=0)
    # So viele Messungen IN FOLGE muessen etwas anderes als null zeigen, bevor
    # der Nullzustand als verlassen gilt und ein neuer Spielwechsel gemeldet
    # werden darf.
    #
    # GEMESSEN 2026-08-30 im Abschnitt F164535-F166780, Takt 25 Frames -- die
    # laengste Straehne von Nicht-Null-Messungen INNERHALB des Nullzustands:
    #     Bahn 2   17 Straehnen, laengste 3
    #     Bahn 3    0 Straehnen
    #     Bahn 4    4 Straehnen, laengste 6
    #     Bahn 5    0 Straehnen
    #
    # Mit 3 meldete Bahn 4 denselben Wechsel dreimal. 10 laesst vier Messungen
    # Luft ueber das gemessene Maximum. Teuer ist das nicht: 10 Messungen sind
    # 10 Sekunden, und das naechste Spiel beginnt nie so schnell.
    game_reset_leave_frames: int = Field(default=10, ge=1)
    # So viele Wuerfe muessen zwischen zwei Spielwechseln liegen. Ein Spiel hat
    # 30 Wuerfe -- zwei Spielenden im Abstand von einem Wurf gibt es nicht.
    #
    # WARUM DAS NOETIG IST: Es gibt ZWEI Zeugen fuer denselben Wechsel, und
    # beide sind gewollt -- der Nullzustand der Anzeige und der Rueckfall der
    # Wurfnummer. Sie treffen aber nicht gleichzeitig ein: Der Nullzustand wird
    # bewusst um bis zu zwei Wuerfe weitergereicht (`_reset_weiterreichen`),
    # weil er im Fenster des VORIGEN Wurfs gesehen wird. Der Rueckfall der
    # Wurfnummer greift dagegen sofort.
    #
    # GEMESSEN ueber den vollen Spieltag 2026-08-29, Wuerfe je erkanntem Spiel:
    #     Bahn 2   25 Spiele: 1,1,1,1,1,1,1,1, 19,19,19, 29x5, 30x6, 32
    #     Bahn 3   16 Spiele: 1, 19,20,21, 29, 30x11
    #     Bahn 5   20 Spiele: 1,2, 20,21,21,28, 30x8, 31x3
    # Die Ein- und Zwei-Wurf-Spiele sind ausnahmslos dieses Muster: Der erste
    # Wurf des neuen Spiels landet allein in einem eigenen Spiel, weil der
    # zweite Zeuge einen Wurf spaeter noch einmal einen Wechsel meldet.
    #
    # 5 ist gross genug fuer die gemessene Verzoegerung (hoechstens zwei
    # Wuerfe) und klein genug, dass echte kurze Saetze (19, 20, 21 Wuerfe)
    # unangetastet bleiben.
    game_reset_min_gap_throws: int = Field(default=5, ge=0)
    # Wuerfe ohne Kegel ueber den Fehlwurfzaehler melden (Q10). Sie sind sonst
    # unsichtbar: Faellt kein Kegel, schaltet die Anlage die gruene Lampe nicht
    # aus. Setzt voraus, dass `left_display` stellenweise kalibriert ist --
    # sonst passiert schlicht nichts.
    detect_zero_throws: bool = True
    # Gruenzyklen verwerfen, bei denen die Kegelraute am Ende genau dasselbe
    # zeigt wie am Anfang. Dann ist nichts gefallen -- und ein Wurf ohne Kegel
    # erzeugt gar keinen Zyklus (Q10), er kommt ueber den Fehlwurfzaehler.
    # GEMESSEN: Genau einer von 479 Zyklen, und genau der war keiner.
    discard_unchanged_cycles: bool = True
    discard_static_zero_cycles: bool = True
    # Null Kegel braucht die Tafelziffer 0 als Zeugen. Begruendung und
    # Messbeleg stehen im `ThrowAnalyzer` und in `config/default.yaml`.
    discard_zero_without_digit: bool = True
    # Wurfnummer 000 -- die Anlage zaehlt vor dem sichtbaren Einschlag hoch,
    # also gab es bei 000 keinen Wurf. Staerker als `discard_zero_without_digit`:
    # greift unabhaengig von Kegelzahl und Spielwechsel-Erkennung, allein an
    # der Wurfnummer selbst. Siehe `ThrowAnalyzer.analyze`.
    discard_zero_throw_number: bool = True
    # BUG-020: Ab wann gilt die WURFNUMMER als "die Frames sind sich einig"?
    # Das ist bewusst eine ANDERE Groesse als `throw_number_min_confidence`:
    # jene misst, wie gut eine Ziffer auf einem Bild zu erkennen war, diese
    # nur, ob die Frames dasselbe gesehen haben. Bei schwach lesbarer Anzeige
    # ist die zweite das einzig Belastbare.
    throw_number_min_agreement: float = Field(default=0.9, ge=0.0, le=1.0)
    # So viele FUEHRENDE Stellen der Wurfnummer bleiben bei der Einigkeit
    # unbewertet. 1, weil ein Spiel 30 Wuerfe hat -- eine Hunderterstelle gibt
    # es fachlich nicht (Nutzerangabe 2026-09-04). Sie steht dauerhaft auf
    # einer dunklen Null und wird chronisch schwach gelesen.
    throw_number_ignore_leading: int = Field(default=1, ge=0)
    # Q16: Die 9 wird an der Einerstelle in 25 % der Faelle als 0 gelesen --
    # systematisch, mit voller zeitlicher Einigkeit. Eine gelesene 0 allein
    # darf deshalb keinen Wurf verwerfen. Verlangt zusaetzlich, dass die SUMME
    # null zeigt: Beim Spielwechsel stehen beide Felder auf null ("000 0000"),
    # ein echter Wurf hat dagegen eine Summe > 0. Zwei unabhaengige Felder
    # muessten gleichzeitig falsch gelesen werden.
    discard_zero_requires_zero_total: bool = True
    # BUG-032: Die zwei Felder oben sind getrennt gelesen und trotzdem NICHT
    # unabhaengig -- beim ERSTEN Wurf eines Spiels stehen beide legitim auf
    # null, solange die Anlage den Wurf noch nicht gebucht hat (dieselbe
    # Verspaetung wie BUG-010). Sie schweigen also aus demselben Grund.
    #
    # Der dritte Zeuge haengt an keinem Ziffernfeld: Liegen am Ende des
    # Zyklus Kegel, ist etwas umgefallen -- was auch immer die Anzeige zeigt.
    #
    # GEMESSEN am Spieltagslauf 2026-09-18, alle 18 Verwerfungen dieser Regel
    # gegen die Lampenspur:
    #     17 x  nichts gefallen (max 0 liegende Kegel)  -- zu Recht verworfen
    #      1 x  sechs Kegel gefallen (Bahn 5, F71033)   -- verlorener Wurf
    # Die Lampen trennen die Faelle vollstaendig; die Bedingung aendert genau
    # eine von achtzehn Entscheidungen, und zwar die falsche.
    discard_zero_requires_empty_diamond: bool = True
    # BUG-017: Ein Gruenzyklus, der irgendwann zwischen GREEN_OFF und
    # GREEN_ON von einer erkannten Tafel-Verdeckung durchlaufen wurde, darf
    # als Ergebnis "0 Kegel" keine Messung sein -- die Kamera hat schlicht
    # nichts gesehen. Begruendung und Messbeleg in `ThrowAnalyzer.analyze`.
    discard_occluded_zero_throws: bool = True
    # Ein Gruenzyklus, bei dem die WURFNUMMER DER TAFEL sich nicht geruehrt
    # hat, ist kein Wurf -- unabhaengig davon, wie viele Kegel die Lampen
    # zeigen.
    #
    # WARUM STAERKER ALS `discard_static_zero_cycles`: Jene Regel verlangt
    # zusaetzlich 0 Kegel. GEMESSEN am 2026-08-31 auf dem zweiten Spieltag
    # (Bahn 3, Satz mit Sollsumme 218):
    #
    #     Wurf 17  F247487   3 Kegel   Tafel: 3,  Wurfnummer 17
    #     Wurf 18  F247898   1 Kegel   Tafel: unlesbar, Wurfnummer BLEIBT 17
    #     Wurf 19  F248578   1 Kegel   Tafel: 1,  Wurfnummer 18
    #
    # Der eingeschobene Wurf zeigte EINEN Kegel, nicht null -- die alte Regel
    # konnte ihn nicht fassen. Ab da lief unsere Zaehlung eins vor der Tafel,
    # und der Satz kam auf 219 Kegel in 31 Wuerfen statt 218 in 30.
    #
    # Die Anlage zaehlt ihre Wuerfe selbst. Ruehrt sich ihr Zaehler nicht, hat
    # kein Wurf stattgefunden -- was auch immer die Lampen anzeigen.
    #
    # DIE SPERRE BLEIBT: Ist die Wurfnummer nicht LESBAR, wird nichts
    # verworfen. Der Gruenzyklus ist ein Beweis, dass die Anlage etwas getan
    # hat, und eine ausgefallene Ziffernlesung darf diesen Beweis nicht
    # aufheben -- das ist BUG-008, wo Verwerfen bei unsicherer Lesung 28 % der
    # Wuerfe kostete.
    discard_cycles_without_throw_number: bool = True
    # So sicher muss die Wurfnummer gelesen sein, damit ihr Stillstand einen
    # Wurf verwerfen darf.
    #
    # DAS IST DER GANZE UNTERSCHIED ZU BUG-008. Dort wurde bei nicht steigender
    # Wurfnummer verworfen, und das kostete 20 von 71 Wuerfen (28 %) -- weil
    # die Nummer FEHLGELESEN war. Eine Fehllesung flackert; sie einigt sich
    # ueber die abgetasteten Frames nicht.
    #
    # GEMESSEN am 2026-08-31, zweiter Spieltag, Bahn 3, ueber 120 Frames je
    # Wurf, alle zehn Frames abgetastet:
    #
    #     Wurf 17  echt      Tafel  17 17 17 17 17 17 17 17 17 17 17 17
    #     Wurf 18  PHANTOM   Tafel  17 17 17 17 17 17 17 17 17 17 17 17
    #     Wurf 19  echt      Tafel  18 18 18 18 18 18 18 18 18 18 18 18
    #
    # Der Stillstand beim Phantomwurf ist felsenfest, nicht wackelig. Genau
    # diese Einigkeit verlangt die Schwelle -- und nur die Pipeline kann sie
    # liefern, weil sie ueber alle Frames des Ereignisses abstimmt.
    throw_number_min_confidence: float = Field(default=0.9, ge=0.0, le=1.0)
    pin_count: int = Field(default=9, ge=1)
    mismatch_confidence_penalty: float = Field(default=0.4, ge=0.0, le=1.0)
    check_running_total: bool = True
    # Die Summenanzeige hinkt einen Wurf hinterher: Die Anlage traegt das
    # Ergebnis erst kurz vor dem naechsten GREEN_ON ein (BUG-010), der Wurf
    # wird aber schon 1,6 s nach GREEN_OFF gemeldet
    # (`sampling.report_after_green_off`).
    #
    # GEMESSEN ueber einen ganzen Lauf: 294-mal stand dort die vorherige
    # Summe, 4-mal die aktuelle. Gegen die aktuelle geprueft schlaegt die
    # Gegenprobe deshalb fast immer fehl.
    #
    # Auf false setzen, wenn wieder erst beim naechsten GREEN_ON gemeldet wird
    # (`report_after_green_off: 0`).
    displayed_total_lags: bool = True
    # Summe A und B sind beide Summen, aber nicht zwangslaeufig gleich (Q3)
    check_total_a_vs_b: bool = False
    # Linkes Display zaehlt Fehlwuerfe -- unabhaengige Gegenprobe (Q2)
    check_foul_count: bool = True
    # Groesster plausibler Sprung der Wurfnummer zwischen zwei erkannten Wuerfen.
    # Darueber gilt die Ziffer als falsch gelesen und wird verworfen.
    max_throw_number_jump: int = Field(default=5, ge=1)


class DebugConfig(BaseModel):
    directory: str = "debug"
    save_frames: bool = True
    save_failed_frames: bool = True
    save_roi_crops: bool = True
    # Vollframes (1920x1080) zusaetzlich speichern. Standard aus: Ein PNG davon
    # belegt 2,8 MB, bei vier Frames je Wurf und hunderten Wuerfen sind das
    # mehrere Gigabyte. Der Tafelausschnitt enthaelt alles Auswertbare.
    save_full_frames: bool = False
    # Auch die ZIFFERN-ROIs als Ausschnitte ablegen. Standard AUS, weil es die
    # Dateizahl je Ereignis rund verdreifacht (10 Lampen -> ~25 Felder).
    #
    # WARUM ES DEN SCHALTER GIBT (2026-09-04): Bei jedem Streit ueber eine
    # Ziffer -- BUG-009, die fuenf Ziffer-Abweichungen, der Warmwerf-
    # Sperrzyklus (BUG-018) -- lag GENAU das Bildmaterial nicht vor, das die
    # Frage haette beantworten koennen. Gespeichert wurden nur Gruenlampe und
    # Kegellampen. Wer eine Ziffernfrage untersucht, schaltet das hier ein.
    save_digit_rois: bool = False
    # GEGENPROBE: Lampen gegen Kegelziffer gegen Summendifferenz, Wurf fuer
    # Wurf mitgeschrieben (siehe `analysis/gegenprobe.py`). Sie korrigiert
    # NICHTS -- sie zaehlt aus, wer wem widerspricht. Kostet je Wurf ein paar
    # Vergleiche, also nichts.
    gegenprobe: bool = True
    max_events_per_lane: int = Field(default=200, ge=0)
    jpeg_quality: int = Field(default=92, ge=1, le=100)
    event_log: bool = True
    # Messwert der GRUENEN LAMPE fuer JEDEN Frame mitschreiben.
    #
    # Die Lampe steuert die Wurferkennung -- geht dort etwas schief, liegt die
    # Ursache in den Frames VOR dem Ereignis. Genau die speichert der
    # Bilder-Mitschnitt nicht: Er beginnt beim Ausloeser. Ohne diese Spur
    # laesst sich "warum hat er hier ausgeloest?" nicht beantworten.
    #
    # Kosten: eine CSV-Zeile je Frame und Bahn, rund 20 Byte. Bei 52 Minuten
    # und vier Bahnen sind das etwa 6 MB -- gegenueber den Bildern nichts.
    green_trace: bool = True
    # Messwerte der NEUN KEGELLAMPEN mitschreiben -- samt der Schwellen, gegen
    # die gemessen wurde.
    #
    # WARUM: Fuer die gruene Lampe gibt es die Spur seit langem, und nur dank
    # ihr liess sich der Phantomwurf vom 2026-08-30 aufklaeren -- derselbe
    # Score bedeutete einmal AUS und drei Frames spaeter AN, weil die Schwelle
    # gewandert war. Fuer die Kegellampen fehlte dieses Gegenstueck; ihr
    # Verfahren (Grundlinie je Lampe aus 400 Messungen) ist seit der
    # Einfuehrung nicht mehr am Material nachgeprueft worden.
    lamp_trace: bool = True
    # Eigener, groeberer Takt als der Lesetakt der Lampen (5 Frames): Bei neun
    # Lampen auf vier Bahnen entstuenden sonst ueber zwei Millionen Zeilen.
    # 25 Frames sind eine Sekunde -- fein genug, denn die Grundlinie laeuft
    # ueber 400 Messungen und bewegt sich ohnehin nur langsam.
    lamp_trace_interval: int = Field(default=25, ge=1)

    # Jeder erkannte Wurf sofort als CSV-Zeile in `wuerfe.csv` des Laufordners.
    #
    # Vorher schrieb ein Lauf nur die Gruenspur und die Ereignisbilder -- die
    # Wurfergebnisse gab es ausschliesslich ueber die Werkzeuge, also erst in
    # einem ZWEITEN Durchlauf. An einem Spieltag laeuft die Analyse aber genau
    # einmal, live.
    #
    # Wird zeilenweise geschrieben und sofort geleert: Bricht der Lauf ab,
    # steht alles bis zum letzten Wurf trotzdem in der Datei.
    throw_log: bool = True
    # Je Wurf ein Belegbild (Tafel + Rahmen + gemessene Werte). Begruendung und
    # Speicherbedarf stehen in `config/default.yaml`.
    throw_sheet: bool = False
    throw_sheet_scale: int = Field(default=2, ge=1, le=6)
    throw_sheet_quality: int = Field(default=85, ge=40, le=100)
    throw_sheet_only_flagged: bool = False

    # Je Bahn ein Blatt: Wuerfe in den Zeilen, Laeufe in den Spalten
    # (bahn{N}_laeufe.csv im Laufordner). Ein LAUF ist der Abschnitt zwischen
    # zwei Ruecksetzungen der Anlage -- sie zeigt dabei `000  0000`.
    #
    # Vom Nutzer fuer den Spieltag gewuenscht: Die Tabelle entspricht dem
    # Spielberichtsbogen und laesst sich unmittelbar danebenlegen.
    cycle_sheets: bool = True


class LoggingConfig(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    file: str = "debug/kegel_cv.log"
    console: bool = True
    max_file_mb: int = Field(default=50, ge=1)
    backup_count: int = Field(default=3, ge=0)


class GuiConfig(BaseModel):
    window_width: int = Field(default=1600, ge=800)
    window_height: int = Field(default=1000, ge=600)
    show_debug_overlay: bool = True
    show_roi_labels: bool = True
    debug_panel_max_lines: int = Field(default=500, ge=10)


class JsonlSinkConfig(BaseModel):
    enabled: bool = True
    path: str = "debug/throws.jsonl"


class SinksConfig(BaseModel):
    jsonl: JsonlSinkConfig = Field(default_factory=JsonlSinkConfig)


class SupabaseConfig(BaseModel):
    """Versand der Wurfergebnisse an eine Supabase-Tabelle."""

    enabled: bool = False
    # DIE ADRESSE STEHT IN EINER UMGEBUNGSVARIABLEN, nicht hier -- aus
    # demselben Grund wie der Schluessel, nur eine Stufe schwaecher: Sie ist
    # kein Geheimnis, aber sie benennt die Datenbank EINES BESTIMMTEN Vereins.
    # In einem oeffentlichen Repository ist das eine Einladung zum
    # Ausprobieren, und fuer jeden anderen Nutzer ist sie schlicht falsch.
    #
    # Leer heisst "nicht eingerichtet": Dann wird nicht versendet, und die
    # Analyse laeuft trotzdem (P8).
    url: str = ""                       # z. B. https://abcdefgh.supabase.co
    url_env: str = "SUPABASE_URL"
    table: str = "throws"
    # Spalte fuer den SPIELNAMEN, den der Nutzer vergibt.
    #
    # Sie steht NEBEN `video_id`, nicht an deren Stelle: `video_id` benennt die
    # Quelle (welcher Sensor hat geliefert), `game_name` die Partie (was
    # gehoert zusammen). Im Multisensor-Aufbau -- Stream fuer zwei Bahnen,
    # Telefon fuer die anderen zwei -- ist genau diese Trennung der Punkt:
    # Beide Geraete schreiben denselben Spielnamen, bleiben aber
    # unterscheidbar, wenn eine Bahn auffaellig wird.
    #
    # Die Spalte muss in der Tabelle existieren:
    #     alter table throws add column game_name text;
    # Fehlt sie, lehnt PostgREST die ganze Zeile ab. Der Versand meldet das
    # einmal im Klartext, statt stumm nichts zu schreiben.
    game_name_column: str = "game_name"
    # Der Schluessel steht in einer UMGEBUNGSVARIABLEN, nicht hier.
    # Konfigurationsdateien landen in der Versionsverwaltung, Zugangsdaten nie.
    api_key_env: str = "SUPABASE_KEY"
    timeout_s: float = Field(default=5.0, gt=0)
    max_retries: int = Field(default=3, ge=1)
    retry_delay_s: float = Field(default=2.0, ge=0)
    # Warteschlange zwischen Analyse und Versand. 500 Wuerfe sind mehr als ein
    # ganzes Training -- die Analyse haengt also selbst bei totem Netz nie.
    queue_size: int = Field(default=500, ge=1)
    # Was nicht rausgeht, wird hier zwischengespeichert und spaeter nachgeliefert.
    spool_file: str = "debug/versand_puffer.jsonl"


class OutputConfig(BaseModel):
    """Wohin die Ergebnisse gehen (Auftrag Paragraph 26)."""

    supabase: SupabaseConfig = Field(default_factory=SupabaseConfig)

    # WELCHE BAHNEN GESENDET WERDEN -- Bahnnummern wie auf der Anlage.
    #
    # Leer heisst: alle, die erfasst werden. Getrennt von `processing.lanes`,
    # weil beides verschiedene Gruende hat: Erfassen spart Rechenzeit, Senden
    # entscheidet, welches Geraet in einem Multisensor-Aufbau fuer welche Bahn
    # zustaendig ist. Wer eine Bahn mitrechnen, aber nicht senden will -- etwa
    # zum Vergleich zweier Kameras -- stellt sie hier heraus und laesst sie
    # oben drin.
    lanes: list[int] = Field(default_factory=list)

    # Das Tafelbild je Wurf mitschicken -- der Beleg zum Ergebnis.
    #
    # Uebertragen wird NUR die eingemessene Anzeigetafel (`lane_box`), nichts
    # aus der Halle. Als Base64 in derselben Zeile, nicht in einem eigenen
    # Speicher-Dienst: So gilt fuer das Bild dieselbe Warteschlange und
    # dieselbe Nachlieferung wie fuer den Wurf. Ein zweiter Uebertragungsweg
    # haette einen zweiten Fehlermodus -- ausgerechnet dann, wenn das Netz
    # ohnehin wackelt.
    send_board_image: bool = True

    # GEMESSEN am Ausschnitt eines echten Wurfs (152x154 px, Bahn 2, F26984):
    #     Qualitaet 40 -> 4,8 KB      70 ->  6,7 KB
    #     Qualitaet 55 -> 5,5 KB      PNG -> 46,4 KB
    # Bei rund 2000 Wuerfen je Spieltag sind 40 also etwa 9 MB. Der Nutzer hat
    # starke Kompression ausdruecklich zugelassen (2026-09-07); gelesen wird
    # die Tafel auf dem Bild von einem Menschen, nicht von einem Detektor.
    board_image_quality: int = Field(default=40, ge=1, le=100)

    # Wie viele Frames nach der Freigabe (GREEN_ON) das "davor"-Bild noch
    # nachgefuehrt wird. 25 Frames sind bei 25 fps eine Sekunde -- lang genug,
    # dass die Anlage die Aufstellung gesetzt hat, kurz genug, dass niemand in
    # dieser Zeit schon geworfen hat (ein Wurfzyklus dauert gemessen 216 bis
    # 338 Frames).
    #
    # ANLASS: Der erste Versuch schrieb bis zum naechsten GREEN_OFF mit und
    # lieferte damit ein Bild, auf dem das Ergebnis schon stand -- GREEN_OFF
    # ist das Sperren NACH dem Wurf.
    # Das "davor"-Bild mitschicken -- die Tafel in dem Frame, in dem die
    # GRUENE LAMPE ANGEHT. Das ist die Aufstellung, auf die geworfen wird.
    #
    # Zwei fruehere Anlaeufe (letzter Frame vor GREEN_OFF; Nachlauf nach
    # GREEN_ON) lieferten beide ein Bild, auf dem das Ergebnis SCHON STAND.
    # Der Nutzer hat den Zeitpunkt daraufhin festgelegt: genau der
    # Freigabe-Frame, ohne Nachlauf und ohne Mitschreiben.
    send_board_before_image: bool = True


class AppConfig(BaseModel):
    """Wurzel der Konfiguration."""

    video: VideoConfig = Field(default_factory=VideoConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    calibration: CalibrationConfig = Field(default_factory=CalibrationConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    state_machine: StateMachineConfig = Field(default_factory=StateMachineConfig)
    scoring: ScoringConfig = Field(default_factory=ScoringConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    gui: GuiConfig = Field(default_factory=GuiConfig)
    sinks: SinksConfig = Field(default_factory=SinksConfig)

    # Wird beim Laden gesetzt, damit relative Pfade aufloesbar bleiben,
    # egal aus welchem Arbeitsverzeichnis die Anwendung gestartet wurde.
    project_root: Path = Field(default_factory=Path.cwd, exclude=True)
    # Woher diese Konfiguration stammt. Gebraucht, um sie NACH dem
    # Aufsetzen des Logging melden zu koennen: `load_config` laeuft
    # davor, und eine Meldung von dort landet nirgends (2026-09-08).
    config_path: Path | None = Field(default=None, exclude=True)

    def resolve(self, relative: str) -> Path:
        """Loest einen konfigurierten relativen Pfad gegen die Projektwurzel auf."""
        p = Path(relative)
        return p if p.is_absolute() else self.project_root / p
