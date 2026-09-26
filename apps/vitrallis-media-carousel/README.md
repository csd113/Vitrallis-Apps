# Vitrallis Media Carousel

A locally managed slideshow for the screen running Vitrallis. Upload from your
phone/computer, organize collections, then select one in the native Python app.
Playback does not open a browser.

**0.4.1** · `io.vitrallis.mediacarousel` · manifest v1.

[Changelog](CHANGELOG.md).

## Runtime and installation

- Python **3.9+** on POSIX Linux/macOS, with **Tk/Tkinter 8.6**.
- **Pillow >=10.4,<13**, installed in the Python environment used to launch the app.
  `requirements.txt` is authoritative. Keep decoder security updates installed.
- The current App Center also needs installed **packaging** to inspect version
  ranges in requirements (`python3-packaging` on Debian); the app itself does not
  import it.
- Optional system **ffmpeg and ffprobe**, both on `PATH`, for WebM. FFmpeg 4.3+
  with Matroska/WebM, VP8/VP9, scale/pad/fps and rawvideo is the intended baseline;
  AV1 requires a working AV1 decoder in that build.
- Optional X11 hardware playback: system **libX11, libEGL and libGLESv2** with a
  working GLES2 driver (including Lima/Mali). No additional pip packages.
- Optional system **gif2webp** (Debian package **webp**) for fast on-device
  GIF-to-WebP conversion. Without it, a bounded built-in Pillow fallback is used.
- A graphical session and writable private storage. No Node/npm, browser runtime,
  web framework, cloud account, audio service or container runtime.

On a suitable Debian system an administrator can provide `python3-tk`,
`python3-pil`, `python3-pil.imagetk`, `python3-packaging` and `ffmpeg`. Verify the distro Pillow meets
the minimum above, or provide an appropriate Python environment and run
`python3 -m pip install -r requirements.txt`. Tkinter is a system prerequisite,
not a pip dependency. Startup never installs packages or changes system settings.
ARMv7 may need distro packages or a Pillow source build with JPEG/zlib/WebP
development libraries; an ARMv7 wheel is not assumed. Old PocketCHIP Debian
images may require an administrator-provided newer OS/Python environment.

Install from the official `main` catalog through Vitrallis Shell App Center:
choose **Check**, select **Vitrallis Media Carousel**, then **Install**. The same
action installs updates and repairs. App Center checks the prerequisites above
and reports missing dependencies; it does not install system packages. Version
0.1.1 publishes the X11 process identity used by the Shell to focus and resume
its native window. Manifest permissions declare network/storage requirements
and audio false, not a sandbox.

Launch `python3 main.py` from this directory, or an absolute path to `main.py`
from any working directory. Resources resolve beside the modules. The installed
package is read-only, including interpreter bytecode.

## Management workflow

1. Launch the app. Home displays its management URL, server state and a random
   **6-character access code**. Port 8765 is preferred; if occupied, a free port
   is chosen and displayed.
2. On another device on the same trusted LAN, open that literal **IP address**
   in a browser and enter the code. Hostname URLs are deliberately rejected.
3. Open **Unsorted** or create a collection. Drop files or choose multiple files.
   The page shows transfer progress, subsequent validation, and each file's result.
4. Use the large up/down buttons to save play order immediately. Rename folders,
   delete files, or confirm whole-collection deletion. Deleting the last collection
   creates a fresh Unsorted. Duplicate media filenames have separate IDs; collection
   names are unique after Unicode normalization and case folding.
5. Select a collection on the device. Its playlist/settings are a stable snapshot;
   uploads/reordering affect the next start, and concurrent deletions are skipped.

The native app starts its slideshow services first and binds the management server
on a background thread, so the home screen and playback are usable immediately even
while LAN address discovery or the FFmpeg capability probe is still running. The
home screen reports the server as `starting`, `ready`, `failed` or `stopped`. A
server that cannot bind is logged and shown on screen; playback and local collection
browsing continue normally.

### Bulk conversion to WebP

Open a collection and use **Convert GIFs**, **Convert images** or **Convert all
supported** in the conversion card, or use the **Convert to WebP** tab for the whole
library (all collections, or one selected folder). One action queues every matching
item. The job runs on the device with a small bounded worker pool (one worker on a
single/dual-core host, two on four or more cores; `CAROUSEL_CONVERT_WORKERS`
overrides it), so the page never freezes and the slideshow keeps playing.

The progress panel is docked at the bottom of the page and shows the current file,
`found / converted / failed / skipped` counts, an overall bar and a final summary;
failures are listed individually and can be hidden or cancelled at any time.
Items already in WebP are reported as **skipped** and left untouched. Ticking
**Re-convert files that are already WebP** re-encodes them deliberately.

Conversion is transactional per item: the source is opened read-only, the result is
written to a staged temporary file, then verified for frame count, per-frame
duration, looping, dimensions, transparency and orientation, and only then atomically
swapped into the library at the same playlist position. A malformed, unsupported or
failed item is reported and skipped while the rest of the batch continues, every
staged file is removed, and the original bytes are kept on every failure path. GIFs
convert through system `gif2webp` when present and through the bounded Pillow
fallback otherwise; still PNG/JPEG images always use Pillow with EXIF orientation
baked into the pixels. Animated media never loses its animation, timing or
transparency to a static first frame.

The bundled responsive phone/desktop site shows device name/IP/status, filename,
actual type, size and shared settings. JavaScript is required. Batch size is 100
files, with two concurrent transfers: each accepted file commits independently, failures
are reported, and earlier successes remain saved. Refresh reads other browsers'
changes; the native folder list updates automatically. Only a requested dependency
installation or a running conversion job polls its status, and a conversion keeps
its progress panel visible until it finishes or is dismissed. There is no cloud
functionality or telemetry.

Codes change at every launch and are kept only in the browser tab's session
storage (or memory when storage is denied). Lock removes the saved code. Codes
never appear in URLs, logs, cookies or persistent device storage. Every API read
and mutation requires bearer authorization; only the login page/CSS/JS are public.
Authenticated collection downloads and thumbnail previews are available. There is
no arbitrary directory listing or package file-serving API.

HTTP is unencrypted: use a trusted LAN and never forward this port to the Internet.
Someone observing LAN traffic can observe the code. This app does not provide TLS.

## Media, settings and controls

| Type | Behavior |
| --- | --- |
| PNG/JPEG/WebP | Pillow-decodable still images; proportional fit, JPEG draft downsampling where available, EXIF orientation, transparency over black. Static WebP uses this still path. |
| GIF | Sequential Pillow frame compositing with disposal/transparency. Original timing clamped to 20 ms–10 s; missing/zero timing uses 100 ms. Complete replays override embedded loop hints. |
| Animated WebP | Every frame plays through the same compositing, timing and bounded-cache path as GIF, including repeat counts and the 20 ms–10 s clamp. |
| WebM | Real muted VP8/VP9/AV1 video where the system decoder supports it. Proportional scale/letterboxing, RGB output paced at the source's own frame rate (clamped to 30 fps) toward the actual display, capped at 1280×720. One decoder process serves every repeat through `-stream_loop`, driven by a bounded reader queue. |

GIF and animated WebP preparation follows the current playlist order and starts as
early as cache space allows, rather than waiting for a fixed item number. The
animation on screen is streamed frame by frame as it decodes, so its first frame
appears immediately instead of after the whole animation is prepared, and the
streamed frames are recorded for its repeats and for the next visit. Upcoming
animations are prepared by one worker that yields the CPU while the on-screen
animation is streaming, and that never bothers with the item already being streamed.
Finished items leave the window, while upcoming cached items remain available.
Ordered loops can prepare across the playlist boundary; shuffled loops prepare the
next cycle only once its order is chosen. Navigation prioritizes the newly selected
animation and exit cancels preparation. The cache lives only in memory for playback.

Animations that do not fit are recorded as unfitted for the current window instead
of being decoded again on every visit. The limits count decoded pixel bytes, not
compressed file sizes, so fewer than ten animations may fit. Oversized animations and
preparation failures fall back to the bounded streaming decoder; preparation has a
30-second deadline. The 32 MiB limit covers retained/preparing cache pixels, not
decoder work buffers, queued frames, or renderer textures. Smoothness under
background decoding still requires a device performance check. Queued work is
bounded: six decoded frames may sit ahead of the presentation loop, and video
buffering is bounded by bytes as well as frame count. Navigating onto an animation
whose preparation is still running cancels that preparation and streams the item in
the foreground instead, which is correct at the cost of one extra decode.

When the hardware EGL path is active, animation frames keep their native resolution
(within the one-million-pixel limit) and are minified with linear filtering without
mipmaps; a very large animation can therefore alias on the small panel. The Tk
fallback performs one bilinear downscale at decode time. Confirm the GPU path on
the target device.

Animated PNG is rejected; use GIF, animated WebP or WebM for animation. Missing
ffmpeg or ffprobe disables WebM with an explanation while images, GIF and WebP
continue working. WebM upload validation checks EBML DocType, stream metadata and a
decoded first frame; a file with a corrupt or truncated tail can therefore play
less than its declared duration or repeat the decodable part, but it is contained
and never crashes or hangs playback. Later errors that the decoder does report are
shown and skipped during playback.

Settings persist and apply when a collection starts:

- Still duration: **1–3600** whole seconds; default **5**.
- Animated/video repeats: **1–100 complete plays**, default **3**, not frames.
- **In Order** uses the saved ordering. **Shuffle** visits each playable item once
  per randomized cycle, avoiding an immediate same-item cycle boundary repeat
  when more than one item is playable.
- **Loop Folder** starts another cycle; **Return to Main Menu** ends after one
  cycle in either order mode. Default: Loop Folder.
- **GIF uploads** can convert each newly uploaded GIF to animated WebP after
  validation; default **Keep as GIF**. Converting an existing GIF is always
  available from playback and the web page.

Native navigation targets **480×272 content pixels**, adapting down to 400×240 and
larger windows. Two collection rows per page preserve touch target size.

- Touch/click a collection to play. Tab/Shift+Tab focuses controls; Enter/Space
  activates buttons. Up/Down navigates collection rows/pages; Left/Right pages.
- During playback: Left = previous (restart the first item at the beginning),
  Right = next, Space on the media canvas = pause/resume, and **C** (or the
  **To WebP** button) converts the current GIF or still image to WebP. Tap/click
  the media or use Tab to reveal controls. Controls hide after three seconds
  unless paused or focused. Tk's normal press/release cancellation applies to
  buttons. A batch conversion started from the web page shows its progress in the
  overlay as counts instead of moving the slideshow position.
- Escape/Back leaves playback/settings; Home/Exit or Escape on Home stops services
  and exits the Python process. Back discards unsaved settings edits. The app
  does not force fullscreen or start another desktop/window manager.
- Shell SIGTERM and terminal SIGINT request the same orderly shutdown, including
  decoder processes and active HTTP transfers.

GIF and WebP decoding and disposal/transparency compositing remain in Pillow and are
never hardware accelerated. On X11, playback automatically tries a hardware
EGL/GLES2 surface inside the existing Tk window. The GPU scales and presents RGBA
(for animation) or RGB (for opaque video) textures instead of creating Tk images and
applying CPU resampling every frame. Texture allocation is reused while the frame
shape stays constant, and the Tk fallback pastes every frame into one reused photo
image instead of creating a Tcl image per frame. Tk retains keyboard navigation and
the control overlay. Software GL rasterizers and unknown GPU names are rejected as
hardware; missing libraries, unsupported desktops (including native macOS Tk), or a
lost surface fall back to Tk and log the reason as `event=media_renderer mode=tk`.
Successful initialization logs `mode=hardware` and the GL renderer name.

Video decoding is selected by capability detection, not by assumption. At startup
the app lists the FFmpeg build's `-hwaccel` methods and then decodes a small
committed sample of each codec with each candidate, accepting a method only when
FFmpeg's own log shows that a hardware pixel format was actually negotiated
(`requires hwaccel …_videotoolbox initialisation`). Anything else is reported as
software. `CAROUSEL_HWACCEL=off` forces software. If a hardware decoder later fails
to produce frames for a specific file, the item is retried once in software and the
backend change is logged. On macOS this verifies VideoToolbox for **VP9 only**: VP8
has no VideoToolbox decoder and always reports `backend=software`. No hardware
decoding is claimed for GIF, WebP, or any codec without a verified path. Every item
logs `event=video_decoder codec=… backend=… hwaccel=… verified=… reason=…`, and the
same information appears on the web Settings tab.

Hardware decode is not always faster: on a fast desktop with a small clip,
VideoToolbox's session setup and per-frame download cost more than software VP9
decode, even though CPU time falls. `tests/bench_media.py` measures this on the
host, and `CAROUSEL_HWACCEL=off` selects the software path when a host prefers it.
Both paths always produce correct frames and correct timing.

Animation and video deadlines follow media time on a monotonic clock, so decoding and
presentation work never add a new delay to every frame. Expired animation frames can
be skipped to catch up, bounded per tick, with a resynchronisation instead of
unlimited drift. Pause retains remaining frame time. Selecting a new item re-arms the
presentation timer immediately, so a decoded first frame is shown without waiting for
the previous item's timer, while a still image or paused view wakes the UI a few
times per second instead of at frame rate. GIFs and animated WebP are
prepared ahead of playback in a rolling window of up to **10 animations**, with an
**8 MiB per-animation** and **32 MiB total** decoded-frame cache. Larger animations
stream with a bounded look-ahead queue. GPU animation frames retain native resolution
(within the existing one-million-pixel limit) for GPU filtering.

Resize refits the current GPU texture. Tk fallback recenters its current frame;
the next item or previous/next action decodes at the new size. High-resolution
and high-frame-rate video can exceed PocketCHIP decoding capacity.

The 0.2.0 GPU path and timing fixes have desktop/fake-device regression coverage;
physical Lima/Mali throughput and overlay behavior still need target verification.
The 0.3.0 animated-WebP playback, on-device conversion, streamed 4 GiB downloads
and hidden-window pause also have desktop regression coverage. The 0.4.0 bulk
conversion pipeline, background web-server startup, timestamped video decoding and
deadline-based pacing have desktop regression coverage and local benchmarks
(`tests/bench_media.py`); ARMv7 decode speed, hardware-acceleration availability on
Lima/Mali, long-transfer endurance and the overlay's five-button layout still need a
physical PocketCHIP check. The 0.4.1 reliability, layout and download fixes have
desktop plus headless-browser regression coverage; physical confirmation of the
revised 480×272/400×240 layout, the >2 GiB ZIP64 download path and signal-shutdown
behavior on the device remains outstanding. The following device evidence describes
the earlier playback implementation.

Source-run validation on an ARMv7 PocketCHIP with the current Vitrallis Shell used
Debian 13.6, Python 3.13.5, Tk 8.6, Pillow 11.1.0 and FFmpeg 7.1.5. The native
480×272 layout, LAN browser upload, still/GIF/WebM playback and clean return to
the existing Shell were exercised. The device owner confirmed physical touch and
keyboard navigation. Automated GUI, media, persistence and security tests also
ran on that device. This does not verify App Center installation. Desktop testing
used macOS, Python 3.13.5, Tk 8.6, Pillow 12.1.0 and FFmpeg 9.0.1.

## Storage and durability

The current contract has no storage SDK; this uses the documented **XDG convention
assumption**, under the stable app ID:

| Content | Default location |
| --- | --- |
| Settings | `~/.config/io.vitrallis.mediacarousel/settings.json` |
| Library metadata | `~/.local/share/io.vitrallis.mediacarousel/library.json` |
| Random-ID media blobs | `~/.local/share/io.vitrallis.mediacarousel/media/` |
| Temporary uploads | `~/.local/share/io.vitrallis.mediacarousel/uploads/` |
| Reserved cache (currently empty) | `~/.cache/io.vitrallis.mediacarousel/` |

`XDG_CONFIG_HOME`, `XDG_DATA_HOME`, `XDG_CACHE_HOME` replace those base directories.
Paths must be absolute, without traversal/symlink components, outside the package.
App-owned directories must belong to the launching user with mode 0700. Invalid
or denied storage fails closed without switching locations. On macOS use resolved
`/private/...` temporary paths; symlinked `/tmp` and `/var` bases are rejected.

A process lock prevents concurrent native writers. Metadata writes stage in the
destination directory, flush/fsync, atomically replace, then fsync the directory.
A pre-commit failure preserves the previous document. A directory sync failure
after replacement retains the committed state and displays a durability warning.
Logical deletion commits before reclaiming bytes; unreachable media/incomplete
uploads left after a crash are safely reclaimed on startup. Cleanup failures are
reported; a leftover that fails validation (unsafe, unreadable or linked) is left
in place with a warning instead of preventing the app from starting. There are no
per-frame or refresh-only metadata writes.

Invalid settings use defaults with a warning and preserve the original until an
explicit successful save; unsafe/oversized settings need local administrator repair.
Invalid library metadata stops startup instead of discarding the library. Back up
the config/data directories while closed. Never make the app package writable just
to save user content.

## Limits and security

- **64 MiB/file**, streamed in at most 64 KiB chunks; two active uploads, one validation decoder and four
  HTTP handlers. Five-second socket idle timeout, 120-second transfer deadline,
  then at most 35 seconds for isolated validation. A 160-second overall connection
  deadline also bounds slow-dripped request headers. Upload staging checks free
  space first and fails with a clear message when it is insufficient.
- **4 GiB folder downloads** (archive-size bound), streamed without a temporary
  archive or RAM buffer, one at a time. The overall connection deadline is
  refreshed during an active transfer and the stream socket allows brief client
  pauses; an aborted transfer never finalizes an archive.
- **100 collections / 2000 items**, 2 MiB library metadata, 64 KiB JSON requests,
  4 KiB settings. Disk-full failures are reported and incomplete uploads removed.
- Images: **8 million pixels** maximum. GIF and animated WebP: **1 million
  pixels/frame**, at most **1000 frames / 256 million aggregate decoded pixels** per
  complete animation. The no-`gif2webp` conversion fallback is bounded to 32
  million decoded pixels.
- WebM: at most **4096×2160**, known positive duration at most **30 minutes**.
  One FFmpeg decoder/filter thread, bounded frame pipe, 10-second output-stall
  detection. Skip/exit terminate/reap owned process groups and validation children.
  Audio/subtitle/data streams are ignored; FFmpeg protocols are limited to file/pipe.
- Names and restored metadata are validated; names never form trusted file paths.
  Reject absolute paths, `..`, slash/backslash, colon, controls, symlinks, FIFOs and
  hardlinks. POSIX no-follow/nonblocking opens verify regular files. Completed,
  validated uploads atomically move into the media directory.
- Pillow validation is isolated in a subprocess with a wall deadline; Linux also
  adds a 30-second CPU limit and 256 MiB virtual-address-space limit. WebM inspection
  on 64-bit Linux allows 1 GiB of virtual mappings for distro decoder libraries;
  ARMv7 keeps the 256 MiB limit. Numerical-library/probe threads are capped at one.
  These are virtual-memory ceilings, not resident-memory usage targets. Allowlisted
  formats are identified from actual bytes. Playback rechecks file size/type/dimensions.
  Keep decoders patched.
- IPv4 listener accepts private/loopback peers. Per-launch 24-bit random code
  (six hexadecimal characters), invalid-code rate limits, explicit IP Host validation, same-origin checks, no
  CORS/cookies, and CSP/no-sniff/no-referrer headers constrain browser attacks.
- Private directories and the same-UID process are the local trust boundary, not
  a sandbox against another malicious process already running as the device user.

## Troubleshooting

- **No LAN address:** join Wi-Fi and restart. The primary IPv4 URL appears on Home;
  all discovered URLs appear in web state. A displayed 127.0.0.1 address works
  only on the device itself. Discovery uses bounded local `hostname -I` on Linux
  or `ifconfig` on macOS, without an Internet connectivity probe. Firewalls or
  Wi-Fi client isolation can prevent access.
- **Code rejected:** use the current six lowercase hexadecimal characters and
  literal IP/port displayed on the device. A restart invalidates old codes.
- **WebM unavailable/slow:** provide both tools on the launcher's PATH. Prefer
  small VP8 video. Images and GIF remain usable without the tools.
- **Upload rejected:** read the per-file result. Re-encode unsupported/corrupt/
  resource-intensive files, shorten filenames, free space or retry after another
  upload. 100% transfer still needs validation. Reorder conflicts require refresh.
- **Conversion is slow or refused:** system `gif2webp` is much faster than the
  fallback and has no extra pixel limit; install Debian `webp`. The fallback
  refuses animations beyond 32 million decoded pixels and always keeps the
  original GIF when it cannot validate a result.
- **No playable media:** unreadable, deleted and corrupt items are reported/skipped;
  all-failed playlists return to the menu with an explanation.
- **Cannot start:** inspect storage permissions/corruption locally with the app
  closed. A second instance is rejected. Native playback remains available if
  only server binding fails.

## Development

From the repository root, with Python 3.11+ for repository tools/tests:

```sh
python3 -m pip install -r apps/vitrallis-media-carousel/requirements.txt
python3 tools/validate_catalog.py --package apps/vitrallis-media-carousel
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/vitrallis-media-carousel/tests -v
PYTHONPYCACHEPREFIX=/tmp/vitrallis-pycache python3 -m compileall -q apps/vitrallis-media-carousel
```

`VITRALLIS_REQUIRE_GUI=1` requires desktop GUI tests (use Linux `xvfb-run -a` when
needed). Optional WebM tests skip without FFmpeg; CI provides it for real decoding
tests. `VITRALLIS_REQUIRE_EGL=1` enables an additional real EGL/texture test on
Linux/Xvfb; its test-only software-policy mock does not enable software GL in
the app. All server tests bind only to loopback, storage is temporary, media samples
are generated and no tests need Internet services. Run all `CONTRIBUTING.md` checks.
For an authorized source-run device session, `tests/device_session.py` opens the
same native app and accepts simple status/navigation commands over standard input;
use separate XDG roots for test media. It exits after ten minutes and is excluded
from the installed package along with the other tests.

`tests/bench_media.py` is a reproducible local benchmark rather than a unit test.
Run it directly and compare checkouts:

```sh
python3 tests/bench_media.py
python3 tests/bench_media.py --package /path/to/another/checkout --json /tmp/that.json
```

It measures capability probing, time until the slideshow path is usable, animated
GIF/WebP decode and first-frame latency, replay cost and file opens, WebM decode
throughput and delivered frame rate, conversion cost, its own bounded caches, and
presentation FPS through the real Tk loop. It writes fixtures to a temporary
directory, binds only to loopback, and performs no device access.

Modules: `main.py` entry; `ui.py` screens/services; `player.py` playlist/clock/bounded
decoders (animation frames and a timestamped FFmpeg video stream); `animation_cache.py`
bounded prepared animation frames; `convert.py` batch GIF/image-to-WebP conversion;
`gpu.py` optional EGL/GLES2 presentation; `media.py` inspection/cached metadata/FFmpeg
commands; `multimedia.py` verified decoder and hardware-acceleration detection;
`storage.py` paths/atomic writes/lock; `library.py` collections/order;
`settings.py` validation; `web_server.py` HTTP and its background start/stop
lifecycle; `web/` bundled site; `assets/` original artwork; `tests/` development-only
tests and benchmarks.

Reference APIs: [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html),
[Pillow GIF](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif),
[FFmpeg protocols](https://ffmpeg.org/ffmpeg-protocols.html),
[FFmpeg options](https://ffmpeg.org/ffmpeg.html).

Original geometric artwork is included as SVG/PNG; reproduce with
`python3 tests/make_icon.py`. No third-party artwork or guessed license metadata.
Repository licensing remains an owner decision.

## Refined management and presentation

The home screen shows the current local URL, a QR code and a separate per-launch access code. Interface addresses refresh every sixty seconds. QR generation uses the small pure-Python `qrcode` dependency alongside Pillow. Loopback-only service addresses do not produce a misleading LAN QR code.

Drag/drop or select up to 100 files per batch. Two transfers run concurrently; one media decoder validates at a time. Individual progress and errors retain successful uploads. Thumbnails are generated on demand in bounded subprocesses and cached in at most 2 MiB of memory. Static first-frame previews cover images/GIF/WebP, with muted WebM previews where FFmpeg works; unsupported previews show a small placeholder.

Download a collection in one action as a ZIP, capped at **4 GiB** of media (the
archive size bound, checked before any bytes are sent). The archive is streamed
straight to the client in 64 KiB chunks with no temporary file and no in-RAM
buffer; only one folder download runs at a time, and its progress reports bytes
received. The browser saves the streamed archive as a Blob before writing it, so a
download near the cap needs enough free memory on the controlling device. The
current library has flat logical collections, not user-controlled
filesystem folders. Original basenames are preserved; duplicate names get separate
internal-ID subdirectories so neither file is lost. Names and IDs are validated and
symlinks rejected before headers commit. A mid-transfer failure closes the
connection without finalizing an archive, so a truncated download never looks like
a complete file.

Convert media to WebP on the device from the playback overlay (**To WebP**, `C`),
from the web page's per-item button, or as a bulk job for a whole collection or the
entire library. System `gif2webp` is preferred for GIFs (Debian package **webp**);
without it, and always for still PNG/JPEG images and for re-encoding an animated
WebP, a bounded Pillow encoder at a 32-megapixel budget is used. The result must
open, keep the frame count, durations, looping, dimensions, orientation and
transparency before the library atomically replaces the source at the same
position; the original is deleted only after that successful validation, and any
failure keeps it byte-for-byte and removes the staged output. A conversion status
line progresses through reading, converting and verifying, and a bulk job reports
found/converted/failed/skipped counts. One job runs at a time, cancelled jobs
publish nothing, and an optional setting converts newly uploaded GIFs
automatically.

Multimedia readiness runs actual 16×16 VP8, VP9 and static WebP decode probes, with cached results. When missing, the authenticated web interface offers one explicit installation action through a no-argument root-owned helper configured at platform installation. It installs Debian `ffmpeg` with necessary dependencies only, without update/upgrade/autoremove, then repeats decode checks. On older platform installations an administrator must provision the helper using `tools/install_carousel_media_support.py --user chip`; app startup never grants itself privileges. Installation failure and missing decoder capabilities are reported separately. Do not interrupt an active package-manager operation.

EGL now requests backbuffer presentation synchronized to VSync and uses absolute GIF deadlines. A rolling GIF cache stores prepared RGBA bytes off the UI thread, bounded to 8 MiB per GIF and 32 MiB total. Media time continued correctly in the unsynchronized/Tk fallback, which was limited to 30 presentations per second. The physical display test exposed tearing even with an accepted EGL swap interval; see the [rendering contract](../../docs/rendering.md) and device verification report for platform limitations.

Since 0.4.0, 0.3.0's 30 FPS presentation ceiling is gone: the Tk fallback presents at the media's own deadline and drops expired frames with a bounded catch-up instead of slowing the animation down. The animation on screen streams its first frame immediately and records itself for later repeats, so the earlier "complete preparation before the clock starts" loading delay no longer applies. Video uses one decoder process per item instead of one per repeat, and is paced from the source frame rate rather than a fixed 20 FPS resample.

See the [2026-09-19 verification report](../../docs/verification/platform-app-refinements-2026-09-19/README.md) for measured app performance, physical tearing confirmation, reboot evidence and installation-validation limits.
