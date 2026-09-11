# Vitrallis Apps

Application source code and development guidance for Vitrallis.

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

It retains its original PocketCHIP launcher and storage paths. It has not yet been converted to the manifest-based Vitrallis package described in the guide; `app.toml`, `main.py`, and a packaged icon are not included upstream. Vitrallis shell integration and device compatibility remain to be verified.
