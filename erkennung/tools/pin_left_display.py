"""Setzt die beiden Stellen des linken Displays und prueft, ob sie tragen.

Vorgeschichte: Der Fehlwurfzaehler (Q2) ist die einzige Quelle, die einen
Nullwurf verraet -- bei 0 Kegeln schaltet die Anlage die gruene Lampe gar nicht
aus (Q10). In der Auswertung lieferte das Feld 0 von 36 789 lesbaren Messungen.

Der Grund war NICHT ein schwacher Leser, sondern schlicht `enabled: false`:
Das Feld wurde beim Kalibrieren nie aktiviert. Der vorhandene ROI sitzt
waagerecht richtig, ist aber zu flach -- die Ziffern sind unten abgeschnitten.

Am Feingitter (Raster 0,005) abgelesen, Bahn 2, Frame 51000:

    linke Stelle    x 0,115 .. 0,168     y 0,651 .. 0,753
    rechte Stelle   x 0,192 .. 0,245     y 0,651 .. 0,753

Die Hoehe 0,10 deckt sich mit den anderen Ziffernfeldern (0,106).

Ein erster Versuch mit x 0,128 / 0,199 scheiterte: 17 % lesbar, Werte 36 und 56
bei einer Anzeige, die "00" zeigt. Bei 11 px Ziffernbreite sind 0,015 normiert
rund drei Pixel -- genug, damit der Leser die Segmente verfehlt. Ein grobes
Gitter (Raster 0,01) reichte fuer diese Feinheit nicht.

Diese Datei schreibt eine KOPIE der Kalibrierung -- die des Nutzers bleibt
unberuehrt -- und misst anschliessend ueber das Fenster des bekannten
Nullwurfs, ob sich der Wert dort aendert.

Aufruf:
    .venv/Scripts/python.exe tools/pin_left_display.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

QUELLE = Path("data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2.json")
ZIEL = Path("data/calibrations/kalibrierung_2026-08-25_0950_allDigits_neu_2"
            "_leftdisplay.json")

# Je Bahn eigene Koordinaten. Ein gemeinsamer Wert reicht NICHT -- genau das
# war der Ausgangsfehler: Auf allen vier Bahnen stand derselbe Vorgabewert,
# waehrend jedes andere Ziffernfeld je Bahn abweicht. Die Tafeln stehen
# unterschiedlich schraeg im Overlay.
#
# Abgelesen am Feingitter (tools/grid_left_display.py, Raster 0,005, Frame 51000):
#
#     Bahn 2   Ziffern x 0,115..0,168 / 0,192..0,245   y 0,651..0,753
#     Bahn 3            x 0,121..0,177 / 0,195..0,252   y 0,655..0,757
#     Bahn 4            x 0,114..0,172 / 0,190..0,248   y 0,668..0,768
#     Bahn 5            x 0,118..0,175 / 0,191..0,250   y 0,660..0,760
STELLEN_JE_BAHN = {
    # Bahn 2 ist die schwierigste: 60 % lesbar, waehrend die anderen drei bei
    # 100 % liegen. Ein Suchlauf ueber 50 Verschiebungen brachte hoechstens
    # 61 % -- die Anzeige ist dort einfach unschaerfer. Gewaehlt wurde die
    # RAUSCHFREIE Variante (0 statt 3 Fehllesungen bei 59,6 % statt 61 %):
    # Fuer den Stabilitaetsfilter zaehlt, dass kein falscher Wert mehrfach
    # hintereinander steht, nicht die Ausbeute.
    2: {1: [0.115, 0.650, 0.060, 0.110], 2: [0.192, 0.650, 0.060, 0.110]},
    3: {1: [0.119, 0.652, 0.060, 0.110], 2: [0.193, 0.652, 0.062, 0.110]},
    4: {1: [0.113, 0.665, 0.062, 0.108], 2: [0.189, 0.665, 0.062, 0.108]},
    5: {1: [0.117, 0.657, 0.060, 0.108], 2: [0.190, 0.657, 0.062, 0.108]},
}


def kalibrierung_schreiben() -> None:
    daten = json.loads(QUELLE.read_text(encoding="utf-8"))
    for lane in daten["lanes"]:
        stellen = STELLEN_JE_BAHN.get(lane["real_lane_number"])
        if stellen is None:
            continue
        vorhanden = {r["name"] for r in lane["rois"]}
        for roi in lane["rois"]:
            if roi["name"] == "left_display":
                roi["enabled"] = True
        for nummer, rect in stellen.items():
            name = f"digit_left_display_{nummer}"
            if name in vorhanden:
                for roi in lane["rois"]:
                    if roi["name"] == name:
                        roi["rect"] = rect
                        roi["enabled"] = True
            else:
                lane["rois"].append({"name": name, "rect": rect,
                                     "enabled": True, "pin_number": None})
        print(f"   Bahn {lane['real_lane_number']}: zwei Stellen gesetzt")
    ZIEL.write_text(json.dumps(daten, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print(f"Kalibrierung geschrieben: {ZIEL}")
    print(f"(die Vorlage {QUELLE.name} bleibt unveraendert)\n")


def messen(von: int, bis: int, abstand: int = 5) -> None:
    """Liest das Feld auf ALLEN Bahnen ueber ein Fenster."""
    from collections import Counter

    from kegel_cv.analysis.lane_processor import LaneProcessor
    from kegel_cv.calibration import Calibration
    from kegel_cv.config import load_config
    from kegel_cv.video import FileVideoSource

    cfg = load_config()
    cal = Calibration.load(ZIEL)
    src = FileVideoSource("kegelVideos/2026-08-22 09-24-46.mp4")
    src.open()
    erster = src.read()

    prozessoren = {}
    for lane in cal.lanes:
        p = LaneProcessor(lane, cfg)
        if p.prepare(erster.image.shape):
            prozessoren[lane.display_number] = p

    src.seek(von)
    frame = src.read()
    werte: dict[int, list[int]] = {dn: [] for dn in prozessoren}
    gesamt = 0
    while frame is not None and frame.index <= bis:
        if frame.index % abstand == 0:
            gesamt += 1
            for dn, p in prozessoren.items():
                feld = p.read_digits(frame).get("left_display")
                if feld is not None and feld.is_readable:
                    werte[dn].append(feld.value)
        frame = src.read()
    src.close()

    print(f"{'Bahn':<6}{'lesbar':>16}{'Verteilung der Werte'}")
    for dn in sorted(prozessoren):
        anteil = 100 * len(werte[dn]) / max(1, gesamt)
        haeufig = dict(sorted(Counter(werte[dn]).most_common(5)))
        print(f"{dn:<6}{len(werte[dn]):>6} / {gesamt:<5} {anteil:>4.0f}%  {haeufig}")


def main() -> int:
    logging.basicConfig(level=logging.ERROR)
    kalibrierung_schreiben()

    print("=" * 70)
    print("FENSTER UM DEN BEKANNTEN NULLWURF (Bahn 2, Satz 3, Wurf 18)")
    print("   erwartet: Bahn 2 zeigt hier 0 UND 1, die anderen nur 0")
    print("=" * 70)
    messen(50600, 51700)

    print("\n" + "=" * 70)
    print("KONTROLLE: ein Abschnitt ohne Nullwurf auf irgendeiner Bahn")
    print("=" * 70)
    messen(5000, 6100)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
