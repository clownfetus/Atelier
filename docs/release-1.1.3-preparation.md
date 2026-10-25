# Atelier 1.1.3 preparation

Prepared on 25 October 2026 in a separate checkout of the preceding verified
1.1.2 candidate. Existing development files and user projects were left in place.

## Integrated sources

- Atelier upstream/main through `25196ea0339c30ba0d2a286b97ca3dedfb8a4a2e`:
  unified native toolchain, pinned source builds, updated texture exports,
  Settings → Tools, reorganized packaging, Python 3.15 and CI/AppImage fixes.
- The connected ink, draft preservation, hero artwork and installer work from
  the 1.1.2 candidate at `893d5bbf6c558a016a209d552b5ae28a0f2d226b`.
- The reviewed Windows picker fix from PR #32 at
  `a09080de44478f79645f4e610fe77e2061b20f79`, applied as `e706515`.
- `scripts/toolchain.py outdated` reported every updatable tool current. The
  approved container tool remains retoc 3.10.2; no unverified version was adopted.

The latest upstream candidate failed while waiting for overwrite confirmation
in the export retry scenario. The test could install its synthetic selection
after grid loading but before the initial tray response. It now waits for tray
initialization and records selection fingerprints, active dialogs and requests
if a later failure occurs. Destination and retry assertions remain in place.

## Release inputs and evidence

The version, README, changelog, release notes, announcement draft and installer
fixture identify 1.1.3. Upgrade inputs retain the published 1.1.1 Windows installer
and AppImage. GitHub release metadata was checked again for their hashes and size;
1.1.2 remains an unpublished candidate at preparation time.

All 60 backend check files pass locally with Python 3.15, including the tool
updater and UV browser regression. The focused export-retry checks also pass.
All 307 checks in the complete browser suite pass with no page errors. Platform
candidate gates provide the packaged release evidence; final results belong
in the bundle's `VERIFICATION.json`.

Interface captures use a dedicated Release Verification project and copied
review caches, with no user projects or mod installation. The model helper and
its C++ library are rebuilt from pinned CUE4Parse source for local capture.
Release CI independently rebuilds and verifies the complete production toolchain.
Screenshot receipts bind the captures to the current application source/version.

The pipeline requires Windows and Linux backend checks, the complete browser
suite, the packaged Windows app, install/upgrade/reinstall/uninstall on Windows
2022 and 2025, native Linux startup and upgrade, and a matching verified bundle.
The release and announcement stay unpublished during preparation.

In-game appearance and Linux Wine workflows are outside the automated gates.
Motionboard proxies and decoded-UV0 inspection retain their documented limits.
