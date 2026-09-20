# Changelog

## 0.1.2 — 2026-09-19

- Prepare a rolling window of up to 10 GIFs before playback, sharing complete frames across first plays and repeats within a 32 MiB total and 8 MiB per-GIF cache.
- Prioritize the current GIF, evict finished items, cancel obsolete preparation on navigation/exit, and stream animations that exceed the cache budget.

## 0.1.1 — 2026-09-19

- Allow the shared-library address space required by 64-bit Linux FFmpeg builds while retaining the 256 MiB PocketCHIP decoder limit and existing media-allocation bounds.

## 0.1.0 — 2026-09-19

- Reimplement the media carousel in Rust with native accelerated, synchronized rendering and keyboard controls for PocketCHIP.
- Share the Python carousel's XDG library, media, settings, and exclusive process lock without migrating or duplicating photos.
- Provide Rust collection management, authenticated LAN uploads, previews, ZIP downloads, and PNG/JPEG/WebP/GIF/WebM playback.
