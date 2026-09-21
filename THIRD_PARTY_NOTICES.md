# Licensing and third-party notices

Audit date: **2026-09-20**. Project-owned code, documentation and original artwork
are offered under the root [MIT License](LICENSE), at the owner's direction.
This grants no rights to third-party material or the unresolved items below.
Copyright remains with the respective contributors; no assignment is implied.

[Dependency inventory](docs/dependency-licenses.md) records exact cached crate
versions, declared license expressions and gaps. [Verbatim license and notice
texts](THIRD_PARTY_LICENSES.txt) preserve upstream attributions, including nested
notices. Keep this file, those texts and LICENSE with source distributions and
applicable binary distribution documentation. An MIT/Apache alternative permits
choosing MIT; an AND expression requires both terms. Apache-only components retain
their license and applicable NOTICE/attribution requirements. These files do not
relicense dependencies or certify that existing artifacts contain their notices.

## Apps, fonts and imported content

- Python source/tooling and documented original icons use project MIT. Tk fonts
  (including DejaVu Sans) are selected from the system, not copied font files.
  Python/Tk/SDL2 and optional FFmpeg/ffprobe remain separately licensed system
  components. App Center downloads Pillow, qrcode and packaging as needed; these
  are not vendored Python distributions here. Their resolved versions, bundled
  libraries and notices must be audited if shipping an environment or OS image.
- Carousel-Rust's 72 locked registry dependencies are inventoried, including
  font8x8's MIT attribution, Unicode data terms, SDL zlib terms and image codecs.
  Keep the BSD/Unicode notices as well as MIT/Apache texts where applicable.
  Exact license texts remain missing for unicode-casefold 0.2.0 and r-efi 5.3.0
  in the cached crates; resolve those records for targets that use them.
  Source metadata is now MIT; existing pinned ELF bytes were not rebuilt or
  proven to correspond to a notice-complete distribution in this audit.
- Media Carousel's geometric icons and solid-red codec probes are documented as
  original, including the copies in Carousel-Rust. Firefly Field's meadow has a
  dated image-generation record; its sprites and generated icon are recorded as
  original. These records are evidence of the stated preparation, not a claim
  of exclusive copyright in generated imagery.
- `apps/bitcoin-dashboard/assets/dashboard.png` is imported from
  PocketChip-Bitcoin-Display. Its asset README identifies the source, but contains
  no upstream license or permission. GitHub's license endpoint returned 404 on
  the audit date. That does not prove no permission exists; redistribution rights
  are unresolved, and this screenshot is excluded from the MIT grant. Confirm
  the provenance and terms of any code carried over from that project as well;
  shared repository ownership alone is not evidence of rights to imported work.
- Firefly's hand-coded `FONT` bitmap table has no explicit source attribution.
  Confirm original authorship or record its source/license before representing
  the entire app as provenance-cleared. This audit does not infer copying.

## Publication boundary

The local catalog matched the default-branch GitHub catalog on 2026-09-20. Catalog
pins, file inventories, app versions and binaries were not changed. Existing pins
still contain their historical README/license wording. Current MIT applies to
project-owned source under this grant; it does not turn old packages into
notice-complete releases. The next authorized app publication must include the
applicable full license/notices inside each package (root files are not included
by app-local inventories), update shipped documentation and regenerate pins with
the required version/changelog changes. Do not redistribute the unresolved
screenshot under MIT or claim rights that the repository does not establish.
