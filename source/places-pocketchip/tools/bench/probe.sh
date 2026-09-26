#!/bin/sh
# Run one named build/configuration on the PocketCHIP and print a one-line result.
#
#   probe.sh <label> <binary> <spawn> <frames> [extra env assignments...]
#
# Born in Pass 3 to A/B two binaries that differ by one renderer decision.
# The shared environment is the shipping configuration: Low profile, lightmaps
# on, VSync off for raw frame time, the warm benchmark state root.
#
# Prints the same fields as measure.sh plus the per-run GPU load summary, the
# level-build time, the peak RSS the run reported and the new GPU fault count.
LABEL=$1; BIN=$2; SPAWN=$3; FRAMES=$4
shift 4
LOGS=$HOME/logs

export DISPLAY=:0
export LIMINAL_LEVEL=places_demo
export LIMINAL_VERBOSE=1
export LIMINAL_BENCH=1
export LIMINAL_BENCH_FRAMES=$FRAMES
export LIMINAL_BENCH_WARMUP=20
export LIMINAL_SPAWN=$SPAWN
export LIMINAL_QUALITY=${LIMINAL_QUALITY:-low}
export LIMINAL_NO_LIGHTMAPS=${LIMINAL_NO_LIGHTMAPS:-0}
export LIMINAL_VSYNC=${LIMINAL_VSYNC:-off}
export LIMINAL_STATE_ROOT=${LIMINAL_STATE_ROOT:-/home/chip/p2-state/linear}
export LIMINAL_BENCH_OUT=$LOGS/p-$LABEL.csv

for assign in "$@"; do
    export "$assign"
done

FAULTS_BEFORE=$(echo chip | sudo -S -p "" dmesg 2>/dev/null | grep -cE "gpmmu|ppmmu|timedout")
if [ "$FAULTS_BEFORE" != "0" ]; then
    echo "$LABEL | SKIPPED: GPU already faulted ($FAULTS_BEFORE messages)"
    exit 0
fi

cd "$HOME/places-dev" || exit 1
LOG=$LOGS/p-$LABEL.log
timeout 300 "$BIN" > "$LOG" 2>&1 &
PID=$!

WAITED=0
while [ $WAITED -lt 120 ]; do
    grep -q "^\[level\]" "$LOG" 2>/dev/null && break
    kill -0 $PID 2>/dev/null || break
    sleep 2
    WAITED=$((WAITED + 2))
done

"$HOME/bin/gpuwatch.sh" "${GPU_SECS:-12}" > "$LOGS/p-$LABEL.gpu" 2>&1 &
GPU_PID=$!
wait $PID 2>/dev/null
wait $GPU_PID 2>/dev/null
RSS_PEAK=$(awk '/VmHWM/{print $2}' /proc/$PID/status 2>/dev/null)
[ -z "$RSS_PEAK" ] && RSS_PEAK=$(grep -oE "VmHWM: +[0-9]+" "$LOG" 2>/dev/null | grep -oE "[0-9]+")

LOAD_MS=$(grep -m1 "^\[level\]" "$LOG" | grep -oE "built in [0-9.]+ ms" | grep -oE "[0-9.]+")
SUM=$(grep -m1 "BENCH_SUMMARY" "$LOG")
FAULTS_AFTER=$(echo chip | sudo -S -p "" dmesg 2>/dev/null | grep -cE "gpmmu|ppmmu|timedout")
NEW_FAULTS=$((FAULTS_AFTER - FAULTS_BEFORE))

if [ -z "$SUM" ]; then
    echo "$LABEL | FAILED faults=$NEW_FAULTS | $(tail -1 "$LOG" | cut -c1-110)"
    exit 0
fi

LABEL="$LABEL" SUMMARY=$(echo "$SUM" | sed "s/BENCH_SUMMARY //") FAULTS="$NEW_FAULTS" \
    LOAD_MS="$LOAD_MS" RSS="$RSS_PEAK" python3 -c '
import json,os
d=json.loads(os.environ["SUMMARY"])
g={}
try:
    for line in open(os.path.expanduser("~/logs/p-")+os.environ["LABEL"]+".gpu"):
        if "=" in line:
            k,v=line.strip().split("=",1); g[k]=v
except Exception: pass
print("%-18s fps=%6.2f 1%%=%5.2f med=%6.2f p95=%6.2f max=%7.2f | render=%5.2f upd=%5.2f swap=%6.2f | draws=%3d tb=%3d mats=%3d verts=%6d | gpu mean=%5s med=%4s p95=%4s | load=%sms rss=%s faults=%s" % (
 os.environ["LABEL"], d["fps_median"], d["fps_1pct_low"], d["frame_median_ms"], d["frame_p95_ms"], d["frame_max_ms"],
 d["render_mean_ms"], d["update_mean_ms"], d["swap_mean_ms"], d["draw_calls"], d["texture_binds"],
 d["material_changes"], d["visible_vertices"],
 g.get("gpu_load_mean","-"), g.get("gpu_load_median","-"), g.get("gpu_load_p95","-"),
 os.environ.get("LOAD_MS","-"), os.environ.get("RSS","-"), os.environ["FAULTS"]))
'
