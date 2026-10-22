# Atelier 1.1.2 release preparation

Prepared on 22 October 2026 from `05c304b`, the reviewed connected-ink and
installer update in PR #28. That commit includes current main through `b0e3f55`,
retaining the merged material batch, VFX Motionboard, UV X-Ray and Assembly work.
The release uses a separate checkout; existing development work and user projects
are not staged into the candidate.

## Release inputs

- `version`, the numbered changelog section, release notes and announcement draft
  all identify **1.1.2**.
- Upgrade inputs point to the published **1.1.1** Windows installer and AppImage.
  Their SHA-256 digests, Windows size and asset URLs were read from GitHub's
  published release metadata. The native Windows tool seed and source recipes
  retain their existing pins.
- Fresh screenshots come from the real configured interface in an isolated
  Release Verification project. The capture only opens, inspects and previews;
  it does not save material/VFX edits or build/install mods. `images/screenshots.json`
  binds each capture to the version and source hashes.
- The release workflow installs Chromium before backend checks on both platforms
  because the UV regression includes a real browser. The minimal DOM fixture now
  supports the custom events emitted when project assets change. The default
  browser suite includes the existing Assembly checks and verifies Showcase's
  current SVG border flow. The Krackle handoff preview uses the mapped Edit icon.

## Evidence and publication

The [connected-ink review](review/connected-ink/README.md) records the preceding
132 focused browser checks, 18 frontend-cache/packaging tests and native installer
appearance inspection. The [Assembly](assembly-verification-2026-10-22.md) and
[UV X-Ray](uv-xray-verification-2026-10-22.md) records describe their native source
checks. Those records are not substitutes for testing the new packaged release.

The 1.1.2 source passed all 60 backend check files on Windows, including 647
reported unit tests and the UV browser regression. All 300 existing full-suite
browser checks passed with no page errors, followed by the seven Assembly
interaction checks; those are now included in the default suite. The complete screenshot set
contains 14 current interface captures, including Assembly, UV X-Ray,
Motionboard and the Krackle examples.

The candidate pipeline requires full backend checks, the Windows browser suite,
the frozen WebView2 application, clean install/running upgrade/reinstall/uninstall
on Windows 2022 and 2025, and Linux AppImage startup and upgrade from 1.1.1.
Bundle assembly rejects failed gates, mixed source commits, changed payloads,
stale screenshots or an incorrect previous release. Its `VERIFICATION.json`
records the final results and exact installer, portable and AppImage hashes.

Building and reviewing the candidate does not publish a release or send the
announcement. In-game appearance and Linux Wine workflows remain outside the
automated gates. Motionboard proxies do not reproduce Unreal simulation; UV
X-Ray retains its decoded-UV0 scope and mapping limitations.
