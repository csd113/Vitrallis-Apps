# Hello Rust (experimental)

A display-free packaging example. It prints a bundled greeting and exits; it is
not a production catalog entry. Python remains the manifest v1 runtime and runs
a small supervisor; the application itself is a precompiled Rust executable.
The device needs Python 3.8+ and the target's normal system C runtime, but never
Cargo or a Rust toolchain. There are no pip dependencies, network, audio, or
persistent writes. The icon and greeting ship through the normal catalog inventory.

Build into a fresh staging directory with `tools/build_rust_app.py`; see
[experimental Rust support](../../docs/experimental-rust.md). Staging adds
`bin/<target>/app` in executable mode. Do not publish this source example without
its compiled payload. Use `python3 /absolute/package/main.py` from any working
directory. Unsupported systems and invalid/missing binaries fail with a clear error.
The Python supervisor forwards SIGTERM/SIGINT/SIGHUP to the child process group
and waits for exit, preserving App Center update/uninstall process detection.

Graphical derivatives must compose complete backbuffer frames and synchronize
presentation to VSync/vblank as required by the rendering contract. This console
probe has no window, controls, rendering loop, or graphical compatibility claim.
