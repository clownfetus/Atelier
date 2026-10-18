# Atelier 1.1 — More room to create

Atelier **1.1.0** brings the work since 1.0 together: custom asset paths, expanded
Model Studio editing and Blender export, and a clearer hero and costume library.

## Create assets where you need them

**Add asset** in the Mod tray creates named textures, material instances and
meshes at a chosen `/Game/Marvel/` path. Copy a compatible game asset, upload
cooked files with their companions, or upload an image using a game texture as
its format template. Added assets work with the normal editors, Build mod and
Delete/Undo. Existing paths are protected from accidental replacement.

Custom material textures also have a **Package location**. Choose the folder
and texture name, with path and collision checks on save and export. Replacing
the image keeps that location. Native checks cover diffuse and normal maps
through container build and readback.

## Take Model Studio further

- **Export to Blender** saves the selected body and visible held weapons in one
  portable `.blend`, with connected materials, packed images and deformation
  bones. The export checks the resting surface before saving.
- **Replace model** offers body and weapon destinations, model ZIPs and companion
  files, texture-bundle options, and preservation of untouched sections. It checks
  all detail levels while retaining the game's existing rig.
- Section eye controls save hidden parts into the exported mesh and restore them
  independently, including sections that share a material.
- Better texture recovery, custom texture assignments, grouped material controls
  and held-weapon hand selection improve inspection.
- Export progress follows preparation and build stages and supports cancellation.
  Inspect/Showcase presentation remains separate from saved edits.

Blender must be installed and configured. Exported scenes do not recreate game
physics or animation controls. Replacement models reuse game rigs and physics;
different shapes can require weight adjustments.

## A clearer library

Hero and costume nameplates, larger costume portraits, verified identity icons
and sharper banners make folders easier to recognize. Banners use their sharper
cached copy when ready. Artwork colors stay on decorative surfaces while
controls and text follow the selected theme.

Home keeps heroes, costume controls and categories in separate rows, including
short windows and larger card sizes. Card size and the **Heroes** startup choice
are remembered. Double-click a Home portrait to open its character folder.
Breadcrumbs have their own scrollable row, and folder hints track the hovered card.

The 36 category emblems use distinct colors with measured contrast in both
themes. Edited assets use their own colors in the Krackle effect. **No mip maps**
starts on and remembers your choice per asset.

## Know what changed

The offline **What's new** popup appears once after an update and includes
skipped releases. Reopen it from the app menu. The installer also refreshes
Explorer's icon cache so upgrades show the current Atelier mark.

## Download and update

- **Windows:** download `AtelierSetup.exe`, close Atelier, and install to the
  existing location. Projects and settings are retained.
- **Linux:** download `Atelier-1.1.0-x86_64.AppImage`, mark it executable and launch
  it. Bundled tools refresh while user data is retained.
- Matching source, `SHA256SUMS.txt` and `VERIFICATION.json` accompany the release.

## Verification and limits

The release gate runs backend and browser checks, the packaged Windows WebView2
app, clean installation, running upgrade from **1.0.0**, reinstall and uninstall
on Windows 2022 and 2025, plus native Linux GTK/WebKit startup and an actual
**1.0.0 AppImage** upgrade. `VERIFICATION.json` records the exact build commit,
artifact hashes and gate outcomes. The final bundle is produced only after all
gates pass.

Native mod build/readback and Blender checks use isolated test projects and do
not install mods into the game. They do not establish in-game appearance for
arbitrary assets. Custom texture slots remain experimental; animated shaders
are not fully represented in the preview. Linux model and animation workflows
require Wine and are not covered by the native Linux startup checks. Project
Galacta controls Skin Swapper availability with its external switch.

[Full changelog](https://github.com/clownfetus/Atelier/blob/1.1.0/CHANGELOG.md)
