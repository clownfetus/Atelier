# 1.1.0 consolidation and verification

The release includes the work since published `1.0.0`, consolidated on `main`:
custom asset creation, offline update notes, Home/library identity and layout,
custom texture locations, and Model Studio editing, replacement and Blender export.

## Source coverage

- Main's Model Studio integration (`c3d3986`, `909b217`, `7c643de`) includes the
  separate Model Studio and appearance worktrees and later integration repairs.
- The Home layout change (`528d2ae`) is retained.
- Portrait double-click (`b7fddbb`) is already included in the integrated roster;
  applying it again produces an empty change.
- Dirty registered worktrees were compared with main. Their product changes are
  represented by the integration or superseded by its fixes. Historical checkouts
  and user worktrees were preserved.

## Repairs found during this release review

- Copying a patched skeletal mesh now completes its streamed LOD data before
  renaming. Incomplete uploaded meshes are rejected; renamed LOD/section meaning
  is checked before atomic project publication. Native readback retained all four
  detail levels, with the mesh payload and bulk data unchanged.
- Blender export requires exactly one visible body. It no longer exports a
  hidden body when none is selected.
- The completed Blender export action remains clickable in both themes and
  smaller windows. Unchanged mesh exports are labelled accurately.
- Small skeletal accessories with short name tables now parse after class and
  asset identity checks, resolving a real Venom accessory's section-mapping failure.
- Previously separate Home, identity, artwork, loading and viewer checks now
  run in the full browser release gate. The new Blender export check exercises
  project-scoped HTTP jobs, progress, failure, retry and Activity history.

## Release evidence

Local checks cover backend regressions, both-theme responsive screenshots,
custom texture and named-asset native build/readback, and real Model Studio and
Blender workflows. Synthetic browser geometry is labelled as such. Native checks
use isolated project/export directories and do not install mods into the game.

The release workflow reruns the final committed backend/browser checks and verifies
the packaged WebView2 application, including its exact bundled changelog. Installer
checks on Windows 2022 and 2025 cover clean install, running upgrade from **1.0.0**,
changelog acknowledgement, reinstall and uninstall with preserved user data.
Ubuntu checks cover the actual **1.0.0 AppImage** upgrade, GTK/WebKit setup, native
tools and preserved data. Inputs are pinned by SHA-256.

The published `VERIFICATION.json` records the final commit, platform results and
artifact hashes. The release bundle cannot be assembled until every platform gate
passes. In-game appearance and Linux Wine model workflows remain separate checks;
Blender exports do not recreate game physics or animation controls.
