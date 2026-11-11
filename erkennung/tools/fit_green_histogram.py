"""Misst eine Schwelle aus dem gleitenden Histogramm -- gegen die Gruenspur.

WOZU -- gemessen am 2026-08-30 auf Bahn 5, Frame 40894 bis 40914:

        Frame   Score    P20    P90  Spanne  AUS-Schwelle  Zustand
        40903    47,8   40,0   70,0    30,0          52,0  OFF
        40906    47,8   41,8   70,0    28,2  fest: 35,0    ON

    DERSELBE Score, zwei verschiedene Zustaende. Der Grund ist nicht das
    Signal: Die Spanne P90-P20 wackelte um die Sperre `adaptive_min_span`
    (30,0) herum, und damit sprang die Schwelle zwischen 52,0 und 35,0.
    Der so entstandene GREEN_OFF erzeugte den Phantomwurf 17, und der
    verschob die ganze folgende Wurfnummernkette (siehe docs/AGENDA.md, A1).

    Die Ursache liegt in den PERZENTILEN: Sie setzen voraus, dass beide
    Zustaende im Fenster vorkommen. Lag die Bahn 71 % der letzten 60 s auf
    AN, dann ist P20 kein AUS-Niveau, sondern nur der untere Rand der
    AN-Wolke -- und die daraus errechnete AUS-Schwelle (52,0) liegt MITTEN
    in der AN-Wolke.

    Das Histogramm desselben Fensters ist dagegen eindeutig zweigipflig:

        18-26   233 Werte   AUS-Wolke, Gipfel bei 24-26
        26-52   ~250        duenn verteilt -- die Flanken
        52-78  ~1069        AN-Wolke, Gipfel bei 56-58

    Der Vorschlag des Nutzers (2026-08-30): ueber ein gleitendes Fenster ein
    Histogramm fuehren und die Schwelle in das Tal zwischen den beiden Wolken
    legen. UNVERHANDELBAR dabei: Gibt es nur EINE Wolke, wird keine Schwelle
    gerechnet und die zuletzt sichere behalten -- sonst passiert genau das,
    was BUG-013 schon einmal anrichtete (kuenstliches AUS innerhalb von AN,
    aus einem Wurf wurden zwei).

Dieses Werkzeug entscheidet nichts. Es spielt die aufgezeichnete Gruenspur
durch das vorgeschlagene Verfahren und zeigt, was dabei herauskaeme --
Zahl der Wurfzyklen je Bahn, Anteil zweigipfliger Fenster, Verlauf der
Schwelle. Erst wenn das trägt, gehoert es in `HsvGreenDetector`.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


class GleitendesHistogramm:
    """Rollendes Histogramm mit Talsuche zwischen zwei Wolken."""

    def __init__(self, fenster: int, bin_breite: float, glaettung: int,
                 min_wolke: float, min_abstand: float, max_tal: float,
                 hysterese: float, takt: int,
                 fest_an: float, fest_aus: float) -> None:
        self.fenster = fenster
        self.bin_breite = bin_breite
        self.glaettung = glaettung
        self.min_wolke = min_wolke
        self.min_abstand = min_abstand
        self.max_tal = max_tal
        self.hysterese = hysterese
        self.takt = takt
        self.fest = (fest_an, fest_aus)

        self.anzahl_bins = int(100.0 / bin_breite) + 1
        self._bins = np.zeros(self.anzahl_bins, dtype=np.int32)
        self._werte: deque[int] = deque()
        self._schwellen = (fest_an, fest_aus)
        self._aus_messung = False   # stammt die Schwelle aus einem Histogramm?
        self._seit_takt = 0
        # Buchhaltung fuer den Bericht
        self.zweigipflig = 0
        self.eingipflig = 0

    def _index(self, wert: float) -> int:
        return min(self.anzahl_bins - 1, max(0, int(wert / self.bin_breite)))

    def hinzufuegen(self, wert: float) -> None:
        i = self._index(wert)
        self._werte.append(i)
        self._bins[i] += 1
        while len(self._werte) > self.fenster:
            self._bins[self._werte.popleft()] -= 1

    def _tal_suchen(self) -> tuple[float, float] | None:
        """Tal zwischen den zwei groessten Gipfeln -- oder None bei einer Wolke."""
        gesamt = int(self._bins.sum())
        if gesamt < self.fenster // 4:
            return None

        # Glaetten: Einzelne leere Bins sind Rauschen, keine Taeler.
        kern = np.ones(self.glaettung, dtype=np.float32) / self.glaettung
        h = np.convolve(self._bins.astype(np.float32), kern, mode="same")

        hoechster = int(np.argmax(h))
        # Zweiter Gipfel: hoechster Bin, der weit genug vom ersten weg liegt.
        mindest_bins = int(self.min_abstand / self.bin_breite)
        maske = np.abs(np.arange(self.anzahl_bins) - hoechster) >= mindest_bins
        if not maske.any() or h[maske].max() <= 0:
            return None
        zweiter = int(np.flatnonzero(maske)[int(np.argmax(h[maske]))])

        links, rechts = sorted((hoechster, zweiter))
        tal_bereich = h[links:rechts + 1]
        if tal_bereich.size < 3:
            return None
        tal = links + int(np.argmin(tal_bereich[1:-1])) + 1

        # ZWEI Wolken -- oder nur eine mit einer Delle?
        #
        # Drei Bedingungen, alle drei noetig:
        #   1. Beide Wolken muessen nennenswert besetzt sein. Ein Gipfel aus
        #      fuenf Frames ist kein Zustand, sondern eine Flanke.
        #   2. Das Tal muss deutlich tiefer sein als der KLEINERE Gipfel.
        #      Sonst ist es keine Trennung, sondern eine Schwankung.
        #   3. Der Abstand der Gipfel ist schon durch `min_abstand` gesichert.
        unten = int(self._bins[:tal].sum())
        oben = int(self._bins[tal:].sum())
        if min(unten, oben) < self.min_wolke * gesamt:
            return None
        kleinerer = min(h[links], h[rechts])
        if kleinerer <= 0 or h[tal] > self.max_tal * kleinerer:
            return None

        tal_wert = (tal + 0.5) * self.bin_breite
        abstand = (rechts - links) * self.bin_breite
        rand = self.hysterese * abstand
        return (tal_wert + rand, tal_wert - rand)

    def schwellen(self) -> tuple[float, float]:
        """Aktuelle (AN, AUS) -- nur alle `takt` Frames neu gerechnet."""
        self._seit_takt += 1
        if self._seit_takt < self.takt:
            return self._schwellen
        self._seit_takt = 0

        neu = self._tal_suchen()
        if neu is None:
            self.eingipflig += 1
            # SPERRE: keine Rueckschluesse aus einer Wolke. Die zuletzt
            # gemessene Schwelle bleibt stehen; gab es noch keine, gilt die
            # feste aus der Konfiguration.
            return self._schwellen
        self.zweigipflig += 1
        self._schwellen = neu
        self._aus_messung = True
        return neu


def zustaende(scores: list[tuple[int, float]], h: GleitendesHistogramm,
              occlusion: float, stabil: int) -> list[tuple[int, str]]:
    """Spielt die Spur durch und gibt die Zustandswechsel zurueck."""
    zustand = "UNKNOWN"
    kandidat, zaehler = "UNKNOWN", 0
    wechsel: list[tuple[int, str]] = []
    for frame, wert in scores:
        if wert <= occlusion:
            # Verdeckte Tafel: Zustand einfrieren UND das Histogramm nicht
            # verfaelschen. Ein Spieler vor der Tafel ist keine AUS-Messung.
            continue
        h.hinzufuegen(wert)
        an, aus = h.schwellen()
        roh = "ON" if wert >= an else ("OFF" if wert <= aus else "UNKNOWN")
        if roh == "UNKNOWN":
            continue
        if roh == kandidat:
            zaehler += 1
        else:
            kandidat, zaehler = roh, 1
        if zaehler >= stabil and roh != zustand:
            zustand = roh
            wechsel.append((frame, roh))
    return wechsel


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--trace", required=True, type=Path,
                   help="gruenspur.csv eines Laufs")
    p.add_argument("--window", type=int, default=22500,
                   help="Fenstergroesse in Frames (22500 = 15 min bei 25 fps)")
    p.add_argument("--bin", type=float, default=2.0)
    p.add_argument("--smooth", type=int, default=3)
    p.add_argument("--min-cloud", type=float, default=0.05)
    p.add_argument("--min-gap", type=float, default=15.0)
    p.add_argument("--max-valley", type=float, default=0.25)
    p.add_argument("--hysteresis", type=float, default=0.10)
    p.add_argument("--interval", type=int, default=25)
    p.add_argument("--occlusion", type=float, default=2.0)
    p.add_argument("--stable", type=int, default=3)
    p.add_argument("--lane", type=int, default=None)
    a = p.parse_args()

    spur: dict[int, list[tuple[int, float]]] = {}
    ist_wechsel: dict[int, int] = {}
    letzter: dict[int, str] = {}
    with a.trace.open(encoding="utf-8-sig", newline="") as d:
        for r in csv.DictReader(d, delimiter=";"):
            bahn = int(r["Bahn"])
            spur.setdefault(bahn, []).append((int(r["Frame"]), float(r["Score"])))
            if r["Zustand"] == "OFF" and letzter.get(bahn) == "ON":
                ist_wechsel[bahn] = ist_wechsel.get(bahn, 0) + 1
            if r["Zustand"] in ("ON", "OFF"):
                letzter[bahn] = r["Zustand"]

    print(f"Fenster {a.window} Frames ({a.window / 25 / 60:.0f} min), "
          f"Bin {a.bin}, Glaettung {a.smooth}, Wolke >= {a.min_cloud:.0%}, "
          f"Gipfelabstand >= {a.min_gap}, Tal <= {a.max_valley:.0%}, "
          f"Hysterese {a.hysteresis:.0%}\n")
    print(f"  {'Bahn':>5} {'GREEN_OFF neu':>14} {'GREEN_OFF Lauf':>15} "
          f"{'zweigipflig':>12} {'gesperrt':>9}")
    for bahn in sorted(spur):
        if a.lane is not None and bahn != a.lane:
            continue
        werte = sorted(spur[bahn])
        h = GleitendesHistogramm(a.window, a.bin, a.smooth, a.min_cloud,
                                 a.min_gap, a.max_valley, a.hysteresis,
                                 a.interval, 45.0, 35.0)
        wechsel = zustaende(werte, h, a.occlusion, a.stable)
        aus = sum(1 for _, z in wechsel if z == "OFF")
        gesamt = h.zweigipflig + h.eingipflig
        anteil = h.zweigipflig / gesamt if gesamt else 0.0
        print(f"  {bahn:>5} {aus:>14} {ist_wechsel.get(bahn, 0):>15} "
              f"{anteil:>11.0%} {h.eingipflig:>9}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
