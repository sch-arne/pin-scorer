"""Ziffernerkennung auf Basis einzeln kalibrierter Stellen.

Der Weg hierher, alles am Material gemessen:

    Segment-Dekodierung, Rot-Maske      0/12
    Segment-Dekodierung, Otsu-Maske     5/12
    Template Matching, Feld geteilt     6/11
    + zeitliche Aggregation             7/12
    + automatisch gemessenes Raster     1/11   (schlechter!)

Alle Varianten scheiterten an derselben Stelle: **der Positionierung der
Ziffernzellen**. Ein Feld in N gleiche Teile zu zerlegen trifft die echten
Ziffergrenzen nicht -- gemessen liegen sie bei x = 5|15|26|38|49, waehrend die
gleichmaessige Teilung 0|13|26|40|53 annimmt. Bei 13x18 px je Ziffer ist das
fast eine halbe Ziffernbreite Versatz.

Dieses Modul dreht den Spiess um: **Der Nutzer rahmt jede Ziffer einzeln ein.**
Damit ist die Position exakt bekannt, und die Segmentflaechen ergeben sich direkt
aus der Ziffernbox -- horizontal gedrittelt, vertikal halbiert:

    +---------+   a = obere Kante          b = rechts oben
    | a  a  a |   g = Mitte                f = links oben
    |f       b|   d = untere Kante         c = rechts unten
    | g  g  g |                            e = links unten
    |e       c|
    | d  d  d |
    +---------+

Der kleine Rand um die Box (`digit_padding`) faengt ab, dass der Nutzer beim
Einrahmen naturgemaess nicht pixelgenau trifft.
"""

from __future__ import annotations

import logging
import math

import cv2
import numpy as np

from ..config.schema import DigitDetectionConfig
from .digit_detector import DigitReading, SevenSegmentDetector

log = logging.getLogger(__name__)

# Bitmuster je Ziffer: (a, b, c, d, e, f, g)
SEGMENT_PATTERNS: dict[tuple[bool, ...], int] = {
    (True, True, True, True, True, True, False): 0,
    (False, True, True, False, False, False, False): 1,
    (True, True, False, True, True, False, True): 2,
    (True, True, True, True, False, False, True): 3,
    (False, True, True, False, False, True, True): 4,
    (True, False, True, True, False, True, True): 5,
    (True, False, True, True, True, True, True): 6,
    (True, True, True, False, False, False, False): 7,
    (True, True, True, True, True, True, True): 8,
    (True, True, True, True, False, True, True): 9,

    # ALTERNATIVE SCHREIBWEISEN dieser Anlage.
    #
    # GESEHEN im Videomaterial (Bahn 5, Frames 4526/4990/9352; Bahn 2, 4990):
    # Die FUNK-Tafel zeichnet die 9 OHNE den unteren Querbalken -- also
    # "abcfg" statt "abcdfg". Das ist keine Fehlmessung, sondern die Bauform
    # der Anzeige; auf dem Standbild ist die Ziffer eindeutig als 9 zu lesen.
    #
    # Was ohne diesen Eintrag geschah: "abcfg" stand in keiner Tabelle, also
    # suchte die Notfallsuche das naechstliegende bekannte Muster. Das ist
    # "bcfg" = 4, genau ein Segment entfernt -- und aus jeder 9 wurde eine 4.
    # Der Fehler war dadurch besonders tueckisch, dass er wie ein
    # Kalibrierungsproblem aussah: Segment d mass 0.00, als laege es
    # ausserhalb des Rahmens. Es leuchtet schlicht nie.
    (True, True, True, False, False, True, True): 9,

    # Aus demselben Grund mitgefuehrt: die 6 ohne oberen Querbalken. Noch
    # NICHT im Material beobachtet -- wer beide Varianten der 9 baut, baut
    # ueblicherweise auch diese. Eindeutig bleibt es: "cdefg" kollidiert mit
    # keinem anderen Muster.
    (False, False, True, True, True, True, True): 6,
}
SEGMENT_ORDER = ("a", "b", "c", "d", "e", "f", "g")

# Zielgroesse einer einzelnen Ziffer fuer die Auswertung
CELL_WIDTH = 24
CELL_HEIGHT = 40


def segment_regions(width: int = CELL_WIDTH,
                    height: int = CELL_HEIGHT,
                    shear: float = 0.0,
                    middle_inset: float = 0.0,
                    ) -> dict[str, tuple[int, int, int, int]]:
    """Segmentflaechen einer exakt eingerahmten Ziffer.

    Die Aufteilung ist rein geometrisch -- moeglich nur, weil die Ziffernbox
    kalibriert ist und nicht geschaetzt werden muss:

        horizontal: Drittel (links | mitte | rechts)
        vertikal:   obere Haelfte | untere Haelfte

    Die Flaechen sind von den Ecken weggerueckt: Dort treffen zwei Segmente
    aufeinander, eine Messung waere mehrdeutig.

    Args:
        shear: Schraeglage der Schrift. Jede Flaeche wird waagerecht
            verschoben, und zwar umso weiter nach rechts, je weiter oben sie
            liegt. Begruendung und Messbeleg stehen bei
            `detection.digits.segment_shear`.
        middle_inset: Wie weit die mittlere Flaeche (g) beidseitig eingezogen
            wird -- siehe `detection.digits.segment_middle_inset`.
    """
    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[int, int, int, int]:
        if shear:
            # Die Verschiebung richtet sich nach der HOEHE der Flaechenmitte:
            # oben am weitesten nach rechts, unten am weitesten nach links.
            # Der Bezugspunkt ist die Zellenmitte, damit die Ziffer als Ganzes
            # an ihrem Platz bleibt und nur gekippt wird.
            versatz = shear * (0.5 - (y0 + y1) / 2.0)
            x0, x1 = x0 + versatz, x1 + versatz
        x0, x1 = max(0.0, min(1.0, x0)), max(0.0, min(1.0, x1))
        px0, py0 = int(x0 * width), int(y0 * height)
        px1, py1 = int(x1 * width), int(y1 * height)
        return px0, py0, max(1, px1 - px0), max(1, py1 - py0)

    # Die WAAGERECHTEN Segmente werden bewusst nur im mittleren Drittel gemessen.
    #
    # GEMESSEN und schmerzhaft gelernt: Eine zu breite Messflaeche fuer "g"
    # erfasst die senkrechten Segmente links (e, f) und rechts (b, c) mit. Jede
    # "0" wurde dadurch als "8" gelesen -- die Trefferquote fiel auf 17 %.
    # Am Rand der Ziffer liegen immer Segmente; nur die Mitte ist eindeutig.
    #
    # NACHTRAG 2026-09-15: Sie war noch nicht schmal genug. Bei schraeger
    # Schrift lehnen die senkrechten Striche in die Mitte hinein, und dieselbe
    # Verwechslung entstand wieder -- nur leiser. GEMESSEN an 1187
    # beschrifteten Bildern hebt ein beidseitiger Einzug die Treffer von
    # 86,8 % auf 87,7 %, auf Bahn 4 und 5 von 66,8 % auf 69,3 %. Der Wert
    # steht in `detection.digits.segment_middle_inset`, die Messtabelle dort.
    #
    # Die SENKRECHTEN Segmente werden am aeusseren Viertel gemessen und von der
    # Mittellinie weggerueckt, wo sie sich mit "g" beruehren wuerden.
    return {
        "a": box(0.30, 0.00, 0.70, 0.16),
        "g": box(0.34 + middle_inset, 0.42, 0.66 - middle_inset, 0.58),
        "d": box(0.30, 0.84, 0.70, 1.00),
        "f": box(0.00, 0.14, 0.26, 0.44),
        "b": box(0.74, 0.14, 1.00, 0.44),
        "e": box(0.00, 0.56, 0.26, 0.86),
        "c": box(0.74, 0.56, 1.00, 0.86),
    }


def segment_candidates(fills: list[float], threshold: float,
                       band: float) -> tuple[int, ...]:
    """Welche Ziffern kommen fuer diese Segmentmessung in Frage?

    Zurueckgegeben wird die direkte Lesung plus alle Ziffern, die sich ergaeben,
    wenn ein Segment NAHE DER SCHWELLE anders ausfiele.

    GEMESSEN auf Bahn 5 ueber zehn aufeinanderfolgende Frames: Segment a lag
    konstant bei 0,333, die Schwelle bei 0,288-0,326. Es galt damit als aktiv,
    und aus "bcfg" (4) wurde "abcfg" (9) -- die Anzeigetafel zeigte im selben
    Frame nachweislich `005 4 0029`.

    Seit BUG-009 stehen beide Muster in der Tabelle und unterscheiden sich in
    genau EINEM Segment. Eine solche Messung KANN aus sich heraus nicht
    entscheiden. Statt zu raten oder zu schweigen, wird die Auswahl
    weitergereicht: Eine andere Quelle -- die Kegellampen -- kann sie aufloesen.

    Dass die Pruefung dabei ehrlich bleibt, liegt an der Richtung: Die Lampen
    duerfen nur zwischen den Kandidaten WAEHLEN, nicht einen neuen Wert setzen.
    Melden sie 7, waehrend {4, 9} zur Wahl stehen, bleibt es ein Widerspruch.
    """
    active = tuple(f >= threshold for f in fills)
    moeglich: list[int] = []

    direkt = SEGMENT_PATTERNS.get(active)
    if direkt is not None:
        moeglich.append(direkt)

    if band > 0:
        for i, fill in enumerate(fills):
            if abs(fill - threshold) > band:
                continue
            gekippt = list(active)
            gekippt[i] = not gekippt[i]
            andere = SEGMENT_PATTERNS.get(tuple(gekippt))
            if andere is not None and andere not in moeglich:
                moeglich.append(andere)

    return tuple(sorted(moeglich))


def segment_probabilities(fills: list[float], threshold: float,
                          scale: float) -> dict[int, float]:
    """Wie wahrscheinlich ist jede Ziffer 0-9 angesichts dieser Messung?

    DIE IDEE (Nutzer, 2026-09-15): *"jede Ziffer gibt an, zu 0,1% eine 1, zu
    5,2% eine 2 usw. und zu 85% eine 9 -- dann koennten wir uns immer die top
    Kandidaten anschauen und daraus Rueckschluesse ziehen."*

    Was `segment_candidates` liefert, ist eine Liste ohne Rangfolge: {4, 9}
    sagt nicht, ob es fast sicher eine 9 ist oder ein echter Muenzwurf. Genau
    das ist aber der Unterschied, an dem eine zweite Quelle ansetzen kann.

    DER WEG. Jedes Segment ist eine eigene Messung mit eigener Unsicherheit.
    Wie sicher es an ist, haengt am Abstand zur Schwelle:

        p_an = 1 / (1 + exp(-(fuellgrad - schwelle) / scale))

    Die Wahrscheinlichkeit einer Ziffer ist dann das Produkt ueber ihre sieben
    Segmente, normiert ueber alle bekannten Muster. Normiert wird BEWUSST nur
    ueber gueltige Muster: Gefragt ist "welche Ziffer, wenn es eine ist" --
    dass ueberhaupt eine Ziffer da ist, klaert die Helligkeitspruefung vorher.

    WARUM DAS MEHR IST ALS KOSMETIK. GEMESSEN auf Bahn 4, letzte Stelle,
    F5695-6000 (Anzeige nachweislich `0133`, siehe `debug/summe_bahn4.gif`):

        a=0,86  b=0,30  c=0,84  d=0,81  e=0,02  f=0,18  g=0,84
        Schwelle 0,301

    Segment b liegt 0,001 unter der Schwelle und wackelt dabei nur um 0,001.
    Das ist kein Rauschen, sondern ein echter Muenzwurf -- den die harte
    Entscheidung als Gewissheit ausgibt. Mit Wahrscheinlichkeiten steht dort,
    was wirklich gemessen wurde: zwei Lesarten, etwa gleich stark.

    Args:
        scale: Wie schnell die Sicherheit mit dem Abstand zur Schwelle
            waechst. GEMESSEN wurde das Rauschen eines Fuellgrades bei
            unveraenderter Anzeige (Bahn 3 und 4, 1329 Frames): Median 0,003
            bis 0,016, 90. Perzentil 0,040. Der Wert steht in
            `detection.digits.segment_probability_scale`.

    Returns:
        {Ziffer: Wahrscheinlichkeit}, Summe 1. Leer, wenn nichts zu rechnen
        war.
    """
    if not fills or scale <= 0:
        return {}
    p_an = [1.0 / (1.0 + math.exp(-max(-60.0, min(60.0,
                                                  (f - threshold) / scale))))
            for f in fills]

    roh: dict[int, float] = {}
    for muster, wert in SEGMENT_PATTERNS.items():
        p = 1.0
        for an, pa in zip(muster, p_an):
            p *= pa if an else (1.0 - pa)
        # Mehrere Muster fuer dieselbe Ziffer (die 9 dieser Anlage gibt es in
        # zwei Schreibweisen) schliessen einander aus -- ihre
        # Wahrscheinlichkeiten addieren sich.
        roh[wert] = roh.get(wert, 0.0) + p

    summe = sum(roh.values())
    if summe <= 0:
        return {}
    return {wert: p / summe for wert, p in roh.items() if p > 0}


def is_ambiguous(fills: list[float], threshold: float, band: float) -> bool:
    """Laesst die Messung mehr als eine Ziffer zu?"""
    return len(segment_candidates(fills, threshold, band)) > 1


class CalibratedDigitReader:
    """Liest Ziffern aus einzeln kalibrierten Stellen-ROIs."""

    def __init__(self, cfg: DigitDetectionConfig) -> None:
        self.cfg = cfg
        self._preprocessor = SevenSegmentDetector(cfg)
        self._regions = segment_regions(
            shear=cfg.segment_shear,
            middle_inset=cfg.segment_middle_inset)

    def read_digit(self, patch: np.ndarray) -> tuple[str, float]:
        zeichen, confidence, _ = self.read_digit_full(patch)
        return zeichen, confidence

    def segment_fills(self, patch: np.ndarray) -> list[float] | None:
        """Wie voll ist jedes der sieben Segmente? `None`, wenn unlesbar.

        Herausgeloest aus `read_digit_full`, damit dieselbe Messung auch von
        aussen zu bekommen ist -- die Wahrscheinlichkeitsrechnung
        (`segment_probabilities`) und die Vermessung der Schwellen brauchen die
        rohen Fuellgrade, nicht das Ergebnis.
        """
        if patch is None or patch.size == 0:
            return None

        # Ist die Anzeige ueberhaupt beleuchtet?
        #
        # Diese Pruefung ist noetig, WEIL Otsu normalisiert: Es findet auch in
        # einem fast schwarzen Ausschnitt eine Schwelle und macht aus blossem
        # Rauschen eine scheinbare Ziffer. GEMESSEN wurde dabei bevorzugt "8" --
        # das Muster mit allen sieben Segmenten -- und dieser Phantomwert
        # widersprach dann der Lampenzaehlung.
        #
        # WORAUF gemessen wird, entscheidet mehr als die Schwelle selbst.
        #
        # Frueher galt das 95. Perzentil ueber die ganze Zelle. Das verwarf
        # lesbare Ziffern: Eine "1" leuchtet mit zwei von sieben Segmenten und
        # bleibt gemittelt dunkler als jede andere Ziffer. GEMESSEN auf Bahn 5,
        # F40903 -- beide Zellen zeigten im Bild eine eindeutige 1:
        #     throw_number[2]   95. Perzentil 220   Maximum 254   verworfen
        #     total_b[2]        95. Perzentil 229   Maximum 255   verworfen
        #
        # GEMESSEN ueber 4800 Zellen, Anteil im unsicheren Bereich 150-245:
        #     95. Perzentil  24,9 %   |   99. Perzentil  6,5 %   |  Maximum  3,6 %
        # Dunkle Zelle: Maximum 114-119. Leuchtende Zelle: 246-255.
        if self.cfg.brightness_percentile >= 100.0:
            helligkeit = float(patch[:, :, 2].max())
        else:
            helligkeit = float(np.percentile(patch[:, :, 2],
                                             self.cfg.brightness_percentile))
        if helligkeit < self.cfg.min_display_brightness:
            return None

        mask = self._preprocessor._red_mask(patch)
        if mask.max() == 0:
            return None

        # Vertikal auf den tatsaechlichen Ziffernumriss beschneiden.
        #
        # Der kalibrierte Rahmen sitzt nie exakt: Er wird von Hand gesetzt und
        # bekommt zusaetzlich `digit_padding` Luft. Diese Luft verschiebt die
        # geometrischen Drittel, und die aeussersten Segmente rutschen aus ihrer
        # Messflaeche.
        #
        # GEMESSEN auf Bahn 5 an drei Wuerfen, deren Tafel klar "9" zeigte:
        #     a=0.24  b=0.61  c=0.51  d=0.00  e=0.00  f=0.30  g=0.70
        # Segment d lag mit 0.00 komplett ausserhalb, a mit 0.17-0.38 auf der
        # Kippe -- gelesen wurde "4" (bcfg) statt "9" (abcdfg). Genau die beiden
        # WAAGERECHTEN Segmente fehlten, also die aeussersten.
        #
        # Der Zuschnitt ist nur VERTIKAL zulaessig, nicht horizontal: Jede
        # 7-Segment-Ziffer nutzt die volle Hoehe (auch die "1" -- b und c
        # zusammen reichen von oben bis unten), aber die "1" nutzt eben NICHT
        # die volle Breite. Ein horizontaler Zuschnitt zoege sie auf die ganze
        # Zelle und machte sie unlesbar.
        trimmed = self._preprocessor._trim_vertical(mask)
        if trimmed.size and trimmed.max() > 0:
            mask = trimmed

        cell = cv2.resize(mask, (CELL_WIDTH, CELL_HEIGHT),
                          interpolation=cv2.INTER_AREA)

        fills: list[float] = []
        for name in SEGMENT_ORDER:
            x, y, w, h = self._regions[name]
            region = cell[y:y + h, x:x + w]
            fills.append(float(region.mean() / 255.0) if region.size else 0.0)
        return fills

    def read_digit_full(
            self, patch: np.ndarray) -> tuple[str, float, tuple[int, ...]]:
        """Dekodiert eine einzelne, exakt eingerahmte Ziffer."""
        zeichen, score, kandidaten, _ = self.read_digit_verteilung(patch)
        return zeichen, score, kandidaten

    def read_digit_verteilung(self, patch: np.ndarray) -> tuple[
            str, float, tuple[int, ...], tuple[tuple[int, float], ...]]:
        """Wie `read_digit_full`, zusaetzlich mit der Verteilung ueber 0-9.

        Die harte Lesung bleibt unveraendert -- die Verteilung tritt NEBEN sie,
        nicht an ihre Stelle. Wer sie nicht braucht, merkt nichts davon; wer
        sie braucht, muss nicht ein zweites Mal messen.
        """
        fills = self.segment_fills(patch)
        if fills is None:
            return "?", 0.0, (), ()

        threshold = self._threshold(fills)
        verteilung = tuple(sorted(
            segment_probabilities(
                fills, threshold, self.cfg.segment_probability_scale).items(),
            key=lambda wp: -wp[1]))
        active = tuple(f >= threshold for f in fills)

        # Haengt das Ergebnis an einem Segment, das auf der Schwelle liegt?
        #
        # GEMESSEN auf Bahn 5: Segment a lag konstant bei 0,333, die Schwelle
        # bei 0,288-0,326. Damit galt es als aktiv, und aus "bcfg" (4) wurde
        # "abcfg" (9) -- die Tafel zeigte nachweislich eine 4.
        #
        # Beide Muster unterscheiden sich seit BUG-009 in genau einem Segment.
        # Wenn ein Umkippen dieses einen Segments eine ANDERE gueltige Ziffer
        # ergaebe, ist die Lesung geraten. Dann lieber "?": Die Ziffer ist
        # Gegenprobe zu den Lampen, und eine falsche Gegenprobe ist schaedlicher
        # als gar keine -- sie erzeugt einen Widerspruch, wo keiner ist.
        # Mehrdeutige Lesungen liefern KEINE Ziffer, aber ihre Kandidaten --
        # eine andere Quelle kann sie aufloesen (siehe segment_candidates).
        kandidaten = segment_candidates(fills, threshold,
                                        self.cfg.segment_ambiguous_band)
        if len(kandidaten) > 1:
            return "?", 0.0, kandidaten, verteilung

        digit = SEGMENT_PATTERNS.get(active)

        if digit is None:
            # KEIN GUELTIGES MUSTER -- und hier lag ein Fehler, den erst die
            # Verteilung sichtbar gemacht hat (2026-09-15).
            #
            # Frueher wurde das naechstliegende Muster nach Hamming-Abstand
            # gesucht: Wie viele Segmente muessten umkippen? Diese Zaehlung
            # behandelt alle Segmente gleich -- aber sie sind es nicht.
            #
            # GEMESSEN auf Bahn 4, F5400, letzte Stelle (im Bild zweifelsfrei
            # eine 9, siehe `debug/warum_falsch.png`):
            #
            #     a=0,885 an   b=0,668 an   c=0,853 an   g=0,853 an
            #     d=0,000 aus  e=0,007 aus  f=0,182 aus     Schwelle 0,310
            #
            # Das Muster "abcg" steht in keiner Tabelle. Im Abstand 1 liegen
            # ZWEI Ziffern: die 3 (d muesste an, liegt 0,31 daneben) und die 9
            # (f muesste an, liegt 0,13 daneben). Der Hamming-Abstand sieht da
            # keinen Unterschied, also gewann schlicht die, die in der Tabelle
            # frueher steht -- die 3. Die Ziffer wurde von der Reihenfolge
            # eines Dictionarys entschieden.
            #
            # Die Verteilung wiegt stattdessen, WIE KNAPP jedes Segment war,
            # und kommt auf 9 zu 99 % gegen 3 zu 1 %.
            #
            # GEMESSEN ueber den ganzen Mitschnitt, auf denselben Frames und
            # gegen ein von beiden Verfahren unabhaengiges Kriterium (die
            # Summe darf nicht fallen und je Wurf hoechstens um 9 steigen):
            #
            #     Bahn 2   49,6 %  ->  56,7 %
            #     Bahn 3   98,5 %  ->  98,5 %
            #     Bahn 4   94,8 %  ->  94,8 %
            #     Bahn 5   98,6 %  ->  99,1 %
            #
            # Nirgends schlechter, auf der schwierigsten Bahn deutlich besser.
            if not verteilung:
                return "?", 0.0, kandidaten, verteilung
            best, p_best = verteilung[0]
            if p_best < self.cfg.segment_probability_min:
                # Kein Kandidat sticht heraus -- dann lieber schweigen. Die
                # Kandidatenliste geht trotzdem mit, eine andere Quelle kann
                # sie aufloesen.
                return "?", 0.0, kandidaten or tuple(
                    sorted(w for w, pp in verteilung
                           if pp >= self.cfg.segment_probability_min / 2)
                ), verteilung
            # DIE CONFIDENCE BLEIBT, WIE SIE WAR (0,35). Geaendert wird nur,
            # WELCHE Ziffer gewaehlt wird -- nicht, wie sehr man ihr traut.
            #
            # Ein ungueltiges Segmentmuster ist ein Warnzeichen, ganz gleich
            # wie klar der wahrscheinlichste Kandidat fuehrt: Irgendetwas an
            # der Messung stimmt nicht, sonst stuende das Muster in der
            # Tabelle. Der Wert liegt unter `min_confidence`, damit solche
            # Lesungen nicht in die harten Feldwerte einfliessen -- sie
            # zaehlen aber weiter fuer die Mehrheit und die Verteilung
            # (`FieldAggregator.als_lesung`), wo die Summenspur sie nutzt.
            #
            # GEMESSEN, warum das noetig ist: Mit `p_best` als Confidence
            # flossen diese Lesungen ploetzlich in die Feldwerte ein. Im
            # Vollauf wurden daraus 61 statt 64 gueltige Wuerfe und 11 statt 3
            # Meldungen "Wurf fehlt" -- die Wurfnummer wurde nun dort gelesen,
            # wo sie vorher schwieg, und sprang.
            return str(best), 0.35, kandidaten or (best,), verteilung

        margins = [abs(f - threshold) for f in fills]
        return (str(digit), min(1.0, 0.5 + 2.0 * min(margins)),
                kandidaten or (digit,), verteilung)

    def _threshold(self, fills: list[float]) -> float:
        """Schwelle RELATIV zum hellsten Segment der Ziffer.

        Ein fester Wert traegt nicht: Gemessen lagen echte Werte bei 0,25
        (aktiv) und 0,39 (inaktiv) -- beidseitig knapp an einer festen Schwelle
        vorbei.

        Die naheliegende Alternative -- die groesste Luecke in den sortierten
        Fuellgraden -- traegt ebenfalls nicht. GEMESSEN an einer "0":

            g=0,10 | a=0,26  f=0,27 | e=0,49  c=0,61  d=0,64  b=0,69
                              groesste Luecke liegt HIER (0,27 -> 0,49)

        Bei einer "0" sind sechs Segmente aktiv und nur eines aus. Die groesste
        Luecke liegt dann *innerhalb* der aktiven Segmente, und die Schwelle
        landet viel zu hoch -- die Ziffer wurde unlesbar.

        Verlaesslich ist dagegen: Das hellste Segment einer Ziffer ist immer
        aktiv. Alles, was einen nennenswerten Bruchteil davon erreicht, ist es
        auch. Die Untergrenze verhindert, dass bei dunkler Anzeige blosses
        Rauschen als Segment zaehlt.
        """
        peak = max(fills) if fills else 0.0
        if peak <= 0:
            return self.cfg.segment_on_ratio
        return max(self.cfg.segment_floor, self.cfg.segment_relative_ratio * peak)

    def read_field(self, patches: list[np.ndarray]) -> DigitReading:
        """Liest ein Feld aus den Ausschnitten seiner einzelnen Stellen."""
        if not patches:
            return DigitReading.unreadable("keine kalibrierten Stellen")

        characters: list[str] = []
        scores: list[float] = []
        kandidaten: list[tuple[int, ...]] = []
        verteilungen: list[tuple[tuple[int, float], ...]] = []
        for patch in patches:
            character, score, moeglich, verteilung =                 self.read_digit_verteilung(patch)
            characters.append(character)
            scores.append(score)
            kandidaten.append(moeglich)
            verteilungen.append(verteilung)

        text = "".join(characters)
        value = int(text) if text.isdigit() else None
        confidence = float(np.mean(scores)) if scores else 0.0
        if value is None:
            confidence = min(confidence, 0.3)

        return DigitReading(text=text, value=value, confidence=confidence,
                            candidates=tuple(kandidaten),
                            verteilung=tuple(verteilungen),
                            digits=tuple(characters), scores=tuple(scores))
