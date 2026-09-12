# PocketCHIP display acceleration verification

Verified on 2026-09-12 against Vitrallis Media Carousel 0.1.0.

**Confirmed: Media Carousel's X11 display rendering uses the hardware Mali-400 GPU
through Lima and Xorg glamor.** Image/video decoding, resizing and RGB frame
preparation remain on the CPU. The app does not implement direct OpenGL playback
or hardware video decoding.

The check used the published Media Carousel source
`331a9612895e0fb725564c116cae291ef22fa537` in an isolated temporary source-run session
on the authorized PocketCHIP. No app code, Shell code, graphics configuration or
system packages were changed.

The running X server's `/var/log/Xorg.0.log` reports:

```text
modeset(0): glamor X acceleration enabled on Mali400
modeset(0): glamor initialized
```

`DISPLAY=:0 glxinfo -B` reports:

```text
direct rendering: Yes
Device: Mali400 (0xffffffff)
Accelerated: yes
OpenGL renderer string: Mali400
OpenGL version string: 2.1 Mesa 25.0.7-2+deb13u1
OpenGL ES profile version string: OpenGL ES 2.0 Mesa 25.0.7-2+deb13u1
```

`xrandr --current` reports the active 480×272 mode at 59.52 Hz. This is the panel's
refresh rate, not the application's video frame rate. `/dev/dri/card1` and
`renderD128` are bound to the `lima` driver; display scanout uses `sun4i-drm` on
`card0`. The device tree identifies the GPU as `arm,mali-400` and names its
interrupts `gp gpmmu pp0 ppmmu0 pmu`.

The actual native Carousel app displayed the generated 480×272 WebM sample while
a temporary helper sampled kernel GPU interrupts and power accounting:

| Phase | Duration | Geometry (`gp`) interrupts | Pixel (`pp0`) interrupts | GPU active time |
| --- | ---: | ---: | ---: | ---: |
| App home, idle | 6.011 s | 10 | 9 | 2.200 s |
| WebM playing | 12.005 s | 341 | 239 | 9.188 s |
| WebM paused | 6.008 s | 9 | 9 | 2.142 s |

GPU activity rose substantially during playback and returned near the background
level when paused. There were no GPU MMU fault interrupts during these intervals,
no playback error, and no displayed frame changes while paused. Together with the
active renderer and Xorg log, this verifies hardware-assisted X11 rendering during
Carousel playback; it does not mean every frame-processing operation runs on the GPU.

The helper observed 53 displayed frame changes over the 12-second playback window
(about 4.4 per second for this sample and test setup). That is an observation of
frame changes, not a general benchmark. Hardware display acceleration therefore
does not establish smooth 20 fps playback. Pillow decoding/scaling, software FFmpeg
decoding/scaling and Tk image transfer can still limit performance.

The code path is FFmpeg software decoding/filtering → raw RGB frames →
`ImageTk.PhotoImage` → Tk canvas → Xorg glamor/Lima → display controller. Source
inspection found no hardware decoder selection or hardware scaling filter.

The app shut down cleanly and returned to the existing Shell. Temporary source,
test media and the verification helper were removed; no verification or FFmpeg
process remained. The verification made no runtime changes; this report and its
measurements record the findings.

[Raw measurements](vitrallis-media-carousel-gpu.json).

The [Xorg modesetting manual](https://manpages.debian.org/trixie/xserver-xorg-core/modesetting.4.en.html)
documents glamor acceleration through OpenGL/OpenGL ES. The
[Mesa Lima documentation](https://docs.mesa3d.org/drivers/lima.html) documents
Mali-400 support and the separate rendering and display-controller roles.
