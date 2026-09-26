#!/usr/bin/env python3
"""Per-pixel comparison of two device capture sets.

Pass-3 tool. Compares PNG captures from the PocketCHIP (`tools/bench/capture_views.sh`
or `tools/bench/atlas_views.sh`) pixel by pixel and reports, per shot, how many
pixels differ by more than a tolerance, the worst channel delta, whether the
difference is spread out or concentrated in a connected region, and where the
region is.

Use it to tell a real rendering regression from a sub-texel filtering
difference: a wrong UV or a missing surface produces a large *connected* region
of large deltas, while an atlas resample shows up as many single pixels of one
or two code values scattered across prop silhouettes.

    python3 tools/bench/capture_diff.py <a-dir> <b-dir> [--tolerance 2]
"""

from __future__ import annotations

import os
import struct
import sys
import zlib


def read_png(path: str) -> tuple[int, int, int, bytes]:
    data = open(path, "rb").read()
    pos = 8
    width = height = bitdepth = colortype = None
    idat = b""
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        kind = data[pos + 4 : pos + 8]
        chunk = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, bitdepth, colortype = struct.unpack(">IIBB", chunk[:10])
        elif kind == b"IDAT":
            idat += chunk
        pos += 12 + length
    raw = zlib.decompress(idat)
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[colortype]
    bpp = channels * bitdepth // 8
    stride = width * bpp
    out = bytearray()
    previous = bytearray(stride)
    i = 0
    for _ in range(height):
        filter_type = raw[i]
        i += 1
        line = bytearray(raw[i : i + stride])
        i += stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = previous[x]
            c = previous[x - bpp] if x >= bpp else 0
            if filter_type == 1:
                line[x] = (line[x] + a) & 255
            elif filter_type == 2:
                line[x] = (line[x] + b) & 255
            elif filter_type == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif filter_type == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + predictor) & 255
        out += line
        previous = line
    return width, height, bpp, bytes(out)


def largest_component(mask: list[bool], width: int, height: int) -> int:
    """Largest 4-connected component size of a boolean mask (iterative)."""
    seen = bytearray(len(mask))
    best = 0
    for start in range(len(mask)):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = 1
        size = 0
        while stack:
            node = stack.pop()
            size += 1
            x = node % width
            y = node // width
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    n = ny * width + nx
                    if mask[n] and not seen[n]:
                        seen[n] = 1
                        stack.append(n)
        best = max(best, size)
    return best


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    tolerance = 2
    if "--tolerance" in sys.argv:
        tolerance = int(sys.argv[sys.argv.index("--tolerance") + 1])
    dir_a, dir_b = args[0], args[1]
    only_a = sorted(
        f for f in os.listdir(dir_a) if f.endswith(".png") and not os.path.exists(os.path.join(dir_b, f))
    )
    only_b = sorted(
        f for f in os.listdir(dir_b) if f.endswith(".png") and not os.path.exists(os.path.join(dir_a, f))
    )
    if only_a:
        print("missing from B:", ", ".join(only_a))
    if only_b:
        print("missing from A:", ", ".join(only_b))

    worst_shot = ("", 0.0)
    total_bad = 0
    print("%-24s %8s %8s %9s %10s %s" % ("shot", "diff%", "worst", "compsize", "pixels", "bbox"))
    print("-" * 88)
    for name in sorted(f for f in os.listdir(dir_a) if f.endswith(".png")):
        path_b = os.path.join(dir_b, name)
        if not os.path.exists(path_b):
            continue
        wa, ha, bpp_a, a = read_png(os.path.join(dir_a, name))
        wb, hb, bpp_b, b = read_png(path_b)
        if (wa, ha, bpp_a) != (wb, hb, bpp_b):
            print("%-24s size mismatch %s vs %s" % (name, (wa, ha), (wb, hb)))
            continue
        mask: list[bool] = []
        worst = 0
        xs: list[int] = []
        ys: list[int] = []
        for y in range(ha):
            for x in range(wa):
                i = (y * wa + x) * bpp_a
                delta = max(abs(a[i + k] - b[i + k]) for k in range(3))
                bad = delta > tolerance
                mask.append(bad)
                if bad:
                    worst = max(worst, delta)
                    xs.append(x)
                    ys.append(y)
        bad_count = sum(mask)
        total_bad += bad_count
        component = largest_component(mask, wa, ha) if bad_count else 0
        fraction = 100.0 * bad_count / (wa * ha)
        bbox = f"x[{min(xs)}..{max(xs)}] y[{min(ys)}..{max(ys)}]" if xs else "-"
        print(
            "%-24s %7.3f%% %8d %9d %10d %s"
            % (name, fraction, worst, component, bad_count, bbox)
        )
        if fraction > worst_shot[1]:
            worst_shot = (name, fraction)
    print("-" * 88)
    print(f"worst shot by area: {worst_shot[0]} ({worst_shot[1]:.3f}%)   total differing pixels: {total_bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
