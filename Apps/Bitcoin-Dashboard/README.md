# Bitcoin CAD for PocketCHIP

A lightweight Bitcoin dashboard for the PocketCHIP's **480 × 272** display,
built with Python and Tkinter. Current version: **1.2.1**.

[Latest release](https://github.com/csd113/PocketChip-Bitcoin-Display/releases/latest)
· [Changelog](CHANGELOG.md)
· [App updater](https://github.com/csd113/Pocketchip-update-apps)

![Bitcoin CAD v1.0.0 running on PocketCHIP; v1.2.0 also adds Settings and card detail views](docs/dashboard.png)

## Features

- Bitcoin price in Canadian dollars, 24-hour change, and a price chart.
- Latest reported block height, circulating supply, and dated blockchain size.
- Tap any network card, or select it with the arrow keys and press Enter, for details.
- Optional ten-second **NEW BLOCK** highlight with a persistent Settings toggle.
- Background refreshes, retries, and saved-data indicators during network outages.
- High-contrast touch controls and RAM session caching to reduce flash writes.

Market data comes from CoinGecko; network statistics come from Blockchain.com.
This is a dashboard—it does not download the blockchain.

## Install or update on PocketCHIP

Use [Update Apps for PocketCHIP](https://github.com/csd113/Pocketchip-update-apps#install-or-upgrade).
Its **Check for updates → Install / update** flow installs Bitcoin CAD if missing,
adds Home/desktop shortcuts, and updates existing installations.

The updater prompts before closing a running Bitcoin app and leaves it closed
after installation. Restart PocketHome after a first install to load its icon.

### Run directly with system Tkinter

Requires Python 3, Tkinter, and a graphical desktop. There are no pip dependencies.
On Debian, install Tkinter if needed:

```sh
sudo apt install python3-tk
```

Then clone and run:

```sh
git clone https://github.com/csd113/PocketChip-Bitcoin-Display.git
cd PocketChip-Bitcoin-Display
python3 bitcoin.py
```

Run this inside the device's graphical session. If an optional `bitcoin.png`
exists beside the script, it is used as the window icon.

### Existing app-local runtime

The included `launch` script expects the app in `~/.local/share/pocket-bitcoin/`
and an ARM Python 3.13 / Tcl 8.6 / Tk 8.6 runtime in that directory's `runtime/usr/`.
Runtime binaries are not included. Use `python3 bitcoin.py` for system Tkinter.

For a manual source update, close Bitcoin and back up `bitcoin.py` first, then
run these commands from the downloaded source directory:

```sh
install -d "$HOME/.local/share/pocket-bitcoin"
install -m 644 bitcoin.py README.md "$HOME/.local/share/pocket-bitcoin/"
```

The existing launcher and Home shortcut can remain in place.

## Controls

| Control | Action |
| --- | --- |
| Refresh / R | Request fresh data when the cooldown allows |
| Settings / S | Open or close Settings |
| Tab / Shift+Tab | Move keyboard focus; cycle within Settings while open |
| Arrow keys | Select a dashboard card (Left/Up backward, Right/Down forward) |
| Enter / Space | Open the selected card or activate a focused control |
| Back | Return from card details to the dashboard |
| Home | Close the app |
| Escape | Close Settings first, then card details, otherwise close the app |

The block card turns green for **10 seconds** when a fresh sample reports a higher
block height. Repeated samples and navigation do not extend the highlight. Detection follows the network refresh schedule rather than a live stream.
Settings persist across launches; a save failure is shown in the panel.
Unreadable settings use the default and show a notice in Settings. Missing data
is labelled unavailable; retained older values are labelled saved. Connection,
rate-limit, malformed-data, and certificate errors appear in the status line
while the app retries automatically. Refresh cooldowns prevent repeated requests.

Card details include subsidy and halving progress, full eight-decimal BTC and
satoshi supply totals, and blockchain size in GB/MB with node-storage context.
Details update with the dashboard data and show loading, unavailable, or saved
status. Tap **Back** or press **Escape** to return to the selected card.

## Data and development

See [data sources, refresh timing, cache behavior, and tests](docs/development.md)
for technical details. The [changelog](CHANGELOG.md) records changes by version.
Release tags use `vMAJOR.MINOR.PATCH`; the `VERSION` constant in `bitcoin.py`
is read by Update Apps.

Report problems in
[GitHub Issues](https://github.com/csd113/PocketChip-Bitcoin-Display/issues),
including the app version and any error message.
