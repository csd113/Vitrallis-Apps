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

No source commits, remote publication or catalog pin changes are authorized in
this pass. `apps.json` therefore continues to advertise its existing published
versions; new source cannot safely receive invented commit hashes or dirty-tree
inventories. Root `CHANGELOG.md` records published catalog versions and must not
announce these unpublished source releases as already available.

After review and explicit authorization, follow `docs/publishing-apps.md`: commit
and publish the tested source, then use its full reachable SHA with
`tools/update_catalog.py` for all five packages. Add the matching Added/Updated
root changelog records when generating those pins, submit source and catalog
together through a PR, and retain source commits when merging. Required committed
publication checks cannot establish agreement with these uncommitted edits yet.

Runtime validation scope is Carousel, Calculator and Bitcoin. Icon-only Debug and
Firefly changes receive asset/package checks without launching either app.
