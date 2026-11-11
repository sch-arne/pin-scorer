"""Bibliothek bekannter Tafeltypen -- damit eine Halle sich selbst erklaert.

DIE IDEE (vom Nutzer, 2026-09-09)

    "cool waere, wenn er standardmaessig wenn ein Stream startet schaut, ob er
     eins der bekannten Kegelboards aus seinem Repertoire kennt. Langfristig
     sollen alle typischen Boards selbststaendig erkannt werden."

Ein Tafeltyp besteht aus zwei Dingen:

* einem **Musterbild** -- die geradegerechnete Tafel, wie sie einmal
  aufgenommen wurde
* den **ROIs in normierten Tafelkoordinaten** -- wo Lampen und Ziffern auf
  dieser Bauart sitzen

Beides zusammen genuegt: Wird das Muster in einem neuen Bild wiedergefunden,
folgen alle Felder aus den vier gefundenen Ecken. Genau darauf beruht die
automatische Kalibrierung.

WAS EIN TYP NICHT IST: eine Halle. Dieselbe FUNK-Anlage steht in vielen
Vereinen. Der Typ beschreibt die BAUART, nicht den Ort -- deshalb traegt er
auch keine Adresse und keinen Vereinsnamen.

WIE SICHER IST SICHER GENUG

Die Zahl der tragenden Merkmale (RANSAC-Inlier) trennt sauber. GEMESSEN am
2026-09-09 ueber vier Tafeln in zwei verschiedenen Quellen: gelungene Treffer
hatten 15 bis 197 Merkmale, ein Fehltreffer 7 -- und der lag 1429 Pixel
daneben. Deshalb gilt ein Typ erst ab `min_inlier` als erkannt, und ein
erkannter Typ wird dem Nutzer VORGESCHLAGEN, nicht aufgezwungen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .board_finder import BoardFinder, Treffer, entzerre, quad_groesse
from .board_match import finde_tafeln, stabile_maske
from .model import Calibration
from .roi_feinschliff import schleife_nach

log = logging.getLogger(__name__)

# Neben jedem Tafeltyp liegt sein Musterbild unter demselben Namen.
MUSTER_ENDUNG = ".png"

# Ersatzmassstaebe fuer den Anker, nach gemessenem Ertrag geordnet.
# 0,6 und 0,7 trafen an keiner der acht Messstellen und fehlen deshalb.
ANKER_STUFEN = [0.9, 1.2, 0.8]


@dataclass
class Tafeltyp:
    """Eine bekannte Bauart: Musterbild plus die ROIs darauf."""

    name: str
    muster: np.ndarray
    kalibrierung: Calibration

    @property
    def bahn(self):
        """Die eine Bahn, die den Typ beschreibt."""
        return self.kalibrierung.lanes[0]


@dataclass
class Erkennung:
    """Ein erkannter Typ samt der gefundenen Tafeln."""

    typ: Tafeltyp
    treffer: list[Treffer]
    # Die Bilder, in denen gefunden wurde. Sie werden fuer den Feinschliff der
    # Bereiche gebraucht (`roi_feinschliff`) -- und der Median ueber mehrere
    # Bilder ist dort das, was den Effekt vom Rauschen trennt. Die Suche hat
    # sie ohnehin gesehen; sie wurden bisher nur weggeworfen.
    bilder: list[np.ndarray] = field(default_factory=list)

    @property
    def merkmale(self) -> int:
        return sum(t.inlier for t in self.treffer)


def lade_bibliothek(ordner: str | Path) -> list[Tafeltyp]:
    """Liest alle Tafeltypen aus einem Ordner.

    Ein Typ, dessen Musterbild fehlt, wird uebersprungen statt zu werfen: Eine
    unvollstaendige Bibliothek darf den Programmstart nicht verhindern.
    """
    ordner = Path(ordner)
    if not ordner.is_dir():
        return []

    typen: list[Tafeltyp] = []
    for pfad in sorted(ordner.glob("*.json")):
        # `<Typ>.korrekturen.json` sind gemerkte Handkorrekturen, kein Typ
        # (siehe `korrekturen.py`). Sie landeten hier als Tafeltyp, wurden
        # wegen des fehlenden Musterbildes verworfen -- und hinterliessen bei
        # jedem Start eine Warnung, die nach einem Fehler aussieht.
        if pfad.stem.endswith(".korrekturen"):
            continue
        bild_pfad = pfad.with_suffix(MUSTER_ENDUNG)
        if not bild_pfad.is_file():
            log.warning("Tafeltyp %s hat kein Musterbild (%s erwartet)",
                        pfad.stem, bild_pfad.name)
            continue
        muster = cv2.imread(str(bild_pfad))
        if muster is None:
            log.warning("Musterbild %s liess sich nicht lesen", bild_pfad.name)
            continue
        try:
            kal = Calibration.load(pfad)
        except Exception as exc:  # noqa: BLE001
            # Eine kaputte Datei darf die uebrigen Typen nicht mitnehmen.
            log.warning("Tafeltyp %s unbrauchbar: %s", pfad.stem, exc)
            continue
        if not kal.lanes:
            log.warning("Tafeltyp %s enthaelt keine Bahn", pfad.stem)
            continue
        typen.append(Tafeltyp(name=pfad.stem, muster=muster, kalibrierung=kal))
    log.info("Tafelbibliothek: %d Typen aus %s", len(typen), ordner)
    return typen


def erkenne(bild: np.ndarray, typen: list[Tafeltyp], *,
            min_inlier: int = 18, max_tafeln: int = 8,
            leiter: list[float] | None = None) -> Erkennung | None:
    """Sucht den Typ, der am besten zu diesem Bild passt.

    Gewertet wird nach der Zahl der TAFELN zuerst und der Summe der tragenden
    Merkmale danach: Ein Typ, der vier Tafeln findet, ist mehr wert als einer,
    der eine einzige besonders sicher trifft.

    `leiter` bietet das Musterbild in mehreren Groessen an. Ohne sie vertraegt
    der Abgleich nur den 0,8- bis 1,5-fachen Massstab -- mit ihr den 0,6- bis
    4-fachen (gemessen 2026-09-15, Belege in `config/schema.py`). Fuer eine
    fest montierte Kamera ist das gleichgueltig; fuer eine Handykamera, die
    irgendwo steht, entscheidet es darueber, ob ueberhaupt etwas gefunden wird.

    Rueckgabe None, wenn keiner passt -- das ist der Normalfall in einer
    unbekannten Halle und kein Fehler.
    """
    if bild is None or bild.size == 0 or not typen:
        return None

    stufen = [f for f in (leiter or [1.0]) if f > 0] or [1.0]
    finder = BoardFinder(min_inlier=min_inlier)
    bestes: Erkennung | None = None
    for typ in typen:
        vorlagen = [typ.muster if f == 1.0 else _skaliert(typ.muster, f)
                    for f in stufen]
        treffer = finder.finde_alle(bild, vorlagen, max_tafeln=max_tafeln)
        if not treffer:
            continue
        treffer = _verfeinere(bild, treffer, finder, max_tafeln)
        kandidat = Erkennung(typ=typ, treffer=treffer)
        log.debug("Tafeltyp %s: %d Tafeln, %d tragende Merkmale",
                  typ.name, len(treffer), kandidat.merkmale)
        if bestes is None or (len(kandidat.treffer), kandidat.merkmale) > \
                (len(bestes.treffer), bestes.merkmale):
            bestes = kandidat

    if bestes is not None:
        log.info("Tafeltyp erkannt: %s -- %d Tafeln, %d tragende Merkmale",
                 bestes.typ.name, len(bestes.treffer), bestes.merkmale)
    return bestes


def _mitte(quad) -> tuple[float, float]:
    q = np.asarray(quad, dtype=float)
    return float(q[:, 0].mean()), float(q[:, 1].mean())


def erkenne_ueber_frames(bilder: list[np.ndarray], typen: list[Tafeltyp], *,
                         min_inlier: int = 14, anker_inlier: int = 8,
                         min_frames: int = 2, max_tafeln: int = 8,
                         runden: int = 3,
                         stufen: list[float] | None = None) -> Erkennung | None:
    """Sucht ueber MEHRERE Standbilder statt ueber eines.

    WARUM EIN BILD NICHT GENUEGT -- gemessen 2026-09-10 am Verbandsligaspiel,
    16 Stichproben ueber 3:08 h, Typ FUNK_klassisch gegen vier gleiche Tafeln:

        4 Tafeln gefunden   1 Frame
        3 Tafeln            6 Frames
        1 Tafel             4 Frames
        gar nichts          5 Frames

    Der Grund steht auf der Tafel selbst: Leuchtende Kegellampen und wechselnde
    Ziffern veraendern genau die Merkmale, an denen der Abgleich haengt. Auf
    einem Bild mit vielen brennenden Lampen wurde KEINE Tafel gefunden, obwohl
    alle vier klar zu sehen waren.

    Was sich dagegen NICHT aendert, ist die Lage: Ein Overlay steht fest, und
    eine Tafel an der Wand steht auch fest. Deshalb wird ueber mehrere Bilder
    gesucht und nach Lage gebuendelt. Was in mindestens `min_frames` Bildern an
    derselben Stelle auftaucht, ist eine Tafel; ein Zufallstreffer wiederholt
    sich dort nicht.

    ZWEI SCHRANKEN, mit Absicht verschieden hoch:

    * `min_inlier` fuer den ANKER -- die erste Tafel, die mit der Vorlage aus
      der Bibliothek gefunden wird. Sie muss sitzen, denn aus ihr wird die
      Vorlage fuer alles Weitere geschnitten.
    * `anker_inlier` fuer die uebrigen. Sie duerfen niedriger liegen, weil die
      Wiederholung ueber mehrere Bilder die Sicherheit ersetzt, die sonst die
      hohe Schranke geben muesste. GEMESSEN: Die vierte Tafel kam mit 11
      tragenden Merkmalen -- unter der Schranke 14, aber an der richtigen
      Stelle und in drei Bildern.
    """
    bilder = [b for b in bilder if b is not None and b.size]
    if not bilder or not typen:
        return None

    bestes: Erkennung | None = None
    for typ in typen:
        treffer = _kette(bilder, typ.muster, min_inlier=min_inlier,
                         anker_inlier=anker_inlier, min_frames=min_frames,
                         max_tafeln=max_tafeln, runden=runden,
                         stufen=ANKER_STUFEN if stufen is None else stufen)
        if not treffer:
            continue
        kandidat = Erkennung(typ=typ, treffer=treffer)
        log.info("Tafeltyp %s ueber %d Bilder: %d Tafeln, %d tragende "
                 "Merkmale", typ.name, len(bilder), len(treffer),
                 kandidat.merkmale)
        if bestes is None or (len(kandidat.treffer), kandidat.merkmale) > \
                (len(bestes.treffer), bestes.merkmale):
            bestes = kandidat
    return bestes


class LaufendeSuche:
    """Eine Suche, die Bild fuer Bild waechst -- fuer den Livestream.

    WOFUER -- Einwand des Nutzers am 2026-09-10:

        "Das ganze soll ja spaeter im Livestream laufen, da kann er ja nicht
         einfach hin und herspringen ... eigentlich waere es besser, wenn er
         in den ersten 5-10 Sekunden das glattzieht ... und wenn es nach 20
         Sekunden immer noch nicht alle Boards gefunden hat"

    Ein Stream hat keine Vergangenheit: Es laesst sich nicht zu Frame 84750
    springen, um ein besseres Bild zu holen. Es gibt nur das naechste Bild.
    Also arbeitet die Suche andersherum -- sie nimmt entgegen, was kommt, und
    wird mit jedem Bild besser.

    ABBRUCH NACH ERFOLG, NICHT NACH ZEIT: Sind so viele Tafeln gefunden wie
    erwartet, ist die Suche fertig. GEMESSEN an der Aufzeichnung: Das tritt
    meist nach zwei bis vier Bildern ein -- keine zwanzig Sekunden Wartezeit,
    wenn es gut laeuft.
    """

    def __init__(self, typen: list[Tafeltyp], *, ziel_anzahl: int = 4,
                 min_inlier: int = 14, anker_inlier: int = 8,
                 min_frames: int = 2, max_tafeln: int = 8,
                 stufen: list[float] | None = None,
                 nachlauf: int = 6, min_guete: float = 0.45) -> None:
        self.typen = list(typen)
        self.stufen = ANKER_STUFEN if stufen is None else list(stufen)
        self.ziel_anzahl = max(1, ziel_anzahl)
        self.min_frames = min_frames
        self.max_tafeln = max_tafeln
        self.nachlauf = max(0, nachlauf)
        self.bilder_gesehen = 0
        self._fertig_seit: int | None = None
        self.min_guete = min_guete
        # BILD IN BILD statt Merkmalsabgleich (Entscheidung des Nutzers am
        # 2026-09-10). Die Vorlage wird als Ganzes gesucht, ueber ein Raster
        # aus Massstab und Drehung -- und die veraenderlichen Teile werden
        # dabei ausgeblendet. Genau das konnte ORB nicht: Brennende Lampen und
        # wechselnde Ziffern sind das, woran der Merkmalsabgleich scheiterte.
        #
        # Alles Uebrige bleibt, wie es gemessen wurde: Buendelung nach Lage
        # ueber mehrere Bilder, Median ueber die Funde, Nachlauf.
        self._stand: dict[str, dict] = {}
        for typ in self.typen:
            muster = cv2.cvtColor(typ.muster, cv2.COLOR_BGR2GRAY)
            self._stand[typ.name] = {
                "typ": typ, "muster": muster, "gruppen": [],
                "maske": stabile_maske(typ.muster, typ.bahn.rois),
                # Massstab und Drehung des ersten Fundes. Danach wird nur noch
                # eng darum gesucht: Dieselbe Uebertragung zeigt die Tafeln in
                # jedem Bild gleich gross. GEMESSEN 2026-09-10 ueber 22
                # Stichproben aus 4,4 Minuten Stream -- Massstab konstant 0,85,
                # obere Kante jedes Mal bei y=49.
                "skala": None, "winkel": None, "bereich": None}

    def fuettere(self, bild: np.ndarray) -> None:
        """Nimmt ein weiteres Standbild entgegen."""
        if bild is None or bild.size == 0:
            return
        self.bilder_gesehen += 1
        for stand in self._stand.values():
            skalen, winkel = self._raster(stand)
            funde = finde_tafeln(bild, stand["muster"], stand["maske"],
                                 max_tafeln=self.ziel_anzahl,
                                 skalen=skalen, winkel=winkel,
                                 min_guete=self.min_guete,
                                 bereich=stand["bereich"])
            if funde and stand["skala"] is None:
                bester = max(funde, key=lambda f: f.guete)
                stand["skala"], stand["winkel"] = bester.skala, bester.winkel
                # NUR DIE HOEHE EINSCHRAENKEN, nicht die Breite. Die Tafeln
                # stehen in einer Reihe; wer die Breite aus dem ersten Bild
                # ableitet, schliesst die Tafeln aus, die dort noch fehlten --
                # gemessen: 3 statt 4 Tafeln.
                alle = np.array([e for f in funde for e in f.quad], float)
                hoch = float(np.ptp(np.array(funde[0].quad)[:, 1]))
                stand["bereich"] = (0, alle[:, 1].min() - hoch,
                                    10 ** 6, alle[:, 1].max() + hoch)
                log.debug("Massstab %.3f, Drehung %+.1f, Gegend %s gemerkt",
                          bester.skala, bester.winkel, stand["bereich"])
            for fund in funde:
                treffer = Treffer(quad=fund.quad,
                                  inlier=int(round(fund.guete * 100)),
                                  paare=100, vorlage_index=0)
                _einsortieren(stand["gruppen"], (treffer, bild))

    def _raster(self, stand: dict):
        """Beim ersten Bild breit suchen, danach eng um das Gefundene.

        Die weite Suche kostet rund sieben Sekunden je Bild -- bei zehn
        Bildern waere die Kalibrierung eine Minute lang beschaeftigt. Ist der
        Massstab einmal bekannt, genuegt ein enges Raster darum.
        """
        if stand["skala"] is None:
            return None, None
        s, w = stand["skala"], stand["winkel"]
        return (np.arange(s - 0.025, s + 0.026, 0.0125),
                (w - 0.5, w, w + 0.5))

    # So viele Bilder gehen in den Feinschliff der Bereiche. Vier genuegen:
    # GEMESSEN 2026-09-11 streut derselbe Versatz ueber vier Stellen um 0,0 bis
    # 0,4 px, der Median daraus ist stabil. Mehr Bilder kosten nur Rechenzeit.
    FEINSCHLIFF_BILDER = 4

    def _bilder(self, stand: dict) -> list[np.ndarray]:
        """Verschiedene Bilder, in denen Tafeln gefunden wurden.

        Aus der groessten Gruppe genommen -- das ist die Tafel, die am
        haeufigsten sass, also die verlaesslichste Auswahl an brauchbaren
        Bildern. Doppelte werden uebergangen: Dieselbe Aufnahme zweimal zu
        messen macht den Median nicht stabiler.
        """
        if not stand["gruppen"]:
            return []
        groesste = max(stand["gruppen"], key=len)
        bilder: list[np.ndarray] = []
        for _, bild in groesste:
            if bild is None or any(b is bild for b in bilder):
                continue
            bilder.append(bild)
            if len(bilder) >= self.FEINSCHLIFF_BILDER:
                break
        return bilder

    def _treffer(self, stand: dict) -> list[Treffer]:
        treffer = [_gemittelt(g) for g in stand["gruppen"]
                   if len(g) >= self.min_frames]
        treffer.sort(key=lambda t: _mitte(t.quad)[0])
        return treffer

    @property
    def gefunden(self) -> int:
        """Zahl der Tafeln der derzeit besten Bauart."""
        return max((len(self._treffer(s)) for s in self._stand.values()),
                   default=0)

    @property
    def fertig(self) -> bool:
        """Sind so viele Tafeln gefunden wie erwartet?"""
        return self.gefunden >= self.ziel_anzahl

    @property
    def genug(self) -> bool:
        """Ist auch der Nachlauf abgearbeitet -- darf die Suche aufhoeren?

        WARUM WEITERSAMMELN, obwohl schon alle Tafeln da sind: Die Ecken
        werden ueber die Funde gemittelt, und gegen Schaetzrauschen hilft
        Mitteln nur, wenn es genug zu mitteln gibt. GEMESSEN 2026-09-10 ueber
        acht Stellen eines Spiels, Streuung der ROI-Lagen zwischen den vier
        baugleichen Tafeln:

            11 bis 13 Funde je Tafel    0,9 px
             2 bis  7 Funde je Tafel    1,8 px

        Die Suche ist meist nach zwei bis vier Bildern vollstaendig -- genau
        im schlechten Bereich. Der Nachlauf kostet im Livestream ein paar
        Sekunden und halbiert den Fehler.
        """
        if not self.fertig:
            return False
        if self._fertig_seit is None:
            self._fertig_seit = self.bilder_gesehen
        return self.bilder_gesehen - self._fertig_seit >= self.nachlauf

    def ergebnis(self) -> Erkennung | None:
        """Die beste Bauart mit ihren Tafeln -- oder None."""
        bestes: Erkennung | None = None
        for stand in self._stand.values():
            treffer = self._treffer(stand)
            if not treffer:
                continue
            kandidat = Erkennung(typ=stand["typ"], treffer=treffer,
                                 bilder=self._bilder(stand))
            if bestes is None or (len(kandidat.treffer), kandidat.merkmale) > \
                    (len(bestes.treffer), bestes.merkmale):
                bestes = kandidat
        if bestes is not None:
            log.info("Laufende Suche: %s, %d Tafeln aus %d Bildern, %d "
                     "tragende Merkmale", bestes.typ.name, len(bestes.treffer),
                     self.bilder_gesehen, bestes.merkmale)
            return bestes

        # EIN MISSERFOLG MUSS AUCH IM PROTOKOLL STEHEN. Am 2026-09-11 lief die
        # automatische Kalibrierung im Livestream zweimal ins Leere, und das
        # Protokoll enthielt dazu NICHTS -- zwischen "Bibliothek geladen" und
        # dem Programmende lagen 38 stumme Sekunden. Was hier steht, haette die
        # Ursache sofort gezeigt: ein Bild gesehen, Tafeln darin gefunden, aber
        # `min_frames` nicht erreicht.
        log.warning(
            "Laufende Suche ohne Ergebnis: %d Bilder gesehen, %s. Mindestens "
            "%d Bilder muessen dieselbe Tafel zeigen.",
            self.bilder_gesehen,
            ", ".join(f"{s['typ'].name}: {len(s['gruppen'])} Stellen, "
                      f"groesste in {max((len(g) for g in s['gruppen']), default=0)} "
                      f"Bildern" for s in self._stand.values()),
            self.min_frames)
        return None


def _kette(bilder: list[np.ndarray], muster: np.ndarray, *, min_inlier: int,
           anker_inlier: int, min_frames: int, max_tafeln: int,
           runden: int, stufen: list[float] | None = None) -> list[Treffer]:
    """Jede gefundene Tafel wird selbst zur Vorlage fuer die naechste Runde.

    WARUM DIE KETTE -- gemessen 2026-09-10 an sechs Stellen des Spiels:

        eine Vorlage      3, 3, 3, 3, 0, 4 Tafeln, schwaechster Treffer 13
        Ankerkette        4, 4, 4, 4, 0, 3 Tafeln, schwaechster Treffer 10,
                          tragende Merkmale je Tafel 46 bis 191

    Der Grund liegt am Blickwinkel: Das Overlay ist ein Ausschnitt einer
    echten Kameraaufnahme, die vier Tafeln stehen darin unterschiedlich
    schraeg. Eine Vorlage von der mittleren Tafel passt schlecht zur
    aeussersten rechten -- die wurde fast immer uebersehen. Ihr NACHBAR passt
    dagegen gut. So waechst die Suche von Tafel zu Tafel weiter, statt von
    einer einzigen Stelle aus alles erreichen zu muessen.
    """
    grob = BoardFinder(min_inlier=min_inlier)
    anker: tuple[Treffer, np.ndarray] | None = None
    for bild in bilder:
        t = finde_anker(grob, bild, muster, stufen, max_tafeln)
        if t is not None and (anker is None or t.inlier > anker[0].inlier):
            anker = (t, bild)
    if anker is None:
        return []

    fein = BoardFinder(min_inlier=anker_inlier)
    vorlagen = [_ausschnitt(anker[1], anker[0].quad)]
    gruppen: list[list[tuple[Treffer, np.ndarray]]] = []
    benutzt: set[int] = set()
    for _ in range(max(1, runden)):
        vorlagen = [v for v in vorlagen if v is not None and v.size]
        if not vorlagen:
            break
        for bild in bilder:
            for t in fein.finde_alle(bild, vorlagen, max_tafeln=max_tafeln):
                _einsortieren(gruppen, (t, bild))

        # Nur die BESTAETIGTEN Tafeln geben eine neue Vorlage her -- aus einem
        # einzelnen Zufallstreffer eine Vorlage zu schneiden hiesse, den
        # Irrtum zu vervielfaeltigen.
        vorlagen = []
        for i, g in enumerate(gruppen):
            if i in benutzt or len(g) < min_frames:
                continue
            benutzt.add(i)
            t, bild = max(g, key=lambda x: x[0].inlier)
            vorlagen.append(_ausschnitt(bild, t.quad))
        if not vorlagen:
            break

    treffer = [_gemittelt(g) for g in gruppen if len(g) >= min_frames]
    treffer.sort(key=lambda t: _mitte(t.quad)[0])   # von links nach rechts
    return treffer


def _gemittelt(gruppe: list[tuple[Treffer, np.ndarray]]) -> Treffer:
    """Aus mehreren Funden derselben Tafel einen mit gemittelten Ecken.

    WARUM MITTELN -- gemessen 2026-09-10. Die vier Tafeln im Overlay sind
    baugleich; wie unterschiedlich sie nach der Kalibrierung aussehen, ist
    also reines Schaetzrauschen. Ueber acht Stellen des Spiels, gemessen als
    Streuung der ROI-Lagen zwischen den vier Tafeln:

        bester Einzeltreffer   1,41 px
        Median ueber die Funde 1,25 px

    Der Median gewann in ALLEN acht Faellen oder lag gleichauf. Die Daten
    liegen ohnehin vor -- die Suche sammelt je Tafel mehrere Funde aus
    verschiedenen Bildern und warf bisher alle bis auf einen weg.

    MEDIAN, NICHT MITTELWERT: Ein einzelner Fehltreffer -- eine Tafel, vor der
    jemand steht -- zoege den Mittelwert mit, den Median nicht.

    Die tragenden Merkmale werden vom BESTEN Fund uebernommen: Sie beschreiben
    die Sicherheit des Fundes, nicht die Lage, und sollen weiter mit dem
    vergleichbar sein, was ohne Mittelung herauskaeme.
    """
    bester = max(gruppe, key=lambda x: x[0].inlier)[0]
    if len(gruppe) < 2:
        return bester
    ecken = np.median(np.array([t.quad for t, _ in gruppe], dtype=float),
                      axis=0)
    return Treffer(quad=[[float(x), float(y)] for x, y in ecken],
                   inlier=bester.inlier, paare=bester.paare,
                   vorlage_index=bester.vorlage_index)


def _ausschnitt(bild: np.ndarray, quad) -> np.ndarray:
    """Schneidet eine Tafel geradegerechnet aus einem Bild."""
    return entzerre(bild, quad, quad_groesse(quad))


def _skaliert(muster: np.ndarray, faktor: float) -> np.ndarray:
    hoehe, breite = muster.shape[:2]
    ziel = (max(8, int(breite * faktor)), max(8, int(hoehe * faktor)))
    return cv2.resize(muster, ziel,
                      interpolation=cv2.INTER_AREA if faktor < 1
                      else cv2.INTER_CUBIC)


def finde_anker(finder: BoardFinder, bild: np.ndarray, muster: np.ndarray,
                stufen: list[float] | None = None,
                max_tafeln: int = 8) -> Treffer | None:
    """Sucht die erste Tafel -- notfalls in mehreren Massstaeben.

    WARUM MASSSTAEBE -- Frage des Nutzers am 2026-09-10, warum die Vorschau so
    verzerrt aussieht, und ob eine entzerrte Vorlage nicht besser waere. Die
    Vorlage IST entzerrt; was nicht passt, ist die GROESSE. Das Muster
    FUNK_klassisch stammt von der Hallenkamera und ist 190x191 Pixel gross, die
    Tafeln im Overlay messen rund 158 -- ein Sprung von 1,2. ORB ist nur
    schwach massstabsunabhaengig.

    GEMESSEN 2026-09-10 an acht Stellen, tragende Merkmale des besten Ankers:

        Stelle    eigene Groesse   0,8    0,9    1,0    1,2
             0                20    15     27     20     24
         21187                 0     0     18      0      0
         84750                36    19     24     36     33
        127125                23    14     23     23     22
        169500                24     0     17     24     30
        254250                 0     0      0      0      0
        300000                30    14     27     30     31
        317812                27     0     25     27     24

    An Stelle 21187 fand NUR 0,9 etwas -- vorher blieb die Suche dort leer.
    0,6 und 0,7 trafen nirgends und fehlen deshalb.

    ZWEITE STUFE, NICHT ERSTE: Die eigene Groesse trifft in sechs von acht
    Faellen und kostet 0,15 s je Bild; alle Stufen kosten 0,65 s. Teure
    Arbeit nur dort, wo die billige versagt hat (P4).
    """
    treffer = finder.finde_alle(bild, [muster], max_tafeln=max_tafeln)
    if treffer:
        return max(treffer, key=lambda t: t.inlier)
    for faktor in (stufen or []):
        treffer = finder.finde_alle(bild, [_skaliert(muster, faktor)],
                                    max_tafeln=max_tafeln)
        if treffer:
            bester = max(treffer, key=lambda t: t.inlier)
            log.info("Anker erst im Massstab %.2f gefunden (%d tragende "
                     "Merkmale)", faktor, bester.inlier)
            return bester
    return None


def _einsortieren(gruppen: list[list[tuple[Treffer, np.ndarray]]],
                  neu: tuple[Treffer, np.ndarray],
                  toleranz: float = 0.5) -> None:
    """Legt einen Treffer zu denen an derselben Stelle -- oder eroeffnet neu.

    `toleranz` ist ein Anteil der Tafelgroesse: Zwei Funde gelten als dieselbe
    Tafel, wenn ihre Mitten naeher beieinander liegen als eine halbe
    Tafelbreite. Das ist grosszuegig genug fuer den Schaetzfehler eines
    schwachen Treffers und eng genug, um Nachbartafeln zu trennen -- die
    stehen rund eine ganze Tafelbreite auseinander (gemessen: Mitten bei
    554, 863, 1096, 1392 Pixel bei 159 Pixel Breite).
    """
    mx, my = _mitte(neu[0].quad)
    breite, hoehe = quad_groesse(neu[0].quad)
    for g in gruppen:
        gx, gy = _mitte(g[0][0].quad)
        if abs(mx - gx) < breite * toleranz and abs(my - gy) < hoehe * toleranz:
            g.append(neu)
            return
    gruppen.append([neu])


def _verfeinere(bild: np.ndarray, treffer: list[Treffer],
                finder: BoardFinder, max_tafeln: int) -> list[Treffer]:
    """Zweiter Durchgang mit einer Vorlage aus dem ZIELBILD selbst.

    Das Muster der Bibliothek stammt aus einer anderen Aufnahme -- anderes
    Licht, andere Kamera, anderer Massstab. Sobald der erste Durchgang eine
    Tafel gefunden hat, laesst sich aus dem Zielbild eine Vorlage schneiden,
    die zu allen uebrigen Tafeln desselben Bildes viel besser passt.

    GEMESSEN 2026-09-09, Muster von der Hallenkamera gegen ein Overlay-Video
    einer anderen Kamera: 92 -> 176 tragende Merkmale, und die am
    schlechtesten sitzende Tafel rueckte um 16 Pixel an die richtige Stelle.

    Uebernommen wird nur, was mindestens so viele Tafeln findet UND mehr
    tragende Merkmale hat -- sonst bleibt es beim ersten Durchgang.
    """
    bester = max(treffer, key=lambda t: t.inlier)
    eigene = entzerre(bild, bester.quad, quad_groesse(bester.quad))
    zweite = finder.finde_alle(bild, [eigene], max_tafeln=max_tafeln)
    if (len(zweite) >= len(treffer)
            and sum(t.inlier for t in zweite) > sum(t.inlier for t in treffer)):
        log.debug("Verfeinerung: %d -> %d Tafeln, %d -> %d Merkmale",
                  len(treffer), len(zweite),
                  sum(t.inlier for t in treffer),
                  sum(t.inlier for t in zweite))
        return zweite
    return treffer


def uebernimm(erkennung: Erkennung, nummern: list[int],
              bild: np.ndarray | None = None, *, quelle: str = "",
              feinschliff: bool = False,
              feinschliff_weite: int = 5, feinschliff_min_pixel: int = 200,
              feinschliff_max_versatz: float = 3.0) -> Calibration:
    """Baut aus einer Erkennung eine vollstaendige Kalibrierung.

    Die ROIs des Typs werden uebernommen -- sie liegen in normierten
    Tafelkoordinaten und gelten deshalb fuer jede Tafel dieser Bauart, egal wie
    gross oder schraeg sie im Bild steht.

    NUR FAST. Mit `feinschliff` wird jede Tafel danach einzeln nachgezogen:
    GEMESSEN 2026-09-11 wandert die Gruenlampe ueber die vier Tafeln um 1,6 px,
    waehrend die Lampenraute stehenbleibt -- innerhalb einer Tafel wollen die
    Gruppen unterschiedlich weit verschoben werden. Siehe `roi_feinschliff`.
    """
    if len(nummern) != len(erkennung.treffer):
        raise ValueError(
            f"{len(nummern)} Bahnnummern fuer {len(erkennung.treffer)} Tafeln")

    kal = erkennung.typ.kalibrierung.model_copy(deep=True)
    # DIE HERKUNFT GEHOERT ZUM NEUEN BILD, nicht zum Musterbild. Sonst erbt
    # jede automatische Kalibrierung die Aufloesung der Kamera, an der die
    # Bauart einmal vermessen wurde. GEMESSEN am 2026-09-10 im ersten
    # Livelauf: Der Typ FUNK_klassisch stammt von der Hallenkamera
    # (2304x1296), der Stream lieferte 1920x1080 -- und die Oberflaeche
    # warnte "ROIs passen vermutlich nicht", obwohl sie perfekt sassen.
    kal.source_hint.width = int(bild.shape[1]) if bild is not None else None
    kal.source_hint.height = int(bild.shape[0]) if bild is not None else None
    # ... und dasselbe gilt fuer Datum und Quelle. Sonst traegt jede
    # automatische Kalibrierung das Entstehungsdatum der BAUART und die
    # Adresse der Kamera, an der sie einmal vermessen wurde. GESEHEN am
    # 2026-09-11 an einer frisch gespeicherten Datei: "created 2026-09-08",
    # "video rtsp://<kamera>" -- beides falsch, beides unauffaellig, und beim
    # Suchen nach der richtigen Kalibrierung genau die Angaben, nach denen man
    # geht.
    kal.created = datetime.now().isoformat(timespec="seconds")
    kal.source_hint.video = quelle or None
    muster = erkennung.typ.bahn
    bahnen = []
    for i, (t, nummer) in enumerate(zip(erkennung.treffer, nummern), start=1):
        bahn = muster.model_copy(deep=True)
        bahn.lane_id = i                    # Position von links
        bahn.real_lane_number = int(nummer)
        bahn.quad = t.quad
        bahnen.append(bahn)
    kal.lanes = bahnen

    if feinschliff:
        bilder = erkennung.bilder or ([bild] if bild is not None else [])
        muster_grau = cv2.cvtColor(erkennung.typ.muster, cv2.COLOR_BGR2GRAY)
        maske = stabile_maske(erkennung.typ.muster, muster.rois)
        for bahn in bahnen:
            schleife_nach(bahn, muster_grau, maske, bilder,
                          weite=feinschliff_weite,
                          min_pixel=feinschliff_min_pixel,
                          max_versatz=feinschliff_max_versatz)
    return kal


def speichere_typ(ordner: str | Path, name: str, bild: np.ndarray,
                  kalibrierung: Calibration, lane_id: int | None = None) -> Path:
    """Legt einen neuen Tafeltyp an -- aus einem Bild und einer Kalibrierung.

    Das Musterbild wird in BEOBACHTETER Groesse abgelegt, nicht in einer
    Normgroesse. GEMESSEN: Eine auf 440x530 entzerrte Vorlage gegen eine im
    Bild 192 Pixel grosse Tafel -- Massstabssprung 2,3fach -- fand nur eine
    von vier Tafeln, die uebrigen lagen 160 bis 600 Pixel daneben.
    """
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    bahn = (next(l for l in kalibrierung.lanes if l.lane_id == lane_id)
            if lane_id is not None else kalibrierung.lanes[0])

    muster = entzerre(bild, bahn.quad, quad_groesse(bahn.quad))
    cv2.imwrite(str(ordner / f"{name}{MUSTER_ENDUNG}"), muster)

    nur_eine = kalibrierung.model_copy(deep=True)
    nur_eine.lanes = [bahn.model_copy(deep=True)]
    nur_eine.name = name
    ziel = ordner / f"{name}.json"
    nur_eine.save(ziel)
    log.info("Tafeltyp %s angelegt: Muster %dx%d px", name,
             muster.shape[1], muster.shape[0])
    return ziel
