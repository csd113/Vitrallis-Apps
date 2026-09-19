# Changelog

Changes are listed newest first. Dates use America/Vancouver time.

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
