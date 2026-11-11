"""Laeuft der Erkennungskern auf diesem Telefon -- und wie schnell?

Dieser Stand baut noch keine Anwendung, er beantwortet eine Frage: Traegt
Chaquopy Python samt numpy und OpenCV auf echter Hardware, und was kosten die
Rechenschritte, auf denen alles andere aufsetzt?

Auf dem Entwicklungsrechner laeuft OpenCV 5.0, auf dem Telefon 4.5.1 -- das
Neueste, was Chaquopys Paketquelle anbietet. Deshalb steht die Version hier
oben in der Ausgabe: Sie gehoert zu jedem Messwert dazu.

Gemessen wird der MEDIAN mehrerer Durchlaeufe, nicht der erste. Der erste
Aufruf eines OpenCV-Verfahrens richtet Puffer ein und ist regelmaessig ein
Vielfaches teurer als der Dauerbetrieb -- wer ihn misst, misst die falsche
Zahl.
"""

from __future__ import annotations

import platform
import time

ZEILENENDE = chr(10)


def _messe(was, wiederholungen: int = 5) -> float:
    """Median mehrerer Durchlaeufe in Millisekunden."""
    zeiten = []
    for _ in range(wiederholungen):
        t0 = time.perf_counter()
        was()
        zeiten.append((time.perf_counter() - t0) * 1000)
    zeiten.sort()
    return zeiten[len(zeiten) // 2]


def selbsttest(modellpfad: str = "") -> str:
    zeilen: list[str] = []
    zeilen.append("Python   " + platform.python_version())
    zeilen.append("Maschine " + platform.machine())

    try:
        import numpy as np
    except Exception as exc:
        zeilen.append("numpy fehlt: " + str(exc))
        return ZEILENENDE.join(zeilen)
    zeilen.append("numpy    " + np.__version__)

    try:
        import cv2
    except Exception as exc:
        zeilen.append("OpenCV fehlt: " + str(exc))
        return ZEILENENDE.join(zeilen)
    zeilen.append("OpenCV   " + cv2.__version__)
    zeilen.append("")

    # Ein Vollbild in der Groesse, die die Anlage liefert.
    bild = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)

    # 1. Die gruene Lampe: der Schritt, der in JEDEM Frame laeuft.
    ausschnitt = bild[80:130, 600:650]

    def gruen():
        hsv = cv2.cvtColor(ausschnitt, cv2.COLOR_BGR2HSV)
        return float(cv2.inRange(hsv, (35, 80, 80), (85, 255, 255)).mean())

    zeilen.append("Gruenlampe (50x50)   %8.2f ms" % _messe(gruen, 20))

    # 2. Die Entzerrung einer Tafel -- Grundlage jeder ROI-Messung.
    quelle = np.float32([[534, 71], [676, 71], [676, 216], [534, 216]])
    ziel = np.float32([[0, 0], [400, 0], [400, 400], [0, 400]])
    matrix = cv2.getPerspectiveTransform(quelle, ziel)

    def entzerren():
        return cv2.warpPerspective(bild, matrix, (400, 400))

    zeilen.append("Tafel entzerren      %8.2f ms" % _messe(entzerren))

    # 3. Das Hintergrundmodell der Personenmaske, auf dem verkleinerten Bild.
    mog = cv2.createBackgroundSubtractorMOG2(500, 32.0, False)
    klein = cv2.resize(bild, (480, 270))
    for _ in range(5):
        mog.apply(klein)

    def maske():
        return mog.apply(klein)

    zeilen.append("Bewegungsmaske (1/4) %8.2f ms" % _messe(maske))

    # 4. Das Personenmodell -- der teuerste Schritt, und der einzige, der
    #    ueberhaupt nur laeuft, wenn ein billiger Zeuge etwas meldet.
    zeilen.append("")
    if not modellpfad:
        zeilen.append("Personenmodell: kein Pfad uebergeben")
        return ZEILENENDE.join(zeilen)
    try:
        netz = cv2.dnn.readNet(modellpfad)
        blob = np.zeros((1, 3, 416, 416), np.float32)
        netz.setInput(blob)
        netz.forward()          # erster Aufruf: richtet ein, zaehlt nicht

        def modell():
            netz.setInput(blob)
            return netz.forward()

        zeilen.append("Personenmodell (416) %8.1f ms" % _messe(modell, 3))
    except Exception as exc:
        zeilen.append("Personenmodell: " + type(exc).__name__ + " -- " + str(exc))

    return ZEILENENDE.join(zeilen)


def kern(konfig: str = "") -> str:
    """Laesst sich der Erkennungskern auf diesem Geraet ueberhaupt importieren?

    Das war bis zum 2026-09-14 die offene Frage: `config/schema.py` und
    `calibration/model.py` haengen an pydantic, und dessen Kern ist in Rust
    geschrieben -- auf Android nicht zu haben. Seit beide Dateien auf die
    projekteigene Pruefung in `kegel_cv/schema.py` umgestellt sind, sollte es
    gehen. Sollte.
    """
    zeilen = []
    schritte = [
        ("kegel_cv.schema", "eigene Feldpruefung"),
        ("kegel_cv.config.schema", "Konfigurationsschema"),
        ("kegel_cv.calibration.model", "Kalibrierungsmodell"),
        ("kegel_cv.detection.lamp_detectors", "Lampenerkennung"),
        ("kegel_cv.detection.personen_modell", "Personenmodell"),
        ("kegel_cv.analysis.lane_processor", "Bahnverarbeitung"),
        ("kegel_cv.analysis.pipeline", "Pipeline"),
    ]
    for modul, was in schritte:
        try:
            __import__(modul)
            zeilen.append("  ok       " + was)
        except Exception as exc:
            zeilen.append("  FEHLER   " + was + ": "
                          + type(exc).__name__ + " " + str(exc)[:90])
            return ZEILENENDE.join(zeilen)

    if konfig:
        try:
            import os

            from kegel_cv.config.loader import load_config
            # Die Wurzel AUSDRUECKLICH mitgeben: Auf dem Telefon gibt es kein
            # Projektverzeichnis, sondern nur den privaten Ordner der
            # Anwendung -- relativ dazu werden Modelldatei und Ausgaben
            # aufgeloest.
            cfg = load_config(konfig, root=os.path.dirname(konfig))
            zeilen.append("  ok       Konfiguration gelesen, Verdeckungsanteil "
                          + str(cfg.detection.green.occlusion_edge_fraction))
        except Exception as exc:
            zeilen.append("  FEHLER   Konfiguration (" + konfig + "): "
                          + type(exc).__name__ + " " + str(exc)[:90])
    else:
        zeilen.append("  FEHLER   Konfiguration: kein Pfad uebergeben")
    return ZEILENENDE.join(zeilen)
