# Vitrallis app build guide for AI developers

Use this document as the development brief for a Vitrallis Python application. Follow it alongside the requested app features and the actual Vitrallis shell documentation or source code.

## 1. Your assignment

Build a complete, lightweight application that Vitrallis can discover and launch through its manifest. Deliver runnable code, assets, dependency declarations, tests, and setup instructions. Keep implementation focused on the requested features. Do not change the Vitrallis shell merely to register an app.

Before building, extract the app's purpose, essential screens, controls, data sources, and persistence needs from the user's request. State any assumptions briefly. Resolve routine design choices yourself; ask only about missing information that prevents correct integration or materially changes the requested behavior.

## 2. What is established, and what needs verification

The platform owner's supplied application contract is:

- An app is a directory containing `app.toml`, `icon.png`, `main.py`, `requirements.txt`, and `assets/`.
- The Python manifest identifies the app, its version, runtime, entry point, and network/audio/storage permissions.
- App registration should not require changes to the shell.
- Description, author, license, minimum Vitrallis version, display settings, and hardware declarations are possible future manifest fields.

The rest of this guide defines recommended development conventions. It does **not** establish that the Vitrallis shell already implements them.

Use the PocketCHIP reference as the initial hardware profile: a small 480 × 272 landscape interface and a lightweight Python/Tkinter implementation. Its documentation describes background updates, keyboard and touch controls, and RAM caching to reduce flash writes. These are useful design examples, not proof that Vitrallis supports the same GUI runtime or launch mechanism. [Reference README](https://github.com/csd113/PocketChip-Bitcoin-Display/blob/9d732e056801c8a98ee3edb60cb5bd88646ac467/README.md)

Before claiming platform compatibility, verify:

| Integration detail | Required evidence |
| --- | --- |
| Target hardware and OS | Device architecture, display dimensions, usable app area, available input devices |
| Python runtime | Exact supported Python version and interpreter selection |
| GUI support | Installed toolkit/version and graphical session/backend |
| App discovery | App install location and manifest schema accepted by the shell |
| Launch and exit | Entry-point resolution, working directory, process lifecycle, return-to-shell behavior |
| Storage | Authorized settings/save/cache paths and permission behavior |
| Resources | Available memory/storage and any platform limits |
| Icons | Required image dimensions, transparency, and file-size constraints |

If this information is unavailable, proceed with an explicitly labeled prototype profile. Keep integration choices isolated and report what remains unverified. Never invent a Vitrallis SDK, environment variable, callback, installation path, or permission API.

## 3. Application package

```text
my-app/
├── app.toml
├── icon.png
├── main.py
├── requirements.txt
├── README.md
├── assets/
│   └── ...
└── tests/
    └── test_app.py
```

The manifest, icon, entry point, requirements file, and assets directory are the owner's supplied structure. README and tests are deliverables required by this guide. Add modules only when they improve clarity; a small app can remain in `main.py`. Include the `assets/` directory even when initially empty, using a small README if the packaging system omits empty directories.

- `main.py`: application entry point. Put startup in `main()` behind `if __name__ == "__main__":`. Importing modules must not open windows, perform network requests, or write files.
- `icon.png`: a real, valid PNG, included in the package. If no icon specification exists, use a provisional 128 × 128 image and label that choice in the README. Verify it in the launcher when available.
- `requirements.txt`: pip-installable runtime dependencies only. It may contain just `# No third-party Python dependencies.`
- `assets/`: packaged images, sounds, fonts, and other immutable resources. Include only assets with known usage rights and record attribution where required.
- `README.md`: target profile, installation and launch instructions, controls, permissions, data locations, validation results, and remaining limitations.

Resolve bundled resources relative to the app's location, never the caller's working directory:

```python
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ASSETS_DIR = APP_DIR / "assets"
```

Treat the installed app directory as read-only. Do not store settings, saves, logs, downloaded files, or caches beside the application code.

## 4. Manifest

Use valid TOML with one assignment per line. This example describes an offline app that saves state:

```toml
name = "Dungeon Box"
id = "io.vitrallis.dungeonbox"
version = "0.1.0"
runtime = "python"
entry = "main.py"

[permissions]
network = false
audio = false
storage = true
```

Replace the example name and ID with the requested application's identity. Keep its ID stable across releases. Prefer a lowercase reverse-domain identifier as a naming convention. Use semantic versions and keep any displayed version consistent with the manifest.

The entry must resolve to a file inside the app directory. Do not use absolute paths, parent traversal, shell commands, or command-line arguments in `entry`.

Declare only capabilities actually used:

| Permission | Convention used by this guide |
| --- | --- |
| `network` | Outbound network access, including APIs, downloads, and telemetry |
| `audio` | Sound playback; microphone access requires a separately verified platform contract |
| `storage` | App-managed filesystem writes, including persistent settings/saves and file-backed caches |

Reading bundled assets and holding state in process memory do not require storage under this proposed interpretation. Verify these semantics against the real shell. A manifest declaration alone does not establish OS-level enforcement or sandboxing. Do not claim otherwise.

When a capability is disabled, the app must not use it. If Vitrallis exposes runtime grants or revocation, integrate with that documented mechanism and handle denial gracefully.

These are **proposed future fields**. Add them to a shipping manifest only after verifying shell support. If used, top-level metadata belongs before the first table header:

```toml
# Proposed top-level metadata; place before [permissions].
description = "An autonomous dungeon simulation."
author = "Your name"
license = "MIT" # Use only if this is the actual project license.
minimum_vitrallis = "0.3.0" # Example only; verify the actual minimum.

[display]
fullscreen = true
orientation = "landscape"

[hardware]
touch = false
keyboard = true
audio = false
```

Do not infer the meaning of hardware flags. The shell must define whether they indicate supported controls, mandatory hardware, or something else. For an unsupported schema, document these needs in the README.

## 5. Runtime and dependencies

- Prefer the standard library and toolkit already available on the device.
- Tkinter is the first candidate for compact dashboards and utilities when the target supports it. For games, use a different toolkit only when its rendering/input needs justify it and device compatibility is verified.
- Avoid heavyweight browser runtimes and large frameworks for this hardware profile unless explicitly required.
- Do not require a newer Python version simply because it exists on the development computer. Match syntax and dependencies to the target interpreter.
- Tkinter is a system/runtime prerequisite, not a pip requirement. Document missing system packages separately; never auto-install them at app startup.
- Do not copy the reference repository's private runtime layout or launcher paths into a generic Vitrallis app. Use Vitrallis's verified runtime contract.
- Never require root, modify the shell, install services, alter swap, or change global system configuration as ordinary app behavior.

## 6. Interface and input

For the provisional PocketCHIP profile, design and inspect every screen at **480 × 272**. Account for any space reserved by the shell or window decorations. Desktop screenshots at larger sizes do not establish device usability.

- Keep essential content and actions visible without horizontal scrolling.
- Use clear contrast, short labels, visible focus, and readable text. Prefer fewer elements over shrinking text until it fits.
- As initial design targets, use roughly 14–16 pixel body text and 36–44 pixel control heights; verify actual font metrics and touch usability on the device.
- Support keyboard access to every essential action. Use Tab/Shift+Tab for focus and Enter/Space for activation; add arrow navigation where appropriate.
- Escape closes the active overlay first, then returns from a subview, then exits from the main screen. Preserve unsaved user work through the app's documented save/discard behavior.
- Provide a visible Home or Exit action. Return to the shell through its documented lifecycle; do not launch another shell or desktop session.
- If touch is supported, use sufficiently spaced targets and avoid hover-only interactions. Cancel a tap action when the pointer moves off the target before release.
- Keep dialogs inside the available app area and restore focus when they close.
- Test long labels, missing values, large numbers, empty lists, and error messages for clipping and overlap.

Fullscreen must follow shell policy; do not force it simply because a proposed manifest field mentions it.

## 7. Responsiveness and lifecycle

Keep the UI responsive during startup, fetching, parsing, saving, and shutdown.

For Tkinter, perform GUI operations on the main thread. Run blocking work in bounded workers, send results through a queue, and process them using scheduled callbacks. The reference source demonstrates this pattern along with selective redraws and input validation. Adapt the approach to the app's needs instead of copying its domain-specific implementation. [Reference source](https://github.com/csd113/PocketChip-Bitcoin-Display/blob/9d732e056801c8a98ee3edb60cb5bd88646ac467/bitcoin.py)

- Prevent duplicate work when users repeatedly press a button.
- Bound worker counts, queues, retained history, and image sizes.
- Redraw when visual state changes. For games, use a capped update/render rate chosen for the device; avoid busy loops.
- Use monotonic time for elapsed durations and retry schedules; use wall-clock time for human-readable timestamps.
- On exit, cancel scheduled callbacks, stop accepting results, release audio/files, and stop owned work within a bounded shutdown policy. Do not block the GUI indefinitely waiting for a worker.
- Respect the actual launcher's termination mechanism. Add signal handling only where appropriate for the verified runtime; never make GUI calls directly from background workers.
- Report startup failures clearly, without a traceback as the only user guidance. Send useful diagnostics to stderr without leaking secrets.

## 8. Network behavior

Apply this section only when network access is requested and declared.

- Show the initial UI before waiting for the network. Display distinct loading, ready, stale, offline, and unavailable states where relevant.
- Use HTTPS with certificate verification. Never bypass certificate checks to accommodate an old device; document clock or CA setup problems.
- Set finite request timeouts and response-size limits. Understand the HTTP client's timeout behavior; do not describe a socket timeout as a guaranteed total deadline.
- Validate types, ranges, units, timestamps, and collection lengths before display or storage.
- Use bounded retry backoff and honor provider rate limits. Manual refresh must not bypass an active request or retry protection.
- Keep last-known valid data during temporary failures, clearly labeled with its age. Do not replace it with invalid or older samples.
- Keep independent data sources independently recoverable where useful.
- Keep credentials out of source, manifests, URLs, logs, and screenshots. Use the platform's documented secret/configuration mechanism and restrict credential forwarding across redirects.
- Do not add analytics, advertising, update checks, or background telemetry unless requested.

## 9. Storage and flash wear

Use documented app-private Vitrallis locations when available. If the platform has no storage API and conventional Linux paths are appropriate, propose per-app XDG config/data/cache directories and document this as a fallback requiring integration verification. Validate environment-provided paths before use.

- Separate durable user saves/settings from expendable cached data.
- Keep rapidly changing state in memory. Use file-backed RAM caching only when the runtime directory is verified safe and actually memory-backed; a path name alone is not proof.
- Save preferences when they change. Debounce or checkpoint game saves according to recovery needs. Do not write on every redraw, poll, or frame.
- Validate file type, size, ownership where applicable, and parsed content. Reject unsafe paths and links at sensitive boundaries; do not let a FIFO or malformed file hang startup.
- Write important state through a temporary file in the same directory and atomically replace the destination after successful writing. Use flushing/fsync when crash durability is required. Preserve the previous valid save if preparation fails.
- Recover safely from missing/corrupt settings and communicate failures to save. Never claim a change is persistent when it only exists in memory.
- If storage is disabled or denied, use a session-only mode where practical and explain its behavior. Do not silently persist through an alternate location.

## 10. Validation and delivery

Implement meaningful automated tests for the app's logic and failure modes using temporary data and mocked network calls. Avoid tests that depend on live services. Keep development tools separate from runtime requirements.

From the app directory, run with the selected development interpreter matching the target version:

```sh
python3 -m compileall -q main.py tests
python3 -m unittest discover -s tests -v
```

Include any additional source modules in compilation checks. Also parse `app.toml` with a real TOML parser and validate it against the shell schema when available. A Python 3.11+ development environment can use `tomllib`; this does not require raising the app's runtime minimum or adding an app dependency. Confirm the entry point exists and the packaged icon/assets decode successfully.

Before handoff, check:

- Launch from the app directory and from a different working directory.
- Launch through the actual Vitrallis shell when available.
- Exercise all screens and controls at the target resolution, including keyboard-only use.
- Test startup offline, timeout/invalid responses, unavailable audio, denied storage, and corrupt saves where those features apply.
- Confirm repeated input does not create duplicate workers or windows.
- Close during active work and confirm the process exits and control returns to the launcher.
- Measure startup, idle CPU, memory, and writes on the target when possible. Report observations rather than inventing performance guarantees.

Deliver the complete app directory with no required placeholders, absolute development paths, credentials, or bundled desktop virtual environments. Include a concise summary, files changed, exact validation commands and results, and remaining integration/device caveats. Distinguish tests actually run from tests merely recommended; skipped GUI tests are not passed GUI tests. Do not claim device validation from desktop checks alone.

## 11. App request to append when reusing this guide

```text
Build a Vitrallis app following the attached Vitrallis app build guide.

App name:
App ID:
Purpose:
Essential features:
Screens or visual direction:
Input devices:
Network/data sources:
Audio needs:
Settings or saved data:
Target hardware and OS:
Python and GUI toolkit versions, if known:
Vitrallis shell repository/docs, if available:
Other constraints:

Make reasonable choices for unspecified cosmetic details. Verify integration
against the supplied platform code or docs. If platform details are unavailable,
build a clearly labeled prototype and list the compatibility checks still needed.
Deliver the complete runnable app and report actual validation results.
```

Reference reviewed at commit `9d732e056801c8a98ee3edb60cb5bd88646ac467` on September 10, 2026. The reference's development notes provide additional examples and explicitly distinguish desktop testing from pending physical-device checks. [Development notes](https://github.com/csd113/PocketChip-Bitcoin-Display/blob/9d732e056801c8a98ee3edb60cb5bd88646ac467/docs/development.md)
