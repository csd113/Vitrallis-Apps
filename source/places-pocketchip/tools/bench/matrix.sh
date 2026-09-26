#!/bin/sh
# Run a series of configurations at one fixed viewpoint and print one line each.
#   matrix.sh <spawn> <frames> <label>:<env...> [<label>:<env...> ...]
SPAWN=$1; FRAMES=$2; shift 2
for spec in "$@"; do
    LABEL=$(echo "$spec" | cut -d: -f1)
    ENVV=$(echo "$spec" | cut -d: -f2-)
    env $ENVV "$HOME/bin/measure.sh" "$LABEL" "$SPAWN" "$FRAMES"
    # Let the device settle between runs.
    sleep 3
done
