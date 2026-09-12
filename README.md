# Vitrallis Apps

A versioned package contract, a GitHub-backed application catalog, and tools for
maintaining either the official catalog or your own. Start with the small
[Hello Vitrallis example](examples/hello-vitrallis/README.md), then publish exact
committed bytes with generated checksums.

## Start here

Use Python **3.11+** and Git on Linux, macOS or WSL for repository tooling.
No pip packages are required. Native Windows file-safety APIs are not supported.
The example runtime is Python **3.8+** with Tkinter; tools and app runtimes are
separate requirements.

1. **Clone or fork** this repository. For your own catalog, follow
   [forking a catalog](docs/forking-a-catalog.md) to choose its source and trust policy.
2. **Create an app:** copy `examples/hello-vitrallis/` to `apps/your-app/` and
   change its identity, version, artwork and behavior. See
   [creating apps](docs/creating-apps.md). Use a case-sensitive checkout when
   keeping both `Apps/` and `apps/` (Linux, or a case-sensitive macOS volume).
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
python3 tools/validate_catalog.py --catalog apps.json --package examples/hello-vitrallis
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s examples/hello-vitrallis/tests -v
```

## What is defined, and what is implemented?

| Layer | Contract or implementation |
| --- | --- |
| [Package manifest v1](docs/creating-apps.md) | This repository defines the official `app.toml` package specification, including `manifest_version = 1`. |
| [Catalog schema v1](docs/catalog-format.md) | Publisher-neutral JSON metadata with full Git commit pins and file sizes/SHA-256 values. Trust is client configuration. |
| Official catalog | [`apps.json`](apps.json) in `csd113/Vitrallis-Apps`; [raw JSON](https://raw.githubusercontent.com/csd113/Vitrallis-Apps/main/apps.json) is its default distribution endpoint. |
| Shell integration | Manifest consumption is version-dependent. The inspected shell uses PocketHome menu entries; a package manifest alone does not register an app. |
| Legacy Bitcoin installation | Pocketchip-update-apps 1.6.x has a reviewed Bitcoin adapter. It is not a general native-package installer or a configurable multi-publisher client. |

## Repository map

```text
apps.json                     Official production catalog (Bitcoin only)
apps.schema.json              Generic catalog schema v1
apps/<app-slug>/               Canonical new native packages (created as needed)
Apps/Bitcoin-Dashboard/       Unchanged legacy source snapshot; keep its casing
examples/hello-vitrallis/      Copyable manifest v1 app, not in production catalog
tools/                        Offline validator and commit-based catalog updater
  tests/                      Adversarial and publication workflow regression tests
docs/                         Format, creation, publication, forking, compatibility
.github/workflows/validate.yml  Push/PR repository checks
CONTRIBUTING.md                Review and validation checklist
VITRALLIS_APP_BUILD_GUIDE.md   Developer guidance linked to the package contract
```

## Official Bitcoin compatibility

The catalog retains `io.vitrallis.bitcoindashboard` **1.2.0**, its exact source
commit, nine files, permissions and installation flag. `Apps/Bitcoin-Dashboard`
is an unchanged import from
[csd113/PocketChip-Bitcoin-Display at 9d732e0](https://github.com/csd113/PocketChip-Bitcoin-Display/tree/9d732e056801c8a98ee3edb60cb5bd88646ac467).
It has no native manifest. Its legacy launcher/storage paths and original docs
are preserved. See [legacy compatibility](docs/legacy-compatibility.md) for the
manager and shell boundaries. Desktop validation does not establish device
compatibility; physical verification remains separate.

## Contributing and licensing

Read [CONTRIBUTING.md](CONTRIBUTING.md). No authoritative repository-wide license
was found. The owner must choose or confirm licensing and the imported app's
redistribution rights before granting reuse rights. These technical copying
instructions do not themselves grant a license.
