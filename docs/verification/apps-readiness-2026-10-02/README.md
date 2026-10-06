# Four-app local readiness pass — 2026-10-02

Implementation and local verification are prepared. **Source/catalog publication
is pending explicit commit/push authorization.** No working-repository commits,
pushes, PRs, Shell changes, SSH sessions or PocketCHIP operations were performed.
Disposable Git fixture commits exist only in tooling tests and are removed afterward.

## Calculator

The original catalog advertised `io.vitrallis.calculator` 0.1.0 at
`0ebb648e06958b4971686ff8c30aad7ec41b14e4:apps/calculator` with
**`installable: false`**. The public App Center contract presents a publisher-disabled
package as unavailable. No malformed manifest, missing module, requirements error,
incorrect checksum or package-relative resource bug was found in that pin.

Manifest v1, Python runtime, `main.py`, `calculation.py`, 128×128 icon, changelog,
requirements and all advertised inventory bytes validate. Requirements contain
only a comment: Python 3.11+ and system Tk are needed, with no app pip distribution.
The `.py` entry is passed to Python; it does not need a shell launcher executable
bit. No CRLF/entry-path or installation-write dependency was found. There is no
saved data to remove or migrate.

The official updater now enables the existing pin and records the limits in its
compatibility note. This metadata correction preserves its source bytes/version.
**It does not yet advertise the new 0.1.1 source.** That source disables direct-launch
bytecode writes and fixes an additional Linux lifecycle bug: idle Tk can defer
Python TERM handlers indefinitely. A 250 ms callback returns to Python without
redrawing, permitting prompt signal exit. The original pin passed macOS staging;
the Linux idle failure was discovered later and fixed in the prepared source.

Regression tooling verifies the original disabled gate, incomplete/wrong inventories,
missing imports and read-only writes. Prepared 0.1.1 passes app-local dependency
provisioning, isolated imports from another CWD, repeated read-only GUI launch and
TERM on macOS and Linux/Xvfb. Publication of 0.1.1 remains required before its Linux
lifecycle fix reaches App Center.

## Music

Prepared `io.vitrallis.music` 0.1.0 is a Python/Tk control surface with bounded,
cancellable filesystem/metadata workers and one owned streaming FFplay decoder.
MP3, FLAC, OGG/Vorbis and WAV were encoded and decoded to a null sink. Metadata
falls back to filenames/Unknown artist/album. Embedded art is scaled to 112×112
before retention. FFprobe/FFmpeg/FFplay restrict protocols to file/pipe, so disguised
playlists cannot contact a network endpoint. No whole-track decoded buffer exists.

The library defaults to the launcher Documents directory, scans recursively with
4,000-track/20,000-entry/16-level bounds, skips symlinks and refreshes explicitly.
Folder/library and now-playing screens expose transport, elapsed/duration, seeking,
volume (including a touch slider), shuffle and repeat. Keys include arrows/Enter,
Space, N/P, +/−, S/T, L/F/V/R, ? and Escape. See the app README for the full map.

Volume/modes/last folder/library position are atomic AppData configuration, distinct
from documents and package bytes. Returning home may retain the owning app under
Shell's documented lifecycle; no daemon is added. Explicit close/TERM reaps playback
and cancels probes. Linux exec helpers request parent-death SIGKILL, including a
paused decoder. Linux tests exercise abrupt parent death and real FFplay controls
using **SDL dummy audio**, never physical speakers.

## Sketch

Prepared `io.vitrallis.sketch` 0.1.0 provides a 464×194 canvas, continuous pencil,
white eraser, 1/3/6/10-pixel brushes, eight colors, bounded undo/redo, clear/new,
open, save and Save As. Touch maps directly to canvas coordinates; keyboard arrows
and Space provide cursor painting. N/O/S/Shift+S, U/Y, E, +/−, 1–8, P, ? and Escape
cover essential workflows; Tab/Enter reach dialogs. Destructive unsaved transitions
start on Cancel. Existing Save As targets require explicit Replace.

PNG is the native save format. PNG/JPEG imports are bounded to 8 MiB/four megapixels
and fitted to the canvas. Malformed/read-only imports and permission failures are
covered. Same-directory temporary writes, fsync and atomic rename preserve old
bytes on pre-commit failure. Post-rename directory-sync failure reports that the
new file was saved but power-loss durability is uncertain. TERM/INT attempts a
uniquely named recovery PNG. A forced kill cannot preserve an in-memory drawing.

Frame updates coalesce to at most 30 Hz only while drawing. A separate 250 ms
callback services idle Python signals without rendering. Tests cover fast/edge
strokes, a true one-pixel dot, 200 strokes/bounded undo, undo/redo, erasing, atomic
save/reopen/interruption, keyboard workflows and in-screen dialogs.

## System Monitor

Prepared 0.4.0 retains **`io.vitrallis.debug`** and `apps/vitrallis-debug/` for upgrade
identity, with the display name **System Monitor**. There is no duplicate app.

Overview shows CPU/load/frequency, RAM used/available/total, swap, root storage/free
space, temperature, GPU and uptime/kernel/architecture. Processes shows PID/name,
CPU relative to one logical CPU and RAM percent, sorting by CPU/memory/name and
paging six rows. Network shows interface/address/hostname, RX/TX rates and kernel
Wi-Fi quality/signal where readable. CPU, RAM, GPU, temperature and network histories
retain only 60 samples in memory. One worker samples approximately every second.

Diagnostics retains hardware/driver identity, sensor/devfreq sources, per-core
information, the existing GPU trace reader and optional EGL Pulse. The known
`/sys/class/devfreq/...gpu` layout and Lima `devfreq_monitor` path remain supported.
CPU details include OS/runtime; Memory details include Root/Documents filesystem
capacity. Reports use explicit fields rather than environment or process-command
line dumps. No credential, token or private-key export is added. Optional Linux utility
probes use the same parent-death cleanup as Music, preventing a probe from surviving
an abruptly terminated app. No process-kill or network-management controls are added.

Existing fixtures plus new tests cover proc CPU/memory, process names/start identity,
PID reuse, disk/reserved space, network deltas/reset, Wi-Fi data, bounded histories,
GPU present/missing/malformed/permission denial, thermal discovery and keyboard/touch
navigation. Actual Mali utilization/physical Pulse were not exercised here.

## Storage and installation boundary

The shared local runtime-integration document was updated during parallel Shell
work. Apps honor `VITRALLIS_APP_DATA_DIR` and `VITRALLIS_DOCUMENTS_DIR`; default data
is `~/Documents/Vitrallis/AppData/<stable-id>/`, with documents in `Documents/` and
preferences in `config/`. Caches use XDG. Assets resolve from the installed source.
New data directories are private 0700; atomic output files are private 0600. Absolute
paths, unsafe ancestors, symlinks and mismatched exported app identities are checked
before writes. No data is stored or cleaned up in an installed package tree.

`tools/simulate_install.py` validates the selected pin/inventory or unpublished
package, creates a disposable system-site venv, probes Tk/declared distributions
with isolated Python, imports and compiles the entry, launches twice (AppData CWD
and unrelated HOME CWD), checks TERM and verifies unchanged payload inventory. Pip
provisioning is explicit and disposable, configuration overrides are disabled and
no pip cache is written beside source. The audit runtime is installer-owned sibling
storage rather than a copied Shell installer implementation.

Opt-in staged workflow tests save/reopen a drawing, persist Music preferences,
write a diagnostic report and calculate from immutable payloads. Package replacement
and removal preserve all external document/state bytes. On unprivileged macOS the
staged payload also rejects a real write attempt. Root containers cannot prove Unix
mode denial, so their additional evidence is unchanged byte inventories and the
same immutable-layout workflows.

The validator does not implement downloads/receipts/rollback transactions, launcher
registration, source trust dialogs, timeout inbox delivery or device presentation.

## Validation commands and results

Host: macOS, Python 3.13.5, Tk 8.6, Pillow 12.1.0, system FFmpeg.
Linux: disposable Debian bookworm AArch64 container with read-only repository mount,
Python 3.11, Xvfb, FFmpeg and Pillow 12.3.0 in a disposable environment. This is
**not** the PocketCHIP ARMv7/Debian 13 target.

| Command | Result |
| --- | --- |
| `python3 tools/validate_catalog.py --package apps/calculator --package apps/music --package apps/sketch --package apps/vitrallis-debug` | Passed, all four working packages |
| `python3 tools/validate_catalog.py` | Passed, six currently pinned apps; fetched the exact missing external Places Git object first |
| `python3 tools/validate_changelogs.py` | Passed for committed HEAD, six published apps; does not certify dirty release edits |
| `python3 -B -m unittest discover -s apps/calculator/tests -v` | Passed, 5 tests on host and Linux |
| `python3 -B -m unittest discover -s apps/music/tests -v` | Passed, 21 tests; two Linux-only cases skipped on macOS, all 21 passed on Linux |
| `python3 -B -m unittest discover -s apps/sketch/tests -v` | Passed, latest 17 on host; Linux's last full pass was 16 before the additional one-pixel regression/palette polish |
| `VITRALLIS_REQUIRE_GUI=1 python3 -B -m unittest discover -s apps/vitrallis-debug/tests -v` | Passed, 75; macOS skips hardware EGL and Linux FIFO; Linux passes FIFO and skips hardware EGL |
| `python3 -B -m unittest discover -s apps/vitrallis-debug/tests -p test_hardware.py -v` | Passed, 20 tests in an isolated Linux container after probe cleanup changes |
| `VITRALLIS_REQUIRE_GUI=1 python3 -B -m unittest discover -s tools/tests -v` | Passed, 84 tests, including four staged GUI workflows and disposable committed release rehearsal |
| `VITRALLIS_REQUIRE_GUI=1 python3 -B -m unittest discover -s tools/tests -p test_staged_apps.py -v` | Passed, four external-state/document workflows on host and Linux |
| `python3 -B -m unittest discover -s tools/tests -p test_release_rehearsal.py -v` | Passed: source-first fixture commits, generated eight-app inventories/pins and committed changelog policy; no real publication |
| `python3 -B tools/simulate_install.py --package apps/<slug> --gui --provision` for calculator/music/sketch/vitrallis-debug | Passed on host and Linux, including repeated idle TERM after the lifecycle fix |
| `PYTHONPYCACHEPREFIX=/tmp/vitrallis-readiness-pycache python3 -m compileall -q tools apps/calculator apps/music apps/sketch apps/vitrallis-debug` | Passed; bytecode outside packages |
| `python3 -B tools/scoped_tests.py` | Preview includes the four owned apps plus concurrent Bitcoin/Carousel edits; those other runtime suites belong to the parallel writer |
| `git diff --check` | Passed |

No Rust files changed; Rust formatting/Clippy/Cargo execution is not applicable.
The Linux command wrapped app tests and staging in `xvfb-run -a`, with
`PYTHONDONTWRITEBYTECODE=1 VITRALLIS_REQUIRE_GUI=1`. The disposable container installed
Tk/Pillow/packaging/venv/Xvfb/FFmpeg without modifying the host or any Shell checkout.

Initial failures were corrected: missing isolated `packaging` required local
provisioning; a missing external Places pin required fetching that commit; Linux
Xvfb needed an explicit test focus owner; idle Tk TERM required a signal-service
callback. No validator acceptance rule was weakened.

## UI and performance evidence

480×272 geometry and text bounds are covered in affected GUI tests, with keyboard
and simulated pointer strokes/activation. Native macOS fixture windows were visually
reviewed through computer-use screenshots: Sketch canvas/save dialog, Music now
playing and System Monitor overview. Retina screenshots contain twice the physical
pixels but Tk content geometry was exactly 480×272. `tools/tests/preview_apps.py`
reproduces disposable previews. Larger 640×360 Monitor geometry was also checked.
Tk's physical synchronized composition remains a device-compositor check.

`python3 -B tools/tests/bench_selected_apps.py <slug>` measured these **macOS model
microbenchmarks**, excluding GUI, playback and hardware:

| Work | Wall time per operation | CPU time per operation | Whole-process peak RSS |
| --- | ---: | ---: | ---: |
| Scan 1,000 synthetic music files (10 runs) | 45.008 ms | 13.527 ms | 23.08 MiB |
| Checkpoint/draw a 464×194 stroke (200 runs) | 0.080 ms | 0.022 ms | 28.92 MiB |
| Sample 100 proc fixtures (100 runs) | 4.685 ms | 2.950 ms | 25.33 MiB |

These figures include interpreter/module memory, use development-host filesystem
caches, and are not PocketCHIP CPU/RAM measurements or decoder memory budgets.

## Deferred device validation

- Actual App Center source acquisition, dependency provisioning on ARMv7, registration,
  focus, update/repair/removal/reinstall and data preservation with the final pins.
- Speaker output, volume/seek latency, device codec availability and background/timeout
  lifecycle under the finalized Shell build.
- Real Mali/Lima counters, thermal/frequency paths, optional EGL Pulse and live network.
- Physical keyboard/touch alignment, readable presentation, scanout/VSync/compositor,
  startup/idle/playing CPU/RAM and flash/power-loss behavior.

## Deferred integration findings

Affected repository: **Vitrallis-Shell**. The parallel writer updated the local
storage contract to export AppData/Documents paths; public upstream documentation
may still describe the previous lowercase documents/XDG layout. Evidence is the
shared `docs/runtime-integration.md` diff and the other chat's coordination notice.
Expected contract: finalized launchers supply matching identity and absolute app,
data and documents paths, start in AppData and preserve it on uninstall. Verify
that contract after the Shell release; no Shell compatibility edits were made here.

The Python package contract does not specify a native advisory safe-close inbox
adapter. TERM/INT are verified; real background-timeout delivery remains a later
integration check, not a new invented protocol. No device session was used.

## Repository state and release steps

Prepared versions: Calculator **0.1.1**, Music **0.1.0**, Sketch **0.1.0**, System
Monitor **0.4.0**. Current real catalog still has six apps and its old source/version
pins, with only Calculator eligibility/compatibility metadata corrected. Music and
Sketch are ready for generated entries; the offline rehearsal defaults new entries
to disabled until client readiness is reviewed. Neither fixture SHA nor dirty-tree
hashes were advertised as real source pins.

After explicit authorization: selectively commit the owned source/tooling/docs,
push it, generate these four entries from that published full SHA, add matching
root Added/Updated records, verify remote availability, commit/push the catalog and
run the committed merge-policy check. Preserve the source commits through PR merge.
Coordinate shared publication with the parallel writer rather than committing
unrelated Bitcoin/Carousel edits. No current dirty state is claimed ready to merge.

Owned changed files:

- Calculator: `app.toml`, `main.py`, `README.md`, `CHANGELOG.md`.
- Music: `app.toml`, `main.py`, `player.py`, `owned_child.py`, `storage.py`,
  `requirements.txt`, `icon.png`, `LICENSE`, `README.md`, `CHANGELOG.md`,
  `assets/README.md`, `tests/test_player.py`, `tests/test_ui.py`.
- Sketch: `app.toml`, `main.py`, `drawing.py`, `storage.py`, `requirements.txt`,
  `icon.png`, `LICENSE`, `README.md`, `CHANGELOG.md`, `assets/README.md`,
  `tests/test_drawing.py`, `tests/test_ui.py`.
- System Monitor: `app.toml`, `main.py`, `ui.py`, `diagnostics.py`, `demo.py`,
  `monitor_ui.py`, `monitoring.py`, `storage.py`, `owned_child.py`, `hardware.py`,
  `README.md`, `CHANGELOG.md`, `assets/README.md`,
  `tests/test_monitor_ui.py`, `tests/test_monitoring.py`.
- Tooling: `tools/simulate_install.py`, `tools/tests/test_simulate_install.py`,
  `test_staged_apps.py`, `test_release_rehearsal.py`, `preview_apps.py`,
  `bench_selected_apps.py` (all latter files under `tools/tests/`).
- Root/docs: `apps.json`, `README.md`, `CHANGELOG.md`, `THIRD_PARTY_NOTICES.md`,
  `docs/runtime-integration.md`
  (shared with the parallel writer), `docs/testing.md`, `docs/publishing-apps.md`,
  and this record.

Working tree is dirty, with concurrent Bitcoin Dashboard/Media Carousel edits
preserved and excluded from this goal's source release. App-test count increased
from 69 to 118 (+49); tooling from 74 to 84 (+10), including opt-in staged cases.

## Final acceptance audit

Audited against the original objective, without treating disposable release
fixtures as published artifacts. The numbered items below correspond to its
final acceptance criteria. Publication authorization is still missing; the
implementation goal therefore remains incomplete.

| Criterion | Authoritative evidence | Current result |
| --- | --- | --- |
| 1. Calculator root cause and package-side fix | Original pinned catalog gate, official updater diff, prepared main.py | Proven locally; 0.1.1 source publication pending |
| 2. Calculator staged regression | test_simulate_install.py gate/inventory/import fixtures; host/Linux repeated staged launch | Passed |
| 3. Music complete catalog-ready app | Package validator, manifest/README, 21 app tests, staged workflow | Source ready; real catalog entry pending |
| 4. Sketch complete catalog-ready app | Package validator, manifest/README, 17 host app tests, staged workflow | Source ready; real catalog entry pending |
| 5. Debug evolved into System Monitor | Stable manifest ID, Monitor entry point, current-facing README/assets name | Implemented; catalog name/version pending |
| 6. Monitor resources and diagnostics | monitor_ui.py, monitoring.py, preserved diagnostics/GPU modules, 75 tests | Locally verified with explicit unavailable states |
| 7. Read-only staged operation | Immutable payload workflows, simulator import/GUI/inventory checks | Passed on host and Linux within documented simulation boundary |
| 8. External documents/state | storage.py path checks and atomic writes; package replacement/removal workflows | Passed |
| 9. Deliberate 480×272 validation | Native geometry/text bounds, keyboard/pointer tests, visual preview review | Passed locally; physical presentation deferred |
| 10. Relevant validation | Exact commands and results above; latest package/compile/diff checks and release rehearsal | Passed within reported scope; final committed release checks pending |
| 11. Consistent release catalog/package metadata | Current six-pin validation; disposable eight-pin source-first rehearsal | Prepared versions validate; actual new pins/root release records pending |
| 12. No Shell modifications | This goal's file list and tool actions; integration findings recorded separately | Boundary preserved |
| 13. No physical PocketCHIP access | Disposable host/container tests only; no SSH/device operations | Boundary preserved |
| 14. No hardware-certification claim | Explicit limitations throughout app READMEs and this report | Preserved |
| 15. Remaining hardware/App Center checks listed | Deferred device validation and integration findings above | Documented |

The previous artwork audit's quoted Vitrallis Debug prompt is historical evidence
and remains unchanged. The current shipped assets heading now says System Monitor.

## Owner provenance clarification — 2026-10-02

The owner explicitly confirmed that Codex created all apps and assets. The root
THIRD_PARTY_NOTICES.md now records that statement, resolving its earlier request
for Firefly FONT authorship confirmation and its missing project-asset provenance
statement for the historical Bitcoin screenshot. Source-history references and
third-party dependency notices remain recorded. No Firefly or Bitcoin package
files were changed by this clarification, so it creates no additional app-version
or catalog-pin requirement. Publication authorization remains pending.

## Publication guide flag correction — 2026-10-02

The Bitcoin publication example incorrectly described its current catalog entry
as enabled. The authoritative working catalog has installable=false for Bitcoin
1.3.0, matching the prior root changelog's pending-certification note. The guide
now states that status and explains that the updater preserves the actual catalog
flag unless explicitly overridden. No catalog flag or package bytes changed.
