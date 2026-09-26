# Places on the PocketCHIP

This copy of Places is built for one device. It is not a desktop game that also
happens to run on a handheld: the renderer, the runtime profile, the frame loop
and the build configuration are all chosen for the PocketCHIP's hardware, and
anything whose only purpose was a larger or more capable machine has been
removed rather than left switched off.

If you are looking for the desktop build, it is not here. `apps/liminal-rust`
in this repository is the published general-purpose package; this directory is
the handheld edition.

## Target hardware

| | |
| --- | --- |
| SoC | Allwinner R8 / sun5i-r8 |
| CPU | one Cortex-A8 at 1.008 GHz, NEON and VFPv3, **single core** |
| GPU | Mali-400 MP1 — one geometry processor, one pixel processor, 32 KB L2, 64-bit bus at 300 MHz, fixed at 297 MHz |
| Display | 480 × 272 panel at 59.52 Hz, Xorg with the `modesetting` driver on `/dev/dri/card0` |
| Memory | 463 MB total, no swap |
| Kernel | 6.12 armv7l, Debian 13 |
| Driver | Lima (`lima 1.1.0`) through Mesa 25.0.7 |
| GL | OpenGL ES 2.0 / GLSL ES 1.0.16 |

The GPU is the part that shapes every decision here. A Mali-400 MP1 has a
single pixel pipe and a 32 KB L2, so it is not merely a slow modern GPU — the
cost model is different. Per-draw-call submission, vertex processing and tile
list building dominate a frame; raw fill rate and texture resolution do not.
Fragment *instruction count* is the frame: the reduced fragment stage executes
at roughly one instruction per cycle on the pixel processor, so every operation
removed from it is measurable in milliseconds.

## What was measured, and what it decided

Every choice below comes from a measurement on the device, not from a rule of
thumb. The benchmark method is in the next section; the numbers are in the
release notes and in `docs/benchmarks.md`.

* **Draw calls were the frame.** The level was originally partitioned into a
  12 m spatial grid, which produced 170 submissions a frame and culled 6 % of
  the level's vertices. Removing the partition entirely — one batch per surface
  group for the whole level, 62 submissions — nearly halved the frame time.
  The grid is gone; `CellGrid::for_extent` returns a single cell.
* **Texture resolution is free.** Sweeping the surface sheet cap from 64 to 512
  texels moved the frame rate by under 2 %. The device is not
  texture-bandwidth-bound, so the cap stays at **256 texels**, which is visibly
  better than 128 on a 480 × 272 panel and costs nothing measurable.
* **The full material stage is not.** The `Full` profile — 1024-texel sheets,
  normal maps, a per-fragment sheen and the exact exponential fog — runs at
  about two thirds of the reduced profile's frame rate and takes four times as
  long to load a level. It is kept only as the A/B reference a benchmark run
  can ask for with `LIMINAL_QUALITY=full`.
* **The fragment stage was the frame, not the textures.** A bench-only probe
  compiled the reduced stage with one block removed at a time: skipping the
  albedo fetch, the atlas reads, the emission term or the fog. The pool view's
  GPU time fell from 46 ms to 38 ms without the atlas reads and to 23 ms
  without emission *and* fog — while disabling lightmaps entirely changed
  nothing. Texture dimension (64–512 texels), the lightmap path and trilinear
  filtering were all measured within noise; the fragment arithmetic was not.
* **Fog was 18 ms of the frame.** The exponential-squared atmosphere evaluated
  a `length()` and a rational curve per fragment. The reduced tier now evaluates
  the same rational curve once per *vertex* from the squared distance and
  interpolates one float to the fragment stage; at 40 m it differs from the
  exact exponential by about 1 % of blend, and at 70 m by about 5 %. The 25-view
  capture diff against the per-fragment path is at most 3/255 per channel.
* **Emission and the light multiply were next.** An emissive term that is black
  for most draws cost ~5 ms of fragment arithmetic; it is now behind one
  uniform gate, which is exact because black emission multiplies to zero under
  any mask. The per-draw light scale and the luminous-face suppression folded
  into a single uploaded gain vector.
* **The lightmap atlas is one texture now.** Both 512-texel pages are stacked
  vertically at upload time and the vertex's page byte becomes the texture
  offset, so every lightmapped fragment takes one fetch instead of two. The
  baked bytes, the chart layout and the disk cache are untouched, and the texel
  count is identical.
* **Back-face culling is on, once the winding was fixed.** Every opaque surface
  is wound so its right-hand normal points out of its solid, so the inward half
  of the static world can be rejected at rasterisation without changing what is
  visible. The previous two passes measured that prize and rejected it because
  X-axis wall reveals were generated back-facing: culling them opened a hole at
  every X-axis window and doorway. The fourth pass fixed the cross-section
  winding (plus two more orientation defects of the same class), declared the
  genuinely two-sided surfaces — panes in openings and glTF `doubleSided` props
  — as explicit exceptions, and enabled culling for everything else. Measured
  on the device: 1.4–1.9 ms of serialised renderer work and 1.6–2.3 ms of
  presented median, with no visible change across the capture set.
* **The offscreen render target had to go.** Places drew the scene into a
  colour+depth framebuffer and resolved it to the window. On this driver that
  path intermittently faults the pixel-processor MMU
  (`lima: ppmmu0 page fault`), after which the GPU never recovers and every
  later job times out. Drawing straight into the default framebuffer ran 150
  frames with zero faults, is one full-screen pass cheaper, and is what the
  renderer now does unconditionally. The post-processing stage that the target
  existed to feed — bloom, exposure, the tone shoulder and the grade — is gone
  with it.
* **Reflections went with it.** A probe bake was twelve whole-scene submissions
  at load and a planar mirror was a second full view of the level every frame,
  both through framebuffers of their own. They are removed rather than left
  off.
* **Memory was the stability problem.** The session kept every decoded PNG at
  its source resolution next to the smaller texture the GPU actually held:
  about 137 MiB of resident pixels for a 463 MB machine with no swap. Decoding
  now fits each sheet to the runtime budget as it is cached, and the process
  peaks at **66 MB** instead of 191 MB.
* **Cortex-A8 needs NEON asked for.** Rust's `armv7-unknown-linux-gnueabihf`
  target enables VFPv3 and leaves NEON off. `.cargo/config.toml` selects
  `target-cpu=cortex-a8` for the ARM targets only.
* **The prop pass is one draw now.** Twenty-seven prop submissions, 27 texture
  binds and 27 material changes became one of each, by baking every model's
  albedo into a single 1024-texel sheet and remapping the instance UVs on the
  CPU at level build time. Measured on the device: serialised renderer work
  −1.1 to −2.0 ms, CPU submission −2.1 ms, frame p95 −5.7 ms, for a measured
  185–337 ms of level build and 6.4 MiB of resident memory. It is the last submission-side
  lever of any size: the prop pass is now about a fifth of the renderer's work
  and the rest of it is rasterisation.
* **The static world was the frame, and half of it was invisible.** A temporary
  attribution probe (skip the props; skip the static passes) put the static
  world at about two thirds of the renderer's work and the prop pass at about a
  fifth. Back-facing rasterisation was the largest single renderer lever found,
  and the fourth pass took it by fixing the geometry rather than by re-authoring
  anything: 1.4–1.9 ms of serialised renderer work (office 31.4 → 29.5 ms, work
  30.2 → 28.6 ms, pool 29.2 → 27.8 ms), at the same draw count and vertex count.
  After the cull the static world's *front* faces, the prop pass (whose
  materials declare themselves two-sided) and the present path are the frame;
  see `docs/benchmarks.md` for the post-cull attribution.

## Graphics configuration

There is one shipping configuration. It is not a quality slider; it is what the
device runs.

| Setting | Value | Why |
| --- | --- | --- |
| Scene resolution | the drawable, 480 × 272 | the panel's own mode |
| Window | full screen | one panel, no window manager |
| Surface / fixture / decal sheets | 256 texels | see the sweep above |
| Prop sheets | 128 texels, packed into one 1024-texel atlas | models are read at 1–2 m; one draw instead of 27 |
| Emissive masks | 128 texels | |
| Lightmaps | on, 9 texels/m, 512-texel pages, stacked into one texture | the bake is the game's whole lighting model |
| Material tier | reduced (no surface frame, no sheen, one-fetch atlas, vertex-stage fog, gated emission) | the full tier is an A/B reference |
| Texture filtering | trilinear | floors and decals are minified 10–30× at room distances; measured within noise |
| Back-face culling | on for every single-sided surface; off for declared two-sided panes and `doubleSided` props | the winding audit made it safe; 1.4–1.9 ms of serialised renderer work measured |
| VSync | requested | the panel is 59.52 Hz; see `docs/presentation.md` for what the request actually does |
| Bloom, reflections | removed | |

Startup overrides exist for measurement, and none changes the shipped
behaviour: `LIMINAL_TEXTURE_EDGE=<64..1024>` pins the sheet cap,
`LIMINAL_PROP_ATLAS=0` falls back to the per-model prop textures,
`LIMINAL_QUALITY=full` selects the reference tier, `LIMINAL_NO_LIGHTMAPS=1`
forces the historical vertex-lit build, `LIMINAL_CULL_FACE=0` disables the new
back-face culling for an A/B, and `LIMINAL_VSYNC=on|off` overrides the swap
interval for a benchmark run. All of them are read once at startup, and the
lightmaps one is literal — a truthy value *disables* lightmaps.

## Build for the PocketCHIP

The device has no compiler. Places is cross-compiled from a development machine
against an ARM sysroot built from the device's own Debian distribution, so the
binary links against the same SDL2 the device runs.

```sh
# 1. An armhf sysroot with SDL2's headers and linker stubs.
mkdir -p ~/chip-sysroot && cd ~/chip-sysroot
curl -O https://deb.debian.org/debian/pool/main/libs/libsdl2/libsdl2-dev_2.32.4+dfsg-1_armhf.deb
curl -O https://deb.debian.org/debian/pool/main/libs/libsdl2/libsdl2-2.0-0_2.32.4+dfsg-1_armhf.deb
for deb in *.deb; do mkdir -p unpack && (cd unpack && ar x "../$deb" && tar xf data.tar.*); done

# 2. Cross-compile. Requires the armv7 target, zig and cargo-zigbuild.
rustup target add armv7-unknown-linux-gnueabihf
export PKG_CONFIG_ALLOW_CROSS=1
export PKG_CONFIG_PATH=~/chip-sysroot/unpack/usr/lib/arm-linux-gnueabihf/pkgconfig
export PKG_CONFIG_SYSROOT_DIR=~/chip-sysroot/unpack
cargo zigbuild --release --target armv7-unknown-linux-gnueabihf
```

The result is `target/armv7-unknown-linux-gnueabihf/release/liminal-rust`.

Any glibc at or above the device's own is fine; the device is Debian 13. Do
not use `target-cpu=native` — the build machine is not the target — and do not
add a generic `[build] rustflags` section, which would apply the ARM tuning to
a desktop build of the same source.

### Deploy

The game is a directory: the executable plus `assets/`, and it creates
`levels/`, `import/`, `cache/` and `settings.json` on first run.

```sh
ssh chip@<device> 'mkdir -p ~/places'
scp target/armv7-unknown-linux-gnueabihf/release/liminal-rust chip@<device>:~/places/places
scp -r assets chip@<device>:~/places/
ssh chip@<device> 'chmod 755 ~/places/places && cd ~/places && DISPLAY=:0 ./places'
```

A packaged install is the same tree under
`~/.local/share/vitrallis/apps/io.vitrallis.liminalrust/`.

### Runtime dependencies

`libSDL2-2.0.so.0`, `libm`, `libc` and SDL's own X11/DRM dependencies, all
already present on the device. Nothing is installed at app startup.

## Benchmarking

Two things are needed: a repeatable camera and a way to see what the GPU is
doing.

**Frame timing.** The game has a benchmark harness built in.

```sh
DISPLAY=:0 LIMINAL_BENCH=1 LIMINAL_BENCH_FRAMES=150 LIMINAL_BENCH_WARMUP=20 \
  LIMINAL_BENCH_OUT=/tmp/bench.csv LIMINAL_SPAWN=2,13,90 LIMINAL_VSYNC=off \
  ~/places/places
```

It prints one `BENCH_SUMMARY` JSON line with mean/median/p95/p99 frame times,
per-phase times (`update`, `render`, `swap`, `loop`), draw calls, vertices,
texture binds and material changes. `LIMINAL_SPAWN=x,z,yaw` pins the viewpoint;
the three views used for every comparison in this repository are the office
reception (`2,5.6,74`), the workroom (`14,3.5,90`) and the pool hall
(`2,13,90`, the heaviest).

Use `LIMINAL_BENCH_FINISH=1` to force the GL pipeline to drain before the swap
so the GPU's own time is separated from the submission cost. `LIMINAL_VSYNC=on`
measures the shipping presentation instead of raw frame time, and
`LIMINAL_NO_LIGHTMAPS=1` (truthy disables) is the vertex-lit diagnostic. Do not
combine the lightmaps diagnostic with a frame-time comparison: it rebuilds the
level through the other lighting path and changes more than the atlas reads.

**GPU activity.** See [`gpu-utilisation.md`](gpu-utilisation.md). The short
version: read the kernel's `devfreq_monitor` tracepoint from
`/run/vitrallis-gpu/trace_pipe` and take its `load` field, which the tracepoint
computes as `100 * busy_time / total_time`. It is a genuine busy fraction, not a
frequency.

**What to watch.** A frame is `render` (CPU submission) plus `swap` (GPU
execution and present). If GPU load sits at ~95 % the frame is GPU-bound and
the answer is fewer submissions or less per-fragment work; if it sits low with
a long `render`, the frame is CPU-bound in the driver. Once the fragment stage
is small enough, both phases matter: on this device the GPU stays near 95 %
busy while its wall-clock share falls, and the frame becomes
`render + swap + update` with the CPU no longer hidden behind the GPU.

## Instrumentation

`Renderer::new` reports the GL vendor, renderer, version and GLSL version once
at startup under `LIMINAL_VERBOSE=1`, and warns loudly if the context is a
software rasteriser. That check exists because the difference between the
Mali-400 and `llvmpipe` is the whole point of the port, and before it the game
could not tell you which one it had.

The graphics-configuration line also reports the profile actually in force and
marks it when a startup override is pinning it.

## Known limitations

* **The Lima driver faults on this hardware under memory pressure.** A GPU
  allocation that fails leaves the pixel or geometry processor reading an
  unmapped address, and the device stays degraded until it is rebooted. The
  offscreen render target used to trigger this on its own; it is gone, and the
  shipping configuration ran 150–200 frame benchmarks at each of the three
  reference viewpoints with zero faults. The mitigation is the memory fix
  above: keep the process's resident set small.
* **Frame rate.** Raw frame time (VSync off) is 36.6–39.4 ms at the three
  reference viewpoints, and 35.7–37.6 ms in the shipping presentation — roughly
  26–27 FPS. The swap interval is requested and accepted, but this
  X11/modesetting path does not block on vertical refresh: frames are not
  quantised to the 16.8 ms refresh, and `docs/presentation.md` shows what the
  present path actually does, what it costs and why it cannot be fixed from
  inside the game. The frame is split between the front faces of the static
  world, the prop pass (about a fifth, deliberately two-sided) and simulation;
  {{BOTTLENECK}}. Back-face rasterisation is no longer part of it: the fourth
  pass culls every single-sided surface and leaves only the declared two-sided
  ones — panes in openings and glTF `doubleSided` props — drawing both faces.
* **The prop pass is one draw.** Every prop model's albedo is packed into one
  1024 × 1024 sheet at level build time and the instance UVs are remapped on the
  CPU, so 27 prop submissions and 27 texture binds became one. Measured:
  serialised renderer work −1.1 to −2.0 ms a frame, `render` −2.1 ms, frame p95
  −5.7 ms, at the cost of 185–337 ms of level build and 6.4 MiB of resident set.
  The presented *median* does not move measurably, because the present path's
  own ±2 ms wander is larger than the saving; see `docs/benchmarks.md`.
* **Level load** is about 3.4 s warm, dominated by prop model decode, the atlas
  build and texture upload (~2.4 s), not by the lightmap bake (~0.33 s). The
  bake is cached by content key under `cache/lightmaps/`.
* **No swap.** A level that exhausts memory is killed rather than paged. The
  budget is the point of the texture caps.

## Files this port owns

| Path | What it is |
| --- | --- |
| `.cargo/config.toml` | Cortex-A8 + NEON for the ARM targets |
| `src/quality.rs` | one shipping profile, 256/128/128 texture budgets, `LIMINAL_TEXTURE_EDGE` sweep override |
| `src/materials/image.rs` | `TextureCache::with_sheet_budget` — fit at decode, not at upload |
| `src/spatial.rs` | one-cell grid: no spatial partition, one batch per surface group |
| `src/render/prop_atlas.rs` | the 1024-texel prop albedo atlas: cell layout, edge-replicated gutters, mip cap, CPU UV remap, `LIMINAL_PROP_ATLAS` |
| `src/render/view.rs` | two material tiers behind `LIMINAL_MATERIAL_SIMPLE`; the reduced tier's one-fetch stacked atlas, gated emission, folded light gain and vertex-stage fog |
| `src/render/renderer.rs` | direct-to-framebuffer rendering, the stacked lightmap upload, the prop-atlas upload and one-draw prop pass, GL identity report, tier selection, per-pass back-face culling with declared two-sided exceptions |
| `src/settings.rs` | 480 × 272 full-screen defaults, 200-pixel minimum window edge |
| `docs/presentation.md` | what the X11/modesetting/Mesa/Lima path actually does with a presented frame, and what may honestly be claimed about it |
