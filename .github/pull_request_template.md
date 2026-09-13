## What changed and why

Describe the problem and resulting behavior. Link related issues and list affected
apps or documents. For documentation-only or test-only changes, state that scope.

## Validation

List commands and results, including failures or skips. State Python/OS and, for
GUI or device work, display size, Shell version, and what was actually verified.
Include redacted screenshots when they help review a UI change.

- [ ] Relevant checks from [the testing guide](https://github.com/csd113/Vitrallis-Apps/blob/main/docs/testing.md) ran; results and remaining limits are recorded above.
- [ ] Documentation, examples, and links match the change.
- [ ] No credentials, access codes, private device data, or build caches are included.

## App releases (mark not applicable when no package is shipped)

List app IDs and versions with links to their changelogs, or write “Not applicable.”

- [ ] Each new or updated package has a dated, concrete changelog entry matching `app.toml`.
- [ ] Shipped-file changes use a higher version; previous release history is preserved.
- [ ] Root `CHANGELOG.md` records each added or updated catalog version.
- [ ] `apps.json` was generated from pushed source commits and matches submitted package bytes.
- [ ] Runtime dependencies, declared requirements, installation readiness, and device limits are accurate.
- [ ] Catalog, package, and committed changelog-policy checks pass.

Keep source commits when merging so a fresh clone can verify catalog pins.
See [CONTRIBUTING.md](https://github.com/csd113/Vitrallis-Apps/blob/main/CONTRIBUTING.md)
and the [changelog policy](https://github.com/csd113/Vitrallis-Apps/blob/main/docs/changelog-policy.md).
