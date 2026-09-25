# PocketCHIP benchmark record

Every number here was taken on the physical PocketCHIP over USB, on the release
build, with the display at its native 480 × 272 and the game full screen. They
are the evidence behind the configuration in [`POCKETCHIP.md`](POCKETCHIP.md).

## Method

`tools/bench/measure.sh` runs one configuration and prints a single line:

```
<label> fps_med=… fps_1pct=… f_med=… f_p95=… f_max=… | render=… upd=… swap=… | draws=… verts=… mats=… tb=… | gpu_mean=… med=… p95=… | load=…ms faults=…
```

* `fps_med` / `fps_1pct` — median frame rate and the mean of the worst 1 % of
  frames, from the game's own `BENCH_SUMMARY`.
* `f_med` / `f_p95` / `f_max` — frame-time median, 95th percentile and worst,
  in milliseconds.
* `render` — CPU time submitting the frame; `swap` — GPU execution and present;
  `upd` — simulation.
* `draws`, `verts`, `mats`, `tb` — draw calls, vertices submitted, material
  changes and texture binds.
* `gpu_mean` / `med` / `p95` — the devfreq busy fraction, see
  [`gpu-utilisation.md`](gpu-utilisation.md).
* `load` — level build time from the `[level]` telemetry line.
* `faults` — count of new `gpmmu`/`timedout` kernel messages produced by the
  run. A non-zero value means the GPU faulted and the run is not comparable.

Three fixed viewpoints, all in `places_demo`:

| Name | `LIMINAL_SPAWN` | What it is |
| --- | --- | --- |
| office | `2,5.6,74` | the reception, a small closed room |
| work | `14,3.5,90` | the workroom, mid-sized, props and windows |
| pool | `2,13,90` | the pool hall, the heaviest view: the longest sight line, the recessed basin, the most fixtures and props |

VSync is off for measurement so the frame time is the renderer's own, not the
panel's. Each row is median-of-run, not median-of-one-frame.

## Baseline — before any change

Shipping defaults at the time: 1920 × 1080 windowed, `Full` profile
(1024-texel sheets, surface response on), lightmaps on, bloom on, reflections on.
Measurements were taken with the cheapest settings the build could run, because
the `Full` configuration could not complete a benchmark — it exhausted memory
and the GPU faulted.

Pool hall, pool-hall viewpoint, 100 frames:

```
fps_med 8.96 | f_med 109.7 | f_p95 118.2 | render 36.7 | upd 4.5 | swap 66.5
draws 170 | verts 31783 | mats 69 | tb 78 | gpu mean 75.7 med 99 p95 100
```

| Viewpoint | fps | frame median | render | swap | draws |
| --- | --- | --- | --- | --- | --- |
| office `2,5.6,74` | 10.15 | 96.6 ms | 36.3 ms | 54.8 ms | 170 |
| work `14,3.5,90` | 10.10 | 97.3 ms | 38.3 ms | 53.2 ms | 170 |
| pool `2,13,90` | 8.96 | 109.7 ms | 36.7 ms | 66.5 ms | 170 |

Environment at baseline:

* `/proc/version` — Linux 6.12.107 armv7l, Debian 13
* `glxinfo -B` — `Mesa`, `Mali400`, `OpenGL ES 2.0 Mesa 25.0.7-2+deb13u1`,
  `OpenGL ES GLSL ES 1.0.16`, accelerated, unified memory
* `xrandr` — `480x272` at `59.52` Hz
* RAM 463 MB total / 290 MB available, no swap
* CPU governor `schedutil` at 1008 MHz
* GPU `1c40000.gpu` at a fixed 297 MHz
* Process peak RSS 191 MB

## After each change

### Texture decode budget (memory)

`TextureCache` fits each sheet to the runtime budget as it is decoded instead of
keeping the source pixels and resizing only for the upload.

| | before | after |
| --- | --- | --- |
| Process peak RSS | 191 MB | **66 MB** |
| Lightmap + surfaces in the level build | 1126 ms | **113 ms** |
| Level build, warm cache | 5622 ms | **3176 ms** |

The frame rate did not move, which is the expected result: this change is about
resident memory, and it is what stopped the process being killed and the GPU
being driven into a fault.

### One spatial cell (draw calls)

`CellGrid::for_extent` returns one cell for the whole level instead of an
adaptive 12–40 m grid, so a surface group is one batch rather than one per cell.
The frustum still tests each batch's bounds; what is given up is the ~6 % of
vertices the grid used to cull.

| | before | after |
| --- | --- | --- |
| Draw calls | 170 | **62** |
| Vertices submitted | 31 783 | 31 527 |
| `render` (CPU) | 36.7 ms | **19.2 ms** |
| Frame median | 109.7 ms | **98.9 ms** |
| fps | 8.96 | **9.98** |

The frame rate moved less than the submission cost did because the GPU then
became the constraint — GPU median went from 44 % to 94 %, i.e. the bottleneck
moved to where it belongs.

### Direct-to-framebuffer (stability)

Removing the offscreen scene target and the post-processing stage it fed. Run at
the pool-hall viewpoint with `LIMINAL_NO_OFFSCREEN=1` first to prove the path,
then made unconditional.

| | offscreen | direct |
| --- | --- | --- |
| `render` | 19.2 ms | **16.1 ms** |
| Frame median | 98.9 ms | 98.9 ms |
| GPU faults in 150 frames | 1 | **0** |

The frame rate is unchanged; the fault count is the result. Before this, one
run in every one or two began with a `lima: ppmmu0 page fault` and every later
job timed out for the rest of the session.

### Material tier and reduced fog shader

The shipping tier compiles out the surface frame, the sheen and the reflections,
and evaluates the fog as `x²/(1+x²)` instead of `1 - exp(-x²)`. It is selected by
the profile, so a `LIMINAL_QUALITY=full` run still measures the full tier.

Shipping configuration (lightmaps on, reduced tier), 150–200 frames per view:

| Viewpoint | fps | fps 1 % low | frame median | frame p95 | frame max | render | swap | draws | load |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| office `2,5.6,74` | 15.25 | 12.18 | 64.4 ms | 75.0 ms | 84.2 ms | 11.9 ms | 49.3 ms | 64 | 4268 ms |
| work `14,3.5,90` | 15.11 | 12.27 | 65.4 ms | 73.6 ms | 86.7 ms | 10.2 ms | 49.2 ms | 54 | 5075 ms |
| pool `2,13,90` | 16.01 | 9.58 | 61.6 ms | 77.7 ms | 106.3 ms | 15.3 ms | 41.6 ms | 62 | 3176 ms |

GPU busy fraction was 73–77 % mean with a 96 % median and a 99 % p95 at every
viewpoint: the frame is GPU-bound and the CPU has headroom.

Level build breakdown at the shipping configuration:
`lighting 353 ms + props 2150 ms + surfaces 113 ms = 3176 ms`, 39 static batches
(floor 10 / ceiling 5 / wall 17 / light 5 / decal 2), 27 prop batches, 1 dynamic
object.

### Texture-cap sweep

Same configuration, same viewpoint, `LIMINAL_TEXTURE_EDGE` varied:

| Sheet edge | fps | frame median | GPU mean / median | Level build |
| --- | --- | --- | --- | --- |
| 64 | 16.18 | 61.0 ms | 72 % / 96 % | 4460 ms |
| 128 | 16.03 | 60.9 ms | 75 % / 96 % | 3357 ms |
| **256 (shipped)** | **16.12** | **60.8 ms** | **73 % / 96 %** | **3460 ms** |
| 512 | 15.90 | 61.1 ms | 63 % / 95 % | 4214 ms |

The spread is under 2 % and inside run-to-run noise. The device is not
texture-bandwidth-bound, so the cap is set by what the panel can show, not by
what the GPU can afford: **256**.

### Full tier, for comparison

`LIMINAL_QUALITY=full` — 1024-texel sheets and the full material stage — at the
pool-hall viewpoint, 60 frames:

```
fps_med 10.86 | f_med 90.6 | render 11.4 | swap 77.4 | draws 62 | load 14349 ms
```

Two thirds of the frame rate for four and a half times the load time, on a
480 × 272 panel. This is why the reduced tier is the shipping profile and the
full tier is only reachable by asking for it.

## Summary

| | baseline | final |
| --- | --- | --- |
| fps, office | 10.15 | **15.25** |
| fps, work | 10.10 | **15.11** |
| fps, pool | 8.96 | **16.01** |
| Frame median, pool | 109.7 ms | **61.6 ms** |
| CPU render time, pool | 36.7 ms | **15.3 ms** |
| Draw calls | 170 | **62** |
| Process peak RSS | 191 MB | **66 MB** |
| Level build, warm | 5622 ms | **3176 ms** |
| GPU faults in a benchmark run | 1 per run | **0** |

## Pass 2 — where the frame actually went

Pass 1 established the stable PocketCHIP renderer and left a GPU-bound frame:
61–65 ms median, 93–96 % GPU busy, 62–64 draws. Pass 2 asked what the pixel
processor was executing and removed it.

Every number below is VSync off, `LIMINAL_QUALITY=low`, lightmaps on, 200
recorded frames after 20 warm-up frames, at one of the three reference
viewpoints, on the same physical device. Run-to-run noise on the frame median
is about ±2 ms; the `swap` figure (GPU execution) is steadier and is what the
paired A/B tables compare.

### Method addition: block-level attribution

The reduced fragment stage was compiled with one block removed at a time
through a bench-only `LIMINAL_FRAG_LEVEL` probe that was removed after this
measurement. Pool hall, one run per level:

| Level | Blocks compiled | frame median | swap (GPU) |
| --- | --- | --- | --- |
| 0 | flat colour, no texture | 30.6 ms | 18.9 ms |
| 1 | + albedo texture | 33.9 ms | 15.9 ms |
| 2 | + atlas lightmap | 38.3 ms | 22.6 ms |
| 3 | + emission | 41.7 ms | 27.6 ms |
| 4 | + fog (shipping stage) | 61.0 ms | 46.3 ms |

Two things follow. Texture work — the albedo fetch, both atlas pages, the
trilinear filtering — is worth a few milliseconds at most, which is why every
texture experiment below lands in the noise. The fog block alone was about
18 ms of GPU time and the emission block another 5 ms: on this GPU a fragment
executes at roughly one instruction per cycle, so the fragment program *is* the
frame. (Levels 0 and 1 ran before the linker fix that kept the atlas attributes
alive, so their absolute numbers are soft; the 2→3→4 deltas are not.)

### Rejected experiments

| Experiment | Result | Why rejected |
| --- | --- | --- |
| Lightmaps off vs on (pool, office) | 61.3 vs 61.0 ms; 66.3 vs 65.0 ms | Both atlas fetches and the page select cost nothing measurable; the bake stays |
| Nearest vs trilinear filtering (office, pool) | 64.2 vs 65.7 ms; 60.4 vs 61.8 ms | About 2 %, and `NEAREST_MIPMAP_NEAREST` pops at mip transitions; trilinear stays |
| Per-frame front-to-back batch sorting | simulated −7 %…+14 % of fragments | With one spatial cell every batch AABB is level-wide, so the sort key carries no depth; the geometry's draw order is already a wall depth prepass for props |
| Wall-only back-face culling | −13 % of shaded fragments, ~2.5 ms of GPU time | The 25-view capture diff shows the window reveals are wall surfaces whose *visible* side is the back face; culling them opens a dark hole at every window and doorway. Rejected on the captures, not on the frame rate |
| Reducing the emission term to a separate program variant | subsumed | One uniform gate removes the block exactly; a program split would add links and a selection predicate per draw |
| Prop texture atlas (27 → 1 draw) | not implemented | The batching audit quantifies it (+3.3 MiB for a 1024-texel atlas, mip-bleed and culling-loss risk) but the prop pass is only 6–8 % of fragments and the CPU saving is unproven; recorded as the next lever instead |

### Retained changes

**Fragment rewrite** — squared distance instead of `length()`, no redundant
clamp, a uniform emission gate, and the per-draw light scale folded with the
luminous-face suppression into one uploaded gain vector. Measured against the
Pass-1 build:

| Viewpoint | Pass-1 shipping | after rewrite | swap before → after |
| --- | --- | --- | --- |
| office `2,5.6,74` | 65.0 ms | 48.3 / 47.8 ms | 47.5 → ~32 ms |
| work `14,3.5,90` | 65.4 ms | 48.0 / 50.0 ms | 49.2 → ~32 ms |
| pool `2,13,90` | 61.0 ms | 48.7 / 44.8 ms | 46.1 → ~28–32 ms |

**One-fetch stacked lightmap and GL-state reduction** — both 512-texel atlas
pages concatenated vertically at upload and the page byte folded into the
vertex UV, plus the redundant texture-unit switches, the duplicate prop bind
and the per-frame lightmap bind removed. About 1–2 ms and two fewer texture
binds per frame, with the draw-call count unchanged.

**Wall back-face culling (measured, then rejected)** — same binary,
`LIMINAL_CULL_WALLS` 0 vs 1:

| Viewpoint | culling off | culling on | swap off → on |
| --- | --- | --- | --- |
| office | 49.8 ms | 47.8 ms | 28.6 → 26.0 ms |
| work | 49.1 ms | 42.3 ms | 32.4 → 29.6 ms |
| pool | 47.7 ms | 44.7 ms | 27.2 → 25.6 ms |

The win was real but the 25-view capture diff showed why it cannot ship: the
window reveals are wall surfaces seen from their back side, so culling them
replaces a lit tiled reveal with a dark hole at every window and doorway
(`office_win_close`, `reception`, `pool_win_from_pool`, `home_ceiling` — up to
10.8 % of a view's pixels). The culling code was removed; the toggle no longer
exists.

**Vertex-stage fog** — same binary, `LIMINAL_VERTEX_FOG` off vs on:

| Viewpoint | per-fragment fog | vertex fog | swap off → on |
| --- | --- | --- | --- |
| office | 48.3 ms | 36.2 ms | 29.3 → 22.3 ms |
| work | 46.7 ms | 36.7 ms | 28.9 → 23.8 ms |
| pool | 46.0 ms | 36.7 ms | 25.7 → 19.1 ms |

The reduced tier evaluates the rational fog curve once per vertex and
interpolates one float; the full tier keeps the exact exponential per fragment
as its reference. 24 of the 25 capture views differ by at most 3/255 per
channel (capture frame 3, camera pinned), with zero pixels above 24/255; the
remaining view is the animated washer drum, where one edge pixel differs
because the drum's angle is time-dependent between runs.

### Visual verification

The 25-view capture set from `tools/bench/capture_views.sh` was rendered with
the per-fragment and vertex fog paths, and with wall culling on and off, then
diffed per pixel. Vertex fog: 24 of 25 views differ by at most 3/255 and zero
pixels exceed 24/255; the single larger delta is one pixel on the animated
washer drum, whose angle is time-dependent between runs. Wall culling: four
views lose their window reveals, which is why it was rejected — the pixel diff
is the evidence, not a frame-rate judgement.

### Final numbers

The final artifact (the clean build after the rejected experiments were
removed), 200 frames per viewpoint, one run each. Peak RSS over a separate
five-minute run was **66,788 kB** (65.2 MiB), and every run above ended with
zero new `gpmmu`/`timedout` kernel messages.

**Raw — VSync off**

| Viewpoint | fps | fps 1 % low | frame median | frame p95 | render | swap | draws | GPU mean / median | faults |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| office `2,5.6,74` | 25.34 | 19.60 | 37.9 ms | 46.9 ms | 9.8 ms | 25.8 ms | 64 | 63 % / 94 % | 0 |
| work `14,3.5,90` | 26.21 | 17.51 | 37.4 ms | 46.1 ms | 10.2 ms | 23.7 ms | 54 | 68 % / 95 % | 0 |
| pool `2,13,90` | 26.09 | 12.85 | 37.4 ms | 55.6 ms | 12.7 ms | 21.5 ms | 62 | 70 % / 94 % | 0 |

**Shipping — VSync on**

| Viewpoint | fps | fps 1 % low | frame median | frame p95 | render | swap | draws | faults |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| office | 23.89 | 10.88 | 40.7 ms | 66.6 ms | 18.6 ms | 20.3 ms | 64 | 0 |
| work | 25.95 | 11.44 | 37.9 ms | 58.5 ms | 12.6 ms | 23.8 ms | 54 | 0 |
| pool | 26.97 | 19.04 | 36.5 ms | 50.7 ms | 9.4 ms | 25.0 ms | 62 | 0 |

The swap interval is requested (`SDL_GL_SetSwapInterval -> Ok`) and reported
active (`SDL_GL_GetSwapInterval -> VSync`), but this X11/modesetting path does
not block on vertical refresh: frame times with VSync on are not quantised to
multiples of the 16.8 ms refresh, and their median matches the VSync-off run.
If the presentation path did block, a 37.5 ms frame would miss the two-refresh
deadline (33.6 ms) and present on the third refresh at 50.4 ms — three-refresh
presentation with the frame itself 13 ms clear of the missed boundary. The
persistent 10–15 ms `render` figure is the driver submission cost of 62–64
draws; that is the term the prop atlas would attack.

GPU busy stays at 94–95 % median in both modes while the wall-clock share of
GPU work falls by more than half versus Pass 1. That is the expected reading
for "the GPU is completing more work per second while remaining saturated":
utilisation is not a proxy for frame time, and the frame-time percentiles are
the decision metric.

## Running it yourself

The scripts live in `tools/bench/` beside this document:

* `measure.sh <label> <spawn> <frames>` — one configuration, one summary line.
* `gpuwatch.sh [seconds] [out.csv]` — the GPU busy-fraction sampler.
* `matrix.sh` / `bisect.sh` — run a series of configurations in one session.

Copy them to the device's `~/bin` together with the built game in `~/places-dev`
and run them over SSH. They need `sudo` only to read `dmesg` for the fault
count.
