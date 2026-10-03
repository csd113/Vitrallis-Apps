# Sketch

A small native sketchpad for the 480×272 PocketCHIP display. Version **0.1.0** uses
Python 3.11+, Tk 8.6 and Pillow. App Center provisions Pillow; Tk is a system
prerequisite (`python3-tk` on Debian 13). The canvas occupies 464×194 pixels with
a compact toolbar and optional palette. Output is lossless PNG. PNG and JPEG
imports are fitted into the canvas against a white background, preserving aspect
ratio; JPEG imports require a new PNG filename. This is a sketchpad, not a layer editor.

## Controls

- Touch/drag draws continuous strokes, including the screen edges.
- Arrow keys move the canvas cursor three pixels. Space toggles the pen down/up
  while the canvas has focus, allowing complete drawing with the keyboard.
- E switches pencil/eraser; +/− cycle 1, 3, 6 and 10-pixel brushes.
- 1–8 select colors; P or Color toggles the palette. The eraser paints white.
- U undoes; Y redoes. New strokes clear redo. History retains at most 16 canvases
  per stack, keeping memory bounded rather than storing every point indefinitely.
- N creates a blank document; C clears with an undo checkpoint.
- O opens an image from Sketch Documents. Up/Down and Enter choose the image.
- S saves; Shift+S is Save As. Type a filename and Enter; existing filenames need
  an explicit Replace action. Tab/Shift+Tab and Enter/Space reach dialog controls.
- ? displays shortcuts. Escape dismisses the palette/dialog, then requests exit.
  New/open/clear/exit warn on unsaved content with Cancel focused by default.

Dialogs fit inside the display. Drawing maps directly to native canvas pixels;
coordinates outside a stroke are clamped. Image presentation is coalesced to at
most 30 updates per second while drawing; static canvases have no redraw loop. A 250 ms callback only returns to Python
so idle Linux Tk can deliver TERM/INT; it never draws or scans files.
Tk uses off-screen composition but offers no portable per-window VSync; the
physical compositor still needs device verification.

## Storage and recovery

Drawings use `VITRALLIS_DOCUMENTS_DIR`, with the documented fallback
**`$HOME/Documents/Vitrallis/AppData/io.vitrallis.sketch/Documents/`** under the current Documents/Vitrallis convention. An exported
launcher ID must match. O lists PNG/JPEG files in this directory. Images are limited
to 8 MiB compressed and four megapixels decoded; malformed images leave the old
canvas intact. Imported files can be read-only.

Brush and color preferences live at
`$VITRALLIS_APP_DATA_DIR/config/settings.json` (default
`~/Documents/Vitrallis/AppData/io.vitrallis.sketch/config/settings.json`). New directories are created only when needed.
Documents and preferences are separate from the read-only installed package and
survive update, repair, removal and reinstall. No unrelated user files are removed.
Storage paths must be absolute, outside the package and free of symlinks.

PNG saves use a same-directory private temporary file, flush/fsync, atomic rename
and directory synchronization. A failed write/rename preserves the previous file
and the unsaved canvas; failures are shown in the dialog. A directory-sync failure
can mean that the new bytes were saved but power-loss durability is unconfirmed.
TERM/INT attempts a uniquely named `Recovery-<timestamp>.png` in Documents before
closing. A failed recovery save is reported to stderr; a forced kill cannot save
an in-memory drawing. Recovery never overwrites an existing named sketch.

Permissions declare storage true, audio/network false. There is no server,
background process or automatic package-directory write.

## Verification and limits

Run `python3 -B -m unittest discover -s apps/sketch/tests -v` and
`python3 tools/simulate_install.py --package apps/sketch --gui --provision`.
Tests exercise fast/edge strokes, many strokes and bounded undo, erasing, keyboard
painting, save/reopen, explicit overwrite, malformed/oversized/read-only input,
permission and interrupted-save failures, dialogs, recovery and storage separation.

**Physical PocketCHIP/App Center validation is intentionally deferred to a later
dedicated integration pass.** Touch calibration, flash behavior during real power
loss, physical keyboard feel and compositor scanout have not been certified.
