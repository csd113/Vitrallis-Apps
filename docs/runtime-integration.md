# Runtime integration

All applications in this repository follow the native manifest v1 contract in
`apps/<app-slug>`. Package validation verifies structure, metadata and pinned
bytes; it does not implement an installer or shell loader.

Before enabling a catalog entry, verify the target client's native package
installation, update and repair flow, Python/Tk runtime, manifest entry launch,
icon loading and return-to-shell behavior. Verify the supported display and
keyboard/touch controls on the target device. Permission declarations describe
requirements; they do not establish sandboxing or consent.

Bitcoin Dashboard is packaged with `main.py` and `icon.png`, and runs with system
Python 3.8+ and Tk 8.6. It has no bundled runtime or installation launcher.
Bitcoin Dashboard, Vitrallis Debug and Vitrallis Media Carousel are enabled in
the official catalog.
Open Vitrallis Shell App Center, choose Check, select one app, then Install.
On Debian, both need the system `python3-tk` package; App Center reports missing
Python/Tk prerequisites and does not install system packages automatically.
Desktop tests do not certify PocketCHIP installation.

Media Carousel requires Python 3.9+, Tk 8.6 and Pillow >=10.4,<13. App Center also
requires the installed `packaging` module to verify that Pillow version range.
On Debian, provide `python3-tk`, `python3-pil`, `python3-pil.imagetk` and
`python3-packaging`; optional `ffmpeg` (including `ffprobe`) enables muted WebM.
App Center reads the official repository's `main` catalog, and Install handles
first installation, updates and repairs. All three native apps publish an X11
process identity so the Shell can focus and resume their windows.

Client implementation changes belong in the consuming client's repository and
must be reviewed there. Do not infer native support from an older client's
ability to run a particular app.
