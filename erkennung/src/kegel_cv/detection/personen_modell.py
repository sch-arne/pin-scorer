"""Ein Personenmodell auf dem Tafelband -- der vierte Zeuge.

WARUM ES DIESES MODUL GIBT

Die drei bisherigen Zeugen erkennen einen Menschen an seiner WIRKUNG: Der
Gruen-Score faellt, die Bewegungsmaske sieht Vordergrund, die Tafelwache sieht
eine Tafel, die nicht mehr wie sie selbst aussieht. Keiner von ihnen weiss,
dass es ein Mensch IST. Deshalb koennen sie ihn auch nicht gezielt schwaerzen,
und deshalb kann keiner von ihnen "Mensch" von "Kalibrierung verrutscht"
unterscheiden -- der Unterschied zwischen "kurz aussetzen" und "diese Bahn
meldet nie wieder etwas".

Der Nutzer am 2026-09-13: *"Am einfachsten waere es, wenn du Personen
zielsicher erkennen und permanent schwaerzen wuerdest, dann haetten wir das
Problem gar nicht, weil der Wert egal wie der Mensch durch die Tafel laeuft auf
0 fallen wuerde."*

WAS GEMESSEN WURDE (2026-09-13/14, Livestream Fastlane, ueber cv2.dnn)

Die entscheidende Messung ist die nach dem ZUSCHNITT. Auf dem blanken
Tafelausschnitt -- also genau dem Bild, das in der Datenbank landet -- findet
das Modell gar nichts:

    Zuschnitt                       Beweisstelle F42237   Fehlalarme/600
    ---------------------------------------------------------------------
    Tafel allein (136x136 px)        19 von 70 Frames            0
    Tafel + 100 % Luft (4 Laeufe)    55 von 70 Frames            0
    Band ueber alle vier Tafeln      53 von 70 Frames            0
    Band, nach unten verlaengert     57 von 70 Frames            0

    Gegenprobe an den 1682 Bildern, die wirklich an die Datenbank gingen:
    auf dem blanken Ausschnitt 0 von 2 bekannten Gesichtern gefunden.

Der Grund ist anschaulich: Im 136x136-Ausschnitt FUELLT der Mensch das Bild,
und ein formatfuellendes Gesicht ohne Umgebung sieht fuer das Netz nach nichts
aus. Es braucht Kontext. Das BAND -- ein Rechteck ueber alle vier Tafeln,
nach unten verlaengert -- liefert ihn mit EINEM Durchlauf statt vier.

KOSTEN UND LIZENZ, gemessen auf diesem Rechner (CPU, OpenCV 5.0):

    Modell            Lizenz       Netz     Beweisstelle   Fehlalarme/600
    ----------------------------------------------------------------------
    YOLOv8n   640     AGPL-3.0     62 ms      57 von 70          0
    YOLOX-S   640     Apache-2.0  100 ms      57 von 70          0
    YOLOX-Tiny 416    Apache-2.0   28 ms      55 von 70          0
    YOLOX-Nano 416    Apache-2.0   13 ms      55 von 70          0

GEWAEHLT: YOLOX-Tiny. Nicht wegen der Lizenz allein -- es ist auch mehr als
doppelt so schnell wie YOLOv8n. Gegen YOLOX-Nano entschied der Abstand zur
Schwelle: An den zehn Frames, in denen die Ampel auf 0,0 fiel, meldet Tiny
0,73 bis 0,83, Nano nur 0,54 bis 0,72; und auf der zweiten Beweisstrecke
findet Tiny 68 statt 64 von 70 Frames. Bei einer Schutzfunktion, deren
Versagen ein Gesicht in eine oeffentliche Datenbank traegt, zaehlt die Reserve.

WARUM NICHT YOLOv8n: Es stammt von Ultralytics und steht unter AGPL-3.0. Das
Projekt steht unter MIT, und die beiden vertragen sich nur in eine Richtung --
ein Werk mit AGPL-Teilen kann nicht unter MIT stehen. YOLOX (Megvii) ist
Apache-2.0 und damit MIT-vertraeglich.

WARUM DAS TROTZ PROJEKTREGEL 4 GEHT

Regel 4 verbietet Frame-fuer-Frame-ML, nicht ML. Das Modell laeuft NUR, wenn
ein billiger Zeuge schon etwas meldet, und zusaetzlich in einem groben Takt als
Streife -- in beiden Faellen mit Mindestabstand. GEMESSEN ueber 20 000 Frames
des Livestreams: In 1,95 % der Frames faellt ueberhaupt eine Bahn unter ihre
Verdeckungsschwelle.

Fehlt die Modelldatei, bleibt das Modul still und meldet das EINMAL. Die
Analyse laeuft dann wie bisher mit drei Zeugen weiter (Projektregel P8).
Geholt wird sie mit `tools/hole_personenmodell.py` -- ein reiner Download,
20 MB, keine weitere Abhaengigkeit.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

# YOLOX gibt je Ankerpunkt 85 Zahlen aus: 4 Kasten, 1 Objektheit, 80 Klassen.
# Klasse 0 des COCO-Datensatzes ist "person" -- die einzige, die hier zaehlt.
SPALTE_OBJEKT = 4
SPALTE_PERSON = 5
# Die drei Aufloesungsstufen des Netzes. Aus ihnen entsteht das Ankergitter.
SCHRITTE = (8, 16, 32)
# YOLOX erwartet rohe BGR-Werte 0..255 als float -- KEIN Teilen durch 255 und
# keine Mittelwertkorrektur. Beides steckt im Netz. Wer normalisiert, bekommt
# ein Netz, das nichts mehr findet, ohne dass irgendwo ein Fehler auftaucht.


class PersonenModell:
    """Sucht Menschen auf dem Tafelband -- hoechstens einmal je Frame.

    Zustandsbehaftet nur im Gedaechtnis fuer den aktuellen Frame: Fragen
    mehrere Bahnen im selben Frame, rechnet das Netz trotzdem nur einmal.
    """

    def __init__(self, modellpfad: Path | str | None, *,
                 eingang: int = 640, vertrauen: float = 0.25,
                 nms: float = 0.45, luft_unten: float = 1.0,
                 luft_seitlich: float = 0.05, gedaechtnis: int = 50,
                 aktiv: bool = True) -> None:
        self.eingang = eingang
        self.vertrauen = vertrauen
        self.nms = nms
        self.luft_unten = luft_unten
        self.luft_seitlich = luft_seitlich
        self._netz = None
        self._gitter, self._schritte = self._ankergitter(eingang)
        self._band: tuple[int, int, int, int] | None = None
        self._tafeln: dict[int, tuple[int, int, int, int]] = {}
        # DAS GEDAECHTNIS. Das veroeffentlichte Tafelbild stammt nicht aus dem
        # laufenden Frame, sondern aus einem Sample-Frame -- bis zu 34 Frames
        # zurueck. Der Ringpuffer der Pipeline haelt aber nur MASKIERTE Bilder,
        # und auf denen verliert das Netz den Menschen: GEMESSEN an 12
        # Beweisframes in 2 davon (F265723, F265724, beide roh sicher
        # gefunden). Also merkt sich dieses Modul den rohen Bandausschnitt --
        # vorskaliert auf die Arbeitsaufloesung des Netzes, damit es bei rund
        # 0,4 MB je Frame bleibt statt 1,7.
        #
        # DAS IST DIE EINZIGE STELLE, an der rohe Bildpunkte von Menschen
        # aufgehoben werden. Sie verlassen den Arbeitsspeicher nie.
        self._gedaechtnis: OrderedDict[int, tuple] = OrderedDict()
        self._ergebnisse: OrderedDict[int, list] = OrderedDict()
        self._tiefe = max(1, gedaechtnis)
        # Der zuletzt WIRKLICH gerechnete Frame. Vier Bahnen fragen versetzt;
        # wer sieht, dass die Antwort frisch genug ist, liest sie mit, statt
        # eine zweite zu bestellen -- die Funde gelten ohnehin fuer alle
        # Tafeln zugleich, es ist ein Band.
        self.letzter_lauf: int | None = None
        self.aufrufe = 0

        if not aktiv:
            log.info("Personenmodell ist abgeschaltet -- es bleiben drei Zeugen")
            return
        pfad = Path(modellpfad) if modellpfad else None
        if pfad is None or not pfad.is_file():
            # KEIN Fehler: Die Datei liegt aus Lizenzgruenden nicht im Repo.
            # Ohne sie arbeitet die Analyse wie vor dem 2026-09-13 weiter.
            log.warning("Personenmodell nicht gefunden (%s) -- es bleiben drei "
                        "Zeugen. Holen mit: "
                        ".venv/Scripts/python.exe tools/hole_personenmodell.py",
                        pfad)
            return
        try:
            self._netz = cv2.dnn.readNet(str(pfad))
        except cv2.error as exc:
            log.error("Personenmodell %s nicht lesbar: %s -- es bleiben drei "
                      "Zeugen", pfad, exc)
            return
        log.info("Personenmodell geladen: %s, Eingang %d px, ab Vertrauen %.2f",
                 pfad.name, eingang, vertrauen)

    @staticmethod
    def _ankergitter(kante: int) -> tuple[np.ndarray, np.ndarray]:
        """Die Ankerpunkte, gegen die YOLOX seine Kaesten meldet.

        Das Netz gibt keine Bildkoordinaten aus, sondern je Ankerpunkt eine
        Verschiebung. Wer das Gitter falsch aufbaut, bekommt Kaesten, die
        plausibel aussehen und an der falschen Stelle liegen.
        """
        gitter, schritte = [], []
        for s in SCHRITTE:
            n = kante // s
            xv, yv = np.meshgrid(np.arange(n), np.arange(n))
            gitter.append(np.stack((xv, yv), 2).reshape(-1, 2))
            schritte.append(np.full((n * n, 1), s))
        return (np.concatenate(gitter).astype(np.float32),
                np.concatenate(schritte).astype(np.float32))

    @property
    def bereit(self) -> bool:
        return self._netz is not None and self._band is not None

    # ---------------------------------------------------------------- Geometrie

    def setze_tafeln(self, tafeln: dict[int, tuple[int, int, int, int] | None],
                     bildform: tuple[int, ...]) -> None:
        """Legt das Band ueber alle Tafeln fest -- der einzige Suchbereich.

        Nach unten verlaengert, weil ein Mensch VOR der Tafel dort seinen Rumpf
        hat und das Netz ihn mit Rumpf sicherer findet als ohne (gemessen:
        57 statt 53 Frames, bei gleich null Fehlalarmen).
        """
        gueltig = {n: k for n, k in tafeln.items() if k is not None}
        self._tafeln = gueltig
        if not gueltig:
            self._band = None
            return
        hoehe, breite = bildform[0], bildform[1]
        x0 = min(x for x, y, w, h in gueltig.values())
        y0 = min(y for x, y, w, h in gueltig.values())
        x1 = max(x + w for x, y, w, h in gueltig.values())
        y1 = max(y + h for x, y, w, h in gueltig.values())
        luft_x = int(self.luft_seitlich * (x1 - x0))
        unten = int(self.luft_unten * (y1 - y0))
        x0 = max(0, x0 - luft_x)
        y0 = max(0, y0)
        x1 = min(breite, x1 + luft_x)
        y1 = min(hoehe, y1 + unten)
        self._band = (x0, y0, x1 - x0, y1 - y0) if x1 > x0 and y1 > y0 else None
        if self._netz is not None and self._band:
            log.info("Personenmodell sucht im Band %dx%d bei (%d, %d)",
                     self._band[2], self._band[3], self._band[0], self._band[1])

    # ------------------------------------------------------------------ Suchen

    def merke(self, bild: np.ndarray, frame_index: int) -> None:
        """Den ROHEN Bandausschnitt dieses Frames vorhalten.

        Muss VOR dem Schwaerzen gerufen werden -- die Bewegungsmaske nimmt
        genau den Rumpf weg, an dem das Netz einen Menschen erkennt.
        """
        if not self.bereit or bild is None or bild.size == 0:
            return
        x, y, w, h = self._band            # type: ignore[misc]
        ausschnitt = bild[y:y + h, x:x + w]
        if ausschnitt.size == 0:
            return
        self._gedaechtnis[frame_index] = self._vorskaliert(ausschnitt)
        while len(self._gedaechtnis) > self._tiefe:
            self._gedaechtnis.popitem(last=False)
        while len(self._ergebnisse) > self._tiefe:
            self._ergebnisse.popitem(last=False)

    def suche(self, bild: np.ndarray,
              frame_index: int) -> list[tuple[int, int, int, int, float]]:
        """Menschen im Band, in Bildkoordinaten. Je Frame hoechstens ein Lauf."""
        if not self.bereit or bild is None or bild.size == 0:
            return []
        if frame_index not in self._gedaechtnis:
            self.merke(bild, frame_index)
        return self.funde_fuer(frame_index)

    def funde_fuer(self, frame_index: int
                   ) -> list[tuple[int, int, int, int, float]]:
        """Die Funde eines gemerkten Frames -- gerechnet wird hoechstens einmal.

        Ist der Frame aus dem Gedaechtnis gefallen, kommt eine leere Liste.
        Lieber nichts behaupten als die Kaesten eines anderen Frames benutzen:
        Ein Mensch bewegt sich, und eine um Frames versetzte Schwaerzung
        traefe daneben.
        """
        if not self.bereit:
            return []
        vorhanden = self._ergebnisse.get(frame_index)
        if vorhanden is not None:
            return vorhanden
        eintrag = self._gedaechtnis.get(frame_index)
        if eintrag is None:
            return []
        klein, vor = eintrag
        x, y = self._band[0], self._band[1]   # type: ignore[index]
        self.aufrufe += 1
        funde = [(int(bx / vor) + x, int(by / vor) + y,
                  int(bw / vor), int(bh / vor), wert)
                 for bx, by, bw, bh, wert in self._netz_fragen(klein)]
        self._ergebnisse[frame_index] = funde
        if self.letzter_lauf is None or frame_index > self.letzter_lauf:
            self.letzter_lauf = frame_index
        while len(self._ergebnisse) > self._tiefe:
            self._ergebnisse.popitem(last=False)
        return funde

    def _vorskaliert(self, ausschnitt: np.ndarray) -> tuple[np.ndarray, float]:
        """Auf die Arbeitsaufloesung des Netzes bringen -- verlustfrei fuer es.

        Das Band wird ohnehin auf `eingang` heruntergerechnet. Wer es schon
        klein aufhebt, spart im Gedaechtnis den Faktor vier, ohne dass das Netz
        einen einzigen Bildpunkt weniger sieht.
        """
        h, w = ausschnitt.shape[:2]
        faktor = min(1.0, self.eingang / max(h, w))
        if faktor >= 1.0:
            return ausschnitt.copy(), 1.0
        klein = cv2.resize(ausschnitt,
                           (max(1, int(round(w * faktor))),
                            max(1, int(round(h * faktor)))),
                           interpolation=cv2.INTER_AREA)
        return klein, faktor

    def _netz_fragen(self, bild: np.ndarray):
        """Ein Netzdurchlauf auf dem Bandausschnitt, Kaesten im Ausschnitt."""
        gefuellt, faktor, ox, oy = self._briefkasten(bild)
        # Kanaele nach vorn, roh und ohne Skalierung -- siehe Kopf der Datei.
        blob = np.transpose(gefuellt, (2, 0, 1))[None].astype(np.float32)
        self._netz.setInput(blob)                     # type: ignore[union-attr]
        roh = self._netz.forward()                    # type: ignore[union-attr]
        werte = roh[0]

        # PASST DAS GITTER ZUM NETZ? Der gefaehrlichste Fehler in diesem Modul
        # macht keinen Laerm: Steht `input_size` nicht auf der Eingangskante
        # der Modelldatei, kommen Kaesten heraus, die plausibel aussehen und an
        # der falschen Stelle liegen -- eine Schwaerzung neben dem Gesicht.
        # Hier faellt es sofort auf, und das Modell schaltet sich ab, statt
        # falsche Auskuenfte zu geben (Projektregel P8: die Analyse laeuft
        # weiter, nur mit drei Zeugen).
        if werte.shape[0] != self._gitter.shape[0]:
            log.error("Personenmodell passt nicht zu input_size=%d: Das Netz "
                      "meldet %d Ankerpunkte, erwartet waren %d. Modell wird "
                      "abgeschaltet -- es bleiben drei Zeugen. Bitte "
                      "detection.person_model.input_size auf die "
                      "Eingangskante der Modelldatei setzen.",
                      self.eingang, werte.shape[0], self._gitter.shape[0])
            self._netz = None
            return []

        mitte = (werte[:, :2] + self._gitter) * self._schritte
        groesse = np.exp(werte[:, 2:4]) * self._schritte
        # Objektheit MAL Klassenwert: Das Netz trennt "hier ist etwas" von
        # "und es ist ein Mensch". Nur das Produkt ist vergleichbar.
        punkte = werte[:, SPALTE_OBJEKT] * werte[:, SPALTE_PERSON]
        treffer = punkte > self.vertrauen
        if not treffer.any():
            return []

        kaesten = [
            [int((mitte[i, 0] - groesse[i, 0] / 2 - ox) / faktor),
             int((mitte[i, 1] - groesse[i, 1] / 2 - oy) / faktor),
             int(groesse[i, 0] / faktor),
             int(groesse[i, 1] / faktor)]
            for i in np.flatnonzero(treffer)]
        gewichte = punkte[treffer].tolist()
        behalten = cv2.dnn.NMSBoxes(kaesten, gewichte, self.vertrauen, self.nms)
        if len(behalten) == 0:
            return []
        return [(*kaesten[int(i)], float(gewichte[int(i)]))
                for i in np.asarray(behalten).flatten()]

    def _briefkasten(self, bild: np.ndarray):
        """Auf Eingangsgroesse bringen, OHNE das Seitenverhaeltnis zu quetschen.

        Ein 900x300-Band auf 640x640 gestaucht macht aus jedem Menschen einen
        Zwerg mit falschen Proportionen -- das Netz kennt nur richtige.
        """
        h, w = bild.shape[:2]
        faktor = self.eingang / max(h, w)
        nw = max(1, int(round(w * faktor)))
        nh = max(1, int(round(h * faktor)))
        tafel = np.full((self.eingang, self.eingang, 3), 114, np.uint8)
        ox, oy = (self.eingang - nw) // 2, (self.eingang - nh) // 2
        tafel[oy:oy + nh, ox:ox + nw] = cv2.resize(bild, (nw, nh),
                                                   interpolation=cv2.INTER_LINEAR)
        return tafel, faktor, ox, oy

    # ------------------------------------------------------------------ Auskunft

    @staticmethod
    def _anteil_in(kasten, ziel) -> float:
        """Welcher Anteil von `ziel` steckt in `kasten`?"""
        ax, ay, aw, ah = kasten[:4]
        bx, by, bw, bh = ziel
        ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
        iy = max(0, min(ay + ah, by + bh) - max(ay, by))
        return (ix * iy) / max(1, bw * bh)

    def auf_tafel(self, kasten: tuple[int, int, int, int] | None,
                  frame_index: int) -> float:
        """Groesster Anteil dieser Tafel, den ein gefundener Mensch bedeckt."""
        funde = self.funde_fuer(frame_index)
        if kasten is None or not funde:
            return 0.0
        return max(self._anteil_in(f, kasten) for f in funde)

    def maske_im_ausschnitt(self, kasten: tuple[int, int, int, int] | None,
                            frame_index: int) -> np.ndarray | None:
        """Die gefundenen Menschen als Maske IM Tafelausschnitt.

        Fuer `board_image.schwaerze_fremdes`: Was hier weiss ist, wird im
        veroeffentlichten Bild schwarz.
        """
        funde = self.funde_fuer(frame_index)
        if kasten is None or not funde:
            return None
        x, y, w, h = kasten
        maske = np.zeros((h, w), np.uint8)
        etwas = False
        for bx, by, bw, bh, _ in funde:
            x0, y0 = max(0, bx - x), max(0, by - y)
            x1, y1 = min(w, bx + bw - x), min(h, by + bh - y)
            if x1 > x0 and y1 > y0:
                maske[y0:y1, x0:x1] = 255
                etwas = True
        return maske if etwas else None
