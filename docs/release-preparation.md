# 2026-10-01 release preparation

The working tree prepares these source versions:

| Package | Version | Concrete change |
| --- | --- | --- |
| `apps/vitrallis-media-carousel` | 0.4.2 | Pixel-measured names/status wrapping and refresh focus retention |
| `apps/calculator` | 0.1.0 | Keyboard-first decimal calculator with precedence and bounded input |
| `apps/bitcoin-dashboard` | 1.3.0 | mempool.space network/watch pages, local watch list and shared Tor transport |
| `apps/vitrallis-debug` | 0.3.2 | Transparent, readable generated launcher icon |
| `apps/firefly-field` | 0.3.1 | Transparent, readable generated launcher icon |

Calculator's manifest (`io.vitrallis.calculator`, Python `main.py`, no permissions)
is the package/install and launcher definition. Proposed App Center description:
“PocketCHIP decimal calculator with keyboard navigation, percent and parentheses.”
Compatibility: “Requires Python 3.11+ and system Tkinter; compositor-backed static
presentation. Device install/update/repair verification pending.” Keep installation
disabled until that verification is complete.

The user authorized source publication and merging on 2026-10-01. Source commit
`0ebb648e06958b4971686ff8c30aad7ec41b14e4` was pushed before generating catalog
inventories. All five versions are pinned to that published commit. The matching
root release records are included with the catalog update. Calculator and the new
Bitcoin release are installation-disabled pending device and real Arti checks;
other existing installation flags are preserved.

Source and catalog are submitted together through a pull request, with a merge
commit retaining all source pins. Required checks must pass before merging.
Runtime validation scope is Carousel, Calculator and Bitcoin. Icon-only Debug and
Firefly changes receive asset/package checks without launching either app.
