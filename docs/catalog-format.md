# Catalog format v1

The generic contract is [`apps.schema.json`](../apps.schema.json) plus the
cross-field rules below. [`apps.json`](../apps.json) is one publisher's production
catalog, not the schema. A publisher selects a HTTPS catalog endpoint; a client
configures that endpoint and an explicit allowlist of GitHub source repositories.
The official endpoint is an example/default, not a requirement of this format.

## Fields

The root contains exactly `schema_version: 1` and `apps` (up to 1,000 entries).
Each entry contains exactly these fields:

| Field | Meaning |
| --- | --- |
| `id` | Stable lowercase reverse-domain ID, at most 128 characters. Each dot-separated component starts with a letter and contains lowercase letters/digits; at least two components. IDs are unique across the catalog. |
| `name`, `description`, `compatibility_notes` | Nonempty display text, at most 1,000 characters each, without C0/C1 control characters. Never executable instructions or trusted markup. |
| `version` | Stable `MAJOR.MINOR.PATCH`, numeric components without leading zeroes, at most 32 characters. No `v`, prerelease or build suffix. Compare components numerically. |
| `runtime` | `python` in v1. Does not authorize invoking an arbitrary interpreter. |
| `entry` | Safe app-relative entry file, included in `files`. Native packages require a `.py` entry. |
| `permissions` | Exactly boolean `network`, `audio`, `storage`. Requirements, not sandbox enforcement or proof of consent. |
| `installable` | Publisher readiness flag. False forbids catalog-driven installation/update/repair. True still needs a compatible runtime, trusted source and reviewed client adapter. |
| `source.repository` | A GitHub `owner/repository` value. Owner: 1–39 ASCII letters/digits/hyphens, starts/ends with a letter or digit, no consecutive hyphens. Repository: 1–100 ASCII letters/digits/underscore/dot/hyphen, excluding `.` and `..`. No URL, credentials, port, path or `.git` suffix convention; use the actual repository name. The syntax check does not establish existence or trust. |
| `source.commit` | Exactly 40 lowercase hexadecimal characters identifying a Git commit (SHA-1 object format). A branch, abbreviated hash, tag object or tree is not a source pin. |
| `source.path` | `apps/<app-slug>` for native packages, where the slug is lowercase letters/digits separated by single hyphens; also accepts legacy `Apps/<name>` with ASCII letters/digits/underscore/hyphen. |
| `files` | Complete source directory at that commit, sorted by ASCII path. Each row has exactly `path`, integer `size`, lowercase 64-hex `sha256`. Includes docs, tests and assets. |

Catalog schema remains **1**: allowing other repository names and native source
paths is additive. Older clients may retain a narrower trust policy and path
support. Format acceptance does not imply installer support.

## Cross-field and byte rules

- Sort apps by ID and files by path using case-sensitive ASCII order. JSON object
  key order is not significant; tooling writes two-space indentation and a final newline.
- Reject duplicate JSON object keys, non-JSON numbers, duplicate app IDs and
  duplicate/case-colliding paths, including directory spelling collisions.
- Entry and file paths are at most 240 characters, contain ASCII letters/digits,
  underscore, dot, hyphen and `/` separators only, and have no empty, `.` or `..`
  component. Absolute paths, backslashes, traversal and file/directory collisions
  are invalid. Never use a path from metadata as shell code.
- Catalog size is at most 8 MiB. A bundle has 1–256 files, each at most 2 MiB and
  together at most 16 MiB. Reject symlinks, submodules and nonregular files.
- Every file must exist in the pinned source directory with exactly the advertised
  byte count and SHA-256. The list must enumerate the **entire** directory; there
  are no publishing ignore rules. Keep caches, secrets and build artifacts out.
- Native `apps/` directories require the complete [manifest v1 package](creating-apps.md).
  A legacy directory containing `app.toml` is also validated as native. Catalog
  ID, name, version, runtime, entry and permissions must equal the manifest.
- Legacy directories without a manifest require a single top-level literal
  `VERSION = "x.y.z"` in the Python entry matching the catalog. Validation parses
  its AST without importing app code. The Bitcoin snapshot satisfies this adapter
  convention; it is not an exemption from hash or path checks.

The standard-library validator applies the vocabulary used by the bundled JSON
schema, then these semantic checks. It is deliberately not a general JSON Schema
engine: unsupported schema keywords fail closed. Schema vocabulary extensions
must extend the evaluator and its tests or adopt a full validator. JSON Schema
alone cannot prove hashes, complete file lists or manifest consistency.

## Verification and trust boundaries

`python3 tools/validate_catalog.py` validates metadata and bytes from local Git
objects; it never fetches source or executes apps. Its default object store is the
checkout containing the tool. For a source hosted in a different repository:

```sh
python3 tools/validate_catalog.py --source-repo publisher/other-apps=/path/to/clone
```

Mappings are explicit and repeatable. Without one, all pins are looked up in the
current checkout, which also supports inherited pins in a fork. Missing commits
fail with instructions to supply a complete checkout; clone/fetch the trusted
source yourself. Local object presence proves content, **not** that GitHub serves
that commit from the declared repository. [Publishing](publishing-apps.md) includes
a separate remote availability check. Git replace objects are disabled during
verification.

Clients should bound network requests and downloads, enforce HTTPS and their
redirect/host policy, validate before enabling install, and never import downloaded
code to discover a version. Equal versions do not imply equal bytes; changed
publication bytes require a new version. Do not automatically downgrade. Unknown
local metadata means unmanaged/unknown, not version zero. Preserve user saves,
stage the entire verified update before replacement, and retain rollback/recovery.
A catalog error means “could not check,” not “up to date.”

A hash served by the publisher is integrity metadata, not an independent
signature. Signed catalogs, runtime permission enforcement, generalized receipts
and dynamic installer discovery are outside v1. See
[legacy compatibility](legacy-compatibility.md) for shipped client limitations.
