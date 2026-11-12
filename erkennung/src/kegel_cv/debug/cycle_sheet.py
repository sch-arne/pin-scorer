"""Je Bahn ein Blatt: Wuerfe in den Zeilen, Laeufe in den Spalten.

Vom Nutzer so gewuenscht (2026-08-28): "in den Zeilen Wurf 1 2 3 (bis zur
hoechsten Zahl, die halt mal erreicht wurde) und in den Spalten Lauf 1 2 3".

Ein LAUF ist der Abschnitt zwischen zwei Ruecksetzungen der Anlage. Sie zeigt
dabei `000  0000` in der unteren Reihe und beginnt neu bei Wurf 1 -- gemessen
ueber 52 Minuten dauert das je Lauf 30 Wuerfe, aber darauf verlaesst sich diese
Datei NICHT: Die Zeilenzahl richtet sich nach der hoechsten tatsaechlich
erreichten Wurfnummer.

ACHTUNG, zwei Bedeutungen von "Lauf":
  - hier  ein Durchgang auf einer Bahn (im Code `game_number`)
  - sonst ein Analysedurchlauf (der Ordner `lauf_JJJJ-MM-TT_HH-MM-SS`)
Die Blaetter liegen IM Ordner eines Analysedurchlaufs, deshalb ist aus dem
Zusammenhang klar, was gemeint ist.

Nicht zu verwechseln mit `cycle_number` im Code -- das ist die 15er-Runde
(Volle bzw. Abraeumen), also die HALBE Laenge eines Laufs.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

from ..models.throw import ThrowResult

log = logging.getLogger(__name__)


class CycleSheet:
    """Sammelt Wuerfe und schreibt am Ende je Bahn ein Blatt."""

    def __init__(self, ordner: Path, aktiv: bool = True) -> None:
        self.aktiv = aktiv
        self.ordner = ordner
        # (Bahn, Lauf, Wurfnummer) -> Kegelzahl
        self._werte: dict[tuple[int, int, int], int] = {}

    def add(self, throw: ThrowResult) -> None:
        if not self.aktiv:
            return
        schluessel = (throw.lane, throw.game_number, throw.throw_number)
        # Sollte dieselbe Zelle zweimal kommen, gewinnt die spaetere Buchung --
        # sie ist die, die auch in der Tabelle steht.
        self._werte[schluessel] = throw.pins_count

    def close(self) -> list[Path]:
        """Schreibt je Bahn ein Blatt. Liefert die geschriebenen Pfade."""
        if not self.aktiv or not self._werte:
            return []
        try:
            self.ordner.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("Zyklusblaetter nicht schreibbar: %s", exc)
            return []

        bahnen = sorted({b for b, _, _ in self._werte})
        geschrieben: list[Path] = []

        for bahn in bahnen:
            eigene = {(lauf, wurf): kegel
                      for (b, lauf, wurf), kegel in self._werte.items() if b == bahn}
            if not eigene:
                continue
            laeufe = sorted({lauf for lauf, _ in eigene})
            # Die hoechste TATSAECHLICH erreichte Wurfnummer, nicht 30 --
            # ein abgebrochener oder verlaengerter Durchgang soll nicht
            # stillschweigend abgeschnitten werden.
            hoechster = max(wurf for _, wurf in eigene)

            ziel = self.ordner / f"bahn{bahn}_laeufe.csv"
            try:
                with ziel.open("w", encoding="utf-8-sig", newline="") as datei:
                    schreiber = csv.writer(datei, delimiter=";")
                    schreiber.writerow(["Wurf"] + [f"Lauf {i}" for i in laeufe])
                    for wurf in range(1, hoechster + 1):
                        schreiber.writerow(
                            [wurf] + [eigene.get((lauf, wurf), "") for lauf in laeufe])
                    # Die Summe je Lauf -- das ist die Zahl, die am Ende auf dem
                    # Spielberichtsbogen steht.
                    schreiber.writerow(
                        ["Summe"] + [sum(v for (lauf, _), v in eigene.items()
                                         if lauf == i) for i in laeufe])
                    schreiber.writerow(
                        ["Wuerfe"] + [sum(1 for (lauf, _) in eigene if lauf == i)
                                      for i in laeufe])
                geschrieben.append(ziel)
            except OSError as exc:
                log.warning("Blatt fuer Bahn %d nicht schreibbar: %s", bahn, exc)

        if geschrieben:
            log.info("Zyklusblaetter geschrieben: %d Bahnen in %s",
                     len(geschrieben), self.ordner)
        return geschrieben
