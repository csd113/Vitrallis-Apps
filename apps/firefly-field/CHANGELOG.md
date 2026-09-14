# Changelog

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
