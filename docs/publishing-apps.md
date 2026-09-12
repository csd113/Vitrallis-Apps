# Publishing apps

Publication has two commits: **source first, catalog second**. Hashes describe
committed source bytes and never a dirty working directory. The updater does not
commit, push, install apps or contact GitHub; each of those is a maintainer action.
Use Python 3.11+ and Git on Linux, macOS or WSL. No additional Python
dependencies are needed.

## New native app or version

1. Follow [creating apps](creating-apps.md). For an update, increment the manifest
   version whenever package bytes change, including docs/artwork. Validate
   and test the exact files you intend to publish. Keep caches, credentials and
   build artifacts outside the app directory: every committed file outside the app-local `tests/` folder is published.
   Keep all app test files in `tests/`; this folder is excluded from device packages.
2. Review and commit source, then push it. For example, replacing repository,
   branch and app names with your own:

   ```sh
   git add apps/my-app
   git diff --cached --check
   git diff --cached --stat
   git commit -m "Add My App 0.1.0"
   git push origin HEAD
   git rev-parse HEAD
   ```

   Copy the full 40-character commit printed by the last command. Use the source
   commit even if the working tree later changes. These commands are instructions
   for an authorized maintainer, not actions performed automatically by the tools.
3. Preview the generated catalog. Set `SOURCE_COMMIT` to that full SHA and
   `PUBLISHER_REPOSITORY` to the actual GitHub `owner/repository`:

   ```sh
   export SOURCE_COMMIT=YOUR_FULL_40_CHARACTER_COMMIT
   export PUBLISHER_REPOSITORY=your-owner/your-catalog
   python3 tools/update_catalog.py \
     --repository "$PUBLISHER_REPOSITORY" --commit "$SOURCE_COMMIT" \
     --path apps/my-app \
     --description "A short description of My App." \
     --compatibility-notes "Requires Python 3.8+ and Tkinter; launcher integration pending."
   ```

   New apps default to `installable: false`. ID, name, version, runtime, entry and
   permissions come from the committed manifest. The tool generates all file
   paths, byte sizes and SHA-256 hashes, sorts the catalog, and validates **every**
   resulting entry. It prints JSON and leaves `apps.json` unchanged by default.
4. Repeat the command with `--write` to atomically replace `apps.json`. Existing
   entries retain their description, compatibility notes and installable flag
   unless explicitly overridden. `--installable` and `--no-installable` are
   explicit overrides; enable installation only after a reviewed adapter and
   runtime/installation/update/repair path are verified. A manifest alone is not
   sufficient. Equal-version changed bytes and version downgrades are refused.
5. Validate and review:

   ```sh
   python3 tools/validate_catalog.py
   git diff --check
   git diff -- apps.json
   ```

   Before publishing, verify GitHub serves the advertised commit from the named
   repository. One independent check is a fresh clone into a temporary directory:

   ```sh
   CHECKOUT=$(mktemp -d)
   git clone "https://github.com/$PUBLISHER_REPOSITORY.git" "$CHECKOUT/source"
   python3 tools/validate_catalog.py \
     --source-repo "$PUBLISHER_REPOSITORY=$CHECKOUT/source"
   ```

   This verifies all entries for that repository against objects fetched from
   GitHub. For additional source repositories, supply additional mappings. Also
   check the raw-file endpoint through the consuming client's Check/download flow
   under its HTTPS/redirect policy; a local Git check is not a network availability
   or client compatibility test. Never publish a commit available only locally.
6. Commit/push `apps.json` after source availability and review. Configure the
   consuming client's endpoint, trusted repositories and adapters as described in
   [forking a catalog](forking-a-catalog.md). A source commit alone does not advertise
   an update; the catalog publication does.

## Tool options and reproducibility

`--catalog FILE` selects an existing catalog; initialize a new empty one with
`{"schema_version": 1, "apps": []}`. `--repo PATH` changes the default local Git
object store. Repeat `--source-repo OWNER/REPO=PATH` for sources in other clones.
`--repository` is always explicit when updating; there is no hard-coded publisher
or inference from the machine's Git identity. All paths are resolved relative to
where you invoke them, except default catalog/object-store paths, which resolve
relative to the tool's repository.

A full source commit is mandatory. Branch names, shortened hashes and tag objects
are rejected. The updater reads Git blobs with replace objects disabled, so dirty
or staged app edits cannot change generated hashes. It never checks out or runs
the app. It validates all input and output before an atomic catalog replacement;
a failed generation leaves the catalog untouched. Concurrent malicious mutation
of the local checkout is outside the offline maintainer tool's threat model.

## Existing legacy app

The official Bitcoin entry uses its existing `VERSION` literal and reviewed
metadata instead of a native manifest. Regenerating its current file list is:

```sh
python3 tools/update_catalog.py \
  --repository csd113/Vitrallis-Apps \
  --commit ab2869b2cf25818cfcf09f5d1fc7055dfbb9a218 \
  --path Apps/Bitcoin-Dashboard --app-id io.vitrallis.bitcoindashboard
```

This produces the current catalog without changing the snapshot or its published
semantics. The legacy adapter reads the new literal version without executing the app and
preserves its reviewed ID, permissions and other metadata. For a future legacy
release, pass its new source commit to regenerate the version/file list and
validate before publishing. Adding arbitrary new legacy apps is intentionally not automated;
new apps use the native package contract. See [compatibility](legacy-compatibility.md).
