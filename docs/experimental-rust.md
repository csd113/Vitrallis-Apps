# Rust application packages

Native Rust applications use `runtime = "rust"` with a closed `binaries` mapping.
App Center selects a precompiled target payload; Cargo is never run on the
device. Manifest and catalog schema versions remain 1 with an explicit additive
runtime alternative. Python packages retain their existing contract unchanged.

```toml
manifest_version = 1
name = "Carousel-Rust"
id = "io.vitrallis.carouselrust"
version = "0.1.0"
runtime = "rust"

[binaries]
armv7-unknown-linux-gnueabihf = "bin/armv7-unknown-linux-gnueabihf/app"

[permissions]
network = true
audio = false
storage = true
```

Native manifests and catalog entries omit `entry`; Python entries omit `binaries`.
Mappings contain one to three unique safe published paths, keyed by exactly
`armv7-unknown-linux-gnueabihf`, `aarch64-unknown-linux-gnu`, or
`x86_64-unknown-linux-gnu`. Each payload must be a matching little-endian ELF
executable. ARM additionally requires EABI5 hard float. Installed launchers exec
the selected binary. Windowed apps must supply X11 process identity and satisfy
the same rendering, keyboard, storage, and publication requirements as Python.

`apps/carousel-rust` implements this profile for new Rust apps.
`examples/hello-rust` is a historical
Python-supervised experiment, not the current native runtime template.

## Build and stage

For a native package, include `app.toml`, `icon.png`, `README.md`, `CHANGELOG.md`,
populated `assets/` and `tests/`, Rust sources, Cargo metadata/lockfile and the
mapped binaries. Native apps need neither `main.py` nor `requirements.txt`.
Keep Cargo/app/changelog versions aligned. Build output stays outside the source
package; stage only the final mapped executable payloads.

On a build machine with the appropriate Rust target and cross linker:

```sh
python3 tools/build_rust_app.py --source apps/carousel-rust \
  --output /absolute/fresh/staged-package --target armv7-unknown-linux-gnueabihf \
  --zig --glibc 2.36
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

The builder requires all declared native targets in one staging operation and
validates the finished package before an atomic no-replace directory publication.
It never commits, pushes, installs, or overwrites an existing output directory.
Configure an image-matched SDL2 pkg-config/sysroot when the application uses SDL.
`--glibc 2.36` pins the GNU libc baseline for Zig; it requires `--zig`. A binary
can still depend on newer symbol versions in external libraries: target launch
and dynamic-link inspection remain mandatory.

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
runtime-specific launcher and receipt paths. The Rust executable and assets are ordinary
managed package files. User data belongs outside the package and requires a
storage permission declaration just as for Python apps. The builder's fixture
tests prove inventory compatibility; the hardware report separately records actual
ARM execution and which App Center workflows were exercised.
