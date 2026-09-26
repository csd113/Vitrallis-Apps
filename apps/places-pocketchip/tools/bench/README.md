# Benchmark and capture suite

Everything here drives the release binary on this development machine (no
device, no SSH) and writes its artifacts below `target/agent-work/`. Those
artifacts are generated locally and **never committed**: `target/` and the
result directories are ignored, so re-running a suite is the way to reproduce
a number, not a file in the repository.

The current workflow is four tools plus two capture scripts:

| tool | what it does |
| --- | --- |
| `bench_local.py` | repeats one benchmark configuration and prints min/median/max per field |
| `capture_views.sh` | renders the fixed validation view set, one PNG per view |
| `capture_baseline_views.sh` | renders the canonical pre-wgpu baseline view set in the High and Low profiles |
| `visual_check.py` | decodes two capture sets and reports per-shot pixel differences |
| `lightmap_report.py` | runs the bake/lighting shot list and writes a `report.json` |
| `check_holes.py` | counts near-black pixels in captures, to catch holes in a level shell |

## Local benchmark

`bench_local.py` runs the release binary directly and repeats one configuration
`--repeat` times. It prints the minimum, median and maximum of every headline
field (the minimum is the number least contaminated by unrelated system work)
and writes the same numbers to `target/agent-work/bench/<label>.json`.

```sh
# the Full profile, five repeats
python3 tools/bench/bench_local.py --label current_full --repeat 5

# the Low profile on the same build
python3 tools/bench/bench_local.py --label current_low --repeat 5 --quality low

# a baseline checkout, for a before/after pair
python3 tools/bench/bench_local.py --label baseline --repeat 5 \
    --binary target/agent-work/baseline/target/release/liminal-rust
```

Flags:

| flag | effect |
| --- | --- |
| `--label NAME` | output name; the JSON lands at `target/agent-work/bench/NAME.json` |
| `--repeat N` | how many whole runs to take the min/median/max over (default 3) |
| `--quality full\|low` | draw this run at the named profile without editing `settings.json` |
| `--no-lightmaps` | `LIMINAL_NO_LIGHTMAPS=1`: force the vertex-lit path |
| `--binary PATH` | measure another executable (default `target/release/liminal-rust`) |
| `--level ID`, `--camera yaw[,pitch]` | the fixed scene (default `places_demo`, `74,0`) |
| `--frames N`, `--warmup N` | recorded frames and discarded warm-up frames (default 120 / 20) |
| `--finish` | insert `glFinish` before the swap, splitting renderer from presentation time |
| `--noswap` | skip `SDL_GL_SwapWindow`, so a run cannot block on a display that has gone to sleep |
| `--timeout S` | seconds before one run is treated as hung (default 300) |

Every run holds the level, assets, camera, frame count and swap interval fixed,
so only the flag you changed differs between two labels.

## Capture views

`capture_views.sh` renders the fixed validation view set: the surface-response
and post-processing shots (windows, panels, deck, sign, linoleum, pause menu)
plus a walkthrough of the demo's route from reception to the unmade world. Each
view nails its spawn and camera, so the same command produces the same image on
any machine and the before/after and Full/Low sets are directly comparable.

```sh
sh tools/bench/capture_views.sh                            # Full profile
LIMINAL_QUALITY=low sh tools/bench/capture_views.sh        # profile suffix _low
```

Files are written as `view_<name><suffix>.png` to
`target/agent-work/captures/` by default. `LIMINAL_CAPTURE_DIR` overrides the
output directory, and `LIMINAL_BIN` points the same view table at another build,
which is how a before/after pair is captured without overwriting the reference:

```sh
LIMINAL_BIN=target/agent-work/baseline/target/release/liminal-rust \
    LIMINAL_CAPTURE_DIR=target/agent-work/captures_baseline \
    sh tools/bench/capture_views.sh
```

The suffix accumulates in the order low / direct / nobloom / norefl, so a
comparison run never overwrites the reference capture.

## Canonical renderer baseline

`capture_baseline_views.sh` renders the smaller, curated view set that is the
permanent pre-wgpu reference for the renderer migration, in both quality
profiles at once. It owns its view table, a pinned `settings.json` under
`target/renderer-baseline-state/` (a 640x360 logical window, which is a
1280x720 drawable on a 2x display) and writes `<name>.png` plus `manifest.txt`
per profile:

```sh
sh tools/bench/capture_baseline_views.sh                        # -> docs/renderer-baseline/{high,low}
LIMINAL_QUALITY=low sh tools/bench/capture_baseline_views.sh    # one profile only
LIMINAL_BIN=target/release/places-wgpu \
    LIMINAL_CAPTURE_DIR=target/agent-work/wgpu-baseline \
    sh tools/bench/capture_baseline_views.sh                    # a future renderer
```

The committed reference and its camera/settings manifest are documented in
`docs/renderer-baseline/BASELINE.md`; that document is the authority on what
each view exercises. `LIMINAL_QUALITY=full` and `LIMINAL_QUALITY=low` select one
profile, and any other value is rejected. Delete the state root before a run to
force a cold lightmap bake rather than reusing its cache.

## Visual regression

`visual_check.py` drives the one-frame capture path from two builds over a fixed
shot list, decodes both sets of PNGs and reports the number of differing pixels,
the fraction of the image and the worst channel delta per shot. It fails on the
largest *connected* group of significant pixels exceeding `--max-component`
(default 256), which separates a one-row float-rounding sliver from dropped or
extra geometry.

```sh
python3 tools/bench/visual_check.py \
    --baseline "$PWD/target/agent-work/baseline/liminal-rust" \
    --current  "$PWD/target/release/liminal-rust"
```

Pass **absolute** binary paths: each capture runs with the staged package as its
working directory, so a repository-relative path does not resolve. `--out`
selects where the captures and the staged package root live; the run
symlinks the shipped `assets/` and the `tests/fixtures/levels/` fixtures into it
and points `LIMINAL_ASSET_ROOT` there, so the demo and the regression fixtures
resolve without copying anything into the repository's own `levels/`.
`--tolerance`, `--max-component` and `--strict` adjust the gate.

## Lightmap bake and lighting A/B

`lightmap_report.py` runs the one-frame capture path plus `LIMINAL_BENCH`
telemetry over the bake/lighting shot list, parses the
`[level]`/`[lighting]`/`[lightmaps]`/`[spatial]` developer lines and writes
`report.json` beside the PNGs and per-frame CSVs.

The parsed `[level]`/`[lighting]`/`[lightmaps]`/`[spatial]` lines are only
emitted by a verbose run, so pass `--env LIMINAL_VERBOSE=1` to populate the
report's metric fields; without it the report still captures every shot but its
numbers are empty.

```sh
# cold bake + captures for the standard shot list
python3 tools/bench/lightmap_report.py --label full --cold --env LIMINAL_VERBOSE=1

# the exact vertex-lit control run (same build, lightmaps forced off)
LIMINAL_NO_LIGHTMAPS=1 python3 tools/bench/lightmap_report.py --label vertex

# a specific profile, run from a package directory holding its settings.json
python3 tools/bench/lightmap_report.py --label low \
    --run-dir $PWD/target/agent-work/benchmarks/run-low
```

Fixtures under `tests/fixtures/levels/` are staged into a package directory under
`target/agent-work/` (via `LIMINAL_ASSET_ROOT`), never copied into the
repository's own `levels/`. `--cold` deletes that run directory's
`cache/lightmaps/` (the runtime lightmap cache below the state root) first, so
the next run bakes for real. `tools/bench/notes/lightmap-bake-validation.md`
holds the measurements taken with it.

## Checking captures for holes

`check_holes.py` counts near-black pixels in captured PNGs. A shelled room never
renders the clear colour, so a capture from inside it must have almost no fully
black pixels; a block of them is a missing wall, floor or ceiling.

```sh
python3 tools/bench/check_holes.py target/agent-work/captures/view_*.png
python3 tools/bench/check_holes.py --threshold 8 --step 2 target/agent-work/captures/
```

It exits non-zero when any capture exceeds `--max-fraction` (default 0.05), so
it can gate a capture matrix.

## Telemetry the game emits

All of it is gated behind `LIMINAL_BENCH=1`; a normal release run prints none of
it and allocates nothing per frame.

| Variable | Meaning |
|---|---|
| `LIMINAL_BENCH=1` | enables the harness (required for all of the below) |
| `LIMINAL_BENCH_OUT=file.csv` | per-frame rows: `frame,update_ms,render_ms,swap_ms,frame_ms,loop_ms,total_vertices,visible_vertices,culled_vertices,total_batches,visible_batches,draw_calls,vbo_bytes,index_bytes,texture_binds,material_changes,reflection_passes` |
| `LIMINAL_BENCH_WARMUP=n` | discard the first `n` frames |
| `LIMINAL_BENCH_FRAMES=n` | stop after `n` recorded frames and print the summary |
| `LIMINAL_CAMERA=yaw[,pitch]` | pin the camera for a repeatable shot |
| `LIMINAL_VSYNC=on\|off` | override the swap interval for VSync characterisation |
| `LIMINAL_BENCH_FINISH=1` | `glFinish` before the swap (splits renderer from presentation time) |
| `LIMINAL_BENCH_NORENDER=1` | skip scene/UI submission (presentation-only run) |
| `LIMINAL_BENCH_NOSWAP=1` | skip `SDL_GL_SwapWindow` (renderer-only run) |
| `LIMINAL_BENCH_NOCULL=1` | submit every batch (isolates what culling is worth) |
| `LIMINAL_BENCH_NOINDEX=1` | submit flat triangle lists (isolates what indexing is worth) |
| `LIMINAL_CELL_METRES=n` | force a uniform spatial grid instead of the adaptive one |
| `LIMINAL_LEVEL=<id>` | boot straight into a level |
| `LIMINAL_SPAWN=x,z[,yaw]` or `x,y,z[,yaw]` | spawn override; the 3-number form drops the player onto the local floor |
| `LIMINAL_CAPTURE=frame.png` | render one frame, write it, exit |
| `LIMINAL_CAPTURE_FRAME=n` | which frame to capture (default 1), so a moving object can be captured mid-animation |
| `LIMINAL_NO_LIGHTMAPS=1` | force the vertex-lit path for a lightmap A/B capture |
| `LIMINAL_CULL_FACE=0` | turn single-sided back-face culling off for one binary's A/B; unset, `1`, `true`, `on` keep the shipped culling |
| `LIMINAL_DUMP_LIGHTMAPS=1` | write baked atlas pages as PNGs under `target/agent-work/atlases/` (a fresh bake only — delete `cache/lightmaps/` first, since a cache hit writes nothing) |
| `LIMINAL_QUALITY=full\|low` | draw this run at the named profile without editing `settings.json` |
| `LIMINAL_PAUSE=1` | open the pause menu on the first frame, so the pause UI can be captured without a keyboard |
| `LIMINAL_VERBOSE=1` | print the startup/level-build telemetry a capture run usually stays silent about |

The demo's emission animations advance on the simulation's own delta, so a
capture at `LIMINAL_CAPTURE_FRAME=1` is always the authored brightness; later
frames show whatever the elapsed clock reached, which is what a flicker capture
wants. The summary reports `reflection_passes` (scene submissions the frame
spent on the active planar plane) alongside the timing and counter fields.

The run summary is printed as a single line:

```
BENCH_SUMMARY {"level":...,"frames":...,"swap_interval":...,"loop_median_ms":...,...}
```

`loop_ms` is begin-of-frame to begin-of-frame, i.e. the real presentation
cadence including the swap. `frame_ms` is begin-of-frame to end-of-swap. FPS
figures in the summary are always derived from `loop_ms`, never from a count of
renderer submissions.

## Retired

The PocketCHIP-over-SSH device suite (`run_bench.py`, `runone.sh`,
`gen_levels.py`, `analyze.py`) was removed with the PocketCHIP device support. It
depended on the historical PocketCHIP/Vitrallis deployment, the committed
cross-compile shim and expect-shim script paths outside the repository, and its
local replacement is `bench_local.py`. `bench_repeat.py` was removed because
`bench_local.py` now reports min/median/max itself, and the earlier per-change
capture scripts were replaced by the single `capture_views.sh`.

## Validation notes

Validation records and measurements live in `notes/`:

| note | contents |
|---|---|
| `renderer-change-validation.md` | how each change was validated, and what the pixel comparison actually measures |
| `level-build-cache.md` | what a level load costs, and the proposed whole-level build-cache key/invalidation design |
| `lightmap-bake-validation.md` | the baked-lightmap measurements: cold/warm bake cost, Full/Low density and memory, runtime draw calls, vertex-memory cost and the lightmap-vs-vertex pixel A/B |
| `surface-response-validation.md` | the surface-response, transparency and offscreen changes |
| `post-processing-reflections-validation.md` | the bloom and reflection changes |
| `compiled-build-qa-validation.md` | the compiled-build smoke tests, Full/Low comparison against the pre-change baseline, demo QA playthrough and error-path additions |
| `office-pool-content-validation.md` | the Office and Pool content checks and the creator replacement test |
| `texture-material-validation.md` | the external-texture/material loading and replacement checks |
| `vertical-geometry-validation.md` | the elevated/recessed/gable geometry checks |
| `wall-boundary-lighting-validation.md` | the wall/floor/ceiling isolation model and its acceptance fixture |

The `LIMINAL_BENCH_*` submission switches (`LIMINAL_BENCH_NOCULL`,
`LIMINAL_BENCH_NOINDEX`) are still implemented and still isolate one renderer
decision each; they are simply exercised by `bench_local.py` now.

`LIMINAL_BENCH_EXACT_VERTEX` is gone. The exact 72-byte vertex layout it
selected is kept in `src/render/mesh.rs` as the reference the packed layout's
dequantization is tested against, but the renderer no longer uploads it: on the
PocketCHIP's Lima driver that upload path reliably faults the geometry
processor's MMU and leaves the GPU unusable until reboot.

## PocketCHIP device suite

The tools above drive a release binary on a development machine. The handheld
edition is measured on the device itself, over SSH, with four shell scripts:

| tool | what it does |
| --- | --- |
| `gpuwatch.sh` | samples the kernel's `devfreq_monitor` tracepoint and reports the GPU busy fraction |
| `measure.sh` | runs one configuration and prints one line of frame timing, GPU load, draw counts and fault count |
| `matrix.sh` | runs a series of named configurations at one viewpoint |
| `bisect.sh` | like `matrix.sh`, and reports the GPU faults each configuration caused |

They expect the built game at `~/places-dev` and themselves in `~/bin` on the
device. `measure.sh` needs `sudo` only to read `dmesg` for its fault count.
See [docs/POCKETCHIP.md](../../docs/POCKETCHIP.md) for the target, the shipped
profile and the measured results, and
[docs/gpu-utilisation.md](../../docs/gpu-utilisation.md) for what the GPU
number is and how it was validated.

### A/B measurement tools

`matrix.sh` compares configurations of one binary, which is enough when a change
is behind an environment switch. Comparing two *binaries* needs the same
treatment, and on a single-core Cortex-A8 that also means controlling for drift:
`schedutil` swings the core between 432 MHz and 1.008 GHz and moves `render_ms`
by 30 % on its own.

| tool | what it does |
| --- | --- |
| `probe.sh <label> <binary> <spawn> <frames> [ENV=VAL ...]` | one run of any binary in the shared benchmark environment; prints frame timing, GPU load, level-build time and the new GPU fault count |
| `ab.sh <spawn> <frames> <label>\|<binary>\|<ENV=VAL ...> ...` | runs every spec once per round, interleaving the rounds, so drift hits every condition equally |
| `csv_stats.py <dir> [labels]` | folds the per-frame CSVs into medians and trimmed means of `loop_ms`, `render+swap`, `render`, `swap` and `update` across all rounds |
| `present_probe.py <label> [ENV=VAL ...]` | runs one presented configuration and reports its cadence: the `loop_ms` histogram, the fast/slow split, and the cumulative-phase concentration against the 59.52 Hz refresh |
| `visual_probe.sh <binary> [ENV=VAL ...]` | reports the geometry and **depth** of the running game's X11 window |
| `atlas_views.sh <dir> [binary]` | captures the prop-atlas visual gate: macro, oblique, far and floor-control prop views, aimed at where an atlas fails if it fails |
| `capture_diff.py <a-dir> <b-dir> [--tolerance n]` | per-pixel comparison of two capture sets, with the largest connected differing region per shot — the shape that separates a dropped surface from a filtering difference |

Pin the governor before an A/B series and put it back afterwards:

```sh
ssh chip@chip 'echo chip | sudo -S -p "" sh -c "echo performance > \
    /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"'
ROUNDS=3 ~/bin/ab.sh 2,5.6,74 200 \
    "baseline|./places-pass2|" \
    "candidate|./places|"
python3 tools/bench/csv_stats.py /tmp/bench-csvs
ssh chip@chip 'echo chip | sudo -S -p "" sh -c "echo schedutil > \
    /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"'
```

Measurement notes that matter more than the scripts:

* `LIMINAL_BENCH_NOSWAP=1 LIMINAL_BENCH_FINISH=1` is the **low-variance** metric:
  it is the frame's serialised CPU + GPU work with no present path involved, and
  repeated runs at one viewpoint agree to about 0.1 ms where presented medians
  scatter by 2 ms. Use it to decide between candidates, then confirm the winner
  with presented medians.
* `render_ms` and `swap_ms` trade time with each other run to run, because a
  full command queue blocks inside whichever call the CPU is in. Compare their
  **sum**, or `loop_ms`, never one alone.
* `LIMINAL_BENCH_NORENDER=1` with `gpuwatch.sh` measures the present path on its
  own: no scene, no UI, just swaps.

