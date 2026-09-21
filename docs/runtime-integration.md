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

Installed packages use `$XDG_DATA_HOME/vitrallis/apps/<id>` (normally
`~/.local/share/vitrallis/apps/<id>`), with native launchers registered by Shell.
Settings and saves use each app's documented location outside the package.
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

On **2026-09-20**, the local `apps.json` matched the published default-branch
catalog. All five entries are enabled. Versions and source inventories belong to
that catalog; an enabled flag is not installation certification. This cleanup
changes source documentation/licensing, not published pins or binaries.

| App | Runtime and prerequisites | Dated evidence and limits |
| --- | --- | --- |
| [Bitcoin Dashboard](../apps/bitcoin-dashboard/README.md) | Python 3.8+, Tk 8.6; no pip dependencies | Catalog records PocketCHIP native installation/focus; that note supplies no test date and is not fresh validation |
| [Vitrallis Debug](../apps/vitrallis-debug/README.md) | Linux, Python 3.8+, Tk; Pulse needs X11/XWayland, EGL/GLES2 and hardware drivers | September 19 staged-source telemetry/keyboard/overlay checks; managed update to 0.3.0 not exercised |
| [Vitrallis Media Carousel](../apps/vitrallis-media-carousel/README.md) | Python 3.9+, Tk 8.6; automatic Pillow >=10.4,<13 and qrcode >=7.4,<9; optional system ffmpeg/ffprobe | September 19 staged playback/uploads/keyboard and codec checks; managed update to catalog 0.2.1 not physically exercised |
| [Carousel-Rust](../apps/carousel-rust/README.md) | Published ARMv7 hard-float payload, glibc 2.36+, SDL2; catalog requires Mali/Lima and a VSync X11 compositor; optional ffmpeg/ffprobe | September 19 native lifecycle, codec and playback evidence; see the exact versions and isolated QA setup in the record |
| [Firefly Field](../apps/firefly-field/README.md) | Python 3.8+, system SDL2 2.0+ and video driver; SDL 2.0.18+ enables batching; no pip dependencies | September 19 physical Mali/Lima rendering measurements; managed update to 0.3.0 not exercised |

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
