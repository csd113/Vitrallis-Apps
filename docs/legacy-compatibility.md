# Legacy compatibility and implementation boundaries

This page documents the official catalog's existing integration. It is not a
requirement that every publisher use PocketCHIP, the Bitcoin ID or these paths.

## Bitcoin snapshot

`Apps/Bitcoin-Dashboard` remains byte-for-byte unchanged, including its original
docs, tests and executable launcher. The production entry remains
`io.vitrallis.bitcoindashboard`, version `1.2.0`, source commit
`ab2869b2cf25818cfcf09f5d1fc7055dfbb9a218`, with nine files and `installable: true`.
The snapshot does not include `app.toml`, `main.py` or `icon.png` and is explicitly
legacy. Do not move it into `apps/` merely to normalize casing.

Its original source import is
[9d732e056801c8a98ee3edb60cb5bd88646ac467](https://github.com/csd113/PocketChip-Bitcoin-Display/tree/9d732e056801c8a98ee3edb60cb5bd88646ac467).
The preserved upstream README describes upstream installation/release URLs; these
are provenance, not instructions for configuring a generic catalog.

## App manager

The inspected [Pocketchip-update-apps 1.6.0 implementation](https://github.com/csd113/Pocketchip-update-apps/tree/946f69ec58fe4327f60bda6e615dbded5491b541)
consumes the official JSON catalog for Bitcoin. It validates all nine source
files and uses a reviewed adapter to install `bitcoin.py` at the existing
`~/.local/share/pocket-bitcoin/` location, supply launcher/icon assets, and register
the existing PocketHome entry. It retains independent self-updates. Its fixed URL,
repository policy and adapter do not become publisher-neutral by changing this
repository's schema. Compatibility with its 1.6.x expectations is preserved by
leaving the production entry and snapshot unchanged.

Existing documentation reports desktop first-install/update/backup/repair checks;
physical PocketCHIP verification of 1.6.0 is still pending. This repository work
uses desktop checks only and does not certify hardware installation.

## Shell

The inspected [Vitrallis-Shell app-development documentation](https://github.com/csd113/Vitrallis-Shell/blob/75c4ab7929be47c6bbfb6740adca51930290e8ea/docs/app-development.md)
describes PocketHome/Marshmallow JSON menu discovery and explicitly has no TOML
loader. This repository now defines manifest v1 as the official package contract;
that does not implement a loader in another repository. Shell support is
version-dependent. Confirm the target revision and use its documented launcher
adapter before claiming discoverability or enabling installation.
