# Vitrallis Debug

Vitrallis Debug is an offline instrument panel for a 480×272 Vitrallis/PocketCHIP
profile. It presents expandable Network, CPU, Temperature and Memory cards using
local Linux interfaces only. It is deliberately useful when one or more sources
are absent: unavailable data is named instead of replaced with invented values.

## Runtime and launch

The app supports Python 3.8+ with system Tkinter and a graphical desktop. It has
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
Shift+Tab move between the four cards, Pulse, and Home/Exit; arrow keys move
between cards; Enter, keypad Enter, and Space activate the focused control.
Expanded pages scroll using Up/Down, Page Up/Page Down, mouse wheel, or touchpad.
Matching press/release is required for a touch activation; dragging away cancels it.

Escape first cancels an active Pulse, then leaves a detail page, then closes the
app. Home/Exit and normal window close return through the normal launcher process
lifecycle.

Pulse is a short, bounded Canvas radar/energy animation. It runs for about two
seconds from monotonic time, is capped near 24 FPS, ignores repeat activation
while running, and uses a fixed set of Canvas objects.

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
- Temperature scans Linux thermal zones and hwmon inputs. A CPU/SoC/package/core
  named source is preferred; otherwise the display says generic sensor. Values are
  shown in °C, with exposed hardware critical limits when available. No guessed
  overheat thresholds are added, and no readable sensor is a normal unavailable
  state.
- Memory uses `MemTotal - MemAvailable` in binary KiB/MiB units. If MemAvailable
  is missing it uses the documented free/buffers/cache/reclaimable fallback and
  labels that result *estimated*. Cache is not double-counted in the meter.

The overview holds up to 60 in-memory samples. Slow or failed refreshes retain a
last valid view with a visible STALE marker and age threshold; no samples, settings,
caches, telemetry, uploads, update checks, audio, or persistent files are created.
The package directory is treated as read-only. All declared manifest permissions
are false.

## Verification and limitations

The app's parsing and interaction tests use injected data, controlled time, and
fixtures, so they do not require PocketCHIP hardware. `--demo` is clearly marked
in the UI and exists only for deterministic visual checks; production startup
never substitutes its readings. Run from the catalog root:

```sh
python3 tools/validate_catalog.py --package apps/vitrallis-debug
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/vitrallis-debug/tests -v
PYTHONPYCACHEPREFIX=/tmp/vitrallis-pycache python3 -m compileall -q apps/vitrallis-debug
```

For GUI validation use a desktop or Linux `xvfb-run -a`, then inspect 480×272 and
800×480 captures for overview, all detail pages, active pulse, unavailable/stale
states, and long text/address cases. Desktop results are not a PocketCHIP guarantee:
physical display fit, touch behavior, kernel sensor/cpufreq availability, launch
lifecycle and actual device performance remain hardware verification work.

## Artwork and licensing

`icon.png` is original raster artwork created for Vitrallis Debug: a dark diagnostic
chip with a mint pulse trace. The app has no external assets. This repository has
no established license; no license is asserted for this new app.
