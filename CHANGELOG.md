# Catalog changelog

[Repository overview](README.md) · [Documentation](docs/README.md)

This is the release history for the main [apps.json](apps.json) catalog. Dates
use America/Vancouver time. App IDs remain stable; each app ships its own
`CHANGELOG.md` with detailed release notes. Keep existing release records intact
and place new records in the newest date section. See the
[changelog policy](docs/changelog-policy.md) for the required submission format.

## 2026-10-03

- Updated `io.vitrallis.music` `0.1.1`: Extend cancellable metadata probing, defer startup pause through empty Linux exec transitions until owned-child cleanup is armed, and read Vorbis stream tags.
- Updated `io.vitrallis.debug` `0.4.1`: Request network interface byte statistics so RX/TX histories receive actual counters.
- Updated `io.vitrallis.fireflyfield` `0.3.2`: Cache sprite coordinates and opacity and reduce per-frame vertex packing work.
- Updated `io.vitrallis.mediacarousel` `0.4.4`: Allow bounded slow startup, defer uncached hardware probes, and preserve decoder stall detection without counting queue backpressure.

Enable installation for all eight catalog apps following the October 3 managed
lifecycle audit and the maintainer's publication instruction. Updated compatibility
notes distinguish exact managed versions from source repairs and retain unresolved
speaker output, physical input/scanout, GPU accuracy, Firefly FPS, Carousel cold
startup and injected-fault Repair checks. The earlier release records below retain
their original publication state.

- Updated `io.vitrallis.calculator` `0.1.1`: Correct the disabled catalog gate, suppress package-local bytecode writes and handle idle Linux termination. [App changelog](apps/calculator/CHANGELOG.md).
- Added `io.vitrallis.music` `0.1.0`: Add local streaming playback, metadata/artwork, folder browsing and keyboard/touch controls. [App changelog](apps/music/CHANGELOG.md).
- Added `io.vitrallis.sketch` `0.1.0`: Add keyboard/touch drawing, bounded undo/redo and atomic PNG saves. [App changelog](apps/sketch/CHANGELOG.md).
- Updated `io.vitrallis.debug` `0.4.0`: Present System Monitor with processes, bounded resource graphs and saved diagnostics while retaining the stable app identity. [App changelog](apps/vitrallis-debug/CHANGELOG.md).

Music and Sketch remain installation-disabled pending the dedicated device pass.
Calculator's publisher gate is corrected; System Monitor retains its existing
flag. Local staged evidence does not certify physical PocketCHIP/App Center behavior.

## 2026-10-02

- Updated `io.vitrallis.liminalrust` `0.11.2`: Preserve settings, custom levels and cache in private AppData, validate storage paths and retain the matched Rust runtime notices. [App changelog](apps/places-pocketchip/CHANGELOG.md).
- Updated `io.vitrallis.bitcoindashboard` `1.3.1`: Keep settings and watch-only addresses in private persistent AppData and reject unsafe storage paths. [App changelog](apps/bitcoin-dashboard/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.4.3`: Separate saved media, uploads and settings from replaceable app files and validate storage roots before writes. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).

Existing installation flags are preserved. Physical lifecycle certification for
these new packages remains in progress.

## 2026-10-01

- Added `io.vitrallis.calculator` `0.1.0`: Add a keyboard-first decimal calculator with precedence, parentheses, percent, bounded input and optimized artwork. [App changelog](apps/calculator/CHANGELOG.md).
- Updated `io.vitrallis.bitcoindashboard` `1.3.0`: Add mempool.space network pages, persistent watch-only address monitoring and fail-closed shared Tor transport while preserving the CAD chart. [App changelog](apps/bitcoin-dashboard/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.4.2`: Fit collection names and status text by measured pixels and preserve keyboard focus during library refreshes. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).
- Updated `io.vitrallis.debug` `0.3.2`: Replace the launcher icon with optimized transparent GPT-generated artwork. [App changelog](apps/vitrallis-debug/CHANGELOG.md).
- Updated `io.vitrallis.fireflyfield` `0.3.1`: Replace the launcher icon with optimized transparent GPT-generated artwork. [App changelog](apps/firefly-field/CHANGELOG.md).

Calculator and the new Bitcoin release remain installation-disabled pending device
lifecycle/presentation verification and real Arti routing checks. Other existing
installation flags are preserved.

- Removed `io.vitrallis.carouselrust` (Carousel-Rust) from the catalog and deleted its app package and dedicated CI checks. Historical release notes and verification records remain in the repository; the deleted package and its changelog remain available in Git history.

## 2026-09-26

- Updated `io.vitrallis.liminalrust` `0.11.1`: Replace the older Liminal package with the PocketCHIP edition of Places, including its ARMv7 build, baked lighting and catalog-sized artwork with repaired texture seams. Installation remains disabled pending App Manager lifecycle verification. [App changelog](apps/places-pocketchip/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.4.1`: Add bulk WebP conversion and improve playback, settings, upload handling, streaming downloads and service shutdown. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).

Places 0.11.1 installation was enabled after PocketCHIP App Manager installation,
0.3.1-to-0.11.1 update, repair, installed-launcher and visual checks. Its package
was mirrored byte-for-byte to the original `csd113/Places` source so existing
installations can update without changing their trusted source. [Device
verification](docs/verification/places-pocketchip-2026-09-26/README.md).

## 2026-09-21

- Updated `io.vitrallis.liminalrust` `0.3.1`: Move the Places package to its standalone repository while preserving App Center's stable application ID and native ARMv7 package contract. [App changelog](https://github.com/csd113/Places/blob/main/apps/liminal-rust/CHANGELOG.md).
- Added `io.vitrallis.liminalrust` `0.1.0`: Publish the native ARMv7 walking game with three residential levels, material and lighting support, and installable App Manager metadata. [App changelog](apps/liminal-rust/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.3.0`: Add animated WebP playback, validated GIF conversion, bounded media caching and streamed folder downloads. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).
- Updated `io.vitrallis.bitcoindashboard` `1.2.5`: Correct the publication guidance and include the project license. [App changelog](apps/bitcoin-dashboard/CHANGELOG.md).
- Updated `io.vitrallis.debug` `0.3.1`: Publish the existing licensing clarification and include the project license. [App changelog](apps/vitrallis-debug/CHANGELOG.md).
- Updated `io.vitrallis.carouselrust` `0.1.4`: Publish the existing MIT metadata and notices with distribution license texts, retaining the native payload. [App changelog](apps/carousel-rust/CHANGELOG.md).

## 2026-09-19

- Updated `io.vitrallis.carouselrust` `0.1.3`: Retain the displayed frame between media items, correct QR sizing and margins, and center native labels and connection details. [App changelog](apps/carousel-rust/CHANGELOG.md).
- Updated `io.vitrallis.carouselrust` `0.1.2`: Prepare up to ten upcoming GIFs within a bounded rolling cache, reuse decoded frames from the first play, and prioritize newly selected animations. [App changelog](apps/carousel-rust/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.2.1`: Prepare upcoming GIFs before playback with bounded caching, cancel obsolete preparation on navigation, and preserve the playback clock when paused during loading. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).
- Added `io.vitrallis.carouselrust` `0.1.1`: Publish an installable native ARMv7 Rust carousel with GPU-synchronized playback, LAN management and the shared Python photo library; retain PocketCHIP decoder bounds while accommodating 64-bit FFmpeg libraries. [App changelog](apps/carousel-rust/CHANGELOG.md).
- Updated `io.vitrallis.fireflyfield` `0.3.0`: Cache menu text, batch sprite rendering and prefer synchronized presentation. [App changelog](apps/firefly-field/CHANGELOG.md).
- Updated `io.vitrallis.debug` `0.3.0`: Add live CPU/GPU Pulse overlays, scoped Lima telemetry and keyboard navigation fixes. [App changelog](apps/vitrallis-debug/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.2.0`: Improve animation presentation, add QR connection details, parallel uploads, thumbnails, folder downloads and verified multimedia setup. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).

## 2026-09-14

- Added `io.vitrallis.fireflyfield` `0.2.1`: Ship packaged meadow artwork, improve renderer selection and input handling, and enable catalog installation. [App changelog](apps/firefly-field/CHANGELOG.md).
- Updated `io.vitrallis.debug` `0.2.1`: Discover Lima/Mali devfreq GPUs and present a stable devfreq-monitor utilization average. [App changelog](apps/vitrallis-debug/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.1.4`: Use an optional GLES2 presentation path for GIFs and keep animation timing on the media clock. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).

## 2026-09-13
- Updated `io.vitrallis.mediacarousel` `0.1.3`: Shorten the per-launch LAN access code to six characters and update the login form and instructions. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).

## 2026-09-12

- Updated `io.vitrallis.debug` `0.2.0`: Restore the polished dashboard, hardware-rendered Pulse, GPU graphs and Linux CPU/GPU driver detection. [App changelog](apps/vitrallis-debug/CHANGELOG.md).
- Updated `io.vitrallis.bitcoindashboard` `1.2.4`: Standardize dated package release history and publish its refreshed inventory. [App changelog](apps/bitcoin-dashboard/CHANGELOG.md).
- Updated `io.vitrallis.debug` `0.1.2`: Add a packaged version history and README link without changing diagnostics. [App changelog](apps/vitrallis-debug/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.1.2`: Add a packaged version history and README link without changing playback. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).
- Updated `io.vitrallis.mediacarousel` `0.1.1`: Enable installation from main and publish X11 identity for Shell focus and resume. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).
- Added `io.vitrallis.mediacarousel` `0.1.0`: Merge the native slideshow and LAN media manager into main, initially with installation disabled. [App changelog](apps/vitrallis-media-carousel/CHANGELOG.md).
- Updated `io.vitrallis.debug` `0.1.1`: Publish X11 process identity for native window focus and resume. [App changelog](apps/vitrallis-debug/CHANGELOG.md).
- Updated `io.vitrallis.bitcoindashboard` `1.2.3`: Publish X11 process identity for native window focus and resume. [App changelog](apps/bitcoin-dashboard/CHANGELOG.md).
- Added `io.vitrallis.debug` `0.1.0`: Publish the offline network, CPU, temperature and memory diagnostics app. [App changelog](apps/vitrallis-debug/CHANGELOG.md).
- Updated `io.vitrallis.bitcoindashboard` `1.2.2`: Move the dashboard to the native manifest v1 package and canonical lowercase app directory. [App changelog](apps/bitcoin-dashboard/CHANGELOG.md).

Bitcoin Dashboard and Vitrallis Debug installation were enabled after native
App Center verification. Media Carousel source-run device checks are recorded
under `docs/verification/`; they are separate from installation verification.

## 2026-09-11

- Updated `io.vitrallis.bitcoindashboard` `1.2.1`: Exclude development tests from installed packages and update the publication instructions. [App changelog](apps/bitcoin-dashboard/CHANGELOG.md).

## 2026-09-10

- Added `io.vitrallis.bitcoindashboard` `1.2.0`: Introduce the versioned JSON catalog entry with pinned source checksums for Bitcoin Dashboard. [App changelog](apps/bitcoin-dashboard/CHANGELOG.md).

These initial catalog records were reconstructed from Git publication history.
Upstream app releases before catalog submission remain in the app changelog.
