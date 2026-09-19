# Experimental Rust application packages

Python remains the default Vitrallis app runtime. Experimental Rust applications
use the same manifest v1, stable app IDs, icon/assets inventory, versioned catalog
pins and App Center transactions. A small Python `main.py` supervises a precompiled
Rust payload. This is an experimental packaging profile, not a new manifest
runtime or an incompatible catalog schema.

## Build and stage

Copy `examples/hello-rust` and change its identity, Cargo/app version, icon, assets,
README and changelog. Keep `runtime = "python"` and `entry = "main.py"`: those fields
accurately describe the launcher-facing supervisor. No Cargo or Rust runtime is
needed on the device; Python 3.8+ and the target's ordinary C runtime are required.

On a build machine with the appropriate Rust target and cross linker:

```sh
python3 tools/build_rust_app.py --source examples/hello-rust \
  --output /absolute/fresh/staged-package --target armv7-unknown-linux-gnueabihf
```

The optional `--zig` flag selects an already-installed `cargo-zigbuild` instead of
Cargo's normal linker. With Rust 1.98 or later, use cargo-zigbuild 0.23.0 or
later: older wrappers reject Rust's AArch64 linker arguments (see the
[upstream fix](https://github.com/rust-cross/cargo-zigbuild/pull/452)). The tool never installs build dependencies. Use a target
sysroot or libc baseline compatible with the oldest supported device, and test
on that device. Supported Linux triples are ARMv7 hard-float (PocketCHIP), AArch64,
and x86-64. Repeat `--target` to include multiple payloads in one package, within
the existing 2 MiB/file and 16 MiB/package catalog limits. Do not use `target-cpu=native`
for cross-device releases. Build directories remain outside the package.

The staged package has `bin/<target>/app` with executable mode, plus its unchanged
manifest, Python supervisor, source, assets, tests and documentation. The supervisor
selects a closed host/architecture mapping, rejects wrong-architecture ELF payloads
and symlinks, and reports missing/incompatible builds. It never chmods, writes to,
or builds inside the installed package. Its Python process remains alive to forward
termination to the child process group and reap it, so current App Center process
matching can stop the app before update/removal. Graphical Rust applications must
publish X11 process identity for focus integration and meet the normal rendering
and keyboard requirements; the minimal example is a display-free packaging probe.

## Publish, install, update and remove

Copy the complete staged result into an `apps/<slug>` source directory. Validate
it with the existing tools. Commit executable payloads with Git mode **100755**;
App Center takes modes from the pinned Git tree. Verify modes with `git ls-files
--stage` before publication. No executable-mode extension to catalog v1 is needed.
Publish source first and catalog pins second using the existing release process.
An updated binary or asset requires an increased app/Cargo version and dated notes.
Never republish different bytes under an existing version. Keep the entry disabled
until its actual target launch and App Center lifecycle have been tested.

Installation, update, repair and uninstall use the existing package inventories,
Python launcher and receipt paths. The Rust executable and assets are ordinary
managed package files. User data belongs outside the package and requires a
storage permission declaration just as for Python apps. The builder's fixture
tests prove inventory compatibility; the hardware report separately records actual
ARM execution and which App Center workflows were exercised.
