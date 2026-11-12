# -*- coding: utf-8 -*-
"""Eine ECHTE Aufzeichnung der Erkennung in ein laufendes Spiel abspielen.

Quelle ist `erkennung/data/fixtures/erkennung_2026-09-08.json`: 65 Wuerfe aus dem
Mitschnitt vom 08.09.2026, von Kegel_CV aus dem Video gelesen. Das ist etwas anderes als
ausgedachte Wuerfe -- es sind die Zahlen, die die Erkennung an dem Abend WIRKLICH
geliefert hat, einschliesslich der Stellen, an denen sie sich selbst widersprochen hat
(Konfidenz 0.3/0.45, Hinweis "Kegel ... galten als bereits gefallen"). Genau daran soll
sich die Oberflaeche zeigen.

    # Bahn 4 der Aufzeichnung auf Bahn 3 des Spiels, 20-fach schneller:
    python tools/erkennung-aufzeichnung-abspielen.py . --bahn 4=3 --nur 3 --tempo 20

    # erst ansehen, nichts schicken:
    python tools/erkennung-aufzeichnung-abspielen.py . --bahn 4=3 --nur 3 --trocken

ZU DEN WURFNUMMERN: Die Aufzeichnung vom 08.09. enthaelt KEINE Tafelnummern -- damals
wurden sie nicht mitgeschrieben. Dieses Werkzeug zaehlt sie deshalb selbst mit, je Bahn ab
1, und schickt sie als `displayed_throw_number`. Das ist eine SAUBERE Tafel: Sie zeigt die
Nummer, die der Wurf wirklich hatte. Genau damit laesst sich pruefen, ob die App den Platz
aus der Nummer nimmt -- denn wenn sie es tut, steht am Ende jeder Wurf unter seiner eigenen
Nummer, auch wenn zwischendurch welche abgelehnt wurden.
Mit `--ohne-nummer N` bleibt jede N-te Nummer weg (so verhaelt sich eine Tafel, die mal
nicht lesbar ist). Diese Wuerfe muessen trotzdem eingetragen werden, am naechsten freien
Platz -- das ist die Zusicherung dahinter.

ZUR UMRECHNUNG: Die Aufzeichnung notiert in `bildVor`/`bildNach` die STEHENDEN Kegel.
Unsere Tabelle `erkannter_wurf` fuehrt in `pins` die GEFALLENEN. Gefallen ist also
bildVor ohne bildNach -- und `pins_count` deren Anzahl. Wer das verwechselt, bekommt
ueberall das Spiegelbild und merkt es erst an der Abraeum-Kette.

Ereignisse der Art `aufstellung` sind keine Wuerfe (die Maschine stellt neu auf) und
werden uebersprungen -- die App leitet den Satzanfang aus dem Spielstand ab, nicht aus
dem Video.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from erkennung_versand import Versand, aufraeumen  # noqa: E402

STANDARD = "erkennung/data/fixtures/erkennung_2026-09-08.json"


def lies_bahnplan(angaben) -> dict:
    """--bahn 4=3 --bahn 2=5  ->  {4: 3, 2: 5}"""
    plan = {}
    for a in angaben or []:
        if "=" not in a:
            raise SystemExit(f"--bahn erwartet VON=NACH, nicht '{a}'.")
        von, nach = a.split("=", 1)
        try:
            plan[int(von)] = int(nach)
        except ValueError:
            raise SystemExit(f"--bahn erwartet Zahlen, nicht '{a}'.")
    return plan


def wuerfe_aus(datei: Path, plan: dict, nur, ohne_nummer: int = 0) -> list:
    roh = json.loads(datei.read_text(encoding="utf-8"))
    ereignisse = roh.get("ereignisse") or []
    raus = []
    # Je BAHN DES SPIELS gezaehlt, nicht je Bahn der Aufzeichnung: Legt man zwei Bahnen
    # auf eine, teilen sie sich den Satz und damit die Wurfnummern.
    zaehler = {}
    for e in ereignisse:
        if e.get("art") != "wurf":
            continue
        # `--nur` zaehlt die Bahn der AUFZEICHNUNG, nicht die des Spiels. Sonst waere
        # `--bahn 4=3 --nur 3` zweideutig: Es traefe die umgelegte Bahn 4 UND die
        # eigene Bahn 3 der Aufzeichnung -- zwei verschiedene Spieler in einem Satz.
        if nur and e["bahn"] not in nur:
            continue
        bahn = plan.get(e["bahn"], e["bahn"])
        steht_vor = set(e.get("bildVor") or [])
        steht_nach = set(e.get("bildNach") or [])
        gefallen = sorted(steht_vor - steht_nach)
        zaehler[bahn] = zaehler.get(bahn, 0) + 1
        nummer = zaehler[bahn]
        if ohne_nummer and nummer % ohne_nummer == 0:
            nummer = None
        raus.append({
            "nummer": nummer,
            "seq": e.get("seq"),
            "zeit": datetime.fromisoformat(e["ts"]),
            "bahn": bahn,
            "quelle_bahn": e["bahn"],
            "holz": len(gefallen),
            "kegel": gefallen,
            "konfidenz": e.get("konfidenz"),
            "hinweis": e.get("hinweis"),
        })
    return raus


def beschreibe(w: dict, plan: dict) -> str:
    herkunft = (f"B{w['quelle_bahn']}->B{w['bahn']}"
                if w["quelle_bahn"] in plan else f"B{w['bahn']}")
    nr = f"Wurf {w['nummer']:>2}" if w["nummer"] is not None else "Wurf  ?"
    text = (f"  #{w['seq']:>3} {w['zeit'].strftime('%H:%M:%S')} {herkunft} {nr} "
            f"{w['holz']} Holz")
    if w["kegel"]:
        text += " (Kegel " + ",".join(str(k) for k in w["kegel"]) + ")"
    if (w["konfidenz"] or 1.0) < 0.8:
        text += f"   ! Konfidenz {w['konfidenz']}"
        if w["hinweis"]:
            text += " -- " + w["hinweis"]
    return text


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("wurzel", help="Projektverzeichnis (meist .)")
    p.add_argument("--datei", default=STANDARD, help=f"Aufzeichnung (Standard: {STANDARD})")
    p.add_argument("--bahn", action="append", metavar="VON=NACH",
                   help="Bahn der Aufzeichnung auf eine Bahn des Spiels legen")
    p.add_argument("--nur", type=int, action="append", metavar="BAHN",
                   help="nur diese Bahn(en) der AUFZEICHNUNG abspielen (vor --bahn)")
    p.add_argument("--tempo", type=float, default=20.0,
                   help="um diesen Faktor schneller als damals (Standard 20, 0 = ohne Pause)")
    p.add_argument("--anzahl", type=int, help="nach so vielen Wuerfen aufhoeren")
    p.add_argument("--hoechstpause", type=float, default=8.0,
                   help="laengste Pause in Sekunden, damit Spielerwechsel nicht langweilen")
    p.add_argument("--ohne-nummer", type=int, default=0, metavar="N",
                   help="jede N-te Wurfnummer weglassen (0 = alle mitschicken)")
    p.add_argument("--trocken", action="store_true", help="nur zeigen, nichts schicken")
    p.add_argument("--aufraeumen", action="store_true",
                   help="alle Zeilen dieser Werkzeuge wieder loeschen")
    a = p.parse_args()

    wurzel = Path(a.wurzel).resolve()
    if a.aufraeumen:
        aufraeumen(wurzel)
        return 0

    datei = Path(a.datei)
    if not datei.is_absolute():
        datei = wurzel / datei
    if not datei.is_file():
        raise SystemExit(f"{datei} gibt es nicht.")

    plan = lies_bahnplan(a.bahn)
    nur = set(a.nur or [])
    wuerfe = wuerfe_aus(datei, plan, nur, a.ohne_nummer)
    if a.anzahl:
        wuerfe = wuerfe[:a.anzahl]
    if not wuerfe:
        raise SystemExit("Nach der Auswahl bleibt kein Wurf uebrig -- --bahn/--nur pruefen.")

    dauer = (wuerfe[-1]["zeit"] - wuerfe[0]["zeit"]).total_seconds()
    print(f"{datei.name}: {len(wuerfe)} Wuerfe, damals {dauer / 60:.1f} Minuten")
    schwach = [w for w in wuerfe if (w["konfidenz"] or 1.0) < 0.8]
    if schwach:
        print(f"davon {len(schwach)} mit schwacher Konfidenz -- die sind der eigentliche Test.")
    ohne = [w for w in wuerfe if w["nummer"] is None]
    if ohne:
        print(f"{len(ohne)} ohne Tafelnummer -- die muessen trotzdem rein, "
              "am naechsten freien Platz.")

    if a.trocken:
        for w in wuerfe:
            print(beschreibe(w, plan))
        print("\n(trocken -- nichts geschickt)")
        return 0

    versand = Versand(wurzel)
    print(f"Als Erkenner angemeldet an {versand.projekt}\n")
    vorher = None
    for w in wuerfe:
        if vorher is not None and a.tempo > 0:
            warte = (w["zeit"] - vorher).total_seconds() / a.tempo
            time.sleep(max(0.0, min(warte, a.hoechstpause)))
        versand.schicke(versand.zeile(w["bahn"], w["holz"], kegel=w["kegel"],
                                      nummer=w["nummer"]))
        print(beschreibe(w, plan))
        vorher = w["zeit"]
    print(f"\n{len(wuerfe)} Wuerfe abgespielt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
