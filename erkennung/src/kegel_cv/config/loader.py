"""Laden und Zusammenfuehren der Konfiguration."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml

from .schema import AppConfig

log = logging.getLogger(__name__)

DEFAULT_CONFIG_NAME = "default.yaml"


def find_project_root(start: Path | None = None) -> Path:
    """Sucht die Projektwurzel anhand des config-Verzeichnisses.

    Damit funktioniert der Start aus jedem Arbeitsverzeichnis heraus -- sonst
    haengt das Laden davon ab, wo der Nutzer die Anwendung aufgerufen hat.
    """
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        try:
            if (candidate / "config" / DEFAULT_CONFIG_NAME).is_file():
                return candidate
        except OSError:
            # Nicht jedes Elternverzeichnis laesst sich befragen. Auf Android
            # ist `/config` ein gesperrtes Kernel-Verzeichnis: Der Zugriff wirft
            # PermissionError, statt schlicht "nein" zu sagen -- und die Suche
            # brach damit ab, bevor sie fertig war (gemessen 2026-09-14 auf dem
            # Geraet). Ein unlesbares Verzeichnis ist keine Projektwurzel;
            # weitersuchen.
            continue
    # Fallback: drei Ebenen ueber diesem Modul (src/kegel_cv/config/loader.py)
    return Path(__file__).resolve().parents[3]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Fuehrt zwei Konfigurations-Dicts zusammen (override gewinnt).

    Verschachtelte Dicts werden rekursiv gemischt, damit eine Nutzerkonfiguration
    einzelne Werte ueberschreiben kann, ohne ganze Bloecke wiederholen zu muessen.
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_env_file(path: Path) -> int:
    """Liest Zugangsdaten aus einer `.env`-Datei in die Umgebung.

    Warum ueberhaupt: Zugangsdaten gehoeren nicht in `config/default.yaml` --
    die Datei liegt in der Versionsverwaltung. Der uebliche Weg unter Windows
    waere `setx`, das schreibt den Wert aber dauerhaft in die Registrierung des
    Benutzers. Eine Datei im Projekt ist sichtbar, jederzeit loeschbar und laesst
    sich ueber `.gitignore` sauber ausschliessen.

    Bereits gesetzte Umgebungsvariablen werden NICHT ueberschrieben: Wer den
    Wert bewusst im System gesetzt hat, soll ihn nicht von einer Datei
    verdraengt bekommen.

    Returns:
        Anzahl der uebernommenen Eintraege.
    """
    if not path.is_file():
        return 0

    uebernommen = 0
    for zeile in path.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, _, wert = zeile.partition("=")
        name = name.strip()
        wert = wert.strip().strip('"').strip("'")
        if not name:
            continue
        if name not in os.environ:
            os.environ[name] = wert
            uebernommen += 1
        elif os.environ[name] != wert:
            # Der Vorrang bleibt bei der Umgebung (siehe Docstring) -- aber
            # STILL darf das nicht geschehen. Genau dieser Fall hat einmal
            # einen Nachmittag gekostet: In der Benutzerumgebung stand aus
            # einem frueheren `setx` ein alter Schluessel, jede Aenderung an
            # `.env` blieb wirkungslos, und nichts sagte warum. Waere die
            # Datei dabei auf einen Schreibschluessel umgestellt worden,
            # haette die Analyse einen ganzen Spieltag lang in den
            # Versandpuffer geschrieben, ohne dass es jemand bemerkt.
            log.warning(
                "%s steht in der Umgebung UND in %s -- mit verschiedenen "
                "Werten. Es gilt die Umgebung; die Datei bleibt wirkungslos. "
                "Entfernen mit: [Environment]::SetEnvironmentVariable('%s', "
                "$null, 'User') -- danach ein NEUES Terminal oeffnen, "
                "laufende Prozesse behalten ihre Kopie.",
                name, path.name, name)

    if uebernommen:
        log.debug("%d Eintraege aus %s uebernommen", uebernommen, path.name)
    return uebernommen


def _warne_vor_luecken(config_path: Path, raw: dict, root: Path) -> None:
    """Warnt, wenn eine eigene Konfiguration ganze Abschnitte auslaesst.

    `--config` ERSETZT `config/default.yaml`, es mischt nicht. Wer eine Datei
    mit nur einem Schluessel uebergibt, bekommt fuer alles andere die
    Schema-Vorgaben -- und die sind an vielen Stellen bewusst andere als die
    gemessenen Werte der Vorgabedatei.

    AM 2026-09-29 hat das einen halben Messtag gekostet: Eine Override-Datei
    mit der einen Zeile `sampling.baseline_from_previous_state: true` liess
    zwanzig Werte zurueckfallen -- darunter alle Lampenschwellen, die
    Bahnnummern-Zuordnung und `breakpoint_from_throw_number`, das im Schema
    auf `true` steht und in der Vorgabedatei auf `false`. Zwei gezielte
    Laeufe und ein anderthalbstuendiger Vollauf waren wertlos, und der
    scheinbare Rueckschritt eines Wurfs schickte die Fehlersuche in die
    falsche Richtung.

    Eine Warnung, kein Fehler: Ein knappes Profil kann gewollt sein.
    """
    vorgabe = root / "config" / DEFAULT_CONFIG_NAME
    if config_path == vorgabe or not vorgabe.is_file():
        return
    try:
        with vorgabe.open("r", encoding="utf-8") as fh:
            standard = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as exc:      # P8: nie den Start verhindern
        log.debug("Vorgabekonfiguration nicht vergleichbar: %s", exc)
        return
    if not isinstance(standard, dict):
        return
    fehlend = sorted(set(standard) - set(raw))
    if fehlend:
        log.warning(
            "%s laesst %d Abschnitt(e) aus, die %s setzt: %s. --config "
            "ERSETZT die Vorgabedatei, es mischt nicht -- fuer diese "
            "Abschnitte gelten jetzt die Schema-Vorgaben, nicht die "
            "gemessenen Werte.",
            config_path.name, len(fehlend), DEFAULT_CONFIG_NAME,
            ", ".join(fehlend))


def load_config(
    path: str | Path | None = None,
    overrides: dict[str, Any] | None = None,
    root: str | Path | None = None,
) -> AppConfig:
    """Laedt die Konfiguration und validiert sie.

    Args:
        path: Pfad zur YAML-Datei. None -> config/default.yaml der Projektwurzel.
        overrides: Zusaetzliche Werte, die die Datei uebersteuern (z.B. aus CLI).
        root: Projektwurzel. None -> wird gesucht. Ausdruecklich angeben muss
            sie, wer keine hat: Auf dem Telefon gibt es kein Projektverzeichnis,
            sondern nur den privaten Ordner der Anwendung -- und relativ dazu
            werden Modelldatei und Ausgaben aufgeloest.

    Raises:
        FileNotFoundError: Konfigurationsdatei fehlt.
        ValueError: Konfiguration ist inhaltlich ungueltig.
    """
    wurzel = Path(root) if root is not None else find_project_root()
    try:
        load_env_file(wurzel / ".env")
    except OSError as exc:
        # Zugangsdaten sind freiwillig; ein unlesbares Verzeichnis darf den
        # Start nicht verhindern (P8).
        log.debug("Keine .env gelesen: %s", exc)
    root = wurzel
    config_path = Path(path) if path else root / "config" / DEFAULT_CONFIG_NAME

    if not config_path.is_file():
        raise FileNotFoundError(f"Konfigurationsdatei nicht gefunden: {config_path}")

    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    if not isinstance(raw, dict):
        raise ValueError(f"Konfiguration muss ein YAML-Mapping sein: {config_path}")

    if overrides:
        raw = _deep_merge(raw, overrides)

    _warne_vor_luecken(config_path, raw, root)

    raw["project_root"] = root
    raw["config_path"] = config_path

    try:
        cfg = AppConfig.model_validate(raw)
    except Exception as exc:
        # Klarer Hinweis auf die Datei -- eine nackte Pydantic-Meldung laesst
        # offen, welche der moeglichen Konfigurationsdateien gemeint ist.
        raise ValueError(f"Ungueltige Konfiguration in {config_path}:\n{exc}") from exc

    # SICHTBAR, nicht als DEBUG. ACHTUNG: Wer `load_config` VOR dem
    # Aufsetzen des Logging aufruft -- die Oberflaeche tut das, sie braucht
    # die Konfiguration ja erst dafuer --, sieht diese Zeile NICHT. Dafuer
    # traegt `config_path` den Pfad weiter, und `main.py` meldet ihn
    # nochmals, sobald das Log steht.
    #
    # Am 2026-09-08 lief die Oberflaeche einen
    # Trainingsabend lang mit den Overlay-Schwellen, waehrend danebenher mit
    # den Kamera-Schwellen nachgemessen wurde. Beide Laeufe sahen im Protokoll
    # gleich aus -- die einzige Zeile, die den Unterschied verraten haette,
    # stand auf DEBUG und wurde nie geschrieben.
    #
    # Mitgegeben werden die beiden Werte, an denen sich die Profile
    # unterscheiden. Ein Pfad allein sagt nichts, wenn jemand die Datei
    # bearbeitet hat.
    # "aus" statt einer Zahl, wenn die Schranke abgeschaltet ist -- eine
    # Null waere an dieser Stelle irrefuehrend, denn sie ist es nicht.
    waerme = cfg.detection.lamps.warmth_min
    log.info("Konfiguration: %s | Verdeckungsschwelle %.1f | Waermeschranke %s",
             config_path, cfg.detection.green.occlusion_score,
             "aus" if waerme is None else "%.1f" % waerme)
    return cfg
