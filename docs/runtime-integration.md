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
Its catalog entry remains `installable: false` until native client integration
has been verified. Desktop tests do not certify PocketCHIP installation.

Client implementation changes belong in the consuming client's repository and
must be reviewed there. Do not infer native support from an older client's
ability to run a particular app.
