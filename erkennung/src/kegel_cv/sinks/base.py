"""Abnehmer fuer Wurfergebnisse.

Die Analyse kennt nur diese Schnittstelle -- ob dahinter eine Datei, eine
Datenbank oder eine HTTP-Schnittstelle liegt, ist ihr gleichgueltig. Damit
laesst sich das Ziel austauschen, ohne die Erkennung anzufassen (Auftrag
Paragraph 26).

**Ein Abnehmer darf die Analyse niemals aufhalten oder abbrechen.** Ein
ausgefallenes Netz ist ein Problem des Versands, nicht der Auswertung -- die
Kegel sind gefallen, ob die Datenbank erreichbar ist oder nicht. Deshalb faengt
jede Implementierung ihre Fehler selbst ab und meldet sie ueber das Log.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from ..models.throw import ThrowResult

log = logging.getLogger(__name__)


class ResultSink(ABC):
    """Nimmt fertige Wurfergebnisse entgegen."""

    @abstractmethod
    def send(self, throw: ThrowResult) -> None:
        """Uebergibt einen Wurf. Darf NICHT blockieren und NICHT werfen."""

    def flush(self) -> None:
        """Wartet, bis alles Uebergebene draussen ist. Standard: nichts zu tun."""

    def close(self) -> None:
        """Gibt Ressourcen frei. Standard: nichts zu tun."""

    def __enter__(self) -> ResultSink:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class NullSink(ResultSink):
    """Verwirft alles -- der Standard, solange kein Ziel eingerichtet ist."""

    def send(self, throw: ThrowResult) -> None:
        return None


class BahnFilterSink(ResultSink):
    """Laesst nur Wuerfe bestimmter Bahnen durch.

    WOZU (Nutzer, 2026-09-24): *"ich moechte auswaehlen, welche Bahnen
    ueberhaupt erfasst und/oder gesendet werden... So kann ich dann ohne
    Probleme ein Multisensorsystem bauen."* Zwei Geraete sehen dieselbe Halle
    -- der Stream die Bahnen 2 und 3, das Telefon die Bahnen 4 und 5. Ohne
    diesen Filter schriebe jedes Geraet alle Bahnen, die es zufaellig lesen
    kann, und die Tabelle haette jeden Wurf doppelt.

    Bewusst HIER und nicht in der Auswertung: Eine Bahn, die man mitrechnen,
    aber nicht senden will -- etwa um zwei Kameras zu vergleichen -- bleibt so
    vollstaendig in den Debugdateien und taucht nur in der Datenbank nicht auf.

    Eine leere Auswahl laesst ALLES durch. Sonst waere die Vorgabe "nichts
    senden", und ein vergessener Eintrag brauechte einen ganzen Spieltag, um
    aufzufallen.
    """

    def __init__(self, inner: ResultSink, bahnen: "list[int] | None") -> None:
        self.inner = inner
        self.bahnen = set(bahnen or ())
        self._abgewiesen = 0

    def send(self, throw: ThrowResult) -> None:
        if self.bahnen and throw.lane not in self.bahnen:
            self._abgewiesen += 1
            return
        self.inner.send(throw)

    def flush(self) -> None:
        self.inner.flush()

    def close(self) -> None:
        if self._abgewiesen:
            log.info("Versandfilter: %d Wuerfe nicht gesendet -- gesendet "
                     "werden nur die Bahnen %s",
                     self._abgewiesen, sorted(self.bahnen))
        self.inner.close()
