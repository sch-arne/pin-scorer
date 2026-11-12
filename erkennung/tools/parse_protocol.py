"""Liest das handgefuehrte Wurfprotokoll (PDF) als Bodenwahrheit ein.

Zweck: Bis jetzt wurde die Erkennung immer nur gegen sich selbst geprueft --
Lampen gegen Ziffern, Ziffern gegen Summenkette. Beide Quellen stammen aus
demselben Bild. Wo sie sich einig sind, kann trotzdem beides falsch sein.

Das vom Nutzer von Hand gefuehrte Protokoll ist die erste Quelle, die
UNABHAENGIG vom Bild entstanden ist. Damit laesst sich zum ersten Mal sagen, ob
die Erkennung recht hat -- nicht nur, ob sie in sich stimmig ist.

Aufbau des Protokolls: eine Seite je Spieler, darauf vier Saetze. Die Spieler
wechseln die Bahn nach jedem Satz, deshalb steht die Bodenwahrheit einer Bahn
ueber vier Seiten verteilt. Diese Datei dreht das um: je Bahn eine
chronologische Wurffolge -- genau die Sicht, die auch das Werkzeug hat.

Aufruf:
    .venv/Scripts/python.exe tools/parse_protocol.py [PDF]

Ergebnis:
    data/ground_truth/wurfprotokoll_langes_video.csv
"""

from __future__ import annotations

import csv
import re
import sys
import zlib
from pathlib import Path

PDF = Path("Wurfprotokoll_LangesVideo.pdf")
AUSGABE = Path("data/ground_truth/wurfprotokoll_langes_video.csv")

WUERFE_JE_MODUS = 15      # Volle, dann Abraeumen
SAETZE_JE_SPIELER = 4


# ------------------------------------------------------------------ PDF-Text

def _literale(block: bytes):
    """Alle `( ... )`-Literale eines Inhaltsstroms, mit Escape-Behandlung.

    Von Hand statt mit einer Bibliothek, weil das Projekt keine PDF-Abhaengigkeit
    braucht -- und weil hier nur Ziffern und ASCII vorkommen.
    """
    i, n = 0, len(block)
    while i < n:
        if block[i:i + 1] != b"(":
            i += 1
            continue
        i += 1
        tiefe, teile = 1, []
        while i < n:
            zeichen = block[i:i + 1]
            if zeichen == b"\\":
                naechstes = block[i + 1:i + 2]
                # Oktale Escapes (\374 = ue, \344 = ae). Ohne diesen Zweig
                # landen die Ziffern als Text im Ergebnis -- und in einem
                # Protokoll aus lauter Zahlen faellt das nicht auf.
                if naechstes.isdigit():
                    ziffern = b""
                    j = i + 1
                    while j < n and len(ziffern) < 3 and block[j:j + 1].isdigit():
                        ziffern += block[j:j + 1]
                        j += 1
                    teile.append(bytes([int(ziffern, 8) & 0xFF]))
                    i = j
                    continue
                teile.append({b"n": b"\n", b"r": b"\r", b"t": b"\t"}.get(
                    naechstes, naechstes))
                i += 2
                continue
            if zeichen == b"(":
                tiefe += 1
            elif zeichen == b")":
                tiefe -= 1
                if tiefe == 0:
                    i += 1
                    break
            teile.append(zeichen)
            i += 1
        yield b"".join(teile)


def pdf_text(pfad: Path) -> str:
    daten = pfad.read_bytes()
    stuecke = []
    for treffer in re.finditer(rb"stream\r?\n(.*?)endstream", daten, re.S):
        try:
            stuecke.append(zlib.decompress(treffer.group(1)))
        except zlib.error:
            pass
    inhalt = b"\n".join(stuecke)

    text = []
    for treffer in re.finditer(rb"BT(.*?)ET", inhalt, re.S):
        for literal in _literale(treffer.group(1)):
            text.append(literal.decode("latin-1"))
        text.append("\n")
    return "".join(text)


# -------------------------------------------------------------- Protokoll

class Protokollfehler(RuntimeError):
    """Das PDF sieht anders aus als erwartet -- lieber abbrechen als raten."""


def _wuerfe_lesen(zeichen: str, pos: int, von: int, bis: int) -> tuple[list[int], int]:
    """Liest Paare `<Kegel><Wurfnummer>` -- die Wurfnummer ist bekannt.

    Dadurch ist die Zerlegung eindeutig: `915` kann nur `9` bei Wurf `15` sein,
    nie `91` bei Wurf `5`. Ohne diese Erwartung waere die Ziffernkette
    mehrdeutig.
    """
    kegel = []
    for nummer in range(von, bis + 1):
        if pos >= len(zeichen) or not zeichen[pos].isdigit():
            raise Protokollfehler(f"Wurf {nummer}: keine Kegelziffer bei {pos}")
        kegel.append(int(zeichen[pos]))
        pos += 1
        erwartet = str(nummer)
        if zeichen[pos:pos + len(erwartet)] != erwartet:
            raise Protokollfehler(
                f"Wurf {nummer}: erwartete Wurfnummer '{erwartet}', "
                f"gefunden '{zeichen[pos:pos + 4]}'")
        pos += len(erwartet)
    return kegel, pos


def _summe_lesen(zeichen: str, pos: int, erwartet: int) -> int:
    """Zieht eine Summe ab, deren Wert bereits feststeht -- als Gegenprobe.

    Die Summe steht ohne Trenner zwischen den Wuerfen. Statt zu raten, wo sie
    endet, wird die berechnete Summe eingesetzt und geprueft, ob sie dasteht.
    Stimmt sie nicht, ist die Zerlegung falsch gelaufen -- und das soll
    auffallen, nicht durchrutschen.
    """
    text = str(erwartet)
    if zeichen[pos:pos + len(text)] != text:
        raise Protokollfehler(
            f"Summe {erwartet} erwartet, gefunden '{zeichen[pos:pos + 8]}'")
    return pos + len(text)


def seiten_teilen(text: str) -> list[str]:
    """Zerlegt das PDF in Spielerseiten.

    Zwei Ausgabeformate sind aufgetreten und werden beide bedient:

        alt   jede Seite beginnt mit "WURFPROTOKOLL", Spielername vorhanden,
              Satznummern und Satzergebnisse mit ausgedruckt
        neu   keine Seitenmarke, kein Name, keine Satznummer, kein Satzergebnis

    Gemeinsam ist beiden der Seitenkopf "Bahn N Name". Danach wird geteilt,
    wenn die alte Marke fehlt.
    """
    if "WURFPROTOKOLL" in text:
        return text.split("WURFPROTOKOLL")[1:]

    grenzen = [m.start() for m in re.finditer(r"Bahn\s*\d\s*Name", text)]
    if not grenzen:
        raise Protokollfehler(
            "Weder 'WURFPROTOKOLL' noch ein Seitenkopf 'Bahn N Name' gefunden "
            "-- ist das PDF ein Wurfprotokoll?")
    grenzen.append(len(text))
    return [text[a:b] for a, b in zip(grenzen[:-1], grenzen[1:])]


def seite_lesen(seite: str) -> tuple[str, list[dict]]:
    """Eine Spielerseite: vier Saetze zu je 30 Wuerfen.

    Der Spielername steht nur im alten Format; fehlt er, wird die Startbahn als
    Bezeichnung verwendet. Die Saetze werden ueber ihre REIHENFOLGE nummeriert
    statt ueber eine ausgedruckte Nummer -- die gibt es im neuen Format nicht,
    und die Reihenfolge ist ohnehin die verlaesslichere Angabe.
    """
    kopf = re.search(r"Bahn\s*(\d)\s*Name\s*(.*?)\s*Kegelbild", seite, re.S)
    startbahn = kopf.group(1) if kopf else "?"
    spieler = (kopf.group(2).strip() if kopf and kopf.group(2).strip()
               else f"Start Bahn {startbahn}")
    # Im Protokoll vom 2026-08-30 folgt auf den Namen ohne Trennung die
    # Mannschaft ("Spieler BMannschaftHeimmannschaft"). Alles ab
    # `Mannschaft` gehoert nicht zum Namen.
    spieler = re.split(r"Mannschaft", spieler)[0].strip()

    zeichen = re.sub(r"\s+", "", seite)
    saetze = []
    pos = 0

    for satznummer in range(1, SAETZE_JE_SPIELER + 1):
        marke = re.compile(r"Bahn(\d)Vo").search(zeichen, pos)
        if marke is None:
            raise Protokollfehler(
                f"Satz {satznummer} nicht gefunden (Marke 'Bahn<N>Vo')")
        bahn = int(marke.group(1))
        pos = marke.end()

        volle, pos = _wuerfe_lesen(zeichen, pos, 1, WUERFE_JE_MODUS)
        pos = _summe_lesen(zeichen, pos, sum(volle))

        # Im alten Format steht zwischen Vollen-Summe und "Kr" das
        # Satzergebnis. Im neuen fehlt es -- dann bleibt der Zwischenraum leer.
        kr = zeichen.find("Kr", pos)
        if kr < 0:
            raise Protokollfehler(f"Satz {satznummer}: kein 'Kr' gefunden")
        ergebnis_text = zeichen[pos:kr]
        pos = kr + 2

        abraeumen, pos = _wuerfe_lesen(zeichen, pos, WUERFE_JE_MODUS + 1,
                                       2 * WUERFE_JE_MODUS)
        pos = _summe_lesen(zeichen, pos, sum(abraeumen))

        ergebnis = sum(volle) + sum(abraeumen)
        if ergebnis_text and ergebnis_text != str(ergebnis):
            raise Protokollfehler(
                f"Satz {satznummer}: Ergebnis '{ergebnis_text}' passt nicht zu "
                f"{sum(volle)} + {sum(abraeumen)} = {ergebnis}")

        saetze.append({"satz": satznummer, "bahn": bahn, "spieler": spieler,
                       "volle": volle, "abraeumen": abraeumen,
                       "ergebnis": ergebnis})
    return spieler, saetze


def _dateiname(pdf: Path) -> str:
    """`Wurfprotokoll_Spieltag_1.pdf` -> `wurfprotokoll_spieltag_1.csv`."""
    rein = "".join(z if (z.isalnum() or z == "_") else "_" for z in pdf.stem)
    return f"{rein.lower()}.csv"


def main() -> int:
    pfad = Path(sys.argv[1]) if len(sys.argv) > 1 else PDF
    if not pfad.exists():
        print(f"PDF nicht gefunden: {pfad}")
        return 1

    # Der Ausgabename folgt dem PDF. WARUM: Solange er fest verdrahtet war,
    # ueberschrieb jedes zweite Protokoll die Bodenwahrheit des ersten --
    # lautlos, denn beide Dateien sehen gleich aus. Am 2026-08-30 passiert.
    ausgabe = (Path(sys.argv[2]) if len(sys.argv) > 2 else
               AUSGABE.with_name(_dateiname(pfad)))

    seiten = seiten_teilen(pdf_text(pfad))
    print(f"{pfad.name}: {len(seiten)} Seiten\n")

    alle: list[dict] = []
    for seite in seiten:
        spieler, saetze = seite_lesen(seite)
        gesamt = sum(s["ergebnis"] for s in saetze)
        bahnen = " ".join(f"B{s['bahn']}:{s['ergebnis']}" for s in saetze)
        print(f"  {spieler:<10} {bahnen}   GESAMT {gesamt}")
        alle.extend(saetze)

    # Umsortieren: je Bahn eine chronologische Wurffolge, Satz 1 zuerst.
    # Das ist die Sicht des Werkzeugs -- es sieht eine Tafel, keinen Spieler.
    zeilen = []
    for satz in sorted(alle, key=lambda s: (s["bahn"], s["satz"])):
        laufend = 0
        for modus, kegel_liste, versatz in (("Volle", satz["volle"], 0),
                                            ("Abraeumen", satz["abraeumen"],
                                             WUERFE_JE_MODUS)):
            for i, kegel in enumerate(kegel_liste, start=1):
                laufend += kegel
                zeilen.append({
                    "Bahn": satz["bahn"],
                    "Satz": satz["satz"],
                    "Spieler": satz["spieler"],
                    "Wurf": versatz + i,
                    "Modus": modus,
                    "Kegel": kegel,
                    "LaufendeSumme": laufend,
                })

    ausgabe.parent.mkdir(parents=True, exist_ok=True)
    with ausgabe.open("w", encoding="utf-8-sig", newline="") as datei:
        schreiber = csv.DictWriter(datei, fieldnames=list(zeilen[0]), delimiter=";")
        schreiber.writeheader()
        schreiber.writerows(zeilen)

    print(f"\n{len(zeilen)} Wuerfe -> {ausgabe}\n")
    print(f"{'Bahn':<6}{'Satz 1':>8}{'Satz 2':>8}{'Satz 3':>8}{'Satz 4':>8}{'gesamt':>9}")
    for bahn in sorted({s["bahn"] for s in alle}):
        satz_ergebnisse = [s["ergebnis"] for s in
                           sorted((x for x in alle if x["bahn"] == bahn),
                                  key=lambda s: s["satz"])]
        print(f"{bahn:<6}" + "".join(f"{e:>8}" for e in satz_ergebnisse)
              + f"{sum(satz_ergebnisse):>9}")
    print(f"\nKegel insgesamt: {sum(z['Kegel'] for z in zeilen)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
