# Creating a Vitrallis app

This repository defines the official **package manifest v1** contract. Shell
support is version-dependent; this specification does not assert that a particular
Vitrallis-Shell version loads TOML. Verify the runtime and launcher adapter for
your target before marking a catalog entry installable.

## Copy the known-good package

From the repository root:

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
├── assets/
│   └── greeting.txt
└── tests/
    └── test_main.py
```

Change `name`, `id` and `version` in the manifest, the window title and greeting
in code/assets, the icon, README and tests. Choose an ID under a namespace you
control, such as `org.yourproject.myapp`; do not publish the example's ID as your
own app. Keep the ID stable on future releases. The directory slug is not the ID.

## Manifest v1 (normative)

```toml
manifest_version = 1
name = "Example App"
id = "io.vitrallis.example"
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

The example is a 480×272 Tkinter window with a greeting, Home button and Escape
exit. It uses no network, audio or persistent storage. This is a desktop-testable
starting profile, not a device compatibility certification. Verify the actual
usable display area, keyboard/touch controls, runtime, launch and return-to-shell
behavior. [The developer guide](../VITRALLIS_APP_BUILD_GUIDE.md) covers responsive
UI, network failure handling and safe storage for more complex apps.

## Validate before committing

```sh
python3 tools/validate_catalog.py --package apps/my-app
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/my-app/tests -v
# Put compilation output outside the package (no publishing ignore rules).
PYTHONPYCACHEPREFIX=/tmp/vitrallis-pycache python3 -m compileall -q apps/my-app
python3 apps/my-app/main.py
```

Also launch using an absolute script path from another working directory, test
keyboard-only navigation and close behavior, and exercise relevant failures.
The validator checks data and files; it does not prove application behavior or
permissions compliance. Continue with [publishing apps](publishing-apps.md).
