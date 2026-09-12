# Runtime integration and compatibility

[Documentation](README.md) · [Available apps](../README.md#available-apps) · [Support](../SUPPORT.md)

All production apps use manifest v1 under `apps/<app-slug>/`. Repository tools
validate structure, metadata, and pinned source bytes. The consuming
[Vitrallis Shell App Center](https://github.com/csd113/Vitrallis-Shell/blob/main/docs/app-center.md)
provides installation and native launcher registration. Support depends on the
Shell build and the target runtime, not just a valid manifest.

## Install, update, or repair

Open **App Center → Check**, select an app, review **Details**, then **Install**.
The same Install action handles first installation, updates, and repairs. The
current Shell resolves the configured GitHub repository's default branch and
reads root `apps.json`; the official repository uses `main`. See
[hosting a catalog](forking-a-catalog.md) for additional sources and scoped trust.

App Center verifies package identity and file inventories before installation and
reports missing runtime dependencies. It does not run pip or install system
packages automatically. Installed packages use the XDG data location
`vitrallis/apps/<id>` (normally `~/.local/share/vitrallis/apps/<id>`), with native
launchers and icons registered by the Shell. Apps' own settings and saves use the
locations documented in their READMEs.

## Current apps and prerequisites

The following summarizes the current [catalog compatibility notes](../apps.json).
Published versions and installation readiness belong to that catalog.

| App | Runtime and dependencies | Recorded verification |
| --- | --- | --- |
| [Bitcoin Dashboard](../apps/bitcoin-dashboard/README.md) | Python 3.8+, Tkinter / Tk 8.6; no pip dependencies | Catalog records native installation and process-based window focus on Debian 13 PocketCHIP |
| [Vitrallis Debug](../apps/vitrallis-debug/README.md) | Python 3.8+, Tkinter / Tk 8.6; no pip dependencies; Linux interfaces provide real diagnostics | Catalog records native installation and process-based window focus on Debian 13 PocketCHIP |
| [Vitrallis Media Carousel](../apps/vitrallis-media-carousel/README.md) | Python 3.9+, Tk 8.6, Pillow >=10.4,<13; App Center also needs `packaging`; optional `ffmpeg` and `ffprobe` for muted WebM | Catalog records source-run playback, LAN uploads, physical touch and keyboard on Debian 13.6 ARMv7 PocketCHIP; device App Center install/update/repair verification remains pending |

**All three entries are enabled in the catalog.** Enablement is a publisher flag,
not a claim that every device workflow has been verified. In particular, keep
Media Carousel's remaining App Center device checks distinct from its source-run
and [display acceleration evidence](verification/vitrallis-media-carousel-gpu.md).
All three apps publish X11 process identity for Shell focus/resume.

The packaged Bitcoin README still says catalog installation is disabled. That
sentence predates enablement; use the current catalog and this guide for status.
The Debug README's general hardware-certification caveat likewise does not negate
the specific installation/focus checks recorded in the catalog. App READMEs ship
inside pinned packages: editing them requires a new app version and publication,
so status updates outside a package do not rewrite previously published bytes.

On Debian, all three apps need `python3-tk`. Media Carousel additionally needs a
suitable Pillow installation (`python3-pil` and `python3-pil.imagetk`) and
`python3-packaging` for App Center's requirement checks; verify that the distro
Pillow meets the declared range. Optional `ffmpeg` supplies WebM tools. Its
[README](../apps/vitrallis-media-carousel/README.md#runtime-and-installation)
explains older images, ARMv7 dependencies, and runtime setup. Repository tools
separately need Python 3.11+.

## Verify a new app or target

Before enabling a new catalog entry, verify:

1. Native install, update, and repair with the intended Shell build and source
   trust configuration, including missing dependencies and failed downloads.
2. The selected Python/toolkit runtime, manifest entry launch, icon, X11 focus
   where applicable, close behavior, and return to the existing Shell.
3. Usable display area, keyboard and touch input, slow/offline operation, storage
   failures, and startup/idle resource use on the actual device.
4. Correct version/identity display and preservation of user data during updates.

Record app version/source commit, Shell version, OS/runtime, display size, steps,
results, and unverified areas. Desktop tests are useful evidence but do not
certify PocketCHIP performance, physical input, or installation. A successful
source launch and a verified App Center installation are separate results.

Permission declarations describe requirements; they do not establish sandboxing
or consent. Checksums are integrity metadata from the publisher, not independent
signatures. See the [catalog trust boundaries](catalog-format.md#verification-and-trust-boundaries)
and [security policy](../SECURITY.md). Client implementation changes belong in the
client repository and require review there.
