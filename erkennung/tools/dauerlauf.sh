#!/usr/bin/env bash
# Haelt die Analyse am Laufen -- und setzt nach einem Abriss dort wieder an,
# wo sie stehengeblieben ist.
#
# WARUM: Ein Stream reisst ab. Ohne diesen Waechter steht die Anzeige dann
# still, und wer die Seite aufruft, sieht nichts. Wichtiger noch: Ein Neustart
# bei Frame 0 wuerde alle bereits gesendeten Wuerfe ein zweites Mal in die
# Tabelle schreiben -- deshalb wird die Position aus dem Protokoll gelesen.
#
# `env -u SUPABASE_KEY` ist Absicht: In einer alten Shell steht dort noch der
# publishable Schluessel, der seit dem `revoke` nicht mehr schreiben darf.
#
#   bash tools/dauerlauf.sh <startframe> <logdatei>

set -u
START_FRAME="${1:-0}"
LOG="${2:-debug/dauerlauf.log}"
KAL="data/calibrations/1Spieltag_sollgroesse.json"
URL="$(cat /tmp/stream_url.txt)"

mkdir -p "$(dirname "$LOG")"
frame="$START_FRAME"
runde=0

while true; do
    runde=$((runde + 1))
    echo "=== Runde $runde, ab Frame $frame, $(date '+%H:%M:%S') ===" >> "$LOG"

    env -u SUPABASE_KEY .venv/Scripts/python.exe tools/run_analysis.py \
        --source "$URL" --calibration "$KAL" \
        --start-frame "$frame" --fps 25 --send >> "$LOG" 2>&1

    # Wo sind wir stehengeblieben? Ohne diesen Schritt begaenne der naechste
    # Anlauf von vorn und schickte alles doppelt.
    letzter="$(grep -o 'bei Frame [0-9]*' "$LOG" | tail -1 | grep -o '[0-9]*')"
    if [ -n "$letzter" ] && [ "$letzter" -gt "$frame" ]; then
        frame=$((letzter + 1))
    else
        # Kein Fortschritt -- die Quelle ist wohl am Ende oder nicht erreichbar.
        echo "kein Fortschritt bei Frame $frame, warte 30 s" >> "$LOG"
        sleep 30
    fi
done
