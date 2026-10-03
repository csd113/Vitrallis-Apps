# PocketCHIP app audit — 2026-10-03

The separately authorized hardware pass is complete. All eight apps passed actual
App Center removal and reinstallation, with 309 published files verified against
their source inventories. The 29-file preservation checkpoint survived, including
three unrelated Notepad documents. All nineteen files present before the audit
also retain their original contents and permissions.

This is an audit with qualified results, not certification of every app or physical
input, audio and presentation behavior. At audit handback, Music and Monitor fixes
were uncommitted
and Carousel had a separate repair patch; the publication follow-up below records
their subsequent releases. No Shell source or installed build was edited.

## Device and boundary

- Normal `chip` user over USB SSH with existing key authentication; no passwords,
  root changes, reflash, reboot or system dependency installation.
- ARMv7 PocketCHIP, Debian 13, kernel `6.12.107+deb13-chip`, Python 3.13.5.
- X11 480×272 at 59.52 Hz, Mali-400/Lima; Pillow 11.1.0, packaging 25.0, Tk and
  FFmpeg available as system dependencies.
- Installed Shell source `5c560670eaf4a775f2b563b1d9ec344cb4f73bba`, generation
  `e5bdb419b999e08519ed0cc8de232b3f48fad869d9917be5a11ca0f3340e3a7c`.
  The generation and boot identity remained unchanged.
- Real X-session keyboard/pointer events were injected through Awesome. They test
  application event handling, not physical key switches or touch calibration.
  Screenshots are device captures; GPU readback can limit what they establish.

The original no-device four-app goal was completed before this separate pass.
The Shell worker released the device for this pass and stayed on host work. Its
later launcher-cache candidate was not installed or certified here.

## Exact managed packages

| App / stable ID | Version | Published source commit | Files checked |
| --- | --- | --- | ---: |
| Calculator / `io.vitrallis.calculator` | 0.1.1 | `d04bcbcb10f75c960552ebe9ce80cf4131b221de` | 9 |
| Music / `io.vitrallis.music` | 0.1.0 | `d04bcbcb10f75c960552ebe9ce80cf4131b221de` | 11 |
| Sketch / `io.vitrallis.sketch` | 0.1.0 | `d04bcbcb10f75c960552ebe9ce80cf4131b221de` | 10 |
| System Monitor / `io.vitrallis.debug` | 0.4.0 | `d04bcbcb10f75c960552ebe9ce80cf4131b221de` | 18 |
| Bitcoin Dashboard / `io.vitrallis.bitcoindashboard` | 1.3.1 | `b1460ed1d7b373719e0edfc1d4fb5fbc9e29e504` | 13 |
| Media Carousel / `io.vitrallis.mediacarousel` | 0.4.3 | `b1460ed1d7b373719e0edfc1d4fb5fbc9e29e504` | 29 |
| Firefly Field / `io.vitrallis.fireflyfield` | 0.3.1 | `0ebb648e06958b4971686ff8c30aad7ec41b14e4` | 18 |
| Places / `io.vitrallis.liminalrust` | 0.11.2 | `368dd1f0c45ca81a0e7f29041eb4bbfe33846b70` in `csd113/Places` | 201 |

The temporary eight-app catalog combined exact published inventories from PR #20
and the independent release candidate. Only its private copy enabled disabled
Bitcoin, Music and Sketch entries. Public flags, pins and versions were unchanged.
The catalog was verified against committed source objects before device use.

Installs used the real App Center UI, downloader, runtime provisioning, receipts
and launchers. Monitor first upgraded Debug 0.3.2 under its unchanged stable ID.
All eight apps then passed removal and reinstallation. The final pass rechecked
all 309 file sizes/SHA-256 hashes, receipts, and preservation-checkpoint files.
Places' 14 MB download exceeded several bounded 60-second check-helper waits;
App Center continued progressing and eventually completed successfully.

Healthy packages expose Open after checking. Repair is reserved for damaged or
incomplete packages, so these were healthy checks and managed rebuilds, not
injected-fault repair tests. Existing completed transaction backups were retained.

## Native behavior

| App | Observed result and limits |
| --- | --- |
| Calculator | Keyboard `200*10% = 20`, pointer `1+2 = 3`, Home/resume with retained expression, and normal Escape exit passed. Reopened and exited offline after reinstall. `=` calculates; Enter activates the focused keypad button. |
| Music | Managed FLAC playback had a live FFplay backend; pause, seek, volume, shuffle/repeat and corrupt-file handling worked. Valid formats exposed a cold-probe timeout and a startup pause/cleanup race, repaired in source below. Offline library/prefs remained available; Home/resume retained PID 27645 and normal Escape exit passed. Speaker output is not certified. |
| Sketch | Keyboard strokes, both canvas edges via pointer, undo/redo, palette, save/open, unsaved Cancel, Home/resume and TERM recovery passed. Saved RGB PNG: 464×194, mode 0600. Offline read-only PNG opening and explicit Replace confirmation worked. Native 17-test suite passed, including malformed input, atomic overwrite/interruption, path hazards and Tk workflows. Screenshots taken while slow operations were pending do not establish completed UI error states. |
| System Monitor | All four sections, process sorting and saved diagnostics worked. Managed Home/resume retained PID 28934 and normal Escape exit passed offline. The first offline Overview capture still said Collecting. Patched Network histories contain RX/TX samples, with occasional unavailable/STALE rates under load. Hardware GLES2 Pulse completed/cancelled and returned to Diagnostics; its captured GPU value stayed 0.0%, so utilization accuracy is unresolved. |
| Bitcoin | Network/empty Watch, invalid-address rejection, Home/resume and normal top Exit worked. Both online-attempt and offline runs showed a clear Shell Tor/API error with cached values retained. Offline launch waited for shared Tor; fresh network data was unavailable. The legacy window title is `Bitcoin CAD v1.3.1`. |
| Firefly | Controls, pause/scatter, mood/wind/HUD, Home/resume, normal exit and offline reopening passed. Low observed FPS remains a concern; see measurement limits and the pending packing comparison. |
| Carousel | Local server/controls and Home/resume worked in the initial run, but managed VP8 playback was black and later reported a decoder stall. That file decoded successfully standalone. Offline relaunch reached a native window and normal Escape exit, but its capture did not establish a usable rendered screen. A source repair comparison produced real frames and closed normally; startup is still slow. |
| Places | Demo movement/look, pause, Home/resume, menu exit and offline reopening passed. Original settings and cache files stayed byte-identical. |

Wi-Fi was disabled only after downloads completed. External HTTPS was unreachable
while USB SSH remained available. Wi-Fi was then re-enabled; NetworkManager
reported connected and an external HTTPS socket succeeded. No credentials,
network profiles or App Center source configuration were changed.

## Prepared source repairs

### Music 0.1.1

- Raise cancellable metadata/artwork startup budget from four to twenty seconds.
  A valid native MP3 failed at four seconds and succeeded in 4.256 seconds with
  the longer bound. Cold FFprobe startup separately took over ten seconds.
- Defer SIGSTOP until the owned Linux exec helper has armed parent-death cleanup.
  The UI can logically pause immediately and cancel a pending pause on resume.
  Both native parent-death tests passed, including immediate startup pause.
- Read Vorbis title/artist/album from audio-stream tags when container tags are
  absent; container metadata retains precedence and video/cover tags are ignored.

A paused seek/volume restart reached FFplay with cleanup armed. Killing its source
player removed the live owned decoder in 0.058 seconds. The final read-only source
snapshot ran 25 native tests in 75.292 seconds with no skips: four real formats,
dummy-audio controls, both parent-death cases, storage and native Tk workflows.
Host results were 25 tests with three Linux-only skips. These establish decoder
and cleanup behavior, not audible sound or publication of 0.1.1.

### System Monitor 0.4.1

Request `ip -j -s address show`; the old command omits the interface byte counters
needed for RX/TX throughput. The regression checks that statistics are requested.
The native read-only source displayed actual history samples. All 76 host tests
passed with two opt-in integration skips. Code was tested on-device; the final
README additionally corrects the prepared-release wording.

### Carousel candidate

[carousel-startup-candidate.patch](carousel-startup-candidate.patch) is a reviewable
four-file patch against published `b1460ed1d7b373719e0edfc1d4fb5fbc9e29e504`.
It can be checked with `git apply --check` in a clean copy of that source.

- Allow a bounded 35 seconds for inspection and 30 seconds for first decoder
  output; retain ten seconds for later output gaps.
- Exclude bounded consumer backpressure from stall timing.
- Use software playback while hardware detection is uncached, letting the existing
  background capability worker fill verified results instead of duplicating
  blocking hardware probes on the playback path.

Nineteen decoder tests passed. The full 274-test host comparison passed with one
opt-in EGL skip. Its first full run had a fixture failure because the isolated
copy lacked repository validators; supplying the unchanged tools resolved it.
The final native comparison produced a VP8 frame at 59.43 seconds from app setup,
advanced through later generations without reported decoder errors, and exited
normally. This does not certify cold-start performance. One earlier orphaned
comparison disappeared without a diagnostic trace; kernel logs were unavailable
to the normal user, so its cause remains unknown.

At audit handback, no production Carousel source had been overwritten; Carousel
0.4.4 and Firefly 0.3.2 still required separate release decisions and publication.
The subsequent authorized publication incorporates copies of those repairs while
preserving the other worker's checkout.

## Resource measurements and startup

These bounded samples include each managed app and owned descendants. CPU is a
percentage of one core; RSS is the maximum observed aggregate resident memory.

| Managed workload | Duration | Mean CPU | Maximum RSS, KiB |
| --- | ---: | ---: | ---: |
| Calculator idle | 10 s | 0.67% | 17,128 |
| Sketch idle | 20 s | 0.69% | 25,084 |
| Music FLAC playback | 30 s | 13.36% | 48,548 |
| Monitor warm Network | 30 s | 16.48% | 30,008 |
| Bitcoin watch navigation | 30 s | 0.50% | 28,040 |
| Firefly default field | 30 s | 47.39% | 46,288 |
| Carousel playback attempt | 30 s | 13.42% | 83,660 |
| Places demo gameplay | 30 s | 20.05% | 58,764 |

**Observer overhead matters:** the `/proc` sampler itself used 19.25% of one core
in a separate 11.603-second idle probe. App CPU figures exclude that observer,
but scheduling and FPS were measured with its added load. They are not production
performance measurements. The sampler now reports its own CPU time. It does not
capture screenshots during steady samples; screenshots close their GDK connection.

Firefly's managed HUD showed 3 FPS. Its pending packing source comparison averaged
42.44% CPU / 46,252 KiB RSS over 31.384 seconds and showed 4 FPS afterward.
It reported hardware GLES2, VSync requested and 480×272 output. Places showed
24–25 FPS during sampled gameplay. Neither establishes physical scanout quality.

Observed cold waits until window focus included Sketch 31.731 seconds and
Carousel 51.819 seconds. Reinstalled offline waits included Sketch 29.008,
Music 34.392, Monitor 33.814 and Carousel 44.078 seconds. Window focus is not the
same as first usable frame. A controlled Tk/Pillow import took 3.665 seconds with
the installed launcher bytecode namespace versus 0.793 seconds without it. This
explains only part of latency; it was reported as a Shell integration finding.
App code does not bypass the Shell runtime contract.

## Validation commands and results

| Command / environment | Result |
| --- | --- |
| `python3 tools/validate_catalog.py --package apps/music` | Pass, prepared 0.1.1 |
| `python3 tools/validate_catalog.py --package apps/vitrallis-debug` | Pass, prepared 0.4.1 |
| `python3 tools/validate_catalog.py --source-repo csd113/Places=/Users/connordawkins/Documents/GitHub/places` and the same command with `--catalog target/apps-hardware-2026-10-03/catalog-test-only.json` | Pass for the published catalog and eight-app private fixture; does not publish working fixes. The map uses the exact `Places` capitalization; a lowercase-map attempt could not resolve the fixture commit |
| `python3 -B -m unittest discover -s apps/music/tests -v` | Host: 25 pass, three Linux-only skips; final native snapshot: 25 pass, no skips |
| `python3 -B -m unittest discover -s apps/vitrallis-debug/tests -v` | Host: 76 pass, two opt-in integration skips |
| `python3 -B -m unittest discover -s <read-only Sketch snapshot>/tests -v` with native `DISPLAY=:0` | 17 pass, no skips |
| `python3 -B -m unittest discover -s <Carousel comparison>/tests -v` | 274 pass, one opt-in EGL skip; targeted decoder suite: 19 pass |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -v` | 84 pass, four opt-in staged GUI skips |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -p test_release_rehearsal.py -v` | Final rerun: one pass in 104.259 s |
| `python3 tools/simulate_install.py --package apps/music --gui --provision` and corresponding Monitor command | Host read-only GUI/TERM simulations pass. Initial attempts without provisioning failed on missing packaging in the isolated environment; disposable venv provisioning resolved them |
| `python3 tools/validate_changelogs.py --base b321a957ef05516f3883000536d632f5aed51db1` | Published HEAD passes; this check reads commits and does not approve uncommitted fixes |
| Manual `device_package.py removed/installed <id>` after App Center UI operations | All eight managed rebuilds and 309 exact published files pass; preservation checkpoint passes |
| `git apply --check docs/verification/apps-hardware-2026-10-03/carousel-startup-candidate.patch` in a clean b146 source copy and the independent release worktree | Pass; neither checkout was patched |
| AST parsing of touched/manual-helper Python and generated remote code; `git diff --check` | Pass |

During the hardware audit, no Rust code was changed and Rust validation was not run. The release rehearsal now
derives fixture versions and notes from generated entries and current changelogs,
rather than hard-coding previous package versions. It creates commits only in
disposable test repositories.

## Evidence and changed files

Reviewable files changed in this worktree:

- `apps/music/`: `app.toml`, `CHANGELOG.md`, `README.md`, `player.py`,
  `owned_child.py`, `tests/test_player.py`.
- `apps/vitrallis-debug/`: `app.toml`, `CHANGELOG.md`, `README.md`,
  `diagnostics.py`, `tests/test_diagnostics.py`.
- `.gitignore` (ignore root `target/`) and `tools/tests/test_release_rehearsal.py`.
- `tools/tests/device_ui.py`, `device_sample.py`, `device_stage.py`,
  `device_package.py`: explicit manual probes requiring exclusive device ownership;
  not automatic test-discovery SSH tasks and not a second installer.
- This report and `carousel-startup-candidate.patch`.

Raw screenshots, pairing information, private filenames and full inventories
remain ignored under `target/apps-hardware-2026-10-03/`. They must not be committed.
The remote audit directory is `~/vitrallis-apps-hardware-2026-10-03/`, mode 0700.
It retains catalog/settings backups, captures, checkpoint data and thirteen
immutable source snapshots. New drawing/media fixtures belong to the audit;
pre-existing documents/settings/media were preserved. Tests use temporary data.

At audit handback, no new real source commits, public catalog entries, merges or
branches had been created in the hardware follow-up. PR #20 was at `75e593dbc1fc14dd6b630a7add5d9c48b283913f`;
its earlier green CI did not cover those uncommitted changes. Music 0.1.1 and
Monitor 0.4.1 still required source-first publication and matching catalog records.

## Device handback

**Exclusive device ownership is released at 2026-10-03 22:04:02 UTC.** No device
commands or UI actions are pending. The Shell worker may resume its authorized
native integration work; this worker performs only host documentation/checks
following handback.

- Original six-entry saved catalog restored byte-for-byte under the App Center
  lock after checking test-fixture identity and absence of pending transactions.
  SHA-256: `5d95b235a18fd9f5508abd7f6f52773d3b3ab772e9c435542283a69cd8d72f38`.
- Wi-Fi enabled and connected; external HTTPS available; source config unchanged.
- Existing user session restarted once to discard the temporary in-memory catalog
  (two session restarts total in this pass, one to load it and one to restore it).
  Shell supervisor/native PIDs at final check: 4385 / 4419; Pocket Home 1272.
- No live app, decoder or source-audit controller; no pending transaction or
  `.installation-pending` marker. Thirty-four completed transaction backups were
  retained, not mistaken for pending work or deleted.
- All eight exact managed packages remain installed. Restoring the original
  catalog does not publish the additional app entries or enable public flags.
- Available storage at final checkpoint: 1,293,725,696 bytes. Root, Apps and
  AppData remain on filesystem device 19. No storage fillers or mount changes.
- Native app rebuilds used the unchanged installed 5c560 Shell. A later launcher
  cache candidate may need to recreate obsolete launchers while preserving AppData.
  Its deployment and native launch-latency result are outside this audit.

Remaining certification work: retest cold startup and Carousel decoder behavior with the next
Shell candidate; resolve GPU utilization accuracy and Firefly performance; exercise
injected-fault Repair; and confirm physical keyboard/touch, audible output and
synchronized scanout. Existing owner decisions remain separate; this audit does
not create new approval requests or claim those checks passed.

## Authorized publication follow-up — 2026-10-03

The maintainer subsequently requested pushing, merging into main, and enabling
installation of all apps. Music 0.1.1, Monitor 0.4.1, Firefly 0.3.2 and Carousel
0.4.4 publish the tested source repairs described above with matching dated notes
and generated inventories. Calculator 0.1.1, Sketch 0.1.0, Bitcoin 1.3.1 and Places
0.11.2 retain their original source pins. All eight catalog install flags are enabled;
the compatibility notes retain the qualified native results and remaining limits.

Music/Monitor source was pushed in `a6a92bd`; the combined source including
Carousel/Firefly repairs was pushed in
`21774cfa5ce0670f2b2884d0060f238cd6af0b4d` before generating catalog pins.
Integration PR #21 preserves the preceding releases and their histories; PR #20
publishes the follow-up versions and enablement. Source commits remain reachable
through merge commits. This publication uses host/GitHub checks after device
handback and makes no new device or Shell changes.

The publication checks additionally reproduced the Music startup-pause regression
on Linux Python 3.11: `/proc/<pid>/cmdline` was briefly empty during exec, so
absence of the helper path prematurely authorized SIGSTOP. Source commit
`ad32a6755ced427e6206c6e2b13b88cb891799da` treats that empty transition as
startup and adds a deterministic regression without relaxing parent-death tests.
Music's final host suite passed 26 tests with three Linux-only skips. A Linux
Python 3.11 container passed 201 checks: 100 repetitions of both parent-death tests
plus the command-line transition regression. This final adjustment was tested on
host/container and CI, without reacquiring the device.

Publication validation also passed all eight package manifests and both examples,
274 Carousel tests (one optional EGL skip), 21 Firefly tests, 76 Monitor tests
(two opt-in skips), and 84 tooling tests (four optional staged-GUI skips).
Places passed `cargo fmt --all --check`, the required strict workspace/all-targets/
all-features Clippy command, and `cargo test --workspace --all-features`:
843 tests passed and three were ignored. GitHub's required Python 3.11/3.13
checks exercise the Linux graphical runtime separately from these host results.
