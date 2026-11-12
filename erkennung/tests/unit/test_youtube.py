"""YouTube-Adressen als Videoquelle.

WOFUER -- Frage des Nutzers am 2026-09-10:

    "kann ich den Youtube link einfach an mein Debugtool geben? Oder muss ich
     den Download von dir finden?"

GEMESSEN, bevor irgendetwas gebaut wurde, mit
https://www.youtube.com/watch?v=SO7ShGGQpHM:

    direkt an OpenCV        geoeffnet=False, kein Frame          2,2 s
    ueber yt-dlp aufgeloest 1920x1080 @30 fps, erstes Frame da   1,4 s

Eine YouTube-Adresse ist eine Webseite, kein Video. Die Uebersetzung gehoert
deshalb in die Quellenfabrik -- an die EINE Stelle, an der entschieden wird,
was eine Angabe ist. Sonst beantwortet das Debugwerkzeug die Frage anders als
die Oberflaeche, und genau das war schon einmal ein Fehler.

KEIN TEST HIER GEHT INS NETZ. Geprueft wird die Verdrahtung, nicht YouTube.
"""

from __future__ import annotations

import sys
import types

import pytest

from kegel_cv.video.factory import open_source, source_label
from kegel_cv.video.source import VideoSourceError
from kegel_cv.video.stream_source import StreamVideoSource
from kegel_cv.video.youtube import ist_youtube, loese_auf, video_kennung

WATCH = "https://www.youtube.com/watch?v=SO7ShGGQpHM"


class TestErkennen:
    @pytest.mark.parametrize("adresse", [
        WATCH,
        "http://youtube.com/watch?v=SO7ShGGQpHM",
        "https://m.youtube.com/watch?v=SO7ShGGQpHM",
        "https://youtu.be/SO7ShGGQpHM",
        "https://www.youtube.com/live/SO7ShGGQpHM",
        "  https://www.youtube.com/watch?v=SO7ShGGQpHM  ",
    ])
    def test_alle_schreibweisen(self, adresse):
        assert ist_youtube(adresse)

    @pytest.mark.parametrize("adresse", [
        "rtsp://admin:x@172.17.0.108:554/h265Preview_02_main",
        "https://cdn.example.com/live/tag1.m3u8",
        "kegelVideos/verbandsliga_voll.mp4",
        "C:/Users/nikla/kegelVideos/spiel.mp4",
        "https://youtube.evil.example.com/watch?v=SO7ShGGQpHM",
    ])
    def test_alles_andere_nicht(self, adresse):
        assert not ist_youtube(adresse)


class TestKennung:
    """Die Kennung ist das einzig Stabile an einer YouTube-Adresse."""

    @pytest.mark.parametrize("adresse", [
        WATCH,
        "https://youtu.be/SO7ShGGQpHM",
        "https://www.youtube.com/live/SO7ShGGQpHM",
        "https://www.youtube.com/embed/SO7ShGGQpHM",
        "https://www.youtube.com/shorts/SO7ShGGQpHM",
        "https://www.youtube.com/watch?v=SO7ShGGQpHM&t=1800s",
        "https://youtu.be/SO7ShGGQpHM?t=42",
    ])
    def test_dieselbe_kennung_aus_jeder_form(self, adresse):
        assert video_kennung(adresse) == "SO7ShGGQpHM"

    def test_ohne_youtube_keine_kennung(self):
        assert video_kennung("https://cdn.example.com/live/tag1.m3u8") is None

    def test_youtube_ohne_video_keine_kennung(self):
        assert video_kennung("https://www.youtube.com/") is None


class TestName:
    """HIER LAG EINE FALLE: Jedes YouTube-Video liegt unter `/watch`. Der
    bisherige Name aus Rechner und Pfadende haette fuer ALLE Videos
    `www.youtube.com_watch` ergeben -- ein gemeinsamer Debug-Ordner und
    dieselbe `video_id` in der Datenbank."""

    def test_die_kennung_steht_im_namen(self):
        assert source_label(WATCH) == "youtube_SO7ShGGQpHM"

    def test_zwei_videos_zwei_namen(self):
        a = source_label("https://www.youtube.com/watch?v=SO7ShGGQpHM")
        b = source_label("https://www.youtube.com/watch?v=aaaaaaaaaaa")
        assert a != b

    def test_dieselbe_sendung_derselbe_name(self):
        """Egal, wie der Link kopiert wurde -- der Lauf gehoert zusammen."""
        assert source_label("https://youtu.be/SO7ShGGQpHM?t=42") \
            == source_label(WATCH)


class TestFabrik:
    def test_youtube_wird_zur_stromquelle(self):
        quelle = open_source(WATCH)
        assert isinstance(quelle, StreamVideoSource)

    def test_beim_bauen_wird_noch_nichts_aufgeloest(self, monkeypatch):
        """Das Aufloesen geht ins Netz und dauert. `open_source` verspricht,
        NICHT zu oeffnen -- also darf es hier auch nicht heimlich passieren."""
        gerufen = []
        monkeypatch.setattr("kegel_cv.video.factory.loese_auf",
                            lambda *a, **k: gerufen.append(a) or "http://x")
        open_source(WATCH)
        assert gerufen == []

    def test_die_eingegebene_adresse_bleibt_sichtbar(self):
        """Die aufgeloeste Adresse ist ueber 900 Zeichen lang -- in einer
        Fehlermeldung waere sie unlesbar."""
        assert open_source(WATCH).url == WATCH

    def test_andere_streams_bekommen_keine_aufloesung(self):
        quelle = open_source("https://cdn.example.com/live/tag1.m3u8")
        assert quelle._url_aufloesung is None


class TestAdresseErneuern:
    """Eine YouTube-Medienadresse verfaellt nach wenigen Stunden. Ein Spieltag
    dauert laenger -- 3:08 h beim Verbandsligaspiel, ein voller Spieltag mehr.
    Beim Wiederverbinden ist der Ablauf deshalb ein ebenso wahrscheinlicher
    Grund wie ein Netzaussetzer."""

    def test_vor_jedem_verbinden_neu_gefragt(self):
        adressen = iter(["http://erste", "http://zweite"])
        q = StreamVideoSource(WATCH, url_aufloesung=lambda: next(adressen))
        q._adresse_erneuern(erster_versuch=True)
        assert q._spiel_url == "http://erste"
        q._adresse_erneuern(erster_versuch=False)
        assert q._spiel_url == "http://zweite"

    def test_der_erste_versuch_meldet_den_fehler(self):
        def kaputt():
            raise VideoSourceError("kein Netz")

        q = StreamVideoSource(WATCH, url_aufloesung=kaputt)
        with pytest.raises(VideoSourceError):
            q._adresse_erneuern(erster_versuch=True)

    def test_mitten_im_lauf_wird_weitergemacht(self):
        """P8: Ein Fehler beendet die Analyse nicht. Vielleicht war nur das
        Netz kurz weg und die alte Adresse gilt noch."""
        rufe = []

        def erst_gut_dann_kaputt():
            rufe.append(1)
            if len(rufe) == 1:
                return "http://gueltig"
            raise RuntimeError("Netz weg")

        q = StreamVideoSource(WATCH, url_aufloesung=erst_gut_dann_kaputt)
        q._adresse_erneuern(erster_versuch=True)
        q._adresse_erneuern(erster_versuch=False)
        assert q._spiel_url == "http://gueltig"

    def test_ohne_aufloesung_bleibt_alles_wie_es_war(self):
        q = StreamVideoSource("rtsp://kamera/bahn")
        q._adresse_erneuern(erster_versuch=True)
        assert q._spiel_url == "rtsp://kamera/bahn"

    def test_rtsp_transport_richtet_sich_nach_der_spieladresse(self):
        """Der TCP-Umweg gilt fuer RTSP. Eine YouTube-Adresse ist HTTP -- die
        Umgebungsvariable darf dabei nicht gesetzt werden."""
        import os
        q = StreamVideoSource(WATCH, url_aufloesung=lambda: "https://media/x")
        q._adresse_erneuern(erster_versuch=True)
        with q._transportweg():
            assert "OPENCV_FFMPEG_CAPTURE_OPTIONS" not in os.environ


class TestAufloesen:
    """Kein Netz: yt_dlp wird durch eine Attrappe ersetzt."""

    def _attrappe(self, monkeypatch, info=None, fehler=None):
        modul = types.ModuleType("yt_dlp")

        class YoutubeDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=False):
                if fehler is not None:
                    raise fehler
                return info

        modul.YoutubeDL = YoutubeDL
        monkeypatch.setitem(sys.modules, "yt_dlp", modul)
        return modul

    def test_die_medienadresse_kommt_zurueck(self, monkeypatch):
        self._attrappe(monkeypatch, info={"url": "https://media/xyz",
                                          "title": "Verbandsliga",
                                          "width": 1920, "height": 1080})
        assert loese_auf(WATCH) == "https://media/xyz"

    def test_die_hoehe_wird_gedeckelt(self, monkeypatch):
        modul = self._attrappe(monkeypatch, info={"url": "https://media/xyz"})
        gemerkt = {}
        alt = modul.YoutubeDL.__init__

        def merken(self, opts):
            gemerkt.update(opts)
            alt(self, opts)

        modul.YoutubeDL.__init__ = merken
        loese_auf(WATCH, max_hoehe=720)
        assert "height<=720" in gemerkt["format"]

    def test_ein_fehler_wird_uebersetzt(self, monkeypatch):
        """yt-dlp wirft eigene Klassen -- der Nutzer soll lesen, was zu tun
        ist, und nicht raten muessen."""
        self._attrappe(monkeypatch, fehler=RuntimeError("Video unavailable"))
        with pytest.raises(VideoSourceError, match="aufloesen"):
            loese_auf(WATCH)

    def test_ohne_abspielbare_fassung_ein_klarer_fehler(self, monkeypatch):
        self._attrappe(monkeypatch, info={"title": "nur Werbung"})
        with pytest.raises(VideoSourceError, match="abspielbare"):
            loese_auf(WATCH)

    def test_ohne_yt_dlp_sagt_er_was_zu_tun_ist(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "yt_dlp", None)
        with pytest.raises(VideoSourceError, match="yt-dlp"):
            loese_auf(WATCH)
