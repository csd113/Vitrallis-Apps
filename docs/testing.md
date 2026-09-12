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
  (Pillow with ImageTk support).
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

## Run the complete working-tree checks

On a graphical desktop, run this block directly. On headless Linux, first start
an Xvfb-backed shell with `xvfb-run -a sh`, run the block in that shell, then `exit`.
Each suite runs in a separate Python process, as in CI, so app modules with the
same names do not interfere with one another.

```sh
(
  set -eu
  export PYTHONDONTWRITEBYTECODE=1
  export VITRALLIS_REQUIRE_GUI=1
  python3 tools/validate_catalog.py --catalog apps.json --package examples/hello-vitrallis
  python3 -m unittest discover -s tools/tests -v
  python3 -m unittest discover -s examples/hello-vitrallis/tests -v
  for package in apps/*; do
    [ -e "$package" ] || [ -L "$package" ] || continue
    python3 tools/validate_catalog.py --package "$package"
    python3 -m unittest discover -s "$package/tests" -v
  done
  PYTHONPYCACHEPREFIX="$(mktemp -d)/vitrallis-pycache" \
    python3 -m compileall -q tools examples/hello-vitrallis
  if [ -d apps ]; then
    PYTHONPYCACHEPREFIX="$(mktemp -d)/vitrallis-pycache" \
      python3 -m compileall -q apps
  fi
  git diff --check
)
```

The loop validates and tests every directory under `apps/`, including newly added
packages; keep that directory reserved for packages. The temporary compilation
cache is outside the source and can be removed afterward.

`VITRALLIS_REQUIRE_GUI=1` makes the example and Media Carousel fail when their
GUI cannot run. Bitcoin's layout tests require Tk/display directly. Vitrallis
Debug's two GUI smoke tests use a `DISPLAY`/Windows guard and can skip on native
macOS even with Tk available. Always inspect skips rather than treating the flag
as a guarantee that every GUI test ran. Linux/Xvfb CI exercises that guard.

## Check committed release history

```sh
python3 tools/validate_changelogs.py
```

For a completed, committed feature branch, fetch the comparison branch and check
against its full commit ID:

```sh
git fetch origin main
python3 tools/validate_changelogs.py --base "$(git rev-parse origin/main)"
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
| [validate (3.11) and validate (3.13)](../.github/workflows/validate.yml) | Linux schema/catalog pins, example and every app, tooling tests, real Tk/Xvfb tests, FFmpeg/Pillow media tests, compilation, and whitespace |
| [Changelog policy](../.github/workflows/changelog-policy.yml) | Committed release histories, version increases, preserved notes, and complete publication agreement |

CI runs on pushes and pull requests without path filters. Tooling tests use
disposable Git repositories, app tests use fixtures/temporary storage, and Media
Carousel server tests bind to loopback. Report exact commands, Python/platform,
failures, and skips in the PR. Live remote availability checks, physical input,
performance, and installation/update/repair on a device are separate verification
steps described in [publishing](publishing-apps.md) and
[runtime integration](runtime-integration.md).
