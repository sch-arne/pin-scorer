#!/usr/bin/env bash
# Haelt die Analyse an der DIREKTEN HALLENKAMERA am Laufen.
#
# Unterschied zu `dauerlauf.sh`: Dort wird nach einem Abriss an der alten
# Frame-Position wieder aufgesetzt, weil hinter der m3u8-Adresse eine
# AUFZEICHNUNG steckt. Eine Live-Kamera hat keine Vergangenheit -- ein
# `--start-frame N` wuerde hier bedeuten, N Frames in ECHTZEIT abzuwarten,
# die es noch gar nicht gibt (2026-09-08 gemessen: 6081 Frames = 6,8 Minuten
# Stillstand mitten im Training). Deshalb beginnt jeder Anlauf bei null.
#
# Doppelte Wuerfe entstehen dadurch nicht: Bei einer Live-Quelle wird nichts
# wiederholt, es geht immer nur weiter.
#
# `env -u SUPABASE_KEY` ist Absicht: In einer alten Shell steht dort noch der
# publishable Schluessel, der seit dem `revoke` nicht mehr schreiben darf.
#
#   bash tools/kamera_dauerlauf.sh <rtsp-url> <logdatei>

set -u
URL="${1:?RTSP-Adresse fehlt}"
LOG="${2:-debug/kamera_dauerlauf.log}"
KAL="data/calibrations/Training.json"


mkdir -p "$(dirname "$LOG")"
runde=0
while true; do
    runde=$((runde + 1))
    echo "=== Runde $runde, $(date '+%H:%M:%S') ===" >> "$LOG"
    env -u SUPABASE_KEY .venv/Scripts/python.exe tools/run_analysis.py \
        --source "$URL" --calibration "$KAL" --send \
        >> "$LOG" 2>&1
    echo "Lauf beendet, neuer Anlauf in 5 s" >> "$LOG"
    sleep 5
done
