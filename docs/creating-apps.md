# Creating a Vitrallis app

[Documentation](README.md) · [Testing](testing.md) · [Publishing](publishing-apps.md)

This repository defines the official **package manifest v1** contract. The current
Vitrallis Shell App Center consumes this format; support in older or other clients
is version-dependent. Verify the runtime and launcher on your target before
marking a catalog entry installable. See [runtime integration](runtime-integration.md).

## Copy the known-good package

From the repository root, choose a new directory name that does not already exist:

```sh
mkdir -p apps
cp -R examples/hello-vitrallis apps/my-app
```

```text
apps/my-app/
├── app.toml
├── icon.png
├── main.py
├── requirements.txt
├── README.md
├── CHANGELOG.md
├── assets/
│   └── greeting.txt
└── tests/
    └── test_main.py
```

Change `name`, `id` and `version` in the manifest, the window title and greeting
in code/assets, the icon, README, changelog and tests. Replace the example's
changelog with your app's dated initial release; follow the
[changelog and merge policy](changelog-policy.md). Choose an ID under a namespace you
control, such as `org.yourproject.myapp`; do not publish the example's ID as your
own app. Keep the ID stable on future releases. The directory slug is not the ID.

## Manifest v1 (normative)

```toml
manifest_version = 1
name = "Example App"
id = "org.yourproject.myapp"
version = "0.1.0"
runtime = "python"
entry = "main.py"

[permissions]
network = false
audio = false
storage = false
```

All seven top-level keys are required, including integer `manifest_version = 1`.
Only the shown keys are accepted in v1; reject unknown keys/versions, duplicate
TOML assignments, extra permission keys and incorrect types. Future extensions
require an explicit contract revision; do not add speculative SDK fields.

- `name` is nonempty display text, up to 1,000 characters, without controls.
- `id` is a stable lowercase reverse-domain identifier: at least two components,
  each starting with a letter and containing only lowercase letters/digits;
  at most 128 characters. Example: `org.yourproject.myapp`.
- `version` is stable SemVer `MAJOR.MINOR.PATCH`, no leading zeroes, prefix,
  prerelease or build suffix; at most 32 characters.
- `runtime` is exactly `python`. The README states the supported Python/toolkit
  versions; the tools' Python 3.11 minimum is not the app's minimum.
- `entry` is a safe app-relative path to a published `.py` file. Use `main.py`
  normally. Absolute paths, traversal, backslashes, arguments and shell commands
  are invalid. `main.py` remains part of the canonical package even with a custom entry.
- `permissions` declares boolean network/audio/storage **requirements only**.
  It does not implement sandboxing, grant consent or establish platform enforcement.
  False means the app must not use that capability. Microphone access has no v1 contract.

The canonical layout requires all shown files and both populated directories.
An otherwise empty `assets/` should contain a README so Git retains it; `tests/`
should contain meaningful app tests. `requirements.txt` may state that no pip
dependencies are needed. Tkinter is a system prerequisite, not a pip dependency.
`CHANGELOG.md` is required and shipped with the app. Its newest dated version
must match `app.toml`, with concrete change bullets; package validation rejects
missing, stale, empty or placeholder release entries.

`icon.png` is the conventional icon. The repository publication profile accepts
noninterlaced PNGs from 1×1 through 512×512 pixels, validates chunk CRCs and bounded
pixel decompression, and recommends 128×128. These dimensions are package
validation limits, not evidence of a shell icon API. Confirm actual launcher
requirements separately. Include original or authorized artwork with attribution.

## Runtime behavior

Resolve resources from `Path(__file__).resolve().parent`; never depend on the
caller's working directory. Importing app code must not start a window, network
request or write. Put startup under `if __name__ == "__main__":`.

Treat installed package directories as read-only. Document any storage locations
and permission behavior in the app README. Use verified app-private platform paths;
if using XDG locations as a fallback, label that assumption, validate externally
supplied paths and use atomic writes. Do not persist when storage is false. Keep
rapidly changing data in memory and avoid unnecessary flash writes.

## Keyboard baseline (catalog acceptance requirement)

Every production app submitted to this catalog **must be baseline usable using
only physical keyboard input**. This is an acceptance rule for App Center
catalogue listings and for enabling installation; touch, mouse and stylus support
are enhancements, never the only path to an essential action.

At a minimum, a keyboard-only user must be able to launch the app, discover the
available controls, reach and operate its primary experience, navigate between
essential screens or modes, dismiss errors/overlays, cancel or go back, and exit
through the normal launcher lifecycle. Controls must have a visible focus state
where focus applies. Use Tab/Shift+Tab and Enter/Space for standard controls,
arrow keys where they fit the layout, and a documented Escape/back sequence.
An ambient or fullscreen app may use direct shortcuts instead, but it must show
or otherwise clearly document those shortcuts from within the app.

Document the complete keyboard map in the app README and add meaningful
keyboard-focused regression tests for the essential paths. Manifest v1 has no
keyboard capability field; a new manifest key is invalid rather than a way to
opt out. The package validator checks structure, not interaction semantics, so
reviewers must reject a submission that lacks this evidence.

The example is a 480×272 Tkinter window with a greeting, Home button and Escape
exit. It uses no network, audio or persistent storage. This is a desktop-testable
starting profile, not a device compatibility certification. Verify the actual
usable display area, the required keyboard-only baseline, touch controls where
provided, runtime, launch and return-to-shell behavior. [The developer guide](../VITRALLIS_APP_BUILD_GUIDE.md) covers responsive
UI, network failure handling and safe storage for more complex apps.

## Validate before committing

```sh
python3 tools/validate_catalog.py --package apps/my-app
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/my-app/tests -v
# Keep compilation output outside the package; Git ignore rules do not filter publication.
PYTHONPYCACHEPREFIX=/tmp/vitrallis-pycache python3 -m compileall -q apps/my-app
python3 apps/my-app/main.py
```

Also launch using an absolute script path from another working directory, test
the complete keyboard-only baseline and close behavior, and exercise relevant
failures.
The validator checks data and files; it does not prove application behavior or
permissions compliance. Continue with [publishing apps](publishing-apps.md).
