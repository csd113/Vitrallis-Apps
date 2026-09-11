# Changelog

Changes are listed newest first. Dates use America/Vancouver time.

## 1.2.0 — 2026-09-10

- Extend the green **NEW BLOCK** highlight to 10 seconds, with an explicit expiry
  callback. Repeated heights and navigation do not restart the timer.
- Make all three network cards tappable and selectable with arrow keys plus
  Enter/keypad Enter or Space. Back/Escape returns to the selected card.
- Add card details for subsidy/halving progress, exact BTC/satoshi supply, and
  blockchain size/storage context. Details share existing data and refreshes.
- Show actionable connection, certificate, rate-limit, and data errors; distinguish
  missing data from saved values and preserve Settings recovery/save notices.
- Add S, Enter/keypad Enter, visible keyboard focus, and contained Settings tab
  navigation; restore toolbar focus when closing the panel.
- Prevent extreme numeric labels and chart coordinates from overflowing the
  480 × 272 layout; bound chart drawing while preserving spikes.
- Keep circulating supply in integer satoshis and format BTC exactly; retain
  compatibility with legacy caches and reject out-of-order updates.
- Recover from truncated HTTP, deeply nested JSON, and numeric overflow; bound
  response reads and back off chart/size retries independently of healthy data.
- Limit API redirects to the same HTTPS origin and prevent API-key forwarding.
- Harden cache/settings reads and atomic writes, batch cache updates, tolerate
  broken optional icons, and cancel polling on shutdown.
- Expand data, failure, layout, and keyboard regression tests. No application
  dependencies added; the launcher remains unchanged.

Validation: 51 tests passed on macOS / Tk 8.6, including all detail layouts at
480 × 272 and touch/keyboard navigation. Physical PocketCHIP testing is pending.

[Release](https://github.com/csd113/PocketChip-Bitcoin-Display/releases/tag/v1.2.0)

## 1.1.0 — 2026-09-09

### Added

- A five-second green **NEW BLOCK** highlight when a fresh network sample reports
  a higher block height. Initial loading, unchanged/lower heights, and delayed
  or out-of-order samples do not trigger it.
- A Settings panel beside Refresh with a **Highlight new blocks** toggle,
  enabled by default. Disabling it clears an active highlight immediately.
- Persistent settings saved atomically only when changed, with a visible message
  if saving fails.
- Tests for block detection, highlight expiry, settings persistence, failure
  handling, and the settings layout.

### Changed

- Moved the version label to the bottom center as **app version 1.1.0**.
- Escape closes Settings before closing the app when the panel is open.

The existing refresh schedule is unchanged and no dependencies were added.

[Release](https://github.com/csd113/PocketChip-Bitcoin-Display/releases/tag/v1.1.0)
· [Implementation](https://github.com/csd113/PocketChip-Bitcoin-Display/commit/943ad81)

## 1.0.0 — 2026-09-09

### Added

- First numbered release, with a literal `VERSION` constant for Update Apps and
  an on-screen **v1.0.0** label.

Dashboard behavior was unchanged from the initial unversioned build below.

[Release](https://github.com/csd113/PocketChip-Bitcoin-Display/releases/tag/v1.0.0)
· [Implementation](https://github.com/csd113/PocketChip-Bitcoin-Display/commit/2d09c49)

## Initial unversioned build — 2026-09-09

### Added

- A Python/Tkinter Bitcoin dashboard for the PocketCHIP's 480 × 272 display.
- CAD price, 24-hour change and price chart, reported block height, circulating
  supply, and dated blockchain block-data size in GB.
- Independent market/network refreshes, manual refresh, retry backoff, and
  saved/delayed-data indicators that preserve usable data during outages.
- High-contrast, touch-friendly layout with text fitting, Home/Escape exit,
  and the R refresh shortcut.
- RAM session caching to reduce flash writes, background fetching, and redraws
  only when displayed data changes.
- HTTPS and response validation, optional CoinGecko demo API-key support,
  an app-local runtime launcher, and data/layout tests.

[Implementation](https://github.com/csd113/PocketChip-Bitcoin-Display/commit/cd1f1d7)
