"""Der Lesefaden fuer Livestreams.

WARUM ES IHN GIBT: Der Player laeuft an einer QTimer, also im GUI-Thread. Ein
`read()` auf einem Stream kann sekundenlang blockieren -- bei weggelaufener
Verbindung bis zum Zeitlimit. Passiert das im GUI-Thread, friert die gesamte
Oberflaeche ein. Gemessen, nachdem die Verbindung waehrend zweier Minuten
Kalibrierarbeit weggelaufen war:

    [WARN] Stream timeout triggered after 30005 ms
    [WARN] Stream timeout triggered after 30000 ms

Und: **Ein Livestream ist ein Livestream** (Nutzer, 2026-08-26). Er wartet
nicht, bis jemand mit dem Kalibrieren fertig ist. Deshalb liest der Faden
durchgehend weiter, auch wenn die Anzeige steht.
"""

from __future__ import annotations

import time

import numpy as np

from kegel_cv.gui.player import _StreamReader
from kegel_cv.video.source import Frame


class LangsameQuelle:
    """Videoquelle, die fuer jeden Frame spuerbar Zeit braucht."""

    def __init__(self, dauer_s: float = 0.05, anzahl: int | None = None) -> None:
        self.dauer_s = dauer_s
        self.anzahl = anzahl
        self.gelesen = 0

    def read(self) -> Frame | None:
        time.sleep(self.dauer_s)
        if self.anzahl is not None and self.gelesen >= self.anzahl:
            return None
        frame = Frame(self.gelesen, self.gelesen / 25.0,
                      np.zeros((4, 4, 3), dtype=np.uint8))
        self.gelesen += 1
        return frame


class TestLesefaden:
    def test_liest_ohne_zutun_weiter(self):
        """Der Kern: Auch wenn niemand abholt, laeuft der Stream weiter --
        sonst staut sich der Puffer oder die Verbindung stirbt."""
        quelle = LangsameQuelle(dauer_s=0.001)
        leser = _StreamReader(quelle, fps=500)     # Bremse hier ausgeschaltet
        leser.start()
        time.sleep(0.2)
        leser.stop()

        assert quelle.gelesen > 5, "der Faden muss von allein weiterlesen"

    def test_liest_hoechstens_im_takt_der_quelle(self):
        """Sonst laeuft eine AUFZEICHNUNG hinter einer Stream-Adresse im
        Zeitraffer: Ein echter Livestream liefert nur in Echtzeit, ein Mux-VOD
        laedt dagegen so schnell wie die Leitung hergibt.
        """
        quelle = LangsameQuelle(dauer_s=0.0)
        leser = _StreamReader(quelle, fps=25)
        leser.start()
        time.sleep(0.4)
        leser.stop()

        # 0,4 s bei 25 fps sind rund 10 Frames -- mit Reserve nach oben
        assert quelle.gelesen <= 16, (
            f"{quelle.gelesen} Frames in 0,4 s -- die Bremse greift nicht"
        )
        assert quelle.gelesen >= 5, "aber stehen bleiben darf er auch nicht"

    def test_liefert_den_juengsten_frame(self):
        """Aeltere Frames sind bei einem Livestream wertlos -- wer zurueckliegt,
        will aufholen, nicht nachspielen."""
        quelle = LangsameQuelle(dauer_s=0.001)
        leser = _StreamReader(quelle, fps=500)
        leser.start()
        time.sleep(0.15)
        erster = leser.newest()
        time.sleep(0.1)
        zweiter = leser.newest()
        leser.stop()

        assert erster is not None and zweiter is not None
        assert zweiter.index > erster.index, "es muss der NEUESTE Frame sein"

    def test_abholen_blockiert_nicht(self):
        """Genau dafuer ist der Faden da: Die Oberflaeche darf nie warten."""
        quelle = LangsameQuelle(dauer_s=0.4)
        leser = _StreamReader(quelle, fps=500)
        leser.start()

        begonnen = time.perf_counter()
        for _ in range(20):
            leser.newest()
        gebraucht = time.perf_counter() - begonnen
        leser.stop()

        assert gebraucht < 0.1, "newest() darf nie auf den Stream warten"

    def test_ende_wird_gemeldet(self):
        quelle = LangsameQuelle(dauer_s=0.001, anzahl=3)
        leser = _StreamReader(quelle, fps=500)
        leser.start()
        time.sleep(0.2)

        assert leser.ended is True
        leser.stop()

    def test_fehler_beendet_den_faden_ohne_absturz(self):
        """Eine Ausnahme im Faden darf die Anwendung nicht mitreissen."""
        class KaputteQuelle:
            def read(self):
                raise RuntimeError("Verbindung weg")

        leser = _StreamReader(KaputteQuelle(), fps=500)
        leser.start()
        time.sleep(0.1)

        assert leser.ended is True
        assert leser.newest() is None
        leser.stop()


class TestDebugOrdnerJeLauf:
    """Jeder Lauf bekommt einen eigenen Ordner.

    Ohne ihn schrieben mehrere Laeufe in dieselben `event_XXX`-Ordner: Die
    Bilder mischten sich, `event.json` wurde ueberschrieben. Beim Untersuchen
    eines Fehlers lagen dadurch Bilder aus ZWEI verschiedenen Videos im selben
    Ordner -- die daraus gebaute Zeitreihe war frei erfunden.
    """

    def test_zwei_laeufe_schreiben_nicht_ineinander(self, tmp_path):
        import time

        from kegel_cv.config.schema import DebugConfig
        from kegel_cv.debug.frame_logger import FrameLogger

        cfg = DebugConfig()
        erster = FrameLogger(cfg, tmp_path, "video.mp4")
        time.sleep(1.1)          # der Ordnername enthaelt Sekunden
        zweiter = FrameLogger(cfg, tmp_path, "video.mp4")

        assert erster.root != zweiter.root
        assert erster.event_directory(2, 1) != zweiter.event_directory(2, 1)

    def test_ordner_liegt_unter_dem_video(self, tmp_path):
        """Die Zuordnung zum Video muss erhalten bleiben -- sonst findet man
        die Laeufe eines bestimmten Spiels nicht mehr wieder."""
        from kegel_cv.config.schema import DebugConfig
        from kegel_cv.debug.frame_logger import FrameLogger

        logger = FrameLogger(DebugConfig(), tmp_path, "spieltag.mp4")

        assert "spieltag.mp4" in str(logger.root)
        assert logger.root.name.startswith("lauf_")
