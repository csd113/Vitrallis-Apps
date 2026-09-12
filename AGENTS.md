# App submission rules for coding agents

Read `CONTRIBUTING.md`, `docs/changelog-policy.md` and `docs/publishing-apps.md`
before changing or submitting an app.

- Every app and the copyable example must include a dated `CHANGELOG.md` whose
  newest entry matches its manifest version and explains the concrete changes.
- Increase the app version whenever shipped files change, including documentation,
  artwork and changelogs. Test-only changes do not change installed packages.
- Record every newly added or updated catalog version in the root `CHANGELOG.md`.
  Preserve existing app and catalog release histories.
- Publish source commits before generating catalog pins. Submit source and catalog
  together through a pull request and keep the source commits when merging.
- Run the package, catalog, changelog-policy and test checks. Do not bypass required
  checks or claim that missing/placeholder changelog entries are ready to merge.

These requirements apply to all app submissions. They do not authorize committing,
publishing, merging or changing device state beyond the user's requested scope.
