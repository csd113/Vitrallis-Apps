# Graphical app presentation requirement

Every graphical Vitrallis app must compose a complete frame in a backbuffer or
an off-screen surface, present it once, and synchronize completed-frame presentation
to VSync/vblank when supported. Drawing directly into a visible/front buffer and
uncontrolled repeated swaps are not acceptable. Keep simulation/media time separate
from presentation time. Static or paused views redraw only for a change or exposure.

For EGL window surfaces, request `EGL_RENDER_BUFFER = EGL_BACK_BUFFER`, verify the
configuration permits a swap interval of at least one, request `eglSwapInterval(1)`,
and use one `eglSwapBuffers` for each completed frame. Preserve absolute animation
deadlines across swaps; adding swap time to each GIF delay makes playback too slow.
See the [EGL specification](https://registry.khronos.org/EGL/specs/eglspec.1.4.pdf).

For SDL2, compose the entire frame with its renderer and call `SDL_RenderPresent`
once. Try all suitable accelerated backends with `SDL_RENDERER_PRESENTVSYNC` before
considering an unsynchronized renderer. Check returned flags and the real renderer;
a software rasterizer must not be described as Mali hardware acceleration.

If synchronization is unavailable or cannot be confirmed, retain buffering, expose
that limitation, and bound unsynchronized animation presentation to at most 30 FPS.
This fallback limits resource usage; it is not a tearing fix. An arbitrary sleep
cannot substitute for a working backend VSync/vblank path. Media timing must remain
correct, with expired frames skipped where necessary instead of slowing animation.

Tk control screens use toolkit off-screen redraws and event-driven updates. Tk does
not expose a portable per-window VSync request. On the supported X11 device the
platform compositor must provide synchronized completed-window presentation; without
that verified compositor, Tk fallback has no tear-free guarantee. Prefer an EGL or
SDL presentation surface for continuous animation, as Debug Pulse, Firefly and
Carousel do. The static hello example is a bounded toolkit fallback, not proof of
hardware synchronization. Do not advertise a toolkit/backend combination as
compliant until its buffering and display presentation path are verified.

Tests should cover swap selection, one presentation per completed frame, bounded
fallback scheduling and paused/static behavior. Validate real display refresh,
tearing, frame pacing and overhead on PocketCHIP; mocks and desktop screenshots
cannot establish tear-free physical scanout. Record kernel, driver, compositor,
backend and any fallback in device evidence.

The [2026-09-19 PocketCHIP verification](verification/platform-app-refinements-2026-09-19/README.md)
records a failed direct-child EGL test followed by a successful compositor-backed
physical test. PocketCHIP setup therefore supplies a minimal XRender/VSync
compositor when no existing compositor owns the display; app swaps alone do not
establish this requirement on the stock X11 session.
