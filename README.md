# Vitrallis Apps

Application source code and development guidance for Vitrallis.

- [App catalog](apps.json): machine-readable app versions and commit-pinned file checksums. App managers should fetch [the raw JSON](https://raw.githubusercontent.com/csd113/Vitrallis-Apps/main/apps.json).
- [Catalog format and update workflow](docs/app-catalog.md): schema, version comparison, integrity checks, and current manager integration status.
- [Vitrallis app build guide](VITRALLIS_APP_BUILD_GUIDE.md): reusable instructions for AI developers, including the proposed package structure, manifest, interface conventions, and validation requirements.
- [Bitcoin Dashboard](Apps/Bitcoin-Dashboard/README.md): the PocketCHIP Bitcoin CAD dashboard, imported with its source, tests, launcher, and documentation.

## Bitcoin Dashboard import

Source: [csd113/PocketChip-Bitcoin-Display](https://github.com/csd113/PocketChip-Bitcoin-Display)

Imported commit: [`9d732e056801c8a98ee3edb60cb5bd88646ac467`](https://github.com/csd113/PocketChip-Bitcoin-Display/commit/9d732e056801c8a98ee3edb60cb5bd88646ac467)

The files in `Apps/Bitcoin-Dashboard` are an unchanged source snapshot. This copy does not automatically synchronize with the upstream repository.

The app currently runs with Python 3 and Tkinter:

```sh
cd Apps/Bitcoin-Dashboard
python3 bitcoin.py
```

It retains its original PocketCHIP launcher and storage paths. It has not yet been converted to the manifest-based Vitrallis package described in the guide; `app.toml`, `main.py`, and a packaged icon are not included upstream. Installation uses the app manager's reviewed Bitcoin adapter, which supplies its own launcher/icon and registers the existing PocketHome entry that Vitrallis reads.

The catalog lists Bitcoin Dashboard at **1.2.0** with installation enabled for [Pocketchip-update-apps 1.6.0 or later](https://github.com/csd113/Pocketchip-update-apps/blob/946f69ec58fe4327f60bda6e615dbded5491b541/docs/updates.md). That manager reads this JSON for Bitcoin versions and verifies the pinned source files. It continues to update itself from its own repository. Desktop install/update/repair and layout checks passed; physical PocketCHIP verification of manager 1.6.0 remains pending.
