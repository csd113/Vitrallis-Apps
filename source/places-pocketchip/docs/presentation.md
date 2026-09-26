# Presentation on the PocketCHIP

This document answers one question with measurements: **what actually happens
between the end of a Places frame and the panel**, and what may honestly be
claimed about it. It exists because the previous pass could only say what SDL
reported, and "SDL returned `Ok`" is not evidence that anything was
synchronised.

Everything below was measured on the physical device with the release build
(`LIMINAL_BENCH=1`, VSync off unless stated), using `tools/bench/present_probe.py`
for the cadence shape, `tools/bench/probe.sh`/`ab.sh` for A/B timing,
`tools/bench/visual_probe.sh` for window geometry, and `tools/bench/gpuwatch.sh`
for the GPU busy fraction.

## What SDL reports

| request | `SDL_GL_SetSwapInterval` | `SDL_GL_GetSwapInterval` | `BENCH_SUMMARY.swap_interval` |
| --- | --- | --- | --- |
| VSync on (shipping) | `Ok(())` | `1` | `1` |
| VSync off (`LIMINAL_VSYNC=off`) | `Ok(())` | `0` | `0` |

`BENCH_SUMMARY.swap_interval` is exactly what `SDL_GL_GetSwapInterval` returned
after the request — a fresh query of the platform, not an echo. So the request
is accepted and reported back. **That is the full extent of what it proves.**

## What the stack actually is

* **GLX**, not EGL. `glxinfo` reports GLX 1.4 through Mesa 25.0.7 on `Mali400`;
  `SDL_VIDEO_X11_FORCE_EGL=1` changes nothing measurable.
* Xorg with the `modesetting` driver on `/dev/dri/card0`, glamor enabled on the
  same Mali-400, one CRTC driving the 480x272 panel at 59.52 Hz.
* X extensions present: **DRI3**, DRI2, **Present**, DOUBLE-BUFFER, GLX,
  Composite, DAMAGE, SYNC, XTEST.
* GLX extensions present include `GLX_EXT_swap_control`,
  `GLX_EXT_swap_control_tear`, `GLX_MESA_swap_control`, `GLX_SGI_swap_control`,
  `GLX_SGI_video_sync` and `GLX_OML_sync_control`. Swap control is *not* being
  emulated by SDL, and the `SGI_video_sync` fallback is not in use.
* The game appears in `/sys/kernel/debug/dri/0/clients` with its own DRM magic,
  so Mesa is talking to the DRM device directly rather than going through the
  server's software paths.

### The window the server is given

`XQueryTree`/`XGetWindowAttributes` on the running game:

```
WIN 0x40000e 480x272 depth=32 override=1
```

The window is **depth 32 (ARGB)** on a screen whose default visual is
**depth 24**. This is not a Places mistake: `glxgears` gets a depth-32 window
from the same GLX visual selection, and no combination of
`SDL_VIDEO_X11_VISUALID`, `SDL_VIDEO_X11_WINDOW_VISUALID`,
`SDL_VIDEO_X11_NODIRECTCOLOR`, `SDL_GL_ALPHA_SIZE=0` or explicit
`SDL_GL_{RED,GREEN,BLUE}_SIZE=8` changes it — `glXChooseVisual` keeps returning
the ARGB config. An ARGB full-screen window on a 24-bit screen has to be
converted by the server for scanout; the server cannot hand the client's buffer
straight to the display controller.

### Who owns the flip

Sampling `/sys/kernel/debug/dri/0/state` while the game runs, the CRTC's plane
alternates between two framebuffers, **both allocated by Xorg**:

```
framebuffer[52]: allocated by = Xorg  format=XR24  480x272
framebuffer[53]: allocated by = Xorg  format=XR24  480x272
...
plane[32]: crtc=crtc-0 fb=52 / fb=53 / fb=52 / fb=53 ...
```

So the presentation path is: the client's GL frame is handed to the X server,
the server produces a complete 24-bit framebuffer, and the **kernel page-flips**
between two of the server's buffers. A DRM page flip takes effect at vertical
blank, so a presented frame is shown whole. **Tearing is structurally
impossible on this path**, whether or not the swap interval is set.

## Is it vblank-synchronised?

No. Take the running total of `loop_ms` and reduce it modulo the 16.801 ms
refresh: if presentation were locked to the panel, that phase would sit still.
It does not.

| configuration | frames | phase concentration `R` | reading |
| --- | --- | --- | --- |
| VSync off | 900 | **0.004** | uniform phase, no locking at all |
| VSync off (`vblank_mode=0`) | 900 | 0.010 | identical |
| VSync on | 900 | **0.147** | a weak association, still not locked |
| FORCE_EGL, VSync off | 900 | 0.029 | no locking |

`R` is the mean resultant length of the phase angle: 0 is a perfectly uniform
distribution, 1 is a perfect lock. A genuinely vblank-locked presentation
reports `R` near 1 and frame times at integer multiples of 16.801 ms.

Turning VSync on moves the phase from "random" to "slightly biased" and changes
the median by less than the run-to-run spread (39.39 ms on, 40.36 ms off). It
does not throttle anything.

## What the present path costs

The frame alternates between two modes with a period of two frames, and it does
so in every configuration tried:

```
frame    update   render     swap    frame     loop     <- one frame each, ms
   61      0.89     7.42    35.11    43.42    33.10
   62      2.85     8.91    16.78    28.54    44.04
   63      2.32     8.01    36.21    46.54    29.13
   64      4.77     7.77    19.88    32.42    47.12
```

(`loop_ms` of frame *N* is the begin-to-begin interval that *ends* at frame *N*,
so it pairs with the previous frame's `frame_ms`.)

`swap_ms` alternates between roughly one and two frames' worth of GPU work while
`update_ms` and `render_ms` take up the slack. That is the signature of a
pipeline that cannot overlap the client's rendering with the presentation: each
`SDL_GL_SwapWindow` absorbs whatever the GPU had left to finish, and the CPU
stalls land wherever the next GL call happens to be.

Two independent measurements bound the cost:

* **Present alone.** `LIMINAL_BENCH_NORENDER=1` submits no scene and no UI at
  all and simply swaps as fast as it can: 4.0 ms per frame (~250 presents/s).
  Even then the GPU is **93 % busy** (median of 403 samples) — about **3.7 ms of
  Mali-400 time per present** with nothing being rendered.
* **Whole frame.** `LIMINAL_BENCH_NOSWAP=1 LIMINAL_BENCH_FINISH=1` measures the
  renderer's serialised CPU + GPU work with no present at all: **32.8 ms** at the
  office viewpoint. The presented median is **39.1-40.4 ms**. The difference —
  about **6 ms** — is what the present path adds on top of the frame.

With the GPU this busy presenting, an explicit vblank wait would be the wrong
trade outright: at a 39 ms frame a correct `glXWaitVideoSyncSGI` against a
16.801 ms refresh would round up to the *third* refresh, 50.4 ms, and cost
11 ms per frame. **Do not add one.**

## What the shipping build does

* The swap interval is still requested (VSync on stays the fresh-install
  default). It is honest to request it, it costs nothing measurable, and the
  presented image is tear-free either way because of the page flip.
* The game does **not** claim to be vblank-synchronised, and nothing depends on
  the swap interval blocking. `docs/POCKETCHIP.md` states the limitation.
* No compositor, no Mesa replacement, no kernel change, and no Xorg
  configuration change was made or is needed.

## What is not claimed

* Tearing was **not** visually observed, because the panel cannot be captured
  over SSH and the PocketCHIP has no video output. The claim that presentation
  is tear-free rests on the structural evidence above — the kernel flips
  complete server framebuffers at vertical blank — not on a photographed
  moving-edge test.
* The exact share of the ~6 ms that is the ARGB-to-RGB conversion, the server's
  damage handling, and the lost CPU/GPU overlap was **not** separated. The
  depth-32 window and the present-only GPU cost are both measured; their causal
  link is a strong inference, not a controlled experiment, because GLX will not
  give this stack a depth-24 window to compare against.

## Reproducing it

```sh
# cadence shape, phase lock and fast/slow split for one configuration
python3 tools/bench/present_probe.py base
python3 tools/bench/present_probe.py vsync_on LIMINAL_VSYNC=on

# present-only cost: frames, and the GPU busy fraction while they are presented
~/bin/probe.sh norender ./places "2,5.6,74" 200 LIMINAL_BENCH_NORENDER=1
~/bin/gpuwatch.sh 15        # run while the above is running

# window geometry and depth
~/bin/visual_probe.sh ./places
```
