#!/bin/sh
# Interleaved A/B benchmark runner for the PocketCHIP.
#
#   ab.sh <spawn> <frames> <spec> <spec> ...
#
# Each spec is `label|binary|ENV=VAL ENV=VAL`. Every spec is run once per round
# and the rounds are interleaved (A B C A B C ...), so a slow drift in the
# device - thermal or CPU-governor - hits every condition equally instead of the
# last one measured. Per-round raw logs and CSVs stay under ~/logs/p-<label>-r<n>.*
# and are meant to be folded on the development machine.
#
# Pin the CPU governor first; on this device `schedutil` swings the core between
# 432 MHz and 1.008 GHz and moves `render_ms` by 30 % on its own:
#
#   ssh chip@chip 'echo chip | sudo -S -p "" sh -c "echo performance > \
#       /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"'
SPAWN=$1; FRAMES=$2; shift 2
ROUNDS=${ROUNDS:-2}
BINS=${BINS:-1}
export GPU_SECS=${GPU_SECS:-12}

ROUND=1
while [ "$ROUND" -le "$ROUNDS" ]; do
    for spec in "$@"; do
        LABEL=$(echo "$spec" | cut -d'|' -f1)
        BIN=$(echo "$spec" | cut -d'|' -f2)
        ENVV=$(echo "$spec" | cut -d'|' -f3-)
        # shellcheck disable=SC2086
        ~/bin/probe.sh "$LABEL-r$ROUND" "$BIN" "$SPAWN" "$FRAMES" $ENVV
    done
    ROUND=$((ROUND + 1))
    [ "$ROUND" -le "$ROUNDS" ] && sleep 4
done
