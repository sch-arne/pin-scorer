"""Automatische Pruefung der Architekturregeln.

Ein Architekturbruch ist kein Stilfehler: Wenn `detection/` die GUI importiert,
laesst sich die Erkennung nicht mehr ohne Qt testen -- und wenn `analysis/`
cv2.VideoCapture kennt, ist der spaetere Livestream ein Umbau statt einer
Konfigzeile. Deshalb wird das hier geprueft statt nur dokumentiert.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "kegel_cv"

# Erlaubte Abhaengigkeiten: Ein Paket darf nur aus den hier genannten importieren.
# Die Pfeile zeigen immer nach unten.
ALLOWED: dict[str, set[str]] = {
    "models":      set(),
    "config":      set(),
    "debug":       {"config", "models", "video"},
    "video":       {"config", "models"},
    "calibration": {"config", "models"},
    "detection":   {"config", "models", "calibration", "video"},
    "analysis":    {"config", "models", "calibration", "video", "detection", "debug"},
    "sinks":       {"config", "models"},
    "gui":         {"config", "models", "calibration", "video", "detection",
                    "analysis", "debug", "sinks"},
}

PACKAGES = sorted(ALLOWED)


def _package_of(path: Path) -> str | None:
    relative = path.relative_to(SRC)
    return relative.parts[0] if len(relative.parts) > 1 else None


def _imported_packages(path: Path) -> set[str]:
    """Sammelt die kegel_cv-Pakete, die eine Datei importiert."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    own = _package_of(path)

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            # Relative Importe: level=1 -> Geschwister im selben Paket,
            # level=2 -> Nachbarpakete unter kegel_cv
            if node.level >= 2:
                candidate = module.split(".")[0] if module else ""
            elif node.level == 1:
                candidate = ""   # gleiches Paket, immer erlaubt
            elif module.startswith("kegel_cv."):
                candidate = module.split(".")[1]
            else:
                candidate = ""
            if candidate in PACKAGES and candidate != own:
                found.add(candidate)

        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("kegel_cv."):
                    parts = alias.name.split(".")
                    if len(parts) > 1 and parts[1] in PACKAGES and parts[1] != own:
                        found.add(parts[1])

    return found


def _python_files(package: str) -> list[Path]:
    return sorted((SRC / package).rglob("*.py"))


@pytest.mark.parametrize("package", PACKAGES)
def test_abhaengigkeiten_zeigen_nach_unten(package: str):
    allowed = ALLOWED[package]
    for path in _python_files(package):
        imported = _imported_packages(path)
        forbidden = imported - allowed
        assert not forbidden, (
            f"{path.relative_to(SRC)} importiert {sorted(forbidden)}, "
            f"erlaubt sind nur {sorted(allowed) or 'keine kegel_cv-Pakete'}"
        )


@pytest.mark.parametrize("package", ["models", "config"])
def test_basisschichten_ohne_opencv(package: str):
    """models/ und config/ enthalten nur Daten und reine Funktionen.

    Sonst braeuchte jeder Test der Zaehllogik eine OpenCV-Installation.
    """
    for path in _python_files(package):
        source = path.read_text(encoding="utf-8")
        assert "import cv2" not in source, f"{path.relative_to(SRC)} importiert cv2"


def _imports_module(path: Path, prefix: str) -> bool:
    """Prueft per AST, ob eine Datei ein Modul importiert.

    Bewusst AST statt Textsuche: Der Modulname kann auch als harmloser String
    vorkommen -- etwa `logging.getLogger("PySide6")`, das gerade KEINE
    Qt-Abhaengigkeit erzeugt, sondern nur dessen Logger stummschaltet.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(prefix):
            return True
        if isinstance(node, ast.Import):
            if any(alias.name.startswith(prefix) for alias in node.names):
                return True
    return False


@pytest.mark.parametrize("package", PACKAGES)
def test_nur_die_gui_kennt_qt(package: str):
    if package == "gui":
        return
    for path in _python_files(package):
        assert not _imports_module(path, "PySide6"), (
            f"{path.relative_to(SRC)} importiert PySide6 -- Qt gehoert "
            f"ausschliesslich in die GUI-Schicht"
        )


def test_analyse_kennt_keine_videocapture():
    """Die Analyse darf nicht wissen, woher die Frames kommen.

    Sonst laesst sich spaeter kein StreamVideoSource ergaenzen, ohne die
    Analyse anzufassen (Auftrag Paragraph 3).
    """
    for package in ("detection", "analysis"):
        for path in _python_files(package):
            source = path.read_text(encoding="utf-8")
            assert "VideoCapture" not in source, (
                f"{path.relative_to(SRC)} verwendet VideoCapture direkt -- "
                f"stattdessen die VideoSource-Abstraktion nutzen"
            )


def test_keine_stillen_ausnahmen():
    """`except: pass` verschluckt Fehler und macht sie unauffindbar."""
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if all(isinstance(stmt, ast.Pass) for stmt in node.body):
                    offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, "Stille Ausnahmebehandlung gefunden: " + ", ".join(offenders)


def test_jedes_paket_hat_ein_init():
    for package in PACKAGES:
        assert (SRC / package / "__init__.py").is_file(), (
            f"Paket {package} hat keine __init__.py"
        )
