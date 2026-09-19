# Vitrallis Media Carousel

A locally managed slideshow for the screen running Vitrallis. Upload from your
phone/computer, organize collections, then select one in the native Python app.
Playback does not open a browser.

**0.2.0** · `io.vitrallis.mediacarousel` · manifest v1.

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

The bundled responsive phone/desktop site shows device name/IP/status, filename,
actual type, size and shared settings. JavaScript is required. Batch size is 100
files, with two concurrent transfers: each accepted file commits independently, failures
are reported, and earlier successes remain saved. Refresh reads other browsers'
changes; the native folder list updates automatically. Only a requested dependency installation polls its status. There is no
cloud functionality or telemetry.

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
| PNG/JPEG/WebP | Pillow-decodable still images; proportional fit, JPEG draft downsampling where available, EXIF orientation, transparency over black. |
| GIF | Sequential Pillow frame compositing with disposal/transparency. Original timing clamped to 20 ms–10 s; missing/zero timing uses 100 ms. Complete replays override embedded loop hints. |
| WebM | Real muted VP8/VP9/AV1 video where the system decoder supports it. Proportional scale/letterboxing, 20 fps RGB output toward the actual display, capped at 1280×720. Reopen the stream for every complete replay. |

Animated PNG/WebP are rejected; use GIF/WebM for animation. Missing ffmpeg or
ffprobe disables WebM with an explanation while images/GIF continue working.
WebM upload validation checks EBML DocType, stream metadata and a decoded first
frame; later corruption is reported and skipped during playback.

Settings persist and apply when a collection starts:

- Still duration: **1–3600** whole seconds; default **5**.
- Animated/video repeats: **1–100 complete plays**, default **3**, not frames.
- **In Order** uses the saved ordering. **Shuffle** visits each playable item once
  per randomized cycle, avoiding an immediate same-item cycle boundary repeat
  when more than one item is playable.
- **Loop Folder** starts another cycle; **Return to Main Menu** ends after one
  cycle in either order mode. Default: Loop Folder.

Native navigation targets **480×272 content pixels**, adapting down to 400×240 and
larger windows. Two collection rows per page preserve touch target size.

- Touch/click a collection to play. Tab/Shift+Tab focuses controls; Enter/Space
  activates buttons. Up/Down navigates collection rows/pages; Left/Right pages.
- During playback: Left = previous (restart the first item at the beginning),
  Right = next, Space on the media canvas = pause/resume. Tap/click the media or
  use Tab to reveal controls. Controls hide after three seconds unless paused
  or focused. Tk's normal press/release cancellation applies to buttons.
- Escape/Back leaves playback/settings; Home/Exit or Escape on Home stops services
  and exits the Python process. Back discards unsaved settings edits. The app
  does not force fullscreen or start another desktop/window manager.
- Shell SIGTERM and terminal SIGINT request the same orderly shutdown, including
  decoder processes and active HTTP transfers.

GIF decoding and disposal/transparency compositing remain in Pillow. On X11,
playback automatically tries a hardware EGL/GLES2 surface inside the existing Tk
window. The GPU scales and presents RGBA textures instead of creating Tk images
and applying CPU resampling every frame. Texture allocation is reused while
frame size stays constant. Tk retains keyboard navigation and the control overlay.
Software GL rasterizers and unknown GPU names are rejected as hardware; missing
libraries, unsupported desktops (including native macOS Tk), or a lost surface
fall back to Tk and log the reason as `event=media_renderer mode=tk`. Successful
initialization logs `mode=hardware` and the GL renderer name.

Animation deadlines follow media time, so uploads and UI polling do not add a
new delay to every frame. Expired frames can be skipped to catch up; decoded
replay counts and frame delays are preserved. Pause retains remaining frame time.
Small GIFs reuse composited frames across repeats within an **8 MiB** cache;
larger animations stream with two queued frames. GPU GIF frames retain native
resolution (within the existing one-million-pixel limit) for GPU filtering.
Neither GIF decompression nor WebM decoding is claimed to be hardware accelerated.
A GPU cannot guarantee full speed when CPU decoding exceeds the frame budget.

Resize refits the current GPU texture. Tk fallback recenters its current frame;
the next item or previous/next action decodes at the new size. High-resolution
and high-frame-rate video can exceed PocketCHIP decoding capacity.

The 0.2.0 GPU path and timing fixes have desktop/fake-device regression coverage;
physical Lima/Mali throughput and overlay behavior still need target verification.
The following device evidence describes the earlier playback implementation.

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
reported. There are no per-frame or refresh-only metadata writes.

Invalid settings use defaults with a warning and preserve the original until an
explicit successful save; unsafe/oversized settings need local administrator repair.
Invalid library metadata stops startup instead of discarding the library. Back up
the config/data directories while closed. Never make the app package writable just
to save user content.

## Limits and security

- **64 MiB/file**, streamed in at most 64 KiB chunks; two active uploads, one validation decoder and four
  HTTP handlers. Five-second socket idle timeout, 120-second transfer deadline,
  then at most 35 seconds for isolated validation. A 160-second overall connection
  deadline also bounds slow-dripped request headers.
- **100 collections / 2000 items**, 2 MiB library metadata, 64 KiB JSON requests,
  4 KiB settings. Disk-full failures are reported and incomplete uploads removed.
- Images: **8 million pixels** maximum. GIF: **1 million pixels/frame**, at most
  **1000 frames / 256 million aggregate decoded pixels** per complete animation.
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

Modules: `main.py` entry; `ui.py` screens/services; `player.py` playlist/clock/single
decoder worker; `gpu.py` optional EGL/GLES2 presentation; `media.py` inspection/FFmpeg; `storage.py` paths/atomic writes/lock;
`library.py` collections/order; `settings.py` validation; `web_server.py` HTTP;
`web/` bundled site; `assets/` original artwork; `tests/` development-only tests.

Reference APIs: [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html),
[Pillow GIF](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html#gif),
[FFmpeg protocols](https://ffmpeg.org/ffmpeg-protocols.html),
[FFmpeg options](https://ffmpeg.org/ffmpeg.html).

Original geometric artwork is included as SVG/PNG; reproduce with
`python3 tests/make_icon.py`. No third-party artwork or guessed license metadata.
Repository licensing remains an owner decision.

## Refined management and presentation

The home screen shows the current local URL, a QR code and a separate per-launch access code. Interface addresses refresh every ten seconds. QR generation uses the small pure-Python `qrcode` dependency alongside Pillow. Loopback-only service addresses do not produce a misleading LAN QR code.

Drag/drop or select up to 100 files per batch. Two transfers run concurrently; one media decoder validates at a time. Individual progress and errors retain successful uploads. Thumbnails are generated on demand in bounded subprocesses and cached in at most 2 MiB of memory. Static first-frame previews cover images/GIF/WebP, with muted WebM previews where FFmpeg works; unsupported previews show a small placeholder.

Download a collection in one action as a ZIP, limited to 256 MiB of media. The current library has flat logical collections, not user-controlled filesystem folders. Original basenames are preserved; duplicate names get separate internal-ID subdirectories so neither file is lost. Names and IDs are validated, symlinks rejected, and the unlinked staging archive is closed after success, failure or disconnect. No persistent archive copy is kept.

Multimedia readiness runs actual 16×16 VP8, VP9 and static WebP decode probes, with cached results. When missing, the authenticated web interface offers one explicit installation action through a no-argument root-owned helper configured at platform installation. It installs Debian `ffmpeg` with necessary dependencies only, without update/upgrade/autoremove, then repeats decode checks. On older platform installations an administrator must provision the helper using `tools/install_carousel_media_support.py --user chip`; app startup never grants itself privileges. Installation failure and missing decoder capabilities are reported separately. Do not interrupt an active package-manager operation.

EGL now requests backbuffer presentation synchronized to VSync and uses absolute GIF deadlines. A bounded 8 MiB GIF cache stores prepared RGBA bytes off the UI thread. Unsynchronized/Tk fallback is limited to 30 presentations per second while media time continues correctly. The physical display test exposed tearing even with an accepted EGL swap interval; see the [rendering contract](../../docs/rendering.md) and device verification report for platform limitations.

See the [2026-09-19 verification report](../../docs/verification/platform-app-refinements-2026-09-19/README.md) for measured app performance, physical tearing confirmation, reboot evidence and installation-validation limits.
