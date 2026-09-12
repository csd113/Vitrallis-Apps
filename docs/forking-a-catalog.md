# Forking a catalog

The package and catalog formats have no publisher allowlist. The official
`csd113/Vitrallis-Apps` catalog is one instance. Trust decisions belong to each
consumer; changing a JSON schema does not reconfigure an existing client.

## Choose your catalog contents

1. Fork/clone into your GitHub repository, preserving history if retaining
   upstream entries.
2. Decide whether to keep Bitcoin. To start empty, replace only `apps.json` with:

   ```json
   {"schema_version": 1, "apps": []}
   ```

   If retained, leave Bitcoin's upstream repository, commit, path, ID, files and
   permissions unchanged. Its ID continues to identify the same native app.
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
| Local identity/version | A trusted installed-app record; never guess by display name or parse app code. |

Verify that the consuming client supports manifest v1 packages and your chosen
catalog endpoint and repository allowlist. The schema alone does not establish
installer or fork compatibility. See [runtime integration](runtime-integration.md)
for the required checks before enabling installation.

No authoritative repository-wide license is present. Confirm the owner's license
choice and imported content rights before distributing or granting reuse rights.
