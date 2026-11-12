"""Bild in Bild: die Tafel als Ganzes suchen statt ueber Merkmalspunkte.

DIE ENTSCHEIDUNG (vom Nutzer, 2026-09-10)

    "wir lassen alle deine Ansaetze und fangen doch an, automatische
     Kalibrierung darueber, das Bild in Bild gesucht wird... dann kann man das
     Bild auch bisschen verzerren und verkippen lassen."

WAS DABEI MOEGLICH WIRD, WAS ORB NIE KONNTE

Die veraenderlichen Teile lassen sich AUSBLENDEN. Brennende Kegellampen und
wechselnde Ziffern sind genau das, woran der Merkmalsabgleich scheitert -- und
aus der Bauart wissen wir, wo sie liegen. `matchTemplate` rechnet mit einer
Maske; ORB kann das nicht.

DIE MASKE IST DER GANZE TRICK -- UND SIE HATTE EIN LOCH

Die obere Leiste der FUNK-Tafel ist eine MATRIXANZEIGE mit wechselndem Text.
Sie ist als einzige Flaeche kein ROI und blieb deshalb unmaskiert. GEMESSEN
2026-09-10 an acht Stellen eines Spiels, ZNCC an der von Hand gesetzten
Kalibrierung:

    ohne Leistenmaske   -0,009  -0,005  -0,010  -0,006  -0,015  -0,026
                         0,684   0,680
    mit Leistenmaske     0,524   0,525   0,523   0,527   0,529   0,518
                         0,577   0,573

An sechs von acht Stellen war die Uebereinstimmung vorher EXAKT NULL. Mit der
Maske ist sie ueberall gleichmaessig. Der leichte Rueckgang an den zwei guten
Stellen ist der Preis: weniger Flaeche, dafuer nur noch Unveraenderliches.

Maskiert wird die Leiste als EIGENES Rechteck, nicht als Band ueber das obere
Drittel -- ein Band nahm die beiden oberen Fenster mit, und die sind die
stabilsten Merkmale der ganzen Tafel (Streuung 0,02 bis 0,04 Pixel ueber
20 Frames).

WARUM DIE GUETE EIGENS BERECHNET WIRD

`TM_CCORR_NORMED` mit Maske ist ueber verschiedene VORLAGENGROESSEN nicht
vergleichbar: Eine kleiner gerechnete Vorlage erreicht fast ueberall hoehere
Werte. Wer damit den Massstab waehlt, landet am Rand des Rasters -- gemessen
an zwei von vier Stellen, Streuung 14,8 statt 0,8 Pixel. Die LAGE wird
deshalb weiter mit `matchTemplate` gesucht (dafuer taugt es, innerhalb eines
Massstabs), die AUSWAHL zwischen Massstaeben aber ueber den maskierten ZNCC im
entzerrten Raum. Der normiert auf die Streuung im Maskenbereich und ist damit
groessenunabhaengig.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)

# Schwelle, ab der eine dunkle Flaeche im Musterbild als Anzeigefenster gilt.
DUNKEL = 57
# Rand um die Lampen, als Anteil der Tafelkante. Der Schein einer brennenden
# Lampe greift weit ueber ihre ROI hinaus.
RAND_LAMPEN = 0.022
# Rand um die Ziffernfelder. GETRENNT, weil der Schein dort schwaecher ist --
# ein grosser Rand frisst die erhabenen Fensterrahmen mit weg, und die sind
# unveraenderliche Struktur.
RAND_ZIFFERN = 0.008
MASKENRAND = RAND_LAMPEN

# Verkleinerung fuer den Grobdurchgang. Die Kosten von `matchTemplate` fallen
# mit der Flaeche -- bei halber Kante also auf ein Viertel.
GROB_FAKTOR = 0.5
# Massstabsschritt im Grobdurchgang. Danach wird um den Fund herum mit dem
# feinen Schritt (0,025) gesucht, der Grobschritt ist also zugleich die
# Fangbreite des feinen Durchgangs.
GROB_SCHRITT = 0.05


@dataclass
class Fund:
    """Eine gefundene Tafel samt Guete und der Verzerrung, die dazu passt."""

    quad: list[list[float]]
    guete: float
    skala: float
    winkel: float

    @property
    def mitte(self) -> tuple[float, float]:
        q = np.asarray(self.quad, dtype=float)
        return float(q[:, 0].mean()), float(q[:, 1].mean())


def stabile_maske(muster: np.ndarray, rois, rand: float = RAND_LAMPEN,
                  rand_ziffern: float | None = None) -> np.ndarray:
    """1 = wird verglichen, 0 = wird ignoriert.

    Verglichen wird, was sich nie aendert: Gehaeuse, Logo, die Rahmen um die
    Anzeigefenster. Ignoriert wird alles, was leuchtet oder Text zeigt.
    """
    grau = (cv2.cvtColor(muster, cv2.COLOR_BGR2GRAY) if muster.ndim == 3
            else muster)
    hoehe, breite = grau.shape[:2]
    maske = np.ones((hoehe, breite), np.uint8)

    def weg(x0, y0, x1, y1):
        maske[max(0, int(y0)):min(hoehe, int(y1)),
              max(0, int(x0)):min(breite, int(x1))] = 0

    # Die obere Matrixleiste: breit, flach, ganz oben -- und kein ROI.
    _, dunkel = cv2.threshold(grau, DUNKEL, 255, cv2.THRESH_BINARY_INV)
    anzahl, _, kennzahlen, _ = cv2.connectedComponentsWithStats(dunkel, 8)
    for i in range(1, anzahl):
        x, y = kennzahlen[i, cv2.CC_STAT_LEFT], kennzahlen[i, cv2.CC_STAT_TOP]
        w, h = (kennzahlen[i, cv2.CC_STAT_WIDTH],
                kennzahlen[i, cv2.CC_STAT_HEIGHT])
        if y < 0.15 * hoehe and w > 0.7 * breite and h < 0.25 * hoehe:
            weg(x - 3, y - 3, x + w + 3, y + h + 3)

    # Lampen und Ziffernfelder. Die einzelnen Stellen brauchen es nicht -- ihr
    # Feld deckt sie ab, und einzeln gerechnet fraesse es die Rahmen mit weg.
    rand_ziffern = RAND_ZIFFERN if rand_ziffern is None else rand_ziffern
    for roi in rois:
        if roi.name.startswith("digit_"):
            continue
        r = rand if roi.name.startswith(("pin_lamp", "green_lamp"))             else rand_ziffern
        x, y, w, h = roi.rect
        weg((x - r) * breite, (y - r) * hoehe,
            (x + w + r) * breite, (y + h + r) * hoehe)
    return maske


def _verzerrt(muster: np.ndarray, maske: np.ndarray, skala: float,
              winkel: float) -> tuple[np.ndarray, np.ndarray]:
    hoehe, breite = muster.shape[:2]
    nb, nh = max(8, int(breite * skala)), max(8, int(hoehe * skala))
    ip = cv2.INTER_AREA if skala < 1 else cv2.INTER_CUBIC
    klein = cv2.resize(muster, (nb, nh), interpolation=ip)
    kmaske = cv2.resize(maske, (nb, nh), interpolation=cv2.INTER_NEAREST)
    if abs(winkel) < 1e-6:
        return klein, kmaske
    M = cv2.getRotationMatrix2D((nb / 2, nh / 2), winkel, 1.0)
    return (cv2.warpAffine(klein, M, (nb, nh), flags=cv2.INTER_LINEAR),
            cv2.warpAffine(kmaske, M, (nb, nh), flags=cv2.INTER_NEAREST))


def guete(muster: np.ndarray, maske: np.ndarray, grau: np.ndarray,
          quad) -> float:
    """Maskierter ZNCC im entzerrten Raum -- ueber Massstaebe vergleichbar."""
    hoehe, breite = muster.shape[:2]
    ecken = np.float32([[0, 0], [breite - 1, 0], [breite - 1, hoehe - 1],
                        [0, hoehe - 1]])
    M = cv2.getPerspectiveTransform(ecken, np.float32(quad))
    ziel = cv2.warpPerspective(grau, M, (breite, hoehe),
                               flags=cv2.WARP_INVERSE_MAP)
    m = maske.astype(bool)
    if m.sum() < 50:
        return -1.0
    a = muster[m].astype(np.float64)
    z = ziel[m].astype(np.float64)
    a -= a.mean()
    z -= z.mean()
    nenner = np.sqrt((a * a).sum() * (z * z).sum())
    return float((a * z).sum() / nenner) if nenner > 0 else -1.0


def _ecken(muster: np.ndarray, skala: float, winkel: float, x: int, y: int,
           vb: int, vh: int) -> list[list[float]]:
    """Die vier Ecken der gedrehten Vorlage an ihrer Fundstelle."""
    hoehe, breite = muster.shape[:2]
    nb, nh = int(breite * skala), int(hoehe * skala)
    M = cv2.getRotationMatrix2D((nb / 2, nh / 2), winkel, 1.0)
    e = np.float32([[0, 0], [nb - 1, 0], [nb - 1, nh - 1], [0, nh - 1]])
    gedreht = cv2.transform(e.reshape(-1, 1, 2), M).reshape(-1, 2)
    gedreht += [x + vb / 2 - nb / 2, y + vh / 2 - nh / 2]
    return [[float(a), float(b)] for a, b in gedreht]


def verkippe(muster: np.ndarray, maske: np.ndarray, grau: np.ndarray,
             quad, *, weite: int = 3, runden: int = 2):
    """Zieht die vier Ecken einzeln nach -- damit auch Verkippung passt.

    WOFUER -- der Nutzer, 2026-09-10:

        "dann kann man das Bild auch bisschen verzerren und verkippen lassen.
         Wie sehr, koennte man ja auch grob ausrechnen notfalls."

    Massstab und Drehung allein beschreiben nur eine AEHNLICHKEIT. Die vier
    Tafeln im Overlay stehen aber unterschiedlich schraeg -- die aeusseren
    werden staerker perspektivisch verzerrt gesehen als die mittleren. Wer nur
    Massstab und Drehung zulaesst, kann das nicht abbilden.

    WIE WEIT GESUCHT WIRD, ist gemessen und nicht geraten: Die Kippung einer
    Rahmenkante gegen die Bildkante lag bei bis zu 9 Pixeln, im Mittel bei 2,3
    (2026-09-10, 16 Kanten). Drei Pixel je Ecke und Runde decken das ab, ohne
    dass die Suche in eine ganz andere Lage abwandern kann.

    Jede Ecke wird einzeln versetzt und behalten, was den maskierten ZNCC
    verbessert. Wird nichts besser, bleibt das Viereck, wie es war.
    """
    beste = [list(map(float, e)) for e in quad]
    bester_wert = guete(muster, maske, grau, beste)
    for _ in range(max(1, runden)):
        verbessert = False
        for i in range(4):
            for dx in range(-weite, weite + 1):
                for dy in range(-weite, weite + 1):
                    if dx == 0 and dy == 0:
                        continue
                    versuch = [list(e) for e in beste]
                    versuch[i][0] += dx
                    versuch[i][1] += dy
                    wert = guete(muster, maske, grau, versuch)
                    if wert > bester_wert:
                        beste, bester_wert = versuch, wert
                        verbessert = True
        if not verbessert:
            break
    return beste, bester_wert


def _grob(grau: np.ndarray, muster: np.ndarray, maske: np.ndarray,
          vollbild: np.ndarray, versatz: tuple[int, int],
          min_guete: float = 0.45):
    """Massstab und Winkel auf einem verkleinerten Bild schaetzen.

    Zurueck kommt ein ENGES Raster um das Gefundene, mit dem der feine
    Durchgang dann in voller Aufloesung arbeitet.

    DIE AUSWAHL BLEIBT DIESELBE wie im feinen Durchgang: Bewertet wird mit dem
    maskierten ZNCC in VOLLER Aufloesung, nicht mit dem Wert aus
    `matchTemplate`. Der ist ueber verschiedene Vorlagengroessen nicht
    vergleichbar -- wer damit den Massstab waehlt, landet am Rand des Rasters
    (gemessen: Streuung 14,8 statt 0,8 Pixel).

    Bei Misserfolg None/None: Dann sucht der Aufrufer wie bisher das volle
    Raster ab. Lieber langsam als falsch.

    WANN DER GROBDURCHGANG AUFGIBT -- GEMESSEN 2026-09-11 an fuenf Stellen der
    Aufzeichnung und drei Bildern ohne Tafel:

        echte Tafel     0,715  0,720  0,726  0,728  0,716
        schwarz        -1,000
        Rauschen        0,038
        graue Flaeche  -0,035

    Dazwischen liegt kein Zweifelsfall. Als Schranke dient dieselbe, an der
    auch der feine Durchgang einen Fund annimmt -- ein Grobdurchgang, der
    unter ihr bleibt, haette dem feinen ohnehin nur die falsche Gegend
    gezeigt.
    """
    klein = cv2.resize(grau, None, fx=GROB_FAKTOR, fy=GROB_FAKTOR,
                       interpolation=cv2.INTER_AREA)
    bester = (-2.0, None, None)
    for s in np.arange(0.70, 1.101, GROB_SCHRITT):
        for w in (-2.0, 0.0, 2.0):
            # Auf dem kleinen Bild ist die Tafel um denselben Faktor kleiner.
            v, vm = _verzerrt(muster, maske, float(s) * GROB_FAKTOR, float(w))
            if v.shape[0] >= klein.shape[0] or v.shape[1] >= klein.shape[1]:
                continue
            karte = cv2.matchTemplate(klein, v, cv2.TM_CCORR_NORMED, mask=vm)
            karte = np.nan_to_num(karte, nan=0.0, posinf=0.0, neginf=0.0)
            _, _, _, stelle = cv2.minMaxLoc(karte)
            quad = _ecken(muster, float(s), float(w),
                          stelle[0] / GROB_FAKTOR + versatz[0],
                          stelle[1] / GROB_FAKTOR + versatz[1],
                          v.shape[1] / GROB_FAKTOR, v.shape[0] / GROB_FAKTOR)
            wert = guete(muster, maske, vollbild, quad)
            if wert > bester[0]:
                bester = (wert, float(s), float(w))
    if bester[1] is None or bester[0] < min_guete:
        log.debug("Grobdurchgang ohne brauchbaren Treffer (beste Guete %.3f) "
                  "-- es wird das volle Raster abgesucht", bester[0])
        return None, None
    log.debug("Grobdurchgang: Massstab %.3f, Drehung %+.1f, Guete %.3f",
              bester[1], bester[2], bester[0])
    return (np.arange(bester[1] - GROB_SCHRITT, bester[1] + GROB_SCHRITT + 1e-9,
                      0.025),
            (bester[2] - 1.0, bester[2], bester[2] + 1.0))


def finde_tafeln(bild: np.ndarray, muster: np.ndarray, maske: np.ndarray, *,
                 max_tafeln: int = 4, skalen=None, winkel=None,
                 min_guete: float = 0.45, bereich=None,
                 kippen: bool = True) -> list[Fund]:
    """Sucht die Vorlage im Bild, ueber ein Raster aus Massstab und Drehung.

    Zurueck kommen bis zu `max_tafeln` Funde, von links nach rechts, jeder mit
    seiner eigenen Verzerrung. Zwei Funde gelten als verschieden, wenn ihre
    Mitten weiter als eine halbe Tafelbreite auseinanderliegen.
    """
    if bild is None or bild.size == 0 or muster is None or muster.size == 0:
        return []
    vollbild = (cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY) if bild.ndim == 3
                else bild)
    grau = vollbild
    # NUR DA SUCHEN, WO SCHON ETWAS WAR. Ein Overlay steht fest; nach dem
    # ersten Bild ist die Gegend bekannt, und der Rest des Bildes muss nicht
    # jedes Mal wieder durchgerechnet werden.
    versatz = (0, 0)
    if bereich is not None:
        x0, y0, x1, y1 = (int(max(0, bereich[0])), int(max(0, bereich[1])),
                          int(min(grau.shape[1], bereich[2])),
                          int(min(grau.shape[0], bereich[3])))
        if x1 - x0 > 40 and y1 - y0 > 40:
            grau = grau[y0:y1, x0:x1]
            versatz = (x0, y0)
    # ERST GROB, DANN FEIN -- sonst dauert das erste Bild zu lange.
    #
    # GEMESSEN 2026-09-11 an der Aufzeichnung: Ein Durchlauf (ein Massstab,
    # ein Winkel) kostet 0,18 s auf einem 1920x1080-Bild. Das volle Raster aus
    # 17 Massstaeben und 5 Winkeln sind 85 Durchlaeufe, also 18 Sekunden --
    # und genau daran ist die automatische Kalibrierung im Livestream
    # gescheitert: Die Zeitgrenze von 20 s war vorbei, bevor das zweite Bild
    # an der Reihe war (und ein einzelnes Bild zaehlt nicht, `min_frames`).
    #
    # Der Grobdurchgang sucht dasselbe Raster auf einem VERKLEINERTEN Bild.
    # Die Kosten fallen mit der Flaeche, bei halber Kante also auf ein Viertel.
    # Gesucht wird dabei nur Massstab und Winkel, nicht die endgueltige Lage --
    # die bestimmt danach der feine Durchgang in voller Aufloesung.
    if skalen is None and winkel is None and GROB_FAKTOR < 1.0:
        skalen, winkel = _grob(grau, muster, maske, vollbild, versatz,
                               min_guete)
    skalen = np.arange(0.70, 1.101, 0.025) if skalen is None else skalen
    winkel = (-2.0, -1.0, 0.0, 1.0, 2.0) if winkel is None else winkel

    kandidaten: list[Fund] = []
    for s in skalen:
        for w in winkel:
            v, vm = _verzerrt(muster, maske, float(s), float(w))
            if v.shape[0] >= grau.shape[0] or v.shape[1] >= grau.shape[1]:
                continue
            karte = cv2.matchTemplate(grau, v, cv2.TM_CCORR_NORMED, mask=vm)
            karte = np.nan_to_num(karte, nan=0.0, posinf=0.0, neginf=0.0)
            arbeit = karte.copy()
            vh, vb = v.shape[:2]
            for _ in range(max_tafeln + 2):
                _, wert, _, stelle = cv2.minMaxLoc(arbeit)
                if wert <= 0:
                    break
                quad = _ecken(muster, float(s), float(w),
                              stelle[0] + versatz[0], stelle[1] + versatz[1],
                              vb, vh)
                kandidaten.append(Fund(
                    quad=quad, skala=float(s), winkel=float(w),
                    guete=guete(muster, maske, vollbild, quad)))
                cv2.circle(arbeit, stelle, int(vb * 0.7), 0.0, -1)

    kandidaten.sort(key=lambda f: -f.guete)
    aus: list[Fund] = []
    for fund in kandidaten:
        if fund.guete < min_guete:
            break
        breite = np.linalg.norm(np.array(fund.quad[1]) - np.array(fund.quad[0]))
        if all(abs(fund.mitte[0] - a.mitte[0]) > 0.5 * breite
               or abs(fund.mitte[1] - a.mitte[1]) > 0.5 * breite for a in aus):
            aus.append(fund)
        if len(aus) >= max_tafeln:
            break
    if kippen:
        for fund in aus:
            quad, wert = verkippe(muster, maske, vollbild, fund.quad)
            fund.quad, fund.guete = quad, wert
    aus.sort(key=lambda f: f.mitte[0])
    if aus:
        log.debug("Bild in Bild: %d Tafeln, Guete %s", len(aus),
                  " ".join(f"{f.guete:.3f}" for f in aus))
    return aus
