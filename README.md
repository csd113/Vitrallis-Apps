# Vitrallis Apps

**Small apps. More possibilities for your Vitrallis screen.**

A home for applications in the [Vitrallis](https://github.com/csd113/Vitrallis-Shell)
Linux and single-board computer ecosystem. Browse useful tools, install them
through Vitrallis Shell's App Center, or build something of your own.

[Available apps](#available-apps) · [Quick start](#quick-start) ·
[Create an app](docs/creating-apps.md) · [Documentation](docs/README.md) ·
[Contribute](CONTRIBUTING.md)

## About

Vitrallis Apps brings a Bitcoin dashboard, offline device diagnostics, and a
locally managed media slideshow to small screens such as PocketCHIP. The apps
use native Python and Rust windows with keyboard and touch controls. Each lives
in its own directory, with its source, artwork, instructions, and tests together.

### What is Vitrallis Apps?

This repository is the official app catalog, the source for its published apps,
and a starting point for app authors and catalog hosts. **Vitrallis Shell** provides
the desktop and **App Center** handles discovery, installation, updates, and
repairs. The Shell's built-in Terminal, Notepad, and Files are maintained in the
Shell repository; they are separate from this catalog.

Vitrallis is pre-release. The current contracts are **catalog v1** and **package
manifest v1**. Runtime requirements and device verification vary by app; see
[compatibility and integration](docs/runtime-integration.md).

## Key capabilities

- **Small-screen applications:** native interfaces designed around a 480×272
  PocketCHIP profile, with app-specific support for larger windows.
- **Inspectable packages:** readable manifests, declared requirements, and source
  files pinned to full Git commits with byte sizes and SHA-256 checksums.
- **A working starting point:** an offline greeting app you can study and adapt.
- **Your own catalog:** host the same format in a GitHub repository and add it to
  a compatible App Center through Sources.
- **Repeatable publication:** standard-library Python tools validate packages,
  generate catalog entries from committed source, and check release histories.

## Available apps

<!-- App rows are derived from apps.json; refresh names, descriptions and links when catalog membership changes. -->
| App | What it does |
| --- | --- |
| [Bitcoin Dashboard](apps/bitcoin-dashboard/README.md) | Bitcoin CAD price, chart, and network dashboard for the PocketCHIP. |
| [Vitrallis Debug](apps/vitrallis-debug/README.md) | Offline network, CPU, temperature, and memory diagnostics for the PocketCHIP. |
| [Vitrallis Media Carousel](apps/vitrallis-media-carousel/README.md) | Native media slideshow with LAN uploads, named collections and shared settings. |
| [Carousel-Rust](apps/carousel-rust/README.md) | Rust media carousel sharing the Python photo library; requires the Shell native Rust runtime. |
| [Liminal](apps/liminal-rust/README.md) | A native first-person walking game through three quiet, decaying residential interiors. |
| [Firefly Field](apps/firefly-field/README.md) | A calm, fullscreen pixel-art firefly meadow rendered through SDL2. |

[`apps.json`](apps.json) records advertised versions, publisher enablement, and
compatibility notes. Enablement is not hardware certification; source publication
and dated device evidence are separate. Local edits do not update published pins.
The [catalog changelog](CHANGELOG.md) records
releases. [Hello Vitrallis](examples/hello-vitrallis/README.md) is a developer
example and is not listed in the production catalog.

## How the ecosystem works

```text
Vitrallis Shell / App Center
  → reads apps.json for available apps and published versions
  → locates apps/<app-slug>/ at each entry's pinned source commit
  → checks app.toml identity, version, entry point and requirements
  → verifies the listed source files, byte sizes and SHA-256 checksums
  → installs the package and registers its native launcher
```

Authors work in `apps/`, validate and test a package, then publish its source.
The updater generates the catalog inventory from that commit; catalog validation
checks the advertised bytes against Git. App Center consumes that publication.
Checksums verify integrity against the catalog. Trust in its publisher is still
required, and permission declarations do not sandbox an app.

## Quick start

**To use an app:** open **App Center → Refresh**, select an app, review **Details**,
then choose **Install**. Read its README for controls and prerequisites. You do
not need to clone this repository to install through App Center.

**To explore the source:** use Git and Python **3.11+** on Linux, macOS, or WSL.
The repository tools need no pip packages. Clone with history so catalog pins can
be verified:

```sh
git clone https://github.com/csd113/Vitrallis-Apps.git
cd Vitrallis-Apps
python3 tools/validate_catalog.py --catalog apps.json --package examples/hello-vitrallis
python3 examples/hello-vitrallis/main.py --check
```

The last command prints the bundled greeting without a display. With Tkinter and
a graphical session available, run `python3 examples/hello-vitrallis/main.py`
to open the example. See [testing setup](docs/testing.md) for the full app suite.

## Using this repository with Vitrallis App Center

The current Shell includes `csd113/Vitrallis-Apps` as its default catalog source.
App Center resolves the repository's default branch and reads its root
`apps.json`. The official branch is `main`; the
[raw catalog](https://raw.githubusercontent.com/csd113/Vitrallis-Apps/main/apps.json)
is also available for inspection.

**Refresh** retrieves catalog metadata. The selected row offers **Install**,
**Update**, **Repair**, or **Open**; **Remove** is a separate confirmed action.
App Center automatically provisions missing Python requirements in an app-local
environment. System prerequisites remain separate. All currently listed apps are
enabled, with app-specific verification limits and prerequisites documented in
[runtime integration](docs/runtime-integration.md).

For additional repositories use **Sources → Add** with `owner/repository`.
See the [hosting guide](docs/forking-a-catalog.md) for source trust and the
[Shell App Center guide](https://github.com/csd113/Vitrallis-Shell/blob/main/docs/app-center.md)
for controls, removal, and recovery.

## Creating your own Vitrallis app

Start with the smallest working example:

```sh
cp -R examples/hello-vitrallis apps/my-app
```

Choose a stable ID in a namespace you control, then customize the manifest,
greeting, window title, icon, README, dated changelog, and tests. Validate before
publishing:

```sh
python3 tools/validate_catalog.py --package apps/my-app
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/my-app/tests -v
```

[Creating apps](docs/creating-apps.md) explains every required file and manifest
field. The [developer build guide](VITRALLIS_APP_BUILD_GUIDE.md) covers responsive
interfaces, lifecycle, network failures, and storage. Confirm the
[licensing position](#license) before reusing or distributing repository content.

## Hosting or forking your own app repository

A catalog uses the same JSON and package contracts regardless of publisher.
Host `apps.json` at the root of your GitHub repository's default branch, publish
source commits before their catalog entries, and add the repository in App Center.
A custom source supplements the built-in catalog.

The [forking guide](docs/forking-a-catalog.md) covers keeping upstream entries,
starting an empty catalog, checking inherited source pins, and approving separate
source repositories. Copying a catalog does not automatically grant trust or
redistribution rights.

## Repository structure

| Path | Purpose |
| --- | --- |
| [`apps/`](apps/) | Production packages, each with a manifest, README, changelog, assets, and tests |
| [`apps.json`](apps.json) / [`apps.schema.json`](apps.schema.json) | Published catalog and its JSON schema |
| [`examples/hello-vitrallis/`](examples/hello-vitrallis/) | Offline app template, excluded from the catalog |
| [`tools/`](tools/) | Package/catalog validation, catalog generation, changelog checks, and regression tests |
| [`docs/`](docs/README.md) | Authoring, format, testing, hosting, publication, and integration guides |
| [`docs/verification/`](docs/verification/) | Dated device evidence and its limits |
| [`.github/`](.github/) | CI workflows, issue forms, and pull request guidance |
| [`CHANGELOG.md`](CHANGELOG.md) | Published app additions and version updates |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Contribution and submission rules |

## App and package format

Each `apps/<app-slug>/app.toml` declares `manifest_version = 1`, a display name,
stable ID, `MAJOR.MINOR.PATCH` version, a `python` or `rust` runtime, and
boolean network/audio/storage requirements. Python uses a `.py` entry and
`requirements.txt`; Rust uses precompiled Linux ELF payloads in a `binaries`
mapping. Both include an icon, README, changelog, assets and tests.

Catalog entries add a description, compatibility notes, installation readiness,
source repository/path/commit, and a complete file inventory. Only app-local
`tests/` is excluded from installed packages; documentation and artwork ship too.
See the [manifest contract](docs/creating-apps.md#manifest-v1-normative) and
[catalog reference](docs/catalog-format.md) for exact fields, limits, and examples.

## Validation and testing

Use the [testing guide](docs/testing.md) for commands that discover **every app**,
run the example and tooling suites, compile Python outside packages, and check
whitespace. CI tests Python 3.11 and 3.13 on Linux with Tk, Xvfb, Pillow, and
FFmpeg. A separate changelog job checks committed publication history.

Package checks can inspect working files; catalog checks verify pinned Git bytes;
changelog-policy checks inspect commits. None replaces testing through the Shell
on your target device.

## Publishing and versioning

Use the [source-first, catalog-second workflow](docs/publishing-apps.md). Increase
the app version whenever shipped bytes change, including app documentation and
artwork. Add dated app release notes, publish the tested source commit, generate
the catalog entry, and record its release in the root changelog. Submit both
commits through a pull request and preserve the source pins when merging.

Root documentation changes do not publish app releases. The
[changelog policy](docs/changelog-policy.md) describes the required checks and
the distinction between package, test-only, and repository documentation changes.

## Documentation

Start at the [documentation index](docs/README.md), or go directly to:

- [Creating an app](docs/creating-apps.md) and [implementation guidance](VITRALLIS_APP_BUILD_GUIDE.md)
- [Catalog format](docs/catalog-format.md) and [publishing](docs/publishing-apps.md)
- [Hosting a catalog](docs/forking-a-catalog.md) and [runtime integration](docs/runtime-integration.md)
- [Testing](docs/testing.md) and [changelog requirements](docs/changelog-policy.md)

## Contributing

App ideas, focused fixes, clearer documentation, and device test reports are
welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) for the submission path and PR
expectations, and the [Code of Conduct](CODE_OF_CONDUCT.md) for working together.
For usage questions and troubleshooting, start with [Support](SUPPORT.md).

## Security

For vulnerabilities involving packages, validation, downloads, or app behavior,
follow [SECURITY.md](SECURITY.md). Keep exploit details, credentials, and private
device data out of public issues.

## Related Vitrallis projects

- [Vitrallis Shell](https://github.com/csd113/Vitrallis-Shell) — the launcher,
  built-in utilities, and App Center that consume this repository.
- [Vitrallis Flasher](https://github.com/csd113/Vitrallis-Flasher) — a separate
  Vitrallis project; consult its repository for current scope and availability.
- [PocketChip Bitcoin Display](https://github.com/csd113/PocketChip-Bitcoin-Display)
  — the original Bitcoin dashboard project and source of its historical screenshot.

## License

Project-owned code, documentation and original assets use [MIT](LICENSE).
[Third-party notices](THIRD_PARTY_NOTICES.md) identify dependency terms and unresolved
imported content excluded from that grant. Catalog pins and existing binaries are
unchanged; this source licensing update does not republish app packages.
