# Forking a catalog

The package and catalog formats have no publisher allowlist. The official
`csd113/Vitrallis-Apps` catalog is one instance. Trust decisions belong to each
consumer; changing a JSON schema does not reconfigure an existing client.

## Choose your catalog contents

1. Fork/clone into your GitHub repository, preserving history if retaining
   upstream entries. For mixed legacy/native development use a case-sensitive
   checkout because `Apps/` and `apps/` are distinct Git paths.
2. Decide whether to keep Bitcoin. To start empty, replace only `apps.json` with:

   ```json
   {"schema_version": 1, "apps": []}
   ```

   If retained, leave Bitcoin's upstream repository, commit, path, ID, files and
   permissions unchanged. Its ID continues to identify the same legacy app.
   Retaining bytes does not automatically grant redistribution rights.
3. Copy the [example](../examples/hello-vitrallis/README.md) into `apps/<your-slug>`.
   Change the manifest identity and app content; do not merely rename the folder.
   No source-code replacement of `csd113` is needed in the tools or schema.
4. Follow [publishing apps](publishing-apps.md), passing your own
   `--repository owner/repository` and full source commit. Keep installation false
   until your target client's adapter supports the app.
5. Update your fork's README branding/default URL and compatibility claims. Keep
   the generic specifications intact. Enable Actions and protect the publication
   branch with validation/review rules appropriate to your project.

The workflow validates inherited commits from a full checkout, so unchanged
Bitcoin pins remain verifiable in a history-preserving fork. If you start without
upstream history, remove that entry or clone its source and supply an explicit
`--source-repo csd113/Vitrallis-Apps=/path/to/upstream` mapping. For a catalog
aggregating unrelated repositories, configure trusted source checkouts and their
mappings in your workflow; validation never automatically fetches arbitrary URLs
supplied by a pull request.

## Configure the consuming client

Provide all of the following through the client's documented configuration or a
reviewed client change:

| Setting | Example / responsibility |
| --- | --- |
| Catalog endpoint | `https://raw.githubusercontent.com/your-owner/your-catalog/main/apps.json`; substitute the actual publication branch. |
| Trusted source repositories | Explicit allowlist such as `your-owner/your-catalog`; add the upstream source only if you intentionally retain/trust its app. |
| Transport policy | HTTPS, allowed hosts/redirects, bounded timeouts and body sizes. |
| Installer mapping | Stable app ID to a reviewed installer/launcher/runtime adapter; metadata never selects arbitrary installation code. |
| Local identity/version | A trusted installed-app record or supported legacy version reader; never guess by display name. |

**Pocketchip-update-apps 1.6.x is not a general fork-configurable client.** The
inspected 1.6.0 implementation uses the official URL and repository checks and
only the reviewed Bitcoin catalog adapter. It needs a reviewed code/configuration
change to consume another publisher. Do not advertise fork compatibility merely
because this schema accepts the new repository name. See
[legacy compatibility](legacy-compatibility.md) for evidence and limits.

No authoritative repository-wide license is present. Confirm the owner's license
choice and imported content rights before distributing or granting reuse rights.
