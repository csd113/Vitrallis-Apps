## App releases

List the app IDs and versions being added or updated, with links to their changelogs.
For a change without app releases, explain its scope.

## Submission checks

- [ ] Each added or updated app has a dated, concrete changelog entry matching `app.toml`.
- [ ] Shipped package changes use a higher version; previously published entries are preserved.
- [ ] The root `CHANGELOG.md` records each added or updated catalog version.
- [ ] `apps.json` was generated from pushed source commits and matches the submitted package bytes.
- [ ] Catalog validation, changelog policy and relevant tests pass.
- [ ] Validation results and any runtime/device limits are described below.

## Validation

List commands and results. Keep the source commits when merging so pinned app
packages remain verifiable from a fresh clone.
