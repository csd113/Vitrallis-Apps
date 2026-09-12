# Data, runtime behavior, and development

[Back to the project](../README.md)

## Controls and refreshes

- **Refresh** or **R** requests an update; manual requests are limited to at least 20 seconds apart, with longer waits after failures.
- **Settings** or **S** opens the settings panel. Toggle **Highlight new blocks** to enable or disable the effect (enabled by default). **Done**, **Settings**, or **S** closes the panel.
- **Tab** / **Shift+Tab** move focus; focus cycles between the toggle and Done while Settings is open. **Enter**, keypad Enter, and **Space** activate controls. Closing Settings restores focus to its toolbar button.
- Tap any dashboard card to open it, or use the arrow keys to select a card and
  **Enter**, keypad Enter, or **Space** to open it. Left/Up moves backward and
  Right/Down moves forward, wrapping across all three cards. The orange outline
  indicates keyboard selection; Tab includes the card area in the focus order.
- **Back** returns from a detail view to the selected dashboard card. **Escape**
  closes Settings first, then details, then the app. **Home** closes the app from
  the main dashboard. Settings can be opened over a detail view.
- Price and network stats refresh every two minutes while open.
- The price chart downloads every ten minutes. Blockchain size downloads every six hours because its source publishes daily samples.
- Network failures keep previous values and back off retries up to 30 minutes.
- Chart and blockchain-size failures have separate retry backoff, so optional data outages do not slow otherwise healthy quotes or network statistics. Refresh never starts a second worker for an in-flight source.

When a fresh network update reports a higher height than the previous value, the block-height card turns green and reads **NEW BLOCK** for ten seconds. Initial loading without a previous height, unchanged/lower heights, and delayed or out-of-order samples do not trigger it. Disabling the option clears any active highlight immediately. Detection follows the existing network refresh schedule. A separate Tk callback
expires the highlight after ten seconds even while details or Settings are open;
repeated heights and navigation do not extend its deadline.

Quotes older than five minutes, network stats older than fifteen minutes, and size samples older than four days are marked saved/delayed. A failed refresh also marks the relevant retained data. Chart data older than thirty minutes is labelled saved.
Absent data is labelled loading during a refresh or unavailable afterward. The
status line shows connection, certificate, rate-limit, or data errors without
including raw server responses or credentials. Older samples cannot replace
newer data. Values changing under an unchanged source timestamp still redraw.

## Card details

Each detail view reads the same validated snapshot as the dashboard and stays
current during background refreshes. Navigation adds no network requests or
persistent writes. Tap activation requires press and release on the same card;
dragging outside cancels the action and repeated taps cannot stack detail views.

- **Block height:** reported height, mainnet subsidy (excluding transaction fees),
  next halving height, and blocks remaining. The calculation uses integer
  satoshis and the 210,000-block interval from
  [Bitcoin Core's mainnet parameters](https://github.com/bitcoin/bitcoin/blob/master/src/kernel/chainparams.cpp).
  Subsidy follows [Bitcoin Core's right-shift rule](https://github.com/bitcoin/bitcoin/blob/master/src/validation.cpp)
  and shows zero with no next halving once issuance ends. The source timestamp
  is a network sample time, not the latest block's mined time.
- **Bitcoin in existence:** BTC to eight decimals, exact integer satoshis, share
  of the 21-million cap, and difference below that nominal cap. The latter is
  explicitly a comparison with 21 million, not a count of spendable or future
  mineable coins. Issuance may include coins whose keys are lost.
- **Blockchain size:** GB and MB to three decimals, what the sample includes,
  and why a node also needs space for chainstate, indexes, undo data, and growth.
  The daily sample timestamp and stale state remain visible.

## Data sources and definitions

[CoinGecko](https://docs.coingecko.com/reference/simple-price) provides the CAD quote and [24-hour chart](https://docs.coingecko.com/reference/coins-id-market-chart). Public endpoints work without a key, subject to provider availability and rate limits. An optional `COINGECKO_DEMO_API_KEY` environment variable is supported and is sent only to CoinGecko.

[Blockchain.com statistics](https://www.blockchain.com/explorer/api/charts_api) provides `n_blocks_total` and `totalbc`. Its block count includes genesis, so the displayed height is count minus one. This conversion was checked against `latestblock.height`. Supply is kept as integer satoshis (`supply_sats`) in memory and in the session cache. Only presentation converts it to BTC using Decimal, rounded to three decimal places with ties to even. Legacy caches storing BTC are still read. Reported circulating issuance includes coins whose keys may be lost; it is not the quantity available for sale.

[Blockchain size](https://www.blockchain.com/explorer/charts/blocks-size) measures block headers and transactions, excluding database indexes. Source MB is converted to decimal GB (1 GB = 1,000 MB). It is a daily published sample, not a measurement of the PocketCHIP's storage. A full archival node needs additional space for chainstate, undo data, indexes, and future growth. Exact requirements depend on configuration. **This dashboard does not download the blockchain.**

Endpoints:

- `https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=cad&include_24hr_change=true&include_last_updated_at=true`
- `https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=cad&days=1`
- `https://api.blockchain.info/stats`
- `https://api.blockchain.info/charts/blocks-size?timespan=3days&format=json`

HTTPS certificate verification stays enabled. Redirects must remain on the same
HTTPS host and port; API keys are never forwarded on redirects. Optional API keys
must be printable ASCII without whitespace, up to 512 characters. Invalid keys
produce a configuration message without including their contents.

Responses are limited to 1 MB and validated before display or caching. Each
blocking network operation has an 18-second timeout; body reads also check a
30-second budget between chunks to stop continuously trickling responses. A
pending socket operation may take its timeout to return, and system DNS remains
subject to the host resolver. Fetching and parsing stay off the UI thread.
Truncated HTTP, deeply nested JSON, and oversized numbers finish with an error
and retry instead of leaving a refresh permanently busy. Partial failures
preserve other successful updates.

## Cache and resource use

The session cache is `/run/user/<uid>/pocket-bitcoin.json`, with private, atomic writes. On the tested device this directory is a RAM filesystem. Writes are skipped if the runtime directory is absent or has unsafe ownership/permissions. The old `~/.cache/pocket-bitcoin/data.json` can seed startup when no session cache exists, but is no longer rewritten. RAM-cached updates are lost on reboot, and the app fetches fresh data at launch.
Cache/settings reads are bounded and reject nonregular files and final symlinks,
including FIFOs that would otherwise freeze startup. Cache writes reject a
symlinked runtime directory and batch updates drained in one poll into one
atomic write. Cache cleanup failures do not stop polling.

The highlight preference is stored in `~/.config/pocket-bitcoin/settings.json` with private, atomic writes only when the toggle changes. Invalid or missing settings use the enabled default. If saving fails, the panel explains that the change applies only to the current session.
Unreadable or invalid settings show a default-recovery notice. Save failures
remain visible when the panel reopens. Settings contents are flushed before
atomic replacement, preserving the previous file if writing fails.

Fetching runs off the UI thread. The canvas redraws only when data, status, or window size changes. The dashboard does not install a service or enable swap.
The chart retains extrema per horizontal pixel column and both endpoints, keeping
Tk drawing work bounded for long histories without removing spikes. Coordinate
normalization handles very large and very small finite prices safely. Extreme
numeric labels use scientific notation to stay inside their display areas.
Shutdown cancels the polling callback; daemon workers never call Tk.

The optional `bitcoin.png` is not included in this repository. Missing, oversized,
or unreadable icon files do not prevent startup. The existing dashboard artwork
and visual identity are preserved. The `launch` script's runtime contract is
unchanged. Missing Tkinter or a missing graphical session now produces a short
setup message. For certificate errors, check the device clock and trusted CA
installation; certificate verification must stay enabled.

## Tests

Data and failure-handling tests, without a display:

```sh
python3 -m unittest discover -s tests -p test_bitcoin.py -v
```

All tests, including real Tk text bounds at 480 × 272:

```sh
python3 -m unittest discover -s tests -v
python3 -m py_compile bitcoin.py tests/test_bitcoin.py tests/test_layout.py
sh -n launch
git diff --check
```

Optional developer-only static checks (Ruff is not an application dependency):

```sh
uvx ruff check --select F,B bitcoin.py tests/test_bitcoin.py tests/test_layout.py
```

Version 1.2.0 passes 51 tests locally on macOS / Tk 8.6. It expands the original
23 tests with regression coverage
for exact supply/cache migration, extreme chart values, response and file limits,
redirect/key isolation, worker completion, independent backoff, repeated input,
out-of-order samples, keyboard focus, configuration errors, slow workers, and
shutdown, all three card detail views, touch/arrow-key navigation, ten-second
expiry across navigation, and halving boundary calculations. Tests use temporary settings/cache files and mocked network data.
Physical PocketCHIP verification of this pass is still pending.

The layout test requires a graphical display and briefly creates a window. On the PocketCHIP use `DISPLAY=:0` and, if using the app-local runtime, the library environment from `launch`. The pixel-layout checks were validated with the device's DejaVu Sans fonts and Linux Tk; other platforms may have different font metrics.

Version 1.0.0 passed all **16 tests** on the PocketCHIP, including malformed data, partial outages, cache handling, API-key isolation, and loading/stale/large-number/flat-chart layouts. Live data fetching, the PocketHome shortcut, and the on-screen Home button were also checked on the device.

## Files

- `bitcoin.py` — dashboard, fetching, validation, caching, and refresh scheduling.
- `launch` — existing installation's app-local ARM runtime launcher.
- `tests/test_bitcoin.py` — data, failure-handling, block-indicator, and settings tests.
- `tests/test_layout.py` — real Tk layout, toolbar, settings, and highlight-expiry tests.
- `docs/dashboard.png` — version 1.0.0 screenshot from the PocketCHIP.
