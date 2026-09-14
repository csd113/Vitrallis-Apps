# Vitrallis app build guide for developers

[Documentation](docs/README.md) · [Create an app](docs/creating-apps.md) · [Testing](docs/testing.md)

Build against the official [manifest v1 package contract](docs/creating-apps.md)
and [catalog v1 contract](docs/catalog-format.md). These are the normative field,
layout, validation and publication definitions. Start by copying
[Hello Vitrallis](examples/hello-vitrallis/README.md) into `apps/<app-slug>/`.
This guide adds implementation practices without defining a second manifest.

## Establish the target

Define the app's purpose, essential screens, controls, data sources, and storage
needs before choosing its layout and dependencies.

Verify the device architecture/OS, Python version, GUI toolkit, usable display
area, input devices, app location, launcher process lifecycle, icon requirements
and writable app-data paths. The 480×272 Python/Tkinter PocketCHIP profile is a
useful starting point. Document the tested device profile and any integration
limits. Use the platform's documented APIs and configuration.

The repository defines manifest v1; shell consumption is version-dependent.
[Runtime integration](docs/runtime-integration.md) must be verified against the
target client. A manifest alone does not register an app in a shell; App Center
handles launcher registration during installation. Changes to the Shell belong
in its own repository.

## Package and runtime

Use the canonical layout, including `manifest_version = 1`, a PNG icon,
requirements, README, dated changelog, assets, and tests. Keep identity and version
consistent with published metadata and use only the fields defined by manifest v1.

Prefer the standard library and installed toolkit. Document the exact app runtime
minimum separately from the repository tools' Python 3.11+ requirement. Tkinter
is a system prerequisite, not a pip dependency. Do not install dependencies,
services, swap or system configuration as ordinary app startup behavior.

Keep startup in `main()` behind the standard import guard. Importing modules must
not open windows, fetch data or write files. Resolve resources relative to the
script's directory. Installed packages are read-only; persistent settings/saves
belong in the validated storage locations documented in the app README.

## Interface and lifecycle

For the initial profile, inspect every screen at 480×272 and allow for shell or
window decorations. Use clear contrast, short labels and visible focus. Roughly
14–16 pixel body text and 36–44 pixel control heights are initial design targets;
verify actual toolkit font metrics and keyboard/touch usability.

Keep essential content visible without horizontal scrolling. The catalog's
keyboard baseline is mandatory: every essential workflow must work without a
pointer or touch input, including discovering controls, primary actions,
navigation, back/cancel and normal exit. Provide keyboard access with
Tab/Shift+Tab and Enter/Space, plus arrow navigation where useful. Escape should
dismiss overlays, return from subviews, then exit from the main view with
documented handling of unsaved work. Provide a visible Home/Exit action. For a
fullscreen or ambient experience, direct shortcuts are acceptable only when the
app itself makes the shortcut map discoverable.
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

Declare the capabilities the app needs. Permission flags describe requirements;
they are not an OS sandbox. Permission denial or revocation depends on support
from the target platform. Telemetry and app-managed update checks require an
explicit product decision and clear user-facing documentation.

Show the UI before network I/O and distinguish loading, ready, stale, offline and
unavailable data. Keep last-known valid samples with their age on failure. Validate
types, ranges, units, timestamps and lengths before use. Use HTTPS with certificate
verification, finite request timeouts, bounded response reads and bounded backoff; manual refresh
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

Launch from the app directory and another working directory. Exercise the complete
keyboard-only baseline first, then touch where applicable, long labels,
missing/extreme values, error messages,
startup offline, invalid responses, denied storage and corrupt saves. Verify close
during active work and repeated input. Test through the actual launcher and measure
startup and idle resource use on the target device. Record the test setup with
any performance measurements.

Include complete code, original or appropriately licensed assets, requirements,
tests, and a README. Tests must cover the keyboard-only essential paths; manual
review must confirm that tests and documentation match the actual controls.
Include a dated `CHANGELOG.md` entry matching the app version and add each
catalog addition or version update to the root changelog. Preserve release history
and run the [required changelog checks](docs/changelog-policy.md) before submitting.
App updates need matching changelogs before merging into `main`. In the pull
request, list validation results and remaining integration limits, distinguishing
desktop tests from device testing. Keep `installable: false` until the target
client and runtime have been verified. Repository licensing is currently
unresolved; confirm reuse and distribution rights with the owner.
