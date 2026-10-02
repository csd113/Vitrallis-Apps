# Validation and testing

[Documentation](README.md) · [Contributing](../CONTRIBUTING.md) · [Publishing](publishing-apps.md)

Run commands from the repository root with Python **3.11+** and Git on Linux,
macOS, or WSL. Use a full clone: catalog validation reads pinned Git objects and
does not fetch missing history. Native Windows lacks the POSIX file-safety APIs
used by these tools.

## Set up the test environment

The catalog and changelog tools need no pip packages. Full app tests also need:

- Tkinter with Tk 8.6 and a graphical session; Linux CI uses Xvfb.
- Media Carousel's [requirements](../apps/vitrallis-media-carousel/requirements.txt)
  (Pillow with ImageTk support and qrcode).
- `ffmpeg` and `ffprobe` on `PATH` for real WebM tests. These tests skip when the
  tools are absent; CI installs them.

Use a virtual environment outside app directories if dependencies are missing:

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r apps/vitrallis-media-carousel/requirements.txt
```

Tkinter is supplied by your Python/system installation, not pip. On Debian/Ubuntu,
an administrator can install `python3-tk`, `python3-venv`, `xvfb`, and `ffmpeg`.
On macOS use a Tk-enabled Python and an active desktop. WSL needs a graphical
session or Xvfb just like headless Linux. App Center separately needs `packaging`
for dependency range checks; it is not a dependency of the repository validators.

## Scoped working-tree checks

Validate package manifests and catalog hashes globally: these checks never boot
applications. Run tooling regression tests globally as well. Runtime, GUI,
screenshot and launch tests run only for affected packages, in separate processes:

```sh
python3 tools/scoped_tests.py                       # preview local changes
python3 tools/scoped_tests.py --run                 # test local affected apps
python3 tools/scoped_tests.py --app apps/bitcoin-dashboard --run
python3 tools/scoped_tests.py --base origin/main --run
python3 -B -m unittest discover -s tools/tests -v
python3 tools/validate_catalog.py --package apps/my-app
git diff --check
```

On headless Linux, prefix the runtime command with `xvfb-run -a` and set
`VITRALLIS_REQUIRE_GUI=1 VITRALLIS_REQUIRE_EGL=1` so unavailable rendering fails
instead of silently skipping. No display is needed for scope previews or metadata
checks. An explicit `--app` adds a suite to the detected scope; it does not hide
other affected packages. Untracked files are included during local development.

The selector discovers packages from manifests. Code, runtime assets, dependency
requirements and tests select their owning package. README/changelog/license,
manifest and icon changes require package/asset checks without booting apps.
Python imports are followed transitively to local shared modules; Cargo path
dependencies select their dependents. Dynamic loading or shared non-code assets
must declare repository-relative dependencies in an app-local
`test-dependencies.json` JSON array. Invalid dependencies or unparseable Python
fail the scope check. Deleted files and both sides of renames remain changes.
There is no hard-coded application list. Tooling or CI edits alone do not imply
that application runtimes changed; their regression tests remain global.

Selected Rust packages receive formatting, strict Clippy and Cargo tests, with
build output outside their package. The Rust example additionally builds and
launches its host staged payload only when selected. CI preserves global schema,
catalog pins, package checks, tooling tests, compilation and whitespace checks.
CI skips graphical prerequisites and application dependency installation when
the detected runtime scope is empty. Compare pull requests against the merge
base of their base SHA and pushes against their predecessor;
a first push uses the empty tree. Review the printed runtime scope in CI.

Do not use a generic loop to boot all apps for single-app development. Desktop
checks cannot establish PocketCHIP scanout, performance or device compatibility.

## Check committed release history

```sh
python3 tools/validate_changelogs.py --source-repo "csd113/Places=/path/to/Places"
```

For a completed, committed feature branch, fetch the comparison branch and check
against its full commit ID:

```sh
git fetch origin main
python3 tools/validate_changelogs.py --source-repo "csd113/Places=/path/to/Places" --base "$(git rev-parse origin/main)"
```

`--base` must be an ancestor of the checked head. If `origin/main` has advanced
beyond your branch, bring the branch up to date before the final check.
The changelog checker reads **committed Git objects**, including `apps.json`,
package files, and root history. It does not validate uncommitted release edits.
Local `--package` validation does read working files and checks app changelog
format/version, but does not establish publication agreement. See the
[submission sequence](changelog-policy.md#submission-sequence).

## Fast checks while developing

Replace `apps/my-app` with the package being changed:

```sh
python3 tools/validate_catalog.py --package apps/my-app
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/my-app/tests -v
```

For every production package, the test suite must include meaningful coverage of
its [keyboard-only baseline](creating-apps.md#keyboard-baseline-catalog-acceptance-requirement): discovery of controls, essential actions, navigation or back/cancel,
and normal exit as applicable. Automated tests cannot decide whether an interface
is semantically usable, so reviewers must also exercise and verify the documented
key-only path before accepting an App Center submission.

For a display-free example check:

```sh
python3 examples/hello-vitrallis/main.py --check
```

Keep compilation output and virtual environments outside app packages. Git ignore
rules do not define the installed inventory; committed files outside app-local
`tests/` ship, and working-tree validation inspects the complete source directory.

## What CI verifies

| Check | Scope |
| --- | --- |
| [validate (3.11) and validate (3.13)](../.github/workflows/validate.yml) | Global schema/catalog/package checks, tooling tests and compilation; affected app Tk/Xvfb, media and Rust suites |
| [Changelog policy](../.github/workflows/changelog-policy.yml) | Committed release histories, version increases, preserved notes, and complete publication agreement |

CI runs on pushes and pull requests without path filters. Tooling tests use
disposable Git repositories, app tests use fixtures/temporary storage, and Media
Carousel server tests bind to loopback. Report exact commands, Python/platform,
failures, and skips in the PR. Live remote availability checks, physical input,
performance, and installation/update/repair on a device are separate verification
steps described in [publishing](publishing-apps.md) and
[runtime integration](runtime-integration.md).

## Experimental Rust build checks

Run `cargo fmt --all --check`, the strict Clippy command below, and
`cargo test --workspace --all-features` from `examples/hello-rust`. Set
`CARGO_TARGET_DIR` outside the package for compilation and tests:

```sh
cargo clippy --workspace --all-targets --all-features -- -D warnings -D clippy::all -D clippy::pedantic -D clippy::nursery -D clippy::cargo
```

Use `tools/build_rust_app.py` for a fresh staged target package and launch its
Python supervisor on that target. Cross-compilation alone does not validate a
foreign architecture at runtime. See [experimental Rust](experimental-rust.md).

## Native Rust application checks

For each app containing `Cargo.toml`, run the same format, strict Clippy and Cargo
test commands above with `CARGO_TARGET_DIR` outside the package. Install the
host development dependencies documented by that app. Package validation checks
the shipped target ELF independently from host tests. Device presentation and
performance remain separate from host tests.
