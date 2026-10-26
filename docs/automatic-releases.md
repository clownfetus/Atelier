# Releasing Atelier

Use **Actions → Release Atelier → Run workflow** on `main`, enter the next
numeric version (for example `1.1.4`), and leave **Publish** enabled. Alternatively,
push a tag such as `v1.1.4` on the intended commit. Both paths run the same release
workflow. A version must be higher than the latest stable GitHub release.

The action builds Windows and Linux, checks the actual packaged applications,
tests upgrading from the current published version, and creates the release.
It uploads every asset into a draft before publishing it as latest. Turning
**Publish** off keeps the complete release as a draft. Nothing publishes on an
ordinary branch push or pull request.

Select **Verify only** to run the complete build and gates without creating a
release or tag. The verified bundle stays in the workflow's artifacts.

Finished changes should be merged as they are ready. Releasing a selected commit
does not combine unfinished feature branches. The release action generates the
build's version and changelog entry automatically; the matching source ZIP contains
those two generated files and records the original commit in `VERIFICATION.json`.
Other source files must still match that commit.

## What users receive

After one installer update to a build with this updater, Windows installations
download only changed application files when updating from the immediately
previous release. The complete portable package is the fallback for skipped
versions, modified application files, or an unusable patch. A changed Python
runtime or packaged dependencies uses the full installer. New installations and
older updater versions always have `AtelierSetup.exe` available.

Linux AppImage installations download and replace the AppImage in-app. Linux
currently uses the full image, rather than a binary delta. The original AppImage
must remain in a writable location; extracted/source launches use the release page.

Downloads are checked against signed release metadata and SHA-256 digests before
installation. The UI offers **Restart and Update** after downloading, so users
can save open edits first. Normal shutdown finishes active jobs. The independent
updater waits for Atelier to exit, backs up replaced files and starts the new
version. If the interface fails its startup acknowledgement, the updater restores
the previous version. User projects, exports, settings, mappings, keys, browser
preferences and custom tool files are outside the managed file inventory.

Only one updater can apply files at a time. Interrupted transactions retain a
journal and standalone helper under `_updates` for startup recovery. Dependency
changes use the installer to avoid replacing the interpreter used by recovery.

## Checks and build reuse

Backend suites run in parallel, with separate disposable copies. Browser and
packaged-app checks run for every version. The signed update also passes through
the actual frozen helper on Windows and Linux: a running native window closes,
the package is applied, and the reopened frontend must acknowledge the new
version while project/settings canaries survive. This handoff check uses a
synthetic baseline; the installer/AppImage and delta checks separately cover the
actual previous release. When an installer, native tool,
dependency, storage/export implementation or build recipe changes, the action
also runs the complete installer lifecycle on Windows 2022 and 2025. Routine
interface changes reuse that installer machinery. Every emitted Windows delta
is applied to the actual previous portable release, launches the upgraded app,
and is rolled back while checking user-data preservation.

Native tool builds are cached by platform and hashes of `native/`, `toolchain/`
and their build recipes. Restored tools are verified against the lockfile. Private
Skin Swapper templates enter the build after caching and are excluded from test
report uploads. Marketing screenshots and Discord copy are no longer release
prerequisites. Existing release-candidate workflows remain available for historical
verification; use **Release Atelier** for normal updates.

## Signing setup

`update_keys.json` contains the public verification keys included in Atelier and
its standalone updater. The matching private key is stored as the repository
Actions secret `ATELIER_UPDATE_PRIVATE_KEY`. The existing
`GALACTA_TEMPLATE_UASSET_B64` and `GALACTA_TEMPLATE_UEXP_B64` secrets are also needed.

The initial signing secret is configured. A private backup is in the configuring
maintainer's local `AtelierRelease` application-data folder, outside Git. Preserve
that key for future releases. `scripts/setup_update_signing.py --configure-github`
reuses the local key and uploads it without printing its contents. Key rotation
requires shipping the new public key in a release still signed by the old key
before switching release signing.

The first complete hosted release still needs to pass Windows and Linux packaging
and upgrade gates. `Verify release updater` checks the protocol and frozen helper
on both operating systems without publishing or running an installer locally.
