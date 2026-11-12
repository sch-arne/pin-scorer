"""Liest Frames aus einem laufenden Livestream.

Tritt an dieselbe Stelle wie `FileVideoSource` -- Analyse und Erkennung merken
den Unterschied nicht. Genau dafuer ist `VideoSource` abstrakt.

Was einen Stream von einer Datei unterscheidet:

**Es gibt kein Ende und keinen Anfang.** `read()` liefert nie None, solange die
Verbindung steht. Wo eine Datei irgendwann fertig ist, laeuft ein Stream bis
jemand ihn beendet.

**Man kann nicht zurueckspringen.** Was verpasst wurde, ist weg. Deshalb zaehlt
der Frame-Index bei einem Verbindungsabriss WEITER, statt neu zu beginnen: Die
Zustandsmaschine und der Ringpuffer arbeiten mit Indizes, und ein Ruecksprung
darin wuerde als Zeitreise erscheinen.

**Ein Aussetzer ist normal, kein Fehler.** Bei einer Datei ist ein
fehlgeschlagener `read()` ein ernstes Zeichen (siehe BUG-003). Bei einem Stream
ist er Alltag -- WLAN, Puffer, Umschaltung der Qualitaetsstufe. Deshalb wird
neu verbunden statt aufzugeben.

Die Randbedingungen sind vom Nutzer geklaert (2026-08-25): Das Overlay mit den
Tafeln bleibt waehrend der gesamten Uebertragung eingeblendet, es gibt keine
Werbeunterbrechung und keinen Kameraschnitt, und die Position ist innerhalb
einer Uebertragung stabil. Deshalb genuegt EINE Kalibrierung zu Beginn, und die
Analyse muss nicht erkennen, ob gerade etwas anderes im Bild ist.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import Callable

import cv2

from .source import Frame, VideoInfo, VideoSource, VideoSourceError

log = logging.getLogger(__name__)


class StreamVideoSource(VideoSource):
    """Videoquelle fuer einen laufenden Stream (HLS, RTSP, HTTP)."""

    def __init__(self, url: str, reconnect_attempts: int = 5,
                 reconnect_delay_s: float = 2.0,
                 read_failures_before_reconnect: int = 8,
                 open_timeout_ms: int = 10000,
                 read_timeout_ms: int = 5000,
                 rtsp_transport: str = "tcp",
                 restart_check: bool = True,
                 restart_probe_frames: int = 90,
                 restart_matches: int = 3,
                 resume_tolerance_frames: int = 100,
                 end_tolerance_frames: int = 100,
                 url_aufloesung: Callable[[], str] | None = None) -> None:
        if not url:
            raise ValueError("Stream-URL fehlt")
        self._url = url
        # ZWEI ADRESSEN, ABSICHTLICH. `_url` ist, was der Nutzer eingegeben hat
        # -- sie steht in jeder Meldung und in der `source_id`. `_spiel_url`
        # ist, was FFmpeg oeffnet. Bei einer YouTube-Adresse sind das zwei
        # verschiedene Dinge: Die abspielbare Adresse ist ueber 900 Zeichen
        # lang, in keiner Meldung lesbar, und sie VERFAELLT nach wenigen
        # Stunden. Deshalb wird sie bei jedem Verbindungsaufbau neu erfragt --
        # ein Lauf ueber einen ganzen Spieltag ueberlebt so ihren Ablauf.
        self._url_aufloesung = url_aufloesung
        self._spiel_url = url
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay_s = reconnect_delay_s
        self._read_failures_before_reconnect = read_failures_before_reconnect
        self._open_timeout_ms = open_timeout_ms
        self._read_timeout_ms = read_timeout_ms
        self._rtsp_transport = (rtsp_transport or "").strip().lower()

        self._cap: cv2.VideoCapture | None = None
        self._info: VideoInfo | None = None
        self._next_index = 0
        self._consecutive_failures = 0
        self._reconnects = 0
        self._lost_frames = 0
        self._started_at: float | None = None
        # Der beim Verbinden gelesene Pruefframe. Er wird NICHT verworfen:
        # Bei einem Livestream ist jeder Frame einmalig.
        self._pending: object | None = None
        self._finished = False

        # NEUANFANG DER QUELLE. Hinter einer m3u8-Adresse steckt oft eine
        # Aufzeichnung statt einer Live-Uebertragung; nach einem
        # Verbindungsabriss beginnt sie wieder bei null (2026-08-29 gemessen:
        # 1517 echte Wuerfe, danach 1693 Wiederholungen).
        self._restart_check = restart_check
        self._restart_probe_frames = restart_probe_frames
        self._restart_matches = restart_matches
        self._resume_tolerance_frames = resume_tolerance_frames
        self._end_tolerance_frames = end_tolerance_frames
        # Fingerabdruecke der ersten Frames, MIT ihrer Reihenfolge. Die
        # Reihenfolge ist das Entscheidende: Eine stehende Szene liefert
        # denselben Abdruck immer wieder, ein Neuanfang dagegen eine
        # AUFSTEIGENDE Folge. Nur die zweite ist ein Neuanfang.
        self._anfangsbilder: dict[bytes, int] = {}
        self._treffer_neustart = 0
        self._letzter_treffer: int | None = None

        # Laenge der Quelle laut FFmpeg. Bei einer echten Live-Uebertragung 0,
        # bei einer Aufzeichnung die Gesamtzahl der Frames (2026-08-30
        # gemessen: 312786 Frames = 3:28:31 fuer die Mux-Playlist). Nur wenn
        # sie bekannt ist, laesst sich nach einem Abriss wieder an die alte
        # Stelle springen, statt bei null weiterzulesen.
        self._gesamtframes = 0

    # ------------------------------------------------------------- Eigenschaften

    @property
    def url(self) -> str:
        return self._url

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    @property
    def info(self) -> VideoInfo:
        if self._info is None:
            raise VideoSourceError("Stream wurde noch nicht geoeffnet")
        return self._info

    @property
    def position(self) -> int:
        """Nummer des naechsten Frames -- laeuft ueber Aussetzer hinweg weiter."""
        return self._next_index

    @property
    def statistik(self) -> dict[str, int]:
        """Was unterwegs passiert ist -- gehoert ins Protokoll eines Spieltags."""
        return {"frames": self._next_index,
                "reconnects": self._reconnects,
                "verlorene_frames_geschaetzt": self._lost_frames}

    # ------------------------------------------------------------- Lebenszyklus

    def open(self) -> None:
        if self.is_open:
            return
        self._verbinden(erster_versuch=True)
        self._started_at = time.perf_counter()

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._pending = None
        if self._reconnects or self._lost_frames:
            log.info("Stream beendet: %d Frames, %d Neuverbindungen, "
                     "geschaetzt %d verlorene Frames",
                     self._next_index, self._reconnects, self._lost_frames)

    def seek(self, frame_index: int) -> bool:
        """Versucht zu springen. Liefert False, wenn die Quelle es nicht kann.

        Hinter einer Stream-Adresse kann eine AUFZEICHNUNG stehen -- dann ist
        ein Sprung moeglich und spart viel Zeit. GEMESSEN: Ohne ihn dauerte das
        Vorspulen auf Frame 11344 volle 77 Sekunden, in denen die Oberflaeche
        scheinbar nichts tat.

        Bei einer echten LIVE-Uebertragung meldet FFmpeg den Sprung haeufig als
        erfolgreich, bewegt sich aber nicht. Deshalb wird das Ergebnis
        NACHGEPRUEFT: Steht die Position danach nicht dort, wo sie soll, gilt
        der Sprung als gescheitert und der Aufrufer spult von Hand vor.

        Waehrend der laufenden Analyse wird nicht gesprungen -- das erledigt
        allein die Startposition.
        """
        if self._cap is None or frame_index < 0:
            return False
        if not self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_index)):
            return False

        erreicht = self._cap.get(cv2.CAP_PROP_POS_FRAMES)
        # Ein paar Frames Abweichung sind normal -- gesprungen wird auf das
        # naechste Schluesselbild.
        if abs(erreicht - frame_index) > 100:
            log.info("Sprung auf Frame %d nicht moeglich (Quelle steht bei %.0f)",
                     frame_index, erreicht)
            return False

        self._next_index = frame_index
        self._pending = None
        log.info("Auf Frame %d gesprungen", frame_index)
        return True

    # ------------------------------------------------------------- Lesen

    def read(self) -> Frame | None:
        """Liefert den naechsten Frame.

        Gibt None erst zurueck, wenn auch nach mehreren Neuverbindungen nichts
        mehr kommt -- dann ist die Uebertragung wirklich zu Ende.
        """
        if self._finished:
            # Nach dem Ende weiterhin None liefern statt zu werfen: Der
            # Aufrufer soll seine Schleife normal beenden koennen.
            return None
        if self._cap is None:
            raise VideoSourceError("Stream ist nicht geoeffnet")

        if self._pending is not None:
            bild, self._pending = self._pending, None
            # Auch der Pruefframe geht durch die Neuanfangs-Pruefung. Sonst
            # bliebe ausgerechnet der erste Frame nach einer Neuverbindung
            # ungeprueft -- und genau dort beginnt eine Wiederholung.
            if self._laeuft_von_vorn(bild):
                self._finished = True
                return None
            frame = Frame(self._next_index, self._zeitstempel(), bild)
            self._next_index += 1
            return frame

        while True:
            ok, bild = self._cap.read()
            if ok and bild is not None:
                if self._consecutive_failures:
                    log.debug("Stream wieder stabil nach %d Fehlversuchen",
                              self._consecutive_failures)
                self._consecutive_failures = 0
                if self._laeuft_von_vorn(bild):
                    self._finished = True
                    return None
                frame = Frame(self._next_index, self._zeitstempel(), bild)
                self._next_index += 1
                return frame

            self._consecutive_failures += 1
            if self._consecutive_failures < self._read_failures_before_reconnect:
                # Kurze Aussetzer sind bei einem Stream normal. Erst nach
                # mehreren Fehlversuchen lohnt der teure Verbindungsaufbau.
                # Eine kurze Pause verhindert, dass bei sofort scheiternden
                # Leseversuchen eine Schleife auf voller Last laeuft.
                time.sleep(0.05)
                continue

            if self._ist_abgespielt():
                # KEIN Abriss, sondern das Ende. Die Quelle kennt ihre Laenge
                # und wir sind dort angekommen -- eine Neuverbindung wuerde nur
                # denselben letzten Frame wiederfinden und nie einen naechsten
                # liefern (BUG-015: endlose Schleife am Ende des Spieltags).
                log.info("Die Aufzeichnung ist abgespielt: Frame %d von %d.",
                         self._next_index, self._gesamtframes)
                self._finished = True
                return None

            log.warning("Stream liefert seit %d Versuchen nichts -- neu verbinden",
                        self._consecutive_failures)
            if not self._neu_verbinden():
                self._finished = True
                return None

    @staticmethod
    def _fingerabdruck(bild) -> bytes:
        """Kurzer Wiedererkennungswert eines Bildes.

        16x16 Graustufen, jeweils gegen den Mittelwert -- 256 Bit. Robust gegen
        Kompressionsrauschen, aber spezifisch genug, dass zwei verschiedene
        Szenen praktisch nie denselben Wert ergeben.
        """
        import cv2
        import numpy as np

        klein = cv2.resize(cv2.cvtColor(bild, cv2.COLOR_BGR2GRAY), (16, 16),
                           interpolation=cv2.INTER_AREA)
        return np.packbits(klein > klein.mean()).tobytes()

    def _laeuft_von_vorn(self, bild) -> bool:
        """Hat die Quelle wieder von vorn angefangen?

        WARUM DAS NOETIG IST -- teuer gelernt am 2026-08-29: Hinter einer
        m3u8-Adresse steckt nicht zwangslaeufig eine Live-Uebertragung, sondern
        oft eine AUFZEICHNUNG. Reisst die Verbindung ab, beginnt sie beim
        Neuaufbau wieder bei null. Der Frame-Index laeuft hier aber monoton
        weiter, und die Analyse hat deshalb dasselbe Material ein zweites Mal
        als neue Wuerfe gebucht:

            1517 echte Wuerfe, danach 1693 Wiederholungen
            in der Datenbank standen alle doppelt

        Das Projekt hatte den Rueckwaertssprung ausdruecklich verboten --
        `seek()` gibt immer False, damit gebuchte Wuerfe nicht erneut kommen.
        Abgesichert war aber nur, dass WIR springen. Dass die QUELLE es von
        sich aus tut, war nicht bedacht, obwohl es derselbe Schaden ist.

        GEPRUEFT WIRD DAUERND, nicht nur nach einer Neuverbindung. Der erste
        Anlauf pruefte nur dort -- und lief genau deshalb ins Leere: Am
        2026-08-29 sprang die Quelle in einem Lauf zurueck, ohne dass unsere
        Leseschleife einen Abriss bemerkt hatte, und niemandem fiel es auf.

        Was einen Neuanfang von einer stehenden Szene unterscheidet, ist NICHT
        die Aehnlichkeit der Bilder, sondern ihre REIHENFOLGE. Eine Spielpause
        liefert denselben Abdruck immer wieder; ein Neuanfang liefert die
        gespeicherten Abdruecke in aufsteigender Folge. Deshalb zaehlt nur eine
        LUECKENLOS AUFSTEIGENDE Kette als Beleg.
        """
        if not self._restart_check:
            return False

        abdruck = self._fingerabdruck(bild)

        if len(self._anfangsbilder) < self._restart_probe_frames:
            # Gedaechtnis fuellen. Der Index ist der Rang, nicht der
            # Frame-Index -- so bleibt der Vergleich auch dann gueltig, wenn
            # unser Zaehler ueber einen Aussetzer hinweg weitergelaufen ist.
            self._anfangsbilder.setdefault(abdruck, len(self._anfangsbilder))
            return False

        rang = self._anfangsbilder.get(abdruck)
        if rang is None:
            self._treffer_neustart = 0
            self._letzter_treffer = None
            return False

        if self._letzter_treffer is not None and rang != self._letzter_treffer + 1:
            # Treffer, aber nicht der naechste in der Reihe: ein Standbild oder
            # ein Zufall, kein Neuanfang. Die Kette beginnt von vorn.
            self._treffer_neustart = 1
            self._letzter_treffer = rang
            return False

        self._treffer_neustart += 1
        self._letzter_treffer = rang
        if self._treffer_neustart < self._restart_matches:
            return False

        log.error("Der Stream hat wieder von vorn begonnen (Frame %d). "
                  "Es ist eine Aufzeichnung, keine Live-Uebertragung. "
                  "Die Auswertung wird beendet, damit dieselben Wuerfe nicht "
                  "ein zweites Mal gebucht werden.", self._next_index)
        return True

    def _zeitstempel(self) -> float:
        """Sekunden seit Beginn der Aufzeichnung.

        Bewusst aus dem Frame-Index gerechnet und nicht aus der Uhr: Die
        Zustandsmaschine misst Abstaende zwischen Ereignissen in Frames, und
        beides muss zusammenpassen. Nach einem Aussetzer stimmt der Wert dann
        zwar nicht mehr mit der Wanduhr ueberein -- dafuer bleibt er mit allem
        konsistent, was die Analyse sonst verwendet.
        """
        fps = self._info.fps if self._info and self._info.fps > 0 else 25.0
        return self._next_index / fps

    # ------------------------------------------------------------- Verbindung

    @contextlib.contextmanager
    def _transportweg(self):
        """Stellt FFmpeg fuer die Dauer des Verbindungsaufbaus auf TCP um.

        WARUM -- gemessen am 2026-09-08 an der Hallenkamera, zwoelf Sekunden
        je Durchgang, dieselbe Kamera, dieselbe Minute:

            udp: 4,7 fps gelesen, groesste Luecke 5089 ms, Decoderfehler
            tcp: 15,9 fps gelesen, groesste Luecke  235 ms, keine Fehler

        Ueber UDP gehen Pakete verloren. Ein grosses Schluesselbild zerfaellt
        in viele Pakete; fehlt eines, ist das ganze Bild hin. Sichtbar wird das
        zweifach: als Stillstand -- FFmpeg wartet auf den Rest, bis das
        Lesezeitlimit greift -- und als verstuemmeltes Bild, das trotzdem
        ausgeliefert wird. Das zweite ist das gefaehrlichere: Ein zerhackter
        Block ueber einer Ziffer ergibt einen falschen Wert, obwohl die ROI
        exakt sitzt.

        Der Weg fuehrt ueber eine Umgebungsvariable, weil OpenCV keinen
        eigenen Parameter dafuer hat. Sie wird nur um den Verbindungsaufbau
        herum gesetzt und danach auf den alten Stand zurueckgedreht -- eine
        dauerhaft gesetzte Variable wuerde jede andere Quelle im selben Prozess
        mitbetreffen, auch die Dateiwiedergabe.
        """
        if not self._rtsp_transport \
                or not self._spiel_url.lower().startswith("rtsp"):
            yield
            return

        schluessel = "OPENCV_FFMPEG_CAPTURE_OPTIONS"
        vorher = os.environ.get(schluessel)
        os.environ[schluessel] = f"rtsp_transport;{self._rtsp_transport}"
        try:
            yield
        finally:
            if vorher is None:
                os.environ.pop(schluessel, None)
            else:
                os.environ[schluessel] = vorher

    def _adresse_erneuern(self, erster_versuch: bool) -> None:
        """Erfragt die abspielbare Adresse neu, wenn sie erfragt werden muss.

        Nur bei einer Quelle mit Aufloesung -- also heute: bei YouTube. Eine
        dort genannte Medienadresse gilt wenige Stunden; ein Spieltag dauert
        laenger. Beim Wiederverbinden ist der Ablauf der Adresse deshalb ein
        genauso wahrscheinlicher Grund wie ein Netzaussetzer.

        Scheitert die Aufloesung mitten im Lauf, bleibt es bei der alten
        Adresse: Vielleicht ist sie noch gueltig und nur das Netz war kurz weg.
        Aufgegeben wird erst beim ERSTEN Versuch, denn dort weiss der Nutzer
        noch nichts von seinem Glueck.
        """
        if self._url_aufloesung is None:
            return
        try:
            neu = self._url_aufloesung()
        except Exception as exc:  # noqa: BLE001
            if erster_versuch:
                raise
            log.warning("Adresse liess sich nicht erneuern (%s) -- es wird "
                        "die bisherige weiterverwendet", exc)
            return
        if neu and neu != self._spiel_url:
            log.info("Abspielbare Adresse fuer %s neu erfragt", self._url)
            self._spiel_url = neu

    def _verbinden(self, erster_versuch: bool = False) -> bool:
        # Zeitlimits VOR dem Oeffnen setzen -- ohne sie wartet FFmpeg 30
        # Sekunden je Leseversuch. Gemessen, nachdem die Verbindung waehrend
        # des Kalibrierens weggelaufen war: Die Oberflaeche fror ein, weil der
        # Player im GUI-Thread liest.
        self._adresse_erneuern(erster_versuch)
        cap = cv2.VideoCapture()
        cap.setExceptionMode(False)
        with self._transportweg():
            cap.open(self._spiel_url, cv2.CAP_FFMPEG, [
                int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), self._open_timeout_ms,
                int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), self._read_timeout_ms,
            ])
        if not cap.isOpened():
            cap.release()
            if erster_versuch:
                raise VideoSourceError(
                    f"Stream nicht erreichbar: {self._url}\n"
                    f"Pruefen: Ist die URL noch gueltig? Laeuft die Uebertragung?"
                )
            return False

        # Puffer klein halten. Bei einem Livestream will man den AKTUELLEN
        # Frame, nicht den aeltesten aus der Warteschlange -- sonst laeuft die
        # Analyse dem Geschehen immer weiter hinterher.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        ok, probe = cap.read()
        if not ok or probe is None:
            cap.release()
            if erster_versuch:
                raise VideoSourceError(
                    f"Stream liefert keine Frames: {self._url}")
            return False

        hoehe, breite = probe.shape[:2]
        # Meldet die Quelle eine Laenge, ist sie eine AUFZEICHNUNG und kein
        # Live-Signal. Das ist die Unterscheidung, an der alles Weitere haengt:
        # Nur bei einer Aufzeichnung darf -- und muss -- nach einem Abriss
        # wieder an die alte Stelle gesprungen werden.
        laenge = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        self._gesamtframes = int(laenge) if laenge and laenge > 0 else 0
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0 or fps > 240:
            # Viele Streams melden keine oder unsinnige Bildrate.
            fps = 25.0
            log.info("Stream meldet keine brauchbare Bildrate -- es wird mit "
                     "25 fps gerechnet")

        self._cap = cap
        # Der Pruefframe ist ein regulaerer Frame -- er wird beim naechsten
        # read() ausgeliefert, nicht weggeworfen.
        self._pending = probe
        if self._info is None:
            self._info = VideoInfo(width=breite, height=hoehe, fps=fps,
                                   frame_count=None,   # ein Stream hat keine Laenge
                                   source_id=self._url)
            if self._gesamtframes:
                log.info("Stream geoeffnet: %dx%d, %.1f fps -- die Quelle "
                         "meldet %d Frames (%.0f min). Es ist eine "
                         "Aufzeichnung; nach einem Abriss wird an die alte "
                         "Stelle zurueckgesprungen.",
                         breite, hoehe, fps, self._gesamtframes,
                         self._gesamtframes / (fps * 60))
            else:
                log.info("Stream geoeffnet: %dx%d, %.1f fps -- die Quelle "
                         "meldet keine Laenge, also eine Live-Uebertragung.",
                         breite, hoehe, fps)
        elif (breite, hoehe) != (self._info.width, self._info.height):
            # Die Bildgroesse bestimmt alle ROI-Rechtecke. Aendert sie sich,
            # zeigt die Kalibrierung ins Leere -- das darf nicht stillschweigend
            # passieren.
            log.error("Stream liefert jetzt %dx%d statt %dx%d -- die "
                      "Kalibrierung passt nicht mehr!",
                      breite, hoehe, self._info.width, self._info.height)
        return True

    def _ist_abgespielt(self) -> bool:
        """Sind wir am Ende der Aufzeichnung -- oder ist die Leitung weg?

        Die Unterscheidung entscheidet ueber Weiterlesen oder Aufhoeren, und
        sie ist nur bei einer AUFZEICHNUNG moeglich: Nur dort meldet die Quelle
        eine Laenge. Ein Livestream hat kein Ende, das man erreichen koennte --
        dort ist jede Luecke ein Abriss.

        GEMESSEN 2026-08-30/31 (BUG-015): Erreicht wurden 312784 von gemeldeten
        312786 Frames. Ohne Toleranz gilt das nicht als Ende, und der Lauf
        drehte endlos -- alle sieben Sekunden ein "Abriss", ein erfolgreicher
        Ruecksprung auf 312784, und wieder kein Frame.
        """
        if not self._gesamtframes:
            return False
        return self._next_index >= self._gesamtframes - self._end_tolerance_frames

    def _wieder_aufsetzen(self) -> bool:
        """Setzt nach einem Abriss dort fort, wo gelesen wurde.

        WARUM -- gemessen am 2026-08-29/30: Die Uebertragung riss rund eine
        Stunde nach dem Verbindungsaufbau ab, bei Vorschau und Analyse zur
        selben Sekunde. Danach begann dieselbe Aufzeichnung wieder bei Frame 0,
        und die Analyse buchte dieselben Wuerfe ein zweites Mal.

        Den Abriss koennen wir nicht verhindern -- er kommt von der Gegenseite.
        Wir koennen aber an die alte Stelle zurueck: Die Playlist ist eine
        Aufzeichnung mit fester Laenge, und der Sprung ist framegenau
        (2026-08-30 geprueft: nach `set(POS_FRAMES, 50)` stimmte der
        Fingerabdruck des gelesenen Bildes mit dem des sequentiell gelesenen
        Frames 50 ueberein).

        Bei einer echten Live-Uebertragung gibt es nichts, wohin man springen
        koennte -- dort meldet die Quelle keine Laenge, und diese Funktion
        liefert False.
        """
        if self._cap is None:
            return False
        if self._ist_abgespielt():
            log.info("Die Aufzeichnung ist bei Frame %d zu Ende (%d Frames).",
                     self._next_index, self._gesamtframes)
            return False

        if not self._cap.set(cv2.CAP_PROP_POS_FRAMES, float(self._next_index)):
            log.warning("Ruecksprung auf Frame %d wurde abgelehnt.",
                        self._next_index)
            return False

        erreicht = self._cap.get(cv2.CAP_PROP_POS_FRAMES)
        # FFmpeg meldet einen Sprung auch dann als gelungen, wenn er nichts
        # bewirkt hat. Deshalb nachpruefen statt glauben.
        if abs(erreicht - self._next_index) > self._resume_tolerance_frames:
            log.error("Ruecksprung auf Frame %d misslungen -- die Quelle steht "
                      "bei %.0f. Es wird nicht weitergelesen, damit dieselben "
                      "Wuerfe nicht ein zweites Mal gebucht werden.",
                      self._next_index, erreicht)
            return False

        # Der beim Verbinden gelesene Pruefframe stammt vom Anfang der Quelle
        # und liegt jetzt hinter uns -- er darf nicht ausgeliefert werden.
        self._pending = None
        luecke = int(erreicht) - self._next_index
        if luecke:
            self._lost_frames += abs(luecke)
        log.warning("Stream riss ab und wurde bei Frame %d fortgesetzt "
                    "(Quelle steht bei %.0f). Es wurde nichts doppelt gelesen.",
                    self._next_index, erreicht)
        return True

    def _neu_verbinden(self) -> bool:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

        for versuch in range(1, self._reconnect_attempts + 1):
            if self._verbinden():
                self._reconnects += 1
                self._consecutive_failures = 0
                self._treffer_neustart = 0
                self._letzter_treffer = None

                if self._gesamtframes:
                    # AUFZEICHNUNG. Sie beginnt beim Neuaufbau wieder bei null.
                    # Es gibt hier nur zwei zulaessige Ausgaenge: Entweder wir
                    # setzen an der alten Stelle wieder auf, oder wir hoeren
                    # auf. Einfach weiterlesen hiesse, dieselben Wuerfe ein
                    # zweites Mal zu buchen -- genau der Schaden vom
                    # 2026-08-29.
                    if self._next_index <= 0:
                        return True          # noch nichts gelesen
                    if self._wieder_aufsetzen():
                        return True
                    log.error("Die Aufzeichnung liesse sich nur von vorn "
                              "lesen. Die Auswertung wird beendet, damit "
                              "dieselben Wuerfe nicht ein zweites Mal "
                              "gebucht werden.")
                    return False

                # Eine echte Live-Uebertragung -- es gibt nichts, wohin man
                # springen koennte.
                # Waehrend der Unterbrechung ist Zeit vergangen. Wie viele
                # Frames genau fehlen, laesst sich nicht ermitteln -- der
                # Schaetzwert dient nur der Diagnose. Der Index laeuft bewusst
                # LUECKENLOS weiter: Ein Sprung darin waere fuer den Ringpuffer
                # und die Zustandsmaschine eine Zeitreise.
                geschaetzt = int(self._reconnect_delay_s * versuch
                                 * (self._info.fps if self._info else 25.0))
                self._lost_frames += geschaetzt
                log.warning("Stream wieder verbunden (Versuch %d). Geschaetzt "
                            "%d Frames verpasst -- dort erkannte Wuerfe fehlen.",
                            versuch, geschaetzt)
                return True
            log.warning("Neuverbindung %d/%d fehlgeschlagen",
                        versuch, self._reconnect_attempts)
            time.sleep(self._reconnect_delay_s * versuch)

        log.error("Stream nach %d Versuchen nicht wiederhergestellt -- Ende",
                  self._reconnect_attempts)
        return False
