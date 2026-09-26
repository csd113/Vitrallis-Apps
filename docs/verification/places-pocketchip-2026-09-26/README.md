# Places PocketCHIP verification — 2026-09-26

## Published package and device

Places 0.11.1 first shipped in Vitrallis-Apps commit
`86c1fe4b908a34ef99cdc0fe1054d2711a8260ec` and is mirrored byte-for-byte
at `csd113/Places` commit `b208b4647d20b1e2a9cf75f733afe1d207b8301d`.
The catalog uses the latter source so existing Places 0.3.1 installations can
update without a publisher/source switch. The packaged ARMv7 executable
has SHA-256 `788ef0745f803c6f80aec0c81c6a00a64a100079acdf4cb16078b298cc7e8fde`.
The same executable and packaged assets were staged under
`/tmp/codex-places-qa-20260926` on the owner's USB-connected PocketCHIP.
The staging directory was separate from the owner's App Center installation and
application data.

The device reports ARMv7, Debian 13, glibc 2.41, SDL2 2.32.4, and the running
Vitrallis Shell. The package and catalog validators passed. The game launched
under X11 and exited successfully in a bounded run. Captures taken through its
own framebuffer path showed the main menu and a rendered pool-hall scene at
480 × 272 with no obvious missing geometry, texture or text. A frame capture
ends the run intentionally; the 13 recorded benchmark frames in each capture
run are not a performance or soak-test result.

## App Manager lifecycle

The installed Vitrallis Shell binary ran in an isolated QA `HOME` under the same
temporary directory. Its App Center loaded a one-app snapshot of the published
0.3.1 catalog entry, then downloaded all 140 pinned files from `csd113/Places`
and installed 0.3.1. The receipt recorded version 0.3.1 and the original source.
The QA profile explicitly trusted the existing `csd113/Places` package source.

The QA App Center then loaded the 0.11.1 catalog entry, showing **Update 0.11.1**.
The real Update action downloaded its 14,250,570-byte package from the new
`csd113/Places` commit and wrote a receipt with version 0.11.1 and the exact
catalog commit. An untracked `qa-sentinel.txt` survived the update. App Center
source inspection showed that pointing 0.11.1 at `csd113/Vitrallis-Apps` would
have violated its installed-source protection; the source mirror keeps the
application's original catalog origin and package source.

After the update, one managed file (`icon.png`) was removed only from the QA
installation. Returning to App Center showed **Repair**; the real Repair action
re-downloaded the pinned package and restored the file. All 198 installed
published files then matched their catalog sizes and SHA-256 hashes, the 0.11.1
receipt retained the expected source commit, and the untracked sentinel still
existed. The generated App Center launcher opened the installed executable and
captured a rendered Places Demo scene before exiting successfully.

## Scope

The runtime launch checked the published binary and assets on the target device.
The captures establish a visual smoke test, not physical keyboard or touch
coverage. Source-level keyboard tests and the documented keyboard map cover the
keyboard baseline separately. The owner's normal App Center installation was not
modified by these checks. The QA Shell was stopped, its temporary profile and
staged files were removed, and the owner's original Shell remained running and
visible.
