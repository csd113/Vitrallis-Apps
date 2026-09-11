# App catalog and version checks

The app manager's remote version index is [`apps.json`](../apps.json). Fetch it from:

```text
https://raw.githubusercontent.com/csd113/Vitrallis-Apps/main/apps.json
```

[`apps.schema.json`](../apps.schema.json) defines format version 1. The catalog is small metadata; checking versions does not require cloning repositories, downloading applications, or executing their code. An app's proposed `app.toml` serves a different purpose: local launch metadata after installation.

## Current integration status

This catalog is ready for a manager to consume, but the current App Center does not consume it yet. The inspected [Vitrallis App Center documentation](https://github.com/csd113/Vitrallis-Shell/blob/75c4ab7929be47c6bbfb6740adca51930290e8ea/docs/devices/pocketchip/store.md) describes an explicit Python `APPS` list and reviewed installation adapters. Its [app development documentation](https://github.com/csd113/Vitrallis-Shell/blob/75c4ab7929be47c6bbfb6740adca51930290e8ea/docs/app-development.md) also confirms that an `app.toml` loader is not implemented.

Bitcoin Dashboard is listed at **1.2.0** with `installable: false`. It is an unchanged source import with a legacy launcher, not a complete generic Vitrallis package. A manager may display its version and compatibility notes, but must disable installation and automatic updates through this catalog until a reviewed adapter is available. This flag does not disable the existing upstream updater, which uses its own catalog.

The ID `io.vitrallis.bitcoindashboard` is newly assigned for this repository. It does not automatically match the current launcher's generated IDs or the legacy updater's entries. A manager adapter must explicitly map an existing Bitcoin installation to this ID before comparing versions; do not guess identity from a similar display name.

## Fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Catalog format version. A client must reject unsupported versions. |
| `apps[].id` | Stable app identity; must be unique within the catalog. |
| `name`, `description` | Display text; never shell commands or markup to execute. |
| `version` | Published stable version, without a `v` prefix. |
| `runtime`, `entry` | Runtime name and app-relative entry file. Version 1 supports Python entries. These do not select an arbitrary executable from the network. |
| `permissions` | Declared capability needs; not proof of sandbox enforcement or user consent. |
| `installable` | Publisher readiness flag. `false` forbids catalog-driven installs/updates; `true` still requires a supported, trusted local adapter and compatible runtime. |
| `compatibility_notes` | Human-readable requirements or remaining limitations. |
| `source.repository` | This trusted repository, `csd113/Vitrallis-Apps`. |
| `source.commit` | Full Git commit containing the published app files. Never a moving branch or tag. |
| `source.path` | App directory inside that commit. |
| `files` | Complete published source snapshot, with paths relative to the app directory, byte sizes, and SHA-256 digests. |

Version 1 accepts stable `MAJOR.MINOR.PATCH` versions only, with no leading zeros, prerelease suffix, or build metadata. Compare the three components numerically: `1.10.0` is newer than `1.9.0`. This is the stable subset of [Semantic Versioning](https://semver.org/). A format extension is needed before publishing other version forms.

The current `files` list includes source, documentation, tests, and the legacy launcher. It describes bytes, not an installation recipe or executable permission policy. A reviewed adapter decides which files it installs and how it supplies runtime libraries, launch wrappers, icons, and menu registration.

## Manager behavior

1. Fetch the fixed catalog URL over verified HTTPS with finite timeouts and an 8 MiB response limit. Cache the last valid result and its retrieval time. Conditional requests with ETag/Last-Modified may reduce transfers; reuse cached data on HTTP 304 only if a valid cached catalog exists. A failed check means “could not check,” not “up to date.”
2. Parse JSON as data, reject duplicate object keys, and validate against a locally bundled schema for version 1. Do not fetch or execute validation code from the catalog. Also reject duplicate app IDs, duplicate/case-colliding file paths, control characters in display text, an entry missing from `files`, and bundles totaling more than 16 MiB. The schema limits each file to 2 MiB and each bundle to 256 files. Cross-field checks remain client responsibilities.
3. Match each remote app to a trusted local installation record by ID. Record installed version, source commit, and verified hashes only after a successful installation. For a legacy Bitcoin install, use the reviewed adapter's AST/literal version reader; never import installed or downloaded code merely to discover a version.
4. Compare numeric versions. Higher means an update is available; equal means the published version matches; lower must not trigger an automatic downgrade. Missing or invalid local metadata means unknown/unmanaged, not version zero. Equal versions with different recorded content require review or a deliberate repair workflow; do not silently reinstall them as an update.
5. When installation is supported and requested, construct file URLs from the validated repository, commit, app path, and file path. For example: `https://raw.githubusercontent.com/csd113/Vitrallis-Apps/ab2869b2cf25818cfcf09f5d1fc7055dfbb9a218/Apps/Bitcoin-Dashboard/bitcoin.py`. Fetch every file from that one commit, limit reads, and verify both size and SHA-256 before using any downloaded file. Restrict URLs and redirects to the manager's trusted HTTPS policy.
6. Reject absolute paths, traversal, symlinks, unsafe destination parents, and path collisions. Stage a complete verified installation before replacing the active version. Preserve settings/saves and retain rollback or interrupted-install recovery. Never run shell fragments, package installation commands, or hooks supplied by remote metadata. Keep runtime provisioning and menu changes in reviewed local adapters.

SHA-256 detects content mismatches; a checksum supplied by the same repository is not an independent signature. This design trusts the configured GitHub repository over HTTPS. Signed catalogs and rollback-resistant metadata can be added later if the distribution trust requirements change.

## Publishing a new app version

1. Update the app and its version, validate it, and commit/push the source files first. For Bitcoin, read the literal `VERSION` in `bitcoin.py`; for future supported packages, keep the app manifest version synchronized.
2. Update the catalog entry to that full commit and version. Enumerate the published app files from the committed tree, calculate SHA-256 and byte sizes from those exact bytes, and replace the complete `files` list. Exclude local caches, secrets, and build artifacts.
3. Preserve the app ID. Keep `installable` false until its complete installation/update path has been implemented and verified. Do not change published application bytes under the same version; publish a new version when app contents change.
4. Validate the catalog against the schema, check the cross-field rules above, and fetch the pinned files to verify availability, sizes, hashes, and the app's actual version.
5. Commit and push `apps.json`. This publication makes the new version discoverable. Documentation-only repository commits do not require changing an app's pinned source commit.

Publishing source before the catalog avoids circular commit references and ensures the advertised files already exist. Each app may reference a different commit. Merely changing app files on `main` does not publish an update until the catalog is updated.
