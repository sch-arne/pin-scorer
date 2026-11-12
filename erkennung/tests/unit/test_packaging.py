"""Prueft, dass das Paket so nutzbar ist, wie es dokumentiert ist.

BUG-004: Der in README und CLAUDE.md dokumentierte Startbefehl scheiterte mit
ModuleNotFoundError, weil alle Tests ueber `pythonpath`/`sys.path` liefen -- der
Weg, den der Nutzer tatsaechlich geht, wurde nie beschritten.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_bug_004_paket_ist_installiert_importierbar():
    """`import kegel_cv` muss ohne sys.path-Eingriff funktionieren.

    Der Unterprozess startet in einem anderen Arbeitsverzeichnis, damit ein
    zufaellig passendes cwd das Ergebnis nicht verfaelscht.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import kegel_cv; print(kegel_cv.__version__)"],
        cwd=ROOT.parent, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        "Paket nicht importierbar -- fehlt 'pip install -e .'?\n" + result.stderr
    )
    assert result.stdout.strip()


def test_bug_004_einstiegspunkt_existiert():
    """Der dokumentierte Aufruf `python -m kegel_cv.main` braucht ein main()."""
    result = subprocess.run(
        [sys.executable, "-c",
         "from kegel_cv.main import main, parse_args; "
         "a = parse_args(['--log-level','ERROR']); print(a.log_level)"],
        cwd=ROOT.parent, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "ERROR" in result.stdout


def test_konfiguration_wird_mitgeliefert():
    assert (ROOT / "config" / "default.yaml").is_file()
