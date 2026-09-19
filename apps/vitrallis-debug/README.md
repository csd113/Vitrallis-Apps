# Vitrallis Debug

Current package: **0.3.0** · [Changelog](CHANGELOG.md).

Vitrallis Debug is an offline instrument panel for a 480×272 Vitrallis/PocketCHIP
profile. Version 0.3.0 retains the X11 process identity so Vitrallis Shell can
focus and resume its window. It presents expandable Network, CPU, GPU, Temperature
and Memory cards using local Linux system interfaces. Hardware and driver
identification covers desktop Linux, Raspberry Pi and Allwinner/PocketCHIP sources.
It is deliberately useful when one or more sources
are absent: unavailable data is named instead of replaced with invented values.

## Runtime and launch

The app requires Linux, Python 3.8+ with system Tkinter and a graphical desktop. It has
no pip dependencies; the repository tools separately require Python 3.11+.

```sh
cd apps/vitrallis-debug
python3 main.py
# It is equally valid to use an absolute path from another directory.
python3 /path/to/apps/vitrallis-debug/main.py
# Explicit fixture mode for visual/UI checks only; it never runs implicitly.
python3 main.py --demo
```

It does not force fullscreen or install a launcher entry. The Vitrallis Shell
native App Center discovers a published manifest package after installation; this
package has not been hardware-certified on a PocketCHIP.

## Controls

Click/tap anywhere on an overview card to open its in-window details. The Back
button returns to the overview and restores the originating card focus. Tab and
Shift+Tab move between the five cards, GPU Pulse, and Home/Exit; arrow keys move
between cards; Enter, keypad Enter, and Space activate the focused control.
Expanded pages scroll using Up/Down, Page Up/Page Down, mouse wheel, or touchpad.
Tab also reaches Back, GPU Pulse, and Home/Exit on detail pages. Text uses actual
font measurements, single-line summaries ellipsize, and full details wrap in a
clipped viewport. The layout supports 400×240, 480×272 and larger windows.
Matching press/release is required for a touch activation; dragging away cancels it.

Escape first cancels an active Pulse, then leaves a detail page, then closes the
app. Home/Exit and normal window close return through the normal launcher process
lifecycle.

GPU Pulse is an eight-second foreground animation with a gentle entrance, repeated
expanding rings, and a fade out. A GLES2 fragment shader renders one triangle on a
native EGL window surface above the dashboard. The geometry and program are
uploaded once; each frame changes only time and viewport uniforms. Submission is
capped below 30 FPS, requests vsync, and never catches up in a busy loop. Stop Pulse
or Escape cancels immediately; minimizing cancels it too. No animation timer runs
while idle, and normal metric refreshes do not submit extra animation frames.
The context is reused between pulses and destroyed on exit or surface failure.

Pulse requires an X11 desktop (including XWayland), system `libX11`, `libEGL`,
`libGLESv2`, and an installed hardware OpenGL ES 2 driver matching the Tk window
visual. These are optional **system** prerequisites, not pip requirements. Other
diagnostics continue working if they are absent. The app never installs drivers,
or falls back to CPU animation. Software renderers such as
llvmpipe, softpipe and SwiftShader, and unrecognized renderer names, are refused.
The GPU detail page shows a failure reason or the renderer selected after Pulse
starts, along with the OpenGL ES version string exported by the userspace driver.
Raspberry Pi V3D/VC4 and Mali/lima hardware renderer names are recognized; a
compatible EGL window surface is still required.

Only the animation is rendered with GLES2. Tk still draws the text, controls, and
small utilization charts at the diagnostic refresh rate (about once a second).
This removes Canvas rasterization from the animation path; it does not promise
zero CPU overhead or establish a measured CPU improvement on a physical device.

## Hardware and driver identification at launch

CPU and GPU model names are discovered automatically on the first diagnostic
worker cycle, after the window opens. Identification is independent of utilization:
a readable model stays visible even when no usage counter is available. The card
shows a measured, ellipsized name; details show the full names, source interfaces,
and all detected GPUs. A sampled Linux DRM card is matched to its detected GPU
through its sysfs device rather than assuming the first GPU is the one being
measured. Without a counter, the first detected GPU appears with a count of any
additional devices. Discovery is cached for the launch; restart to refresh the
hardware inventory after a device change.

- CPU names come from `/proc/cpuinfo` (never a numeric `processor` index or a
  board name). CPU device-tree `compatible` properties provide names such as
  ARM Cortex-A8 when cpuinfo is missing or only reports a generic ARM processor.
- GPU identity comes from DRM, devfreq GPU aliases, PCI and platform sysfs devices, optional local
  `lspci -D -vmm -nn`, and GPU device-tree bindings. DRM card, render and framebuffer
  nodes for the same device are deduplicated. Without a model database, readable
  PCI IDs are shown explicitly as IDs with “model unavailable”.
- Raspberry Pi VC4 display bindings and V3D graphics bindings are reported
  separately where the kernel exposes them. An older VC4 render device is retained
  as a GPU when no separate V3D component is exposed. PocketCHIP's Allwinner R8
  and Cortex-A8 can be identified from device tree; Mali-400 and `lima` or legacy
  `mali` bindings are read when exposed. Legacy Mali platform devices are checked
  even when a separate `sun4i-drm` display card exists. A legacy kernel that exports
  only a Mali driver name retains that name with “model unavailable”.
- Each device's actual `driver` symlink supplies the bound kernel driver name.
  Its `module` link supplies the module name and exported `version`/`srcversion`
  metadata. Missing metadata is labelled “not exported”; the kernel release is
  shown separately and never passed off as the driver version. Present graphics
  modules are listed separately: module presence does not prove a device binding.
- CPU details include board model, SoC identity, kernel release and the CPU
  frequency scaling driver. Sources include `/sys/firmware/devicetree/base`
  (or `/proc/device-tree`), `/sys/devices/socN`, `/proc/sys/kernel/osrelease`, and
  cpufreq `scaling_driver`. Raw device-tree identifiers and source paths remain
  visible in details. Unrecognized SoC identifiers are not guessed.

Commands have an eight-second timeout and a 1 MiB retained-output limit. No
network lookup, root access, third-party Python package, driver install, or
persistent cache is used. Missing or unsupported sources produce an explicit
unavailable state. Names on virtual machines describe what the guest OS exposes;
physical host models cannot be inferred reliably from a VM.

Kernel and device-tree discovery happens on launch without opening a GPU context.
The userspace OpenGL ES version/renderer is read only when Pulse creates its
context; before that, its detail row says “Not checked”. Detection never loads
kernel modules, installs drivers, or alters their configuration.

## Data sources and fallbacks

- Network uses the local `ip -j address show` and `ip -j route show default`
  utilities when present. It never contacts a DNS service, public IP service, or
  any Internet endpoint. A configured address means local configuration/link only,
  **not** Internet connectivity. IPv4/IPv6 addresses, default route and gateway
  are shown by interface; loopback is not selected when a usable non-loopback
  address exists.
- CPU utilization is calculated from successive `/proc/stat` counter deltas.
  The initial reading remains “Collecting” until two samples exist; invalid deltas
  and counter resets do not produce spikes. Frequency prefers cpufreq
  `cpuinfo_cur_freq`; a `scaling_cur_freq` fallback is explicitly labelled
  *driver-reported/requested*, not a guaranteed instantaneous clock. No BogoMIPS,
  advertised maximum, hardcoded PocketCHIP rate, or guess is substituted.
- GPU reads the first valid `/sys/class/drm/cardN/device/gpu_busy_percent` counter,
  then GPU devfreq load events, then GPU 0 through optional `nvidia-smi`.
  Discovery is cached for 30 seconds. `/sys/class/devfreq/*gpu*` identities are
  matched to GPU sysfs devices and their device-tree/driver names, including
  Lima/Mali. Frequency alone is never treated as utilization.
  On PocketCHIP, the platform installer configures a root-owned service with a
  GPU-filtered private trace instance. The normal `chip` user reads only its
  `/run/vitrallis-gpu/trace_pipe` bind mount and the device's read-only current
  frequency. The tracefs root remains private. The app never configures tracefs,
  invokes sudo, changes permissions or changes GPU governors. An exclusive
  reader lock prevents consuming another app reader's stream. Samples expire
  after two seconds using monotonic time; malformed and stale values show as
  unavailable. Re-running platform setup repairs the same scoped configuration.
  Other GPU counters continue working without tracefs access. The selected
  device/source appears in details and may differ from Pulse's rendering GPU.
  Charts retain a 60-sample window with gaps for unavailable readings.
- Temperature scans Linux thermal zones and hwmon inputs. A CPU/SoC/package/core
  named source is preferred; otherwise the display says generic sensor. Values are
  shown in °C, with exposed hardware critical limits when available. No guessed
  overheat thresholds are added, and no readable sensor is a normal unavailable
  state.
- Memory uses `MemTotal - MemAvailable` in binary KiB/MiB units. If MemAvailable
  is missing it uses the documented free/buffers/cache/reclaimable fallback and
  labels that result *estimated*. Cache is not double-counted in the meter.

Each graph holds up to 60 in-memory sample slots, with gaps for missing readings. Slow or failed refreshes retain a
last valid view with a visible STALE marker and age threshold; no samples, settings,
caches, telemetry, uploads, update checks, audio, or persistent files are created.
The package directory is treated as read-only. The GPU reader writes no app storage. All declared manifest permissions are false.

## Verification and limitations

The app's parsing and interaction tests use injected data, controlled time, and
fixtures, so they do not require PocketCHIP hardware. `--demo` is clearly marked
in the UI and exists only for deterministic visual checks; production startup
never substitutes its readings. Run from the catalog root:

```sh
python3 tools/validate_catalog.py --package apps/vitrallis-debug
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/vitrallis-debug/tests -v
PYTHONPYCACHEPREFIX=/tmp/vitrallis-pycache python3 -m compileall -q apps/vitrallis-debug
# Linux EGL integration: system Mesa EGL/GLES2 + Xvfb required.
VITRALLIS_REQUIRE_GUI=1 VITRALLIS_REQUIRE_EGL=1 xvfb-run -a python3 -m unittest discover -s apps/vitrallis-debug/tests -v
```

The opt-in EGL test first checks production rejection of a software context, then
uses a test-local mock to exercise real shader compilation, drawing, resizing and
cleanup under Mesa/Xvfb. There is no application switch to allow software rendering.
This tests API correctness, **not physical GPU performance**. CI enables this test.

For GUI validation use a desktop or Linux `xvfb-run -a`, then inspect 480×272 and
800×480 captures for overview, all detail pages, active pulse, unavailable/stale
states, and long text/address cases. Desktop results are not a PocketCHIP guarantee:
physical display fit, touch behavior, kernel sensor/cpufreq availability, launch
lifecycle and actual device performance remain hardware verification work.

## Driver references

The renderer follows the [Khronos EGL specification](https://registry.khronos.org/EGL/).
GPU telemetry uses the documented [AMDGPU busy counter](https://kernel.org/doc/html/v5.10/gpu/amdgpu.html)
, the Linux [devfreq_monitor trace definition](https://github.com/torvalds/linux/blob/master/include/trace/events/devfreq.h),
[isolated ftrace instances](https://docs.kernel.org/trace/ftrace.html#instances),
and [NVIDIA SMI query interface](https://docs.nvidia.com/deploy/nvidia-smi/).
Identity detection follows the [PCI sysfs interfaces](https://kernel.org/doc/html/v5.12/PCI/sysfs-pci.html)
and [pciutils machine-readable format](https://manpages.debian.org/unstable/pciutils/lspci.8.en.html).
Embedded identities use the Linux bindings for
[Broadcom V3D](https://github.com/torvalds/linux/blob/master/Documentation/devicetree/bindings/gpu/brcm%2Cbcm-v3d.yaml),
[VC4](https://github.com/torvalds/linux/blob/master/Documentation/devicetree/bindings/display/brcm%2Cbcm2835-vc4.yaml),
[Mali Utgard](https://github.com/torvalds/linux/blob/master/Documentation/devicetree/bindings/gpu/arm%2Cmali-utgard.yaml)
and the [C.H.I.P. board tree](https://github.com/torvalds/linux/blob/master/arch/arm/boot/dts/allwinner/sun5i-r8-chip.dts).
Driver metadata follows the kernel's [module ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-module)
and [CPU sysfs ABI](https://github.com/torvalds/linux/blob/master/Documentation/ABI/testing/sysfs-devices-system-cpu).

## Publication

The source package is version 0.3.0. The repository catalog pins the published
source commit and its file hashes through the two-commit publication workflow.
App Center receives an update only after the corresponding catalog publication
is merged into the configured catalog branch.

## Artwork and licensing

`icon.png` is original raster artwork created for Vitrallis Debug: a dark diagnostic
chip with a mint pulse trace. The app has no external assets. This repository has
no established license; no license is asserted for this new app.

## Private Lima telemetry and Pulse overlay

Current platform setup provides `/run/vitrallis-gpu/trace_pipe`, a read-only bind mount of a filtered private tracefs instance. Debug opens it as the desktop user, takes an exclusive reader lock, rejects stale records, and preserves valid zero utilization. It does not create instances or modify global tracefs. The Shell PocketCHIP installer owns GPU OPP configuration and the boot service that recreates access. No manual permission commands belong in the app's startup path.

Pulse composites CPU utilization, real GPU utilization and GPU frequency directly into its completed EGL frame. Metrics upload once per second from the existing worker sample; unavailable/stale values show `--`. Tab/Shift-Tab, arrows, Enter/Space, Page Up/Down and Escape cover the dashboard, detail panels and Pulse start/stop. EGL requests backbuffer VSync; physical scanout still requires the platform presentation path described in the [rendering contract](../../docs/rendering.md).

See the [2026-09-19 verification report](../../docs/verification/platform-app-refinements-2026-09-19/README.md) for measured app performance, physical tearing confirmation, reboot evidence and installation-validation limits.
