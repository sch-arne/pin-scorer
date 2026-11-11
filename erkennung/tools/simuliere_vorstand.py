"""Die Grundlinie ist der Stand des vorigen Wurfs -- gegen den Spieltag.

WOZU (Nutzer, 2026-09-29): *"wie waere es mit, die Grundlinie darf nur 0 sein
ODER derselbe Wert wie im Wurf zuvor?"*

Die Grundlinie wird heute GEMESSEN -- als kleinster Stand ueber eine
Blinkperiode seit dem vorigen Gruen-AUS. Das ist eine Messung, die schiefgehen
kann, und auf Bahn 4 ging sie zweimal schief: In der Pause nach einem
Fehlercode war die Tafel 2,5 bzw. 3,75 Sekunden KOMPLETT dunkel, der kleinste
Stand also leer, und aus einem Wurf mit 1 Kegel wurden 9.

Dabei ist die Grundlinie gar nicht frei: Kegel stehen nicht wieder auf. Nach
einem Wurf liegt genau das, was vorher lag, plus was dieser Wurf umgeworfen
hat. Nur beim Abraeumen -- alle neune unten -- stellt die Anlage neu auf, und
dann liegt nichts. Es gibt also nur ZWEI erlaubte Grundlinien:

    Grundlinie(N+1) = Ergebnis(N)        oder
    Grundlinie(N+1) = leer               (nur nach Abraeumen / Spielwechsel)

EINEN SCHRITT WEITER. Steht die Grundlinie fest, ohne gemessen zu werden, dann
sagt sie auch, WANN der Wurf beginnt: in dem Augenblick, in dem die Tafel
genau diesen Stand zeigt. Alles davor ist Nachleuchten des vorigen Wurfs --
Jubelblinken oder Fehlercode. Gemessen an Bahn 4, Spiel 4:

    47105  .....67.9   Fehlercode
    47117  123456789   Fehlercode
    47130  ...4567.9   Fehlercode, letztes Aufflackern
    47140  123..6789   <- HIER: genau das Ergebnis von Wurf 22
    47605  1234.6789   Kegel 4 faellt
    47674  Gruen-AUS                       Ergebnis - Grundlinie = {4} = 1

Damit wird beides an derselben Stelle geschnitten, und der Fehlercode kommt in
keiner der beiden Mengen vor -- ohne dass die Regel ihn je erwaehnt.

WANN SIE SCHWEIGT: Zeigt die Tafel den Vorstand in der ganzen Gruenphase nie
genau, weiss die Regel nichts (eine verdeckte Bahn, eine Lampe die nie hell
genug wird, ein verschluckter Wurf). Dann gilt unveraendert das heutige
Verfahren -- Raten waere schlimmer.

Gemessen wird gegen die TAFELSUMME: SummeTafel(N+1) - SummeTafel(N) ist die
Kegelzahl von Wurf N.

Aufruf:

    .venv/Scripts/python.exe tools/simuliere_vorstand.py \
        --lauf debug/Fehlercode-Filter_v2/lauf_2026-09-28_18-08-07
"""

from __future__ import annotations

import argparse
import bisect
import collections
import csv
from pathlib import Path

FPS = 20.0


def gruenzyklen(lauf: Path) -> dict:
    folge: dict = collections.defaultdict(list)
    with (lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter=";"):
            folge[r["Bahn"]].append((int(r["Frame"]), r["Zustand"]))
    zyklen: dict = collections.defaultdict(list)
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


def lampenspur(lauf: Path) -> dict:
    roh: dict = collections.defaultdict(lambda: collections.defaultdict(set))
    with (lauf / "lampenspur.csv").open(encoding="utf-8-sig") as f:
        f.readline()
        for zeile in f:
            t = zeile.split(";")
            if len(t) < 6 or not t[3].startswith("pin_lamp_"):
                continue
            eintrag = roh[t[2]][int(t[0])]
            if t[5] == "ON":
                eintrag.add(int(t[3].rsplit("_", 1)[1]))
    return {b: [(fr, frozenset(s)) for fr, s in sorted(m.items())]
            for b, m in roh.items()}


def ist_fehlercode(staende: list, mindest_dunkelphasen: int = 2,
                   mindest_blinkende: int = 1) -> bool:
    """Dauerleuchtender UND blinkender Teil zugleich besetzt.

    `mindest_blinkende` ist neu (Nutzer, 2026-09-29: *"es gab nur 2
    Fehlercodes im ganzen Spiel"*). Mit nur EINER blinkenden Lampe meldete die
    Regel ueber den Spieltag fuenf Codes -- vier davon waren Bahn 5 Kegel 8,
    die zweimal flackerte (BUG-034). Die beiden echten Codes hatten sechs und
    fuenf blinkende Lampen.
    """
    if len(staende) < 3:
        return False
    blinkende = 0
    fest = False
    for pin in range(1, 10):
        folge = [pin in s for s in staende]
        dunkel = sum(1 for a, b in zip(folge, folge[1:]) if a and not b)
        if dunkel >= mindest_dunkelphasen:
            blinkende += 1
        elif all(folge):
            fest = True
    return blinkende >= mindest_blinkende and fest


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--nachlauf", type=float, default=2.0)
    p.add_argument("--blinkende", type=int, default=2,
                   help="so viele Lampen muessen blinken, damit es ein "
                        "Fehlercode ist")
    p.add_argument("--nur-grundlinie", action="store_true",
                   help="nur die Grundlinie ersetzen, den Ergebnisbeginn "
                        "NICHT verschieben -- das ist die Regel des Nutzers "
                        "ohne den zusaetzlichen Schritt")
    p.add_argument("--zeige", type=int, default=15)
    a = p.parse_args()

    nach = int(round(a.nachlauf * FPS))
    zyklen = gruenzyklen(a.lauf)
    starts = {b: [x for x, _ in v] for b, v in zyklen.items()}
    spur = lampenspur(a.lauf)

    with (a.lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as f:
        wuerfe = list(csv.DictReader(f, delimiter=";"))
    nach_bahn: dict = collections.defaultdict(list)
    for r in wuerfe:
        nach_bahn[r["Bahn"]].append(r)
    for reihe in nach_bahn.values():
        reihe.sort(key=lambda r: int(r["Frame"]))

    soll = {}
    for reihe in nach_bahn.values():
        for r, n in zip(reihe, reihe[1:]):
            if r["Spiel"] != n["Spiel"]:
                continue
            try:
                d = int(n["SummeTafel"]) - int(r["SummeTafel"])
            except (TypeError, ValueError):
                continue
            if 0 <= d <= 9:
                soll[id(r)] = d

    bilanz = collections.Counter()
    geaendert = []
    for bahn, reihe in nach_bahn.items():
        vorstand: frozenset = frozenset()      # Stand nach dem vorigen Wurf
        vorspiel = None
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
            if r["Spiel"] != vorspiel:
                vorstand = frozenset()          # neues Spiel, neuer Satz
                vorspiel = r["Spiel"]

            vor = [(f, s) for f, s in spur.get(bahn, []) if an <= f <= aus]
            danach = [(f, s) for f, s in spur.get(bahn, [])
                      if aus < f <= aus + nach]
            if ist_fehlercode([s for _, s in danach],
                              mindest_blinkende=a.blinkende):
                bilanz["Fehlercode"] += 1
                danach = []
            fenster = vor + danach
            if len(fenster) < 3:
                continue
            try:
                alt = int(r["Kegel"])
            except (TypeError, ValueError):
                continue

            # DER ANKER: das erste Bild, das eine der BEIDEN erlaubten
            # Grundlinien zeigt -- leer oder den Stand des vorigen Wurfs.
            #
            # WARUM ZWEI UND NICHT EINE: Bei den VOLLEN stellt die Anlage nach
            # jedem Wurf neu auf, die Grundlinie ist dort immer leer. Beim
            # ABRAEUMEN bleibt liegen, was lag. Welches von beidem gerade
            # gilt, muss man nicht wissen -- die Tafel zeigt es zu Beginn der
            # Gruenphase. Alles, was WEDER das eine NOCH das andere ist, ist
            # Nachleuchten des vorigen Wurfs: Jubelblinken oder Fehlercode.
            erlaubt = (frozenset(), vorstand)
            anker = next((k for k, (_, st) in enumerate(fenster)
                          if st in erlaubt), None)
            if anker is None:
                neu, warum = alt, "kein Anker -- heutiges Verfahren"
            else:
                grundlinie = fenster[anker][1]
                beginn = 0 if a.nur_grundlinie else anker
                ergebnis = frozenset().union(*[s for _, s in fenster[beginn:]])
                neu = len(ergebnis - grundlinie)
                warum = (f"Anker F{fenster[anker][0]}, "
                         f"Grundlinie {sorted(grundlinie)}")
                bilanz["Anker gefunden"] += 1

            # Der Stand fuer den naechsten Wurf: gemessenes Ende der
            # Gruenphase. Liegen alle neun, stellt die Anlage neu auf.
            ende = frozenset().union(*[s for _, s in fenster[-3:]])
            vorstand = frozenset() if len(ende) >= 9 else ende

            s = soll.get(id(r))
            if s is None:
                continue
            bilanz["geprueft"] += 1
            bilanz["alt richtig"] += (alt == s)
            bilanz["neu richtig"] += (neu == s)
            if alt != neu:
                bilanz["anders"] += 1
                if (alt == s) != (neu == s):
                    geaendert.append((bahn, r, alt, neu, s, warum))

    n = max(1, bilanz["geprueft"])
    modus = ("nur Grundlinie" if a.nur_grundlinie
             else "Grundlinie UND Ergebnisbeginn")
    print(f"{modus}, blinkende Lampen fuer Fehlercode >= {a.blinkende}\n")
    print(f"Geprueft (Tafelsumme lesbar): {bilanz['geprueft']}")
    print(f"  Anker gefunden:             {bilanz['Anker gefunden']}")
    print(f"  Fehlercodes:                {bilanz['Fehlercode']}")
    print(f"  Buchung weicht ab:          {bilanz['anders']}")
    print(f"  heute  richtig:             {bilanz['alt richtig']}"
          f"  ({bilanz['alt richtig'] / n:.1%})")
    print(f"  Regel  richtig:             {bilanz['neu richtig']}"
          f"  ({bilanz['neu richtig'] / n:.1%})")
    besser = [g for g in geaendert if g[3] == g[4]]
    schlechter = [g for g in geaendert if g[2] == g[4]]
    print(f"\nBESSER {len(besser)} | SCHLECHTER {len(schlechter)}")
    for name, menge in (("BESSER", besser), ("SCHLECHTER", schlechter)):
        for bahn, r, alt, neu, s, warum in menge[:a.zeige]:
            print(f"  {name:<10} Bahn {bahn} Spiel {r['Spiel']:>2} Wurf "
                  f"{r['Wurfnummer']:>2} F{r['Frame']:>7}: Tafel {s}, "
                  f"heute {alt}, Regel {neu}   [{warum}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
