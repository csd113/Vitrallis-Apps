# Catalog changelog

[Repository overview](README.md) · [Documentation](docs/README.md)

This is the release history for the main [apps.json](apps.json) catalog. Dates
use America/Vancouver time. App IDs remain stable; each app ships its own
`CHANGELOG.md` with detailed release notes. Keep existing release records intact
and place new records in the newest date section. See the
[changelog policy](docs/changelog-policy.md) for the required submission format.

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
