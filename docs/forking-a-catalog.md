# Hosting or forking a catalog

[Documentation](README.md) · [Publishing](publishing-apps.md) · [Runtime integration](runtime-integration.md)

The package and catalog formats have no publisher allowlist. The official
`csd113/Vitrallis-Apps` catalog is one instance. A catalog publisher hosts metadata
and chooses its source pins; each consuming client decides which publishers and
source repositories to trust.

## Prepare your GitHub repository

1. Fork or clone with history if you plan to retain upstream entries. Host
   `apps.json` at the repository root on its default branch. The current Shell
   resolves that branch through GitHub; it does not accept an arbitrary JSON URL
   in the Sources editor.
2. Decide which entries and packages to keep. For a retained upstream app, keep
   its ID, source repository, commit, path, permissions, and file inventory intact.
   Its identity continues to refer to the same app. Confirm redistribution rights;
   retaining bytes does not grant a license.
3. To start empty, use this catalog:

   ```json
   {"schema_version": 1, "apps": []}
   ```

   In your fork, also remove the unwanted package directories under `apps/`.
   Replacing only the JSON fails the submission policy: every local production
   package must be represented in the catalog. Retain existing dated root release
   records when preserving history; explain the fork's current scope above them.
   The policy permits removal of entries but preserves earlier release records.
4. Keep the example and tools. Copy the [example](../examples/hello-vitrallis/README.md)
   into `apps/<your-slug>/` for your own app. Change its manifest identity, content,
   and initial changelog; a renamed folder alone is not a new app.
5. Follow [publishing](publishing-apps.md), passing your own explicit
   `--repository owner/repository` and full source commit. New entries default
   to installation disabled. Verify the target client before enabling them.
6. Update your README branding, catalog endpoint, app list, and compatibility
   statements. Review CI as well: package discovery is generic, but the current
   [validation workflow](../.github/workflows/validate.yml) installs Media Carousel's
   requirements explicitly. Remove or adjust that step if your fork omits the app,
   and provide any dependencies your own tests need. Enable Actions and choose
   branch protection and review rules for your project.

No source-code replacement of `csd113` is needed in the tools or schema. The
validator uses local Git objects and supports inherited pins in a full,
history-preserving fork. Without upstream history, remove the corresponding
entries or provide a separate trusted checkout explicitly:

```sh
python3 tools/validate_catalog.py \
  --source-repo csd113/Vitrallis-Apps=/path/to/upstream
python3 tools/validate_changelogs.py \
  --source-repo csd113/Vitrallis-Apps=/path/to/upstream
```

Repeat mappings for additional source repositories. Configure trusted checkouts
and mappings in CI for an aggregating catalog; validators never automatically
fetch URLs supplied by a pull request. Local object presence does not prove that
GitHub serves a commit from its advertised repository. Perform the separate
[remote availability check](publishing-apps.md#new-native-app-or-version).

## Add the catalog in Vitrallis Shell

On a Shell build with the current
[App Center Sources interface](https://github.com/csd113/Vitrallis-Shell/blob/main/docs/app-center.md#catalog-sources):

1. Open **App Center → Sources → Add**.
2. Enter `your-owner/your-catalog` or its HTTPS GitHub repository URL, then save.
3. Choose **Check** to load its root `apps.json` from the resolved default branch.
4. Select an app and review **Details**. If its files come from a different
   repository, review **Trust source** and approve only a source you intend to
   trust. Choose **Check** again after approval.
5. Install once the package and runtime checks allow it.

A configured catalog can supply files from its own repository. Separate source
approvals are scoped to that catalog. Custom catalogs supplement the built-in
source, which cannot be edited or removed. Duplicate app IDs from different
catalogs require an explicit publisher selection; existing installations cannot
silently switch publishers. Removing a catalog removes its source approvals but
does not uninstall apps or erase saves.

## Other clients and hosting limits

Catalog v1 is publisher-neutral, but its source contract is GitHub `owner/repository`
plus a full commit and `apps/<app-slug>` path. It does not define arbitrary archive,
GitLab, or self-hosted source URLs. Other clients may accept an HTTPS JSON endpoint
such as `https://raw.githubusercontent.com/your-owner/your-catalog/main/apps.json`;
that is a client capability, not an App Center Sources input format.

For another client, verify endpoint selection, explicit source trust,
HTTPS/redirect policy and bounded downloads, manifest/runtime support, launcher
registration, and trusted installed-app identity. Metadata must never choose
arbitrary installer code. Use [runtime integration](runtime-integration.md) as
the verification checklist rather than inferring support from schema acceptance.

No authoritative repository-wide license is present. Choosing licensing and
confirming imported content rights remain owner decisions before distribution.
