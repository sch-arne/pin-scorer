"""Gemerkte Feinkorrekturen zu einer Bauart -- was von Hand nachgezogen wurde.

DIE IDEE (Nutzer, 2026-09-11):

    "Am besten waere es, wenn sich der Code das merkt, und wenn das naechste
     Mal der Tafeltyp ausgewaehlt wird, dann schlaegt er automatisch vielleicht
     verschiedene Kalibrierungen vor oder so."

WAS GEMERKT WIRD -- und was ausdruecklich nicht:

Gespeichert werden **nur die Versaetze** gegenueber der Bauart, je Tafel und je
Bereich, in normierten Tafelkoordinaten. NICHT die Tafelecken: Die haengen an
Kamera, Zoom und Blickwinkel und sind in der naechsten Halle wertlos. Die
Versaetze dagegen beschreiben, wie die Bereiche AUF der Tafel sitzen -- und das
ist eine Eigenschaft der Anlage, nicht der Aufnahme.

WARUM JE TAFEL UND NICHT GEMITTELT: GEMESSEN 2026-09-11 wandert die Gruenlampe
ueber die vier Tafeln eines Overlays um 1,6 px, waehrend die Lampenraute
stehenbleibt. Ein gemeinsamer Mittelwert verschlechterte drei Tafeln, um eine
zu verbessern -- deshalb traegt jede Tafelposition ihren eigenen Satz.

WARUM ES VORGESCHLAGEN UND NICHT ANGEWANDT WIRD: Ob dieselbe Korrektur passt,
haengt an Halle und Kamera. Das weiss der Mensch davor, nicht das Programm.
Eine still angewandte Korrektur aus einer anderen Halle waere ein Fehler, den
niemand sucht, weil niemand von ihr weiss.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# Neben der Bauart, unter demselben Namen.
ENDUNG = ".korrekturen.json"
# Kleiner als das ist kein Versatz, sondern Rauschen im letzten Bit. Bei einer
# 160 px breiten Tafel sind 0,0005 ein zwoelftel Pixel.
KLEINSTER_VERSATZ = 0.0005


@dataclass
class Korrektur:
    """Was auf einer Anlage von Hand nachgezogen wurde."""

    name: str
    # Tafelposition von links (1-basiert) -> {ROI-Name: (dx, dy)}
    tafeln: dict[int, dict[str, tuple[float, float]]] = field(default_factory=dict)
    erstellt: str = ""
    zuletzt: str = ""

    @property
    def bereiche(self) -> int:
        return sum(len(v) for v in self.tafeln.values())

    def beschreibung(self) -> str:
        tag = (self.zuletzt or self.erstellt or "")[:10]
        return (f"{self.name} ({len(self.tafeln)} Tafeln, "
                f"{self.bereiche} Bereiche{', ' + tag if tag else ''})")


def _pfad(ordner: str | Path, typ_name: str) -> Path:
    return Path(ordner) / f"{typ_name}{ENDUNG}"


def lade(ordner: str | Path, typ_name: str) -> list[Korrektur]:
    """Liest die gemerkten Korrekturen einer Bauart. Fehlt die Datei: leer.

    Eine kaputte Datei darf die Kalibrierung nicht verhindern (P8) -- sie wird
    gemeldet und uebergangen.
    """
    pfad = _pfad(ordner, typ_name)
    if not pfad.is_file():
        return []
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        aus = []
        for eintrag in daten.get("korrekturen", []):
            tafeln = {int(k): {n: (float(v[0]), float(v[1]))
                               for n, v in felder.items()}
                      for k, felder in eintrag.get("tafeln", {}).items()}
            aus.append(Korrektur(name=eintrag["name"], tafeln=tafeln,
                                 erstellt=eintrag.get("erstellt", ""),
                                 zuletzt=eintrag.get("zuletzt", "")))
        return aus
    except Exception as exc:  # noqa: BLE001 -- siehe Docstring
        log.warning("Korrekturen zu %s nicht lesbar: %s", typ_name, exc)
        return []


def speichere(ordner: str | Path, typ_name: str,
              korrekturen: list[Korrektur]) -> Path:
    """Schreibt die Korrekturen neben die Bauart."""
    pfad = _pfad(ordner, typ_name)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_text(json.dumps({
        "typ": typ_name,
        "korrekturen": [{
            "name": k.name,
            "erstellt": k.erstellt,
            "zuletzt": k.zuletzt,
            "tafeln": {str(nr): {n: [round(v[0], 6), round(v[1], 6)]
                                 for n, v in felder.items()}
                       for nr, felder in k.tafeln.items()},
        } for k in korrekturen],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Korrekturen zu %s gespeichert: %d Eintraege (%s)",
             typ_name, len(korrekturen), pfad.name)
    return pfad


def aus_vergleich(vorlage_rois, kalibrierung, name: str) -> Korrektur:
    """Leitet die Korrektur aus dem Unterschied zur Bauart ab.

    Verglichen wird jede Tafel mit den Bereichen der VORLAGE -- was dazwischen
    liegt, hat jemand von Hand gemacht, egal auf welchem Weg (gezogen,
    Pfeiltaste, Versatzfeld, Nullenausrichtung).

    Winzige Unterschiede werden uebergangen: Sie stammen aus dem Runden und
    beschreiben nichts.
    """
    vorlage = {r.name: r.rect for r in vorlage_rois}
    jetzt = datetime.now().isoformat(timespec="seconds")
    korrektur = Korrektur(name=name, erstellt=jetzt, zuletzt=jetzt)
    for position, bahn in enumerate(
            sorted(kalibrierung.lanes, key=lambda b: b.quad[0][0]), start=1):
        felder: dict[str, tuple[float, float]] = {}
        for roi in bahn.rois:
            alt = vorlage.get(roi.name)
            if alt is None:
                continue
            dx, dy = roi.rect[0] - alt[0], roi.rect[1] - alt[1]
            if abs(dx) >= KLEINSTER_VERSATZ or abs(dy) >= KLEINSTER_VERSATZ:
                felder[roi.name] = (dx, dy)
        if felder:
            korrektur.tafeln[position] = felder
    return korrektur


def wende_an(kalibrierung, korrektur: Korrektur) -> int:
    """Legt eine gemerkte Korrektur auf eine frische Kalibrierung.

    Zugeordnet wird ueber die TAFELPOSITION von links -- dieselbe Reihenfolge,
    in der die Bahnnummern abgefragt werden. Fehlt eine Position (es wurden
    weniger Tafeln gefunden als beim Merken), bleibt sie unveraendert, statt
    dass sich alles um eine Stelle verschiebt.

    Zurueck kommt die Zahl der verschobenen Bereiche.
    """
    bahnen = sorted(kalibrierung.lanes, key=lambda b: b.quad[0][0])
    verschoben = 0
    for position, bahn in enumerate(bahnen, start=1):
        felder = korrektur.tafeln.get(position)
        if not felder:
            continue
        for i, roi in enumerate(bahn.rois):
            versatz = felder.get(roi.name)
            if versatz is None:
                continue
            x, y, w, h = roi.rect
            # In der Tafel bleiben -- `model_copy` prueft nichts, ein
            # hinausgeschobener Bereich waere still kaputt.
            neu_x = min(max(x + versatz[0], 0.0), max(0.0, 1.0 - w))
            neu_y = min(max(y + versatz[1], 0.0), max(0.0, 1.0 - h))
            bahn.rois[i] = roi.model_copy(update={"rect": (neu_x, neu_y, w, h)})
            verschoben += 1
    if verschoben:
        log.info("Korrektur '%s' angewandt: %d Bereiche auf %d Tafeln",
                 korrektur.name, verschoben, len(bahnen))
    return verschoben
