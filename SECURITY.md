# Security policy

Security reports are welcome for Vitrallis Apps packages, catalog metadata,
validation, and publication tooling. Installer, launcher, and App Center issues
belong to [Vitrallis Shell](https://github.com/csd113/Vitrallis-Shell); consult
that project's security guidance for its reporting process.

## Reporting a vulnerability

Do not put exploit details, malicious payloads, access codes, API keys, or private
device data in a public issue or pull request.

Use **Report a vulnerability** on the repository's
[Security page](https://github.com/csd113/Vitrallis-Apps/security) when available.
**Private vulnerability reporting is currently disabled, and no dedicated private
security address is published.** Until the owner provides a private channel,
open an issue titled “Private security contact requested” with no technical or
identifying details, or ask the repository owner through a contact method they
publish on their [GitHub profile](https://github.com/csd113). Wait for a private
channel before sharing the report. A public issue is not a confidential channel.

Once a private route is established, include:

- Affected app/tool, version, catalog source pin, and Shell version if relevant.
- Device/OS/runtime, the trust boundary crossed, and the expected impact.
- Minimal reproduction steps using synthetic files and disposable storage.
- Any mitigation you have verified, without including real credentials or user data.

There is no published response-time or long-term support commitment. Vitrallis is
pre-release; start from the current catalog version and report older affected
versions too. Do not assume an old version receives backported fixes.

## Trust and deployment boundaries

- Catalog pins and SHA-256 checksums let clients verify advertised bytes. They
  do not independently authenticate the publisher or make untrusted code safe.
- Manifest network/audio/storage flags declare requirements. Apps run with the
  launching user's privileges and are not sandboxed by this format.
- Validate external metadata, files, paths, and source inventories before use.
  Keep credentials, caches, and private data out of packages: all app files
  outside `tests/` are published.
- Media Carousel's management interface uses unencrypted HTTP and a per-launch
  access code. Use a trusted LAN and do not forward its port to the Internet.
  Follow its [security and limits](apps/vitrallis-media-carousel/README.md#limits-and-security),
  and keep Pillow and FFmpeg current.

For the exact validation and client responsibilities, see
[catalog trust boundaries](docs/catalog-format.md#verification-and-trust-boundaries)
and [runtime integration](docs/runtime-integration.md). Ordinary setup problems
and non-sensitive bug reports go through [Support](SUPPORT.md).
