# Changelog

## 0.3.0 — 2026-09-19

- Cache menu glyph textures and batch ordered glow/body/grass sprites while preserving particle count and controls.
- Use backend VSync first, bound unsynchronized rendering and wait for native events while paused.

## 0.2.1 — 2026-09-14

- Ship a painted pixel-art meadow and prebuilt RGBA scene, firefly, glow and grass textures; remove startup pixel generation.
- Reject known software OpenGL rasterizers like the current Shell and log the active GL renderer identity.
- Cap rendering at 60 FPS, retain depth order between population changes and batch bitmap text draws.
- Restore touch-generated mouse input, clear stale pointer influence and ignore repeated toggle key events.
- Show complete help at startup, add keyboard scatter and complete missing bitmap glyphs.
- Exclude guest CPU time from duplicate accounting and label unassociated device utilization as DRM rather than app GPU load.
- Publish the package as installable after its source, catalog inventory and app checks complete.

## 0.2.0 — 2026-09-13

- Add an opt-in performance overlay with local CPU utilization and real DRM GPU
  busy readings where the driver exposes them, reporting unavailable otherwise.
- Add single-firefly A/D controls bounded to the 30–260 population range while
  retaining the Up/Down ten-firefly shortcuts.
- Add keyboard-selectable Night, Mist and Moss color moods plus three wind
  strengths, with current values displayed in the status overlay.

## 0.1.1 — 2026-09-13

- Make the complete ambient experience keyboard-operable and expose every key
  binding in the optional status overlay, including a normal Escape exit.
- Add keyboard regression coverage for pause, reseed, overlay, population, glow
  and exit controls without requiring a graphical SDL session.
- Polish atmospheric depth with softly twinkling stars, a brief streaked shooting
  star, and a translucent status panel that clearly reports paused state.

## 0.1.0 — 2026-09-13

- Add the offline Firefly Field ambient app with original pixel-art night scene,
  textured fireflies, independently timed blinking and depth-aware movement.
- Request SDL2's accelerated vsynced renderer and render reusable textures with
  alpha/additive blending, while retaining an SDL renderer fallback.
- Follow Vitrallis Shell's GPU renderer selection: advertise-driver discovery,
  GLES2 preference, verified renderer flags, fresh-window retries, diagnostics
  and explicit `auto`, `hardware` and `software` modes.
- Add keyboard, pointer and touch-friendly field controls, package documentation
  and simulation tests that do not require a graphical display.
