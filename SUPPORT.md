# Getting help

Start with the [available apps](README.md#available-apps) and the affected app's
README. Each describes controls, dependencies, storage, and known limitations.
The [documentation index](docs/README.md) covers creating and hosting apps.

## Where to ask

| Question or problem | Best place |
| --- | --- |
| App behavior, package content, catalog metadata, or repository tools | [Vitrallis Apps issues](https://github.com/csd113/Vitrallis-Apps/issues) |
| Shell installation, App Center controls, launcher, update/repair, or uninstall | [Shell App Center guide](https://github.com/csd113/Vitrallis-Shell/blob/main/docs/app-center.md), then [Shell issues](https://github.com/csd113/Vitrallis-Shell/issues) |
| A third-party catalog or modified app | Its publisher, with the catalog and source repository identified |
| Security vulnerability or suspected trust bypass | [Security policy](SECURITY.md); keep details out of public issues |

Search existing issues first. Use the bug report or feature request form when it
fits; a blank issue is available for usage questions and documentation corrections.
There is no dedicated help desk or guaranteed response time.

## Before filing a report

- **Install unavailable or missing dependencies:** choose Refresh, select the app,
  and read Details. Compare its prerequisites with [runtime integration](docs/runtime-integration.md).
  App Center reports missing Python/Tk/Pillow dependencies but does not install
  system packages. Do not bypass checksum, trust, or recovery errors.
- **Validator cannot find a commit:** use a full clone/fetch of the trusted source
  or an explicit `--source-repo` mapping. See [catalog verification](docs/catalog-format.md#verification-and-trust-boundaries).
- **Tests cannot open a window:** follow [testing setup](docs/testing.md); Tkinter
  needs a graphical session or Linux/Xvfb.
- **Media Carousel upload or playback problem:** consult its
  [troubleshooting guide](apps/vitrallis-media-carousel/README.md#troubleshooting).
  Never include the management access code in screenshots or logs.
- **Debug shows unavailable readings:** Linux sensor, CPU, and network interfaces
  vary by device. An unavailable reading is not automatically a fault; include
  the missing field and your hardware/OS.

## Make a report reproducible

Include the app name/ID and version (or tool command and repository commit),
Shell version where relevant, catalog source, device/OS, Python/Tk versions,
and display size. Describe steps, expected and actual results, and the exact
error. State whether the failure occurs when launched directly, through the
Shell, or during installation. Include a small synthetic fixture when useful.

Redact access codes, API keys, usernames, private paths, network addresses, and
personal media. A report does not need a whole home directory, media library,
or unfiltered diagnostic dump. Follow the [Code of Conduct](CODE_OF_CONDUCT.md)
when discussing problems and proposed fixes.
