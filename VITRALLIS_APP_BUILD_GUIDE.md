# Vitrallis app build guide for developers

[Documentation](docs/README.md) · [Create an app](docs/creating-apps.md) · [Testing](docs/testing.md)

Build against the official [manifest v1 package contract](docs/creating-apps.md)
and [catalog v1 contract](docs/catalog-format.md). These are the normative field,
layout, validation and publication definitions. Start by copying
[Hello Vitrallis](examples/hello-vitrallis/README.md) into `apps/<app-slug>/`.
This guide adds implementation practices without defining a second manifest.

## Establish the target

Extract purpose, essential screens, controls, data sources and persistence needs
from the requested app. Resolve routine choices conservatively; state assumptions
and ask only for missing information that prevents correct integration.

Verify the device architecture/OS, Python version, GUI toolkit, usable display
area, input devices, app location, launcher process lifecycle, icon requirements
and authorized storage paths. The 480×272 Python/Tkinter PocketCHIP profile is a
useful starting point, not evidence that every Vitrallis installation supports it.
When device integration cannot be checked, label the prototype profile and report
what remains unverified. Do not invent SDKs, environment variables or permission APIs.

The repository defines manifest v1; shell consumption is version-dependent.
[Runtime integration](docs/runtime-integration.md) must be verified against the
target client. A manifest alone does not register an app in a shell. Do not change the shell just to register an app without authorization.

## Package and runtime

Use the canonical layout, including required `manifest_version = 1`, the real PNG
icon, requirements, README, dated changelog, assets and tests. Keep identity/version consistent
with published metadata. No speculative manifest fields belong in v1.

Prefer the standard library and installed toolkit. Document the exact app runtime
minimum separately from the repository tools' Python 3.11+ requirement. Tkinter
is a system prerequisite, not a pip dependency. Do not install dependencies,
services, swap or system configuration as ordinary app startup behavior.

Keep startup in `main()` behind the standard import guard. Importing modules must
not open windows, fetch data or write files. Resolve resources relative to the
script's directory. Installed packages are read-only; persistent settings/saves
belong only in documented, validated storage locations. Each app must document its own storage requirements.

## Interface and lifecycle

For the initial profile, inspect every screen at 480×272 and allow for shell or
window decorations. Use clear contrast, short labels and visible focus. Roughly
14–16 pixel body text and 36–44 pixel control heights are initial design targets;
verify actual toolkit font metrics and keyboard/touch usability.

Keep essential content visible without horizontal scrolling. Provide keyboard
access with Tab/Shift+Tab and Enter/Space, plus arrow navigation where useful.
Escape should dismiss overlays, return from subviews, then exit from the main
view with documented handling of unsaved work. Provide a visible Home/Exit action.
Return through the documented launcher lifecycle; do not launch another desktop.
Do not force fullscreen without shell policy. Touch activation should cancel when
the pointer leaves the target before release. Restore focus after closing dialogs.

Perform Tk operations only on the main thread. Put blocking work in bounded
workers with queued results and scheduled UI callbacks. Prevent duplicate requests
and windows. Bound queues, history and decoded images; redraw on relevant changes
or use a capped game frame rate. Use monotonic time for durations/retries.
On exit, cancel callbacks, stop accepting worker results and release resources
within a bounded policy. Never block the GUI indefinitely waiting for a worker.

## Network and storage

Use capabilities only when requested and declared. Permission flags declare
requirements; they are not an OS sandbox. Integrate denial/revocation only through
an actually documented platform mechanism. Do not add telemetry or update checks
unless requested.

Show the UI before network I/O and distinguish loading, ready, stale, offline and
unavailable data. Keep last-known valid samples with their age on failure. Validate
types, ranges, units, timestamps and lengths before use. Use verified HTTPS,
finite request timeouts, bounded response reads and bounded backoff; manual refresh
must respect active work and rate limits. A socket timeout is not necessarily a
total deadline. Keep independent sources independently recoverable. Never forward
credentials across untrusted redirects or include them in logs/screenshots.

Use documented app-private storage. If conventional XDG paths are a fallback,
label and validate that assumption, including environment-provided paths. Separate
saves/settings from caches; keep rapidly changing state in memory and debounce
writes to reduce flash wear. Do not assume a path is RAM-backed merely from its name.
Reject unsafe paths, links, nonregular files, oversized or malformed data before
use. Stage important writes in the destination directory and atomically replace
after success; flush/fsync where durability requires it. Preserve the previous
valid save on failure and tell the user when a change is only in memory. Do not
persist through another path when storage is disabled or denied.

## Validate and deliver

Follow [CONTRIBUTING.md](CONTRIBUTING.md) for the exact repository checks and
[publishing apps](docs/publishing-apps.md) for commit-based catalog generation.
App tests should cover real behavior and failure modes with mocked network calls
and temporary storage, not live service dependencies. Compile all source modules
with bytecode redirected outside the package, validate the manifest/files/icon,
and run the complete app test suite.

Launch from the app directory and another working directory. Exercise keyboard,
touch where applicable, long labels, missing/extreme values, error messages,
startup offline, invalid responses, denied storage and corrupt saves. Verify close
during active work and repeated input. Test through the actual launcher and measure
startup/idle resource use when the target is available; do not invent guarantees.

Deliver complete code, original/authorized assets, requirements, tests and README.
Include a dated `CHANGELOG.md` entry matching the app version and add each
catalog addition or version update to the root changelog. Preserve release history
and run the [required changelog checks](docs/changelog-policy.md) before submitting.
App updates without proper changelog entries must not be merged into `main`.
Report files changed, exact checks/results and remaining integration limits.
Desktop or skipped GUI tests must not be reported as device verification. Keep
`installable: false` until the consuming client/runtime adapter is verified.
Never add an assumed license; record licensing as an owner decision if unresolved.
