# Vitrallis Apps documentation

[Repository overview](../README.md) · [Contributing](../CONTRIBUTING.md) · [Support](../SUPPORT.md)

## Find your next step

| I want to… | Read |
| --- | --- |
| Choose and use an app | [Available apps](../README.md#available-apps), then its own README |
| Install through App Center or check runtime requirements | [Runtime integration](runtime-integration.md) |
| Build my first app | [Creating apps](creating-apps.md) and [Hello Vitrallis](../examples/hello-vitrallis/README.md) |
| Design a responsive, well-behaved app | [Developer build guide](../VITRALLIS_APP_BUILD_GUIDE.md) |
| Validate a change and run all tests | [Testing](testing.md) |
| Publish a new app or version | [Publishing apps](publishing-apps.md) and [changelog policy](changelog-policy.md) |
| Host a separate catalog | [Forking a catalog](forking-a-catalog.md) |
| Implement or inspect the package/catalog contract | [Manifest v1](creating-apps.md#manifest-v1-normative), [catalog v1](catalog-format.md), and [JSON schema](../apps.schema.json) |
| See what was published | [Catalog changelog](../CHANGELOG.md) and each app's changelog |
| Review recorded device evidence | [Media Carousel display acceleration](verification/vitrallis-media-carousel-gpu.md) and [raw measurements](verification/vitrallis-media-carousel-gpu.json) |

## Terms and sources of truth

An **app** is the program a user launches. Its **source package** lives in
`apps/<app-slug>/`; the **installed package** excludes app-local `tests/`.
The **manifest** (`app.toml`) owns identity, version, runtime, entry, and declared
requirements. The **catalog** (`apps.json`) advertises releases, source pins,
file inventories, and installation readiness. **App Center**, part of Vitrallis
Shell, consumes that catalog and installs packages.

The manifest and catalog guides define the contracts; the build guide adds
implementation advice. App READMEs describe their packaged release. Read current
catalog compatibility notes and [runtime integration](runtime-integration.md)
for installation status that may have changed since a package was published.
Device reports describe the dated setup and operations tested, not blanket
certification for later releases or other hardware.
