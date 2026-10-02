# Apps polish verification — 2026-10-01

Host: macOS 27.0.1 arm64, Python 3.13.5, Tk 8.6 and Pillow 12.1.0.
Screenshots are actual 480×272 desktop windows. Bitcoin values are fixtures;
Carousel uses temporary storage and a closed loopback management server. The
Mac's native Tk controls differ from Debian/X11 controls. No PocketCHIP or real
Arti service was exercised, and no physical VSync/tearing claim is made.

## Result

Carousel 0.4.2 retains its playback/GPU architecture, asynchronous startup,
bounded frame catch-up, warm image cache and hidden-window idle path. Names and
status tokens fit by font measurements, including a bounded ellipsis. A library
refresh preserves the selected collection or header focus. Native macOS button
labels now remain readable. Startup/exit, settings, keyboard focus, media paths
and existing performance regressions pass.

Calculator 0.1.0 is a standard-library Python/Tk package with no new dependency.
Its bounded recursive-descent parser uses 28-digit Decimal arithmetic, precedence,
parentheses, postfix percent and scientific exponents. It handles signed input,
clear/backspace, repeated evaluation, chained results, malformed input,
divide-by-zero and overflow. Display uses 12 significant digits and compact
notation. A 4×5 keypad, separate parentheses controls and keyboard shortcuts fit
480×272; typing, focus navigation, startup and SIGTERM exit were verified.

Bitcoin 1.3.0 opens on mempool.space network information, with a separate watch
page and the existing CAD chart retained. Up to eight labeled mainnet addresses
use Base58Check/Bech32/Bech32m validation, including BIP350 Taproot vectors.
Confirmed/pending balances use exact integer satoshis; lifetime counters can
exceed supply while the resulting balance remains bounded. Recent transactions
show confirmation and net address movement. Local watch-list edits are atomic,
invalid existing files are preserved, and successful data remains cached on
failure. Only the selected address is refreshed. One cancellable worker owns no
Tk objects; a refresh publishes only complete watch snapshots. Timeouts, a 1 MB
response cap, five-minute automatic refresh, manual rate limiting and bounded
backoff keep network work out of rendering.

The official mempool route implementation and Esplora API contract were inspected
before implementation. The implementation consumes `v1/blocks`,
`v1/fees/recommended`, `mempool`, `address/:address` and `address/:address/txs`
under `https://mempool.space/api/`. The preserved chart additionally uses its
existing CoinGecko/Blockchain.com providers.

Bitcoin requests the existing Shell Arti service with `tor = "preferred"`.
Shell API-v1 traffic uses loopback SOCKS5 with remote DNS and verified TLS.
Unavailable/invalid Tor or proxy errors have no direct fallback. Standalone
launch without the contract uses HTTPS. Fake SOCKS tests verify remote names,
connection errors and fail-closed configuration. Apps-side validation now
strictly accepts Shell's optional networking table; Shell was not changed.

Calculator, Debug 0.3.2 and Firefly 0.3.1 received optimized transparent GPT-generated
icons, respectively 13,310, 14,692 and 12,410 bytes. Carousel, Bitcoin and Places
art was retained after audit. All six package icons are 128×128 and reviewed at
32 pixels; prompts and processing are in [artwork](../../artwork.md). Terminal,
Notepad and Files are Shell companions and were not changed.

## Test scope and performance

Previously CI launched every application suite plus the examples on every push
or PR. It now keeps global package/catalog/changelog/tooling checks and Python
compilation while selecting runtime suites from package ownership, transitive
local imports, Cargo path/workspace dependencies and explicit dynamic dependency
files. Changes to documentation, manifests and icons do not boot applications.
Runtime requirements are installed only for selected suites; graphical setup is
skipped entirely for an empty runtime scope. Explicit `--app` selection adds to
the affected scope. Invalid dependency declarations and unsafe paths fail closed.

This working tree selects exactly Bitcoin, Calculator and Carousel, excluding
icon-only Debug/Firefly, Places and the examples. Five scope-preview processes
averaged **0.251 seconds** on this Mac. Calculator's complete five-test suite ran
in **0.510 seconds**. Carousel's full suite ran in **57.457 seconds**. These are
host measurements, not R8 performance or a measured before/after device speedup.
Existing tests confirm no folder rebuild without a revision change, warm image
reuse, paused/static/hidden behavior and bounded presentation scheduling. No
expensive new animation or continuous calculator redraw loop was introduced.

## Commands and exact results

Commands ran from the repository root. Test logs were captured outside packages
under `/tmp/vitrallis-*.log`; compilation caches also stayed outside packages.

| Command/check | Result |
| --- | --- |
| `PYTHONDONTWRITEBYTECODE=1 VITRALLIS_REQUIRE_GUI=1 python3 tools/scoped_tests.py --run` | Passed: Bitcoin 66, Calculator 5, Carousel 271 tests; Carousel skipped one opt-in real EGL test on macOS |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/bitcoin-dashboard/tests -v` after final Bitcoin fixes | Passed: 69 tests, 2.935 seconds |
| `python3 -B -m unittest discover -s apps/bitcoin-dashboard/tests -p test_monitor.py -v` after adding BIP350 vector cases | Passed: 7 tests |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/calculator/tests -v` after final UI/art changes | Passed: 5 tests, 0.510 seconds |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s apps/vitrallis-media-carousel/tests -p test_ui.py -v` after final UI changes | Passed: 31 tests, 32.373 seconds |
| `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -v` | Passed: 74 tests, 27.368 seconds |
| `python3 tools/validate_catalog.py --package apps/calculator --package apps/bitcoin-dashboard --package apps/vitrallis-media-carousel --package apps/vitrallis-debug --package apps/firefly-field` | Passed: all five prepared package versions, PNGs and matching app changelogs |
| `python3 tools/validate_catalog.py --source-repo csd113/Places=/tmp/vitrallis-places-source` | Passed: five published apps, pinned bytes verified |
| `python3 tools/validate_changelogs.py --source-repo csd113/Places=/tmp/vitrallis-places-source` | Passed: five committed published histories and versions; does not establish publication agreement for uncommitted source |
| `PYTHONPYCACHEPREFIX=/tmp/vitrallis-polish-pycache python3 -m compileall -q tools apps examples` | Passed |
| `git diff --check` | Passed |
| Workflow YAML parsing via Ruby YAML, embedded Python parsing via `ast.parse` | Passed; GitHub Actions itself was not run |
| Absolute-path Calculator child launch from a temporary working directory, followed by SIGTERM | Passed: exit 0 |
| Pillow asset checks and 32-pixel contact-sheet review | Passed: six valid 128×128 icons, optimized new assets, transparent corners and full alpha range for all three generated icons |
| Live `network_snapshot(fetch)` request with `SSL_CERT_FILE=/etc/ssl/cert.pem` | Passed: current mempool.space response parsed with verified system CA trust |

The initial live request using this Python installation's default CA store failed
certificate verification. Verification was never disabled; the successful check
used the Mac's existing system CA bundle only for that process. The UI now reports
TLS clock/certificate configuration failures clearly.

No Rust source changed. Rust formatting, strict Clippy and Cargo tests were not
run on unrelated apps. The scoped runner preserves all three required Cargo
commands for affected Rust packages and preserves the Rust example's staged host
build/launch when that example is selected.

## Remaining release/device work

At the initial handoff, source changes were uncommitted and unpublished by
instruction. The user subsequently authorized publication and merging. Source
commit `0ebb648e06958b4971686ff8c30aad7ec41b14e4` was pushed before generating
all five catalog inventories and matching root release records. Calculator and
the new Bitcoin release remain installation-disabled pending device verification. Follow [release preparation](../../release-preparation.md)
and the existing source-first publication policy. The completed committed release must pass the required publication checks
before merging.

Real PocketCHIP installation/update/repair, keyboard hardware, R8 memory/CPU,
compositor buffering/VSync and real Arti bootstrapping/routing remain unverified.
Tk static-window presentation depends on the device compositor. In-flight network
requests are timed and cancellable between requests; the daemon worker does not
hold exit open. Watch caches are intentionally session-local, and only the active
address refreshes automatically. External APIs remain availability dependencies.

## Desktop screenshots

- [Calculator](calculator.png)
- [Bitcoin network](bitcoin-network.png)
- [Bitcoin watch](bitcoin-watch.png)
- [Add address](bitcoin-add.png)
- [Carousel home](carousel-home.png)
- [Carousel settings](carousel-settings.png)
- [128/32-pixel icon contact sheet](icons.png)

## Files changed
- `.github/workflows/validate.yml`
- `CONTRIBUTING.md`
- `README.md`
- `apps/bitcoin-dashboard/CHANGELOG.md`
- `apps/bitcoin-dashboard/README.md`
- `apps/bitcoin-dashboard/app.toml`
- `apps/bitcoin-dashboard/main.py`
- `apps/bitcoin-dashboard/tests/test_layout.py`
- `apps/firefly-field/CHANGELOG.md`
- `apps/firefly-field/app.toml`
- `apps/firefly-field/assets/README.md`
- `apps/firefly-field/icon.png`
- `apps/vitrallis-debug/CHANGELOG.md`
- `apps/vitrallis-debug/README.md`
- `apps/vitrallis-debug/app.toml`
- `apps/vitrallis-debug/assets/README.md`
- `apps/vitrallis-debug/icon.png`
- `apps/vitrallis-media-carousel/CHANGELOG.md`
- `apps/vitrallis-media-carousel/README.md`
- `apps/vitrallis-media-carousel/app.toml`
- `apps/vitrallis-media-carousel/main.py`
- `apps/vitrallis-media-carousel/tests/test_package.py`
- `apps/vitrallis-media-carousel/tests/test_ui.py`
- `apps/vitrallis-media-carousel/ui.py`
- `docs/README.md`
- `docs/creating-apps.md`
- `docs/testing.md`
- `tools/catalog_lib.py`
- `tools/tests/test_catalog.py`
- `apps/bitcoin-dashboard/monitor.py`
- `apps/bitcoin-dashboard/monitor_ui.py`
- `apps/bitcoin-dashboard/tests/test_monitor.py`
- `apps/bitcoin-dashboard/tests/test_monitor_ui.py`
- `apps/bitcoin-dashboard/tor_transport.py`
- `apps/calculator/CHANGELOG.md`
- `apps/calculator/LICENSE`
- `apps/calculator/README.md`
- `apps/calculator/app.toml`
- `apps/calculator/assets/README.md`
- `apps/calculator/calculation.py`
- `apps/calculator/icon.png`
- `apps/calculator/main.py`
- `apps/calculator/requirements.txt`
- `apps/calculator/tests/test_calculation.py`
- `apps/calculator/tests/test_ui.py`
- `docs/artwork.md`
- `docs/release-preparation.md`
- `docs/verification/apps-polish-2026-10-01/README.md`
- `docs/verification/apps-polish-2026-10-01/bitcoin-add.png`
- `docs/verification/apps-polish-2026-10-01/bitcoin-network.png`
- `docs/verification/apps-polish-2026-10-01/bitcoin-watch.png`
- `docs/verification/apps-polish-2026-10-01/calculator.png`
- `docs/verification/apps-polish-2026-10-01/carousel-home.png`
- `docs/verification/apps-polish-2026-10-01/carousel-settings.png`
- `docs/verification/apps-polish-2026-10-01/icons.png`
- `tools/scoped_tests.py`
- `tools/tests/test_scope.py`
