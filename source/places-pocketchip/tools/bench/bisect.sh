#!/bin/sh
# Run configurations in sequence and report the GPU fault delta each one causes.
#
#   bisect.sh <spawn> <frames> <label>:<env...> [...]
SPAWN=$1; FRAMES=$2; shift 2
FAULTS=$(echo chip | sudo -S -p "" dmesg 2>/dev/null | grep -cE "gpmmu|timedout")
echo "start faults=$FAULTS"
for spec in "$@"; do
    LABEL=$(echo "$spec" | cut -d: -f1)
    ENVV=$(echo "$spec" | cut -d: -f2-)
    BEFORE=$(echo chip | sudo -S -p "" dmesg 2>/dev/null | grep -cE "gpmmu|timedout")
    RESULT=$(env $ENVV "$HOME/bin/measure.sh" "$LABEL" "$SPAWN" "$FRAMES" 2>&1 | tail -1)
    AFTER=$(echo chip | sudo -S -p "" dmesg 2>/dev/null | grep -cE "gpmmu|timedout")
    echo "$RESULT  newfaults=$((AFTER - BEFORE))"
done
