# Changelogs and merge requirements

[Documentation](README.md) · [Contributing](../CONTRIBUTING.md) · [Publishing](publishing-apps.md)

Every submitted app must ship `apps/<slug>/CHANGELOG.md`. The main catalog's
companion [CHANGELOG.md](../CHANGELOG.md) records when apps are added and when
their published versions change. `apps.json` remains catalog schema v1; its
pinned inventory includes each app changelog, with its size and SHA-256.

## App release notes

Use UTF-8 Markdown and put releases newest first. The newest heading must match
the exact `app.toml` version, include a real calendar date in `YYYY-MM-DD` form,
and contain concrete change bullets. Versions and dates must descend; repeated
version headings, empty entries and placeholder notes are rejected.

```markdown
# Changelog

## 0.2.0 — 2026-09-12

- Add keyboard navigation between image collections.
- Fix interrupted uploads leaving temporary files behind.

## 0.1.0 — 2026-09-10

- Add the native image viewer and its initial app package.
```

Use the shown em dash in release headings. Each bullet must start with `- ` and
describe a specific change (at least 12 characters on the first line); continued
lines and optional `### Added`, `### Changed` or `### Fixed` headings are allowed.
Do not submit TODO/TBD/FIXME/WIP placeholders. Reviewers must also confirm that
the notes accurately describe the change: automated checks establish structure
and consistency, not the truth or completeness of a prose summary.

Preserve existing dated release entries when publishing another version. Record
features, fixes, dependency/permission changes, behavior changes and documentation
or packaging changes as applicable. Dates use America/Vancouver time in this
catalog. A catalog publication date may follow the app's release date.

## Catalog release notes

Add a record under the newest `## YYYY-MM-DD` section in the root changelog:

```markdown
## 2026-09-12

- Added `org.example.viewer` `0.1.0`: Add a native image viewer with keyboard controls.
- Updated `io.vitrallis.debug` `0.1.2`: Add a packaged version history and README link.
```

Use `Added` only when the app ID is first submitted to the catalog; use `Updated`
for a higher version of an existing app. Include its exact ID, version and a
concrete summary; a relative link to the app changelog is encouraged. Do not edit
or delete previous release records or announce an unpublished future version.
Metadata-only notes such as changes in installation readiness can be ordinary
paragraphs within the date section, without inventing a new app release.

## Changes outside shipped packages

Root documentation, files under root `docs/`, and community files under `.github/`
are outside app packages. Changes confined to them do not require an app version
bump or a new catalog release record. Keep existing history intact. App-local
READMEs and docs do ship, so their edits require a new version and publication.

## Submission sequence

1. Work on a feature branch. Add the app changelog entry, increase `app.toml`
   whenever shipped bytes change, and update any version displayed by the app.
   Documentation, artwork, requirements and the changelog itself are shipped
   bytes. Files inside app-local `tests/` are excluded and do not require a
   release when they are the only app files changed.
2. Validate and test the package, then commit and push its source to the feature
   branch. Never republish different bytes at an existing version.
3. Generate `apps.json` using that full source commit through
   `tools/update_catalog.py`. Add the root catalog record, commit the catalog
   and documentation, and push the feature branch again. Source-only intermediate
   commits can fail the complete submission check until this step is done.
4. Open a pull request into `main`. Every submitted package in `apps/` must match
   the current catalog inventory. Preserve the source commits with a merge commit
   so fresh clones can verify the pinned objects; do not squash away source pins.
5. Run the required checks and resolve failures before merging. `main` requires
   the **Changelog policy**, **validate (3.11)** and **validate (3.13)** checks,
   an up-to-date branch and a pull request. No additional approving review count
   is imposed by this policy.

For a local committed feature branch, fetch `main` and use its full SHA:

```sh
git fetch origin main
python3 tools/validate_catalog.py
python3 tools/validate_changelogs.py --base "$(git rev-parse origin/main)"
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tools/tests -v
```

`validate_changelogs.py` reads committed Git objects, not dirty working files.
`--head` can select another full commit; without `--base`, it validates the
current publication and histories. Both files and input commit IDs are validated
before use. GitHub runs it for every push and pull request, without path filters.
Pull requests compare against their base commit; pushes compare against their
previous head when present. Missing or failed validation blocks merging.

The policy verifies package and catalog version increases, dated matching notes,
preserved histories, committed inventory agreement and complete catalog entries.
The initial adoption backfills history from existing Git records and introduces
patch releases for existing apps; later submissions must preserve that history.
