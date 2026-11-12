"""Zeitliche Aggregation von Messungen (Auftrag Paragraph 8).

Der Grund steht im Auftrag und ist am Material bestaetigt: Die Anzeigen sind
nicht in jedem Frame lesbar. Belegt: `2026-08-22 09-15-50.mp4`, Frame 90,
Bahn 2 -- das Kegelanzahl-Feld ist dort unbeleuchtet, waehrend es in Frame 42
klar "7" zeigt.

    Frame 1 -> 7  (conf 0,91)
    Frame 2 -> ?  (conf 0,12)   verwerfen, nicht raten
    Frame 3 -> 7  (conf 0,88)
    Frame 4 -> 1  (conf 0,34)   Mischbild
                                => Ergebnis 7, hohe Confidence

Regeln, die hier gelten:

* Ein einzelnes Messergebnis wird **nie** uebernommen.
* Messungen unter `min_confidence` fliessen gar nicht erst ein.
* Gewichtet wird nach Confidence, nicht nach blosser Haeufigkeit -- drei
  unsichere Messungen wiegen weniger als eine klare.
* Bleibt es uneindeutig, ist das Ergebnis `None`. Es wird **nicht** die
  haeufigste Variante geraten.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Generic, Hashable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T", bound=Hashable)


@dataclass
class Vote(Generic[T]):
    """Eine Einzelmessung mit ihrer Herkunft."""

    value: T
    confidence: float
    frame_index: int = -1

    def to_dict(self) -> dict:
        return {"value": self.value, "confidence": round(self.confidence, 3),
                "frame": self.frame_index}


@dataclass
class AggregationResult(Generic[T]):
    """Ergebnis einer Aggregation -- mit allem, was zur Begruendung noetig ist."""

    value: T | None
    confidence: float
    votes: tuple[Vote[T], ...] = ()
    agreement: float = 0.0          # Anteil der Stimmen fuer den Gewinner
    rejected: int = 0               # wegen zu geringer Confidence verworfen

    @property
    def is_decided(self) -> bool:
        return self.value is not None

    def explain(self) -> str:
        if not self.votes:
            return "keine verwertbare Messung"
        counts: dict[T, int] = defaultdict(int)
        for vote in self.votes:
            counts[vote.value] += 1
        detail = ", ".join(f"{value}x{count}" for value, count in counts.items())
        if self.value is None:
            return f"uneindeutig ({detail}), {self.rejected} verworfen"
        return (f"{self.value} aus {len(self.votes)} Messungen ({detail}), "
                f"Einigkeit {self.agreement:.0%}, Confidence {self.confidence:.2f}")

    def to_dict(self) -> dict:
        return {"value": self.value, "confidence": round(self.confidence, 3),
                "agreement": round(self.agreement, 3),
                "votes": [v.to_dict() for v in self.votes],
                "rejected": self.rejected}


class TemporalAggregator(Generic[T]):
    """Sammelt Messungen ueber mehrere Frames und entscheidet gewichtet."""

    def __init__(self, min_confidence: float = 0.5,
                 min_agreement: float = 0.5,
                 min_votes: int = 1) -> None:
        self.min_confidence = min_confidence
        self.min_agreement = min_agreement
        self.min_votes = min_votes
        self._votes: list[Vote[T]] = []
        self._rejected = 0
        # ALLE Messungen, auch die unterhalb von `min_confidence`. Sie zaehlen
        # nicht mit, aber sie sind die einzige Grundlage fuer `mehrheit()` --
        # siehe dort. Frueher wurden sie nur GEZAEHLT (`_rejected`), womit die
        # zeitliche Einigkeit nachtraeglich nicht mehr bestimmbar war.
        self._alle: list[Vote[T]] = []

    def add(self, value: T | None, confidence: float, frame_index: int = -1) -> bool:
        """Nimmt eine Messung auf. Liefert False, wenn sie verworfen wurde."""
        if value is not None:
            self._alle.append(Vote(value, confidence, frame_index))
        if value is None or confidence < self.min_confidence:
            self._rejected += 1
            return False
        self._votes.append(Vote(value, confidence, frame_index))
        return True

    def mehrheit(self) -> tuple[T | None, float]:
        """Was haben die Frames MEHRHEITLICH gesehen -- und wie einig waren sie?

        UNTERSCHIED ZU `result()`: Diese Methode fragt NICHT, wie gut eine
        Ziffer auf einem Bild zu erkennen war. Sie fragt nur, ob die Frames
        DASSELBE gesehen haben. Beides zu vermischen war ein Denkfehler
        (BUG-020).

        GEMESSEN am 2026-09-04, Bahn 4, Sperrzyklus F126593 (10 Sample-Frames):

            alle zehn Frames lasen '0','0','0'   -> voellig einig
            Scores der fuehrenden Stellen: 0,35  -> unter `min_confidence` 0,5

        `result()` liefert dort `None`: Jede einzelne Stimme faellt an der
        Confidence-Schwelle durch, und ein Feld mit einer unklaren Stelle wird
        ganz verworfen. Die Information "zehn von zehn sagen dasselbe" geht
        dabei verloren -- obwohl genau sie bei einer schwach lesbaren Anzeige
        das einzig Belastbare ist.

        Returns:
            (haeufigster Wert, Anteil dieses Werts an allen Messungen).
            Ohne Messungen: (None, 0.0).
        """
        if not self._alle:
            return None, 0.0
        counts: dict[T, int] = defaultdict(int)
        for vote in self._alle:
            counts[vote.value] += 1
        best = max(counts, key=lambda v: counts[v])
        return best, counts[best] / len(self._alle)

    def anteile(self) -> dict[T, float]:
        """Welcher Wert kam mit welchem Anteil vor?

        `mehrheit()` behaelt nur den Sieger; hier bleibt das ganze Feld
        stehen. Gebraucht wird das vom gefuehrten Lesen: Eine Stelle, die in
        60 % der Frames als '4' und in 40 % als '9' gelesen wurde, ist nicht
        einfach eine '4' -- sie ist eine Stelle mit zwei Kandidaten, und eine
        andere Quelle darf zwischen ihnen waehlen.
        """
        if not self._alle:
            return {}
        counts: dict[T, int] = defaultdict(int)
        for vote in self._alle:
            counts[vote.value] += 1
        gesamt = len(self._alle)
        return {wert: anzahl / gesamt for wert, anzahl in counts.items()}

    def result(self) -> AggregationResult[T]:
        """Wertet die gesammelten Messungen aus."""
        if len(self._votes) < self.min_votes or not self._votes:
            return AggregationResult(value=None, confidence=0.0,
                                     votes=tuple(self._votes),
                                     rejected=self._rejected)

        weights: dict[T, float] = defaultdict(float)
        counts: dict[T, int] = defaultdict(int)
        for vote in self._votes:
            weights[vote.value] += vote.confidence
            counts[vote.value] += 1

        best = max(weights, key=lambda v: weights[v])
        total_weight = sum(weights.values())
        share = weights[best] / total_weight if total_weight > 0 else 0.0
        agreement = counts[best] / len(self._votes)

        if share < self.min_agreement:
            # Kein klarer Gewinner -- lieber kein Ergebnis als ein geratenes.
            log.debug("Aggregation uneindeutig: %s",
                      {str(k): round(v, 2) for k, v in weights.items()})
            return AggregationResult(value=None, confidence=0.0,
                                     votes=tuple(self._votes),
                                     agreement=agreement,
                                     rejected=self._rejected)

        # Confidence: mittlere Confidence der Gewinnerstimmen, gedaempft durch
        # den Anteil abweichender Messungen. Uneinigkeit muss sich im Ergebnis
        # niederschlagen, sonst taeuscht es Sicherheit vor.
        winner_confidence = weights[best] / counts[best]
        confidence = winner_confidence * (0.5 + 0.5 * agreement)

        return AggregationResult(value=best, confidence=min(1.0, confidence),
                                 votes=tuple(self._votes), agreement=agreement,
                                 rejected=self._rejected)

    def reset(self) -> None:
        self._votes.clear()
        self._alle.clear()
        self._rejected = 0

    @property
    def vote_count(self) -> int:
        return len(self._votes)


class FieldAggregator:
    """Fasst ein mehrstelliges Ziffernfeld ueber die Zeit zusammen -- STELLENWEISE.

    Warum nicht ueber den Gesamtwert: Die vierstellige Summe wurde vorher als
    ganze Zahl abgestimmt. Eine einzige wackelige Stelle liess damit die
    komplette Summe durchfallen.

    GEMESSEN auf Bahn 3, 40 Frames einer unveraenderten Anzeige (`0040`):

        Stelle 1: '0' 40x      Stelle 3: '4' 35x, '9' 5x
        Stelle 2: '0' 40x      Stelle 4: '0' 40x

    Drei Stellen waren vollkommen eindeutig, nur eine schwankte -- und ausgerechnet
    zwischen '4' und '9', die sich auf dieser Anlage in genau EINEM Segment
    unterscheiden (siehe BUG-009). Ueber den Gesamtwert abgestimmt standen 35
    Stimmen fuer "0040" gegen 5 fuer "0090"; sank der Anteil unter
    `min_agreement`, war die Summe verloren. Stellenweise gewinnt die 4 mit 35:5,
    und die drei sicheren Stellen bleiben unangetastet.

    Der Preis, ehrlich benannt: Stellenweises Abstimmen kann einen Wert erzeugen,
    der in KEINEM einzelnen Frame so gelesen wurde. Das ist hier richtig, weil die
    Stellen unabhaengig voneinander gelesen werden -- jede hat ihren eigenen ROI
    und ihre eigene Segmentmessung.
    """

    def __init__(self, digits: int, min_confidence: float = 0.0,
                 min_agreement: float = 0.5) -> None:
        self.digits = digits
        self._per_digit: list[TemporalAggregator[str]] = [
            TemporalAggregator(min_confidence=min_confidence,
                               min_agreement=min_agreement)
            for _ in range(digits)
        ]
        self._seen = 0

    def add(self, characters: Sequence[str], scores: Sequence[float],
            frame_index: int = -1) -> None:
        """Nimmt die Einzelzeichen einer Lesung auf.

        Stellen, die als '?' gelesen wurden, werden uebersprungen -- eine
        unlesbare Stelle ist keine Stimme, aber sie entwertet auch nicht die
        uebrigen Stellen derselben Lesung.
        """
        if len(characters) != self.digits:
            # Andere Stellenzahl -> die Zuordnung waere geraten
            return
        self._seen += 1
        for i, character in enumerate(characters):
            if not character.isdigit():
                continue
            score = scores[i] if i < len(scores) else 0.0
            self._per_digit[i].add(character, score, frame_index)

    def result(self) -> tuple[int | None, float]:
        """Liefert (Wert, Confidence). Wert ist None, sobald EINE Stelle unklar ist.

        Ein teilweise gelesener Zahlenwert waere schlimmer als gar keiner: Aus
        '0?40' liesse sich kein Wert bilden, ohne eine Ziffer zu erfinden.
        """
        zeichen: list[str] = []
        confidences: list[float] = []
        for aggregator in self._per_digit:
            ergebnis = aggregator.result()
            if ergebnis.value is None:
                return None, 0.0
            zeichen.append(ergebnis.value)
            confidences.append(ergebnis.confidence)

        text = "".join(zeichen)
        if not text.isdigit():
            return None, 0.0
        # Die schwaechste Stelle bestimmt die Sicherheit des Ganzen
        return int(text), min(confidences) if confidences else 0.0

    def als_lesung(self, mindestanteil: float = 0.10):
        """Das Feld als Lesung MIT Kandidaten je Stelle.

        `result()` und `mehrheit()` liefern eine Zahl -- eine Stelle, die
        zwischen zwei Ziffern schwankte, ist darin auf ihren Sieger
        eingedampft. Fuer das gefuehrte Lesen (`analysis.gefuehrtes_lesen`)
        ist gerade die Schwankung die Information: Nur wer weiss, WORUEBER
        die Frames uneinig waren, kann die Erwartung ehrlich dagegenhalten.

        Args:
            mindestanteil: Ab welchem Stimmenanteil eine Ziffer als Kandidat
                zaehlt. Zu klein, und ein einzelner Ausreisser unter fuenfzig
                Frames macht jede Stelle beliebig; zu gross, und die zweite
                Lesart verschwindet. GEMESSEN auf Bahn 3 (40 Frames einer
                unveraenderten `0040`): Die schwankende Stelle stand 35:5 fuer
                '4' gegen '9' -- der Unterlegene kam auf 12,5 %. Die Schwelle liegt knapp
                darunter, damit genau so ein Fall beide Lesarten behaelt; ein
                einzelner Ausreisser unter fuenfzig Frames (2 %) faellt
                weiterhin durch.

        Returns:
            Eine `DigitReading`, deren `digits` die Mehrheitsziffern sind
            ('?' wo gar nichts gelesen wurde) und deren `candidates` je Stelle
            alle hinreichend oft gesehenen Ziffern enthalten.
        """
        from kegel_cv.detection.digit_detector import DigitReading

        zeichen: list[str] = []
        kandidaten: list[tuple[int, ...]] = []
        anteile_je_stelle: list[float] = []
        for aggregator in self._per_digit:
            anteile = aggregator.anteile()
            gueltig = {z: a for z, a in anteile.items()
                       if isinstance(z, str) and z.isdigit()}
            if not gueltig:
                zeichen.append("?")
                kandidaten.append(())
                continue
            sieger = max(gueltig, key=lambda z: gueltig[z])
            zeichen.append(sieger)
            anteile_je_stelle.append(gueltig[sieger])
            kandidaten.append(tuple(sorted(
                int(z) for z, a in gueltig.items() if a >= mindestanteil)))

        text = "".join(zeichen)
        return DigitReading(
            text=text,
            value=int(text) if text.isdigit() else None,
            confidence=min(anteile_je_stelle) if anteile_je_stelle else 0.0,
            digits=tuple(zeichen),
            candidates=tuple(kandidaten),
            scores=tuple(anteile_je_stelle))

    def mehrheit(self, ignoriere_fuehrende: int = 0) -> tuple[int | None, float]:
        """Der zeitliche Mehrheitswert des Feldes und die Einigkeit darueber.

        Fragt -- anders als `result()` -- NICHT, wie gut die Ziffern auf den
        Bildern zu erkennen waren, sondern nur, ob die Frames dasselbe gesehen
        haben. Begruendung und Messbeleg stehen bei
        `TemporalAggregator.mehrheit`.

        Args:
            ignoriere_fuehrende: So viele fuehrende Stellen bleiben
                unberuecksichtigt. Fuer die WURFNUMMER ist das die
                Hunderterstelle: Ein Spiel hat 30 Wuerfe, es gibt keinen
                hundertsten (Nutzerangabe 2026-09-04). Die Stelle steht
                dauerhaft auf einer dunklen Null und wird deshalb chronisch
                schwach gelesen -- sie mitzubewerten hiesse, das ganze Feld an
                einer Stelle scheitern zu lassen, die nichts aussagt.

        Returns:
            (Wert aus den Mehrheitsziffern, kleinste Einigkeit aller
            betrachteten Stellen). Kann eine Stelle gar nicht gelesen werden,
            ist der Wert None.
        """
        zeichen: list[str] = []
        einigkeiten: list[float] = []
        for i, aggregator in enumerate(self._per_digit):
            wert, einigkeit = aggregator.mehrheit()
            if i < ignoriere_fuehrende:
                # Die Stelle wird gelesen, aber nicht bewertet. Ihr Wert geht
                # trotzdem in die Zahl ein -- sonst waere aus '030' eine '30'
                # mit anderer Bedeutung geworden.
                zeichen.append(wert if wert is not None else "0")
                continue
            if wert is None:
                return None, 0.0
            zeichen.append(wert)
            einigkeiten.append(einigkeit)

        text = "".join(zeichen)
        if not text.isdigit():
            return None, 0.0
        # Die uneinigste betrachtete Stelle bestimmt die Einigkeit des Ganzen.
        return int(text), min(einigkeiten) if einigkeiten else 0.0
