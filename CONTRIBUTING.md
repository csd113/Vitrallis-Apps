# Contributing

Start with [the repository overview](README.md), then [create an app](docs/creating-apps.md)
or read [the catalog format](docs/catalog-format.md). Keep changes focused and
preserve stable application IDs. All apps belong in lowercase `apps/<app-slug>/`
and follow the native manifest v1 contract.

## Pre-release compatibility policy

Vitrallis is pre-release. Do not preserve compatibility with obsolete pre-release
layouts, APIs, manifests, paths, behaviors or implementation details unless
compatibility is explicitly requested for the change. Update all affected code
to the current canonical design and delete superseded code instead of adding
compatibility layers, fallbacks, aliases, adapters, dual paths, deprecated formats
or migration shims. This rule applies to contributors and coding agents.

No repository-wide license has been established. Ask the owner to confirm licensing
and imported content rights; do not add a guessed license or license metadata.
Do not commit credentials, caches, device runtimes or generated build artifacts.

## Checks before review

Use Python 3.11+ and Git on Linux, macOS or WSL for tools (standard library only).
The file-safety checks use POSIX no-follow/nonblocking APIs. Tkinter is needed for
GUI tests. Run from the repository root:

```sh
python3 tools/validate_catalog.py --catalog apps.json --package examples/hello-vitrallis --package apps/bitcoin-dashboard
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s examples/hello-vitrallis/tests -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/bitcoin-dashboard/tests -v
PYTHONPYCACHEPREFIX=/tmp/vitrallis-pycache python3 -m compileall -q tools examples/hello-vitrallis apps
git diff --check
```

Validate every new native app with `--package apps/<slug>` and run its own tests.
The workflow discovers, validates and runs tests for every native package.
For display tests, use a graphical desktop or Linux `xvfb-run -a`; with
`VITRALLIS_REQUIRE_GUI=1` the example tests fail rather than skip if Tk/display is
missing. CI sets this flag and uses Xvfb. Desktop tests are not device validation.

When changing validators, add failing cases for malformed metadata, path/file
hazards and the changed invariant, plus a successful publishing flow. The tooling
tests create disposable Git repositories and commits as fixtures; they never
commit to the working repository or use the network. Keep schema and validator
vocabulary synchronized; unknown schema keywords must fail closed.

## Publication review

Use [the two-commit publication workflow](docs/publishing-apps.md). Source must be
committed and pushed before the catalog advertises it. Review generated metadata,
check remote availability, and enable installation only after verifying client
runtime/adapter support. Do not republish changed bytes under the same version.
The example is a template and does not belong in the production catalog.

A review should state what changed, files affected, validation results and any
remaining integration/device limits. Never claim a shell
loader, permission sandbox or generalized installer exists because the package
specification defines metadata for it.
