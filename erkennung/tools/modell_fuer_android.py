"""Macht das Personenmodell fuer das OpenCV des Telefons lesbar.

DAS PROBLEM. Auf dem Geraet laeuft OpenCV 4.5.1 -- das Neueste, was Chaquopy
anbietet. Sein ONNX-Leser bricht an YOLOX ab:

    Slice layer only supports steps = 1

Gemeint ist die **Focus-Schicht** am Netzeingang. Sie zerlegt das Bild in vier
Viertel, indem sie es mit Schrittweite 2 abtastet, und legt die Viertel als
Kanaele nebeneinander:

    472 = Bild[.., 0::2, 0::2]    oben links
    492 = Bild[.., 1::2, 0::2]    unten links
    482 = Bild[.., 0::2, 1::2]    oben rechts
    502 = Bild[.., 1::2, 1::2]    unten rechts
    503 = Concat(472, 492, 482, 502)      12 Kanaele aus 3

Im Graphen sind das acht Slice-Knoten und ein Concat. Neuere ONNX-Leser koennen
Schrittweiten, 4.5.1 nicht.

DIE LOESUNG. Dieselbe Zerlegung leistet **eine einzige Faltung**: Kern 2x2,
Schrittweite 2, 3 Eingangs- und 12 Ausgangskanaele, und in den Gewichten steht
genau eine Eins je Ausgangskanal -- an der Stelle des Viertels, das er holen
soll. Ausgangskanal p*3+c nimmt Eingangskanal c am Versatz des Viertels p.

Das ist keine Naeherung, sondern dieselbe Rechnung in anderer Schreibweise.
Und weil es dieselbe ist, laesst sie sich BEWEISEN: Das Werkzeug laesst beide
Netze auf demselben Zufallsbild laufen und vergleicht die Ausgaben. Weicht
irgendetwas ab, bricht es ab und schreibt nichts.

    .venv/Scripts/python.exe tools/modell_fuer_android.py

Braucht `onnx` (nur zum Umbauen, nicht zur Laufzeit):

    .venv/Scripts/python.exe -m pip install onnx
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

WURZEL = Path(__file__).resolve().parents[1]

# Reihenfolge der Viertel, wie YOLOX sie aneinanderhaengt: oben links,
# unten links, oben rechts, unten rechts -- als (Zeilenversatz, Spaltenversatz).
VIERTEL = ((0, 0), (1, 0), (0, 1), (1, 1))


def finde_focus(graph):
    """Sucht die acht Slice-Knoten und ihren Concat.

    Erkannt wird das Muster, nicht der Name: ein Concat auf Achse 1, dessen
    vier Eingaenge ueber je zwei Slice-Knoten am selben Tensor haengen.
    """
    nach_ausgang = {a: k for k in graph.node for a in k.output}
    for knoten in graph.node:
        if knoten.op_type != "Concat" or len(knoten.input) != 4:
            continue
        if not any(a.name == "axis" and a.i == 1 for a in knoten.attribute):
            continue
        kette, quellen = [], set()
        for eingang in knoten.input:
            zweiter = nach_ausgang.get(eingang)
            if zweiter is None or zweiter.op_type != "Slice":
                break
            erster = nach_ausgang.get(zweiter.input[0])
            if erster is None or erster.op_type != "Slice":
                break
            kette.append((erster, zweiter))
            quellen.add(erster.input[0])
        if len(kette) == 4 and len(quellen) == 1:
            return knoten, kette, quellen.pop()
    return None, None, None


def wert(graph, name: str):
    from onnx import numpy_helper
    for i in graph.initializer:
        if i.name == name:
            return numpy_helper.to_array(i)
    return None


def versatz_der_kette(graph, erster, zweiter) -> tuple[int, int]:
    """Aus welchem Viertel holt dieses Slice-Paar?

    Der erste Slice arbeitet auf der Zeilenachse, der zweite auf der
    Spaltenachse -- der Startwert ist der Versatz.
    """
    zeile = int(wert(graph, erster.input[1])[0])
    spalte = int(wert(graph, zweiter.input[1])[0])
    return zeile, spalte


def baue_um(quelle: Path, ziel: Path) -> tuple[int, int]:
    import onnx
    from onnx import helper, numpy_helper

    modell = onnx.load(str(quelle))
    graph = modell.graph
    concat, kette, eingang = finde_focus(graph)
    if concat is None:
        raise SystemExit(f"{quelle.name}: keine Focus-Schicht gefunden -- "
                         "entweder schon umgebaut oder ein anderes Netz.")

    # Welcher Concat-Eingang holt welches Viertel? Die Reihenfolge im Netz ist
    # NICHT die naheliegende, deshalb wird sie ausgelesen statt angenommen.
    reihenfolge = []
    for eingangsname in concat.input:
        paar = next(p for p in kette if p[1].output[0] == eingangsname)
        reihenfolge.append(versatz_der_kette(graph, *paar))

    kanaele = 3
    gewicht = np.zeros((4 * kanaele, kanaele, 2, 2), dtype=np.float32)
    for viertel, (zeile, spalte) in enumerate(reihenfolge):
        for kanal in range(kanaele):
            gewicht[viertel * kanaele + kanal, kanal, zeile, spalte] = 1.0

    name = "focus_als_faltung"
    graph.initializer.append(numpy_helper.from_array(gewicht, name + "_W"))
    neuer = helper.make_node(
        "Conv", inputs=[eingang, name + "_W"], outputs=[concat.output[0]],
        name=name, kernel_shape=[2, 2], strides=[2, 2], pads=[0, 0, 0, 0],
        group=1, dilations=[1, 1])

    entfernt = {id(concat)} | {id(k) for paar in kette for k in paar}
    behalten = [k for k in graph.node if id(k) not in entfernt]
    stelle = min(i for i, k in enumerate(graph.node) if id(k) in entfernt)
    del graph.node[:]
    graph.node.extend(behalten[:stelle] + [neuer] + behalten[stelle:])

    onnx.checker.check_model(modell)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(modell, str(ziel))
    return len(entfernt), int(gewicht.sum())


def beweise_gleichheit(alt: Path, neu: Path, kante: int, laeufe: int = 3) -> float:
    """Beide Netze auf demselben Zufallsbild -- groesster Unterschied.

    Gerechnet wird mit dem OpenCV DIESES Rechners. Das beweist nicht, dass das
    Telefon dasselbe rechnet, aber es beweist, dass der Umbau die Rechnung
    nicht veraendert hat -- und genau darum geht es hier.
    """
    a = cv2.dnn.readNet(str(alt))
    b = cv2.dnn.readNet(str(neu))
    groesster = 0.0
    for i in range(laeufe):
        rng = np.random.default_rng(1000 + i)
        blob = rng.random((1, 3, kante, kante), dtype=np.float32) * 255.0
        a.setInput(blob)
        b.setInput(blob)
        ausgabe_a, ausgabe_b = a.forward(), b.forward()
        if ausgabe_a.shape != ausgabe_b.shape:
            raise SystemExit(f"Form weicht ab: {ausgabe_a.shape} "
                             f"gegen {ausgabe_b.shape}")
        groesster = max(groesster,
                        float(np.abs(ausgabe_a - ausgabe_b).max()))
    return groesster


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--quelle", default="models/yolox_tiny.onnx")
    p.add_argument("--ziel", default="models/yolox_tiny_android.onnx")
    p.add_argument("--kante", type=int, default=416,
                   help="Eingangskante des Netzes, fuer die Gegenprobe")
    p.add_argument("--grenze", type=float, default=1e-4,
                   help="groesster erlaubter Unterschied in der Ausgabe")
    a = p.parse_args()

    quelle, ziel = WURZEL / a.quelle, WURZEL / a.ziel
    if not quelle.is_file():
        raise SystemExit(f"{quelle} fehlt -- erst tools/hole_personenmodell.py")
    try:
        import onnx  # noqa: F401
    except ImportError:
        raise SystemExit("Es fehlt `onnx`. Nur zum Umbauen noetig:\n"
                         "  .venv/Scripts/python.exe -m pip install onnx")

    knoten, einsen = baue_um(quelle, ziel)
    print(f"{knoten} Knoten ersetzt durch eine Faltung mit {einsen} Einsen.")

    unterschied = beweise_gleichheit(quelle, ziel, a.kante)
    print(f"Groesster Unterschied in der Ausgabe: {unterschied:.3e}")
    if unterschied > a.grenze:
        ziel.unlink(missing_ok=True)
        raise SystemExit("Zu gross -- das umgebaute Netz rechnet anders. "
                         "Datei wieder geloescht.")

    print(f"gleichwertig. {ziel} ({ziel.stat().st_size/1e6:.1f} MB)")
    print("Fuer die App:  cp " + a.ziel + " android/app/src/main/assets/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
