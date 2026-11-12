"""Grundlinie UND Ergebnis am ersten Plateau trennen -- gegen den Spieltag.

WOZU (Nutzer, 2026-09-29): *"Bekommen wir die 2 Wuerfe irgendwie
eingefangen?"* -- gemeint sind die beiden Wuerfe auf Bahn 4, die nach einem
Fehlercode mit 9 statt 1 Kegel gebucht wurden (Spiel 4 Wurf 23, Spiel 10
Wurf 21). Beide Male sagt die Tafelsumme 1, beide Male sind es +8.

WAS IN DER SPUR STEHT (gemessen an Lauf 2026-09-28_18-08-07, Bahn 4):

    47105  .....67.9   <- Fehlercode leuchtet in die Gruenphase nach
    47117  123456789
    47130  ...4567.9
    47140  123..6789   <- DAS ist die Grundlinie: 7 Kegel lagen schon
      ...  123..6789      (92 Messungen lang unveraendert, 23 Sekunden)
    47605  1234.6789   <- Kegel 4 faellt: der Wurf hatte 1 Kegel
    47674  Gruen-AUS

Heute nimmt die Grundlinie den KLEINSTEN Stand ueber eine Blinkperiode seit
dem vorigen Gruen-AUS. In der Pause war die Tafel 2,5 s lang KOMPLETT dunkel
(alle neun Lampen bei 180 gegen eine Schwelle von 215) -- also ist die
Grundlinie leer. Und das Ergebnis vereinigt alles ab dem Grundlinienfenster,
also auch den nachleuchtenden Fehlercode. Leer abgezogen von allen neun: 9.

DIE REGEL, DIE HIER GEPRUEFT WIRD, nennt den Fehlercode gar nicht:

    Grundlinie = der erste Stand, der `plateau` Sekunden unveraendert steht
                 und nach dem keine Lampe mehr ausgeht.
    Ergebnis   = die Vereinigung ab diesem Plateau.

Kegel fallen nur; sie stehen nicht wieder auf. Ein Stand, nach dem eine Lampe
wieder ausgeht, war deshalb nie ein Kegelstand, sondern eine Blinkphase --
das erledigt Fehlercode, Jubelblinken und dunkle Tafel mit demselben Satz.

Gemessen wird gegen die TAFELSUMME: SummeTafel(N+1) - SummeTafel(N) ist die
Kegelzahl von Wurf N. Sie ist der unabhaengigste Zeuge, den wir haben, und
anders als die Kegelziffer auf Bahn 4 auch lesbar.

Aufruf:

    .venv/Scripts/python.exe tools/simuliere_plateau.py \
        --lauf debug/Fehlercode-Filter_v2/lauf_2026-09-28_18-08-07 \
        --plateau 0.75
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
from pathlib import Path

FPS = 20.0          # Bildrate der Aufzeichnung; nur zum Umrechnen der Sekunden


def gruenzyklen(lauf: Path) -> dict[str, list[tuple[int, int]]]:
    """Je Bahn die Abschnitte (Gruen-AN, Gruen-AUS). UNKNOWN zaehlt nicht."""
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


def lampenspur(lauf: Path) -> dict[str, list[tuple[int, frozenset]]]:
    """Je Bahn die Folge (Frame, leuchtende Kegel) ueber ALLE Anlaesse.

    UNKNOWN gilt als aus -- so haelt es auch `aggregate_pin_readings`.
    """
    roh: dict[str, dict[int, set]] = collections.defaultdict(
        lambda: collections.defaultdict(set))
    with (lauf / "lampenspur.csv").open(encoding="utf-8-sig") as f:
        f.readline()
        for zeile in f:
            t = zeile.split(";")
            if len(t) < 6 or not t[3].startswith("pin_lamp_"):
                continue
            bahn, frame = t[2], int(t[0])
            eintrag = roh[bahn][frame]      # Frame anlegen, auch wenn dunkel
            if t[5] == "ON":
                eintrag.add(int(t[3].rsplit("_", 1)[1]))
    return {b: [(fr, frozenset(s)) for fr, s in sorted(m.items())]
            for b, m in roh.items()}


def ist_fehlercode(staende: list, mindest_dunkelphasen: int = 2) -> bool:
    """Wie `kegel_cv.models.readings.ist_fehlercode`, nur auf Mengen.

    Dauerleuchtender UND blinkender Teil zugleich besetzt -- das hat sonst
    nichts. Gezaehlt werden Dunkelphasen, nicht Wechsel (BUG-034).
    """
    if len(staende) < 3:
        return False
    blinkt = fest = False
    for pin in range(1, 10):
        folge = [pin in s for s in staende]
        dunkel = sum(1 for a, b in zip(folge, folge[1:]) if a and not b)
        if dunkel >= mindest_dunkelphasen:
            blinkt = True
        elif all(folge):
            fest = True
    return blinkt and fest


def huellen(messungen: list, periode: int) -> list:
    """Je Messung die Vereinigung ueber die naechste Blinkperiode.

    WOZU: Die Pruefung „nach diesem Stand geht keine Lampe mehr aus" ist gegen
    EINZELNE Messungen zu streng. Bahn 5 Kegel 8 liest sich regelmaessig
    faelschlich als aus (BUG-034) -- ein einziger Aussetzer verwirft sonst die
    richtige Grundlinie. Ueber eine Blinkperiode vereinigt, ueberlebt sie.
    """
    n = len(messungen)
    huelle = [frozenset()] * n
    j = 0
    vereinigt: list = []
    for i in range(n):
        while j < n and messungen[j][0] - messungen[i][0] <= periode:
            j += 1
        huelle[i] = frozenset().union(*[s for _, s in messungen[i:max(j, i + 1)]])
    del vereinigt
    return huelle


def plateau_schnitt(messungen: list, mindest_frames: int,
                    periode: int) -> tuple:
    """(Index des Plateaus, Grundlinie, Begruendung).

    Das erste Plateau, das lange genug steht und nach dem keine Lampe mehr
    ausgeht. Gemessen wird in FRAMES (aus Sekunden gerechnet), nicht in
    Messungen -- der Lesetakt wechselt innerhalb einer Gruenphase zwischen
    Anzeige (25 Frames) und Abtastung (2 bis 6 Frames).
    """
    n = len(messungen)
    if n == 0:
        return 0, frozenset(), "keine Messung"
    huelle = huellen(messungen, periode)
    i = 0
    while i < n:
        j = i
        while j + 1 < n and messungen[j + 1][1] == messungen[i][1]:
            j += 1
        # Das Plateau reicht bis zum naechsten ANDEREN Stand -- so lange stand
        # dieser Wert wirklich.
        ende = messungen[j + 1][0] if j + 1 < n else messungen[j][0]
        stand = messungen[i][1]
        if ende - messungen[i][0] >= mindest_frames:
            if all(stand <= huelle[k] for k in range(i, n)):
                return i, stand, f"Plateau ab Frame {messungen[i][0]}"
        i = j + 1
    return 0, messungen[0][1], "kein Plateau -- erste Messung"


def sollwerte(wuerfe: list) -> dict:
    """SummeTafel(N+1) - SummeTafel(N) ist die Kegelzahl von Wurf N."""
    nach_bahn = collections.defaultdict(list)
    for r in wuerfe:
        nach_bahn[r["Bahn"]].append(r)
    soll = {}
    for reihe in nach_bahn.values():
        reihe.sort(key=lambda r: int(r["Frame"]))
        for r, n in zip(reihe, reihe[1:]):
            if r["Spiel"] != n["Spiel"]:
                continue
            try:
                d = int(n["SummeTafel"]) - int(r["SummeTafel"])
            except (TypeError, ValueError):
                continue
            if 0 <= d <= 9:
                soll[id(r)] = d
    return soll, nach_bahn


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--plateau", type=float, default=0.75,
                   help="Mindestdauer des Plateaus in Sekunden")
    p.add_argument("--nachlauf", type=float, default=2.0,
                   help="Sekunden nach Gruen-AUS, die noch zum Wurf zaehlen")
    p.add_argument("--periode", type=float, default=1.5,
                   help="Blinkperiode in Sekunden -- so weit wird fuer die "
                        "Pruefung 'es geht nichts mehr aus' vereinigt")
    p.add_argument("--zeige", type=int, default=12)
    a = p.parse_args()

    mindest = int(round(a.plateau * FPS))
    nach = int(round(a.nachlauf * FPS))
    periode = int(round(a.periode * FPS))

    zyklen = gruenzyklen(a.lauf)
    starts = {b: [x for x, _ in v] for b, v in zyklen.items()}
    spur = lampenspur(a.lauf)

    with (a.lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as f:
        wuerfe = list(csv.DictReader(f, delimiter=";"))
    soll, nach_bahn = sollwerte(wuerfe)

    bilanz = collections.Counter()
    geaendert = []
    for bahn, reihe in nach_bahn.items():
        for r in reihe:
            if r["Herkunft"] != "gruenzyklus":
                continue
            fr = int(r["Frame"])
            i = bisect.bisect_right(starts.get(bahn, []), fr) - 1
            if i < 0:
                continue
            an, aus = zyklen[bahn][i]
            if not (an <= fr <= aus + 120):
                continue
            # Das Sammelfenster der Pipeline bleibt bis zum naechsten
            # Gruen-AN offen (BUG-010: die Anlage traegt die Summe erst kurz
            # davor ein). Genau so weit reicht auch die Folge, an der
            # `ist_fehlercode` entscheidet -- mit einem kurzen Fenster
            # erkennt man den Code NICHT, weil ein Blinken darin nur eine
            # einzige Dunkelphase hat.
            naechstes_an = (zyklen[bahn][i + 1][0]
                            if i + 1 < len(zyklen[bahn]) else aus + nach)
            vor = [(f, s) for f, s in spur.get(bahn, []) if an <= f <= aus]
            danach = [(f, s) for f, s in spur.get(bahn, [])
                      if aus < f <= aus + nach]
            # ZWEI VERSCHIEDENE FENSTER, und das ist kein Versehen:
            #
            #   * Das ERGEBNIS vereinigt nur die Abtastung kurz nach
            #     Gruen-AUS (`report_after_green_off`, 40 Frames).
            #   * Die FRAGE "ist das ein Fehlercode" braucht die ganze Pause
            #     bis zum naechsten Gruen-AN. In 4 Sekunden hat ein Blinken
            #     mit ~10 s Periode nur EINE Dunkelphase -- und
            #     `ist_fehlercode` verlangt zwei (BUG-034). Gemessen an
            #     Bahn 4 Spiel 10 Wurf 20: mit 4 s Fenster nicht erkannt,
            #     mit der ganzen Pause erkannt.
            code = [s for f, s in spur.get(bahn, [])
                    if aus < f < naechstes_an]
            if ist_fehlercode(code):
                bilanz["Fehlercode nach Gruen-AUS"] += 1
                danach = []
            fenster = vor + danach
            if len(fenster) < 3:
                continue
            k, grund, warum = plateau_schnitt(fenster, mindest, periode)
            ergebnis = frozenset().union(*[s for _, s in fenster[k:]])
            try:
                alt = int(r["Kegel"])
            except (TypeError, ValueError):
                continue
            s = soll.get(id(r))
            if s is None:
                continue
            # SCHWEIGT DIE REGEL, gilt weiter das heutige Verfahren. Ohne
            # Plateau weiss sie nichts -- und Raten waere schlimmer.
            if warum.startswith("Plateau"):
                neu = len(ergebnis - grund)
                bilanz["Plateau gefunden"] += 1
            else:
                neu = alt
            bilanz["geprueft"] += 1
            bilanz["alt richtig"] += (alt == s)
            bilanz["neu richtig"] += (neu == s)
            if alt != neu:
                bilanz["anders"] += 1
                if (alt == s) != (neu == s):
                    geaendert.append((bahn, r, sorted(grund), sorted(ergebnis),
                                      alt, neu, s, warum))

    n = max(1, bilanz["geprueft"])
    print(f"Plateau >= {a.plateau} s ({mindest} Frames), "
          f"Nachlauf {a.nachlauf} s\n")
    print(f"Geprueft (Tafelsumme lesbar): {bilanz['geprueft']}")
    print(f"  Buchung weicht ab:          {bilanz['anders']}")
    print(f"  heute  richtig:             {bilanz['alt richtig']}"
          f"  ({bilanz['alt richtig'] / n:.1%})")
    print(f"  Plateau richtig:            {bilanz['neu richtig']}"
          f"  ({bilanz['neu richtig'] / n:.1%})")
    print(f"  Plateau gefunden:           {bilanz['Plateau gefunden']}")
    besser = [g for g in geaendert if g[5] == g[6]]
    schlechter = [g for g in geaendert if g[4] == g[6]]
    print(f"\nBESSER {len(besser)} | SCHLECHTER {len(schlechter)}")
    for name, menge in (("BESSER", besser), ("SCHLECHTER", schlechter)):
        for bahn, r, grund, erg, alt, neu, s, warum in menge[:a.zeige]:
            print(f"  {name:<10} Bahn {bahn} Spiel {r['Spiel']:>2} Wurf "
                  f"{r['Wurfnummer']:>2} F{r['Frame']:>7}: Tafel {s}, "
                  f"heute {alt}, Plateau {neu}  "
                  f"Grundlinie {grund} Ergebnis {erg}  [{warum}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
