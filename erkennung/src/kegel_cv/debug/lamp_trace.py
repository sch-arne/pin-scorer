"""Schreibt die Messwerte der neun Kegellampen mit -- samt ihrer Schwellen.

WARUM: Fuer die gruene Lampe gibt es die `gruenspur.csv` seit langem, und sie
hat sich bezahlt gemacht: Der Phantomwurf vom 2026-08-30 liess sich nur
aufklaeren, weil dort Score UND Zustand fuer jeden Frame standen. Erst daran
war zu sehen, dass derselbe Score (47,8) einmal AUS und drei Frames spaeter AN
bedeutete -- nicht das Signal hatte sich geaendert, sondern die Schwelle.

Fuer die KEGELLAMPEN fehlt dieses Gegenstueck. Sie arbeiten mit einem ganz
anderen Verfahren: je Lampe ein Gedaechtnis von 400 Messungen, daraus per
Perzentil das AUS-Niveau, und die Schwellen anteilig zwischen diesem Niveau und
der Saettigung (255). Ob dieses Niveau am Material richtig sitzt, ist seit der
Einfuehrung nicht mehr nachgemessen worden.

Der Verdacht, der diese Spur veranlasst hat (2026-08-31): Beim Aufbau eines
beschrifteten Ziffern-Datensatzes stimmten die Frame-fuer-Frame gelesenen
Lampen auf Bahn 5 in 63 % der Faelle nicht mit der Anzeige ueberein -- auf
Bahn 2 und 3 waren es 0 bis 8 %. Das wurde damals der fehlenden zeitlichen
Aggregation zugeschrieben. Das war plausibel, aber nicht belegt; es koennte
ebenso die Grundlinie sein. Ohne Spur ist das nicht zu entscheiden.

MITGESCHRIEBEN WIRD deshalb nicht nur der Messwert, sondern auch, WOGEGEN er
gemessen wurde: Grundlinie, AN-Schwelle, AUS-Schwelle. Genau daran zeigt sich
der Fehler, den die Gruenspur bei der gruenen Lampe sichtbar gemacht hat --
ein wandernder Massstab unter einem ruhigen Signal.

NICHT mitgeschrieben wird die Waerme. Sie dient nur als Plausibilitaetsschranke
gegen helle, aber farblose Reflexe; gemessen ueber 3600 Einzelmessungen trennt
die Helligkeit mehr als doppelt so gut (Guete 7,66 gegen 3,35). Eine Spalte,
die nichts entscheidet, macht die Datei nur breiter.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..models.readings import PinLampReading

log = logging.getLogger(__name__)


class LampTrace:
    """Protokolliert Helligkeit, Zustand und Schwellen je Kegellampe."""

    def __init__(self, ziel: Path, aktiv: bool = True, takt: int = 25) -> None:
        self.aktiv = aktiv
        self.pfad = ziel
        # Eigener, groeberer Takt als der Lesetakt der Lampen (5 Frames): Bei
        # neun Lampen auf vier Bahnen entstuenden sonst ueber zwei Millionen
        # Zeilen. 25 Frames sind eine Sekunde und damit fein genug, um einen
        # wandernden Massstab zu erkennen -- die Grundlinie laeuft ueber 400
        # Messungen, bewegt sich also ohnehin nur langsam.
        self.takt = max(1, takt)
        self._datei = None
        self._zeilen = 0

    def _oeffnen(self) -> None:
        if self._datei is not None or not self.aktiv:
            return
        try:
            self.pfad.parent.mkdir(parents=True, exist_ok=True)
            self._datei = self.pfad.open("w", encoding="utf-8-sig", newline="")
            self._datei.write("Frame;Zeit_s;Bahn;Lampe;Helligkeit;Zustand;"
                              "Grundlinie;AN_Schwelle;AUS_Schwelle;Anlass\n")
        except OSError as exc:
            # Ein Protokollierungsfehler darf die Analyse nicht anhalten.
            log.warning("Lampenspur nicht schreibbar: %s", exc)
            self.aktiv = False

    def add(self, frame_index: int, timestamp: float, lane: int,
            reading: PinLampReading, detector, anlass: str = "live") -> None:
        """Schreibt eine Zeile je Lampe.

        Der eigene, groebere Takt gilt nur fuer die Messungen der ANZEIGE. Alles,
        was in ein Wurfergebnis eingeht -- Grundlinie, Gruenphase, Ergebnis --
        wird IMMER geschrieben.

        WARUM (Spieltag 2026-09-19): Das Wurfergebnis ist die Vereinigung aller
        Messungen eines Zyklus, und genau die der Gruenphase fehlten in der
        Spur. Als ein Wurf mit 9 gebucht wurde, obwohl Tafel und gespeicherte
        Bilder 7 zeigten, liess sich aus der Datei nicht mehr klaeren, woher die
        zwei zusaetzlichen Kegel kamen -- in 622 von 628 Streitfaellen zeigte
        die Spur den gebuchten Stand nie. Eine Spur, die das Entscheidende
        wegwirft, beweist nichts.

        `anlass` haelt fest, wofuer gemessen wurde -- ohne das stuenden Zeilen
        nebeneinander, die ganz verschiedene Rollen haben.
        """
        if not self.aktiv:
            return
        if anlass == "live" and frame_index % self.takt:
            return
        self._oeffnen()
        if self._datei is None:
            return
        try:
            for lampe in reading.lamps:
                an, aus, grundlinie = detector.schwellen_von(lampe.name)
                self._datei.write(
                    f"{frame_index};{timestamp:.2f};{lane};{lampe.name};"
                    f"{lampe.score:.1f};{lampe.state.value};"
                    f"{grundlinie:.1f};{an:.1f};{aus:.1f};{anlass}\n")
                self._zeilen += 1
        except OSError as exc:
            log.warning("Lampenspur abgebrochen: %s", exc)
            self.aktiv = False

    def close(self) -> None:
        if self._datei is not None:
            self._datei.close()
            self._datei = None
            log.info("Lampenspur geschrieben: %s (%d Zeilen)",
                     self.pfad, self._zeilen)
