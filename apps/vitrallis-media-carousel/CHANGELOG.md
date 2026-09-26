# Changelog

Changes are listed newest first. Dates use America/Vancouver time.

## 0.4.1 — 2026-09-25

- Fix a corrupt or missing upcoming animation being re-decoded in a tight loop:
  the prefetch worker now records it as unfittable after one attempt instead of
  pinning a CPU core while a still image is on screen.
- Keep the native settings screen usable at 480×272 and the supported 400×240
  minimum: Save is always visible and keyboard reachable, long captions wrap
  instead of overlapping, long status text is clamped by measured pixels, and the
  collection rows keep a 36-pixel touch-target floor.
- Present the first frame of a newly selected item immediately instead of waiting
  out the previous polling interval, and re-arm the presentation deadline on
  navigation. A still image or paused view now wakes the UI four times a second
  instead of fifty, and the playback overlay no longer hides while one of its
  buttons has focus.
- Make folder downloads work past the classic 2 GiB ZIP boundary: streamed
  archives opt into ZIP64 data descriptors and end records, the advertised size
  bound includes ZIP64 overhead, and an internal archive failure closes the
  response cleanly instead of raising a worker traceback.
- Report a zero-byte upload as an empty file instead of "request too large",
  report a shutdown-cancelled upload as "server stopping", accept JSON and upload
  Content-Type parameters, serve cache-busted asset URLs, and refuse to encode
  loopback, link-local, unspecified, multicast or reserved hosts in the QR code.
- Release services and exit cleanly when a startup or settings action failed, when
  an HTTP worker outlives its bounded join, or when a Pillow conversion is still
  encoding: conversion workers are daemon threads, abandoned staging is reclaimed
  at the next start, and the original media is never replaced.
- Make the in-playback FFmpeg backend probe cancellable on navigation or shutdown,
  keep the decoder worker alive after an unexpected failure, and never signal a
  subprocess that was already reaped.
- Report unsafe leftover files in the media or upload staging directories instead
  of refusing to start, and show a friendly recovery message when the library
  metadata cannot be opened.
- Guard backward navigation on a finished or empty playlist so it cannot index
  past the last item.
- Polish the management page: state the upload limits, reject empty files before
  sending them, keep conversion disabled while uploads run, handle an expired
  session mid-batch, lock on expired thumbnail requests, and keep mobile tap
  targets at 44 pixels.
- Correct the documented WebM truncation behavior and document the GPU animation
  filtering and rapid-navigation decode tradeoffs.

## 0.4.0 — 2026-09-21

- Convert a whole collection — or the entire library — to WebP in one action:
  "Convert GIFs", "Convert images" and "Convert all supported" run as one
  background job with a bounded worker pool, live progress (found, current,
  completed, failed, skipped) and a final summary, and the page stays usable
  while it runs.
- Report items already in WebP as skipped instead of re-encoding or ignoring
  them, and add an explicit "re-convert files that are already WebP" opt-in for
  replacement. Animated WebP re-encoding no longer needs `gif2webp`, which only
  understands GIF.
- Convert still PNG/JPEG images with orientation baked in, transparency and
  dimensions verified before the original is replaced; verification reads GIF
  frame durations from frame headers instead of decoding every frame twice.
- Start the management web server as an independent background service: library,
  decoder and conversion job are ready in milliseconds, the HTTP bind, LAN
  address discovery and the FFmpeg capability probe all happen off the playback
  path, and a failed or slow server no longer delays or stops the slideshow.
  Add an explicit `starting/ready/failed/stopped` server state with a matching
  home-screen status line.
- Make the FFmpeg capability probe cancellable so shutdown never waits on a slow
  probe, and never let a probe failure propagate into playback.
- Decode video with a persistent per-item FFmpeg process instead of restarting
  it for every repeat, with a bounded reader queue and a byte-bounded
  presentation look-ahead so decoding is never blocked by the render loop.
- Pace video from the source's own frame rate instead of a fixed 20 FPS guess;
  a 25 FPS clip now presents 25 FPS (it previously showed only 20 of every 25
  frames) and each frame costs less to prepare.
- Detect hardware video decoding by decoding a sample and reading FFmpeg's own
  negotiation log, use it only when a codec really has it, fall back to software
  on any failure, and log the selected backend. On macOS VideoToolbox is
  verified for VP9 only; VP8 always reports software. Animated WebP and GIF stay
  fully CPU-decoded and are documented as such.
- Detect the child-process reaping bug where `os.killpg` reports EPERM for an
  already-exited child on macOS, which could abort a video decode at end of file.
- Stream the first animation frame immediately instead of waiting for the whole
  animation to be cached, record streamed frames for the repeats and the next
  visit, keep filtered frames and still images in byte-bounded caches, and stop
  re-decoding animations that do not fit the cache budget on every navigation.
- Reuse a single Tk photo image per media item instead of creating a Tcl image
  every frame, and keep every decoded frame as immutable display-ready bytes
  (RGBA for animation, RGB for opaque video) so no channel pass or redundant
  resize happens on the presentation path.
- Replace `sleep(frame_duration)` scheduling with deadline-based pacing on a
  monotonic clock: drop expired animation frames with a bounded catch-up, resync
  rather than drift, and back the poll off while waiting for a slow decoder.
- Polish the web interface: a sticky conversion progress panel, clearer section
  grouping and button hierarchy, per-collection and library-wide conversion
  cards, honest empty states, long-filename wrapping, responsive media rows,
  accessible focus/hover/disabled states and a visible server status.
- Keep the existing library layout, settings file, collection ordering and
  playback definitions unchanged; no migration is required.

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
