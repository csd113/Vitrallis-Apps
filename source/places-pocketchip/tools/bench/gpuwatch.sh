#!/bin/sh
# PocketCHIP GPU activity sampler.
#
# Source: the kernel devfreq tracepoint `devfreq_monitor` on the Lima GPU
# device `1c40000.gpu`, read from the dedicated tracefs instance
# `/sys/kernel/tracing/instances/vitrallis-gpu` through the pre-mounted
# `/run/vitrallis-gpu/trace_pipe`. The governor polls the GPU device's busy
# time every `polling_ms` and the tracepoint prints
#
#     load = 100 * busy_time / total_time
#
# which is a true busy fraction of the polling window, not a frequency.
#
# Usage: gpuwatch.sh [seconds] [output.csv]
# Prints: samples, mean/median/p95/max load %, and the distinct frequencies.

SECS=${1:-30}
OUT=${2:-}
PIPE=/run/vitrallis-gpu/trace_pipe

if [ ! -r "$PIPE" ]; then
    echo "gpuwatch: cannot read $PIPE" >&2
    exit 1
fi

END=$(( $(date +%s) + SECS ))
if [ -n "$OUT" ]; then : > "$OUT"; fi

# timeout kills the reader; the trace_pipe never reaches EOF.
timeout "$SECS" cat "$PIPE" 2>/dev/null | awk -v out="$OUT" '
/ devfreq_monitor:/ {
    n++
    for (i = 1; i <= NF; i++) {
        if ($i ~ /^load=/) { split($i, a, "="); load = a[2] + 0; nload++ }
        if ($i ~ /^freq=/) { split($i, a, "="); freq = a[2] + 0; freqs[freq] = 1 }
    }
    v[nload] = load
    if (load > max) max = load
    sum += load
    if (out != "") print systime(), load, freq > out
}
END {
    if (nload == 0) { print "gpuwatch: no devfreq_monitor samples"; exit }
    # insertion sort: samples are few hundred to a few thousand
    for (i = 2; i <= nload; i++) { key = v[i]; j = i - 1; while (j >= 0 && v[j] > key) { v[j+1] = v[j]; j-- } v[j+1] = key }
    med = v[int((nload + 1) / 2)]
    p95 = v[int(nload * 0.95) < 1 ? 1 : int(nload * 0.95)]
    printf "gpu_samples=%d\n", nload
    printf "gpu_load_mean=%.1f\n", sum / nload
    printf "gpu_load_median=%d\n", med
    printf "gpu_load_p95=%d\n", p95
    printf "gpu_load_max=%d\n", max
    printf "gpu_freqs="
    for (f in freqs) printf "%s ", f
    printf "\n"
}
'
