"""Logging-Einrichtung.

Logging ist von Anfang an integriert (Auftrag Paragraph 16), nicht nachtraeglich.
Meldungen sind deutschsprachig -- der Nutzer liest sie.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

from ..config.schema import LoggingConfig

_CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(name)-28s %(message)s"
_FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)-28s [%(filename)s:%(lineno)d] %(message)s"
_TIME_FORMAT = "%H:%M:%S"

_configured = False


def setup_logging(cfg: LoggingConfig, project_root: Path | None = None) -> None:
    """Richtet Konsolen- und Datei-Logging ein.

    Mehrfachaufruf ist unschaedlich: Bestehende Handler werden ersetzt, damit
    beim Neuladen der Konfiguration keine doppelten Ausgaben entstehen.
    """
    global _configured

    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.level))

    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    if cfg.console:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(_CONSOLE_FORMAT, _TIME_FORMAT))
        root.addHandler(console)

    if cfg.file:
        log_path = Path(cfg.file)
        if project_root is not None and not log_path.is_absolute():
            log_path = project_root / log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Rotierend: Bei 25 fps und vier Bahnen waechst eine DEBUG-Logdatei
        # sonst unbegrenzt.
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=cfg.max_file_mb * 1024 * 1024,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
        root.addHandler(file_handler)

    # Qt-interne Meldungen sind sehr gespraechig und selten hilfreich.
    logging.getLogger("PySide6").setLevel(logging.WARNING)

    _configured = True
    logging.getLogger(__name__).debug("Logging eingerichtet (Level %s)", cfg.level)


def is_configured() -> bool:
    return _configured
