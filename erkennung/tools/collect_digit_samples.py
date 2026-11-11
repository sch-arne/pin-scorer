"""Sammelt beschriftete Ziffernbilder aus dem Material -- Wahrheit aus den Lampen.

WOZU: Ein besserer Erkenner laesst sich nicht behaupten, nur messen. Dafuer
braucht es Ziffernbilder, deren Wert UNABHAENGIG von der Ziffernerkennung
bekannt ist -- sonst misst man am Ende nur die eigene Schwaeche nach.

Diese Wahrheit gibt es im Material: die neun Kegellampen. Sie zeigen dasselbe
Ergebnis wie das Feld `pin_count` -- aber NICHT dieselbe Groesse.

DER FEHLER, DEN ES HIER ZU VERMEIDEN GILT (Hinweis des Nutzers, 2026-08-30):
Die Lampen zeigen alle Kegel, die GERADE LIEGEN -- also kumulativ ueber beide
Wuerfe eines Bildes. Die Ziffer zeigt nur den AKTUELLEN Wurf. Wer die Zahl der
leuchtenden Lampen als Beschriftung nimmt, beschriftet jede Raeumung falsch:

    leuchtende Lampen   Ziffer   in Wahrheit
              9            2     7, dann Raeumung 2
              9            1     8, dann Raeumung 1
              9            4     5, dann 4
              9            9     alle neune, erster Wurf
              7            3     4, dann 3

Gemessen an 288 so beschrifteten Bildern: Nur 45 waren wirklich eine 9. Der
Erkenner hatte in den uebrigen recht -- die Beschriftung war falsch. Eine
Wahrheit, die man nicht prueft, misst am Ende die eigene Annahme.

Der Ausweg (Vorschlag des Nutzers, 2026-08-30): NUR Wuerfe IN DIE VOLLEN
nehmen. Dort standen vorher alle neun Kegel, also zeigen Lampen und Ziffer
zwangslaeufig dieselbe Zahl. Beim Abraeumen ist das nicht so, und genau dort
entstand der Fehler.

Erkennen laesst sich das OHNE jede Ziffernlesung: Ein Wurf in die Vollen ist
der, bei dem der bestaetigte Lampenstand VORHER LEER war. Damit haengt die
Beschriftung an keiner Groesse, die selbst erst erkannt werden muesste.

Der Preis ist bekannt und wird ausgewiesen: In die Vollen fallen fast nur 5 bis
9 Kegel. Die niedrigen Ziffern kommen deshalb aus der Wurfnummer, wo die Kette
sie stuetzt.

Gesammelt wird nur, wenn:
  * ALLE neun Lampen lesbar sind (sonst ist die Wahrheit selbst unsicher)
  * die Ziffernzelle beleuchtet ist (Maximum des Rotkanals >= 200)
  * die Lampenanzeige seit mindestens `--ruhe` Frames UNVERAENDERT steht

Die letzte Bedingung ist die wichtigste, und sie fehlte im ersten Anlauf. Was
dabei herauskam, war eine Lehrstunde: 608 Bilder wurden als "0" beschriftet,
weil die Lampen dunkel waren -- die Anzeige zeigte in diesen Frames aber noch
die 9 des vorigen Wurfs. Beide Anzeigen zeigen dasselbe Ergebnis, aber NICHT
zur selben Zeit. Die Anlage setzt die Lampen zurueck, waehrend die Ziffer noch
steht (gemessen: die Ziffer folgt rund 40 Frames nach GREEN_OFF).

Eine Wahrheit, die nur meistens gilt, ist keine. Deshalb wird gewartet, bis
sich seit mehreren Sekunden nichts mehr geruehrt hat -- dann haben beide
Anzeigen denselben Stand erreicht.

Zusaetzlich wird das Feld `throw_number` mitgesammelt, aber NUR wo die Kette es
bestaetigt: Die Wurfnummer zaehlt innerhalb eines Satzes monoton hoch. Eine
Lesung, die genau um eins ueber der vorigen liegt, ist durch die Kette
gestuetzt und nicht bloss durch den Erkenner. Das bringt die Ziffern 3, 4 und 5
in den Datensatz, die bei den Kegelzahlen kaum vorkommen.

Geschrieben wird eine .npz mit den Masken und ihren Beschriftungen. Die
Auswertung passiert getrennt (`tools/fit_digit_classifier.py`), damit sich
Erkenner vergleichen lassen, ohne jedes Mal den Stream zu lesen.
"""

from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kegel_cv.calibration import Calibration  # noqa: E402
from kegel_cv.calibration.geometry import norm_rect_to_frame_bbox  # noqa: E402
from kegel_cv.config import load_config  # noqa: E402
from kegel_cv.detection.digit_detector import SevenSegmentDetector  # noqa: E402
from kegel_cv.detection.digit_reader import CalibratedDigitReader  # noqa: E402
from kegel_cv.detection.lamp_detectors import WarmthLampDetector  # noqa: E402

LEUCHTET_AB = 200
# Groesse, auf die jede Maske gebracht wird. Bewusst GROESSER als das Original
# (8x14 px): Beim Verkleinern verschwinden die duennen Segmente.
BREITE, HOEHE = 12, 20


def maske_holen(patch: np.ndarray, vor: SevenSegmentDetector) -> np.ndarray | None:
    """Binaere, auf den Ziffernumriss beschnittene und normierte Maske."""
    if patch.size == 0 or int(patch[:, :, 2].max()) < LEUCHTET_AB:
        return None
    maske = vor._red_mask(patch)
    if maske.max() == 0:
        return None
    beschnitten = vor._trim_vertical(maske)
    if beschnitten.size and beschnitten.max() > 0:
        maske = beschnitten
    return cv2.resize(maske, (BREITE, HOEHE), interpolation=cv2.INTER_AREA)


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--source", required=True, help="Datei ODER Stream-URL")
    p.add_argument("--calibration", required=True, type=Path)
    p.add_argument("--blocks",
                   default="20000,60000,100000,140000,180000,220000,260000")
    p.add_argument("--block-length", type=int, default=3000)
    p.add_argument("--every", type=int, default=6)
    p.add_argument("--ruhe", type=int, default=120,
                   help="so viele Frames muss die Lampenanzeige unveraendert "
                        "stehen (120 = 4,8 s bei 25 fps)")
    p.add_argument("--out", type=Path,
                   default=Path("data/ground_truth/ziffern.npz"))
    a = p.parse_args()

    cal = Calibration.load(a.calibration)
    cfg = load_config()
    vor = SevenSegmentDetector(cfg.detection.digits)
    leser = CalibratedDigitReader(cfg.detection.digits)
    lampen = WarmthLampDetector(cfg.detection.lamps)

    cap = cv2.VideoCapture()
    cap.open(a.source, cv2.CAP_FFMPEG,
             [int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), 20000,
              int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), 15000])
    if not cap.isOpened():
        raise SystemExit("Quelle nicht erreichbar")

    masken: list[np.ndarray] = []
    werte: list[int] = []
    quellen: list[str] = []
    alt: list[str] = []          # was der heutige Erkenner sagt
    letzte_nummer: dict[int, int] = {}
    letzte_lampen: dict[int, tuple] = {}
    ruht_seit: dict[int, int] = {}
    gezaehlt: dict[int, set] = {}
    beschriftung: dict[int, int] = {}
    tfs: dict[int, object] = {}

    for start in (int(x) for x in a.blocks.split(",")):
        cap.set(cv2.CAP_PROP_POS_FRAMES, float(start))
        for k in range(a.block_length):
            ok, bild = cap.read()
            if not ok:
                break
            if k % a.every:
                continue
            for lane in cal.lanes:
                bahn = lane.display_number
                if bahn not in tfs:
                    tfs[bahn] = lane.transform(bild.shape[1], bild.shape[0])
                tf = tfs[bahn]

                def schnitt(rect):
                    bx, by, bw, bh = norm_rect_to_frame_bbox(tf, rect, bild.shape)
                    return bild[by:by + bh, bx:bx + bw]

                # --- Wahrheit 1: die neun Lampen ---
                lampen_rois = [r for r in lane.pin_lamps() if r.enabled]
                messung = lampen.detect(
                    [schnitt(r.rect) for r in lampen_rois],
                    [r.pin_number if r.pin_number is not None
                     else int(r.name.removeprefix("pin_lamp_"))
                     for r in lampen_rois])
                # Ruhe messen: Erst wenn sich die Lampen lange nicht mehr
                # geruehrt haben, steht auch die Ziffer auf demselben Wert.
                jetzt = start + k
                if messung.is_complete:
                    if messung.pins != letzte_lampen.get(bahn):
                        letzte_lampen[bahn] = messung.pins
                        ruht_seit[bahn] = jetzt
                else:
                    ruht_seit.pop(bahn, None)
                ruhig = (bahn in ruht_seit
                         and jetzt - ruht_seit[bahn] >= a.ruhe)

                # NUR ein BESTAETIGTER Stand darf zaehlen. Die Lampen
                # werden hier Frame fuer Frame gelesen, ohne die zeitliche
                # Aggregation der Pipeline -- eine einzelne flackernde Lampe
                # saehe sonst aus wie ein Wurf mit einem Kegel. Genau das
                # passierte: 722 Bilder wurden als "1" beschriftet, weit mehr
                # als es Raeumungen gibt.
                if ruhig:
                    jetzige = set(letzte_lampen[bahn])
                    vorige = gezaehlt.get(bahn)
                    if jetzige != vorige:
                        # NUR aus dem leeren Stand heraus wird beschriftet.
                        # Dann standen alle neun Kegel, und die Ziffer zeigt
                        # genau die Zahl der jetzt leuchtenden Lampen. Wuchs
                        # der Stand aus einem schon besetzten heraus, ist es
                        # eine Raeumung -- dort weichen Lampen und Ziffer
                        # auseinander, und es wird nichts beschriftet.
                        if vorige == set() and jetzige:
                            beschriftung[bahn] = len(jetzige)
                        else:
                            beschriftung.pop(bahn, None)
                        gezaehlt[bahn] = jetzige

                # Gesammelt wird, solange der Stand ruht: Die Ziffer steht dann
                # auf demselben Wurf wie die Lampen.
                if ruhig and bahn in beschriftung:
                    for zelle in lane.digit_rois("pin_count"):
                        patch = schnitt(zelle.rect)
                        maske = maske_holen(patch, vor)
                        if maske is None:
                            continue
                        masken.append(maske)
                        werte.append(beschriftung[bahn])
                        quellen.append(f"lampen_b{bahn}")
                        alt.append(leser.read_digit_full(patch)[0])

                # --- Wahrheit 2: die Kette der Wurfnummer ---
                zellen = lane.digit_rois("throw_number")
                if len(zellen) == 3:
                    patches = [schnitt(z.rect) for z in zellen]
                    zeichen = [leser.read_digit_full(pt)[0] for pt in patches]
                    text = "".join(zeichen)
                    if text.isdigit():
                        nummer = int(text)
                        vorher = letzte_nummer.get(bahn)
                        # NUR wenn die Kette es stuetzt: genau eins weiter.
                        # Eine gleiche oder rueckwaerts laufende Lesung sagt
                        # nichts, eine springende erst recht nicht.
                        if vorher is not None and nummer == vorher + 1:
                            for stelle, pt in enumerate(patches):
                                maske = maske_holen(pt, vor)
                                if maske is None:
                                    continue
                                masken.append(maske)
                                werte.append(int(text[stelle]))
                                quellen.append(f"kette_b{bahn}")
                                alt.append(zeichen[stelle])
                        if vorher is None or nummer != vorher:
                            letzte_nummer[bahn] = nummer
    cap.release()

    if not masken:
        raise SystemExit("Nichts gesammelt")

    m = np.stack(masken)
    w = np.array(werte, dtype=np.int8)
    q = np.array(quellen)
    v = np.array(alt)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(a.out, masken=m, werte=w, quellen=q, alt=v)

    print(f"{len(m)} beschriftete Ziffernbilder -> {a.out}\n")
    print(f"  {'Ziffer':>7} {'gesamt':>8} {'aus Lampen':>12} {'aus Kette':>11}")
    for ziffer in range(10):
        maske = w == ziffer
        n = int(maske.sum())
        aus_l = int(np.char.startswith(q[maske], "lampen").sum()) if n else 0
        print(f"  {ziffer:>7} {n:>8} {aus_l:>12} {n - aus_l:>11}")
    print(f"\nQuellen: {dict(collections.Counter(x.split('_')[0] for x in q))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
