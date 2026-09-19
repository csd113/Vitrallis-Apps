# Carousel-Rust verification — 2026-09-19

Before publication, Carousel-Rust 0.1.0 was built and exercised from the working branch
`rust-app-demo`. At the time of these device checks, no source commit, catalog
pin, installed app receipt or catalog release had been created. These results identify the tested executable by its bytes,
not by a fictitious source revision.

## Artifact and physical device

The ARMv7 EABI5 hard-float executable is 1,381,964 bytes with SHA-256:

```
b8a135e6c56c20b0f1902cd193c785fc485049374beb7f85d9ab2e29ca4ac3a0
```

The same bytes were staged and executed as the normal `chip` user from `/`, on
PocketCHIP, Debian 13.7, kernel `6.12.107+deb13-chip`, SDL 2.32.4, 480×272.
The binary has a GNU libc 2.36 baseline. Dynamic dependencies resolved on-device.
The app reported SDL `opengl`, GL renderer `Mali400`, acceleration enabled and
VSync requested. The X11 compositor selection-owner check passed. No compositor,
package, device configuration or driver was installed or changed by this test.

The physical moving-bar GIF observation **passed**. Asked specifically about
horizontal tearing, flicker or broken playback, the owner replied:
**“Looks clean and plays correctly.”** This observation applies to this
Carousel-Rust fixture on this device/session. It does not certify other Shell
transitions, every media workload or other driver configurations. Runtime flags
continue to report `physical_scanout=unverified`, because software cannot infer
the owner's physical observation from an accepted VSync request.

The temporary library contained PNG, JPEG, still WebP, a 12-frame GIF with a
moving white bar and 50 ms frame delays, and a VP8 WebM. Settings used one-second
stills, three animation/video repeats, ordered looping playback. The bounded
90-second run reported 448 presentations, 435 decoded frames and 207 skipped
frames. These counters include startup and mixed media; they are not a frame-rate
or Rust-versus-Python performance result. Skipped frames are counted when absolute
media deadlines have passed, rather than extending media duration to hide delay.

A separate short process-tree sample recorded approximately 52.6% CPU of one
core and 69,880 KiB peak aggregate resident memory. This was an exploratory sample
with process startup and interactive validation, not a controlled benchmark.
Summed RSS double-counts shared pages; sampling can miss short-lived children.
No language-performance conclusion is supported by this sample.

## Shared storage and keyboard controls

The original Python carousel modules opened the fixture after Rust playback and
read the same five media records and settings. Python saved a two-second duration;
a new native Rust run displayed that value, changed it to three seconds and saved.
Python then read the Rust-written value and the same five records successfully.
The shared POSIX instance lock was available after exit. This exercises the actual
Python and Rust implementations against the same paths, without a migration.

A fresh 14-second native run checked its live PID and X11 input focus before every
key. Settings edit/save, playback, pause, next/previous, return home and
keyboard exit passed. Screenshots were inspected. An earlier attempt outlived its
smoke deadline and captured Shell; those captures are excluded from passing
evidence. The final run exited normally and the original Shell was restored. A separate
Help check using H displayed the expected controls page and exited normally.
Injected F1 did not display that page; the PocketCHIP function-key layer was not
validated by that injection, and no F1 device pass is claimed.

## Automated validation

Commands ran with Cargo targets outside installed package directories.

```sh
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings -D clippy::all -D clippy::pedantic -D clippy::nursery -D clippy::cargo
cargo test --workspace --all-features
CAROUSEL_RUST_TEST_BINARY=/path/to/host/carousel-rust cargo test --workspace --all-features -- --include-ignored
python3 -m unittest discover -s tools/tests -v
CAROUSEL_RUST_TEST_BINARY=/path/to/host/carousel-rust python3 -m unittest discover -s apps/carousel-rust/tests -v
python3 tools/validate_catalog.py
python3 tools/validate_changelogs.py
```

- Formatting and strict Clippy passed; Clippy also passed for the ARMv7 target.
- Rust tests: 15 passed and one explicitly opt-in real HTTP test skipped in the
  ordinary invocation; rerunning with the executable and `--include-ignored`
  passed all 16, on both macOS and Linux.
- Native package/codec Python tests: all seven passed on the host. They include
  real Rust subprocess decoding against Pillow results and FFmpeg WebM fixtures.
- On the PocketCHIP itself, all four real codec tests passed in 39.57 seconds:
  PNG/JPEG/WebP identification and JPEG orientation; GIF disposal, transparency,
  timing and full replay; animated PNG/WebP, corruption and oversized-image
  rejection; actual VP8 and VP9 WebM inspection and repeated decoding.
- Catalog tooling: all 67 tests passed, including native manifest/schema, ELF
  checks, staged-source building and disposable-repository catalog publication.
- All existing app/example Python suites completed: 236 passed, three skipped.
  The skips are two opt-in GPU integration cases and one Linux-specific FIFO
  case unavailable in that host configuration. No skip is counted as a pass.
- Package checks passed for the new native package and all existing app/example
  packages. The existing catalog verified all four published entries and pinned
  bytes; the committed-history changelog-policy check passed. These historical
  checks do not certify the uncommitted new app as a published catalog release.
- `cargo audit` reported no known dependency advisories or warnings.
- A three-second Linux Xvfb software-development smoke passed with the explicit
  30 FPS cap. This is not GPU evidence. A host Metal accelerated/VSync smoke also
  passed; the physical PocketCHIP evidence above supplies the target GPU check.

## Isolation and release limits

All device files are confined to
`~/.local/share/vitrallis-validation/carousel-rust-20260919/`.
The app's HOME was a private fixture directory below it, exercising the normal
`io.vitrallis.mediacarousel` storage suffix without touching the owner's photos.
The original Shell process was preserved and restored to focus. Final checks
found only its window, no running QA executable and no listener on port 8765.
The temporary Linux validation container was stopped; fixture files and logs are
retained for review. The unrelated Shell task's isolated
fixture installation/update/uninstall tests establish its native runtime contract;
they do not establish this unpublished Carousel package's App Center lifecycle.

Catalog publication retains the source commits and uses generated pins and root
release history. Installation stays disabled until this exact package is exercised
through the updated App Center installation/update/repair/uninstall flow. Touch interaction also needs
physical coverage. A quantitative language comparison requires repeated alternating
Python/Rust runs with the same media, settings, compositor, power/thermal state and
codec versions, with WebM/FFmpeg work reported separately.
