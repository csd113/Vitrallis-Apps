# Changelog

## 0.1.1 — 2026-10-03

- Treat an empty Linux process command line during exec as startup, preventing pause before parent-death cleanup is armed.
- Allow up to twenty seconds for cancellable ARMv7 metadata and artwork probes so slow FFmpeg startup does not incorrectly label valid tracks corrupt.
- Defer a startup pause until the Linux child has armed parent-death cleanup, including paused seek and volume restarts.
- Read Vorbis title, artist and album tags from audio streams while preserving container metadata precedence.

## 0.1.0 — 2026-10-02

- A compact local music player with keyboard controls, metadata and album artwork.
- Keep documents in the launcher Documents directory and preferences in app-private AppData configuration.
- Support read-only installed payloads and clean signal-driven exit without hardware certification.
