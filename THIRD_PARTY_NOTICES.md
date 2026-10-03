# Licensing and third-party notices

Audit date: **2026-09-20**. Project-owned code, documentation and original artwork
are offered under the root [MIT License](LICENSE), at the owner's direction.
This grants no rights to separately licensed third-party material.
Copyright remains with the respective contributors; no assignment is implied.

[Dependency inventory](docs/dependency-licenses.md) records exact cached crate
versions, declared license expressions and gaps. [Verbatim license and notice
texts](THIRD_PARTY_LICENSES.txt) preserve upstream attributions, including nested
notices. Keep this file, those texts and LICENSE with source distributions and
applicable binary distribution documentation. An MIT/Apache alternative permits
choosing MIT; an AND expression requires both terms. Apache-only components retain
their license and applicable NOTICE/attribution requirements. These files do not
relicense dependencies or certify that existing artifacts contain their notices.

## Owner-provided provenance update — 2026-10-02

The repository owner confirmed: “All of the apps were made by codex, all of the
assets too.” This records the owner's provenance confirmation for project app
code and bundled artwork, including Firefly's hand-coded `FONT` bitmap table and
the Bitcoin dashboard screenshot. The September 20 authorship questions for those
project materials are resolved by that confirmation. Project-owned material
remains covered by the existing owner-directed MIT grant. Dependency license and
notice records below remain applicable to separately licensed components.

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
- `apps/bitcoin-dashboard/assets/dashboard.png` is a historical screenshot from
  PocketChip-Bitcoin-Display, as identified by its asset README. The owner's
  October 2 Codex-authorship confirmation supplies the previously missing
  provenance statement for this project asset and project app code. Preserve
  that source history if the screenshot remains in a package.
- Firefly's hand-coded `FONT` bitmap table is covered by the owner's October 2
  confirmation that Codex created the apps and their assets. No external font
  source is asserted; the previous request to confirm authorship is resolved.

## Publication boundary

The local catalog matched the default-branch GitHub catalog on 2026-09-20. Catalog
pins, file inventories, app versions and binaries were not changed. Existing pins
still contain their historical README/license wording. Current MIT applies to
project-owned source under this grant; it does not turn old packages into
notice-complete releases. The next authorized app publication must include the
applicable full license/notices inside each package (root files are not included
by app-local inventories), update shipped documentation and regenerate pins with
the required version/changelog changes. The October 2 owner confirmation updates
project-material provenance; it does not replace third-party dependency notices.
