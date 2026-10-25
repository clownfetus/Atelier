# Atelier 1.1.2

A more connected workspace, with fluid ink feedback, a refreshed installer and
new ways to inspect models, edit effects and work across materials.

## What changed

- **Ink that follows your work.** Loading, saving, exporting and finding the
  game configuration use connected flows with clear sources and destinations.
  Ink travels along the app's borders, follows the current hero or costume
  colours, and catches and rebounds when work finishes. Try the examples in
  **Settings → Try Krackle**, or choose Calm or Off.
- **A matching Windows installer.** Paper and Ink artwork, clearer text and a
  connected A-mark illustration give setup the same character as the app.
- **Assembly View.** Select a model surface to see its geometry, verified
  material and connected textures. Follow those connections into the existing
  editors, UV tools or Blender while retaining the camera position.
- **UV X-Ray.** Pick a surface in Inspect to see its UV0 wireframe over a
  texture, read the clicked UV coordinate and export a transparent wireframe PNG.
- **VFX Motionboard.** Edit synchronized Niagara LUT tracks with playback,
  scrubbing, original/edited comparison and individual point or track restores.
  Organize tracks locally and arrange 2D particle proxies alongside the existing
  gradient controls. Untouched LUTs keep their original samples during export.
- **Bulk material editing.** Review opacity, named scalar, colour, parent and
  complete material changes for up to 1,000 assets. Parent changes survive export,
  recursive parent chains are rejected, and missing scalar overrides are reported
  as unchanged.
- **Better artwork and safer feedback.** Corrected hero artwork, catalogue
  discovery and reused costume previews improve browsing. Newer curve, level and
  text drafts stay unsaved when an earlier save finishes; old loading responses
  cannot replace a reopened editor or trigger its success animation.

## Updating

- **Windows:** close Atelier and run `AtelierSetup.exe` in the existing location.
  Projects and settings are retained. The portable ZIP contains the same files.
- **Linux:** download `Atelier-1.1.2-x86_64.AppImage`, mark it executable and launch.
  Bundled tools refresh while user data is retained.

The candidate bundle includes the Windows installer, portable ZIP, Linux
AppImage, matching source, screenshots, release copy, `SHA256SUMS.txt` and
`VERIFICATION.json`. The verification file binds the assets and test results to
their exact source commit. Publication requires all platform gates to pass.

## Verification and limits

The candidate workflow checks backend and browser behavior, the frozen Windows
app, clean install, upgrade from **1.1.1**, reinstall and uninstall on Windows
2022/2025, plus native Linux startup and a **1.1.1 AppImage** upgrade.

Source checks cover the connected flows, draft preservation and native-border
geometry. Dated [Assembly](https://github.com/clownfetus/Atelier/blob/1.1.2/docs/assembly-verification-2026-10-22.md)
and [UV X-Ray](https://github.com/clownfetus/Atelier/blob/1.1.2/docs/uv-xray-verification-2026-10-22.md)
records describe the real assets tested and their limits.

Motionboard particle proxies are editing aids; they do not reproduce Unreal's
rendering or simulation. UV X-Ray covers decoded UV0, not shader-driven mappings
or tiled/UDIM layouts. Assembly identifies verified relationships and explains
unavailable ones. In-game appearance and Linux Wine workflows remain outside the
automated release gates.

[Full changelog](https://github.com/clownfetus/Atelier/blob/1.1.2/CHANGELOG.md)
