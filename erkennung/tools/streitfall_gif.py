"""Macht einen Streitfall zwischen Lampen und Ziffer als GIF sichtbar.

WOZU (Nutzer, 2026-09-18): *"Gib mir bitte für die ganzen Streitfälle GIFs
oder ähnliches aus auch von dem Wegen BUG-031"*

`tools/vergleiche_lampen_ziffern.py` sagt, DASS ein Wurf falsch gebucht wurde.
Es sagt nicht, warum. Bei BUG-031 liegt der Grund nicht beim Wurf, sondern
rund 25 Frames nach dem Grün-AN -- dort wird gemessen, wie viele Kegel schon
lagen, und genau dieser Wert wird beim Grün-AUS abgezogen.

Deshalb zeigt dieses Werkzeug ZWEI Zeitabschnitte desselben Wurfs:

    1. das Grundlinienfenster  (Grün-AN bis Grün-AN + max(baseline_offsets))
    2. den Wurf selbst         (kurz vor Grün-AUS bis zur Meldung)

Liegen sie dicht beieinander, wird ein durchgehender Abschnitt daraus. Liegen
Minuten dazwischen -- der eigentliche Fehlerfall --, zeigt das GIF beide und
blendet die Lücke als Schnitt ein. Wer das sieht, braucht keine Erklärung mehr.

Je Bild: Zeit seit Aufzeichnungsbeginn, Framenummer, Zustand der grünen Lampe,
jede Kegellampe einzeln mit Helligkeit, und alle Ziffernfelder.

Aufruf:

    .venv/Scripts/python.exe tools/streitfall_gif.py \
        --lauf debug/<quelle>/lauf_2026-09-17_12-53-11 \
        --kalibrierung data/calibrations/1Spieltag_Neu_Feinkalibriert_FinalBahn5.json \
        --quelle "https://.../rendition.m3u8?..." \
        --bahn 4 --frame 47227

Ohne `--bahn/--frame` werden ALLE Streitfälle des Laufs abgearbeitet, die der
Vergleich findet. Das kostet je Fall zwei Sprünge im Stream -- bei einem
laufenden Analyselauf also Geduld.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, "src")

from kegel_cv.analysis.lane_processor import LaneProcessor          # noqa: E402
from kegel_cv.calibration.model import Calibration                  # noqa: E402
from kegel_cv.config import load_config                             # noqa: E402
from kegel_cv.models.readings import LampState                      # noqa: E402

FELDER = ("throw_number", "pin_count", "total_b", "left_display")
BESCHRIFTUNG = {"throw_number": "Wurfnummer", "pin_count": "Kegel",
                "total_b": "Summe", "left_display": "Fehlwurf"}


class Bild:
    """Was der LaneProcessor als Frame erwartet."""

    def __init__(self, bild, index: int, fps: float) -> None:
        self.image, self.index, self.timestamp = bild, index, index / fps


def lies_gruenzyklen(lauf: Path) -> dict[int, list[tuple[int, int]]]:
    """AN/AUS-Paare je Bahn aus der Grünspur."""
    zustand: dict[int, list[tuple[int, str]]] = defaultdict(list)
    with (lauf / "gruenspur.csv").open(encoding="utf-8-sig", newline="") as d:
        for z in csv.DictReader(d, delimiter=";"):
            zustand[int(z["Bahn"])].append((int(z["Frame"]), z["Zustand"]))
    zyklen: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for bahn, reihe in zustand.items():
        reihe.sort()
        an = vor = None
        for frame, s in reihe:
            if s == "ON" and vor != "ON":
                an = frame
            elif s == "OFF" and vor == "ON" and an is not None:
                zyklen[bahn].append((an, frame))
                an = None
            # UNKNOWN aendert den Zustand nicht -- es ist die Totzone
            # zwischen den Schwellen, kein Wechsel.
            if s in ("ON", "OFF"):
                vor = s
    return zyklen


def lies_wuerfe(lauf: Path) -> list[dict[str, str]]:
    with (lauf / "wuerfe.csv").open(encoding="utf-8-sig", newline="") as d:
        return list(csv.DictReader(d, delimiter=";"))


def abschnitte(gruen_an: int | None, gruen_aus: int | None, wurf: int,
               fenster: int, vorlauf: int, nachlauf: int
               ) -> list[tuple[int, int]]:
    """Die zu zeigenden Zeitabschnitte, zusammengelegt wenn sie sich beruehren."""
    teile: list[tuple[int, int]] = []
    if gruen_an is not None:
        teile.append((gruen_an - vorlauf, gruen_an + fenster + vorlauf))
    teile.append((wurf - 260, wurf + nachlauf))
    if gruen_aus is not None:
        teile.append((gruen_aus - 60, gruen_aus + nachlauf))

    teile.sort()
    zusammen: list[list[int]] = []
    for von, bis in teile:
        if zusammen and von <= zusammen[-1][1] + 40:
            zusammen[-1][1] = max(zusammen[-1][1], bis)
        else:
            zusammen.append([von, bis])
    return [(max(0, a), b) for a, b in zusammen]


def zeichne(bild, prozessor: LaneProcessor, nummer: int, fps: float,
            kasten: tuple[int, int, int, int], marken: dict[int, str],
            zeuge: dict[str, str]) -> tuple[np.ndarray, dict]:
    """Ein beschriftetes Einzelbild -- und was darauf gemessen wurde."""
    rahmen = Bild(bild, nummer, fps)
    lampen = prozessor._read_pin_lamps(rahmen)
    ziffern = prozessor.read_digits(rahmen)
    gruen = (prozessor.green_detector.detect(
        prozessor._crop(bild, prozessor._green_box))
        if prozessor._green_box else None)

    je_nummer = {}
    if lampen is not None:
        for lampe in lampen.lamps:
            je_nummer[int(lampe.name.rsplit("_", 1)[1])] = lampe
    liegend = sorted(lampen.pins) if lampen is not None else []
    gelesen = {f: (ziffern[f].text if ziffern.get(f) else "-") for f in FELDER}

    bx0, by0, bx1, by1 = kasten
    ausschnitt = bild[by0:by1, bx0:bx1]
    zoom = max(1, int(620 / max(1, ausschnitt.shape[1])))
    gross = cv2.resize(ausschnitt,
                       (ausschnitt.shape[1] * zoom, ausschnitt.shape[0] * zoom),
                       interpolation=cv2.INTER_NEAREST)
    for (kx, ky, kw, kh), pin in zip(prozessor._lamp_boxes,
                                     prozessor._pin_numbers):
        lampe = je_nummer.get(pin)
        zustand = lampe.state if lampe else None
        farbe = ((70, 230, 70) if zustand == LampState.ON
                 else (60, 90, 240) if zustand == LampState.OFF
                 else (170, 170, 170))
        ecke = ((kx - bx0) * zoom, (ky - by0) * zoom)
        cv2.rectangle(gross, ecke,
                      (ecke[0] + kw * zoom, ecke[1] + kh * zoom), farbe, 1)
        cv2.putText(gross, str(pin), (ecke[0] + 1, ecke[1] - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, farbe, 1)

    zeit = nummer / fps
    tafel = np.zeros((max(gross.shape[0], 372) + 10, gross.shape[1] + 380, 3),
                     np.uint8)
    tafel[5:5 + gross.shape[0], 5:5 + gross.shape[1]] = gross
    s = gross.shape[1] + 18

    def schreibe(text, y, groesse=0.45, farbe=(230, 230, 230), dick=1):
        cv2.putText(tafel, text, (s, y), cv2.FONT_HERSHEY_SIMPLEX, groesse,
                    farbe, dick)

    schreibe(f"{int(zeit//3600)}:{int(zeit%3600//60):02d}:{zeit%60:05.2f}",
             26, 0.62, (255, 255, 255), 2)
    schreibe(f"Frame {nummer}", 48, 0.46, (180, 180, 180))
    gz = gruen.state.name if gruen else "-"
    schreibe(f"Gruen {gz}" + ("" if gruen is None else f"   {gruen.score:.1f}"),
             72, 0.48, (70, 230, 70) if gz == "ON" else (60, 90, 240))

    schreibe("Kegellampen", 100, 0.42, (170, 170, 170))
    for i, pin in enumerate(range(1, 10)):
        lampe = je_nummer.get(pin)
        zustand = lampe.state.name if lampe else "?"
        farbe = ((70, 230, 70) if zustand == "ON"
                 else (60, 90, 240) if zustand == "OFF" else (170, 170, 170))
        cv2.putText(tafel,
                    f"{pin}: {zustand:<4s}"
                    f"{'' if lampe is None else f'{lampe.score:6.1f}'}",
                    (s + (i // 5) * 170, 120 + (i % 5) * 17),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, farbe, 1)
    schreibe(f"liegend: {liegend}  ({len(liegend)})", 224, 0.45,
             (255, 255, 255))

    schreibe("Ziffern der Tafel", 252, 0.42, (170, 170, 170))
    for i, feld in enumerate(FELDER):
        schreibe(f"{BESCHRIFTUNG[feld]:<11s} {gelesen[feld]}", 272 + i * 18,
                 0.44, (255, 255, 255))

    schreibe(zeuge["kopf"], 352, 0.44, (0, 200, 255))

    for marken_frame, text in marken.items():
        if abs(marken_frame - nummer) <= 6:
            cv2.putText(tafel, text, (8, tafel.shape[0] - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2)
    return tafel, {"frame": nummer, "liegend": liegend, "gruen": gz,
                   "ziffern": gelesen}


def schnittbild(breite: int, hoehe: int, text: str) -> np.ndarray:
    """Eine Tafel, die die uebersprungene Zeit benennt."""
    bild = np.zeros((hoehe, breite, 3), np.uint8)
    for i, zeile in enumerate(text.split("\n")):
        cv2.putText(bild, zeile, (30, hoehe // 2 - 30 + i * 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 220, 255), 2)
    return bild


def ein_fall(quelle: str, kal: Calibration, cfg, bahn: int, wurf_frame: int,
             zyklen: dict[int, list[tuple[int, int]]], zeile: dict[str, str],
             ziel: Path, takt: int, fps: float,
             spanne: tuple[int, int] | None = None) -> None:
    """`spanne` zeigt einen DURCHGEHENDEN Abschnitt statt der zwei Fenster.

    Noetig, sobald mehrere Wuerfe in EINER Gruenphase stecken (gemessen am
    2026-09-24 auf Bahn 5: 683 Frames, in denen die Tafel von 026 auf 028
    zaehlte). Die zwei ueblichen Fenster zeigen dann Anfang und Ende und
    schneiden ausgerechnet die Stelle heraus, an der die Tafel weiterzaehlt.
    """
    passend = [(an, aus) for an, aus in zyklen.get(bahn, [])
               if an <= wurf_frame <= aus + 120]
    gruen_an, gruen_aus = passend[-1] if passend else (None, None)
    fenster = max(cfg.sampling.baseline_offsets)

    marken: dict[int, str] = {}
    if gruen_an is not None:
        marken[gruen_an] = "GRUEN AN -- hier wird die Grundlinie gemessen"
        marken[gruen_an + fenster] = (
            f"Grundlinienfenster zu (+{fenster} Frames)")
    if gruen_aus is not None:
        marken[gruen_aus] = "GRUEN AUS -- jetzt gilt das Ergebnis"
    if zeile["Kegel"] == "KEIN WURF GEBUCHT":
        marken[wurf_frame] = "HIER WURDE KEIN WURF GEBUCHT"
        kopf = f"Bahn {bahn}: Gruenzyklus ohne Wurfergebnis"
    else:
        marken[wurf_frame] = (
            f"gebucht: {zeile['Kegel']} Kegel   |   Tafel sagt "
            f"{zeile['Ziffer'] or '?'}   |   Grundlinie "
            f"{zeile['Grundlinie'] or '0'}")
        kopf = (f"Bahn {bahn} Wurf {zeile['Wurfnummer']}: gebucht "
                f"{zeile['Kegel']}, Tafel {zeile['Ziffer'] or '?'}")

    lane = next(l for l in kal.lanes if l.real_lane_number == bahn)
    kamera = cv2.VideoCapture(quelle)
    if not kamera.isOpened():
        raise SystemExit("Quelle nicht zu oeffnen")

    teile = ([spanne] if spanne else
             abschnitte(gruen_an, gruen_aus, wurf_frame, fenster, 70, 90))
    print(f"Bahn {bahn}, Wurf bei F{wurf_frame}: Gruen {gruen_an} -> "
          f"{gruen_aus}"
          + (f" ({gruen_aus - gruen_an} Frames)"
             if gruen_an and gruen_aus else ""))
    for von, bis in teile:
        print(f"   Abschnitt {von}..{bis}")

    prozessor: LaneProcessor | None = None
    bilder: list[np.ndarray] = []
    verlauf = []
    for nummer_abschnitt, (von, bis) in enumerate(teile):
        kamera.set(cv2.CAP_PROP_POS_FRAMES, von)
        n = von
        while n <= bis:
            ok, bild = kamera.read()
            if not ok:
                print(f"   Stream liefert bei Frame {n} nichts -- Abschnitt "
                      f"endet hier")
                break
            if prozessor is None:
                prozessor = LaneProcessor(lane, cfg)
                prozessor.prepare(bild.shape)
                q = np.asarray(lane.quad, np.float32)
                kasten = (max(0, int(q[:, 0].min()) - 60),
                          max(0, int(q[:, 1].min()) - 25),
                          min(bild.shape[1], int(q[:, 0].max()) + 60),
                          min(bild.shape[0], int(q[:, 1].max()) + 140))
            nahe_marke = any(abs(m - n) <= 6 for m in marken)
            if (n - von) % takt and not nahe_marke:
                n += 1
                continue
            tafel, gemessen = zeichne(bild, prozessor, n, fps, kasten, marken,
                                      {"kopf": kopf})
            bilder.append(tafel)
            verlauf.append(gemessen)
            n += 1
        if nummer_abschnitt + 1 < len(teile) and bilder:
            luecke = teile[nummer_abschnitt + 1][0] - bis
            for _ in range(4):
                bilder.append(schnittbild(
                    bilder[0].shape[1], bilder[0].shape[0],
                    f"... {luecke} Frames uebersprungen\n"
                    f"    ({luecke / fps:.0f} Sekunden)\n"
                    f"    Die Grundlinie von oben gilt weiter."))
    kamera.release()

    if not bilder:
        print("   kein einziges Bild -- Quelle abgelaufen?")
        return

    print(f"\n   {'Frame':>7s} {'Gruen':>7s} {'liegend':>26s}  "
          f"Wurfnr / Kegel / Summe")
    vorher = None
    for g in verlauf:
        schluessel = (tuple(g["liegend"]), g["gruen"])
        if schluessel != vorher:
            z = g["ziffern"]
            print(f"   {g['frame']:>7d} {g['gruen']:>7s} "
                  f"{str(g['liegend']):>26s}  {z['throw_number']} / "
                  f"{z['pin_count']} / {z['total_b']}")
            vorher = schluessel

    from PIL import Image
    hoehe = max(b.shape[0] for b in bilder)
    breite = max(b.shape[1] for b in bilder)
    einheitlich = []
    for b in bilder:
        if b.shape[:2] != (hoehe, breite):
            leer = np.zeros((hoehe, breite, 3), np.uint8)
            leer[:b.shape[0], :b.shape[1]] = b
            b = leer
        einheitlich.append(Image.fromarray(cv2.cvtColor(b, cv2.COLOR_BGR2RGB)))
    ziel.parent.mkdir(parents=True, exist_ok=True)
    einheitlich[0].save(ziel, save_all=True, append_images=einheitlich[1:],
                        duration=260, loop=0)
    print(f"\n   GIF: {ziel}  ({len(einheitlich)} Bilder, "
          f"{ziel.stat().st_size / 2**20:.1f} MB)\n")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lauf", required=True, type=Path)
    p.add_argument("--kalibrierung", required=True, type=Path)
    p.add_argument("--quelle", required=True, help="Videodatei oder Stream")
    p.add_argument("--bahn", type=int, default=0)
    p.add_argument("--frame", type=int, default=0)
    p.add_argument("--takt", type=int, default=8,
                   help="jedes wievielte Frame ins GIF (Vorgabe 8)")
    p.add_argument("--fps", type=float, default=25.0)
    p.add_argument("--spanne", default="",
                   help="VON:BIS -- ein durchgehender Abschnitt statt "
                        "der zwei ueblichen Fenster. Fuer Faelle, in "
                        "denen mehrere Wuerfe in einer Gruenphase "
                        "stecken.")
    p.add_argument("--ziel", type=Path, default=Path("debug/streitfaelle"))
    a = p.parse_args()

    cfg = load_config()
    kal = Calibration.load(a.kalibrierung)
    zyklen = lies_gruenzyklen(a.lauf)
    wuerfe = lies_wuerfe(a.lauf)

    if a.bahn and a.frame:
        gewaehlt = [z for z in wuerfe
                    if int(z["Bahn"]) == a.bahn and int(z["Frame"]) == a.frame]
        if not gewaehlt:
            # KEIN GEBUCHTER WURF AN DIESER STELLE -- und genau das ist oft der
            # Fehler, der belegt werden soll: ein verworfener Gruenzyklus. Ohne
            # diesen Zweig liesse sich ausgerechnet der Verlust nicht zeigen.
            print(f"Kein gebuchter Wurf auf Bahn {a.bahn} bei Frame {a.frame} "
                  f"-- es wird der Gruenzyklus gezeigt, der keinen lieferte.\n")
            gewaehlt = [{"Bahn": str(a.bahn), "Frame": str(a.frame),
                         "Kegel": "KEIN WURF GEBUCHT", "Ziffer": "",
                         "Wurfnummer": "-", "Grundlinie": "", "Spiel": "",
                         "SummeTafel": "", "Kegelnummern": "", "Status": ""}]
    else:
        # Alle Wuerfe, bei denen Lampen und Ziffer auseinandergehen.
        gewaehlt = [z for z in wuerfe
                    if z["Ziffer"].strip().isdigit()
                    and int(z["Ziffer"]) != int(z["Kegel"])]
    if not gewaehlt:
        print("Kein passender Wurf gefunden")
        return 1

    print(f"{len(gewaehlt)} Fall/Faelle\n")
    for zeile in gewaehlt:
        bahn, frame = int(zeile["Bahn"]), int(zeile["Frame"])
        ziel = a.ziel / f"streit_bahn{bahn}_f{frame}.gif"
        spanne = None
        if a.spanne:
            von, bis = (int(x) for x in a.spanne.split(":"))
            spanne = (von, bis)
            ziel = a.ziel / f"streit_bahn{bahn}_f{von}-{bis}.gif"
        ein_fall(a.quelle, kal, cfg, bahn, frame, zyklen, zeile, ziel,
                 a.takt, a.fps, spanne)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
