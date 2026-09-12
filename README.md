# Vitrallis Apps

A versioned package contract, a GitHub-backed application catalog, and tools for
maintaining either the official catalog or your own. Start with the small
[Hello Vitrallis example](examples/hello-vitrallis/README.md), then publish exact
committed bytes with generated checksums.

[Catalog changelog](CHANGELOG.md) · [Required app changelogs and merge policy](docs/changelog-policy.md)

## Start here

Use Python **3.11+** and Git on Linux, macOS or WSL for repository tooling.
No pip packages are required. Native Windows file-safety APIs are not supported.
The example runtime is Python **3.8+** with Tkinter; tools and app runtimes are
separate requirements.

1. **Clone or fork** this repository. For your own catalog, follow
   [forking a catalog](docs/forking-a-catalog.md) to choose its source and trust policy.
2. **Create an app:** copy `examples/hello-vitrallis/` to `apps/your-app/` and
   change its identity, version, artwork and behavior. See
   [creating apps](docs/creating-apps.md).
3. **Validate** the working package, then run its tests:

   ```sh
   python3 tools/validate_catalog.py --package apps/your-app
   PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/your-app/tests -v
   ```

4. **Publish:** commit the tested source first, then use
   [the publishing commands](docs/publishing-apps.md) to generate and validate
   the catalog entry from that full commit. Commit/push the catalog afterward.
5. **Configure the client:** select the catalog URL, allowed source repositories,
   runtime and installer adapter in a client that supports them. A fork does
   not reconfigure existing clients automatically.

Check this repository itself:

```sh
python3 tools/validate_catalog.py --catalog apps.json --package examples/hello-vitrallis --package apps/bitcoin-dashboard
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s examples/hello-vitrallis/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/bitcoin-dashboard/tests -v
```

## What is defined, and what is implemented?

| Layer | Contract or implementation |
| --- | --- |
| [Package manifest v1](docs/creating-apps.md) | This repository defines the official `app.toml` package specification, including `manifest_version = 1`. |
| [Catalog schema v1](docs/catalog-format.md) | Publisher-neutral JSON metadata with full Git commit pins and file sizes/SHA-256 values. Trust is client configuration. |
| Official catalog | [`apps.json`](apps.json) in `csd113/Vitrallis-Apps`; [raw JSON](https://raw.githubusercontent.com/csd113/Vitrallis-Apps/main/apps.json) is its default distribution endpoint. |
| Shell integration | Vitrallis Shell App Center reads this catalog, verifies pinned packages, and registers native launchers after installation. |
| Native packages | Bitcoin Dashboard, Vitrallis Debug and Vitrallis Media Carousel are listed and enabled for installation through App Center. |

## Repository map

```text
apps.json                     Official production catalog (three native apps)
CHANGELOG.md                  Dated catalog app additions and version updates
apps.schema.json              Generic catalog schema v1
apps/bitcoin-dashboard/       Native Bitcoin Dashboard package
apps/vitrallis-debug/          Native offline diagnostics package
apps/vitrallis-media-carousel/ Native slideshow with LAN media management
apps/<app-slug>/               Canonical location for all applications
examples/hello-vitrallis/      Copyable manifest v1 app, not in production catalog
tools/                        Offline validator and commit-based catalog updater
  tests/                      Adversarial and publication workflow regression tests
docs/                         Format, creation, publication, forking, runtime integration
.github/workflows/validate.yml  Push/PR repository checks
CONTRIBUTING.md                Review and validation checklist
VITRALLIS_APP_BUILD_GUIDE.md   Developer guidance linked to the package contract
```

## Bitcoin Dashboard

[Bitcoin Dashboard](apps/bitcoin-dashboard/README.md) is a native manifest v1
package at `apps/bitcoin-dashboard`, with stable ID
`io.vitrallis.bitcoindashboard` and version **1.2.4**. It preserves the CAD quote,
chart, network cards, detail views, settings and keyboard/touch controls of the
PocketCHIP dashboard. Python 3.8+ and Tkinter with Tk 8.6 are required.

The package declares network and storage requirements and no audio. It includes
its own icon and runs through `main.py` with system Python. Install it through
Vitrallis Shell App Center: Check, select the app, then Install.
See [runtime integration](docs/runtime-integration.md).
Desktop validation does not establish physical device compatibility.

## Vitrallis Media Carousel

[Vitrallis Media Carousel](apps/vitrallis-media-carousel/README.md) **0.1.2**
provides native image, GIF and muted WebM slideshows with LAN uploads and named
collections. Install it through App Center after providing Python 3.9+, Tk 8.6,
Pillow >=10.4,<13 and `packaging` in the launcher's Python environment. WebM also
requires optional system `ffmpeg` and `ffprobe`. App Center reports missing
prerequisites without installing system packages. See
[runtime integration](docs/runtime-integration.md).

## Contributing and licensing

Read [CONTRIBUTING.md](CONTRIBUTING.md). No authoritative repository-wide license
was found. The owner must choose or confirm licensing and the imported app's
redistribution rights before granting reuse rights. These technical copying
instructions do not themselves grant a license.
