#!/usr/bin/env python3
"""Run one presented configuration on the device and report its cadence shape.

    python3 tools/bench/present_probe.py <label> [ENV=VAL ...]

Runs the game with the benchmark harness, pulls the per-frame CSV and prints the
distribution of `loop_ms` in 2 ms bins, the fraction of frames in the fast and
slow modes and the cumulative-phase concentration against the 59.52 Hz refresh
(0 = presentation is not vblank-locked, 1 = perfectly locked).

Built for Pass 3 to characterise what the X11/modesetting present path actually
does, rather than trusting `SDL_GL_SetSwapInterval`'s return value.
"""

from __future__ import annotations

import csv
import io
import math
import statistics
import subprocess
import sys
import collections

REFRESH_MS = 1000.0 / 59.52
HOST = "pocketchip"
BINARY = "./places-probe1"
SPAWN = "2,5.6,74"
FRAMES = "900"


def main() -> int:
    label = sys.argv[1]
    overrides = sys.argv[2:]
    assign = " ".join(overrides)
    remote = f"""
set -e
cd ~/places-dev
rm -f ~/logs/pp-{label}.csv ~/logs/pp-{label}.log
export DISPLAY=:0 LIMINAL_LEVEL=places_demo LIMINAL_VERBOSE=1
export LIMINAL_BENCH=1 LIMINAL_BENCH_FRAMES={FRAMES} LIMINAL_BENCH_WARMUP=40
export LIMINAL_SPAWN={SPAWN} LIMINAL_QUALITY=low LIMINAL_NO_LIGHTMAPS=0
export LIMINAL_VSYNC=off LIMINAL_STATE_ROOT=/home/chip/p2-state/linear
export LIMINAL_BENCH_OUT=/home/chip/logs/pp-{label}.csv
{assign} {BINARY} > ~/logs/pp-{label}.log 2>&1
grep -m1 BENCH_SUMMARY ~/logs/pp-{label}.log
"""
    summary_line = subprocess.run(
        ["ssh", HOST, remote], capture_output=True, text=True, check=True
    ).stdout.strip()
    data = subprocess.run(
        ["ssh", HOST, f"cat ~/logs/pp-{label}.csv"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = [
        {k: float(v) for k, v in row.items() if v}
        for row in csv.DictReader(io.StringIO(data))
    ]
    seq = [r["loop_ms"] for r in rows]
    if not seq:
        print(f"{label}: no frames")
        return 1
    median = statistics.median(seq)
    fast = [v for v in seq if v < 36]
    slow = [v for v in seq if v >= 36]
    histogram = collections.Counter(int(v // 2) * 2 for v in seq)
    cumulative = 0.0
    phases = []
    for value in seq:
        cumulative += value
        phases.append(cumulative % REFRESH_MS)
    angles = [p / REFRESH_MS * 2 * math.pi for p in phases]
    cx = sum(math.cos(a) for a in angles) / len(angles)
    cy = sum(math.sin(a) for a in angles) / len(angles)
    print(f"== {label}  n={len(seq)}  median={median:.2f}  mean={statistics.mean(seq):.2f}")
    print("   summary: " + summary_line)
    print("   bins(2ms): " + " ".join(f"{b}:{c}" for b, c in sorted(histogram.items()) if c >= len(seq) * 0.01))
    print(
        "   render med=%.1f  swap med=%.1f  update med=%.1f"
        % (
            statistics.median([r["render_ms"] for r in rows]),
            statistics.median([r["swap_ms"] for r in rows]),
            statistics.median([r["update_ms"] for r in rows]),
        )
    )
    print(
        "   fast(<36) n=%d med=%.1f | slow(>=36) n=%d med=%.1f | vblank_lock R=%.3f"
        % (
            len(fast), statistics.median(fast) if fast else float("nan"),
            len(slow), statistics.median(slow) if slow else float("nan"),
            math.hypot(cx, cy),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
