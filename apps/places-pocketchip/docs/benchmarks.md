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
* `probe.sh` / `ab.sh` / `csv_stats.py` — interleaved A/B of two *binaries*.
* `present_probe.py` — the presented cadence and its vblank phase lock.
* `visual_probe.sh` — the running window's X11 geometry and depth.

Copy them to the device's `~/bin` together with the built game in `~/places-dev`
and run them over SSH. They need `sudo` only to read `dmesg` for the fault
count.

---

# Pass 3 — where the frame actually goes

Pass 2 cut the fragment stage and the frame fell from 61-65 ms to 37-38 ms. Pass
3 started from the hypothesis that the next lever was the 27 prop submissions.
That hypothesis was measured before anything was built, and it turned out to be
worth about 2 ms — a real but small win. Measuring it properly also produced a
much more useful map of the frame, which is what this section records.

Everything below is a device measurement. The two measurement tools that made it
possible are `LIMINAL_BENCH_NOSWAP=1 LIMINAL_BENCH_FINISH=1` (the frame's
**serialised** CPU + GPU work, repeatable to ~0.1 ms) and `LIMINAL_BENCH_NOSWAP=1`
alone (the same frame with the CPU and GPU free to overlap, i.e. the GPU's own
throughput).

## The frame, decomposed

Office viewpoint, `2,5.6,74`, 200 frames, median of interleaved rounds:

| measurement | median | what it is |
| --- | --- | --- |
| presented (`loop_ms`) | 39.1-40.4 ms | the shipping frame |
| serialised work (`NOSWAP+FINISH`) | **32.8 ms** | CPU submission + GPU, no present |
| pipelined (`NOSWAP`) | **17.2 ms** | GPU throughput with the CPU hidden behind it |
| present-only (`NORENDER`) | **4.0 ms** | swap + update, no scene at all |
| work with a 96x54 viewport (`NOSWAP+FINISH TINY`) | **16.0 ms** | same submissions, ~1/25 the pixels |

Three things follow directly.

1. **The GPU's own work is about 16.5 ms a frame** — the `NOSWAP` run is 98 %
   GPU-busy at 17.2 ms a frame.
2. **The pixel processor is about half the frame.** Shrinking only the viewport
   removes 16.8 ms of the 32.8 ms, with every draw call, texture bind and
   material change still issued. That 16.8 ms is fill *and* tile-list binning;
   the two were not separated.
3. **Presenting costs about 6 ms and destroys the CPU/GPU overlap.** `NORENDER`
   proves the swap itself is cheap when there is nothing to present (4 ms a
   frame, i.e. ~250 presents a second), and `docs/presentation.md` shows what
   the X server is doing for that time.

## Draw calls, measured before they were removed

The prop pass drew 27 ranges with 27 textures. A temporary benchmark collapsed
it in two steps, on one build, at one viewpoint, with everything else held
fixed:

| condition | draws | binds | material changes | serialised work | delta |
| --- | --- | --- | --- | --- | --- |
| normal | 64 | 69 | 62 | **32.85 ms** | — |
| every prop range through one texture | 64 | 46 | 39 | **31.42 ms** | **-1.43 ms** |
| all prop geometry in one draw | 41 | 46 | 39 | **30.87 ms** | **-0.58 ms** |

The three rows repeat to 0.05 ms. So:

* removing 23 **texture/material state changes** is worth **1.43 ms** (0.062 ms
  each — the single most expensive per-unit cost measured anywhere in the frame);
* removing 23 **draw submissions** is worth **0.58 ms** (0.025 ms each);
* collapsing the prop pass therefore has an upper bound of **about 2.0 ms**, or
  6 % of the frame.

The Prop 1 stop rule was "less than ~2 ms total, stop". The measurement landed
*on* 2 ms: the prop atlas was worth building, but it was never going to be the
thing that crossed 33.6 ms, and the report says so rather than implying
otherwise.

## Rejected experiments

Each of these was measured on the device and not retained.

| experiment | measured | verdict |
| --- | --- | --- |
| **Back-face culling, all surfaces** | serialised work 32.8 → 29.9 ms (**-2.9 ms**), presented 39.1 → 36.4 ms | **Rejected.** It is the single largest renderer lever found, but it opens holes: 22 of the 25 reference views change, up to 111/255 per channel, and the reception view loses wall surface beside the doorway. Pass 2 rejected the same change for the same reason, and this pass did not find a *safe* subset: see the next row. |
| **Back-face culling, per surface kind** | walls -2.06 ms, props -0.63 ms, floors+ceilings **±0.08 ms** | **Rejected.** The entire prize is in walls and props, which are exactly the kinds whose winding the renderer cannot vouch for; the one safe kind is worth nothing. |
| **Front-to-back opaque submission** | serialised work 32.8 → **35.5 ms** | **Rejected, worse.** Sorting the 39 static batches by camera distance costs more in state churn than the early depth test saves. Pass 2 saw the same thing; this reproduces it with a switch that isolates the ordering alone. |
| **Coarse spatial partitioning** | at 16 m: 115 draws instead of 64, serialised work 32.8 → **38.3 ms**, and it culled **20 of 29 491 vertices** | **Rejected, much worse.** The level is compact enough that every 16 m cell still intersects the view frustum, so the extra batches buy no geometry and cost 5.5 ms. This is Pass 1's result, reproduced in the post-Pass-2 cost model. |
| **Pinning a depth-24 X11 visual** | window stays depth 32 under every `SDL_VIDEO_X11_*` override, `SDL_GL_ALPHA_SIZE=0` and explicit RGB sizes; `glxgears` gets depth 32 too | **Not reachable.** GLX on this stack always returns the ARGB config, so the server-side conversion measured in `docs/presentation.md` cannot be removed from inside the game. |

## Static batches

Untouched, deliberately. A read-only audit of `SurfaceKey` found exactly two
of the 39 batches mergeable under the reduced tier — one wall pair split only by
a `shine` value the reduced shader reads no location for, and one floor pair
whose two materials resolve to the same albedo. Together they would remove about
one material change, well under 0.1 ms. Everything else is a genuine albedo or
pass distinction, and the tiling surface sheets cannot be atlased without
shader UV arithmetic, which is the wrong trade on this part.

## Where the frame actually is

The pass-3 attribution probe — temporary `LIMINAL_BENCH_NO_PROPS` and
`LIMINAL_BENCH_NO_STATIC` early-returns in `draw_scene_body`, removed again
after the measurement — is the most useful number this pass produced. Office
viewpoint, serialised work (`NOSWAP+FINISH`):

| submitted | work | share |
| --- | --- | --- |
| everything | 30.9 ms | 100 % |
| props only (all static passes skipped) | 10.0 ms | — |
| static only (prop pass skipped) | 24.9 ms | — |
| neither (dynamic + clear + UI + loop) | 6.3 ms | 20 % |

The shares overlap because the parts are not independent, but the ranking is
unambiguous: **the static world is about two thirds of the renderer's work and
the prop pass is about a fifth of it.** The prop pass was the right thing to
collapse because it was cheap to collapse — not because it was the biggest
thing in the frame. With the atlas in, the prop pass draws 24 344 vertices in
one submission and still costs ~6 ms, almost all of it rasterisation and tile
work rather than submission.

That also gives the answer to "is a prop-visibility feature worth building?".
The absolute upper bound on every prop-visibility idea, including dropping props
entirely, is the ~6 ms above — and the visible props (3 to 13 instances a view)
must survive it. It is not a large enough prize for an occlusion pipeline on
this driver, and the audit that proposed it said to stop if the bound was small.

## The prop atlas

Implemented, measured, and shipped. `src/render/prop_atlas.rs` packs every prop
model's albedo into one 1024 × 1024 RGBA8 sheet and remaps the instance UVs on
the CPU as the level is built, so the fragment stage does no atlas arithmetic.

| | Pass 2 | Pass 3 |
| --- | --- | --- |
| prop draws | 27 | **1** |
| prop batches | 27 | **1** |
| total draws, office / work / pool | 64 / 54 / 62 | **41 / 35 / 38** |
| texture binds, office / work / pool | 69 / 56 / 64 | **46 / 37 / 40** |
| material changes, office / work / pool | 62 / 53 / 60 | **39 / 34 / 36** |

Layout: cell stride 144 texels, 7 × 7 = 49 cells, content 128 × 128 with an
8-texel edge-replicated gutter, mipmaps kept but capped at level 3 (the deepest
level where an 8-texel gutter is still ≥ 1 texel, so a bilinear footprint can
never reach a neighbouring cell). A model whose submeshes do not agree on one
unmasked albedo, or that does not fit, keeps the historical per-model path.
`LIMINAL_PROP_ATLAS=0` disables it for an A/B.

### Measured effect

Serialised work (`NOSWAP+FINISH`), interleaved rounds, one binary each:

| viewpoint | Pass 2 | Pass 3 | delta |
| --- | --- | --- | --- |
| office `2,5.6,74` | 32.86 ms | **30.84 ms** | **−2.02 ms** |
| work `14,3.5,90` | 30.63 ms | **29.53 ms** | **−1.10 ms** |
| pool `2,13,90` | 30.57 ms | **28.66 ms** | **−1.91 ms** |

Presented (VSync off), 4 interleaved rounds × 300 frames pooled, office:

| metric | Pass 2 | Pass 3 | delta |
| --- | --- | --- | --- |
| `render` median | 9.18 ms | **7.12 ms** | **−2.06 ms** |
| `loop` p95 | 62.58 ms | **56.89 ms** | **−5.69 ms** |
| `loop` trimmed mean | 40.00 ms | **39.12 ms** | **−0.88 ms** |
| `loop` median | 39.86 ms | 42.01 ms | +2.15 ms |

The CPU submission cost and the frame-time tail both fall, exactly as the
submission model predicts. **The presented median does not**, and the reason is
in `docs/presentation.md`: the present path alternates between a ~30 ms and a
~43 ms frame with a period of two, so its contribution wanders by ±2 ms between
runs while a 2 ms renderer saving is fixed. Three round-pairings of the same two
binaries produced presented medians 2.7 ms apart in either direction; four
pooled rounds are not enough to resolve a 2 ms change through that.

### Cost and memory

* Atlas build: **185–337 ms** of the level build (per-run spread), fitting and
  copying 27 images and replicating every cell's gutter. Level build
  3.18 s → 3.34–3.43 s.
* Peak resident set: **65.4 MiB → 71.9 MiB** (VmHWM 67 416 kB → 73 628 kB). The
  sheet is 4 MiB plus its mip chain; the 27 per-model textures (1.7 MiB) are no
  longer uploaded, and the CPU staging buffer is dropped once the level's props
  are uploaded. The task's soft ceiling was 80 MiB.
* Zero new `gpmmu`/`ppmmu`/`timedout` kernel messages across every run, including
  the 1 200-frame presented A/B.

### Visual verification

Comparing the shipping build against *itself* with `LIMINAL_PROP_ATLAS=0`, so
the atlas is the only difference, over the 25-view capture set plus ten
purpose-built macro/oblique/far prop views:

* 3 of the 35 views are pixel-identical (`floor_office`, `floor_deck`,
  `oblique_office_wall` — the controls that contain no props).
* 28 views differ on **under 0.4 %** of pixels; the worst is
  `home_balcony_east` at **1.02 %**, and its delta histogram is 5 318 pixels at
  1–9/255, 218 at 10–19, 29 at 20–49 and a **single pixel** at 57/255, on a prop
  silhouette.
* Every difference lies on a prop edge. There are no seams, no neighbour
  texture, no wrong texture, no flipped UV and no missing prop, and a repeated
  capture of the same view is byte-identical, so none of it is measurement
  noise. It is what edge filtering and mip generation at a cell boundary look
  like; the cause is the level-3 mip cap and edge texels of a cell's blocks.
* The atlas also changes *what* is submitted: the merged prop draw has one
  level-wide bound, so the 1 576–4 832 vertices frustum culling used to reject
  are now always submitted. The atlas still wins on the work metric.

## Final numbers

Shipping build, 200 frames per viewpoint, one run each, `LIMINAL_VSYNC=off`
(raw) and `=on` (shipping presentation). Peak RSS and faults from the runs
above.

**Raw — VSync off**

| Viewpoint | fps | fps 1 % low | median | p95 | render | swap | draws | binds | materials | GPU mean / median | faults |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| office `2,5.6,74` | 24.76 | 11.29 | 39.4 ms | 51.9 ms | 10.8 ms | 22.7 ms | 41 | 46 | 39 | 32 % / 4 % | 0 |
| work `14,3.5,90` | 24.69 | 14.88 | 38.5 ms | 48.8 ms | 8.2 ms | 24.6 ms | 35 | 37 | 34 | 75 % / 96 % | 0 |
| pool `2,13,90` | 26.89 | 21.09 | 36.6 ms | 43.1 ms | 6.2 ms | 26.8 ms | 38 | 40 | 36 | 73 % / 96 % | 0 |

**Shipping — VSync on**

| Viewpoint | fps | fps 1 % low | median | p95 | render | swap | draws | faults |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| office | 26.17 | 18.22 | 37.6 ms | 51.8 ms | 7.3 ms | 28.3 ms | 41 | 0 |
| work | 26.65 | 16.43 | 36.5 ms | 52.6 ms | 9.2 ms | 25.1 ms | 35 | 0 |
| pool | 27.59 | 18.79 | 35.7 ms | 50.2 ms | 6.6 ms | 26.9 ms | 38 | 0 |

Pass 2's equivalent shipping table was 40.7 / 37.9 / 36.5 ms. Read those three
rows with the caveat above: at a 36–40 ms frame the presented median carries a
±2 ms run-to-run spread, so the honest reading is "at or slightly better",
while the renderer work behind it is decisively and repeatably lower.

**Did it cross 33.6 ms?** No. The best representative presented median measured
on the shipping build is **35.7 ms** (pool) against a two-refresh budget of
33.6 ms, and the deterministic renderer work it sits on is 28.7–30.8 ms. The
gap is the present path, not the renderer.



---

# Pass 4 — winding correctness and back-face culling

Passes 2 and 3 both measured global back-face culling and rejected it. The prize
was real — about 2.9 ms of serialised renderer work — but X-axis wall reveals
were generated back-facing, so culling them opened a hole at every X-axis
window and doorway. Pass 4 fixed the geometry rather than the demo, declared the
surfaces that are genuinely two-sided, and then shipped the cull.

Everything below is a device measurement on the same PocketCHIP, with the CPU
governor pinned to `performance` for every A/B (restored to `schedutil`
afterwards), interleaved rounds, and the same level, lightmaps, profile and
camera as the Pass-3 record. `render_ms` and `swap_ms` still trade time with
each other, so the tables compare their sum and `loop_ms`.

## Reproduced Pass-3 baseline

Before any change, the Pass-3 release binary (`places-final`) was re-measured at
the three viewpoints under the controlled governor. Serialised work
(`LIMINAL_BENCH_NOSWAP=1 LIMINAL_BENCH_FINISH=1`, 200 frames) and presented
median (`LIMINAL_VSYNC=on`, 200 frames):

| viewpoint | serialised | presented | draws |
| --- | --- | --- | --- |
| office `2,5.6,74` | 30.91 ms | 37.06 ms | 41 |
| work `14,3.5,90` | 29.55 ms | 38.18 ms | 35 |
| pool `2,13,90` | 28.70 ms | 35.98 ms | 38 |

The Pass-3 record's serialised figures were 30.84 / 29.53 / 28.66 ms, within
0.1 ms of every reproduction: the baseline is the same frame.

## The canonical convention

**Front face is the GL default, `GL_CCW`**, and a triangle's front side is the
side the right-hand normal over `p0 -> p1 -> p2` points to. Every face of a
solid is wound so that normal points **out of the solid**: a floor faces +Y, a
ceiling −Y, a wall face points into the room it looks at, a jamb or reveal
points into the opening it belongs to, and an end cap points out of the wall's
own end. The full contract is in
[`MAP_AUTHORING_GUIDE.md`](MAP_AUTHORING_GUIDE.md) ("Face winding and back-face
culling").

The two deliberately two-sided geometry classes are **panes in openings**
(`glass`: a single quad at the wall's centre plane, visible from either side,
whichever alpha mode its material uses) and **props whose glTF material declares
`doubleSided: true`**. Nothing else is two-sided, and no emitter duplicates a
solid face to fake it.

## Defects found

The winding audit covered every triangle producer in the crate. Four real
defects were found; none was visible while culling was off, and all four are a
hole the moment it is on.

| geometry | cause | effect with culling |
| --- | --- | --- |
| X-axis wall end caps and opening reveals (door/window jambs, header ends) | `add_wall_cross_quad`'s X corner walk was the Z walk transposed, so its forward order faced −X while `facing_positive` meant "+length" only on Z | every X-axis end cap and reveal is culled from its visible side: holes beside doorways and at windows |
| Z-axis stair treads and archway top caps | `horizontal_quad`'s Z mapping was the X mapping transposed, flipping handedness: documented "faces up", computed facing down | treads and caps vanish from above on Z-axis pieces |
| floating box undersides (raised half walls, columns) | the bottom cap reused the up-facing corner order while declaring a −Y normal | the visible underside vanishes |
| ramp sides that land flush on a floor (and other folded degenerate quads) | `orient` normalises against the quad normal, but a quad with a coincident corner pair has a zero normal, so it could not detect the reversed winding; the fold then emitted the wrong triangle | a falling ramp's side skirt can be culled away |
| a wall end (or reveal) that shows through an opening in the wall it abuts | `cross_section_covered` counted an abutting perpendicular wall as covering its whole length, so an opening cut through that wall did not reduce the cover | the exposed strip is deleted and the opening shows the clear colour: two void regions in the pool-hall capture set |

## Geometry corrections

* `add_wall_cross_quad` now pairs its corners into the walk that faces the
  positive length direction on **both** axes; the X branch runs down the
  thickness axis and the Z branch up it.
* `horizontal_quad`'s Z walk now runs the other way round so it genuinely faces
  up; the floating box's bottom cap reverses that same walk for its downward
  face.
* `emit_face` re-asserts a face's declared outward normal on the corners that
  survive `fold_triangle_to_quad`, so a degenerate fold can never keep a
  reversed winding; the reversed form keeps the repeated corner last so the
  index pass still drops the zero-area triangle.
* `cross_section_covered` now contributes each **solid slice** of a
  perpendicular abutting wall instead of its whole length, so an opening cut
  through that wall leaves exactly the strip of end face that shows through it
  exposed and keeps the covered part suppressed.
* No level, lightmap or material content changed. Positions, materials, UVs and
  lightmap charts are the same surfaces, plus the end strips that the coverage
  bug deleted; only their winding and, for mirrored X-axis reveals, their
  in-plane frame were corrected.

## Two-sided semantics

* **Panes** carry a `two_sided` surface key from the emitter that knows the
  geometry is a sheet. The renderer draws that batch with culling disabled, so a
  `cutout` transfer grille keeps rendering from the far room and an `opaque`
  pane is never culled from one side. Blend panes already drew in the unculled
  translucent pass.
* **Props** read the glTF material's `doubleSided` flag. It defaults to `false`
  (the glTF default), so a single-sided model is a closed solid and is culled;
  a model that declares it draws both faces. Every shipped prop declares it —
  the pool curtains are folded ribbons built from two windings — so props render
  exactly as before. The atlas merge refuses to mix culling states, so a merged
  draw can never apply one range's sidedness to another's geometry.
* **Everything else** — floors, ceilings, wall faces, reveals, fixtures, prop
  placeholder boxes, ramps, stairs, trim and decals — is single-sided and
  culled.

## Renderer culling

`glFrontFace(GL_CCW)` and `glCullFace(GL_BACK)` are set once when the context is
created, and `GL_CULL_FACE` is bracketed per pass with change tracking:

1. static opaque batches, per batch (on unless the key is two-sided);
2. props and dynamic objects, per range (on unless the material is
   `doubleSided`);
3. static cut-out batches, per batch (as opaque);
4. translucent (off — glass is two-sided by nature);
5. decals (on);
6. restored off before the HUD.

At the shipping content that is six `glEnable`/`glDisable` calls a frame, none of
which changes the pipeline: props are one double-sided merged draw, so the
whole scene costs the same number of state changes as culling off plus a
handful of toggles.

## Visual verification

The 38-view capture set (`tools/bench/capture_views.sh`) was captured twice on
the device with the **same binary**, once with culling on and once with
`LIMINAL_CULL_FACE=0`, and compared per pixel with
`tools/bench/capture_diff.py`; the transfer grille was additionally captured
from both rooms with stable viewpoints (`grille_west`, `grille_east`).

Against the pre-fix Pass-4 build, the final build adds the end strips the
coverage fix restores only where it should: two views change. `wet_deck_shallow`
is the void strip fixed (0.896 % of pixels, the region the clear colour used to
show through), `pool_entry` the other (2.697 %, a 15 cm strip plus the pool
corner). On the final build those same two views are compared between culling
on and off directly: `wet_deck_shallow` is **pixel-identical** (0 differing
pixels) and `pool_entry` differs on 19 pixels (0.015 %, largest connected
component 7 px), all on a lit edge. No clear-colour pixel appears in either.

For the other 36 views the geometry is unchanged by the coverage fix, so the
pre-fix on/off comparison still describes them. Its result, with the same
culling-on/off pair:

* **22 of 38 views are pixel-identical** at a tolerance of 2/255, including
  every office window, the reception, the workroom, the stair hall, the pool
  windows, the curtains and the drum.
* 13 views differ on under 0.1 % of pixels — the largest is the curtain wall at
  638 pixels (0.081 %, worst channel delta 37) — and every difference is on a
  lit silhouette edge, which is the sub-pixel coverage a removed back face
  legitimately changes. There is no clear-colour region in any of them.
* `grille_pool` is excluded: its shipped spawn (8.9, 6.2) stands inside the wall
  that carries the grille (x 8.85–9.15), so collision resolution can land the
  player a little differently per run. It is replaced in the view table by
  `grille_west` and `grille_east`, which stand clear in each room and differ
  between culling on and off on **2 pixels each** — the pane renders from both
  sides.

`check_holes.py` reports no capture above 0.1 % near-black on either set, and
the clear-colour scan of the final captures finds no culling-caused void: the
few exact-clear pixels in `office`, `reception`/`spawn` and `pool_wide` are
pre-existing open edges of the demo shell and appear identically with culling on
and off.

## Culling A/B

Same binary (`places-pass4-d`), `LIMINAL_CULL_FACE=0` vs default, interleaved
rounds; `csv_stats.py` folds the per-frame CSVs. Serialised work is
`NOSWAP+FINISH` (200 frames × 3 rounds, n = 600); presented is
`LIMINAL_VSYNC=on` (300 frames × 2 rounds, n = 600). The presented row is the
headline: the same level, camera and binary, culling off then on.

**Serialised work — `NOSWAP+FINISH`**

| viewpoint | off median | on median | delta | off trimmed | on trimmed | off p95 | on p95 | draws on/off | verts on/off |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| office `2,5.6,74` | 31.43 ms | **29.54 ms** | **−1.89 ms** | 31.54 | 29.84 | 33.23 | 36.40 | 41 / 41 | 31 071 / 31 071 |
| work `14,3.5,90` | 30.19 ms | **28.58 ms** | **−1.61 ms** | 31.01 | 28.69 | 39.85 | 30.46 | 35 / 35 | 30 931 / 30 931 |
| pool `2,13,90` | 29.17 ms | **27.75 ms** | **−1.42 ms** | 29.33 | 27.89 | 34.39 | 29.77 | 38 / 38 | 30 951 / 30 951 |

**Presented — `LIMINAL_VSYNC=on`**

| viewpoint | off median | on median | delta | off trimmed | on trimmed | off p95 | on p95 | GPU load off → on (mean/med/p95) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| office | 38.75 ms | **36.46 ms** | **−2.29 ms** | 38.90 | 36.55 | 55.11 | 52.20 | 73.3/95/98 → 77.6/96/98 |
| work | 38.20 ms | **36.59 ms** | **−1.61 ms** | 38.10 | 36.31 | 52.98 | 52.37 | 75.9/95/98 → 77.3/95/98 |
| pool | 36.32 ms | **34.66 ms** | **−1.66 ms** | 36.28 | 35.09 | 51.78 | 50.88 | 74.2/95/98 → 76.3/95/98 |

The submitted geometry is identical in both states — the same draw calls, the
same vertices, the same texture binds and material changes — so the saving is
purely raster and tile-list work the pixel processor no longer executes. The
GPU's busy fraction stays at 95–96 % median in both states: the GPU remains
saturated, it simply completes the same frame with less work in it. The
per-range medians are stable run to run (office serial: off 30.80/30.91/30.82,
on 28.99/28.91/28.92), which is the same repeatability the Pass-3 method
promised for this metric.

## Final numbers

Final artifact (`places-pass4-d`), CPU governor `performance`, interleaved
rounds. "Shipping" is `LIMINAL_VSYNC=on` (300 frames × 3 rounds per label,
pooled into one CSV per label); serialised is `NOSWAP+FINISH` (200 frames × 3
rounds). Pass 3 is the released `places-final` binary, measured in the same
interleaved series for the presented table.

**Shipping presented — Pass 3 vs Pass 4**

| viewpoint | Pass 3 median | Pass 4 median | delta | Pass 3 trimmed | Pass 4 trimmed | Pass 3 p95 | Pass 4 p95 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| office `2,5.6,74` | 38.55 ms | **36.86 ms** | **−1.69 ms** | 38.73 | 36.82 | 54.52 | 52.89 |
| work `14,3.5,90` | 37.58 ms | **37.06 ms** | **−0.52 ms** | 37.86 | 36.71 | 52.76 | 52.55 |
| pool `2,13,90` | 37.24 ms | **35.58 ms** | **−1.66 ms** | 37.17 | 35.74 | 52.84 | 53.49 |

`render+swap` medians (the frame's non-simulation work): office 35.48 → 33.55,
work 34.47 → 32.50, pool 32.89 → 31.39 ms. Draw calls, texture binds, material
changes and submitted vertices are unchanged from Pass 3 except for the four
vertices the restored end strips add on the pool view; the frame is smaller
because fewer fragments are rasterised, not because anything left the level.

**Raw serialised renderer work — culling off vs on** (the A/B table above):
29.54 / 28.58 / 27.75 ms with culling on, 31.43 / 30.19 / 29.17 ms with it off.
The Pass-3 release reported 30.84 / 29.53 / 28.66 ms at the same viewpoints on
its own binary.

## Did it cross 33.6 ms?

The presented median is the audience-facing number; the deterministic renderer
work is the engineering one. Per viewpoint:

* **office: 36.86 ms presented, 29.54 ms serialised.** No.
* **work: 37.06 ms presented, 28.58 ms serialised.** No.
* **pool: 35.58 ms presented, 27.75 ms serialised.** No.

The renderer's own work crossed 33.6 ms by a wide margin — it is 27.8–29.5 ms
at every viewpoint — but the present path's ~4–6 ms and its ±2 ms run-to-run
wander sit on top of it, exactly as Pass 3's `docs/presentation.md` describes.
The best individual presented run in the series is pool round 2 at **33.84 ms**
and the pool label's trimmed mean is 35.74 ms; the distribution does not yet sit
under two refresh intervals. Nothing was changed to force it: the resolution,
FOV, level content, lightmaps and props are all as shipped.

## Memory and GPU stability

`rssprobe.sh` on the final binary (lightmap bake + level build + steady state,
`VmHWM` at 12 s after the level reported ready): **73 368 kB (71.65 MiB)**, and
73 372 kB with `LIMINAL_CULL_FACE=0`. The Pass-3 release measured 73 628 kB
(71.9 MiB); the culling machinery costs two booleans and changes no allocation.
The soft ceiling is 80 MiB and the value is comfortably inside it.

Kernel-log fault count across every measurement in this section: **0** new
`gpmmu`, `ppmmu` or `timedout` messages, including the 1 200-frame presented
A/B, the 48-run final series, the capture sets and the RSS runs.

## Rejected approaches

* **Turning culling on before fixing the geometry.** This is Pass 2 and Pass 3's
  rejected experiment, and it was not re-tried: the audit showed the reveal
  winding was wrong, so the fix came first. The measured size of the prize on
  the final build (−1.4 to −2.3 ms) matches what those passes measured.
* **Culling the prop pass.** Every shipped prop material declares
  `doubleSided: true`, and the pool curtains are genuinely two-faced; the flag
  is the model's stated semantics, so props stay unculled. The alternative —
  deciding per model by inspecting geometry — would be culling by heuristics
  rather than by asset properties.
* **Duplicating opaque panes into two windings.** The pane's key declares it
  two-sided instead, which keeps one quad per pane, one lightmap patch and one
  draw range, and keeps blend panes from double-blending.
* **Switching `glFrontFace` per pass.** The convention is fixed once at startup;
  the corrected geometry is consistent, so there is nothing to compensate.
* **Re-authoring the demo level around the missing end strips.** The strips are
  geometry the emitter should have produced; the fix is in the coverage test,
  not in the level.

## Post-cull re-profile

{{REPROFILE}}
