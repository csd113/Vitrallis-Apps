# PocketCHIP support

The PocketCHIP edition of Places is the game source at the repository root:
the renderer, the runtime profile and the build configuration are all chosen
for that device, and `docs/POCKETCHIP.md` is the target document. Nothing under
this directory is part of that build.

`vitrallis/` is the historical deployment manifest and precompiled ARMv7
payload from the earlier PocketCHIP packaging. It predates the current
cross-compilation workflow, pins an outdated version, and is kept for reference
only — `docs/POCKETCHIP.md` describes how the handheld binary is built and
deployed now.

This directory is a development tree, not a catalogued package: it carries no
`app.toml`, ships 39 MB of source artwork and 22 MB of reference captures, and
is not listed in `apps.json`. The repository's catalog validation loop expects
every `apps/<slug>` directory to be a manifest v1 package under the 16 MiB
bundle limit, so `tools/validate_catalog.py --package apps/places-pocketchip`
still reports the tree as too large; publishing this edition as a package would
be a separate packaging release with its own manifest, asset budget and catalog
pin.
