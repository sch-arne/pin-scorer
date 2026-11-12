"""Vergleicht Ziffernerkenner auf demselben beschrifteten Datensatz.

WOZU: Der heutige Erkenner tastet sieben Segmentflaechen ab, die geometrisch
aus der Zellenbox abgeleitet werden. Gemessen ueber 4320 beleuchtete Zellen
ergeben nur 58 % davon ein GUELTIGES Muster; bei weiteren 32 % passt keines,
und es wird auf das naechstliegende geraten. Auf einem Sieben-Segment-Code
liegen 0/8, 8/9, 3/9 und 5/6 jeweils genau einen Schritt auseinander -- die
Reparatur ist dort ein Muenzwurf, der als Ergebnis auftritt.

Der Verdacht: Bei 8x14 px je Ziffer ist ein senkrechtes Segment rund 2 px
breit. Ein Versatz von einem Pixel verschiebt die Messflaeche um die halbe
Segmentbreite. Die Form im Bild ist dagegen sauber -- eine Clusterung ohne
jede Segmentlogik (`tools/cluster_digits.py`) liefert klar erkennbare Ziffern.

Geprueft werden deshalb Erkenner, die die FORM als Ganzes vergleichen statt sie
in sieben Flaechen zu zerlegen.

TRENNUNG VON LERNEN UND PRUEFEN: Aufeinanderfolgende Frames zeigen dieselbe
Ziffer und sind damit fast identisch. Ein zufaelliger Schnitt wuerde
Nachbarbilder auf beide Seiten verteilen, und jeder Erkenner saehe im Test,
was er im Lernen schon hatte. Geteilt wird deshalb nach ZUSAMMENHAENGENDEN
LAEUFEN gleicher Beschriftung -- ein ganzer Lauf geht immer nur auf eine Seite.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def laeufe_teilen(werte: np.ndarray, quellen: np.ndarray,
                  ) -> tuple[np.ndarray, np.ndarray]:
    """Zusammenhaengende Laeufe gleicher Beschriftung abwechselnd aufteilen."""
    lernen = np.zeros(len(werte), dtype=bool)
    lauf_nr = 0
    for i in range(len(werte)):
        if i > 0 and (werte[i] != werte[i - 1] or quellen[i] != quellen[i - 1]):
            lauf_nr += 1
        lernen[i] = (lauf_nr % 2 == 0)
    return lernen, ~lernen


def naechster_mittelpunkt(lern_x, lern_y, test_x) -> np.ndarray:
    """Je Ziffer ein Mittelbild; zugeordnet wird das aehnlichste."""
    mitten = np.stack([lern_x[lern_y == z].mean(axis=0) for z in range(10)])
    abstand = ((test_x[:, None, :] - mitten[None, :, :]) ** 2).sum(axis=2)
    return abstand.argmin(axis=1)


def knn(lern_x, lern_y, test_x, k: int) -> np.ndarray:
    """k naechste Nachbarn -- in Bloecken, damit der Speicher reicht."""
    ergebnis = np.empty(len(test_x), dtype=np.int64)
    for anfang in range(0, len(test_x), 256):
        stueck = test_x[anfang:anfang + 256]
        abstand = ((stueck[:, None, :] - lern_x[None, :, :]) ** 2).sum(axis=2)
        naechste = np.argpartition(abstand, k, axis=1)[:, :k]
        for i, reihe in enumerate(naechste):
            ergebnis[anfang + i] = np.bincount(lern_y[reihe],
                                               minlength=10).argmax()
    return ergebnis


def bericht(name: str, wahr: np.ndarray, geraten: np.ndarray) -> None:
    treffer = wahr == geraten
    print(f"\n{name}: {treffer.mean():.1%} richtig "
          f"({int(treffer.sum())} von {len(wahr)})")
    print(f"   {'Ziffer':>7} {'Anzahl':>7} {'richtig':>8}   haeufigste Verwechslung")
    for z in range(10):
        maske = wahr == z
        n = int(maske.sum())
        if not n:
            continue
        quote = float(treffer[maske].mean())
        falsch = geraten[maske][~treffer[maske]]
        hinweis = ""
        if falsch.size:
            # -1 steht fuer "unlesbar" -- das ist keine Verwechslung, sondern
            # ein Ausfall, und gehoert getrennt ausgewiesen.
            ausfall = int((falsch < 0).sum())
            echt = falsch[falsch >= 0]
            teile = []
            if echt.size:
                zaehler = np.bincount(echt, minlength=10)
                teile.append(f"-> {int(zaehler.argmax())} ({int(zaehler.max())}x)")
            if ausfall:
                teile.append(f"{ausfall}x unlesbar")
            hinweis = "  ".join(teile)
        print(f"   {z:>7} {n:>7} {quote:>8.1%}   {hinweis}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--samples", type=Path,
                   default=Path("data/ground_truth/ziffern.npz"))
    p.add_argument("--k", type=int, default=3)
    p.add_argument("--lanes", default=None,
                   help="nur diese Bahnen, mit Komma getrennt. GEMESSEN: Auf "
                        "Bahn 4 und 5 ist die Lampenlesung selbst unsicher, "
                        "und damit die Beschriftung. Wer dort misst, misst "
                        "die Lampen, nicht die Ziffern.")
    a = p.parse_args()

    d = np.load(a.samples, allow_pickle=True)
    masken, werte, quellen, alt = d["masken"], d["werte"], d["quellen"], d["alt"]
    if a.lanes:
        erlaubt = {f"_b{n.strip()}" for n in a.lanes.split(",")}
        behalten = np.array([any(q.endswith(e) for e in erlaubt)
                             for q in quellen])
        masken, werte = masken[behalten], werte[behalten]
        quellen, alt = quellen[behalten], alt[behalten]
        print(f"Nur Bahnen {a.lanes}: {len(masken)} Bilder")

    x = masken.reshape(len(masken), -1).astype(np.float32) / 255.0
    y = werte.astype(np.int64)

    lernen, testen = laeufe_teilen(y, quellen)
    print(f"{len(x)} Bilder: {int(lernen.sum())} zum Lernen, "
          f"{int(testen.sum())} zum Pruefen "
          f"(nach zusammenhaengenden Laeufen getrennt)")

    # --- Der heutige Erkenner, auf DEMSELBEN Pruefteil ---
    heute = np.array([int(z) if z.isdigit() else -1 for z in alt])[testen]
    wahr = y[testen]
    unlesbar = int((heute < 0).sum())
    bericht(f"Heute (Segmentabtastung), {unlesbar} davon unlesbar",
            wahr, np.where(heute < 0, -1, heute))

    lx, ly = x[lernen], y[lernen]
    bericht("Naechster Mittelpunkt (ein Mittelbild je Ziffer)",
            wahr, naechster_mittelpunkt(lx, ly, x[testen]))
    bericht(f"{a.k} naechste Nachbarn", wahr, knn(lx, ly, x[testen], a.k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
