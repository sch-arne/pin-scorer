"""Prueft den Blink-Erkenner an einer etikettierten Liste echter Wuerfe.

WOZU (Nutzer, 2026-09-25): *"nimmst eine 8 die Wurfnummer > 15 hat, mit
1,2,3,4,6,7,8,9 / nimmst ein paar 9er, nimmst ein paar vom Raeumen (7 gespielt
danach 0,1,1) oder 7 danach 2 / dann BEIDE mit Fehlercode / und testest dich
so selbst dran rum"*

DIE ETIKETTEN KOMMEN NICHT AUS DEM ERKENNER. Sie kommen aus der Kegelziffer
und der Tafelsumme -- zwei Ziffernfelder, die nichts von den Lampen wissen:

    jubel       Alle Neune (Wurfbild 1..9, Ziffer 9) oder 8er Kranz
                (Wurfbild ohne die 5, Ziffer 8). Beide nur mit EINEM Wurf.
    ruhig       alles andere -- auch mehrteiliges Raeumen, dabei blinkt nichts
    fehlercode  die vier bekannten Wuerfe auf Bahn 4

DIE MASSE GEHOERT DAZU. Fuenf ausgesuchte Faelle zeigen nicht, was ein
Erkenner an einem Spieltag anrichtet. Geprueft wird deshalb gegen ALLE Wuerfe:
Die Sonderfaelle muessen erkannt werden, die restlichen rund 1650 muessen ihn
schweigen lassen.

DER ANLAUF WIRD GETRENNT BESTIMMT UND GEPRUEFT. Kurz nach Gruen-AN schaltet
die Anzeige vom vorigen Stand auf den neuen um; dabei wechseln Lampen, ohne
dass etwas blinkt. Der Erkenner braucht deshalb einen Anlauf. Ihn an denselben
Wuerfen zu eichen, an denen man ihn prueft, hiesse sich selbst zu bestaetigen
-- darum: ungerade Spiele eichen, gerade Spiele pruefen.

Aufruf:

    .venv/Scripts/python.exe tools/pruefe_blinkerkennung.py \
        --lauf debug/<quelle>/lauf_2026-09-24_11-54-45
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
from pathlib import Path

# Die vier Wuerfe, bei denen der Nutzer den Fehlercode an der Tafel abgelesen
# hat (Bahn 4, "Kegel im Kugelkran"). Gruen-AUS-Frames.
FEHLERCODE = {("4", 46676), ("4", 47674), ("4", 138158), ("4", 139069)}

# Ab so vielen AN/AUS-Wechseln gilt eine Lampe als blinkend. Ein einzelner
# Wechsel ist der fallende Kegel; eine einzelne Fehllesung (BUG-034) ebenso.
MIND_WECHSEL = 2

ARTEN = ("ruhig", "jubel", "fehlercode")


def gruenzyklen(lauf: Path) -> dict[str, list[tuple[int, int]]]:
    folge: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
    with (lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            folge[r["Bahn"]].append((int(r["Frame"]), r["Zustand"]))
    zyklen: dict[str, list[tuple[int, int]]] = collections.defaultdict(list)
    for bahn, reihe in folge.items():
        reihe.sort()
        an = vor = None
        for frame, zustand in reihe:
            if zustand == "ON" and vor != "ON":
                an = frame
            elif zustand == "OFF" and vor == "ON" and an is not None:
                zyklen[bahn].append((an, frame))
                an = None
            if zustand in ("ON", "OFF"):
                vor = zustand
    return zyklen


def zahl(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def etikett(reihe: dict, summe: int | None) -> str | None:
    """Was dieser Wurf ist -- entschieden von der KEGELZIFFER.

    `None` heisst: nicht etikettierbar, der Wurf faellt aus der Pruefung.

    ERSTE FASSUNG WAR FALSCH (2026-09-25): Sie verlangte zusaetzlich eine
    passende Tafelsumme und schrieb sonst "ruhig". Die Summe ist aber das
    schwaechste Feld -- sie fehlte bei 295 Wuerfen, und die landeten
    faelschlich in der Gegenprobe. Der Erkenner sah dadurch schlechter aus,
    als er ist. Wo die Ziffer schweigt, gibt es kein Etikett, nicht das
    Etikett "ruhig".
    """
    bild, ziffer = reihe["Kegelnummern"], reihe["Ziffer"]
    if not ziffer:
        return None
    # Die Summe widerspricht? Dann ist der Wurf selbst strittig und taugt
    # nicht als Massstab.
    if summe is not None and summe != int(ziffer):
        return None
    if bild == "1 2 3 4 5 6 7 8 9" and ziffer == "9":
        return "jubel"
    if bild == "1 2 3 4 6 7 8 9" and ziffer == "8":
        return "jubel"
    return "ruhig"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--anlauf", type=int, default=None,
                   help="Frames nach Gruen-AN, die uebersprungen werden. Ohne "
                        "Angabe wird er an den ungeraden Spielen gesucht.")
    a = p.parse_args()

    zyklen = gruenzyklen(a.lauf)
    starts = {b: [x for x, _ in v] for b, v in zyklen.items()}

    with (a.lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as f:
        reihen = list(csv.DictReader(f, delimiter=";"))
    proSpiel: dict[tuple, list[dict]] = collections.defaultdict(list)
    for r in reihen:
        proSpiel[(r["Bahn"], r["Spiel"])].append(r)

    label: dict[tuple, tuple[str, dict]] = {}
    for (bahn, _), w in proSpiel.items():
        for i, r in enumerate(w):
            if r["Herkunft"] != "gruenzyklus":
                continue
            fr = int(r["Frame"])
            zyk = next(((x, y) for x, y in zyklen.get(bahn, [])
                        if x <= fr <= y + 60), None)
            if zyk is None:
                continue
            summe = None
            if i + 1 < len(w):
                a_, b_ = zahl(r["SummeTafel"]), zahl(w[i + 1]["SummeTafel"])
                if a_ is not None and b_ is not None and 0 <= b_ - a_ <= 9:
                    summe = b_ - a_
            art = ("fehlercode" if (bahn, zyk[1]) in FEHLERCODE
                   else etikett(r, summe))
            if art is None:
                continue                    # kein Massstab, kein Urteil
            label[(bahn, zyk[1])] = (art, r)

    # Lampenspur einmal lesen: je Zyklus und Lampe die Messfolge, der Versatz
    # ist relativ zu Gruen-AN.
    folgen: dict[tuple, dict[int, list[tuple[int, str]]]] = \
        collections.defaultdict(lambda: collections.defaultdict(list))
    with (a.lauf / "lampenspur.csv").open(encoding="utf-8-sig") as f:
        f.readline()
        for zeile in f:
            t = zeile.split(";")
            if t[9].strip() == "live" or t[5] == "UNKNOWN":
                continue
            bahn, frame = t[2], int(t[0])
            if bahn not in starts:
                continue
            i = bisect.bisect_right(starts[bahn], frame) - 1
            if i < 0:
                continue
            an, aus = zyklen[bahn][i]
            if frame > aus:
                continue                    # nur die Gruenphase selbst
            folgen[(bahn, aus)][int(t[3].rsplit("_", 1)[1])].append(
                (frame - an, t[5]))

    def urteil(schluessel: tuple, anlauf: int) -> str:
        blinkt = fest = 0
        for messungen in folgen.get(schluessel, {}).values():
            werte = [z for versatz, z in sorted(messungen) if versatz >= anlauf]
            if not werte:
                continue
            wechsel = sum(1 for x, y in zip(werte, werte[1:]) if x != y)
            if wechsel >= MIND_WECHSEL:
                blinkt += 1
            elif wechsel == 0 and werte[0] == "ON":
                fest += 1
        if not blinkt:
            return "ruhig"
        return "jubel" if not fest else "fehlercode"

    eichen = {k: v for k, v in label.items() if int(v[1]["Spiel"]) % 2 == 1}
    pruefen = {k: v for k, v in label.items() if int(v[1]["Spiel"]) % 2 == 0}

    def bewerte(menge, anlauf):
        m = collections.Counter()
        for k, (art, _) in menge.items():
            m[(art, urteil(k, anlauf))] += 1
        richtig = sum(v for (x, y), v in m.items() if x == y)
        return richtig / max(1, sum(m.values())), m

    if a.anlauf is None:
        print("Anlauf an den UNGERADEN Spielen gesucht:")
        print(f"{'Anlauf':>7} {'Sekunden':>9} {'Trefferquote':>13}")
        bester, beste = 0, -1.0
        for anlauf in range(0, 141, 10):
            q, _ = bewerte(eichen, anlauf)
            print(f"{anlauf:>7} {anlauf / 20:>8.1f}s {q * 100:>12.1f}%")
            if q > beste:
                bester, beste = anlauf, q
        print(f"\n  gewaehlt: {bester} Frames ({bester / 20:.1f} s)\n")
    else:
        bester = a.anlauf

    for name, menge in (("EICHUNG (ungerade Spiele)", eichen),
                        ("PRUEFUNG (gerade Spiele)", pruefen)):
        q, m = bewerte(menge, bester)
        print(f"=== {name}: {sum(m.values())} Wuerfe, {q * 100:.1f} % richtig ===")
        print(f"{'Etikett | Urteil':<20}" + "".join(f"{x:>12}" for x in ARTEN))
        for art in ARTEN:
            print(f"{art:<20}" + "".join(f"{m[(art, u)]:>12}" for u in ARTEN))
        print()

    # Wer faellt durch? Die Fehlercodes einzeln, und ein paar Fehlalarme.
    print("Die vier Fehlercode-Wuerfe einzeln:")
    for schluessel in sorted(FEHLERCODE):
        if schluessel in label:
            r = label[schluessel][1]
            print(f"  Bahn {schluessel[0]} Frame {schluessel[1]:>7} "
                  f"(Spiel {r['Spiel']:>2}, Wurf {r['Wurfnummer']:>2}): "
                  f"Urteil {urteil(schluessel, bester)}")
        else:
            print(f"  Bahn {schluessel[0]} Frame {schluessel[1]:>7}: "
                  f"nicht in der Wurfliste")

    # DIE EINE ZAHL, AUF DIE ES ANKOMMT. "jubel" statt "ruhig" ist harmlos --
    # in beiden Faellen gilt die Vereinigung der Lampen. Gefaehrlich ist nur,
    # wenn der Erkenner bei einem gesunden Wurf "fehlercode" ruft, denn dann
    # wuerde ein richtiges Ergebnis verworfen.
    fehlalarm = [k for k, v in sorted(label.items())
                 if v[0] != "fehlercode" and urteil(k, bester) == "fehlercode"]
    gesund = sum(1 for v in label.values() if v[0] != "fehlercode")
    print(f"\nFEHLALARME (gesunder Wurf als Fehlercode beurteilt): "
          f"{len(fehlalarm)} von {gesund}")
    for k in fehlalarm[:20]:
        r = label[k][1]
        print(f"  Bahn {k[0]} Spiel {r['Spiel']:>2} Wurf {r['Wurfnummer']:>2} "
              f"Frame {k[1]:>7}  Wurfbild {r['Kegelnummern']:<20} "
              f"Ziffer {r['Ziffer'] or '-'}")

    falsch = [(k, v[0], urteil(k, bester)) for k, v in sorted(label.items())
              if v[0] != urteil(k, bester)]
    print(f"\nInsgesamt falsch beurteilt: {len(falsch)} von {len(label)}")
    for k, soll, ist in falsch[:25]:
        r = label[k][1]
        print(f"  Bahn {k[0]} Spiel {r['Spiel']:>2} Wurf {r['Wurfnummer']:>2} "
              f"Frame {k[1]:>7}  Wurfbild {r['Kegelnummern']:<20} "
              f"Ziffer {r['Ziffer'] or '-'}  soll {soll:<10} ist {ist}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
