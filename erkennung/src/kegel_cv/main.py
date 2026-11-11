"""Einstiegspunkt der Anwendung.

    python -m kegel_cv.main
    python -m kegel_cv.main --config config/default.yaml --log-level DEBUG
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import load_config
from .debug.logging_setup import setup_logging

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kegel_cv",
        description="Automatische Kegelerfassung aus Video",
    )
    parser.add_argument("--config", type=Path, default=None,
                        help="Pfad zur Konfigurationsdatei (Standard: config/default.yaml)")
    parser.add_argument("--video", type=Path, default=None,
                        help="Video direkt beim Start laden")
    parser.add_argument("--calibration", type=Path, default=None,
                        help="Kalibrierung direkt beim Start laden")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        default=None, help="Log-Level (uebersteuert die Konfiguration)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    overrides: dict = {}
    if args.log_level:
        overrides["logging"] = {"level": args.log_level}

    try:
        cfg = load_config(args.config, overrides or None)
    except (FileNotFoundError, ValueError) as exc:
        # Vor dem Logging-Setup -- daher direkt auf stderr
        print(f"Konfiguration konnte nicht geladen werden:\n{exc}", file=sys.stderr)
        return 2

    setup_logging(cfg.logging, cfg.project_root)
    log.info("Kegel_CV startet (Projektwurzel: %s)", cfg.project_root)
    # WELCHE Konfiguration -- und die beiden Werte, an denen sich die Profile
    # unterscheiden. Am 2026-09-08 lief ein Trainingsabend mit den
    # Overlay-Schwellen, waehrend danebenher mit den Kamera-Schwellen
    # nachgemessen wurde; im Protokoll sah beides gleich aus.
    # "aus" statt einer Zahl, wenn die Schranke abgeschaltet ist -- eine
    # Null waere an dieser Stelle irrefuehrend, denn sie ist es nicht.
    waerme = cfg.detection.lamps.warmth_min
    log.info("Konfiguration: %s | Verdeckungsschwelle %.1f | Waermeschranke %s",
             cfg.config_path, cfg.detection.green.occlusion_score,
             "aus" if waerme is None else "%.1f" % waerme)

    # Qt erst nach dem Logging importieren, damit Importfehler sauber im Log landen
    from PySide6.QtWidgets import QApplication

    from .gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Kegel_CV")

    window = MainWindow(cfg)
    window.show()

    if args.video:
        window._load_video(args.video)
    if args.calibration:
        from .calibration import Calibration
        try:
            window.session.calibration = Calibration.load(args.calibration)
            window._rebuild_lane_panels()
            window._refresh_active_lane_combo()
            window._redraw_overlays()
            window._update_calibration_hint()
        except (FileNotFoundError, ValueError) as exc:
            log.error("Kalibrierung konnte nicht geladen werden: %s", exc)

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
