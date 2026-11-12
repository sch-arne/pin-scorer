#!/usr/bin/env python
"""Erzeugt die Ereignis-Fixture fuer die App `pin-scorer`.

WOFUER

`sch-arne/pin-scorer` soll erkannte Wuerfe uebernehmen. Deren
`docs/wurferkennung-plan.md` verlangt vor der ersten Zeile Code eine echte
Aufzeichnung als JSON-Fixture:

    "Vor der ersten Zeile Code: echte Aufzeichnung einer kompletten Serie
     (Volle + Abraeumen, mit Fehlwurf und Kranz) als JSON-Fixture. Ohne die
     baut man die Zuordnung gegen Vermutungen."

Genau die liefert dieses Werkzeug -- aus dem Wurfprotokoll eines Laufs.

DER KONTRAKT (aus deren Plan, Abschnitt 1)

    {"eventId": "uuid", "anlage": "...", "bahn": 3, "seq": 147,
     "ts": "2026-09-01T18:22:31.402Z", "art": "wurf",
     "bildVor": [1,...,9], "bildNach": [5,7], "konfidenz": 0.97}

DER ENTSCHEIDENDE UNTERSCHIED

`bildVor` und `bildNach` sind die STEHENDEN Kegel. Wir messen die GEFALLENEN
-- die Lampen der Anlage leuchten, wenn ein Kegel liegt. Umgerechnet wird
hier, nach denselben Regeln wie im Liveticker (`apps/liveticker/ticker.js`,
`automaticPhase` und `needsFreshPicture`); die Regeln stammen vom Nutzer.

WARUM DIE ids STABIL SIND

Deren Anforderung 5 verlangt Idempotenz ueber `eventId`. Die id wird deshalb
aus Lauf, Bahn und Videozeit ABGELEITET (uuid5), nicht gewuerfelt: Ein
zweiter Export derselben Aufzeichnung erzeugt dieselben ids, und ein zweimal
eingespieltes Ereignis bleibt eines.

Aufruf:

    .venv/Scripts/python.exe tools/export_erkennungs_fixture.py
        --lauf debug/<quelle>/lauf_<zeit> --anlage "Heimhalle"
        --beginn 2026-09-08T20:12:22 --ziel fixture.json
"""

from __future__ import annotations

import argparse
import csv
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# Aus apps/liveticker/ticker.js -- bewusst gespiegelt statt importiert: Die
# Regeln sind dort getestet, und ein zweiter Ort mit denselben Zahlen ist
# besser als eine Abhaengigkeit von JavaScript in einem Python-Werkzeug.
ALLE_KEGEL = [1, 2, 3, 4, 5, 6, 7, 8, 9]
KOENIG = 5
VOLLEN_WUERFE = 15
SPIEL_WUERFE = 30

# Fester Namensraum fuer die abgeleiteten ids. Beliebig gewaehlt, aber
# UNVERAENDERLICH -- wer ihn aendert, erzeugt fuer dieselben Wuerfe neue ids
# und damit Dubletten auf der Gegenseite.
NAMENSRAUM = uuid.UUID("6b1f5b7e-9c2a-5d3e-8f10-2a4b6c8d0e12")


def ist_vollen(wurfnummer: int) -> bool:
    """Volle oder Abraeumen? Wie `automaticPhase` im Liveticker."""
    im_spiel = ((wurfnummer - 1) % SPIEL_WUERFE) + 1
    return im_spiel <= VOLLEN_WUERFE


def braucht_neues_bild(stehend: list[int]) -> bool:
    """Stellt die Anlage neu auf? Wie `needsFreshPicture` im Liveticker.

    Regel des Nutzers (2026-09-07): Neu aufgestellt wird, wenn nichts mehr
    steht ODER nur noch der Koenig steht.
    """
    if not stehend:
        return True
    return len(stehend) == 1 and stehend[0] == KOENIG


def lies_wuerfe(lauf: Path) -> list[dict]:
    pfad = lauf / "wuerfe.csv"
    if not pfad.is_file():
        raise SystemExit(f"Kein Wurfprotokoll unter {pfad}")
    with pfad.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=";"))


def zahl(wert: str | None, vorgabe: float = 0.0) -> float:
    try:
        return float((wert or "").replace(",", "."))
    except ValueError:
        return vorgabe


def baue_ereignisse(zeilen: list[dict], anlage: str, beginn: datetime,
                    lauf_name: str) -> tuple[list[dict], int]:
    """Rechnet Wurfzeilen in den Ereignisstrom der App um.

    Reine Funktion ohne Dateizugriff -- so laesst sie sich pruefen, ohne
    einen Lauf zu erzeugen.
    """
    # Je Bahn das aktuelle Kegelbild mitfuehren. P6: Die Bahnen sind
    # unabhaengig, also je Bahn ein eigener Zustand.
    stehend: dict[int, list[int]] = {}
    ereignisse: list[dict] = []
    seq = 0
    uebersprungen = 0

    for z in zeilen:
        try:
            bahn = int(z["Bahn"])
            wurfnummer = int(z["Wurfnummer"])
        except (KeyError, ValueError, TypeError):
            uebersprungen += 1
            continue

        gefallen = sorted(int(t) for t in (z.get("Kegelnummern") or "").split()
                          if t.isdigit())
        video_s = zahl(z.get("Zeitstempel_s"))
        ts = beginn + timedelta(seconds=video_s)

        vorher = stehend.get(bahn, list(ALLE_KEGEL))
        if ist_vollen(wurfnummer):
            # Volle: Vor JEDEM Wurf steht das volle Bild.
            vorher = list(ALLE_KEGEL)
        elif braucht_neues_bild(vorher):
            # Abraeumen, aber die Anlage hat neu aufgestellt. Deren Plan will
            # das als EIGENES Ereignis (Anforderung 4), nicht als Wurf mit
            # neun stehenden Kegeln.
            seq += 1
            ereignisse.append({
                "eventId": str(uuid.uuid5(
                    NAMENSRAUM, f"{lauf_name}|{bahn}|{video_s}|aufstellung")),
                "anlage": anlage, "bahn": bahn, "seq": seq,
                "ts": ts.isoformat(timespec="milliseconds"),
                "art": "aufstellung",
                "bildVor": vorher, "bildNach": list(ALLE_KEGEL),
                "konfidenz": 1.0,
            })
            vorher = list(ALLE_KEGEL)

        # WIDERSPRUCH NICHT WEGENTSCHEIDEN: Faellt ein Kegel, der laut Bild
        # gar nicht mehr stand, stimmt unser Bild nicht. Deren Drift-Erkennung
        # lebt genau davon, dass `bildVor` ehrlich mitkommt -- also wird der
        # Wurf normal gemeldet und der Widerspruch vermerkt.
        unmoeglich = [k for k in gefallen if k not in vorher]
        nachher = [k for k in vorher if k not in gefallen]

        seq += 1
        ereignis = {
            "eventId": str(uuid.uuid5(
                NAMENSRAUM, f"{lauf_name}|{bahn}|{video_s}|wurf")),
            "anlage": anlage, "bahn": bahn, "seq": seq,
            "ts": ts.isoformat(timespec="milliseconds"),
            "art": "wurf",
            "bildVor": vorher, "bildNach": nachher,
            "konfidenz": round(zahl(z.get("Confidence")), 2),
        }
        if unmoeglich:
            ereignis["hinweis"] = (
                f"Kegel {unmoeglich} galten als bereits gefallen -- unser "
                f"Bild und die Messung widersprechen sich hier.")
        ereignisse.append(ereignis)
        stehend[bahn] = nachher

    return ereignisse, uebersprungen


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path,
                   help="Laufordner unter debug/ mit wuerfe.csv")
    p.add_argument("--anlage", default="unbekannt",
                   help="Name der Anlage, geht so in jedes Ereignis")
    p.add_argument("--beginn", required=True,
                   help="Startzeit der Aufzeichnung, ISO: 2026-09-08T20:12:22")
    p.add_argument("--ziel", type=Path,
                   default=Path("erkennung_fixture.json"))
    a = p.parse_args()

    beginn = datetime.fromisoformat(a.beginn)
    zeilen = lies_wuerfe(a.lauf)
    ereignisse, uebersprungen = baue_ereignisse(
        zeilen, a.anlage, beginn, a.lauf.name)

    a.ziel.parent.mkdir(parents=True, exist_ok=True)
    a.ziel.write_text(json.dumps({
        "quelle": "Kegel_CV",
        "lauf": a.lauf.name,
        "anlage": a.anlage,
        "erzeugt": datetime.now().isoformat(timespec="seconds"),
        "hinweis": ("bildVor und bildNach sind die STEHENDEN Kegel. Kegel 1 "
                    "ist der vorderste, 9 der hinterste, 5 der Koenig -- "
                    "identisch zu KEGEL_LAYOUT in pin-scorer."),
        "ereignisse": ereignisse,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    wuerfe = [e for e in ereignisse if e["art"] == "wurf"]
    fehl = [e for e in wuerfe if e["bildVor"] == e["bildNach"]]
    print(f"{len(ereignisse)} Ereignisse -> {a.ziel}")
    print(f"  {len(wuerfe)} Wuerfe, davon {len(fehl)} ohne Kegel (Fehlwurf)")
    print(f"  {len(ereignisse) - len(wuerfe)} Aufstellungen")
    print(f"  {sum(1 for e in ereignisse if 'hinweis' in e)} mit Widerspruch")
    if uebersprungen:
        print(f"  {uebersprungen} Zeilen ohne Bahn/Wurfnummer uebersprungen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
