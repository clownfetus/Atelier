# 1.1.1 consolidation and verification

Prepared on 22 October 2026 from `main` merge `4256fa0`, which merged PR #26.
Its tree (`3d81d8a1f54ffc4e9a36e48ff940e18ed3e7e0c8`) is identical to the
reviewed integration head `4359a16`; the merge dropped no files or changes.
The additional fork branch `fix/live-blender-and-catalogue-upstream` at `66737b4`
also contributes live Blender transfer, geometry preservation and reference-name
updates that were absent from main. Those changes are included in this patch.

## Remaining branches and saved work

- The 19-commit live Blender fork branch is merged with the newer HDR, identity,
  material and loading fixes retained. Its Blender extension is bundled with
  setup instructions; portable export remains available.
- The staged 18-file UI worktree at `3d28c77` exactly matches integrated commit
  `734493a` for those files. Thirteen files also match final main byte for byte.
  The other five contain the later shared identities, HDR and Blender preference
  changes from `4359a16`. Those later fixes are retained.
- The asset-pipeline archive `a3c7d00`, all 24 remaining Showcase branch patches,
  and the Krackle mark are patch-equivalent to merged work.
- Material replacement, Home/nameplates, reliability, the Material foundation,
  launch/update fixes and old Linux packaging were integrated or superseded in
  earlier releases. They remain covered by the current regression and release
  checks; their old branches are historical references.
- Both recovery stashes are retained. The first holds only the already tracked
  motion brief. The second holds the original material-replacement and logo work,
  including its source scripts and tests, all present in the integrated source.
- The retired Claude source directory has no Git worktree metadata. All 486
  present tracked files match historical commit `bf3ad13` exactly; three historical
  configuration/workflow files are absent. It contains no changed tracked source.
- Original branches, retired source copies and dirty worktrees are preserved.
  No historical checkout was reset or deleted to make the release appear clean.
  Local agent configuration is excluded from this checkout, not included in the
  source archive.

The preceding [repository integration audit](repository-integrations-2026-10-20.md)
records the earlier worktree archives and source-by-source decisions.

## Existing native evidence retained

- [New Blender 5.1.2 verification](release-1.1.1-blender-verification.json): a
  generated scene retains 26 bevel faces and outward winding after a mirrored
  transform; singular scale is rejected. The packaged extension imports into an
  existing scene, acknowledges the request, and preserves both meshes after save
  and reopen. The receipt records extension and source hashes. This uses generated
  geometry and does not establish in-game rendering.
- [Shared identities, HDR and optional Blender texture copies](identity-hdr-blender-verification-2026-10-22.md):
  14,916 recognized folder contexts agree between Python and the browser; four
  HDR cubemaps and one material pass native and independent readback; a reopened
  Blender scene retains 31 packed images and byte-identical existing paint.
- [Character previews](character-preview-verification-2026-10-21.md): installed
  default costumes and discovered forms, including materials and held equipment.
- [Texture import/export repair](texture-import-verification-2026-10-21.md):
  the reported T_Visor mismatch and cooked payload preservation.
- [Shader tool rebuild](shader-rebuild-verification-2026-10-21.md),
  [pinned native inputs](native-tool-inputs-verification-2026-10-21.md), and
  [persistent imports](persistent-import-verification-2026-10-21.md).

These dated runs establish their stated Windows source workflows. The new
installer and Linux results belong to this patch's release-candidate workflow,
not to those older receipts.

Only the Windows shader CLI is rebuilt from the maintained source recipe.
Linux inherits its separately hash-pinned 1.1.0 native shader binary. The existing
Linux appimagetool download uses its upstream continuous build; the final
AppImage is identified by its own SHA-256 in the release verification.

## Patch release gate

Local preparation passed all **56 backend suites**: **601 unit tests** and
**138 script checks**, with two optional native checks skipped in disposable
fixtures. The final release-integrity suite includes 16 checks for complete bundles,
mixed builds, stale screenshots, failed platform results and changed source copy.
Ten fresh real-interface screenshots at 1400 × 900 have no page errors; their
receipt binds each image to the version and exact interface source hashes.

Hosted Linux validation exposed an outdated native-tool mock in the missing-cache
texture recovery test. It now stops at the image decoder boundary and asserts
that the recovered work copy reaches that decoder. The fixture needs neither
Wine nor an installed native tool; packaged native-tool checks remain separate.

Version, bundled changelog, release copy and fresh screenshots use **1.1.1**.
The previous installers are pinned to the published **1.1.0** assets using their
actual GitHub SHA-256 digests and Windows byte count. Native build inputs retain
their separately pinned seed and source recipes.

The complete backend and browser suites run before packaging. Windows gates
verify the frozen WebView2 app and clean install, running upgrade, reinstall and
uninstall on Windows 2022 and 2025. Linux checks GTK/WebKit startup, bundled tool
refresh and an actual previous-AppImage upgrade.

The bundle assembler requires every gate, exact source commit/version, matching
installer and AppImage hashes, a matching portable inventory, and screenshot
hashes and version. It produces installers, portable and matching source ZIPs,
screenshots, release notes, Discord paste, checksums and `VERIFICATION.json`.
Building a candidate does not publish a release or send a Discord message.

In-game rendering and Linux Wine workflows remain outside these automated gates.
