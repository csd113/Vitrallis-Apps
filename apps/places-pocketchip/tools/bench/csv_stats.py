#!/usr/bin/env python3
"""Per-frame CSV analysis for the PocketCHIP benchmark runs.

Reads `p-<label>-r<n>.csv` files (written by the game's own bench harness,
`LIMINAL_BENCH_OUT`) and reports robust statistics per label: the median and
trimmed mean of `loop_ms` (begin-of-frame to begin-of-frame, the real cadence),
of `render_ms + swap_ms` (the frame's non-simulation work) and of the GPU-only
and CPU-only shares.

`render_ms` and `swap_ms` swap work between them run to run because a full
command queue blocks inside whichever call the CPU is in, so the pass-3 report
leans on their sum and on `loop_ms`.

    python3 tools/bench/csv_stats.py /tmp/p3/csv 'pass2|probe-normal|onetex|onedraw'
"""

from __future__ import annotations

import csv
import glob
import os
import re
import statistics
import sys


def trimmed(values: list[float], fraction: float = 0.05) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    cut = int(len(ordered) * fraction)
    kept = ordered[cut : len(ordered) - cut] if cut else ordered
    return statistics.mean(kept) if kept else float("nan")


def summarise(rows: list[dict[str, float]]) -> dict[str, float]:
    loop = [r["loop_ms"] for r in rows]
    work = [r["render_ms"] + r["swap_ms"] for r in rows]
    render = [r["render_ms"] for r in rows]
    swap = [r["swap_ms"] for r in rows]
    update = [r["update_ms"] for r in rows]
    ordered = sorted(loop)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    p99 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))]
    return {
        "n": len(loop),
        "loop_med": statistics.median(loop),
        "loop_trim": trimmed(loop),
        "loop_p95": p95,
        "loop_p99": p99,
        "loop_min": ordered[0],
        "work_med": statistics.median(work),
        "work_trim": trimmed(work),
        "render_med": statistics.median(render),
        "swap_med": statistics.median(swap),
        "update_med": statistics.median(update),
        "fps_from_loop_med": 1000.0 / statistics.median(loop),
        "fps_trim": 1000.0 / trimmed(loop),
    }


def main() -> int:
    root = sys.argv[1]
    wanted = sys.argv[2].split("|") if len(sys.argv) > 2 else None

    groups: dict[str, list[dict[str, float]]] = {}
    for path in sorted(glob.glob(os.path.join(root, "p-*.csv"))):
        match = re.search(r"p-(.*)-r(\d+)\.csv$", path)
        if not match:
            continue
        label = match.group(1)
        if wanted and label not in wanted:
            continue
        with open(path, newline="") as handle:
            rows = [
                {k: float(v) for k, v in row.items() if v not in ("", None)}
                for row in csv.DictReader(handle)
            ]
        groups.setdefault(label, []).extend(rows)

    header = ("%-16s %5s %8s %8s %8s %8s %8s %8s %8s %8s %7s" % (
        "label", "n", "fps_med", "fps_trim", "loop_med", "loop_trim",
        "loop_p95", "work_med", "render", "swap", "update"))
    print(header)
    print("-" * len(header))
    for label in sorted(groups):
        s = summarise(groups[label])
        print("%-16s %5d %8.2f %8.2f %8.2f %8.2f %8.2f %8.2f %8.2f %8.2f %7.2f" % (
            label, s["n"], s["fps_from_loop_med"], s["fps_trim"], s["loop_med"],
            s["loop_trim"], s["loop_p95"], s["work_med"], s["render_med"],
            s["swap_med"], s["update_med"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
