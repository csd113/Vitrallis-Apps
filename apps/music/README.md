# Music

A local music player designed for the 480×272 PocketCHIP keyboard and touchscreen.
Version **0.1.0** uses Python 3.11+, Tk 8.6, Pillow and the system FFmpeg tools
(`ffplay`, `ffprobe`, `ffmpeg`). On Debian 13, Tk and FFmpeg are system prerequisites;
App Center provisions the declared Pillow distribution in its app-local runtime.
The app never runs apt or installs software at startup. Missing FFmpeg produces
an actionable status while the library remains browsable.

MP3, FLAC, OGG/Vorbis and WAV stream through one owned FFplay process; there is no
whole-song decoded buffer. Metadata supplies title, artist, album and duration.
Missing tags use filenames and Unknown artist/album; corrupt tracks show an error.
Embedded artwork is decoded to at most 112×112 and only the current image is held.
Decoder/probe protocol whitelists permit only local file/pipe input, so disguised
playlists cannot initiate internet requests. No accounts or streaming services are used. Permissions declare
audio and storage requirements, with network false.

## Controls

- Up/Down select tracks or folders; Enter opens the selection. Tab/Shift+Tab and
  Enter/Space activate buttons. Double-tap/click a track also opens it.
- Space plays/pauses the current selection; N/P choose next/previous.
- Left/Right seek five seconds; the seek slider supports touch dragging.
- V opens the touch volume slider; Left/Right and +/− change volume in five-percent steps. S toggles shuffle. T cycles repeat
  off, all, one. Shuffle chooses another track when possible.
- L returns to Library. F chooses Documents or a child folder (tracks inside the
  chosen folder are discovered recursively). R refreshes changes explicitly.
- ? displays more shortcuts. Escape returns from Now Playing/Folders to Library;
  Escape from Library exits. The Exit button always closes the app.

The Now Playing surface shows track information and artwork; transport remains
available on every screen. Scanning runs in one cancellable worker, with bounds
of 4,000 tracks, 20,000 entries and 16 directory levels. Symlinks are skipped.
Sorting uses relative paths, case-insensitively with deterministic tie breaking.
There are no continuous rescans or idle artwork animations.

## Documents, state and lifecycle

The canonical library is the launcher's `VITRALLIS_DOCUMENTS_DIR`; the documented
fallback is **`$HOME/Documents/Vitrallis/AppData/io.vitrallis.music/Documents/`**, under the current Documents/Vitrallis convention.
An exported `VITRALLIS_APP_ID` must match the stable ID. New music files belong in
this folder or its children. It is created with minimal user permissions when
needed. Denied storage is reported; the app does not silently switch directories.

Volume, shuffle, repeat, last folder and library position are written atomically to
`$VITRALLIS_APP_DATA_DIR/config/settings.json` (default
`~/Documents/Vitrallis/AppData/io.vitrallis.music/config/settings.json`). Tracks remain user documents; package replacement,
repair or removal does not own or delete them. There are no saved decoded buffers,
telemetry logs or package-local caches. Absolute paths are validated and symlink
storage paths fail closed.

Returning home may leave the supervised app running under the documented Shell
lifecycle. Playback remains owned by that app; no daemon is created. Exit, TERM
and INT stop/resume-if-paused, terminate and reap the decoder and cancel probes.
On Linux, decoder/probe children also request a parent-death SIGKILL through a
small exec helper, covering an unexpectedly killed parent without unsafe threaded
pre-exec hooks. Pausing/seeking/volume use POSIX process controls; seek and volume
restart the stream at the retained position, so a brief audible gap is possible.

Tk composes off-screen and redraws from events and bounded playback status updates.
Per-window VSync is unavailable through Tk; synchronized presentation relies on the
device compositor. macOS development uses native Tk button appearance.

## Verification and limits

Run `python3 -B -m unittest discover -s apps/music/tests -v` and
`python3 tools/simulate_install.py --package apps/music --gui --provision`.
Tests cover empty/bounded libraries, extension discovery, corrupt metadata,
real format decoding to a null sink, playback state and owned-process cleanup,
keyboard navigation, read-only payloads and external writable state.

**Physical PocketCHIP/App Center validation is intentionally deferred to a later
dedicated integration pass.** Speaker output, ARMv7 codec availability, actual
background lifecycle, touch feel, startup resource use and display synchronization
have not been certified. A missing audio device produces a playback error; decoder
success on a desktop is not real audio-output verification.
