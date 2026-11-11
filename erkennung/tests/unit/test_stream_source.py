"""Die Stream-Videoquelle.

Schwerpunkt sind die Eigenschaften, in denen sich ein Stream von einer Datei
unterscheidet -- alles andere deckt `test_video_source.py` ab.

Die Randbedingungen sind vom Nutzer geklaert (2026-08-25): Das Overlay mit den
Tafeln bleibt waehrend der ganzen Uebertragung eingeblendet, es gibt keine
Werbeunterbrechung und keinen Kameraschnitt, und die Position ist innerhalb
einer Uebertragung stabil.
"""

from __future__ import annotations

import numpy as np
import pytest

from kegel_cv.video.source import VideoSourceError
from kegel_cv.video.stream_source import StreamVideoSource


class UnechteCapture:
    """Ersatz fuer cv2.VideoCapture -- liefert Frames und faellt auf Wunsch aus."""

    def __init__(self, frames: int = 5, faellt_aus_ab: int | None = None,
                 groesse: tuple[int, int] = (240, 320),
                 springt: bool = False, laenge: float = 0.0) -> None:
        # `laenge` ist das, was FFmpeg als CAP_PROP_FRAME_COUNT meldet: 0 bei
        # einer echten Live-Uebertragung, die Framezahl bei einer Aufzeichnung.
        self.laenge = laenge
        self.springt = springt
        self.position = 0.0
        self.frames = frames
        self.faellt_aus_ab = faellt_aus_ab
        self.groesse = groesse
        self.gelesen = 0
        self.freigegeben = False
        self.geoeffnet = False
        self.params: list = []
        self.eigenschaften: dict[int, float] = {}
        self.transport_beim_oeffnen: str | None = None

    def isOpened(self) -> bool:            # noqa: N802 (cv2-Schnittstelle)
        return self.geoeffnet and not self.freigegeben

    def open(self, url, backend=None, params=None) -> bool:  # noqa: A003
        """Seit den Zeitlimits wird `VideoCapture()` leer erzeugt und dann
        geoeffnet -- nur so lassen sich Parameter mitgeben."""
        import os
        self.geoeffnet = True
        self.params = params or []
        # Der Transportweg kommt nicht als Parameter, sondern ueber eine
        # Umgebungsvariable -- OpenCV kennt keinen eigenen dafuer. Deshalb wird
        # hier festgehalten, wie sie im Moment des Oeffnens stand.
        self.transport_beim_oeffnen = os.environ.get(
            "OPENCV_FFMPEG_CAPTURE_OPTIONS")
        return True

    def setExceptionMode(self, an: bool) -> None:   # noqa: N802
        pass

    def read(self):
        if self.faellt_aus_ab is not None and self.gelesen >= self.faellt_aus_ab:
            return False, None
        if self.gelesen >= self.frames:
            return False, None
        self.gelesen += 1
        return True, np.zeros((*self.groesse, 3), dtype=np.uint8)

    def get(self, prop: int) -> float:
        import cv2
        if prop == cv2.CAP_PROP_POS_FRAMES:
            return self.position
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return self.laenge
        return 25.0

    def set(self, prop: int, wert: float) -> bool:
        import cv2
        self.eigenschaften[prop] = wert
        if prop == cv2.CAP_PROP_POS_FRAMES:
            # Eine echte Live-Uebertragung meldet Erfolg, bewegt sich aber nicht.
            if self.springt:
                self.position = wert
            return True
        return True

    def release(self) -> None:
        self.freigegeben = True


@pytest.fixture
def capture(monkeypatch):
    """Gibt eine Fabrik zurueck, die die naechste Capture bestimmt."""
    erzeugte: list[UnechteCapture] = []
    bauplan: dict = {"naechste": lambda: UnechteCapture()}

    def fabrik(*args, **kwargs):
        cap = bauplan["naechste"]()
        erzeugte.append(cap)
        return cap

    monkeypatch.setattr("kegel_cv.video.stream_source.cv2.VideoCapture", fabrik)
    monkeypatch.setattr("kegel_cv.video.stream_source.time.sleep", lambda s: None)
    return bauplan, erzeugte


class TestGrundlagen:
    def test_ohne_url_kein_objekt(self):
        with pytest.raises(ValueError):
            StreamVideoSource("")

    def test_ein_stream_hat_keine_laenge(self, capture):
        bauplan, _ = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=100)

        quelle = StreamVideoSource("http://beispiel/stream.m3u8")
        quelle.open()

        assert quelle.info.frame_count is None
        assert quelle.info.width == 320

    def test_sprung_wird_nachgeprueft(self, capture):
        """Bei einer echten Live-Uebertragung meldet FFmpeg den Sprung oft als
        erfolgreich, bewegt sich aber nicht. Ein ungeprueftes True liesse die
        Analyse an der falschen Stelle beginnen."""
        bauplan, _ = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10, springt=False)

        quelle = StreamVideoSource("http://beispiel/stream.m3u8")
        quelle.open()

        assert quelle.seek(5000) is False, "ohne Bewegung gilt der Sprung als gescheitert"

    def test_gelungener_sprung_setzt_die_position(self, capture):
        """Hinter einer Stream-Adresse kann eine Aufzeichnung stehen -- dort
        spart der Sprung 77 Sekunden Vorspulen (gemessen)."""
        bauplan, _ = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=20000, springt=True)

        quelle = StreamVideoSource("http://beispiel/aufzeichnung.m3u8")
        quelle.open()

        assert quelle.seek(11344) is True
        assert quelle.read().index == 11344

    def test_unerreichbarer_stream_meldet_sich_deutlich(self, capture):
        bauplan, _ = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=0)

        quelle = StreamVideoSource("http://beispiel/tot.m3u8")
        with pytest.raises(VideoSourceError, match="keine Frames|nicht erreichbar"):
            quelle.open()

    def test_puffer_wird_klein_gehalten(self, capture):
        """Bei einem Livestream will man den aktuellen Frame, nicht den
        aeltesten aus der Warteschlange."""
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10)

        StreamVideoSource("http://beispiel/stream.m3u8").open()

        import cv2
        assert erzeugte[0].eigenschaften.get(cv2.CAP_PROP_BUFFERSIZE) == 1

    def test_zeitlimits_werden_gesetzt(self, capture):
        """Ohne sie wartet FFmpeg 30 Sekunden je Leseversuch -- gemessen, als
        die Verbindung waehrend des Kalibrierens weggelaufen war."""
        import cv2

        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10)

        StreamVideoSource("http://beispiel/stream.m3u8",
                          open_timeout_ms=9000, read_timeout_ms=4000).open()

        params = erzeugte[0].params
        assert int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC) in params
        assert 9000 in params and 4000 in params


class TestTransportweg:
    """RTSP ueber TCP statt UDP.

    GEMESSEN 2026-09-08 an der Hallenkamera (Reolink, 2304x1296, h264), je
    zwoelf Sekunden, dieselbe Kamera, dieselbe Minute:

        udp:  4,7 fps gelesen | groesste Luecke 5089 ms | Decoderfehler
        tcp: 15,9 fps gelesen | groesste Luecke  235 ms | keine Fehler

    Ein verlorenes UDP-Paket zerstoert das ganze Bild. Es fehlt dann entweder
    -- Stillstand, bis das Lesezeitlimit greift -- oder es kommt verstuemmelt
    an. Das zweite ist das schlimmere: Ein zerhackter Block ueber einer Ziffer
    liefert einen falschen Wert, obwohl die ROI exakt sitzt.
    """

    def test_rtsp_wird_ueber_tcp_geoeffnet(self, capture):
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10)

        StreamVideoSource("rtsp://kamera/stream").open()

        assert erzeugte[0].transport_beim_oeffnen == "rtsp_transport;tcp"

    def test_transportweg_ist_einstellbar(self, capture):
        """Sollte eine Kamera kein TCP koennen, muss UDP erreichbar bleiben."""
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10)

        StreamVideoSource("rtsp://kamera/stream", rtsp_transport="udp").open()

        assert erzeugte[0].transport_beim_oeffnen == "rtsp_transport;udp"

    def test_ohne_transportweg_bleibt_ffmpeg_unbehelligt(self, capture):
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10)

        StreamVideoSource("rtsp://kamera/stream", rtsp_transport="").open()

        assert erzeugte[0].transport_beim_oeffnen is None

    def test_nur_rtsp_ist_betroffen(self, capture):
        """Eine HLS-Adresse kennt keinen rtsp_transport -- die Variable dort
        zu setzen waere bestenfalls wirkungslos."""
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10)

        StreamVideoSource("https://beispiel/stream.m3u8").open()

        assert erzeugte[0].transport_beim_oeffnen is None

    def test_die_variable_wird_danach_zurueckgedreht(self, capture, monkeypatch):
        """Sie wirkt prozessweit. Bliebe sie stehen, betraefe sie auch die
        Dateiwiedergabe im selben Prozess."""
        import os

        bauplan, _ = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10)
        monkeypatch.setenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", "etwas;anderes")

        StreamVideoSource("rtsp://kamera/stream").open()

        assert os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] == "etwas;anderes"

    def test_ohne_vorherigen_wert_bleibt_die_variable_weg(self, capture,
                                                          monkeypatch):
        import os

        bauplan, _ = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=10)
        monkeypatch.delenv("OPENCV_FFMPEG_CAPTURE_OPTIONS", raising=False)

        StreamVideoSource("rtsp://kamera/stream").open()

        assert "OPENCV_FFMPEG_CAPTURE_OPTIONS" not in os.environ

    def test_auch_die_neuverbindung_geht_ueber_tcp(self, capture):
        """Der Abriss ist genau der Moment, in dem UDP am haeufigsten
        scheitert -- dort darf der Transportweg nicht verlorengehen."""
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(frames=2)
        quelle = StreamVideoSource("rtsp://kamera/stream",
                                   read_failures_before_reconnect=2)
        quelle.open()
        quelle.read()
        quelle.read()
        bauplan["naechste"] = lambda: UnechteCapture(frames=5)
        quelle.read()

        assert len(erzeugte) > 1, "es wurde nicht neu verbunden"
        assert erzeugte[-1].transport_beim_oeffnen == "rtsp_transport;tcp"


class TestAussetzer:
    def test_kurzer_aussetzer_fuehrt_nicht_zum_abbruch(self, capture):
        """Ein fehlgeschlagener read() ist bei einem Stream Alltag -- anders als
        bei einer Datei, wo er ein ernstes Zeichen ist (siehe BUG-003)."""
        bauplan, _ = capture
        zaehler = {"n": 0}

        def naechste():
            zaehler["n"] += 1
            # Erste Verbindung liefert 3 Frames, dann nichts mehr.
            # Die zweite liefert wieder welche.
            return UnechteCapture(frames=3 if zaehler["n"] == 1 else 5)

        bauplan["naechste"] = naechste
        quelle = StreamVideoSource("http://beispiel/stream.m3u8",
                                   read_failures_before_reconnect=3)
        quelle.open()

        gelesen = [quelle.read() for _ in range(6)]
        assert all(f is not None for f in gelesen[:5])
        assert quelle.statistik["reconnects"] >= 1

    def test_frame_index_laeuft_ueber_den_aussetzer_weiter(self, capture):
        """Der Kern: Ein Ruecksprung im Index waere fuer den Ringpuffer und die
        Zustandsmaschine eine Zeitreise."""
        bauplan, _ = capture
        zaehler = {"n": 0}

        def naechste():
            zaehler["n"] += 1
            return UnechteCapture(frames=2 if zaehler["n"] == 1 else 5)

        bauplan["naechste"] = naechste
        quelle = StreamVideoSource("http://beispiel/stream.m3u8",
                                   read_failures_before_reconnect=2)
        quelle.open()

        indizes = [f.index for f in (quelle.read() for _ in range(5))
                   if f is not None]

        assert indizes == sorted(indizes), "Indizes muessen monoton steigen"
        assert len(set(indizes)) == len(indizes), "und duerfen sich nicht wiederholen"

    def test_endgueltiger_ausfall_liefert_none(self, capture):
        bauplan, _ = capture
        zaehler = {"n": 0}

        def naechste():
            zaehler["n"] += 1
            return UnechteCapture(frames=2 if zaehler["n"] == 1 else 0)

        bauplan["naechste"] = naechste
        quelle = StreamVideoSource("http://beispiel/stream.m3u8",
                                   read_failures_before_reconnect=2,
                                   reconnect_attempts=2)
        quelle.open()

        for _ in range(2):
            quelle.read()
        assert quelle.read() is None, "irgendwann ist die Uebertragung zu Ende"

    def test_verlorene_frames_werden_beziffert(self, capture):
        """Fuer das Protokoll eines Spieltags: Wo eine Luecke war, fehlen Wuerfe."""
        bauplan, _ = capture
        zaehler = {"n": 0}

        def naechste():
            zaehler["n"] += 1
            return UnechteCapture(frames=2 if zaehler["n"] == 1 else 5)

        bauplan["naechste"] = naechste
        quelle = StreamVideoSource("http://beispiel/stream.m3u8",
                                   read_failures_before_reconnect=2)
        quelle.open()
        for _ in range(4):
            quelle.read()

        assert quelle.statistik["verlorene_frames_geschaetzt"] > 0


class TestNeuanfangDerQuelle:
    """Eine Aufzeichnung beginnt nach einem Abriss wieder bei null.

    TEUER GELERNT am 2026-08-29: Hinter der m3u8-Adresse steckte keine
    Live-Uebertragung, sondern eine Aufzeichnung. Nach einem Abriss lief sie
    wieder von vorn, der Frame-Index hier lief monoton weiter, und die Analyse
    buchte dasselbe Material ein zweites Mal:

        1517 echte Wuerfe, danach 1693 Wiederholungen
        in der Datenbank standen alle doppelt

    Das Projekt hatte den Rueckwaertssprung ausdruecklich verboten -- `seek()`
    gibt immer False. Abgesichert war aber nur, dass WIR springen. Dass die
    QUELLE es von sich aus tut, war nicht bedacht, obwohl es derselbe Schaden
    ist.

    Der erste Anlauf prueft NUR nach einer Neuverbindung -- und lief genau
    deshalb ins Leere: Am 2026-08-29 sprang die Quelle in einem Lauf zurueck,
    ohne dass die Leseschleife einen Abriss bemerkt hatte. Deshalb wird jetzt
    dauernd geprueft, und unterschieden wird an der REIHENFOLGE.
    """

    @staticmethod
    def _bild(seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        return rng.integers(0, 255, (64, 64, 3), dtype=np.uint8)

    def _quelle(self, **kw) -> StreamVideoSource:
        quelle = StreamVideoSource("http://beispiel/aufzeichnung.m3u8",
                                   restart_probe_frames=10, **kw)
        for i in range(10):
            quelle._laeuft_von_vorn(self._bild(i))     # Gedaechtnis fuellen
        return quelle

    def test_wiederholte_bilder_beenden_die_quelle(self):
        quelle = self._quelle()

        erkannt = [quelle._laeuft_von_vorn(self._bild(i)) for i in range(4)]

        assert any(erkannt), "der Neuanfang muss auffallen"

    def test_geprueft_wird_auch_ohne_neuverbindung(self):
        """Der Fall vom 2026-08-29: Die Quelle sprang zurueck, ohne dass die
        Leseschleife einen Abriss gesehen hatte. Eine Pruefung, die an die
        Neuverbindung gebunden ist, haette hier geschwiegen."""
        quelle = self._quelle()
        assert quelle._reconnects == 0

        assert any(quelle._laeuft_von_vorn(self._bild(i)) for i in range(4))

    def test_ein_einzelnes_gleiches_bild_reicht_nicht(self):
        """Sonst braeche eine zufaellige Uebereinstimmung die Auswertung ab."""
        quelle = self._quelle()

        assert quelle._laeuft_von_vorn(self._bild(0)) is False

    def test_stehendes_bild_ist_kein_neuanfang(self):
        """Eine Spielpause liefert DASSELBE Bild immer wieder. Ein Neuanfang
        liefert die gespeicherten Bilder in AUFSTEIGENDER Folge. Nur das
        zweite darf die Auswertung beenden -- sonst haette jede laengere
        Standzeit vor der Tafel den Spieltag abgebrochen."""
        quelle = self._quelle()

        assert not any(quelle._laeuft_von_vorn(self._bild(3))
                       for _ in range(20))

    def test_rueckwaerts_ist_kein_neuanfang(self):
        quelle = self._quelle()

        assert not any(quelle._laeuft_von_vorn(self._bild(i))
                       for i in (9, 8, 7, 6, 5))

    def test_neue_bilder_laufen_normal_weiter(self):
        quelle = self._quelle()

        assert not any(quelle._laeuft_von_vorn(self._bild(i))
                       for i in range(100, 110))

    def test_abschaltbar(self):
        quelle = self._quelle(restart_check=False)

        assert not any(quelle._laeuft_von_vorn(self._bild(i)) for i in range(4))


class TestBug015AufzeichnungEndetNicht:
    """Am Ende einer Aufzeichnung wird aufgehoert, nicht endlos neu verbunden.

    GEMESSEN 2026-08-30/31: Der Lauf ueber den vollen Spieltag erreichte Frame
    312784 von gemeldeten 312786 -- zwei Frames vor dem Ende. Weil das nicht
    als Ende galt, drehte er endlos:

        23:59:41  Stream liefert seit 25 Versuchen nichts -- neu verbinden
        23:59:46  Stream riss ab und wurde bei Frame 312784 fortgesetzt
        23:59:47  Stream liefert seit 25 Versuchen nichts -- neu verbinden
        ...

    Alle sieben Sekunden eine Runde. Der Lauf endete erst mit dem Herunterfahren
    des Rechners, und die Schlussbilanz -- Gruenzyklen ohne Wurfergebnis, die
    BUG-008-Kontrolle -- entstand nie.

    Die Quelle KANNTE ihre Laenge die ganze Zeit; sie hat sie nur nicht benutzt.
    """

    def test_am_ende_wird_beendet_statt_neu_verbunden(self, capture):
        bauplan, erzeugte = capture
        # 20 Frames Material, gemeldet werden 22 -- genau der reale Fall:
        # die letzten Frames einer HLS-Aufzeichnung fehlen.
        bauplan["naechste"] = lambda: UnechteCapture(
            frames=20, faellt_aus_ab=20, springt=True, laenge=22)
        quelle = StreamVideoSource("http://beispiel/aufzeichnung.m3u8",
                                   read_failures_before_reconnect=2,
                                   reconnect_attempts=1,
                                   end_tolerance_frames=100)
        quelle.open()
        for _ in range(20):
            assert quelle.read() is not None

        vorher = len(erzeugte)
        assert quelle.read() is None, "Am Ende muss None kommen"
        assert len(erzeugte) == vorher, (
            "Es wurde neu verbunden, obwohl die Aufzeichnung zu Ende ist -- "
            "genau die Endlosschleife von BUG-015"
        )

    def test_nach_dem_ende_bleibt_es_beim_ende(self, capture):
        """Der Aufrufer soll seine Schleife normal beenden koennen."""
        bauplan, _ = capture
        bauplan["naechste"] = lambda: UnechteCapture(
            frames=20, faellt_aus_ab=20, springt=True, laenge=22)
        quelle = StreamVideoSource("http://beispiel/a.m3u8",
                                   read_failures_before_reconnect=2,
                                   reconnect_attempts=1)
        quelle.open()
        for _ in range(20):
            quelle.read()

        assert quelle.read() is None
        assert quelle.read() is None

    def test_ein_abriss_MITTEN_drin_verbindet_weiterhin_neu(self, capture):
        """Die Toleranz darf nicht dazu fuehren, dass jeder Aussetzer als Ende
        gilt -- sonst waere BUG-014 zurueck, nur andersherum."""
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(
            frames=3, faellt_aus_ab=3, springt=True, laenge=312786)
        quelle = StreamVideoSource("http://beispiel/aufzeichnung.m3u8",
                                   read_failures_before_reconnect=2,
                                   reconnect_attempts=1)
        quelle.open()
        for _ in range(3):
            quelle.read()

        vorher = len(erzeugte)
        bauplan["naechste"] = lambda: UnechteCapture(
            frames=50, springt=True, laenge=312786)
        assert quelle.read() is not None
        assert len(erzeugte) > vorher, (
            "Bei Frame 3 von 312786 ist ein Aussetzer ein Abriss, kein Ende"
        )

    def test_livestream_kennt_kein_ende(self, capture):
        """Ohne gemeldete Laenge gibt es nichts, was 'zu Ende' heissen koennte."""
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(
            frames=3, faellt_aus_ab=3, laenge=0.0)
        quelle = StreamVideoSource("http://beispiel/live.m3u8",
                                   read_failures_before_reconnect=2,
                                   reconnect_attempts=1)
        quelle.open()
        for _ in range(3):
            quelle.read()

        vorher = len(erzeugte)
        bauplan["naechste"] = lambda: UnechteCapture(frames=50, laenge=0.0)
        assert quelle.read() is not None
        assert len(erzeugte) > vorher


class TestAbrissMittenInDerAufzeichnung:
    """Nach einem Abriss wird fortgesetzt, nicht neu begonnen.

    GEMESSEN 2026-08-29/30: Die Uebertragung riss rund eine Stunde nach dem
    Verbindungsaufbau ab -- bei Vorschau und Analyse zur selben Sekunde
    (22:24:40 und 22:24:47). Beide verbanden neu, beide bekamen dieselbe
    Aufzeichnung wieder ab Frame 0.

    Den Abriss koennen wir nicht verhindern. Wir koennen aber zurueck an die
    alte Stelle: Die Quelle meldet eine Laenge (312786 Frames = 3:28:31), und
    der Sprung ist framegenau (2026-08-30 geprueft).
    """

    def test_aufzeichnung_setzt_an_der_alten_stelle_fort(self, capture):
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(
            frames=3, faellt_aus_ab=3, springt=True, laenge=312786)
        quelle = StreamVideoSource("http://beispiel/aufzeichnung.m3u8",
                                   read_failures_before_reconnect=2,
                                   reconnect_attempts=1)
        quelle.open()
        for _ in range(3):
            quelle.read()
        stand = quelle.position

        bauplan["naechste"] = lambda: UnechteCapture(
            frames=50, springt=True, laenge=312786)
        quelle.read()

        import cv2
        assert erzeugte[-1].eigenschaften[cv2.CAP_PROP_POS_FRAMES] == float(stand)

    def test_misslungener_sprung_liest_nicht_doppelt_weiter(self, capture):
        """FFmpeg meldet einen Sprung auch dann als gelungen, wenn er nichts
        bewirkt. Dann lieber aufhoeren als dieselben Wuerfe noch einmal
        buchen."""
        bauplan, _ = capture
        bauplan["naechste"] = lambda: UnechteCapture(
            frames=500, faellt_aus_ab=500, springt=False, laenge=312786)
        quelle = StreamVideoSource("http://beispiel/aufzeichnung.m3u8",
                                   read_failures_before_reconnect=2,
                                   reconnect_attempts=1)
        quelle.open()
        for _ in range(500):
            quelle.read()
        assert quelle.position == 500

        bauplan["naechste"] = lambda: UnechteCapture(
            frames=50, springt=False, laenge=312786)

        assert quelle.read() is None

    def test_live_uebertragung_springt_nicht(self, capture):
        """Ohne gemeldete Laenge gibt es nichts, wohin man springen koennte --
        dort laeuft der Index wie bisher lueckenlos weiter."""
        bauplan, erzeugte = capture
        bauplan["naechste"] = lambda: UnechteCapture(
            frames=3, faellt_aus_ab=3, springt=True, laenge=0.0)
        quelle = StreamVideoSource("http://beispiel/live.m3u8",
                                   read_failures_before_reconnect=2,
                                   reconnect_attempts=1)
        quelle.open()
        for _ in range(3):
            quelle.read()

        bauplan["naechste"] = lambda: UnechteCapture(frames=50, laenge=0.0)
        frame = quelle.read()

        import cv2
        assert cv2.CAP_PROP_POS_FRAMES not in erzeugte[-1].eigenschaften
        assert frame is not None and frame.index == 3


class TestQuellenwahl:
    """Datei oder Stream -- die Entscheidung faellt an EINER Stelle.

    Sonst wird sie in Oberflaeche und Analyse verschieden beantwortet, und ein
    Stream laeuft an einem der beiden Orte als Datei auf.
    """

    @pytest.mark.parametrize("quelle,erwartet_stream", [
        ("kegelVideos/spiel.mp4", False),
        (r"C:\Users\nikla\video.mp4", False),      # Laufwerksbuchstabe
        ("/home/nikla/video.mp4", False),
        ("https://cdn.example.com/live.m3u8", True),
        ("http://example.com/stream", True),
        ("rtsp://kamera.local/stream", True),
    ])
    def test_erkennung(self, quelle, erwartet_stream):
        from kegel_cv.video.factory import is_stream

        assert is_stream(quelle) is erwartet_stream

    def test_laufwerksbuchstabe_ist_kein_schema(self):
        """`C:` sieht fuer urlparse wie ein Schema aus -- ist aber Windows."""
        from kegel_cv.video.factory import is_stream

        assert not is_stream(r"C:\Videos\kegeln.mp4")

    def test_passende_quelle_wird_gebaut(self):
        from kegel_cv.video.factory import open_source
        from kegel_cv.video.file_source import FileVideoSource

        assert isinstance(open_source("x.mp4"), FileVideoSource)
        assert isinstance(open_source("https://x/live.m3u8"), StreamVideoSource)

    def test_bezeichner_taugt_als_dateiname(self):
        """Wird fuer Debug-Ordner und als video_id beim Versand gebraucht."""
        from kegel_cv.video.factory import source_label

        assert source_label("kegelVideos/spiel.mp4") == "spiel.mp4"
        label = source_label("https://cdn.example.com/live/tag1.m3u8")
        assert "cdn.example.com" in label
        assert not any(z in label for z in r'/\:?*"<>|')

    def test_bezeichner_unterscheidet_zwei_uebertragungen(self):
        from kegel_cv.video.factory import source_label

        a = source_label("https://cdn.example.com/live/spieltag1.m3u8")
        b = source_label("https://cdn.example.com/live/spieltag2.m3u8")
        assert a != b
