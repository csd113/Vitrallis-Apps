# Changelog

Changes are listed newest first. Dates use America/Vancouver time.

## 0.3.0 — 2026-09-20

- Include the project MIT license in the installed package.

- Play animated WebP frame by frame with per-frame durations, transparency and loop
  metadata through the existing animation pipeline; static WebP and GIF keep their
  current behavior.
- Cache prepared GIF and animated-WebP frames in the bounded rolling window, reuse
  decoded still images across slideshow cycles, and release both caches on
  navigation, hidden playback and exit.
- Convert an existing GIF to animated WebP on the device from the playback overlay
  (To WebP or the `C` key) or the web page's per-item button, preferring system
  `gif2webp` with a bounded Pillow fallback.
- Convert through a staged temporary file, verify the result's frame count,
  durations, looping and openability, then atomically replace the GIF at the same
  playlist position; delete the original only after validation and keep it
  byte-for-byte on every failure.
- Show conversion progress and results in the playback overlay and web page, and add
  a shared "GIF uploads" setting that converts newly uploaded GIFs automatically.
- Stream folder downloads in 64 KiB chunks with no temporary archive and no in-RAM
  buffer and raise the explicit limit from 256 MiB to 4 GiB, refreshing the transfer
  deadline during long transfers and checking free space before staging uploads.
- Stop decoding and presenting when the native window is hidden, floor idle playback
  polling, keep overlay focus and redraw work off the hot path, and refresh
  discovered LAN addresses every sixty seconds instead of ten.
- Downscale display copies with bilinear filtering, keep rejecting animated PNG
  uploads explicitly, normalize legacy library and settings files, and reclaim
  abandoned conversion staging at startup.

## 0.2.1 — 2026-09-19

- Prepare a rolling window of up to 10 GIFs before playback, sharing complete frames across first plays and repeats within a 32 MiB total and 8 MiB per-GIF cache.
- Prioritize the current GIF, evict finished items, cancel obsolete preparation on navigation/exit, and stream animations that exceed the cache budget.

## 0.2.0 — 2026-09-19

- Request EGL backbuffer VSync and retain media deadlines; cache prepared GIF bytes off the UI thread.
- Add two concurrent streamed uploads, bounded thumbnail caching and authenticated folder archive downloads.
- Display a current-address QR code and verify real WebM/WebP decoding before offering scoped multimedia installation.

## 0.1.4 — 2026-09-14

- Present GIF frames through optional hardware EGL/GLES2 textures on X11, moving proportional scaling and display composition off Tk/Pillow.
- Preserve CPU decoding and Tk fallback when a compatible GPU surface is unavailable or lost; reject software GL rasterizers as hardware.
- Advance animation deadlines without accumulating image-upload cost, schedule near the next frame deadline and skip expired frames when late.
- Reuse composited GIF frames within an eight-MiB cache across repeats while preserving disposal, frame durations, bounded queues and cancellation.

## 0.1.3 — 2026-09-13

- Shorten the per-launch LAN access code from sixteen to six hexadecimal
  characters and align the browser login field and instructions.

## 0.1.2 — 2026-09-12

- Add a versioned package changelog and link it from the README; media playback,
  LAN management and runtime requirements are unchanged.

## 0.1.1 — 2026-09-12

- Publish X11 process identity for Vitrallis Shell window focus and resume.
- Enable App Center installation from the consolidated main catalog and document
  the Python, Tk, Pillow, packaging and optional FFmpeg prerequisites.

## 0.1.0 — 2026-09-12

- Add native image, GIF and muted WebM slideshows with LAN uploads, named
  collections, saved play order and shared settings.
- Bound uploads, decoder resources and subprocess lifetimes; validate media and
  storage paths and preserve responsive keyboard/touch controls.
- Publish initially on the development branch with installation disabled pending
  the default-branch catalog integration.
