# Runtime integration and compatibility

[Documentation](README.md) · [Available apps](../README.md#available-apps) · [Support](../SUPPORT.md)

All production apps use manifest v1 under `apps/<app-slug>/`. Repository tools
validate structure, metadata, and pinned source bytes. The consuming
[Vitrallis Shell App Center](https://github.com/csd113/Vitrallis-Shell/blob/main/docs/app-center.md)
provides installation and native launcher registration. Support depends on the
Shell build and the target runtime, not just a valid manifest.

## Install, update, or repair

Open **App Center → Refresh**, select an app and review **Details**. Its primary
action is **Install**, **Update**, **Repair**, or **Open**, depending on local
state; **Remove** is separate and confirmed. Refresh retrieves catalog metadata;
local installation checks do not refresh it. App Center reads root `apps.json`
from each configured GitHub repository's default branch (`main` here). See
[hosting a catalog](forking-a-catalog.md) for sources and scoped trust.

The canonical [Shell App Center guide](https://github.com/csd113/Vitrallis-Shell/blob/main/docs/app-center.md)
defines dependency provisioning, controls and transactions. For Python packages,
installation automatically provisions missing declared distributions in an
app-local environment under `runtime/<requirements hash>`. It exposes compatible
base-interpreter system packages and installs missing/incompatible requirements
plus `packaging` locally with pip, without upgrading or removing system packages.
The staged interpreter is checked before package publication; failed provisioning
removes the staged environment while preserving existing environments. This is
not a sandbox, and system package changes can affect an app-local environment.
Dependency downloads require network access and a usable distribution/wheel or
build prerequisites for the target. Refresh alone does not install dependencies.

Installed packages use `$HOME/Documents/Vitrallis/Apps/<id>`, with native launchers registered by Shell.
The launcher starts in `$HOME/Documents/Vitrallis/AppData/<id>` and exports
`VITRALLIS_APP_ID`, `VITRALLIS_APP_DIR`, `VITRALLIS_APP_DATA_DIR` and
`VITRALLIS_DOCUMENTS_DIR` (AppData/Documents). Persistent settings, saves and
media belong in AppData; update, repair and normal uninstall preserve them.
Resolve shipped assets from the entry's location or APP_DIR. Disposable caches
may use XDG_CACHE_HOME. These locations are user-owned; new data directories
are private (0700). Permissions are declarations, not a sandbox.
Rust packages select a precompiled Linux ELF payload for the device ABI; App Center
runs neither Cargo nor pip for them. A runtime accepting a target triple does not
mean this catalog publishes a payload for it.

## System prerequisites

App Center does not run apt, install Python/Tk/SDL2, graphics drivers or FFmpeg,
or execute publisher installation scripts. Python apps need a compatible base
Python, venv/pip support, and Tk when declared. On Debian the relevant packages
include `python3`, `python3-venv`, `python3-tk` and `python3-packaging`.
Pillow and qrcode are app-local Python requirements, not mandatory manual apt
installations; already-compatible system distributions may be reused.

The separate [PocketCHIP Shell setup](https://github.com/csd113/Vitrallis-Shell/blob/main/docs/devices/pocketchip.md)
under `integrations/pocketchip/` prepares supported system prerequisites and the
supervised session. Carousel's optional FFmpeg installation action uses that
setup's fixed privileged multimedia helper; it is separate from App Center's pip
provisioning. Source launches outside App Center need their own dependency setup.
Repository tooling separately requires Python 3.11+.

## Current catalog and recorded evidence

Carousel-Rust was removed from the catalog and source tree on **2026-10-01**.
Its dated verification records remain below as historical evidence. Current
catalog membership and versions are recorded in `apps.json`; an enabled flag
is not installation certification.

| App | Runtime and prerequisites | Dated evidence and limits |
| --- | --- | --- |
| [Bitcoin Dashboard](../apps/bitcoin-dashboard/README.md) | Python 3.8+, Tk 8.6; no pip dependencies | October 3 managed 1.3.1 lifecycle and offline cached/error states; fresh Tor/API data unavailable |
| [System Monitor](../apps/vitrallis-debug/README.md) | Linux, Python 3.11+, Tk; Pulse needs X11/XWayland, EGL/GLES2 and hardware drivers | October 3 managed 0.4.0 lifecycle and native 0.4.1 network-counter repair; GPU utilization accuracy unresolved |
| [Calculator](../apps/calculator/README.md) | Python 3.11+, system Tk; no pip requirements | October 3 managed 0.1.1 removal/reinstall, arithmetic, Home/resume and offline exit; physical input/scanout unverified |
| [Music](../apps/music/README.md) | Python 3.11+, Tk, Pillow >=10.4,<13; system FFplay/FFprobe/FFmpeg | October 3 managed 0.1.0 lifecycle and 25 native 0.1.1 source tests; speaker output unverified |
| [Sketch](../apps/sketch/README.md) | Python 3.11+, Tk, Pillow >=10.4,<13 | October 3 managed 0.1.0 drawing/save/open/lifecycle and 17 native tests; physical touch/scanout unverified |
| [Vitrallis Media Carousel](../apps/vitrallis-media-carousel/README.md) | Python 3.9+, Tk 8.6; automatic Pillow >=10.4,<13 and qrcode >=7.4,<9; optional system ffmpeg/ffprobe | October 3 managed 0.4.3 lifecycle and native 0.4.4 VP8 source repair; cold startup remains slow |
| [Firefly Field](../apps/firefly-field/README.md) | Python 3.8+, system SDL2 2.0+ and video driver; SDL 2.0.18+ enables batching; no pip dependencies | October 3 managed 0.3.1 lifecycle and native 0.3.2 packing comparison; low FPS remains a concern |
| [Places](../apps/places-pocketchip/README.md) | ARMv7 hard-float Linux, glibc 2.36+, SDL2 2.32+, GLES2/X11; trust csd113/Places | October 3 managed 0.11.2 removal/reinstall, movement/pause/Home/resume/offline exit; settings/cache preserved |

See [September 19 platform/app evidence](verification/platform-app-refinements-2026-09-19/README.md),
[Carousel-Rust lifecycle evidence](verification/carousel-rust-2026-09-19/README.md),
and the earlier [Carousel graphics report](verification/vitrallis-media-carousel-gpu.md).
Those records identify tested builds, OS, methods and limits. They do not certify
all catalog versions, touch paths or other devices. Shell's Linux release targets
are x86-64 and ARMv7 (glibc 2.36+, SDL2 2.26.5+); its macOS development build is
not a Linux package target. Rust's manifest can describe AArch64 as well, but
neither a Shell AArch64 release nor a Carousel-Rust AArch64 payload is implied.

Packaged READMEs describe their pinned source and can retain historical disabled
flags or license wording. Current source grant and unresolved rights are in
[third-party notices](../THIRD_PARTY_NOTICES.md); a source edit does not republish
a package. Hardware support requires the matching runtime, platform integration
and dated evidence, not just a matching resolution.

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


## October 2 package-side readiness pass

Calculator's original catalog entry was publisher-disabled, rather than invalid.
The original payload passed macOS staged provisioning/import/GUI checks; prepared
0.1.1 also fixes Linux idle termination and passed repeated read-only launch on
both platforms. Calculator 0.1.1, Music 0.1.0, Sketch 0.1.0 and System Monitor 0.4.0
had published source and generated catalog pins in the draft PR branch.
At that pass, the releases were draft-only and Music and Sketch remained disabled.
See the [local verification record](verification/apps-readiness-2026-10-02/README.md).

The current [Shell storage contract](https://github.com/csd113/Vitrallis-Shell/blob/main/docs/settings-storage.md)
exports `VITRALLIS_APP_ID` and `VITRALLIS_DOCUMENTS_DIR`; its canonical fallback is
`$HOME/Documents/Vitrallis/AppData/<stable-app-id>/Documents/` in the current
local integration contract above. Music libraries, Sketch drawings and saved
System Monitor reports use the exported Documents path. Preferences use the
exported AppData root (config/), with XDG reserved for disposable caches; caches/temp
files never belong to the source/package payload. The public upstream storage guide
may still describe the previous path while parallel Shell release work is pending.
An invalid launcher identity or unsafe storage path fails closed.

The October 2 pass deferred physical validation and made no Shell changes or
device accesses. The separately authorized October 3 pass completed managed
removal/reinstallation for all eight apps. All catalog installation flags are now
enabled; exact versions, source repairs and remaining physical/performance checks
are recorded in the [October 3 audit](verification/apps-hardware-2026-10-03/README.md).
