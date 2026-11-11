#!/usr/bin/env bash
# Wertet die Mitschnitte eines Abends aus -- OHNE Versand.
#
# Kein `--send`: Diese Laeufe dienen der Pruefung, nicht der Erfassung. Die
# Wuerfe stehen bereits in der Datenbank; sie ein zweites Mal zu schicken
# erzeugte Dubletten (2026-09-07 passiert, 478 ueberzaehlige Zeilen).
set -u
KAL="${1:-data/calibrations/Training.json}"
LOG="${2:-debug/pruefung_mitschnitte.log}"
mkdir -p "$(dirname "$LOG")"
: > "$LOG"
for f in debug/training_2026-09-08/*.mp4; do
    echo "=== $f  $(date '+%H:%M:%S') ===" >> "$LOG"
    .venv/Scripts/python.exe tools/run_analysis.py \
        --source "$f" --calibration "$KAL" >> "$LOG" 2>&1
done
echo "=== fertig $(date '+%H:%M:%S') ===" >> "$LOG"
