# Carousel-Rust

**0.1.0** · `io.vitrallis.carouselrust` · native Rust · PocketCHIP ARMv7.
[Release notes](CHANGELOG.md).

A Rust implementation of Media Carousel's native screens, playlist, settings,
image/GIF decoding, storage, and authenticated LAN management service. The
responsive browser assets retain the Python app's routes and controls. Browser
JavaScript remains browser JavaScript; no Python process runs this app. SDL2
provides the platform window/GPU API. System FFmpeg supplies WebM decoding,
exactly as it does for the Python app.

Catalog installation requires the Shell native Rust runtime described below. PocketCHIP GPU
playback, physical moving-bar observation, keyboard controls and shared Python/Rust
storage passed isolated device checks. App Center lifecycle coverage, physical touch and
comparable performance are distinguished in the verification report below. No language
performance advantage is claimed from these functional checks.

## Target and runtime

The native manifest uses `runtime = "rust"` and a closed `[binaries]` mapping.
The accompanying Shell native runtime changes are required. The ARMv7 payload
is built for EABI5 hard float, GNU libc **2.36+**, and dynamically links the
PocketCHIP's SDL2 library. No Rust compiler, Cargo, Python, Pillow, or Tk runtime
is needed to launch it. System prerequisites are SDL2 with X11/EGL/GLES2 and a
working Mali/Lima driver. WebM additionally requires `ffmpeg` and `ffprobe` on
PATH, with VP8/VP9 and optionally AV1.

Native application code and raster/GIF decoders are Rust. SDL2, graphics drivers,
and FFmpeg are native platform dependencies. Media decoding is CPU work; only
texture scaling, compositing, and presentation are GPU accelerated. This boundary
matters when interpreting a Rust-versus-Python benchmark.

The renderer tries all advertised accelerated VSync SDL backends, checks the
returned flags and actual GL renderer, and rejects software/unknown renderers.
Frames are composed in a backbuffer and presented once; paused/still screens only
redraw on changes or exposure. The supported PocketCHIP X11 session also needs
the platform's verified VSync compositor. Startup rejects an X11 session without
a compositor selection owner. Accepted SDL flags alone cannot prove
physical scanout is synchronized. See the [rendering contract](../../docs/rendering.md).
There is no automatic unsynchronized fallback. A clearly logged `--software-dev`
mode is available for development, bounded to 30 presentations/second; it offers
no hardware or tearing guarantee.

## Shared photo pile

Both implementations deliberately use **`io.vitrallis.mediacarousel`** for storage,
while their installed app IDs remain separate:

| Data | Default location |
| --- | --- |
| Settings | `~/.config/io.vitrallis.mediacarousel/settings.json` |
| Library | `~/.local/share/io.vitrallis.mediacarousel/library.json` |
| Media | `~/.local/share/io.vitrallis.mediacarousel/media/` |
| Upload staging | `~/.local/share/io.vitrallis.mediacarousel/uploads/` |
| Exclusive lock | `~/.local/share/io.vitrallis.mediacarousel/instance.lock` |
| Cache root | `~/.cache/io.vitrallis.mediacarousel/` |

The same `XDG_CONFIG_HOME`, `XDG_DATA_HOME`, and `XDG_CACHE_HOME` overrides apply.
Close one carousel before launching the other. Rust uses the same POSIX flock
as Python, so concurrent native writers are refused. Photos are neither copied
nor migrated. A Python-created library and settings document can be edited in Rust
and reopened in Python. Keep both apps under the same device user and XDG roots.

Configured paths must be absolute, have no traversal/symlink components, and stay
outside the installed package. App directories must belong to the user and have
0700 permissions. Files must be owned regular files, with one link and bounded
size. Invalid library metadata stops startup without replacing it. Invalid
settings values use defaults with a warning until an explicit save; unsafe files
require local repair. Writes use staged fsync, atomic rename, and directory fsync.
A post-rename sync failure preserves committed memory state with a warning.
Logical deletions commit before blob reclamation. Backup the shared directories
with both applications closed.

## Management and media

The Home screen displays the local management URL, QR code, and six hexadecimal
access characters. Port 8765 is preferred; a free port is chosen if occupied.
Open the literal private IPv4 address on a trusted LAN and enter the current code.
Codes change each launch. HTTP is unencrypted; do not forward the port publicly.
Every API request requires bearer authorization. The service checks private peers,
literal-IP Host, Origin, framing, timeouts, and authentication rate limits.

The browser supports collection creation/rename/deletion, two concurrent uploads,
saved reordering, settings, first-frame thumbnails, and ZIP collection downloads.
The bundled UI retains per-file progress, confirmation dialogs and a 100-file batch
limit. A downloaded ZIP preserves basenames beneath unique media-ID directories.
The explicitly requested multimedia installation action uses only the existing
root-owned no-argument platform helper; startup never installs dependencies.

| Format | Behavior |
| --- | --- |
| PNG/JPEG/static WebP | Detect actual bytes, EXIF orientation, proportional GPU fit and transparency over black. |
| GIF | Rust compositing/disposal, 20 ms–10 s frame delays (100 ms for absent/zero), complete replay counts, bounded 8 MiB cache. |
| WebM | Muted VP8/VP9/AV1 where system FFmpeg supports the codec, 20 fps RGBA, proportional scale/letterbox, one decoder/filter thread. |

Animated PNG/WebP and other formats are rejected. WebM requires EBML WebM DocType,
positive bounded dimensions/duration, supported codec and a decodable first frame.
Unsupported/corrupt/deleted items are skipped with a visible explanation. Playback
uses a stable library/settings snapshot; edits apply on the next start. Animation
uses absolute media deadlines and skips expired frames, preserving pause time.

Limits match Python: 64 MiB/file; 100 collections; 2,000 items; 2 MiB metadata;
64 KiB JSON bodies; 4 KiB settings; 8 million still pixels; 1 million GIF pixels,
1,000 GIF frames and 256 million aggregate GIF pixels; WebM up to 4096×2160 and
30 minutes; output capped at 1280×720; 256 MiB collection download. Four HTTP
workers and two upload slots bound concurrency; one validation/preview decoder
runs at a time. Raster validation and playback use isolated copies of the Rust
executable with bounded output, memory (256 MiB on Linux), validation CPU/time,
and cancellable process groups. Playback streams through two queued frames.

## Keyboard and touch controls

The native UI uses 480×272 logical pixels and scales to other window sizes.

- Home: Up/Down select collections, Left/Right page, Enter/Space play; Tab and
  Shift+Tab focus collections, Settings and Exit. `S` opens Settings, `F1`/`H`
  discovers the key map; `Q` or Escape exits.
- Playback: Left previous/restart first item, Right next, Space pause/resume.
  Tab reveals/focuses Previous/Pause/Next/Back, Enter activates. Click/tap media
  reveals the controls; controls remain visible while paused.
- Settings: Tab/Shift+Tab or Up/Down select duration, repeat count, order, ending,
  Save or Back; Left/Right edit. Shift changes still duration by 60 seconds.
  Enter/Space activates Save/Back. Touch the left/right half of a setting to
  decrease/increase it.
- Escape/Backspace returns Home and discards unsaved settings. Help also closes
  with Enter. Touch/click activates the visible buttons.
- SIGTERM/SIGINT/SIGHUP shut down playback, decoder children and HTTP transfers.
  An explicitly started system package operation must finish without killing dpkg.

## Build and validate

Use Rust 1.89+, a locked Cargo build, and host SDL2 development files. The narrowly
selected crates cover codecs, SDL bindings, typed JSON, Unicode validation,
randomness, QR/font rendering, signals and stored ZIP writing; no web framework,
async executor or additional on-device runtime is required. Cargo output must stay
outside the app package.

```sh
cd apps/carousel-rust
export CARGO_TARGET_DIR=/absolute/external/carousel-target
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings -D clippy::all -D clippy::pedantic -D clippy::nursery -D clippy::cargo
cargo test --workspace --all-features
```

Cross-build with an image-matched SDL2 sysroot, `cargo-zigbuild` and Zig:

```sh
PKG_CONFIG_LIBDIR=/absolute/arm-sysroot/lib/pkgconfig \
PKG_CONFIG_ALLOW_CROSS=1 PKG_CONFIG_PATH= \
CARGO_TARGET_DIR=/absolute/external/carousel-arm \
cargo zigbuild --locked --release --target armv7-unknown-linux-gnueabihf.2.36
```

Stage using `tools/build_rust_app.py` from the repository root with the matching
sysroot/linker environment. Every declared target needs a matching ELF. The staged
binary belongs at `bin/armv7-unknown-linux-gnueabihf/app` with executable mode;
validate the complete package and keep source commits before catalog pins.

For isolated development, set all three XDG bases to private temporary directories.
Run the compiled executable from any working directory. `--smoke-seconds N`
bounds a graphical run, `--play-first` starts the first collection, and
`--screenshot /absolute/new.png` captures the completed backbuffer without
replacing a file. Exit logs `event=carousel_metrics` with elapsed time, presented,
decoded and skipped frames; it never logs the access code or media names.

For fair device comparison use the same library, ordering, duration/replays,
480×272 display, compositor, brightness, power/thermal state and codec versions.
Measure startup, CPU, resident memory, decoded/presented/skipped frames and
physical tearing separately. Repeat in alternating Python/Rust order, recording
cold and warm filesystem-cache runs. WebM measures substantial shared FFmpeg work,
so report it separately from still/GIF and native UI workloads. Do not count the
Python app's CPU without its child decoder processes, or compare software versus
hardware renderers as a language result.

## Verification status

Host, Linux and ARM build/test results, device screenshots and the owner’s clean
physical playback observation are recorded in the repository’s
[verification report](../../docs/verification/carousel-rust-2026-09-19/README.md).
The report distinguishes completed checks from remaining validation and controlled
Python/Rust benchmarks. Native installation needs a Shell version that recognizes
`runtime = "rust"`; older Python-only launchers cannot run this package. Source
commits and the pinned ARM payload remain available for review and isolated testing.
