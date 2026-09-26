#!/bin/sh
# Run one Places configuration and report frame timing, memory and GPU load.
#
#   measure.sh <label> <spawn> <frames>
#
# Waits for the level build to finish (the `[level]` telemetry line) before it
# starts sampling, so RSS and FPS describe the running scene and not the load.
LABEL=$1; SPAWN=$2; FRAMES=$3
LOGS=$HOME/logs

export DISPLAY=:0
export LIMINAL_LEVEL=places_demo
export LIMINAL_VERBOSE=1
export LIMINAL_BENCH=1
export LIMINAL_BENCH_FRAMES=$FRAMES
export LIMINAL_BENCH_WARMUP=20
export LIMINAL_SPAWN=$SPAWN
export LIMINAL_QUALITY=${LIMINAL_QUALITY:-low}
# The variable names the stage to switch off: 0 keeps the shipping lightmapped
# build, 1 forces the vertex-lit path. Never default to 1 here — the script's
# purpose is to measure the shipping configuration.
export LIMINAL_NO_LIGHTMAPS=${LIMINAL_NO_LIGHTMAPS:-0}
export LIMINAL_NO_REFLECTIONS=${LIMINAL_NO_REFLECTIONS:-1}
export LIMINAL_NO_BLOOM=${LIMINAL_NO_BLOOM:-1}
# VSync is off for raw frame time by default; `LIMINAL_VSYNC=on` measures the
# shipping presentation instead.
export LIMINAL_VSYNC=${LIMINAL_VSYNC:-off}
export LIMINAL_BENCH_OUT=$LOGS/m-$LABEL.csv

FAULTS_BEFORE=$(echo chip | sudo -S -p "" dmesg 2>/dev/null | grep -cE "gpmmu|timedout")
if [ "$FAULTS_BEFORE" != "0" ]; then
    echo "$LABEL | SKIPPED: GPU already faulted"
    exit 0
fi

cd "$HOME/places-dev" || exit 1
LOG=$LOGS/m-$LABEL.log
timeout 300 ./places > "$LOG" 2>&1 &
PID=$!

# Wait for the level build to complete (bounded), then sample.
WAITED=0
while [ $WAITED -lt 120 ]; do
    grep -q "^\[level\]" "$LOG" 2>/dev/null && break
    kill -0 $PID 2>/dev/null || break
    sleep 2
    WAITED=$((WAITED + 2))
done

RSS_BEFORE=$(awk '/VmRSS/{print $2}' /proc/$PID/status 2>/dev/null)
"$HOME/bin/gpuwatch.sh" 25 > "$LOGS/m-$LABEL.gpu" 2>&1 &
GPU_PID=$!
wait $PID 2>/dev/null
wait $GPU_PID 2>/dev/null
RSS_PEAK=$(grep VmHWM "$LOG" 2>/dev/null)

LOAD_MS=$(grep -m1 "^\[level\]" "$LOG" | grep -oE "built in [0-9.]+ ms" | grep -oE "[0-9.]+")
SUM=$(grep -m1 "BENCH_SUMMARY" "$LOG")
FAULTS_AFTER=$(echo chip | sudo -S -p "" dmesg 2>/dev/null | grep -cE "gpmmu|timedout")

if [ -z "$SUM" ]; then
    echo "$LABEL | FAILED faults=$FAULTS_AFTER | $(tail -1 "$LOG" | cut -c1-110)"
    exit 0
fi

LABEL="$LABEL" SUMMARY=$(echo "$SUM" | sed "s/BENCH_SUMMARY //") FAULTS="$FAULTS_AFTER" LOAD_MS="$LOAD_MS" RSS="$RSS_PEAK" python3 -c '
import json,os
d=json.loads(os.environ["SUMMARY"])
g={}
try:
    for line in open(os.path.expanduser("~/logs/m-")+os.environ["LABEL"]+".gpu"):
        if "=" in line:
            k,v=line.strip().split("=",1); g[k]=v
except Exception: pass
print("%-20s fps=%6.2f 1%%=%5.2f f_med=%6.1f f_p95=%6.1f f_max=%7.1f | render=%5.1f upd=%4.1f swap=%6.1f | draws=%4d verts=%6d mats=%3d tb=%3d | gpu_mean=%6s med=%4s p95=%4s | load=%sms faults=%s" % (
 os.environ["LABEL"], d["fps_median"], d["fps_1pct_low"], d["frame_median_ms"], d["frame_p95_ms"], d["frame_max_ms"],
 d["render_mean_ms"], d["update_mean_ms"], d["swap_mean_ms"], d["draw_calls"], d["total_vertices"],
 d["material_changes"], d["texture_binds"], g.get("gpu_load_mean","-"), g.get("gpu_load_median","-"),
 g.get("gpu_load_p95","-"), os.environ.get("LOAD_MS","-"), os.environ["FAULTS"]))
'
