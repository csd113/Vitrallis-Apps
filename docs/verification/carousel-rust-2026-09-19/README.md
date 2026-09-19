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
the later real-package lifecycle checks below establish Carousel coverage.

Catalog publication retains the source commits and uses generated pins and root
release history. Installation is enabled as requested, with native Shell
0.1.0-beta3.1 or newer required. The later publication checks below supplement
the initial source-run evidence. Touch interaction also needs
physical coverage. A quantitative language comparison requires repeated alternating
Python/Rust runs with the same media, settings, compositor, power/thermal state and
codec versions, with WebM/FFmpeg work reported separately.

## Publication validation and 0.1.1

GitHub Ubuntu 24.04 x86-64 exposed an FFprobe startup failure before decoding:
`libicudata.so.74: failed to map segment from shared object`. A bounded subprocess
reproduction failed at 256 MiB and succeeded at 384 and 512 MiB. Version 0.1.1
therefore permits 512 MiB of address space on 64-bit Linux development hosts;
the PocketCHIP/32-bit Linux limit remains 256 MiB. This is a virtual-address
mapping allowance, not a change to image allocation, dimensions, frame counts,
HTTP input limits or the device performance workload. All 16 Rust tests, seven
host package/codec tests, formatting and strict host/ARM Clippy passed again.

Version 0.1.1 source is pinned to
`a7e7b5b39aa052c94ead80a7b89e6a4592bf5620`; the ARM ELF SHA-256 is
`9b31520240dbeb58667a4cd44eeda549a869218f2d1d4f2a6775c896e7415504`.
Both source commits remain reachable. The root catalog record describes the
final initial main-branch release, 0.1.1; app-local history retains 0.1.0.

Actual App Center installation fetched all 28 published files from GitHub over
its normal HTTPS transport and verified their size/hash inventory. The pre-merge
catalog was fetched by immutable commit and placed in a separate QA HOME's
catalog cache, because normal discovery still followed main before merge.
A temporary loopback SSH CONNECT tunnel provided the USB-only device access to
only api.github.com and raw.githubusercontent.com. It did not change TLS trust,
device DNS, routing or production download/installer code.

Version 0.1.0 installed and opened from the real App Center action, executing the
installed native ELF. Keyboard exit and child reaping passed. Removing only
the QA installation's executable triggered Repair; the real repair action
re-downloaded and restored the exact file. A shared-data sentinel survived.

The exact released Shell 0.1.0-beta3.1 ARM binary then performed the real
0.1.0 → 0.1.1 update. All 28 resulting file hashes matched the new pinned
inventory, and shared data survived. The updated app opened as a fresh process
from the installed path and exited normally. All four actual codec tests passed
again against that installed 0.1.1 executable (38.05 seconds). The uninstall
confirmation defaulted to Cancel and retained the package; confirming Uninstall
removed its files and launcher while preserving shared user data.

All managed-package tests used `manager-home/` under the same private QA root.
The test Shell stopped, original Shell PID3419 was restored, and no test app
window or port8765 listener remained. No app was installed into the owner's
normal profile. Screenshots containing temporary access codes were excluded.

An existing Python carousel test exposed a separate response/cleanup race in CI:
a successful HTTP response can arrive before the worker releases its upload slot.
The test now waits up to two seconds for that release before occupying the slot
to test saturation. Production Python files are unchanged. Twenty repeated
regression runs passed, followed by all 91 Python carousel tests (one documented
opt-in EGL skip on the host). No app version change is needed for this test-only
correction. Required GitHub checks are attached to the publication pull request.
