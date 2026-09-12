# Contributing to Vitrallis Apps

Help make small-screen apps useful and pleasant to use. Documentation fixes,
reproducible bug reports, app improvements, and device verification reports are
all welcome. Start with the [overview](README.md) and [documentation index](docs/README.md).
For usage help see [Support](SUPPORT.md); report vulnerabilities using
[Security](SECURITY.md). Follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Choose the right place

| Change | Location |
| --- | --- |
| New app or app fix | `apps/<app-slug>/`, with its own README, changelog, assets, and tests |
| App template | `examples/hello-vitrallis/`; keep it small and outside the production catalog |
| Format, publication, or onboarding docs | `docs/` and the root documentation |
| Catalog entry | `apps.json`, generated through `tools/update_catalog.py` |
| Validator or publication tooling | `tools/`, with regression tests in `tools/tests/` |
| Shell launcher, App Center, or installer behavior | [Vitrallis Shell](https://github.com/csd113/Vitrallis-Shell) |

For larger features or new dependencies, describe the use case in an issue first
so scope and device constraints can be discussed. Small fixes can go straight to
a pull request. Keep changes focused and do not overwrite another contributor's work.

## Create or update an app

1. Work on a feature branch. Copy `examples/hello-vitrallis/` into lowercase
   `apps/<app-slug>/` for a new app; use an ID in a namespace you control.
2. Follow the [manifest v1 contract](docs/creating-apps.md). Include `app.toml`,
   `main.py`, `icon.png`, `requirements.txt`, `README.md`, `CHANGELOG.md`, and
   populated `assets/` and `tests/`. Preserve an existing app's stable ID.
3. Document Python/toolkit requirements, controls, storage locations, declared
   permissions, and known device limits in the app README. Prefer existing
   dependencies or the standard library. Do not install system dependencies at
   app startup or treat permission flags as a sandbox.
4. Validate and test the working package using [the testing guide](docs/testing.md).
   Exercise relevant failure modes and launch from another working directory.
5. Complete release notes and publication before submitting an app release.

Do not commit credentials, caches, device runtimes, or generated build artifacts.
All committed app files outside `tests/` are published, including documentation.
No repository-wide license has been established; ask the owner to confirm
licensing and imported content rights, and do not add guessed license metadata.

## Version and changelog requirements

Follow the [changelog and merge policy](docs/changelog-policy.md):

- Every app and the example need dated, concrete release notes whose newest
  version matches `app.toml`. Preserve existing release history.
- Increase the app version for **any shipped-file change**, including app READMEs,
  artwork, requirements, and changelogs. Keep versions displayed in code aligned.
- App-local test-only changes do not alter installed packages and do not require
  a release. Root/docs/community changes outside packages also do not require an
  app version bump or a fabricated catalog release entry.
- Record each newly added or updated catalog version in root `CHANGELOG.md`.
  Keep the README's available-app table aligned with catalog membership and link
  each production app to its README; avoid duplicating version numbers there.

The **Changelog policy** check verifies committed package/catalog agreement and
release history. Reviewers must also check that the notes explain the real change.

## Validation before review

Use Python **3.11+** and Git on Linux, macOS, or WSL. The tools use only the standard
library and POSIX file-safety APIs; native Windows is not supported. App tests
add Tkinter, a graphical session, and the dependencies described in
[testing](docs/testing.md). That guide contains the complete commands for every
package, tooling and example tests, compilation, and whitespace checks.

For one package, start with:

```sh
python3 tools/validate_catalog.py --package apps/my-app
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/my-app/tests -v
```

Then run the full repository checks. CI uses Python 3.11 and 3.13, Linux/Xvfb,
Tkinter, Pillow, and FFmpeg. Report skipped tests and host-specific failures;
desktop success does not establish device compatibility.

When changing validators, add malformed-metadata and path/file-hazard cases for
the changed invariant, plus a successful publishing flow. Keep schema and
validator vocabulary synchronized; unsupported schema keywords must fail closed.
Tooling tests create commits only in disposable fixture repositories and do not
use the network.

## Publish the catalog entry

Follow [publishing apps](docs/publishing-apps.md): commit and push the tested app
source first, then generate the catalog entry from that full commit. Review its
inventory, verify remote availability, add the root release record, and commit
the catalog on the same feature branch. The updater previews by default and does
not commit, push, install, or fetch source.

Enable installation only after checking the target runtime, installer, launcher,
update, and repair paths. Submit source and catalog together in a pull request.
Keep the source commits when merging so a fresh clone can resolve every pin.
Do not republish different bytes under the same version.

## Pull request expectations

Explain the problem, resulting behavior, affected apps or documents, and commands
run with their results. For UI changes include useful screenshots and the tested
display size; for device claims include OS/runtime, app and Shell versions, and
what was actually exercised. Remove secrets and private information from evidence.
Mark release-only checklist items as not applicable for documentation-only PRs.

App releases must include matching changelogs and catalog inventories before
merge. Required checks are **Changelog policy**, **validate (3.11)**, and
**validate (3.13)**, with an up-to-date branch and a pull request. See the
[merge policy](docs/changelog-policy.md) for details. Coding agents must also follow
any local agent instructions; submission instructions do not authorize commits or
publication beyond the user's request.

## Pre-release compatibility policy

Vitrallis is pre-release. Do not preserve compatibility with obsolete pre-release
layouts, APIs, manifests, paths, behaviors or implementation details unless
compatibility is explicitly requested for the change. Update all affected code
to the current canonical design and delete superseded code instead of adding
compatibility layers, fallbacks, aliases, adapters, dual paths, deprecated formats
or migration shims. This rule applies to contributors and coding agents.
