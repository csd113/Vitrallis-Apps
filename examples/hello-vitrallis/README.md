# Hello Vitrallis

A complete, intentionally small manifest v1 example: one offline greeting and a
Home button. It is a template, not an entry in the production catalog.

## Run

Requires Python 3.8+ and system Tkinter with a graphical desktop. There are no pip
dependencies. The repository validator requires Python 3.11+ separately.

```sh
python3 main.py
python3 main.py --check
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

`--check` reads and prints the packaged greeting without opening a window. Launch
using an absolute path from any working directory. Imports perform no I/O. Missing
Tkinter, display or greeting assets produce a short error and nonzero exit status.

Home, Escape or the window close button exits. Tab/Shift+Tab select the button;
Enter/keypad Enter/Space activate it. The 480×272 desktop window is a starting
profile; actual shell launch and PocketCHIP behavior require separate verification.
It does not force fullscreen or install a menu entry.

## Copy and customize

Copy this entire directory to `apps/<your-slug>/` in your catalog checkout.
Change the manifest `name`, `id`
and `version`, the dated release entry in `CHANGELOG.md`, window title in `main.py`, greeting asset, icon, README and tests.
Choose a stable reverse-domain ID you control; do not reuse `io.vitrallis.hello`.
Keep `manifest_version = 1` and declare only permissions you actually use.
Run `python3 tools/validate_catalog.py --package apps/<your-slug>` from the catalog
root, then its tests. Follow the catalog's `docs/publishing-apps.md` to publish
committed bytes and generated hashes. Documentation names here are plain paths
so this README stays self-contained when copied into another package directory.

## Files and permissions

`app.toml` is the metadata authority. `main.py` reads `assets/greeting.txt` relative
to its own file, not the working directory. `icon.png` is an original 128×128 navy
and mint geometric V tile, included for the launcher. The app does not require
or assume a launcher icon API. `tests/test_main.py` covers safe imports, resource
resolution, errors, icon decoding and GUI bounds/exit behavior.

All permissions are false: no network, audio or app-managed filesystem writes.
There are no settings, saves or caches. The package is read-only at runtime;
Python compilation caches are interpreter behavior, and development commands
should disable or redirect them outside the package. No telemetry or update checks.

No license is asserted by this example; the repository owner must establish reuse
rights. Artwork was created for this example and has no external asset attribution.

## Presentation contract

Graphical derivatives must follow [double buffering and VSync requirements](../../docs/rendering.md). This static Tk example redraws only when widgets change or are exposed. Tk has no portable app-level VSync request; synchronized physical presentation depends on a verified platform compositor. Treat a noncomposited Tk desktop as an unconfirmed, event-driven fallback, not tear-free certification. Use an EGL/SDL backbuffer surface for continuous animation.
