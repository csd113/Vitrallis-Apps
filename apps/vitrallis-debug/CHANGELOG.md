# Changelog

Changes are listed newest first. Dates use America/Vancouver time.

## 0.2.1 — 2026-09-14

- Discover Lima/Mali GPU identities and aliases through GPU devfreq class devices.
- Read Linux devfreq_monitor load events from an isolated tracefs instance when permitted and display a two-second polling-weighted rolling average.
- Reject stale, malformed and unrelated-device events; show unavailable when trace access or fresh load samples are missing.
- Release owned trace resources on normal exit, startup failure and handled termination without changing global trace settings.

## 0.2.0 — 2026-09-12

- Replace the background Canvas pulse with an eight-second foreground EGL/GLES2
  animation, capped below 30 FPS; reject software renderers and hidden windows.
- Add GPU utilization graphs with source labels and explicit unavailable readings.
- Polish small-screen card layout, measured text, scrolling and keyboard controls.
- Detect Linux CPU/GPU names, board and SoC identity, bound graphics drivers,
  exported module versions, kernel release and CPU frequency drivers on launch.
- Support Raspberry Pi VC4/V3D and Allwinner Mali device bindings, including lima
  and legacy Mali; hardware identity remains visible without utilization counters.
- Keep GPU Pulse optional with system X11/EGL/GLES2 prerequisites and no new pip
  dependencies; physical Raspberry Pi and PocketCHIP performance is unverified.

## 0.1.2 — 2026-09-12

- Add a versioned package changelog and link it from the README; diagnostics and
  runtime behavior are unchanged.

## 0.1.1 — 2026-09-12

- Publish the X11 client hostname so Tk exposes the process ID used by Vitrallis
  Shell to focus and resume the native diagnostics window.

## 0.1.0 — 2026-09-12

- Add the native offline diagnostics app with network, CPU, temperature and
  memory panels, keyboard/touch navigation, and a demo mode.
- Publish the manifest v1 package and enable installation through App Center.
